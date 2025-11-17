"""Unit tests for the search endpoint."""
from __future__ import annotations

from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from butterscout.models.internal import NormalizedSearchResult
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

        # Mock clients
        mock_state.redis_client = MagicMock()
        mock_state.searxng_client = MagicMock()
        mock_state.extraction_strategy = MagicMock()

        yield mock_state


def test_search_validation_empty_query() -> None:
    """Test request validation with empty query."""
    from butterscout.main import app

    client = TestClient(app, raise_server_exceptions=False)

    # Empty query should fail validation
    response = client.post("/api/v1/search", json={"query": ""})
    assert response.status_code == 422

    # Whitespace-only query should fail
    response = client.post("/api/v1/search", json={"query": "   "})
    assert response.status_code == 422


def test_search_validation_max_results() -> None:
    """Test request validation with invalid max_results."""
    from butterscout.main import app

    client = TestClient(app, raise_server_exceptions=False)

    # Too many results should fail
    response = client.post("/api/v1/search", json={
        "query": "test",
        "max_results": 100,
    })
    assert response.status_code == 422

    # Zero results should fail
    response = client.post("/api/v1/search", json={
        "query": "test",
        "max_results": 0,
    })
    assert response.status_code == 422

    # Negative results should fail
    response = client.post("/api/v1/search", json={
        "query": "test",
        "max_results": -1,
    })
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_search_authentication_required(mock_app_state: MagicMock) -> None:
    """Test that authentication is enforced when API key is set."""
    from butterscout.main import app

    # Set API key requirement
    mock_app_state.settings.BS_API_KEY = "test-api-key-12345"

    # Mock rate limiter to allow (since rate limiting happens before auth now)
    with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        client = TestClient(app, raise_server_exceptions=False)

        # Request without API key should fail
        response = client.post("/api/v1/search", json={"query": "test"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"
        assert "WWW-Authenticate" in response.headers
        # Verify rate limit headers are included on 401
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers

        # Request with wrong API key should fail
        response = client.post(
            "/api/v1/search",
            json={"query": "test"},
            headers={"x-api-key": "wrong-key"}
        )
        assert response.status_code == 401
        # Verify rate limit headers on wrong key too
        assert "X-RateLimit-Limit" in response.headers


@pytest.mark.asyncio
async def test_search_cache_hit(mock_app_state: MagicMock) -> None:
    """Test that cache hits return immediately without calling SearXNG."""
    from butterscout.main import app

    # Mock cache hit
    cached_response = SearchResponse(
        query="test query",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=50,
            searxng_time_ms=20,
            extraction_time_ms=None,
            cache_hit=False,  # Will be set to True in endpoint
            sources_queried=["searxng"],
            rate_limited=False,
        ),
    )

    # Mock rate limiter to allow request
    with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        # Mock cache service to return cached response
        with patch("butterscout.routers.search.CacheService") as mock_cache_class:
            mock_cache = mock_cache_class.return_value
            mock_cache.get = AsyncMock(return_value=cached_response)

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/search", json={"query": "test query"})

            assert response.status_code == 200
            data = response.json()

            # Verify cache_hit is True
            assert data["metadata"]["cache_hit"] is True

            # Verify SearXNG was not called
            mock_app_state.searxng_client.search.assert_not_called()


@pytest.mark.asyncio
async def test_search_without_content(mock_app_state: MagicMock) -> None:
    """Test search with include_content=false."""
    from butterscout.main import app

    # Mock search results
    search_results = [
        NormalizedSearchResult(
            title="Test Result",
            url=HttpUrl("https://example.com"),
            snippet="Test snippet",
            score=1.0,
            source="searxng",
        )
    ]

    mock_app_state.searxng_client.search = AsyncMock(return_value=search_results)

    # Mock rate limiter
    with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        # Mock cache service (miss)
        with patch("butterscout.routers.search.CacheService") as mock_cache_class:
            mock_cache = mock_cache_class.return_value
            mock_cache.get = AsyncMock(return_value=None)
            mock_cache.set = AsyncMock(return_value=True)

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/search", json={
                "query": "test query",
                "include_content": False,
            })

            assert response.status_code == 200
            data = response.json()

            # Results should have no content
            for result in data["results"]:
                assert result["content"] is None

            # extraction_time_ms should be None
            assert data["metadata"]["extraction_time_ms"] is None


@pytest.mark.asyncio
async def test_rate_limit_headers() -> None:
    """Test that rate limit headers are included in response."""
    from butterscout.main import app

    with patch("butterscout.routers.search.app_state") as mock_state:
        mock_state.settings = MagicMock()
        mock_state.settings.BS_API_KEY = None
        mock_state.settings.allowed_domains_list = []
        mock_state.settings.blocked_domains_list = []

        # Mock rate limiter
        with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
            mock_limiter = mock_limiter_class.return_value
            mock_limiter.check_rate_limit = AsyncMock(
                return_value=(True, None, 45, 60, 1234567890)
            )

            # Mock cache service (hit to return quickly)
            with patch("butterscout.routers.search.CacheService") as mock_cache_class:
                mock_cache = mock_cache_class.return_value
                cached_response = SearchResponse(
                    query="test",
                    results=[],
                    metadata=ResponseMetadata(
                        search_time_ms=10,
                        cache_hit=False,
                        sources_queried=["searxng"],
                        rate_limited=False,
                    ),
                )
                mock_cache.get = AsyncMock(return_value=cached_response)

                client = TestClient(app, raise_server_exceptions=False)
                response = client.post("/api/v1/search", json={"query": "test"})

                # Check rate limit headers
                assert "X-RateLimit-Limit" in response.headers
                assert "X-RateLimit-Remaining" in response.headers
                assert "X-RateLimit-Reset" in response.headers
                assert response.headers["X-RateLimit-Limit"] == "60"
                assert response.headers["X-RateLimit-Remaining"] == "45"


@pytest.mark.asyncio
async def test_rate_limit_exceeded() -> None:
    """Test 429 response when rate limit is exceeded."""
    from butterscout.main import app

    with patch("butterscout.routers.search.app_state") as mock_state:
        mock_state.settings = MagicMock()
        mock_state.settings.BS_API_KEY = None

        # Mock rate limiter to deny request
        with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
            mock_limiter = mock_limiter_class.return_value
            mock_limiter.check_rate_limit = AsyncMock(
                return_value=(False, 3600, 0, 60, 1234567890)
            )

            client = TestClient(app, raise_server_exceptions=False)
            response = client.post("/api/v1/search", json={"query": "test"})

            assert response.status_code == 429
            data = response.json()
            assert data["error"]["code"] == "RATE_LIMITED"
            assert "Retry-After" in response.headers
            assert response.headers["Retry-After"] == "3600"


@pytest.mark.asyncio
async def test_searxng_failure() -> None:
    """Test 502 response when SearXNG fails."""
    from butterscout.main import app

    with patch("butterscout.routers.search.app_state") as mock_state:
        mock_state.settings = MagicMock()
        mock_state.settings.BS_API_KEY = None
        mock_state.searxng_client = MagicMock()

        # Mock SearXNG to fail
        mock_state.searxng_client.search = AsyncMock(
            side_effect=Exception("SearXNG connection failed")
        )

        # Mock rate limiter to allow
        with patch("butterscout.routers.search.RateLimiter") as mock_limiter_class:
            mock_limiter = mock_limiter_class.return_value
            mock_limiter.check_rate_limit = AsyncMock(
                return_value=(True, None, 59, 60, 1234567890)
            )

            # Mock cache miss
            with patch("butterscout.routers.search.CacheService") as mock_cache_class:
                mock_cache = mock_cache_class.return_value
                mock_cache.get = AsyncMock(return_value=None)

                client = TestClient(app, raise_server_exceptions=False)
                response = client.post("/api/v1/search", json={"query": "test"})

                assert response.status_code == 502
                data = response.json()
                assert data["error"]["code"] == "UPSTREAM_ERROR"
                assert data["error"]["details"]["component"] == "searxng"


@pytest.mark.asyncio
async def test_request_id_in_response() -> None:
    """Test that request ID is included in response metadata."""
    from butterscout.main import app

    client = TestClient(app, raise_server_exceptions=False)

    # Make any request (will fail but that's ok)
    response = client.post("/api/v1/search", json={"query": ""})

    # Request ID should be in response headers
    assert "X-Request-ID" in response.headers
    assert "X-Response-Time" in response.headers
