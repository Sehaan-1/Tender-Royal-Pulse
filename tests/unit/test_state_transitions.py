"""
tests/unit/test_state_transitions.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for every valid task state transition defined by the queue module:

    PENDING ──claim──► RUNNING ──done──────────► DONE
                             └──retryable──► FAILED_RETRYABLE
                             └──permanent──► FAILED_PERMANENT

Also covers:
  * Guard: claim_task on non-PENDING returns None
  * Guard: mark_task_done on non-RUNNING raises ValueError
  * max_attempts enforcement (engine-level): FAILED_RETRYABLE promoted to
    FAILED_PERMANENT when attempt_count >= max_attempts
"""
from __future__ import annotations

import sqlite3

import pytest

from tender_royal_pulse.crawler.engine import execute_list_page_task
from tender_royal_pulse.crawler.queue import (
    ListPagePayload,
    Task,
    TaskStatus,
    claim_task,
    create_run,
    create_tasks,
    mark_task_done,
    mark_task_failed_permanent,
    mark_task_failed_retryable,
)

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from tender_royal_pulse.db.schema import initialize_schema
    initialize_schema(conn)
    yield conn
    conn.close()


def _make_task(conn: sqlite3.Connection, *, max_attempts: int = 3) -> Task:
    """Create a run + one PENDING task and return the Task object."""
    run_id = create_run(conn)
    tasks = create_tasks(conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    # Override max_attempts if needed
    if max_attempts != 3:
        conn.execute(
            "UPDATE tasks SET max_attempts = ? WHERE id = ?",
            (max_attempts, tasks[0].id),
        )
        conn.commit()
    return tasks[0]


def _row(conn: sqlite3.Connection, task_id: str) -> sqlite3.Row:
    return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


# ---------------------------------------------------------------------------
# 3.1a  PENDING → RUNNING  (claim_task)
# ---------------------------------------------------------------------------


class TestClaimTask:
    def test_pending_to_running(self, db_conn):
        task = _make_task(db_conn)
        claimed = claim_task(db_conn, task.id)

        assert claimed is not None
        assert claimed.status == TaskStatus.RUNNING
        row = _row(db_conn, task.id)
        assert row["status"] == "RUNNING"

    def test_increments_attempt_count(self, db_conn):
        task = _make_task(db_conn)
        assert task.attempt_count == 0

        claimed = claim_task(db_conn, task.id)

        assert claimed is not None
        assert claimed.attempt_count == 1
        assert _row(db_conn, task.id)["attempt_count"] == 1

    def test_sets_heartbeat_at(self, db_conn):
        task = _make_task(db_conn)
        claimed = claim_task(db_conn, task.id)

        assert claimed is not None
        assert claimed.heartbeat_at is not None
        assert _row(db_conn, task.id)["heartbeat_at"] is not None

    def test_returns_none_for_running_task(self, db_conn):
        """Claiming an already-RUNNING task must return None (idempotent guard)."""
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)  # first claim → RUNNING

        second = claim_task(db_conn, task.id)
        assert second is None

    def test_returns_none_for_done_task(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)
        mark_task_done(db_conn, task.id)

        result = claim_task(db_conn, task.id)
        assert result is None

    def test_returns_none_for_failed_permanent_task(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)
        mark_task_failed_permanent(db_conn, task.id, "Err", "msg")

        result = claim_task(db_conn, task.id)
        assert result is None

    def test_returns_none_for_failed_retryable_task(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)
        mark_task_failed_retryable(db_conn, task.id, "Err", "msg")

        result = claim_task(db_conn, task.id)
        assert result is None


# ---------------------------------------------------------------------------
# 3.1b  RUNNING → DONE  (mark_task_done)
# ---------------------------------------------------------------------------


class TestMarkTaskDone:
    def test_running_to_done(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)

        mark_task_done(db_conn, task.id)

        row = _row(db_conn, task.id)
        assert row["status"] == "DONE"

    def test_updates_updated_at(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)
        before = _row(db_conn, task.id)["updated_at"]

        mark_task_done(db_conn, task.id)

        after = _row(db_conn, task.id)["updated_at"]
        # updated_at must change (or at minimum be set)
        assert after is not None
        # ISO strings are lexicographically ordered — after >= before
        assert after >= before

    def test_raises_on_pending_task(self, db_conn):
        """mark_task_done on a PENDING task must raise ValueError."""
        task = _make_task(db_conn)

        with pytest.raises(ValueError, match="must be RUNNING"):
            mark_task_done(db_conn, task.id)

    def test_raises_on_failed_retryable_task(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)
        mark_task_failed_retryable(db_conn, task.id, "Err", "msg")

        with pytest.raises(ValueError, match="must be RUNNING"):
            mark_task_done(db_conn, task.id)

    def test_raises_on_failed_permanent_task(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)
        mark_task_failed_permanent(db_conn, task.id, "Err", "msg")

        with pytest.raises(ValueError, match="must be RUNNING"):
            mark_task_done(db_conn, task.id)


# ---------------------------------------------------------------------------
# 3.1c  RUNNING → FAILED_RETRYABLE  (mark_task_failed_retryable)
# ---------------------------------------------------------------------------


class TestMarkTaskFailedRetryable:
    def test_running_to_failed_retryable(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)

        mark_task_failed_retryable(db_conn, task.id, "TIMEOUT", "timed out")

        row = _row(db_conn, task.id)
        assert row["status"] == "FAILED_RETRYABLE"

    def test_sets_error_class(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)

        mark_task_failed_retryable(db_conn, task.id, "HTTP_429", "rate limited")

        row = _row(db_conn, task.id)
        assert row["error_class"] == "HTTP_429"
        assert row["last_error"] == "rate limited"


# ---------------------------------------------------------------------------
# 3.1d  RUNNING → FAILED_PERMANENT  (mark_task_failed_permanent)
# ---------------------------------------------------------------------------


class TestMarkTaskFailedPermanent:
    def test_running_to_failed_permanent(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)

        mark_task_failed_permanent(db_conn, task.id, "HTTP_4XX", "not found")

        row = _row(db_conn, task.id)
        assert row["status"] == "FAILED_PERMANENT"

    def test_sets_error_class_and_message(self, db_conn):
        task = _make_task(db_conn)
        claim_task(db_conn, task.id)

        mark_task_failed_permanent(db_conn, task.id, "SELECTOR_DRIFT", "layout changed")

        row = _row(db_conn, task.id)
        assert row["error_class"] == "SELECTOR_DRIFT"
        assert row["last_error"] == "layout changed"


# ---------------------------------------------------------------------------
# 3.1e  max_attempts enforcement (engine-level promotion)
#       When attempt_count >= max_attempts the engine must choose
#       FAILED_PERMANENT even for a normally-retryable error class.
# ---------------------------------------------------------------------------


class TestMaxAttemptsPromotion:
    """
    The engine compares *task.attempt_count* (after claim, so already
    incremented) against *retry_config.max_attempts* (derived from the error
    class, not the task row).

    Strategy to force FAILED_PERMANENT in one call:
      * Use an error that maps to max_attempts=1 (HTTP_4XX / SELECTOR_DRIFT).
      * On the first claim attempt_count goes 0 → 1, and 1 >= 1 → permanent.
    """

    def test_retryable_error_at_max_attempts_becomes_permanent(self, db_conn):
        """
        HTTP_4XX maps to RetryConfig(max_attempts=1).
        First claim: attempt_count 0→1, then 1 >= 1 → FAILED_PERMANENT.
        """
        run_id = create_run(db_conn)
        tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])

        # HTTP 404 message → classify_error → HTTP_4XX → max_attempts=1
        def always_fail(row_index, conn):
            raise RuntimeError("HTTP 404 not found")

        from tender_royal_pulse.monitoring.logging import setup_logging
        execute_list_page_task(
            db_conn,
            tasks[0],
            process_row=always_fail,
            heartbeat_interval=0.01,
            logger=setup_logging(),
        )

        row = _row(db_conn, tasks[0].id)
        assert row["status"] == "FAILED_PERMANENT", (
            f"Expected FAILED_PERMANENT for HTTP_4XX on first attempt, got {row['status']}"
        )

    def test_retryable_error_below_max_attempts_stays_retryable(self, db_conn):
        """
        NETWORK_ERROR maps to max_attempts=3. First attempt: count=1 < 3 → retryable.
        """
        run_id = create_run(db_conn)
        tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])

        def always_fail(row_index, conn):
            raise ConnectionError("net::ERR_CONNECTION_RESET")

        from tender_royal_pulse.monitoring.logging import setup_logging
        execute_list_page_task(
            db_conn,
            tasks[0],
            process_row=always_fail,
            heartbeat_interval=0.01,
            logger=setup_logging(),
        )

        row = _row(db_conn, tasks[0].id)
        assert row["status"] == "FAILED_RETRYABLE", (
            f"Expected FAILED_RETRYABLE for first NETWORK_ERROR with max_attempts=3, got {row['status']}"
        )

    def test_network_error_exhausted_becomes_permanent(self, db_conn):
        """
        Pre-seed attempt_count=2 (max_attempts=3 for NETWORK_ERROR).
        After claim: count=3, 3 >= 3 → FAILED_PERMANENT.
        """
        run_id = create_run(db_conn)
        tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
        task_id = tasks[0].id
        # Simulate two prior failed attempts
        db_conn.execute("UPDATE tasks SET attempt_count = 2 WHERE id = ?", (task_id,))
        db_conn.commit()

        def always_fail(row_index, conn):
            raise ConnectionError("net::ERR_CONNECTION_RESET")

        from tender_royal_pulse.monitoring.logging import setup_logging
        execute_list_page_task(
            db_conn,
            tasks[0],
            process_row=always_fail,
            heartbeat_interval=0.01,
            logger=setup_logging(),
        )

        row = _row(db_conn, task_id)
        assert row["status"] == "FAILED_PERMANENT", (
            f"Expected FAILED_PERMANENT after exhausting NETWORK_ERROR retries, got {row['status']}"
        )
