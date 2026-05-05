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
│                      TaskScheduler                          │
│  - State machine: PENDING → RUNNING → DONE                 │
│  - Retry policy with exponential backoff                    │
│  - Checkpoint to SQLite                                     │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
┌──────────────────┐                   ┌──────────────────────┐
│ ListingFetcher   │                   │ DetailFetcher       │
│ (Playwright)     │                   │ (Playwright)         │
└──────────────────┘                   └──────────────────────┘
        │                                       │
        └─────────────────────┬─────────────────┘
                              ▼
                   ┌─────────────────────┐
                   │   Exporter          │
                   │   CSV / JSONL       │
                   └─────────────────────┘
```

## Components

### 1. CLI (`src/tenderpulse/cli.py`)
- Entry point using Typer
- Commands: `crawl`, `status`

### 2. Task Scheduler
- Manages task queue and state transitions
- Handles crash recovery via SQLite checkpointing
- Implements retry policy (tenacity)

### 3. Fetchers
- `ListingFetcher`: Uses Playwright to fetch tender listing pages
- `DetailFetcher`: Uses Playwright to fetch individual tender details

### 4. Session Manager
- Stores/restores Playwright storage_state
- Detects session expiry ("Your session has timed out.")

### 5. Exporters
- CSV exporter
- JSONL exporter

## Data Flow

1. Load `INPUT.json` with filters and session context
2. Create ListingFetchTasks for each page
3. Execute tasks sequentially (single worker)
4. Store tender_id + metadata in SQLite
5. On resume: load incomplete tasks, skip DONE/permanent
6. Export completed tenders to CSV/JSONL

## Database Schema

See `docs/data_contract.md` for full schema.