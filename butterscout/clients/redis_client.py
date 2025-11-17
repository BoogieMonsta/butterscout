"""Async Valkey client with connection pooling."""
from __future__ import annotations

import logging
from typing import Optional

import valkey.asyncio as valkey

from butterscout.config import Settings

logger = logging.getLogger(__name__)


class ValkeyClient:
    """Async Valkey client with connection pooling."""

    def __init__(self, settings: Settings):
        """Initialize Valkey client with settings."""
        self.settings = settings
        self.valkey: Optional[valkey.Valkey] = None

    async def connect(self) -> None:
        """Establish Valkey connection pool."""
        try:
            logger.info("Connecting to Valkey at %s", self.settings.BS_REDIS_URL)
            self.valkey = await valkey.from_url(  # type: ignore
                self.settings.BS_REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=200,
                socket_keepalive=True,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            # Verify connection with ping
            await self.valkey.ping()
            logger.info("Successfully connected to Valkey")
        except Exception as e:
            logger.error(
                "Failed to connect to Valkey at %s: %s. "
                "Ensure Valkey is running and the URL is correct.",
                self.settings.BS_REDIS_URL,
                str(e),
            )
            raise

    async def disconnect(self) -> None:
        """Close Valkey connection pool."""
        if self.valkey:
            logger.info("Disconnecting from Valkey")
            await self.valkey.aclose()  # close is deprecated; aclose is the async variant
            logger.info("Disconnected from Valkey")
            self.valkey = None

    async def ping(self) -> bool:
        """Health check - returns True if Valkey is responsive.

        Returns:
            True if Valkey responds to ping, False otherwise
        """
        if not self.valkey:
            return False
        try:
            await self.valkey.ping()
            return True
        except Exception:
            return False

    async def get(self, key: str) -> Optional[str]:
        """Get value by key.

        Args:
            key: Valkey key to retrieve

        Returns:
            Value associated with key, or None if key doesn't exist

        Raises:
            RuntimeError: If Valkey is not connected
        """
        if not self.valkey:
            raise RuntimeError(
                "Valkey client not connected. "
                "Call 'await client.connect()' before using Valkey operations."
            )
        return await self.valkey.get(key)  # type: ignore

    async def set(
        self, key: str, value: str, ttl_seconds: Optional[int] = None
    ) -> bool:
        """Set key-value with optional TTL.

        Args:
            key: Valkey key to set
            value: Value to store
            ttl_seconds: Optional time-to-live in seconds

        Returns:
            True if operation succeeded

        Raises:
            RuntimeError: If Valkey is not connected
        """
        if not self.valkey:
            raise RuntimeError(
                "Valkey client not connected. "
                "Call 'await client.connect()' before using Valkey operations."
            )

        if ttl_seconds:
            result: Optional[bool] = await self.valkey.setex(key, ttl_seconds, value)
        else:
            result = await self.valkey.set(key, value)
        return bool(result)

    async def delete(self, key: str) -> int:
        """Delete key, returns number of keys deleted.

        Args:
            key: Valkey key to delete

        Returns:
            Number of keys deleted (0 or 1)

        Raises:
            RuntimeError: If Valkey is not connected
        """
        if not self.valkey:
            raise RuntimeError(
                "Valkey client not connected. "
                "Call 'await client.connect()' before using Valkey operations."
            )
        return await self.valkey.delete(key)  # type: ignore

    async def exists(self, key: str) -> bool:
        """Check if key exists.

        Args:
            key: Valkey key to check

        Returns:
            True if key exists, False otherwise

        Raises:
            RuntimeError: If Valkey is not connected
        """
        if not self.valkey:
            raise RuntimeError(
                "Valkey client not connected. "
                "Call 'await client.connect()' before using Valkey operations."
            )
        return await self.valkey.exists(key) > 0  # type: ignore

    async def incr(self, key: str) -> int:
        """Increment integer value at key.

        Args:
            key: Valkey key to increment

        Returns:
            New value after increment

        Raises:
            RuntimeError: If Valkey is not connected
        """
        if not self.valkey:
            raise RuntimeError(
                "Valkey client not connected. "
                "Call 'await client.connect()' before using Valkey operations."
            )
        return await self.valkey.incr(key)  # type: ignore

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration on key.

        Args:
            key: Valkey key to set expiration on
            seconds: Time-to-live in seconds

        Returns:
            True if expiration was set, False if key doesn't exist

        Raises:
            RuntimeError: If Valkey is not connected
        """
        if not self.valkey:
            raise RuntimeError(
                "Valkey client not connected. "
                "Call 'await client.connect()' before using Valkey operations."
            )
        return await self.valkey.expire(key, seconds)  # type: ignore

    async def ttl(self, key: str) -> int:
        """Get TTL of key in seconds.

        Args:
            key: Valkey key to get TTL for

        Returns:
            TTL in seconds, -1 if no expiry set, -2 if key doesn't exist

        Raises:
            RuntimeError: If Valkey is not connected
        """
        if not self.valkey:
            raise RuntimeError(
                "Valkey client not connected. "
                "Call 'await client.connect()' before using Valkey operations."
            )
        return await self.valkey.ttl(key)  # type: ignore
