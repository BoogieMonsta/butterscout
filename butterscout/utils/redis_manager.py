"""Valkey connection lifecycle management and dependency injection."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings

logger = logging.getLogger(__name__)

# Global instance
_valkey_client: Optional[ValkeyClient] = None


def get_valkey_client() -> ValkeyClient:
    """Get singleton Valkey client instance.

    Returns:
        The global ValkeyClient instance

    Raises:
        RuntimeError: If Valkey client has not been initialized
    """
    global _valkey_client
    if _valkey_client is None:
        raise RuntimeError("Valkey client not initialized")
    return _valkey_client


async def init_valkey(settings: Settings) -> ValkeyClient:
    """Initialize Valkey client on startup.

    Args:
        settings: Application settings containing Valkey configuration

    Returns:
        Initialized and connected ValkeyClient instance
    """
    global _valkey_client
    logger.info("Initializing Valkey client")
    _valkey_client = ValkeyClient(settings)
    await _valkey_client.connect()
    logger.info("Valkey client initialized successfully")
    return _valkey_client


async def close_valkey() -> None:
    """Close Valkey connection on shutdown."""
    global _valkey_client
    if _valkey_client:
        logger.info("Closing Valkey client")
        await _valkey_client.disconnect()
        _valkey_client = None
        logger.info("Valkey client closed")


@asynccontextmanager
async def valkey_lifespan(settings: Settings) -> AsyncGenerator[ValkeyClient, None]:
    """Lifespan context manager for FastAPI.

    This context manager handles Valkey/Redis client initialization and cleanup
    for the FastAPI application lifespan.

    Args:
        settings: Application settings containing Valkey configuration

    Yields:
        Initialized ValkeyClient instance

    Example:
        ```python
        from contextlib import asynccontextmanager
        from fastapi import FastAPI

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            settings = load_settings()
            async with valkey_lifespan(settings) as valkey_client:
                # Valkey is connected and ready
                yield
            # Valkey is automatically disconnected
        ```
    """
    client = await init_valkey(settings)
    try:
        yield client
    finally:
        await close_valkey()
