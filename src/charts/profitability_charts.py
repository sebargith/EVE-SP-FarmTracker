"""Plotly chart builders for profitability views."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


STATUS_COLORS = {"PROFIT": "#22C55E", "LOSS": "#EF4444"}


def style_chart(fig: go.Figure) -> go.Figure:
    """Apply the app's dark dashboard chart styling."""

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(2, 8, 23, 0.35)",
        font=dict(color="#CBD5E1"),
        margin=dict(l=10, r=20, t=28, b=10),
        legend_title_text="",
        xaxis=dict(gridcolor="rgba(148, 163, 184, 0.18)", zerolinecolor="#94A3B8"),
        yaxis=dict(gridcolor="rgba(148, 163, 184, 0.18)", zerolinecolor="#94A3B8"),
    )
    return fig


def top_scenarios_chart(ranked: pd.DataFrame, limit: int = 12) -> go.Figure:
    """Build a horizontal bar chart of top scenarios by profit/month."""

    top = ranked.head(limit).copy()
    top["Scenario"] = top["ID"].astype(str) + " - " + top["Training / Omega Offer"]
    fig = px.bar(
        top,
        x="Profit / Calendar Month ISK",
        y="Scenario",
        color="Status",
        color_discrete_map=STATUS_COLORS,
        orientation="h",
        labels={"Profit / Calendar Month ISK": "Profit / Month", "Scenario": ""},
    )
    fig.update_layout(height=460, yaxis=dict(autorange="reversed"))
    return style_chart(fig)


def profit_by_scenario_type_chart(df: pd.DataFrame) -> go.Figure:
    """Build a chart of best monthly profit by scenario type."""

    grouped = (
        df.groupby("Scenario Type", as_index=False)["Profit / Calendar Month ISK"]
        .max()
        .sort_values("Profit / Calendar Month ISK", ascending=False)
    )
    fig = px.bar(
        grouped,
        x="Scenario Type",
        y="Profit / Calendar Month ISK",
        color="Profit / Calendar Month ISK",
        color_continuous_scale=["#EF4444", "#F59E0B", "#22C55E"],
        labels={"Profit / Calendar Month ISK": "Best Profit / Month"},
    )
    return style_chart(fig)


def lsi_sensitivity_chart(sensitivity: pd.DataFrame) -> go.Figure:
    """Build LSI price sensitivity line chart."""

    fig = px.line(
        sensitivity,
        x="LSI Price",
        y="Profit / Month",
        markers=True,
        labels={"LSI Price": "LSI Sell Price", "Profit / Month": "Profit / Month"},
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#94A3B8")
    return style_chart(fig)


def extractor_sensitivity_chart(sensitivity: pd.DataFrame) -> go.Figure:
    """Build extractor cost sensitivity line chart."""

    fig = px.line(
        sensitivity,
        x="Extractor Cost",
        y="Profit / Month",
        markers=True,
        labels={
            "Extractor Cost": "Extractor Unit Cost",
            "Profit / Month": "Profit / Month",
        },
    )
    fig.add_hline(y=0, line_dash="dash", line_color="#94A3B8")
    return style_chart(fig)
