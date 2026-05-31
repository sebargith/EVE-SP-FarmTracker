"""Streamlit page sections for account and character SP progression."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from html import escape
from textwrap import dedent

import pandas as pd
import streamlit as st

from src.calculations.assumptions import FarmAssumptions, TrainingAssumptions
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
    list_extraction_events,
    list_groups,
    list_recent_sync_runs,
    list_skill_queue_entries,
    list_sp_snapshots,
    latest_wallet_snapshot,
    update_account_operations,
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
from src.services.account_operations_service import (
    AccountOperation,
    list_account_operations,
    summarize_account_operations,
)
from src.services.character_service import (
    CharacterProgress,
    list_character_progress,
    progress_to_dataframe,
    summarize_progress,
)
from src.services.esi_sync_service import (
    import_authorized_character,
    list_sync_health,
    sync_character_from_token_row,
    sync_due_authorized_characters,
)
from src.services.extraction_service import (
    ExtractionPricingContext,
    ExtractionPlanRow,
    build_extraction_plan,
    complete_planned_extraction,
    extraction_pricing_context,
    log_realized_extraction,
    summarize_extraction_plan,
)
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
    _auto_sync_stale_characters(connection)

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

    section_header(
        "Account Operations",
        "Manual Omega and MCT coverage with queue utilization warnings.",
    )
    _account_operations_panel(connection, training, progress)

    section_header(
        "Sync Diagnostics",
        "Authorized character health, queue coverage, and SP at risk before the next sync.",
    )
    _sync_health_panel(connection)

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
    assumptions: FarmAssumptions,
) -> None:
    """Render the supporting farm readiness and extraction planning view."""

    progress = list_character_progress(connection, assumptions.training)
    farm_summary = summarize_progress(progress)
    progress_df = progress_to_dataframe(progress)
    plan = build_extraction_plan(connection, assumptions, progress=progress)
    plan_summary = summarize_extraction_plan(plan)
    pricing = extraction_pricing_context(connection, assumptions)

    section_header(
        "Farm / Extraction Support",
        "Secondary view for extraction readiness after SP tracking flags useful action.",
    )
    _extraction_pricing_panel(pricing)
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        metric_card(
            "Ready Characters",
            f"{plan_summary.ready_characters:,}",
            "ready state now",
            tone="success" if plan_summary.ready_characters else "neutral",
            icon="RDY",
        )
    with c2:
        metric_card(
            "Whole Injectors",
            f"{plan_summary.injectors_ready:,}",
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
            "Available This Week",
            f"{plan_summary.injectors_available_this_week:,}",
            "ready plus near-term injectors",
            tone="success" if plan_summary.injectors_available_this_week else "neutral",
            icon="7D",
        )
    with c5:
        metric_card(
            "Planned Net",
            _format_isk(plan_summary.planned_net_profit),
            "LSI net less extractors",
            tone="success" if plan_summary.planned_net_profit >= 0 else "danger",
            icon="ISK",
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

    section_header(
        "Extraction Action Queue",
        "Recommendations use tracked SP and the editable sidebar market assumptions.",
    )
    _extraction_plan_table(plan)

    action_tab, audit_tab, grouped_tab = st.tabs(
        ["Log Completed Extraction", "Extraction Audit", "Grouped Farm View"]
    )
    with action_tab:
        _log_extraction_form(connection, assumptions, plan)
    with audit_tab:
        _extraction_audit_table(connection)
        _complete_planned_extraction_form(connection, assumptions)
    with grouped_tab:
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


def _account_operations_panel(
    connection: sqlite3.Connection,
    training: TrainingAssumptions,
    progress: list[CharacterProgress],
) -> None:
    operations = list_account_operations(connection, training, progress=progress)
    if not operations:
        st.info("No accounts are tracked yet.")
        return

    summary = summarize_account_operations(operations)
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        metric_card(
            "Healthy Accounts",
            f"{summary.healthy_accounts:,}/{summary.total_accounts:,}",
            f"{summary.attention_accounts:,} need attention",
            tone="success" if not summary.attention_accounts else "warning",
            icon="ACC",
        )
    with c2:
        metric_card(
            "Active Queues",
            f"{summary.active_queues:,}/{summary.queue_capacity:,}",
            "tracked vs available slots",
            tone="success" if summary.active_queues == summary.queue_capacity else "warning",
            icon="QUE",
        )
    with c3:
        metric_card(
            "Unassigned Slots",
            f"{summary.unused_queue_slots:,}",
            "main queue plus MCT capacity",
            tone="warning" if summary.unused_queue_slots else "success",
            icon="MCT",
        )
    with c4:
        metric_card(
            "Stopped Queues",
            f"{summary.stopped_queues:,}",
            "tracked characters not training",
            tone="danger" if summary.stopped_queues else "success",
            icon="ALT",
        )

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Group": row.group_name,
                    "Account": row.account_name,
                    "Health": row.health,
                    "Operation": row.operational_status,
                    "Omega": row.omega_status,
                    "Omega Expires": row.omega_expires_at,
                    "MCT Slots": row.mct_slots,
                    "MCT Expires": row.mct_expires_at,
                    "Tracked Characters": row.tracked_characters,
                    "Active Queues": row.active_queues,
                    "Queue Capacity": row.queue_capacity,
                    "Unassigned Slots": row.unused_queue_slots,
                    "Stopped Queues": row.stopped_queues,
                    "Warnings": "; ".join(row.warnings) or "none",
                }
                for row in operations
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    with st.expander("Edit Account Operations", expanded=False):
        _account_operations_form(connection, operations)


def _account_operations_form(
    connection: sqlite3.Connection,
    operations: list[AccountOperation],
) -> None:
    labels = {
        f"{row.group_name} / {row.account_name}": row
        for row in operations
    }
    selected = labels[
        st.selectbox("Account", list(labels), key="account_operations_account")
    ]
    operational_options = ["Active", "Paused", "Retiring"]
    omega_options = ["Omega", "Alpha", "Unknown"]
    operational_status = st.selectbox(
        "Operational status",
        operational_options,
        index=_option_index(operational_options, selected.operational_status),
    )
    omega_status = st.selectbox(
        "Omega status",
        omega_options,
        index=_option_index(omega_options, selected.omega_status),
    )
    omega_expires = st.text_input(
        "Omega expiration date",
        value=_date_field_value(selected.omega_expires_at),
        placeholder="YYYY-MM-DD",
        help="Manual field. Leave blank if the date is unknown.",
    )
    mct_slots = st.number_input(
        "MCT slots",
        min_value=0,
        max_value=2,
        value=selected.mct_slots,
        step=1,
    )
    mct_expires = st.text_input(
        "MCT expiration date",
        value=_date_field_value(selected.mct_expires_at),
        placeholder="YYYY-MM-DD",
        help="Manual field. Leave blank if the date is unknown or no MCT is active.",
    )
    notes = st.text_area("Account notes", value=selected.notes)

    if st.button("Save Account Operations"):
        try:
            update_account_operations(
                connection,
                account_id=selected.account_id,
                omega_status=omega_status,
                omega_expires_at=_normalize_expiration(omega_expires),
                mct_slots=int(mct_slots),
                mct_expires_at=_normalize_expiration(mct_expires),
                operational_status=operational_status,
                notes=notes,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success("Account operations updated.")
            st.rerun()


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


def _extraction_plan_table(plan: list[ExtractionPlanRow]) -> None:
    if not plan:
        st.info("No tracked characters are available for extraction planning.")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Group": row.group_name,
                    "Account": row.account_name,
                    "Character": row.character_name,
                    "Recommendation": row.recommendation,
                    "State": row.readiness,
                    "Projected SP": row.projected_sp,
                    "Extractable SP": row.extractable_sp,
                    "Injectors Ready": row.injectors_ready,
                    "Days To Next": row.days_to_next_injector,
                    "Gross Revenue": row.gross_revenue,
                    "Fees": row.market_fees,
                    "Extractor Cost": row.extractor_total_cost,
                    "Projected Net": row.projected_profit,
                    "Price Source": row.pricing_source,
                    "Price As Of": row.pricing_as_of,
                    "Price Age Hours": row.pricing_age_hours,
                    "Price Warning": row.pricing_warning,
                    "Queue Ends": row.queue_ends_at,
                }
                for row in plan
            ]
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "Projected SP": st.column_config.NumberColumn("Projected SP", format="%d SP"),
            "Extractable SP": st.column_config.NumberColumn("Extractable SP", format="%d SP"),
            "Injectors Ready": st.column_config.NumberColumn("Injectors Ready", format="%d"),
            "Days To Next": st.column_config.NumberColumn("Days To Next", format="%.2f"),
            "Gross Revenue": st.column_config.NumberColumn("Gross Revenue", format="%.0f ISK"),
            "Fees": st.column_config.NumberColumn("Fees", format="%.0f ISK"),
            "Extractor Cost": st.column_config.NumberColumn("Extractor Cost", format="%.0f ISK"),
            "Projected Net": st.column_config.NumberColumn("Projected Net", format="%.0f ISK"),
            "Price Age Hours": st.column_config.NumberColumn("Price Age Hours", format="%.1f"),
        },
    )


def _extraction_pricing_panel(pricing: ExtractionPricingContext) -> None:
    description = f"Price source: {pricing.source}. Freshness: {pricing.freshness}."
    if pricing.as_of:
        description += f" Snapshot: {pricing.as_of}."
    if pricing.warnings:
        st.warning(description + " " + " ".join(pricing.warnings))
    else:
        st.success(description)
    st.caption(pricing.source_summary)


def _log_extraction_form(
    connection: sqlite3.Connection,
    assumptions: FarmAssumptions,
    plan: list[ExtractionPlanRow],
) -> None:
    ready = [row for row in plan if row.injectors_ready > 0]
    if not ready:
        st.info("No character currently has a whole injector available.")
        return

    labels = {
        f"{row.group_name} / {row.account_name} / {row.character_name}": row
        for row in ready
    }
    selected = labels[
        st.selectbox("Character", list(labels), key="extraction_event_character")
    ]
    injectors = st.number_input(
        "Injectors created",
        min_value=1,
        max_value=selected.injectors_ready,
        value=selected.injectors_ready,
        step=1,
        key=f"extraction_injectors_{selected.character_id}",
    )
    lsi_price = st.number_input(
        "Realized LSI sale price per unit",
        min_value=0,
        value=int(selected.lsi_unit_price),
        step=10_000_000,
        format="%d",
        key=f"extraction_lsi_price_{selected.character_id}",
    )
    extractor_cost = st.number_input(
        "Realized extractor cost per unit",
        min_value=0,
        value=int(selected.extractor_unit_cost),
        step=10_000_000,
        format="%d",
        key=f"extraction_extractor_cost_{selected.character_id}",
    )
    fee_pct = st.number_input(
        "Realized fees and taxes (%)",
        min_value=0.0,
        max_value=99.0,
        value=float(selected.market_fee_rate * 100),
        step=0.25,
        format="%.2f",
        key=f"extraction_fee_pct_{selected.character_id}",
    )
    notes = st.text_input(
        "Extraction notes",
        value="",
        key=f"extraction_notes_{selected.character_id}",
    )
    event_status = st.selectbox(
        "Event state",
        ["Completed", "Planned"],
        help=(
            "Completed immediately updates the local SP baseline and waits for ESI "
            "reconciliation. Planned records the intended action without changing SP."
        ),
    )
    estimated_net = (
        int(injectors) * float(lsi_price) * (1 - float(fee_pct) / 100)
        - int(injectors) * float(extractor_cost)
    )
    st.caption(f"Estimated realized net: {_format_isk(estimated_net)}")

    if st.button("Record Extraction Event"):
        try:
            log_realized_extraction(
                connection,
                assumptions,
                character_id=selected.character_id,
                injectors_created=int(injectors),
                lsi_sale_unit_price=float(lsi_price),
                extractor_unit_cost=float(extractor_cost),
                market_fee_rate=float(fee_pct) / 100,
                notes=notes,
                status=event_status,
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            message = (
                "Completed extraction recorded. SP baseline updated; ESI reconciliation is pending."
                if event_status == "Completed"
                else "Planned extraction recorded. SP baseline was not changed."
            )
            st.success(message)
            st.rerun()


def _extraction_audit_table(connection: sqlite3.Connection) -> None:
    events = list_extraction_events(connection, limit=100)
    if not events:
        st.info("No completed extraction events have been recorded yet.")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Timestamp": row["timestamp"],
                    "State": row["status"],
                    "Reconciliation": row["reconciliation_status"],
                    "Group": row["group_name"],
                    "Account": row["account_name"],
                    "Character": row["character_name"],
                    "Injectors": row["injectors_created"],
                    "SP Extracted": row["sp_extracted"],
                    "LSI Unit Price": row["lsi_sale_unit_price"],
                    "Extractor Cost": row["extractor_total_cost"],
                    "Fees": row["market_fees"],
                    "Realized Revenue": row["realized_revenue"],
                    "Realized Profit": row["realized_profit"],
                    "SP Before": row["total_sp_before"],
                    "SP After": row["total_sp_after"],
                    "ESI SP": row["esi_total_sp"],
                    "Expected SP": row["expected_total_sp"],
                    "Delta SP": row["reconciliation_delta_sp"],
                    "Reconciliation Detail": row["reconciliation_message"],
                    "Notes": row["notes"],
                }
                for row in events
            ]
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "Injectors": st.column_config.NumberColumn("Injectors", format="%d"),
            "SP Extracted": st.column_config.NumberColumn("SP Extracted", format="%d SP"),
            "LSI Unit Price": st.column_config.NumberColumn("LSI Unit Price", format="%.0f ISK"),
            "Extractor Cost": st.column_config.NumberColumn("Extractor Cost", format="%.0f ISK"),
            "Fees": st.column_config.NumberColumn("Fees", format="%.0f ISK"),
            "Realized Revenue": st.column_config.NumberColumn("Realized Revenue", format="%.0f ISK"),
            "Realized Profit": st.column_config.NumberColumn("Realized Profit", format="%.0f ISK"),
            "SP Before": st.column_config.NumberColumn("SP Before", format="%d SP"),
            "SP After": st.column_config.NumberColumn("SP After", format="%d SP"),
            "ESI SP": st.column_config.NumberColumn("ESI SP", format="%d SP"),
            "Expected SP": st.column_config.NumberColumn("Expected SP", format="%d SP"),
            "Delta SP": st.column_config.NumberColumn("Delta SP", format="%d SP"),
        },
    )


def _complete_planned_extraction_form(
    connection: sqlite3.Connection,
    assumptions: FarmAssumptions,
) -> None:
    events = [
        event
        for event in list_extraction_events(connection, limit=100)
        if event["status"] == "Planned"
    ]
    if not events:
        return

    with st.expander("Complete Planned Extraction", expanded=False):
        labels = {
            (
                f"{event['group_name']} / {event['account_name']} / "
                f"{event['character_name']} - {event['injectors_created']} injector(s)"
            ): event
            for event in events
        }
        selected = labels[
            st.selectbox("Planned event", list(labels), key="planned_extraction_event")
        ]
        event_id = int(selected["id"])
        lsi_price = st.number_input(
            "Completed LSI sale price per unit",
            min_value=0,
            value=int(selected["lsi_sale_unit_price"]),
            step=10_000_000,
            format="%d",
            key=f"planned_lsi_price_{event_id}",
        )
        extractor_cost = st.number_input(
            "Completed extractor cost per unit",
            min_value=0,
            value=int(selected["extractor_unit_cost"]),
            step=10_000_000,
            format="%d",
            key=f"planned_extractor_cost_{event_id}",
        )
        fee_pct = st.number_input(
            "Completed fees and taxes (%)",
            min_value=0.0,
            max_value=99.0,
            value=_event_fee_pct(selected),
            step=0.25,
            format="%.2f",
            key=f"planned_fee_pct_{event_id}",
        )
        notes = st.text_input(
            "Completed extraction notes",
            value=str(selected["notes"]),
            key=f"planned_notes_{event_id}",
        )
        if st.button("Mark Planned Extraction Completed"):
            try:
                complete_planned_extraction(
                    connection,
                    assumptions,
                    event_id=event_id,
                    lsi_sale_unit_price=float(lsi_price),
                    extractor_unit_cost=float(extractor_cost),
                    market_fee_rate=float(fee_pct) / 100,
                    notes=notes,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success("Planned extraction completed. ESI reconciliation is pending.")
                st.rerun()


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
            dedent(
                """
            <div class="eve-list-panel">
                <div class="eve-empty-state">No SP tracking alerts.</div>
            </div>
            """
            ).strip(),
            unsafe_allow_html=True,
        )
        return

    rows = []
    for alert in alerts[:6]:
        tone = _severity_tone(alert.severity)
        rows.append(
            dedent(
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
            ).strip()
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
            dedent(
                """
            <div class="eve-list-panel">
                <div class="eve-empty-state">No SP milestones available.</div>
            </div>
            """
            ).strip(),
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
            dedent(
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
            ).strip()
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


def _option_index(options: list[str], selected: str) -> int:
    return options.index(selected) if selected in options else 0


def _date_field_value(value: str | None) -> str:
    return str(value)[:10] if value else ""


def _normalize_expiration(value: str) -> str | None:
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ValueError("Expiration dates must use YYYY-MM-DD format.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _event_fee_pct(event: dict[str, object]) -> float:
    gross_revenue = float(event["gross_revenue"])
    return float(event["market_fees"]) / gross_revenue * 100 if gross_revenue else 0


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


def _auto_sync_stale_characters(connection: sqlite3.Connection) -> None:
    if st.session_state.get("eve_auto_sync_checked"):
        return
    st.session_state["eve_auto_sync_checked"] = True

    config = load_sso_config()
    if not config.is_configured:
        return

    summary = sync_due_authorized_characters(connection, config=config)
    if summary.attempted:
        st.session_state["eve_auto_sync_summary"] = (
            f"Auto-sync checked {summary.attempted} character(s): "
            f"{summary.successful} healthy, {summary.partial} partial, {summary.failed} failed."
        )


def _sync_health_panel(connection: sqlite3.Connection) -> None:
    summary = st.session_state.get("eve_auto_sync_summary")
    if summary:
        st.caption(str(summary))

    health_rows = list_sync_health(connection)
    if not health_rows:
        st.info("No authorized EVE SSO characters yet.")
        return

    table = pd.DataFrame(
        [
            {
                "Group": row.group_name,
                "Account": row.account_name,
                "Character": row.character_name,
                "Health": row.health,
                "Training": row.training_state,
                "Token": row.token_status,
                "Last Sync": row.last_sync_at,
                "Last Success": row.last_successful_sync_at,
                "Last Failure": row.last_failure_at,
                "Next Sync": row.next_recommended_sync_at,
                "Queue Coverage Hours": row.queue_coverage_hours,
                "SP At Risk": row.sp_at_risk_before_next_sync,
                "Missing Scopes": ", ".join(row.missing_scopes) or "none",
                "Failed Endpoints": ", ".join(row.failed_endpoints) or "none",
            }
            for row in health_rows
        ]
    )
    st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        column_config={
            "Queue Coverage Hours": st.column_config.NumberColumn(
                "Queue Coverage Hours",
                format="%.1f",
            ),
            "SP At Risk": st.column_config.NumberColumn("SP At Risk", format="%d SP"),
        },
    )

    recent_runs = list_recent_sync_runs(connection, limit=10)
    with st.expander("Recent Sync Runs", expanded=False):
        if not recent_runs:
            st.info("No sync runs have been recorded yet.")
        else:
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Character": row["character_name"],
                            "Trigger": row["trigger"],
                            "Status": row["status"],
                            "Started": row["started_at"],
                            "Completed": row["completed_at"],
                            "Error": row["error_message"] or "",
                        }
                        for row in recent_runs
                    ]
                ),
                width="stretch",
                hide_index=True,
            )


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
                    sync_character_from_token_row(
                        connection,
                        token_row=token,
                        config=config,
                        trigger="manual_all",
                    )
                    successes += 1
                except Exception as exc:
                    st.error(f"Sync failed for {token['character_name']}: {exc}")
            if successes:
                st.success(f"Synced {successes} character(s) from EVE SSO.")
                st.rerun()

        for token in tokens:
            sync_col, forget_col = st.columns(2)
            with sync_col:
                if st.button(
                    f"Sync Now: {token['character_name']}",
                    key=f"sync_token_{token['id']}",
                    width="stretch",
                ):
                    try:
                        result = sync_character_from_token_row(
                            connection,
                            token_row=token,
                            config=config,
                            trigger="manual_character",
                        )
                    except Exception as exc:
                        st.error(f"Sync failed for {token['character_name']}: {exc}")
                    else:
                        st.success(f"{result.character_name}: {result.status}.")
                        st.rerun()
            with forget_col:
                if st.button(
                    f"Forget SSO: {token['character_name']}",
                    key=f"delete_token_{token['id']}",
                    width="stretch",
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
