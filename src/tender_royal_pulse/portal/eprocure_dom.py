from __future__ import annotations

import re

from playwright.sync_api import Locator, Page

from tender_royal_pulse.models import Attachment, Tender

ROWS_SELECTOR = "table.list_table tr.even, table.list_table tr.odd"
PAGINATION_CONTAINER_SELECTOR = 'span[id^="informal_"]'
NEXT_BUTTON_SELECTOR = 'a[id="linkFwd"]'
CLOSING_7DAYS_SELECTOR = 'a[id="LinkSubmit_0"]'
CLOSING_TODAY_SELECTOR = 'a[id="tabByClosingToday"]'
PAGE_CONTENT_SELECTOR = "td.page_content, div.page_content"


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def row_locators(page: Page) -> list[Locator]:
    return page.locator(ROWS_SELECTOR).all()


def extract_listing_rows(page: Page) -> list[Tender]:
    results: list[Tender] = []
    rows = row_locators(page)
    for row in rows:
        tender = _parse_listing_row(row)
        results.append(tender)
    return results


def _parse_listing_row(row: Locator) -> Tender:
    cells = row.locator("td").all()
    total = len(cells)

    sl_no = _cell_text(cells[0]) if total > 0 else None
    sl_no = sl_no.strip().rstrip(".") if sl_no else None
    published_date = _cell_text(cells[1]) if total > 1 else None
    closing_date = _cell_text(cells[2]) if total > 2 else None
    opening_date = _cell_text(cells[3]) if total > 3 else None
    title_ref_raw = _cell_text(cells[4]) if total > 4 else None
    org_chain = _cell_text(cells[5]) if total > 5 else None

    title_text = title_ref_raw.strip() if title_ref_raw else None
    tender_id: str | None = None
    title: str | None = None
    if title_text:
        id_match = re.search(r"\[([A-Za-z0-9_]+)\]$", title_text)
        if id_match:
            tender_id = id_match.group(1)
            title = title_text[: id_match.start()].strip()
        else:
            title = title_text

    detail_url: str | None = None
    if total > 4:
        link = cells[4].locator("a").first
        try:
            href = link.get_attribute("href", timeout=1000)
            if href and not href.startswith("http"):
                detail_url = (
                    "https://eprocure.gov.in" + href
                    if href.startswith("/")
                    else "https://eprocure.gov.in/eprocure/" + href
                )
            else:
                detail_url = href or None
        except Exception:
            detail_url = None

    return Tender(
        tender_id=tender_id or "",
        title=title,
        published_date=published_date.strip() if published_date else None,  # type: ignore[arg-type]
        closing_date=closing_date.strip() if closing_date else None,  # type: ignore[arg-type]
        opening_date=opening_date.strip() if opening_date else None,  # type: ignore[arg-type]
        org_chain=org_chain.strip() if org_chain else None,
        detail_url=detail_url,
    )


def _cell_text(cell: Locator) -> str:
    try:
        raw = cell.inner_text(timeout=1000)
        return _clean_text(raw) if raw else ""
    except Exception:
        return ""


def wait_for_rows(page: Page, timeout_ms: int = 30000) -> None:
    page.wait_for_selector(ROWS_SELECTOR, timeout=timeout_ms)


def _content_area(page: Page) -> Locator:
    content = page.locator(PAGE_CONTENT_SELECTOR).first
    try:
        if content.is_visible():
            return content
    except Exception:
        pass
    return page.locator("body")


def extract_detail_page(page: Page) -> Tender:
    page.wait_for_selector("table", timeout=15000)
    content = _content_area(page)

    try:
        page_text = content.inner_text(timeout=3000)
    except Exception:
        page_text = ""

    tender_id = _regex_find(page_text, r"Tender ID\s+(\S+)")
    if not tender_id:
        tender_id = _extract_field_by_label(content, "Tender ID")

    reference_number = _regex_find(
        page_text, r"Tender Reference Number\s+(.+?)\s+Tender ID"
    )
    if not reference_number:
        reference_number = _extract_field_by_label(content, "Tender Reference Number")

    org_chain = _regex_find(
        page_text, r"Organisation Chain\s+(.+?)\s+Tender Reference Number"
    )
    if not org_chain:
        org_chain = _extract_field_by_label(content, "Organisation Chain")

    tender_type = _regex_find(
        page_text, r"Tender Type\s+(.+?)\s+Form Of Contract"
    )
    if not tender_type:
        tender_type = _extract_field_by_label(content, "Tender Type")

    category = _regex_find(
        page_text, r"Tender Category\s+(.+?)\s+No\. of Covers"
    )
    if not category:
        category = _extract_field_by_label(content, "Tender Category")

    title = _regex_find(
        page_text, r"Title\s+(.+?)\s+Work Description"
    )
    if not title:
        title = _extract_field_by_label(content, "Title")

    tender_value = _regex_find(page_text, r"Tender Value in \S+\s+(\S+)")
    if not tender_value:
        tender_value = _regex_find(page_text, r"Tender Value\s+([\d,]+)")
    if not tender_value:
        tender_value = _extract_field_by_label(content, "Tender Value")

    emd_amount = _regex_find(page_text, r"EMD Amount in \S+\s+([\d,]+)")
    if not emd_amount:
        emd_amount = _extract_field_by_label(content, "EMD Amount")

    doc_fee = _regex_find(page_text, r"Tender Fee in \S+\s+([\d,]+)")
    if not doc_fee:
        doc_fee = _regex_find(page_text, r"Tender Fee\s+([\d,]+)")
    if not doc_fee:
        doc_fee = _extract_field_by_label(content, "Document Fee")

    attachment_section = _regex_find(
        page_text,
        r"Work Item Documents\s+(.+?)(?:Critical Dates|Tender Inviting Authority)",
    )
    if attachment_section:
        attachments = _parse_attachment_text(attachment_section)
    else:
        attachments = _extract_attachments(content)

    return Tender(
        tender_id=tender_id or "",
        title=title,
        reference_number=reference_number,
        org_chain=org_chain,
        tender_type=tender_type,
        category=category,
        tender_value=tender_value,  # type: ignore[arg-type]
        emd_amount=emd_amount,  # type: ignore[arg-type]
        doc_fee=doc_fee,  # type: ignore[arg-type]
        attachments=attachments,
    )


def _regex_find(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _parse_attachment_text(text: str) -> list[Attachment]:
    attachments: list[Attachment] = []
    rows = text.split("\n")
    for row in rows:
        row = row.strip()
        if not row:
            continue
        parts = re.split(r"\s{2,}", row)
        if len(parts) >= 2:
            potential_file = parts[-1] or parts[-2] if len(parts) >= 2 else ""
            if "." in potential_file and not potential_file.startswith("S.No"):
                doc_type = parts[1] if len(parts) > 2 else None
                attachments.append(
                    Attachment(filename=potential_file, doc_type=doc_type)
                )
    return attachments


def _extract_field_by_label(scope: Page | Locator, label: str) -> str | None:
    try:
        rows = scope.locator("table tr").all()
        label_lower = label.lower()
        for row in rows:
            cells = row.locator("td").all()
            if len(cells) < 2:
                continue
            first_text = (
                cells[0].inner_text(timeout=500).strip().rstrip(":").lstrip("*").strip()
            )
            if label_lower in first_text.lower():
                try:
                    raw = cells[1].evaluate(
                        "el => { let t = ''; for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; if (n.nodeType === 1 && n.tagName !== 'TABLE') { for (const c of n.childNodes) { if (c.nodeType === 3) t += c.textContent; } break; } } return t.trim(); }"
                    )
                    if raw:
                        return _clean_text(raw)
                except Exception:
                    pass
                value = cells[1].inner_text(timeout=500).strip()
                return _clean_text(value) if value else None
    except Exception:
        pass
    return None


def _direct_text(cell: Locator) -> str:
    try:
        result: str | None = cell.evaluate(
            "el => { let t = ''; for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; } return t.trim(); }"
        )
        if result:
            return result
    except Exception:
        pass
    return cell.inner_text(timeout=500).strip()


def _extract_attachments(scope: Locator) -> list[Attachment]:
    attachments: list[Attachment] = []
    try:
        attachment_tables = scope.locator("table").all()
        for table in attachment_tables:
            rows = table.locator("tr").all()
            header_texts: list[str] = []
            for cell in rows[0].locator("td,th").all() if rows else []:
                header_texts.append(_clean_text(cell.inner_text(timeout=500).lower()))

            filename_idx = _find_header_index(
                header_texts, "file name", "document name", "attachment", "title"
            )
            doctype_idx = _find_header_index(
                header_texts, "document type", "type", "category"
            )
            desc_idx = _find_header_index(header_texts, "description", "details")

            if filename_idx is None:
                continue

            for row in rows[1:]:
                cells = row.locator("td,th").all()
                if not cells:
                    continue
                filename = _get_cell_safe(cells, filename_idx)
                if not filename:
                    continue
                attachments.append(
                    Attachment(
                        filename=filename,
                        doc_type=_get_cell_safe(cells, doctype_idx),
                        description=_get_cell_safe(cells, desc_idx),
                    )
                )
            if attachments:
                break
    except Exception:
        pass
    return attachments


def _find_header_index(headers: list[str], *keywords: str) -> int | None:
    for i, h in enumerate(headers):
        h_lower = h.lower()
        for kw in keywords:
            if kw.lower() in h_lower:
                return i
    return None


def _get_cell_safe(cells: list[Locator], idx: int | None) -> str | None:
    if idx is None or idx >= len(cells):
        return None
    try:
        val = cells[idx].inner_text(timeout=500).strip()
        return _clean_text(val) if val else None
    except Exception:
        return None


class PaginationNavigator:

    def __init__(self, page: Page) -> None:
        self._page = page

    def has_next(self) -> bool:
        try:
            container = self._page.locator(PAGINATION_CONTAINER_SELECTOR).first
            next_btn = container.locator(NEXT_BUTTON_SELECTOR).first
            if not next_btn.is_visible(timeout=2000):
                return False
            disabled = next_btn.get_attribute("disabled")
            if disabled is not None:
                return False
            style = next_btn.get_attribute("style") or ""
            if "hidden" in style.lower() or "none" in style.lower():
                return False
            onclick = next_btn.get_attribute("onclick") or ""
            if onclick.strip():
                return True
            classes = (next_btn.get_attribute("class") or "").lower()
            if "disabled" in classes:
                return False
            return True
        except Exception:
            return False

    def go_next(self) -> bool:
        try:
            current_sn = self._current_first_sl_no()
            container = self._page.locator(PAGINATION_CONTAINER_SELECTOR).first
            next_btn = container.locator(NEXT_BUTTON_SELECTOR).first
            next_btn.click()
            self._page.wait_for_timeout(500)
            for _ in range(30):
                new_sn = self._current_first_sl_no()
                if new_sn and new_sn != current_sn:
                    return True
                self._page.wait_for_timeout(500)
            return True
        except Exception:
            return False

    def _current_first_sl_no(self) -> str | None:
        try:
            first_row = self._page.locator(ROWS_SELECTOR).first
            cells = first_row.locator("td").all()
            if cells:
                return _cell_text(cells[0])
        except Exception:
            pass
        return None
