from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

CREATE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    status      TEXT NOT NULL DEFAULT 'running',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""

CREATE_TASKS_TABLE = """
CREATE TABLE IF NOT EXISTS tasks (
    id                    TEXT PRIMARY KEY,
    run_id                TEXT NOT NULL,
    task_type             TEXT NOT NULL,
    status                TEXT NOT NULL DEFAULT 'PENDING',
    attempt_count         INTEGER NOT NULL DEFAULT 0,
    max_attempts          INTEGER NOT NULL DEFAULT 3,
    heartbeat_at          TEXT,
    error_class           TEXT,
    last_error            TEXT,
    payload_json          TEXT NOT NULL,
    session_context_json  TEXT,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(id)
);
"""

CREATE_TASK_ATTEMPTS_TABLE = """
CREATE TABLE IF NOT EXISTS task_attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id         TEXT NOT NULL,
    attempt_number  INTEGER NOT NULL,
    status          TEXT NOT NULL,
    error_class     TEXT,
    error_message   TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
"""

CREATE_TENDERS_TABLE = """
CREATE TABLE IF NOT EXISTS tenders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source          TEXT NOT NULL DEFAULT 'eprocure',
    tender_id       TEXT NOT NULL,
    title           TEXT,
    reference_number  TEXT,
    org_chain       TEXT,
    tender_type     TEXT,
    category        TEXT,
    tender_value    TEXT,
    emd_amount      TEXT,
    doc_fee         TEXT,
    closing_date    TEXT,
    opening_date    TEXT,
    published_date  TEXT,
    detail_url      TEXT,
    raw_json        TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE(source, tender_id)
);
"""


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(CREATE_RUNS_TABLE)
    conn.execute(CREATE_TASKS_TABLE)
    conn.execute(CREATE_TASK_ATTEMPTS_TABLE)
    conn.execute(CREATE_TENDERS_TABLE)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_run_id ON tasks(run_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_heartbeat ON tasks(heartbeat_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_attempts_task_id ON task_attempts(task_id)")
    conn.commit()
