"""Charts for account and character progression views."""

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.charts.profitability_charts import style_chart


def extractable_sp_by_group_chart(progress_df: pd.DataFrame) -> go.Figure:
    """Build extractable SP by account group chart."""

    grouped = (
        progress_df.groupby("group_name", as_index=False)["extractable_sp"]
        .sum()
        .sort_values("extractable_sp", ascending=False)
    )
    fig = px.bar(
        grouped,
        x="group_name",
        y="extractable_sp",
        color="extractable_sp",
        color_continuous_scale=["#0E7490", "#22C55E"],
        labels={"group_name": "Account Group", "extractable_sp": "Extractable SP"},
    )
    return style_chart(fig)


def readiness_chart(progress_df: pd.DataFrame) -> go.Figure:
    """Build character readiness count chart."""

    grouped = (
        progress_df.groupby("ready_state", as_index=False)["character_id"]
        .count()
        .rename(columns={"character_id": "characters"})
    )
    fig = px.bar(
        grouped,
        x="ready_state",
        y="characters",
        color="ready_state",
        color_discrete_map={
            "READY": "#22C55E",
            "TRAINING": "#06B6D4",
            "QUEUE BLOCKED": "#F59E0B",
            "QUEUE ENDED": "#EF4444",
            "PAUSED": "#94A3B8",
        },
        labels={"ready_state": "Readiness", "characters": "Characters"},
    )
    return style_chart(fig)


def projected_sp_by_group_chart(sp_tracking_df: pd.DataFrame) -> go.Figure:
    """Build projected SP by account group chart."""

    grouped = (
        sp_tracking_df.groupby("Group", as_index=False)["Projected SP"]
        .sum()
        .sort_values("Projected SP", ascending=False)
    )
    fig = px.bar(
        grouped,
        x="Group",
        y="Projected SP",
        color="Projected SP",
        color_continuous_scale=["#155E75", "#22D3EE"],
        labels={"Group": "Account Group", "Projected SP": "Projected SP"},
    )
    return style_chart(fig)


def queue_health_chart(sp_tracking_df: pd.DataFrame) -> go.Figure:
    """Build queue health count chart."""

    grouped = (
        sp_tracking_df.groupby("Queue Status", as_index=False)["Character"]
        .count()
        .rename(columns={"Character": "Characters"})
    )
    fig = px.bar(
        grouped,
        x="Queue Status",
        y="Characters",
        color="Queue Status",
        color_discrete_map={
            "TRAINING": "#06B6D4",
            "ENDS SOON": "#F59E0B",
            "QUEUE ENDED": "#EF4444",
            "PAUSED": "#94A3B8",
            "NO QUEUE": "#A855F7",
        },
        labels={"Queue Status": "Queue Status", "Characters": "Characters"},
    )
    return style_chart(fig)


def sp_velocity_chart(analytics_df: pd.DataFrame) -> go.Figure:
    """Build observed vs expected SP/day chart by character."""

    if analytics_df.empty:
        return style_chart(go.Figure())

    display = analytics_df.copy()
    display["7D Observed SP/day"] = display["7D Observed SP/day"].fillna(0)
    display["7D Expected SP/day"] = display["7D Expected SP/day"].fillna(0)
    display["Label"] = display["Account"] + " / " + display["Character"]
    display = display.sort_values("7D Observed SP/day", ascending=False)
    fig = go.Figure()
    fig.add_bar(
        x=display["Label"],
        y=display["7D Observed SP/day"],
        name="7D Observed",
        marker_color="#22D3EE",
    )
    fig.add_bar(
        x=display["Label"],
        y=display["7D Expected SP/day"],
        name="Expected",
        marker_color="#64748B",
        opacity=0.65,
    )
    fig.update_layout(
        barmode="group",
        xaxis_title="Character",
        yaxis_title="SP/day",
    )
    return style_chart(fig)


def sp_snapshot_history_chart(history_df: pd.DataFrame) -> go.Figure:
    """Build SP snapshot history chart for one character."""

    fig = px.line(
        history_df,
        x="timestamp",
        y="total_sp",
        color="source",
        markers=True,
        labels={"timestamp": "Snapshot Time", "total_sp": "Total SP", "source": "Source"},
    )
    return style_chart(fig)
