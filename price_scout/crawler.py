import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from .fetcher import Fetcher, FetchError
from .models import Category, Product
from .sites.base import Site


@dataclass
class CrawlResult:
    products: list[Product] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    pages: int = 0


class CategoryNotFound(LookupError):
    def __init__(self, wanted: str, available: list[Category]):
        names = ", ".join(c.slug for c in available[:10])
        super().__init__(f"unknown category {wanted!r}; try one of: {names}…")


def find_category(categories: list[Category], wanted: str) -> Category:
    w = wanted.strip().lower()
    for c in categories:
        if w in (c.name.lower(), c.slug):
            return c
    raise CategoryNotFound(wanted, categories)


async def list_categories(fetcher: Fetcher, site: Site) -> list[Category]:
    return site.parse_categories(await fetcher.get(site.start_url), site.start_url)


async def crawl(
    fetcher: Fetcher,
    site: Site,
    *,
    category: str | None = None,
    limit: int | None = None,
    on_discovered: Callable[[int], None] | None = None,
    on_product: Callable[[], None] | None = None,
) -> CrawlResult:
    """Walk listing pages (sequentially — each page links to the next) and fetch product pages concurrently.

    A failed product page is recorded in `errors` instead of aborting the whole run.
    """
    result = CrawlResult()
    url: str | None = site.start_url
    if category:
        url = find_category(await list_categories(fetcher, site), category).url

    product_urls: list[str] = []
    seen: set[str] = set()
    while url and (limit is None or len(product_urls) < limit):
        html = await fetcher.get(url)
        result.pages += 1
        found, url = site.parse_listing(html, url)
        for u in found:
            if u not in seen:
                seen.add(u)
                product_urls.append(u)
    if limit is not None:
        product_urls = product_urls[:limit]
    if on_discovered:
        on_discovered(len(product_urls))

    async def scrape(u: str) -> Product | None:
        try:
            return site.parse_product(await fetcher.get(u), u)
        except (FetchError, ValueError) as exc:
            result.errors.append(str(exc))
            return None
        finally:
            if on_product:
                on_product()

    products = await asyncio.gather(*(scrape(u) for u in product_urls))
    result.products = [p for p in products if p is not None]  # gather keeps the listing order
    return result
