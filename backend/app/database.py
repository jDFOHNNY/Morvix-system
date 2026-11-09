"""SQLite connection and versioned schema initialization."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend.app import config

SCHEMA_VERSION = 3


def connect() -> sqlite3.Connection:
    path: Path = config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    return connection


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    db = connect()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database() -> None:
    """Create the initial schema. Future schema changes must use numbered migrations."""
    with connection() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS oauth_identities (
                provider TEXT NOT NULL,
                subject TEXT NOT NULL,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                PRIMARY KEY(provider, subject),
                UNIQUE(user_id, provider)
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                label TEXT NOT NULL,
                token_hash TEXT UNIQUE,
                pairing_code_hash TEXT UNIQUE,
                pairing_expires_at TEXT,
                paired_at TEXT,
                last_seen_at TEXT,
                revoked_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);
            CREATE TABLE IF NOT EXISTS policies (
                user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                protection_enabled INTEGER NOT NULL DEFAULT 1,
                modalities_json TEXT NOT NULL,
                category_actions_json TEXT NOT NULL,
                thresholds_json TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS rules (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK(kind IN ('website', 'category')),
                target TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('allow', 'warn', 'block')),
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, kind, target)
            );
            CREATE INDEX IF NOT EXISTS idx_rules_user_enabled ON rules(user_id, enabled);
            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                device_id TEXT REFERENCES devices(id) ON DELETE SET NULL,
                occurred_at TEXT NOT NULL,
                modality TEXT NOT NULL CHECK(modality IN ('text', 'image', 'video')),
                category TEXT NOT NULL,
                confidence REAL,
                action TEXT NOT NULL CHECK(action IN ('allow', 'warn', 'block')),
                source_domain TEXT,
                classifier_version TEXT,
                policy_reason TEXT,
                policy_version INTEGER,
                reviewed INTEGER NOT NULL DEFAULT 0,
                event_key TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, event_key)
            );
            CREATE INDEX IF NOT EXISTS idx_events_user_time ON events(user_id, occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_user_action ON events(user_id, action, occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_user_modality ON events(user_id, modality, occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_events_user_category ON events(user_id, category, occurred_at DESC);
            CREATE TABLE IF NOT EXISTS alerts (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                event_id TEXT NOT NULL UNIQUE REFERENCES events(id) ON DELETE CASCADE,
                severity TEXT NOT NULL CHECK(severity IN ('warning', 'blocked')),
                reviewed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_user_time ON alerts(user_id, created_at DESC);
            CREATE TABLE IF NOT EXISTS model_metadata (
                id TEXT PRIMARY KEY,
                modality TEXT NOT NULL,
                model_name TEXT NOT NULL,
                model_version TEXT NOT NULL,
                license TEXT,
                supported_labels_json TEXT NOT NULL,
                evaluation_reference TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(modality, model_name, model_version)
            );
            """
        )
        existing = db.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]
        if existing is None:
            from backend.app.time_utils import utc_now

            db.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, utc_now()),
            )
        elif existing == 1:
            from backend.app.time_utils import utc_now

            event_columns = {row["name"] for row in db.execute("PRAGMA table_info(events)")}
            if "policy_version" not in event_columns:
                db.execute("ALTER TABLE events ADD COLUMN policy_version INTEGER")
            db.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (2, utc_now()),
            )
            existing = 2
        if existing == 2:
            db.execute(
                "CREATE TABLE IF NOT EXISTS oauth_identities ("
                "provider TEXT NOT NULL, subject TEXT NOT NULL, "
                "user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                "created_at TEXT NOT NULL, PRIMARY KEY(provider, subject), UNIQUE(user_id, provider))"
            )
            from backend.app.time_utils import utc_now

            db.execute(
                "INSERT INTO schema_version(version, applied_at) VALUES (?, ?)",
                (3, utc_now()),
            )
        elif existing is not None and existing > SCHEMA_VERSION:
            raise RuntimeError("Database schema is newer than this application.")


def database_ready() -> bool:
    try:
        with connection() as db:
            db.execute("SELECT 1 FROM schema_version LIMIT 1").fetchone()
        return True
    except sqlite3.Error:
        return False

