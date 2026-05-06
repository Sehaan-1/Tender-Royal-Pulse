from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tender_royal_pulse.crawler.engine import CrawlEngine, execute_list_page_task
from tender_royal_pulse.crawler.queue import (
    ListPagePayload,
    TaskStatus,
    _task_from_row,
    claim_task,
    create_run,
    create_tasks,
    mark_task_done,
    recover_stale_tasks,
    update_heartbeat,
    upsert_tender,
)
from tender_royal_pulse.db.schema import initialize_schema
from tender_royal_pulse.models import Tender


def _build_tender(task_id: str, page_index: int, row_index: int) -> Tender:
    return Tender(
        source="test",
        tender_id=f"task-{task_id[-8:]}-p{page_index}-r{row_index}",
        title=f"Tender {page_index}-{row_index}",
        reference_number=f"REF-{page_index}-{row_index}",
        org_chain="Test Org / Dept",
        closing_date="2026-06-15",
        opening_date="2026-06-16",
    )


@pytest.fixture
def fresh_db(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "test_crash.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    initialize_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def seeded_run(fresh_db: sqlite3.Connection) -> tuple[str, str]:
    conn = fresh_db
    run_id = create_run(conn)
    payloads = [
        ListPagePayload(mode="closing_today", page_index=i, date_filter="2026-05-06")
        for i in range(3)
    ]
    tasks = create_tasks(conn, run_id, payloads)
    assert len(tasks) == 3
    return run_id, str(conn.execute("PRAGMA database_list").fetchone()["file"])


class TestStaleRecovery:
    def test_stale_heartbeat_recovered_to_pending(self, fresh_db: sqlite3.Connection) -> None:
        conn = fresh_db
        run_id = create_run(conn)
        payloads = [ListPagePayload(mode="closing_today", page_index=0)]
        tasks = create_tasks(conn, run_id, payloads)
        task = tasks[0]

        claimed = claim_task(conn, task.id)
        assert claimed is not None
        assert claimed.status == TaskStatus.RUNNING

        conn.execute(
            "UPDATE tasks SET heartbeat_at = '2020-01-01T00:00:00' WHERE id = ?",
            (task.id,),
        )
        conn.commit()

        recovered = recover_stale_tasks(conn, run_id, stale_timeout_seconds=1.0)
        assert len(recovered) == 1
        assert recovered[0].id == task.id
        assert recovered[0].status == TaskStatus.PENDING

    def test_fresh_heartbeat_not_recovered(self, fresh_db: sqlite3.Connection) -> None:
        conn = fresh_db
        run_id = create_run(conn)
        payloads = [ListPagePayload(mode="closing_today", page_index=0)]
        tasks = create_tasks(conn, run_id, payloads)
        task = tasks[0]

        claimed = claim_task(conn, task.id)
        assert claimed is not None
        update_heartbeat(conn, task.id)

        recovered = recover_stale_tasks(conn, run_id, stale_timeout_seconds=1.0)
        assert len(recovered) == 0

    def test_stale_task_at_max_attempts_not_recovered(self, fresh_db: sqlite3.Connection) -> None:
        conn = fresh_db
        run_id = create_run(conn)
        payloads = [ListPagePayload(mode="closing_today", page_index=0)]
        tasks = create_tasks(conn, run_id, payloads)
        task = tasks[0]

        conn.execute(
            "UPDATE tasks SET status = 'RUNNING', attempt_count = 3, "
            "heartbeat_at = '2020-01-01T00:00:00' WHERE id = ?",
            (task.id,),
        )
        conn.commit()

        recovered = recover_stale_tasks(conn, run_id, stale_timeout_seconds=1.0)
        assert len(recovered) == 0

    def test_multiple_stale_tasks_recovered(self, fresh_db: sqlite3.Connection) -> None:
        conn = fresh_db
        run_id = create_run(conn)
        payloads = [ListPagePayload(mode="closing_today", page_index=i) for i in range(5)]
        tasks = create_tasks(conn, run_id, payloads)

        for task in tasks[:3]:
            claim_task(conn, task.id)
        for task in tasks[:2]:
            conn.execute(
                "UPDATE tasks SET heartbeat_at = '2020-01-01T00:00:00' WHERE id = ?",
                (task.id,),
            )
        conn.commit()
        update_heartbeat(conn, tasks[2].id)

        recovered = recover_stale_tasks(conn, run_id, stale_timeout_seconds=1.0)
        assert len(recovered) == 2


class TestIdempotentUpsert:
    def test_insert_new_tender(self, fresh_db: sqlite3.Connection) -> None:
        conn = fresh_db
        tender = Tender(source="test", tender_id="T001", title="Test Tender", closing_date="2026-06-15")
        inserted = upsert_tender(conn, tender)
        assert inserted is True

        cursor = conn.execute("SELECT * FROM tenders WHERE tender_id = ?", ("T001",))
        row = cursor.fetchone()
        assert row is not None
        assert row["title"] == "Test Tender"

    def test_upsert_updates_existing(self, fresh_db: sqlite3.Connection) -> None:
        conn = fresh_db
        upsert_tender(conn, Tender(source="test", tender_id="T001", title="Original Title"))
        updated = upsert_tender(conn, Tender(source="test", tender_id="T001", title="Updated Title"))
        assert not updated

        cursor = conn.execute("SELECT * FROM tenders WHERE tender_id = ?", ("T001",))
        row = cursor.fetchone()
        assert row["title"] == "Updated Title"

    def test_unique_constraint_prevents_duplicates(self, fresh_db: sqlite3.Connection) -> None:
        conn = fresh_db
        upsert_tender(conn, Tender(source="test", tender_id="T001", title="First"))
        upsert_tender(conn, Tender(source="test", tender_id="T001", title="Second"))

        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM tenders WHERE source = ? AND tender_id = ?",
            ("test", "T001"),
        )
        assert cursor.fetchone()["cnt"] == 1

    def test_different_sources_same_tender_id(self, fresh_db: sqlite3.Connection) -> None:
        conn = fresh_db
        upsert_tender(conn, Tender(source="src_a", tender_id="T001", title="A"))
        upsert_tender(conn, Tender(source="src_b", tender_id="T001", title="B"))

        cursor = conn.execute("SELECT COUNT(*) as cnt FROM tenders")
        assert cursor.fetchone()["cnt"] == 2


class TestCrashRecoveryFlow:
    ROWS_PER_PAGE = 3

    def test_full_run_completes_with_no_duplicates(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "recovery_test.db")
        run_id = "recovery-run-1"

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)

        create_run(conn, run_id)
        payloads = [
            ListPagePayload(mode="closing_today", page_index=i)
            for i in range(3)
        ]
        tasks = create_tasks(conn, run_id, payloads)
        conn.close()

        all_tenders: dict[str, list[Tender]] = {}
        for t in tasks:
            tenders = [
                _build_tender(t.id, t.payload.page_index, ri)
                for ri in range(self.ROWS_PER_PAGE)
            ]
            all_tenders[t.id] = tenders

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        task0 = tasks[0]
        conn.execute(
            "UPDATE tasks SET status = 'DONE', updated_at = datetime('now') WHERE id = ?",
            (task0.id,),
        )
        conn.commit()

        for tender in all_tenders[task0.id]:
            upsert_tender(conn, tender)

        task1 = tasks[1]
        conn.execute(
            "UPDATE tasks SET status = 'RUNNING', heartbeat_at = '2020-01-01T00:00:00Z', "
            "attempt_count = 1 WHERE id = ?",
            (task1.id,),
        )
        conn.commit()

        for tender in all_tenders[task1.id][:1]:
            upsert_tender(conn, tender)

        conn.close()

        engine = CrawlEngine(
            db_path=db_path,
            row_processor=lambda ri, c: None,
            heartbeat_interval=0.5,
            stale_timeout_seconds=5.0,
        )
        recovered = engine.recover_stale(run_id)
        assert len(recovered) == 1
        assert recovered[0].id == task1.id

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        recovered_cursor = conn.execute(
            "SELECT status FROM tasks WHERE id = ?", (task1.id,)
        )
        assert recovered_cursor.fetchone()["status"] == "PENDING"

        for task in tasks[1:]:
            pending_cursor = conn.execute(
                "SELECT status FROM tasks WHERE id = ?", (task.id,)
            )
            assert pending_cursor.fetchone()["status"] == "PENDING"

            conn.execute(
                "UPDATE tasks SET status = 'DONE', updated_at = datetime('now') WHERE id = ?",
                (task.id,),
            )
            conn.commit()

            for tender in all_tenders[task.id]:
                upsert_tender(conn, tender)

        conn.close()

        all_done_conn = sqlite3.connect(db_path)
        all_done_conn.row_factory = sqlite3.Row
        all_task_rows = all_done_conn.execute(
            "SELECT status FROM tasks WHERE run_id = ?", (run_id,)
        ).fetchall()
        all_statuses = [r["status"] for r in all_task_rows]
        assert all(s == "DONE" for s in all_statuses), f"Not all tasks done: {all_statuses}"
        all_done_conn.close()

        verify_conn = sqlite3.connect(db_path)
        verify_conn.row_factory = sqlite3.Row
        tender_count = verify_conn.execute("SELECT COUNT(*) as cnt FROM tenders").fetchone()["cnt"]
        expected = len(tasks) * self.ROWS_PER_PAGE
        assert tender_count == expected, f"Expected {expected} tenders, got {tender_count}"
        verify_conn.close()

    def test_idempotence_on_reprocessing(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "idempotence_test.db")
        run_id = "idem-run-1"

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        create_run(conn, run_id)
        conn.close()

        tender_ids = [f"IDEM-T-{i:04d}" for i in range(5)]

        for _round in range(3):
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            for tid in tender_ids:
                upsert_tender(conn, Tender(source="test", tender_id=tid, title=f"Round {_round} - {tid}"))
            conn.close()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) as cnt FROM tenders").fetchone()["cnt"]
        assert count == 5, f"Expected 5 tenders, got {count}"
        row = conn.execute(
            "SELECT title FROM tenders WHERE tender_id = ?", (tender_ids[0],)
        ).fetchone()
        assert row is not None
        assert "Round 2" in row["title"], f"Expected 'Round 2' title, got: {row['title']}"
        conn.close()


class TestEngineExecuteSingleTask:
    def test_single_task_executes_to_done(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "single_task.db")
        run_id = "single-task-run"

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        create_run(conn, run_id)
        payloads = [ListPagePayload(mode="closing_today", page_index=0)]
        tasks = create_tasks(conn, run_id, payloads)
        task_id = tasks[0].id
        conn.close()

        row_count = 0

        def mock_processor(row_index: int, conn: sqlite3.Connection) -> Tender | None:
            nonlocal row_count
            if row_count >= 3:
                return None
            tender = _build_tender(task_id, 0, row_count)
            row_count += 1
            return tender

        conn2 = sqlite3.connect(db_path)
        conn2.row_factory = sqlite3.Row
        cursor = conn2.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        task = _task_from_row(cursor.fetchone())
        execute_list_page_task(conn2, task, process_row=mock_processor, heartbeat_interval=0.1)
        conn2.close()

        conn3 = sqlite3.connect(db_path)
        conn3.row_factory = sqlite3.Row
        status_row = conn3.execute(
            "SELECT status FROM tasks WHERE id = ?", (task_id,)
        ).fetchone()
        assert status_row is not None
        assert status_row["status"] == "DONE"
        tender_count = conn3.execute("SELECT COUNT(*) as cnt FROM tenders").fetchone()["cnt"]
        assert tender_count == 3, f"Expected 3 tenders, got {tender_count}"
        conn3.close()


class TestStaleRecoveryEndToEnd:
    def test_engine_recovers_and_completes(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "end_to_end.db")
        run_id = "e2e-run-1"
        task_count = 3
        rows_per_task = 3

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        initialize_schema(conn)
        create_run(conn, run_id)
        payloads = [
            ListPagePayload(mode="closing_today", page_index=i)
            for i in range(task_count)
        ]
        tasks = create_tasks(conn, run_id, payloads)
        conn.close()

        task_tenders: dict[str, list[Tender]] = {}
        for t in tasks:
            task_tenders[t.id] = [
                _build_tender(t.id, t.payload.page_index, ri)
                for ri in range(rows_per_task)
            ]

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        claim_task(conn, tasks[0].id)
        for tender in task_tenders[tasks[0].id]:
            upsert_tender(conn, tender)
        mark_task_done(conn, tasks[0].id)

        conn.execute(
            "UPDATE tasks SET status = 'RUNNING', heartbeat_at = '2020-01-01T00:00:00Z', "
            "attempt_count = 1 WHERE id = ?",
            (tasks[1].id,),
        )
        conn.execute(
            "UPDATE tasks SET status = 'RUNNING', heartbeat_at = '2020-01-01T00:00:00Z', "
            "attempt_count = 1 WHERE id = ?",
            (tasks[2].id,),
        )
        conn.commit()
        conn.close()

        engine = CrawlEngine(
            db_path=db_path,
            heartbeat_interval=0.5,
            stale_timeout_seconds=0.1,
        )
        recovered = engine.recover_stale(run_id)
        assert len(recovered) == 2
        recovered_ids = {t.id for t in recovered}
        assert tasks[1].id in recovered_ids
        assert tasks[2].id in recovered_ids

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        for tid in recovered_ids:
            status = conn.execute("SELECT status FROM tasks WHERE id = ?", (tid,)).fetchone()["status"]
            assert status == "PENDING", f"Task {tid} should be PENDING, got {status}"

        for tid in recovered_ids:
            for tender in task_tenders[tid]:
                upsert_tender(conn, tender)
            conn.execute(
                "UPDATE tasks SET status = 'DONE', updated_at = datetime('now') WHERE id = ?",
                (tid,),
            )
        conn.commit()

        all_statuses = [
            conn.execute("SELECT status FROM tasks WHERE id = ?", (t.id,)).fetchone()["status"]
            for t in tasks
        ]
        assert all(s == "DONE" for s in all_statuses), f"Not all DONE: {all_statuses}"

        tender_count = conn.execute("SELECT COUNT(*) as cnt FROM tenders").fetchone()["cnt"]
        expected = len(tasks) * rows_per_task
        assert tender_count == expected, f"Expected {expected} tenders, got {tender_count}"

        tender_ids_query = conn.execute("SELECT tender_id FROM tenders ORDER BY tender_id").fetchall()
        all_tids = [r["tender_id"] for r in tender_ids_query]
        assert len(all_tids) == len(set(all_tids)), "Duplicate tender_ids found!"
        conn.close()
