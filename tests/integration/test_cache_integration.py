"""Integration tests for cache service with real Redis instance.

These tests require a running Redis/Valkey instance.
Run with: pytest -m integration tests/integration/test_cache_integration.py
"""
from __future__ import annotations

import asyncio
import time

import pytest
import pytest_asyncio

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.models.requests import SearchOptions, SearchRequest
from butterscout.models.responses import (
    ResponseMetadata,
    ResultMetadata,
    ResultScores,
    SearchResponse,
    SearchResult,
)
from butterscout.services.cache_service import CacheService


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        BS_REDIS_URL="valkey://localhost:6379/1",  # Use DB 1 for tests
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_CACHE_TTL_SECONDS=3600,
    )


@pytest_asyncio.fixture
async def redis_client(settings: Settings) -> ValkeyClient:
    """Create and connect Redis client."""
    client = ValkeyClient(settings)
    await client.connect()
    yield client
    await client.disconnect()


@pytest_asyncio.fixture
async def cache_service(
    redis_client: ValkeyClient, settings: Settings
) -> CacheService:
    """Create cache service with connected Redis client."""
    return CacheService(redis_client, settings)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_round_trip(cache_service: CacheService) -> None:
    """Test complete cache round trip: set -> get -> invalidate."""
    request = SearchRequest(query="integration test query")
    response = SearchResponse(
        query="integration test query",
        results=[
            SearchResult(
                title="Test Result",
                url="https://example.com",
                snippet="Test snippet",
                content="Test content",
                metadata=ResultMetadata(
                    domain="example.com",
                    word_count=50,
                    extracted_by="crawl4ai",
                    extraction_ok=True,
                ),
                scores=ResultScores(search_score=0.95, rank=1),
                source="searxng",
            )
        ],
        metadata=ResponseMetadata(
            search_time_ms=150,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    try:
        # Set cache
        set_success = await cache_service.set(request, response, "integration-1")
        assert set_success is True

        # Get from cache
        cached = await cache_service.get(request, "integration-1")
        assert cached is not None
        assert cached.query == "integration test query"
        assert len(cached.results) == 1
        assert cached.results[0].title == "Test Result"

        # Invalidate
        invalidated = await cache_service.invalidate(request)
        assert invalidated is True

        # Should be gone
        cached_after = await cache_service.get(request, "integration-1")
        assert cached_after is None
    finally:
        # Cleanup in case test fails
        await cache_service.invalidate(request)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_ttl_behavior(settings: Settings, redis_client: ValkeyClient) -> None:
    """Test TTL behavior over time."""
    # Use short TTL for this test
    settings.BS_CACHE_TTL_SECONDS = 2
    cache_service = CacheService(redis_client, settings)

    request = SearchRequest(query="ttl test")
    response = SearchResponse(
        query="ttl test",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    try:
        # Cache with 2 second TTL
        await cache_service.set(request, response, "ttl-test")

        # Should be available immediately
        cached = await cache_service.get(request, "ttl-test")
        assert cached is not None

        # Wait 1 second (still within TTL)
        await asyncio.sleep(1)
        cached = await cache_service.get(request, "ttl-test")
        assert cached is not None  # Still there

        # Wait another 2 seconds (should expire)
        await asyncio.sleep(2)
        cached = await cache_service.get(request, "ttl-test")
        assert cached is None  # Expired
    finally:
        await cache_service.invalidate(request)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_large_response_caching(cache_service: CacheService) -> None:
    """Test caching large responses with many results."""
    request = SearchRequest(query="large response test", max_results=25)

    # Create response with many results
    results = []
    for i in range(25):
        results.append(
            SearchResult(
                title=f"Result {i}",
                url=f"https://example.com/{i}",
                snippet=f"Snippet for result {i}" * 10,  # Make it larger
                content=f"Content for result {i}\n" * 100,  # ~2KB per result
                metadata=ResultMetadata(
                    domain="example.com",
                    word_count=1000 + i,
                    extracted_by="crawl4ai",
                    extraction_ok=True,
                ),
                scores=ResultScores(search_score=0.95 - i * 0.01, rank=i + 1),
                source="searxng",
            )
        )

    response = SearchResponse(
        query="large response test",
        results=results,
        metadata=ResponseMetadata(
            search_time_ms=500,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    try:
        # Cache large response
        start_time = time.time()
        set_success = await cache_service.set(request, response, "large-test")
        set_duration_ms = (time.time() - start_time) * 1000
        assert set_success is True

        # Should be fast enough (< 100ms for local Redis)
        assert set_duration_ms < 200, f"Cache set took {set_duration_ms}ms (too slow)"

        # Retrieve large response
        start_time = time.time()
        cached = await cache_service.get(request, "large-test")
        get_duration_ms = (time.time() - start_time) * 1000
        assert cached is not None

        # Should be fast enough (< 50ms for local Redis)
        assert get_duration_ms < 100, f"Cache get took {get_duration_ms}ms (too slow)"

        # Verify all data is intact
        assert len(cached.results) == 25
        assert cached.results[0].title == "Result 0"
        assert cached.results[24].title == "Result 24"
        assert "Content for result 10" in (cached.results[10].content or "")
    finally:
        await cache_service.invalidate(request)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_cache_operations(cache_service: CacheService) -> None:
    """Test concurrent cache operations don't interfere."""

    async def cache_operation(index: int) -> bool:
        """Perform cache operation for a specific index."""
        request = SearchRequest(query=f"concurrent test {index}")
        response = SearchResponse(
            query=f"concurrent test {index}",
            results=[],
            metadata=ResponseMetadata(
                search_time_ms=100 + index,
                cache_hit=False,
                sources_queried=["searxng"],
            ),
        )

        # Set
        await cache_service.set(request, response, f"concurrent-{index}")

        # Get
        cached = await cache_service.get(request, f"concurrent-{index}")

        # Verify
        if cached is None:
            return False

        # Clean up
        await cache_service.invalidate(request)

        return (
            cached.query == f"concurrent test {index}"
            and cached.metadata.search_time_ms == 100 + index
        )

    # Run 10 concurrent operations
    tasks = [cache_operation(i) for i in range(10)]
    results = await asyncio.gather(*tasks)

    # All should succeed
    assert all(results), "Some concurrent operations failed"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_with_search_options(cache_service: CacheService) -> None:
    """Test that cache properly handles different search options."""
    base_query = "test with options"

    # Different options should produce different cache keys
    req1 = SearchRequest(
        query=base_query,
        options=SearchOptions(domains=["example.com"]),
    )
    req2 = SearchRequest(
        query=base_query,
        options=SearchOptions(domains=["test.com"]),
    )
    req3 = SearchRequest(
        query=base_query,
        options=SearchOptions(language="es"),
    )

    response1 = SearchResponse(
        query=base_query,
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100, cache_hit=False, sources_queried=["searxng"]
        ),
    )
    response2 = SearchResponse(
        query=base_query,
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=200, cache_hit=False, sources_queried=["searxng"]
        ),
    )
    response3 = SearchResponse(
        query=base_query,
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=300, cache_hit=False, sources_queried=["searxng"]
        ),
    )

    try:
        # Cache all three
        await cache_service.set(req1, response1, "options-1")
        await cache_service.set(req2, response2, "options-2")
        await cache_service.set(req3, response3, "options-3")

        # Each should get their own response
        cached1 = await cache_service.get(req1, "options-1")
        cached2 = await cache_service.get(req2, "options-2")
        cached3 = await cache_service.get(req3, "options-3")

        assert cached1 is not None
        assert cached2 is not None
        assert cached3 is not None

        # Verify they got the right responses
        assert cached1.metadata.search_time_ms == 100
        assert cached2.metadata.search_time_ms == 200
        assert cached3.metadata.search_time_ms == 300
    finally:
        await cache_service.invalidate(req1)
        await cache_service.invalidate(req2)
        await cache_service.invalidate(req3)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_performance_metrics(
    cache_service: CacheService, redis_client: ValkeyClient
) -> None:
    """Test cache performance meets requirements."""
    request = SearchRequest(query="performance test")
    response = SearchResponse(
        query="performance test",
        results=[
            SearchResult(
                title="Test",
                url="https://example.com",
                snippet="Test snippet",
                content="Test content",
                metadata=ResultMetadata(
                    domain="example.com",
                    word_count=50,
                    extracted_by="crawl4ai",
                    extraction_ok=True,
                ),
                scores=ResultScores(search_score=0.95, rank=1),
                source="searxng",
            )
        ],
        metadata=ResponseMetadata(
            search_time_ms=150,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    try:
        # Measure cache set performance
        set_times = []
        for i in range(10):
            start = time.time()
            await cache_service.set(request, response, f"perf-{i}")
            duration_ms = (time.time() - start) * 1000
            set_times.append(duration_ms)

        avg_set_time = sum(set_times) / len(set_times)
        print(f"\nAverage cache set time: {avg_set_time:.2f}ms")

        # Should be under 10ms requirement
        assert avg_set_time < 50, f"Cache set too slow: {avg_set_time}ms"

        # Measure cache get performance
        get_times = []
        for i in range(10):
            start = time.time()
            cached = await cache_service.get(request, f"perf-{i}")
            duration_ms = (time.time() - start) * 1000
            get_times.append(duration_ms)
            assert cached is not None

        avg_get_time = sum(get_times) / len(get_times)
        print(f"Average cache get time: {avg_get_time:.2f}ms")

        # Should be under 5ms requirement
        assert avg_get_time < 20, f"Cache get too slow: {avg_get_time}ms"

    finally:
        # Cleanup
        await cache_service.invalidate(request)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_survives_redis_reconnection(settings: Settings) -> None:
    """Test that cached data survives Redis reconnection."""
    # First connection
    client1 = ValkeyClient(settings)
    await client1.connect()
    cache1 = CacheService(client1, settings)

    request = SearchRequest(query="reconnection test")
    response = SearchResponse(
        query="reconnection test",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    try:
        # Cache with first connection
        await cache1.set(request, response, "reconnect-1")

        # Disconnect
        await client1.disconnect()

        # New connection
        client2 = ValkeyClient(settings)
        await client2.connect()
        cache2 = CacheService(client2, settings)

        # Should still be able to retrieve (data persists in Redis)
        cached = await cache2.get(request, "reconnect-2")
        assert cached is not None
        assert cached.query == "reconnection test"

        # Cleanup
        await cache2.invalidate(request)
        await client2.disconnect()
    finally:
        # Ensure cleanup
        if client1.valkey:
            try:
                await client1.disconnect()
            except Exception:
                pass
