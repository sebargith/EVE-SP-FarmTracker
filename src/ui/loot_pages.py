"""Streamlit page for appraisal-style clipboard loot tracking."""

from __future__ import annotations

import sqlite3

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
    import_history,
    loot_history,
    remove_filter,
    remove_item,
    start_tracking,
    stop_tracking,
    update_item,
)
from src.ui.components import detail_panel, metric_card, section_header
from src.ui.formatting import format_isk


def loot_tracker_page(connection: sqlite3.Connection) -> None:
    """Render cumulative manual cargo-paste tracking."""

    section_header(
        "Loot Tracker",
        "Paste cargo blocks repeatedly and track cumulative looted value until you stop the run.",
    )
    st.caption(
        "Copy items from EVE cargo and paste them here. Loot Tracker values them from public "
        "Jita buy orders; it does not use ESI asset refreshes or require another authorization."
    )

    session = active_session(connection)
    if not session:
        _start_panel(connection)
    else:
        _active_panel(connection, session)

    _filters_panel(connection, session_id=int(session["id"]) if session else None)
    _history_panel(connection)


def _start_panel(connection: sqlite3.Connection) -> None:
    section_header("Start Tracking", "Open one cumulative loot run before pasting cargo.")
    notes = st.text_input(
        "Tracking notes",
        placeholder="Optional activity, system, fleet, or character-group note",
    )
    if st.button("Start Tracking", type="primary"):
        try:
            session_id = start_tracking(connection, notes=notes)
        except Exception as exc:
            st.error(f"Unable to start loot tracking: {exc}")
        else:
            st.success(f"Loot tracking run {session_id} started.")
            st.rerun()


def _active_panel(connection: sqlite3.Connection, session: dict[str, object]) -> None:
    session_id = int(session["id"])
    items = current_items(connection, session_id=session_id)
    imports = import_history(connection, session_id=session_id)
    total_value = sum(float(item["total_value_isk"]) for item in items)

    section_header("Active Tracking Run", "Each paste adds another cargo batch to the running total.")
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("Total Looted Value", format_isk(total_value), "Jita buy valuation", icon="ISK")
    with c2:
        metric_card("Tracked Items", f"{len(items):,}", "unique item names", icon="ITM")
    with c3:
        metric_card("Cargo Imports", f"{len(imports):,}", "pasted batches", icon="PST")

    detail_panel(
        f"Tracking Run {session_id}",
        [
            ("Status", "Tracking"),
            ("Started", str(session["started_at"])),
            ("Notes", str(session.get("notes") or "None")),
        ],
        badge="ACTIVE",
        badge_tone="success",
    )

    _price_panel(connection, session_id=session_id)
    _paste_panel(connection, session_id=session_id)
    _current_items_panel(connection, session_id=session_id, items=items)
    _imports_panel(imports)

    if st.button("Stop Global Tracking", type="primary"):
        try:
            stop_tracking(connection, session_id=session_id)
        except Exception as exc:
            st.error(f"Unable to stop loot tracking: {exc}")
        else:
            st.success("Loot tracking run saved.")
            st.rerun()


def _paste_panel(connection: sqlite3.Connection, *, session_id: int) -> None:
    section_header("Paste Cargo", "Paste one or more cargo exports during the active run.")
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
    selected_character = st.selectbox(
        "Source character",
        list(character_options),
        help="Optional label for this pasted cargo batch. SSO is not required.",
        key=f"loot_source_character_{session_id}",
    )
    cargo_version_key = f"loot_cargo_text_version_{session_id}"
    cargo_version = int(st.session_state.get(cargo_version_key, 0))
    if cargo_version:
        st.session_state.pop(f"loot_cargo_text_{session_id}_{cargo_version - 1}", None)
    cargo_key = f"loot_cargo_text_{session_id}_{cargo_version}"
    cargo_text = st.text_area(
        "Cargo clipboard",
        placeholder=(
            "Paste copied EVE inventory rows here.\n"
            "Example: Item Name<TAB>Quantity<TAB>...<TAB>Estimated Price ISK"
        ),
        height=180,
        key=cargo_key,
    )
    if st.button("Add Pasted Cargo", type="primary", key=f"loot_add_paste_{session_id}"):
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


def _price_panel(connection: sqlite3.Connection, *, session_id: int) -> None:
    action, status = st.columns([1.4, 5])
    if action.button("Refresh Prices", key=f"loot_refresh_prices_{session_id}"):
        try:
            refresh_loot_prices(connection, session_id=session_id, force_refresh=True)
        except Exception as exc:
            st.error(f"Unable to refresh Jita buy prices: {exc}")
        else:
            st.rerun()

    summary = loot_price_status(connection, session_id=session_id)
    caption = (
        "Automatic valuation uses Jita buy orders. "
        "When no Jita buy order exists, the row is marked Estimated."
    )
    if summary.priced_at:
        caption += f" Prices cached for five minutes. Oldest active market price: {summary.priced_at}."
    status.caption(caption)


def _current_items_panel(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    items: list[dict[str, object]],
) -> None:
    section_header("Cumulative Loot", "Edit quantities, remove a row, or filter it from future pastes.")
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


def _imports_panel(imports: list[dict[str, object]]) -> None:
    section_header("Paste History", "Every cargo import remains attached to the active run.")
    if not imports:
        st.caption("No cargo batches pasted yet.")
        return
    st.dataframe(
        [
            {
                "Paste": row["id"],
                "Imported": row["imported_at"],
                "Character": row["character_name"] or "Unassigned / combined cargo",
                "Parsed Rows": row["parsed_item_count"],
                "Accepted Rows": row["accepted_item_count"],
                "Filtered Rows": row["ignored_item_count"],
            }
            for row in imports
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "Paste": st.column_config.NumberColumn("Paste", format="%d"),
            "Parsed Rows": st.column_config.NumberColumn("Parsed Rows", format="%d"),
            "Accepted Rows": st.column_config.NumberColumn("Accepted Rows", format="%d"),
            "Filtered Rows": st.column_config.NumberColumn("Filtered Rows", format="%d"),
        },
    )


def _history_panel(connection: sqlite3.Connection) -> None:
    section_header("Loot Tracking History", "Saved global tracking runs and their cumulative totals.")
    rows = loot_history(connection)
    if not rows:
        st.info("No loot tracking runs recorded yet.")
        return
    st.dataframe(
        [
            {
                "Run": row["id"],
                "Status": row["status"],
                "Started": row["started_at"],
                "Stopped": row["confirmed_at"],
                "Loot Value": row["total_value_isk"],
                "Notes": row["notes"],
            }
            for row in rows
        ],
        width="stretch",
        hide_index=True,
        column_config={
            "Run": st.column_config.NumberColumn("Run", format="%d"),
            "Loot Value": st.column_config.NumberColumn("Loot Value", format="%.0f ISK"),
        },
    )
