import httpx
import pytest

from price_scout.fetcher import Fetcher, FetchError, RateLimiter, retry_after_seconds


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))


async def test_rate_limiter_spaces_requests_evenly():
    clock = FakeClock()
    limiter = RateLimiter(2, clock=clock, sleep=clock.sleep)  # 2 req/s -> one every 0.5s
    for _ in range(4):
        await limiter.acquire()
    assert clock.sleeps == [0.5, 1.0, 1.5]

    clock.now = 10.0  # after a long pause there is no backlog to pay off
    clock.sleeps.clear()
    await limiter.acquire()
    assert clock.sleeps == []


def scripted(responses):
    """Transport returning the given responses/exceptions in order; robots.txt is always 404."""
    calls = []

    def handler(request: httpx.Request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(request.url.path)
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return httpx.MockTransport(handler), calls


async def make(transport, sleeps: list[float], **kw) -> Fetcher:
    async def sleep(s: float):
        sleeps.append(s)

    return Fetcher(httpx.AsyncClient(transport=transport), rate=1000, sleep=sleep, **kw)


async def test_retries_transient_errors_with_backoff():
    req = httpx.Request("GET", "https://x.test/")
    transport, calls = scripted(
        [httpx.Response(503), httpx.ConnectError("boom", request=req), httpx.Response(200, text="ok")]
    )
    sleeps: list[float] = []
    f = await make(transport, sleeps, backoff=1.0)
    assert await f.get("https://x.test/page") == "ok"
    assert len(calls) == 3
    backoffs = [s for s in sleeps if s >= 0.5]
    assert 1.0 <= backoffs[0] <= 1.5 and 2.0 <= backoffs[1] <= 3.0  # exponential with jitter


async def test_honours_retry_after():
    transport, _ = scripted([httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(200, text="ok")])
    sleeps: list[float] = []
    f = await make(transport, sleeps)
    assert await f.get("https://x.test/") == "ok"
    assert 7.0 in sleeps


async def test_does_not_retry_client_errors():
    transport, calls = scripted([httpx.Response(404)])
    f = await make(transport, [])
    with pytest.raises(FetchError, match="HTTP 404"):
        await f.get("https://x.test/missing")
    assert len(calls) == 1


async def test_gives_up_after_max_retries():
    transport, calls = scripted([httpx.Response(500)] * 3)
    f = await make(transport, [], retries=2)
    with pytest.raises(FetchError, match="after 3 attempts"):
        await f.get("https://x.test/")
    assert len(calls) == 3


async def test_robots_txt_is_respected(shop):
    f = Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(shop)), rate=1000)
    with pytest.raises(FetchError, match="robots.txt"):
        await f.get("https://books.toscrape.com/admin/secret")
    assert "/admin/secret" not in shop.hits
    assert await f.allowed("https://books.toscrape.com/index.html")
    assert shop.hits.count("/robots.txt") == 1  # cached per origin


def test_retry_after_parsing():
    assert retry_after_seconds("120") == 120.0
    assert retry_after_seconds(None) is None
    assert retry_after_seconds("garbage") is None
    assert retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0  # in the past
