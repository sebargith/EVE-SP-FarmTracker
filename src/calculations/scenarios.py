"""Scenario matrix generation."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from src.calculations.assumptions import (
    FarmAssumptions,
    MctSource,
    TrainingPlan,
    coerce_assumptions,
)
from src.calculations.scenario_engine import evaluate_scenario
from src.domain.scenarios import ScenarioInput, ScenarioResult


WORKBOOK_COLUMNS = [
    "ID",
    "Scenario Type",
    "Training / Omega Offer",
    "Omega Months",
    "Queues",
    "MCT Source",
    "Extractor Source",
    "Omega PLEX Total",
    "MCT Unit PLEX",
    "MCT Market Unit ISK",
    "MCT PLEX Total",
    "MCT Market ISK Total",
    "Bundle PLEX Total",
    "Training PLEX Total",
    "Training Cost ISK",
    "Queue-Months",
    "Training SP",
    "Bonus SP",
    "Total SP",
    "Injectors Produced",
    "Full Injectors",
    "Remainder SP",
    "Extractor Unit PLEX",
    "Extractor Unit ISK",
    "Extractor Cost ISK",
    "LSI Gross Revenue",
    "Market Fees",
    "LSI Net Revenue",
    "Total Cost ISK",
    "Profit ISK",
    "Profit / Calendar Month ISK",
    "Profit / Queue-Month ISK",
    "Break-even LSI Sell Price",
    "Status",
    "Notes",
]


def generate_scenario_matrix(
    assumptions: FarmAssumptions | Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """Generate the full workbook-equivalent scenario matrix."""

    farm = coerce_assumptions(assumptions)
    rows: list[dict[str, Any]] = []
    scenario_id = 1

    for plan in farm.omega_plans:
        for row in _regular_plan_rows(scenario_id, plan, farm):
            rows.append(row)
            scenario_id += 1

    for plan in farm.omega_mct_bundle_plans:
        for extractor in farm.extractor_sources:
            rows.append(
                _build_row(
                    scenario_id=scenario_id,
                    plan=plan,
                    queue_count=3,
                    mct_source=farm.included_bundle_mct_source,
                    extractor_source=extractor,
                    assumptions=farm,
                )
            )
            scenario_id += 1

    return pd.DataFrame(rows, columns=WORKBOOK_COLUMNS)


def rank_scenarios(df: pd.DataFrame) -> pd.DataFrame:
    """Rank scenarios by total profit, then calendar-month profit."""

    return df.sort_values(
        ["Profit ISK", "Profit / Calendar Month ISK"],
        ascending=[False, False],
        kind="mergesort",
    ).reset_index(drop=True)


def filter_profitable(df: pd.DataFrame) -> pd.DataFrame:
    """Return only scenarios with positive profit."""

    return df[df["Profit ISK"] > 0].reset_index(drop=True)


def _regular_plan_rows(
    starting_id: int,
    plan: TrainingPlan,
    assumptions: FarmAssumptions,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scenario_id = starting_id

    for extractor in assumptions.extractor_sources:
        rows.append(
            _build_row(
                scenario_id=scenario_id,
                plan=plan,
                queue_count=1,
                mct_source=assumptions.no_mct_source,
                extractor_source=extractor,
                assumptions=assumptions,
            )
        )
        scenario_id += 1

    for queue_count in (2, 3):
        for mct_source in assumptions.regular_mct_sources:
            for extractor in assumptions.extractor_sources:
                rows.append(
                    _build_row(
                        scenario_id=scenario_id,
                        plan=plan,
                        queue_count=queue_count,
                        mct_source=mct_source,
                        extractor_source=extractor,
                        assumptions=assumptions,
                    )
                )
                scenario_id += 1

    return rows


def _build_row(
    scenario_id: int,
    plan: TrainingPlan,
    queue_count: int,
    mct_source: MctSource,
    extractor_source: Any,
    assumptions: FarmAssumptions,
) -> dict[str, Any]:
    scenario = ScenarioInput(
        scenario_id=scenario_id,
        scenario_type=plan.scenario_type,
        training_offer=plan.name,
        omega_months=plan.months,
        queue_count=queue_count,
        mct_source=mct_source.name,
        extractor_source=extractor_source.name,
        omega_plex_total=plan.omega_plex_total,
        mct_unit_plex=mct_source.unit_plex,
        mct_market_unit_isk=mct_source.unit_isk,
        bundle_plex_total=plan.bundle_plex_total,
        bonus_sp=plan.bonus_sp,
        extractor_unit_plex=extractor_source.unit_plex,
        extractor_unit_isk=extractor_source.unit_isk,
        notes=_notes(plan, queue_count, mct_source, extractor_source),
    )
    return _result_to_workbook_row(evaluate_scenario(scenario, assumptions))


def _result_to_workbook_row(result: ScenarioResult) -> dict[str, Any]:
    scenario = result.scenario_input
    training = result.training

    return {
        "ID": scenario.scenario_id,
        "Scenario Type": scenario.scenario_type,
        "Training / Omega Offer": scenario.training_offer,
        "Omega Months": scenario.omega_months,
        "Queues": scenario.queue_count,
        "MCT Source": scenario.mct_source,
        "Extractor Source": scenario.extractor_source,
        "Omega PLEX Total": scenario.omega_plex_total,
        "MCT Unit PLEX": scenario.mct_unit_plex,
        "MCT Market Unit ISK": scenario.mct_market_unit_isk,
        "MCT PLEX Total": result.mct_plex_total,
        "MCT Market ISK Total": result.mct_market_isk_total,
        "Bundle PLEX Total": scenario.bundle_plex_total,
        "Training PLEX Total": result.training_plex_total,
        "Training Cost ISK": result.training_cost_isk,
        "Queue-Months": training.queue_months,
        "Training SP": training.training_sp,
        "Bonus SP": training.bonus_sp,
        "Total SP": training.total_sp,
        "Injectors Produced": training.injectors_produced,
        "Full Injectors": training.full_injectors,
        "Remainder SP": training.remainder_sp,
        "Extractor Unit PLEX": scenario.extractor_unit_plex,
        "Extractor Unit ISK": scenario.extractor_unit_isk,
        "Extractor Cost ISK": result.extractor_cost_isk,
        "LSI Gross Revenue": result.lsi_gross_revenue,
        "Market Fees": result.market_fees,
        "LSI Net Revenue": result.lsi_net_revenue,
        "Total Cost ISK": result.total_cost_isk,
        "Profit ISK": result.profit_isk,
        "Profit / Calendar Month ISK": result.profit_per_calendar_month_isk,
        "Profit / Queue-Month ISK": result.profit_per_queue_month_isk,
        "Break-even LSI Sell Price": result.break_even_lsi_sell_price,
        "Status": result.status,
        "Notes": scenario.notes,
    }


def _notes(
    plan: TrainingPlan,
    queue_count: int,
    mct_source: MctSource,
    extractor_source: Any,
) -> str:
    parts = [plan.name]
    if queue_count == 1:
        parts.append("One training queue only")
    else:
        parts.append(mct_source.name)
    parts.append(extractor_source.name)
    return ". ".join(parts) + "."
