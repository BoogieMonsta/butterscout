"""Integration tests for rate limiter with real Valkey/Redis."""
from __future__ import annotations

import asyncio
import time

import pytest

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.services.rate_limiter import RateLimiter
from butterscout.utils.redis_keys import generate_global_rate_limit_key


@pytest.fixture
def settings() -> Settings:
    """Create test settings with low rate limits."""
    return Settings(
        BS_REDIS_URL="valkey://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_RATE_LIMIT_PER_HOUR=10,
        BS_API_KEY_RATE_LIMIT_PER_HOUR=100,
        BS_GLOBAL_RATE_LIMIT_PER_HOUR=1000,
    )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_allows_within_limit(settings: Settings) -> None:
    """Test that requests within limit are allowed."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Ensure clean slate
        from butterscout.utils.redis_keys import generate_global_rate_limit_key

        global_key = generate_global_rate_limit_key(settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR)
        await client.delete(global_key)

        limiter = RateLimiter(client, settings)

        # Make requests within limit
        for i in range(5):
            is_allowed, retry_after, remaining, limit, reset_ts = await limiter.check_rate_limit(
                client_ip="192.168.1.1",
                api_key=None,
                request_id=f"test-within-{i}",
            )
            assert is_allowed is True
            assert retry_after is None
            assert remaining >= 0
            assert limit == settings.BS_RATE_LIMIT_PER_HOUR
            assert reset_ts > int(time.time())  # Reset is in the future

        # Clean up
        await client.delete("bs:ratelimit:ip:" + "192.168.1.1"[:16])
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_blocks_over_limit(settings: Settings) -> None:
    """Test that requests over limit are blocked."""
    # Use very low limit for testing
    settings.BS_RATE_LIMIT_PER_HOUR = 5

    client = ValkeyClient(settings)
    await client.connect()

    global_key = generate_global_rate_limit_key(settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR)
    await client.delete(global_key)

    try:
        limiter = RateLimiter(client, settings)

        # Make 5 requests (at limit)
        for i in range(5):
            is_allowed, _, _, _, _ = await limiter.check_rate_limit(
                client_ip="192.168.1.2",
                api_key=None,
                request_id=f"test-over-{i}",
            )
            assert is_allowed is True

        # 6th request should be blocked
        is_allowed, retry_after, remaining, limit, reset_ts = await limiter.check_rate_limit(
            client_ip="192.168.1.2",
            api_key=None,
            request_id="test-over-6",
        )

        assert is_allowed is False
        assert retry_after is not None
        assert retry_after > 0
        assert remaining == 0
        assert limit == 5
        assert reset_ts > int(time.time())  # Reset is in the future

        # Clean up
        from butterscout.utils.redis_keys import generate_rate_limit_key

        key = generate_rate_limit_key("192.168.1.2", "ip")
        await client.delete(key)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_api_key_higher_limit(settings: Settings) -> None:
    """Test that API keys get higher rate limits."""
    settings.BS_RATE_LIMIT_PER_HOUR = 10
    settings.BS_API_KEY_RATE_LIMIT_PER_HOUR = 100

    client = ValkeyClient(settings)
    await client.connect()

    from butterscout.utils.redis_keys import generate_global_rate_limit_key

    global_key = generate_global_rate_limit_key(settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR)
    await client.delete(global_key)

    try:
        limiter = RateLimiter(client, settings)

        # Make 15 requests with API key (over IP limit, under key limit)
        for i in range(15):
            is_allowed, _, _, limit, _ = await limiter.check_rate_limit(
                client_ip="192.168.1.3",
                api_key="test-api-key",
                request_id=f"test-api-{i}",
            )
            assert is_allowed is True
            assert limit == 100  # Using API key limit

        # Clean up
        from butterscout.utils.redis_keys import generate_rate_limit_key

        key = generate_rate_limit_key("test-api-key", "api_key")
        await client.delete(key)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_sliding_window(settings: Settings) -> None:
    """Test sliding window behavior - old requests expire."""
    settings.BS_RATE_LIMIT_PER_HOUR = 3

    client = ValkeyClient(settings)
    await client.connect()

    try:
        limiter = RateLimiter(client, settings)

        # Make 3 requests (at limit)
        first_reset_ts = None
        for i in range(3):
            is_allowed, _, _, _, reset_ts = await limiter.check_rate_limit(
                client_ip="192.168.1.4",
                api_key=None,
                request_id=f"test-sliding-{i}",
            )
            assert is_allowed is True
            if i == 0:
                first_reset_ts = reset_ts

        # 4th request should be blocked
        is_allowed, retry_after, _, _, reset_ts = await limiter.check_rate_limit(
            client_ip="192.168.1.4",
            api_key=None,
            request_id="test-sliding-4",
        )
        assert is_allowed is False
        assert retry_after is not None
        # Reset timestamp should match when first request expires
        assert reset_ts == first_reset_ts

        # Clean up
        from butterscout.utils.redis_keys import generate_rate_limit_key

        key = generate_rate_limit_key("192.168.1.4", "ip")
        await client.delete(key)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_different_ips(settings: Settings) -> None:
    """Test that different IPs have separate rate limits."""
    settings.BS_RATE_LIMIT_PER_HOUR = 5

    client = ValkeyClient(settings)
    await client.connect()

    try:
        limiter = RateLimiter(client, settings)

        # Use up limit for IP1
        for i in range(5):
            await limiter.check_rate_limit(
                client_ip="192.168.1.5",
                api_key=None,
                request_id=f"test-ip1-{i}",
            )

        # IP1 should be blocked
        is_allowed, _, _, _, _ = await limiter.check_rate_limit(
            client_ip="192.168.1.5",
            api_key=None,
            request_id="test-ip1-blocked",
        )
        assert is_allowed is False

        # IP2 should still be allowed
        is_allowed, _, _, _, _ = await limiter.check_rate_limit(
            client_ip="192.168.1.6",
            api_key=None,
            request_id="test-ip2-allowed",
        )
        assert is_allowed is True

        # Clean up
        from butterscout.utils.redis_keys import generate_rate_limit_key

        key1 = generate_rate_limit_key("192.168.1.5", "ip")
        key2 = generate_rate_limit_key("192.168.1.6", "ip")
        await client.delete(key1)
        await client.delete(key2)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_global_rate_limit(settings: Settings) -> None:
    """Test global rate limit across all users."""
    settings.BS_RATE_LIMIT_PER_HOUR = 100
    settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR = 5

    client = ValkeyClient(settings)
    await client.connect()

    from butterscout.utils.redis_keys import generate_global_rate_limit_key

    global_key = generate_global_rate_limit_key(settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR)
    await client.delete(global_key)

    try:
        limiter = RateLimiter(client, settings)

        # Use up global limit with different IPs
        for i in range(5):
            is_allowed, _, _, _, _ = await limiter.check_rate_limit(
                client_ip=f"192.168.1.{100 + i}",
                api_key=None,
                request_id=f"test-global-{i}",
            )
            assert is_allowed is True

        # Next request should be blocked by global limit
        is_allowed, retry_after, _, limit, _ = await limiter.check_rate_limit(
            client_ip="192.168.1.200",
            api_key=None,
            request_id="test-global-blocked",
        )
        assert is_allowed is False
        assert limit == 5  # Global limit

        # Clean up
        await client.delete(global_key)

        # Clean up individual IP keys
        from butterscout.utils.redis_keys import generate_rate_limit_key

        for i in range(5):
            key = generate_rate_limit_key(f"192.168.1.{100 + i}", "ip")
            await client.delete(key)
        key = generate_rate_limit_key("192.168.1.200", "ip")
        await client.delete(key)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_disabled_global(settings: Settings) -> None:
    """Test that global rate limit can be disabled."""
    settings.BS_RATE_LIMIT_PER_HOUR = 10
    settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR = 0  # Disabled

    client = ValkeyClient(settings)
    await client.connect()

    try:
        limiter = RateLimiter(client, settings)

        # Make request - should only check per-IP limit
        is_allowed, _, _, limit, _ = await limiter.check_rate_limit(
            client_ip="192.168.1.7",
            api_key=None,
            request_id="test-no-global",
        )
        assert is_allowed is True
        assert limit == 10  # Per-IP limit

        # Clean up
        from butterscout.utils.redis_keys import generate_rate_limit_key

        key = generate_rate_limit_key("192.168.1.7", "ip")
        await client.delete(key)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_fail_open_on_error(settings: Settings) -> None:
    """Test that rate limiter fails open on Redis errors."""
    client = ValkeyClient(settings)
    await client.connect()
    await client.disconnect()  # Disconnect to simulate error

    limiter = RateLimiter(client, settings)

    # Should allow request even though Redis is down
    is_allowed, retry_after, remaining, limit, reset_ts = await limiter.check_rate_limit(
        client_ip="192.168.1.8",
        api_key=None,
        request_id="test-fail-open",
    )

    assert is_allowed is True
    assert retry_after is None
    assert remaining == settings.BS_RATE_LIMIT_PER_HOUR
    assert reset_ts > int(time.time())  # Reset is in the future


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_concurrent_requests_no_overflow(settings: Settings) -> None:
    """Test that concurrent requests don't exceed limit due to race conditions.

    This test verifies that the Lua script provides atomic operations.
    """
    settings.BS_RATE_LIMIT_PER_HOUR = 10
    settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR = 0  # Disable global

    client = ValkeyClient(settings)
    await client.connect()

    try:
        limiter = RateLimiter(client, settings)

        # Launch 20 concurrent requests (2x the limit)
        # With proper atomic operations, exactly 10 should succeed
        async def make_request(i: int) -> bool:
            is_allowed, _, _, _, _ = await limiter.check_rate_limit(
                client_ip="192.168.1.99",
                api_key=None,
                request_id=f"concurrent-test-{i}",
            )
            return is_allowed

        # Execute all requests concurrently
        results = await asyncio.gather(*[make_request(i) for i in range(20)])

        # Count how many were allowed
        allowed_count = sum(1 for r in results if r)
        blocked_count = sum(1 for r in results if not r)

        # Exactly 10 should be allowed (our limit)
        assert allowed_count == 10, f"Expected 10 allowed, got {allowed_count}"
        assert blocked_count == 10, f"Expected 10 blocked, got {blocked_count}"

        # Clean up
        from butterscout.utils.redis_keys import generate_rate_limit_key

        key = generate_rate_limit_key("192.168.1.99", "ip")
        await client.delete(key)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_rate_limit_reset_timestamp_accuracy(settings: Settings) -> None:
    """Test that reset timestamp accurately reflects when oldest entry expires."""
    settings.BS_RATE_LIMIT_PER_HOUR = 2

    client = ValkeyClient(settings)
    await client.connect()

    try:
        limiter = RateLimiter(client, settings)

        # First request - capture its timestamp
        start_time = int(time.time())
        is_allowed, _, _, _, first_reset = await limiter.check_rate_limit(
            client_ip="192.168.1.98",
            api_key=None,
            request_id="reset-test-1",
        )
        assert is_allowed is True

        # Wait a second
        await asyncio.sleep(1)

        # Second request - should have same reset time
        is_allowed, _, _, _, second_reset = await limiter.check_rate_limit(
            client_ip="192.168.1.98",
            api_key=None,
            request_id="reset-test-2",
        )
        assert is_allowed is True

        # Third request - should be blocked
        is_allowed, retry_after, _, _, blocked_reset = await limiter.check_rate_limit(
            client_ip="192.168.1.98",
            api_key=None,
            request_id="reset-test-3",
        )
        assert is_allowed is False
        assert retry_after is not None

        # Reset timestamps should match (based on first request)
        assert first_reset == second_reset == blocked_reset

        # Reset should be ~3600 seconds after first request
        expected_reset = start_time + 3600
        assert abs(first_reset - expected_reset) <= 2  # Allow 2 second tolerance

        # Retry-after should be less than 3600 (we waited 1 second)
        assert retry_after < 3600
        assert retry_after > 3590  # Should be close to 3600 minus our wait

        # Clean up
        from butterscout.utils.redis_keys import generate_rate_limit_key

        key = generate_rate_limit_key("192.168.1.98", "ip")
        await client.delete(key)
    finally:
        await client.disconnect()
