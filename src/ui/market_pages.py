"""Streamlit page sections for public market data."""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from src.services.market_service import asset_valuations, latest_market_overview, sync_market_snapshots
from src.ui.components import detail_panel, metric_card, section_header
from src.ui.formatting import format_isk


def market_page(connection: sqlite3.Connection) -> None:
    """Render public market data and tracked asset valuation."""

    section_header(
        "Market Monitor",
        "Public ESI prices for PLEX, Large Skill Injectors, and Skill Extractors.",
    )
    action_left, action_right = st.columns([1, 3])
    with action_left:
        if st.button("Sync Market Prices", width="stretch"):
            try:
                snapshots = sync_market_snapshots(connection)
            except Exception as exc:
                st.error(f"Market sync failed: {exc}")
            else:
                st.success(f"Synced {len(snapshots)} market price snapshot(s).")
                st.rerun()
    with action_right:
        st.caption("Market data supports planning. It is not a guarantee of execution price.")

    latest_prices = latest_market_overview(connection)
    if not latest_prices:
        st.info("No market snapshots yet. Run Sync Market Prices.")
    else:
        _price_kpis(latest_prices)
        section_header("Current Market Snapshot")
        _price_table(latest_prices)

    section_header(
        "Tracked Asset Valuation",
        "Values synced LSI, extractor, and PLEX assets when present.",
    )
    valuations = asset_valuations(connection)
    if not valuations:
        st.info("No tracked LSI, Skill Extractor, or PLEX assets found on synced characters.")
        return

    rows = [
        {
            "Group": row.group_name,
            "Account": row.account_name,
            "Character": row.character_name,
            "Asset": row.item_name,
            "Quantity": row.quantity,
            "Unit Sell": row.unit_sell_price,
            "Unit Buy": row.unit_buy_price,
            "Sell Value": row.estimated_sell_value,
            "Buy Value": row.estimated_buy_value,
        }
        for row in valuations
    ]
    df = pd.DataFrame(rows)
    total_sell = sum(row.estimated_sell_value or 0 for row in valuations)
    total_buy = sum(row.estimated_buy_value or 0 for row in valuations)
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("Estimated Sell Value", format_isk(total_sell), "latest reference sell", icon="ISK")
    with c2:
        metric_card("Estimated Buy Value", format_isk(total_buy), "latest buy side", icon="BUY")
    with c3:
        metric_card("Tracked Stacks", f"{len(valuations):,}", "asset type rows", icon="AST")

    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "Quantity": st.column_config.NumberColumn("Quantity", format="%d"),
            "Unit Sell": st.column_config.NumberColumn("Unit Sell", format="%.0f ISK"),
            "Unit Buy": st.column_config.NumberColumn("Unit Buy", format="%.0f ISK"),
            "Sell Value": st.column_config.NumberColumn("Sell Value", format="%.0f ISK"),
            "Buy Value": st.column_config.NumberColumn("Buy Value", format="%.0f ISK"),
        },
    )


def _price_kpis(rows: list[dict[str, object]]) -> None:
    columns = st.columns(3)
    for column, row in zip(columns, rows):
        with column:
            sell = row.get("best_sell_price")
            buy = row.get("best_buy_price")
            average = row.get("average_price")
            if sell is not None:
                value = format_isk(float(sell))
                delta = f"buy {format_isk(float(buy))}" if buy is not None else "no buy orders"
            elif average is not None:
                value = format_isk(float(average))
                delta = "ESI market average"
            else:
                value = "n/a"
                delta = "no public price"
            metric_card(
                str(row["item_name"]),
                value,
                delta,
                tone="neutral" if value != "n/a" else "warning",
                icon=_market_icon(str(row["item_name"])),
            )


def _price_table(rows: list[dict[str, object]]) -> None:
    df = pd.DataFrame(
        [
            {
                "Item": row["item_name"],
                "Best Buy": row["best_buy_price"],
                "Best Sell": row["best_sell_price"],
                "Average": row["average_price"],
                "Buy Volume": row["buy_volume"],
                "Sell Volume": row["sell_volume"],
                "Orders": row["order_count"],
                "Price Source": row["price_source"],
                "Location": "Jita 4-4" if row["location_id"] else "The Forge",
                "Timestamp": row["timestamp"],
            }
            for row in rows
        ]
    )
    st.dataframe(
        df,
        width="stretch",
        hide_index=True,
        column_config={
            "Best Buy": st.column_config.NumberColumn("Best Buy", format="%.0f ISK"),
            "Best Sell": st.column_config.NumberColumn("Best Sell", format="%.0f ISK"),
            "Average": st.column_config.NumberColumn("Average", format="%.0f ISK"),
            "Buy Volume": st.column_config.NumberColumn("Buy Volume", format="%d"),
            "Sell Volume": st.column_config.NumberColumn("Sell Volume", format="%d"),
            "Orders": st.column_config.NumberColumn("Orders", format="%d"),
        },
    )

    latest_timestamp = max(str(row["timestamp"]) for row in rows if row.get("timestamp"))
    detail_panel(
        "Market Data State",
        [
            ("Tracked items", f"{len(rows):,}"),
            ("Latest snapshot", latest_timestamp),
            ("Region", "The Forge"),
            ("Primary hub", "Jita 4-4 when order book exists"),
        ],
        badge="ESI",
        badge_tone="success",
    )


def _market_icon(item_name: str) -> str:
    if "PLEX" in item_name:
        return "PLX"
    if "Injector" in item_name:
        return "LSI"
    if "Extractor" in item_name:
        return "EXT"
    return "MKT"
