"""Streamlit page for appraisal-style clipboard loot tracking."""

from __future__ import annotations

import sqlite3
from datetime import datetime

import streamlit as st

from src.data.repositories import list_character_rows
from src.services.loot_pricing_service import loot_price_status, refresh_loot_prices
from src.services.loot_tracker_service import (
    active_session,
    add_filter,
    current_items,
    exclude_item,
    excluded_items,
    import_cargo_text,
    loot_history,
    remove_filter,
    remove_item,
    start_tracking,
    stop_tracking,
    update_item,
)
from src.ui.components import section_header
from src.ui.formatting import format_isk


def loot_tracker_page(connection: sqlite3.Connection) -> None:
    """Render cumulative manual cargo-paste tracking."""

    section_header(
        "Loot Tracker",
        "Paste cargo repeatedly and track the total until you stop the session.",
    )

    session = active_session(connection)
    if not session:
        _start_panel(connection)
    else:
        _active_panel(connection, session)

    _filters_panel(connection, session_id=int(session["id"]) if session else None)
    _history_panel(connection)


def _start_panel(connection: sqlite3.Connection) -> None:
    if st.button("Start Tracking", type="primary"):
        try:
            start_tracking(connection)
        except Exception as exc:
            st.error(f"Unable to start loot tracking: {exc}")
        else:
            st.rerun()
    st.caption("Start one session, paste cargo as you loot, then stop it to save the total.")


def _active_panel(connection: sqlite3.Connection, session: dict[str, object]) -> None:
    session_id = int(session["id"])
    items = current_items(connection, session_id=session_id)
    total_value = sum(float(item["total_value_isk"]) for item in items)

    _summary_panel(connection, session_id=session_id, total_value=total_value, item_count=len(items))
    _action_row(connection, session_id=session_id)
    _paste_panel(connection, session_id=session_id)
    _current_items_panel(connection, session_id=session_id, items=items)


def _summary_panel(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    total_value: float,
    item_count: int,
) -> None:
    summary = loot_price_status(connection, session_id=session_id)
    priced_at = _format_price_time(summary.priced_at)
    st.markdown(
        f"""
        <div class="eve-loot-summary">
            <div>
                <div class="eve-loot-total-label">Total Loot Value</div>
                <div class="eve-loot-total-value">{format_isk(total_value)}</div>
                <div class="eve-loot-total-subtitle">Jita buy valuation</div>
            </div>
            <div class="eve-loot-summary-meta">
                <span><strong>{item_count:,}</strong> item types</span>
                <span><strong>{summary.estimated_count:,}</strong> estimated</span>
                <span>prices: {priced_at}</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _action_row(connection: sqlite3.Connection, *, session_id: int) -> None:
    refresh, stop, description = st.columns([1.15, 1.25, 5])
    if refresh.button("Refresh Prices", key=f"loot_refresh_prices_{session_id}"):
        try:
            refresh_loot_prices(connection, session_id=session_id, force_refresh=True)
        except Exception as exc:
            st.error(f"Unable to refresh Jita buy prices: {exc}")
        else:
            st.rerun()
    if stop.button("Stop Session", type="primary"):
        try:
            stop_tracking(connection, session_id=session_id)
        except Exception as exc:
            st.error(f"Unable to stop loot tracking: {exc}")
        else:
            st.rerun()
    description.caption("Automatic public Jita buy prices. No extra EVE authorization required.")


def _paste_panel(connection: sqlite3.Connection, *, session_id: int) -> None:
    section_header("Add Cargo")
    characters = list_character_rows(connection)
    character_options = {"Unassigned / combined cargo": None}
    character_options.update(
        {
            f"{row['group_name']} / {row['account_name']} / {row['character_name']}": int(
                row["character_id"]
            )
            for row in characters
        }
    )
    cargo_version_key = f"loot_cargo_text_version_{session_id}"
    cargo_version = int(st.session_state.get(cargo_version_key, 0))
    if cargo_version:
        st.session_state.pop(f"loot_cargo_text_{session_id}_{cargo_version - 1}", None)
    cargo_key = f"loot_cargo_text_{session_id}_{cargo_version}"
    source, cargo = st.columns([1.8, 4.2])
    selected_character = source.selectbox(
        "Source character",
        list(character_options),
        help="Optional local label for this pasted cargo batch.",
        key=f"loot_source_character_{session_id}",
    )
    cargo_text = cargo.text_area(
        "Cargo clipboard",
        placeholder="Paste copied EVE inventory rows here",
        height=105,
        key=cargo_key,
    )
    if source.button("Count Loot", type="primary", key=f"loot_add_paste_{session_id}"):
        try:
            summary = import_cargo_text(
                connection,
                session_id=session_id,
                raw_text=cargo_text,
                character_id=character_options[selected_character],
            )
        except Exception as exc:
            st.error(f"Unable to add pasted cargo: {exc}")
        else:
            message = (
                f"Added {summary.accepted_item_count:,} item row(s) from paste "
                f"{summary.import_id}."
            )
            if summary.ignored_item_count:
                message += f" Ignored by filters: {summary.ignored_item_count:,}."
            if summary.pricing_error:
                st.warning(
                    f"{message} Cargo was saved, but automatic pricing could not refresh: "
                    f"{summary.pricing_error}"
                )
            else:
                st.success(f"{message} Jita buy values refreshed.")
            st.session_state[cargo_version_key] = cargo_version + 1
            st.rerun()


def _current_items_panel(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    items: list[dict[str, object]],
) -> None:
    section_header("Looted Items")
    if not items:
        st.info("No loot items added yet. Paste cargo to begin tracking.")
        return

    header = st.columns([4, 1.3, 2, 2, 2, 0.55, 0.95])
    for column, label in zip(
        header,
        ("Item", "Quantity", "Unit Value", "Total Value", "Value Source", "", ""),
    ):
        column.caption(label)

    for item in items:
        item_id = int(item["id"])
        columns = st.columns([4, 1.3, 2, 2, 2, 0.55, 0.95])
        columns[0].markdown(f"**{item['item_name']}**")
        quantity = columns[1].number_input(
            "Quantity",
            min_value=0,
            value=int(item["quantity"]),
            step=1,
            label_visibility="collapsed",
            key=f"loot_quantity_{session_id}_{item_id}_{item['updated_at']}",
        )
        unit_value = float(item["unit_value_isk"])
        columns[2].markdown(format_isk(unit_value))
        columns[3].markdown(format_isk(int(quantity) * unit_value))
        columns[4].caption(str(item["price_source"]))
        if columns[5].button(
            "X",
            key=f"loot_remove_{session_id}_{item_id}",
            help=f"Remove {item['item_name']} from this tracking run",
        ):
            remove_item(connection, session_id=session_id, item_id=item_id)
            st.rerun()
        if columns[6].button(
            "Filter",
            key=f"loot_filter_{session_id}_{item_id}",
            help=f"Ignore {item['item_name']} in future cargo pastes",
        ):
            exclude_item(connection, session_id=session_id, item_id=item_id)
            st.rerun()
        if int(quantity) != int(item["quantity"]):
            update_item(
                connection,
                session_id=session_id,
                item_id=item_id,
                quantity=int(quantity),
                unit_value_isk=unit_value,
            )
            st.rerun()


def _format_price_time(priced_at: str | None) -> str:
    if not priced_at:
        return "pending"
    try:
        return f"{datetime.fromisoformat(priced_at):%H:%M} UTC"
    except ValueError:
        return "cached"


def _filters_panel(connection: sqlite3.Connection, *, session_id: int | None) -> None:
    with st.expander("Automatic Item Filters"):
        st.caption("Filtered item names are ignored automatically in future cargo pastes.")
        item_name = st.text_input("Item name to exclude", key="loot_filter_name")
        if st.button("Add Filter", key="loot_filter_add"):
            try:
                add_filter(connection, item_name=item_name, session_id=session_id)
            except Exception as exc:
                st.error(f"Unable to add filter: {exc}")
            else:
                st.success("Loot filter added.")
                st.rerun()

        rows = excluded_items(connection)
        if not rows:
            st.caption("No automatic item filters configured.")
            return
        for row in rows:
            label, action = st.columns([6, 1])
            label.markdown(f"**{row['item_name']}**")
            if action.button(
                "X",
                key=f"loot_filter_remove_{row['normalized_name']}",
                help=f"Remove filter for {row['item_name']}",
            ):
                remove_filter(connection, normalized_name=str(row["normalized_name"]))
                st.rerun()


def _history_panel(connection: sqlite3.Connection) -> None:
    rows = [row for row in loot_history(connection, limit=8) if row["status"] == "Confirmed"]
    with st.expander("Previous Sessions"):
        if not rows:
            st.caption("No completed sessions yet.")
            return
        st.dataframe(
            [
                {
                    "Ended": row["confirmed_at"],
                    "Loot Value": row["total_value_isk"],
                }
                for row in rows
            ],
            width="stretch",
            height=min(35 + len(rows) * 35, 245),
            hide_index=True,
            column_config={
                "Loot Value": st.column_config.NumberColumn("Loot Value", format="%.0f ISK"),
            },
        )
