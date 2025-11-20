from __future__ import annotations

import asyncio
import time
from typing import Protocol

from butterscout.clients.redis_client import ValkeyClient


class CacheBackend(Protocol):
    """Protocol for cache backends."""

    async def get(self, key: str) -> str | None:
        """Get a value from the cache.

        Args:
            key: Cache key to retrieve

        Returns:
            Cached value if found and not expired, None otherwise
        """
        ...

    async def set(self, key: str, value: str, ttl: int) -> bool:
        """Set a value in the cache with a TTL.

        Args:
            key: Cache key to set
            value: Value to cache
            ttl: Time-to-live in seconds

        Returns:
            True if operation succeeded
        """
        ...

    async def delete(self, key: str) -> int:
        """Delete a value from the cache.

        Args:
            key: Cache key to delete

        Returns:
            Number of keys deleted (0 or 1)
        """
        ...

    async def health_check(self) -> bool:
        """Check if the backend is healthy.

        Returns:
            True if backend is operational, False otherwise
        """
        ...


class RedisBackend:
    """Redis-based cache backend using Valkey client."""

    def __init__(self, client: ValkeyClient) -> None:
        """Initialize Redis backend.

        Args:
            client: Connected ValkeyClient instance
        """
        self.client = client

    async def get(self, key: str) -> str | None:
        """Get a value from Redis cache."""
        return await self.client.get(key)

    async def set(self, key: str, value: str, ttl: int) -> bool:
        """Set a value in Redis cache with TTL.

        Returns:
            True if operation succeeded
        """
        return await self.client.set(key, value, ttl_seconds=ttl)

    async def delete(self, key: str) -> int:
        """Delete a value from Redis cache."""
        return await self.client.delete(key)

    async def health_check(self) -> bool:
        """Check Redis connection health."""
        return await self.client.ping()


class MemoryBackend:
    """In-memory cache backend for development/testing.

    This backend provides a thread-safe, TTL-aware in-memory cache
    with automatic cleanup of expired entries. Suitable for development
    and testing when Redis is not available.
    """

    def __init__(self) -> None:
        """Initialize in-memory cache backend."""
        self._store: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()
        self._last_cleanup = time.time()

    async def _cleanup_expired(self) -> None:
        """Remove expired entries from the cache.

        Called periodically during get/set operations to prevent
        unbounded memory growth. Uses a 60-second cleanup interval.
        """
        current_time = time.time()
        # Only cleanup every 60 seconds to avoid overhead
        if current_time - self._last_cleanup < 60:
            return

        self._last_cleanup = current_time
        expired_keys = [key for key, (_, expiry) in self._store.items() if current_time > expiry]
        for key in expired_keys:
            del self._store[key]

    async def get(self, key: str) -> str | None:
        """Get a value from in-memory cache."""
        async with self._lock:
            if key not in self._store:
                return None

            value, expiry = self._store[key]
            if time.time() > expiry:
                del self._store[key]
                return None

            # Opportunistic cleanup of other expired entries
            await self._cleanup_expired()
            return value

    async def set(self, key: str, value: str, ttl: int) -> bool:
        """Set a value in in-memory cache with TTL.

        Returns:
            True if operation succeeded
        """
        async with self._lock:
            self._store[key] = (value, time.time() + ttl)
            # Opportunistic cleanup of expired entries
            await self._cleanup_expired()
        return True

    async def delete(self, key: str) -> int:
        """Delete a value from in-memory cache."""
        async with self._lock:
            if key in self._store:
                del self._store[key]
                return 1
            return 0

    async def health_check(self) -> bool:
        """Check in-memory cache health.

        Always returns True as in-memory cache has no external dependencies.
        """
        return True
