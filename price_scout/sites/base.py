from typing import Protocol

from ..models import Category, Product


class Site(Protocol):
    """Everything site-specific lives behind this interface; the crawler is generic.

    Adding a new shop = one new module implementing these four members, plus fixture-based tests.
    """

    name: str
    start_url: str

    def parse_categories(self, html: str, base_url: str) -> list[Category]: ...

    def parse_listing(self, html: str, base_url: str) -> tuple[list[str], str | None]:
        """Product URLs on a listing page and the URL of the next page (or None)."""
        ...

    def parse_product(self, html: str, url: str) -> Product: ...
