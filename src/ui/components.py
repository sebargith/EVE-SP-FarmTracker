"""Reusable Streamlit display components."""

from __future__ import annotations

from html import escape

import pandas as pd
import streamlit as st


def app_header(
    *,
    active_view: str,
    scenario_set: str,
    last_updated: str | None = None,
) -> None:
    """Render the application top bar."""

    updated_text = last_updated or "manual data"
    st.markdown(
        f"""
        <div class="eve-topbar">
            <div class="eve-topbar-left">
                <div class="eve-menu-mark">&#9776;</div>
                <div>
                    <div class="eve-app-title">EVE SP Farm Planner</div>
                    <div class="eve-app-subtitle">SP progression command center</div>
                </div>
            </div>
            <div class="eve-topbar-right">
                <span class="eve-top-pill">{escape(active_view)}</span>
                <span class="eve-top-pill">{escape(scenario_set)}</span>
                <span class="eve-updated">Last updated: {escape(updated_text)}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_header(title: str, subtitle: str | None = None) -> None:
    """Render a compact operational section heading."""

    subtitle_html = (
        f'<div class="eve-section-subtitle">{escape(subtitle)}</div>'
        if subtitle
        else ""
    )
    st.markdown(
        f"""
        <div class="eve-section-heading">
            <div class="eve-section-title">{escape(title)}</div>
            {subtitle_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def status_badge(label: str, *, tone: str = "neutral") -> str:
    """Return an inline status badge HTML fragment."""

    return f'<span class="eve-badge {escape(tone)}">{escape(label)}</span>'


def render_status_badge(label: str, *, tone: str = "neutral") -> None:
    """Render a standalone status badge."""

    st.markdown(status_badge(label, tone=tone), unsafe_allow_html=True)


def detail_panel(
    title: str,
    rows: list[tuple[str, str]],
    *,
    badge: str | None = None,
    badge_tone: str = "neutral",
) -> None:
    """Render a compact key/value detail panel."""

    badge_html = status_badge(badge, tone=badge_tone) if badge else ""
    row_html = "\n".join(
        f"""
        <div class="eve-detail-row">
            <span>{escape(label)}</span>
            <strong>{escape(value)}</strong>
        </div>
        """
        for label, value in rows
    )
    st.markdown(
        f"""
        <div class="eve-detail-panel">
            <div class="eve-detail-heading">
                <div>{escape(title)}</div>
                {badge_html}
            </div>
            <div class="eve-detail-body">
                {row_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def metric_card(
    label: str,
    value: str,
    delta: str,
    *,
    tone: str = "neutral",
    icon: str | None = None,
) -> None:
    """Render a dashboard metric tile."""

    icon_html = f'<div class="eve-kpi-icon">{escape(icon)}</div>' if icon else ""
    st.markdown(
        f"""
        <div class="eve-kpi {escape(tone)}">
            {icon_html}
            <div class="eve-kpi-copy">
                <div class="eve-kpi-label">{escape(label)}</div>
                <div class="eve-kpi-value">{escape(value)}</div>
                <div class="eve-kpi-delta">{escape(delta)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, delta: str, *, is_loss: bool = False) -> None:
    """Render a dashboard KPI tile."""

    metric_card(label, value, delta, tone="danger" if is_loss else "success")


def scenario_table(df: pd.DataFrame) -> None:
    """Render the standard scenario matrix subset."""

    table = df[
        [
            "ID",
            "Status",
            "Training / Omega Offer",
            "Omega Months",
            "Queues",
            "MCT Source",
            "Extractor Source",
            "Injectors Produced",
            "Total Cost ISK",
            "LSI Net Revenue",
            "Profit ISK",
            "Profit / Calendar Month ISK",
            "Break-even LSI Sell Price",
        ]
    ].copy()

    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "ID": st.column_config.NumberColumn("ID", format="%d"),
            "Omega Months": st.column_config.NumberColumn("Months", format="%d"),
            "Queues": st.column_config.NumberColumn("Queues", format="%d"),
            "Injectors Produced": st.column_config.NumberColumn(
                "Injectors",
                format="%.3f",
            ),
            "Total Cost ISK": st.column_config.NumberColumn(
                "Total Cost",
                format="%.0f ISK",
            ),
            "LSI Net Revenue": st.column_config.NumberColumn(
                "Net Revenue",
                format="%.0f ISK",
            ),
            "Profit ISK": st.column_config.NumberColumn(
                "Profit",
                format="%.0f ISK",
            ),
            "Profit / Calendar Month ISK": st.column_config.NumberColumn(
                "Profit / Month",
                format="%.0f ISK",
            ),
            "Break-even LSI Sell Price": st.column_config.NumberColumn(
                "Break-even LSI",
                format="%.0f ISK",
            ),
        },
    )


def character_progress_table(df: pd.DataFrame) -> None:
    """Render character progression rows."""

    table = df[
        [
            "group_name",
            "account_name",
            "character_name",
            "omega_status",
            "mct_slots",
            "projected_sp",
            "sp_above_floor",
            "extractable_sp",
            "estimated_injectors",
            "ready_state",
            "character_sync_status",
            "character_last_sync_at",
            "days_to_next_injector",
            "current_skill",
            "queue_ends_at",
        ]
    ].copy()

    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "group_name": "Group",
            "account_name": "Account",
            "character_name": "Character",
            "omega_status": "Omega",
            "mct_slots": st.column_config.NumberColumn("MCT", format="%d"),
            "projected_sp": st.column_config.NumberColumn("Projected SP", format="%d SP"),
            "sp_above_floor": st.column_config.NumberColumn("Above Floor", format="%d SP"),
            "extractable_sp": st.column_config.NumberColumn("Extractable", format="%d SP"),
            "estimated_injectors": st.column_config.NumberColumn("Injectors", format="%d"),
            "ready_state": "State",
            "character_sync_status": "Sync",
            "character_last_sync_at": "Last Sync",
            "days_to_next_injector": st.column_config.NumberColumn(
                "Days to Next",
                format="%.2f",
            ),
            "current_skill": "Current Skill",
            "queue_ends_at": "Queue Ends",
        },
    )
