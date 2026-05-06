"""`ulle` command-line interface."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .analyze import embeddings, stats, topics
from .db import connect, init_db
from .ingest.service import ingest_path
from .vault import export_vault

app = typer.Typer(help="Ultimate LLM Explorer CLI")
console = Console()


@app.command()
def init() -> None:
    """Create the SQLite database."""
    init_db()
    console.print("[green]Database initialized.[/green]")


@app.command()
def ingest(path: Path = typer.Argument(..., exists=True)) -> None:
    """Ingest a file or directory of LLM exports."""
    init_db()
    db = connect()
    try:
        results = ingest_path(db, path.expanduser().resolve())
    finally:
        db.close()
    table = Table(title="Ingest results")
    table.add_column("Provider")
    table.add_column("Source")
    table.add_column("Convs", justify="right")
    table.add_column("Msgs", justify="right")
    table.add_column("Errors", justify="right")
    for r in results:
        table.add_row(
            r.provider,
            r.source,
            str(r.conversations),
            str(r.messages),
            str(len(r.errors)),
        )
    console.print(table)


@app.command("build-index")
def build_index() -> None:
    """Compute missing embeddings, rebuild topics and daily stats."""
    init_db()
    db = connect()
    try:
        n = embeddings.compute_missing(db)
        console.print(f"[cyan]embeddings:[/cyan] {n} computed")
        t = topics.rebuild(db)
        console.print(f"[cyan]topics:[/cyan] {t} created")
        d = stats.rebuild_daily(db)
        console.print(f"[cyan]daily stats:[/cyan] {d} days")
    finally:
        db.close()


@app.command("export-vault")
def export_vault_cmd(dest: Path = typer.Argument(...)) -> None:
    """Export an Obsidian-compatible vault to ``dest``."""
    init_db()
    db = connect()
    try:
        out = export_vault(db, dest.expanduser().resolve())
    finally:
        db.close()
    console.print(f"[green]Wrote {out['conversations']} conversations to {out['vault']}[/green]")


if __name__ == "__main__":  # pragma: no cover
    app()
