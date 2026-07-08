from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    event_type TEXT NOT NULL,
    ticket INTEGER,
    symbol TEXT,
    open_price REAL,
    close_price REAL,
    profit REAL,
    message TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    UNIQUE(account, event_type, ticket)
);

CREATE TABLE IF NOT EXISTS pending_state (
    account TEXT NOT NULL,
    ticket INTEGER NOT NULL,
    near_alert_sent INTEGER NOT NULL DEFAULT 0,
    last_distance REAL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (account, ticket)
);

CREATE TABLE IF NOT EXISTS position_state (
    account TEXT NOT NULL,
    ticket INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    open_price REAL NOT NULL,
    pending_ticket INTEGER,
    triggered_at TEXT NOT NULL,
    position_type INTEGER NOT NULL DEFAULT 0,
    volume REAL NOT NULL DEFAULT 0,
    sl REAL NOT NULL DEFAULT 0,
    tp REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (account, ticket)
);

CREATE TABLE IF NOT EXISTS weekly_summary_sent (
    account TEXT NOT NULL,
    week_start TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (account, week_start)
);

CREATE TABLE IF NOT EXISTS watcher_status (
    account TEXT PRIMARY KEY,
    connected INTEGER NOT NULL DEFAULT 0,
    last_poll_at TEXT,
    last_error TEXT
);
"""


def _migrate_schema(conn: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(position_state)").fetchall()
    }
    additions = {
        "position_type": "INTEGER NOT NULL DEFAULT 0",
        "volume": "REAL NOT NULL DEFAULT 0",
        "sl": "REAL NOT NULL DEFAULT 0",
        "tp": "REAL NOT NULL DEFAULT 0",
    }
    for name, ddl in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE position_state ADD COLUMN {name} {ddl}")
    conn.commit()


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate_schema(conn)
    conn.commit()
    return conn
