"""Unit tests for FastAPI application."""
from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_app_creation() -> None:
    """Test that the app can be imported and created."""
    from butterscout.main import app

    assert app is not None
    assert app.title == "Butterscout API"
    assert app.version == "0.1.0"


def test_routers_included() -> None:
    """Test that routers are included in the app."""
    from butterscout.main import app

    # Check that health router is included
    routes = [getattr(route, "path", "") for route in app.routes]
    assert "/health" in routes


def test_middleware_registered() -> None:
    """Test that middleware is registered."""
    from butterscout.main import app

    # Check CORS middleware is registered
    middleware_types = [type(m).__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in str(app.user_middleware)


def test_exception_handlers_registered() -> None:
    """Test that exception handlers are registered."""
    from butterscout.main import app

    # Check that exception handlers are registered
    assert Exception in app.exception_handlers
