"""
Phase 2 Live Smoke Test - Extract real tenders from eprocure.gov.in

Usage:
    python scripts/phase2_smoke.py [--pages 2] [--detail-sample 5]

Exports:
    samples/sample_outputs/phase2_live_smoke/tenders.csv
    samples/sample_outputs/phase2_live_smoke/tenders.jsonl
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from playwright.sync_api import Page, sync_playwright  # noqa: E402

from tender_royal_pulse.models import Tender  # noqa: E402
from tender_royal_pulse.portal.eprocure_dom import (  # noqa: E402
    CLOSING_7DAYS_SELECTOR,
    PaginationNavigator,
    extract_detail_page,
    extract_listing_rows,
    wait_for_rows,
)

LISTING_URL = (
    "https://eprocure.gov.in/eprocure/app?page=FrontEndListTendersbyDate&service=page"
)
OUTPUT_DIR = PROJECT_ROOT / "samples" / "sample_outputs" / "phase2_live_smoke"


def _write_csv(records: list[dict], path: Path) -> None:
    if not records:
        return
    fieldnames = list(records[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def _write_jsonl(records: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _merge_record(listing: Tender, detail: Tender | None) -> dict:
    rec = listing.model_dump()
    if detail:
        det = detail.model_dump()
        rec.update(det)
    return rec


def _fetch_listings(page: Page, max_pages: int) -> list[Tender]:
    all_listings: list[Tender] = []
    nav = PaginationNavigator(page)

    page.goto(LISTING_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)

    try:
        page.wait_for_selector(CLOSING_7DAYS_SELECTOR, timeout=15000)
        page.click(CLOSING_7DAYS_SELECTOR)
        page.wait_for_timeout(5000)
    except Exception:
        pass

    try:
        wait_for_rows(page, timeout_ms=15000)
    except Exception:
        try:
            page.wait_for_selector("table.list_table", timeout=15000)
        except Exception:
            pass

    page.screenshot(path=str(OUTPUT_DIR / "page_screenshot.png"))

    for pg in range(1, max_pages + 1):
        print(f"  Extracting listing page {pg} ...")
        listings = extract_listing_rows(page)
        all_listings.extend(listings)
        print(f"    -> {len(listings)} rows extracted (total: {len(all_listings)})")
        if pg < max_pages and nav.has_next():
            nav.go_next()
        else:
            break

    return all_listings


def _fetch_details(
    page: Page, listings: list[Tender], sample: int
) -> tuple[list[dict], list[Tender]]:
    combined: list[dict] = []
    details: list[Tender] = []

    to_detail = listings[:sample]

    for i, listing in enumerate(to_detail):
        url = listing.detail_url
        if not url:
            combined.append(_merge_record(listing, None))
            continue

        print(f"  [{i+1}/{sample}] Fetching detail: {listing.title[:60] if listing.title else 'N/A'} ...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)
            detail = extract_detail_page(page)
            details.append(detail)
            combined.append(_merge_record(listing, detail))
            tid = detail.tender_id or listing.tender_id or "?"
            print(f"           tender_id={tid}")
        except Exception as exc:
            print(f"           FAILED: {type(exc).__name__}")
            combined.append(_merge_record(listing, None))
        time.sleep(1)

    for listing in listings[sample:]:
        combined.append(_merge_record(listing, None))
        details.append(Tender(tender_id=""))

    return combined, details


def run_smoke(max_pages: int = 2, detail_sample: int = 5) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Phase 2 Live Smoke: {max_pages} page(s), {detail_sample} detail sample(s)")
    print(f"Output: {OUTPUT_DIR}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            print("[1] Fetching listing pages ...")
            listings = _fetch_listings(page, max_pages)
            print(f"    Total listings: {len(listings)}\n")

            if not listings:
                print("ERROR: No listings extracted. Aborting.")
                browser.close()
                return

            print(f"[2] Fetching detail pages (sample={detail_sample}) ...")
            combined, details = _fetch_details(page, listings, detail_sample)

            detail_with_id = [
                d for d in details if d.tender_id
            ]
            listing_with_id = [listing for listing in listings if listing.tender_id]
            print(f"\n    Detail success: {len(detail_with_id)}/{min(len(listings), detail_sample)}")
            print(f"    Listings with tender_id: {len(listing_with_id)}/{len(listings)}")

            csv_path = OUTPUT_DIR / "tenders.csv"
            jsonl_path = OUTPUT_DIR / "tenders.jsonl"
            _write_csv(combined, csv_path)
            _write_jsonl(combined, jsonl_path)
            print(f"\n[3] Exported: {csv_path} ({len(combined)} records)")
            print(f"    Exported: {jsonl_path} ({len(combined)} records)")

            sample_ids = [listing.tender_id for listing in listings[:5] if listing.tender_id]
            print("\n[4] Summary:")
            print(f"    Listings: {len(listings)}")
            print(f"    With tender_id: {len(listing_with_id)}")
            print(f"    Details attempted: {min(len(listings), detail_sample)}")
            print(f"    Details with tender_id: {len(detail_with_id)}")
            if sample_ids:
                print(f"    Sample tender_ids: {sample_ids}")

        finally:
            browser.close()

    print("\nDone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 2 Live Smoke Test")
    parser.add_argument("--pages", type=int, default=2)
    parser.add_argument("--detail-sample", type=int, default=5)
    args = parser.parse_args()
    run_smoke(max_pages=args.pages, detail_sample=args.detail_sample)
