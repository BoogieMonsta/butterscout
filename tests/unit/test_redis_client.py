"""Unit tests for Valkey client."""

from __future__ import annotations

from typing import Any

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


@pytest.mark.asyncio
async def test_initialization(settings: Settings) -> None:
    """Test Valkey client initialization."""
    client = ValkeyClient(settings)

    assert client.settings is settings
    assert client.valkey is None


@pytest.mark.asyncio
async def test_connect_disconnect_cycle(settings: Settings) -> None:
    """Test connect/disconnect cycle using mocks."""
    from unittest.mock import AsyncMock, patch

    client = ValkeyClient(settings)

    with patch("butterscout.clients.redis_client.valkey.from_url") as mock_from_url:
        mock_pool = AsyncMock()
        # Make from_url return an awaitable

        async def async_from_url(*args: Any, **kwargs: Any) -> Any:
            return mock_pool

        mock_from_url.side_effect = async_from_url

        # Connect
        await client.connect()
        assert client.valkey is mock_pool
        mock_from_url.assert_called_once()

        # Disconnect
        await client.disconnect()
        assert client.valkey is None
        mock_pool.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_get_with_mocked_valkey(settings: Settings) -> None:
    """Test get operation with mocked Valkey."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    # Valkey client has decode_responses=True, so returns string not bytes
    client.valkey.get = AsyncMock(return_value="test_value")

    result = await client.get("test:key")

    assert result == "test_value"
    client.valkey.get.assert_called_once_with("test:key")


@pytest.mark.asyncio
async def test_get_returns_none_when_key_not_found(settings: Settings) -> None:
    """Test get returns None when key doesn't exist."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.get = AsyncMock(return_value=None)

    result = await client.get("test:missing")

    assert result is None


@pytest.mark.asyncio
async def test_set_with_ttl(settings: Settings) -> None:
    """Test set operation with TTL."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.setex = AsyncMock(return_value=True)

    result = await client.set("test:key", "value", ttl_seconds=60)

    assert result is True
    client.valkey.setex.assert_called_once_with("test:key", 60, "value")


@pytest.mark.asyncio
async def test_set_without_ttl(settings: Settings) -> None:
    """Test set operation without TTL."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.set = AsyncMock(return_value=True)

    result = await client.set("test:key", "value")

    assert result is True
    client.valkey.set.assert_called_once_with("test:key", "value")


@pytest.mark.asyncio
async def test_delete_single_key(settings: Settings) -> None:
    """Test deleting a single key."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.delete = AsyncMock(return_value=1)

    result = await client.delete("test:key")

    assert result == 1
    client.valkey.delete.assert_called_once_with("test:key")


@pytest.mark.asyncio
async def test_exists_key_present(settings: Settings) -> None:
    """Test exists when key is present."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.exists = AsyncMock(return_value=1)

    result = await client.exists("test:key")

    assert result is True


@pytest.mark.asyncio
async def test_exists_key_absent(settings: Settings) -> None:
    """Test exists when key is absent."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.exists = AsyncMock(return_value=0)

    result = await client.exists("test:key")

    assert result is False


@pytest.mark.asyncio
async def test_incr_operation(settings: Settings) -> None:
    """Test increment operation."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.incr = AsyncMock(return_value=5)

    result = await client.incr("test:counter")

    assert result == 5
    client.valkey.incr.assert_called_once_with("test:counter")


@pytest.mark.asyncio
async def test_expire_operation(settings: Settings) -> None:
    """Test expire operation."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.expire = AsyncMock(return_value=1)

    result = await client.expire("test:key", 60)

    assert result == 1
    client.valkey.expire.assert_called_once_with("test:key", 60)


@pytest.mark.asyncio
async def test_ttl_operation(settings: Settings) -> None:
    """Test TTL operation."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.ttl = AsyncMock(return_value=120)

    result = await client.ttl("test:key")

    assert result == 120
    client.valkey.ttl.assert_called_once_with("test:key")


@pytest.mark.asyncio
async def test_ping_when_connected(settings: Settings) -> None:
    """Test ping when connected."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.ping = AsyncMock(return_value=True)

    result = await client.ping()

    assert result is True
    client.valkey.ping.assert_called_once()


@pytest.mark.asyncio
async def test_set_with_ttl_zero(settings: Settings) -> None:
    """Test set operation with TTL=0 (should use set without TTL)."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.set = AsyncMock(return_value=True)

    result = await client.set("test:key", "value", ttl_seconds=0)

    assert result is True
    # Should use set() not setex() when ttl_seconds=0
    client.valkey.set.assert_called_once_with("test:key", "value")


@pytest.mark.asyncio
async def test_set_with_invalid_ttl_type(settings: Settings) -> None:
    """Test set operation with invalid TTL type raises TypeError."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()

    with pytest.raises(TypeError, match="ttl_seconds must be an integer"):
        await client.set("test:key", "value", ttl_seconds="60")  # type: ignore


@pytest.mark.asyncio
async def test_set_with_negative_ttl(settings: Settings) -> None:
    """Test set operation with negative TTL raises ValueError."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()

    with pytest.raises(ValueError, match="ttl_seconds must be non-negative"):
        await client.set("test:key", "value", ttl_seconds=-10)


@pytest.mark.asyncio
async def test_set_with_ttl_handles_setex_error(settings: Settings) -> None:
    """Test that set with TTL properly handles and re-raises setex errors."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.setex = AsyncMock(side_effect=Exception("Redis connection error"))

    with pytest.raises(Exception, match="Redis connection error"):
        await client.set("test:key", "value", ttl_seconds=60)


@pytest.mark.asyncio
async def test_set_without_ttl_handles_set_error(settings: Settings) -> None:
    """Test that set without TTL properly handles and re-raises set errors."""
    from unittest.mock import AsyncMock

    client = ValkeyClient(settings)
    client.valkey = AsyncMock()
    client.valkey.set = AsyncMock(side_effect=Exception("Redis connection error"))

    with pytest.raises(Exception, match="Redis connection error"):
        await client.set("test:key", "value")


# Integration tests moved to tests/integration/test_redis_integration.py
