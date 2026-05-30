"""Character SP progression and extraction readiness service."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor
from typing import Any

import pandas as pd

from src.calculations.assumptions import TrainingAssumptions
from src.data.repositories import list_character_rows


@dataclass(frozen=True)
class CharacterProgress:
    group_id: int
    group_name: str
    account_id: int
    account_name: str
    omega_status: str
    omega_expires_at: str | None
    mct_slots: int
    sync_status: str
    character_sync_status: str
    character_last_sync_at: str | None
    character_id: int
    character_name: str
    eve_character_id: int | None
    total_sp: int
    projected_sp: int
    total_sp_updated_at: str
    training_rate_sp_min: float
    current_skill: str
    queue_ends_at: str | None
    attribute_profile: str
    implant_profile: str
    sp_above_floor: int
    extractable_sp: int
    estimated_injectors: int
    ready_state: str
    next_injector_at: str | None
    days_to_next_injector: float | None
    projected_monthly_sp: float
    projected_monthly_injectors: float
    notes: str


@dataclass(frozen=True)
class CharacterProgressSummary:
    total_groups: int
    total_accounts: int
    total_characters: int
    ready_characters: int
    total_extractable_sp: int
    total_available_injectors: int
    projected_monthly_sp: float
    projected_monthly_injectors: float


def list_character_progress(
    connection: sqlite3.Connection,
    training: TrainingAssumptions,
    *,
    now: datetime | None = None,
) -> list[CharacterProgress]:
    """Return projected SP progression for all tracked characters."""

    current_time = now or datetime.now(timezone.utc)
    return [
        progress_from_row(row, training, now=current_time)
        for row in list_character_rows(connection)
    ]


def progress_from_row(
    row: dict[str, Any],
    training: TrainingAssumptions,
    *,
    now: datetime,
) -> CharacterProgress:
    """Calculate progression and readiness for one joined character row."""

    updated_at = parse_datetime(row["total_sp_updated_at"])
    queue_ends_at = parse_datetime(row["queue_ends_at"]) if row.get("queue_ends_at") else None
    rate = float(row["training_rate_sp_min"])
    projected_sp = project_sp(
        total_sp=int(row["total_sp"]),
        updated_at=updated_at,
        rate_sp_min=rate,
        now=now,
        queue_ends_at=queue_ends_at,
    )
    extractable_sp, injectors = extraction_capacity(
        projected_sp,
        extraction_floor_sp=int(training.extraction_floor_sp),
        minimum_sp_before_extraction=int(training.minimum_sp_before_extraction),
        sp_per_injector=int(training.sp_per_large_skill_injector),
    )
    sp_above_floor = max(projected_sp - int(training.extraction_floor_sp), 0)
    next_at, days_to_next = next_injector_timing(
        projected_sp=projected_sp,
        rate_sp_min=rate,
        now=now,
        queue_ends_at=queue_ends_at,
        extraction_floor_sp=int(training.extraction_floor_sp),
        minimum_sp_before_extraction=int(training.minimum_sp_before_extraction),
        sp_per_injector=int(training.sp_per_large_skill_injector),
    )
    monthly_sp = rate * 60 * 24 * 30
    ready_state = readiness_state(
        injectors=injectors,
        rate_sp_min=rate,
        next_injector_at=next_at,
        queue_ends_at=queue_ends_at,
        now=now,
    )

    return CharacterProgress(
        group_id=int(row["group_id"]),
        group_name=str(row["group_name"]),
        account_id=int(row["account_id"]),
        account_name=str(row["account_name"]),
        omega_status=str(row["omega_status"]),
        omega_expires_at=row["omega_expires_at"],
        mct_slots=int(row["mct_slots"]),
        sync_status=str(row["sync_status"]),
        character_sync_status=str(row.get("character_sync_status", "Manual")),
        character_last_sync_at=row.get("character_last_sync_at"),
        character_id=int(row["character_id"]),
        character_name=str(row["character_name"]),
        eve_character_id=row["eve_character_id"],
        total_sp=int(row["total_sp"]),
        projected_sp=projected_sp,
        total_sp_updated_at=str(row["total_sp_updated_at"]),
        training_rate_sp_min=rate,
        current_skill=str(row["current_skill"]),
        queue_ends_at=row["queue_ends_at"],
        attribute_profile=str(row["attribute_profile"]),
        implant_profile=str(row["implant_profile"]),
        sp_above_floor=sp_above_floor,
        extractable_sp=extractable_sp,
        estimated_injectors=injectors,
        ready_state=ready_state,
        next_injector_at=next_at.isoformat() if next_at else None,
        days_to_next_injector=days_to_next,
        projected_monthly_sp=monthly_sp,
        projected_monthly_injectors=monthly_sp / training.sp_per_large_skill_injector,
        notes=str(row["notes"]),
    )


def project_sp(
    *,
    total_sp: int,
    updated_at: datetime,
    rate_sp_min: float,
    now: datetime,
    queue_ends_at: datetime | None = None,
) -> int:
    """Project current SP from the last manual snapshot and training rate."""

    if rate_sp_min <= 0 or now <= updated_at:
        return total_sp

    projection_end = min(now, queue_ends_at) if queue_ends_at else now
    if projection_end <= updated_at:
        return total_sp

    minutes = (projection_end - updated_at).total_seconds() / 60
    return int(total_sp + minutes * rate_sp_min)


def extraction_capacity(
    total_sp: int,
    *,
    extraction_floor_sp: int,
    minimum_sp_before_extraction: int,
    sp_per_injector: int,
) -> tuple[int, int]:
    """Return whole extractable SP and injector count for a character."""

    if total_sp < minimum_sp_before_extraction:
        return 0, 0

    injectors = floor(max(total_sp - extraction_floor_sp, 0) / sp_per_injector)
    return injectors * sp_per_injector, injectors


def next_injector_timing(
    *,
    projected_sp: int,
    rate_sp_min: float,
    now: datetime,
    queue_ends_at: datetime | None,
    extraction_floor_sp: int,
    minimum_sp_before_extraction: int,
    sp_per_injector: int,
) -> tuple[datetime | None, float | None]:
    """Return when the next whole injector threshold is reached."""

    if rate_sp_min <= 0:
        return None, None

    _, current_injectors = extraction_capacity(
        projected_sp,
        extraction_floor_sp=extraction_floor_sp,
        minimum_sp_before_extraction=minimum_sp_before_extraction,
        sp_per_injector=sp_per_injector,
    )
    next_threshold = max(
        minimum_sp_before_extraction,
        extraction_floor_sp + (current_injectors + 1) * sp_per_injector,
    )
    if projected_sp >= next_threshold:
        return now, 0.0

    minutes_needed = (next_threshold - projected_sp) / rate_sp_min
    next_at = now + pd.Timedelta(minutes=minutes_needed).to_pytimedelta()
    if queue_ends_at and next_at > queue_ends_at:
        return None, None
    return next_at, minutes_needed / 60 / 24


def readiness_state(
    *,
    injectors: int,
    rate_sp_min: float,
    next_injector_at: datetime | None,
    queue_ends_at: datetime | None,
    now: datetime,
) -> str:
    if injectors > 0:
        return "READY"
    if queue_ends_at and queue_ends_at <= now:
        return "QUEUE ENDED"
    if rate_sp_min <= 0:
        return "PAUSED"
    if next_injector_at is None:
        return "QUEUE BLOCKED"
    return "TRAINING"


def summarize_progress(
    progress: list[CharacterProgress],
) -> CharacterProgressSummary:
    """Summarize character progression rows for dashboard KPIs."""

    return CharacterProgressSummary(
        total_groups=len({row.group_id for row in progress}),
        total_accounts=len({row.account_id for row in progress}),
        total_characters=len(progress),
        ready_characters=sum(1 for row in progress if row.ready_state == "READY"),
        total_extractable_sp=sum(row.extractable_sp for row in progress),
        total_available_injectors=sum(row.estimated_injectors for row in progress),
        projected_monthly_sp=sum(row.projected_monthly_sp for row in progress),
        projected_monthly_injectors=sum(row.projected_monthly_injectors for row in progress),
    )


def progress_to_dataframe(progress: list[CharacterProgress]) -> pd.DataFrame:
    """Convert progress rows to a display-friendly dataframe."""

    return pd.DataFrame([row.__dict__ for row in progress])


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
