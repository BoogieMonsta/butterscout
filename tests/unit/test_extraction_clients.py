"""Tests for extraction clients."""

from __future__ import annotations

from typing import cast

import httpx
import pytest
import respx
from httpx import Response
from prometheus_client import REGISTRY
from pydantic import HttpUrl, TypeAdapter

from butterscout.clients import trafilatura_client as trafilatura_module
from butterscout.clients.crawl4ai_client import (
    Crawl4AIBusyError,
    Crawl4AIClient,
    Crawl4AIUnavailableError,
)
from butterscout.clients.extraction_strategy import ExtractionStrategy
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent


def _url(url_str: str) -> HttpUrl:
    return cast(HttpUrl, url_str)


def _validated_url(url_str: str) -> HttpUrl:
    return TypeAdapter(HttpUrl).validate_python(url_str)


def _crawl_ok(raw: str) -> dict[str, object]:
    """A Crawl4AI 0.9 /crawl response for one successfully crawled page."""
    return {
        "success": True,
        "results": [{"success": True, "markdown": {"raw_markdown": raw, "fit_markdown": ""}}],
    }


@pytest.mark.asyncio
async def test_extraction_strategy_fallback_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure fallback is invoked when Crawl4AI fails."""

    class FakeCrawl4AI:
        async def extract(
            self,
            url: HttpUrl,
            request_id: str,
            timeout_ms: int | None = None,
            markdown_filter: str = "raw",
        ) -> ExtractedContent:
            raise RuntimeError("crawl failure")

    class FakeTrafilatura:
        async def extract(
            self, url: HttpUrl, request_id: str, timeout_ms: int | None = None
        ) -> ExtractedContent:
            return ExtractedContent(
                url=url,
                content="fallback content",
                word_count=2,
                extracted_by="trafilatura",
                extraction_ok=True,
                extraction_time_ms=10,
            )

    settings = Settings(
        BS_SEARXNG_URL="http://searxng:8080",
        BS_CRAWL4AI_URL="http://crawl4ai:11235",
        BS_REDIS_URL="redis://redis:6379/0",
        BS_FALLBACK_ENABLED=True,
    )

    strategy = ExtractionStrategy(
        crawl4ai=cast(Crawl4AIClient, FakeCrawl4AI()),
        trafilatura=cast(TrafilaturaClient, FakeTrafilatura()),
        settings=settings,
    )

    result = await strategy.extract(_url("https://example.com"), "req-1")
    assert result.extraction_ok is True
    assert result.extracted_by == "trafilatura"
    assert result.content == "fallback content"


@pytest.mark.asyncio
async def test_extraction_strategy_no_fallback() -> None:
    """Ensure failure returns a failed result when fallback disabled or missing."""

    class FakeCrawl4AI:
        async def extract(
            self,
            url: HttpUrl,
            request_id: str,
            timeout_ms: int | None = None,
            markdown_filter: str = "raw",
        ) -> ExtractedContent:
            raise RuntimeError("crawl failure")

    settings = Settings(
        BS_SEARXNG_URL="http://searxng:8080",
        BS_CRAWL4AI_URL="http://crawl4ai:11235",
        BS_REDIS_URL="redis://redis:6379/0",
        BS_FALLBACK_ENABLED=False,
    )

    strategy = ExtractionStrategy(
        crawl4ai=cast(Crawl4AIClient, FakeCrawl4AI()),
        trafilatura=None,
        settings=settings,
    )

    result = await strategy.extract(_url("https://example.com"), "req-1")
    assert result.extraction_ok is False
    assert result.extracted_by == "none"
    assert result.error is not None and "crawl failure" in result.error


@pytest.mark.asyncio
async def test_trafilatura_extraction() -> None:
    """Test Trafilatura fallback extractor."""
    from butterscout.clients.trafilatura_client import TrafilaturaClient

    html = """
    <html><body>
    <article>
        <h1>Article Title</h1>
        <p>This is the main content of the article. It contains important information.</p>
        <p>Here is another paragraph with more details about the topic.</p>
    </article>
    <nav>Navigation links that should be filtered out</nav>
    <footer>Footer content</footer>
    </body></html>
    """

    settings = Settings(
        BS_SEARXNG_URL="http://searxng:8080",
        BS_CRAWL4AI_URL="http://crawl4ai:11235",
        BS_REDIS_URL="redis://redis:6379/0",
        BS_FALLBACK_TIMEOUT_MS=2000,
        BS_FALLBACK_MAX_WORKERS=2,
    )

    client = TrafilaturaClient(settings)
    await client.connect()

    try:
        content = trafilatura_module._parse(html)
        assert content is not None
        assert len(content) > 0
        # Trafilatura should extract main content
        assert "main content" in content.lower() or "article" in content.lower()
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_trafilatura_full_extraction(settings: Settings) -> None:
    """Test Trafilatura full extraction flow with HTTP fetch."""
    html_content = """
    <html><body>
    <article>
        <h1>Test Article</h1>
        <p>This is test content that should be extracted by Trafilatura.</p>
    </article>
    </body></html>
    """

    respx.get("https://example.com").mock(return_value=Response(200, text=html_content))

    client = TrafilaturaClient(settings)
    await client.connect()

    try:
        result = await client.extract(_url("https://example.com"), "test-traf-123")
        assert result.extraction_ok is True
        assert result.extracted_by == "trafilatura"
        assert result.word_count > 0
        assert len(result.content) > 0
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_trafilatura_empty_html(settings: Settings) -> None:
    """Test Trafilatura with empty/whitespace HTML."""
    html_content = "<html><body></body></html>"

    respx.get("https://example.com").mock(return_value=Response(200, text=html_content))

    client = TrafilaturaClient(settings)
    await client.connect()

    try:
        with pytest.raises(ValueError, match="empty content"):
            await client.extract(_url("https://example.com"), "test-traf-empty")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_trafilatura_http_error(settings: Settings) -> None:
    """Test Trafilatura HTTP error handling."""
    respx.get("https://example.com").mock(
        return_value=Response(500, json={"error": "Server error"})
    )

    client = TrafilaturaClient(settings)
    await client.connect()

    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.extract(_url("https://example.com"), "test-traf-error")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_extraction_strategy_crawl4ai_success(settings: Settings) -> None:
    """Test extraction strategy with successful Crawl4AI."""
    respx.post(f"{settings.BS_CRAWL4AI_URL}/crawl").mock(
        return_value=Response(200, json=_crawl_ok("Content from Crawl4AI primary extractor."))
    )

    crawl4ai = Crawl4AIClient(settings)
    trafilatura = TrafilaturaClient(settings)
    strategy = ExtractionStrategy(crawl4ai, trafilatura, settings)

    await crawl4ai.connect()
    await trafilatura.connect()

    try:
        result = await strategy.extract(_url("https://example.com"), "test-strategy-1")
        assert result.extraction_ok is True
        assert result.extracted_by == "crawl4ai"
        assert result.crawl4ai_failure is None
    finally:
        await crawl4ai.disconnect()
        await trafilatura.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_extraction_strategy_fallback_to_trafilatura(settings: Settings) -> None:
    """Test extraction strategy falls back to Trafilatura when Crawl4AI fails."""
    # Mock Crawl4AI to fail
    respx.post(f"{settings.BS_CRAWL4AI_URL}/crawl").mock(
        return_value=Response(500, json={"error": "Internal error"})
    )

    # Mock successful Trafilatura fetch
    html_content = """
    <html><body>
    <article>
        <p>Fallback content from Trafilatura.</p>
    </article>
    </body></html>
    """
    respx.get("https://example.com").mock(return_value=Response(200, text=html_content))

    crawl4ai = Crawl4AIClient(settings)
    trafilatura = TrafilaturaClient(settings)
    strategy = ExtractionStrategy(crawl4ai, trafilatura, settings)

    await crawl4ai.connect()
    await trafilatura.connect()

    try:
        result = await strategy.extract(_url("https://example.com"), "test-strategy-fallback")
        assert result.extraction_ok is True
        assert result.extracted_by == "trafilatura"
        assert result.crawl4ai_failure == "server_error"
    finally:
        await crawl4ai.disconnect()
        await trafilatura.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_extraction_strategy_both_fail(settings: Settings) -> None:
    """Test extraction strategy when both extractors fail."""
    # Mock Crawl4AI to fail
    respx.post(f"{settings.BS_CRAWL4AI_URL}/crawl").mock(
        return_value=Response(500, json={"error": "Internal error"})
    )

    # Mock Trafilatura to fail
    respx.get("https://example.com").mock(
        return_value=Response(500, json={"error": "Server error"})
    )

    crawl4ai = Crawl4AIClient(settings)
    trafilatura = TrafilaturaClient(settings)
    strategy = ExtractionStrategy(crawl4ai, trafilatura, settings)

    await crawl4ai.connect()
    await trafilatura.connect()

    try:
        result = await strategy.extract(_url("https://example.com"), "test-strategy-both-fail")
        assert result.extraction_ok is False
        assert result.extracted_by == "none"
        assert result.error is not None
    finally:
        await crawl4ai.disconnect()
        await trafilatura.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_extraction_strategy_fallback_disabled(settings: Settings) -> None:
    """Test extraction strategy with fallback disabled."""
    # Modify settings to disable fallback
    settings.BS_FALLBACK_ENABLED = False

    # Mock Crawl4AI to fail
    respx.post(f"{settings.BS_CRAWL4AI_URL}/crawl").mock(
        return_value=Response(500, json={"error": "Internal error"})
    )

    crawl4ai = Crawl4AIClient(settings)
    trafilatura = TrafilaturaClient(settings)
    strategy = ExtractionStrategy(crawl4ai, trafilatura, settings)

    await crawl4ai.connect()
    await trafilatura.connect()

    try:
        result = await strategy.extract(_url("https://example.com"), "test-no-fallback")
        # Should return failed extraction without trying fallback
        assert result.extraction_ok is False
        assert result.extracted_by == "none"
    finally:
        await crawl4ai.disconnect()
        await trafilatura.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_extraction_strategy_crawl4ai_empty_content_fallback(
    settings: Settings,
) -> None:
    """Test extraction strategy falls back when Crawl4AI returns empty content."""
    # Mock Crawl4AI to return empty content
    respx.post(f"{settings.BS_CRAWL4AI_URL}/crawl").mock(
        return_value=Response(200, json=_crawl_ok(""))
    )

    # Mock successful Trafilatura fetch
    html_content = """
    <html><body>
    <article>
        <p>Fallback content from Trafilatura after Crawl4AI empty.</p>
    </article>
    </body></html>
    """
    respx.get("https://example.com").mock(return_value=Response(200, text=html_content))

    crawl4ai = Crawl4AIClient(settings)
    trafilatura = TrafilaturaClient(settings)
    strategy = ExtractionStrategy(crawl4ai, trafilatura, settings)

    await crawl4ai.connect()
    await trafilatura.connect()

    try:
        result = await strategy.extract(_url("https://example.com"), "test-empty-fallback")
        # Should succeed with Trafilatura after Crawl4AI returned empty
        assert result.extraction_ok is True
        assert result.extracted_by == "trafilatura"
        assert result.crawl4ai_failure == "page"
        assert len(result.content) > 0
    finally:
        await crawl4ai.disconnect()
        await trafilatura.disconnect()


@pytest.mark.parametrize(
    ("error", "failure", "metric_reason"),
    [
        (Crawl4AIBusyError("no slot"), "busy", "busy"),
        (Crawl4AIUnavailableError("auth", "HTTP 401"), "auth", "auth"),
        (Crawl4AIUnavailableError("unreachable", "ConnectError"), "unreachable", "unreachable"),
        (TimeoutError("slow page"), "page", "timeout"),
        (ValueError("blocked page"), "page", "error"),
    ],
)
async def test_strategy_records_why_crawl4ai_failed(
    settings: Settings, error: Exception, failure: str, metric_reason: str
) -> None:
    """Every Crawl4AI failure is tagged on the result and counted by reason."""

    class FakeCrawl4AI:
        async def extract(
            self,
            url: HttpUrl,
            request_id: str,
            timeout_ms: int | None = None,
            markdown_filter: str = "raw",
        ) -> ExtractedContent:
            raise error

    labels = {"extractor": "crawl4ai", "reason": metric_reason}
    before = REGISTRY.get_sample_value("butterscout_extraction_failures_total", labels) or 0.0
    settings.BS_FALLBACK_ENABLED = False
    strategy = ExtractionStrategy(cast(Crawl4AIClient, FakeCrawl4AI()), None, settings)

    result = await strategy.extract(_url("https://example.com"), "req")

    assert result.extraction_ok is False
    assert result.crawl4ai_failure == failure
    after = REGISTRY.get_sample_value("butterscout_extraction_failures_total", labels)
    assert after == before + 1


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (Crawl4AIBusyError("Crawl4AI refused for load (HTTP 429)"), "busy"),
        (TimeoutError("slow page"), "timeout"),
    ],
)
async def test_without_fallback_only_a_page_timeout_reads_as_timeout(
    settings: Settings, error: Exception, expected: str
) -> None:
    """Load shedding (busy) subclasses TimeoutError but is not this page timing out."""

    class FakeCrawl4AI:
        async def extract(self, *args: object, **kwargs: object) -> ExtractedContent:
            raise error

    settings.BS_FALLBACK_ENABLED = False
    strategy = ExtractionStrategy(cast(Crawl4AIClient, FakeCrawl4AI()), None, settings)
    result = await strategy.extract(_url("https://example.com"), "req")
    assert (result.error == "timeout") is (expected == "timeout")
