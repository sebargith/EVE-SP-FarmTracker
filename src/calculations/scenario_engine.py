"""Domain scenario evaluator."""

from __future__ import annotations

from math import floor

from src.calculations.assumptions import FarmAssumptions
from src.calculations.break_even import break_even_lsi_price
from src.calculations.profitability import (
    calculate_extractor_cost,
    calculate_lsi_revenue,
    calculate_profit,
    calculate_training_cost,
    profit_per_month,
)
from src.calculations.sp_training import injectors_from_sp
from src.domain.scenarios import ScenarioInput, ScenarioResult, TrainingPlanResult


def evaluate_scenario(
    scenario: ScenarioInput,
    assumptions: FarmAssumptions,
) -> ScenarioResult:
    """Evaluate one scenario into a domain result."""

    market = assumptions.market
    training_assumptions = assumptions.training

    mct_plex_total = (
        scenario.omega_months
        * (scenario.queue_count - 1)
        * scenario.mct_unit_plex
    )
    mct_market_isk_total = (
        scenario.omega_months
        * (scenario.queue_count - 1)
        * scenario.mct_market_unit_isk
    )
    training_plex_total = (
        scenario.omega_plex_total + mct_plex_total + scenario.bundle_plex_total
    )
    training_cost_isk = calculate_training_cost(
        training_plex_total * market.plex_cost_basis_isk,
        mct_market_isk_total,
    )

    queue_months = scenario.omega_months * scenario.queue_count
    training_sp = queue_months * training_assumptions.optimized_sp_per_month_per_queue
    total_sp = training_sp + scenario.bonus_sp
    injectors = injectors_from_sp(
        total_sp,
        training_assumptions.sp_per_large_skill_injector,
    )
    full_injectors = floor(injectors)
    remainder_sp = (
        total_sp
        - full_injectors * training_assumptions.sp_per_large_skill_injector
    )
    training = TrainingPlanResult(
        queue_months=queue_months,
        training_sp=training_sp,
        bonus_sp=scenario.bonus_sp,
        total_sp=total_sp,
        injectors_produced=injectors,
        full_injectors=full_injectors,
        remainder_sp=remainder_sp,
    )

    extractor_unit_cost_isk = (
        scenario.extractor_unit_plex * market.plex_cost_basis_isk
        + scenario.extractor_unit_isk
    )
    extractor_cost_isk = calculate_extractor_cost(injectors, extractor_unit_cost_isk)

    lsi_gross_revenue = (
        injectors * market.large_skill_injector_sell_price_isk
    )
    lsi_net_revenue = calculate_lsi_revenue(
        injectors,
        market.large_skill_injector_sell_price_isk,
        market.lsi_market_fee_tax_rate,
    )
    market_fees = lsi_gross_revenue - lsi_net_revenue
    total_cost_isk = training_cost_isk + extractor_cost_isk
    profit_isk = calculate_profit(lsi_net_revenue, total_cost_isk)
    profit_per_calendar_month_isk = profit_per_month(
        profit_isk,
        scenario.omega_months,
    )
    profit_per_queue_month_isk = (
        profit_isk / queue_months if queue_months else 0
    )
    break_even_price = break_even_lsi_price(
        total_cost_isk,
        injectors,
        market.lsi_market_fee_tax_rate,
    )

    return ScenarioResult(
        scenario_input=scenario,
        mct_plex_total=mct_plex_total,
        mct_market_isk_total=mct_market_isk_total,
        training_plex_total=training_plex_total,
        training_cost_isk=training_cost_isk,
        training=training,
        extractor_unit_cost_isk=extractor_unit_cost_isk,
        extractor_cost_isk=extractor_cost_isk,
        lsi_gross_revenue=lsi_gross_revenue,
        market_fees=market_fees,
        lsi_net_revenue=lsi_net_revenue,
        total_cost_isk=total_cost_isk,
        profit_isk=profit_isk,
        profit_per_calendar_month_isk=profit_per_calendar_month_isk,
        profit_per_queue_month_isk=profit_per_queue_month_isk,
        break_even_lsi_sell_price=break_even_price,
        status="PROFIT" if profit_isk > 0 else "LOSS",
    )
