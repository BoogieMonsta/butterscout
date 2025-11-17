"""Performance benchmark for rate limiter.

Run this script to benchmark rate limiting operations.
Requires a running Valkey/Redis instance at redis://localhost:6379
"""
from __future__ import annotations

import asyncio
import time

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.services.rate_limiter import RateLimiter
from butterscout.utils.rate_limit_headers import generate_rate_limit_headers


async def benchmark_rate_limit_checks() -> None:
    """Benchmark 1000 rate limit checks."""
    settings = Settings(
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_RATE_LIMIT_PER_HOUR=10000,  # High limit for testing
    )

    client = ValkeyClient(settings)
    await client.connect()

    try:
        limiter = RateLimiter(client, settings)

        # Warm up
        await limiter.check_rate_limit("192.168.0.1", None, "warmup")

        # Benchmark 1000 rate limit checks
        start = time.perf_counter()
        for i in range(1000):
            await limiter.check_rate_limit(
                client_ip=f"192.168.{i // 256}.{i % 256}",
                api_key=None,
                request_id=f"bench-{i}",
            )
        duration = time.perf_counter() - start

        # Cleanup
        from butterscout.utils.redis_keys import generate_rate_limit_key

        for i in range(1000):
            key = generate_rate_limit_key(f"192.168.{i // 256}.{i % 256}", "ip")
            await client.delete(key)

        print("\n📊 Rate Limit Check Performance:")
        print(f"  1000 checks in: {duration:.3f}s")
        print(f"  Average: {duration/1000*1000:.2f}ms per check")
        print(f"  Throughput: {1000/duration:.2f} checks/sec")

        # Check if we meet performance requirements (< 10ms per check)
        avg_ms = duration / 1000 * 1000
        if avg_ms < 10:
            print("  ✓ Performance requirement met (< 10ms per check)")
        else:
            print(f"  ✗ Performance requirement not met (target: < 10ms, actual: {avg_ms:.2f}ms)")

    finally:
        await client.disconnect()


async def benchmark_concurrent_rate_limits() -> None:
    """Benchmark concurrent rate limit checks (simulating load)."""
    settings = Settings(
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_RATE_LIMIT_PER_HOUR=10000,
    )

    client = ValkeyClient(settings)
    await client.connect()

    try:
        limiter = RateLimiter(client, settings)

        async def concurrent_check(i: int) -> bool:
            """Execute concurrent rate limit check."""
            is_allowed, _, _, _, _ = await limiter.check_rate_limit(
                client_ip=f"192.168.100.{i % 256}",
                api_key=None,
                request_id=f"concurrent-{i}",
            )
            return is_allowed

        # Benchmark 100 concurrent checks
        start = time.perf_counter()
        results = await asyncio.gather(*[concurrent_check(i) for i in range(100)])
        duration = time.perf_counter() - start

        # Cleanup
        from butterscout.utils.redis_keys import generate_rate_limit_key

        for i in range(256):
            key = generate_rate_limit_key(f"192.168.100.{i}", "ip")
            await client.delete(key)

        print("\n🔀 Concurrent Rate Limit Checks (100 concurrent):")
        print(f"  Total duration: {duration:.3f}s")
        print(f"  All checks allowed: {all(results)}")
        print(f"  Checks per second: {100/duration:.2f}")
        print(f"  Average latency: {duration/100*1000:.2f}ms")

    finally:
        await client.disconnect()


async def benchmark_memory_usage() -> None:
    """Benchmark memory usage with many clients."""
    settings = Settings(
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_RATE_LIMIT_PER_HOUR=60,
    )

    client = ValkeyClient(settings)
    await client.connect()

    try:
        limiter = RateLimiter(client, settings)

        # Simulate 1000 different clients making requests
        print("\n💾 Memory Usage Test (1000 clients):")
        for i in range(1000):
            await limiter.check_rate_limit(
                client_ip=f"10.0.{i // 256}.{i % 256}",
                api_key=None,
                request_id=f"memory-{i}",
            )

        # Check memory usage by counting keys
        # Note: In a real scenario, you'd use Redis INFO command
        print("  Simulated 1000 clients making requests")
        print("  Each client creates a sorted set with timestamps")
        print("  Keys auto-expire after window + 60s")

        # Cleanup
        from butterscout.utils.redis_keys import generate_rate_limit_key

        cleanup_count = 0
        for i in range(1000):
            key = generate_rate_limit_key(f"10.0.{i // 256}.{i % 256}", "ip")
            deleted = await client.delete(key)
            cleanup_count += deleted

        print(f"  Cleaned up {cleanup_count} rate limit keys")

    finally:
        await client.disconnect()


async def demo_rate_limit_behavior() -> None:
    """Demonstrate rate limit behavior with examples."""
    print("\n📝 Rate Limit Behavior Demo:")

    settings = Settings(
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_RATE_LIMIT_PER_HOUR=5,  # Low limit for demo
        BS_API_KEY_RATE_LIMIT_PER_HOUR=10,
    )

    client = ValkeyClient(settings)
    await client.connect()

    try:
        limiter = RateLimiter(client, settings)

        print("\n  Example 1: Request within limit")
        is_allowed, retry_after, remaining, limit, reset_ts = await limiter.check_rate_limit(
            client_ip="192.168.1.100",
            api_key=None,
            request_id="demo-1",
        )
        headers = generate_rate_limit_headers(limit, remaining, reset_ts, retry_after)
        print(f"    Allowed: {is_allowed}")
        print(f"    Remaining: {remaining}/{limit}")
        print(f"    Headers: {headers}")

        print("\n  Example 2: Use up rate limit")
        for i in range(4):
            await limiter.check_rate_limit(
                client_ip="192.168.1.100",
                api_key=None,
                request_id=f"demo-exhaust-{i}",
            )

        print("\n  Example 3: Request blocked (rate limited)")
        is_allowed, retry_after, remaining, limit, reset_ts = await limiter.check_rate_limit(
            client_ip="192.168.1.100",
            api_key=None,
            request_id="demo-blocked",
        )
        headers = generate_rate_limit_headers(limit, remaining, reset_ts, retry_after)
        print(f"    Allowed: {is_allowed}")
        print(f"    Remaining: {remaining}/{limit}")
        print(f"    Retry after: {retry_after}s")
        print(f"    Headers: {headers}")

        print("\n  Example 4: API key gets higher limit")
        is_allowed, retry_after, remaining, limit, reset_ts = await limiter.check_rate_limit(
            client_ip="192.168.1.101",
            api_key="sk_test_abc123",
            request_id="demo-api-key",
        )
        headers = generate_rate_limit_headers(limit, remaining, reset_ts, retry_after)
        print(f"    Allowed: {is_allowed}")
        print(f"    Remaining: {remaining}/{limit} (higher limit for API key)")
        print(f"    Headers: {headers}")

        # Cleanup
        from butterscout.utils.redis_keys import generate_rate_limit_key

        await client.delete(generate_rate_limit_key("192.168.1.100", "ip"))
        await client.delete(generate_rate_limit_key("192.168.1.101", "ip"))
        await client.delete(generate_rate_limit_key("sk_test_abc123", "api_key"))

    finally:
        await client.disconnect()


async def main() -> None:
    """Run all benchmarks and demos."""
    print("=" * 60)
    print("Rate Limiter Benchmark & Demo")
    print("=" * 60)

    try:
        # Try to run Valkey/Redis-dependent benchmarks
        try:
            await demo_rate_limit_behavior()
            await benchmark_rate_limit_checks()
            await benchmark_concurrent_rate_limits()
            await benchmark_memory_usage()
        except Exception as e:
            print(f"\n⚠️  Rate limiter benchmarks skipped: {e}")
            print("  Make sure Valkey/Redis is running at redis://localhost:6379")

        print("\n" + "=" * 60)
        print("✓ Benchmark complete!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
