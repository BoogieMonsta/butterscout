"""Performance benchmark for Valkey/Redis client.

Run this script to benchmark Valkey/Redis operations.
Requires a running Valkey/Redis instance at redis://localhost:6379
"""

from __future__ import annotations

import asyncio
import time

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.models.requests import SearchOptions, SearchRequest
from butterscout.utils.redis_keys import generate_cache_key, generate_rate_limit_key


async def benchmark_get_set_operations() -> None:
    """Benchmark 1000 get/set operations."""
    settings = Settings(
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
    )

    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Warm up
        await client.set("warmup", "value")
        await client.get("warmup")

        # Benchmark set operations
        start = time.perf_counter()
        for i in range(1000):
            await client.set(f"bench:key:{i}", f"value_{i}", ttl_seconds=60)
        set_duration = time.perf_counter() - start

        # Benchmark get operations
        start = time.perf_counter()
        for i in range(1000):
            await client.get(f"bench:key:{i}")
        get_duration = time.perf_counter() - start

        # Cleanup
        for i in range(1000):
            await client.delete(f"bench:key:{i}")

        print("\n📊 Performance Benchmark Results:")
        print(f"  Set operations: 1000 ops in {set_duration:.3f}s")
        print(f"  Average: {set_duration / 1000 * 1000:.2f}ms per operation")
        print(f"  Get operations: 1000 ops in {get_duration:.3f}s")
        print(f"  Average: {get_duration / 1000 * 1000:.2f}ms per operation")
    finally:
        await client.disconnect()


async def benchmark_concurrent_operations() -> None:
    """Benchmark connection pool under concurrent load."""
    settings = Settings(
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
    )

    client = ValkeyClient(settings)
    await client.connect()

    try:

        async def concurrent_op(i: int) -> bool:
            """Execute concurrent set/get/delete operations."""
            key = f"bench:concurrent:{i}"
            await client.set(key, f"value_{i}", ttl_seconds=60)
            value = await client.get(key)
            await client.delete(key)
            return value == f"value_{i}"

        # Benchmark 100 concurrent operations
        start = time.perf_counter()
        results = await asyncio.gather(*[concurrent_op(i) for i in range(100)])
        duration = time.perf_counter() - start

        print("\n🔀 Concurrent Operations (100 concurrent set/get/delete):")
        print(f"  Total duration: {duration:.3f}s")
        print(f"  All operations succeeded: {all(results)}")
        print(f"  Operations per second: {100 / duration:.2f}")
    finally:
        await client.disconnect()


async def demo_cache_key_generation() -> None:
    """Demonstrate cache key generation and usage."""
    print("\n🔑 Cache Key Generation Demo:")

    # Create sample search requests
    req1 = SearchRequest(
        query="python asyncio tutorial",
        max_results=10,
        include_content=True,
        options=SearchOptions(domains=["stackoverflow.com", "python.org"], language="en"),
    )

    req2 = SearchRequest(
        query="Python Asyncio Tutorial",  # Different case
        max_results=10,
        include_content=True,
        options=SearchOptions(domains=["python.org", "stackoverflow.com"], language="en"),
    )

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    print(f"  Request 1 cache key: {key1}")
    print(f"  Request 2 cache key: {key2}")
    print(f"  Keys are identical (normalized): {key1 == key2}")

    # Demonstrate rate limit keys
    ip_key = generate_rate_limit_key("192.168.1.1", "ip")
    api_key = generate_rate_limit_key("sk_test_abc123", "api_key")

    print(f"\n  Rate limit key (IP): {ip_key}")
    print(f"  Rate limit key (API): {api_key}")


async def demo_basic_usage() -> None:
    """Demonstrate basic Valkey/Redis client usage."""
    print("\n📝 Basic Usage Demo:")

    settings = Settings(
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
    )

    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Health check
        is_healthy = await client.ping()
        print(f"  Valkey health check: {'✓ Connected' if is_healthy else '✗ Failed'}")

        # Set a value with TTL
        await client.set("demo:key", "demo_value", ttl_seconds=30)
        print("  Set key with 30s TTL: demo:key = demo_value")

        # Get the value
        value = await client.get("demo:key")
        print(f"  Retrieved value: {value}")

        # Check TTL
        ttl = await client.ttl("demo:key")
        print(f"  Time to live: {ttl}s")

        # Check existence
        exists = await client.exists("demo:key")
        print(f"  Key exists: {exists}")

        # Increment counter
        for _ in range(3):
            count = await client.incr("demo:counter")
        print(f"  Counter after 3 increments: {count}")

        # Cleanup
        await client.delete("demo:key")
        await client.delete("demo:counter")
        print("  Cleaned up demo keys")
    finally:
        await client.disconnect()


async def main() -> None:
    """Run all benchmarks and demos."""
    print("=" * 60)
    print("Valkey Client Benchmark & Demo")
    print("=" * 60)

    try:
        # Run demos that don't require Valkey/Redis
        await demo_cache_key_generation()

        # Try to run Valkey/Redis-dependent benchmarks
        try:
            await demo_basic_usage()
            await benchmark_get_set_operations()
            await benchmark_concurrent_operations()
        except Exception as e:
            print(f"\n⚠️  Valkey benchmarks skipped: {e}")
            print("  Make sure Valkey is running at redis://localhost:6379")

        print("\n" + "=" * 60)
        print("✓ Benchmark complete!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
