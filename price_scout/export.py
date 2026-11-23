import csv
import json
from pathlib import Path

from .models import Product

COLUMNS = ["sku", "title", "price", "currency", "in_stock", "rating", "category", "url"]


class UnsupportedFormat(ValueError):
    pass


def export(products: list[Product], path: Path) -> Path:
    """Write products to .csv, .json or .xlsx, chosen by file extension."""
    suffix = path.suffix.lower()
    path.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".csv":
        _csv(products, path)
    elif suffix == ".json":
        _json(products, path)
    elif suffix == ".xlsx":
        _xlsx(products, path)
    else:
        raise UnsupportedFormat(f"unsupported format {suffix!r}: use .csv, .json or .xlsx")
    return path


def _csv(products: list[Product], path: Path) -> None:
    # utf-8-sig: the BOM makes Excel open UTF-8 (e.g. Cyrillic, £) correctly on double-click
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(p.to_row() for p in products)


def _json(products: list[Product], path: Path) -> None:
    path.write_text(json.dumps([p.to_row() for p in products], ensure_ascii=False, indent=2), encoding="utf-8")


def _xlsx(products: list[Product], path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Products"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="4F46E5")
    for p in products:
        row = p.to_row()
        row["price"] = float(p.price)  # a real number in Excel, so it can be summed and sorted
        ws.append([row[c] for c in COLUMNS])
        ws.cell(ws.max_row, COLUMNS.index("url") + 1).hyperlink = p.url

    price_col = get_column_letter(COLUMNS.index("price") + 1)
    for cell in ws[price_col][1:]:
        cell.number_format = "#,##0.00"
    widths = {"sku": 18, "title": 50, "price": 10, "currency": 9, "in_stock": 9, "rating": 7, "category": 18, "url": 60}
    for i, name in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = widths[name]
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)
