# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLI (Typer + Rich)                           │
│   tenderpulse crawl --input ... --db ... --output ... --limit ...  │
│   tenderpulse export --db ... --output ... --format csv|jsonl      │
│   tenderpulse status --db ...                                       │
└─────────────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     CrawlEngine / Queue                             │
│  - SQLite task queue (state machine: PENDING → RUNNING → DONE)     │
│  - Heartbeat writes every 30 s + stale recovery on startup         │
│  - Retry taxonomy: 9 error buckets with per-class backoff          │
└─────────────────────────────────────────────────────────────────────┘
                               │
              ┌────────────────┴──────────────────┐
              ▼                                   ▼
┌──────────────────────┐            ┌──────────────────────────┐
│  Playwright Fetcher  │            │  Record & Export Layer    │
│  (eprocure_dom.py)   │            │                           │
│  - list pages        │            │  - upsert_tender()        │
│  - detail pages      │            │  - CSVExporter            │
│  - PaginationNav     │            │  - JSONLExporter          │
│  - SessionContext    │            │                           │
└──────────────────────┘            └──────────────────────────┘
              │
┌─────────────▼──────────────┐
│  Normalization Layer       │
│  - parse_indian_money()    │
│  - parse_date/datetime()   │
│  - clean_text()            │
└─────────────┬──────────────┘
              │
┌─────────────▼──────────────┐
│   SQLite Database          │
│   (initialize_schema())    │
│                            │
│   runs                     │
│   tasks                    │
│   task_attempts            │
│   tenders  (+ 4 indexes)   │
└────────────────────────────┘
```

---

## Components

### 1. CLI — `src/tender_royal_pulse/cli.py`

Entry point using **Typer** with **Rich** console output.

| Command | Description |
|---------|-------------|
| `crawl` | Load input JSON → create run + tasks → run `CrawlEngine` → optional export |
| `export` | Read tenders from SQLite → write CSV or JSONL |
| `status` | Print a Rich table of the last 5 runs with task counts by state |

Helper module `cli_helpers.py` provides `load_input_json()`, `resolve_db()`, `build_row_processor()`.

---

### 2. Task Queue — `src/tender_royal_pulse/crawler/queue.py`

Manages the full **task lifecycle** in SQLite.

**Key functions:**

| Function | Description |
|----------|-------------|
| `create_run()` | Insert a row into `runs` |
| `create_tasks()` | Bulk-insert `ListPagePayload` tasks into `tasks` |
| `claim_task()` | Atomically transition `PENDING → RUNNING`, increment `attempt_count` |
| `update_heartbeat()` | Write `heartbeat_at = now()` for an active task |
| `mark_task_done()` | Transition `RUNNING → DONE` |
| `mark_task_failed_retryable()` | Transition to `FAILED_RETRYABLE` with error class + message |
| `mark_task_failed_permanent()` | Transition to `FAILED_PERMANENT` |
| `log_task_attempt()` | Append a row to `task_attempts` (audit trail) |
| `recover_stale_tasks()` | Reset `RUNNING` tasks with expired heartbeat to `PENDING` |
| `upsert_tender()` | Insert or update a `Tender` in `tenders` (idempotent on `UNIQUE(source, tender_id)`) |

---

### 3. CrawlEngine — `src/tender_royal_pulse/crawler/engine.py`

Orchestrates the task lifecycle:

1. On startup: calls `recover_stale_tasks()` to re-queue crashed tasks
2. Fetches `PENDING` tasks for the run
3. For each task: `claim_task()` → start heartbeat thread → call row processor → `mark_task_done()` or `mark_task_failed_*`
4. Returns count of processed tasks

---

### 4. Retry Layer — `src/tender_royal_pulse/crawler/retry.py`

Classifies exceptions into **9 `ErrorClass` buckets** and looks up the corresponding `RetryConfig` (max attempts + backoff seconds list).

Errors at or beyond `max_attempts` are promoted to `FAILED_PERMANENT`.

---

### 5. Playwright Fetcher — `src/tender_royal_pulse/portal/eprocure_dom.py`

Uses **Playwright sync API** to render eProcure's JavaScript-heavy pages.

| Export | Description |
|--------|-------------|
| `extract_listing_rows(page)` | Returns `list[Tender]` from a listing page |
| `extract_detail_page(page)` | Returns a `Tender` (with attachments) from a detail page |
| `PaginationNavigator(page)` | `has_next()` / `click_next()` helpers |

Manages **session context** (cookies & Playwright storage state) for ASP.NET session-bound URLs.

---

### 6. DB Layer — `src/tender_royal_pulse/db/`

- `schema.py`: `initialize_schema(conn)` — creates all tables and indexes, sets `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON`
- `engine.py`: connection helpers

---

### 7. Exporters — `src/tender_royal_pulse/exporters/`

| Class | Output |
|-------|--------|
| `CSVExporter` | UTF-8 CSV with proper quoting (handles commas, quotes, newlines in fields) |
| `JSONLExporter` | One JSON object per line — BigQuery / streaming pipeline friendly |

Both accept `list[dict[str, Any]]` and a filename. Output directory is set at construction time.

---

### 8. Normalization — `src/tender_royal_pulse/normalization/`

Auto-applied in `Tender._normalize_fields()` via Pydantic `model_validator`:

| Module | Function | Description |
|--------|----------|-------------|
| `money.py` | `parse_indian_money(raw)` | Strips ₹/Rs/INR, handles lakh/crore comma groupings → `Decimal` |
| `dates.py` | `parse_date(raw)`, `parse_datetime(raw)` | Indian date formats → `date` / `datetime` |
| `text.py` | `clean_text(raw)` | Strips extra whitespace, normalizes encoding |

---

## Data Flow

```
1. INPUT JSON
   └─ load_input_json() → extract filters + session_context

2. QUEUE INIT
   └─ create_run() → runs table
   └─ create_tasks() → tasks table (one ListPagePayload per page)

3. CRAWL LOOP (CrawlEngine.process_run)
   ├─ recover_stale_tasks() → reset crashed RUNNING tasks
   └─ for each PENDING task:
       ├─ claim_task()           → PENDING → RUNNING
       ├─ heartbeat thread start
       ├─ row_processor(task)    → Playwright fetch + DOM extract
       │   └─ extract_listing_rows(page) → list[Tender]
       │       └─ upsert_tender(conn, tender) → INSERT OR UPDATE tenders
       └─ mark_task_done() / mark_task_failed_*()

4. EXPORT
   └─ SELECT * FROM tenders → CSVExporter / JSONLExporter
```

---

## Architecture Decision Records

| ADR | Decision |
|-----|----------|
| [0001-single-worker](adr/0001-single-worker.md) | Single-process, single-worker design for simplicity and SQLite compatibility |
| [0002-playwright-sync](adr/0002-playwright-sync.md) | Playwright sync API chosen over async to avoid event-loop complexity |
| [0003-session-bound-urls](adr/0003-session-bound-urls.md) | Session-bound URLs stored only for debug; `tender_id` is the durable key |
