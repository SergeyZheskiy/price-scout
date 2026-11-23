from decimal import Decimal
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://books.toscrape.com"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class MiniShop:
    """A tiny fake books.toscrape.com: same markup, our own data. Mutable, so tests can change prices."""

    def __init__(self):
        self.products = {
            # slug: (title, price, stock, rating word, category)
            "alpha_1": ("Alpha", "10.00", 5, "Three", "Travel"),
            "beta_2": ("Beta", "20.50", 0, "Five", "Travel"),
            "gamma_3": ("Gamma", "7.99", 2, "One", "Travel"),
            "delta_4": ("Delta", "15.00", 9, "Four", "Poetry"),
            "broken_5": ("Broken", "1.00", 1, "Two", "Poetry"),
        }
        self.broken = {"broken_5"}  # always answers 500
        self.robots = "User-agent: *\nDisallow: /admin/\n"
        self.hits: list[str] = []

    def listing(self, slugs: list[str], next_href: str | None) -> str:
        pods = "".join(
            f'<article class="product_pod"><h3><a href="../../../{s}/index.html" title="x">x</a></h3></article>'
            for s in slugs
        )
        nxt = f'<li class="next"><a href="{next_href}">next</a></li>' if next_href else ""
        return f'<html><body><section>{pods}</section><ul class="pager">{nxt}</ul></body></html>'

    def home(self) -> str:
        pods = "".join(
            f'<article class="product_pod"><h3><a href="catalogue/{s}/index.html">x</a></h3></article>'
            for s in self.products
        )
        return f"""<html><body><div class="side_categories"><ul class="nav nav-list"><li>
            <a href="catalogue/category/books_1/index.html">Books</a><ul>
            <li><a href="catalogue/category/books/travel_2/index.html">Travel</a></li>
            <li><a href="catalogue/category/books/poetry_23/index.html">Poetry</a></li>
            </ul></li></ul></div><section>{pods}</section></body></html>"""

    def product(self, slug: str) -> str:
        title, price, stock, rating, category = self.products[slug]
        avail = f"In stock ({stock} available)" if stock else "Out of stock"
        return f"""<html><body>
            <ul class="breadcrumb"><li><a href="/">Home</a></li><li><a href="/b">Books</a></li>
            <li><a href="/c">{category}</a></li><li class="active">{title}</li></ul>
            <div class="col-sm-6 product_main"><h1>{title}</h1><p class="price_color">£{price}</p>
            <p class="instock availability">{avail}</p><p class="star-rating {rating}"></p></div>
            <table class="table table-striped"><tr><th>UPC</th><td>upc-{slug}</td></tr></table>
            </body></html>"""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.hits.append(path)
        if path == "/robots.txt":
            return httpx.Response(200, text=self.robots)
        if path in ("/", "/index.html"):
            return httpx.Response(200, text=self.home())
        if path == "/catalogue/category/books/travel_2/index.html":
            return httpx.Response(200, text=self.listing(["alpha_1", "beta_2"], "page-2.html"))
        if path == "/catalogue/category/books/travel_2/page-2.html":
            return httpx.Response(200, text=self.listing(["gamma_3", "alpha_1"], None))  # duplicate on purpose
        if path == "/catalogue/category/books/poetry_23/index.html":
            return httpx.Response(200, text=self.listing(["delta_4", "broken_5"], None))
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "catalogue" and parts[1] in self.products:
            if parts[1] in self.broken:
                return httpx.Response(500)
            return httpx.Response(200, text=self.product(parts[1]))
        return httpx.Response(404)


@pytest.fixture
def shop() -> MiniShop:
    return MiniShop()


async def no_sleep(_seconds: float) -> None:
    return None


@pytest.fixture
def money():
    return Decimal
