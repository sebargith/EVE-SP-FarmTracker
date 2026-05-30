from datetime import datetime, timezone

from src.calculations.assumptions import load_assumptions
from src.data.database import connect, initialize_database, seed_demo_data
from src.services.character_service import list_character_progress
from src.services.sp_tracking_service import (
    analytics_dataframe,
    alerts_dataframe,
    milestones_dataframe,
    next_sp_milestone,
    queue_health,
    snapshot_trend,
    snapshot_trends_by_character,
    sp_progress_analytics,
    sp_progress_analytics_by_character,
    sp_milestones,
    sp_tracking_dataframe,
    summarize_sp_tracking,
    tracking_alerts,
)


def test_summarize_sp_tracking_leads_with_queue_health() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 31, 0, 0, tzinfo=timezone.utc),
    )

    summary = summarize_sp_tracking(
        progress,
        now=datetime(2026, 5, 31, 0, 0, tzinfo=timezone.utc),
        warning_hours=24,
    )

    assert summary.total_projected_sp > 0
    assert summary.projected_monthly_sp > 0
    assert summary.active_training_queues == 3
    assert summary.queue_warning_characters == 1
    assert summary.empty_or_paused_queues == 0


def test_sp_tracking_dataframe_contains_progression_fields() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
    )

    df = sp_tracking_dataframe(
        progress,
        now=datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
    )

    assert set(
        [
            "Projected SP",
            "Monthly SP",
            "Queue Status",
            "Hours To Queue End",
            "Next Injector Days",
            "SP Above Floor",
            "SP Gain Since Last Snapshot",
            "Observed SP/day",
            "Expected SP/day",
            "Training Delta SP/day",
            "Snapshot Age Hours",
        ]
    ).issubset(df.columns)
    assert set(df["Queue Status"]) == {"TRAINING"}


def test_snapshot_trend_compares_latest_two_snapshots() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )
    character = progress[0]

    trend = snapshot_trend(
        character,
        [
            {
                "timestamp": "2026-05-30T00:00:00+00:00",
                "total_sp": 5_064_800,
                "source": "ESI",
                "notes": "",
            },
            {
                "timestamp": "2026-05-29T00:00:00+00:00",
                "total_sp": 5_000_000,
                "source": "ESI",
                "notes": "",
            },
        ],
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert trend.sp_gained == 64_800
    assert trend.hours_between_snapshots == 24
    assert trend.observed_sp_per_day == 64_800
    assert trend.expected_sp_per_day == 64_800
    assert trend.training_delta_sp_per_day == 0
    assert trend.snapshot_age_hours == 12


def test_sp_tracking_dataframe_includes_snapshot_trend_values() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )
    character = progress[0]
    trends = snapshot_trends_by_character(
        progress,
        {
            character.character_id: [
                {
                    "timestamp": "2026-05-30T00:00:00+00:00",
                    "total_sp": 5_064_800,
                    "source": "ESI",
                    "notes": "",
                },
                {
                    "timestamp": "2026-05-29T00:00:00+00:00",
                    "total_sp": 5_000_000,
                    "source": "ESI",
                    "notes": "",
                },
            ]
        },
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )

    df = sp_tracking_dataframe(
        progress,
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
        snapshot_trends=trends,
    )
    tracked = df.loc[df["Character"] == character.character_name].iloc[0]

    assert tracked["SP Gain Since Last Snapshot"] == 64_800
    assert tracked["Observed SP/day"] == 64_800
    assert tracked["Expected SP/day"] == 64_800
    assert tracked["Training Delta SP/day"] == 0
    assert tracked["Snapshot Age Hours"] == 12


def test_tracking_alerts_warn_when_snapshots_show_no_sp_gain() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )
    character = progress[0]
    trends = snapshot_trends_by_character(
        [character],
        {
            character.character_id: [
                {
                    "timestamp": "2026-05-30T00:00:00+00:00",
                    "total_sp": 5_000_000,
                    "source": "ESI",
                    "notes": "",
                },
                {
                    "timestamp": "2026-05-29T00:00:00+00:00",
                    "total_sp": 5_000_000,
                    "source": "ESI",
                    "notes": "",
                },
            ]
        },
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )

    alerts = tracking_alerts(
        [character],
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
        stale_snapshot_hours=48,
        snapshot_trends=trends,
    )

    assert any(
        alert.category == "Training"
        and alert.message == "No SP gain was observed between the last two snapshots."
        for alert in alerts
    )


def test_sp_progress_analytics_calculates_7d_and_30d_windows() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )
    character = progress[0]

    analytics = sp_progress_analytics(
        character,
        [
            {
                "timestamp": "2026-04-30T00:00:00+00:00",
                "total_sp": 3_056_000,
                "source": "ESI",
                "notes": "",
            },
            {
                "timestamp": "2026-05-23T00:00:00+00:00",
                "total_sp": 4_546_400,
                "source": "ESI",
                "notes": "",
            },
            {
                "timestamp": "2026-05-30T00:00:00+00:00",
                "total_sp": 5_000_000,
                "source": "ESI",
                "notes": "",
            },
        ],
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )

    assert analytics.snapshot_count == 3
    assert analytics.seven_day.sp_gained == 453_600
    assert analytics.seven_day.observed_sp_per_day == 64_800
    assert analytics.seven_day.window_coverage_pct == 100
    assert analytics.thirty_day.sp_gained == 1_944_000
    assert analytics.thirty_day.observed_sp_per_day == 64_800
    assert analytics.thirty_day.window_coverage_pct == 100
    assert analytics.queue_coverage_pct == 100


def test_analytics_dataframe_flattens_window_metrics() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )
    character = progress[0]
    analytics = sp_progress_analytics_by_character(
        [character],
        {
            character.character_id: [
                {
                    "timestamp": "2026-05-23T00:00:00+00:00",
                    "total_sp": 4_546_400,
                    "source": "ESI",
                    "notes": "",
                },
                {
                    "timestamp": "2026-05-30T00:00:00+00:00",
                    "total_sp": 5_000_000,
                    "source": "ESI",
                    "notes": "",
                },
            ]
        },
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )

    df = analytics_dataframe(analytics)

    assert len(df) == 1
    assert df.iloc[0]["7D SP Gain"] == 453_600
    assert df.iloc[0]["7D Observed SP/day"] == 64_800
    assert "30D Data Coverage %" in df.columns


def test_tracking_alerts_warn_when_7d_training_underperforms() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )
    character = progress[0]
    analytics = sp_progress_analytics_by_character(
        [character],
        {
            character.character_id: [
                {
                    "timestamp": "2026-05-23T00:00:00+00:00",
                    "total_sp": 4_900_000,
                    "source": "ESI",
                    "notes": "",
                },
                {
                    "timestamp": "2026-05-30T00:00:00+00:00",
                    "total_sp": 5_000_000,
                    "source": "ESI",
                    "notes": "",
                },
            ]
        },
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
    )

    alerts = tracking_alerts(
        [character],
        now=datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc),
        progress_analytics=analytics,
    )

    assert any(
        alert.category == "Training"
        and alert.message.startswith("7 day observed SP/day is below expected")
        for alert in alerts
    )


def test_queue_health_identifies_ended_queue() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc),
    )

    assert queue_health(
        progress[0],
        now=datetime(2026, 6, 10, 0, 0, tzinfo=timezone.utc),
    ) == "QUEUE ENDED"


def test_tracking_alerts_prioritize_ended_and_ending_queues() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc),
    )

    alerts = tracking_alerts(
        progress,
        now=datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc),
        warning_hours=24,
    )
    alerts_df = alerts_dataframe(alerts)

    assert not alerts_df.empty
    assert alerts[0].severity == "critical"
    assert alerts[0].category == "Queue"
    assert any(alert.message.startswith("Training queue ends in") for alert in alerts)


def test_next_sp_milestone_uses_500k_boundary() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
    )

    character = next(row for row in progress if row.character_name == "Example Farmer C")
    milestone = next_sp_milestone(
        character,
        now=datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
    )

    assert milestone.current_sp == 5_010_000
    assert milestone.target_sp == 5_500_000
    assert milestone.remaining_sp == 490_000
    assert round(milestone.days_to_milestone or 0, 2) == 7.56


def test_sp_milestones_dataframe_has_one_row_per_character() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)
    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
    )

    milestones = sp_milestones(
        progress,
        now=datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
    )
    milestones_df = milestones_dataframe(milestones)

    assert len(milestones) == len(progress)
    assert not milestones_df.empty
    assert set(["current_sp", "target_sp", "remaining_sp"]).issubset(milestones_df.columns)
