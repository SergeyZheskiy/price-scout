"""Snapshot history in SQLite: every run is stored, so price changes can be diffed later."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from .models import Product

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    source TEXT NOT NULL,
    scope TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    sku TEXT NOT NULL,
    title TEXT NOT NULL,
    price TEXT NOT NULL,          -- Decimal as text: SQLite REAL would reintroduce float rounding
    currency TEXT NOT NULL,
    in_stock INTEGER NOT NULL,
    rating INTEGER,
    category TEXT NOT NULL,
    url TEXT NOT NULL,
    PRIMARY KEY (run_id, sku)
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self.conn:  # commits, or rolls back on exception
            yield self.conn

    def save_run(self, products: list[Product], *, source: str, scope: str, at: datetime | None = None) -> int:
        started = (at or datetime.now(UTC)).isoformat(timespec="seconds")
        with self._tx() as c:
            run_id = c.execute(
                "INSERT INTO runs (started_at, source, scope) VALUES (?, ?, ?)", (started, source, scope)
            ).lastrowid
            c.executemany(
                "INSERT OR REPLACE INTO snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (run_id, p.sku, p.title, str(p.price), p.currency, p.in_stock, p.rating, p.category, p.url)
                    for p in products
                ],
            )
        assert run_id is not None
        return run_id

    def runs(self, scope: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT r.*, COUNT(s.sku) AS products FROM runs r LEFT JOIN snapshots s ON s.run_id = r.id"
        args: tuple = ()
        if scope is not None:
            sql += " WHERE r.scope = ?"
            args = (scope,)
        return self.conn.execute(sql + " GROUP BY r.id ORDER BY r.id", args).fetchall()

    def products(self, run_id: int) -> list[Product]:
        rows = self.conn.execute("SELECT * FROM snapshots WHERE run_id = ? ORDER BY title", (run_id,)).fetchall()
        return [
            Product(
                sku=r["sku"],
                title=r["title"],
                price=Decimal(r["price"]),
                currency=r["currency"],
                in_stock=r["in_stock"],
                rating=r["rating"],
                category=r["category"],
                url=r["url"],
            )
            for r in rows
        ]
