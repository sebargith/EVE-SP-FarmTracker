import json

import httpx

from src.data.database import connect, initialize_database
from src.data.repositories import (
    add_account,
    add_account_group,
    add_character,
    latest_market_snapshots,
    replace_character_assets,
)
from src.integrations.esi_public import (
    EsiPublicClient,
    JITA_4_4_STATION_ID,
    LARGE_SKILL_INJECTOR_TYPE_ID,
    PLEX_TYPE_ID,
    SKILL_EXTRACTOR_TYPE_ID,
    summarize_market_orders,
)
from src.services.market_service import (
    asset_valuations,
    latest_market_scenario_overrides,
    sync_market_snapshots,
)


class FakeMarketClient:
    def __init__(self) -> None:
        self.closed = False

    def get_market_orders(self, *, region_id: int, type_id: int, order_type: str = "all"):
        base = {
            PLEX_TYPE_ID: 6_000_000,
            SKILL_EXTRACTOR_TYPE_ID: 500_000_000,
            LARGE_SKILL_INJECTOR_TYPE_ID: 1_000_000_000,
        }[type_id]
        return [
            {
                "is_buy_order": False,
                "location_id": JITA_4_4_STATION_ID,
                "price": base + 100,
                "volume_remain": 10,
            },
            {
                "is_buy_order": False,
                "location_id": JITA_4_4_STATION_ID,
                "price": base + 50,
                "volume_remain": 20,
            },
            {
                "is_buy_order": True,
                "location_id": JITA_4_4_STATION_ID,
                "price": base - 25,
                "volume_remain": 30,
            },
            {
                "is_buy_order": True,
                "location_id": JITA_4_4_STATION_ID,
                "price": base - 10,
                "volume_remain": 40,
            },
        ]

    def get_market_prices(self):
        return {
            PLEX_TYPE_ID: {"average_price": 6_100_000.0, "adjusted_price": 0.0},
            SKILL_EXTRACTOR_TYPE_ID: {
                "average_price": 500_000_000.0,
                "adjusted_price": 450_000_000.0,
            },
            LARGE_SKILL_INJECTOR_TYPE_ID: {
                "average_price": 1_000_000_000.0,
                "adjusted_price": 750_000_000.0,
            },
        }

    def close(self) -> None:
        self.closed = True


def test_public_client_resolves_inventory_type_names() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/latest/universe/ids/"
        assert json.loads(request.content) == ["Carbon", "Metal Scraps"]
        return httpx.Response(
            200,
            json={
                "inventory_types": [
                    {"id": 2016, "name": "Carbon"},
                    {"id": 15331, "name": "Metal Scraps"},
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = EsiPublicClient(client=http_client)
        assert client.resolve_inventory_type_ids(["Metal Scraps", "Carbon", "Carbon"]) == {
            "Carbon": 2016,
            "Metal Scraps": 15331,
        }


def test_summarize_market_orders_uses_jita_best_buy_and_sell() -> None:
    snapshot = summarize_market_orders(
        [
            {
                "is_buy_order": False,
                "location_id": JITA_4_4_STATION_ID,
                "price": 100,
                "volume_remain": 5,
            },
            {
                "is_buy_order": False,
                "location_id": JITA_4_4_STATION_ID,
                "price": 90,
                "volume_remain": 7,
            },
            {
                "is_buy_order": True,
                "location_id": JITA_4_4_STATION_ID,
                "price": 80,
                "volume_remain": 11,
            },
            {
                "is_buy_order": True,
                "location_id": JITA_4_4_STATION_ID,
                "price": 85,
                "volume_remain": 13,
            },
        ],
        region_id=10000002,
        location_id=JITA_4_4_STATION_ID,
        type_id=PLEX_TYPE_ID,
        item_name="PLEX",
    )

    assert snapshot.best_sell_price == 90
    assert snapshot.best_buy_price == 85
    assert snapshot.sell_volume == 12
    assert snapshot.buy_volume == 24
    assert snapshot.price_source == "order_book"


def test_summarize_market_orders_falls_back_to_average_price_source() -> None:
    snapshot = summarize_market_orders(
        [],
        region_id=10000002,
        location_id=JITA_4_4_STATION_ID,
        type_id=PLEX_TYPE_ID,
        item_name="PLEX",
        average_price=6_100_000,
        adjusted_price=0,
    )

    assert snapshot.best_sell_price is None
    assert snapshot.average_price == 6_100_000
    assert snapshot.price_source == "market_average"


def test_sync_market_snapshots_and_asset_valuation() -> None:
    connection = connect(":memory:")
    initialize_database(connection)
    group_id = add_account_group(connection, name="Market Group")
    account_id = add_account(connection, group_id=group_id, name="Market Account")
    character_id = add_character(connection, account_id=account_id, name="Market Character", total_sp=0)
    replace_character_assets(
        connection,
        character_id=character_id,
        assets=[
            {
                "item_id": 1,
                "type_id": LARGE_SKILL_INJECTOR_TYPE_ID,
                "quantity": 2,
                "location_id": JITA_4_4_STATION_ID,
                "location_type": "station",
                "location_flag": "Hangar",
            }
        ],
    )

    snapshots = sync_market_snapshots(connection, client=FakeMarketClient())
    latest = latest_market_snapshots(
        connection,
        type_ids=(PLEX_TYPE_ID, SKILL_EXTRACTOR_TYPE_ID, LARGE_SKILL_INJECTOR_TYPE_ID),
    )
    valuations = asset_valuations(connection)

    assert len(snapshots) == 3
    assert len(latest) == 3
    assert len(valuations) == 1
    assert valuations[0].quantity == 2
    assert valuations[0].estimated_sell_value == 2_000_000_100


def test_latest_market_scenario_overrides_use_best_sell_then_average() -> None:
    connection = connect(":memory:")
    initialize_database(connection)

    sync_market_snapshots(connection, client=FakeMarketClient())
    overrides = latest_market_scenario_overrides(connection)

    assert overrides.has_any_price
    assert overrides.plex_cost_basis_isk == 6_000_050
    assert overrides.large_skill_injector_sell_price_isk == 1_000_000_050
    assert overrides.skill_extractor_market_buy_price_isk == 500_000_050
    assert "PLEX" in overrides.source_summary
