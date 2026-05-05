# Data Contract

## Task State Machine

```
PENDING → RUNNING → DONE
              ↓
        FAILED_RETRYABLE → RUNNING (retry)
              ↓
        FAILED_PERMANENT
              ↓
             STALE → RUNNING (recover)
              ↓
            SKIPPED
```

### State Definitions

| State | Description | Can Transition To |
|-------|-------------|-------------------|
| PENDING | Not yet started | RUNNING |
| RUNNING | Currently processing | DONE, FAILED_RETRYABLE, FAILED_PERMANENT, STALE |
| DONE | Successfully completed | - |
| FAILED_RETRYABLE | Failed but recoverable (network timeout, rate limit) | RUNNING (retry), FAILED_PERMANENT (max retries) |
| FAILED_PERMANENT | Failed with no recovery path (invalid input, auth failure) | - |
| STALE | Session expired during processing | RUNNING (recover) |
| SKIPPED | Skipped by user or dedup logic | - |

### Resume Semantics

- **Same filters only**: Resume uses identical filter criteria as original run
- **Skip completed/permanent**: Tasks already DONE or FAILED_PERMANENT are skipped
- **Stale recovery**: STALE tasks are retried with fresh session
- **At-least-once**: May re-fetch already DONE items if checkpoint corrupted

## Task Types

### 1. ListingFetchTask

Fetches tender listing pages.

**Required payload fields:**
```python
{
    "task_type": "listing_fetch",
    "filters": {
        "date_from": "YYYY-MM-DD",
        "date_to": "YYYY-MM-DD",
        "tender_type": "all" | "debug" | "fresh",
    },
    "page_number": int,
    "session_context": SessionContext,
}
```

### 2. DetailFetchTask

Fetches individual tender detail page.

**Required payload fields:**
```python
{
    "task_type": "detail_fetch",
    "tender_id": str,  # durable key
    "direct_link": str,  # ephemeral, for debug only
    "session_context": SessionContext,
}
```

### 3. ExportTask

Exports collected data to file.

**Required payload fields:**
```python
{
    "task_type": "export",
    "output_path": str,
    "format": "csv" | "jsonl",
    "records": list[TenderRecord],
}
```

## SessionContext Schema

```python
class SessionContext(BaseModel):
    version: int = 1
    storage_state: dict | None = None
    user_agent: str | None = None
    created_at: datetime | None = None

    class Config:
        extra = "forbid"
```

**Schema versioning**: `version` field enables future schema migrations.

## TenderRecord Schema

```python
class TenderRecord(BaseModel):
    tender_id: str  # durable key
    title: str
    closing_date: str | None
    opening_date: str | None
    direct_link: str | None = None  # ephemeral, debug only
    fetched_at: datetime

    class Config:
        extra = "forbid"
```

## Database Schema

### tasks table

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT PRIMARY KEY | UUID |
| task_type | TEXT | listing_fetch, detail_fetch, export |
| state | TEXT | PENDING, RUNNING, DONE, etc. |
| payload | TEXT | JSON-encoded task payload |
| attempt | INTEGER | retry attempt number |
| error_message | TEXT | last error if failed |
| created_at | TEXT | ISO timestamp |
| updated_at | TEXT | ISO timestamp |

### tenders table

| Column | Type | Description |
|--------|------|-------------|
| tender_id | TEXT PRIMARY KEY | durable key |
| title | TEXT | tender title |
| closing_date | TEXT | closing date |
| opening_date | TEXT | opening date |
| direct_link | TEXT | session-bound URL (ephemeral) |
| fetched_at | TEXT | ISO timestamp |

## Retry Policy

- **Max attempts**: 3 for FAILED_RETRYABLE
- **Backoff**: exponential, 1s, 2s, 4s
- **Retryable errors**: timeout, 429, 503, network error
- **Permanent errors**: 401 (auth), 400 (bad request), invalid input

## Event Log Schema

| Field | Type | Description |
|-------|------|-------------|
| timestamp | TEXT | ISO timestamp |
| task_id | TEXT | task UUID |
| event | TEXT | started, completed, failed, retried |
| details | TEXT | JSON metadata |