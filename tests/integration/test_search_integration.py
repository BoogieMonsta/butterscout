"""Integration tests for the search endpoint."""
from __future__ import annotations

from typing import Any, Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from butterscout.models.internal import ExtractedContent, NormalizedSearchResult
from butterscout.models.responses import (
    ResponseMetadata,
    ResultMetadata,
    ResultScores,
    SearchResponse,
    SearchResult,
)


@pytest.fixture
def mock_app_state() -> Generator[MagicMock, None, None]:
    """Mock app_state for testing."""
    with patch("butterscout.routers.search.app_state") as mock_state:
        # Mock settings
        mock_state.settings = MagicMock()
        mock_state.settings.BS_API_KEY = None
        mock_state.settings.BS_RATE_LIMIT_PER_HOUR = 60
        mock_state.settings.BS_API_KEY_RATE_LIMIT_PER_HOUR = 600
        mock_state.settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR = 10000
        mock_state.settings.allowed_domains_list = []
        mock_state.settings.blocked_domains_list = []
        mock_state.settings.BS_MAX_CONCURRENT_EXTRACTIONS = 4

        # Mock clients
        mock_state.redis_client = MagicMock()
        mock_state.searxng_client = MagicMock()
        mock_state.extraction_strategy = MagicMock()

        yield mock_state


@pytest.mark.asyncio
async def test_cache_miss_fetch_and_store_flow(mock_app_state: MagicMock) -> None:
    """Test complete flow: cache miss -> fetch from SearXNG -> extract -> store in cache."""
    from butterscout.main import app

    # Mock search results from SearXNG
    search_results = [
        NormalizedSearchResult(
            title="Test Result 1",
            url=HttpUrl("https://example.com/page1"),
            snippet="Test snippet 1",
            score=0.95,
            source="searxng",
        ),
        NormalizedSearchResult(
            title="Test Result 2",
            url=HttpUrl("https://example.com/page2"),
            snippet="Test snippet 2",
            score=0.85,
            source="searxng",
        ),
    ]

    mock_app_state.searxng_client.search = AsyncMock(return_value=search_results)

    # Track if cache.set was called
    cache_set_called = False
    cached_request = None
    cached_response = None

    async def mock_cache_set(
        request: Any, response: SearchResponse, request_id: str
    ) -> bool:
        nonlocal cache_set_called, cached_request, cached_response
        cache_set_called = True
        cached_request = request
        cached_response = response
        return True

    # Mock rate limiter to allow
    with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        # Mock cache service (miss on get, track set)
        with patch("butterscout.routers.search.CacheService") as mock_cache_class:
            mock_cache = mock_cache_class.return_value
            mock_cache.get = AsyncMock(return_value=None)  # Cache miss
            mock_cache.set = AsyncMock(side_effect=mock_cache_set)

            # Mock extraction orchestrator
            with patch(
                "butterscout.routers.search.ExtractionOrchestrator"
            ) as mock_orch_class:
                mock_orch = mock_orch_class.return_value
                mock_orch.extract_all = AsyncMock(
                    return_value=[
                        ExtractedContent(
                            url=HttpUrl("https://example.com/page1"),
                            content="Full content from page 1",
                            word_count=50,
                            extracted_by="crawl4ai",
                            extraction_ok=True,
                            extraction_time_ms=100,
                        ),
                        ExtractedContent(
                            url=HttpUrl("https://example.com/page2"),
                            content="Full content from page 2",
                            word_count=75,
                            extracted_by="crawl4ai",
                            extraction_ok=True,
                            extraction_time_ms=150,
                        ),
                    ]
                )

                # Mock deduplicator and ranker to pass through
                with patch(
                    "butterscout.routers.search.URLDeduplicator"
                ) as mock_dedup:
                    mock_dedup.deduplicate = MagicMock(
                        side_effect=lambda results, request_id: results
                    )

                    with patch("butterscout.routers.search.Ranker") as mock_ranker_class:
                        mock_ranker = mock_ranker_class.return_value
                        mock_ranker.rank = MagicMock(
                            side_effect=lambda results, request_id: results
                        )

                        client = TestClient(app, raise_server_exceptions=False)
                        response = client.post(
                            "/api/v1/search",
                            json={"query": "test query", "include_content": True},
                        )

                        # Verify response
                        assert response.status_code == 200
                        data = response.json()

                        # Verify cache miss
                        assert data["metadata"]["cache_hit"] is False

                        # Verify SearXNG was called
                        mock_app_state.searxng_client.search.assert_called_once()

                        # Verify extraction was called
                        mock_orch.extract_all.assert_called_once()

                        # Verify cache.set was called with the response
                        assert cache_set_called is True
                        assert cached_request is not None
                        assert cached_response is not None
                        assert cached_response.query == "test query"
                        assert len(cached_response.results) == 2


@pytest.mark.asyncio
async def test_extraction_failure_partial_results(mock_app_state: MagicMock) -> None:
    """Test that extraction failures don't break the request - partial results are returned."""
    from butterscout.main import app

    # Mock search results
    search_results = [
        NormalizedSearchResult(
            title="Good Result",
            url=HttpUrl("https://example.com/good"),
            snippet="This one works",
            score=0.95,
            source="searxng",
        ),
        NormalizedSearchResult(
            title="Bad Result",
            url=HttpUrl("https://example.com/bad"),
            snippet="This one fails",
            score=0.85,
            source="searxng",
        ),
        NormalizedSearchResult(
            title="Another Good Result",
            url=HttpUrl("https://example.com/good2"),
            snippet="This one also works",
            score=0.75,
            source="searxng",
        ),
    ]

    mock_app_state.searxng_client.search = AsyncMock(return_value=search_results)

    # Mock rate limiter
    with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        # Mock cache miss
        with patch("butterscout.routers.search.CacheService") as mock_cache_class:
            mock_cache = mock_cache_class.return_value
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock(return_value=True)

            # Mock extraction orchestrator with partial failures
            with patch(
                "butterscout.routers.search.ExtractionOrchestrator"
            ) as mock_orch_class:
                mock_orch = mock_orch_class.return_value
                mock_orch.extract_all = AsyncMock(
                    return_value=[
                        ExtractedContent(
                            url=HttpUrl("https://example.com/good"),
                            content="Good content",
                            word_count=50,
                            extracted_by="crawl4ai",
                            extraction_ok=True,
                            extraction_time_ms=100,
                        ),
                        ExtractedContent(
                            url=HttpUrl("https://example.com/bad"),
                            content="",
                            word_count=0,
                            extracted_by="none",
                            extraction_ok=False,
                            extraction_time_ms=0,
                            error="Timeout",
                        ),
                        ExtractedContent(
                            url=HttpUrl("https://example.com/good2"),
                            content="More good content",
                            word_count=75,
                            extracted_by="trafilatura",
                            extraction_ok=True,
                            extraction_time_ms=200,
                        ),
                    ]
                )

                # Mock deduplicator and ranker
                with patch(
                    "butterscout.routers.search.URLDeduplicator"
                ) as mock_dedup:
                    mock_dedup.deduplicate = MagicMock(
                        side_effect=lambda results, request_id: results
                    )

                    with patch("butterscout.routers.search.Ranker") as mock_ranker_class:
                        mock_ranker = mock_ranker_class.return_value
                        mock_ranker.rank = MagicMock(
                            side_effect=lambda results, request_id: results
                        )

                        client = TestClient(app, raise_server_exceptions=False)
                        response = client.post(
                            "/api/v1/search",
                            json={"query": "test query", "include_content": True},
                        )

                        # Verify response is successful despite partial failures
                        assert response.status_code == 200
                        data = response.json()

                        # Verify all 3 results are present
                        assert len(data["results"]) == 3

                        # Verify extraction status flags
                        results = data["results"]
                        assert results[0]["metadata"]["extraction_ok"] is True
                        assert results[0]["content"] is not None

                        assert results[1]["metadata"]["extraction_ok"] is False
                        assert results[1]["content"] is None  # Failed extraction

                        assert results[2]["metadata"]["extraction_ok"] is True
                        assert results[2]["content"] is not None


@pytest.mark.asyncio
async def test_domain_filtering(mock_app_state: MagicMock) -> None:
    """Test that domain filtering is applied to search results."""
    from butterscout.main import app

    # Configure domain filtering
    mock_app_state.settings.allowed_domains_list = ["example.com"]
    mock_app_state.settings.blocked_domains_list = ["blocked.com"]

    # Mock search results with mixed domains
    search_results = [
        NormalizedSearchResult(
            title="Allowed Domain",
            url=HttpUrl("https://example.com/page1"),
            snippet="This should pass",
            score=0.95,
            source="searxng",
        ),
        NormalizedSearchResult(
            title="Different Allowed Domain",
            url=HttpUrl("https://www.example.com/page2"),
            snippet="This should also pass",
            score=0.90,
            source="searxng",
        ),
        NormalizedSearchResult(
            title="Blocked Domain",
            url=HttpUrl("https://blocked.com/page3"),
            snippet="This should be filtered out",
            score=0.85,
            source="searxng",
        ),
        NormalizedSearchResult(
            title="Other Domain",
            url=HttpUrl("https://other.com/page4"),
            snippet="This should be filtered (not in allowed list)",
            score=0.80,
            source="searxng",
        ),
    ]

    mock_app_state.searxng_client.search = AsyncMock(return_value=search_results)

    # Mock rate limiter
    with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        # Mock cache miss
        with patch("butterscout.routers.search.CacheService") as mock_cache_class:
            mock_cache = mock_cache_class.return_value
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock(return_value=True)

            # Mock deduplicator and ranker
            with patch("butterscout.routers.search.URLDeduplicator") as mock_dedup:
                mock_dedup.deduplicate = MagicMock(
                    side_effect=lambda results, request_id: results
                )

                with patch("butterscout.routers.search.Ranker") as mock_ranker_class:
                    mock_ranker = mock_ranker_class.return_value
                    mock_ranker.rank = MagicMock(
                        side_effect=lambda results, request_id: results
                    )

                    client = TestClient(app, raise_server_exceptions=False)
                    response = client.post(
                        "/api/v1/search",
                        json={
                            "query": "test query",
                            "include_content": False,  # Skip extraction
                        },
                    )

                    # Verify response
                    assert response.status_code == 200
                    data = response.json()

                    # Only 2 results should pass (both example.com)
                    assert len(data["results"]) == 2

                    # Verify the URLs
                    result_urls = [r["url"] for r in data["results"]]
                    assert "https://example.com/page1" in result_urls
                    assert "https://www.example.com/page2" in result_urls

                    # Verify blocked and other domains were filtered
                    assert "https://blocked.com/page3" not in result_urls
                    assert "https://other.com/page4" not in result_urls


@pytest.mark.asyncio
async def test_rate_limit_headers_on_auth_failure(mock_app_state: MagicMock) -> None:
    """Test that 401 responses include rate limit headers."""
    from butterscout.main import app

    # Enable authentication
    mock_app_state.settings.BS_API_KEY = "test-secret-key"

    # Mock rate limiter to allow (so we get past rate limit check)
    with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 45, 60, 1234567890)
        )

        client = TestClient(app, raise_server_exceptions=False)

        # Request without API key
        response = client.post("/api/v1/search", json={"query": "test"})

        # Should be 401
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"

        # MUST include rate limit headers
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers
        assert "WWW-Authenticate" in response.headers

        # Verify header values
        assert response.headers["X-RateLimit-Limit"] == "60"
        assert response.headers["X-RateLimit-Remaining"] == "45"


@pytest.mark.asyncio
async def test_complete_happy_path_flow(mock_app_state: MagicMock) -> None:
    """Integration test of the complete happy path flow."""
    from butterscout.main import app

    # Mock all components for complete flow
    search_results = [
        NormalizedSearchResult(
            title="Result 1",
            url=HttpUrl("https://example.com/1"),
            snippet="Snippet 1",
            score=0.95,
            source="searxng",
        ),
    ]

    mock_app_state.searxng_client.search = AsyncMock(return_value=search_results)

    with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        with patch("butterscout.routers.search.CacheService") as mock_cache_class:
            mock_cache = mock_cache_class.return_value
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock(return_value=True)

            with patch(
                "butterscout.routers.search.ExtractionOrchestrator"
            ) as mock_orch_class:
                mock_orch = mock_orch_class.return_value
                mock_orch.extract_all = AsyncMock(
                    return_value=[
                        ExtractedContent(
                            url=HttpUrl("https://example.com/1"),
                            content="Content",
                            word_count=50,
                            extracted_by="crawl4ai",
                            extraction_ok=True,
                            extraction_time_ms=100,
                        )
                    ]
                )

                with patch(
                    "butterscout.routers.search.URLDeduplicator"
                ) as mock_dedup:
                    mock_dedup.deduplicate = MagicMock(
                        side_effect=lambda r, rid: r
                    )

                    with patch("butterscout.routers.search.Ranker") as mock_ranker_class:
                        mock_ranker = mock_ranker_class.return_value
                        mock_ranker.rank = MagicMock(side_effect=lambda r, rid: r)

                        client = TestClient(app, raise_server_exceptions=False)
                        response = client.post(
                            "/api/v1/search", json={"query": "test"}
                        )

                        # Verify success
                        assert response.status_code == 200

                        # Verify response structure
                        data = response.json()
                        assert "query" in data
                        assert "results" in data
                        assert "metadata" in data

                        # Verify metadata
                        assert data["metadata"]["cache_hit"] is False
                        assert data["metadata"]["api_version"] == "v1"
                        assert "search_time_ms" in data["metadata"]
                        assert "searxng_time_ms" in data["metadata"]
                        assert "extraction_time_ms" in data["metadata"]

                        # Verify results
                        assert len(data["results"]) == 1
                        result = data["results"][0]
                        assert result["title"] == "Result 1"
                        assert result["url"] == "https://example.com/1"
                        assert result["content"] is not None
                        assert result["metadata"]["extraction_ok"] is True

                        # Verify headers
                        assert "X-RateLimit-Limit" in response.headers
                        assert "X-RateLimit-Remaining" in response.headers
                        assert "X-Request-ID" in response.headers
