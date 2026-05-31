"""Sidebar controls for Streamlit views."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.calculations.assumptions import (
    FarmAssumptions,
    apply_scenario_preset,
    with_market_overrides,
)
from src.services.market_service import MarketScenarioOverrides
from src.ui.formatting import format_isk


APP_VIEWS = (
    "SP Overview",
    "Farm / Extraction",
    "Loot Tracker",
    "Market",
    "Command Center",
    "Scenario Matrix",
    "Break-even",
)


def sidebar_navigation() -> str:
    """Render the app navigation rail and return the active view."""

    with st.sidebar:
        st.markdown(
            """
            <div class="eve-sidebar-brand">
                <div class="eve-sidebar-brand-title">EVE SP Farm Planner</div>
                <div class="eve-sidebar-brand-subtitle">Local SP operations dashboard</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="eve-sidebar-section-title">Navigation</div>',
            unsafe_allow_html=True,
        )
        active_view = st.radio(
            "Navigation",
            APP_VIEWS,
            index=0,
            label_visibility="collapsed",
            key="eve_active_view",
        )
        st.markdown('<div class="eve-sidebar-divider"></div>', unsafe_allow_html=True)

    return active_view


def sidebar_assumptions(
    assumptions: FarmAssumptions,
    market_overrides: MarketScenarioOverrides | None = None,
) -> FarmAssumptions:
    """Render scenario preset and market assumption controls."""

    with st.sidebar:
        st.markdown(
            '<div class="eve-sidebar-section-title">Scenario Set</div>',
            unsafe_allow_html=True,
        )
        presets = assumptions.scenario_presets
        preset_names = [preset.name for preset in presets]
        selected_name = st.selectbox("Active preset", preset_names, index=0)
        selected_preset = presets[preset_names.index(selected_name)]
        st.session_state["active_scenario_set_name"] = selected_name
        st.caption(selected_preset.description)

        assumptions = apply_scenario_preset(assumptions, selected_preset.key)

        st.markdown(
            '<div class="eve-sidebar-section-title">Market Assumptions</div>',
            unsafe_allow_html=True,
        )
        use_market_prices = False
        if market_overrides and market_overrides.has_any_price:
            use_market_prices = st.checkbox(
                "Use latest market prices",
                value=False,
                help=(
                    "Use latest saved public ESI prices for PLEX, LSI, and "
                    "Skill Extractors. MCT remains manual."
                ),
            )
            if use_market_prices:
                st.caption(f"Market data: {market_overrides.timestamp or 'unknown time'}")
                st.caption(market_overrides.source_summary)
        else:
            st.caption("No synced market prices yet. Use the Market tab to sync them.")

        starting_plex_basis = int(
            market_overrides.plex_cost_basis_isk
            if use_market_prices and market_overrides and market_overrides.plex_cost_basis_isk
            else assumptions.market.plex_cost_basis_isk
        )
        starting_lsi_price = int(
            market_overrides.large_skill_injector_sell_price_isk
            if (
                use_market_prices
                and market_overrides
                and market_overrides.large_skill_injector_sell_price_isk
            )
            else assumptions.market.large_skill_injector_sell_price_isk
        )
        starting_extractor_price = int(
            market_overrides.skill_extractor_market_buy_price_isk
            if (
                use_market_prices
                and market_overrides
                and market_overrides.skill_extractor_market_buy_price_isk
            )
            else assumptions.market.skill_extractor_market_buy_price_isk
        )
        market_key = (
            f"market_{market_overrides.timestamp}"
            if use_market_prices and market_overrides
            else "manual"
        )

        plex_basis = st.number_input(
            "PLEX basis (ISK / PLEX)",
            min_value=0,
            value=starting_plex_basis,
            step=100_000,
            format="%d",
            key=f"{selected_preset.key}_{market_key}_plex_basis",
        )
        lsi_price = st.number_input(
            "LSI sell price (ISK)",
            min_value=0,
            value=starting_lsi_price,
            step=10_000_000,
            format="%d",
            key=f"{selected_preset.key}_{market_key}_lsi_price",
        )
        extractor_price = st.number_input(
            "Market extractor buy (ISK)",
            min_value=0,
            value=starting_extractor_price,
            step=10_000_000,
            format="%d",
            key=f"{selected_preset.key}_{market_key}_extractor_price",
        )
        mct_price = st.number_input(
            "Market MCT buy (ISK)",
            min_value=0,
            value=int(assumptions.market.mct_market_buy_price_isk),
            step=50_000_000,
            format="%d",
            key=f"{selected_preset.key}_mct_price",
        )
        fee_rate_pct = st.number_input(
            "LSI sales fees/taxes (%)",
            min_value=0.0,
            max_value=99.0,
            value=assumptions.market.lsi_market_fee_tax_rate * 100,
            step=0.25,
            format="%.2f",
            key=f"{selected_preset.key}_fee_rate",
        )
        if use_market_prices:
            st.caption(
                "Applied market inputs: "
                f"PLEX {format_isk(plex_basis)}, "
                f"LSI {format_isk(lsi_price)}, "
                f"Extractor {format_isk(extractor_price)}."
            )

    return with_market_overrides(
        assumptions,
        plex_cost_basis_isk=plex_basis,
        large_skill_injector_sell_price_isk=lsi_price,
        skill_extractor_market_buy_price_isk=extractor_price,
        mct_market_buy_price_isk=mct_price,
        lsi_market_fee_tax_rate=fee_rate_pct / 100,
    )


def filter_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Render scenario filters and return the filtered matrix."""

    with st.sidebar:
        st.markdown(
            '<div class="eve-sidebar-section-title">Scenario Filters</div>',
            unsafe_allow_html=True,
        )
        statuses = sorted(df["Status"].unique())
        selected_statuses = st.multiselect("Status", statuses, default=statuses)

        queue_options = sorted(df["Queues"].unique())
        selected_queues = st.multiselect("Queues", queue_options, default=queue_options)

        omega_options = sorted(df["Training / Omega Offer"].unique())
        selected_omega = st.multiselect("Omega plan", omega_options, default=omega_options)

        mct_options = sorted(df["MCT Source"].unique())
        selected_mct = st.multiselect("MCT source", mct_options, default=mct_options)

        extractor_options = sorted(df["Extractor Source"].unique())
        selected_extractors = st.multiselect(
            "Extractor source",
            extractor_options,
            default=extractor_options,
        )

    return df[
        df["Status"].isin(selected_statuses)
        & df["Queues"].isin(selected_queues)
        & df["Training / Omega Offer"].isin(selected_omega)
        & df["MCT Source"].isin(selected_mct)
        & df["Extractor Source"].isin(selected_extractors)
    ].copy()
