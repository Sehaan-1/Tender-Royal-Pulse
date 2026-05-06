from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from tender_royal_pulse.models import Tender, TenderMeta


def test_tender_normalization_logic():
    # Test raw input normalization via Pydantic model_validator
    raw_data = {
        "tender_id": "  TID-123  ",
        "title": "  Medical \n Equipment  ",
        "closing_date": "09-Feb-2026 09:30 AM",
        "tender_value": "₹ 1,23,45,678",
        "emd_amount": "1,00,000",
        "doc_fee": "500",
        "attachments": [
            {"filename": " doc1.pdf ", "doc_type": "Technical"}
        ]
    }
    tender = Tender(**raw_data)

    assert tender.tender_id == "TID-123"
    assert tender.title == "Medical Equipment"
    assert isinstance(tender.closing_date, datetime)
    assert tender.tender_value == Decimal("12345678")
    assert tender.emd_amount == Decimal("100000")
    assert tender.doc_fee == Decimal("500")
    assert tender.attachments[0].filename == "doc1.pdf"

def test_canonical_url_hash_stability():
    # Hash should be stable for same critical components
    t1 = Tender(tender_id="T1", source="src1", title="Title A", org_chain="Org A")
    t2 = Tender(tender_id="T1", source="src1", title="Title A", org_chain="Org A")

    assert t1.canonical_url_hash == t2.canonical_url_hash
    assert len(t1.canonical_url_hash) == 64 # SHA-256

def test_canonical_url_hash_changes_on_id():
    t1 = Tender(tender_id="T1", source="src1")
    t2 = Tender(tender_id="T2", source="src1")
    assert t1.canonical_url_hash != t2.canonical_url_hash

def test_to_csv_row_format():
    meta = TenderMeta(run_id="run-123", fetched_at=datetime.now(UTC))
    tender = Tender(
        tender_id="T1",
        title="Title",
        closing_date=datetime(2026, 1, 1, tzinfo=UTC),
        meta=meta
    )
    row = tender.to_csv_row()
    assert row["tender_id"] == "T1"
    assert "2026-01-01" in row["closing_date"]
    assert row["run_id"] == "run-123"
