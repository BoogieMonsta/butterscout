"""Unit tests for main.py utility functions."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


def test_should_skip_startup_with_pytest_env() -> None:
    """Test that startup is skipped when PYTEST_CURRENT_TEST is set."""
    from butterscout.main import _should_skip_startup

    with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "test_foo.py::test_bar"}):
        assert _should_skip_startup() is True


def test_should_skip_startup_with_bs_skip_startup_true() -> None:
    """Test that startup is skipped when BS_SKIP_STARTUP is true."""
    from butterscout.main import _should_skip_startup

    for value in ["1", "true", "yes", "True", "TRUE", "YES"]:
        with patch.dict(os.environ, {"BS_SKIP_STARTUP": value}, clear=True):
            assert _should_skip_startup() is True, f"Failed for value: {value}"


def test_should_skip_startup_with_bs_skip_startup_false() -> None:
    """Test that startup is not skipped when BS_SKIP_STARTUP is false."""
    from butterscout.main import _should_skip_startup

    for value in ["0", "false", "no", "False", "FALSE", "NO", ""]:
        with patch.dict(os.environ, {"BS_SKIP_STARTUP": value}, clear=True):
            assert _should_skip_startup() is False, f"Failed for value: {value}"


def test_should_skip_startup_without_env_vars() -> None:
    """Test that startup is not skipped without env vars."""
    from butterscout.main import _should_skip_startup

    with patch.dict(os.environ, {}, clear=True):
        assert _should_skip_startup() is False


def test_get_client_ip_from_x_forwarded_for() -> None:
    """Test extracting client IP from X-Forwarded-For header."""
    from butterscout.main import get_client_ip

    request = MagicMock()
    request.headers.get.side_effect = lambda key: {
        "x-forwarded-for": "203.0.113.1, 198.51.100.1"
    }.get(key)

    ip = get_client_ip(request)
    assert ip == "203.0.113.1"


def test_get_client_ip_from_x_real_ip() -> None:
    """Test extracting client IP from X-Real-IP header."""
    from butterscout.main import get_client_ip

    request = MagicMock()
    request.headers.get.side_effect = lambda key: {
        "x-real-ip": "203.0.113.5"
    }.get(key)

    ip = get_client_ip(request)
    assert ip == "203.0.113.5"


def test_get_client_ip_from_client_host() -> None:
    """Test extracting client IP from request.client."""
    from butterscout.main import get_client_ip

    request = MagicMock()
    request.headers.get.return_value = None
    request.client.host = "203.0.113.10"

    ip = get_client_ip(request)
    assert ip == "203.0.113.10"


def test_get_client_ip_unknown() -> None:
    """Test that unknown is returned when no IP source is available."""
    from butterscout.main import get_client_ip

    request = MagicMock()
    request.headers.get.return_value = None
    request.client = None

    ip = get_client_ip(request)
    assert ip == "unknown"


def test_get_client_ip_x_forwarded_for_strips_whitespace() -> None:
    """Test that X-Forwarded-For IP is stripped of whitespace."""
    from butterscout.main import get_client_ip

    request = MagicMock()
    request.headers.get.side_effect = lambda key: {
        "x-forwarded-for": "  203.0.113.1  , 198.51.100.1"
    }.get(key)

    ip = get_client_ip(request)
    assert ip == "203.0.113.1"


def test_get_normalized_endpoint_with_route() -> None:
    """Test getting normalized endpoint from route path."""
    from butterscout.main import get_normalized_endpoint

    request = MagicMock()
    route = MagicMock()
    route.path = "/api/v1/search"
    request.scope = {"route": route}

    endpoint = get_normalized_endpoint(request)
    assert endpoint == "/api/v1/search"


def test_get_normalized_endpoint_without_route() -> None:
    """Test getting normalized endpoint when route is not available."""
    from butterscout.main import get_normalized_endpoint

    request = MagicMock()
    request.scope = {}
    request.url.path = "/api/v1/search"

    endpoint = get_normalized_endpoint(request)
    assert endpoint == "/api/v1/search"


def test_get_normalized_endpoint_with_non_string_path() -> None:
    """Test getting normalized endpoint when route.path is not a string."""
    from butterscout.main import get_normalized_endpoint

    request = MagicMock()
    route = MagicMock()
    route.path = None  # Not a string
    request.scope = {"route": route}
    request.url.path = "/fallback/path"

    endpoint = get_normalized_endpoint(request)
    assert endpoint == "/fallback/path"


@pytest.mark.asyncio
async def test_uptime_updater() -> None:
    """Test uptime updater background task."""
    import asyncio
    from butterscout.main import uptime_updater
    from butterscout.services.metrics import metrics_service
    from unittest.mock import patch

    with patch.object(metrics_service, 'update_uptime') as mock_update:
        # Create task
        task = asyncio.create_task(uptime_updater())

        # Let it run for a bit
        await asyncio.sleep(0.1)

        # Cancel it
        task.cancel()

        try:
            await task
        except asyncio.CancelledError:
            pass

        # Should have called update_uptime at least once (called before first sleep)
        assert mock_update.call_count >= 1
