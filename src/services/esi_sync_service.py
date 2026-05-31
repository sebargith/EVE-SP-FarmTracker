"""Synchronize local character records from EVE SSO/ESI."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Protocol, TypeVar

from src.data.repositories import (
    add_sync_endpoint_result,
    add_wallet_snapshot,
    complete_sync_run,
    get_character_row,
    list_api_tokens,
    list_latest_sync_runs,
    list_sync_endpoint_results,
    list_sync_run_summaries,
    mark_api_token_sync,
    mark_api_token_sync_by_character,
    mark_character_sync_status,
    record_character_esi_sync,
    replace_character_assets,
    replace_character_skills,
    replace_skill_queue_entries,
    start_sync_run,
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
from src.services.extraction_service import reconcile_pending_extraction_events


SKILLS_SCOPE = "esi-skills.read_skills.v1"
SKILL_QUEUE_SCOPE = "esi-skills.read_skillqueue.v1"
IMPLANTS_SCOPE = "esi-clones.read_implants.v1"
WALLET_SCOPE = "esi-wallet.read_character_wallet.v1"
ASSETS_SCOPE = "esi-assets.read_assets.v1"
CORE_TRACKING_SCOPES = frozenset((SKILLS_SCOPE, SKILL_QUEUE_SCOPE, IMPLANTS_SCOPE))
DEFAULT_AUTO_SYNC_MINUTES = 60
DEFAULT_NEXT_SYNC_HOURS = 24


class CharacterDataClient(Protocol):
    def get_character_skills(self, character_id: int) -> dict[str, Any]: ...

    def get_skill_queue(self, character_id: int) -> list[dict[str, Any]]: ...

    def get_attributes(self, character_id: int) -> dict[str, Any]: ...

    def get_implants(self, character_id: int) -> list[int]: ...

    def get_wallet_balance(self, character_id: int) -> float: ...

    def get_assets(self, character_id: int) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class SyncEndpointResult:
    endpoint: str
    status: str
    message: str = ""


@dataclass(frozen=True)
class SyncResult:
    character_id: int
    eve_character_id: int
    character_name: str
    total_sp: int
    current_skill: str
    queue_ends_at: str | None
    status: str
    sync_run_id: int
    snapshot_recorded: bool
    endpoint_results: tuple[SyncEndpointResult, ...]


@dataclass(frozen=True)
class SyncHealth:
    character_id: int
    group_name: str
    account_name: str
    character_name: str
    health: str
    token_status: str
    training_state: str
    last_sync_at: str | None
    last_successful_sync_at: str | None
    last_failure_at: str | None
    next_recommended_sync_at: str | None
    latest_run_status: str | None
    missing_scopes: tuple[str, ...]
    failed_endpoints: tuple[str, ...]
    queue_coverage_hours: float
    sp_at_risk_before_next_sync: int


@dataclass(frozen=True)
class AutoSyncSummary:
    attempted: int
    successful: int
    partial: int
    failed: int


class EsiSyncError(RuntimeError):
    """Raised when required ESI data cannot be synchronized."""


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
        trigger="sso_import",
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
    trigger: str = "manual",
) -> SyncResult:
    """Refresh a stored token and sync one character."""

    character_id = int(token_row["character_id"])
    sync_run_id = start_sync_run(connection, character_id=character_id, trigger=trigger)
    try:
        refresh_token = decrypt_refresh_token(str(token_row["encrypted_refresh_token"]))
        token_response = refresh_access_token(config, refresh_token=refresh_token)
        _record_endpoint(connection, sync_run_id, "token_refresh", "Success")
    except Exception as exc:
        message = _error_message(exc)
        _record_endpoint(connection, sync_run_id, "token_refresh", "Failed", message)
        complete_sync_run(
            connection,
            sync_run_id=sync_run_id,
            status="Failed",
            error_message=message,
        )
        mark_api_token_sync(connection, token_id=int(token_row["id"]), status="Sync Failed")
        mark_character_sync_status(connection, character_id=character_id, status="SSO Sync Failed")
        raise

    scopes = tuple(str(token_row["scopes"]).split())
    try:
        result = sync_character_with_access_token(
            connection,
            character_id=character_id,
            eve_character_id=int(token_row["eve_character_id"]),
            character_name=str(token_row["character_name"]),
            access_token=token_response.access_token,
            scopes=scopes,
            client=client,
            trigger=trigger,
            sync_run_id=sync_run_id,
        )
    except Exception:
        mark_api_token_sync(connection, token_id=int(token_row["id"]), status="Sync Failed")
        raise

    store_api_token(
        connection,
        character_id=character_id,
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
    trigger: str = "manual",
    sync_run_id: int | None = None,
) -> SyncResult:
    """Fetch endpoint-level ESI data and write successful fields locally."""

    run_id = sync_run_id or start_sync_run(
        connection,
        character_id=character_id,
        trigger=trigger,
    )
    owns_client = client is None
    esi_client = client or EsiAuthenticatedClient(access_token)
    scope_set = set(scopes)
    existing = get_character_row(connection, character_id=character_id)
    endpoint_results: list[SyncEndpointResult] = []
    try:
        if not existing:
            raise EsiSyncError(f"Local character {character_id} was not found.")

        skills = _fetch_endpoint(
            connection,
            run_id,
            endpoint_results,
            endpoint="skills",
            getter=lambda: esi_client.get_character_skills(eve_character_id),
            scope=SKILLS_SCOPE,
            scopes=scope_set,
            required=True,
        )
        queue = _fetch_endpoint(
            connection,
            run_id,
            endpoint_results,
            endpoint="skill_queue",
            getter=lambda: esi_client.get_skill_queue(eve_character_id),
            scope=SKILL_QUEUE_SCOPE,
            scopes=scope_set,
        )
        attributes = _fetch_endpoint(
            connection,
            run_id,
            endpoint_results,
            endpoint="attributes",
            getter=lambda: esi_client.get_attributes(eve_character_id),
            scope=SKILLS_SCOPE,
            scopes=scope_set,
        )
        implants = _fetch_endpoint(
            connection,
            run_id,
            endpoint_results,
            endpoint="implants",
            getter=lambda: esi_client.get_implants(eve_character_id),
            scope=IMPLANTS_SCOPE,
            scopes=scope_set,
        )
        wallet_balance = _fetch_endpoint(
            connection,
            run_id,
            endpoint_results,
            endpoint="wallet",
            getter=lambda: esi_client.get_wallet_balance(eve_character_id),
            scope=WALLET_SCOPE,
            scopes=scope_set,
        )
        assets = _fetch_endpoint(
            connection,
            run_id,
            endpoint_results,
            endpoint="assets",
            getter=lambda: esi_client.get_assets(eve_character_id),
            scope=ASSETS_SCOPE,
            scopes=scope_set,
        )

        summary = summarize_esi_character_data(
            EsiCharacterData(
                skills=skills,
                skill_queue=queue or [],
                attributes=attributes,
                implants=implants or [],
                wallet_balance=wallet_balance,
                assets=assets,
            )
        )
        reconciliation = reconcile_pending_extraction_events(
            connection,
            character_id=character_id,
            esi_total_sp=summary.total_sp,
        )
        if reconciliation:
            reconciliation_status = (
                "Success" if reconciliation.status == "Match" else "Failed"
            )
            _record_endpoint(
                connection,
                run_id,
                "extraction_reconciliation",
                reconciliation_status,
                reconciliation.message,
            )
            endpoint_results.append(
                SyncEndpointResult(
                    endpoint="extraction_reconciliation",
                    status=reconciliation_status,
                    message=reconciliation.message,
                )
            )
        optional_failed = any(result.status == "Failed" for result in endpoint_results)
        sync_status = "SSO Partial" if optional_failed else "SSO Synced"
        snapshot_recorded = record_character_esi_sync(
            connection,
            character_id=character_id,
            total_sp=summary.total_sp,
            training_rate_sp_min=(
                summary.training_rate_sp_min
                if queue is not None
                else float(existing["training_rate_sp_min"])
            ),
            current_skill=summary.current_skill if queue is not None else str(existing["current_skill"]),
            queue_ends_at=summary.queue_ends_at if queue is not None else existing["queue_ends_at"],
            attribute_profile=(
                summary.attribute_profile
                if attributes is not None
                else str(existing["attribute_profile"])
            ),
            implant_profile=(
                summary.implant_profile
                if implants is not None
                else str(existing["implant_profile"])
            ),
            sync_status=sync_status,
        )
        replace_character_skills(
            connection,
            character_id=character_id,
            skills=list((skills or {}).get("skills", [])),
        )
        if queue is not None:
            replace_skill_queue_entries(
                connection,
                character_id=character_id,
                queue_entries=queue,
            )
        if wallet_balance is not None:
            add_wallet_snapshot(
                connection,
                character_id=character_id,
                balance=float(wallet_balance),
            )
        if assets is not None:
            replace_character_assets(
                connection,
                character_id=character_id,
                assets=assets,
            )
        complete_sync_run(
            connection,
            sync_run_id=run_id,
            status="Partial" if optional_failed else "Success",
        )
        return SyncResult(
            character_id=character_id,
            eve_character_id=eve_character_id,
            character_name=character_name,
            total_sp=summary.total_sp,
            current_skill=summary.current_skill,
            queue_ends_at=summary.queue_ends_at,
            status=sync_status,
            sync_run_id=run_id,
            snapshot_recorded=snapshot_recorded,
            endpoint_results=tuple(endpoint_results),
        )
    except Exception as exc:
        message = _error_message(exc)
        complete_sync_run(
            connection,
            sync_run_id=run_id,
            status="Failed",
            error_message=message,
        )
        mark_character_sync_status(connection, character_id=character_id, status="SSO Sync Failed")
        raise
    finally:
        if owns_client:
            esi_client.close()


def sync_due_authorized_characters(
    connection: sqlite3.Connection,
    *,
    config: SsoConfig,
    stale_after_minutes: int = DEFAULT_AUTO_SYNC_MINUTES,
    now: datetime | None = None,
) -> AutoSyncSummary:
    """Synchronize authorized characters whose last sync is stale."""

    current_time = now or datetime.now(timezone.utc)
    attempted = 0
    successful = 0
    partial = 0
    failed = 0
    for token in list_api_tokens(connection):
        if not is_token_sync_due(token, now=current_time, stale_after_minutes=stale_after_minutes):
            continue
        attempted += 1
        try:
            result = sync_character_from_token_row(
                connection,
                token_row=token,
                config=config,
                trigger="auto",
            )
        except Exception:
            failed += 1
        else:
            if result.status == "SSO Partial":
                partial += 1
            else:
                successful += 1
    return AutoSyncSummary(
        attempted=attempted,
        successful=successful,
        partial=partial,
        failed=failed,
    )


def is_token_sync_due(
    token_row: dict[str, Any],
    *,
    now: datetime | None = None,
    stale_after_minutes: int = DEFAULT_AUTO_SYNC_MINUTES,
) -> bool:
    """Return whether a stored token should be synchronized."""

    if not token_row.get("last_sync_at"):
        return True
    current_time = now or datetime.now(timezone.utc)
    last_sync = _parse_datetime(token_row["last_sync_at"])
    if not last_sync:
        return True
    return current_time - last_sync >= timedelta(minutes=stale_after_minutes)


def list_sync_health(
    connection: sqlite3.Connection,
    *,
    now: datetime | None = None,
    stale_after_minutes: int = DEFAULT_AUTO_SYNC_MINUTES,
    next_sync_hours: int = DEFAULT_NEXT_SYNC_HOURS,
) -> list[SyncHealth]:
    """Return token and endpoint health for authorized characters."""

    current_time = now or datetime.now(timezone.utc)
    latest_runs = {
        int(row["character_id"]): row
        for row in list_latest_sync_runs(connection)
    }
    run_summaries = {
        int(row["character_id"]): row
        for row in list_sync_run_summaries(connection)
    }
    health_rows: list[SyncHealth] = []
    for token in list_api_tokens(connection):
        character_id = int(token["character_id"])
        scopes = set(str(token["scopes"]).split())
        missing_scopes = tuple(sorted(CORE_TRACKING_SCOPES - scopes))
        latest_run = latest_runs.get(character_id)
        run_summary = run_summaries.get(character_id, {})
        endpoints = (
            list_sync_endpoint_results(connection, sync_run_id=int(latest_run["id"]))
            if latest_run
            else []
        )
        failed_endpoints = tuple(
            str(endpoint["endpoint"])
            for endpoint in endpoints
            if endpoint["status"] == "Failed"
        )
        queue_hours = _queue_coverage_hours(
            token.get("character_queue_ends_at"),
            now=current_time,
        )
        training_rate = float(token.get("character_training_rate_sp_min") or 0)
        sp_at_risk = int(max(next_sync_hours - queue_hours, 0) * 60 * training_rate)
        training_state = _training_state(
            token.get("character_queue_ends_at"),
            training_rate=training_rate,
            now=current_time,
        )
        due = is_token_sync_due(
            token,
            now=current_time,
            stale_after_minutes=stale_after_minutes,
        )
        latest_status = str(latest_run["status"]) if latest_run else None
        health_rows.append(
            SyncHealth(
                character_id=character_id,
                group_name=str(token["group_name"]),
                account_name=str(token["account_name"]),
                character_name=str(token["character_name"]),
                health=_health_state(
                    latest_status=latest_status,
                    missing_scopes=missing_scopes,
                    due=due,
                    training_state=training_state,
                ),
                token_status=str(token["status"]),
                training_state=training_state,
                last_sync_at=token.get("last_sync_at"),
                last_successful_sync_at=run_summary.get("last_successful_sync_at"),
                last_failure_at=run_summary.get("last_failure_at"),
                next_recommended_sync_at=_next_sync_at(
                    token.get("last_sync_at"),
                    stale_after_minutes=stale_after_minutes,
                ),
                latest_run_status=latest_status,
                missing_scopes=missing_scopes,
                failed_endpoints=failed_endpoints,
                queue_coverage_hours=queue_hours,
                sp_at_risk_before_next_sync=sp_at_risk,
            )
        )
    return health_rows


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


T = TypeVar("T")


def _fetch_endpoint(
    connection: sqlite3.Connection,
    sync_run_id: int,
    results: list[SyncEndpointResult],
    *,
    endpoint: str,
    getter: Callable[[], T],
    scope: str,
    scopes: set[str],
    required: bool = False,
) -> T | None:
    if scope not in scopes:
        message = f"Missing scope: {scope}"
        status = "Failed" if required else "Skipped"
        _record_endpoint(connection, sync_run_id, endpoint, status, message)
        results.append(SyncEndpointResult(endpoint=endpoint, status=status, message=message))
        if required:
            raise EsiSyncError(message)
        return None
    try:
        value = getter()
    except Exception as exc:
        message = _error_message(exc)
        _record_endpoint(connection, sync_run_id, endpoint, "Failed", message)
        results.append(SyncEndpointResult(endpoint=endpoint, status="Failed", message=message))
        if required:
            raise EsiSyncError(f"{endpoint} sync failed: {message}") from exc
        return None
    _record_endpoint(connection, sync_run_id, endpoint, "Success")
    results.append(SyncEndpointResult(endpoint=endpoint, status="Success"))
    return value


def _record_endpoint(
    connection: sqlite3.Connection,
    sync_run_id: int,
    endpoint: str,
    status: str,
    message: str = "",
) -> None:
    add_sync_endpoint_result(
        connection,
        sync_run_id=sync_run_id,
        endpoint=endpoint,
        status=status,
        message=message,
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


def _queue_coverage_hours(queue_ends_at: Any, *, now: datetime) -> float:
    parsed = _parse_datetime(queue_ends_at)
    if not parsed:
        return 0
    return max((parsed - now).total_seconds() / 3600, 0)


def _training_state(queue_ends_at: Any, *, training_rate: float, now: datetime) -> str:
    parsed = _parse_datetime(queue_ends_at)
    if not parsed:
        return "Queue Empty"
    if parsed <= now:
        return "Queue Ended"
    if training_rate <= 0:
        return "Projected Only"
    return "Training"


def _health_state(
    *,
    latest_status: str | None,
    missing_scopes: tuple[str, ...],
    due: bool,
    training_state: str,
) -> str:
    if latest_status == "Failed":
        return "Sync Failed"
    if missing_scopes:
        return "Missing Scope"
    if latest_status == "Partial":
        return "Partial Sync"
    if due:
        return "Sync Due"
    if training_state != "Training":
        return training_state
    return "Healthy"


def _next_sync_at(last_sync_at: Any, *, stale_after_minutes: int) -> str | None:
    parsed = _parse_datetime(last_sync_at)
    if not parsed:
        return None
    return (parsed + timedelta(minutes=stale_after_minutes)).isoformat()


def _error_message(exc: Exception) -> str:
    return str(exc)[:500] or exc.__class__.__name__
