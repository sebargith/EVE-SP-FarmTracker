"""Extraction recommendations and realized event logging."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from math import ceil

from src.calculations.assumptions import FarmAssumptions
from src.calculations.profitability import calculate_extractor_cost, calculate_lsi_revenue
from src.data.repositories import record_extraction_event
from src.services.character_service import CharacterProgress, list_character_progress


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
) -> int:
    """Record a completed extraction and update the local SP baseline."""

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
        notes=notes,
        timestamp=current_time.isoformat(),
    )


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
