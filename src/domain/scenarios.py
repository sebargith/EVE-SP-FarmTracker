"""Domain-level scenario inputs and outputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioInput:
    """Inputs required to evaluate one SP farm scenario."""

    scenario_id: int
    scenario_type: str
    training_offer: str
    omega_months: int
    queue_count: int
    mct_source: str
    extractor_source: str
    omega_plex_total: float
    mct_unit_plex: float
    mct_market_unit_isk: float
    bundle_plex_total: float
    bonus_sp: float
    extractor_unit_plex: float
    extractor_unit_isk: float
    notes: str


@dataclass(frozen=True)
class TrainingPlanResult:
    """Skill point output for a scenario's training plan."""

    queue_months: int
    training_sp: float
    bonus_sp: float
    total_sp: float
    injectors_produced: float
    full_injectors: int
    remainder_sp: float


@dataclass(frozen=True)
class ScenarioResult:
    """Fully evaluated scenario result, independent of any UI representation."""

    scenario_input: ScenarioInput
    mct_plex_total: float
    mct_market_isk_total: float
    training_plex_total: float
    training_cost_isk: float
    training: TrainingPlanResult
    extractor_unit_cost_isk: float
    extractor_cost_isk: float
    lsi_gross_revenue: float
    market_fees: float
    lsi_net_revenue: float
    total_cost_isk: float
    profit_isk: float
    profit_per_calendar_month_isk: float
    profit_per_queue_month_isk: float
    break_even_lsi_sell_price: float
    status: str
