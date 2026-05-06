from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel

from tender_royal_pulse.models import Tender


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"


class TaskType(StrEnum):
    LIST_PAGE = "LIST_PAGE"


class ListPagePayload(BaseModel):
    mode: str
    page_index: int
    date_filter: str | None = None
    row_cursor: int | None = None


class Task(BaseModel):
    id: str
    run_id: str
    task_type: TaskType
    status: TaskStatus = TaskStatus.PENDING
    attempt_count: int = 0
    max_attempts: int = 3
    heartbeat_at: str | None = None
    error_class: str | None = None
    last_error: str | None = None
    payload: ListPagePayload
    session_context_json: str | None = None
    created_at: str
    updated_at: str


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _task_from_row(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        run_id=row["run_id"],
        task_type=TaskType(row["task_type"]),
        status=TaskStatus(row["status"]),
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        heartbeat_at=row["heartbeat_at"],
        error_class=row["error_class"],
        last_error=row["last_error"],
        payload=ListPagePayload.model_validate_json(row["payload_json"]),
        session_context_json=row["session_context_json"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_run(conn: sqlite3.Connection, run_id: str | None = None) -> str:
    rid = run_id or str(uuid4())
    now = _now_iso()
    conn.execute(
        "INSERT INTO runs (id, status, created_at, updated_at) VALUES (?, 'running', ?, ?)",
        (rid, now, now),
    )
    conn.commit()
    return rid


def create_tasks(
    conn: sqlite3.Connection,
    run_id: str,
    payloads: list[ListPagePayload],
    session_context_json: str | None = None,
) -> list[Task]:
    tasks: list[Task] = []
    now = _now_iso()
    rows: list[tuple[str, str, str, str, int, int, str, str | None, str]] = []
    for p in payloads:
        task_id = str(uuid4())
        rows.append((
            task_id,
            run_id,
            TaskType.LIST_PAGE.value,
            p.model_dump_json(),
            0,
            3,
            now,
            session_context_json,
            now,
        ))
        tasks.append(Task(
            id=task_id,
            run_id=run_id,
            task_type=TaskType.LIST_PAGE,
            status=TaskStatus.PENDING,
            attempt_count=0,
            max_attempts=3,
            payload=p,
            session_context_json=session_context_json,
            created_at=now,
            updated_at=now,
        ))
    conn.executemany(
        "INSERT INTO tasks (id, run_id, task_type, payload_json, attempt_count, max_attempts, "
        "created_at, session_context_json, updated_at, heartbeat_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        rows,
    )
    conn.commit()
    return tasks


def get_pending_tasks(conn: sqlite3.Connection, run_id: str) -> list[Task]:
    cursor = conn.execute(
        "SELECT * FROM tasks WHERE run_id = ? AND status = 'PENDING' ORDER BY created_at",
        (run_id,),
    )
    return [_task_from_row(row) for row in cursor.fetchall()]


def get_run_tasks(conn: sqlite3.Connection, run_id: str) -> list[Task]:
    cursor = conn.execute(
        "SELECT * FROM tasks WHERE run_id = ? ORDER BY created_at",
        (run_id,),
    )
    return [_task_from_row(row) for row in cursor.fetchall()]


def claim_task(conn: sqlite3.Connection, task_id: str) -> Task | None:
    cursor = conn.execute(
        "SELECT * FROM tasks WHERE id = ? AND status = 'PENDING'",
        (task_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    now = _now_iso()
    conn.execute(
        "UPDATE tasks SET status = 'RUNNING', heartbeat_at = ?, "
        "attempt_count = attempt_count + 1, updated_at = ? WHERE id = ?",
        (now, now, task_id),
    )
    conn.commit()
    return _task_from_row(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())


def update_heartbeat(conn: sqlite3.Connection, task_id: str) -> None:
    now = _now_iso()
    conn.execute("UPDATE tasks SET heartbeat_at = ? WHERE id = ?", (now, task_id))
    conn.commit()


def mark_task_done(conn: sqlite3.Connection, task_id: str) -> None:
    now = _now_iso()
    conn.execute(
        "UPDATE tasks SET status = 'DONE', updated_at = ? WHERE id = ?",
        (now, task_id),
    )
    conn.commit()


def mark_task_failed_retryable(
    conn: sqlite3.Connection,
    task_id: str,
    error_class: str,
    error_message: str,
) -> None:
    now = _now_iso()
    conn.execute(
        "UPDATE tasks SET status = 'FAILED_RETRYABLE', error_class = ?, "
        "last_error = ?, updated_at = ? WHERE id = ?",
        (error_class, error_message, now, task_id),
    )
    conn.commit()


def mark_task_failed_permanent(
    conn: sqlite3.Connection,
    task_id: str,
    error_class: str,
    error_message: str,
) -> None:
    now = _now_iso()
    conn.execute(
        "UPDATE tasks SET status = 'FAILED_PERMANENT', error_class = ?, "
        "last_error = ?, updated_at = ? WHERE id = ?",
        (error_class, error_message, now, task_id),
    )
    conn.commit()


def log_task_attempt(
    conn: sqlite3.Connection,
    task_id: str,
    attempt_number: int,
    status: str,
    error_class: str | None = None,
    error_message: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO task_attempts (task_id, attempt_number, status, error_class, "
        "error_message, started_at, finished_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (task_id, attempt_number, status, error_class, error_message, started_at, finished_at),
    )
    conn.commit()


def recover_stale_tasks(
    conn: sqlite3.Connection,
    run_id: str,
    stale_timeout_seconds: float = 30.0,
) -> list[Task]:
    threshold = (datetime.now(UTC) - timedelta(seconds=stale_timeout_seconds)).isoformat()
    cursor = conn.execute(
        "SELECT * FROM tasks WHERE run_id = ? AND status = 'RUNNING' "
        "AND heartbeat_at < ? AND attempt_count < max_attempts",
        (run_id, threshold),
    )
    stale_rows = cursor.fetchall()
    recovered: list[Task] = []
    for row in stale_rows:
        conn.execute(
            "UPDATE tasks SET status = 'PENDING', updated_at = ? WHERE id = ?",
            (_now_iso(), row["id"]),
        )
        recovered.append(_task_from_row(
            conn.execute("SELECT * FROM tasks WHERE id = ?", (row["id"],)).fetchone()
        ))
    if recovered:
        conn.commit()
    return recovered


def upsert_tender(
    conn: sqlite3.Connection,
    tender: Tender,
    raw_json_str: str | None = None,
) -> bool:
    now = _now_iso()
    cursor = conn.execute(
        "SELECT id FROM tenders WHERE source = ? AND tender_id = ?",
        (tender.source, tender.tender_id),
    )
    existing = cursor.fetchone()

    # We use the model's attributes directly.
    # We convert Decimals/Datetimes to strings for SQLite.

    vals = (
        tender.title or None,
        tender.reference_number or None,
        tender.org_chain or None,
        tender.tender_type or None,
        tender.category or None,
        str(tender.tender_value) if tender.tender_value is not None else None,
        str(tender.emd_amount) if tender.emd_amount is not None else None,
        str(tender.doc_fee) if tender.doc_fee is not None else None,
        tender.closing_date.isoformat() if tender.closing_date else None,
        tender.opening_date.isoformat() if tender.opening_date else None,
        tender.published_date.isoformat() if tender.published_date else None,
        tender.detail_url or None,
        raw_json_str,
    )

    if existing:
        conn.execute(
            "UPDATE tenders SET title = ?, reference_number = ?, org_chain = ?, "
            "tender_type = ?, category = ?, tender_value = ?, emd_amount = ?, "
            "doc_fee = ?, closing_date = ?, opening_date = ?, published_date = ?, "
            "detail_url = ?, raw_json = ?, updated_at = ? WHERE id = ?",
            (*vals, now, existing["id"]),
        )
        conn.commit()
        return False
    else:
        conn.execute(
            "INSERT INTO tenders (source, tender_id, title, reference_number, org_chain, "
            "tender_type, category, tender_value, emd_amount, doc_fee, closing_date, "
            "opening_date, published_date, detail_url, raw_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tender.source, tender.tender_id, *vals, now, now),
        )
        conn.commit()
        return True
