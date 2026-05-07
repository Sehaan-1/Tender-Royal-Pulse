# Test Plan

## Test Categories

### 1. Unit Tests (`tests/unit/`)

Fast tests — no browser, no SQLite file I/O.

| File | Coverage |
|------|----------|
| `test_error_classifier.py` | 9-bucket error classification (`ErrorClass` enum + `classify_error()`) |
| `test_models_invariants.py` | `Tender` / `Attachment` Pydantic v2 field constraints and normalization |
| `test_normalization_dates.py` | `parse_date()`, `parse_datetime()` — Indian date format handling |
| `test_normalization_money.py` | `parse_indian_money()` — ₹/Rs/INR, lakh/crore grouping → `Decimal` |
| `test_queue.py` | SQLite task queue: create/claim/done/failed state transitions, heartbeat update, stale recovery |
| `test_retry_policy.py` | Backoff schedules, max-attempts enforcement, retryable vs permanent classification |
| `test_heartbeat.py` | Heartbeat liveness writes & stale detectability |
| `test_sigterm_shutdown.py` | Graceful SIGTERM handling in CrawlEngine |
| `test_stale_recovery.py` | Stale task reset & recovery logic |
| `test_state_transitions.py` | Task state machine transitions |

### 2. Top-level Unit Tests (`tests/`)

| File | Coverage |
|------|----------|
| `test_exporters.py` | `CSVExporter` (comma/quote/newline escaping) and `JSONLExporter` (line-per-record validity) |
| `test_migrations.py` | Schema migration runner — bootstrap, indexes, TEXT→REAL cast, idempotency |
| `test_state_machine.py` | `SessionContext`: default version, nullable storage, `to_playwright_storage_state()`, `from_playwright_storage_state()` |

### 3. Integration Tests (`tests/integration/`)

Require SQLite (no browser required to run).

| File | Coverage |
|------|----------|
| `test_crash_recovery.py` | Stale task detection & recovery, idempotent upsert, full crash-recovery E2E flow, engine re-queue |

### 4. Portal Parser Tests (`tests/test_portal_parser.py`)

Marked `@pytest.mark.integration`. Require **Playwright** + HTML fixtures in `tests/fixtures/html/`.

| Test Class | Coverage |
|------------|----------|
| `TestListingExtraction` | `extract_listing_rows()`: row count, `tender_id`, `published_date`, `title`, `org_chain`, `detail_url` |
| `TestPaginationNavigation` | `PaginationNavigator.has_next()` |
| `TestDetailExtraction` | `extract_detail_page()`: `tender_id`, `reference_number`, title, attachment count |

---

## Test Fixtures

| Path | Purpose |
|------|---------|
| `tests/fixtures/html/listing_page.html` | Sample eProcure listing page (5 rows) for DOM extraction tests |
| `tests/fixtures/html/detail_page.html` | Sample eProcure detail page for `extract_detail_page()` tests |

---

## Running Tests

```bash
# Unit tests only (fast, default CI run)
pytest -m "not integration" -q

# All unit tests with coverage
make test
# equivalent: pytest --cov=src --cov-report=term-missing --cov-report=xml -q

# Integration tests (SQLite, no browser)
make test-integration
# equivalent: pytest tests/integration/ -v

# Portal parser tests (requires Playwright)
pytest tests/test_portal_parser.py -v

# Skip Playwright tests via env flag
SKIP_PLAYWRIGHT_TESTS=1 pytest tests/test_portal_parser.py -v

# Full verbose suite
make test-all
```

---

## CI Gate

All of the following must pass before merging:

1. `ruff check src tests` — linting (E, F, I, N, W, UP rules)
2. `mypy src/` — strict type checking (`--strict`)
3. `pytest -m "not integration" -q` — unit tests (fast, no browser)

Integration tests run separately and may require Playwright installation.