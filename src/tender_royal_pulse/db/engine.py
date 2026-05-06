from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from tender_royal_pulse.db.schema import initialize_schema


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")  # wait up to 5 s instead of immediate failure
    return conn


def create_database(db_path: str | Path) -> sqlite3.Connection:
    conn = get_connection(db_path)
    initialize_schema(conn)
    return conn


@contextmanager
def database_session(db_path: str | Path) -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
