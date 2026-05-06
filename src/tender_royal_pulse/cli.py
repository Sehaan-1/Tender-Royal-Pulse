from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from tender_royal_pulse.cli_helpers import build_row_processor, load_input_json, resolve_db
from tender_royal_pulse.crawler import (
    CrawlEngine,
    ListPagePayload,
    create_run,
    create_tasks,
)
from tender_royal_pulse.exporters import CSVExporter, JSONLExporter

app = typer.Typer(name="tender_royal_pulse", help="eProcure tender crawler with crash recovery")
console = Console()


def _build_page_payloads(input_data: dict[str, Any], limit: int | None) -> list[ListPagePayload]:
    filters = input_data["filters"]
    max_pages = limit if limit is not None else 10
    date_filter = f"{filters['date_from']},{filters['date_to']}"

    payloads: list[ListPagePayload] = []
    for i in range(1, max_pages + 1):
        payloads.append(ListPagePayload(
            mode="closing_today",
            page_index=i,
            date_filter=date_filter,
        ))
    return payloads


@app.command()
def crawl(
    input_path: Path = typer.Option(..., "--input", "-i", help="Input JSON file with filters"),
    db_path: Path = typer.Option(..., "--db", "-d", help="SQLite database path for state"),
    output_path: Path | None = typer.Option(None, "--output", "-o", help="Output file path after crawl"),
    format: str = typer.Option("jsonl", "--format", "-f", help="Output format: csv or jsonl"),
    limit: int | None = typer.Option(None, "--limit", help="Limit number of pages to process"),
) -> None:
    input_data = load_input_json(input_path)

    conn = resolve_db(db_path)
    run_id = create_run(conn)
    session_context = input_data.get("session_context")
    session_context_json = json.dumps(session_context) if session_context else None

    payloads = _build_page_payloads(input_data, limit)
    tasks = create_tasks(conn, run_id, payloads, session_context_json)
    conn.close()

    engine = CrawlEngine(str(db_path), row_processor=build_row_processor("mock"))
    processed = engine.process_run(run_id)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    tender_count = conn.execute("SELECT COUNT(*) as cnt FROM tenders").fetchone()["cnt"]
    conn.close()

    table = Table(title="Crawl Summary")
    table.add_column("Run ID", style="cyan", no_wrap=True)
    table.add_column("Pages", justify="right")
    table.add_column("Tasks", justify="right")
    table.add_column("Tenders", justify="right", style="green")
    table.add_row(run_id[:8], str(processed), str(len(tasks)), str(tender_count))
    console.print(table)

    if output_path:
        _do_export(db_path, output_path, format)


@app.command()
def export(
    db_path: Path = typer.Option(..., "--db", "-d", help="SQLite database path"),
    output_path: Path = typer.Option(..., "--output", "-o", help="Output file path"),
    format: str = typer.Option("jsonl", "--format", "-f", help="Output format: csv or jsonl"),
) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM tenders ORDER BY created_at DESC").fetchall()
    conn.close()

    records: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = dict(row)
        for key, value in record.items():
            if isinstance(value, Decimal):
                record[key] = str(value)
            elif isinstance(value, datetime):
                record[key] = value.isoformat()
        if "id" in record:
            del record["id"]
        records.append(record)

    exporter = CSVExporter(str(output_path.parent)) if format == "csv" else JSONLExporter(str(output_path.parent))
    exporter.export(records, output_path.name)
    console.print(f"[green]Exported {len(records)} records to {output_path}[/green]")


@app.command()
def status(
    db_path: Path = typer.Option(..., "--db", "-d", help="SQLite database path"),
) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    runs = conn.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 5").fetchall()
    conn.close()

    if not runs:
        console.print("[yellow]No runs found in database[/yellow]")
        return

    table = Table(title="Recent Crawl Runs")
    table.add_column("Run ID", style="cyan", no_wrap=True)
    table.add_column("Status", style="green")
    table.add_column("Started", style="dim")
    table.add_column("Total", justify="right")
    table.add_column("Done", justify="right", style="green")
    table.add_column("Pending", justify="right", style="yellow")
    table.add_column("Failed", justify="right", style="red")

    for run in runs:
        run_id = run["id"]
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        task_counts = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM tasks WHERE run_id = ? GROUP BY status",
            (run_id,),
        ).fetchall()
        conn.close()

        counts: dict[str, int] = {"PENDING": 0, "RUNNING": 0, "DONE": 0, "FAILED_RETRYABLE": 0, "FAILED_PERMANENT": 0}
        for row in task_counts:
            counts[row["status"]] = row["cnt"]

        total = sum(counts.values())
        done = counts["DONE"]
        pending = counts["PENDING"]
        failed = counts["FAILED_RETRYABLE"] + counts["FAILED_PERMANENT"]

        table.add_row(
            run_id[:8],
            run["status"],
            run["created_at"][:19],
            str(total),
            str(done),
            str(pending),
            str(failed),
        )

    console.print(table)


def _do_export(db_path: Path, output_path: Path, format: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM tenders ORDER BY created_at DESC").fetchall()
    conn.close()

    records: list[dict[str, Any]] = []
    for row in rows:
        record: dict[str, Any] = dict(row)
        for key, value in record.items():
            if isinstance(value, Decimal):
                record[key] = str(value)
            elif isinstance(value, datetime):
                record[key] = value.isoformat()
        if "id" in record:
            del record["id"]
        records.append(record)

    exporter = CSVExporter(str(output_path.parent)) if format == "csv" else JSONLExporter(str(output_path.parent))
    exporter.export(records, output_path.name)
    console.print(f"[green]Exported {len(records)} records to {output_path}[/green]")


if __name__ == "__main__":
    app()
