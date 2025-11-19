"""Unit tests for rate limiter."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.services.rate_limiter import RateLimiter
from butterscout.utils.rate_limit_headers import generate_rate_limit_headers


@pytest.fixture
def settings() -> Settings:
    """Create test settings with low rate limits."""
    return Settings(
        BS_REDIS_URL="valkey://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_API_KEY="test-api-key",
        BS_RATE_LIMIT_PER_HOUR=10,
        BS_API_KEY_RATE_LIMIT_PER_HOUR=100,
        BS_GLOBAL_RATE_LIMIT_PER_HOUR=1000,
    )


@pytest.fixture
def mock_valkey_client() -> ValkeyClient:
    """Create mock Valkey client."""
    mock = AsyncMock(spec=ValkeyClient)
    mock.valkey = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_rate_limit_headers_generation() -> None:
    """Test rate limit header generation."""
    reset_time = int(time.time()) + 3600
    headers = generate_rate_limit_headers(
        limit=100,
        remaining=75,
        reset_timestamp=reset_time,
        retry_after=None,
    )

    assert headers["X-RateLimit-Limit"] == "100"
    assert headers["X-RateLimit-Remaining"] == "75"
    assert headers["X-RateLimit-Reset"] == str(reset_time)
    assert "Retry-After" not in headers

    # With retry-after
    headers = generate_rate_limit_headers(
        limit=100,
        remaining=0,
        reset_timestamp=reset_time,
        retry_after=3600,
    )

    assert headers["Retry-After"] == "3600"
    assert headers["X-RateLimit-Remaining"] == "0"
    assert headers["X-RateLimit-Reset"] == str(reset_time)


@pytest.mark.asyncio
async def test_rate_limit_headers_negative_remaining() -> None:
    """Test that negative remaining is clamped to zero."""
    reset_time = int(time.time()) + 3600
    headers = generate_rate_limit_headers(
        limit=100,
        remaining=-5,
        reset_timestamp=reset_time,
    )

    assert headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.asyncio
async def test_rate_limiter_initialization(
    settings: Settings, mock_valkey_client: ValkeyClient
) -> None:
    """Test rate limiter initialization."""
    limiter = RateLimiter(mock_valkey_client, settings)

    assert limiter.redis is mock_valkey_client
    assert limiter.settings is settings


@pytest.mark.asyncio
async def test_rate_limiter_fail_open_on_redis_error(settings: Settings) -> None:
    """Test that rate limiter fails open when Redis is unavailable."""
    # Create mock that raises exception on eval
    mock_client = AsyncMock(spec=ValkeyClient)
    mock_client.eval = AsyncMock(side_effect=Exception("Redis connection error"))

    limiter = RateLimiter(mock_client, settings)

    # Should allow request and not raise
    is_allowed, retry_after, remaining, limit, reset_ts = await limiter.check_rate_limit(
        client_ip="192.168.1.1",
        api_key=None,
        request_id="test-123",
    )

    assert is_allowed is True
    assert retry_after is None
    assert remaining == settings.BS_RATE_LIMIT_PER_HOUR
    assert limit == settings.BS_RATE_LIMIT_PER_HOUR
    assert reset_ts > int(time.time())


@pytest.mark.asyncio
async def test_rate_limiter_uses_api_key_limit_when_provided(settings: Settings) -> None:
    """Test that API key uses higher limit."""
    mock_client = AsyncMock(spec=ValkeyClient)
    # Mock eval to return Lua script format: [is_allowed (1=allowed), count, oldest_timestamp]
    current_time = int(time.time())
    oldest_timestamp = current_time - 100
    # Return: allowed (1), count=1, oldest entry timestamp
    mock_client.eval = AsyncMock(return_value=[1, 1, oldest_timestamp])

    limiter = RateLimiter(mock_client, settings)

    is_allowed, retry_after, remaining, limit, reset_ts = await limiter.check_rate_limit(
        client_ip="192.168.1.1",
        api_key="test-api-key",
        request_id="test-123",
    )

    assert is_allowed is True
    assert limit == 100  # API key limit, not default
    assert remaining == 99  # 100 - 1


@pytest.mark.asyncio
async def test_rate_limiter_blocked_request(settings: Settings) -> None:
    """Test blocked request returns correct values."""
    mock_client = AsyncMock(spec=ValkeyClient)
    # Mock eval to return Lua script format: [is_allowed (0=blocked), count, oldest_timestamp]
    # When count >= limit, is_allowed=0
    current_time = int(time.time())
    oldest_timestamp = current_time - 3000  # 3000 seconds ago
    # Return: blocked (0), count=10 (at limit), oldest entry timestamp
    mock_client.eval = AsyncMock(return_value=[0, 10, oldest_timestamp])

    limiter = RateLimiter(mock_client, settings)

    is_allowed, retry_after, remaining, limit, returned_reset = await limiter.check_rate_limit(
        client_ip="192.168.1.1",
        api_key=None,
        request_id="test-123",
    )

    assert is_allowed is False
    assert retry_after is not None
    assert retry_after > 0
    assert remaining == 0
    assert limit == 10
    # Reset timestamp should be oldest_timestamp + 3600
    assert returned_reset == oldest_timestamp + 3600


@pytest.mark.asyncio
async def test_rate_limiter_global_limit_disabled(settings: Settings) -> None:
    """Test that global limit can be disabled."""
    settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR = 0

    mock_client = AsyncMock(spec=ValkeyClient)
    current_time = int(time.time())
    oldest_timestamp = current_time - 100
    # Return Lua script format: [allowed (1), count=9, oldest entry timestamp]
    mock_client.eval = AsyncMock(return_value=[1, 9, oldest_timestamp])

    limiter = RateLimiter(mock_client, settings)

    # Should still work with global limit disabled
    is_allowed, _, _, limit, _ = await limiter.check_rate_limit(
        client_ip="192.168.1.1",
        api_key=None,
        request_id="test-123",
    )

    assert is_allowed is True
    assert limit == settings.BS_RATE_LIMIT_PER_HOUR


# Integration tests moved to tests/integration/test_rate_limiter_integration.py
