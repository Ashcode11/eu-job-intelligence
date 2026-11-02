"""A polite HTTP client: robots.txt, per-host rate limiting, retries, honest user agent."""

import asyncio
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

from common.logging import get_logger

log = get_logger(__name__)

USER_AGENT = (
    "EUJobIntelligence/0.1 (personal job search; +https://github.com/Ashcode11/eu-job-intelligence)"
)
_RETRY_STATUSES = {429, 500, 502, 503, 504}


class RobotsDisallowed(Exception):
    """The site's robots.txt does not allow fetching this URL."""


class FetchError(Exception):
    """A request failed after retries."""


class _Robots:
    def __init__(self, parser: RobotFileParser | None, allow_all: bool, deny_all: bool):
        self.parser, self.allow_all, self.deny_all = parser, allow_all, deny_all

    def allowed(self, url: str) -> bool:
        if self.deny_all:
            return False
        if self.allow_all or self.parser is None:
            return True
        return self.parser.can_fetch(USER_AGENT, url)

    def crawl_delay(self) -> float | None:
        if self.parser is None:
            return None
        delay = self.parser.crawl_delay(USER_AGENT)
        return float(delay) if delay is not None else None


class PoliteClient:
    """Shared by all connectors in one discovery run.

    - robots.txt is fetched once per host and cached for the client's lifetime.
      2xx: obeyed. 401/403: treated as "disallow all". Other 4xx: no rules (allow).
      5xx or network failure: treated as "disallow" for this run (be conservative).
    - Requests to one host are spaced by max(60/rate_per_minute, robots Crawl-delay).
    - 429/5xx/timeouts are retried with exponential backoff, honouring Retry-After.
    """

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        default_rate_per_minute: int = 30,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        timeout: float = 20.0,
        respect_robots: bool = True,
    ) -> None:
        self._client = httpx.AsyncClient(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json, */*;q=0.5"},
        )
        self._default_rate = default_rate_per_minute
        self._host_rate: dict[str, int] = {}
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._respect_robots = respect_robots
        self._robots: dict[str, _Robots] = {}
        self._robots_locks: dict[str, asyncio.Lock] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._last_request: dict[str, float] = {}
        self.request_count = 0

    async def __aenter__(self) -> "PoliteClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    def set_rate_limit(self, host: str, per_minute: int) -> None:
        self._host_rate[host] = max(1, per_minute)

    async def get_json(self, url: str, **params: object) -> object:
        return (await self.get(url, params=params)).json()

    async def get(self, url: str, *, params: dict[str, object] | None = None) -> httpx.Response:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        full_url = str(httpx.URL(url, params=clean)) if clean else url
        host = urlsplit(url).netloc
        if self._respect_robots:
            robots = await self._robots_for(url)
            if not robots.allowed(full_url):
                raise RobotsDisallowed(f"robots.txt disallows {_redact(full_url)}")

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            await self._wait_turn(host)
            try:
                self.request_count += 1
                resp = await self._client.get(url, params=clean or None)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                delay = self._backoff_base * 2**attempt
            else:
                if resp.status_code not in _RETRY_STATUSES:
                    if resp.is_error:
                        raise FetchError(f"HTTP {resp.status_code} from {_redact(full_url)}")
                    return resp
                last_exc = FetchError(f"HTTP {resp.status_code} from {_redact(full_url)}")
                delay = _retry_after(resp) or self._backoff_base * 2**attempt
            if attempt < self._max_retries:
                log.warning(
                    "http_retry", host=host, attempt=attempt + 1, delay_s=delay, error=str(last_exc)
                )
                await asyncio.sleep(min(delay, 30.0))
        raise FetchError(str(last_exc)) from last_exc

    async def _wait_turn(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            interval = 60.0 / self._host_rate.get(host, self._default_rate)
            robots = self._robots.get(host)
            if robots and (cd := robots.crawl_delay()):
                interval = max(interval, cd)
            wait = self._last_request.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request[host] = time.monotonic()

    async def _robots_for(self, url: str) -> _Robots:
        parts = urlsplit(url)
        host = parts.netloc
        if host in self._robots:
            return self._robots[host]
        async with self._robots_locks.setdefault(host, asyncio.Lock()):
            if host in self._robots:
                return self._robots[host]
            robots_url = f"{parts.scheme}://{host}/robots.txt"
            try:
                await self._wait_turn(host)
                self.request_count += 1
                resp = await self._client.get(robots_url)
            except httpx.HTTPError as exc:
                log.warning("robots_unreachable", host=host, error=str(exc))
                result = _Robots(None, allow_all=False, deny_all=True)
            else:
                ctype = resp.headers.get("content-type", "")
                if resp.status_code in (401, 403):
                    result = _Robots(None, allow_all=False, deny_all=True)
                elif 400 <= resp.status_code < 500:
                    result = _Robots(None, allow_all=True, deny_all=False)
                elif resp.status_code >= 500:
                    result = _Robots(None, allow_all=False, deny_all=True)
                elif "html" in ctype:
                    # Some API hosts serve an HTML page instead of robots.txt: no rules.
                    result = _Robots(None, allow_all=True, deny_all=False)
                else:
                    parser = RobotFileParser()
                    parser.parse(resp.text.splitlines())
                    result = _Robots(parser, allow_all=False, deny_all=False)
            self._robots[host] = result
            return result


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            return max(0.0, parsedate_to_datetime(value).timestamp() - time.time())
        except (TypeError, ValueError):
            return None


def _redact(url: str) -> str:
    """Never log API keys passed as query parameters."""
    u = httpx.URL(url)
    if not u.params:
        return url
    safe = {
        k: ("***" if "key" in k.lower() or k.lower() == "app_id" else v)
        for k, v in u.params.items()
    }
    return str(u.copy_with(params=safe))
