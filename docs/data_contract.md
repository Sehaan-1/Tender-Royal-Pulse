# Data Contract

## Task State Machine

```
PENDING → RUNNING → DONE ✅
              ↓
        FAILED_RETRYABLE → RUNNING (retry, if attempt_count < max_attempts)
              ↓
        FAILED_PERMANENT ❌
```

> **Note:** Stale detection is handled implicitly — tasks stuck in `RUNNING` with an expired
> `heartbeat_at` are reset to `PENDING` by `recover_stale_tasks()` on the next engine startup.

### State Definitions

| State | Description | Transitions To |
|-------|-------------|----------------|
| `PENDING` | Not yet started | `RUNNING` |
| `RUNNING` | Currently processing; heartbeat updated every 30 s | `DONE`, `FAILED_RETRYABLE`, `FAILED_PERMANENT` |
| `DONE` | Successfully completed | — |
| `FAILED_RETRYABLE` | Transient failure (timeout, 429, network) | `RUNNING` (retry), `FAILED_PERMANENT` (max attempts) |
| `FAILED_PERMANENT` | No recovery path (auth failure, invalid input) | — |

### Resume Semantics

- **Crash recovery**: tasks stuck in `RUNNING` with `heartbeat_at < now - threshold` are reset to `PENDING`
- **Idempotent upsert**: even if a task is re-processed, `upsert_tender()` updates existing rows — no duplicates
- **At-least-once delivery**: a task may re-fetch an already-`DONE` page if the heartbeat threshold is very short

---

## Task Types

### `LIST_PAGE`

Fetches a single tender listing page.

**`ListPagePayload` fields:**

```python
class ListPagePayload(BaseModel):
    mode:        str            # "closing_today" | "all" | custom
    page_index:  int            # 1-based
    date_filter: str | None     # "YYYY-MM-DD,YYYY-MM-DD"
    row_cursor:  int | None     # optional row-level resume cursor
```

---

## Pydantic Models

### `SessionContext`

```python
class SessionContext(BaseModel):
    version:       int = 1
    storage_state: dict | None = None   # Playwright storage state (cookies, localStorage)
    user_agent:    str | None = None
    created_at:    datetime | None = None

    model_config = ConfigDict(extra="forbid")
```

- `to_playwright_storage_state()` → returns `storage_state` dict
- `from_playwright_storage_state(state, user_agent)` → class method constructor

---

### `Tender` — canonical record

```python
class Tender(BaseModel):
    source:           str = "eprocure"
    tender_id:        str                # durable key
    title:            str | None
    reference_number: str | None
    org_chain:        str | None         # "Dept > SubDept > Unit"
    tender_type:      str | None
    category:         str | None
    tender_value:     Decimal | None     # auto-parsed from Indian money strings
    emd_amount:       Decimal | None
    doc_fee:          Decimal | None
    currency:         str = "INR"
    closing_date:     datetime | None    # auto-parsed from Indian date strings
    opening_date:     datetime | None
    published_date:   datetime | None
    detail_url:       str | None         # ephemeral session URL (debug only)
    attachments:      list[Attachment]
    meta:             TenderMeta | None
    raw_json:         dict | None

    model_config = ConfigDict(extra="forbid", validate_assignment=True)
```

**Key computed properties:**

- `canonical_url_hash` → SHA-256 of `source|tender_id|reference_number|title|org_chain`
- `to_canonical_key()` → `"source|tender_id"`
- `to_csv_row()` → `dict[str, str]` with all fields as strings (for CSV export)

---

### `Attachment`

```python
class Attachment(BaseModel):
    filename:    str
    doc_type:    str | None
    description: str | None
    url:         str | None

    model_config = ConfigDict(extra="forbid")
```

---

### `TenderMeta`

```python
class TenderMeta(BaseModel):
    run_id:        str | None = None
    task_id:       str | None = None
    fetched_at:    datetime | None = None
    fetcher_used:  str = "eprocure_dom.playwright"
    parse_version: str = "1.0.0"
    page_index:    int | None = None
    row_index:     int | None = None

    model_config = ConfigDict(extra="forbid")
```

---

### `RunSummary`

```python
class RunSummary(BaseModel):
    run_id:             str
    status:             str = "running"
    tasks_total:        int = 0
    tasks_completed:    int = 0
    tasks_failed:       int = 0
    tenders_collected:  int = 0
    tenders_new:        int = 0
    tenders_updated:    int = 0
    started_at:         datetime | None = None
    finished_at:        datetime | None = None
    errors:             list[ErrorEvent] = []
```

---

### `ErrorEvent`

```python
class ErrorEvent(BaseModel):
    error_class:   str
    error_message: str
    task_id:       str | None = None
    tender_id:     str | None = None
    timestamp:     datetime | None = None
    resolved:      bool = False
```

---

## Database Schema

### `tasks` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `run_id` | TEXT FK→runs | Parent run |
| `task_type` | TEXT | `LIST_PAGE` |
| `status` | TEXT | `PENDING` \| `RUNNING` \| `DONE` \| `FAILED_RETRYABLE` \| `FAILED_PERMANENT` |
| `attempt_count` | INTEGER | Current attempt number |
| `max_attempts` | INTEGER | Default 3 |
| `heartbeat_at` | TEXT | ISO timestamp; updated every 30 s while RUNNING |
| `error_class` | TEXT | 9-bucket error classification |
| `last_error` | TEXT | Last error message |
| `payload_json` | TEXT | JSON-encoded `ListPagePayload` |
| `session_context_json` | TEXT | JSON-encoded `SessionContext` |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |

### `tenders` table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK AUTOINCREMENT | Internal row ID |
| `source` | TEXT | Default `eprocure` |
| `tender_id` | TEXT | Durable key from portal |
| `title` | TEXT | |
| `reference_number` | TEXT | |
| `org_chain` | TEXT | Hierarchy string |
| `tender_type` | TEXT | |
| `category` | TEXT | |
| `tender_value` | TEXT | Decimal as string |
| `emd_amount` | TEXT | Decimal as string |
| `doc_fee` | TEXT | Decimal as string |
| `closing_date` | TEXT | ISO 8601 |
| `opening_date` | TEXT | ISO 8601 |
| `published_date` | TEXT | ISO 8601 |
| `detail_url` | TEXT | Ephemeral session URL |
| `raw_json` | TEXT | Raw JSON blob |
| `created_at` | TEXT | ISO timestamp |
| `updated_at` | TEXT | ISO timestamp |
| **UNIQUE** | | `(source, tender_id)` — idempotent upsert key |

---

## Retry Policy

See `src/tender_royal_pulse/crawler/retry.py` for the authoritative config.

| Error Class | Max Attempts | Backoff (s) |
|-------------|:------------:|-------------|
| `TIMEOUT` | 3 | 1, 2, 4 |
| `HTTP_429` | 3 | 5, 10, 20 |
| `HTTP_5XX` | 3 | 1, 2, 4 |
| `SESSION_EXPIRED` | 2 | 3, 6 |
| `PARSE_FAILURE` | 2 | 0.5, 1 |
| `NETWORK_ERROR` | 3 | 1, 2, 4 |
| `HTTP_4XX` | 1 | — |
| `SELECTOR_DRIFT` | 1 | — |
| `UNKNOWN` | 2 | 1, 2 |