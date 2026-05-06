from pathlib import Path

import typer

app = typer.Typer(name="tender_royal_pulse", help="eProcure tender crawler with crash recovery")


@app.command()
def crawl(
    input_path: Path = typer.Option(..., "--input", "-i", help="Input JSON file with filters"),
    db_path: Path = typer.Option(..., "--db", "-d", help="SQLite database path for state"),
    output_path: Path | None = typer.Option(None, "--output", "-o", help="Output file path"),
    format: str = typer.Option("jsonl", "--format", "-f", help="Output format: csv or jsonl"),
    mock_http: bool = typer.Option(False, "--mock-http", help="Use recorded HTML fixtures instead of live network"),
) -> None:
    """Run tender crawler with specified input configuration."""
    typer.echo(f"Crawling with input: {input_path}")
    typer.echo(f"Database: {db_path}")
    typer.echo(f"Output: {output_path or 'none'}")


@app.command()
def status(
    db_path: Path = typer.Option(..., "--db", "-d", help="SQLite database path"),
) -> None:
    """Show current crawl status and statistics."""
    typer.echo(f"Status from: {db_path}")


if __name__ == "__main__":
    app()
