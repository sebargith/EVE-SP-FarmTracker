"""Automatic public-market valuation for clipboard loot tracking."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from src.data.repositories import (
    apply_loot_item_prices,
    list_loot_item_price_cache,
    list_loot_session_items,
    upsert_loot_item_price_cache,
)
from src.integrations.esi_public import (
    EsiPublicClient,
    JITA_4_4_STATION_ID,
    THE_FORGE_REGION_ID,
)


LOOT_PRICE_CACHE_TTL = timedelta(minutes=5)
_WHITESPACE = re.compile(r"\s+")
_PUBLIC_PRICE_SOURCES = frozenset(("Jita Buy", "Estimated"))


@dataclass(frozen=True)
class LootPriceRefreshSummary:
    jita_buy_count: int
    estimated_count: int
    pasted_estimate_count: int
    unpriced_count: int
    priced_at: str | None


def refresh_loot_prices(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    force_refresh: bool = False,
    client: EsiPublicClient | None = None,
    now: datetime | None = None,
) -> LootPriceRefreshSummary:
    """Apply cached or freshly fetched Jita buy values to one loot run."""

    timestamp = now or datetime.now(timezone.utc)
    rows = list_loot_session_items(connection, session_id=session_id)
    if not rows:
        return _summary([], {})

    normalized_names = [_normalized_row_name(row) for row in rows]
    cache = _cache_by_name(connection, normalized_names=normalized_names)
    stale_rows = [
        row
        for row in rows
        if force_refresh or _is_stale(cache.get(_normalized_row_name(row)), now=timestamp)
    ]
    if stale_rows:
        updates = _fetch_price_updates(stale_rows, cache=cache, client=client, now=timestamp)
        upsert_loot_item_price_cache(connection, items=updates)
        cache = _cache_by_name(connection, normalized_names=normalized_names)

    valuations = [_valuation_for_row(row, cache=cache) for row in rows]
    apply_loot_item_prices(connection, session_id=session_id, items=valuations)
    return _summary(valuations, cache)


def loot_price_status(
    connection: sqlite3.Connection,
    *,
    session_id: int,
) -> LootPriceRefreshSummary:
    """Describe the single displayed valuation source for a loot run."""

    rows = list_loot_session_items(connection, session_id=session_id)
    cache = _cache_by_name(
        connection,
        normalized_names=[_normalized_row_name(row) for row in rows],
    )
    return _summary(rows, cache)


def normalize_item_name(item_name: str) -> str:
    return _WHITESPACE.sub(" ", item_name.strip()).casefold()


def _fetch_price_updates(
    rows: list[dict[str, Any]],
    *,
    cache: dict[str, dict[str, Any]],
    client: EsiPublicClient | None,
    now: datetime,
) -> list[dict[str, Any]]:
    owns_client = client is None
    esi_client = client or EsiPublicClient()
    try:
        names_to_resolve = [
            str(row["item_name"])
            for row in rows
            if not _cached_type_id(cache.get(_normalized_row_name(row)))
        ]
        resolved_names = (
            esi_client.resolve_inventory_type_ids(names_to_resolve)
            if names_to_resolve
            else {}
        )
        resolved_ids = {
            normalize_item_name(name): int(type_id)
            for name, type_id in resolved_names.items()
        }
        type_ids = {
            _resolved_type_id(row, cache=cache, resolved_ids=resolved_ids)
            for row in rows
        }
        averages = esi_client.get_market_prices() if any(type_ids) else {}

        updates: list[dict[str, Any]] = []
        for row in rows:
            normalized_name = _normalized_row_name(row)
            type_id = _resolved_type_id(row, cache=cache, resolved_ids=resolved_ids)
            unit_value = 0.0
            source = "Unpriced"
            if type_id is not None:
                try:
                    orders = esi_client.get_market_orders(
                        region_id=THE_FORGE_REGION_ID,
                        type_id=type_id,
                        order_type="buy",
                    )
                except Exception:
                    orders = []
                jita_buy = max(
                    (
                        float(order["price"])
                        for order in orders
                        if bool(order.get("is_buy_order", False))
                        and int(order.get("location_id", 0)) == JITA_4_4_STATION_ID
                    ),
                    default=None,
                )
                average = averages.get(type_id, {}).get("average_price")
                if jita_buy is not None:
                    unit_value = float(jita_buy)
                    source = "Jita Buy"
                elif average is not None:
                    unit_value = float(average)
                    source = "Estimated"

            updates.append(
                {
                    "normalized_name": normalized_name,
                    "item_name": str(row["item_name"]),
                    "type_id": type_id,
                    "unit_value_isk": unit_value,
                    "price_source": source,
                    "priced_at": now.isoformat(),
                }
            )
        return updates
    finally:
        if owns_client:
            esi_client.close()


def _valuation_for_row(
    row: dict[str, Any],
    *,
    cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    normalized_name = _normalized_row_name(row)
    cached = cache.get(normalized_name)
    if cached and float(cached["unit_value_isk"]) > 0:
        unit_value = float(cached["unit_value_isk"])
        source = str(cached["price_source"])
        type_id = _cached_type_id(cached)
    elif float(row["unit_value_isk"]) > 0 and "pasted" in str(row["price_source"]).casefold():
        unit_value = float(row["unit_value_isk"])
        source = "Pasted Estimate"
        type_id = _cached_type_id(cached)
    else:
        unit_value = 0.0
        source = "Unpriced"
        type_id = _cached_type_id(cached)
    return {
        "id": int(row["id"]),
        "normalized_name": normalized_name,
        "quantity": int(row["quantity"]),
        "type_id": type_id,
        "unit_value_isk": unit_value,
        "price_source": source,
    }


def _summary(
    rows: list[dict[str, Any]],
    cache: dict[str, dict[str, Any]],
) -> LootPriceRefreshSummary:
    sources = [str(row["price_source"]) for row in rows]
    priced_times = [
        str(cached["priced_at"])
        for cached in cache.values()
        if str(cached["price_source"]) in _PUBLIC_PRICE_SOURCES
    ]
    return LootPriceRefreshSummary(
        jita_buy_count=sources.count("Jita Buy"),
        estimated_count=sources.count("Estimated"),
        pasted_estimate_count=sources.count("Pasted Estimate"),
        unpriced_count=sources.count("Unpriced"),
        priced_at=min(priced_times) if priced_times else None,
    )


def _cache_by_name(
    connection: sqlite3.Connection,
    *,
    normalized_names: list[str],
) -> dict[str, dict[str, Any]]:
    return {
        str(row["normalized_name"]): row
        for row in list_loot_item_price_cache(
            connection,
            normalized_names=tuple(sorted(set(normalized_names))),
        )
    }


def _is_stale(cached: dict[str, Any] | None, *, now: datetime) -> bool:
    if not cached:
        return True
    try:
        priced_at = datetime.fromisoformat(str(cached["priced_at"]))
    except ValueError:
        return True
    if priced_at.tzinfo is None:
        priced_at = priced_at.replace(tzinfo=timezone.utc)
    return now - priced_at >= LOOT_PRICE_CACHE_TTL


def _resolved_type_id(
    row: dict[str, Any],
    *,
    cache: dict[str, dict[str, Any]],
    resolved_ids: dict[str, int],
) -> int | None:
    normalized_name = _normalized_row_name(row)
    return _cached_type_id(cache.get(normalized_name)) or resolved_ids.get(normalized_name)


def _cached_type_id(cached: dict[str, Any] | None) -> int | None:
    if not cached or cached.get("type_id") is None:
        return None
    return int(cached["type_id"])


def _normalized_row_name(row: dict[str, Any]) -> str:
    return str(row.get("normalized_name") or normalize_item_name(str(row["item_name"])))
