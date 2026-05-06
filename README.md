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
- [Data Snapshot](#-data-snapshot)
- [Reliability Engine](#-reliability-engine)
  - [State Machine](#state-machine)
  - [Heartbeat & Stale Recovery](#heartbeat--stale-recovery)
  - [Retry Taxonomy](#retry-taxonomy)
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
| **Duplicate records** | Portal returns overlapping pages across sessions | Idempotent upsert keyed on `(source, tender_id)` |
| **Pagination drift** | Page numbers shift when new tenders are added | Shard-by-page tasks; each page is an atomic unit with full recovery |
| **Large datasets** | 50 000+ tenders across hundreds of pages | SQLite task queue with per-page granularity and incremental export |

---

## 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                           CLI  (Typer + Rich)                       │
│    tenderpulse crawl │ export │ status                              │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    CrawlEngine  /  Task Queue                        │
│                                                                      │
│   ┌─────────────┐  claim_task()  ┌─────────────┐  mark_done()      │
│   │   PENDING   │ ────────────▶  │   RUNNING   │ ──────────▶ DONE  │
│   └─────────────┘                └──────┬──────┘                   │
│         ▲  recover_stale_tasks()        │ mark_failed()             │
│         └─────────────────────────── FAILED_RETRYABLE              │
│                                         │ (max attempts)            │
│                                    FAILED_PERMANENT                 │
│                                                                      │
│   Heartbeat thread writes heartbeat_at every 30 s per active task   │
└──────────────────┬──────────────────────────┬───────────────────────┘
                   │                          │
         ┌─────────▼──────────┐   ┌───────────▼────────────┐
         │  Playwright Fetcher │   │  Record & Export Layer  │
         │                    │   │                          │
         │  • List pages      │   │  • upsert_tender()       │
         │  • Detail pages    │   │  • CSV exporter          │
         │  • Session ctx     │   │  • JSONL exporter        │
         │  • Re-auth         │   │  • attachments           │
         └────────────────────┘   └──────────────────────────┘
                   │
         ┌─────────▼──────────┐
         │   SQLite Database   │
         │                    │
         │  runs              │
         │  tasks             │
         │  task_attempts     │
         │  tenders           │
         │  attachments       │
         └────────────────────┘
```

**Data flow:**

```
JSON Input → Queue (ListPagePayload tasks) → Playwright fetch each page
    → extract rows → upsert_tender() [idempotent]
    → on restart: recover_stale_tasks() → re-queue → continue
    → export: tenders + attachments → CSV / JSONL
```

---

## ✨ Key Features

| Feature | Details |
|---------|---------|
| 🤖 **Headless Browser Scraping** | Playwright-powered; handles JavaScript, session cookies, ASP.NET state |
| 🔄 **Crash Recovery** | Heartbeat per task; stale detection & automatic re-queue on restart |
| ♻️ **Idempotent Upserts** | `(source, tender_id)` unique key prevents duplicate records across runs |
| 📦 **Typed Data Models** | Full Pydantic v2 schema for `TenderRecord`, `SessionContext`, task payloads |
| 🏷️ **9-Bucket Retry Taxonomy** | Per-error-class max attempts and backoff — not a one-size-fits-all retry |
| 📊 **Dual Export** | CSV (for analysts) and JSONL (for BigQuery / streaming pipelines) |
| 🛡️ **Strict Type Safety** | `mypy --strict` passes; zero `Any` leakage in production paths |
| 🔍 **Ruff Linting** | E, F, I, N, W, UP rule sets enforced in CI |
| 🧪 **Integration Tests** | Full crash-recovery end-to-end test suite with 12+ passing tests |
| 📋 **Rich CLI** | `crawl`, `export`, `status` commands with progress bars via Rich |

---

## 🗂️ Project Structure

```
tenderpulse/
│
├── src/
│   ├── tender_royal_pulse/          # Main package
│   │   ├── cli.py                   # Typer CLI entry point
│   │   ├── models.py                # Pydantic data models (TenderRecord, etc.)
│   │   ├── session_context.py       # ASP.NET session state management
│   │   │
│   │   ├── crawler/
│   │   │   ├── engine.py            # CrawlEngine – orchestrates task lifecycle
│   │   │   ├── queue.py             # SQLite task queue & state machine
│   │   │   └── retry.py            # 9-bucket error classification + backoff
│   │   │
│   │   ├── portal/
│   │   │   └── eprocure_dom.py     # Playwright DOM fetcher (list + detail pages)
│   │   │
│   │   ├── db/                     # SQLite schema, migrations, upsert logic
│   │   ├── exporters/              # CSV and JSONL exporters
│   │   ├── normalization/          # Field cleaning and standardization
│   │   ├── monitoring/             # Heartbeat thread management
│   │   └── reporters/              # Rich progress reporters
│   │
│   └── tenderpulse/                # Legacy alias package
│
├── tests/
│   ├── unit/                       # Fast unit tests (no I/O)
│   └── integration/
│       └── test_crash_recovery.py  # Crash & stale recovery E2E tests
│
├── docs/
│   ├── architecture.md             # Component diagram & data flow
│   ├── data_contract.md            # SQLite schema & Pydantic field spec
│   ├── test_plan.md                # Testing strategy & gates
│   ├── portal_analysis.md          # eProcure portal reverse-engineering notes
│   └── adr/                        # Architecture Decision Records
│
├── samples/
│   └── sample_outputs/
│       └── main_dataset/
│           ├── tenders.csv         # ~1 000 sample tender rows
│           ├── tenders.jsonl       # JSONL equivalent
│           └── attachments.csv     # ~3 000 attachment rows
│
├── scripts/                        # Helper scripts
├── reports/                        # Coverage & audit reports
├── Makefile                        # Developer shortcuts
└── pyproject.toml                  # Build config, deps, ruff, mypy settings
```

---

## 📊 Data Snapshot

**Sample dataset (bundled in `samples/`):**

| File | Rows | Size |
|------|-----:|-----:|
| `tenders.csv` | ~1 000 | ~106 KB |
| `tenders.jsonl` | ~1 000 | ~160 KB |
| `attachments.csv` | ~3 000 | ~50 KB |

**Sample `tenders.csv` rows:**

```csv
"tender_id","title","org_chain","closing_date","value","status"
"TEND-1000","Tender for Supply of Goods 0","Central Govt > Ministry of Commerce > Department of Trade","2026-05-13","4066116","Open"
"TEND-1001","Tender for Supply of Goods 1","Central Govt > Ministry of Commerce > Department of Trade","2026-05-13","4768494","Awarded"
"TEND-1002","Tender for Supply of Goods 2","Central Govt > Ministry of Commerce > Department of Trade","2026-05-15","3967549","Closed"
```

**Full `TenderRecord` Pydantic schema:**

```python
class TenderRecord(BaseModel):
    tender_id:    str            # Durable key — survives session expiry
    title:        str
    closing_date: str | None
    opening_date: str | None
    direct_link:  str | None     # Ephemeral session URL (debug only)
    fetched_at:   datetime

    model_config = ConfigDict(extra="forbid")
```

---

## 🛡️ Reliability Engine

### State Machine

Every crawl page is an atomic **task** with a strict lifecycle enforced by the SQLite queue:

```
   ┌───────────┐  claim_task()  ┌───────────┐  mark_done()
   │  PENDING  │──────────────▶ │  RUNNING  │─────────────▶  DONE ✅
   └───────────┘                └─────┬─────┘
         ▲                            │  mark_failed()
         │  recover_stale_tasks()     ▼
         │  (heartbeat expired) FAILED_RETRYABLE 🔁
         │                            │  (max attempts reached)
         └────────────────────────────┘
                                      ▼
                              FAILED_PERMANENT ❌
```

| State | Meaning | Transitions To |
|-------|---------|----------------|
| `PENDING` | Queued, not started | `RUNNING` |
| `RUNNING` | Actively processing | `DONE`, `FAILED_RETRYABLE`, `FAILED_PERMANENT`, `STALE` |
| `DONE` | Successfully completed | — |
| `FAILED_RETRYABLE` | Transient failure (timeout, 429, network) | `RUNNING`, `FAILED_PERMANENT` |
| `FAILED_PERMANENT` | Unrecoverable (401, bad input) | — |
| `STALE` | Heartbeat expired; process presumed dead | `PENDING` (auto-recovered) |
| `SKIPPED` | Deduplication or user-skip | — |

---

### Heartbeat & Stale Recovery

Each task runs a **background heartbeat thread** writing `heartbeat_at = now()` to SQLite every 30 seconds. On the next `CrawlEngine` startup, `recover_stale_tasks()` scans for tasks where `heartbeat_at < now() - threshold AND state = 'RUNNING'` and resets them to `PENDING`. **No human intervention required.**

**Integration test results:**

```
$ python -m pytest tests/integration/test_crash_recovery.py -v

TestStaleRecovery
    test_stale_heartbeat_recovered_to_pending ........... PASSED
    test_fresh_heartbeat_not_recovered .................. PASSED
    test_stale_task_at_max_attempts_not_recovered ....... PASSED
    test_multiple_stale_tasks_recovered ................. PASSED

TestIdempotentUpsert
    test_insert_new_tender .............................. PASSED
    test_upsert_updates_existing ........................ PASSED
    test_unique_constraint_prevents_duplicates .......... PASSED
    test_different_sources_same_tender_id ............... PASSED

TestCrashRecoveryFlow
    test_full_run_completes_with_no_duplicates .......... PASSED
    test_idempotence_on_reprocessing .................... PASSED

TestEngineExecuteSingleTask
    test_single_task_executes_to_done ................... PASSED

TestStaleRecoveryEndToEnd
    test_engine_recovers_and_completes .................. PASSED
```

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
python -m tender_royal_pulse.cli --help
```

---

## 🚀 Usage

### Crawl tenders

```bash
python -m tender_royal_pulse.cli crawl \
    --input  samples/INPUT.example.json \
    --db     data/tenderpulse.db \
    --output data/tenders.csv
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
python -m tender_royal_pulse.cli export \
    --db data/tenderpulse.db --output exports/tenders.jsonl --format jsonl

# CSV — Excel / analysis
python -m tender_royal_pulse.cli export \
    --db data/tenderpulse.db --output exports/tenders.csv --format csv
```

### Check crawl status

```bash
python -m tender_royal_pulse.cli status --db data/tenderpulse.db
```

---

## 🧪 Testing

```bash
# Full suite with coverage
python -m pytest

# Fast unit tests only (no browser, no DB I/O)
python -m pytest -m "not integration" -q

# Crash-recovery integration tests
python -m pytest tests/integration/test_crash_recovery.py -v

# Lint + type check (mirrors CI)
ruff check .
mypy src/

# All-in-one shortcut
make test
```

---

## 📋 Makefile Reference

| Command | Description |
|---------|-------------|
| `make test` | Full test suite with coverage report |
| `make run` | Sample crawl using mock input |
| `make export` | Export the sample SQLite DB to JSONL |
| `make lint` | `ruff check .` |
| `make typecheck` | `mypy src/` |

---

## 🗄️ Database Schema

```sql
-- One row per crawl session
CREATE TABLE runs (
    id TEXT PRIMARY KEY, started_at TEXT, ended_at TEXT, status TEXT
);

-- Core task queue (one row per page)
CREATE TABLE tasks (
    id            TEXT PRIMARY KEY,
    task_type     TEXT,         -- listing_fetch | detail_fetch | export
    state         TEXT,         -- PENDING | RUNNING | DONE | ...
    payload       TEXT,         -- JSON-encoded payload
    attempt       INTEGER DEFAULT 0,
    error_class   TEXT,         -- 9-bucket classification
    error_message TEXT,
    heartbeat_at  TEXT,         -- updated every 30 s
    created_at    TEXT,
    updated_at    TEXT
);

-- Full audit trail of every attempt
CREATE TABLE task_attempts (
    id TEXT PRIMARY KEY, task_id TEXT REFERENCES tasks(id),
    attempt INTEGER, error_class TEXT, error_message TEXT,
    started_at TEXT, ended_at TEXT
);

-- Canonical tender records — idempotent via UNIQUE(source, tender_id)
CREATE TABLE tenders (
    tender_id TEXT, source TEXT, title TEXT,
    closing_date TEXT, opening_date TEXT, direct_link TEXT, fetched_at TEXT,
    PRIMARY KEY (tender_id, source)
);

-- Documents / files linked to each tender
CREATE TABLE attachments (
    id TEXT PRIMARY KEY, tender_id TEXT REFERENCES tenders(tender_id),
    filename TEXT, url TEXT, size_bytes INTEGER
);
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [`docs/architecture.md`](docs/architecture.md) | Component diagram, data flow, module responsibilities |
| [`docs/data_contract.md`](docs/data_contract.md) | SQLite schema, Pydantic models, state machine spec |
| [`docs/test_plan.md`](docs/test_plan.md) | Testing strategy, coverage gates, CI requirements |
| [`docs/portal_analysis.md`](docs/portal_analysis.md) | eProcure portal reverse-engineering notes |
| [`docs/adr/`](docs/adr/) | Architecture Decision Records |

---

## ⚖️ Ethics & Limitations

| Topic | Policy |
|-------|--------|
| **Rate limiting** | Built-in adaptive delay; backs off aggressively on `HTTP_429` — we stay within eProcure's limits |
| **No CAPTCHA bypass** | Crawler **stops** and surfaces `SELECTOR_DRIFT` if a CAPTCHA is detected |
| **Public data only** | Only government-published procurement data visible without credentials |
| **Robots.txt** | Respected — do not scale beyond reasonable limits |
| **Use sample data first** | Bundled `samples/` covers ~1 000 tenders; use for development before live runs |
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
