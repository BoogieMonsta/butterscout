"""Tests for extraction clients."""

from __future__ import annotations

import json
from typing import cast

import httpx
import pytest
import respx
from httpx import Response
from pydantic import HttpUrl, TypeAdapter

from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.extraction_strategy import ExtractionStrategy
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent


def _url(url_str: str) -> HttpUrl:
    return cast(HttpUrl, url_str)


def _validated_url(url_str: str) -> HttpUrl:
    return TypeAdapter(HttpUrl).validate_python(url_str)


@pytest.mark.asyncio
@respx.mock
async def test_crawl4ai_success(settings: Settings) -> None:
    """Test successful Crawl4AI extraction."""
    mock_response = {
        "markdown": "This is extracted content from Crawl4AI. It has multiple words here.",
        "success": True,
    }

    route = respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
        return_value=Response(200, json=mock_response)
    )

    client = Crawl4AIClient(settings)
    await client.connect()

    try:
        result = await client.extract(_validated_url("https://example.com"), "test-123")

        assert result.extraction_ok is True
        assert result.extracted_by == "crawl4ai"
        assert result.word_count > 0
        assert "Crawl4AI" in result.content
        assert result.extraction_time_ms > 0
        payload = json.loads(route.calls.last.request.content)
        assert payload["url"] == "https://example.com/"
        assert payload["f"] == "raw"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_extraction_strategy_fallback_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure fallback is invoked when Crawl4AI fails."""

    class FakeCrawl4AI:
        async def extract(
            self, url: HttpUrl, request_id: str, timeout_ms: int | None = None
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
            self, url: HttpUrl, request_id: str, timeout_ms: int | None = None
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
@respx.mock
async def test_crawl4ai_timeout(settings: Settings) -> None:
    """Test Crawl4AI timeout handling."""
    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
        side_effect=httpx.TimeoutException("Request timeout")
    )

    client = Crawl4AIClient(settings)
    await client.connect()

    try:
        with pytest.raises(TimeoutError):
            await client.extract(_url("https://example.com"), "test-timeout")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_crawl4ai_http_error(settings: Settings) -> None:
    """Test Crawl4AI HTTP error handling."""
    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
        return_value=Response(500, json={"error": "Internal server error"})
    )

    client = Crawl4AIClient(settings)
    await client.connect()

    try:
        with pytest.raises(httpx.HTTPStatusError):
            await client.extract(_url("https://example.com"), "test-error")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_crawl4ai_empty_content(settings: Settings) -> None:
    """Test Crawl4AI empty content handling."""
    mock_response = {
        "markdown": "",
        "success": True,
    }

    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
        return_value=Response(200, json=mock_response)
    )

    client = Crawl4AIClient(settings)
    await client.connect()

    try:
        with pytest.raises(ValueError, match="empty content"):
            await client.extract(_url("https://example.com"), "test-empty")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_crawl4ai_whitespace_only_content(settings: Settings) -> None:
    """Test Crawl4AI whitespace-only content handling."""
    mock_response = {
        "markdown": "   \n\t  ",
        "success": True,
    }

    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
        return_value=Response(200, json=mock_response)
    )

    client = Crawl4AIClient(settings)
    await client.connect()

    try:
        with pytest.raises(ValueError, match="empty content"):
            await client.extract(_url("https://example.com"), "test-whitespace")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_crawl4ai_invalid_response_format(settings: Settings) -> None:
    """Test Crawl4AI invalid response format handling."""
    # Return a list instead of dict
    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
        return_value=Response(200, json=["not", "a", "dict"])
    )

    client = Crawl4AIClient(settings)
    await client.connect()

    try:
        with pytest.raises(ValueError, match="Invalid response format"):
            await client.extract(_url("https://example.com"), "test-invalid-format")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_crawl4ai_health_check_success(settings: Settings) -> None:
    """Test Crawl4AI health check success."""
    respx.get(f"{settings.BS_CRAWL4AI_URL}/health").mock(return_value=Response(200))

    client = Crawl4AIClient(settings)
    await client.connect()

    try:
        healthy = await client.health_check()
        assert healthy is True
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_crawl4ai_health_check_failure(settings: Settings) -> None:
    """Test Crawl4AI health check failure."""
    respx.get(f"{settings.BS_CRAWL4AI_URL}/health").mock(return_value=Response(503))

    client = Crawl4AIClient(settings)
    await client.connect()

    try:
        healthy = await client.health_check()
        assert healthy is False
    finally:
        await client.disconnect()


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
        content = client._extract_sync(html)
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
    mock_response = {
        "markdown": "Content from Crawl4AI primary extractor.",
        "success": True,
    }

    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
        return_value=Response(200, json=mock_response)
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
    finally:
        await crawl4ai.disconnect()
        await trafilatura.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_extraction_strategy_fallback_to_trafilatura(settings: Settings) -> None:
    """Test extraction strategy falls back to Trafilatura when Crawl4AI fails."""
    # Mock Crawl4AI to fail
    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
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
    finally:
        await crawl4ai.disconnect()
        await trafilatura.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_extraction_strategy_both_fail(settings: Settings) -> None:
    """Test extraction strategy when both extractors fail."""
    # Mock Crawl4AI to fail
    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
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
    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
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
    respx.post(f"{settings.BS_CRAWL4AI_URL}/md").mock(
        return_value=Response(200, json={"markdown": "", "success": True})
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
        assert len(result.content) > 0
    finally:
        await crawl4ai.disconnect()
        await trafilatura.disconnect()
