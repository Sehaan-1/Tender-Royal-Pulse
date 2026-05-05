# ADR-0001: Single Worker Synchronous

## Status

Accepted

## Date

2026-05-05

## Context

We need to decide on the concurrency model for the crawler. Options considered:
- Multi-threaded workers with shared queue
- Async/await with event loop
- Single synchronous worker

## Decision

Use single worker with synchronous execution.

## Consequences

### Positive
- Simpler state management (no race conditions on task queue)
- Easier crash recovery (deterministic state transitions)
- Lower complexity for first ship (correctness > performance)
- Easier debugging (deterministic execution order)
- Playwright sync API fits naturally

### Negative
- Slower than parallel alternatives
- Underutilizes I/O wait time during page loads

### Mitigation
- Future: add workers as needed for Phase 2
- Current: acceptable for initial volume (single procurement portal)

## Related

- ADR-0002: Playwright sync DOM fetcher
- ADR-0003: Session-bound URLs; tender_id as canonical key