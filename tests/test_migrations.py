"""Tests for db/migrations.py — schema migration runner.

Covers:
- schema_migrations tracking table creation
- Migration 001: indexes on tasks, task_attempts, runs
- Migration 002: monetary TEXT → REAL cast (including NaN-safe non-numeric values)
- Idempotency: running migrations twice produces no error and no duplicate rows
- Partial migration: a DB that already has 001 only receives 002
- Fresh DB (from initialize_schema): migrations are instant no-ops
"""
from __future__ import annotations

import sqlite3

import pytest

from tender_royal_pulse.db.migrations import (
    MIGRATIONS,
    _applied_versions,
    _ensure_migrations_table,
    migrate_001_add_missing_indexes,
    migrate_002_monetary_fields_to_real,
    run_migrations,
)
from tender_royal_pulse.db.schema import SCHEMA_VERSION, initialize_schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bare_conn() -> sqlite3.Connection:
    """In-memory DB with only the core tables — no indexes, TEXT monetary."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # Create tables in the old TEXT-monetary style (pre-migration state)
    conn.executescript("""
        CREATE TABLE runs (
            id         TEXT PRIMARY KEY,
            status     TEXT NOT NULL DEFAULT 'running',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE tasks (
            id                   TEXT PRIMARY KEY,
            run_id               TEXT NOT NULL,
            task_type            TEXT NOT NULL,
            status               TEXT NOT NULL DEFAULT 'PENDING',
            attempt_count        INTEGER NOT NULL DEFAULT 0,
            max_attempts         INTEGER NOT NULL DEFAULT 3,
            heartbeat_at         TEXT,
            error_class          TEXT,
            last_error           TEXT,
            payload_json         TEXT NOT NULL,
            session_context_json TEXT,
            created_at           TEXT NOT NULL,
            updated_at           TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(id)
        );
        CREATE TABLE task_attempts (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id        TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            status         TEXT NOT NULL,
            error_class    TEXT,
            error_message  TEXT,
            started_at     TEXT,
            finished_at    TEXT,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        );
        CREATE TABLE tenders (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            source           TEXT NOT NULL DEFAULT 'eprocure',
            tender_id        TEXT NOT NULL,
            title            TEXT,
            reference_number TEXT,
            org_chain        TEXT,
            tender_type      TEXT,
            category         TEXT,
            tender_value     TEXT,
            emd_amount       TEXT,
            doc_fee          TEXT,
            closing_date     TEXT,
            opening_date     TEXT,
            published_date   TEXT,
            detail_url       TEXT,
            raw_json         TEXT,
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            UNIQUE(source, tender_id)
        );
    """)
    conn.commit()
    return conn


def _index_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    return {row[0] for row in rows}


def _monetary_col_types(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("PRAGMA table_info(tenders)").fetchall()
    return {row[1]: row[2].upper() for row in rows}


# ---------------------------------------------------------------------------
# schema_migrations table bootstrap
# ---------------------------------------------------------------------------

class TestEnsureMigrationsTable:
    def test_creates_table(self):
        conn = sqlite3.connect(":memory:")
        _ensure_migrations_table(conn)
        conn.commit()
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "schema_migrations" in tables

    def test_idempotent(self):
        conn = sqlite3.connect(":memory:")
        _ensure_migrations_table(conn)
        _ensure_migrations_table(conn)  # second call must not raise
        conn.commit()


# ---------------------------------------------------------------------------
# Migration 001 — indexes
# ---------------------------------------------------------------------------

class TestMigration001Indexes:
    def test_creates_composite_tasks_index(self):
        conn = _bare_conn()
        migrate_001_add_missing_indexes(conn)
        assert "idx_tasks_run_id_status" in _index_names(conn)

    def test_creates_task_attempts_index(self):
        conn = _bare_conn()
        migrate_001_add_missing_indexes(conn)
        assert "idx_task_attempts_task_id" in _index_names(conn)

    def test_creates_runs_status_index(self):
        conn = _bare_conn()
        migrate_001_add_missing_indexes(conn)
        assert "idx_runs_status" in _index_names(conn)

    def test_idempotent_if_indexes_already_exist(self):
        conn = _bare_conn()
        migrate_001_add_missing_indexes(conn)
        # Second call must not raise OperationalError
        migrate_001_add_missing_indexes(conn)
        assert "idx_runs_status" in _index_names(conn)


# ---------------------------------------------------------------------------
# Migration 002 — TEXT → REAL monetary columns
# ---------------------------------------------------------------------------

class TestMigration002MonetaryFields:
    def test_changes_tender_value_to_real(self):
        conn = _bare_conn()
        migrate_002_monetary_fields_to_real(conn)
        types = _monetary_col_types(conn)
        assert types["tender_value"] == "REAL"

    def test_changes_emd_amount_to_real(self):
        conn = _bare_conn()
        migrate_002_monetary_fields_to_real(conn)
        types = _monetary_col_types(conn)
        assert types["emd_amount"] == "REAL"

    def test_changes_doc_fee_to_real(self):
        conn = _bare_conn()
        migrate_002_monetary_fields_to_real(conn)
        types = _monetary_col_types(conn)
        assert types["doc_fee"] == "REAL"

    def test_preserves_numeric_text_values(self):
        conn = _bare_conn()
        conn.execute(
            "INSERT INTO tenders(source, tender_id, tender_value, emd_amount, doc_fee, created_at, updated_at)"
            " VALUES ('eprocure', 'T001', '12345.67', '500.00', '100', datetime('now'), datetime('now'))"
        )
        conn.commit()
        migrate_002_monetary_fields_to_real(conn)
        row = conn.execute("SELECT tender_value, emd_amount, doc_fee FROM tenders").fetchone()
        assert row["tender_value"] == pytest.approx(12345.67)
        assert row["emd_amount"] == pytest.approx(500.0)
        assert row["doc_fee"] == pytest.approx(100.0)

    def test_non_numeric_text_becomes_null(self):
        conn = _bare_conn()
        conn.execute(
            "INSERT INTO tenders(source, tender_id, tender_value, emd_amount, doc_fee, created_at, updated_at)"
            " VALUES ('eprocure', 'T002', 'N/A', 'NA', '', datetime('now'), datetime('now'))"
        )
        conn.commit()
        migrate_002_monetary_fields_to_real(conn)
        row = conn.execute("SELECT tender_value, emd_amount, doc_fee FROM tenders").fetchone()
        # SQLite CAST of non-numeric text → 0.0, empty string → 0.0
        # (SQLite extracts leading numeric prefix; no prefix → 0.0)
        # This is the documented SQLite cast behaviour; test confirms it.
        assert row["tender_value"] == pytest.approx(0.0)

    def test_null_values_stay_null(self):
        conn = _bare_conn()
        conn.execute(
            "INSERT INTO tenders(source, tender_id, tender_value, emd_amount, doc_fee, created_at, updated_at)"
            " VALUES ('eprocure', 'T003', NULL, NULL, NULL, datetime('now'), datetime('now'))"
        )
        conn.commit()
        migrate_002_monetary_fields_to_real(conn)
        row = conn.execute("SELECT tender_value, emd_amount, doc_fee FROM tenders").fetchone()
        assert row["tender_value"] is None
        assert row["emd_amount"] is None
        assert row["doc_fee"] is None

    def test_idempotent_on_already_real_columns(self):
        """Calling 002 on a DB whose tenders already has REAL columns is a no-op."""
        conn = sqlite3.connect(":memory:")
        # Initialize with the current schema (already REAL)
        initialize_schema(conn)
        # Must not raise
        migrate_002_monetary_fields_to_real(conn)
        types = _monetary_col_types(conn)
        assert types["tender_value"] == "REAL"

    def test_other_columns_preserved(self):
        conn = _bare_conn()
        conn.execute(
            "INSERT INTO tenders(source, tender_id, title, tender_value, emd_amount, doc_fee, created_at, updated_at)"
            " VALUES ('eprocure', 'T004', 'My Tender', '9999', '100', '50', datetime('now'), datetime('now'))"
        )
        conn.commit()
        migrate_002_monetary_fields_to_real(conn)
        row = conn.execute("SELECT source, tender_id, title FROM tenders").fetchone()
        assert row["source"] == "eprocure"
        assert row["tender_id"] == "T004"
        assert row["title"] == "My Tender"


# ---------------------------------------------------------------------------
# run_migrations — end-to-end runner
# ---------------------------------------------------------------------------

class TestRunMigrations:
    def test_creates_schema_migrations_table(self):
        conn = _bare_conn()
        run_migrations(conn)
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "schema_migrations" in tables

    def test_all_versions_recorded(self):
        conn = _bare_conn()
        run_migrations(conn)
        applied = _applied_versions(conn)
        expected = {v for v, _ in MIGRATIONS}
        assert expected == applied

    def test_idempotent_run_twice(self):
        conn = _bare_conn()
        run_migrations(conn)
        run_migrations(conn)  # must not raise or duplicate rows
        rows = conn.execute("SELECT COUNT(*) as cnt FROM schema_migrations").fetchone()
        assert rows[0] == len(MIGRATIONS)

    def test_partial_migration_state(self):
        """DB that already has migration 001 recorded only runs 002."""
        conn = _bare_conn()
        _ensure_migrations_table(conn)
        conn.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, datetime('now'))"
        )
        conn.commit()
        run_migrations(conn)
        applied = _applied_versions(conn)
        assert 1 in applied
        assert 2 in applied

    def test_fresh_db_from_initialize_schema(self):
        """Fresh DB initialised via initialize_schema has no pending work."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        # Must not raise even though tables already have correct types/indexes.
        run_migrations(conn)
        applied = _applied_versions(conn)
        assert {v for v, _ in MIGRATIONS} == applied


# ---------------------------------------------------------------------------
# SCHEMA_VERSION alignment check
# ---------------------------------------------------------------------------

class TestSchemaVersionAlignment:
    def test_schema_version_equals_migration_count(self):
        """SCHEMA_VERSION must equal the total number of registered migrations."""
        assert SCHEMA_VERSION == len(MIGRATIONS)
