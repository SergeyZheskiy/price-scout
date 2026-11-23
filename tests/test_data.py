import csv
import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from price_scout.diff import diff_snapshots
from price_scout.export import UnsupportedFormat, export
from price_scout.models import Product
from price_scout.storage import Store


def product(sku: str, price: str, stock: int = 3, title: str | None = None) -> Product:
    return Product(sku, title or sku.title(), Decimal(price), "GBP", stock, 4, "Travel", f"https://shop.test/{sku}")


def test_diff():
    before = [product("a", "10.00"), product("b", "20.00"), product("c", "5.00", 0), product("gone", "1.00")]
    after = [product("a", "8.00"), product("b", "25.00"), product("c", "5.00", 4), product("new", "3.00")]
    d = diff_snapshots(before, after)
    assert [p.sku for p in d.added] == ["new"]
    assert [p.sku for p in d.removed] == ["gone"]
    assert [(c.after.sku, c.delta, c.percent) for c in d.price_changes] == [
        ("a", Decimal("-2.00"), Decimal("-20.0")),  # biggest drop first
        ("b", Decimal("5.00"), Decimal("25.0")),
    ]
    assert [p.sku for p in d.back_in_stock] == ["c"]
    assert diff_snapshots(after, after).is_empty


def test_store_round_trip_keeps_exact_decimals(tmp_path):
    store = Store(tmp_path / "h.db")
    items = [product("a", "0.10"), product("b", "0.20")]
    run = store.save_run(items, source="test", scope="t:all", at=datetime(2026, 1, 1, tzinfo=UTC))
    store.save_run(items[:1], source="test", scope="t:other")
    loaded = store.products(run)
    assert sum(p.price for p in loaded) == Decimal("0.30")  # 0.1 + 0.2 as floats would be 0.30000000000000004
    assert [(r["scope"], r["products"]) for r in store.runs()] == [("t:all", 2), ("t:other", 1)]
    assert len(store.runs("t:all")) == 1


def test_exports(tmp_path):
    items = [product("a", "12.50", title='Quote "this", please'), product("b", "3.00")]

    rows = list(csv.DictReader(export(items, tmp_path / "out.csv").open(encoding="utf-8-sig")))
    assert rows[0]["title"] == 'Quote "this", please' and rows[0]["price"] == "12.50"

    data = json.loads(export(items, tmp_path / "nested/out.json").read_text())
    assert data[1] == {**data[1], "sku": "b", "price": "3.00"}

    ws = load_workbook(export(items, tmp_path / "out.xlsx")).active
    assert [c.value for c in ws[1]][:3] == ["sku", "title", "price"]
    assert ws["C2"].value == 12.5 and ws["C2"].number_format == "#,##0.00"
    assert ws["H2"].hyperlink.target == "https://shop.test/a"
    assert ws.auto_filter.ref == "A1:H3"

    with pytest.raises(UnsupportedFormat):
        export(items, tmp_path / "out.pdf")
