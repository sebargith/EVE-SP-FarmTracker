from src.data.database import connect, initialize_database


def test_extraction_event_lifecycle_columns_migrate_existing_table() -> None:
    connection = connect(":memory:")
    connection.executescript(
        """
        CREATE TABLE extraction_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            injectors_created INTEGER NOT NULL,
            sp_extracted INTEGER NOT NULL,
            extractor_unit_cost REAL NOT NULL,
            extractor_total_cost REAL NOT NULL,
            lsi_sale_unit_price REAL NOT NULL,
            gross_revenue REAL NOT NULL,
            market_fees REAL NOT NULL,
            realized_revenue REAL NOT NULL,
            realized_profit REAL NOT NULL,
            total_sp_before INTEGER NOT NULL,
            total_sp_after INTEGER NOT NULL,
            notes TEXT NOT NULL DEFAULT ''
        );

        INSERT INTO extraction_events (
            character_id, timestamp, injectors_created, sp_extracted,
            extractor_unit_cost, extractor_total_cost, lsi_sale_unit_price,
            gross_revenue, market_fees, realized_revenue, realized_profit,
            total_sp_before, total_sp_after, notes
        )
        VALUES (
            1, '2026-05-30T00:00:00+00:00', 1, 500000,
            450000000, 450000000, 800000000,
            800000000, 40000000, 760000000, 310000000,
            6100000, 5600000, 'legacy row'
        );
        """
    )

    initialize_database(connection)

    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(extraction_events)").fetchall()
    }
    event = connection.execute("SELECT * FROM extraction_events").fetchone()

    assert {
        "status",
        "reconciliation_status",
        "reconciled_at",
        "esi_total_sp",
        "expected_total_sp",
        "reconciliation_delta_sp",
        "reconciliation_message",
    } <= columns
    assert event["status"] == "Completed"
    assert event["reconciliation_status"] == "Pending"
