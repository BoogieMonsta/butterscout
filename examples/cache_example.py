"""Example demonstrating cache service usage.

This example shows:
1. Cache miss → upstream query → cache set
2. Cache hit → fast response

To run: uv run python examples/cache_example.py
Requires: Redis/Valkey running on localhost:6379
"""
import asyncio
import time

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import ResponseMetadata, SearchResponse
from butterscout.services.cache_service import CacheService


async def simulate_slow_search(request: SearchRequest) -> SearchResponse:
    """Simulate a slow upstream search (e.g., SearXNG + extraction)."""
    print(f"  ⏳ Simulating slow upstream search for: '{request.query}'")
    await asyncio.sleep(0.5)  # Simulate 500ms search
    return SearchResponse(
        query=request.query,
        results=[],  # Simplified for demo
        metadata=ResponseMetadata(
            search_time_ms=500,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )


async def main() -> None:
    """Run cache demonstration."""
    print("🔍 Cache Service Demo\n")

    # Setup
    settings = Settings(
        BS_REDIS_URL="valkey://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_CACHE_TTL_SECONDS=3600,  # 1 hour
    )

    redis_client = ValkeyClient(settings)
    await redis_client.connect()

    try:
        cache_service = CacheService(redis_client, settings)
        request = SearchRequest(query="butterscout caching demo")

        # Clean up any existing cache
        await cache_service.invalidate(request)

        # === Scenario 1: Cache MISS ===
        print("📊 Scenario 1: Cache MISS (first request)")
        print("-" * 50)

        start = time.time()
        cached_response = await cache_service.get(request, "req-001")
        if cached_response is None:
            print("  ❌ Cache miss - must query upstream")
            response = await simulate_slow_search(request)
            await cache_service.set(request, response, "req-001")
            print("  ✅ Response cached for future requests")
        miss_duration = (time.time() - start) * 1000

        print(f"  ⏱️  Total time: {miss_duration:.1f}ms\n")

        # === Scenario 2: Cache HIT ===
        print("📊 Scenario 2: Cache HIT (subsequent request)")
        print("-" * 50)

        start = time.time()
        cached_response = await cache_service.get(request, "req-002")
        if cached_response is not None:
            print("  ✅ Cache hit - instant response!")
            print(f"  📄 Query: '{cached_response.query}'")
            print(f"  🎯 Original search time: {cached_response.metadata.search_time_ms}ms")
        hit_duration = (time.time() - start) * 1000

        print(f"  ⏱️  Total time: {hit_duration:.1f}ms\n")

        # === Performance Comparison ===
        print("📈 Performance Improvement")
        print("-" * 50)
        speedup = miss_duration / hit_duration if hit_duration > 0 else 0
        print(f"  Cache miss: {miss_duration:.1f}ms")
        print(f"  Cache hit:  {hit_duration:.1f}ms")
        print(f"  Speedup:    {speedup:.1f}x faster\n")

        # === Cleanup ===
        print("🧹 Cleanup")
        print("-" * 50)
        deleted = await cache_service.invalidate(request)
        if deleted:
            print("  ✅ Cache entry deleted")
        else:
            print("  ⚠️  No cache entry to delete")

    finally:
        await redis_client.disconnect()
        print("\n✨ Demo complete!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as e:
        print(f"\n❌ Error: {e}")
        print("\nMake sure Redis/Valkey is running:")
        print("  docker run -d -p 6379:6379 valkey/valkey:latest")
