import asyncio
import statistics
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from . import __version__
from .crawler import CategoryNotFound, crawl, list_categories
from .diff import Diff, diff_snapshots
from .export import UnsupportedFormat, export
from .fetcher import Fetcher, FetchError
from .models import Product
from .sites import SITES
from .storage import Store

app = typer.Typer(
    help="Polite async scraper that tracks prices and stock between runs.",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
USER_AGENT = f"price-scout/{__version__} (+https://github.com/SergeyZheskiy/price-scout)"

SiteOpt = Annotated[str, typer.Option(help=f"Site adapter: {', '.join(SITES)}")]
DbOpt = Annotated[Path, typer.Option(help="SQLite file with run history")]


@asynccontextmanager
async def make_fetcher(rate: float, concurrency: int, transport: httpx.AsyncBaseTransport | None = None):
    async with httpx.AsyncClient(
        transport=transport, headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(15.0)
    ) as client:
        yield Fetcher(client, rate=rate, concurrency=concurrency)


def get_site(name: str):
    if name not in SITES:
        raise typer.BadParameter(f"unknown site {name!r}; available: {', '.join(SITES)}")
    return SITES[name]()


# Tests replace this to run the CLI against an in-memory site.
TRANSPORT: httpx.AsyncBaseTransport | None = None
SHOW_PROGRESS = True


@app.command()
def scrape(
    site: SiteOpt = "books",
    category: Annotated[str | None, typer.Option("--category", "-c", help="Category name or slug")] = None,
    limit: Annotated[int | None, typer.Option("--limit", "-n", min=1, help="Stop after N products")] = None,
    out: Annotated[list[Path] | None, typer.Option("--out", "-o", help="Export file(s): .csv, .json or .xlsx")] = None,
    db: DbOpt = Path("price-scout.db"),
    rate: Annotated[float, typer.Option(min=0.1, help="Max requests per second")] = 5.0,
    concurrency: Annotated[int, typer.Option(min=1, max=64, help="Parallel connections")] = 8,
):
    """Scrape products, save a snapshot and show what changed since the previous run."""
    adapter = get_site(site)
    scope = f"{site}:{category or 'all'}"

    async def run():
        async with make_fetcher(rate, concurrency, TRANSPORT) as fetcher:
            with Progress(
                TextColumn("[bold]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=True,
                disable=not SHOW_PROGRESS,
            ) as progress:
                task = progress.add_task("Discovering products", total=None)
                result = await crawl(
                    fetcher,
                    adapter,
                    category=category,
                    limit=limit,
                    on_discovered=lambda n: progress.update(task, total=n, description="Scraping"),
                    on_product=lambda: progress.advance(task),
                )
            return result, fetcher.requests_made

    try:
        result, requests = asyncio.run(run())
    except (FetchError, CategoryNotFound) as exc:
        console.print(f"[red]✗[/] {exc}")
        raise typer.Exit(1) from exc

    store = Store(db)
    previous = store.runs(scope)
    run_id = store.save_run(result.products, source=adapter.name, scope=scope)
    console.print(
        f"[green]✓[/] {len(result.products)} products from {result.pages} listing pages "
        f"({requests} requests) — saved as run #{run_id} in {db}"
    )
    for err in result.errors[:5]:
        console.print(f"  [yellow]![/] {err}")
    if len(result.errors) > 5:
        console.print(f"  [yellow]![/] …and {len(result.errors) - 5} more errors")

    for path in out or []:
        try:
            console.print(f"[green]✓[/] exported {export(result.products, path)}")
        except UnsupportedFormat as exc:
            console.print(f"[red]✗[/] {exc}")

    if previous:
        print_diff(
            diff_snapshots(store.products(previous[-1]["id"]), result.products), f"since run #{previous[-1]['id']}"
        )
    store.close()
    if result.errors and not result.products:
        raise typer.Exit(1)


@app.command()
def categories(site: SiteOpt = "books"):
    """List categories available on the site."""
    adapter = get_site(site)

    async def run():
        async with make_fetcher(5, 1, TRANSPORT) as fetcher:
            return await list_categories(fetcher, adapter)

    table = Table("slug", "name", box=None)
    for c in asyncio.run(run()):
        table.add_row(c.slug, c.name)
    console.print(table)


@app.command()
def history(db: DbOpt = Path("price-scout.db")):
    """Show previous runs."""
    store = Store(db)
    table = Table("run", "started (UTC)", "scope", "products")
    for r in store.runs():
        table.add_row(str(r["id"]), r["started_at"], r["scope"], str(r["products"]))
    console.print(table)


@app.command()
def diff(
    db: DbOpt = Path("price-scout.db"),
    scope: Annotated[str, typer.Option(help="Scope as shown by `history`, e.g. books:all")] = "books:all",
):
    """Compare the last two runs of a scope."""
    runs = Store(db).runs(scope)
    if len(runs) < 2:
        console.print(f"Need at least two runs for scope {scope!r}; found {len(runs)}.")
        raise typer.Exit(1)
    store = Store(db)
    a, b = runs[-2]["id"], runs[-1]["id"]
    print_diff(diff_snapshots(store.products(a), store.products(b)), f"run #{a} → #{b}")


@app.command()
def report(db: DbOpt = Path("price-scout.db")):
    """Per-category price statistics for the latest run."""
    store = Store(db)
    runs = store.runs()
    if not runs:
        console.print("No runs yet. Start with: price-scout scrape")
        raise typer.Exit(1)
    products = store.products(runs[-1]["id"])
    console.print(category_table(products, f"Run #{runs[-1]['id']} · {runs[-1]['scope']}"))


def category_table(products: list[Product], title: str) -> Table:
    groups: dict[str, list[Product]] = defaultdict(list)
    for p in products:
        groups[p.category].append(p)
    table = Table("category", "items", "min", "median", "max", "avg rating", "in stock", title=title)
    for cat, items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        prices = [p.price for p in items]
        ratings = [p.rating for p in items if p.rating]
        cur = items[0].currency
        table.add_row(
            cat,
            str(len(items)),
            f"{min(prices)} {cur}",
            f"{statistics.median(prices):.2f} {cur}",
            f"{max(prices)} {cur}",
            f"{statistics.mean(ratings):.1f} ★" if ratings else "—",
            str(sum(p.in_stock for p in items)),
        )
    return table


def print_diff(d: Diff, label: str) -> None:
    if d.is_empty:
        console.print(f"[dim]No changes {label}.[/]")
        return
    console.rule(f"Changes {label}")
    if d.price_changes:
        t = Table("title", "was", "now", "change", box=None)
        for c in d.price_changes:
            color = "green" if c.delta < 0 else "red"
            t.add_row(c.after.title[:60], str(c.before.price), str(c.after.price), f"[{color}]{c.percent:+}%[/]")
        console.print(t)
    for label_, items, style in (
        ("new", d.added, "green"),
        ("removed", d.removed, "red"),
        ("back in stock", d.back_in_stock, "cyan"),
        ("sold out", d.sold_out, "yellow"),
    ):
        if items:
            console.print(f"[{style}]{len(items)} {label_}:[/] " + "; ".join(p.title[:40] for p in items[:5]))


@app.callback(invoke_without_command=True)
def main(version: Annotated[bool, typer.Option("--version", help="Show version and exit")] = False):
    if version:
        console.print(f"price-scout {__version__}")
        raise typer.Exit()
