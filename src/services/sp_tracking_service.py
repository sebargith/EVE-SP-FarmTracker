"""SP tracking and queue-health services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from src.services.character_service import CharacterProgress, parse_datetime


@dataclass(frozen=True)
class SpTrackingSummary:
    total_projected_sp: int
    projected_monthly_sp: float
    active_training_queues: int
    queue_warning_characters: int
    empty_or_paused_queues: int
    synced_characters: int
    next_queue_end_at: str | None


@dataclass(frozen=True)
class TrackingAlert:
    severity: str
    category: str
    group_name: str
    account_name: str
    character_name: str
    message: str
    action: str
    due_at: str | None = None


@dataclass(frozen=True)
class SpMilestone:
    group_name: str
    account_name: str
    character_name: str
    milestone: str
    current_sp: int
    target_sp: int
    remaining_sp: int
    days_to_milestone: float | None
    projected_at: str | None


@dataclass(frozen=True)
class SpSnapshotTrend:
    character_id: int
    latest_sp: int | None
    previous_sp: int | None
    latest_at: str | None
    previous_at: str | None
    sp_gained: int | None
    hours_between_snapshots: float | None
    observed_sp_per_day: float | None
    expected_sp_per_day: float
    training_delta_sp_per_day: float | None
    snapshot_age_hours: float | None


def summarize_sp_tracking(
    progress: list[CharacterProgress],
    *,
    now: datetime | None = None,
    warning_hours: float = 24,
) -> SpTrackingSummary:
    """Summarize SP progression and queue health."""

    current_time = now or datetime.now(timezone.utc)
    queue_rows = [
        (row, queue_health(row, now=current_time, warning_hours=warning_hours))
        for row in progress
    ]
    queue_end_times = [
        parse_datetime(row.queue_ends_at)
        for row in progress
        if row.queue_ends_at and parse_datetime(row.queue_ends_at) > current_time
    ]

    return SpTrackingSummary(
        total_projected_sp=sum(row.projected_sp for row in progress),
        projected_monthly_sp=sum(row.projected_monthly_sp for row in progress),
        active_training_queues=sum(1 for _, status in queue_rows if status == "TRAINING"),
        queue_warning_characters=sum(1 for _, status in queue_rows if status == "ENDS SOON"),
        empty_or_paused_queues=sum(
            1 for _, status in queue_rows if status in {"QUEUE ENDED", "PAUSED", "NO QUEUE"}
        ),
        synced_characters=sum(1 for row in progress if row.eve_character_id is not None),
        next_queue_end_at=min(queue_end_times).isoformat() if queue_end_times else None,
    )


def sp_tracking_dataframe(
    progress: list[CharacterProgress],
    *,
    now: datetime | None = None,
    warning_hours: float = 24,
    snapshot_trends: dict[int, SpSnapshotTrend] | None = None,
) -> pd.DataFrame:
    """Build the main SP tracking table."""

    current_time = now or datetime.now(timezone.utc)
    columns = [
        "Group",
        "Account",
        "Character",
        "Projected SP",
        "Monthly SP",
        "Current Skill",
        "Queue Status",
        "Queue Ends",
        "Hours To Queue End",
        "Next Injector Days",
        "SP Above Floor",
        "SP Gain Since Last Snapshot",
        "Observed SP/day",
        "Expected SP/day",
        "Training Delta SP/day",
        "Snapshot Age Hours",
        "Sync",
        "Last Sync",
    ]
    rows = []
    for row in progress:
        trend = _trend_for(row, snapshot_trends, now=current_time)
        rows.append(
            {
                "Group": row.group_name,
                "Account": row.account_name,
                "Character": row.character_name,
                "Projected SP": row.projected_sp,
                "Monthly SP": row.projected_monthly_sp,
                "Current Skill": row.current_skill or "n/a",
                "Queue Status": queue_health(row, now=current_time, warning_hours=warning_hours),
                "Queue Ends": row.queue_ends_at,
                "Hours To Queue End": hours_to_queue_end(row, now=current_time),
                "Next Injector Days": row.days_to_next_injector,
                "SP Above Floor": row.sp_above_floor,
                "SP Gain Since Last Snapshot": trend.sp_gained,
                "Observed SP/day": trend.observed_sp_per_day,
                "Expected SP/day": trend.expected_sp_per_day,
                "Training Delta SP/day": trend.training_delta_sp_per_day,
                "Snapshot Age Hours": trend.snapshot_age_hours,
                "Sync": row.character_sync_status,
                "Last Sync": row.character_last_sync_at,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def tracking_alerts(
    progress: list[CharacterProgress],
    *,
    now: datetime | None = None,
    warning_hours: float = 24,
    stale_sync_hours: float = 24,
    stale_snapshot_hours: float = 24,
    min_trend_hours: float = 1,
    low_training_ratio: float = 0.85,
    snapshot_trends: dict[int, SpSnapshotTrend] | None = None,
) -> list[TrackingAlert]:
    """Return actionable SP tracking alerts."""

    current_time = now or datetime.now(timezone.utc)
    alerts: list[TrackingAlert] = []
    for row in progress:
        status = queue_health(row, now=current_time, warning_hours=warning_hours)
        if status == "QUEUE ENDED":
            alerts.append(
                _alert(
                    row,
                    severity="critical",
                    category="Queue",
                    message="Training queue has ended.",
                    action="Log in and restart training.",
                    due_at=row.queue_ends_at,
                )
            )
        elif status == "ENDS SOON":
            hours_remaining = hours_to_queue_end(row, now=current_time)
            alerts.append(
                _alert(
                    row,
                    severity="warning",
                    category="Queue",
                    message=f"Training queue ends in {hours_remaining:.1f} hours.",
                    action="Prepare the next queued skill.",
                    due_at=row.queue_ends_at,
                )
            )
        elif status == "PAUSED":
            alerts.append(
                _alert(
                    row,
                    severity="warning",
                    category="Queue",
                    message="SP projection is paused because training rate is zero.",
                    action="Check Omega/training state or update the character.",
                )
            )
        elif status == "NO QUEUE":
            alerts.append(
                _alert(
                    row,
                    severity="warning",
                    category="Queue",
                    message="No active training queue is tracked.",
                    action="Sync ESI or add queue details.",
                )
            )

        if row.eve_character_id and is_sync_stale(
            row,
            now=current_time,
            stale_sync_hours=stale_sync_hours,
        ):
            alerts.append(
                _alert(
                    row,
                    severity="info",
                    category="Sync",
                    message="SSO data is stale.",
                    action="Run Sync All Authorized Characters.",
                    due_at=row.character_last_sync_at,
                )
            )

        trend = _trend_for(row, snapshot_trends, now=current_time)
        if trend.latest_at is None:
            alerts.append(
                _alert(
                    row,
                    severity="info",
                    category="Snapshot",
                    message="No SP snapshot is recorded.",
                    action="Sync ESI or save a manual SP snapshot.",
                )
            )
        elif (
            trend.snapshot_age_hours is not None
            and trend.snapshot_age_hours > stale_snapshot_hours
        ):
            alerts.append(
                _alert(
                    row,
                    severity="info",
                    category="Snapshot",
                    message=f"Latest SP snapshot is {trend.snapshot_age_hours:.1f} hours old.",
                    action="Sync ESI or save a fresh SP snapshot.",
                    due_at=trend.latest_at,
                )
            )

        if (
            trend.hours_between_snapshots is not None
            and trend.hours_between_snapshots >= min_trend_hours
            and trend.expected_sp_per_day > 0
            and trend.sp_gained is not None
        ):
            if trend.sp_gained <= 0:
                alerts.append(
                    _alert(
                        row,
                        severity="warning",
                        category="Training",
                        message="No SP gain was observed between the last two snapshots.",
                        action="Check Omega status, implants, and the active queue.",
                        due_at=trend.latest_at,
                    )
                )
            elif (
                trend.observed_sp_per_day is not None
                and trend.observed_sp_per_day < trend.expected_sp_per_day * low_training_ratio
            ):
                alerts.append(
                    _alert(
                        row,
                        severity="warning",
                        category="Training",
                        message=(
                            "Observed SP/day is below the expected training rate "
                            f"({trend.observed_sp_per_day:,.0f} vs "
                            f"{trend.expected_sp_per_day:,.0f})."
                        ),
                        action="Review attributes, implants, Omega state, and queue coverage.",
                        due_at=trend.latest_at,
                    )
                )

    severity_rank = {"critical": 0, "warning": 1, "info": 2}
    return sorted(
        alerts,
        key=lambda alert: (
            severity_rank.get(alert.severity, 9),
            alert.due_at or "",
            alert.group_name,
            alert.account_name,
            alert.character_name,
        ),
    )


def snapshot_trends_by_character(
    progress: list[CharacterProgress],
    snapshots_by_character: dict[int, list[dict[str, object]]],
    *,
    now: datetime | None = None,
) -> dict[int, SpSnapshotTrend]:
    """Build latest-vs-previous SP trend rows keyed by local character ID."""

    current_time = now or datetime.now(timezone.utc)
    return {
        row.character_id: snapshot_trend(
            row,
            snapshots_by_character.get(row.character_id, []),
            now=current_time,
        )
        for row in progress
    }


def snapshot_trend(
    row: CharacterProgress,
    snapshots: list[dict[str, object]],
    *,
    now: datetime | None = None,
) -> SpSnapshotTrend:
    """Compare the two most recent SP snapshots for one character."""

    current_time = now or datetime.now(timezone.utc)
    expected_sp_per_day = row.training_rate_sp_min * 60 * 24
    if not snapshots:
        return SpSnapshotTrend(
            character_id=row.character_id,
            latest_sp=None,
            previous_sp=None,
            latest_at=None,
            previous_at=None,
            sp_gained=None,
            hours_between_snapshots=None,
            observed_sp_per_day=None,
            expected_sp_per_day=expected_sp_per_day,
            training_delta_sp_per_day=None,
            snapshot_age_hours=None,
        )

    latest = snapshots[0]
    latest_at = str(latest["timestamp"])
    latest_time = parse_datetime(latest_at)
    latest_sp = int(latest["total_sp"])
    snapshot_age_hours = (current_time - latest_time).total_seconds() / 3600

    if len(snapshots) < 2:
        return SpSnapshotTrend(
            character_id=row.character_id,
            latest_sp=latest_sp,
            previous_sp=None,
            latest_at=latest_at,
            previous_at=None,
            sp_gained=None,
            hours_between_snapshots=None,
            observed_sp_per_day=None,
            expected_sp_per_day=expected_sp_per_day,
            training_delta_sp_per_day=None,
            snapshot_age_hours=snapshot_age_hours,
        )

    previous = snapshots[1]
    previous_at = str(previous["timestamp"])
    previous_time = parse_datetime(previous_at)
    previous_sp = int(previous["total_sp"])
    hours_between = (latest_time - previous_time).total_seconds() / 3600
    sp_gained = latest_sp - previous_sp
    observed_sp_per_day: float | None = None
    training_delta_sp_per_day: float | None = None
    if hours_between > 0:
        observed_sp_per_day = sp_gained / hours_between * 24
        training_delta_sp_per_day = observed_sp_per_day - expected_sp_per_day

    return SpSnapshotTrend(
        character_id=row.character_id,
        latest_sp=latest_sp,
        previous_sp=previous_sp,
        latest_at=latest_at,
        previous_at=previous_at,
        sp_gained=sp_gained,
        hours_between_snapshots=hours_between if hours_between > 0 else None,
        observed_sp_per_day=observed_sp_per_day,
        expected_sp_per_day=expected_sp_per_day,
        training_delta_sp_per_day=training_delta_sp_per_day,
        snapshot_age_hours=snapshot_age_hours,
    )


def sp_milestones(
    progress: list[CharacterProgress],
    *,
    now: datetime | None = None,
    milestone_size_sp: int = 500_000,
) -> list[SpMilestone]:
    """Return next generic SP milestone for each character."""

    current_time = now or datetime.now(timezone.utc)
    milestones = [
        next_sp_milestone(
            row,
            now=current_time,
            milestone_size_sp=milestone_size_sp,
        )
        for row in progress
    ]
    return sorted(
        milestones,
        key=lambda milestone: (
            milestone.days_to_milestone is None,
            milestone.days_to_milestone if milestone.days_to_milestone is not None else 10**9,
            milestone.group_name,
            milestone.account_name,
            milestone.character_name,
        ),
    )


def next_sp_milestone(
    row: CharacterProgress,
    *,
    now: datetime | None = None,
    milestone_size_sp: int = 500_000,
) -> SpMilestone:
    """Return the next SP boundary for a character."""

    current_time = now or datetime.now(timezone.utc)
    target_sp = ((row.projected_sp // milestone_size_sp) + 1) * milestone_size_sp
    remaining_sp = max(target_sp - row.projected_sp, 0)
    days_to_milestone: float | None = None
    projected_at: str | None = None

    if row.training_rate_sp_min > 0 and remaining_sp > 0:
        minutes = remaining_sp / row.training_rate_sp_min
        projected_time = current_time + pd.Timedelta(minutes=minutes).to_pytimedelta()
        if not row.queue_ends_at or projected_time <= parse_datetime(row.queue_ends_at):
            days_to_milestone = minutes / 60 / 24
            projected_at = projected_time.isoformat()

    return SpMilestone(
        group_name=row.group_name,
        account_name=row.account_name,
        character_name=row.character_name,
        milestone=f"Next {milestone_size_sp:,} SP boundary",
        current_sp=row.projected_sp,
        target_sp=target_sp,
        remaining_sp=remaining_sp,
        days_to_milestone=days_to_milestone,
        projected_at=projected_at,
    )


def queue_health(
    row: CharacterProgress,
    *,
    now: datetime | None = None,
    warning_hours: float = 24,
) -> str:
    """Return queue health independent of extraction readiness."""

    current_time = now or datetime.now(timezone.utc)
    if row.training_rate_sp_min <= 0:
        return "PAUSED"
    if not row.queue_ends_at:
        return "NO QUEUE"

    queue_end = parse_datetime(row.queue_ends_at)
    if queue_end <= current_time:
        return "QUEUE ENDED"

    hours_remaining = (queue_end - current_time).total_seconds() / 3600
    if hours_remaining <= warning_hours:
        return "ENDS SOON"
    return "TRAINING"


def hours_to_queue_end(row: CharacterProgress, *, now: datetime | None = None) -> float | None:
    if not row.queue_ends_at:
        return None
    current_time = now or datetime.now(timezone.utc)
    return (parse_datetime(row.queue_ends_at) - current_time).total_seconds() / 3600


def is_sync_stale(
    row: CharacterProgress,
    *,
    now: datetime | None = None,
    stale_sync_hours: float = 24,
) -> bool:
    if not row.character_last_sync_at:
        return True
    current_time = now or datetime.now(timezone.utc)
    last_sync = parse_datetime(row.character_last_sync_at)
    return (current_time - last_sync).total_seconds() / 3600 > stale_sync_hours


def snapshot_history_dataframe(snapshots: list[dict[str, object]]) -> pd.DataFrame:
    """Return oldest-first SP snapshot history for charting."""

    return pd.DataFrame(list(reversed(snapshots)))


def trends_dataframe(trends: dict[int, SpSnapshotTrend]) -> pd.DataFrame:
    return pd.DataFrame([trend.__dict__ for trend in trends.values()])


def alerts_dataframe(alerts: list[TrackingAlert]) -> pd.DataFrame:
    return pd.DataFrame([alert.__dict__ for alert in alerts])


def milestones_dataframe(milestones: list[SpMilestone]) -> pd.DataFrame:
    return pd.DataFrame([milestone.__dict__ for milestone in milestones])


def _alert(
    row: CharacterProgress,
    *,
    severity: str,
    category: str,
    message: str,
    action: str,
    due_at: str | None = None,
) -> TrackingAlert:
    return TrackingAlert(
        severity=severity,
        category=category,
        group_name=row.group_name,
        account_name=row.account_name,
        character_name=row.character_name,
        message=message,
        action=action,
        due_at=due_at,
    )


def _trend_for(
    row: CharacterProgress,
    snapshot_trends: dict[int, SpSnapshotTrend] | None,
    *,
    now: datetime | None = None,
) -> SpSnapshotTrend:
    if snapshot_trends and row.character_id in snapshot_trends:
        return snapshot_trends[row.character_id]
    return snapshot_trend(row, [], now=now)
