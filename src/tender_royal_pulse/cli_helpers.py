from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import typer

from tender_royal_pulse.crawler.engine import RowProcessor
from tender_royal_pulse.db.migrations import run_migrations
from tender_royal_pulse.db.schema import initialize_schema


def load_input_json(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data: Any = json.load(f)

    if "filters" not in data:
        typer.echo("Error: 'filters' key is required in input JSON", err=True)
        raise typer.Exit(code=1)

    filters = data["filters"]
    required_filters = ["date_from", "date_to", "tender_type"]
    for key in required_filters:
        if key not in filters:
            typer.echo(f"Error: 'filters.{key}' is required in input JSON", err=True)
            raise typer.Exit(code=1)

    if "session_context" not in data:
        typer.echo("Error: 'session_context' key is required in input JSON", err=True)
        raise typer.Exit(code=1)

    return cast(dict[str, Any], data)


def resolve_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    is_new = not db_path.exists()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    if is_new:
        initialize_schema(conn)

    # Apply any pending migrations (idempotent — safe to call on every startup).
    run_migrations(conn)

    return conn


def build_row_processor(mode: str) -> RowProcessor:
    return lambda ri, c: None
