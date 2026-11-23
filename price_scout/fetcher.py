import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
Sleep = Callable[[float], Awaitable[None]]


class FetchError(Exception):
    def __init__(self, url: str, reason: str):
        super().__init__(f"{url}: {reason}")
        self.url, self.reason = url, reason


class RateLimiter:
    """Spaces requests evenly: at most `rate` request starts per second, shared by all workers."""

    def __init__(self, rate: float, *, clock: Callable[[], float] = time.monotonic, sleep: Sleep = asyncio.sleep):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.interval = 1 / rate
        self._clock, self._sleep = clock, sleep
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self.interval
        if (wait := slot - now) > 0:
            await self._sleep(wait)


def retry_after_seconds(value: str | None) -> float | None:
    """Retry-After may be seconds ('120') or an HTTP date."""
    if not value:
        return None
    if value.strip().isdigit():
        return float(value)
    try:
        return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
    except (TypeError, ValueError):
        return None


class Fetcher:
    """Polite HTTP client: robots.txt, global rate limit, bounded concurrency, retries with backoff."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        rate: float = 5.0,
        concurrency: int = 8,
        retries: int = 3,
        backoff: float = 0.5,
        respect_robots: bool = True,
        sleep: Sleep = asyncio.sleep,
    ):
        self.client = client
        self.limiter = RateLimiter(rate, sleep=sleep)
        self.semaphore = asyncio.Semaphore(concurrency)
        self.retries, self.backoff = retries, backoff
        self.respect_robots = respect_robots
        self._sleep = sleep
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = asyncio.Lock()
        self.requests_made = 0

    async def _robots_for(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        async with self._robots_lock:
            if origin not in self._robots:
                parser: RobotFileParser | None = None
                try:
                    resp = await self.client.get(f"{origin}/robots.txt")
                    if resp.status_code == 200:
                        parser = RobotFileParser()
                        parser.parse(resp.text.splitlines())
                except httpx.HTTPError:
                    pass  # no robots.txt reachable -> everything allowed
                self._robots[origin] = parser
            return self._robots[origin]

    async def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        robots = await self._robots_for(url)
        user_agent = self.client.headers.get("user-agent", "*")
        return robots is None or robots.can_fetch(user_agent, url)

    async def get(self, url: str) -> str:
        if not await self.allowed(url):
            raise FetchError(url, "disallowed by robots.txt")

        for attempt in range(self.retries + 1):
            await self.limiter.acquire()
            delay: float | None = None
            async with self.semaphore:
                self.requests_made += 1
                try:
                    resp = await self.client.get(url, follow_redirects=True)
                except httpx.TransportError as exc:
                    reason = f"{type(exc).__name__}"
                else:
                    if resp.status_code < 400:
                        return resp.text
                    reason = f"HTTP {resp.status_code}"
                    if resp.status_code not in RETRYABLE_STATUS:
                        raise FetchError(url, reason)  # 404 etc. won't fix themselves
                    delay = retry_after_seconds(resp.headers.get("retry-after"))

            if attempt == self.retries:
                raise FetchError(url, f"{reason} after {attempt + 1} attempts")
            # exponential backoff with jitter so parallel workers don't retry in lockstep
            delay = delay if delay is not None else self.backoff * 2**attempt * random.uniform(1, 1.5)
            log.debug("retrying %s in %.2fs (%s)", url, delay, reason)
            await self._sleep(delay)
        raise AssertionError("unreachable")
