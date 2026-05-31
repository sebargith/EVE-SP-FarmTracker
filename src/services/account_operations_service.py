"""Manual account operations model around tracked character queues."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from src.calculations.assumptions import TrainingAssumptions
from src.data.repositories import list_accounts
from src.services.character_service import CharacterProgress, list_character_progress, parse_datetime


@dataclass(frozen=True)
class AccountOperation:
    group_name: str
    account_id: int
    account_name: str
    operational_status: str
    health: str
    omega_status: str
    omega_expires_at: str | None
    omega_days_remaining: float | None
    mct_slots: int
    mct_expires_at: str | None
    mct_days_remaining: float | None
    queue_capacity: int
    tracked_characters: int
    active_queues: int
    unused_queue_slots: int
    stopped_queues: int
    wallet_balance: float | None
    sync_status: str
    warnings: tuple[str, ...]
    notes: str


@dataclass(frozen=True)
class AccountOperationsSummary:
    total_accounts: int
    healthy_accounts: int
    attention_accounts: int
    queue_capacity: int
    active_queues: int
    unused_queue_slots: int
    stopped_queues: int


def list_account_operations(
    connection: sqlite3.Connection,
    training: TrainingAssumptions,
    *,
    now: datetime | None = None,
    progress: list[CharacterProgress] | None = None,
) -> list[AccountOperation]:
    """Return manually managed account status enriched with queue utilization."""

    current_time = now or datetime.now(timezone.utc)
    tracked = progress if progress is not None else list_character_progress(
        connection,
        training,
        now=current_time,
    )
    rows: list[AccountOperation] = []
    for account in list_accounts(connection):
        account_characters = [
            character
            for character in tracked
            if character.account_id == int(account["id"])
        ]
        active_queues = sum(
            1
            for character in account_characters
            if _is_training(character, now=current_time)
        )
        capacity = 1 + int(account["mct_slots"])
        unused_slots = max(capacity - len(account_characters), 0)
        stopped_queues = max(len(account_characters) - active_queues, 0)
        omega_days = _days_remaining(account["omega_expires_at"], now=current_time)
        mct_days = _days_remaining(account["mct_expires_at"], now=current_time)
        warnings = _account_warnings(
            omega_status=str(account["omega_status"]),
            omega_days_remaining=omega_days,
            mct_slots=int(account["mct_slots"]),
            mct_days_remaining=mct_days,
            unused_queue_slots=unused_slots,
            stopped_queues=stopped_queues,
            operational_status=str(account["operational_status"]),
        )
        rows.append(
            AccountOperation(
                group_name=str(account["group_name"]),
                account_id=int(account["id"]),
                account_name=str(account["name"]),
                operational_status=str(account["operational_status"]),
                health=_account_health(warnings),
                omega_status=str(account["omega_status"]),
                omega_expires_at=account["omega_expires_at"],
                omega_days_remaining=omega_days,
                mct_slots=int(account["mct_slots"]),
                mct_expires_at=account["mct_expires_at"],
                mct_days_remaining=mct_days,
                queue_capacity=capacity,
                tracked_characters=len(account_characters),
                active_queues=active_queues,
                unused_queue_slots=unused_slots,
                stopped_queues=stopped_queues,
                wallet_balance=(
                    float(account["wallet_balance"])
                    if account["wallet_balance"] is not None
                    else None
                ),
                sync_status=str(account["sync_status"]),
                warnings=warnings,
                notes=str(account["notes"]),
            )
        )
    return rows


def summarize_account_operations(
    operations: list[AccountOperation],
) -> AccountOperationsSummary:
    return AccountOperationsSummary(
        total_accounts=len(operations),
        healthy_accounts=sum(row.health == "Healthy" for row in operations),
        attention_accounts=sum(row.health != "Healthy" for row in operations),
        queue_capacity=sum(row.queue_capacity for row in operations),
        active_queues=sum(row.active_queues for row in operations),
        unused_queue_slots=sum(row.unused_queue_slots for row in operations),
        stopped_queues=sum(row.stopped_queues for row in operations),
    )


def _is_training(character: CharacterProgress, *, now: datetime) -> bool:
    if character.training_rate_sp_min <= 0 or not character.queue_ends_at:
        return False
    return parse_datetime(character.queue_ends_at) > now


def _days_remaining(value: str | None, *, now: datetime) -> float | None:
    if not value:
        return None
    return (parse_datetime(value) - now).total_seconds() / 86_400


def _account_warnings(
    *,
    omega_status: str,
    omega_days_remaining: float | None,
    mct_slots: int,
    mct_days_remaining: float | None,
    unused_queue_slots: int,
    stopped_queues: int,
    operational_status: str,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if operational_status != "Active":
        warnings.append(f"Account marked {operational_status.lower()}")
    if omega_status != "Omega":
        warnings.append(f"Omega status is {omega_status}")
    elif omega_days_remaining is not None and omega_days_remaining <= 0:
        warnings.append("Omega expired")
    elif omega_days_remaining is not None and omega_days_remaining <= 7:
        warnings.append("Omega expires within 7 days")
    if mct_slots and mct_days_remaining is not None and mct_days_remaining <= 0:
        warnings.append("MCT expired")
    elif mct_slots and mct_days_remaining is not None and mct_days_remaining <= 7:
        warnings.append("MCT expires within 7 days")
    if unused_queue_slots:
        warnings.append(f"{unused_queue_slots} queue slot(s) unassigned")
    if stopped_queues:
        warnings.append(f"{stopped_queues} tracked queue(s) stopped")
    return tuple(warnings)


def _account_health(warnings: tuple[str, ...]) -> str:
    if not warnings:
        return "Healthy"
    if any(
        warning in {"Omega expired", "MCT expired"}
        or warning.startswith("Omega status")
        for warning in warnings
    ):
        return "Critical"
    return "Attention"
