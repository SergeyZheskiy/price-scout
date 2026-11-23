"""Render docs/demo.svg: a real scrape, then a second run against a doctored first snapshot.

books.toscrape.com prices never change, so to show the diff output we edit a few prices in
run #1 to simulate "last week's" data. Everything else is real output.
"""

import sqlite3
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from price_scout import cli

cli.console = Console(record=True, width=96, force_terminal=True)
cli.SHOW_PROGRESS = False  # a transient progress bar leaves artifacts in a recording
runner = CliRunner()
db = Path("demo.db")  # relative, so no machine paths end up in the SVG
db.unlink(missing_ok=True)


def show(*args: str) -> None:
    cli.console.print(f"[bold green]$[/] price-scout {' '.join(args)}")
    result = runner.invoke(cli.app, list(args))
    assert result.exit_code == 0, result.output
    cli.console.print()


show("scrape", "--category", "travel", "--db", str(db))
with sqlite3.connect(db) as conn:
    rows = conn.execute("SELECT sku, price FROM snapshots WHERE run_id = 1 ORDER BY title LIMIT 3").fetchall()
    for (sku, price), factor in zip(rows, ("1.25", "0.8", "1.1"), strict=True):
        conn.execute(
            "UPDATE snapshots SET price = printf('%.2f', CAST(? AS REAL) * ?) WHERE run_id = 1 AND sku = ?",
            (price, factor, sku),
        )
    conn.execute("UPDATE snapshots SET in_stock = 0 WHERE run_id = 1 AND rowid = (SELECT max(rowid) FROM snapshots)")
show("scrape", "--category", "travel", "--db", str(db), "-o", "travel.xlsx")
show("report", "--db", str(db))

out = Path(__file__).resolve().parent.parent / "docs" / "demo.svg"
cli.console.save_svg(str(out), title="price-scout")
Path("travel.xlsx").unlink(missing_ok=True)
db.unlink(missing_ok=True)
print(f"wrote {out}")
