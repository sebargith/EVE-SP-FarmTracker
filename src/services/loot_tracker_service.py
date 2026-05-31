"""Clipboard-driven loot tracking for explicit player-controlled activity windows."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from src.data.repositories import (
    add_loot_excluded_item,
    complete_clipboard_loot_session,
    create_clipboard_loot_session,
    delete_clipboard_loot_item,
    get_active_clipboard_loot_session,
    get_loot_session,
    list_clipboard_loot_imports,
    list_loot_excluded_items,
    list_loot_session_items,
    list_loot_sessions,
    record_clipboard_loot_import,
    remove_loot_excluded_item,
    update_clipboard_loot_item,
)
from src.integrations.esi_public import EsiPublicClient
from src.services.loot_pricing_service import (
    LootPriceRefreshSummary,
    normalize_item_name,
    refresh_loot_prices,
)


_HEADER_NAMES = frozenset(("item", "item name", "name", "type"))
_NUMBER_CHARS = re.compile(r"[^0-9,.\-]")


@dataclass(frozen=True)
class ParsedLootItem:
    item_name: str
    normalized_name: str
    quantity: int
    unit_value_isk: float
    total_value_isk: float
    price_source: str


@dataclass(frozen=True)
class LootImportSummary:
    import_id: int
    parsed_item_count: int
    accepted_item_count: int
    ignored_item_count: int
    imported_value_isk: float
    price_refresh: LootPriceRefreshSummary | None
    pricing_error: str | None


def start_tracking(
    connection: sqlite3.Connection,
    *,
    notes: str = "",
    now: datetime | None = None,
) -> int:
    """Start one cumulative loot tracking run."""

    if get_active_clipboard_loot_session(connection):
        raise ValueError("Stop the active loot tracking run before starting another.")
    return create_clipboard_loot_session(
        connection,
        notes=notes.strip(),
        started_at=(now or datetime.now(timezone.utc)).isoformat(),
    )


def import_cargo_text(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    raw_text: str,
    character_id: int | None = None,
    now: datetime | None = None,
    pricing_client: EsiPublicClient | None = None,
    auto_price: bool = True,
) -> LootImportSummary:
    """Parse and add one pasted cargo block to an active tracking run."""

    _require_active_session(connection, session_id=session_id)
    items = parse_cargo_text(raw_text)
    excluded = {
        str(row["normalized_name"])
        for row in list_loot_excluded_items(connection)
    }
    accepted = [item for item in items if item.normalized_name not in excluded]
    ignored_count = len(items) - len(accepted)
    imported_at = (now or datetime.now(timezone.utc)).isoformat()
    import_id = record_clipboard_loot_import(
        connection,
        session_id=session_id,
        character_id=character_id,
        raw_text=raw_text,
        items=[_item_mapping(item) for item in accepted],
        parsed_item_count=len(items),
        ignored_item_count=ignored_count,
        imported_at=imported_at,
    )
    price_refresh = None
    pricing_error = None
    if auto_price:
        try:
            price_refresh = refresh_loot_prices(
                connection,
                session_id=session_id,
                client=pricing_client,
                now=now,
            )
        except Exception as exc:
            pricing_error = str(exc)
    return LootImportSummary(
        import_id=import_id,
        parsed_item_count=len(items),
        accepted_item_count=len(accepted),
        ignored_item_count=ignored_count,
        imported_value_isk=sum(item.total_value_isk for item in accepted),
        price_refresh=price_refresh,
        pricing_error=pricing_error,
    )


def parse_cargo_text(raw_text: str) -> list[ParsedLootItem]:
    """Parse inventory clipboard text into normalized cumulative item rows."""

    if not raw_text.strip():
        raise ValueError("Paste at least one cargo item.")

    aggregated: dict[str, ParsedLootItem] = {}
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parsed = _parse_line(line)
        if not parsed:
            continue
        existing = aggregated.get(parsed.normalized_name)
        if not existing:
            aggregated[parsed.normalized_name] = parsed
            continue
        unit_value = parsed.unit_value_isk or existing.unit_value_isk
        quantity = existing.quantity + parsed.quantity
        aggregated[parsed.normalized_name] = ParsedLootItem(
            item_name=parsed.item_name,
            normalized_name=parsed.normalized_name,
            quantity=quantity,
            unit_value_isk=unit_value,
            total_value_isk=quantity * unit_value,
            price_source=(
                parsed.price_source
                if parsed.unit_value_isk > 0
                else existing.price_source
            ),
        )

    if not aggregated:
        raise ValueError("No cargo items could be parsed from the pasted text.")
    return sorted(aggregated.values(), key=lambda item: item.item_name.casefold())


def current_items(connection: sqlite3.Connection, *, session_id: int) -> list[dict[str, Any]]:
    return list_loot_session_items(connection, session_id=session_id)


def import_history(connection: sqlite3.Connection, *, session_id: int) -> list[dict[str, Any]]:
    return list_clipboard_loot_imports(connection, session_id=session_id)


def loot_history(connection: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    return list_loot_sessions(connection, limit=limit)


def active_session(connection: sqlite3.Connection) -> dict[str, Any] | None:
    return get_active_clipboard_loot_session(connection)


def update_item(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    item_id: int,
    quantity: int,
    unit_value_isk: float,
) -> None:
    _require_active_session(connection, session_id=session_id)
    if int(quantity) < 0:
        raise ValueError("Quantity cannot be negative.")
    if float(unit_value_isk) < 0:
        raise ValueError("Unit value cannot be negative.")
    update_clipboard_loot_item(
        connection,
        session_id=session_id,
        item_id=item_id,
        quantity=quantity,
        unit_value_isk=unit_value_isk,
    )


def remove_item(connection: sqlite3.Connection, *, session_id: int, item_id: int) -> None:
    _require_active_session(connection, session_id=session_id)
    delete_clipboard_loot_item(connection, session_id=session_id, item_id=item_id)


def exclude_item(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    item_id: int,
) -> None:
    """Remove one current row and ignore that item name in future paste batches."""

    _require_active_session(connection, session_id=session_id)
    item = next(
        (
            row
            for row in list_loot_session_items(connection, session_id=session_id)
            if int(row["id"]) == int(item_id)
        ),
        None,
    )
    if not item:
        raise ValueError("Loot item was not found.")
    normalized_name = str(item.get("normalized_name") or normalize_item_name(str(item["item_name"])))
    add_loot_excluded_item(
        connection,
        normalized_name=normalized_name,
        item_name=str(item["item_name"]),
        remove_from_session_id=session_id,
    )


def add_filter(connection: sqlite3.Connection, *, item_name: str, session_id: int | None = None) -> None:
    if not item_name.strip():
        raise ValueError("Enter an item name to exclude.")
    add_loot_excluded_item(
        connection,
        normalized_name=normalize_item_name(item_name),
        item_name=item_name.strip(),
        remove_from_session_id=session_id,
    )


def remove_filter(connection: sqlite3.Connection, *, normalized_name: str) -> None:
    remove_loot_excluded_item(connection, normalized_name=normalized_name)


def excluded_items(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return list_loot_excluded_items(connection)


def stop_tracking(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    now: datetime | None = None,
) -> None:
    _require_active_session(connection, session_id=session_id)
    complete_clipboard_loot_session(
        connection,
        session_id=session_id,
        confirmed_at=(now or datetime.now(timezone.utc)).isoformat(),
    )


def _parse_line(line: str) -> ParsedLootItem | None:
    columns = [column.strip() for column in line.split("\t")]
    if len(columns) > 1:
        item_name = columns[0]
        if normalize_item_name(item_name) in _HEADER_NAMES:
            return None
        quantity = _parse_quantity(columns[1], default=1)
        total_value = _last_isk_value(columns[2:])
        return _build_item(item_name, quantity=quantity, total_value_isk=total_value)

    quantity_suffix = re.match(r"^(.*?)\s+[xX]\s*([\d,.\s]+)$", line)
    if quantity_suffix:
        return _build_item(
            quantity_suffix.group(1),
            quantity=_parse_quantity(quantity_suffix.group(2), default=1),
        )
    quantity_prefix = re.match(r"^([\d,.\s]+)\s*[xX]\s+(.+)$", line)
    if quantity_prefix:
        return _build_item(
            quantity_prefix.group(2),
            quantity=_parse_quantity(quantity_prefix.group(1), default=1),
        )
    return _build_item(line, quantity=1)


def _build_item(
    item_name: str,
    *,
    quantity: int,
    total_value_isk: float | None = None,
) -> ParsedLootItem | None:
    name = item_name.strip()
    if not name or quantity <= 0:
        return None
    unit_value = float(total_value_isk or 0) / quantity
    return ParsedLootItem(
        item_name=name,
        normalized_name=normalize_item_name(name),
        quantity=quantity,
        unit_value_isk=unit_value,
        total_value_isk=float(total_value_isk or 0),
        price_source="Pasted estimate" if total_value_isk is not None else "Manual value needed",
    )


def _parse_quantity(value: str, *, default: int) -> int:
    parsed = _parse_number(value)
    return max(int(parsed), 0) if parsed is not None else default


def _last_isk_value(columns: list[str]) -> float | None:
    for value in reversed(columns):
        if "isk" not in value.casefold():
            continue
        parsed = _parse_number(value)
        if parsed is not None:
            return parsed
    return None


def _parse_number(value: str) -> float | None:
    candidate = _NUMBER_CHARS.sub("", value.replace("\u00a0", " ")).replace(" ", "")
    if not candidate:
        return None
    if "," in candidate and "." in candidate:
        candidate = candidate.replace(",", "")
    elif candidate.count(",") > 1:
        candidate = candidate.replace(",", "")
    elif "," in candidate:
        left, right = candidate.split(",", 1)
        candidate = left + right if len(right) == 3 else left + "." + right
    try:
        return float(candidate)
    except ValueError:
        return None


def _item_mapping(item: ParsedLootItem) -> dict[str, Any]:
    return {
        "item_name": item.item_name,
        "normalized_name": item.normalized_name,
        "quantity": item.quantity,
        "unit_value_isk": item.unit_value_isk,
        "total_value_isk": item.total_value_isk,
        "price_source": item.price_source,
    }


def _require_active_session(connection: sqlite3.Connection, *, session_id: int) -> dict[str, Any]:
    session = get_loot_session(connection, session_id=session_id)
    if not session:
        raise ValueError("Loot tracking run was not found.")
    if session["status"] != "Active":
        raise ValueError("Loot tracking run is already closed.")
    return session
