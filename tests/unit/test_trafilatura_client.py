"""Tests for the Trafilatura fallback: one deadline, bounded admission, bounded fetch."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, Optional, cast

import httpx
import pytest
from pydantic import HttpUrl, TypeAdapter

import butterscout.clients.trafilatura_client as module
from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.extraction_strategy import ExtractionStrategy
from butterscout.clients.trafilatura_client import (
    MAX_BODY_BYTES,
    MAX_REDIRECTS,
    TrafilaturaClient,
    _parse_unless_expired,
)
from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent

URL = TypeAdapter(HttpUrl).validate_python("https://example.com/page")
ARTICLE = (
    "<html><body><article><h1>Fallback</h1><p>"
    + "This article has plenty of ordinary prose for the extractor to keep. " * 5
    + "</p></article></body></html>"
)


class _CountingStream(httpx.AsyncByteStream):
    """A response body that records how many chunks were read from it."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.read = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            self.read += 1
            yield chunk


def _page(text: str = ARTICLE) -> httpx.Response:
    """A streamed HTML response (in-memory `text=` responses are pre-read by HTTPX, unlike
    real network responses, so they cannot be streamed raw)."""
    return httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        stream=_CountingStream([text.encode()]),
    )


async def _client(settings: Settings, handler: Callable[[httpx.Request], Any]) -> TrafilaturaClient:
    client = TrafilaturaClient(settings)
    await client.connect()
    assert client.http_client is not None
    headers = client.http_client.headers
    await client.http_client.aclose()
    client.http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers=headers, follow_redirects=False
    )
    return client


def test_budget_is_the_fallback_setting_capped_by_the_caller(settings: Settings) -> None:
    settings.BS_FALLBACK_TIMEOUT_MS = 2000
    settings.BS_REQUEST_TIMEOUT_MS = 6000
    client = TrafilaturaClient(settings)
    assert client.budget_ms(None) == 2000
    assert client.budget_ms(2500) == 2000  # the setting now applies to search and /extract
    assert client.budget_ms(500) == 500  # a short request stays short
    settings.BS_REQUEST_TIMEOUT_MS = 1500
    assert client.budget_ms(None) == 1500


async def test_extracts_a_page_and_asks_for_no_compression(settings: Settings) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _page()

    client = await _client(settings, handler)
    try:
        result = await client.extract(URL, "req")
    finally:
        await client.disconnect()
    assert result.extracted_by == "trafilatura"
    assert "ordinary prose" in result.content
    assert seen[0].headers["accept-encoding"] == "identity"


@pytest.mark.parametrize("user_agent", [None, "", "ExampleFetcher/0.0"])
async def test_sends_the_configured_user_agent_or_the_httpx_default(
    settings: Settings, user_agent: Optional[str]
) -> None:
    settings.BS_FALLBACK_USER_AGENT = user_agent
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _page()

    client = await _client(settings, handler)
    try:
        await client.extract(URL, "req")
    finally:
        await client.disconnect()
    sent = seen[0].headers["user-agent"]
    assert sent == (user_agent or f"python-httpx/{httpx.__version__}")
    assert seen[0].headers["accept-encoding"] == "identity"


async def test_a_compressed_answer_is_refused_unread(settings: Settings) -> None:
    body = _CountingStream([b"\x1f\x8b" + b"\x00" * 100])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-encoding": "gzip"}, stream=body)

    client = await _client(settings, handler)
    try:
        with pytest.raises(ValueError, match="compressed"):
            await client.extract(URL, "req")
    finally:
        await client.disconnect()
    assert body.read == 0


async def test_an_oversized_page_is_refused_before_parsing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    parsed: list[str] = []
    monkeypatch.setattr(module, "_parse", lambda html: parsed.append(html) or "x")
    chunk = b"<p>" + b"x" * 65_536 + b"</p>"
    body = _CountingStream([chunk] * (MAX_BODY_BYTES // len(chunk) + 5))

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=body)

    client = await _client(settings, handler)
    try:
        with pytest.raises(ValueError, match="larger than"):
            await client.extract(URL, "req")
    finally:
        await client.disconnect()
    assert parsed == []
    assert body.read < len(body.chunks)  # stopped reading once over the cap


async def test_redirects_are_followed_without_reading_their_bodies(settings: Settings) -> None:
    hop_body = _CountingStream([b"moved " * 1000] * 50)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/page":
            return httpx.Response(302, headers={"location": "/final"}, stream=hop_body)
        return _page()

    client = await _client(settings, handler)
    try:
        result = await client.extract(URL, "req")
    finally:
        await client.disconnect()
    assert "ordinary prose" in result.content
    assert hop_body.read == 0


async def test_a_redirect_loop_stops(settings: Settings) -> None:
    hops: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        hops.append(request.url.path)
        return httpx.Response(302, headers={"location": f"/hop{len(hops)}"})

    client = await _client(settings, handler)
    try:
        with pytest.raises(ValueError, match="redirects"):
            await client.extract(URL, "req")
    finally:
        await client.disconnect()
    assert len(hops) == MAX_REDIRECTS + 1


async def test_fetch_and_parse_share_one_deadline(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each fits the budget alone; together they must not."""
    settings.BS_FALLBACK_TIMEOUT_MS = 500

    def slow_parse(html: str) -> Optional[str]:
        time.sleep(0.35)
        return "text"

    monkeypatch.setattr(module, "_parse", slow_parse)

    async def handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.35)
        return _page()

    client = await _client(settings, handler)
    started = time.perf_counter()
    try:
        with pytest.raises(TimeoutError):
            await client.extract(URL, "req")
        elapsed = time.perf_counter() - started
    finally:
        await client.disconnect()
    assert elapsed < 0.5 + 0.15


async def test_an_abandoned_parse_keeps_its_permit_until_its_thread_ends(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Parses cannot be cancelled; admission must count them until they really finish."""
    settings.BS_FALLBACK_MAX_WORKERS = 1  # 2 permits
    settings.BS_FALLBACK_TIMEOUT_MS = 200
    release = threading.Event()

    def stuck_parse(html: str) -> Optional[str]:
        release.wait(5)
        return "text"

    monkeypatch.setattr(module, "_parse", stuck_parse)
    fetches: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetches.append(request.url.path)
        return _page()

    client = await _client(settings, handler)
    try:
        for _ in range(2):  # both permits now held by parses nobody waits for
            with pytest.raises(TimeoutError):
                await client.extract(URL, "abandoned")
        with pytest.raises(TimeoutError):
            await client.extract(URL, "no permit")
        assert len(fetches) == 2  # the third never got to fetch
        release.set()
        monkeypatch.setattr(module, "_parse", lambda html: "text")
        for _ in range(50):  # the threads finish; their permits come back
            await asyncio.sleep(0.01)
            if client._permits._value == 2:
                break
        result = await client.extract(URL, "after")
    finally:
        release.set()
        await client.disconnect()
    assert result.content == "text"


def test_a_job_queued_past_its_deadline_is_skipped_as_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(module, "_parse", lambda html: called.append(html) or "x")
    with pytest.raises(TimeoutError):
        _parse_unless_expired("<p>x</p>", time.monotonic() - 1)
    assert called == []


async def test_httpx_phase_timers_are_off_so_the_deadline_owns_the_clock(
    settings: Settings,
) -> None:
    client = TrafilaturaClient(settings)
    await client.connect()
    try:
        assert client.http_client is not None
        assert client.http_client.timeout == httpx.Timeout(None)
    finally:
        await client.disconnect()


async def test_an_httpx_timeout_is_still_reported_as_a_timeout(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = await _client(settings, handler)
    try:
        with pytest.raises(TimeoutError):
            await client.extract(URL, "req")
    finally:
        await client.disconnect()


async def test_a_fallback_timeout_is_reported_as_a_timeout(settings: Settings) -> None:
    """/extract and MCP say "timed out" only if they are told; a generic failure hid it."""

    class FailingCrawl4AI:
        async def extract(self, *args: Any, **kwargs: Any) -> ExtractedContent:
            raise ValueError("page refused")

    class SlowFallback:
        async def extract(self, *args: Any, **kwargs: Any) -> ExtractedContent:
            raise TimeoutError("fallback ran out of time")

    strategy = ExtractionStrategy(
        cast(Crawl4AIClient, FailingCrawl4AI()), cast(TrafilaturaClient, SlowFallback()), settings
    )
    result = await strategy.extract(URL, "req")
    assert result.extraction_ok is False
    assert result.error == "timeout"


class _PageRefusedByCrawl4AI:
    async def extract(self, *args: Any, **kwargs: Any) -> ExtractedContent:
        raise ValueError("Crawl4AI could not crawl the page")


async def _slow_site(request: httpx.Request) -> httpx.Response:
    await asyncio.sleep(3)
    return _page()


def test_a_fallback_timeout_reaches_rest_and_mcp_as_a_timeout(settings: Settings) -> None:
    """A real fallback timing out: /extract says timeout in its 502, MCP says "timed out"."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from fastapi.testclient import TestClient

    from butterscout.main import app
    from butterscout.state import app_state

    from .test_mcp_endpoint import call_tool, mcp_client

    settings.BS_FALLBACK_TIMEOUT_MS = 3000

    async def scenario() -> ExtractionStrategy:
        fallback = await _client(settings, _slow_site)
        return ExtractionStrategy(
            cast(Crawl4AIClient, _PageRefusedByCrawl4AI()), fallback, settings
        )

    url = "https://93.184.216.34/page"
    allow = AsyncMock(return_value=(True, None, 59, 60, 1234567890))
    with patch("butterscout.services.rate_limiter.RateLimiter.check_rate_limit", new=allow):
        with patch.object(app_state, "redis_client", MagicMock(), create=True):
            with TestClient(app, raise_server_exceptions=False) as client:
                strategy = client.portal.call(scenario)  # type: ignore[union-attr]
                with patch.object(app_state, "extraction_strategy", strategy, create=True):
                    rest = client.post(
                        "/api/v1/extract", json={"url": url, "extract_timeout_ms": 500}
                    )
                client.portal.call(strategy.trafilatura.disconnect)  # type: ignore[union-attr]
            with mcp_client() as mcp:
                strategy = mcp.portal.call(scenario)  # type: ignore[union-attr]
                with patch.object(app_state, "extraction_strategy", strategy, create=True):
                    tool = call_tool(
                        mcp, "butterscout_extract", {"url": url, "extract_timeout_ms": 500}
                    )
                mcp.portal.call(strategy.trafilatura.disconnect)  # type: ignore[union-attr]

    assert rest.status_code == 502
    assert rest.json()["error"]["details"]["timeout"] is True
    assert tool["isError"] is True
    assert "timed out" in tool["content"][0]["text"]
