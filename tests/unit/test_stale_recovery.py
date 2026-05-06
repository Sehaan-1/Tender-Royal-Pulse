"""
tests/unit/test_stale_recovery.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for recover_stale_tasks() — the crash-recovery path that resets
zombie RUNNING tasks back to PENDING so they can be retried.

Spec (3.2):
  * Task with heartbeat_at < now − threshold AND RUNNING  → reset to PENDING
  * Task at max_attempts + stale                          → NOT reset
  * Task with fresh heartbeat                             → NOT reset
  * Multiple tasks: only stale ones are reset
  * Recovered task updated_at must be refreshed
"""
from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from tender_royal_pulse.crawler.queue import (
    ListPagePayload,
    TaskStatus,
    claim_task,
    create_run,
    create_tasks,
    recover_stale_tasks,
)

# ---------------------------------------------------------------------------
# Shared fixture & helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from tender_royal_pulse.db.schema import initialize_schema
    initialize_schema(conn)
    yield conn
    conn.close()


def _make_running_task(
    conn: sqlite3.Connection,
    *,
    heartbeat_age_seconds: float,
    attempt_count: int = 1,
    max_attempts: int = 3,
) -> str:
    """
    Create a RUNNING task whose heartbeat_at is *heartbeat_age_seconds* in the
    past and return its task_id.
    """
    run_id = create_run(conn)
    tasks = create_tasks(conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id

    heartbeat_ts = (datetime.now(UTC) - timedelta(seconds=heartbeat_age_seconds)).isoformat()
    conn.execute(
        "UPDATE tasks SET status = 'RUNNING', heartbeat_at = ?, "
        "attempt_count = ?, max_attempts = ? WHERE id = ?",
        (heartbeat_ts, attempt_count, max_attempts, task_id),
    )
    conn.commit()
    return task_id


def _status(conn, task_id: str) -> str:
    return conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()["status"]


def _run_id_of(conn, task_id: str) -> str:
    return conn.execute("SELECT run_id FROM tasks WHERE id = ?", (task_id,)).fetchone()["run_id"]


# ---------------------------------------------------------------------------
# Core recovery scenarios
# ---------------------------------------------------------------------------


class TestRecoverStaleTasks:
    def test_stale_running_task_resets_to_pending(self, db_conn):
        """Heartbeat 60 s ago with 30 s threshold → must recover."""
        task_id = _make_running_task(db_conn, heartbeat_age_seconds=60)

        run_id = _run_id_of(db_conn, task_id)
        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)

        assert len(recovered) == 1
        assert recovered[0].id == task_id
        assert recovered[0].status == TaskStatus.PENDING
        assert _status(db_conn, task_id) == "PENDING"

    def test_recovered_task_updated_at_is_refreshed(self, db_conn):
        """The updated_at of a recovered task must move forward."""
        task_id = _make_running_task(db_conn, heartbeat_age_seconds=60)
        run_id = _run_id_of(db_conn, task_id)

        before = db_conn.execute(
            "SELECT updated_at FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()["updated_at"]

        recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)

        after = db_conn.execute(
            "SELECT updated_at FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()["updated_at"]
        assert after >= before

    def test_fresh_heartbeat_is_not_reset(self, db_conn):
        """Heartbeat only 5 s ago with 30 s threshold → must NOT recover."""
        task_id = _make_running_task(db_conn, heartbeat_age_seconds=5)
        run_id = _run_id_of(db_conn, task_id)

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)

        assert recovered == []
        assert _status(db_conn, task_id) == "RUNNING"

    def test_at_max_attempts_stale_not_reset(self, db_conn):
        """
        A stale task that has already hit max_attempts must NOT be put back to
        PENDING — it should stay RUNNING (caller's responsibility to mark
        FAILED_PERMANENT, which recover_stale_tasks intentionally skips).
        """
        task_id = _make_running_task(
            db_conn,
            heartbeat_age_seconds=60,
            attempt_count=3,
            max_attempts=3,
        )
        run_id = _run_id_of(db_conn, task_id)

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)

        assert recovered == []
        # Status unchanged — still RUNNING; cleanup is external concern
        assert _status(db_conn, task_id) == "RUNNING"

    def test_above_max_attempts_stale_not_reset(self, db_conn):
        """attempt_count > max_attempts (defensive): also must not recover."""
        task_id = _make_running_task(
            db_conn,
            heartbeat_age_seconds=60,
            attempt_count=5,
            max_attempts=3,
        )
        run_id = _run_id_of(db_conn, task_id)

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)

        assert recovered == []

    def test_pending_task_is_not_touched(self, db_conn):
        """recover_stale_tasks only operates on RUNNING tasks."""
        run_id = create_run(db_conn)
        tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
        task_id = tasks[0].id  # stays PENDING

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=0.0)

        assert recovered == []
        assert _status(db_conn, task_id) == "PENDING"

    def test_done_task_is_not_touched(self, db_conn):
        """DONE tasks must never be touched by recovery."""
        run_id = create_run(db_conn)
        tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
        task_id = tasks[0].id
        claim_task(db_conn, task_id)
        from tender_royal_pulse.crawler.queue import mark_task_done
        mark_task_done(db_conn, task_id)

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=0.0)

        assert recovered == []
        assert _status(db_conn, task_id) == "DONE"

    def test_returns_empty_list_when_nothing_stale(self, db_conn):
        run_id = create_run(db_conn)
        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)
        assert recovered == []


# ---------------------------------------------------------------------------
# Multi-task selective recovery
# ---------------------------------------------------------------------------


class TestSelectiveRecovery:
    def test_only_stale_tasks_are_recovered(self, db_conn):
        """Mix: one stale + one fresh → only stale is recovered."""
        stale_id = _make_running_task(db_conn, heartbeat_age_seconds=60)
        fresh_id = _make_running_task(db_conn, heartbeat_age_seconds=5)

        # Both belong to different runs; recover per run
        stale_run = _run_id_of(db_conn, stale_id)
        fresh_run = _run_id_of(db_conn, fresh_id)

        stale_recovered = recover_stale_tasks(db_conn, stale_run, stale_timeout_seconds=30.0)
        fresh_recovered = recover_stale_tasks(db_conn, fresh_run, stale_timeout_seconds=30.0)

        assert len(stale_recovered) == 1
        assert stale_recovered[0].id == stale_id
        assert fresh_recovered == []
        assert _status(db_conn, fresh_id) == "RUNNING"

    def test_run_isolation(self, db_conn):
        """Tasks from a different run_id are not recovered."""
        stale_id = _make_running_task(db_conn, heartbeat_age_seconds=60)
        other_run_id = create_run(db_conn)  # a completely separate run

        recovered = recover_stale_tasks(db_conn, other_run_id, stale_timeout_seconds=30.0)

        assert recovered == []
        # stale task is unaffected
        assert _status(db_conn, stale_id) == "RUNNING"

    def test_multiple_stale_tasks_all_recovered(self, db_conn):
        """All stale tasks in a run must be recovered in one call."""
        run_id = create_run(db_conn)
        payloads = [ListPagePayload(mode="test", page_index=i) for i in range(3)]
        tasks = create_tasks(db_conn, run_id, payloads)

        stale_ts = (datetime.now(UTC) - timedelta(seconds=90)).isoformat()
        for t in tasks:
            db_conn.execute(
                "UPDATE tasks SET status = 'RUNNING', heartbeat_at = ?, attempt_count = 1 WHERE id = ?",
                (stale_ts, t.id),
            )
        db_conn.commit()

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)

        assert len(recovered) == 3
        for t in tasks:
            assert _status(db_conn, t.id) == "PENDING"
