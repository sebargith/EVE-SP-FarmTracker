from datetime import datetime, timedelta, timezone

from src.data.database import connect, initialize_database
from src.integrations.esi_public import JITA_4_4_STATION_ID
from src.services.loot_pricing_service import loot_price_status, refresh_loot_prices
from src.services.loot_tracker_service import current_items, import_cargo_text, start_tracking


class FakeLootMarketClient:
    def __init__(self) -> None:
        self.resolve_calls = 0
        self.order_calls = 0
        self.average_calls = 0

    def resolve_inventory_type_ids(self, names):
        self.resolve_calls += 1
        available = {
            "Burned Logic Circuit": 25607,
            "Carbon": 2016,
        }
        return {name: available[name] for name in names if name in available}

    def get_market_orders(self, *, region_id: int, type_id: int, order_type: str = "all"):
        self.order_calls += 1
        if type_id == 25607:
            return [
                {
                    "is_buy_order": True,
                    "location_id": JITA_4_4_STATION_ID,
                    "price": 125_000,
                    "volume_remain": 10,
                },
                {
                    "is_buy_order": True,
                    "location_id": 60008494,
                    "price": 140_000,
                    "volume_remain": 10,
                },
            ]
        return []

    def get_market_prices(self):
        self.average_calls += 1
        return {
            25607: {"average_price": 130_000.0},
            2016: {"average_price": 20.0},
        }


def _connection():
    connection = connect(":memory:")
    initialize_database(connection)
    return connection


def test_refresh_uses_jita_buy_then_estimated_and_pasted_fallbacks() -> None:
    connection = _connection()
    session_id = start_tracking(connection)
    import_cargo_text(
        connection,
        session_id=session_id,
        raw_text=(
            "Burned Logic Circuit\t2\tSalvage\t400,000 ISK\n"
            "Carbon x 3\n"
            "Unknown Relic\t1\tRelic\t75,000 ISK"
        ),
        auto_price=False,
    )

    summary = refresh_loot_prices(
        connection,
        session_id=session_id,
        client=FakeLootMarketClient(),
        now=datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc),
    )
    rows = {row["item_name"]: row for row in current_items(connection, session_id=session_id)}

    assert rows["Burned Logic Circuit"]["unit_value_isk"] == 125_000
    assert rows["Burned Logic Circuit"]["total_value_isk"] == 250_000
    assert rows["Burned Logic Circuit"]["price_source"] == "Jita Buy"
    assert rows["Carbon"]["unit_value_isk"] == 20
    assert rows["Carbon"]["price_source"] == "Estimated"
    assert rows["Unknown Relic"]["unit_value_isk"] == 75_000
    assert rows["Unknown Relic"]["price_source"] == "Pasted Estimate"
    assert summary.jita_buy_count == 1
    assert summary.estimated_count == 1
    assert summary.pasted_estimate_count == 1
    assert summary.unpriced_count == 0


def test_refresh_reuses_five_minute_cache_unless_forced() -> None:
    connection = _connection()
    session_id = start_tracking(connection)
    import_cargo_text(
        connection,
        session_id=session_id,
        raw_text="Burned Logic Circuit x 2",
        auto_price=False,
    )
    client = FakeLootMarketClient()
    started_at = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)

    refresh_loot_prices(connection, session_id=session_id, client=client, now=started_at)
    refresh_loot_prices(
        connection,
        session_id=session_id,
        client=client,
        now=started_at + timedelta(minutes=4),
    )

    assert client.resolve_calls == 1
    assert client.order_calls == 1
    assert client.average_calls == 1

    refresh_loot_prices(
        connection,
        session_id=session_id,
        force_refresh=True,
        client=client,
        now=started_at + timedelta(minutes=4),
    )

    assert client.resolve_calls == 1
    assert client.order_calls == 2
    assert client.average_calls == 2


def test_import_automatically_applies_public_price() -> None:
    connection = _connection()
    session_id = start_tracking(connection)

    summary = import_cargo_text(
        connection,
        session_id=session_id,
        raw_text="Burned Logic Circuit x 2",
        pricing_client=FakeLootMarketClient(),
    )
    row = current_items(connection, session_id=session_id)[0]
    status = loot_price_status(connection, session_id=session_id)

    assert summary.pricing_error is None
    assert summary.price_refresh is not None
    assert row["unit_value_isk"] == 125_000
    assert row["total_value_isk"] == 250_000
    assert row["price_source"] == "Jita Buy"
    assert status.priced_at is not None


def test_unpriced_repeat_paste_preserves_existing_market_value() -> None:
    connection = _connection()
    session_id = start_tracking(connection)
    import_cargo_text(
        connection,
        session_id=session_id,
        raw_text="Burned Logic Circuit x 2",
        pricing_client=FakeLootMarketClient(),
    )

    import_cargo_text(
        connection,
        session_id=session_id,
        raw_text="Burned Logic Circuit x 1",
        auto_price=False,
    )
    row = current_items(connection, session_id=session_id)[0]

    assert row["quantity"] == 3
    assert row["unit_value_isk"] == 125_000
    assert row["total_value_isk"] == 375_000
    assert row["price_source"] == "Jita Buy"
