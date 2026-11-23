from decimal import Decimal

import httpx
import pytest

from price_scout.crawler import CategoryNotFound, crawl
from price_scout.fetcher import Fetcher
from price_scout.sites import BooksToScrape

from .conftest import no_sleep


def fetcher_for(shop) -> Fetcher:
    return Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(shop)), rate=1000, retries=1, sleep=no_sleep)


async def test_crawls_category_across_pages_and_dedupes(shop):
    result = await crawl(fetcher_for(shop), BooksToScrape(), category="travel")
    assert [p.title for p in result.products] == ["Alpha", "Beta", "Gamma"]
    assert result.pages == 2
    assert result.errors == []
    beta = result.products[1]
    assert beta.price == Decimal("20.50") and beta.in_stock == 0 and beta.rating == 5 and beta.category == "Travel"


async def test_broken_product_is_reported_not_fatal(shop):
    result = await crawl(fetcher_for(shop), BooksToScrape(), category="Poetry")
    assert [p.title for p in result.products] == ["Delta"]
    assert len(result.errors) == 1 and "broken_5" in result.errors[0] and "HTTP 500" in result.errors[0]


async def test_limit_stops_early(shop):
    discovered = []
    result = await crawl(fetcher_for(shop), BooksToScrape(), limit=2, on_discovered=discovered.append)
    assert len(result.products) == 2 and discovered == [2]


async def test_unknown_category(shop):
    with pytest.raises(CategoryNotFound, match="travel"):
        await crawl(fetcher_for(shop), BooksToScrape(), category="cooking")
