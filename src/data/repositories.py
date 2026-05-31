"""Repository functions for local SP farm data."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any


def list_character_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Return characters joined to account and group metadata."""

    rows = connection.execute(
        """
        SELECT
            account_groups.id AS group_id,
            account_groups.name AS group_name,
            accounts.id AS account_id,
            accounts.name AS account_name,
            accounts.omega_status,
            accounts.omega_expires_at,
            accounts.mct_slots,
            accounts.sync_status,
            characters.id AS character_id,
            characters.name AS character_name,
            characters.eve_character_id,
            characters.total_sp,
            characters.total_sp_updated_at,
            characters.training_rate_sp_min,
            characters.current_skill,
            characters.queue_ends_at,
            characters.attribute_profile,
            characters.implant_profile,
            characters.last_sync_at AS character_last_sync_at,
            characters.sync_status AS character_sync_status,
            characters.notes
        FROM characters
        JOIN accounts ON accounts.id = characters.account_id
        JOIN account_groups ON account_groups.id = accounts.group_id
        ORDER BY account_groups.name, accounts.name, characters.name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_groups(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        "SELECT id, name, notes FROM account_groups ORDER BY name"
    ).fetchall()
    return [dict(row) for row in rows]


def list_accounts(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            accounts.id, accounts.group_id, account_groups.name AS group_name,
            accounts.name, accounts.omega_status, accounts.omega_expires_at,
            accounts.mct_slots, accounts.wallet_balance, accounts.sync_status,
            accounts.notes
        FROM accounts
        JOIN account_groups ON account_groups.id = accounts.group_id
        ORDER BY account_groups.name, accounts.name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def add_account_group(
    connection: sqlite3.Connection,
    *,
    name: str,
    notes: str = "",
) -> int:
    cursor = connection.execute(
        "INSERT INTO account_groups (name, notes) VALUES (?, ?)",
        (name, notes),
    )
    connection.commit()
    return int(cursor.lastrowid)


def add_account(
    connection: sqlite3.Connection,
    *,
    group_id: int,
    name: str,
    omega_status: str = "Unknown",
    omega_expires_at: str | None = None,
    mct_slots: int = 0,
    notes: str = "",
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO accounts (
            group_id, name, omega_status, omega_expires_at, mct_slots,
            sync_status, notes
        )
        VALUES (?, ?, ?, ?, ?, 'Manual', ?)
        """,
        (group_id, name, omega_status, omega_expires_at, mct_slots, notes),
    )
    connection.commit()
    return int(cursor.lastrowid)


def add_character(
    connection: sqlite3.Connection,
    *,
    account_id: int,
    name: str,
    total_sp: int,
    training_rate_sp_min: float = 45,
    current_skill: str = "",
    queue_ends_at: str | None = None,
    attribute_profile: str = "Optimized",
    implant_profile: str = "+5",
    notes: str = "",
) -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        """
        INSERT INTO characters (
            account_id, name, total_sp, total_sp_updated_at,
            training_rate_sp_min, current_skill, queue_ends_at,
            attribute_profile, implant_profile, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_id,
            name,
            total_sp,
            timestamp,
            training_rate_sp_min,
            current_skill,
            queue_ends_at,
            attribute_profile,
            implant_profile,
            notes,
        ),
    )
    character_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO sp_snapshots (character_id, timestamp, total_sp, source, notes)
        VALUES (?, ?, ?, 'Manual', 'Initial character entry')
        """,
        (character_id, timestamp, total_sp),
    )
    connection.commit()
    return character_id


def upsert_sso_character(
    connection: sqlite3.Connection,
    *,
    account_id: int,
    eve_character_id: int,
    name: str,
    total_sp: int = 0,
    training_rate_sp_min: float = 45,
    current_skill: str = "",
    queue_ends_at: str | None = None,
    attribute_profile: str = "ESI",
    implant_profile: str = "ESI",
    sync_status: str = "SSO Authorized",
) -> int:
    """Create or update a character linked to an EVE SSO identity."""

    timestamp = datetime.now(timezone.utc).isoformat()
    existing = connection.execute(
        """
        SELECT id FROM characters
        WHERE eve_character_id = ?
        """,
        (eve_character_id,),
    ).fetchone()

    if existing:
        character_id = int(existing["id"])
        connection.execute(
            """
            UPDATE characters
            SET account_id = ?, name = ?, training_rate_sp_min = ?,
                current_skill = ?, queue_ends_at = ?, attribute_profile = ?,
                implant_profile = ?, last_sync_at = ?, sync_status = ?
            WHERE id = ?
            """,
            (
                account_id,
                name,
                training_rate_sp_min,
                current_skill,
                queue_ends_at,
                attribute_profile,
                implant_profile,
                timestamp,
                sync_status,
                character_id,
            ),
        )
        connection.commit()
        return character_id

    cursor = connection.execute(
        """
        INSERT INTO characters (
            account_id, name, eve_character_id, total_sp, total_sp_updated_at,
            training_rate_sp_min, current_skill, queue_ends_at,
            attribute_profile, implant_profile, last_sync_at, sync_status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '')
        """,
        (
            account_id,
            name,
            eve_character_id,
            total_sp,
            timestamp,
            training_rate_sp_min,
            current_skill,
            queue_ends_at,
            attribute_profile,
            implant_profile,
            timestamp,
            sync_status,
        ),
    )
    character_id = int(cursor.lastrowid)
    connection.execute(
        """
        INSERT INTO sp_snapshots (character_id, timestamp, total_sp, source, notes)
        VALUES (?, ?, ?, 'ESI', 'Initial EVE SSO import')
        """,
        (character_id, timestamp, total_sp),
    )
    connection.commit()
    return character_id


def update_character_sp(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    total_sp: int,
    source: str = "Manual",
    notes: str = "",
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        UPDATE characters
        SET total_sp = ?, total_sp_updated_at = ?
        WHERE id = ?
        """,
        (total_sp, timestamp, character_id),
    )
    connection.execute(
        """
        INSERT INTO sp_snapshots (character_id, timestamp, total_sp, source, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (character_id, timestamp, total_sp, source, notes),
    )
    connection.commit()


def record_character_esi_sync(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    total_sp: int,
    training_rate_sp_min: float,
    current_skill: str,
    queue_ends_at: str | None,
    attribute_profile: str,
    implant_profile: str,
    sync_status: str = "SSO Synced",
    snapshot_cooldown_minutes: int = 15,
) -> bool:
    timestamp = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        UPDATE characters
        SET total_sp = ?, total_sp_updated_at = ?, training_rate_sp_min = ?,
            current_skill = ?, queue_ends_at = ?, attribute_profile = ?,
            implant_profile = ?, last_sync_at = ?, sync_status = ?
        WHERE id = ?
        """,
        (
            total_sp,
            timestamp,
            training_rate_sp_min,
            current_skill,
            queue_ends_at,
            attribute_profile,
            implant_profile,
            timestamp,
            sync_status,
            character_id,
        ),
    )
    snapshot_recorded = record_sp_snapshot_if_due(
        connection,
        character_id=character_id,
        total_sp=total_sp,
        source="ESI",
        notes="EVE SSO sync",
        timestamp=timestamp,
        cooldown_minutes=snapshot_cooldown_minutes,
    )
    connection.commit()
    return snapshot_recorded


def record_sp_snapshot_if_due(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    total_sp: int,
    source: str,
    notes: str = "",
    timestamp: str | None = None,
    cooldown_minutes: int = 15,
) -> bool:
    """Store a snapshot unless the same SP value was recently recorded."""

    recorded_at = timestamp or datetime.now(timezone.utc).isoformat()
    latest = connection.execute(
        """
        SELECT timestamp, total_sp
        FROM sp_snapshots
        WHERE character_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT 1
        """,
        (character_id,),
    ).fetchone()
    if latest and int(latest["total_sp"]) == int(total_sp):
        latest_at = datetime.fromisoformat(str(latest["timestamp"]).replace("Z", "+00:00"))
        if latest_at.tzinfo is None:
            latest_at = latest_at.replace(tzinfo=timezone.utc)
        current_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        if current_at.tzinfo is None:
            current_at = current_at.replace(tzinfo=timezone.utc)
        if current_at - latest_at < timedelta(minutes=cooldown_minutes):
            return False

    connection.execute(
        """
        INSERT INTO sp_snapshots (character_id, timestamp, total_sp, source, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (character_id, recorded_at, int(total_sp), source, notes),
    )
    return True


def store_api_token(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    eve_character_id: int,
    scopes: list[str] | tuple[str, ...],
    encrypted_refresh_token: str,
    access_token_expires_at: str | None,
    status: str = "Authorized",
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    scopes_text = " ".join(scopes)
    connection.execute(
        """
        INSERT INTO api_tokens (
            character_id, eve_character_id, scopes, encrypted_refresh_token,
            access_token_expires_at, last_refresh_at, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(eve_character_id) DO UPDATE SET
            character_id = excluded.character_id,
            scopes = excluded.scopes,
            encrypted_refresh_token = excluded.encrypted_refresh_token,
            access_token_expires_at = excluded.access_token_expires_at,
            last_refresh_at = excluded.last_refresh_at,
            status = excluded.status,
            updated_at = excluded.updated_at
        """,
        (
            character_id,
            eve_character_id,
            scopes_text,
            encrypted_refresh_token,
            access_token_expires_at,
            timestamp,
            status,
            timestamp,
            timestamp,
        ),
    )
    connection.commit()


def list_api_tokens(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            api_tokens.*,
            characters.name AS character_name,
            characters.queue_ends_at AS character_queue_ends_at,
            characters.training_rate_sp_min AS character_training_rate_sp_min,
            characters.sync_status AS character_sync_status,
            accounts.name AS account_name,
            account_groups.name AS group_name
        FROM api_tokens
        JOIN characters ON characters.id = api_tokens.character_id
        JOIN accounts ON accounts.id = characters.account_id
        JOIN account_groups ON account_groups.id = accounts.group_id
        ORDER BY account_groups.name, accounts.name, characters.name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_character_row(
    connection: sqlite3.Connection,
    *,
    character_id: int,
) -> dict[str, Any] | None:
    """Return one character row with account metadata."""

    row = connection.execute(
        """
        SELECT
            characters.*,
            accounts.name AS account_name,
            account_groups.name AS group_name
        FROM characters
        JOIN accounts ON accounts.id = characters.account_id
        JOIN account_groups ON account_groups.id = accounts.group_id
        WHERE characters.id = ?
        """,
        (character_id,),
    ).fetchone()
    return dict(row) if row else None


def start_sync_run(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    trigger: str,
) -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        """
        INSERT INTO sync_runs (character_id, trigger, started_at, status)
        VALUES (?, ?, ?, 'Running')
        """,
        (character_id, trigger, timestamp),
    )
    connection.commit()
    return int(cursor.lastrowid)


def complete_sync_run(
    connection: sqlite3.Connection,
    *,
    sync_run_id: int,
    status: str,
    error_message: str = "",
) -> None:
    connection.execute(
        """
        UPDATE sync_runs
        SET completed_at = ?, status = ?, error_message = ?
        WHERE id = ?
        """,
        (datetime.now(timezone.utc).isoformat(), status, error_message, sync_run_id),
    )
    connection.commit()


def add_sync_endpoint_result(
    connection: sqlite3.Connection,
    *,
    sync_run_id: int,
    endpoint: str,
    status: str,
    message: str = "",
) -> None:
    connection.execute(
        """
        INSERT INTO sync_endpoint_results (
            sync_run_id, endpoint, status, message, recorded_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            sync_run_id,
            endpoint,
            status,
            message,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    connection.commit()


def list_latest_sync_runs(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT sync_runs.*
        FROM sync_runs
        JOIN (
            SELECT character_id, MAX(id) AS latest_id
            FROM sync_runs
            GROUP BY character_id
        ) latest ON latest.latest_id = sync_runs.id
        ORDER BY sync_runs.started_at DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_sync_endpoint_results(
    connection: sqlite3.Connection,
    *,
    sync_run_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT id, sync_run_id, endpoint, status, message, recorded_at
        FROM sync_endpoint_results
        WHERE sync_run_id = ?
        ORDER BY id
        """,
        (sync_run_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_recent_sync_runs(
    connection: sqlite3.Connection,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            sync_runs.*,
            characters.name AS character_name,
            accounts.name AS account_name,
            account_groups.name AS group_name
        FROM sync_runs
        JOIN characters ON characters.id = sync_runs.character_id
        JOIN accounts ON accounts.id = characters.account_id
        JOIN account_groups ON account_groups.id = accounts.group_id
        ORDER BY sync_runs.started_at DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [dict(row) for row in rows]


def list_sync_run_summaries(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            character_id,
            MAX(
                CASE
                    WHEN status IN ('Success', 'Partial') THEN completed_at
                END
            ) AS last_successful_sync_at,
            MAX(
                CASE
                    WHEN status = 'Failed' THEN completed_at
                END
            ) AS last_failure_at
        FROM sync_runs
        GROUP BY character_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def mark_api_token_sync(
    connection: sqlite3.Connection,
    *,
    token_id: int,
    status: str,
    access_token_expires_at: str | None = None,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        UPDATE api_tokens
        SET status = ?, access_token_expires_at = COALESCE(?, access_token_expires_at),
            last_sync_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (status, access_token_expires_at, timestamp, timestamp, token_id),
    )
    connection.commit()


def mark_api_token_sync_by_character(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    status: str,
    access_token_expires_at: str | None = None,
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        UPDATE api_tokens
        SET status = ?, access_token_expires_at = COALESCE(?, access_token_expires_at),
            last_sync_at = ?, updated_at = ?
        WHERE character_id = ?
        """,
        (status, access_token_expires_at, timestamp, timestamp, character_id),
    )
    connection.commit()


def mark_character_sync_status(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    status: str,
) -> None:
    connection.execute(
        "UPDATE characters SET sync_status = ? WHERE id = ?",
        (status, character_id),
    )
    connection.commit()


def delete_api_token(connection: sqlite3.Connection, *, token_id: int) -> None:
    connection.execute("DELETE FROM api_tokens WHERE id = ?", (token_id,))
    connection.commit()


def create_sso_auth_state(
    connection: sqlite3.Connection,
    *,
    state: str,
    account_id: int,
    code_verifier: str,
    expires_in_minutes: int = 15,
) -> None:
    timestamp = datetime.now(timezone.utc)
    connection.execute(
        """
        INSERT OR REPLACE INTO sso_auth_states (
            state, account_id, code_verifier, created_at, expires_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            state,
            account_id,
            code_verifier,
            timestamp.isoformat(),
            (timestamp + timedelta(minutes=expires_in_minutes)).isoformat(),
        ),
    )
    connection.commit()


def get_sso_auth_state(
    connection: sqlite3.Connection,
    *,
    state: str,
) -> dict[str, Any] | None:
    delete_expired_sso_auth_states(connection)
    row = connection.execute(
        """
        SELECT state, account_id, code_verifier, created_at, expires_at
        FROM sso_auth_states
        WHERE state = ?
        """,
        (state,),
    ).fetchone()
    return dict(row) if row else None


def delete_sso_auth_state(connection: sqlite3.Connection, *, state: str) -> None:
    connection.execute("DELETE FROM sso_auth_states WHERE state = ?", (state,))
    connection.commit()


def delete_expired_sso_auth_states(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DELETE FROM sso_auth_states WHERE expires_at <= ?",
        (datetime.now(timezone.utc).isoformat(),),
    )
    connection.commit()


def replace_character_skills(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    skills: list[dict[str, Any]],
) -> None:
    synced_at = datetime.now(timezone.utc).isoformat()
    connection.execute("DELETE FROM character_skills WHERE character_id = ?", (character_id,))
    connection.executemany(
        """
        INSERT INTO character_skills (
            character_id, skill_id, active_skill_level, trained_skill_level,
            skillpoints_in_skill, synced_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                character_id,
                int(skill["skill_id"]),
                int(skill.get("active_skill_level", 0)),
                int(skill.get("trained_skill_level", 0)),
                int(skill.get("skillpoints_in_skill", 0)),
                synced_at,
            )
            for skill in skills
        ],
    )
    connection.commit()


def replace_skill_queue_entries(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    queue_entries: list[dict[str, Any]],
) -> None:
    synced_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        "DELETE FROM skill_queue_entries WHERE character_id = ?",
        (character_id,),
    )
    connection.executemany(
        """
        INSERT INTO skill_queue_entries (
            character_id, queue_position, skill_id, finished_level, start_date,
            finish_date, training_start_sp, level_start_sp, level_end_sp, synced_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                character_id,
                int(entry.get("queue_position", 0)),
                int(entry["skill_id"]),
                int(entry.get("finished_level", 0)),
                entry.get("start_date"),
                entry.get("finish_date"),
                _optional_int(entry.get("training_start_sp")),
                _optional_int(entry.get("level_start_sp")),
                _optional_int(entry.get("level_end_sp")),
                synced_at,
            )
            for entry in queue_entries
        ],
    )
    connection.commit()


def add_wallet_snapshot(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    balance: float,
    source: str = "ESI",
) -> None:
    connection.execute(
        """
        INSERT INTO wallet_snapshots (character_id, timestamp, balance, source)
        VALUES (?, ?, ?, ?)
        """,
        (character_id, datetime.now(timezone.utc).isoformat(), float(balance), source),
    )
    connection.commit()


def replace_character_assets(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    assets: list[dict[str, Any]],
) -> None:
    synced_at = datetime.now(timezone.utc).isoformat()
    connection.execute("DELETE FROM character_assets WHERE character_id = ?", (character_id,))
    connection.executemany(
        """
        INSERT INTO character_assets (
            character_id, item_id, type_id, quantity, location_id, location_type,
            location_flag, is_blueprint_copy, is_singleton, synced_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                character_id,
                int(asset["item_id"]),
                int(asset["type_id"]),
                int(asset.get("quantity", 1)),
                int(asset["location_id"]),
                str(asset.get("location_type", "")),
                str(asset.get("location_flag", "")),
                _optional_bool(asset.get("is_blueprint_copy")),
                1 if bool(asset.get("is_singleton", False)) else 0,
                synced_at,
            )
            for asset in assets
        ],
    )
    connection.commit()


def list_character_skills(
    connection: sqlite3.Connection,
    *,
    character_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT skill_id, active_skill_level, trained_skill_level,
               skillpoints_in_skill, synced_at
        FROM character_skills
        WHERE character_id = ?
        ORDER BY skillpoints_in_skill DESC, skill_id
        """,
        (character_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_skill_queue_entries(
    connection: sqlite3.Connection,
    *,
    character_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT queue_position, skill_id, finished_level, start_date, finish_date,
               training_start_sp, level_start_sp, level_end_sp, synced_at
        FROM skill_queue_entries
        WHERE character_id = ?
        ORDER BY queue_position
        """,
        (character_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def latest_wallet_snapshot(
    connection: sqlite3.Connection,
    *,
    character_id: int,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT timestamp, balance, source
        FROM wallet_snapshots
        WHERE character_id = ?
        ORDER BY timestamp DESC
        LIMIT 1
        """,
        (character_id,),
    ).fetchone()
    return dict(row) if row else None


def list_sp_snapshots(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT timestamp, total_sp, source, notes
        FROM sp_snapshots
        WHERE character_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
        """,
        (character_id, int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def list_assets_by_type(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    type_ids: list[int] | tuple[int, ...],
) -> list[dict[str, Any]]:
    if not type_ids:
        return []

    placeholders = ",".join("?" for _ in type_ids)
    rows = connection.execute(
        f"""
        SELECT type_id, SUM(quantity) AS quantity, COUNT(*) AS stacks,
               MAX(synced_at) AS synced_at
        FROM character_assets
        WHERE character_id = ? AND type_id IN ({placeholders})
        GROUP BY type_id
        ORDER BY type_id
        """,
        (character_id, *[int(type_id) for type_id in type_ids]),
    ).fetchall()
    return [dict(row) for row in rows]


def count_character_assets(connection: sqlite3.Connection, *, character_id: int) -> int:
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM character_assets WHERE character_id = ?",
            (character_id,),
        ).fetchone()[0]
    )


def add_market_snapshot(
    connection: sqlite3.Connection,
    *,
    region_id: int,
    location_id: int | None,
    type_id: int,
    item_name: str,
    best_buy_price: float | None,
    best_sell_price: float | None,
    buy_volume: int,
    sell_volume: int,
    order_count: int,
    average_price: float | None = None,
    adjusted_price: float | None = None,
    price_source: str = "order_book",
    source: str = "ESI",
) -> None:
    connection.execute(
        """
        INSERT INTO market_snapshots (
            timestamp, region_id, location_id, type_id, item_name,
            best_buy_price, best_sell_price, average_price, adjusted_price,
            buy_volume, sell_volume, order_count, price_source, source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            int(region_id),
            int(location_id) if location_id is not None else None,
            int(type_id),
            item_name,
            best_buy_price,
            best_sell_price,
            average_price,
            adjusted_price,
            int(buy_volume),
            int(sell_volume),
            int(order_count),
            price_source,
            source,
        ),
    )
    connection.commit()


def latest_market_snapshots(
    connection: sqlite3.Connection,
    *,
    type_ids: list[int] | tuple[int, ...] | None = None,
) -> list[dict[str, Any]]:
    type_filter = ""
    params: list[Any] = []
    if type_ids:
        placeholders = ",".join("?" for _ in type_ids)
        type_filter = f"WHERE market_snapshots.type_id IN ({placeholders})"
        params.extend(int(type_id) for type_id in type_ids)

    rows = connection.execute(
        f"""
        SELECT market_snapshots.*
        FROM market_snapshots
        JOIN (
            SELECT type_id, MAX(timestamp) AS latest_timestamp
            FROM market_snapshots
            {type_filter}
            GROUP BY type_id
        ) latest
            ON latest.type_id = market_snapshots.type_id
           AND latest.latest_timestamp = market_snapshots.timestamp
        ORDER BY market_snapshots.item_name
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_market_history(
    connection: sqlite3.Connection,
    *,
    type_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT timestamp, region_id, location_id, type_id, item_name,
               best_buy_price, best_sell_price, average_price, adjusted_price,
               buy_volume, sell_volume, order_count, price_source, source
        FROM market_snapshots
        WHERE type_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (int(type_id), int(limit)),
    ).fetchall()
    return [dict(row) for row in rows]


def latest_asset_quantities_by_type(
    connection: sqlite3.Connection,
    *,
    type_ids: list[int] | tuple[int, ...],
) -> list[dict[str, Any]]:
    if not type_ids:
        return []

    placeholders = ",".join("?" for _ in type_ids)
    rows = connection.execute(
        f"""
        SELECT
            characters.id AS character_id,
            characters.name AS character_name,
            accounts.name AS account_name,
            account_groups.name AS group_name,
            character_assets.type_id,
            SUM(character_assets.quantity) AS quantity,
            COUNT(*) AS stacks,
            MAX(character_assets.synced_at) AS synced_at
        FROM character_assets
        JOIN characters ON characters.id = character_assets.character_id
        JOIN accounts ON accounts.id = characters.account_id
        JOIN account_groups ON account_groups.id = accounts.group_id
        WHERE character_assets.type_id IN ({placeholders})
        GROUP BY characters.id, character_assets.type_id
        ORDER BY account_groups.name, accounts.name, characters.name, character_assets.type_id
        """,
        tuple(int(type_id) for type_id in type_ids),
    ).fetchall()
    return [dict(row) for row in rows]


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _optional_bool(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0
