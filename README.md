<div align="center">

<!-- BANNER -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:0f2027,50:203a43,100:2c5364&height=200&section=header&text=TenderPulse&fontSize=72&fontColor=ffffff&fontAlignY=38&desc=Production-grade%20eProcure%20Tender%20Intelligence%20Engine&descAlignY=58&descSize=18&animation=fadeIn" width="100%"/>

<!-- BADGES -->
![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.40%2B-2EAD33?style=for-the-badge&logo=playwright&logoColor=white)
![SQLite](https://img.shields.io/badge/SQLite-Queue%20Engine-003B57?style=for-the-badge&logo=sqlite&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-v2-E92063?style=for-the-badge&logo=pydantic&logoColor=white)
![Ruff](https://img.shields.io/badge/Linter-Ruff-FCC21B?style=for-the-badge)
![mypy](https://img.shields.io/badge/Types-mypy%20strict-2A6DB2?style=for-the-badge)
![License](https://img.shields.io/badge/License-MIT-22C55E?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Alpha%20v0.1-F59E0B?style=for-the-badge)

<br/>

> **Crawl. Validate. Export.**
> Automated extraction of 50 000+ public tenders from [eProcure / CPPP](https://etenders.gov.in) — India's Government procurement portal — with crash recovery, idempotent upserts, and a full retry taxonomy.

</div>

---

## 📋 Table of Contents

- [Why eProcure Is Hard](#-why-eprocure-is-hard)
- [Architecture Overview](#-architecture-overview)
- [Key Features](#-key-features)
- [Project Structure](#-project-structure)
- [Data Model](#-data-model)
- [Reliability Engine](#-reliability-engine)
  - [State Machine](#state-machine)
  - [Heartbeat & Stale Recovery](#heartbeat--stale-recovery)
  - [Retry Taxonomy](#retry-taxonomy)
- [Quickstart](#-quickstart)
- [Installation](#-installation)
- [Usage](#-usage)
- [Testing](#-testing)
- [Makefile Reference](#-makefile-reference)
- [Database Schema](#-database-schema)
- [Documentation](#-documentation)
- [Ethics & Limitations](#-ethics--limitations)
- [License](#-license)

---

## 🔥 Why eProcure Is Hard

The [eProcure (CPPP)](https://etenders.gov.in) portal is one of the most technically hostile scraping targets in Indian e-government infrastructure. Here's why — and how TenderPulse handles every obstacle:

| Challenge | Root Cause | TenderPulse Solution |
|-----------|-----------|----------------------|
| **Session-bound links** | ASP.NET ViewState + ephemeral session tokens in URLs | Playwright session context with cookie persistence & re-auth on expiry |
| **Dynamic JavaScript** | React/JS-rendered tables, no static HTML | Headless browser with explicit DOM-ready waits |
| **Rate limiting / IP blocks** | Aggressive throttling after burst requests | Adaptive exponential backoff with per-error-class limits |
| **Mid-run crashes** | Long crawls (hours) interrupted by network drops or OOM | SQLite heartbeat; supervisor re-queues stale tasks automatically |
| **Duplicate records** | Portal returns overlapping pages across sessions | Idempotent upsert keyed on `UNIQUE(source, tender_id)` |
| **Pagination drift** | Page numbers shift when new tenders are added | Shard-by-page tasks; each page is an atomic unit with full recovery |
| **Large datasets** | 50 000+ tenders across hundreds of pages | SQLite task queue with per-page granularity and incremental export |

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CLI  (Typer + Rich)                          │
│    tenderpulse crawl │ export │ status                              │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    CrawlEngine  /  Task Queue                       │
│                                                                     │
│   ┌─────────────┐  claim_task()  ┌─────────────┐  mark_done()     │
│   │   PENDING   │ ─────────────▶ │   RUNNING   │ ──────────▶ DONE │
│   └─────────────┘                └──────┬──────┘                   │
│         ▲  recover_stale_tasks()        │ mark_failed()            │
│         └────────────────────────── FAILED_RETRYABLE               │
│                                         │ (max attempts)           │
│                                    FAILED_PERMANENT                 │
│                                                                     │
│   Heartbeat thread writes heartbeat_at every 30 s per active task  │
└──────────────────┬──────────────────────────┬──────────────────────┘
                   │                          │
         ┌─────────▼──────────┐   ┌───────────▼────────────┐
         │  Playwright Fetcher │   │  Record & Export Layer  │
         │                    │   │                          │
         │  • List pages      │   │  • upsert_tender()       │
         │  • Detail pages    │   │  • CSV exporter          │
         │  • Session context │   │  • JSONL exporter        │
         │  • Re-auth         │   │  • attachments           │
         └────────────────────┘   └──────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │   SQLite Database  │
         │                    │
         │  runs              │
         │  tasks             │
         │  task_attempts     │
         │  tenders           │
         └────────────────────┘
```

**Data flow:**

```
Input JSON → Queue (ListPagePayload tasks) → Playwright fetch each page
    → extract rows → upsert_tender() [idempotent on UNIQUE(source, tender_id)]
    → on restart: recover_stale_tasks() → re-queue → continue
    → export: tenders → CSV / JSONL
```

---

## ✨ Key Features

| Feature | Details |
|---------|---------|
| 🤖 **Headless Browser Scraping** | Playwright-powered; handles JavaScript, session cookies, ASP.NET state |
| 🔄 **Crash Recovery** | Heartbeat per task; stale detection & automatic re-queue on restart |
| ♻️ **Idempotent Upserts** | `UNIQUE(source, tender_id)` prevents duplicate records across runs |
| 📦 **Rich Typed Data Models** | Pydantic v2 `Tender`, `Attachment`, `TenderMeta`, `RunSummary`, `ErrorEvent` |
| 🏷️ **9-Bucket Retry Taxonomy** | Per-error-class max attempts and exponential backoff |
| 💱 **Indian Money Normalization** | Parses ₹/Rs/INR, lakh/crore groupings → `Decimal` |
| 📅 **Date Normalization** | Handles Indian date formats → `datetime` |
| 📊 **Dual Export** | CSV (for analysts) and JSONL (for BigQuery / streaming pipelines) |
| 🛡️ **Strict Type Safety** | `mypy --strict` passes; zero `Any` leakage in production paths |
| 🔍 **Ruff Linting** | E, F, I, N, W, UP rule sets enforced in CI |
| 🧪 **Comprehensive Tests** | Unit tests (6 files) + integration crash-recovery E2E suite |
| 📋 **Rich CLI** | `crawl`, `export`, `status` commands with progress tables via Rich |

---

## 🗂️ Project Structure

```
tenderpulse/
│
├── src/
│   └── tender_royal_pulse/          # Main package (pip install name: tender-royal-pulse)
│       ├── __init__.py
│       ├── cli.py                   # Typer CLI — crawl, export, status commands
│       ├── cli_helpers.py           # Shared helpers: load_input_json, resolve_db, build_row_processor
│       ├── models.py                # Pydantic v2 models: Tender, Attachment, TenderMeta,
│       │                            #   RunSummary, ErrorEvent
│       ├── session_context.py       # ASP.NET session state (SessionContext Pydantic model)
│       │
│       ├── crawler/
│       │   ├── engine.py            # CrawlEngine — orchestrates task lifecycle
│       │   ├── queue.py             # SQLite task queue & state machine; upsert_tender()
│       │   └── retry.py             # 9-bucket error classification + backoff schedules
│       │
│       ├── portal/
│       │   └── eprocure_dom.py      # Playwright DOM fetcher: extract_listing_rows(),
│       │                            #   extract_detail_page(), PaginationNavigator
│       │
│       ├── db/
│       │   ├── engine.py            # DB connection helpers
│       │   └── schema.py            # DDL: initialize_schema(), all CREATE TABLE statements
│       │
│       ├── exporters/
│       │   ├── csv.py               # CSVExporter
│       │   └── jsonl.py             # JSONLExporter
│       │
│       ├── normalization/
│       │   ├── dates.py             # parse_date(), parse_datetime() — Indian date formats
│       │   ├── money.py             # parse_indian_money() — ₹/Rs/INR + lakh/crore groupings
│       │   └── text.py              # clean_text() — whitespace & encoding cleanup
│       │
│       ├── monitoring/
│       │   └── logging.py           # Heartbeat thread management & structured logging
│       │
│       └── reporters/
│           └── run_summary.py       # Rich progress reporter for crawl runs
│
├── tests/
│   ├── conftest.py                  # Shared pytest fixtures
│   ├── fixtures/
│   │   └── html/                   # listing_page.html, detail_page.html for integration tests
│   │
│   ├── unit/                        # Fast unit tests — no I/O, no browser
│   │   ├── test_error_classifier.py # 9-bucket error classification
│   │   ├── test_models_invariants.py# Tender / Attachment Pydantic invariants
│   │   ├── test_normalization_dates.py
│   │   ├── test_normalization_money.py
│   │   ├── test_queue.py            # SQLite task queue state transitions
│   │   └── test_retry_policy.py     # Backoff schedules & max-attempts enforcement
│   │
│   ├── integration/
│   │   └── test_crash_recovery.py  # Crash & stale recovery E2E tests (requires SQLite)
│   │
│   ├── test_exporters.py           # CSV / JSONL exporter correctness
│   ├── test_portal_parser.py       # Playwright DOM extraction (marked integration)
│   └── test_state_machine.py       # SessionContext model tests
│
├── docs/
│   ├── architecture.md             # Component diagram & data flow
│   ├── data_contract.md            # SQLite schema & Pydantic field spec
│   ├── test_plan.md                # Testing strategy & CI gates
│   ├── portal_analysis.md          # eProcure portal reverse-engineering notes
│   └── adr/                        # Architecture Decision Records
│       ├── 0001-single-worker.md
│       ├── 0002-playwright-sync.md
│       └── 0003-session-bound-urls.md
│
├── samples/                         # Sample outputs for local dev
├── scripts/                         # Helper scripts (e.g. build_main_dataset.py)
├── reports/                         # Coverage & audit reports
├── Makefile                         # Developer shortcuts
└── pyproject.toml                   # Build config, deps, ruff, mypy, pytest settings
```

---

## 📊 Data Model

### `Tender` — the canonical record

```python
class Tender(BaseModel):
    source:           str           # default "eprocure"
    tender_id:        str           # durable key — survives session expiry
    title:            str | None
    reference_number: str | None
    org_chain:        str | None    # "Ministry > Dept > SubDept > Unit"
    tender_type:      str | None
    category:         str | None
    tender_value:     Decimal | None  # normalized via parse_indian_money()
    emd_amount:       Decimal | None
    doc_fee:          Decimal | None
    currency:         str           # default "INR"
    closing_date:     datetime | None
    opening_date:     datetime | None
    published_date:   datetime | None
    detail_url:       str | None    # ephemeral session URL (debug only)
    attachments:      list[Attachment]
    meta:             TenderMeta | None
    raw_json:         dict | None
```

Auto-normalizes on construction: Indian money strings → `Decimal`, Indian date strings → `datetime`, text fields stripped via `clean_text()`.

### `Attachment`

```python
class Attachment(BaseModel):
    filename:    str
    doc_type:    str | None
    description: str | None
    url:         str | None
```

### `TenderMeta`

```python
class TenderMeta(BaseModel):
    run_id:        str | None
    task_id:       str | None
    fetched_at:    datetime | None
    fetcher_used:  str   # "eprocure_dom.playwright"
    parse_version: str   # "1.0.0"
    page_index:    int | None
    row_index:     int | None
```

---

## 🛡️ Reliability Engine

### State Machine

Every crawl page is an atomic **task** with a strict lifecycle enforced by the SQLite queue:

```
   ┌───────────┐  claim_task()  ┌───────────┐  mark_task_done()
   │  PENDING  │──────────────▶ │  RUNNING  │──────────────────▶  DONE ✅
   └───────────┘                └─────┬─────┘
         ▲                            │  mark_task_failed_retryable()
         │  recover_stale_tasks()     ▼
         │  (heartbeat expired) FAILED_RETRYABLE 🔁
         │                            │  (attempt_count >= max_attempts)
         └────────────────────────────┘
                                      ▼
                              FAILED_PERMANENT ❌
```

| State | Meaning | Transitions To |
|-------|---------|----------------|
| `PENDING` | Queued, not started | `RUNNING` |
| `RUNNING` | Actively processing | `DONE`, `FAILED_RETRYABLE`, `FAILED_PERMANENT` |
| `DONE` | Successfully completed | — |
| `FAILED_RETRYABLE` | Transient failure (timeout, 429, network) | `RUNNING` (retry), `FAILED_PERMANENT` |
| `FAILED_PERMANENT` | Unrecoverable (auth failure, bad input) | — |

---

### Heartbeat & Stale Recovery

Each active task updates `heartbeat_at = now()` in SQLite every **30 seconds** via a background thread. On the next `CrawlEngine` startup, `recover_stale_tasks()` queries:

```sql
SELECT * FROM tasks
WHERE run_id = ?
  AND status = 'RUNNING'
  AND heartbeat_at < <now - threshold>
  AND attempt_count < max_attempts
```

Stale tasks are reset to `PENDING` and re-processed. **No human intervention required.**

---

### Retry Taxonomy

Errors are classified into **9 distinct buckets** — each with its own max-attempts ceiling and exponential backoff schedule.

| Error Class | Cause | Max Attempts | Backoff |
|-------------|-------|:------------:|---------|
| `TIMEOUT` | Request timed out | 3 | 1 s → 2 s → 4 s |
| `HTTP_429` | Rate limited | 3 | 5 s → 10 s → 20 s |
| `HTTP_5XX` | Server error | 3 | 1 s → 2 s → 4 s |
| `SESSION_EXPIRED` | ASP.NET session invalidated | 2 | 3 s → 6 s |
| `PARSE_FAILURE` | DOM structure mismatch | 2 | 0.5 s → 1 s |
| `NETWORK_ERROR` | DNS / TCP failure | 3 | 1 s → 2 s → 4 s |
| `HTTP_4XX` | Bad request / not found | 1 | — |
| `SELECTOR_DRIFT` | CSS selector gone | 1 | — |
| `UNKNOWN` | Unclassified exception | 2 | 1 s → 2 s |

Every attempt is persisted in `task_attempts` for forensic debugging.
> Source: [`src/tender_royal_pulse/crawler/retry.py`](src/tender_royal_pulse/crawler/retry.py)

---

## 🚀 Quickstart

```bash
# 1 — Install
pip install -e ".[dev]"
playwright install chromium

# 2 — Run unit tests (no browser required)
python -m pytest -m "not integration" -q

# 3 — Lint + type check
ruff check . && mypy src/

# 4 — Run a sample crawl (mock mode)
make run

# 5 — Export to JSONL
make export
```

> **Note:** The `crawl` command requires a live Playwright session with eProcure credentials. Use `make run` with `samples/INPUT.example.json` for local development.

---

## ⚙️ Installation

### Prerequisites

- Python **3.11+**
- Git
- ~500 MB disk space (Chromium for Playwright)

```bash
# 1 — Clone
git clone https://github.com/yourusername/tenderpulse.git
cd tenderpulse

# 2 — Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3 — Install package + dev dependencies
pip install -e ".[dev]"

# 4 — Download Playwright's Chromium
playwright install chromium

# 5 — Verify
tenderpulse --help
# or: python -m tender_royal_pulse.cli --help
```

---

## 🚀 Usage

### Crawl tenders

```bash
tenderpulse crawl \
    --input  samples/INPUT.example.json \
    --db     data/tenderpulse.db \
    --output data/tenders.csv \
    --format csv

# Limit to 5 pages (for testing)
tenderpulse crawl --input samples/INPUT.example.json --db data/tenderpulse.db --limit 5
```

**Minimal `INPUT.example.json`:**

```json
{
  "filters": {
    "date_from": "2026-01-01",
    "date_to":   "2026-05-01",
    "tender_type": "all"
  },
  "session_context": { "version": 1 }
}
```

### Export from an existing database

```bash
# JSONL — BigQuery / streaming pipelines
tenderpulse export --db data/tenderpulse.db --output exports/tenders.jsonl --format jsonl

# CSV — Excel / analysis
tenderpulse export --db data/tenderpulse.db --output exports/tenders.csv --format csv
```

### Check crawl status

```bash
tenderpulse status --db data/tenderpulse.db
```

Output (Rich table):

```
            Recent Crawl Runs
┌──────────┬─────────┬─────────────────────┬───────┬──────┬─────────┬────────┐
│ Run ID   │ Status  │ Started             │ Total │ Done │ Pending │ Failed │
├──────────┼─────────┼─────────────────────┼───────┼──────┼─────────┼────────┤
│ a1b2c3d4 │ running │ 2026-05-07 01:00:00 │    10 │    8 │       1 │      1 │
└──────────┴─────────┴─────────────────────┴───────┴──────┴─────────┴────────┘
```

---

## 🧪 Testing

```bash
# Unit tests only — fast, no browser, no DB I/O
python -m pytest -m "not integration" -q

# Full suite with coverage
make test

# Integration tests — requires SQLite (no browser)
python -m pytest tests/integration/ -v

# Portal parser tests — requires Playwright + HTML fixtures
python -m pytest tests/test_portal_parser.py -v

# Lint + type check (mirrors CI)
ruff check .
mypy src/
```

### Test suite overview

| Module | Tests | Category |
|--------|-------|----------|
| `tests/unit/test_error_classifier.py` | Error bucket classification | Unit |
| `tests/unit/test_models_invariants.py` | Pydantic model constraints | Unit |
| `tests/unit/test_normalization_dates.py` | Indian date parsing | Unit |
| `tests/unit/test_normalization_money.py` | Indian money parsing | Unit |
| `tests/unit/test_queue.py` | SQLite state machine | Unit |
| `tests/unit/test_retry_policy.py` | Backoff & max-attempts | Unit |
| `tests/integration/test_crash_recovery.py` | Crash + stale recovery E2E | Integration |
| `tests/test_exporters.py` | CSV / JSONL escaping & validity | Unit |
| `tests/test_state_machine.py` | `SessionContext` model | Unit |
| `tests/test_portal_parser.py` | DOM extraction via Playwright | Integration |

---

## 📋 Makefile Reference

| Command | Description |
|---------|-------------|
| `make test` | Full test suite with coverage (`--cov=src`) |
| `make test-all` | Full suite verbose (`-v`) |
| `make test-unit` | Unit tests only (`-m "not integration"`) |
| `make test-integration` | Integration tests only |
| `make run` | Sample crawl via mock input JSON |
| `make export` | Export sample SQLite DB → JSONL |
| `make lint` | `ruff check src tests` |
| `make typecheck` | `mypy src/` |
| `make fmt` | `ruff format src tests` |
| `make clean` | Remove `__pycache__`, `.pytest_cache`, build artifacts |
| `make clean-win` | Same as `clean` but PowerShell-compatible |

---

## 🗄️ Database Schema

```sql
-- One row per crawl session
CREATE TABLE runs (
    id         TEXT PRIMARY KEY,
    status     TEXT NOT NULL DEFAULT 'running',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Core task queue (one row per page)
CREATE TABLE tasks (
    id                   TEXT PRIMARY KEY,
    run_id               TEXT NOT NULL REFERENCES runs(id),
    task_type            TEXT NOT NULL,          -- LIST_PAGE
    status               TEXT NOT NULL DEFAULT 'PENDING',
    attempt_count        INTEGER NOT NULL DEFAULT 0,
    max_attempts         INTEGER NOT NULL DEFAULT 3,
    heartbeat_at         TEXT,                   -- updated every 30 s
    error_class          TEXT,                   -- 9-bucket classification
    last_error           TEXT,
    payload_json         TEXT NOT NULL,          -- JSON-encoded ListPagePayload
    session_context_json TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

-- Full audit trail of every attempt
CREATE TABLE task_attempts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id        TEXT NOT NULL REFERENCES tasks(id),
    attempt_number INTEGER NOT NULL,
    status         TEXT NOT NULL,
    error_class    TEXT,
    error_message  TEXT,
    started_at     TEXT,
    finished_at    TEXT
);

-- Canonical tender records — idempotent via UNIQUE(source, tender_id)
CREATE TABLE tenders (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT NOT NULL DEFAULT 'eprocure',
    tender_id        TEXT NOT NULL,
    title            TEXT,
    reference_number TEXT,
    org_chain        TEXT,
    tender_type      TEXT,
    category         TEXT,
    tender_value     TEXT,      -- stored as Decimal string
    emd_amount       TEXT,
    doc_fee          TEXT,
    closing_date     TEXT,      -- ISO 8601
    opening_date     TEXT,
    published_date   TEXT,
    detail_url       TEXT,
    raw_json         TEXT,      -- full raw JSON blob
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE(source, tender_id)
);
```

**Indexes** (auto-created by `initialize_schema()`):

```sql
CREATE INDEX idx_tasks_run_id     ON tasks(run_id);
CREATE INDEX idx_tasks_status     ON tasks(status);
CREATE INDEX idx_tasks_heartbeat  ON tasks(heartbeat_at);
CREATE INDEX idx_task_attempts_task_id ON task_attempts(task_id);
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [`docs/architecture.md`](docs/architecture.md) | Component diagram, data flow, module responsibilities |
| [`docs/data_contract.md`](docs/data_contract.md) | SQLite schema, Pydantic models, state machine spec |
| [`docs/test_plan.md`](docs/test_plan.md) | Testing strategy, coverage gates, CI requirements |
| [`docs/portal_analysis.md`](docs/portal_analysis.md) | eProcure portal reverse-engineering notes |
| [`docs/adr/0001-single-worker.md`](docs/adr/0001-single-worker.md) | ADR: Single-worker architecture |
| [`docs/adr/0002-playwright-sync.md`](docs/adr/0002-playwright-sync.md) | ADR: Playwright sync API choice |
| [`docs/adr/0003-session-bound-urls.md`](docs/adr/0003-session-bound-urls.md) | ADR: Session-bound URL handling |

---

## ⚖️ Ethics & Limitations

| Topic | Policy |
|-------|--------|
| **Rate limiting** | Built-in adaptive delay; backs off aggressively on `HTTP_429` — we stay within eProcure's limits |
| **No CAPTCHA bypass** | Crawler **stops** and surfaces `SELECTOR_DRIFT` if a CAPTCHA is detected |
| **Public data only** | Only government-published procurement data visible without credentials |
| **Robots.txt** | Respected — do not scale beyond reasonable limits |
| **Use sample data first** | Use `samples/` and `make run` for development before live runs |
| **No PII** | No Personally Identifiable Information is collected or stored |

---

## 📄 License

MIT © 2026 TenderPulse Team

---

<div align="center">

**Built for India's public procurement ecosystem 🇮🇳**

*Crawl responsibly. Export cleanly. Recover automatically.*

![Footer](https://capsule-render.vercel.app/api?type=waving&color=0:2c5364,100:0f2027&height=100&section=footer)

</div>
