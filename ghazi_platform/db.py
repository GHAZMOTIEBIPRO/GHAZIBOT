"""SQLite store for private user data.

SQLite keeps the alpha free of paid infrastructure. Every user-owned row has a
`user_id` column and every query in the repository modules filters on it, so a
later move to PostgreSQL with row-level security keeps the same shape.
This database is never written to `public/` or to `bot-state`.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    email_verified_at TEXT,
    -- Admin role is only ever set by the server-side owner command (never by an
    -- HTTP request); these record when and how it was granted.
    admin_granted_at TEXT,
    admin_granted_via TEXT,
    consent_version TEXT NOT NULL,
    consent_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    user_agent TEXT NOT NULL DEFAULT '',
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS one_time_tokens (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    purpose TEXT NOT NULL CHECK (purpose IN ('verify_email', 'reset_password')),
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT
);

-- Rate-limit and failed-login events. Keys are namespaced ("login:email:...",
-- "register:ip:..."); e-mail keys hold a SHA-256 of the address, not the address.
CREATE TABLE IF NOT EXISTS rate_events (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL,
    at_unix REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS rate_events_key ON rate_events(key, at_unix);

CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS watchlist_symbols (
    watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL,
    PRIMARY KEY (watchlist_id, symbol)
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    label TEXT NOT NULL,
    rights_attestation TEXT NOT NULL,
    bars_json TEXT NOT NULL,
    bar_count INTEGER NOT NULL,
    first_date TEXT NOT NULL,
    last_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS datasets_user ON datasets(user_id);

CREATE TABLE IF NOT EXISTS backtests (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    strategy TEXT NOT NULL,
    params_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    -- 'running' reserves a slot of the daily quota before the (slow) run starts
    status TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('running', 'done')),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS backtests_user ON backtests(user_id, created_at);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    plan TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'grace', 'canceled', 'expired')),
    source TEXT NOT NULL CHECK (source IN ('default', 'admin_grant', 'sandbox_billing')),
    current_period_end TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS billing_events (
    id INTEGER PRIMARY KEY,
    provider_event_id TEXT NOT NULL UNIQUE,
    user_id INTEGER,
    kind TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at TEXT NOT NULL,
    outcome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    actor_id INTEGER,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    ip TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_user ON audit_events(user_id, at);
"""


# Columns added after the first alpha schema: (table, column, definition).
_ADDED_COLUMNS = (
    ("users", "admin_granted_at", "TEXT"),
    ("users", "admin_granted_via", "TEXT"),
    ("backtests", "status", "TEXT NOT NULL DEFAULT 'done'"),
)


class Database:
    """One connection per thread; foreign keys enforced on every connection.

    Connections run in autocommit mode and every `tx()` opens BEGIN IMMEDIATE,
    which takes SQLite's write lock at the start. A "count, check the plan limit,
    insert" sequence inside one `tx()` is therefore atomic even across processes
    (several WSGI workers on one database file).
    """

    def __init__(self, path: str):
        self.path = path
        self._local = threading.local()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._shared = self._open() if path == ":memory:" else None
        self._lock = threading.RLock()
        with self._lock:
            conn = self._conn()
            conn.executescript(SCHEMA)
            for table, column, definition in _ADDED_COLUMNS:
                have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                if column not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '2')")
            conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None, check_same_thread=False)
        if self.path != ":memory:":
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _conn(self) -> sqlite3.Connection:
        if self._shared is not None:
            return self._shared
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._open()
            self._local.conn = conn
        return conn

    def tx(self) -> _Tx:
        return _Tx(self)

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn().execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None


class _Tx:
    def __init__(self, db: Database):
        self.db = db

    def __enter__(self) -> sqlite3.Connection:
        self.db._lock.acquire()
        try:
            self.conn = self.db._conn()
            self.conn.execute("BEGIN IMMEDIATE")
        except BaseException:
            self.db._lock.release()
            raise
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self.conn.execute("COMMIT" if exc_type is None else "ROLLBACK")
        finally:
            self.db._lock.release()
