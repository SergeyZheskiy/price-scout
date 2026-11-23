"""Adapter for https://books.toscrape.com — a sandbox shop built for scraping practice."""

import re
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..models import Category, Product

RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
CURRENCY_SYMBOLS = {"£": "GBP", "$": "USD", "€": "EUR"}


class ParseError(ValueError):
    pass


def parse_price(text: str) -> tuple[Decimal, str]:
    """'£51.77' -> (Decimal('51.77'), 'GBP'). Tolerates the mojibake 'Â£' that appears with wrong encodings."""
    cleaned = text.strip().replace("Â", "")
    symbol, amount = cleaned[:1], cleaned[1:].replace(",", "")
    if symbol not in CURRENCY_SYMBOLS:
        raise ParseError(f"unknown currency in price {text!r}")
    try:
        return Decimal(amount), CURRENCY_SYMBOLS[symbol]
    except InvalidOperation as exc:
        raise ParseError(f"bad price {text!r}") from exc


def parse_stock(text: str) -> int:
    """'In stock (22 available)' -> 22, 'Out of stock' -> 0."""
    match = re.search(r"\((\d+) available\)", text)
    if match:
        return int(match.group(1))
    return 0 if "out of stock" in text.lower() else 1


def parse_rating(classes: list[str]) -> int | None:
    return next((RATINGS[c] for c in classes if c in RATINGS), None)


class BooksToScrape:
    name = "books.toscrape.com"
    start_url = "https://books.toscrape.com/index.html"

    def parse_categories(self, html: str, base_url: str) -> list[Category]:
        soup = BeautifulSoup(html, "html.parser")
        links = soup.select(".side_categories ul.nav-list > li > ul > li > a")
        return [Category(a.get_text(strip=True), urljoin(base_url, a["href"])) for a in links]

    def parse_listing(self, html: str, base_url: str) -> tuple[list[str], str | None]:
        soup = BeautifulSoup(html, "html.parser")
        urls = [urljoin(base_url, a["href"]) for a in soup.select("article.product_pod h3 a[href]")]
        nxt = soup.select_one("li.next a[href]")
        return urls, urljoin(base_url, nxt["href"]) if nxt else None

    def parse_product(self, html: str, url: str) -> Product:
        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one("div.product_main")
        if main is None or main.h1 is None:
            raise ParseError(f"not a product page: {url}")

        table = {
            row.th.get_text(strip=True): row.td.get_text(strip=True)
            for row in soup.select("table.table-striped tr")
            if row.th and row.td
        }
        price_el = main.select_one("p.price_color")
        price, currency = parse_price(price_el.get_text() if price_el else table.get("Price (incl. tax)", ""))
        stock_el = main.select_one("p.availability")
        rating_el = main.select_one("p.star-rating")
        crumbs = soup.select("ul.breadcrumb li a")

        return Product(
            sku=table.get("UPC") or url,
            title=main.h1.get_text(strip=True),
            price=price,
            currency=currency,
            in_stock=parse_stock(stock_el.get_text(" ", strip=True) if stock_el else table.get("Availability", "")),
            rating=parse_rating(rating_el.get("class", []) if rating_el else []),
            category=crumbs[-1].get_text(strip=True) if len(crumbs) >= 3 else "",
            url=url,
        )
