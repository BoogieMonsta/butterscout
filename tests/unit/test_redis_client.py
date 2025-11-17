"""Unit tests for Valkey client."""
from __future__ import annotations

import pytest
import pytest_asyncio

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        BS_REDIS_URL="valkey://localhost:6379/0",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
    )


@pytest_asyncio.fixture
async def valkey_client(settings: Settings) -> ValkeyClient:
    """Create Valkey client fixture."""
    client = ValkeyClient(settings)
    return client


@pytest.mark.asyncio
async def test_redis_operations_require_connection(valkey_client: ValkeyClient) -> None:
    """Test that operations fail gracefully when not connected."""
    error_msg = "Valkey client not connected"

    with pytest.raises(RuntimeError, match=error_msg):
        await valkey_client.get("test:key")

    with pytest.raises(RuntimeError, match=error_msg):
        await valkey_client.set("test:key", "value")

    with pytest.raises(RuntimeError, match=error_msg):
        await valkey_client.delete("test:key")

    with pytest.raises(RuntimeError, match=error_msg):
        await valkey_client.exists("test:key")

    with pytest.raises(RuntimeError, match=error_msg):
        await valkey_client.incr("test:counter")

    with pytest.raises(RuntimeError, match=error_msg):
        await valkey_client.expire("test:key", 10)

    with pytest.raises(RuntimeError, match=error_msg):
        await valkey_client.ttl("test:key")


@pytest.mark.asyncio
async def test_ping_returns_false_when_not_connected(valkey_client: ValkeyClient) -> None:
    """Test that ping returns False when not connected."""
    result = await valkey_client.ping()
    assert result is False


# Integration tests - only run if Valkey/Redis is available
@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_connection(settings: Settings) -> None:
    """Test Valkey/Redis connection and ping."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        assert await client.ping() is True
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_get_set(settings: Settings) -> None:
    """Test basic get/set operations."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Set value
        result = await client.set("test:key", "test_value", ttl_seconds=10)
        assert result is True

        # Get value
        value = await client.get("test:key")
        assert value == "test_value"

        # Check TTL
        ttl = await client.ttl("test:key")
        assert 0 < ttl <= 10

        # Clean up
        await client.delete("test:key")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_exists(settings: Settings) -> None:
    """Test key existence checking."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Key should not exist initially
        assert await client.exists("test:exists") is False

        # Set key
        await client.set("test:exists", "value")

        # Key should now exist
        assert await client.exists("test:exists") is True

        # Clean up
        await client.delete("test:exists")

        # Key should not exist after deletion
        assert await client.exists("test:exists") is False
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_incr(settings: Settings) -> None:
    """Test increment operations."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # First increment creates key with value 1
        value = await client.incr("test:counter")
        assert value == 1

        # Second increment increases to 2
        value = await client.incr("test:counter")
        assert value == 2

        # Third increment increases to 3
        value = await client.incr("test:counter")
        assert value == 3

        # Clean up
        await client.delete("test:counter")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_expire(settings: Settings) -> None:
    """Test setting expiration on keys."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Set key without expiration
        await client.set("test:expire", "value")

        # TTL should be -1 (no expiration)
        ttl = await client.ttl("test:expire")
        assert ttl == -1

        # Set expiration
        result = await client.expire("test:expire", 60)
        assert result is True

        # TTL should now be set
        ttl = await client.ttl("test:expire")
        assert 0 < ttl <= 60

        # Clean up
        await client.delete("test:expire")
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_delete(settings: Settings) -> None:
    """Test key deletion."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Set a key
        await client.set("test:delete", "value")

        # Delete should return 1 (one key deleted)
        count = await client.delete("test:delete")
        assert count == 1

        # Deleting non-existent key should return 0
        count = await client.delete("test:delete")
        assert count == 0
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_redis_ttl_nonexistent_key(settings: Settings) -> None:
    """Test TTL on non-existent key."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # TTL on non-existent key should return -2
        ttl = await client.ttl("test:nonexistent")
        assert ttl == -2
    finally:
        await client.disconnect()
