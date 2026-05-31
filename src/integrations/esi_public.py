"""Public ESI integration helpers and market stubs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


THE_FORGE_REGION_ID = 10000002
JITA_4_4_STATION_ID = 60003760
PLEX_TYPE_ID = 44992
SKILL_EXTRACTOR_TYPE_ID = 40519
LARGE_SKILL_INJECTOR_TYPE_ID = 40520
MARKET_ITEM_NAMES = {
    PLEX_TYPE_ID: "PLEX",
    SKILL_EXTRACTOR_TYPE_ID: "Skill Extractor",
    LARGE_SKILL_INJECTOR_TYPE_ID: "Large Skill Injector",
}


@dataclass(frozen=True)
class PublicMarketSnapshot:
    region_id: int
    location_id: int | None
    type_id: int
    item_name: str
    best_buy_price: float | None
    best_sell_price: float | None
    average_price: float | None
    adjusted_price: float | None
    buy_volume: int
    sell_volume: int
    order_count: int
    price_source: str


class EsiPublicClient:
    """Small public ESI client for market and inventory metadata."""

    def __init__(
        self,
        *,
        base_url: str = "https://esi.evetech.net/latest",
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=30)
        self.headers = {
            "User-Agent": "EVE SP Farm Planner/0.1 local",
            "X-Compatibility-Date": _compatibility_date(),
        }

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def get_market_orders(
        self,
        *,
        region_id: int,
        type_id: int,
        order_type: str = "all",
    ) -> list[dict[str, Any]]:
        return self._get_paginated(
            f"/markets/{int(region_id)}/orders/",
            params={
                "datasource": "tranquility",
                "order_type": order_type,
                "type_id": int(type_id),
            },
        )

    def get_market_prices(self) -> dict[int, dict[str, float]]:
        response = self.client.get(
            f"{self.base_url}/markets/prices/",
            headers=self.headers,
            params={"datasource": "tranquility"},
        )
        response.raise_for_status()
        return {
            int(row["type_id"]): {
                key: float(row[key])
                for key in ("average_price", "adjusted_price")
                if key in row
            }
            for row in response.json()
        }

    def resolve_inventory_type_ids(self, names: list[str] | tuple[str, ...]) -> dict[str, int]:
        """Resolve exact inventory type names through the public universe endpoint."""

        unique_names = sorted({str(name).strip() for name in names if str(name).strip()})
        if not unique_names:
            return {}

        response = self.client.post(
            f"{self.base_url}/universe/ids/",
            headers=self.headers,
            params={"datasource": "tranquility"},
            json=unique_names,
        )
        response.raise_for_status()
        return {
            str(item["name"]): int(item["id"])
            for item in response.json().get("inventory_types", [])
        }

    def _get_paginated(self, path: str, *, params: dict[str, Any]) -> list[dict[str, Any]]:
        first_response = self.client.get(
            f"{self.base_url}{path}",
            headers=self.headers,
            params={**params, "page": 1},
        )
        first_response.raise_for_status()
        results = list(first_response.json())
        pages = int(first_response.headers.get("X-Pages", "1"))
        for page in range(2, pages + 1):
            response = self.client.get(
                f"{self.base_url}{path}",
                headers=self.headers,
                params={**params, "page": page},
            )
            response.raise_for_status()
            results.extend(response.json())
        return results


def fetch_market_snapshot(
    *,
    type_id: int,
    item_name: str | None = None,
    region_id: int = THE_FORGE_REGION_ID,
    location_id: int | None = JITA_4_4_STATION_ID,
    client: EsiPublicClient | None = None,
) -> PublicMarketSnapshot:
    """Fetch and summarize public market orders for one inventory type."""

    owns_client = client is None
    esi_client = client or EsiPublicClient()
    try:
        orders = esi_client.get_market_orders(region_id=region_id, type_id=type_id)
        market_prices = esi_client.get_market_prices()
    finally:
        if owns_client:
            esi_client.close()

    return summarize_market_orders(
        orders,
        region_id=region_id,
        location_id=location_id,
        type_id=type_id,
        item_name=item_name or MARKET_ITEM_NAMES.get(type_id, f"Type {type_id}"),
        average_price=market_prices.get(int(type_id), {}).get("average_price"),
        adjusted_price=market_prices.get(int(type_id), {}).get("adjusted_price"),
    )


def summarize_market_orders(
    orders: list[dict[str, Any]],
    *,
    region_id: int,
    location_id: int | None,
    type_id: int,
    item_name: str,
    average_price: float | None = None,
    adjusted_price: float | None = None,
) -> PublicMarketSnapshot:
    """Summarize order book into best buy/sell and volume."""

    selected_orders = [
        order
        for order in orders
        if location_id is None or int(order.get("location_id", 0)) == int(location_id)
    ]
    if not selected_orders and location_id is not None:
        selected_orders = orders
        selected_location_id = None
    else:
        selected_location_id = location_id

    buy_orders = [order for order in selected_orders if bool(order.get("is_buy_order", False))]
    sell_orders = [order for order in selected_orders if not bool(order.get("is_buy_order", False))]

    price_source = "order_book"
    if not buy_orders and not sell_orders and average_price is not None:
        price_source = "market_average"

    return PublicMarketSnapshot(
        region_id=region_id,
        location_id=selected_location_id,
        type_id=type_id,
        item_name=item_name,
        best_buy_price=max((float(order["price"]) for order in buy_orders), default=None),
        best_sell_price=min((float(order["price"]) for order in sell_orders), default=None),
        average_price=average_price,
        adjusted_price=adjusted_price,
        buy_volume=sum(int(order.get("volume_remain", 0)) for order in buy_orders),
        sell_volume=sum(int(order.get("volume_remain", 0)) for order in sell_orders),
        order_count=len(selected_orders),
        price_source=price_source,
    )


def fetch_inventory_type_names(type_ids: list[int] | tuple[int, ...]) -> dict[int, str]:
    """Resolve EVE inventory type names from public ESI."""

    unique_type_ids = sorted({int(type_id) for type_id in type_ids if type_id})
    if not unique_type_ids:
        return {}

    response = httpx.post(
        "https://esi.evetech.net/latest/universe/names/",
        json=unique_type_ids,
        headers={
            "User-Agent": "EVE SP Farm Planner/0.1 local",
            "X-Compatibility-Date": _compatibility_date(),
        },
        params={"datasource": "tranquility"},
        timeout=20,
    )
    response.raise_for_status()
    return {
        int(item["id"]): str(item["name"])
        for item in response.json()
        if item.get("category") == "inventory_type"
    }


def _compatibility_date(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    return (current - timedelta(hours=11)).date().isoformat()
