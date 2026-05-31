from datetime import datetime, timedelta, timezone

import pytest

from src.calculations.assumptions import load_assumptions
from src.data.database import connect, initialize_database
from src.data.repositories import (
    add_account,
    add_account_group,
    add_character,
    list_extraction_events,
    list_sp_snapshots,
)
from src.services.character_service import list_character_progress
from src.services.extraction_service import (
    build_extraction_plan,
    log_realized_extraction,
    summarize_extraction_plan,
)


def test_extraction_plan_uses_incremental_market_economics() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Extraction Group")
    account_id = add_account(connection, group_id=group_id, name="Extraction Account")
    add_character(
        connection,
        account_id=account_id,
        name="Ready Farmer",
        total_sp=6_100_000,
        training_rate_sp_min=0,
    )
    assumptions = load_assumptions()

    rows = build_extraction_plan(
        connection,
        assumptions,
        now=datetime(2026, 5, 31, 0, 0, tzinfo=timezone.utc),
    )
    summary = summarize_extraction_plan(rows)

    assert rows[0].injectors_ready == 2
    assert rows[0].extractable_sp == 1_000_000
    assert rows[0].recommendation == "Extract Now"
    assert rows[0].projected_profit == pytest.approx(
        2
        * (
            assumptions.market.large_skill_injector_sell_price_isk
            * (1 - assumptions.market.lsi_market_fee_tax_rate)
            - assumptions.market.skill_extractor_market_buy_price_isk
        )
    )
    assert summary.ready_characters == 1
    assert summary.injectors_ready == 2


def test_log_realized_extraction_updates_sp_baseline_and_audit() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Audit Group")
    account_id = add_account(connection, group_id=group_id, name="Audit Account")
    character_id = add_character(
        connection,
        account_id=account_id,
        name="Audit Farmer",
        total_sp=6_100_000,
        training_rate_sp_min=0,
    )
    assumptions = load_assumptions()
    recorded_at = datetime.now(timezone.utc) + timedelta(seconds=1)

    event_id = log_realized_extraction(
        connection,
        assumptions,
        character_id=character_id,
        injectors_created=1,
        lsi_sale_unit_price=800_000_000,
        extractor_unit_cost=450_000_000,
        market_fee_rate=0.05,
        notes="Manual audit test",
        now=recorded_at,
    )

    events = list_extraction_events(connection)
    progress = list_character_progress(
        connection,
        assumptions.training,
        now=recorded_at,
    )
    snapshots = list_sp_snapshots(connection, character_id=character_id)

    assert event_id == events[0]["id"]
    assert events[0]["injectors_created"] == 1
    assert events[0]["sp_extracted"] == 500_000
    assert events[0]["realized_profit"] == pytest.approx(310_000_000)
    assert events[0]["total_sp_before"] == 6_100_000
    assert events[0]["total_sp_after"] == 5_600_000
    assert progress[0].total_sp == 5_600_000
    assert snapshots[0]["source"] == "Extraction"


def test_log_realized_extraction_rejects_more_than_available() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Guard Group")
    account_id = add_account(connection, group_id=group_id, name="Guard Account")
    character_id = add_character(
        connection,
        account_id=account_id,
        name="Guard Farmer",
        total_sp=5_600_000,
        training_rate_sp_min=0,
    )

    with pytest.raises(ValueError, match="more injectors"):
        log_realized_extraction(
            connection,
            load_assumptions(),
            character_id=character_id,
            injectors_created=2,
        )
