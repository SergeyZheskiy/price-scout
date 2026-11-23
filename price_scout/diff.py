from dataclasses import dataclass, field
from decimal import Decimal

from .models import Product


@dataclass(frozen=True, slots=True)
class PriceChange:
    before: Product
    after: Product

    @property
    def delta(self) -> Decimal:
        return self.after.price - self.before.price

    @property
    def percent(self) -> Decimal:
        if self.before.price == 0:
            return Decimal("0")
        return (self.delta / self.before.price * 100).quantize(Decimal("0.1"))


@dataclass
class Diff:
    added: list[Product] = field(default_factory=list)
    removed: list[Product] = field(default_factory=list)
    price_changes: list[PriceChange] = field(default_factory=list)
    back_in_stock: list[Product] = field(default_factory=list)
    sold_out: list[Product] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.price_changes or self.back_in_stock or self.sold_out)


def diff_snapshots(before: list[Product], after: list[Product]) -> Diff:
    """Compare two runs by SKU. Price changes are sorted biggest drop first — that is what buyers care about."""
    old = {p.sku: p for p in before}
    new = {p.sku: p for p in after}
    d = Diff(
        added=sorted((new[s] for s in new.keys() - old.keys()), key=lambda p: p.title),
        removed=sorted((old[s] for s in old.keys() - new.keys()), key=lambda p: p.title),
    )
    for sku in old.keys() & new.keys():
        a, b = old[sku], new[sku]
        if a.price != b.price:
            d.price_changes.append(PriceChange(a, b))
        if a.in_stock == 0 and b.in_stock > 0:
            d.back_in_stock.append(b)
        elif a.in_stock > 0 and b.in_stock == 0:
            d.sold_out.append(b)
    d.price_changes.sort(key=lambda c: c.percent)
    return d
