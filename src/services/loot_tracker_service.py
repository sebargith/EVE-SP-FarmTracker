"""Multi-character loot tracking from explicit before and after asset snapshots."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from src.data.repositories import (
    add_manual_loot_item,
    confirm_loot_session as persist_confirm_loot_session,
    create_loot_session,
    get_loot_session,
    get_open_loot_session,
    list_api_tokens,
    list_loot_asset_diff_by_type,
    list_loot_end_holders_by_type,
    list_loot_session_characters,
    list_loot_session_items,
    list_loot_sessions,
    replace_character_assets,
    replace_loot_asset_diff_items,
    replace_loot_end_snapshots,
    update_loot_session_items,
)
from src.integrations.esi_public import EsiPublicClient, fetch_inventory_type_names
from src.integrations.sso import SsoConfig
from src.services.authorized_asset_service import (
    ASSETS_SCOPE,
    fetch_assets_from_stored_authorization,
)


ASSET_CACHE_MAX_SECONDS = 3600


def list_authorized_loot_characters(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return SSO characters whose stored token can read assets."""

    return [
        token
        for token in list_api_tokens(connection)
        if ASSETS_SCOPE in str(token["scopes"]).split()
    ]


def start_tracking(
    connection: sqlite3.Connection,
    *,
    config: SsoConfig,
    character_ids: list[int] | tuple[int, ...],
    notes: str = "",
    asset_fetcher: Callable[[dict[str, Any], SsoConfig], list[dict[str, Any]]] | None = None,
    now: datetime | None = None,
) -> int:
    """Capture a baseline asset snapshot for selected authorized characters."""

    if get_open_loot_session(connection):
        raise ValueError("Finish or confirm the open loot session before starting another.")
    selected_ids = tuple(dict.fromkeys(int(character_id) for character_id in character_ids))
    if not selected_ids:
        raise ValueError("Select at least one authorized character.")

    assets_by_character = _capture_assets(
        connection,
        config=config,
        character_ids=selected_ids,
        asset_fetcher=asset_fetcher,
    )
    recorded_at = (now or datetime.now(timezone.utc)).isoformat()
    return create_loot_session(
        connection,
        assets_by_character=assets_by_character,
        notes=notes,
        started_at=recorded_at,
    )


def stop_or_refresh_tracking(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    config: SsoConfig,
    asset_fetcher: Callable[[dict[str, Any], SsoConfig], list[dict[str, Any]]] | None = None,
    type_name_resolver: Callable[[list[int] | tuple[int, ...]], dict[int, str]] = fetch_inventory_type_names,
    market_price_fetcher: Callable[[], dict[int, dict[str, float]]] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Capture an end snapshot, then regenerate editable candidate-loot rows."""

    session = _required_session(connection, session_id=session_id)
    if session["status"] not in {"Active", "Awaiting Confirmation"}:
        raise ValueError("Only active or awaiting-confirmation sessions can capture assets.")
    character_ids = [
        int(row["character_id"])
        for row in list_loot_session_characters(connection, session_id=session_id)
    ]
    assets_by_character = _capture_assets(
        connection,
        config=config,
        character_ids=tuple(character_ids),
        asset_fetcher=asset_fetcher,
    )
    captured_at = (now or datetime.now(timezone.utc)).isoformat()
    replace_loot_end_snapshots(
        connection,
        session_id=session_id,
        assets_by_character=assets_by_character,
        captured_at=captured_at,
    )
    return refresh_candidate_items(
        connection,
        session_id=session_id,
        type_name_resolver=type_name_resolver,
        market_price_fetcher=market_price_fetcher,
    )


def refresh_candidate_items(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    type_name_resolver: Callable[[list[int] | tuple[int, ...]], dict[int, str]] = fetch_inventory_type_names,
    market_price_fetcher: Callable[[], dict[int, dict[str, float]]] | None = None,
) -> list[dict[str, Any]]:
    """Regenerate asset-diff candidates and estimate their market-average value."""

    diffs = list_loot_asset_diff_by_type(connection, session_id=session_id)
    type_ids = [int(row["type_id"]) for row in diffs]
    names = _resolve_names(type_ids, resolver=type_name_resolver)
    prices = _resolve_prices(fetcher=market_price_fetcher) if type_ids else {}
    items = []
    for diff in diffs:
        type_id = int(diff["type_id"])
        quantity = int(diff["quantity"])
        unit_value, source = _reference_value(prices.get(type_id, {}))
        items.append(
            {
                "type_id": type_id,
                "item_name": names.get(type_id, f"Type {type_id}"),
                "quantity": quantity,
                "unit_value_isk": unit_value,
                "total_value_isk": quantity * unit_value,
                "price_source": source,
            }
        )
    replace_loot_asset_diff_items(connection, session_id=session_id, items=items)
    return list_loot_items_with_holders(connection, session_id=session_id)


def list_loot_items_with_holders(
    connection: sqlite3.Connection,
    *,
    session_id: int,
) -> list[dict[str, Any]]:
    holders: dict[int, list[str]] = {}
    for row in list_loot_end_holders_by_type(connection, session_id=session_id):
        holders.setdefault(int(row["type_id"]), []).append(
            f"{row['character_name']} ({int(row['quantity']):,})"
        )
    items = list_loot_session_items(connection, session_id=session_id)
    for item in items:
        type_id = item.get("type_id")
        item["current_holders"] = (
            ", ".join(holders.get(int(type_id), []))
            if type_id is not None
            else "Manual entry"
        )
    return items


def add_manual_item(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    item_name: str,
    quantity: int,
    unit_value_isk: float,
) -> int:
    session = _required_session(connection, session_id=session_id)
    if session["status"] != "Awaiting Confirmation":
        raise ValueError("Manual loot items can be added after capturing an end snapshot.")
    if not item_name.strip():
        raise ValueError("Item name is required.")
    if int(quantity) <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if float(unit_value_isk) < 0:
        raise ValueError("Unit value cannot be negative.")
    return add_manual_loot_item(
        connection,
        session_id=session_id,
        item_name=item_name.strip(),
        quantity=int(quantity),
        unit_value_isk=float(unit_value_isk),
    )


def confirm_tracking(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    items: list[dict[str, Any]],
) -> None:
    session = _required_session(connection, session_id=session_id)
    if session["status"] != "Awaiting Confirmation":
        raise ValueError("Capture an end snapshot before confirming loot.")
    update_loot_session_items(connection, session_id=session_id, items=items)
    persist_confirm_loot_session(connection, session_id=session_id)


def loot_history(connection: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    return list_loot_sessions(connection, limit=limit)


def next_recommended_refresh_at(session: dict[str, Any]) -> str | None:
    if not session.get("end_snapshot_at"):
        return None
    parsed = datetime.fromisoformat(str(session["end_snapshot_at"]).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (parsed + timedelta(seconds=ASSET_CACHE_MAX_SECONDS)).isoformat()


def _capture_assets(
    connection: sqlite3.Connection,
    *,
    config: SsoConfig,
    character_ids: tuple[int, ...],
    asset_fetcher: Callable[[dict[str, Any], SsoConfig], list[dict[str, Any]]] | None,
) -> dict[int, list[dict[str, Any]]]:
    tokens = {
        int(token["character_id"]): token
        for token in list_authorized_loot_characters(connection)
    }
    missing = [character_id for character_id in character_ids if character_id not in tokens]
    if missing:
        raise ValueError(
            "Selected characters must be authorized with "
            f"{ASSETS_SCOPE}: {', '.join(str(character_id) for character_id in missing)}"
        )
    fetcher = asset_fetcher or _default_asset_fetcher(connection)
    assets_by_character = {
        character_id: list(fetcher(tokens[character_id], config))
        for character_id in character_ids
    }
    for character_id, assets in assets_by_character.items():
        replace_character_assets(connection, character_id=character_id, assets=assets)
    return assets_by_character


def _default_asset_fetcher(
    connection: sqlite3.Connection,
) -> Callable[[dict[str, Any], SsoConfig], list[dict[str, Any]]]:
    return lambda token_row, config: fetch_assets_from_stored_authorization(
        connection,
        token_row=token_row,
        config=config,
    )


def _required_session(connection: sqlite3.Connection, *, session_id: int) -> dict[str, Any]:
    session = get_loot_session(connection, session_id=session_id)
    if not session:
        raise ValueError("Loot session was not found.")
    return session


def _resolve_names(
    type_ids: list[int],
    *,
    resolver: Callable[[list[int] | tuple[int, ...]], dict[int, str]],
) -> dict[int, str]:
    try:
        return resolver(type_ids)
    except Exception:
        return {}


def _resolve_prices(
    *,
    fetcher: Callable[[], dict[int, dict[str, float]]] | None,
) -> dict[int, dict[str, float]]:
    if fetcher:
        try:
            return fetcher()
        except Exception:
            return {}
    client = EsiPublicClient()
    try:
        return client.get_market_prices()
    except Exception:
        return {}
    finally:
        client.close()


def _reference_value(prices: dict[str, float]) -> tuple[float, str]:
    if prices.get("average_price") is not None:
        return float(prices["average_price"]), "ESI market average"
    if prices.get("adjusted_price") is not None:
        return float(prices["adjusted_price"]), "ESI adjusted price"
    return 0.0, "Unpriced"
