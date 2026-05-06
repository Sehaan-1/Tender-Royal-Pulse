"""Schema migration runner for TenderPulse.

Each migration is a plain function that receives an open ``sqlite3.Connection``
and applies exactly one forward-only schema change.  Migrations are idempotent:
every DDL statement uses ``IF NOT EXISTS`` / ``IF NOT EXISTS`` guards so they
can be safely re-run without error even if interrupted mid-flight.

Adding a new migration
----------------------
1. Write ``def migrate_NNN_description(conn): ...`` below.
2. Append it to the ``MIGRATIONS`` list at the bottom of this file.
3. Bump ``SCHEMA_VERSION`` in ``schema.py`` to match len(MIGRATIONS).

The runner records every applied version in the ``schema_migrations`` table
so each migration runs at most once per database file.
"""
from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bootstrap: tracking table
# ---------------------------------------------------------------------------

_CREATE_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL
);
"""


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(_CREATE_MIGRATIONS_TABLE)


def _applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def _record_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, ?)",
        (version, datetime.now(UTC).isoformat()),
    )


# ---------------------------------------------------------------------------
# Migration 001 — missing indexes
# ---------------------------------------------------------------------------

def migrate_001_add_missing_indexes(conn: sqlite3.Connection) -> None:
    """Add composite / covering indexes that speed up the most common queries.

    * ``tasks(run_id, status)``  — covers ``get_pending_tasks`` and
      ``recover_stale_tasks`` without a full table scan.
    * ``task_attempts(task_id)`` — covers attempt history lookups.
    * ``runs(status)``           — covers status-filtered run queries.

    All three use ``IF NOT EXISTS`` so running against a DB that already has
    them (e.g. freshly initialised via ``initialize_schema``) is a no-op.
    """
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_tasks_run_id_status"
        " ON tasks(run_id, status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_task_attempts_task_id"
        " ON task_attempts(task_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runs_status"
        " ON runs(status)"
    )
    logger.info("migration 001: indexes ensured")


# ---------------------------------------------------------------------------
# Migration 002 — cast monetary TEXT columns to REAL
# ---------------------------------------------------------------------------

def migrate_002_monetary_fields_to_real(conn: sqlite3.Connection) -> None:
    """Migrate ``tender_value``, ``emd_amount``, ``doc_fee`` from TEXT to REAL.

    SQLite does not support ``ALTER COLUMN``.  The standard approach is the
    12-step table-rebuild procedure:

    1. Rename old table.
    2. Create new table with updated column types.
    3. Copy data, casting TEXT → REAL via ``CAST(... AS REAL)`` (NULLs and
       non-numeric strings become NULL, not an error).
    4. Drop old table.
    5. Re-create any indexes on the new table.

    The whole operation runs inside the caller's transaction so it is atomic.
    """
    # Check whether the column is already REAL — if so, skip.
    col_info = conn.execute("PRAGMA table_info(tenders)").fetchall()
    col_types = {row[1]: row[2].upper() for row in col_info}

    monetary_cols = ("tender_value", "emd_amount", "doc_fee")
    already_real = all(col_types.get(c, "") == "REAL" for c in monetary_cols)
    if already_real:
        logger.info("migration 002: monetary columns already REAL, skipping rebuild")
        return

    logger.info("migration 002: rebuilding tenders table with REAL monetary columns")

    # Step 1 — rename old table
    conn.execute("ALTER TABLE tenders RENAME TO tenders_old")

    # Step 2 — create new table with REAL monetary columns
    conn.execute("""
        CREATE TABLE tenders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source          TEXT NOT NULL DEFAULT 'eprocure',
            tender_id       TEXT NOT NULL,
            title           TEXT,
            reference_number  TEXT,
            org_chain       TEXT,
            tender_type     TEXT,
            category        TEXT,
            tender_value    REAL,
            emd_amount      REAL,
            doc_fee         REAL,
            closing_date    TEXT,
            opening_date    TEXT,
            published_date  TEXT,
            detail_url      TEXT,
            raw_json        TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            UNIQUE(source, tender_id)
        )
    """)

    # Step 3 — copy rows, casting monetary TEXT to REAL
    conn.execute("""
        INSERT INTO tenders
            SELECT
                id,
                source,
                tender_id,
                title,
                reference_number,
                org_chain,
                tender_type,
                category,
                CAST(tender_value AS REAL),
                CAST(emd_amount   AS REAL),
                CAST(doc_fee      AS REAL),
                closing_date,
                opening_date,
                published_date,
                detail_url,
                raw_json,
                created_at,
                updated_at
            FROM tenders_old
    """)

    # Step 4 — drop old table
    conn.execute("DROP TABLE tenders_old")

    logger.info("migration 002: tenders table rebuilt successfully")


# ---------------------------------------------------------------------------
# Registry — ordered list of all migrations
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[int, Callable[[sqlite3.Connection], None]]] = [
    (1, migrate_001_add_missing_indexes),
    (2, migrate_002_monetary_fields_to_real),
]


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

def run_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations to *conn* in version order.

    Safe to call on every startup: already-applied versions are skipped.
    Each migration is committed individually so a crash mid-run leaves the
    database in a consistent state (partially migrated, but no half-applied
    migration).
    """
    _ensure_migrations_table(conn)
    conn.commit()  # commit the table creation before reading applied versions

    applied = _applied_versions(conn)

    for version, migrate_fn in MIGRATIONS:
        if version in applied:
            logger.debug("migration %03d: already applied, skipping", version)
            continue

        logger.info("migration %03d: applying …", version)
        migrate_fn(conn)
        _record_version(conn, version)
        conn.commit()
        logger.info("migration %03d: done", version)
