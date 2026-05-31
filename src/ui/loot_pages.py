"""Streamlit page for explicit multi-character loot tracking sessions."""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from src.data.repositories import (
    get_open_loot_session,
    list_loot_session_characters,
)
from src.integrations.sso import load_sso_config
from src.services.loot_tracker_service import (
    add_manual_item,
    confirm_tracking,
    list_authorized_loot_characters,
    list_loot_items_with_holders,
    loot_history,
    next_recommended_refresh_at,
    start_tracking,
    stop_or_refresh_tracking,
)
from src.ui.components import detail_panel, metric_card, section_header
from src.ui.formatting import format_isk


def loot_tracker_page(connection: sqlite3.Connection) -> None:
    """Render start/stop asset-diff loot tracking."""

    section_header(
        "Loot Tracker",
        "Capture asset differences for several authorized characters during an activity.",
    )
    st.caption(
        "Loot Tracker reuses each character's stored EVE SSO authorization. "
        "No separate login is required when the token includes esi-assets.read_assets.v1."
    )

    session = get_open_loot_session(connection)
    if not session:
        _start_panel(connection)
    elif session["status"] == "Active":
        _active_panel(connection, session)
    else:
        _confirmation_panel(connection, session)

    _history_panel(connection)


def _start_panel(connection: sqlite3.Connection) -> None:
    section_header("Start Tracking", "Choose all characters participating in the activity.")
    tokens = list_authorized_loot_characters(connection)
    if not tokens:
        st.info(
            "No characters are authorized for asset tracking. Connect a character through "
            "EVE SSO with esi-assets.read_assets.v1 in the SP Overview controls."
        )
        return

    options = {
        f"{row['group_name']} / {row['account_name']} / {row['character_name']}": int(
            row["character_id"]
        )
        for row in tokens
    }
    selected = st.multiselect(
        "Participating characters",
        list(options),
        help="Internal transfers between selected characters are excluded from combined loot.",
    )
    notes = st.text_input("Activity notes", placeholder="Optional activity, location, or fleet note")
    if st.button("Start Tracking", type="primary"):
        try:
            session_id = start_tracking(
                connection,
                config=load_sso_config(),
                character_ids=[options[label] for label in selected],
                notes=notes,
            )
        except Exception as exc:
            st.error(f"Unable to start loot tracking: {exc}")
        else:
            st.success(f"Loot session {session_id} started.")
            st.rerun()


def _active_panel(connection: sqlite3.Connection, session: dict[str, object]) -> None:
    section_header("Active Session", "Loot tracking is recording a before-and-after asset window.")
    participants = list_loot_session_characters(connection, session_id=int(session["id"]))
    detail_panel(
        f"Session {session['id']}",
        [
            ("Status", "Tracking"),
            ("Started", str(session["started_at"])),
            ("Characters", f"{len(participants):,}"),
            ("Notes", str(session.get("notes") or "None")),
        ],
        badge="ACTIVE",
        badge_tone="success",
    )
    st.dataframe(
        [
            {
                "Group": row["group_name"],
                "Account": row["account_name"],
                "Character": row["character_name"],
            }
            for row in participants
        ],
        width="stretch",
        hide_index=True,
    )
    st.warning(
        "Character assets are cached by ESI for up to 60 minutes. The first end snapshot "
        "may still reflect the starting inventory. You can retry the end snapshot later."
    )
    if st.button("Stop Tracking And Capture Assets", type="primary"):
        _capture_end_snapshot(connection, session_id=int(session["id"]))


def _confirmation_panel(connection: sqlite3.Connection, session: dict[str, object]) -> None:
    section_header("Confirm Candidate Loot", "Review asset additions before saving the session.")
    items = list_loot_items_with_holders(connection, session_id=int(session["id"]))
    included_total = sum(
        float(item["total_value_isk"])
        for item in items
        if bool(item["included"])
    )
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("Estimated Loot Value", format_isk(included_total), "included candidate items", icon="ISK")
    with c2:
        metric_card("Candidate Items", f"{len(items):,}", "asset diff and manual rows", icon="ITM")
    with c3:
        metric_card(
            "End Snapshot",
            "Captured",
            str(session.get("end_snapshot_at") or "unknown time"),
            tone="warning",
            icon="ESI",
        )

    refresh_at = next_recommended_refresh_at(session)
    st.warning(
        "ESI assets may remain cached for up to 60 minutes. If expected loot is missing, "
        f"retry the snapshot after {refresh_at or 'the cache window'} or add it manually."
    )
    action_left, action_right = st.columns([1, 3])
    with action_left:
        if st.button("Retry End Snapshot", width="stretch"):
            _capture_end_snapshot(connection, session_id=int(session["id"]))
    with action_right:
        st.caption(
            "Combined differences exclude transfers between participating characters. "
            "Purchases, deliveries, and unrelated inventory changes still require review."
        )

    edited = _candidate_editor(
        items,
        session_id=int(session["id"]),
        snapshot_at=str(session.get("end_snapshot_at") or ""),
    )
    st.caption("Edited quantities and unit values are recalculated when the session is confirmed.")
    _manual_item_form(connection, session_id=int(session["id"]))

    if st.button("Confirm Loot Session", type="primary"):
        try:
            confirm_tracking(
                connection,
                session_id=int(session["id"]),
                items=_editable_rows(edited),
            )
        except Exception as exc:
            st.error(f"Unable to confirm loot session: {exc}")
        else:
            st.success("Loot session confirmed.")
            st.rerun()


def _capture_end_snapshot(connection: sqlite3.Connection, *, session_id: int) -> None:
    try:
        stop_or_refresh_tracking(
            connection,
            session_id=session_id,
            config=load_sso_config(),
        )
    except Exception as exc:
        st.error(f"Unable to capture assets: {exc}")
    else:
        st.success("End asset snapshot captured. Review the candidate loot.")
        st.rerun()


def _candidate_editor(
    items: list[dict[str, object]],
    *,
    session_id: int,
    snapshot_at: str,
) -> pd.DataFrame:
    if not items:
        st.info(
            "No positive asset differences were detected yet. Retry after the ESI cache "
            "window or add an item manually."
        )
    frame = pd.DataFrame(
        [
            {
                "ID": int(item["id"]),
                "Include": bool(item["included"]),
                "Item": item["item_name"],
                "Quantity": int(item["quantity"]),
                "Unit Value": float(item["unit_value_isk"]),
                "Estimated Total": float(item["total_value_isk"]),
                "Price Source": item["price_source"],
                "Current Holders": item["current_holders"],
            }
            for item in items
        ],
        columns=[
            "ID",
            "Include",
            "Item",
            "Quantity",
            "Unit Value",
            "Estimated Total",
            "Price Source",
            "Current Holders",
        ],
    )
    revision = "_".join(f"{item['id']}_{item['updated_at']}" for item in items)
    return st.data_editor(
        frame,
        width="stretch",
        hide_index=True,
        key=f"loot_candidates_{session_id}_{snapshot_at}_{revision}",
        disabled=["ID", "Item", "Estimated Total", "Price Source", "Current Holders"],
        column_config={
            "ID": st.column_config.NumberColumn("ID", format="%d"),
            "Include": st.column_config.CheckboxColumn("Include"),
            "Quantity": st.column_config.NumberColumn("Quantity", min_value=0, step=1, format="%d"),
            "Unit Value": st.column_config.NumberColumn("Unit Value", min_value=0, format="%.0f ISK"),
            "Estimated Total": st.column_config.NumberColumn("Estimated Total", format="%.0f ISK"),
        },
    )


def _manual_item_form(connection: sqlite3.Connection, *, session_id: int) -> None:
    with st.expander("Add Manual Loot Item"):
        st.caption("Use this when cached assets, sold loot, or discarded items are absent from the diff.")
        item_name = st.text_input("Item name", key=f"loot_manual_name_{session_id}")
        quantity = st.number_input(
            "Quantity",
            min_value=1,
            value=1,
            step=1,
            key=f"loot_manual_quantity_{session_id}",
        )
        unit_value = st.number_input(
            "Estimated unit value (ISK)",
            min_value=0.0,
            value=0.0,
            step=1_000_000.0,
            key=f"loot_manual_value_{session_id}",
        )
        if st.button("Add Manual Item", key=f"loot_manual_add_{session_id}"):
            try:
                add_manual_item(
                    connection,
                    session_id=session_id,
                    item_name=item_name,
                    quantity=int(quantity),
                    unit_value_isk=float(unit_value),
                )
            except Exception as exc:
                st.error(f"Unable to add manual loot item: {exc}")
            else:
                st.success("Manual loot item added.")
                st.rerun()


def _editable_rows(frame: pd.DataFrame) -> list[dict[str, object]]:
    return [
        {
            "id": int(row["ID"]),
            "included": bool(row["Include"]),
            "quantity": int(row["Quantity"]),
            "unit_value_isk": float(row["Unit Value"]),
        }
        for _, row in frame.iterrows()
    ]


def _history_panel(connection: sqlite3.Connection) -> None:
    section_header("Loot Session History", "Confirmed and open multi-character tracking windows.")
    rows = loot_history(connection)
    if not rows:
        st.info("No loot sessions recorded yet.")
        return
    st.dataframe(
        [
            {
                "Session": row["id"],
                "Status": row["status"],
                "Started": row["started_at"],
                "End Snapshot": row["end_snapshot_at"],
                "Confirmed": row["confirmed_at"],
                "Characters": row["character_count"],
                "Loot Value": row["total_value_isk"],
                "Notes": row["notes"],
            }
            for row in rows
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "Session": st.column_config.NumberColumn("Session", format="%d"),
            "Characters": st.column_config.NumberColumn("Characters", format="%d"),
            "Loot Value": st.column_config.NumberColumn("Loot Value", format="%.0f ISK"),
        },
    )
