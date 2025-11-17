"""Integration tests for Valkey client against real Valkey instance."""
from __future__ import annotations

import asyncio

import pytest

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.utils.redis_manager import close_valkey, init_valkey


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        BS_REDIS_URL="valkey://localhost:6379/1",  # Use database 1 for tests
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_connection_pool_lifecycle(settings: Settings) -> None:
    """Test Valkey connection pool initialization and cleanup."""
    client = ValkeyClient(settings)

    # Not connected initially
    assert client.valkey is None
    assert await client.ping() is False

    # Connect
    await client.connect()
    assert client.valkey is not None
    assert await client.ping() is True

    # Disconnect
    await client.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_concurrent_operations(settings: Settings) -> None:
    """Test connection pool under concurrent load."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Run 100 concurrent operations
        async def set_and_get(i: int) -> bool:
            key = f"test:concurrent:{i}"
            await client.set(key, f"value_{i}", ttl_seconds=10)
            value = await client.get(key)
            await client.delete(key)
            return value == f"value_{i}"

        # Execute concurrently
        results = await asyncio.gather(*[set_and_get(i) for i in range(100)])

        # All operations should succeed
        assert all(results)
    finally:
        await client.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ttl_expiration_behavior(settings: Settings) -> None:
    """Test that TTL expiration works correctly."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Set key with 1 second TTL
        await client.set("test:ttl", "value", ttl_seconds=1)

        # Key should exist initially
        assert await client.exists("test:ttl") is True

        # Wait for expiration
        await asyncio.sleep(1.5)

        # Key should be expired
        assert await client.exists("test:ttl") is False
    finally:
        await client.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_valkey_manager_lifecycle(settings: Settings) -> None:
    """Test Valkey manager initialization and cleanup."""
    # Initialize
    client = await init_valkey(settings)
    assert client is not None
    assert await client.ping() is True

    # Can perform operations
    await client.set("test:manager", "value")
    value = await client.get("test:manager")
    assert value == "value"

    # Cleanup
    await client.delete("test:manager")
    await close_valkey()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_large_value_storage(settings: Settings) -> None:
    """Test storing and retrieving large values."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Create a large value (1MB)
        large_value = "x" * (1024 * 1024)

        # Store and retrieve
        await client.set("test:large", large_value, ttl_seconds=10)
        retrieved = await client.get("test:large")

        assert retrieved == large_value

        # Cleanup
        await client.delete("test:large")
    finally:
        await client.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_increment_operations_concurrent(settings: Settings) -> None:
    """Test increment operations under concurrent load."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Run 50 concurrent increments
        async def increment() -> int:
            return await client.incr("test:concurrent_incr")

        # Execute concurrently
        results = await asyncio.gather(*[increment() for _ in range(50)])

        # Should get values from 1 to 50 in some order
        assert sorted(results) == list(range(1, 51))

        # Final value should be 50
        final = await client.get("test:concurrent_incr")
        assert final == "50"

        # Cleanup
        await client.delete("test:concurrent_incr")
    finally:
        await client.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multiple_key_operations(settings: Settings) -> None:
    """Test operations on multiple keys."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Set multiple keys
        keys = [f"test:multi:{i}" for i in range(10)]
        for i, key in enumerate(keys):
            await client.set(key, f"value_{i}", ttl_seconds=60)

        # Verify all exist
        for i, key in enumerate(keys):
            value = await client.get(key)
            assert value == f"value_{i}"
            assert await client.exists(key) is True

        # Delete all
        for key in keys:
            count = await client.delete(key)
            assert count == 1

        # Verify all deleted
        for key in keys:
            assert await client.exists(key) is False
    finally:
        await client.disconnect()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_error_handling_invalid_operations(settings: Settings) -> None:
    """Test error handling for invalid operations."""
    client = ValkeyClient(settings)
    await client.connect()

    try:
        # Set a string value
        await client.set("test:string", "not_a_number")

        # Try to increment it (should raise an error)
        with pytest.raises(Exception):  # noqa: B017 - Valkey raises ResponseError for type mismatch
            await client.incr("test:string")

        # Cleanup
        await client.delete("test:string")
    finally:
        await client.disconnect()
