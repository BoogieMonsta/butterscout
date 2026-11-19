"""Smoke test: the real client against a real, pinned Crawl4AI.

Unit tests fake Crawl4AI's responses; this checks the contract they assume, on the image
the compose files pin. It needs a running Crawl4AI and the network, so it is skipped
unless pointed at one:

    BS_SMOKE_CRAWL4AI_URL=http://localhost:11235 \\
    BS_SMOKE_CRAWL4AI_TOKEN=$BS_CRAWL4AI_API_TOKEN \\
    uv run pytest tests/smoke --no-cov
"""

from __future__ import annotations

import os
import time

import httpx
import pytest
from pydantic import HttpUrl, TypeAdapter

from butterscout.clients.crawl4ai_client import (
    RESPONSE_GRACE_SECONDS,
    Crawl4AIClient,
    Crawl4AIUnavailableError,
)
from butterscout.config import Settings

BASE_URL = os.environ.get("BS_SMOKE_CRAWL4AI_URL")
TOKEN = os.environ.get("BS_SMOKE_CRAWL4AI_TOKEN")

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(not (BASE_URL and TOKEN), reason="no Crawl4AI to smoke-test"),
]


def _url(value: str) -> HttpUrl:
    return TypeAdapter(HttpUrl).validate_python(value)


async def _client(token: str | None = TOKEN) -> Crawl4AIClient:
    settings = Settings(
        BS_CRAWL4AI_URL=BASE_URL or "",
        BS_CRAWL4AI_API_TOKEN=token,
        BS_HEALTH_TIMEOUT_MS=3000,
        BS_REQUEST_TIMEOUT_MS=6000,
    )
    client = Crawl4AIClient(settings)
    await client.connect()
    return client


async def test_probe_renders_with_the_search_fit_config() -> None:
    client = await _client()
    try:
        assert await client.health_check() is True
    finally:
        await client.disconnect()


async def test_a_wrong_token_is_reported_as_auth() -> None:
    client = await _client(token="not-the-token")
    try:
        with pytest.raises(Crawl4AIUnavailableError) as info:
            await client.health_check()
    finally:
        await client.disconnect()
    assert info.value.reason == "auth"


async def test_raw_and_fit_extraction_of_a_real_page() -> None:
    client = await _client()
    try:
        raw = await client.extract(_url("https://example.com/"), "smoke", timeout_ms=6000)
        fit = await client.extract(
            _url("https://example.com/"), "smoke", timeout_ms=6000, markdown_filter="fit"
        )
    finally:
        await client.disconnect()
    assert "documentation examples" in raw.content
    assert raw.extracted_by == fit.extracted_by == "crawl4ai"
    assert len(fit.content) <= len(raw.content)


async def test_a_slow_page_times_out_within_the_budget() -> None:
    client = await _client()
    started = time.perf_counter()
    try:
        with pytest.raises(TimeoutError):
            await client.extract(_url("https://httpbin.org/delay/10"), "smoke", timeout_ms=2000)
    finally:
        await client.disconnect()
    assert time.perf_counter() - started < 2.0 + RESPONSE_GRACE_SECONDS + 0.5


async def test_the_server_deadline_ends_crawls_we_abandon() -> None:
    """Crawl4AI waits a fixed 30 s for an HTML <body>, which an SVG never has, and keeps
    going after we hang up. The mounted config's 8 s deadline (crawl4ai-config/config.yml)
    must end it; with upstream's 300 s it runs the full 30 s. Talks to /crawl directly,
    because Butterscout's client gives up sooner.
    """
    body = {
        "urls": ["https://www.w3.org/Icons/SVG/svg-logo-v.svg"],
        "crawler_config": {
            "type": "CrawlerRunConfig",
            "params": {
                "page_timeout": 2500,
                "body_visibility_timeout": 1000,
                "cache_mode": "bypass",
            },
        },
    }
    started = time.perf_counter()
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {TOKEN}"}) as client:
        response = await client.post(f"{BASE_URL}/crawl", json=body, timeout=40)
    elapsed = time.perf_counter() - started
    assert response.status_code == 504
    assert elapsed < 12
