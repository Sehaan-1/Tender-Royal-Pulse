"""
tests/unit/test_heartbeat.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for update_heartbeat() — the liveness signal written by the background
heartbeat thread during task execution.

Spec (3.3):
  * update_heartbeat() writes a fresh ISO timestamp to heartbeat_at
  * After a heartbeat update, the task is NOT detectable as stale
  * Without a heartbeat update, a task IS detectable as stale after the
    threshold has elapsed
  * Monotonicity: a second call must produce a timestamp >= the first
"""
from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta

import pytest

from tender_royal_pulse.crawler.queue import (
    ListPagePayload,
    TaskStatus,
    claim_task,
    create_run,
    create_tasks,
    recover_stale_tasks,
    update_heartbeat,
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


def _heartbeat_at(conn, task_id: str) -> str | None:
    return conn.execute(
        "SELECT heartbeat_at FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()["heartbeat_at"]


def _make_running_task(conn) -> tuple[str, str]:
    """Return (run_id, task_id) for a freshly claimed RUNNING task."""
    run_id = create_run(conn)
    tasks = create_tasks(conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    claim_task(conn, task_id)
    return run_id, task_id


# ---------------------------------------------------------------------------
# Basic heartbeat writes
# ---------------------------------------------------------------------------


class TestUpdateHeartbeat:
    def test_writes_non_null_timestamp(self, db_conn):
        _, task_id = _make_running_task(db_conn)
        # Wipe heartbeat_at so we can confirm the update writes it
        db_conn.execute("UPDATE tasks SET heartbeat_at = NULL WHERE id = ?", (task_id,))
        db_conn.commit()

        update_heartbeat(db_conn, task_id)

        assert _heartbeat_at(db_conn, task_id) is not None

    def test_writes_valid_iso_timestamp(self, db_conn):
        _, task_id = _make_running_task(db_conn)

        update_heartbeat(db_conn, task_id)

        ts = _heartbeat_at(db_conn, task_id)
        assert ts is not None
        # Must be parseable as an ISO 8601 timestamp
        parsed = datetime.fromisoformat(ts)
        # Must be recent (within the last 5 seconds)
        age = datetime.now(UTC) - parsed.astimezone(UTC)
        assert age.total_seconds() < 5

    def test_timestamp_is_monotonic(self, db_conn):
        """A second heartbeat call must produce a timestamp >= the first."""
        _, task_id = _make_running_task(db_conn)

        update_heartbeat(db_conn, task_id)
        first = _heartbeat_at(db_conn, task_id)

        # Small sleep to ensure clock advances on fast machines
        time.sleep(0.01)

        update_heartbeat(db_conn, task_id)
        second = _heartbeat_at(db_conn, task_id)

        assert second is not None
        assert first is not None
        # Lexicographic comparison works for ISO 8601 strings
        assert second >= first

    def test_overwrites_stale_heartbeat(self, db_conn):
        """update_heartbeat must overwrite an old timestamp with a fresh one."""
        run_id, task_id = _make_running_task(db_conn)

        # Plant a very old heartbeat
        old_ts = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        db_conn.execute("UPDATE tasks SET heartbeat_at = ? WHERE id = ?", (old_ts, task_id))
        db_conn.commit()

        update_heartbeat(db_conn, task_id)

        new_ts = _heartbeat_at(db_conn, task_id)
        assert new_ts > old_ts


# ---------------------------------------------------------------------------
# Staleness detectability
# ---------------------------------------------------------------------------


class TestStaleDetectability:
    def test_fresh_heartbeat_not_stale(self, db_conn):
        """A task with a recent heartbeat must not appear in stale recovery."""
        run_id, task_id = _make_running_task(db_conn)

        update_heartbeat(db_conn, task_id)

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)
        assert recovered == [], (
            "Task with a fresh heartbeat must not be treated as stale"
        )

    def test_no_heartbeat_update_becomes_stale(self, db_conn):
        """
        Simulate a task that never sends a heartbeat after being claimed.
        Force its heartbeat_at to be old enough for detection.
        """
        run_id, task_id = _make_running_task(db_conn)

        # Backdate the heartbeat to simulate a dead worker
        stale_ts = (datetime.now(UTC) - timedelta(seconds=90)).isoformat()
        db_conn.execute(
            "UPDATE tasks SET heartbeat_at = ? WHERE id = ?", (stale_ts, task_id)
        )
        db_conn.commit()

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)
        assert len(recovered) == 1
        assert recovered[0].id == task_id
        assert recovered[0].status == TaskStatus.PENDING

    def test_heartbeat_prevents_stale_detection(self, db_conn):
        """
        A task backdated to stale, then given a fresh heartbeat, must NOT be
        recovered — the fresh heartbeat is enough to protect it.
        """
        run_id, task_id = _make_running_task(db_conn)

        # First backdate
        stale_ts = (datetime.now(UTC) - timedelta(seconds=90)).isoformat()
        db_conn.execute(
            "UPDATE tasks SET heartbeat_at = ? WHERE id = ?", (stale_ts, task_id)
        )
        db_conn.commit()

        # Then refresh
        update_heartbeat(db_conn, task_id)

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)
        assert recovered == [], (
            "A freshly heartbeated task must not be treated as stale even if it was old before"
        )

    def test_threshold_boundary_just_inside(self, db_conn):
        """Heartbeat exactly at threshold - 1 s → stale."""
        run_id, task_id = _make_running_task(db_conn)
        threshold = 30.0
        stale_ts = (datetime.now(UTC) - timedelta(seconds=threshold + 1)).isoformat()
        db_conn.execute(
            "UPDATE tasks SET heartbeat_at = ? WHERE id = ?", (stale_ts, task_id)
        )
        db_conn.commit()

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=threshold)
        assert len(recovered) == 1

    def test_threshold_boundary_just_outside(self, db_conn):
        """Heartbeat well within the threshold → not stale."""
        run_id, task_id = _make_running_task(db_conn)
        threshold = 30.0
        fresh_ts = (datetime.now(UTC) - timedelta(seconds=threshold - 10)).isoformat()
        db_conn.execute(
            "UPDATE tasks SET heartbeat_at = ? WHERE id = ?", (fresh_ts, task_id)
        )
        db_conn.commit()

        recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=threshold)
        assert recovered == []
