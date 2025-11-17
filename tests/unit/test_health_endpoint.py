"""Unit tests for health endpoint."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_health_endpoint_structure_mocked() -> None:
    """Test health endpoint returns correct structure with mocked dependencies."""
    # Mock the clients
    with patch("butterscout.main.app_state") as mock_app_state:
        # Setup mock settings
        mock_settings = MagicMock()
        mock_settings.BS_HEALTH_TIMEOUT_MS = 750
        mock_app_state.settings = mock_settings

        # Setup mock clients with successful health checks
        mock_app_state.redis_client.ping = AsyncMock(return_value=True)
        mock_app_state.searxng_client.health_check = AsyncMock(return_value=True)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(return_value=True)

        # Import after patching to avoid import errors
        from butterscout.routers.health import health_check
        from fastapi import Response

        response = Response()
        result = await health_check(response)

        # Verify structure
        assert result.status == "ok"
        assert "valkey" in result.components
        assert "searxng" in result.components
        assert "crawl4ai" in result.components
        assert result.version == "0.1.0"
        assert result.uptime_seconds >= 0
        assert result.timestamp > 0
        assert response.status_code == 200

        # Verify component status
        assert result.components["valkey"].status == "ok"
        assert result.components["searxng"].status == "ok"
        assert result.components["crawl4ai"].status == "ok"


@pytest.mark.asyncio
async def test_health_endpoint_degraded_state() -> None:
    """Test health endpoint returns 503 when a component is down."""
    with patch("butterscout.main.app_state") as mock_app_state:
        # Setup mock settings
        mock_settings = MagicMock()
        mock_settings.BS_HEALTH_TIMEOUT_MS = 750
        mock_app_state.settings = mock_settings

        # Setup mock clients - redis is down
        mock_app_state.redis_client.ping = AsyncMock(return_value=False)
        mock_app_state.searxng_client.health_check = AsyncMock(return_value=True)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(return_value=True)

        from butterscout.routers.health import health_check
        from fastapi import Response

        response = Response()
        result = await health_check(response)

        # Verify degraded state
        assert result.status == "degraded"
        assert response.status_code == 503
        assert result.components["valkey"].status == "down"
        assert result.components["searxng"].status == "ok"
        assert result.components["crawl4ai"].status == "ok"


@pytest.mark.asyncio
async def test_health_endpoint_timeout_handling() -> None:
    """Test health endpoint handles timeouts correctly."""
    with patch("butterscout.main.app_state") as mock_app_state:
        # Setup mock settings
        mock_settings = MagicMock()
        mock_settings.BS_HEALTH_TIMEOUT_MS = 750
        mock_app_state.settings = mock_settings

        # Setup mock clients - redis times out
        import asyncio

        async def timeout_func() -> bool:
            await asyncio.sleep(2)  # Simulate timeout
            return True

        mock_app_state.redis_client.ping = timeout_func
        mock_app_state.searxng_client.health_check = AsyncMock(return_value=True)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(return_value=True)

        from butterscout.routers.health import health_check
        from fastapi import Response

        response = Response()
        result = await health_check(response)

        # Verify timeout is handled
        assert result.status == "degraded"
        assert response.status_code == 503
        assert result.components["valkey"].status == "down"
        assert result.components["valkey"].error == "Timeout"
