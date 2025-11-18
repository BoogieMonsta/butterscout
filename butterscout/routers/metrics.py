"""Metrics endpoint router."""
from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response

from butterscout.services.metrics import get_metrics

if TYPE_CHECKING:
    from butterscout.config import Settings

logger = structlog.get_logger()

router = APIRouter(tags=["metrics"])


class MetricsAuth:
    """Dependency for metrics authentication."""

    def __init__(self, settings: Settings):
        """Initialize with settings.

        Args:
            settings: Application settings
        """
        self.settings = settings

    async def __call__(self, x_api_key: str | None = Header(None, alias="x-api-key")) -> None:
        """Verify access to metrics endpoint (if auth enabled).

        Args:
            x_api_key: Optional API key from header

        Raises:
            HTTPException: If authentication fails
        """
        if self.settings.BS_API_KEY:
            # Use constant-time comparison to prevent timing attacks
            is_valid = (
                x_api_key is not None
                and secrets.compare_digest(x_api_key, self.settings.BS_API_KEY)
            )
            if not is_valid:
                raise HTTPException(status_code=401, detail="Unauthorized")


def create_metrics_router(settings: Settings) -> APIRouter:
    """Create metrics router with settings dependency.

    Args:
        settings: Application settings

    Returns:
        Configured APIRouter
    """
    metrics_auth = MetricsAuth(settings)

    @router.get("/metrics", dependencies=[Depends(metrics_auth)])
    async def metrics_endpoint() -> Response:
        """Prometheus metrics endpoint.

        Returns metrics in Prometheus text format.

        Access control:
        - If BS_API_KEY is set, requires authentication
        - Otherwise, publicly accessible (use reverse proxy to restrict)

        Returns:
            Response with Prometheus metrics

        Raises:
            HTTPException: If metrics are disabled
        """
        if not settings.BS_ENABLE_METRICS:
            raise HTTPException(status_code=404, detail="Metrics disabled")

        return get_metrics()

    return router
