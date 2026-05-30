"""SQLite database initialization for local tracking."""

from __future__ import annotations

import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "sp_farm.db"


def connect(db_path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """Open a SQLite connection with useful defaults."""

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    """Create local tables if they do not already exist."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS account_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            notes TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            omega_status TEXT NOT NULL DEFAULT 'Unknown',
            omega_expires_at TEXT,
            mct_slots INTEGER NOT NULL DEFAULT 0,
            wallet_balance REAL,
            sync_status TEXT NOT NULL DEFAULT 'Manual',
            notes TEXT NOT NULL DEFAULT '',
            UNIQUE(group_id, name),
            FOREIGN KEY(group_id) REFERENCES account_groups(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            eve_character_id INTEGER,
            total_sp INTEGER NOT NULL DEFAULT 0,
            total_sp_updated_at TEXT NOT NULL,
            training_rate_sp_min REAL NOT NULL DEFAULT 45,
            current_skill TEXT NOT NULL DEFAULT '',
            queue_ends_at TEXT,
            attribute_profile TEXT NOT NULL DEFAULT 'Optimized',
            implant_profile TEXT NOT NULL DEFAULT '+5',
            last_sync_at TEXT,
            sync_status TEXT NOT NULL DEFAULT 'Manual',
            notes TEXT NOT NULL DEFAULT '',
            UNIQUE(account_id, name),
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_characters_eve_character_id
        ON characters(eve_character_id)
        WHERE eve_character_id IS NOT NULL;

        CREATE TABLE IF NOT EXISTS sp_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            total_sp INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'Manual',
            notes TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS api_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL,
            eve_character_id INTEGER NOT NULL UNIQUE,
            scopes TEXT NOT NULL,
            encrypted_refresh_token TEXT NOT NULL,
            access_token_expires_at TEXT,
            last_refresh_at TEXT,
            last_sync_at TEXT,
            status TEXT NOT NULL DEFAULT 'Authorized',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sso_auth_states (
            state TEXT PRIMARY KEY,
            account_id INTEGER NOT NULL,
            code_verifier TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS character_skills (
            character_id INTEGER NOT NULL,
            skill_id INTEGER NOT NULL,
            active_skill_level INTEGER NOT NULL DEFAULT 0,
            trained_skill_level INTEGER NOT NULL DEFAULT 0,
            skillpoints_in_skill INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT NOT NULL,
            PRIMARY KEY(character_id, skill_id),
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS skill_queue_entries (
            character_id INTEGER NOT NULL,
            queue_position INTEGER NOT NULL,
            skill_id INTEGER NOT NULL,
            finished_level INTEGER NOT NULL,
            start_date TEXT,
            finish_date TEXT,
            training_start_sp INTEGER,
            level_start_sp INTEGER,
            level_end_sp INTEGER,
            synced_at TEXT NOT NULL,
            PRIMARY KEY(character_id, queue_position),
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS wallet_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            character_id INTEGER NOT NULL,
            timestamp TEXT NOT NULL,
            balance REAL NOT NULL,
            source TEXT NOT NULL DEFAULT 'ESI',
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS character_assets (
            character_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            type_id INTEGER NOT NULL,
            quantity INTEGER NOT NULL,
            location_id INTEGER NOT NULL,
            location_type TEXT NOT NULL,
            location_flag TEXT NOT NULL,
            is_blueprint_copy INTEGER,
            is_singleton INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT NOT NULL,
            PRIMARY KEY(character_id, item_id),
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS market_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            region_id INTEGER NOT NULL,
            location_id INTEGER,
            type_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            best_buy_price REAL,
            best_sell_price REAL,
            average_price REAL,
            adjusted_price REAL,
            buy_volume INTEGER NOT NULL DEFAULT 0,
            sell_volume INTEGER NOT NULL DEFAULT 0,
            order_count INTEGER NOT NULL DEFAULT 0,
            price_source TEXT NOT NULL DEFAULT 'order_book',
            source TEXT NOT NULL DEFAULT 'ESI'
        );
        """
    )
    _ensure_column(connection, "characters", "last_sync_at", "TEXT")
    _ensure_column(connection, "characters", "sync_status", "TEXT NOT NULL DEFAULT 'Manual'")
    _ensure_column(connection, "market_snapshots", "average_price", "REAL")
    _ensure_column(connection, "market_snapshots", "adjusted_price", "REAL")
    _ensure_column(
        connection,
        "market_snapshots",
        "price_source",
        "TEXT NOT NULL DEFAULT 'order_book'",
    )
    connection.commit()


def ensure_database(
    db_path: str | Path = DEFAULT_DB_PATH,
    *,
    seed: bool = True,
) -> sqlite3.Connection:
    """Open, initialize, and optionally seed the local database."""

    connection = connect(db_path)
    initialize_database(connection)
    if seed:
        seed_demo_data(connection)
    return connection


def seed_demo_data(connection: sqlite3.Connection) -> None:
    """Seed non-private sample data only when the database is empty."""

    existing = connection.execute("SELECT COUNT(*) FROM account_groups").fetchone()[0]
    if existing:
        return

    connection.executescript(
        """
        INSERT INTO account_groups (name, notes)
        VALUES
            ('Main Farm Cluster', 'Example local data. Replace with real accounts.'),
            ('Alt Farm Cluster', 'Example local data. Replace with real accounts.');

        INSERT INTO accounts (
            group_id, name, omega_status, omega_expires_at, mct_slots,
            wallet_balance, sync_status, notes
        )
        VALUES
            (1, 'Farm Account 01', 'Omega', '2026-06-30T00:00:00+00:00', 2, NULL, 'Manual', ''),
            (1, 'Farm Account 02', 'Omega', '2026-06-21T00:00:00+00:00', 1, NULL, 'Manual', ''),
            (2, 'Alt Account 01', 'Omega', '2026-06-12T00:00:00+00:00', 0, NULL, 'Manual', '');

        INSERT INTO characters (
            account_id, name, eve_character_id, total_sp, total_sp_updated_at,
            training_rate_sp_min, current_skill, queue_ends_at,
            attribute_profile, implant_profile, notes
        )
        VALUES
            (1, 'Example Farmer A', NULL, 5480000, '2026-05-30T00:00:00+00:00', 45, 'Biology V', '2026-05-31T09:00:00+00:00', 'Optimized Int/Mem', '+5', 'Sample character near extraction threshold.'),
            (1, 'Example Farmer B', NULL, 6210000, '2026-05-30T00:00:00+00:00', 45, 'Cybernetics V', '2026-06-02T12:00:00+00:00', 'Optimized Int/Mem', '+5', 'Sample character ready to extract.'),
            (2, 'Example Farmer C', NULL, 5010000, '2026-05-30T00:00:00+00:00', 45, 'Science V', '2026-06-07T18:00:00+00:00', 'Optimized Int/Mem', '+4', 'Sample character below ready threshold.'),
            (3, 'Example Farmer D', NULL, 7420000, '2026-05-30T00:00:00+00:00', 45, 'Neural Enhancement V', '2026-06-01T04:00:00+00:00', 'Optimized Int/Mem', '+5', 'Sample character with multiple injectors available.');

        INSERT INTO sp_snapshots (character_id, timestamp, total_sp, source, notes)
        VALUES
            (1, '2026-05-30T00:00:00+00:00', 5480000, 'Seed', ''),
            (2, '2026-05-30T00:00:00+00:00', 6210000, 'Seed', ''),
            (3, '2026-05-30T00:00:00+00:00', 5010000, 'Seed', ''),
            (4, '2026-05-30T00:00:00+00:00', 7420000, 'Seed', '');
        """
    )
    connection.commit()


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_definition: str,
) -> None:
    columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in columns:
        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )
