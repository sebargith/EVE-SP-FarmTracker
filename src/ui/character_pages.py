"""Streamlit page sections for account and character SP progression."""

from __future__ import annotations

import sqlite3
from html import escape

import pandas as pd
import streamlit as st

from src.calculations.assumptions import TrainingAssumptions
from src.charts.account_charts import (
    extractable_sp_by_group_chart,
    projected_sp_by_group_chart,
    queue_health_chart,
    readiness_chart,
    sp_snapshot_history_chart,
    sp_velocity_chart,
)
from src.data.repositories import (
    add_account,
    add_account_group,
    add_character,
    create_sso_auth_state,
    delete_api_token,
    delete_sso_auth_state,
    get_sso_auth_state,
    count_character_assets,
    list_api_tokens,
    list_accounts,
    list_assets_by_type,
    list_character_skills,
    list_groups,
    list_skill_queue_entries,
    list_sp_snapshots,
    latest_wallet_snapshot,
    update_character_sp,
)
from src.integrations.esi_public import (
    LARGE_SKILL_INJECTOR_TYPE_ID,
    PLEX_TYPE_ID,
    SKILL_EXTRACTOR_TYPE_ID,
    fetch_inventory_type_names,
)
from src.integrations.sso import (
    build_authorization_url,
    exchange_authorization_code,
    generate_pkce_pair,
    generate_state,
    load_sso_config,
    validate_access_token,
)
from src.integrations.token_store import TokenStoreError
from src.services.character_service import (
    CharacterProgress,
    list_character_progress,
    progress_to_dataframe,
    summarize_progress,
)
from src.services.esi_sync_service import import_authorized_character, sync_character_from_token_row
from src.services.sp_tracking_service import (
    analytics_dataframe,
    alerts_dataframe,
    milestones_dataframe,
    snapshot_history_dataframe,
    snapshot_trends_by_character,
    sp_progress_analytics_by_character,
    sp_milestones,
    sp_tracking_dataframe,
    summarize_sp_tracking,
    tracking_alerts,
)
from src.ui.components import (
    character_progress_table,
    kpi_card,
    metric_card,
    section_header,
    status_badge,
)


RELEVANT_ASSET_TYPES = {
    LARGE_SKILL_INJECTOR_TYPE_ID: "Large Skill Injector",
    SKILL_EXTRACTOR_TYPE_ID: "Skill Extractor",
    PLEX_TYPE_ID: "PLEX",
}


def characters_page(
    connection: sqlite3.Connection,
    training: TrainingAssumptions,
) -> None:
    """Render the character SP progression tab."""

    _handle_sso_callback(connection)

    progress = list_character_progress(connection, training)
    farm_summary = summarize_progress(progress)
    sp_summary = summarize_sp_tracking(progress)
    progress_df = progress_to_dataframe(progress)
    snapshots_by_character = {
        row.character_id: list_sp_snapshots(connection, character_id=row.character_id, limit=200)
        for row in progress
    }
    snapshot_trends = snapshot_trends_by_character(progress, snapshots_by_character)
    progress_analytics = sp_progress_analytics_by_character(progress, snapshots_by_character)
    analytics_df = analytics_dataframe(progress_analytics)
    tracking_df = sp_tracking_dataframe(progress, snapshot_trends=snapshot_trends)
    alerts = tracking_alerts(
        progress,
        snapshot_trends=snapshot_trends,
        progress_analytics=progress_analytics,
    )
    milestones = sp_milestones(progress)

    section_header(
        "SP Command Center",
        "Progression, queue health, and snapshot trend signals.",
    )
    _sp_command_metrics(sp_summary, tracking_df, alerts)

    main_col, side_col = st.columns([2.45, 1], gap="large")
    with main_col:
        section_header("Character SP Tracking", "Live projection plus observed snapshot trend.")
        _sp_tracking_table(tracking_df)
    with side_col:
        section_header("Tracking Attention", "Fix queues and stale data first.")
        _attention_board(alerts)
        section_header("Next SP Milestones", "Nearest 500k SP boundaries.")
        _milestone_board(milestones)

    analytics_left, analytics_right = st.columns([1.15, 1], gap="large")
    with analytics_left:
        section_header("SP Velocity", "7 day observed SP/day vs expected rate.")
        st.plotly_chart(
            sp_velocity_chart(analytics_df),
            width="stretch",
            key="sp_velocity_chart",
        )
    with analytics_right:
        section_header("Progression Analytics", "7d/30d SP gain and queue coverage.")
        _sp_analytics_table(analytics_df)

    chart_left, chart_right = st.columns(2, gap="large")
    with chart_left:
        section_header("Projected SP By Group")
        st.plotly_chart(
            projected_sp_by_group_chart(tracking_df),
            width="stretch",
            key="projected_sp_by_group_chart",
        )
    with chart_right:
        section_header("Queue Health")
        st.plotly_chart(queue_health_chart(tracking_df), width="stretch", key="queue_health_chart")

    section_header("Character Inspector", "Skills, queue, assets, and snapshot history.")
    _character_detail_panel(connection, progress)

    with st.expander("Farm / Extraction Support Feature", expanded=False):
        st.caption("Secondary planning view fed by SP tracking and readiness states.")
        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card(
                "Ready Characters",
                f"{farm_summary.ready_characters:,}",
                "available for extraction review",
                tone="success" if farm_summary.ready_characters else "neutral",
                icon="RDY",
            )
        with c2:
            metric_card(
                "Whole Injectors",
                f"{farm_summary.total_available_injectors:,}",
                "ready above extraction floor",
                tone="success" if farm_summary.total_available_injectors else "neutral",
                icon="LSI",
            )
        with c3:
            metric_card(
                "Extractable SP",
                _format_sp(farm_summary.total_extractable_sp),
                "whole injector capacity",
                tone="neutral",
                icon="EXT",
            )

        readiness_tab, extractable_tab, group_tab = st.tabs(
            ["Readiness", "Extractable SP", "Grouped Farm View"]
        )
        with readiness_tab:
            st.plotly_chart(readiness_chart(progress_df), width="stretch", key="readiness_chart")
        with extractable_tab:
            st.plotly_chart(
                extractable_sp_by_group_chart(progress_df),
                width="stretch",
                key="extractable_sp_by_group_chart",
            )
        with group_tab:
            _grouped_character_view(progress)

    with st.expander("Sync And Manual Controls", expanded=False):
        control_left, control_right = st.columns(2, gap="large")
        with control_left:
            section_header("EVE SSO")
            _sso_panel(connection)
        with control_right:
            section_header("Manual Updates")
            update_tab, add_tab = st.tabs(["Update SP Snapshot", "Add Character"])
            with update_tab:
                _sp_update_form(connection, progress)
            with add_tab:
                _add_character_form(connection)

    with st.expander("Progression Audit Table", expanded=False):
        character_progress_table(progress_df)


def farm_extraction_page(
    connection: sqlite3.Connection,
    training: TrainingAssumptions,
) -> None:
    """Render the supporting farm readiness and extraction planning view."""

    progress = list_character_progress(connection, training)
    farm_summary = summarize_progress(progress)
    progress_df = progress_to_dataframe(progress)

    section_header(
        "Farm / Extraction Support",
        "Secondary view for extraction readiness after SP tracking flags useful action.",
    )
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card(
            "Ready Characters",
            f"{farm_summary.ready_characters:,}",
            "ready state now",
            tone="success" if farm_summary.ready_characters else "neutral",
            icon="RDY",
        )
    with c2:
        metric_card(
            "Whole Injectors",
            f"{farm_summary.total_available_injectors:,}",
            "available above floor",
            tone="success" if farm_summary.total_available_injectors else "neutral",
            icon="LSI",
        )
    with c3:
        metric_card(
            "Extractable SP",
            _format_sp(farm_summary.total_extractable_sp),
            "whole injector capacity",
            tone="neutral",
            icon="EXT",
        )
    with c4:
        metric_card(
            "Monthly Injectors",
            f"{farm_summary.projected_monthly_injectors:,.2f}",
            "projected from training",
            tone="success",
            icon="30D",
        )

    chart_left, chart_right = st.columns(2, gap="large")
    with chart_left:
        section_header("Readiness State")
        st.plotly_chart(readiness_chart(progress_df), width="stretch", key="farm_readiness_chart")
    with chart_right:
        section_header("Extractable SP By Group")
        st.plotly_chart(
            extractable_sp_by_group_chart(progress_df),
            width="stretch",
            key="farm_extractable_sp_chart",
        )

    section_header("Extraction Readiness Queue", "Grouped by account group and account.")
    _farm_readiness_table(progress)

    with st.expander("Grouped Farm View", expanded=True):
        _grouped_character_view(progress)


def _sp_command_metrics(
    sp_summary,
    tracking_df: pd.DataFrame,
    alerts: list,
) -> None:
    observed = pd.to_numeric(tracking_df["Observed SP/day"], errors="coerce")
    expected = pd.to_numeric(tracking_df["Expected SP/day"], errors="coerce")
    observed_mask = observed.notna()
    observed_total = observed[observed_mask].sum()
    expected_for_observed = expected[observed_mask].sum()
    observed_delta = observed_total - expected_for_observed
    observed_delta_text = (
        f"{observed_delta:,.0f} vs expected"
        if observed_mask.any()
        else "needs two snapshots"
    )
    observed_value = f"{observed_total:,.0f}" if observed_mask.any() else "n/a"
    warning_count = sp_summary.queue_warning_characters + sp_summary.empty_or_paused_queues

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        metric_card(
            "Total SP",
            _format_sp(sp_summary.total_projected_sp),
            "projected now",
            tone="neutral",
            icon="SP",
        )
    with c2:
        metric_card(
            "30D SP Gain",
            _format_sp(sp_summary.projected_monthly_sp),
            "projected training",
            tone="success",
            icon="30D",
        )
    with c3:
        metric_card(
            "Observed SP/day",
            observed_value,
            observed_delta_text,
            tone="success" if observed_mask.any() and observed_delta >= 0 else "warning",
            icon="DAY",
        )
    with c4:
        metric_card(
            "Active Queues",
            f"{sp_summary.active_training_queues:,}",
            f"{sp_summary.synced_characters:,} SSO synced",
            tone="success" if sp_summary.active_training_queues else "warning",
            icon="QUE",
        )
    with c5:
        metric_card(
            "Attention",
            f"{len(alerts):,}",
            f"{warning_count:,} queue issue(s)",
            tone="danger" if alerts else "success",
            icon="ALT",
        )


def _sp_tracking_table(tracking_df: pd.DataFrame) -> None:
    visible_columns = [
        "Group",
        "Account",
        "Character",
        "Projected SP",
        "SP Gain Since Last Snapshot",
        "Observed SP/day",
        "Expected SP/day",
        "Training Delta SP/day",
        "Queue Status",
        "Queue Ends",
        "Next Injector Days",
        "Sync",
        "Snapshot Age Hours",
    ]
    table = tracking_df[visible_columns].copy()
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "Projected SP": st.column_config.NumberColumn("Projected SP", format="%d SP"),
            "Next Injector Days": st.column_config.NumberColumn(
                "Next Injector Days",
                format="%.2f",
            ),
            "SP Gain Since Last Snapshot": st.column_config.NumberColumn(
                "SP Gain Since Last Snapshot",
                format="%d SP",
            ),
            "Observed SP/day": st.column_config.NumberColumn("Observed SP/day", format="%.0f SP"),
            "Expected SP/day": st.column_config.NumberColumn("Expected SP/day", format="%.0f SP"),
            "Training Delta SP/day": st.column_config.NumberColumn(
                "Training Delta SP/day",
                format="%.0f SP",
            ),
            "Snapshot Age Hours": st.column_config.NumberColumn(
                "Snapshot Age Hours",
                format="%.1f",
            ),
        },
    )


def _farm_readiness_table(progress: list[CharacterProgress]) -> None:
    rows = [
        {
            "Group": row.group_name,
            "Account": row.account_name,
            "Character": row.character_name,
            "State": row.ready_state,
            "Projected SP": row.projected_sp,
            "SP Above Floor": row.sp_above_floor,
            "Extractable SP": row.extractable_sp,
            "Injectors Ready": row.estimated_injectors,
            "Days To Next Injector": row.days_to_next_injector,
            "Queue Ends": row.queue_ends_at,
            "Sync": row.character_sync_status,
        }
        for row in progress
    ]
    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Projected SP": st.column_config.NumberColumn("Projected SP", format="%d SP"),
            "SP Above Floor": st.column_config.NumberColumn("SP Above Floor", format="%d SP"),
            "Extractable SP": st.column_config.NumberColumn("Extractable SP", format="%d SP"),
            "Injectors Ready": st.column_config.NumberColumn("Injectors Ready", format="%d"),
            "Days To Next Injector": st.column_config.NumberColumn(
                "Days To Next Injector",
                format="%.2f",
            ),
        },
    )


def _sp_analytics_table(analytics_df: pd.DataFrame) -> None:
    if analytics_df.empty:
        st.info("No SP analytics available yet.")
        return

    visible_columns = [
        "Group",
        "Account",
        "Character",
        "Snapshots",
        "Queue Coverage %",
        "7D SP Gain",
        "7D Observed SP/day",
        "7D Delta SP/day",
        "7D Data Coverage %",
        "30D SP Gain",
        "30D Observed SP/day",
        "30D Delta SP/day",
        "30D Data Coverage %",
    ]
    st.dataframe(
        analytics_df[visible_columns],
        width="stretch",
        hide_index=True,
        column_config={
            "Snapshots": st.column_config.NumberColumn("Snapshots", format="%d"),
            "Queue Coverage %": st.column_config.NumberColumn(
                "Queue Coverage %",
                format="%.0f%%",
            ),
            "7D SP Gain": st.column_config.NumberColumn("7D SP Gain", format="%d SP"),
            "7D Observed SP/day": st.column_config.NumberColumn(
                "7D Observed SP/day",
                format="%.0f SP",
            ),
            "7D Delta SP/day": st.column_config.NumberColumn(
                "7D Delta SP/day",
                format="%.0f SP",
            ),
            "7D Data Coverage %": st.column_config.NumberColumn(
                "7D Data Coverage %",
                format="%.0f%%",
            ),
            "30D SP Gain": st.column_config.NumberColumn("30D SP Gain", format="%d SP"),
            "30D Observed SP/day": st.column_config.NumberColumn(
                "30D Observed SP/day",
                format="%.0f SP",
            ),
            "30D Delta SP/day": st.column_config.NumberColumn(
                "30D Delta SP/day",
                format="%.0f SP",
            ),
            "30D Data Coverage %": st.column_config.NumberColumn(
                "30D Data Coverage %",
                format="%.0f%%",
            ),
        },
    )


def _attention_board(alerts: list) -> None:
    if not alerts:
        st.markdown(
            """
            <div class="eve-list-panel">
                <div class="eve-empty-state">No SP tracking alerts.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    rows = []
    for alert in alerts[:6]:
        tone = _severity_tone(alert.severity)
        rows.append(
            f"""
            <div class="eve-alert-row {tone}">
                <div class="eve-alert-top">
                    {status_badge(alert.severity.upper(), tone=tone)}
                    <span>{escape(alert.category)}</span>
                </div>
                <div class="eve-alert-title">{escape(alert.character_name)}</div>
                <div class="eve-alert-message">{escape(alert.message)}</div>
                <div class="eve-alert-action">{escape(alert.action)}</div>
            </div>
            """
        )
    if len(alerts) > 6:
        rows.append(
            f'<div class="eve-list-more">+{len(alerts) - 6} more alert(s)</div>'
        )
    st.markdown(
        '<div class="eve-list-panel">' + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )


def _milestone_board(milestones: list) -> None:
    if not milestones:
        st.markdown(
            """
            <div class="eve-list-panel">
                <div class="eve-empty-state">No SP milestones available.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    rows = []
    for milestone in milestones[:6]:
        days = (
            f"{milestone.days_to_milestone:.2f} days"
            if milestone.days_to_milestone is not None
            else "blocked by queue"
        )
        tone = "success" if milestone.days_to_milestone is not None else "warning"
        rows.append(
            f"""
            <div class="eve-milestone-row">
                <div class="eve-alert-top">
                    {status_badge(days, tone=tone)}
                </div>
                <div class="eve-alert-title">{escape(milestone.character_name)}</div>
                <div class="eve-alert-message">
                    {escape(_format_sp(milestone.current_sp))} -> {escape(_format_sp(milestone.target_sp))}
                </div>
                <div class="eve-alert-action">{escape(_format_sp(milestone.remaining_sp))} remaining</div>
            </div>
            """
        )
    if len(milestones) > 6:
        rows.append(
            f'<div class="eve-list-more">+{len(milestones) - 6} more milestone(s)</div>'
        )
    st.markdown(
        '<div class="eve-list-panel">' + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )


def _tracking_alerts_table(alerts_df: pd.DataFrame) -> None:
    if alerts_df.empty:
        st.success("No SP tracking alerts.")
        return

    st.dataframe(
        alerts_df,
        width="stretch",
        hide_index=True,
        column_config={
            "severity": "Severity",
            "category": "Category",
            "group_name": "Group",
            "account_name": "Account",
            "character_name": "Character",
            "message": "Message",
            "action": "Action",
            "due_at": "Due / Last Sync",
        },
    )


def _milestones_table(milestones_df: pd.DataFrame) -> None:
    if milestones_df.empty:
        st.info("No SP milestones available.")
        return

    st.dataframe(
        milestones_df,
        width="stretch",
        hide_index=True,
        column_config={
            "group_name": "Group",
            "account_name": "Account",
            "character_name": "Character",
            "milestone": "Milestone",
            "current_sp": st.column_config.NumberColumn("Current SP", format="%d SP"),
            "target_sp": st.column_config.NumberColumn("Target SP", format="%d SP"),
            "remaining_sp": st.column_config.NumberColumn("Remaining SP", format="%d SP"),
            "days_to_milestone": st.column_config.NumberColumn(
                "Days",
                format="%.2f",
            ),
            "projected_at": "Projected At",
        },
    )


def _grouped_character_view(progress: list[CharacterProgress]) -> None:
    for group_name in sorted({row.group_name for row in progress}):
        group_rows = [row for row in progress if row.group_name == group_name]
        ready_count = sum(1 for row in group_rows if row.ready_state == "READY")
        with st.expander(
            f"{group_name} - {len(group_rows)} characters, {ready_count} ready",
            expanded=True,
        ):
            for account_name in sorted({row.account_name for row in group_rows}):
                account_rows = [row for row in group_rows if row.account_name == account_name]
                st.markdown(f"**{account_name}**")
                for row in account_rows:
                    status = row.ready_state
                    injectors = row.estimated_injectors
                    next_text = (
                        f"{row.days_to_next_injector:.2f} days"
                        if row.days_to_next_injector is not None
                        else "n/a"
                    )
                    st.write(
                        f"{row.character_name}: {row.projected_sp:,} SP, "
                        f"{injectors} injectors, {status}, next {next_text}, "
                        f"sync {row.character_sync_status}"
                    )


def _character_detail_panel(
    connection: sqlite3.Connection,
    progress: list[CharacterProgress],
) -> None:
    if not progress:
        st.info("No characters are tracked yet.")
        return

    labels = {
        f"{row.group_name} / {row.account_name} / {row.character_name}": row
        for row in progress
    }
    selected_label = st.selectbox(
        "Character detail",
        list(labels),
        key="character_detail_select",
    )
    selected = labels[selected_label]

    overview_tab, skills_tab, queue_tab, history_tab = st.tabs(
        ["Overview", "Skills", "Training Queue", "SP History"]
    )
    with overview_tab:
        _character_overview(connection, selected)
    with skills_tab:
        _character_skills_table(connection, selected.character_id)
    with queue_tab:
        _character_queue_table(connection, selected.character_id)
    with history_tab:
        _character_sp_history(connection, selected.character_id)


def _character_overview(
    connection: sqlite3.Connection,
    selected: CharacterProgress,
) -> None:
    wallet = latest_wallet_snapshot(connection, character_id=selected.character_id)
    relevant_assets = list_assets_by_type(
        connection,
        character_id=selected.character_id,
        type_ids=tuple(RELEVANT_ASSET_TYPES),
    )
    asset_count = count_character_assets(connection, character_id=selected.character_id)

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        kpi_card("Projected SP", f"{selected.projected_sp:,}", selected.ready_state)
    with c2:
        kpi_card("Injectors Ready", f"{selected.estimated_injectors:,}", "whole injectors")
    with c3:
        wallet_value = _format_isk(wallet["balance"]) if wallet else "n/a"
        wallet_delta = wallet["timestamp"] if wallet else "not synced"
        kpi_card("Wallet", wallet_value, wallet_delta)
    with c4:
        kpi_card("Assets", f"{asset_count:,}", "items from ESI")

    asset_rows = [
        {
            "Asset": RELEVANT_ASSET_TYPES.get(int(row["type_id"]), f"Type {row['type_id']}"),
            "Quantity": int(row["quantity"] or 0),
            "Stacks": int(row["stacks"] or 0),
            "Synced": row["synced_at"],
        }
        for row in relevant_assets
    ]
    if asset_rows:
        st.dataframe(asset_rows, width="stretch", hide_index=True)
    else:
        st.info(
            "No LSI, Skill Extractor, or PLEX assets found on this character. "
            "Use the Market tab after syncing prices to value those assets when present."
        )


def _character_skills_table(connection: sqlite3.Connection, character_id: int) -> None:
    skills = list_character_skills(connection, character_id=character_id)
    if not skills:
        st.info("No skill inventory has been synced for this character yet.")
        return

    type_names = _inventory_type_names([int(row["skill_id"]) for row in skills])
    rows = [
        {
            "Skill": type_names.get(int(row["skill_id"]), f"Skill {row['skill_id']}"),
            "Skill ID": int(row["skill_id"]),
            "Active Level": int(row["active_skill_level"]),
            "Trained Level": int(row["trained_skill_level"]),
            "SP": int(row["skillpoints_in_skill"]),
            "Synced": row["synced_at"],
        }
        for row in skills
    ]
    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "SP": st.column_config.NumberColumn("SP", format="%d SP"),
            "Skill ID": st.column_config.NumberColumn("Skill ID", format="%d"),
        },
    )


def _character_queue_table(connection: sqlite3.Connection, character_id: int) -> None:
    queue_entries = list_skill_queue_entries(connection, character_id=character_id)
    if not queue_entries:
        st.warning("No training queue is synced for this character.")
        return

    type_names = _inventory_type_names([int(row["skill_id"]) for row in queue_entries])
    rows = [
        {
            "Position": int(row["queue_position"]),
            "Skill": type_names.get(int(row["skill_id"]), f"Skill {row['skill_id']}"),
            "Target Level": int(row["finished_level"]),
            "Start": row["start_date"],
            "Finish": row["finish_date"],
            "Training Start SP": row["training_start_sp"],
            "Level End SP": row["level_end_sp"],
        }
        for row in queue_entries
    ]
    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Position": st.column_config.NumberColumn("Position", format="%d"),
            "Target Level": st.column_config.NumberColumn("Target Level", format="%d"),
            "Training Start SP": st.column_config.NumberColumn(
                "Training Start SP",
                format="%d SP",
            ),
            "Level End SP": st.column_config.NumberColumn("Level End SP", format="%d SP"),
        },
    )


def _character_sp_history(connection: sqlite3.Connection, character_id: int) -> None:
    snapshots = list_sp_snapshots(connection, character_id=character_id)
    if not snapshots:
        st.info("No SP snapshots recorded for this character yet.")
        return

    history_df = snapshot_history_dataframe(snapshots)
    st.plotly_chart(
        sp_snapshot_history_chart(history_df),
        width="stretch",
        key=f"sp_history_{character_id}",
    )
    st.dataframe(
        history_df,
        width="stretch",
        hide_index=True,
        column_config={
            "total_sp": st.column_config.NumberColumn("Total SP", format="%d SP"),
        },
    )


@st.cache_data(show_spinner=False, ttl=3600)
def _inventory_type_names(type_ids: list[int]) -> dict[int, str]:
    try:
        return fetch_inventory_type_names(type_ids)
    except Exception:
        return {}


def _format_isk(value: float) -> str:
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B ISK"
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M ISK"
    return f"{value:,.0f} ISK"


def _format_sp(value: float) -> str:
    absolute = abs(value)
    sign = "-" if value < 0 else ""
    if absolute >= 1_000_000_000:
        return f"{sign}{absolute / 1_000_000_000:.2f}B SP"
    if absolute >= 1_000_000:
        return f"{sign}{absolute / 1_000_000:.2f}M SP"
    if absolute >= 1_000:
        return f"{sign}{absolute / 1_000:.1f}K SP"
    return f"{sign}{absolute:,.0f} SP"


def _severity_tone(severity: str) -> str:
    if severity == "critical":
        return "danger"
    if severity == "warning":
        return "warning"
    return "neutral"


def _handle_sso_callback(connection: sqlite3.Connection) -> None:
    query_params = st.query_params
    authorization_code = query_params.get("code")
    returned_state = query_params.get("state")
    if not authorization_code and not returned_state:
        return

    if not authorization_code or not returned_state:
        st.error("EVE SSO callback was missing the authorization code or state.")
        return

    auth_state = get_sso_auth_state(connection, state=str(returned_state))
    if not auth_state:
        st.error("EVE SSO login expired or was not started from this app. Start the login flow again.")
        return

    config = load_sso_config()
    if not config.is_configured:
        st.error("EVE SSO is not configured. Add EVE_CLIENT_ID and EVE_CALLBACK_URL to .env.")
        return

    try:
        token_response = exchange_authorization_code(
            config,
            authorization_code=str(authorization_code),
            code_verifier=str(auth_state["code_verifier"]),
        )
        claims = validate_access_token(token_response.access_token, client_id=config.client_id)
        result = import_authorized_character(
            connection,
            account_id=int(auth_state["account_id"]),
            config=config,
            token_response=token_response,
            claims=claims,
        )
    except TokenStoreError as exc:
        st.error(str(exc))
        return
    except Exception as exc:
        st.error(f"EVE SSO import failed: {exc}")
        return

    delete_sso_auth_state(connection, state=str(returned_state))
    st.session_state.pop("eve_sso_auth_url", None)
    st.query_params.clear()
    st.success(f"Imported {result.character_name} from EVE SSO.")
    st.rerun()


def _sso_panel(connection: sqlite3.Connection) -> None:
    config = load_sso_config()
    accounts = list_accounts(connection)
    tokens = list_api_tokens(connection)

    if not config.is_configured:
        st.warning(
            "EVE SSO is not configured. Create a .env file with EVE_CLIENT_ID "
            "and EVE_CALLBACK_URL before connecting characters."
        )
        st.code(
            "EVE_CLIENT_ID=your_eve_application_client_id\n"
            "EVE_CALLBACK_URL=http://localhost:8766",
            language="dotenv",
        )
    else:
        st.caption(
            "Requested scopes: "
            + ", ".join(config.scopes)
            + ". Connect one EVE character at a time."
        )

    connect_tab, sync_tab = st.tabs(["Connect Character", "Authorized Characters"])
    with connect_tab:
        if not accounts:
            st.info("Create a local account before connecting an EVE character.")
        elif config.is_configured:
            account_options = {
                f"{account['group_name']} / {account['name']}": account["id"]
                for account in accounts
            }
            selected_account = st.selectbox(
                "Attach authorized character to account",
                list(account_options),
                key="sso_account",
            )
            if st.button("Prepare EVE SSO Login"):
                verifier, challenge = generate_pkce_pair()
                state = generate_state()
                create_sso_auth_state(
                    connection,
                    state=state,
                    account_id=int(account_options[selected_account]),
                    code_verifier=verifier,
                )
                st.session_state["eve_sso_auth_url"] = build_authorization_url(
                    config,
                    state=state,
                    code_challenge=challenge,
                )

            auth_url = st.session_state.get("eve_sso_auth_url")
            if auth_url:
                st.link_button("Log in with EVE Online", str(auth_url))

    with sync_tab:
        if not tokens:
            st.info("No EVE SSO characters are authorized yet.")
            return

        token_rows = [
            {
                "Group": token["group_name"],
                "Account": token["account_name"],
                "Character": token["character_name"],
                "Scopes": token["scopes"],
                "Status": token["status"],
                "Last Sync": token["last_sync_at"],
            }
            for token in tokens
        ]
        st.dataframe(token_rows, width="stretch", hide_index=True)

        if st.button("Sync All Authorized Characters"):
            successes = 0
            for token in tokens:
                try:
                    sync_character_from_token_row(connection, token_row=token, config=config)
                    successes += 1
                except Exception as exc:
                    st.error(f"Sync failed for {token['character_name']}: {exc}")
            if successes:
                st.success(f"Synced {successes} character(s) from EVE SSO.")
                st.rerun()

        for token in tokens:
            if st.button(
                f"Forget SSO for {token['character_name']}",
                key=f"delete_token_{token['id']}",
            ):
                delete_api_token(connection, token_id=int(token["id"]))
                st.success("Stored EVE SSO token removed.")
                st.rerun()


def _sp_update_form(
    connection: sqlite3.Connection,
    progress: list[CharacterProgress],
) -> None:
    if not progress:
        st.info("No characters are tracked yet.")
        return

    labels = {
        f"{row.group_name} / {row.account_name} / {row.character_name}": row
        for row in progress
    }
    selected_label = st.selectbox("Character", list(labels))
    selected = labels[selected_label]
    total_sp = st.number_input(
        "New total SP",
        min_value=0,
        value=int(selected.projected_sp),
        step=50_000,
        format="%d",
    )
    notes = st.text_input("Snapshot notes", value="")
    if st.button("Save SP Snapshot"):
        update_character_sp(
            connection,
            character_id=selected.character_id,
            total_sp=int(total_sp),
            notes=notes,
        )
        st.success("SP snapshot saved.")
        st.rerun()


def _add_character_form(connection: sqlite3.Connection) -> None:
    groups = list_groups(connection)
    accounts = list_accounts(connection)

    with st.expander("Create account group"):
        group_name = st.text_input("Group name", key="new_group_name")
        group_notes = st.text_input("Group notes", key="new_group_notes")
        if st.button("Add Group"):
            if group_name.strip():
                add_account_group(connection, name=group_name.strip(), notes=group_notes)
                st.success("Group added.")
                st.rerun()

    with st.expander("Create account"):
        if groups:
            group_options = {group["name"]: group["id"] for group in groups}
            selected_group = st.selectbox("Group", list(group_options), key="new_account_group")
            account_name = st.text_input("Account name", key="new_account_name")
            omega_status = st.selectbox(
                "Omega status",
                ["Omega", "Alpha", "Unknown"],
                key="new_account_omega",
            )
            mct_slots = st.number_input("MCT slots", min_value=0, max_value=2, value=0)
            if st.button("Add Account"):
                if account_name.strip():
                    add_account(
                        connection,
                        group_id=group_options[selected_group],
                        name=account_name.strip(),
                        omega_status=omega_status,
                        mct_slots=int(mct_slots),
                    )
                    st.success("Account added.")
                    st.rerun()

    if not accounts:
        st.info("Create an account before adding a character.")
        return

    account_options = {
        f"{account['group_name']} / {account['name']}": account["id"]
        for account in accounts
    }
    selected_account = st.selectbox("Account", list(account_options))
    character_name = st.text_input("Character name")
    total_sp = st.number_input("Total SP", min_value=0, value=5_000_000, step=50_000, format="%d")
    training_rate = st.number_input(
        "Training rate SP/min",
        min_value=0.0,
        value=45.0,
        step=0.5,
        format="%.1f",
    )
    current_skill = st.text_input("Current skill")
    attribute_profile = st.text_input("Attribute profile", value="Optimized")
    implant_profile = st.text_input("Implant profile", value="+5")
    notes = st.text_input("Character notes")

    if st.button("Add Character"):
        if character_name.strip():
            add_character(
                connection,
                account_id=account_options[selected_account],
                name=character_name.strip(),
                total_sp=int(total_sp),
                training_rate_sp_min=float(training_rate),
                current_skill=current_skill,
                attribute_profile=attribute_profile,
                implant_profile=implant_profile,
                notes=notes,
            )
            st.success("Character added.")
            st.rerun()
