# Task 07: Rate Limiting System

**Role:** You are a senior backend engineer specializing in API rate limiting, Redis-based algorithms, and DoS prevention strategies.

## Context

Implement sliding window rate limiting using Valkey/Redis to protect the API from abuse. Support multiple rate limit tiers (IP-based, API key-based, global) with proper HTTP headers and retry-after semantics.

Defaults: 60 req/hr per IP, 600 req/hr per API key, optional global 10k/hr; keying prefers API key when present; emit X-RateLimit-* headers and Retry-After; sliding window via Redis.

Refer to **[TECH SPEC.md]** §4.1, §4.2, §6.2, §6.5, §7.2 for complete details.

## Deliverables

### 1. Rate Limiter Service (`butterscout/services/rate_limiter.py`)

```python
import time
from typing import Optional, Tuple
from butterscout.clients.redis_client import RedisClient
from butterscout.utils.redis_keys import (
    generate_rate_limit_key,
    generate_global_rate_limit_key,
)
from butterscout.config import Settings
import structlog

logger = structlog.get_logger()

class RateLimiter:
    """Sliding window rate limiter using Redis"""

    def __init__(self, redis_client: RedisClient, settings: Settings):
        self.redis = redis_client
        self.settings = settings

    async def check_rate_limit(
        self,
        client_ip: str,
        api_key: Optional[str],
        request_id: str
    ) -> Tuple[bool, Optional[int], int, int]:
        """
        Check if request is within rate limits

        Args:
            client_ip: Client IP address
            api_key: Optional API key
            request_id: Request ID for logging

        Returns:
            Tuple of (is_allowed, retry_after_seconds, remaining, limit)
            - is_allowed: True if request should proceed
            - retry_after_seconds: Seconds until retry (if rate limited)
            - remaining: Remaining requests in window
            - limit: Total limit per window
        """
        # Determine which rate limit to use
        if api_key:
            # API key rate limit (higher tier)
            identifier = api_key
            limit_per_hour = self.settings.BS_API_KEY_RATE_LIMIT_PER_HOUR
            key_type = "api_key"
        else:
            # IP-based rate limit (lower tier)
            identifier = client_ip
            limit_per_hour = self.settings.BS_RATE_LIMIT_PER_HOUR
            key_type = "ip"

        # Check user-specific limit
        is_allowed, retry_after, remaining = await self._check_limit(
            identifier,
            key_type,
            limit_per_hour,
            request_id,
        )

        if not is_allowed:
            logger.warning(
                "rate_limit_exceeded",
                request_id=request_id,
                key_type=key_type,
                identifier_hash=identifier[:8] + "...",
                limit=limit_per_hour,
            )
            return False, retry_after, 0, limit_per_hour

        # Check global rate limit if configured
        if self.settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR > 0:
            global_allowed, global_retry, _ = await self._check_global_limit(
                request_id
            )
            if not global_allowed:
                logger.warning(
                    "global_rate_limit_exceeded",
                    request_id=request_id,
                )
                return False, global_retry, 0, self.settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR

        logger.info(
            "rate_limit_ok",
            request_id=request_id,
            key_type=key_type,
            remaining=remaining,
            limit=limit_per_hour,
        )

        return True, None, remaining, limit_per_hour

    async def _check_limit(
        self,
        identifier: str,
        key_type: str,
        limit_per_hour: int,
        request_id: str,
    ) -> Tuple[bool, Optional[int], int]:
        """
        Check rate limit using sliding window algorithm

        Args:
            identifier: IP or API key
            key_type: "ip" or "api_key"
            limit_per_hour: Max requests per hour
            request_id: Request ID

        Returns:
            Tuple of (is_allowed, retry_after_seconds, remaining)
        """
        rate_limit_key = generate_rate_limit_key(identifier, key_type)
        window_seconds = 3600  # 1 hour
        current_time = int(time.time())

        try:
            # Use sliding window with timestamps
            # Store each request timestamp as a sorted set member
            # Score = timestamp, Value = request_id

            # Remove old entries outside the window
            cutoff_time = current_time - window_seconds
            await self.redis.redis.zremrangebyscore(
                rate_limit_key,
                "-inf",
                cutoff_time,
            )

            # Count requests in current window
            count = await self.redis.redis.zcard(rate_limit_key)

            if count >= limit_per_hour:
                # Rate limit exceeded
                # Calculate when oldest request will expire
                oldest_entries = await self.redis.redis.zrange(
                    rate_limit_key, 0, 0, withscores=True
                )
                if oldest_entries:
                    oldest_timestamp = int(oldest_entries[0][1])
                    retry_after = (oldest_timestamp + window_seconds) - current_time
                    retry_after = max(1, retry_after)  # At least 1 second
                else:
                    retry_after = window_seconds

                remaining = 0
                return False, retry_after, remaining

            # Add current request to window
            await self.redis.redis.zadd(
                rate_limit_key,
                {request_id: current_time},
            )

            # Set expiration on the key
            await self.redis.expire(rate_limit_key, window_seconds + 60)

            remaining = limit_per_hour - count - 1
            return True, None, remaining

        except Exception as e:
            logger.error(
                "rate_limit_check_error",
                request_id=request_id,
                error=str(e),
            )
            # On error, allow request (fail open)
            return True, None, limit_per_hour

    async def _check_global_limit(
        self,
        request_id: str
    ) -> Tuple[bool, Optional[int], int]:
        """Check global rate limit across all users"""
        global_key = generate_global_rate_limit_key()
        return await self._check_limit(
            "global",
            "global",
            self.settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR,
            request_id,
        )
```

### 2. Rate Limit Headers (`butterscout/utils/rate_limit_headers.py`)

Generate standard rate limit headers:

```python
from typing import Dict, Optional

def generate_rate_limit_headers(
    limit: int,
    remaining: int,
    retry_after: Optional[int] = None,
) -> Dict[str, str]:
    """
    Generate standard rate limit headers

    Args:
        limit: Total requests allowed per window
        remaining: Remaining requests in window
        retry_after: Seconds until retry (if rate limited)

    Returns:
        Dictionary of HTTP headers
    """
    import time

    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Reset": str(int(time.time()) + 3600),  # 1 hour from now
    }

    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)

    return headers
```

## Key Implementation Details

### Sliding Window Algorithm (TECH SPEC §6.2)

- Use Redis sorted set (ZSET) with timestamps as scores
- Each request adds entry with current timestamp
- Remove entries older than window (1 hour)
- Count remaining entries
- If count ≥ limit, reject with retry-after

**Advantages over token bucket:**
- More accurate (no burst allowance)
- Better for API protection
- Simpler to implement

### Rate Limit Tiers (TECH SPEC §6.5)

1. **IP-based** (unauthenticated): `BS_RATE_LIMIT_PER_HOUR` (default 60/hour)
2. **API key-based** (authenticated): `BS_API_KEY_RATE_LIMIT_PER_HOUR` (default 600/hour)
3. **Global** (optional): `BS_GLOBAL_RATE_LIMIT_PER_HOUR` (default 10000/hour, disabled if 0)

### Retry-After Calculation

- Calculate when oldest request in window will expire
- Return seconds until that expiration
- Minimum 1 second

### Error Handling - Fail Open

**Critical:** On Redis errors, allow request (fail open)
- Prevents Redis outages from blocking all traffic
- Log errors for monitoring
- Return full limit as remaining

### HTTP Headers (TECH SPEC §6.5)

**Standard headers:**
- `X-RateLimit-Limit`: Total limit
- `X-RateLimit-Remaining`: Remaining in window
- `X-RateLimit-Reset`: Unix timestamp of reset

**On 429 response:**
- Add `Retry-After` header (seconds)
- Include `retry_after_ms` in error body

## Testing Requirements

### Unit Tests (`tests/unit/test_rate_limiter.py`)

```python
import pytest
import time
from butterscout.services.rate_limiter import RateLimiter

@pytest.mark.asyncio
async def test_rate_limit_allows_within_limit(redis_client, settings):
    """Test that requests within limit are allowed"""
    settings.BS_RATE_LIMIT_PER_HOUR = 10
    limiter = RateLimiter(redis_client, settings)

    # Make 5 requests (under limit)
    for i in range(5):
        is_allowed, retry_after, remaining, limit = await limiter.check_rate_limit(
            client_ip="192.168.1.1",
            api_key=None,
            request_id=f"test-{i}",
        )
        assert is_allowed is True
        assert retry_after is None

@pytest.mark.asyncio
async def test_rate_limit_blocks_over_limit(redis_client, settings):
    """Test that requests over limit are blocked"""
    settings.BS_RATE_LIMIT_PER_HOUR = 5
    limiter = RateLimiter(redis_client, settings)

    # Make 5 requests (at limit)
    for i in range(5):
        await limiter.check_rate_limit(
            client_ip="192.168.1.2",
            api_key=None,
            request_id=f"test-{i}",
        )

    # 6th request should be blocked
    is_allowed, retry_after, remaining, limit = await limiter.check_rate_limit(
        client_ip="192.168.1.2",
        api_key=None,
        request_id="test-6",
    )

    assert is_allowed is False
    assert retry_after is not None
    assert retry_after > 0
    assert remaining == 0

@pytest.mark.asyncio
async def test_api_key_higher_limit(redis_client, settings):
    """Test that API keys get higher rate limits"""
    settings.BS_RATE_LIMIT_PER_HOUR = 10
    settings.BS_API_KEY_RATE_LIMIT_PER_HOUR = 100
    limiter = RateLimiter(redis_client, settings)

    # Make 15 requests with API key (over IP limit, under key limit)
    for i in range(15):
        is_allowed, _, _, limit = await limiter.check_rate_limit(
            client_ip="192.168.1.3",
            api_key="test-api-key",
            request_id=f"test-{i}",
        )
        assert is_allowed is True
        assert limit == 100  # Using API key limit

@pytest.mark.asyncio
async def test_rate_limit_headers():
    """Test rate limit header generation"""
    from butterscout.utils.rate_limit_headers import generate_rate_limit_headers

    headers = generate_rate_limit_headers(
        limit=100,
        remaining=75,
        retry_after=None,
    )

    assert headers["X-RateLimit-Limit"] == "100"
    assert headers["X-RateLimit-Remaining"] == "75"
    assert "X-RateLimit-Reset" in headers

    # With retry-after
    headers = generate_rate_limit_headers(
        limit=100,
        remaining=0,
        retry_after=3600,
    )

    assert headers["Retry-After"] == "3600"
```

### Integration Tests

- Test window sliding behavior over time
- Test multiple clients simultaneously
- Test Redis failure (verify fail-open)
- Test global rate limit interaction

## Performance Requirements

- Rate limit check: < 10ms
- Support 1000+ requests/second (single node)
- Minimal Redis memory usage (ZSET cleanup)

## Output Format

When complete, provide:

1. ✅ All files created
2. ✅ Tests passing
3. 📊 Performance benchmark:
   - 1000 rate limit checks timing
   - Memory usage with many clients
4. 📝 Example showing:
   - Request allowed with headers
   - Request blocked with retry-after

## Dependencies

- **Task 01** (Project Foundation)
- **Task 02** (Redis Client)

## Time Estimate

4-5 hours

## Reference

- [TECH SPEC.md] §4.1: Caching & Rate Limiting
- [TECH SPEC.md] §6.2: Rate limits configuration
- [TECH SPEC.md] §6.5: Auth & Rate-Limit Semantics
- [TECH SPEC.md] §7.2: Rate limit env vars
