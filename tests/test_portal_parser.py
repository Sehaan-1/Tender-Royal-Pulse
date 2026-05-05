from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from tender_royal_pulse.portal.eprocure_dom import (
    Attachment,
    PaginationNavigator,
    TenderDetail,
    TenderListing,
    extract_detail_page,
    extract_listing_rows,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "html"


def _read_fixture(filename: str) -> str:
    return (FIXTURES_DIR / filename).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def page() -> Page:
    pw: Playwright = sync_playwright().start()
    browser: Browser = pw.chromium.launch(headless=True)
    p: Page = browser.new_page()
    yield p
    browser.close()
    pw.stop()


def _load_listing_page(page: Page) -> Page:
    page.set_content(_read_fixture("listing_page.html"))
    return page


def _load_detail_page(page: Page) -> Page:
    page.set_content(_read_fixture("detail_page.html"))
    return page


class TestListingExtraction:
    def test_extract_rows_returns_correct_count(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert len(rows) == 5

    def test_extract_rows_sl_no(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert rows[0].sl_no == "1"
        assert rows[4].sl_no == "5"

    def test_extract_rows_published_date(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert rows[0].published_date == "04-May-2026 06:00 PM"
        assert rows[1].published_date == "04-May-2026 05:30 PM"

    def test_extract_rows_closing_date(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert rows[0].closing_date == "26-May-2026 06:00 PM"
        assert rows[1].closing_date == "20-May-2026 03:00 PM"

    def test_extract_rows_opening_date(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert rows[0].opening_date == "27-May-2026 03:00 PM"
        assert rows[1].opening_date == "21-May-2026 11:00 AM"

    def test_extract_rows_title_ref(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert "Supply of Medical Equipment for ICU Ward" in (rows[0].title_ref or "")
        assert rows[0].tender_id == "2026_AIMSD_897626_1"

    def test_extract_rows_org_chain(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert rows[0].org_chain == "DGAFMS-MOD||DGAFMS||AIIMS-Delhi||Medical Store"
        assert rows[1].org_chain == "RITES-LTD||Engineering Division||Civil Works"

    def test_extract_rows_detail_url(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert rows[0].detail_url is not None
        assert rows[0].detail_url.startswith("https://eprocure.gov.in")

    def test_extract_rows_returns_listings(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        for row in rows:
            assert isinstance(row, TenderListing)

    def test_to_dict_produces_expected_keys(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        d = rows[0].to_dict()
        assert set(d.keys()) == {
            "sl_no", "published_date", "closing_date", "opening_date",
            "title_ref", "org_chain", "tender_id", "detail_url",
        }


class TestPaginationNavigation:
    def test_has_next_returns_true_when_next_available(self, page):
        _load_listing_page(page)
        nav = PaginationNavigator(page)
        assert nav.has_next() is True

    def test_has_next_returns_false_when_next_hidden(self, page):
        page.set_content("""
            <span id="informal_pag">
                <a id="linkFwd" style="display:none">Next</a>
            </span>
        """)
        nav = PaginationNavigator(page)
        assert nav.has_next() is False


class TestDetailExtraction:
    def test_extract_detail_tender_id(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert detail.tender_id == "2026_AIMSD_897626_1"

    def test_extract_detail_reference_number(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert detail.reference_number == "2026_AIMSD_897626_1"

    def test_extract_detail_org_chain(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert detail.org_chain == "DGAFMS-MOD||DGAFMS||AIIMS-Delhi||Medical Store"

    def test_extract_detail_tender_type(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert detail.tender_type == "Open Tender"

    def test_extract_detail_category(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert detail.category == "Goods"

    def test_extract_detail_tender_title(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert detail.tender_title == "Supply of Medical Equipment for ICU Ward"

    def test_extract_detail_returns_tender_detail(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert isinstance(detail, TenderDetail)

    def test_extract_detail_attachments_count(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert len(detail.attachments) == 3

    def test_extract_detail_attachments_have_filenames(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        filenames = [a.filename for a in detail.attachments]
        assert "tender_document_1.pdf" in filenames
        assert "boq_schedule.xlsx" in filenames
        assert "technical_specs.pdf" in filenames

    def test_extract_detail_attachments_have_doc_types(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        doc_types = [a.doc_type for a in detail.attachments]
        assert "Tender Document" in doc_types
        assert "BOQ" in doc_types
        assert "Technical Specification" in doc_types

    def test_attachment_to_dict(self):
        att = Attachment(filename="test.pdf", doc_type="Type A", description="Desc")
        d = att.to_dict()
        assert d == {"filename": "test.pdf", "doc_type": "Type A", "description": "Desc"}

    def test_tender_detail_to_dict_includes_attachments(self):
        detail = TenderDetail(
            tender_id="2026_X_Y_1",
            tender_type="Open",
            attachments=[Attachment(filename="f1.pdf", doc_type="Tender")],
        )
        d = detail.to_dict()
        assert d["tender_id"] == "2026_X_Y_1"
        assert len(d["attachments"]) == 1
        assert d["attachments"][0]["filename"] == "f1.pdf"
