# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI (Typer)                          │
│  tenderpulse crawl --input ... --db ... --output ...       │
└─────────────────────────────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                     CrawlEngine / Queue                     │
│  - SQLite task queue (state machine)                        │
│  - Heartbeat writes + stale recovery                         │
│  - Retry taxonomy with exponential backoff                   │
└─────────────────────────────────────────────────────────────┘
                               │
              ┌────────────────┴──────────────────┐
              ▼                                   ▼
┌──────────────────────┐            ┌──────────────────────┐
│  Playwright fetcher    │            │  Record & export     │
│  - list pages          │            │  - SQLite → tender   │
│  - detail pages        │            │  - CSV / JSONL       │
│  - session context     │            │  - attachments       │
└──────────────────────┘            └──────────────────────┘
```

## Components

### 1. CLI (`src/tender_royal_pulse/cli.py`)
- Entry point using **Typer**
- Commands: `crawl`, `export`, `status`

### 2. Task Scheduler / Queue (`src/tender_royal_pulse/crawler/queue.py`)
- Manages **PENDING → RUNNING → DONE / FAILED** state transitions
- Stores every task as a row in **SQLite** (native durability)
- Runs a **heartbeat thread** per active task

### 3. CrawlEngine (`src/tender_royal_pulse/crawler/engine.py`)
- Picks up pending tasks
- Calls `execute_list_page_task()` which:
  1. Claims the task (`PENDING → RUNNING`)
  2. Starts heartbeat thread
  3. Processes each row → `upsert_tender()`
  4. Marks `DONE` or `FAILED`
- On startup: **recovers stale tasks** and re‑queues them

### 4. Retry layer (`src/tender_royal_pulse/crawler/retry.py`)
- Classifies errors into **9 buckets** (`ErrorClass` enum)
- Looks up `RetryConfig` (max attempts & back‑off seconds)
- Logs each attempt into `task_attempts` table

### 5. Playwright fetcher (`src/tender_royal_pulse/portal/eprocure_dom.py`)
- Uses **Playwright** to render dynamic JavaScript
- Manages **session context** (cookies & storage state) for ASP.NET session links
- Detects session expiry and re‑authenticates

### 6. Exporters (`src/tenderpulse/exporters/`)
- **CSV** exporter for tabular analysis
- **JSONL** exporter for streaming / BigQuery‑style pipelines

## Data flow

1. **Input** JSON → read filters, date range, session context
2. **Queue** → create `ListPagePayload` entries in `tasks` table
3. **Crawl** → `execute_list_page_task` fetches each page, extracts rows
4. **Upsert** → each `Tender` record inserted or updated in `tenders` table (idempotent via unique key: `source`, `tender_id`)
5. **Recover** → on restart: `recover_stale_tasks()` returns crashed/running tasks to `PENDING`
6. **Export** → `exporter` reads `tenders` + `attachments` out to CSV / JSONL

## Database tables

| Table | Purpose |
|-------|---------|
| `runs` | One row per crawl run |
| `tasks` | One row per page / task with state, heartbeat, error class |
| `task_attempts` | Full history of every attempt (audit trail) |
| `tenders` | Canonical tender records (idempotent upsert) |
| `attachments` | Files linked to each tender |
