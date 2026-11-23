from __future__ import annotations

import csv
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def seed_database_from_samples(db_path: Path | str) -> int:
    """Populate database with sample tenders if empty or requested."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Ensure schema is initialized
    from tender_royal_pulse.cli_helpers import resolve_db
    conn.close()
    conn = resolve_db(Path(db_path))

    now = datetime.now(UTC).isoformat()
    inserted = 0

    base_path = Path(__file__).resolve().parent.parent.parent.parent
    smoke_csv = base_path / "samples" / "sample_outputs" / "phase2_live_smoke" / "tenders.csv"
    main_csv = base_path / "samples" / "sample_outputs" / "main_dataset" / "tenders.csv"

    # 1. Seed phase2 live smoke tenders
    if smoke_csv.exists():
        with open(smoke_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                tid = r.get("tender_id") or "UNK"
                title = r.get("tender_title") or r.get("title_ref") or "Untitled Tender"
                ref = r.get("reference_number")
                org = r.get("org_chain")
                ttype = r.get("tender_type") or "Open Tender"
                cat = r.get("category") or "Works"
                val = float(r["tender_value"]) if r.get("tender_value") and r["tender_value"].replace(".", "", 1).isdigit() else None
                emd = float(r["emd_amount"]) if r.get("emd_amount") and r["emd_amount"].replace(".", "", 1).isdigit() else None
                doc = float(r["doc_fee"]) if r.get("doc_fee") and r["doc_fee"].replace(".", "", 1).isdigit() else None
                cdate = r.get("closing_date")
                odate = r.get("opening_date")
                pdate = r.get("published_date")
                durl = r.get("detail_url")

                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO tenders (
                        source, tender_id, title, reference_number, org_chain,
                        tender_type, category, tender_value, emd_amount, doc_fee,
                        closing_date, opening_date, published_date, detail_url,
                        raw_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("eprocure", tid, title, ref, org, ttype, cat, val, emd, doc, cdate, odate, pdate, durl, json.dumps(r), now, now),
                )
                if cursor.rowcount > 0:
                    inserted += 1

    # 2. Seed main mock dataset tenders
    if main_csv.exists():
        with open(main_csv, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            categories = ["Works", "Goods", "Services", "Consultancy"]
            for idx, r in enumerate(reader):
                tid = r.get("tender_id") or f"TEND-{idx+1000}"
                title = r.get("title") or "Untitled Tender"
                org = r.get("org_chain")
                val = float(r["value"]) if r.get("value") and r["value"].replace(".", "", 1).isdigit() else None
                cdate = r.get("closing_date")
                pdate = r.get("publish_date")
                ttype = "Open Tender"
                cat = categories[idx % len(categories)]
                ref = f"GEM/2026/B/{100000 + idx}"

                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO tenders (
                        source, tender_id, title, reference_number, org_chain,
                        tender_type, category, tender_value, emd_amount, doc_fee,
                        closing_date, opening_date, published_date, detail_url,
                        raw_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("eprocure", tid, title, ref, org, ttype, cat, val, round((val or 100000) * 0.02, 2) if val else None, 1000.0, cdate, None, pdate, f"https://eprocure.gov.in/eprocure/app?page=FrontEndTenderDetails&tenderId={tid}", json.dumps(r), now, now),
                )
                if cursor.rowcount > 0:
                    inserted += 1

    conn.commit()
    conn.close()
    return inserted


if __name__ == "__main__":
    count = seed_database_from_samples("data/tenderpulse.db")
    print(f"Seeded {count} tenders into database.")
