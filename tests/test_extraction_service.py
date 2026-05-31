from datetime import datetime, timedelta, timezone

import pytest

from src.calculations.assumptions import load_assumptions, with_market_overrides
from src.data.database import connect, initialize_database
from src.data.repositories import (
    add_account,
    add_account_group,
    add_character,
    add_market_snapshot,
    list_extraction_events,
    list_sp_snapshots,
)
from src.integrations.esi_public import (
    LARGE_SKILL_INJECTOR_TYPE_ID,
    PLEX_TYPE_ID,
    SKILL_EXTRACTOR_TYPE_ID,
)
from src.services.character_service import list_character_progress
from src.services.extraction_service import (
    build_extraction_plan,
    complete_planned_extraction,
    extraction_pricing_context,
    log_realized_extraction,
    reconcile_pending_extraction_events,
    summarize_extraction_plan,
)
from src.services.market_service import latest_market_scenario_overrides


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


def test_planned_extraction_does_not_change_sp_until_completed() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Plan Group")
    account_id = add_account(connection, group_id=group_id, name="Plan Account")
    character_id = add_character(
        connection,
        account_id=account_id,
        name="Plan Farmer",
        total_sp=6_100_000,
        training_rate_sp_min=0,
    )
    assumptions = load_assumptions()
    planned_at = datetime.now(timezone.utc) + timedelta(seconds=1)

    event_id = log_realized_extraction(
        connection,
        assumptions,
        character_id=character_id,
        injectors_created=1,
        status="Planned",
        now=planned_at,
    )
    planned = list_extraction_events(connection)[0]
    progress = list_character_progress(connection, assumptions.training, now=planned_at)

    assert planned["status"] == "Planned"
    assert planned["reconciliation_status"] == "Not Due"
    assert progress[0].total_sp == 6_100_000

    completed_at = planned_at + timedelta(seconds=1)
    complete_planned_extraction(
        connection,
        assumptions,
        event_id=event_id,
        now=completed_at,
    )
    completed = list_extraction_events(connection)[0]
    progress = list_character_progress(connection, assumptions.training, now=completed_at)

    assert completed["status"] == "Completed"
    assert completed["reconciliation_status"] == "Pending"
    assert progress[0].total_sp == 5_600_000


def test_reconcile_pending_extraction_marks_match_or_drift() -> None:
    assumptions = load_assumptions()

    match_connection = connect(":memory:")
    initialize_database(match_connection)
    group_id = add_account_group(match_connection, name="Match Group")
    account_id = add_account(match_connection, group_id=group_id, name="Match Account")
    character_id = add_character(
        match_connection,
        account_id=account_id,
        name="Match Farmer",
        total_sp=6_100_000,
        training_rate_sp_min=0,
    )
    completed_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    log_realized_extraction(
        match_connection,
        assumptions,
        character_id=character_id,
        injectors_created=1,
        now=completed_at,
    )

    reconciliation = reconcile_pending_extraction_events(
        match_connection,
        character_id=character_id,
        esi_total_sp=5_600_000,
        observed_at=completed_at,
    )

    assert reconciliation is not None
    assert reconciliation.status == "Match"
    assert list_extraction_events(match_connection)[0]["status"] == "Reconciled"

    drift_connection = connect(":memory:")
    initialize_database(drift_connection)
    group_id = add_account_group(drift_connection, name="Drift Group")
    account_id = add_account(drift_connection, group_id=group_id, name="Drift Account")
    character_id = add_character(
        drift_connection,
        account_id=account_id,
        name="Drift Farmer",
        total_sp=6_100_000,
        training_rate_sp_min=0,
    )
    log_realized_extraction(
        drift_connection,
        assumptions,
        character_id=character_id,
        injectors_created=1,
        now=completed_at,
    )

    reconciliation = reconcile_pending_extraction_events(
        drift_connection,
        character_id=character_id,
        esi_total_sp=5_750_000,
        observed_at=completed_at,
    )
    drift_event = list_extraction_events(drift_connection)[0]

    assert reconciliation is not None
    assert reconciliation.status == "Drift"
    assert reconciliation.delta_sp == 150_000
    assert drift_event["status"] == "Completed"
    assert drift_event["reconciliation_status"] == "Drift"


def test_extraction_pricing_context_identifies_manual_fresh_and_stale_prices() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    assumptions = load_assumptions()

    manual = extraction_pricing_context(connection, assumptions)
    assert manual.freshness == "Manual"
    assert manual.warnings == ("Planner uses editable manual/sidebar prices.",)

    for type_id, item_name, price in (
        (PLEX_TYPE_ID, "PLEX", 6_000_000),
        (LARGE_SKILL_INJECTOR_TYPE_ID, "Large Skill Injector", 1_000_000_000),
        (SKILL_EXTRACTOR_TYPE_ID, "Skill Extractor", 500_000_000),
    ):
        add_market_snapshot(
            connection,
            region_id=10000002,
            location_id=60003760,
            type_id=type_id,
            item_name=item_name,
            best_buy_price=price - 10,
            best_sell_price=price,
            buy_volume=10,
            sell_volume=10,
            order_count=2,
        )
    market = latest_market_scenario_overrides(connection)
    live_assumptions = with_market_overrides(
        assumptions,
        plex_cost_basis_isk=market.plex_cost_basis_isk,
        large_skill_injector_sell_price_isk=market.large_skill_injector_sell_price_isk,
        skill_extractor_market_buy_price_isk=market.skill_extractor_market_buy_price_isk,
    )

    fresh = extraction_pricing_context(connection, live_assumptions)
    assert fresh.source == "Saved ESI market snapshots"
    assert fresh.freshness == "Fresh"
    assert fresh.warnings == ()

    connection.execute(
        "UPDATE market_snapshots SET timestamp = '2026-05-01T00:00:00+00:00'"
    )
    connection.commit()
    stale = extraction_pricing_context(
        connection,
        live_assumptions,
        now=datetime(2026, 5, 31, 0, 0, tzinfo=timezone.utc),
    )
    assert stale.freshness == "Stale"
    assert "720.0 hours old" in stale.warnings[0]
