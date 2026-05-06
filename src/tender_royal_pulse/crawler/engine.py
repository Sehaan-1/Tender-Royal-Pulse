from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable

from tender_royal_pulse.crawler.queue import (
    Task,
    claim_task,
    get_pending_tasks,
    log_task_attempt,
    mark_task_done,
    mark_task_failed_permanent,
    mark_task_failed_retryable,
    recover_stale_tasks,
    update_heartbeat,
    upsert_tender,
)
from tender_royal_pulse.crawler.retry import (
    classify_error,
    get_retry_config,
)
from tender_royal_pulse.models import Tender
from tender_royal_pulse.monitoring.logging import EventLogger, setup_logging


class CancellationToken:
    def __init__(self) -> None:
        self._cancelled = False
        self._lock = threading.Lock()

    @property
    def cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True


RowProcessor = Callable[[int, sqlite3.Connection], Tender | None]


def _default_row_processor(row_index: int, conn: sqlite3.Connection) -> Tender | None:
    return None


def execute_list_page_task(
    conn: sqlite3.Connection,
    task: Task,
    process_row: RowProcessor = _default_row_processor,
    heartbeat_interval: float = 2.0,
    cancel_token: CancellationToken | None = None,
    logger: EventLogger | None = None,
) -> None:
    log = logger or setup_logging()
    log = log.bind(
        run_id=task.run_id,
        task_id=task.id,
        task_type=task.task_type.value,
        attempt=task.attempt_count,
    )

    claimed = claim_task(conn, task.id)
    if claimed is None:
        log.warning("task_already_claimed")
        return
    task = claimed

    attempt_started = task.updated_at
    log_task_attempt(
        conn, task.id, task.attempt_count, "RUNNING", started_at=attempt_started,
    )

    heartbeat_stop = threading.Event()

    def _heartbeat_loop() -> None:
        while not heartbeat_stop.is_set():
            try:
                update_heartbeat(conn, task.id)
            except Exception:
                pass
            heartbeat_stop.wait(heartbeat_interval)

    heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    heartbeat_thread.start()

    row_count = 0
    try:
        payload = task.payload
        log.info(
            "task_started",
            mode=payload.mode,
            page_index=payload.page_index,
        )

        row_index = payload.row_cursor or 0
        while True:
            if cancel_token and cancel_token.cancelled:
                log.warning("task_cancelled")
                mark_task_failed_retryable(
                    conn, task.id, "CancelledError", "Task cancelled externally",
                )
                log_task_attempt(
                    conn, task.id, task.attempt_count, "FAILED_RETRYABLE",
                    error_class="CancelledError",
                    error_message="Task cancelled externally",
                    finished_at=task.updated_at,
                )
                return

            tender = process_row(row_index, conn)
            if tender is None:
                break

            upsert_tender(
                conn,
                tender=tender,
                raw_json_str=None
            )
            log.debug("row_processed", tender_id=tender.tender_id, row_index=row_index)
            row_count += 1
            row_index += 1

        mark_task_done(conn, task.id)
        log.info("task_completed", rows_processed=row_count)
        log_task_attempt(
            conn, task.id, task.attempt_count, "DONE",
            finished_at=task.updated_at,
        )

    except Exception as exc:
        error_class = classify_error(exc)
        retry_config = get_retry_config(exc)
        error_message = str(exc)
        log.exception("task_failed", error_class=error_class.value)
        if task.attempt_count >= retry_config.max_attempts:
            mark_task_failed_permanent(conn, task.id, error_class.value, error_message)
            log.error(
                "task_failed_permanent",
                error_class=error_class.value,
                attempt=task.attempt_count,
                max_attempts=retry_config.max_attempts,
            )
            log_task_attempt(
                conn, task.id, task.attempt_count, "FAILED_PERMANENT",
                error_class=error_class.value, error_message=error_message,
                finished_at=task.updated_at,
            )
        else:
            mark_task_failed_retryable(conn, task.id, error_class.value, error_message)
            log.warning(
                "task_failed_retryable",
                error_class=error_class.value,
                attempt=task.attempt_count,
            )
            log_task_attempt(
                conn, task.id, task.attempt_count, "FAILED_RETRYABLE",
                error_class=error_class.value, error_message=error_message,
                finished_at=task.updated_at,
            )

    finally:
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=heartbeat_interval + 1)


class CrawlEngine:
    def __init__(
        self,
        db_path: str,
        row_processor: RowProcessor = _default_row_processor,
        heartbeat_interval: float = 2.0,
        stale_timeout_seconds: float = 30.0,
        logger: EventLogger | None = None,
    ) -> None:
        self._db_path = db_path
        self._row_processor = row_processor
        self._heartbeat_interval = heartbeat_interval
        self._stale_timeout_seconds = stale_timeout_seconds
        self._logger = logger or setup_logging()
        self._cancel_token = CancellationToken()

    @property
    def cancel_token(self) -> CancellationToken:
        return self._cancel_token

    def recover_stale(self, run_id: str) -> list[Task]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            recovered = recover_stale_tasks(conn, run_id, self._stale_timeout_seconds)
            if recovered:
                self._logger.info(
                    "stale_tasks_recovered",
                    run_id=run_id,
                    count=len(recovered),
                )
            return recovered
        finally:
            conn.close()

    def process_run(self, run_id: str) -> int:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            self._logger.info("run_started", run_id=run_id)

            recovered = recover_stale_tasks(conn, run_id, self._stale_timeout_seconds)
            if recovered:
                self._logger.info(
                    "stale_tasks_recovered",
                    run_id=run_id,
                    count=len(recovered),
                )

            processed = 0
            while True:
                if self._cancel_token.cancelled:
                    self._logger.warning("engine_cancelled", run_id=run_id)
                    break

                pending = get_pending_tasks(conn, run_id)
                if not pending:
                    self._logger.info("run_completed", run_id=run_id, tasks_processed=processed)
                    break

                task = pending[0]
                execute_list_page_task(
                    conn,
                    task,
                    process_row=self._row_processor,
                    heartbeat_interval=self._heartbeat_interval,
                    cancel_token=self._cancel_token,
                    logger=self._logger,
                )
                processed += 1

            return processed
        finally:
            conn.close()

    def cancel(self) -> None:
        self._cancel_token.cancel()

    def execute_single_task(self, run_id: str, task_id: str) -> None:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row is None:
                raise ValueError(f"Task {task_id} not found")
            from tender_royal_pulse.crawler.queue import _task_from_row
            task = _task_from_row(row)
            execute_list_page_task(
                conn,
                task,
                process_row=self._row_processor,
                heartbeat_interval=self._heartbeat_interval,
                cancel_token=self._cancel_token,
                logger=self._logger,
            )
        finally:
            conn.close()
