"""Performance tests."""
from __future__ import annotations

import asyncio
import time

import pytest

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import ResponseMetadata, SearchResponse
from butterscout.services.cache_service import CacheService
from butterscout.services.deduplicator import URLDeduplicator


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.integration
async def test_cache_performance(
    redis_client: ValkeyClient, settings: Settings
) -> None:
    """Test cache operations are fast enough"""
    cache = CacheService(redis_client, settings)

    request = SearchRequest(query="performance test")
    response = SearchResponse(
        query="performance test",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    # Measure set operation
    start = time.perf_counter()
    await cache.set(request, response, "perf-test")
    set_duration = time.perf_counter() - start

    # Cache set should be fast (< 100ms for local Redis)
    assert set_duration < 0.1

    # Measure get operation
    start = time.perf_counter()
    await cache.get(request, "perf-test")
    get_duration = time.perf_counter() - start

    # Cache get should be very fast (< 50ms for local Redis)
    assert get_duration < 0.05

    # Cleanup
    await cache.invalidate(request)


@pytest.mark.slow
@pytest.mark.unit
def test_url_normalization_performance() -> None:
    """Test URL normalization is fast"""
    urls = [
        f"https://example{i}.com/page?utm_source=google&id={i}"
        for i in range(1000)
    ]

    start = time.perf_counter()
    for url in urls:
        URLDeduplicator.normalize_url(url)
    duration = time.perf_counter() - start

    # Should handle 1000 URLs in < 100ms
    assert duration < 0.1

    # Per-URL performance should be < 1ms
    avg_per_url = duration / len(urls)
    assert avg_per_url < 0.001


@pytest.mark.slow
@pytest.mark.unit
def test_deduplication_performance() -> None:
    """Test deduplication performance with many results"""
    from typing import cast

    from pydantic import HttpUrl

    from butterscout.models.internal import NormalizedSearchResult

    def _url(url_str: str) -> HttpUrl:
        return cast(HttpUrl, url_str)

    # Create 100 results with some duplicates
    results = []
    for i in range(100):
        # Every 10th result is a duplicate of result 0
        if i % 10 == 0 and i > 0:
            url = "https://example.com/page0"
        else:
            url = f"https://example{i}.com/page{i}"

        results.append(
            NormalizedSearchResult(
                title=f"Result {i}",
                url=_url(url),
                snippet=f"Snippet {i}",
                score=0.9 - (i * 0.001),
            )
        )

    start = time.perf_counter()
    deduplicated = URLDeduplicator.deduplicate(results, "perf-test")
    duration = time.perf_counter() - start

    # Should be very fast (< 10ms for 100 items)
    assert duration < 0.01

    # Should have removed duplicates
    assert len(deduplicated) < len(results)


@pytest.mark.slow
@pytest.mark.unit
def test_cache_key_generation_performance() -> None:
    """Test cache key generation is fast"""
    from butterscout.utils.redis_keys import generate_cache_key

    # Create many different requests
    requests = [
        SearchRequest(query=f"test query {i}", max_results=10)
        for i in range(1000)
    ]

    start = time.perf_counter()
    keys = [generate_cache_key(req) for req in requests]
    duration = time.perf_counter() - start

    # Should handle 1000 keys in < 50ms
    assert duration < 0.05

    # All keys should be unique
    assert len(set(keys)) == len(keys)


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.integration
async def test_concurrent_cache_operations_performance(
    redis_client: ValkeyClient, settings: Settings
) -> None:
    """Test concurrent cache operations performance"""
    cache = CacheService(redis_client, settings)

    async def cache_operation(index: int) -> None:
        """Single cache operation"""
        request = SearchRequest(query=f"concurrent test {index}")
        response = SearchResponse(
            query=f"concurrent test {index}",
            results=[],
            metadata=ResponseMetadata(
                search_time_ms=100,
                cache_hit=False,
                sources_queried=["searxng"],
            ),
        )
        await cache.set(request, response, f"concurrent-{index}")
        await cache.get(request, f"concurrent-{index}")
        await cache.invalidate(request)

    # Run 50 concurrent operations
    start = time.perf_counter()
    await asyncio.gather(*[cache_operation(i) for i in range(50)])
    duration = time.perf_counter() - start

    # 50 operations should complete in reasonable time (< 5 seconds)
    assert duration < 5.0

    # Average per operation should be reasonable
    avg_per_op = duration / 50
    assert avg_per_op < 0.2


@pytest.mark.slow
@pytest.mark.unit
def test_model_validation_performance() -> None:
    """Test model validation doesn't slow down request processing"""
    from butterscout.models.requests import SearchOptions, SearchRequest

    start = time.perf_counter()
    for i in range(1000):
        SearchRequest(
            query=f"test query {i}",
            max_results=10,
            include_content=True,
            options=SearchOptions(
                domains=["example.com", "test.com"],
                language="en",
            ),
        )
    duration = time.perf_counter() - start

    # Should handle 1000 validations in < 100ms
    assert duration < 0.1


@pytest.mark.slow
@pytest.mark.unit
def test_url_normalization_edge_cases_performance() -> None:
    """Test URL normalization performance with complex URLs"""
    # Complex URLs with many tracking params
    complex_urls = [
        f"https://www.example{i}.com/very/long/path/to/page?utm_source=google&utm_medium=cpc&utm_campaign=test&utm_term=keyword&utm_content=ad{i}&id={i}&fbclid=xyz123&gclid=abc456&ref=source&referrer=page"
        for i in range(100)
    ]

    start = time.perf_counter()
    for url in complex_urls:
        URLDeduplicator.normalize_url(url)
    duration = time.perf_counter() - start

    # Should handle 100 complex URLs quickly (< 50ms)
    assert duration < 0.05
