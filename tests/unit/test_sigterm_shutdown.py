"""Tests for 7.3 — graceful SIGTERM handling in CrawlEngine.

Scenarios:
  - SIGTERM during process_run cancels the engine
  - RUNNING tasks are reset to PENDING in the DB on SIGTERM
  - A task that finished before SIGTERM is preserved as DONE
"""
from __future__ import annotations

import signal
import sqlite3
from datetime import UTC, datetime

import pytest

from tender_royal_pulse.crawler.engine import CancellationToken, _sigterm_handler
from tender_royal_pulse.crawler.queue import (
    ListPagePayload,
    TaskStatus,
    claim_task,
    create_run,
    create_tasks,
)
from tender_royal_pulse.db.schema import initialize_schema
from tender_royal_pulse.monitoring.logging import setup_logging


@pytest.fixture()
def db(tmp_path):  # type: ignore[no-untyped-def]
    db_file = tmp_path / "test.db"
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row
    initialize_schema(conn)
    conn.commit()
    conn.close()
    return str(db_file)


def _make_task(db_path: str) -> tuple[str, str]:
    """Create a run + one pending task; return (run_id, task_id)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    run_id = create_run(conn)
    payload = ListPagePayload(mode="closing_today", page_index=1)
    tasks = create_tasks(conn, run_id, [payload])
    conn.close()
    return run_id, tasks[0].id


class TestSigtermHandler:
    def test_no_sigterm_leaves_handler_unchanged(self, db: str) -> None:
        """Without a signal the context manager is a transparent no-op."""
        token = CancellationToken()
        log = setup_logging()
        run_id, _ = _make_task(db)

        original = signal.getsignal(signal.SIGTERM)
        with _sigterm_handler(token, db, run_id, log):
            assert not token.cancelled
        assert signal.getsignal(signal.SIGTERM) is original

    def test_sigterm_cancels_token(self, db: str) -> None:
        """Sending SIGTERM to our own process sets the cancel token."""
        token = CancellationToken()
        log = setup_logging()
        run_id, _ = _make_task(db)

        with _sigterm_handler(token, db, run_id, log):
            signal.raise_signal(signal.SIGTERM)

        assert token.cancelled

    def test_sigterm_resets_running_tasks_to_pending(self, db: str) -> None:
        """After SIGTERM any RUNNING task for the run must become PENDING."""
        token = CancellationToken()
        log = setup_logging()
        run_id, task_id = _make_task(db)

        # Claim the task so it becomes RUNNING.
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        claim_task(conn, task_id)
        conn.close()

        # Verify it is RUNNING before the signal.
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        assert row["status"] == TaskStatus.RUNNING

        with _sigterm_handler(token, db, run_id, log):
            signal.raise_signal(signal.SIGTERM)

        # After the context exits, RUNNING → PENDING.
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        assert row["status"] == TaskStatus.PENDING

    def test_sigterm_leaves_done_tasks_intact(self, db: str) -> None:
        """A task that was already DONE before SIGTERM must stay DONE."""
        token = CancellationToken()
        log = setup_logging()
        run_id, task_id = _make_task(db)

        # Claim → mark DONE manually.
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        claim_task(conn, task_id)
        conn.execute(
            "UPDATE tasks SET status = 'DONE', updated_at = ? WHERE id = ?",
            (datetime.now(UTC).isoformat(), task_id),
        )
        conn.commit()
        conn.close()

        with _sigterm_handler(token, db, run_id, log):
            signal.raise_signal(signal.SIGTERM)

        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
        conn.close()
        assert row["status"] == TaskStatus.DONE

    def test_original_sigterm_handler_restored_after_exit(self, db: str) -> None:
        """The original SIGTERM handler is always restored, even on SIGTERM."""
        token = CancellationToken()
        log = setup_logging()
        run_id, _ = _make_task(db)

        sentinel = signal.getsignal(signal.SIGTERM)
        with _sigterm_handler(token, db, run_id, log):
            signal.raise_signal(signal.SIGTERM)

        assert signal.getsignal(signal.SIGTERM) is sentinel
