from datetime import datetime, timezone

import pytest

from src.data.database import connect, initialize_database
from src.data.repositories import (
    add_account,
    add_account_group,
    add_character,
)
from src.services.loot_tracker_service import (
    active_session,
    add_filter,
    current_items,
    exclude_item,
    excluded_items,
    import_cargo_text,
    import_history,
    loot_history,
    parse_cargo_text,
    remove_filter,
    remove_item,
    start_tracking,
    stop_tracking,
    update_item,
)


def _connection():
    connection = connect(":memory:")
    initialize_database(connection)
    return connection


def test_parse_inventory_clipboard_rows_and_aggregate_duplicates() -> None:
    items = parse_cargo_text(
        """
Item\tQuantity\tGroup\tVolume\tEstimated Price
Burned Logic Circuit\t4\tSalvaged Materials\t0.04 m3\t1,200,000.00 ISK
Burned Logic Circuit\t2\tSalvaged Materials\t0.02 m3\t600,000.00 ISK
Tripped Power Circuit\t3\tSalvaged Materials\t0.03 m3\t900,000.00 ISK
        """
    )

    assert [(item.item_name, item.quantity) for item in items] == [
        ("Burned Logic Circuit", 6),
        ("Tripped Power Circuit", 3),
    ]
    assert items[0].unit_value_isk == 300_000
    assert items[0].total_value_isk == 1_800_000
    assert items[0].price_source == "Pasted estimate"


def test_parse_plain_and_quantity_marker_rows() -> None:
    items = parse_cargo_text(
        """
10 x Metal Scraps
Carbon x 3
Single Item
        """
    )

    assert [(item.item_name, item.quantity, item.unit_value_isk) for item in items] == [
        ("Carbon", 3, 0),
        ("Metal Scraps", 10, 0),
        ("Single Item", 1, 0),
    ]


def test_tracking_run_accumulates_pastes_filters_items_and_saves_history() -> None:
    connection = _connection()
    group_id = add_account_group(connection, name="Loot Group")
    account_id = add_account(connection, group_id=group_id, name="Loot Account")
    character_id = add_character(
        connection,
        account_id=account_id,
        name="Salvager",
        total_sp=0,
    )
    run_id = start_tracking(
        connection,
        notes="Abyss run",
        now=datetime(2026, 5, 31, 10, 0, tzinfo=timezone.utc),
    )

    first = import_cargo_text(
        connection,
        session_id=run_id,
        character_id=character_id,
        raw_text=(
            "Item\tQuantity\tGroup\tEstimated Price\n"
            "Burned Logic Circuit\t2\tSalvage\t400,000 ISK\n"
            "Metal Scraps\t5\tCommodity\t50,000 ISK"
        ),
        now=datetime(2026, 5, 31, 10, 5, tzinfo=timezone.utc),
        auto_price=False,
    )
    assert first.accepted_item_count == 2
    assert first.imported_value_isk == 450_000

    scraps = next(item for item in current_items(connection, session_id=run_id) if item["item_name"] == "Metal Scraps")
    exclude_item(connection, session_id=run_id, item_id=int(scraps["id"]))

    second = import_cargo_text(
        connection,
        session_id=run_id,
        raw_text=(
            "Burned Logic Circuit\t3\tSalvage\t900,000 ISK\n"
            "Metal Scraps\t2\tCommodity\t20,000 ISK\n"
            "Tripped Power Circuit\t1\tSalvage\t500,000 ISK"
        ),
        now=datetime(2026, 5, 31, 10, 15, tzinfo=timezone.utc),
        auto_price=False,
    )
    assert second.parsed_item_count == 3
    assert second.accepted_item_count == 2
    assert second.ignored_item_count == 1

    rows = current_items(connection, session_id=run_id)
    assert {row["item_name"]: row["quantity"] for row in rows} == {
        "Burned Logic Circuit": 5,
        "Tripped Power Circuit": 1,
    }
    assert {row["item_name"]: row["total_value_isk"] for row in rows} == {
        "Burned Logic Circuit": 1_500_000,
        "Tripped Power Circuit": 500_000,
    }
    assert len(import_history(connection, session_id=run_id)) == 2
    assert excluded_items(connection)[0]["item_name"] == "Metal Scraps"

    circuit = next(row for row in rows if row["item_name"] == "Tripped Power Circuit")
    update_item(
        connection,
        session_id=run_id,
        item_id=int(circuit["id"]),
        quantity=2,
        unit_value_isk=600_000,
    )
    stop_tracking(
        connection,
        session_id=run_id,
        now=datetime(2026, 5, 31, 11, 0, tzinfo=timezone.utc),
    )

    assert active_session(connection) is None
    history = loot_history(connection)
    assert history[0]["status"] == "Confirmed"
    assert history[0]["total_value_isk"] == 2_700_000


def test_remove_item_and_remove_filter() -> None:
    connection = _connection()
    run_id = start_tracking(connection)
    import_cargo_text(
        connection,
        session_id=run_id,
        raw_text="Metal Scraps x 4",
        auto_price=False,
    )
    item_id = int(current_items(connection, session_id=run_id)[0]["id"])

    remove_item(connection, session_id=run_id, item_id=item_id)
    assert current_items(connection, session_id=run_id) == []

    add_filter(connection, item_name="Metal Scraps", session_id=run_id)
    assert excluded_items(connection)[0]["normalized_name"] == "metal scraps"
    remove_filter(connection, normalized_name="metal scraps")
    assert excluded_items(connection) == []


def test_cannot_start_second_run_or_import_after_stop() -> None:
    connection = _connection()
    run_id = start_tracking(connection)

    with pytest.raises(ValueError, match="Stop the active"):
        start_tracking(connection)

    stop_tracking(connection, session_id=run_id)
    with pytest.raises(ValueError, match="already closed"):
        import_cargo_text(connection, session_id=run_id, raw_text="Metal Scraps")
