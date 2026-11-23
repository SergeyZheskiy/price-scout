import httpx
import pytest
from typer.testing import CliRunner

from price_scout import cli

runner = CliRunner()


@pytest.fixture(autouse=True)
def offline(shop, monkeypatch):
    monkeypatch.setattr(cli, "TRANSPORT", httpx.MockTransport(shop))
    monkeypatch.setattr(cli.console, "width", 120)


def test_scrape_twice_shows_price_changes(shop, tmp_path):
    db = str(tmp_path / "h.db")
    first = runner.invoke(
        cli.app, ["scrape", "-c", "travel", "--db", db, "--rate", "1000", "-o", str(tmp_path / "a.xlsx")]
    )
    assert first.exit_code == 0, first.output
    assert "3 products" in first.output and "a.xlsx" in first.output

    shop.products["alpha_1"] = ("Alpha", "8.00", 5, "Three", "Travel")
    shop.products["beta_2"] = ("Beta", "20.50", 4, "Five", "Travel")
    second = runner.invoke(cli.app, ["scrape", "-c", "travel", "--db", db, "--rate", "1000"])
    assert second.exit_code == 0, second.output
    assert "Changes since run #1" in second.output
    assert "-20.0%" in second.output
    assert "back in stock" in second.output

    assert "-20.0%" in runner.invoke(cli.app, ["diff", "--db", db, "--scope", "books:travel"]).output
    report = runner.invoke(cli.app, ["report", "--db", db])
    assert "Travel" in report.output and "8.00 GBP" in report.output
    assert "books:travel" in runner.invoke(cli.app, ["history", "--db", db]).output


def test_categories_and_errors(tmp_path):
    assert "poetry" in runner.invoke(cli.app, ["categories"]).output
    bad = runner.invoke(cli.app, ["scrape", "-c", "nope", "--db", str(tmp_path / "x.db")])
    assert bad.exit_code == 1 and "unknown category" in bad.output
    assert runner.invoke(cli.app, ["diff", "--db", str(tmp_path / "x.db")]).exit_code == 1
