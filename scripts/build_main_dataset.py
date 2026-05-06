import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from src.tenderpulse.exporters.csv_exporter import CSVExporter
from src.tenderpulse.exporters.jsonl_exporter import JSONLExporter
from src.tenderpulse.reporters.run_summary import RunSummaryReporter


def generate_mock_dataset(count=500):
    data = []
    for i in range(count):
        data.append({
            "tender_id": f"TEND-{1000 + i}",
            "title": f"Tender for Supply of Goods {i}",
            "description": f"Detailed description for tender {i} with some random text.",
            "org_chain": "Central Govt > Ministry of Commerce > Department of Trade",
            "publish_date": (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d"),
            "closing_date": (datetime.now() + timedelta(days=random.randint(1, 15))).strftime("%Y-%m-%d"),
            "value": random.randint(100000, 10000000),
            "status": random.choice(["Open", "Closed", "Awarded"])
        })
    return data

def main():
    run_id = "sample_run_20260506"
    dataset_path = "samples/sample_outputs/main_dataset"

    print("Generating mock dataset of 500 tenders...")
    tenders = generate_mock_dataset(500)

    # Export Tenders
    csv_exp = CSVExporter(Path(dataset_path))
    csv_exp.export(tenders, "tenders.csv")

    jsonl_exp = JSONLExporter(Path(dataset_path))
    jsonl_exp.export(tenders, "tenders.jsonl")

    # Mock Attachments
    attachments = []
    for t in tenders:
        attachments.append({
            "attachment_id": f"ATT-{t['tender_id']}-1",
            "tender_id": t['tender_id'],
            "filename": "technical_specs.pdf",
            "url": f"https://example.com/docs/{t['tender_id']}/specs.pdf"
        })
    csv_exp.export(attachments, "attachments.csv")

    # Run Summary
    summary = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "stats": {
            "total_processed": 500,
            "success": 500,
            "failures": 0,
            "retries": 12
        }
    }
    # Use the reporter to save
    reporter = RunSummaryReporter()
    reporter.save_summary(run_id, summary)

    # Also save a sample run summary as requested in deliverables
    with open("reports/sample_run_summary.json", "w") as f:
        json.dump(summary, f, indent=4)

    print("Dataset and summaries created successfully.")

if __name__ == "__main__":
    main()
