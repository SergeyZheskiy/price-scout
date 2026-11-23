from dataclasses import asdict, dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Category:
    name: str
    url: str

    @property
    def slug(self) -> str:
        # ".../books/historical-fiction_4/index.html" -> "historical-fiction"
        part = self.url.rstrip("/").split("/")[-2]
        return part.rsplit("_", 1)[0]


@dataclass(frozen=True, slots=True)
class Product:
    """One product snapshot. Prices are Decimal — never float — so £0.10 + £0.20 is exactly £0.30."""

    sku: str
    title: str
    price: Decimal
    currency: str
    in_stock: int
    rating: int | None
    category: str
    url: str

    def to_row(self) -> dict:
        row = asdict(self)
        row["price"] = str(self.price)
        return row
