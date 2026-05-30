from datetime import datetime, timezone

from src.calculations.assumptions import load_assumptions
from src.data.database import connect, initialize_database, seed_demo_data
from src.data.repositories import add_account, add_account_group, add_character, update_character_sp
from src.services.character_service import (
    extraction_capacity,
    list_character_progress,
    next_injector_timing,
    project_sp,
    summarize_progress,
)


def test_extraction_capacity_uses_whole_injectors_and_floor() -> None:
    training = load_assumptions().training

    assert extraction_capacity(
        5_490_000,
        extraction_floor_sp=int(training.extraction_floor_sp),
        minimum_sp_before_extraction=int(training.minimum_sp_before_extraction),
        sp_per_injector=int(training.sp_per_large_skill_injector),
    ) == (0, 0)
    assert extraction_capacity(
        5_500_000,
        extraction_floor_sp=int(training.extraction_floor_sp),
        minimum_sp_before_extraction=int(training.minimum_sp_before_extraction),
        sp_per_injector=int(training.sp_per_large_skill_injector),
    ) == (500_000, 1)
    assert extraction_capacity(
        6_210_000,
        extraction_floor_sp=int(training.extraction_floor_sp),
        minimum_sp_before_extraction=int(training.minimum_sp_before_extraction),
        sp_per_injector=int(training.sp_per_large_skill_injector),
    ) == (1_000_000, 2)


def test_project_sp_stops_at_queue_end() -> None:
    updated_at = datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc)
    queue_ends_at = datetime(2026, 5, 30, 1, 0, tzinfo=timezone.utc)
    now = datetime(2026, 5, 30, 2, 0, tzinfo=timezone.utc)

    assert project_sp(
        total_sp=5_000_000,
        updated_at=updated_at,
        rate_sp_min=45,
        now=now,
        queue_ends_at=queue_ends_at,
    ) == 5_002_700


def test_next_injector_timing() -> None:
    training = load_assumptions().training
    now = datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc)

    next_at, days = next_injector_timing(
        projected_sp=5_455_000,
        rate_sp_min=45,
        now=now,
        queue_ends_at=None,
        extraction_floor_sp=int(training.extraction_floor_sp),
        minimum_sp_before_extraction=int(training.minimum_sp_before_extraction),
        sp_per_injector=int(training.sp_per_large_skill_injector),
    )

    assert next_at is not None
    assert days is not None
    assert round(days, 3) == round((45_000 / 45) / 60 / 24, 3)


def test_list_character_progress_and_summary_from_database() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    seed_demo_data(connection)

    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 30, 0, 0, tzinfo=timezone.utc),
    )
    summary = summarize_progress(progress)

    assert len(progress) == 4
    assert summary.total_groups == 2
    assert summary.total_accounts == 3
    assert summary.ready_characters == 2
    assert summary.total_available_injectors == 6


def test_repository_manual_character_update() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Test Group")
    account_id = add_account(connection, group_id=group_id, name="Test Account")
    character_id = add_character(
        connection,
        account_id=account_id,
        name="Test Character",
        total_sp=5_100_000,
    )
    update_character_sp(connection, character_id=character_id, total_sp=5_600_000)

    progress = list_character_progress(
        connection,
        load_assumptions().training,
        now=datetime.now(timezone.utc),
    )

    assert progress[0].character_name == "Test Character"
    assert progress[0].total_sp == 5_600_000
    assert progress[0].estimated_injectors == 1
