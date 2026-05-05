# eProcure Portal Analysis

## Overview

This document captures the mechanics of the eProcure tender listing portal based on manual exploration.

## Base URL

```
https://eprocure.gov.in/
```

## Listing Page Structure

### Table Selector

Tender rows are located in:
```css
table#table.list_table tr.even
table#table.list_table tr.odd
```

Each row contains:
- Tender Reference Number
- Title/Description
- Closing Date
- Bid Opening Date
- DirectLink (session-bound URL)

### Pagination

Container ID pattern:
```css
span[id^="informal_"]
```

Navigation elements:
- Next button: `a[id="linkFwd"]`
- Page links: `a[id="linkPage"]`

**Critical**: These IDs repeat across pagination controls. Must scope by container.

### Session Detection

When session expires, page displays:
```
"Your session has timed out."
```

This text indicates the storage state is invalid and needs re-authentication.

## URL Mechanics

### DirectLink URLs

Format: `https://eprocure.gov.in/tenders/...`

Parameters observed:
- `session=T` - session token
- `sp=...` - security parameters

**Ephemeral**: These URLs expire when session expires. Do NOT store as permanent reference.

### Tender ID

The stable, permanent identifier for a tender is the tender reference number (tender_id extracted from listing row). This is the durable key for deduplication.

## Authentication Flow

1. User navigates to eProcure homepage
2. Clicks login, enters credentials
3. Session cookie set
4. Subsequent requests use session cookie
5. Session expires after inactivity (typically 30 min)

## Data Extraction Points

### From Listing Table Row

```python
{
    "tender_id": str,        # from tender reference column
    "title": str,            # from title column
    "closing_date": str,     # from closing date column
    "opening_date": str,    # from bid opening date column
    "direct_link": str,      # from DirectLink column (session-bound)
}
```

### From Detail Page (if needed)

- Full description
- Eligibility criteria
- Document downloads
- Corrigendum history

## Failure Modes

1. **Session Timeout**: Page shows "session timed out" → need to re-authenticate
2. **Page Load Failure**: Network error → retry with backoff
3. **Empty Results**: Filters too restrictive → adjust input
4. **Rate Limiting**: 429 response → backoff and retry

## Verification Commands

Manual verification steps to confirm portal mechanics:

```bash
# 1. Fetch listing page with authenticated session
playwright navigates to listing URL

# 2. Verify rows exist
document.querySelectorAll("table#table.list_table tr.even, tr.odd")

# 3. Verify pagination exists
document.querySelector("a[id='linkFwd']")

# 4. Test session expiry (incognito)
# - Copy DirectLink URL
# - Open in incognito window
# - Should fail or redirect to login

# 5. Test pagination
# - Click "Next"
# - Verify table content changes
```