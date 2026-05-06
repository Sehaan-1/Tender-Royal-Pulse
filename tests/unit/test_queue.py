from __future__ import annotations

import datetime
import sqlite3
from datetime import timedelta

import pytest

from tender_royal_pulse.crawler.queue import (
    ListPagePayload,
    TaskStatus,
    claim_task,
    create_run,
    create_tasks,
    mark_task_done,
    mark_task_failed_permanent,
    mark_task_failed_retryable,
    recover_stale_tasks,
    update_heartbeat,
)


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    from tender_royal_pulse.db.schema import initialize_schema
    initialize_schema(conn)
    yield conn
    conn.close()

def test_create_run_returns_id(db_conn):
    run_id = create_run(db_conn)
    assert run_id is not None
    row = db_conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert row["status"] == "running"

def test_create_tasks_creates_pending_tasks(db_conn):
    run_id = create_run(db_conn)
    payloads = [ListPagePayload(mode="test", page_index=i) for i in range(3)]
    tasks = create_tasks(db_conn, run_id, payloads)
    assert len(tasks) == 3
    for task in tasks:
        row = db_conn.execute("SELECT status FROM tasks WHERE id = ?", (task.id,)).fetchone()
        assert row["status"] == "PENDING"

def test_claim_task_changes_status_to_running(db_conn):
    run_id = create_run(db_conn)
    tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    claimed = claim_task(db_conn, task_id)
    assert claimed is not None
    assert claimed.status == TaskStatus.RUNNING
    row = db_conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row["status"] == "RUNNING"

def test_claim_task_returns_none_for_already_claimed(db_conn):
    run_id = create_run(db_conn)
    tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    claim_task(db_conn, task_id)
    second_claim = claim_task(db_conn, task_id)
    assert second_claim is None

def test_update_heartbeat_sets_timestamp(db_conn):
    run_id = create_run(db_conn)
    tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    update_heartbeat(db_conn, task_id)
    row = db_conn.execute("SELECT heartbeat_at FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row["heartbeat_at"] is not None

def test_mark_task_done_sets_status(db_conn):
    run_id = create_run(db_conn)
    tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    mark_task_done(db_conn, task_id)
    row = db_conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row["status"] == "DONE"

def test_mark_task_failed_permanent(db_conn):
    run_id = create_run(db_conn)
    tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    mark_task_failed_permanent(db_conn, task_id, "PermError", "Critical failure")
    row = db_conn.execute("SELECT status, error_class, last_error FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row["status"] == "FAILED_PERMANENT"
    assert row["error_class"] == "PermError"
    assert row["last_error"] == "Critical failure"

def test_mark_task_failed_retryable(db_conn):
    run_id = create_run(db_conn)
    tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    mark_task_failed_retryable(db_conn, task_id, "RetryError", "Transient failure")
    row = db_conn.execute("SELECT status, error_class, last_error FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row["status"] == "FAILED_RETRYABLE"
    assert row["error_class"] == "RetryError"
    assert row["last_error"] == "Transient failure"

def test_recover_stale_tasks_resets_to_pending(db_conn):
    run_id = create_run(db_conn)
    tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    stale_iso = (datetime.datetime.now(datetime.UTC) - timedelta(seconds=60)).isoformat()
    db_conn.execute("UPDATE tasks SET status = 'RUNNING', heartbeat_at = ? WHERE id = ?", (stale_iso, task_id))
    db_conn.commit()

    recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)
    assert len(recovered) == 1
    assert recovered[0].id == task_id
    row = db_conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row["status"] == "PENDING"

def test_recover_stale_skips_fresh_heartbeat(db_conn):
    run_id = create_run(db_conn)
    tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    fresh_iso = (datetime.datetime.now(datetime.UTC) - timedelta(seconds=5)).isoformat()
    db_conn.execute("UPDATE tasks SET status = 'RUNNING', heartbeat_at = ? WHERE id = ?", (fresh_iso, task_id))
    db_conn.commit()

    recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)
    assert len(recovered) == 0

def test_recover_stale_skips_max_attempts(db_conn):
    run_id = create_run(db_conn)
    tasks = create_tasks(db_conn, run_id, [ListPagePayload(mode="test", page_index=0)])
    task_id = tasks[0].id
    stale_iso = (datetime.datetime.now(datetime.UTC) - timedelta(seconds=60)).isoformat()
    db_conn.execute("UPDATE tasks SET status = 'RUNNING', heartbeat_at = ?, attempt_count = 3, max_attempts = 3 WHERE id = ?", (stale_iso, task_id))
    db_conn.commit()

    recovered = recover_stale_tasks(db_conn, run_id, stale_timeout_seconds=30.0)
    assert len(recovered) == 0
