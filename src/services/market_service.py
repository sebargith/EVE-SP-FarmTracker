"""Market price ingestion and valuation services."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from src.data.repositories import (
    add_market_snapshot,
    latest_asset_quantities_by_type,
    latest_market_snapshots,
)
from src.integrations.esi_public import (
    EsiPublicClient,
    JITA_4_4_STATION_ID,
    LARGE_SKILL_INJECTOR_TYPE_ID,
    MARKET_ITEM_NAMES,
    PLEX_TYPE_ID,
    SKILL_EXTRACTOR_TYPE_ID,
    THE_FORGE_REGION_ID,
    PublicMarketSnapshot,
    fetch_market_snapshot,
)


TRACKED_MARKET_TYPES = (
    PLEX_TYPE_ID,
    SKILL_EXTRACTOR_TYPE_ID,
    LARGE_SKILL_INJECTOR_TYPE_ID,
)


@dataclass(frozen=True)
class AssetValuation:
    group_name: str
    account_name: str
    character_name: str
    type_id: int
    item_name: str
    quantity: int
    unit_sell_price: float | None
    unit_buy_price: float | None
    estimated_sell_value: float | None
    estimated_buy_value: float | None


@dataclass(frozen=True)
class MarketScenarioOverrides:
    plex_cost_basis_isk: float | None
    large_skill_injector_sell_price_isk: float | None
    skill_extractor_market_buy_price_isk: float | None
    timestamp: str | None
    source_summary: str

    @property
    def has_any_price(self) -> bool:
        return any(
            value is not None
            for value in (
                self.plex_cost_basis_isk,
                self.large_skill_injector_sell_price_isk,
                self.skill_extractor_market_buy_price_isk,
            )
        )


def sync_market_snapshots(
    connection: sqlite3.Connection,
    *,
    region_id: int = THE_FORGE_REGION_ID,
    location_id: int | None = JITA_4_4_STATION_ID,
    client: EsiPublicClient | None = None,
) -> list[PublicMarketSnapshot]:
    """Fetch and store current market snapshots for tracked SP farm items."""

    owns_client = client is None
    esi_client = client or EsiPublicClient()
    try:
        snapshots = [
            fetch_market_snapshot(
                type_id=type_id,
                item_name=MARKET_ITEM_NAMES[type_id],
                region_id=region_id,
                location_id=location_id,
                client=esi_client,
            )
            for type_id in TRACKED_MARKET_TYPES
        ]
    finally:
        if owns_client:
            esi_client.close()

    for snapshot in snapshots:
        add_market_snapshot(
            connection,
            region_id=snapshot.region_id,
            location_id=snapshot.location_id,
            type_id=snapshot.type_id,
            item_name=snapshot.item_name,
            best_buy_price=snapshot.best_buy_price,
            best_sell_price=snapshot.best_sell_price,
            buy_volume=snapshot.buy_volume,
            sell_volume=snapshot.sell_volume,
            order_count=snapshot.order_count,
            average_price=snapshot.average_price,
            adjusted_price=snapshot.adjusted_price,
            price_source=snapshot.price_source,
        )
    return snapshots


def latest_market_overview(connection: sqlite3.Connection) -> list[dict[str, object]]:
    """Return latest price rows for tracked market types."""

    return latest_market_snapshots(connection, type_ids=TRACKED_MARKET_TYPES)


def latest_market_scenario_overrides(
    connection: sqlite3.Connection,
) -> MarketScenarioOverrides:
    """Return scenario-market inputs derived from latest public market snapshots."""

    rows = latest_market_overview(connection)
    prices = {int(row["type_id"]): row for row in rows}
    timestamps = [str(row["timestamp"]) for row in rows if row.get("timestamp")]
    source_parts = [
        f"{row['item_name']}: {row.get('price_source', 'unknown')}"
        for row in rows
    ]

    return MarketScenarioOverrides(
        plex_cost_basis_isk=_scenario_reference_price(prices.get(PLEX_TYPE_ID)),
        large_skill_injector_sell_price_isk=_scenario_reference_price(
            prices.get(LARGE_SKILL_INJECTOR_TYPE_ID)
        ),
        skill_extractor_market_buy_price_isk=_scenario_reference_price(
            prices.get(SKILL_EXTRACTOR_TYPE_ID)
        ),
        timestamp=max(timestamps) if timestamps else None,
        source_summary=", ".join(source_parts) if source_parts else "No market snapshots",
    )


def asset_valuations(connection: sqlite3.Connection) -> list[AssetValuation]:
    """Value tracked character assets using latest market snapshots."""

    price_rows = latest_market_overview(connection)
    prices = {int(row["type_id"]): row for row in price_rows}
    asset_rows = latest_asset_quantities_by_type(
        connection,
        type_ids=TRACKED_MARKET_TYPES,
    )

    valuations: list[AssetValuation] = []
    for asset in asset_rows:
        type_id = int(asset["type_id"])
        quantity = int(asset["quantity"] or 0)
        price = prices.get(type_id, {})
        best_sell = _optional_float(price.get("best_sell_price"))
        best_buy = _optional_float(price.get("best_buy_price"))
        reference_sell = best_sell or _optional_float(price.get("average_price"))
        valuations.append(
            AssetValuation(
                group_name=str(asset["group_name"]),
                account_name=str(asset["account_name"]),
                character_name=str(asset["character_name"]),
                type_id=type_id,
                item_name=MARKET_ITEM_NAMES.get(type_id, f"Type {type_id}"),
                quantity=quantity,
                unit_sell_price=reference_sell,
                unit_buy_price=best_buy,
                estimated_sell_value=quantity * reference_sell if reference_sell is not None else None,
                estimated_buy_value=quantity * best_buy if best_buy is not None else None,
            )
        )
    return valuations


def _optional_float(value: object) -> float | None:
    return float(value) if value is not None else None


def _scenario_reference_price(row: dict[str, object] | None) -> float | None:
    if not row:
        return None
    for key in ("best_sell_price", "average_price", "best_buy_price"):
        value = row.get(key)
        if value is not None:
            return float(value)
    return None
