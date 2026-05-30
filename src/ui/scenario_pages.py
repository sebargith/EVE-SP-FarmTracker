"""Streamlit page sections for scenario views."""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st

from src.charts.profitability_charts import (
    extractor_sensitivity_chart,
    lsi_sensitivity_chart,
    profit_by_scenario_type_chart,
    top_scenarios_chart,
)
from src.services.scenario_service import (
    baseline_monthly_profit,
    best_scenario,
    extractor_cost_sensitivity,
    lsi_price_sensitivity,
    profitable_scenarios,
    ranked_scenarios,
)
from src.ui.components import detail_panel, metric_card, scenario_table, section_header, status_badge
from src.ui.formatting import format_isk, format_number, metric_delta


def command_center(df: pd.DataFrame) -> None:
    """Render the scenario-focused command center tab."""

    ranked = ranked_scenarios(df)
    profitable = profitable_scenarios(df)
    best = best_scenario(df)
    vs_baseline = best["Profit / Calendar Month ISK"] - baseline_monthly_profit(df)

    section_header(
        "Profit Command Center",
        "Scenario results under the active assumptions and filters.",
    )
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        metric_card("Scenarios", f"{len(df):,}", "currently in filter", icon="ALL")
    with c2:
        metric_card(
            "Profitable",
            f"{len(profitable):,}",
            f"{len(profitable) / len(df):.1%} of shown",
            tone="success" if len(profitable) else "danger",
            icon="PRF",
        )
    with c3:
        metric_card(
            "Best Profit",
            format_isk(best["Profit ISK"]),
            metric_delta(best["Profit ISK"]),
            tone="success" if best["Profit ISK"] > 0 else "danger",
            icon="ISK",
        )
    with c4:
        metric_card(
            "Best / Month",
            format_isk(best["Profit / Calendar Month ISK"]),
            f"{format_isk(vs_baseline)} vs baseline",
            tone="success" if best["Profit / Calendar Month ISK"] > 0 else "danger",
            icon="MON",
        )
    with c5:
        metric_card(
            "Best Scenario",
            f"#{int(best['ID'])}",
            f"{int(best['Queues'])} queue(s)",
            tone="success" if best["Status"] == "PROFIT" else "danger",
            icon="TOP",
        )

    left, right = st.columns([1.3, 1])
    with left:
        section_header("Top Scenarios", "Ranked by profit per calendar month.")
        st.plotly_chart(
            top_scenarios_chart(ranked),
            width="stretch",
            key="top_scenarios_chart",
        )

    with right:
        section_header("Current Best", "Highest monthly profit in the filtered set.")
        _best_scenario_panel(best)

    chart_left, chart_right = st.columns(2)
    with chart_left:
        section_header("Profit By Scenario Type")
        st.plotly_chart(
            profit_by_scenario_type_chart(df),
            width="stretch",
            key="profit_by_type_chart",
        )

    with chart_right:
        section_header("Top Scenario Sensitivity")
        st.plotly_chart(
            lsi_sensitivity_chart(lsi_price_sensitivity(best)),
            width="stretch",
            key="overview_lsi_sensitivity_chart",
        )

    st.markdown(
        """
        <div class="eve-note">
            Baseline single-queue farming is usually unprofitable. Treat green
            scenarios as profitable under the current assumptions, not as safe
            guarantees.
        </div>
        """,
        unsafe_allow_html=True,
    )


def scenario_matrix(df: pd.DataFrame) -> None:
    """Render the scenario matrix tab."""

    ranked = ranked_scenarios(df)
    profitable = profitable_scenarios(ranked)
    section_header(
        "Scenario Matrix",
        "Audit table for all filtered profitability combinations.",
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Rows", f"{len(ranked):,}", "filtered scenarios", icon="ROW")
    with c2:
        metric_card(
            "Profitable",
            f"{len(profitable):,}",
            f"{len(profitable) / len(ranked):.1%} of rows",
            tone="success" if len(profitable) else "danger",
            icon="PRF",
        )
    with c3:
        metric_card(
            "Best / Month",
            format_isk(ranked.iloc[0]["Profit / Calendar Month ISK"]),
            f"scenario #{int(ranked.iloc[0]['ID'])}",
            tone="success" if ranked.iloc[0]["Profit / Calendar Month ISK"] > 0 else "danger",
            icon="MON",
        )
    with c4:
        st.download_button(
            "Download CSV",
            data=ranked.to_csv(index=False).encode("utf-8"),
            file_name="eve_sp_farm_scenario_matrix.csv",
            mime="text/csv",
            width="stretch",
        )
    scenario_table(ranked)


def break_even(df: pd.DataFrame) -> None:
    """Render the break-even tab."""

    ranked = ranked_scenarios(df)
    best = ranked.iloc[0]

    section_header(
        "Break-even Monitor",
        "How far current assumptions can move before the best scenario stops working.",
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card("Best Scenario", f"#{int(best['ID'])}", best["Status"], icon="TOP")
    with c2:
        metric_card("Break-even LSI", format_isk(best["Break-even LSI Sell Price"]), "net of fees", icon="LSI")
    with c3:
        metric_card(
            "Profit / Month",
            format_isk(best["Profit / Calendar Month ISK"]),
            metric_delta(best["Profit / Calendar Month ISK"]),
            tone="success" if best["Profit / Calendar Month ISK"] > 0 else "danger",
            icon="MON",
        )
    with c4:
        metric_card(
            "Extractor Unit",
            format_isk(best["Extractor Cost ISK"] / best["Injectors Produced"]),
            "effective cost",
            icon="EXT",
        )

    left, right = st.columns(2)
    with left:
        section_header("LSI Price Sensitivity")
        st.plotly_chart(
            lsi_sensitivity_chart(lsi_price_sensitivity(best)),
            width="stretch",
            key="break_even_lsi_sensitivity_chart",
        )

    with right:
        section_header("Extractor Cost Sensitivity")
        st.plotly_chart(
            extractor_sensitivity_chart(extractor_cost_sensitivity(best)),
            width="stretch",
            key="break_even_extractor_sensitivity_chart",
        )

    section_header("Top Break-even Rows", "Best scenarios sorted by monthly profit.")
    scenario_table(ranked.head(20))


def _best_scenario_panel(best: pd.Series) -> None:
    tone = "success" if best["Status"] == "PROFIT" else "danger"
    detail_panel(
        f"Scenario {int(best['ID'])}",
        [
            ("Omega", str(best["Training / Omega Offer"])),
            ("Queues", f"{int(best['Queues'])}"),
            ("MCT", str(best["MCT Source"])),
            ("Extractor", str(best["Extractor Source"])),
            ("Injectors", format_number(best["Injectors Produced"])),
            ("Total cost", format_isk(best["Total Cost ISK"])),
            ("Net revenue", format_isk(best["LSI Net Revenue"])),
            ("Break-even LSI", format_isk(best["Break-even LSI Sell Price"])),
        ],
        badge=str(best["Status"]),
        badge_tone=tone,
    )

    notes = escape(str(best["Notes"]))
    st.markdown(
        f"""
        <div class="eve-note" style="margin-top: 0.65rem;">
            {status_badge("ASSUMPTION BOUND", tone="warning")}
            <div style="margin-top: 0.45rem;">{notes}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
