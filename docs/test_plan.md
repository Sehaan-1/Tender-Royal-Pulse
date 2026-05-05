# Test Plan

## Test Categories

### 1. Unit Tests

- `tests/test_state_machine.py` - State transitions (PENDING → RUNNING → DONE)
- `tests/test_session_context.py` - SessionContext Pydantic model
- `tests/test_exporters.py` - CSV/JSONL export logic

### 2. Integration Tests

- `tests/integration/test_crash_recovery.py` **(NON-NEGOTIABLE)**
  - Simulates crash mid-crawl
  - Verifies resume picks up from correct position
  - Tests stale session recovery
  - Tests retry policy

### 3. Retry Policy Tests

- `tests/test_retry_policy.py`
  - Exponential backoff timing
  - Max attempts enforcement
  - Retryable vs permanent error classification

### 4. Exporter Tests

- `tests/test_csv_exporter.py`
- `tests/test_jsonl_exporter.py`

## Test Fixtures

- `tests/fixtures/listing_page.html` - Sample listing HTML
- `tests/fixtures/session_storage.json` - Sample storage state

## Running Tests

```bash
# All tests
pytest tests/

# Integration only
pytest tests/integration/

# With coverage
pytest tests/ --cov=tenderpulse
```

## CI Gate

- `ruff check src/ tests/` must pass
- `mypy src/tenderpulse/` must pass
- `pytest tests/` must pass