"""Unit tests for cache service."""
from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import ResponseMetadata, SearchResponse
from butterscout.services.cache_service import CacheService
from butterscout.utils.redis_keys import generate_cache_key


@pytest.fixture
def settings() -> Settings:
    """Create test settings with short TTL for testing."""
    return Settings(
        BS_REDIS_URL="valkey://localhost:6379/1",  # Use DB 1 for tests
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_CACHE_TTL_SECONDS=3600,  # 1 hour default
    )


@pytest_asyncio.fixture
async def redis_client(settings: Settings) -> ValkeyClient:
    """Create Redis client fixture (not connected for unit tests)."""
    client = ValkeyClient(settings)
    return client


@pytest_asyncio.fixture
async def cache_service(redis_client: ValkeyClient, settings: Settings) -> CacheService:
    """Create cache service fixture."""
    return CacheService(redis_client, settings)


@pytest.mark.asyncio
async def test_cache_service_initialization(
    cache_service: CacheService, settings: Settings
) -> None:
    """Test that cache service initializes correctly."""
    assert cache_service.redis is not None
    assert cache_service.ttl_seconds == settings.BS_CACHE_TTL_SECONDS
    assert cache_service.settings is settings


@pytest.mark.asyncio
async def test_cache_miss_when_not_connected(cache_service: CacheService) -> None:
    """Test that cache miss is returned when Redis is not connected."""
    request = SearchRequest(query="test query")
    result = await cache_service.get(request, "test-123")

    # Should return None on error, not raise
    assert result is None


@pytest.mark.asyncio
async def test_cache_set_fails_gracefully_when_not_connected(
    cache_service: CacheService,
) -> None:
    """Test that cache set fails gracefully when Redis is not connected."""
    request = SearchRequest(query="test query")
    response = SearchResponse(
        query="test query",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    # Should return False on error, not raise
    success = await cache_service.set(request, response, "test-123")
    assert success is False


@pytest.mark.asyncio
async def test_invalidate_fails_gracefully_when_not_connected(
    cache_service: CacheService,
) -> None:
    """Test that cache invalidation fails gracefully when Redis is not connected."""
    request = SearchRequest(query="test query")

    # Should return False on error, not raise
    result = await cache_service.invalidate(request)
    assert result is False


# Integration tests - require Redis/Valkey running
@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_miss(settings: Settings) -> None:
    """Test cache miss returns None."""
    redis_client = ValkeyClient(settings)
    await redis_client.connect()

    try:
        cache = CacheService(redis_client, settings)

        request = SearchRequest(query="test query miss")
        result = await cache.get(request, "test-123")

        assert result is None
    finally:
        await redis_client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_hit(settings: Settings) -> None:
    """Test cache hit returns stored response."""
    redis_client = ValkeyClient(settings)
    await redis_client.connect()

    try:
        cache = CacheService(redis_client, settings)

        request = SearchRequest(query="test query hit")

        # Create and cache response
        original_response = SearchResponse(
            query="test query hit",
            results=[],
            metadata=ResponseMetadata(
                search_time_ms=100,
                cache_hit=False,
                sources_queried=["searxng"],
            ),
        )

        await cache.set(request, original_response, "test-123")

        # Retrieve from cache
        cached_response = await cache.get(request, "test-123")

        assert cached_response is not None
        assert cached_response.query == "test query hit"
        assert cached_response.metadata.search_time_ms == 100
        assert cached_response.results == []

        # Clean up
        await cache.invalidate(request)
    finally:
        await redis_client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_key_stability(settings: Settings) -> None:
    """Test that identical requests produce same cache key."""
    redis_client = ValkeyClient(settings)
    await redis_client.connect()

    try:
        cache = CacheService(redis_client, settings)

        req1 = SearchRequest(query="test", max_results=10)
        req2 = SearchRequest(query="test", max_results=10)

        key1 = generate_cache_key(req1)
        key2 = generate_cache_key(req2)

        assert key1 == key2

        # Set with first request
        response = SearchResponse(
            query="test",
            results=[],
            metadata=ResponseMetadata(
                search_time_ms=100,
                cache_hit=False,
                sources_queried=["searxng"],
            ),
        )
        await cache.set(req1, response, "test-123")

        # Should get with second request (same key)
        cached = await cache.get(req2, "test-456")
        assert cached is not None
        assert cached.query == "test"

        # Clean up
        await cache.invalidate(req1)
    finally:
        await redis_client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_ttl_expiration(settings: Settings) -> None:
    """Test that cache entries expire after TTL."""
    # Use short TTL for this test
    settings.BS_CACHE_TTL_SECONDS = 1

    redis_client = ValkeyClient(settings)
    await redis_client.connect()

    try:
        cache = CacheService(redis_client, settings)

        request = SearchRequest(query="test expiry")
        response = SearchResponse(
            query="test expiry",
            results=[],
            metadata=ResponseMetadata(
                search_time_ms=100,
                cache_hit=False,
                sources_queried=["searxng"],
            ),
        )

        await cache.set(request, response, "test-123")

        # Should be cached immediately
        cached = await cache.get(request, "test-123")
        assert cached is not None

        # Wait for expiration (TTL + small buffer)
        await asyncio.sleep(2)

        # Should be expired
        cached = await cache.get(request, "test-123")
        assert cached is None
    finally:
        await redis_client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_handles_errors_gracefully(settings: Settings) -> None:
    """Test that cache errors don't break requests."""
    redis_client = ValkeyClient(settings)
    await redis_client.connect()

    cache = CacheService(redis_client, settings)

    # Disconnect Redis to simulate error
    await redis_client.disconnect()

    request = SearchRequest(query="test")

    # Should return None on error, not raise
    result = await cache.get(request, "test-123")
    assert result is None

    # Should return False on set error, not raise
    response = SearchResponse(
        query="test",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )
    success = await cache.set(request, response, "test-123")
    assert success is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_invalidate(settings: Settings) -> None:
    """Test manual cache invalidation."""
    redis_client = ValkeyClient(settings)
    await redis_client.connect()

    try:
        cache = CacheService(redis_client, settings)

        request = SearchRequest(query="test invalidate")
        response = SearchResponse(
            query="test invalidate",
            results=[],
            metadata=ResponseMetadata(
                search_time_ms=100,
                cache_hit=False,
                sources_queried=["searxng"],
            ),
        )

        # Cache response
        await cache.set(request, response, "test-123")

        # Verify it's cached
        cached = await cache.get(request, "test-123")
        assert cached is not None

        # Invalidate
        deleted = await cache.invalidate(request)
        assert deleted is True

        # Should be gone now
        cached = await cache.get(request, "test-123")
        assert cached is None

        # Invalidating again should return False (key doesn't exist)
        deleted = await cache.invalidate(request)
        assert deleted is False
    finally:
        await redis_client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_serialization_deserialization(settings: Settings) -> None:
    """Test that complex responses serialize and deserialize correctly."""
    redis_client = ValkeyClient(settings)
    await redis_client.connect()

    try:
        from butterscout.models.responses import (
            ResultMetadata,
            ResultScores,
            SearchResult,
        )

        cache = CacheService(redis_client, settings)

        request = SearchRequest(query="test serialization")

        # Create a complex response with results
        response = SearchResponse(
            query="test serialization",
            results=[
                SearchResult(
                    title="Test Result 1",
                    url="https://example.com/1",
                    snippet="This is a test snippet",
                    content="Full content here",
                    metadata=ResultMetadata(
                        domain="example.com",
                        word_count=100,
                        extracted_by="crawl4ai",
                        extraction_ok=True,
                    ),
                    scores=ResultScores(search_score=0.95, rank=1),
                    source="searxng",
                ),
                SearchResult(
                    title="Test Result 2",
                    url="https://example.com/2",
                    snippet="Another test snippet",
                    content=None,  # No content
                    metadata=ResultMetadata(
                        domain="example.com",
                        word_count=None,
                        extracted_by="none",
                        extraction_ok=False,
                        extraction_error="timeout",
                    ),
                    scores=ResultScores(search_score=0.85, rank=2),
                    source="searxng",
                ),
            ],
            metadata=ResponseMetadata(
                search_time_ms=250,
                searxng_time_ms=100,
                extraction_time_ms=150,
                cache_hit=False,
                sources_queried=["searxng"],
                rate_limited=False,
            ),
        )

        # Cache it
        await cache.set(request, response, "test-123")

        # Retrieve and verify all fields are intact
        cached = await cache.get(request, "test-123")

        assert cached is not None
        assert cached.query == "test serialization"
        assert len(cached.results) == 2

        # Check first result
        result1 = cached.results[0]
        assert result1.title == "Test Result 1"
        assert str(result1.url) == "https://example.com/1"
        assert result1.snippet == "This is a test snippet"
        assert result1.content == "Full content here"
        assert result1.metadata.domain == "example.com"
        assert result1.metadata.word_count == 100
        assert result1.metadata.extracted_by == "crawl4ai"
        assert result1.metadata.extraction_ok is True
        assert result1.scores.search_score == 0.95
        assert result1.scores.rank == 1

        # Check second result
        result2 = cached.results[1]
        assert result2.title == "Test Result 2"
        assert result2.content is None
        assert result2.metadata.extraction_ok is False
        assert result2.metadata.extraction_error == "timeout"

        # Check metadata
        assert cached.metadata.search_time_ms == 250
        assert cached.metadata.searxng_time_ms == 100
        assert cached.metadata.extraction_time_ms == 150

        # Clean up
        await cache.invalidate(request)
    finally:
        await redis_client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_with_different_request_parameters(settings: Settings) -> None:
    """Test that different request parameters produce different cache keys."""
    redis_client = ValkeyClient(settings)
    await redis_client.connect()

    try:
        cache = CacheService(redis_client, settings)

        # Different queries
        req1 = SearchRequest(query="query 1")
        req2 = SearchRequest(query="query 2")

        response1 = SearchResponse(
            query="query 1",
            results=[],
            metadata=ResponseMetadata(
                search_time_ms=100, cache_hit=False, sources_queried=["searxng"]
            ),
        )
        response2 = SearchResponse(
            query="query 2",
            results=[],
            metadata=ResponseMetadata(
                search_time_ms=200, cache_hit=False, sources_queried=["searxng"]
            ),
        )

        await cache.set(req1, response1, "test-1")
        await cache.set(req2, response2, "test-2")

        # Each should get their own response
        cached1 = await cache.get(req1, "test-1")
        cached2 = await cache.get(req2, "test-2")

        assert cached1 is not None
        assert cached2 is not None
        assert cached1.query == "query 1"
        assert cached2.query == "query 2"
        assert cached1.metadata.search_time_ms == 100
        assert cached2.metadata.search_time_ms == 200

        # Clean up
        await cache.invalidate(req1)
        await cache.invalidate(req2)
    finally:
        await redis_client.disconnect()
