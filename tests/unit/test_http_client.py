import time

import httpx
import pytest

from connectors.http import FetchError, PoliteClient, RobotsDisallowed


def _client(handler, **kw) -> PoliteClient:
    kw.setdefault("backoff_base", 0)
    kw.setdefault("default_rate_per_minute", 6000)
    return PoliteClient(transport=httpx.MockTransport(handler), **kw)


async def test_robots_disallow_blocks_request():
    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/")
        return httpx.Response(200, json={"ok": True})

    async with _client(handler) as c:
        assert await c.get_json("https://ex.test/public") == {"ok": True}
        with pytest.raises(RobotsDisallowed):
            await c.get("https://ex.test/private/x")


@pytest.mark.parametrize("status,allowed", [(404, True), (403, False), (503, False)])
async def test_robots_status_policy(status, allowed):
    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(status)
        return httpx.Response(200, json={})

    async with _client(handler, max_retries=0) as c:
        if allowed:
            await c.get("https://ex.test/a")
        else:
            with pytest.raises(RobotsDisallowed):
                await c.get("https://ex.test/a")


async def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"done": True})

    async with _client(handler) as c:
        assert await c.get_json("https://ex.test/x") == {"done": True}
    assert calls["n"] == 3


async def test_gives_up_after_max_retries():
    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(502)

    async with _client(handler, max_retries=2) as c:
        with pytest.raises(FetchError):
            await c.get("https://ex.test/x")


async def test_non_retryable_error_raises_immediately():
    calls = {"n": 0}

    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls["n"] += 1
        return httpx.Response(404)

    async with _client(handler) as c:
        with pytest.raises(FetchError, match="404"):
            await c.get("https://ex.test/missing")
    assert calls["n"] == 1


async def test_crawl_delay_spaces_requests():
    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nCrawl-delay: 1\nAllow: /")
        return httpx.Response(200, json={})

    async with _client(handler) as c:
        t0 = time.monotonic()
        for _ in range(2):
            await c.get("https://ex.test/x")
        assert time.monotonic() - t0 >= 1.0  # Crawl-delay is whole seconds (stdlib parser)


async def test_api_keys_are_redacted_in_errors():
    def handler(req: httpx.Request):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(400)

    async with _client(handler) as c:
        with pytest.raises(FetchError) as e:
            await c.get("https://ex.test/x", params={"app_key": "SECRET123", "q": "a"})
    assert "SECRET123" not in str(e.value)
