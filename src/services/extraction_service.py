"""Extraction recommendations and realized event logging."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil

from src.calculations.assumptions import FarmAssumptions
from src.calculations.profitability import calculate_extractor_cost, calculate_lsi_revenue
from src.data.repositories import (
    complete_planned_extraction_event,
    get_character_row,
    get_extraction_event,
    list_pending_completed_extraction_events,
    record_extraction_event,
    record_extraction_reconciliation,
)
from src.integrations.esi_public import LARGE_SKILL_INJECTOR_TYPE_ID, SKILL_EXTRACTOR_TYPE_ID
from src.services.character_service import (
    CharacterProgress,
    list_character_progress,
    parse_datetime,
    project_sp,
)
from src.services.market_service import latest_market_overview, latest_market_scenario_overrides


DEFAULT_MARKET_STALE_HOURS = 24


@dataclass(frozen=True)
class ExtractionPlanRow:
    group_name: str
    account_name: str
    character_id: int
    character_name: str
    readiness: str
    recommendation: str
    projected_sp: int
    extractable_sp: int
    injectors_ready: int
    days_to_next_injector: float | None
    next_injector_at: str | None
    queue_ends_at: str | None
    lsi_unit_price: float
    extractor_unit_cost: float
    market_fee_rate: float
    gross_revenue: float
    market_fees: float
    net_revenue: float
    extractor_total_cost: float
    projected_profit: float
    pricing_source: str
    pricing_as_of: str | None
    pricing_age_hours: float | None
    pricing_warning: str


@dataclass(frozen=True)
class ExtractionPlanSummary:
    ready_characters: int
    injectors_ready: int
    injectors_available_this_week: int
    total_extractable_sp: int
    planned_gross_revenue: float
    planned_extractor_cost: float
    planned_market_fees: float
    planned_net_profit: float


@dataclass(frozen=True)
class ExtractionPricingContext:
    source: str
    as_of: str | None
    age_hours: float | None
    freshness: str
    source_summary: str
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionReconciliation:
    event_ids: tuple[int, ...]
    status: str
    esi_total_sp: int
    expected_total_sp: int
    delta_sp: int
    tolerance_sp: int
    message: str


def build_extraction_plan(
    connection: sqlite3.Connection,
    assumptions: FarmAssumptions,
    *,
    now: datetime | None = None,
    progress: list[CharacterProgress] | None = None,
) -> list[ExtractionPlanRow]:
    """Build extraction recommendations from tracked SP and editable prices."""

    current_time = now or datetime.now(timezone.utc)
    tracked = progress if progress is not None else list_character_progress(
        connection,
        assumptions.training,
        now=current_time,
    )
    lsi_price = assumptions.market.large_skill_injector_sell_price_isk
    extractor_price = assumptions.market.skill_extractor_market_buy_price_isk
    fee_rate = assumptions.market.lsi_market_fee_tax_rate
    pricing = extraction_pricing_context(
        connection,
        assumptions,
        now=current_time,
    )
    rows: list[ExtractionPlanRow] = []
    for character in tracked:
        injectors = character.estimated_injectors
        gross_revenue = injectors * lsi_price
        net_revenue = calculate_lsi_revenue(injectors, lsi_price, fee_rate)
        extractor_total = calculate_extractor_cost(injectors, extractor_price)
        rows.append(
            ExtractionPlanRow(
                group_name=character.group_name,
                account_name=character.account_name,
                character_id=character.character_id,
                character_name=character.character_name,
                readiness=character.ready_state,
                recommendation=_recommendation(
                    character,
                    profit_per_injector=calculate_lsi_revenue(1, lsi_price, fee_rate)
                    - extractor_price,
                ),
                projected_sp=character.projected_sp,
                extractable_sp=character.extractable_sp,
                injectors_ready=injectors,
                days_to_next_injector=character.days_to_next_injector,
                next_injector_at=character.next_injector_at,
                queue_ends_at=character.queue_ends_at,
                lsi_unit_price=lsi_price,
                extractor_unit_cost=extractor_price,
                market_fee_rate=fee_rate,
                gross_revenue=gross_revenue,
                market_fees=gross_revenue - net_revenue,
                net_revenue=net_revenue,
                extractor_total_cost=extractor_total,
                projected_profit=net_revenue - extractor_total,
                pricing_source=pricing.source,
                pricing_as_of=pricing.as_of,
                pricing_age_hours=pricing.age_hours,
                pricing_warning="; ".join(pricing.warnings),
            )
        )
    return rows


def summarize_extraction_plan(rows: list[ExtractionPlanRow]) -> ExtractionPlanSummary:
    return ExtractionPlanSummary(
        ready_characters=sum(row.injectors_ready > 0 for row in rows),
        injectors_ready=sum(row.injectors_ready for row in rows),
        injectors_available_this_week=sum(
            row.injectors_ready
            + (
                1
                if row.days_to_next_injector is not None
                and 0 < row.days_to_next_injector <= 7
                else 0
            )
            for row in rows
        ),
        total_extractable_sp=sum(row.extractable_sp for row in rows),
        planned_gross_revenue=sum(row.gross_revenue for row in rows),
        planned_extractor_cost=sum(row.extractor_total_cost for row in rows),
        planned_market_fees=sum(row.market_fees for row in rows),
        planned_net_profit=sum(row.projected_profit for row in rows),
    )


def log_realized_extraction(
    connection: sqlite3.Connection,
    assumptions: FarmAssumptions,
    *,
    character_id: int,
    injectors_created: int,
    lsi_sale_unit_price: float | None = None,
    extractor_unit_cost: float | None = None,
    market_fee_rate: float | None = None,
    notes: str = "",
    now: datetime | None = None,
    status: str = "Completed",
) -> int:
    """Record a planned or completed extraction event."""

    current_time = now or datetime.now(timezone.utc)
    progress = list_character_progress(
        connection,
        assumptions.training,
        now=current_time,
    )
    character = next(
        (row for row in progress if row.character_id == int(character_id)),
        None,
    )
    if not character:
        raise ValueError("Tracked character was not found.")
    if injectors_created <= 0:
        raise ValueError("injectors_created must be greater than zero.")
    if injectors_created > character.estimated_injectors:
        raise ValueError("Cannot log more injectors than the character currently has available.")

    unit_lsi = float(
        lsi_sale_unit_price
        if lsi_sale_unit_price is not None
        else assumptions.market.large_skill_injector_sell_price_isk
    )
    unit_extractor = float(
        extractor_unit_cost
        if extractor_unit_cost is not None
        else assumptions.market.skill_extractor_market_buy_price_isk
    )
    fee_rate = float(
        market_fee_rate
        if market_fee_rate is not None
        else assumptions.market.lsi_market_fee_tax_rate
    )
    sp_extracted = int(injectors_created * assumptions.training.sp_per_large_skill_injector)
    total_sp_after = character.projected_sp - sp_extracted
    if total_sp_after < int(assumptions.training.extraction_floor_sp):
        raise ValueError("Extraction would leave the character below the configured SP floor.")

    gross_revenue = injectors_created * unit_lsi
    net_revenue = calculate_lsi_revenue(injectors_created, unit_lsi, fee_rate)
    extractor_total = calculate_extractor_cost(injectors_created, unit_extractor)
    return record_extraction_event(
        connection,
        character_id=character.character_id,
        injectors_created=injectors_created,
        sp_extracted=sp_extracted,
        extractor_unit_cost=unit_extractor,
        extractor_total_cost=extractor_total,
        lsi_sale_unit_price=unit_lsi,
        gross_revenue=gross_revenue,
        market_fees=gross_revenue - net_revenue,
        realized_revenue=net_revenue,
        realized_profit=net_revenue - extractor_total,
        total_sp_before=character.projected_sp,
        total_sp_after=total_sp_after,
        status=status,
        notes=notes,
        timestamp=current_time.isoformat(),
    )


def complete_planned_extraction(
    connection: sqlite3.Connection,
    assumptions: FarmAssumptions,
    *,
    event_id: int,
    lsi_sale_unit_price: float | None = None,
    extractor_unit_cost: float | None = None,
    market_fee_rate: float | None = None,
    notes: str | None = None,
    now: datetime | None = None,
) -> None:
    """Apply a planned event when the extraction is actually completed."""

    event = get_extraction_event(connection, event_id=event_id)
    if not event:
        raise ValueError("Extraction event was not found.")
    if event["status"] != "Planned":
        raise ValueError("Only planned extraction events can be completed.")
    injectors_created = int(event["injectors_created"])
    current_time = now or datetime.now(timezone.utc)
    progress = list_character_progress(connection, assumptions.training, now=current_time)
    character = next(
        (row for row in progress if row.character_id == int(event["character_id"])),
        None,
    )
    if not character:
        raise ValueError("Tracked character was not found.")
    if injectors_created > character.estimated_injectors:
        raise ValueError("Character no longer has enough extractable SP for this plan.")

    unit_lsi, unit_extractor, fee_rate = _resolved_prices(
        assumptions,
        lsi_sale_unit_price=lsi_sale_unit_price,
        extractor_unit_cost=extractor_unit_cost,
        market_fee_rate=market_fee_rate,
        fallback_event=event,
    )
    sp_extracted = int(injectors_created * assumptions.training.sp_per_large_skill_injector)
    total_sp_after = character.projected_sp - sp_extracted
    gross_revenue = injectors_created * unit_lsi
    net_revenue = calculate_lsi_revenue(injectors_created, unit_lsi, fee_rate)
    extractor_total = calculate_extractor_cost(injectors_created, unit_extractor)
    complete_planned_extraction_event(
        connection,
        event_id=event_id,
        total_sp_before=character.projected_sp,
        total_sp_after=total_sp_after,
        extractor_unit_cost=unit_extractor,
        extractor_total_cost=extractor_total,
        lsi_sale_unit_price=unit_lsi,
        gross_revenue=gross_revenue,
        market_fees=gross_revenue - net_revenue,
        realized_revenue=net_revenue,
        realized_profit=net_revenue - extractor_total,
        notes=str(notes if notes is not None else event["notes"]),
        timestamp=current_time.isoformat(),
    )


def reconcile_pending_extraction_events(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    esi_total_sp: int,
    observed_at: datetime | None = None,
    tolerance_sp: int | None = None,
) -> ExtractionReconciliation | None:
    """Compare the next ESI total SP against completed local extraction events."""

    pending = list_pending_completed_extraction_events(
        connection,
        character_id=character_id,
    )
    if not pending:
        return None
    character = get_character_row(connection, character_id=character_id)
    if not character:
        raise ValueError("Tracked character was not found.")

    current_time = observed_at or datetime.now(timezone.utc)
    rate = float(character["training_rate_sp_min"])
    expected_total_sp = project_sp(
        total_sp=int(character["total_sp"]),
        updated_at=parse_datetime(str(character["total_sp_updated_at"])),
        rate_sp_min=rate,
        now=current_time,
        queue_ends_at=(
            parse_datetime(str(character["queue_ends_at"]))
            if character["queue_ends_at"]
            else None
        ),
    )
    allowed_delta = int(tolerance_sp if tolerance_sp is not None else max(rate * 15, 1_000))
    delta = int(esi_total_sp) - expected_total_sp
    status = "Match" if abs(delta) <= allowed_delta else "Drift"
    event_ids = tuple(int(event["id"]) for event in pending)
    message = (
        f"ESI SP matched the expected post-extraction baseline within {allowed_delta:,} SP."
        if status == "Match"
        else (
            f"ESI SP drifted by {delta:,} SP from the expected post-extraction "
            f"baseline; tolerance is {allowed_delta:,} SP."
        )
    )
    record_extraction_reconciliation(
        connection,
        event_ids=event_ids,
        reconciliation_status=status,
        esi_total_sp=int(esi_total_sp),
        expected_total_sp=expected_total_sp,
        reconciliation_delta_sp=delta,
        reconciliation_message=message,
        reconciled_at=current_time.isoformat(),
    )
    return ExtractionReconciliation(
        event_ids=event_ids,
        status=status,
        esi_total_sp=int(esi_total_sp),
        expected_total_sp=expected_total_sp,
        delta_sp=delta,
        tolerance_sp=allowed_delta,
        message=message,
    )


def extraction_pricing_context(
    connection: sqlite3.Connection,
    assumptions: FarmAssumptions,
    *,
    now: datetime | None = None,
    stale_after_hours: float = DEFAULT_MARKET_STALE_HOURS,
) -> ExtractionPricingContext:
    """Describe whether planner prices are live saved ESI values or manual inputs."""

    current_time = now or datetime.now(timezone.utc)
    market = latest_market_scenario_overrides(connection)
    market_rows = latest_market_overview(connection)
    extraction_timestamps = [
        str(row["timestamp"])
        for row in market_rows
        if int(row["type_id"]) in {LARGE_SKILL_INJECTOR_TYPE_ID, SKILL_EXTRACTOR_TYPE_ID}
        and row.get("timestamp")
    ]
    extraction_as_of = min(extraction_timestamps) if len(extraction_timestamps) == 2 else None
    uses_saved_market = (
        market.large_skill_injector_sell_price_isk is not None
        and market.skill_extractor_market_buy_price_isk is not None
        and assumptions.market.large_skill_injector_sell_price_isk
        == market.large_skill_injector_sell_price_isk
        and assumptions.market.skill_extractor_market_buy_price_isk
        == market.skill_extractor_market_buy_price_isk
    )
    age_hours = _age_hours(extraction_as_of, now=current_time)
    warnings: list[str] = []
    if not uses_saved_market:
        warnings.append("Planner uses editable manual/sidebar prices.")
    elif age_hours is None:
        warnings.append("Saved ESI price timestamp is unavailable.")
    elif age_hours > stale_after_hours:
        warnings.append(f"Saved ESI market prices are {age_hours:.1f} hours old.")
    return ExtractionPricingContext(
        source="Saved ESI market snapshots" if uses_saved_market else "Manual/sidebar assumptions",
        as_of=extraction_as_of if uses_saved_market else None,
        age_hours=age_hours if uses_saved_market else None,
        freshness=(
            "Manual"
            if not uses_saved_market
            else "Stale"
            if warnings
            else "Fresh"
        ),
        source_summary=market.source_summary,
        warnings=tuple(warnings),
    )


def _resolved_prices(
    assumptions: FarmAssumptions,
    *,
    lsi_sale_unit_price: float | None,
    extractor_unit_cost: float | None,
    market_fee_rate: float | None,
    fallback_event: dict[str, object] | None = None,
) -> tuple[float, float, float]:
    return (
        float(
            lsi_sale_unit_price
            if lsi_sale_unit_price is not None
            else fallback_event["lsi_sale_unit_price"]
            if fallback_event
            else assumptions.market.large_skill_injector_sell_price_isk
        ),
        float(
            extractor_unit_cost
            if extractor_unit_cost is not None
            else fallback_event["extractor_unit_cost"]
            if fallback_event
            else assumptions.market.skill_extractor_market_buy_price_isk
        ),
        float(
            market_fee_rate
            if market_fee_rate is not None
            else (
                float(fallback_event["market_fees"]) / float(fallback_event["gross_revenue"])
                if fallback_event and float(fallback_event["gross_revenue"])
                else assumptions.market.lsi_market_fee_tax_rate
            )
        ),
    )


def _age_hours(value: str | None, *, now: datetime) -> float | None:
    if not value:
        return None
    return max((now - parse_datetime(value)).total_seconds() / 3_600, 0)


def _recommendation(
    character: CharacterProgress,
    *,
    profit_per_injector: float,
) -> str:
    if character.estimated_injectors:
        return "Extract Now" if profit_per_injector > 0 else "Review Margin"
    if character.ready_state in {"QUEUE ENDED", "QUEUE BLOCKED", "PAUSED"}:
        return "Queue Blocked"
    days = character.days_to_next_injector
    if days is None:
        return "Review"
    if days <= 1:
        return "Wait 1 Day"
    if days <= 2:
        return "Wait 2 Days"
    if days <= 7:
        return f"Wait {ceil(days)} Days"
    return "Keep Training"
