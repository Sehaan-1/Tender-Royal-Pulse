# ADR-0003: Session-Bound URLs; tender_id as Canonical Key

## Status

Accepted

## Date

2026-05-05

## Context

eProcure "DirectLink" URLs contain session tokens (session=T, sp=...). These URLs:
- Expire when session times out
- Are different per login session
- Cannot be stored long-term

We need a durable key for tender identity.

## Decision

1. Use `tender_id` (tender reference number from listing) as canonical key
2. Store `direct_link` as ephemeral data (debug only, not for recovery)
3. On resume, re-run listing pages and dedupe by tender_id

## Consequences

### Positive
- Tender IDs survive session expiry
- Resume doesn't require storing long-lived URLs
- Simpler checkpointing (just store tender_id + metadata)
- Natural deduplication against existing records

### Negative
- Must re-fetch listing pages on resume (more requests)
- DirectLink detail pages not reusable for recovery
- Need to handle tender_id extraction from listing row

### Design Implications

- `DetailFetchTask` still gets direct_link but only for current-session fetch
- On stale session, re-run listing to get fresh tender_ids
- Checkpoint stores: `{tender_id, title, closing_date, opening_date, fetched_at}`
- Never rely on direct_link persisting across restarts

## Related

- ADR-0001: Single worker synchronous
- ADR-0002: Playwright sync DOM fetcher