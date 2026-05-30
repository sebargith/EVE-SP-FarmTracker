import os

from src.data.database import connect, initialize_database
from src.data.repositories import (
    add_account,
    add_account_group,
    latest_wallet_snapshot,
    list_api_tokens,
    list_assets_by_type,
    list_character_rows,
    list_character_skills,
    list_skill_queue_entries,
)
from src.integrations.esi_public import LARGE_SKILL_INJECTOR_TYPE_ID, PLEX_TYPE_ID
from src.integrations.esi_auth import EsiCharacterData
from src.integrations.sso import SsoConfig, TokenResponse
from src.services.esi_sync_service import import_authorized_character, summarize_esi_character_data


class FakeEsiClient:
    def __init__(self, data: EsiCharacterData) -> None:
        self.data = data

    def get_character_data(
        self,
        character_id: int,
        *,
        include_wallet: bool = False,
        include_assets: bool = False,
    ):
        return self.data

    def close(self) -> None:
        return None


def test_summarize_esi_character_data_maps_skill_queue() -> None:
    summary = summarize_esi_character_data(
        EsiCharacterData(
            skills={"total_sp": 6_250_000},
            skill_queue=[
                {
                    "queue_position": 0,
                    "skill_id": 3402,
                    "finished_level": 5,
                    "start_date": "2026-05-30T00:00:00Z",
                    "finish_date": "2026-05-30T10:00:00Z",
                    "training_start_sp": 0,
                    "level_end_sp": 27_000,
                }
            ],
            attributes={"intelligence": 32, "memory": 26},
            implants=[10216, 10217],
            assets=[],
        )
    )

    assert summary.total_sp == 6_250_000
    assert summary.current_skill == "Skill 3402 to 5"
    assert summary.queue_ends_at == "2026-05-30T10:00:00Z"
    assert summary.training_rate_sp_min == 45
    assert summary.attribute_profile == "INT 32, MEM 26"
    assert summary.implant_profile == "2 active implants"


def test_import_authorized_character_stores_token_and_syncs(monkeypatch) -> None:
    if os.name != "nt":
        monkeypatch.setenv("EVE_ALLOW_UNENCRYPTED_TOKENS", "1")

    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="SSO Group")
    account_id = add_account(connection, group_id=group_id, name="SSO Account")
    config = SsoConfig(
        client_id="client-123",
        callback_url="http://localhost:8766",
        scopes=(
            "esi-skills.read_skills.v1",
            "esi-skills.read_skillqueue.v1",
            "esi-clones.read_implants.v1",
            "esi-wallet.read_character_wallet.v1",
            "esi-assets.read_assets.v1",
        ),
    )
    token_response = TokenResponse(
        access_token="access-token",
        refresh_token="refresh-token",
        expires_in=1200,
        token_type="Bearer",
    )

    result = import_authorized_character(
        connection,
        account_id=account_id,
        config=config,
        token_response=token_response,
        claims={
            "sub": "CHARACTER:EVE:987654",
            "name": "SSO Farmer",
            "scp": list(config.scopes),
        },
        client=FakeEsiClient(
            EsiCharacterData(
                skills={
                    "total_sp": 5_750_000,
                    "skills": [
                        {
                            "skill_id": 3300,
                            "active_skill_level": 5,
                            "trained_skill_level": 5,
                            "skillpoints_in_skill": 256000,
                        }
                    ],
                },
                skill_queue=[
                    {
                        "queue_position": 0,
                        "skill_id": 3402,
                        "finished_level": 4,
                        "start_date": "2026-05-30T00:00:00Z",
                        "finish_date": "2026-05-30T08:00:00Z",
                        "training_start_sp": 0,
                        "level_start_sp": 0,
                        "level_end_sp": 21600,
                    }
                ],
                attributes={"intelligence": 32, "memory": 26},
                implants=[],
                wallet_balance=123_456_789.0,
                assets=[
                    {
                        "item_id": 1,
                        "type_id": LARGE_SKILL_INJECTOR_TYPE_ID,
                        "quantity": 3,
                        "location_id": 60003760,
                        "location_type": "station",
                        "location_flag": "Hangar",
                        "is_singleton": False,
                    },
                    {
                        "item_id": 2,
                        "type_id": PLEX_TYPE_ID,
                        "quantity": 500,
                        "location_id": 60003760,
                        "location_type": "station",
                        "location_flag": "Hangar",
                        "is_singleton": False,
                    },
                ],
            )
        ),
    )

    rows = list_character_rows(connection)
    tokens = list_api_tokens(connection)
    skills = list_character_skills(connection, character_id=result.character_id)
    queue = list_skill_queue_entries(connection, character_id=result.character_id)
    wallet = latest_wallet_snapshot(connection, character_id=result.character_id)
    assets = list_assets_by_type(
        connection,
        character_id=result.character_id,
        type_ids=(LARGE_SKILL_INJECTOR_TYPE_ID, PLEX_TYPE_ID),
    )

    assert result.character_name == "SSO Farmer"
    assert rows[0]["eve_character_id"] == 987654
    assert rows[0]["total_sp"] == 5_750_000
    assert rows[0]["character_sync_status"] == "SSO Synced"
    assert len(tokens) == 1
    assert tokens[0]["character_name"] == "SSO Farmer"
    assert tokens[0]["encrypted_refresh_token"] != "refresh-token"
    assert skills[0]["skill_id"] == 3300
    assert skills[0]["skillpoints_in_skill"] == 256000
    assert queue[0]["skill_id"] == 3402
    assert wallet is not None
    assert wallet["balance"] == 123_456_789.0
    assert {row["type_id"]: row["quantity"] for row in assets} == {
        LARGE_SKILL_INJECTOR_TYPE_ID: 3,
        PLEX_TYPE_ID: 500,
    }
