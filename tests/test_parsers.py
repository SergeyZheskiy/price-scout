from decimal import Decimal

import pytest

from price_scout.models import Category
from price_scout.sites.books_toscrape import BooksToScrape, ParseError, parse_price, parse_rating, parse_stock

from .conftest import BASE, fixture

site = BooksToScrape()


def test_categories_from_real_homepage():
    cats = site.parse_categories(fixture("index.html"), f"{BASE}/index.html")
    assert len(cats) == 50
    assert cats[0] == Category("Travel", f"{BASE}/catalogue/category/books/travel_2/index.html")
    assert cats[0].slug == "travel"
    assert any(c.slug == "historical-fiction" for c in cats)


def test_listing_with_pagination():
    url = f"{BASE}/catalogue/category/books/mystery_3/index.html"
    urls, nxt = site.parse_listing(fixture("category_mystery_p1.html"), url)
    assert len(urls) == 20
    assert all(u.startswith(f"{BASE}/catalogue/") and u.endswith("/index.html") for u in urls)
    assert "/category/" not in urls[0]  # relative ../../../ links resolved correctly
    assert nxt == f"{BASE}/catalogue/category/books/mystery_3/page-2.html"

    urls, nxt = site.parse_listing(fixture("category_mystery_p2.html"), nxt)
    assert len(urls) == 12 and nxt is None


def test_product_page():
    url = f"{BASE}/catalogue/a-light-in-the-attic_1000/index.html"
    p = site.parse_product(fixture("product.html"), url)
    assert p.title == "A Light in the Attic"
    assert p.price == Decimal("51.77") and p.currency == "GBP"
    assert p.in_stock == 22
    assert p.rating == 3
    assert p.category == "Poetry"
    assert p.sku == "a897fe39b1053632"
    assert p.url == url


def test_non_product_page_is_rejected():
    with pytest.raises(ParseError):
        site.parse_product(fixture("index.html"), BASE)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£51.77", (Decimal("51.77"), "GBP")),
        ("Â£10.00", (Decimal("10.00"), "GBP")),
        (" $1,299.5 ", (Decimal("1299.5"), "USD")),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text", ["51.77", "£abc", ""])
def test_parse_price_rejects_garbage(text):
    with pytest.raises(ParseError):
        parse_price(text)


def test_stock_and_rating():
    assert parse_stock("In stock (22 available)") == 22
    assert parse_stock("Out of stock") == 0
    assert parse_stock("In stock") == 1
    assert parse_rating(["star-rating", "Four"]) == 4
    assert parse_rating(["star-rating"]) is None
