"""Unit tests for FastAPI application."""

from __future__ import annotations


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
    from fastapi.middleware.cors import CORSMiddleware

    from butterscout.main import app

    # Check CORS middleware is registered
    assert any(m.cls is CORSMiddleware for m in app.user_middleware)


def test_exception_handlers_registered() -> None:
    """Test that exception handlers are registered."""
    from butterscout.main import app

    # Check that exception handlers are registered
    assert Exception in app.exception_handlers
