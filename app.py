from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.calculations.assumptions import (
    DEFAULT_ASSUMPTIONS_PATH,
    FarmAssumptions,
    load_assumptions,
)
from src.data.database import ensure_database
from src.services.market_service import latest_market_scenario_overrides
from src.services.scenario_service import scenario_matrix_for_market
from src.ui.character_pages import characters_page, farm_extraction_page
from src.ui.components import app_header
from src.ui.market_pages import market_page
from src.ui.scenario_pages import break_even, command_center, scenario_matrix
from src.ui.sidebar import filter_frame, sidebar_assumptions, sidebar_navigation
from src.ui.theme import inject_theme


st.set_page_config(page_title="EVE SP Farm Planner", layout="wide")


@st.cache_data(show_spinner=False)
def base_assumptions(path: str, modified_ns: int) -> FarmAssumptions:
    return load_assumptions(path)


def current_assumptions() -> FarmAssumptions:
    path = Path(DEFAULT_ASSUMPTIONS_PATH)
    return base_assumptions(str(path), path.stat().st_mtime_ns)


@st.cache_resource(show_spinner=False)
def database_connection():
    return ensure_database()


@st.cache_data(show_spinner=False)
def scenario_data(
    assumptions_modified_ns: int,
    plex_cost_basis_isk: float,
    large_skill_injector_sell_price_isk: float,
    skill_extractor_market_buy_price_isk: float,
    mct_market_buy_price_isk: float,
    lsi_market_fee_tax_rate: float,
) -> pd.DataFrame:
    _ = assumptions_modified_ns
    return scenario_matrix_for_market(
        current_assumptions(),
        plex_cost_basis_isk=plex_cost_basis_isk,
        large_skill_injector_sell_price_isk=large_skill_injector_sell_price_isk,
        skill_extractor_market_buy_price_isk=skill_extractor_market_buy_price_isk,
        mct_market_buy_price_isk=mct_market_buy_price_isk,
        lsi_market_fee_tax_rate=lsi_market_fee_tax_rate,
    )


def main() -> None:
    inject_theme()

    connection = database_connection()
    market_overrides = latest_market_scenario_overrides(connection)
    active_view = sidebar_navigation()
    assumptions = sidebar_assumptions(
        current_assumptions(),
        market_overrides=market_overrides,
    )
    df = scenario_data(
        Path(DEFAULT_ASSUMPTIONS_PATH).stat().st_mtime_ns,
        assumptions.market.plex_cost_basis_isk,
        assumptions.market.large_skill_injector_sell_price_isk,
        assumptions.market.skill_extractor_market_buy_price_isk,
        assumptions.market.mct_market_buy_price_isk,
        assumptions.market.lsi_market_fee_tax_rate,
    )
    filtered = filter_frame(df)

    app_header(
        active_view=active_view,
        scenario_set=st.session_state.get("active_scenario_set_name", "Scenario Set"),
        last_updated=market_overrides.timestamp,
    )

    if filtered.empty:
        st.warning("No scenarios match the current filters.")
        return

    if active_view == "SP Overview":
        characters_page(connection, assumptions.training)
    elif active_view == "Farm / Extraction":
        farm_extraction_page(connection, assumptions.training)
    elif active_view == "Market":
        market_page(connection)
    elif active_view == "Command Center":
        command_center(filtered)
    elif active_view == "Scenario Matrix":
        scenario_matrix(filtered)
    elif active_view == "Break-even":
        break_even(filtered)


if __name__ == "__main__":
    main()
