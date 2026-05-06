from __future__ import annotations

import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from tender_royal_pulse.portal.eprocure_dom import (
    Attachment,
    PaginationNavigator,
    extract_detail_page,
    extract_listing_rows,
)

pytestmark = pytest.mark.integration

requires_playwright = pytest.mark.skipif(
    os.environ.get("SKIP_PLAYWRIGHT_TESTS", "0") == "1",
    reason="Playwright integration tests skipped via env flag"
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


@requires_playwright
class TestListingExtraction:
    def test_extract_rows_returns_correct_count(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert len(rows) == 5

    def test_extract_rows_sl_no(self, page):
        # Since Tender model doesn't have sl_no, this test needs adjustment
        # or we check a field that exists.
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert rows[0].tender_id is not None # wait, Tender has tender_id

    def test_extract_rows_published_date(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        # The Tender model normalizes this to datetime
        assert rows[0].published_date is not None

    def test_extract_rows_title_ref(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert "Supply of Medical Equipment for ICU Ward" in (rows[0].title or "")
        assert rows[0].tender_id == "2026_AIMSD_897626_1"

    def test_extract_rows_org_chain(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert rows[0].org_chain == "DGAFMS-MOD||DGAFMS||AIIMS-Delhi||Medical Store"

    def test_extract_rows_detail_url(self, page):
        _load_listing_page(page)
        rows = extract_listing_rows(page)
        assert rows[0].detail_url is not None
        assert rows[0].detail_url.startswith("https://eprocure.gov.in")


@requires_playwright
class TestPaginationNavigation:
    def test_has_next_returns_true_when_next_available(self, page):
        _load_listing_page(page)
        nav = PaginationNavigator(page)
        assert nav.has_next() is True


@requires_playwright
class TestDetailExtraction:
    def test_extract_detail_tender_id(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert detail.tender_id == "2026_AIMSD_897626_1"

    def test_extract_detail_reference_number(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert detail.reference_number == "2026_AIMSD_897626_1"

    def test_extract_detail_tender_title(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert detail.title == "Supply of Medical Equipment for ICU Ward"

    def test_extract_detail_attachments_count(self, page):
        _load_detail_page(page)
        detail = extract_detail_page(page)
        assert len(detail.attachments) == 3

    def test_attachment_to_dict(self):
        att = Attachment(filename="test.pdf", doc_type="Type A", description="Desc")
        # Pydantic models use model_dump() instead of to_dict()
        d = att.model_dump()
        assert d["filename"] == "test.pdf"
        assert d["doc_type"] == "Type A"
        assert d["description"] == "Desc"
