from datetime import datetime, timezone

from src.calculations.assumptions import load_assumptions
from src.data.database import connect, initialize_database
from src.data.repositories import add_account, add_account_group, add_character, update_account_operations
from src.services.account_operations_service import (
    list_account_operations,
    summarize_account_operations,
)


def test_account_operations_reports_unused_and_stopped_queues() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Operations Group")
    account_id = add_account(
        connection,
        group_id=group_id,
        name="Operations Account",
        omega_status="Omega",
        omega_expires_at="2026-07-01T00:00:00+00:00",
        mct_slots=1,
        mct_expires_at="2026-07-01T00:00:00+00:00",
    )
    add_character(
        connection,
        account_id=account_id,
        name="Training Farmer",
        total_sp=5_100_000,
        queue_ends_at="2026-06-02T00:00:00+00:00",
    )
    add_character(
        connection,
        account_id=account_id,
        name="Stopped Farmer",
        total_sp=5_100_000,
        queue_ends_at=None,
    )

    operations = list_account_operations(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 31, 0, 0, tzinfo=timezone.utc),
    )
    summary = summarize_account_operations(operations)

    assert operations[0].queue_capacity == 2
    assert operations[0].tracked_characters == 2
    assert operations[0].active_queues == 1
    assert operations[0].unused_queue_slots == 0
    assert operations[0].stopped_queues == 1
    assert operations[0].health == "Attention"
    assert operations[0].warnings == ("1 tracked queue(s) stopped",)
    assert summary.active_queues == 1
    assert summary.stopped_queues == 1


def test_update_account_operations_persists_manual_subscription_fields() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Manual Group")
    account_id = add_account(connection, group_id=group_id, name="Manual Account")

    update_account_operations(
        connection,
        account_id=account_id,
        omega_status="Omega",
        omega_expires_at="2026-06-10T00:00:00+00:00",
        mct_slots=2,
        mct_expires_at="2026-06-08T00:00:00+00:00",
        operational_status="Paused",
        notes="Review before renewal.",
    )

    operations = list_account_operations(
        connection,
        load_assumptions().training,
        now=datetime(2026, 5, 31, 0, 0, tzinfo=timezone.utc),
    )

    assert operations[0].omega_status == "Omega"
    assert operations[0].mct_slots == 2
    assert operations[0].mct_expires_at == "2026-06-08T00:00:00+00:00"
    assert operations[0].operational_status == "Paused"
    assert operations[0].notes == "Review before renewal."
