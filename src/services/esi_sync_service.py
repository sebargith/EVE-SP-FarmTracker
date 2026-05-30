"""Synchronize local character records from EVE SSO/ESI."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from src.data.repositories import (
    add_wallet_snapshot,
    mark_api_token_sync,
    mark_api_token_sync_by_character,
    record_character_esi_sync,
    replace_character_assets,
    replace_character_skills,
    replace_skill_queue_entries,
    store_api_token,
    upsert_sso_character,
)
from src.integrations.esi_auth import EsiAuthenticatedClient, EsiCharacterData
from src.integrations.sso import (
    SsoConfig,
    TokenResponse,
    character_id_from_claims,
    refresh_access_token,
    scopes_from_claims,
    validate_access_token,
)
from src.integrations.token_store import decrypt_refresh_token, encrypt_refresh_token


class CharacterDataClient(Protocol):
    def get_character_data(
        self,
        character_id: int,
        *,
        include_wallet: bool = False,
        include_assets: bool = False,
    ) -> EsiCharacterData: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class SyncResult:
    character_id: int
    eve_character_id: int
    character_name: str
    total_sp: int
    current_skill: str
    queue_ends_at: str | None
    status: str


def import_authorized_character(
    connection: sqlite3.Connection,
    *,
    account_id: int,
    config: SsoConfig,
    token_response: TokenResponse,
    claims: dict[str, Any] | None = None,
    client: CharacterDataClient | None = None,
) -> SyncResult:
    """Persist a newly authorized character and immediately sync ESI fields."""

    verified_claims = claims or validate_access_token(
        token_response.access_token,
        client_id=config.client_id,
    )
    eve_character_id = character_id_from_claims(verified_claims)
    character_name = str(verified_claims.get("name", f"Character {eve_character_id}"))
    scopes = scopes_from_claims(verified_claims) or config.scopes

    character_id = upsert_sso_character(
        connection,
        account_id=account_id,
        eve_character_id=eve_character_id,
        name=character_name,
    )
    store_api_token(
        connection,
        character_id=character_id,
        eve_character_id=eve_character_id,
        scopes=scopes,
        encrypted_refresh_token=encrypt_refresh_token(token_response.refresh_token),
        access_token_expires_at=_expires_at_iso(token_response.expires_in),
    )
    result = sync_character_with_access_token(
        connection,
        character_id=character_id,
        eve_character_id=eve_character_id,
        character_name=character_name,
        access_token=token_response.access_token,
        scopes=scopes,
        client=client,
    )
    mark_api_token_sync_by_character(
        connection,
        character_id=character_id,
        status=result.status,
        access_token_expires_at=_expires_at_iso(token_response.expires_in),
    )
    return result


def sync_character_from_token_row(
    connection: sqlite3.Connection,
    *,
    token_row: dict[str, Any],
    config: SsoConfig,
    client: CharacterDataClient | None = None,
) -> SyncResult:
    """Refresh a stored token and sync one character."""

    refresh_token = decrypt_refresh_token(str(token_row["encrypted_refresh_token"]))
    token_response = refresh_access_token(config, refresh_token=refresh_token)
    scopes = tuple(str(token_row["scopes"]).split())
    result = sync_character_with_access_token(
        connection,
        character_id=int(token_row["character_id"]),
        eve_character_id=int(token_row["eve_character_id"]),
        character_name=str(token_row["character_name"]),
        access_token=token_response.access_token,
        scopes=scopes,
        client=client,
    )
    store_api_token(
        connection,
        character_id=int(token_row["character_id"]),
        eve_character_id=int(token_row["eve_character_id"]),
        scopes=scopes,
        encrypted_refresh_token=encrypt_refresh_token(token_response.refresh_token),
        access_token_expires_at=_expires_at_iso(token_response.expires_in),
        status=result.status,
    )
    mark_api_token_sync(
        connection,
        token_id=int(token_row["id"]),
        status=result.status,
        access_token_expires_at=_expires_at_iso(token_response.expires_in),
    )
    return result


def sync_character_with_access_token(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    eve_character_id: int,
    character_name: str,
    access_token: str,
    scopes: tuple[str, ...] | list[str],
    client: CharacterDataClient | None = None,
) -> SyncResult:
    """Fetch ESI character data and write it to the local database."""

    owns_client = client is None
    esi_client = client or EsiAuthenticatedClient(access_token)
    try:
        data = esi_client.get_character_data(
            eve_character_id,
            include_wallet="esi-wallet.read_character_wallet.v1" in scopes,
            include_assets="esi-assets.read_assets.v1" in scopes,
        )
    finally:
        if owns_client:
            esi_client.close()

    summary = summarize_esi_character_data(data)
    record_character_esi_sync(
        connection,
        character_id=character_id,
        total_sp=summary.total_sp,
        training_rate_sp_min=summary.training_rate_sp_min,
        current_skill=summary.current_skill,
        queue_ends_at=summary.queue_ends_at,
        attribute_profile=summary.attribute_profile,
        implant_profile=summary.implant_profile,
    )
    replace_character_skills(
        connection,
        character_id=character_id,
        skills=list((data.skills or {}).get("skills", [])),
    )
    replace_skill_queue_entries(
        connection,
        character_id=character_id,
        queue_entries=data.skill_queue,
    )
    if data.wallet_balance is not None:
        add_wallet_snapshot(
            connection,
            character_id=character_id,
            balance=data.wallet_balance,
        )
    if data.assets is not None:
        replace_character_assets(
            connection,
            character_id=character_id,
            assets=data.assets,
        )
    return SyncResult(
        character_id=character_id,
        eve_character_id=eve_character_id,
        character_name=character_name,
        total_sp=summary.total_sp,
        current_skill=summary.current_skill,
        queue_ends_at=summary.queue_ends_at,
        status="SSO Synced",
    )


@dataclass(frozen=True)
class EsiCharacterSummary:
    total_sp: int
    training_rate_sp_min: float
    current_skill: str
    queue_ends_at: str | None
    attribute_profile: str
    implant_profile: str


def summarize_esi_character_data(data: EsiCharacterData) -> EsiCharacterSummary:
    skills = data.skills or {}
    skill_queue = data.skill_queue
    first_queue_item = _first_active_queue_item(skill_queue)
    current_skill = _current_skill_text(first_queue_item)
    queue_ends_at = _queue_ends_at(skill_queue)
    training_rate = _training_rate_from_queue_item(first_queue_item)

    return EsiCharacterSummary(
        total_sp=int(skills.get("total_sp", 0)),
        training_rate_sp_min=training_rate,
        current_skill=current_skill,
        queue_ends_at=queue_ends_at,
        attribute_profile=_attribute_profile_text(data.attributes),
        implant_profile=_implant_profile_text(data.implants),
    )


def _first_active_queue_item(skill_queue: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not skill_queue:
        return None
    ordered = sorted(skill_queue, key=lambda row: int(row.get("queue_position", 0)))
    return ordered[0]


def _current_skill_text(queue_item: dict[str, Any] | None) -> str:
    if not queue_item:
        return ""
    skill_id = queue_item.get("skill_id", "unknown")
    level = queue_item.get("finished_level", "?")
    return f"Skill {skill_id} to {level}"


def _queue_ends_at(skill_queue: list[dict[str, Any]]) -> str | None:
    finish_dates = [str(row["finish_date"]) for row in skill_queue if row.get("finish_date")]
    return max(finish_dates) if finish_dates else None


def _training_rate_from_queue_item(queue_item: dict[str, Any] | None) -> float:
    if not queue_item:
        return 0.0
    start = _parse_datetime(queue_item.get("start_date"))
    finish = _parse_datetime(queue_item.get("finish_date"))
    training_start_sp = queue_item.get("training_start_sp")
    level_end_sp = queue_item.get("level_end_sp")
    if not start or not finish or training_start_sp is None or level_end_sp is None:
        return 45.0
    minutes = (finish - start).total_seconds() / 60
    if minutes <= 0:
        return 45.0
    return max((float(level_end_sp) - float(training_start_sp)) / minutes, 0.0)


def _attribute_profile_text(attributes: dict[str, Any] | None) -> str:
    if not attributes:
        return "ESI"
    keys = ["intelligence", "memory", "perception", "willpower", "charisma"]
    parts = [f"{key[:3].upper()} {int(attributes[key])}" for key in keys if key in attributes]
    return ", ".join(parts) if parts else "ESI"


def _implant_profile_text(implants: list[int]) -> str:
    if not implants:
        return "No active implants"
    return f"{len(implants)} active implants"


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _expires_at_iso(expires_in: int) -> str:
    return datetime.fromtimestamp(
        datetime.now(timezone.utc).timestamp() + int(expires_in),
        tz=timezone.utc,
    ).isoformat()
