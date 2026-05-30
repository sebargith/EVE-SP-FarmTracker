"""Scenario orchestration helpers used by the Streamlit UI."""

from __future__ import annotations

import pandas as pd

from src.calculations.assumptions import FarmAssumptions, with_market_overrides
from src.calculations.scenarios import (
    filter_profitable,
    generate_scenario_matrix,
    rank_scenarios,
)


def scenario_matrix_for_market(
    base_assumptions: FarmAssumptions,
    *,
    plex_cost_basis_isk: float,
    large_skill_injector_sell_price_isk: float,
    skill_extractor_market_buy_price_isk: float,
    mct_market_buy_price_isk: float,
    lsi_market_fee_tax_rate: float,
) -> pd.DataFrame:
    """Generate a scenario matrix from base assumptions and market overrides."""

    assumptions = with_market_overrides(
        base_assumptions,
        plex_cost_basis_isk=plex_cost_basis_isk,
        large_skill_injector_sell_price_isk=large_skill_injector_sell_price_isk,
        skill_extractor_market_buy_price_isk=skill_extractor_market_buy_price_isk,
        mct_market_buy_price_isk=mct_market_buy_price_isk,
        lsi_market_fee_tax_rate=lsi_market_fee_tax_rate,
    )
    return generate_scenario_matrix(assumptions)


def ranked_scenarios(df: pd.DataFrame) -> pd.DataFrame:
    """Return scenarios ranked by the app's default profitability sort."""

    return rank_scenarios(df)


def profitable_scenarios(df: pd.DataFrame) -> pd.DataFrame:
    """Return profitable scenarios under current assumptions."""

    return filter_profitable(df)


def best_scenario(df: pd.DataFrame) -> pd.Series:
    """Return the best-ranked scenario row."""

    return ranked_scenarios(df).iloc[0]


def baseline_monthly_profit(df: pd.DataFrame, scenario_id: int = 1) -> float:
    """Return baseline monthly profit for comparison, or zero if filtered out."""

    baseline = df[df["ID"] == scenario_id]
    if baseline.empty:
        return 0.0
    return float(baseline.iloc[0]["Profit / Calendar Month ISK"])


def lsi_price_sensitivity(row: pd.Series) -> pd.DataFrame:
    """Calculate monthly profit sensitivity to LSI sell price for one scenario."""

    injectors = float(row["Injectors Produced"])
    months = int(row["Omega Months"])
    gross_revenue = float(row["LSI Gross Revenue"])
    net_revenue = float(row["LSI Net Revenue"])
    total_cost = float(row["Total Cost ISK"])
    current_lsi_price = gross_revenue / injectors
    net_rate = net_revenue / gross_revenue
    factors = (0.75, 0.85, 0.95, 1.0, 1.05, 1.15, 1.25)

    return pd.DataFrame(
        {
            "LSI Price": [current_lsi_price * factor for factor in factors],
            "Profit / Month": [
                (injectors * current_lsi_price * factor * net_rate - total_cost) / months
                for factor in factors
            ],
        }
    )


def extractor_cost_sensitivity(row: pd.Series) -> pd.DataFrame:
    """Calculate monthly profit sensitivity to extractor unit cost for one scenario."""

    injectors = float(row["Injectors Produced"])
    months = int(row["Omega Months"])
    training_cost = float(row["Training Cost ISK"])
    net_revenue = float(row["LSI Net Revenue"])
    current_unit_cost = float(row["Extractor Cost ISK"]) / injectors
    factors = (0.7, 0.85, 1.0, 1.15, 1.3)

    return pd.DataFrame(
        {
            "Extractor Cost": [current_unit_cost * factor for factor in factors],
            "Profit / Month": [
                (net_revenue - training_cost - injectors * current_unit_cost * factor)
                / months
                for factor in factors
            ],
        }
    )
