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
            accounts.mct_expires_at,
            accounts.operational_status,
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
            accounts.mct_slots, accounts.mct_expires_at,
            accounts.operational_status, accounts.wallet_balance,
            accounts.sync_status, accounts.notes
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
    mct_expires_at: str | None = None,
    operational_status: str = "Active",
    notes: str = "",
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO accounts (
            group_id, name, omega_status, omega_expires_at, mct_slots,
            mct_expires_at, operational_status, sync_status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'Manual', ?)
        """,
        (
            group_id,
            name,
            omega_status,
            omega_expires_at,
            mct_slots,
            mct_expires_at,
            operational_status,
            notes,
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)


def update_account_operations(
    connection: sqlite3.Connection,
    *,
    account_id: int,
    omega_status: str,
    omega_expires_at: str | None,
    mct_slots: int,
    mct_expires_at: str | None,
    operational_status: str,
    notes: str,
) -> None:
    connection.execute(
        """
        UPDATE accounts
        SET omega_status = ?, omega_expires_at = ?, mct_slots = ?,
            mct_expires_at = ?, operational_status = ?, notes = ?
        WHERE id = ?
        """,
        (
            omega_status,
            omega_expires_at,
            int(mct_slots),
            mct_expires_at,
            operational_status,
            notes,
            int(account_id),
        ),
    )
    connection.commit()


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


def record_extraction_event(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    injectors_created: int,
    sp_extracted: int,
    extractor_unit_cost: float,
    extractor_total_cost: float,
    lsi_sale_unit_price: float,
    gross_revenue: float,
    market_fees: float,
    realized_revenue: float,
    realized_profit: float,
    total_sp_before: int,
    total_sp_after: int,
    status: str = "Completed",
    notes: str = "",
    timestamp: str | None = None,
) -> int:
    """Persist one extraction event and apply completed events to the SP baseline."""

    recorded_at = timestamp or datetime.now(timezone.utc).isoformat()
    if status not in {"Planned", "Completed"}:
        raise ValueError("Extraction status must be Planned or Completed.")
    cursor = connection.execute(
        """
        INSERT INTO extraction_events (
            character_id, timestamp, injectors_created, sp_extracted,
            extractor_unit_cost, extractor_total_cost, lsi_sale_unit_price,
            gross_revenue, market_fees, realized_revenue, realized_profit,
            total_sp_before, total_sp_after, status, reconciliation_status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(character_id),
            recorded_at,
            int(injectors_created),
            int(sp_extracted),
            float(extractor_unit_cost),
            float(extractor_total_cost),
            float(lsi_sale_unit_price),
            float(gross_revenue),
            float(market_fees),
            float(realized_revenue),
            float(realized_profit),
            int(total_sp_before),
            int(total_sp_after),
            status,
            "Pending" if status == "Completed" else "Not Due",
            notes,
        ),
    )
    if status == "Completed":
        _apply_extraction_sp_baseline(
            connection,
            character_id=character_id,
            total_sp_after=total_sp_after,
            recorded_at=recorded_at,
            notes=notes,
        )
    connection.commit()
    return int(cursor.lastrowid)


def complete_planned_extraction_event(
    connection: sqlite3.Connection,
    *,
    event_id: int,
    total_sp_before: int,
    total_sp_after: int,
    extractor_unit_cost: float,
    extractor_total_cost: float,
    lsi_sale_unit_price: float,
    gross_revenue: float,
    market_fees: float,
    realized_revenue: float,
    realized_profit: float,
    notes: str = "",
    timestamp: str | None = None,
) -> None:
    """Transition a planned extraction to completed and reset the SP baseline."""

    recorded_at = timestamp or datetime.now(timezone.utc).isoformat()
    event = connection.execute(
        """
        SELECT character_id, status
        FROM extraction_events
        WHERE id = ?
        """,
        (int(event_id),),
    ).fetchone()
    if not event:
        raise ValueError("Extraction event was not found.")
    if event["status"] != "Planned":
        raise ValueError("Only planned extraction events can be completed.")
    connection.execute(
        """
        UPDATE extraction_events
        SET timestamp = ?, extractor_unit_cost = ?, extractor_total_cost = ?,
            lsi_sale_unit_price = ?, gross_revenue = ?, market_fees = ?,
            realized_revenue = ?, realized_profit = ?, total_sp_before = ?,
            total_sp_after = ?, status = 'Completed',
            reconciliation_status = 'Pending', notes = ?
        WHERE id = ?
        """,
        (
            recorded_at,
            float(extractor_unit_cost),
            float(extractor_total_cost),
            float(lsi_sale_unit_price),
            float(gross_revenue),
            float(market_fees),
            float(realized_revenue),
            float(realized_profit),
            int(total_sp_before),
            int(total_sp_after),
            notes,
            int(event_id),
        ),
    )
    _apply_extraction_sp_baseline(
        connection,
        character_id=int(event["character_id"]),
        total_sp_after=total_sp_after,
        recorded_at=recorded_at,
        notes=notes,
    )
    connection.commit()


def get_extraction_event(
    connection: sqlite3.Connection,
    *,
    event_id: int,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM extraction_events
        WHERE id = ?
        """,
        (int(event_id),),
    ).fetchone()
    return dict(row) if row else None


def list_pending_completed_extraction_events(
    connection: sqlite3.Connection,
    *,
    character_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM extraction_events
        WHERE character_id = ?
          AND status = 'Completed'
          AND reconciliation_status = 'Pending'
        ORDER BY timestamp, id
        """,
        (int(character_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def record_extraction_reconciliation(
    connection: sqlite3.Connection,
    *,
    event_ids: list[int] | tuple[int, ...],
    reconciliation_status: str,
    esi_total_sp: int,
    expected_total_sp: int,
    reconciliation_delta_sp: int,
    reconciliation_message: str,
    reconciled_at: str | None = None,
) -> None:
    if not event_ids:
        return
    if reconciliation_status not in {"Match", "Drift"}:
        raise ValueError("Reconciliation status must be Match or Drift.")
    recorded_at = reconciled_at or datetime.now(timezone.utc).isoformat()
    placeholders = ",".join("?" for _ in event_ids)
    status_update = ", status = 'Reconciled'" if reconciliation_status == "Match" else ""
    connection.execute(
        f"""
        UPDATE extraction_events
        SET reconciliation_status = ?, reconciled_at = ?, esi_total_sp = ?,
            expected_total_sp = ?, reconciliation_delta_sp = ?,
            reconciliation_message = ?{status_update}
        WHERE id IN ({placeholders})
        """,
        (
            reconciliation_status,
            recorded_at,
            int(esi_total_sp),
            int(expected_total_sp),
            int(reconciliation_delta_sp),
            reconciliation_message,
            *[int(event_id) for event_id in event_ids],
        ),
    )
    connection.commit()


def _apply_extraction_sp_baseline(
    connection: sqlite3.Connection,
    *,
    character_id: int,
    total_sp_after: int,
    recorded_at: str,
    notes: str,
) -> None:
    connection.execute(
        """
        UPDATE characters
        SET total_sp = ?, total_sp_updated_at = ?
        WHERE id = ?
        """,
        (int(total_sp_after), recorded_at, int(character_id)),
    )
    connection.execute(
        """
        INSERT INTO sp_snapshots (character_id, timestamp, total_sp, source, notes)
        VALUES (?, ?, ?, 'Extraction', ?)
        """,
        (int(character_id), recorded_at, int(total_sp_after), notes or "Extraction event"),
    )


def list_extraction_events(
    connection: sqlite3.Connection,
    *,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            extraction_events.*,
            characters.name AS character_name,
            accounts.name AS account_name,
            account_groups.name AS group_name
        FROM extraction_events
        JOIN characters ON characters.id = extraction_events.character_id
        JOIN accounts ON accounts.id = characters.account_id
        JOIN account_groups ON account_groups.id = accounts.group_id
        ORDER BY extraction_events.timestamp DESC, extraction_events.id DESC
        LIMIT ?
        """,
        (int(limit),),
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


def create_loot_session(
    connection: sqlite3.Connection,
    *,
    assets_by_character: dict[int, list[dict[str, Any]]],
    notes: str = "",
    started_at: str | None = None,
) -> int:
    """Create a loot session and persist its starting asset evidence."""

    if not assets_by_character:
        raise ValueError("Select at least one character before starting loot tracking.")
    recorded_at = started_at or datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        """
        INSERT INTO loot_sessions (status, started_at, notes)
        VALUES ('Active', ?, ?)
        """,
        (recorded_at, notes),
    )
    session_id = int(cursor.lastrowid)
    connection.executemany(
        """
        INSERT INTO loot_session_characters (session_id, character_id)
        VALUES (?, ?)
        """,
        [(session_id, int(character_id)) for character_id in assets_by_character],
    )
    _insert_loot_asset_snapshot_rows(
        connection,
        session_id=session_id,
        phase="Start",
        captured_at=recorded_at,
        assets_by_character=assets_by_character,
    )
    connection.commit()
    return session_id


def replace_loot_end_snapshots(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    assets_by_character: dict[int, list[dict[str, Any]]],
    captured_at: str | None = None,
) -> None:
    """Replace the latest end snapshot for a loot session."""

    recorded_at = captured_at or datetime.now(timezone.utc).isoformat()
    connection.execute(
        "DELETE FROM loot_asset_snapshots WHERE session_id = ? AND phase = 'End'",
        (int(session_id),),
    )
    _insert_loot_asset_snapshot_rows(
        connection,
        session_id=session_id,
        phase="End",
        captured_at=recorded_at,
        assets_by_character=assets_by_character,
    )
    connection.execute(
        """
        UPDATE loot_sessions
        SET status = 'Awaiting Confirmation', end_snapshot_at = ?
        WHERE id = ?
        """,
        (recorded_at, int(session_id)),
    )
    connection.commit()


def get_open_loot_session(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM loot_sessions
        WHERE status IN ('Active', 'Awaiting Confirmation')
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def get_loot_session(
    connection: sqlite3.Connection,
    *,
    session_id: int,
) -> dict[str, Any] | None:
    row = connection.execute(
        "SELECT * FROM loot_sessions WHERE id = ?",
        (int(session_id),),
    ).fetchone()
    return dict(row) if row else None


def list_loot_session_characters(
    connection: sqlite3.Connection,
    *,
    session_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            characters.id AS character_id,
            characters.eve_character_id,
            characters.name AS character_name,
            accounts.name AS account_name,
            account_groups.name AS group_name
        FROM loot_session_characters
        JOIN characters ON characters.id = loot_session_characters.character_id
        JOIN accounts ON accounts.id = characters.account_id
        JOIN account_groups ON account_groups.id = accounts.group_id
        WHERE loot_session_characters.session_id = ?
        ORDER BY account_groups.name, accounts.name, characters.name
        """,
        (int(session_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def list_loot_asset_diff_by_type(
    connection: sqlite3.Connection,
    *,
    session_id: int,
) -> list[dict[str, Any]]:
    """Return positive combined asset differences across selected characters."""

    rows = connection.execute(
        """
        WITH start_totals AS (
            SELECT type_id, SUM(quantity) AS quantity
            FROM loot_asset_snapshots
            WHERE session_id = ? AND phase = 'Start'
            GROUP BY type_id
        ),
        end_totals AS (
            SELECT type_id, SUM(quantity) AS quantity
            FROM loot_asset_snapshots
            WHERE session_id = ? AND phase = 'End'
            GROUP BY type_id
        )
        SELECT
            end_totals.type_id,
            end_totals.quantity - COALESCE(start_totals.quantity, 0) AS quantity
        FROM end_totals
        LEFT JOIN start_totals ON start_totals.type_id = end_totals.type_id
        WHERE end_totals.quantity - COALESCE(start_totals.quantity, 0) > 0
        ORDER BY end_totals.type_id
        """,
        (int(session_id), int(session_id)),
    ).fetchall()
    return [dict(row) for row in rows]


def list_loot_end_holders_by_type(
    connection: sqlite3.Connection,
    *,
    session_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            loot_asset_snapshots.type_id,
            characters.name AS character_name,
            SUM(loot_asset_snapshots.quantity) AS quantity
        FROM loot_asset_snapshots
        JOIN characters ON characters.id = loot_asset_snapshots.character_id
        WHERE loot_asset_snapshots.session_id = ?
          AND loot_asset_snapshots.phase = 'End'
        GROUP BY loot_asset_snapshots.type_id, characters.id
        ORDER BY loot_asset_snapshots.type_id, characters.name
        """,
        (int(session_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def replace_loot_asset_diff_items(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    items: list[dict[str, Any]],
) -> None:
    """Replace generated asset-diff items while preserving manual additions."""

    timestamp = datetime.now(timezone.utc).isoformat()
    connection.execute(
        "DELETE FROM loot_session_items WHERE session_id = ? AND item_source = 'Asset diff'",
        (int(session_id),),
    )
    connection.executemany(
        """
        INSERT INTO loot_session_items (
            session_id, type_id, item_name, quantity, unit_value_isk,
            total_value_isk, price_source, included, item_source, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'Asset diff', ?)
        """,
        [
            (
                int(session_id),
                int(item["type_id"]),
                str(item["item_name"]),
                int(item["quantity"]),
                float(item.get("unit_value_isk", 0)),
                float(item.get("total_value_isk", 0)),
                str(item.get("price_source", "Unpriced")),
                timestamp,
            )
            for item in items
        ],
    )
    connection.commit()


def add_manual_loot_item(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    item_name: str,
    quantity: int,
    unit_value_isk: float,
) -> int:
    timestamp = datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        """
        INSERT INTO loot_session_items (
            session_id, type_id, item_name, quantity, unit_value_isk,
            total_value_isk, price_source, included, item_source, updated_at
        )
        VALUES (?, NULL, ?, ?, ?, ?, 'Manual', 1, 'Manual', ?)
        """,
        (
            int(session_id),
            item_name,
            int(quantity),
            float(unit_value_isk),
            int(quantity) * float(unit_value_isk),
            timestamp,
        ),
    )
    connection.commit()
    return int(cursor.lastrowid)


def list_loot_session_items(
    connection: sqlite3.Connection,
    *,
    session_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            loot_session_items.id,
            loot_session_items.session_id,
            loot_session_items.type_id,
            loot_session_items.item_name,
            loot_session_items.normalized_name,
            loot_session_items.quantity,
            loot_session_items.unit_value_isk,
            loot_session_items.total_value_isk,
            loot_session_items.price_source,
            loot_session_items.included,
            loot_session_items.item_source,
            loot_session_items.updated_at,
            loot_item_price_cache.priced_at AS market_priced_at
        FROM loot_session_items
        LEFT JOIN loot_item_price_cache
            ON loot_item_price_cache.normalized_name = loot_session_items.normalized_name
        WHERE loot_session_items.session_id = ?
        ORDER BY loot_session_items.total_value_isk DESC, loot_session_items.item_name
        """,
        (int(session_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def create_clipboard_loot_session(
    connection: sqlite3.Connection,
    *,
    notes: str = "",
    started_at: str | None = None,
) -> int:
    """Create one global clipboard-driven loot tracking run."""

    recorded_at = started_at or datetime.now(timezone.utc).isoformat()
    cursor = connection.execute(
        """
        INSERT INTO loot_sessions (status, started_at, notes)
        VALUES ('Active', ?, ?)
        """,
        (recorded_at, notes),
    )
    connection.commit()
    return int(cursor.lastrowid)


def get_active_clipboard_loot_session(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM loot_sessions
        WHERE status = 'Active'
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """
    ).fetchone()
    return dict(row) if row else None


def record_clipboard_loot_import(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    character_id: int | None,
    raw_text: str,
    items: list[dict[str, Any]],
    parsed_item_count: int,
    ignored_item_count: int,
    imported_at: str | None = None,
) -> int:
    """Persist one pasted cargo block and add accepted quantities to the run."""

    recorded_at = imported_at or datetime.now(timezone.utc).isoformat()
    imported_value = sum(float(item["total_value_isk"]) for item in items)
    cursor = connection.execute(
        """
        INSERT INTO loot_imports (
            session_id, character_id, imported_at, raw_text, parsed_item_count,
            accepted_item_count, ignored_item_count, imported_value_isk
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(session_id),
            int(character_id) if character_id is not None else None,
            recorded_at,
            raw_text,
            int(parsed_item_count),
            len(items),
            int(ignored_item_count),
            float(imported_value),
        ),
    )
    for item in items:
        existing = connection.execute(
            """
            SELECT id, quantity, unit_value_isk, price_source
            FROM loot_session_items
            WHERE session_id = ? AND normalized_name = ?
            LIMIT 1
            """,
            (int(session_id), str(item["normalized_name"])),
        ).fetchone()
        incoming_unit_value = float(item["unit_value_isk"])
        if existing:
            quantity = int(existing["quantity"]) + int(item["quantity"])
            unit_value = (
                incoming_unit_value
                if incoming_unit_value > 0
                else float(existing["unit_value_isk"])
            )
            price_source = (
                str(item["price_source"])
                if incoming_unit_value > 0
                else str(existing["price_source"])
            )
            connection.execute(
                """
                UPDATE loot_session_items
                SET item_name = ?, quantity = ?, unit_value_isk = ?,
                    total_value_isk = ?, price_source = ?, included = 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    str(item["item_name"]),
                    quantity,
                    unit_value,
                    quantity * unit_value,
                    price_source,
                    recorded_at,
                    int(existing["id"]),
                ),
            )
        else:
            connection.execute(
                """
                INSERT INTO loot_session_items (
                    session_id, type_id, item_name, normalized_name, quantity,
                    unit_value_isk, total_value_isk, price_source, included,
                    item_source, updated_at
                )
                VALUES (?, NULL, ?, ?, ?, ?, ?, ?, 1, 'Clipboard', ?)
                """,
                (
                    int(session_id),
                    str(item["item_name"]),
                    str(item["normalized_name"]),
                    int(item["quantity"]),
                    incoming_unit_value,
                    float(item["total_value_isk"]),
                    str(item["price_source"]),
                    recorded_at,
                ),
            )
    connection.commit()
    return int(cursor.lastrowid)


def list_clipboard_loot_imports(
    connection: sqlite3.Connection,
    *,
    session_id: int,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            loot_imports.id,
            loot_imports.session_id,
            loot_imports.character_id,
            characters.name AS character_name,
            loot_imports.imported_at,
            loot_imports.parsed_item_count,
            loot_imports.accepted_item_count,
            loot_imports.ignored_item_count,
            loot_imports.imported_value_isk
        FROM loot_imports
        LEFT JOIN characters ON characters.id = loot_imports.character_id
        WHERE loot_imports.session_id = ?
        ORDER BY loot_imports.imported_at DESC, loot_imports.id DESC
        """,
        (int(session_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def update_clipboard_loot_item(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    item_id: int,
    quantity: int,
    unit_value_isk: float,
) -> None:
    connection.execute(
        """
        UPDATE loot_session_items
        SET quantity = ?, unit_value_isk = ?, total_value_isk = ?, updated_at = ?
        WHERE id = ? AND session_id = ?
        """,
        (
            int(quantity),
            float(unit_value_isk),
            int(quantity) * float(unit_value_isk),
            datetime.now(timezone.utc).isoformat(),
            int(item_id),
            int(session_id),
        ),
    )
    connection.commit()


def delete_clipboard_loot_item(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    item_id: int,
) -> None:
    connection.execute(
        "DELETE FROM loot_session_items WHERE id = ? AND session_id = ?",
        (int(item_id), int(session_id)),
    )
    connection.commit()


def complete_clipboard_loot_session(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    confirmed_at: str | None = None,
) -> None:
    recorded_at = confirmed_at or datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        UPDATE loot_sessions
        SET status = 'Confirmed', confirmed_at = ?
        WHERE id = ? AND status = 'Active'
        """,
        (recorded_at, int(session_id)),
    )
    connection.commit()


def list_loot_excluded_items(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT normalized_name, item_name, created_at
        FROM loot_excluded_items
        ORDER BY item_name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def add_loot_excluded_item(
    connection: sqlite3.Connection,
    *,
    normalized_name: str,
    item_name: str,
    remove_from_session_id: int | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO loot_excluded_items (normalized_name, item_name, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(normalized_name) DO UPDATE SET item_name = excluded.item_name
        """,
        (normalized_name, item_name, datetime.now(timezone.utc).isoformat()),
    )
    if remove_from_session_id is not None:
        connection.execute(
            """
            DELETE FROM loot_session_items
            WHERE session_id = ? AND normalized_name = ?
            """,
            (int(remove_from_session_id), normalized_name),
        )
    connection.commit()


def remove_loot_excluded_item(
    connection: sqlite3.Connection,
    *,
    normalized_name: str,
) -> None:
    connection.execute(
        "DELETE FROM loot_excluded_items WHERE normalized_name = ?",
        (normalized_name,),
    )
    connection.commit()


def list_loot_item_price_cache(
    connection: sqlite3.Connection,
    *,
    normalized_names: list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    if not normalized_names:
        return []

    placeholders = ",".join("?" for _ in normalized_names)
    rows = connection.execute(
        f"""
        SELECT normalized_name, item_name, type_id, unit_value_isk,
               price_source, priced_at
        FROM loot_item_price_cache
        WHERE normalized_name IN ({placeholders})
        ORDER BY item_name
        """,
        tuple(str(name) for name in normalized_names),
    ).fetchall()
    return [dict(row) for row in rows]


def upsert_loot_item_price_cache(
    connection: sqlite3.Connection,
    *,
    items: list[dict[str, Any]],
) -> None:
    connection.executemany(
        """
        INSERT INTO loot_item_price_cache (
            normalized_name, item_name, type_id, unit_value_isk,
            price_source, priced_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(normalized_name) DO UPDATE SET
            item_name = excluded.item_name,
            type_id = excluded.type_id,
            unit_value_isk = excluded.unit_value_isk,
            price_source = excluded.price_source,
            priced_at = excluded.priced_at
        """,
        [
            (
                str(item["normalized_name"]),
                str(item["item_name"]),
                int(item["type_id"]) if item.get("type_id") is not None else None,
                float(item["unit_value_isk"]),
                str(item["price_source"]),
                str(item["priced_at"]),
            )
            for item in items
        ],
    )
    connection.commit()


def apply_loot_item_prices(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    items: list[dict[str, Any]],
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    connection.executemany(
        """
        UPDATE loot_session_items
        SET type_id = ?, normalized_name = ?, unit_value_isk = ?,
            total_value_isk = ?, price_source = ?, updated_at = ?
        WHERE session_id = ? AND id = ?
        """,
        [
            (
                int(item["type_id"]) if item.get("type_id") is not None else None,
                str(item["normalized_name"]),
                float(item["unit_value_isk"]),
                int(item["quantity"]) * float(item["unit_value_isk"]),
                str(item["price_source"]),
                timestamp,
                int(session_id),
                int(item["id"]),
            )
            for item in items
        ],
    )
    connection.commit()


def update_loot_session_items(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    items: list[dict[str, Any]],
) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    connection.executemany(
        """
        UPDATE loot_session_items
        SET included = ?, quantity = ?, unit_value_isk = ?,
            total_value_isk = ?, updated_at = ?
        WHERE id = ? AND session_id = ?
        """,
        [
            (
                1 if bool(item.get("included", True)) else 0,
                int(item["quantity"]),
                float(item["unit_value_isk"]),
                int(item["quantity"]) * float(item["unit_value_isk"]),
                timestamp,
                int(item["id"]),
                int(session_id),
            )
            for item in items
        ],
    )
    connection.commit()


def confirm_loot_session(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    confirmed_at: str | None = None,
) -> None:
    timestamp = confirmed_at or datetime.now(timezone.utc).isoformat()
    connection.execute(
        """
        UPDATE loot_sessions
        SET status = 'Confirmed', confirmed_at = ?
        WHERE id = ? AND status = 'Awaiting Confirmation'
        """,
        (timestamp, int(session_id)),
    )
    connection.commit()


def list_loot_sessions(
    connection: sqlite3.Connection,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            loot_sessions.*,
            COALESCE(character_totals.character_count, 0) AS character_count,
            COALESCE(item_totals.total_value_isk, 0) AS total_value_isk
        FROM loot_sessions
        LEFT JOIN (
            SELECT session_id, COUNT(*) AS character_count
            FROM loot_session_characters
            GROUP BY session_id
        ) character_totals ON character_totals.session_id = loot_sessions.id
        LEFT JOIN (
            SELECT
                session_id,
                SUM(
                    CASE
                        WHEN included = 1 THEN total_value_isk
                        ELSE 0
                    END
                ) AS total_value_isk
            FROM loot_session_items
            GROUP BY session_id
        ) item_totals ON item_totals.session_id = loot_sessions.id
        ORDER BY loot_sessions.started_at DESC, loot_sessions.id DESC
        LIMIT ?
        """,
        (int(limit),),
    ).fetchall()
    return [dict(row) for row in rows]


def _insert_loot_asset_snapshot_rows(
    connection: sqlite3.Connection,
    *,
    session_id: int,
    phase: str,
    captured_at: str,
    assets_by_character: dict[int, list[dict[str, Any]]],
) -> None:
    connection.executemany(
        """
        INSERT INTO loot_asset_snapshots (
            session_id, character_id, phase, item_id, type_id, quantity,
            location_id, location_type, location_flag, captured_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                int(session_id),
                int(character_id),
                phase,
                int(asset["item_id"]),
                int(asset["type_id"]),
                int(asset.get("quantity", 1)),
                int(asset["location_id"]),
                str(asset.get("location_type", "")),
                str(asset.get("location_flag", "")),
                captured_at,
            )
            for character_id, assets in assets_by_character.items()
            for asset in assets
        ],
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
