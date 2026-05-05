import pytest


@pytest.fixture
def sample_tender_record():
    return {
        "tender_id": "2026/TN/001234",
        "title": "Supply of Medical Equipment",
        "closing_date": "2026-06-15",
        "opening_date": "2026-06-16",
        "direct_link": "https://eprocure.gov.in/tenders/...?session=T123",
        "fetched_at": "2026-05-05T10:30:00Z",
    }


@pytest.fixture
def sample_storage_state():
    return {
        "cookies": [
            {"name": "JSESSIONID", "value": "ABC123XYZ", "domain": ".eprocure.gov.in", "path": "/"}
        ],
        "origins": [],
    }
