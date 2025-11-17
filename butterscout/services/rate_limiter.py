"""Sliding window rate limiter using Valkey."""
import time
from typing import Any, Optional, Sequence, Tuple, cast

import structlog

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.utils.redis_keys import generate_rate_limit_key

logger = structlog.get_logger()


class RateLimiter:
    """Sliding window rate limiter using Valkey (Redis protocol)."""

    def __init__(self, redis_client: ValkeyClient, settings: Settings):
        """Initialize rate limiter.

        Args:
            redis_client: Valkey client instance
            settings: Application settings
        """
        self.redis = redis_client
        self.settings = settings

    async def check_rate_limit(
        self, client_ip: str, api_key: Optional[str], request_id: str
    ) -> Tuple[bool, Optional[int], int, int, int]:
        """Check if request is within rate limits.

        Args:
            client_ip: Client IP address
            api_key: Optional API key
            request_id: Request ID for logging

        Returns:
            Tuple of (is_allowed, retry_after_seconds, remaining, limit, reset_timestamp)
            - is_allowed: True if request should proceed
            - retry_after_seconds: Seconds until retry (if rate limited)
            - remaining: Remaining requests in window
            - limit: Total limit per window
            - reset_timestamp: Unix timestamp when rate limit resets
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
        is_allowed, retry_after, remaining, reset_timestamp = await self._check_limit(
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
            return False, retry_after, 0, limit_per_hour, reset_timestamp

        # Check global rate limit if configured
        if self.settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR > 0:
            result = await self._check_global_limit(request_id)
            global_allowed, global_retry, _, global_reset = result
            if not global_allowed:
                logger.warning(
                    "global_rate_limit_exceeded",
                    request_id=request_id,
                )
                return (
                    False,
                    global_retry,
                    0,
                    self.settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR,
                    global_reset,
                )

        logger.info(
            "rate_limit_ok",
            request_id=request_id,
            key_type=key_type,
            remaining=remaining,
            limit=limit_per_hour,
        )

        return True, None, remaining, limit_per_hour, reset_timestamp

    async def _check_limit(
        self,
        identifier: str,
        key_type: str,
        limit_per_hour: int,
        request_id: str,
    ) -> Tuple[bool, Optional[int], int, int]:
        """Check rate limit using sliding window algorithm with atomic operations.

        Args:
            identifier: IP or API key
            key_type: "ip" or "api_key"
            limit_per_hour: Max requests per hour
            request_id: Request ID

        Returns:
            Tuple of (is_allowed, retry_after_seconds, remaining, reset_timestamp)
        """
        rate_limit_key = generate_rate_limit_key(identifier, key_type)
        window_seconds = 3600  # 1 hour
        current_time = int(time.time())
        cutoff_time = current_time - window_seconds
        reset_timestamp = current_time + window_seconds

        try:
            # Use Lua script for atomic operations to prevent race conditions
            # This ensures check-and-add happens atomically even under high concurrency
            lua_script = """
            local key = KEYS[1]
            local cutoff = tonumber(ARGV[1])
            local current_time = tonumber(ARGV[2])
            local limit = tonumber(ARGV[3])
            local request_id = ARGV[4]
            local window_seconds = tonumber(ARGV[5])
            local expiry = tonumber(ARGV[6])

            -- Remove old entries outside the window
            redis.call('ZREMRANGEBYSCORE', key, '-inf', cutoff)

            -- Count requests in current window
            local count = redis.call('ZCARD', key)

            -- Get oldest entry timestamp for reset calculation
            local oldest_timestamp = nil
            if count > 0 then
                local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
                if oldest and oldest[2] then
                    oldest_timestamp = tonumber(oldest[2])
                end
            end

            -- Check if we're at or over limit
            if count >= limit then
                return {0, count, oldest_timestamp or current_time}
            end

            -- Under limit - add current request
            redis.call('ZADD', key, current_time, request_id)
            redis.call('EXPIRE', key, expiry)

            -- Return success with updated count
            return {1, count + 1, oldest_timestamp or current_time}
            """

            # Execute Lua script atomically
            result = cast(
                Sequence[Any],
                await self.redis.eval(
                    lua_script,
                    1,  # Number of keys
                    rate_limit_key,  # KEYS[1]
                    cutoff_time,  # ARGV[1]
                    current_time,  # ARGV[2]
                    limit_per_hour,  # ARGV[3]
                    request_id,  # ARGV[4]
                    window_seconds,  # ARGV[5]
                    window_seconds + 60,  # ARGV[6] - expiry with buffer
                ),
            )

            if len(result) < 3:
                raise ValueError("Unexpected response from rate limit script")

            is_allowed = bool(result[0])
            count = int(result[1])
            oldest_timestamp = int(result[2])

            # Calculate reset time based on oldest entry
            reset_timestamp = oldest_timestamp + window_seconds

            if not is_allowed:
                # Rate limit exceeded
                retry_after = reset_timestamp - current_time
                retry_after = max(1, retry_after)  # At least 1 second
                remaining = 0
                return False, retry_after, remaining, reset_timestamp

            # Request allowed
            remaining = limit_per_hour - count
            return True, None, remaining, reset_timestamp

        except Exception as e:
            logger.error(
                "rate_limit_check_error",
                request_id=request_id,
                error=str(e),
            )
            # On error, allow request (fail open)
            return True, None, limit_per_hour, reset_timestamp

    async def _check_global_limit(self, request_id: str) -> Tuple[bool, Optional[int], int, int]:
        """Check global rate limit across all users.

        Args:
            request_id: Request ID for logging

        Returns:
            Tuple of (is_allowed, retry_after_seconds, remaining, reset_timestamp)
        """
        return await self._check_limit(
            "global",
            "global",
            self.settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR,
            request_id,
        )
