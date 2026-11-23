from .base import Site
from .books_toscrape import BooksToScrape

SITES: dict[str, type[Site]] = {"books": BooksToScrape}

__all__ = ["SITES", "BooksToScrape", "Site"]
