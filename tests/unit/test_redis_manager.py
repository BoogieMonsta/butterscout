"""Unit tests for redis manager."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from butterscout.config import Settings
from butterscout.utils.redis_manager import (
    close_valkey,
    get_valkey_client,
    init_valkey,
    valkey_lifespan,
)


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        BS_REDIS_URL="redis://localhost:6379/15",
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
    )


@pytest.mark.asyncio
async def test_init_valkey(settings: Settings) -> None:
    """Test initializing Valkey client."""
    with patch("butterscout.utils.redis_manager.ValkeyClient") as mock_client_class:
        mock_instance = AsyncMock()
        mock_instance.connect = AsyncMock()
        mock_client_class.return_value = mock_instance

        client = await init_valkey(settings)

        assert client is mock_instance
        mock_client_class.assert_called_once_with(settings)
        mock_instance.connect.assert_called_once()


@pytest.mark.asyncio
async def test_get_valkey_client_not_initialized() -> None:
    """Test getting Valkey client before initialization raises error."""
    # Reset global state
    import butterscout.utils.redis_manager as manager
    manager._valkey_client = None

    with pytest.raises(RuntimeError, match="Valkey client not initialized"):
        get_valkey_client()


@pytest.mark.asyncio
async def test_get_valkey_client_after_init(settings: Settings) -> None:
    """Test getting Valkey client after initialization."""
    import butterscout.utils.redis_manager as manager

    with patch("butterscout.utils.redis_manager.ValkeyClient") as mock_client_class:
        mock_instance = AsyncMock()
        mock_instance.connect = AsyncMock()
        mock_client_class.return_value = mock_instance

        # Initialize
        await init_valkey(settings)

        # Get should work now
        client = get_valkey_client()
        assert client is mock_instance

        # Cleanup
        manager._valkey_client = None


@pytest.mark.asyncio
async def test_close_valkey_when_initialized(settings: Settings) -> None:
    """Test closing Valkey client when initialized."""
    import butterscout.utils.redis_manager as manager

    with patch("butterscout.utils.redis_manager.ValkeyClient") as mock_client_class:
        mock_instance = AsyncMock()
        mock_instance.connect = AsyncMock()
        mock_instance.disconnect = AsyncMock()
        mock_client_class.return_value = mock_instance

        # Initialize
        await init_valkey(settings)

        # Close
        await close_valkey()

        mock_instance.disconnect.assert_called_once()
        assert manager._valkey_client is None


@pytest.mark.asyncio
async def test_close_valkey_when_not_initialized() -> None:
    """Test closing Valkey client when not initialized doesn't error."""
    import butterscout.utils.redis_manager as manager
    manager._valkey_client = None

    # Should not raise
    await close_valkey()

    assert manager._valkey_client is None


@pytest.mark.asyncio
async def test_valkey_lifespan(settings: Settings) -> None:
    """Test valkey lifespan context manager."""
    with patch("butterscout.utils.redis_manager.ValkeyClient") as mock_client_class:
        mock_instance = AsyncMock()
        mock_instance.connect = AsyncMock()
        mock_instance.disconnect = AsyncMock()
        mock_client_class.return_value = mock_instance

        async with valkey_lifespan(settings) as client:
            # Client should be initialized
            assert client is mock_instance
            mock_instance.connect.assert_called_once()

        # Client should be disconnected after context
        mock_instance.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_valkey_lifespan_cleanup_on_error(settings: Settings) -> None:
    """Test that valkey lifespan cleans up even on error."""
    with patch("butterscout.utils.redis_manager.ValkeyClient") as mock_client_class:
        mock_instance = AsyncMock()
        mock_instance.connect = AsyncMock()
        mock_instance.disconnect = AsyncMock()
        mock_client_class.return_value = mock_instance

        with pytest.raises(RuntimeError):
            async with valkey_lifespan(settings) as client:
                assert client is mock_instance
                raise RuntimeError("Test error")

        # Should still disconnect on error
        mock_instance.disconnect.assert_called_once()


@pytest.mark.asyncio
async def test_init_valkey_multiple_calls(settings: Settings) -> None:
    """Test that multiple init calls replace the global instance."""
    import butterscout.utils.redis_manager as manager

    with patch("butterscout.utils.redis_manager.ValkeyClient") as mock_client_class:
        mock_instance1 = AsyncMock()
        mock_instance1.connect = AsyncMock()
        mock_instance2 = AsyncMock()
        mock_instance2.connect = AsyncMock()

        mock_client_class.side_effect = [mock_instance1, mock_instance2]

        # First init
        client1 = await init_valkey(settings)
        assert client1 is mock_instance1

        # Second init (should replace)
        client2 = await init_valkey(settings)
        assert client2 is mock_instance2

        # Global should be the second instance
        assert manager._valkey_client is mock_instance2

        # Cleanup
        manager._valkey_client = None
