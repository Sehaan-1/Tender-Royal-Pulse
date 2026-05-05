# ADR-0002: Playwright Sync DOM Fetcher

## Status

Accepted

## Date

2026-05-05

## Context

We need a strategy to fetch and parse tender listing pages from eProcure. Options considered:
- `requests` / `httpx` with static HTML parsing
- Playwright with sync API
- Playwright with async API

eProcure portal renders tenders via JavaScript - static requests won't get the full table.

## Decision

Use Playwright with synchronous API (playwright.sync_playwright).

## Consequences

### Positive
- Executes JavaScript, renders full DOM
- Handles dynamic content, lazy loading
- Can capture console errors for debugging
- Sync API aligns with single-worker decision (ADR-0001)
- Can capture storage_state for session persistence

### Negative
- Heavier than HTTP requests
- Slower startup (browser launch)
- More resource intensive

### Alternatives Rejected

**Static requests (httpx)**: DOM elements like `table#table.list_table` don't exist in raw HTML - JavaScript populates them.

**Playwright async**: Would require async queue, adds complexity. Sync is simpler for single worker.

## Related

- ADR-0001: Single worker synchronous
- ADR-0003: Session-bound URLs; tender_id as canonical key