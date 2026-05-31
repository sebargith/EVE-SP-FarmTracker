import os
from datetime import datetime, timezone

from src.data.database import connect, initialize_database
from src.data.repositories import (
    add_account,
    add_account_group,
    add_character,
    list_api_tokens,
    list_loot_session_items,
    store_api_token,
)
from src.integrations.sso import SsoConfig, TokenResponse
from src.integrations.token_store import decrypt_refresh_token, encrypt_refresh_token
from src.services.authorized_asset_service import fetch_assets_from_stored_authorization
from src.services.loot_tracker_service import (
    add_manual_item,
    confirm_tracking,
    list_authorized_loot_characters,
    loot_history,
    start_tracking,
    stop_or_refresh_tracking,
)


def _asset(item_id: int, type_id: int, quantity: int) -> dict[str, object]:
    return {
        "item_id": item_id,
        "type_id": type_id,
        "quantity": quantity,
        "location_id": 60003760,
        "location_type": "station",
        "location_flag": "Hangar",
    }


def _setup_authorized_characters(monkeypatch):
    if os.name != "nt":
        monkeypatch.setenv("EVE_ALLOW_UNENCRYPTED_TOKENS", "1")
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Loot Group")
    account_id = add_account(connection, group_id=group_id, name="Loot Account")
    character_ids = []
    for index, name in enumerate(("Looter A", "Looter B"), start=1):
        character_id = add_character(
            connection,
            account_id=account_id,
            name=name,
            total_sp=0,
        )
        store_api_token(
            connection,
            character_id=character_id,
            eve_character_id=9000 + index,
            scopes=("esi-assets.read_assets.v1",),
            encrypted_refresh_token=encrypt_refresh_token(f"refresh-{index}"),
            access_token_expires_at=None,
        )
        character_ids.append(character_id)
    return connection, character_ids


def test_loot_tracking_aggregates_characters_and_excludes_internal_transfers(monkeypatch) -> None:
    connection, character_ids = _setup_authorized_characters(monkeypatch)
    character_a, character_b = character_ids
    snapshots = [
        {
            character_a: [_asset(1, 100, 5), _asset(2, 200, 2)],
            character_b: [_asset(3, 100, 1)],
        },
        {
            character_a: [_asset(1, 100, 1)],
            character_b: [_asset(3, 100, 8), _asset(4, 300, 4)],
        },
    ]

    def fetch_assets(token, config):
        return snapshots[0 if not hasattr(fetch_assets, "stopped") else 1][
            int(token["character_id"])
        ]

    config = SsoConfig(client_id="client", callback_url="http://localhost:8766")
    session_id = start_tracking(
        connection,
        config=config,
        character_ids=character_ids,
        asset_fetcher=fetch_assets,
        now=datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc),
    )
    fetch_assets.stopped = True
    items = stop_or_refresh_tracking(
        connection,
        session_id=session_id,
        config=config,
        asset_fetcher=fetch_assets,
        type_name_resolver=lambda ids: {100: "Transferred Loot", 300: "New Loot"},
        market_price_fetcher=lambda: {
            100: {"average_price": 10.0},
            300: {"average_price": 25.0},
        },
        now=datetime(2026, 5, 31, 10, 30, tzinfo=timezone.utc),
    )

    assert {row["item_name"]: row["quantity"] for row in items} == {
        "Transferred Loot": 3,
        "New Loot": 4,
    }
    assert {row["item_name"]: row["total_value_isk"] for row in items} == {
        "Transferred Loot": 30,
        "New Loot": 100,
    }
    assert "Looter B" in next(
        row["current_holders"] for row in items if row["item_name"] == "New Loot"
    )

    add_manual_item(
        connection,
        session_id=session_id,
        item_name="Sold Before Snapshot",
        quantity=2,
        unit_value_isk=50,
    )
    editable = list_loot_session_items(connection, session_id=session_id)
    for row in editable:
        if row["item_name"] == "Transferred Loot":
            row["included"] = False
    confirm_tracking(connection, session_id=session_id, items=editable)

    history = loot_history(connection)
    assert history[0]["status"] == "Confirmed"
    assert history[0]["character_count"] == 2
    assert history[0]["total_value_isk"] == 200


def test_authorized_loot_characters_require_assets_scope(monkeypatch) -> None:
    connection, character_ids = _setup_authorized_characters(monkeypatch)
    connection.execute(
        "UPDATE api_tokens SET scopes = 'esi-skills.read_skills.v1' WHERE character_id = ?",
        (character_ids[1],),
    )
    connection.commit()

    authorized = list_authorized_loot_characters(connection)

    assert [row["character_id"] for row in authorized] == [character_ids[0]]


def test_asset_fetcher_reuses_and_rotates_stored_character_authorization(monkeypatch) -> None:
    connection, _ = _setup_authorized_characters(monkeypatch)
    token = list_api_tokens(connection)[0]
    config = SsoConfig(client_id="client", callback_url="http://localhost:8766")
    called = {}

    def refresh(config_arg, *, refresh_token):
        called["refresh_token"] = refresh_token
        return TokenResponse(
            access_token="new-access",
            refresh_token="rotated-refresh",
            expires_in=1200,
            token_type="Bearer",
        )

    class FakeAssetClient:
        def __init__(self, access_token):
            called["access_token"] = access_token

        def get_assets(self, eve_character_id):
            called["eve_character_id"] = eve_character_id
            return [_asset(1, 100, 2)]

        def close(self):
            called["closed"] = True

    assets = fetch_assets_from_stored_authorization(
        connection,
        token_row=token,
        config=config,
        refresh=refresh,
        client_factory=FakeAssetClient,
    )
    updated = list_api_tokens(connection)[0]

    assert assets == [_asset(1, 100, 2)]
    assert called == {
        "refresh_token": "refresh-1",
        "access_token": "new-access",
        "eve_character_id": 9001,
        "closed": True,
    }
    assert decrypt_refresh_token(updated["encrypted_refresh_token"]) == "rotated-refresh"
