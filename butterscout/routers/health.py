"""Health check endpoint."""

from __future__ import annotations

import asyncio
import time
from typing import Optional

import structlog
from fastapi import APIRouter, Response
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(tags=["health"])

# Will be updated by main.py after successful startup
startup_time: float = time.time()


class ComponentStatus(BaseModel):
    """Status of individual component."""

    status: str  # "ok", "degraded", "down"
    response_time_ms: Optional[int] = None
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    components: dict[str, ComponentStatus]
    version: str
    uptime_seconds: int
    timestamp: float


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """The API process is up. For container healthchecks.

    /health checks every dependency and returns 503 when one is down. A container
    healthcheck on it marks the API unhealthy (and a proxy may stop routing to it) when
    only Crawl4AI is down, although search still works through the fallback extractor.
    """
    return {"status": "alive"}


@router.get("/health", response_model=HealthResponse)
async def health_check(response: Response) -> HealthResponse:
    """
    Health check endpoint.

    Returns 200 if all components are OK
    Returns 503 if any component is degraded/down
    """
    # Import here to avoid circular import
    from butterscout.main import app_state

    timeout_ms = app_state.settings.BS_HEALTH_TIMEOUT_MS
    timeout_seconds = timeout_ms / 1000.0

    # Check all components in parallel
    valkey_task = asyncio.create_task(_check_valkey(timeout_seconds))
    cache_task = asyncio.create_task(_check_cache(timeout_seconds))
    searxng_task = asyncio.create_task(_check_searxng(timeout_seconds))
    crawl4ai_task = asyncio.create_task(_check_crawl4ai(timeout_seconds))

    results = await asyncio.gather(
        valkey_task,
        cache_task,
        searxng_task,
        crawl4ai_task,
        return_exceptions=True,
    )

    valkey_status, cache_status, searxng_status, crawl4ai_status = results

    components = {
        "valkey": (
            valkey_status
            if isinstance(valkey_status, ComponentStatus)
            else ComponentStatus(status="down", error=str(valkey_status))
        ),
        "cache": (
            cache_status
            if isinstance(cache_status, ComponentStatus)
            else ComponentStatus(status="down", error=str(cache_status))
        ),
        "searxng": (
            searxng_status
            if isinstance(searxng_status, ComponentStatus)
            else ComponentStatus(status="down", error=str(searxng_status))
        ),
        "crawl4ai": (
            crawl4ai_status
            if isinstance(crawl4ai_status, ComponentStatus)
            else ComponentStatus(status="down", error=str(crawl4ai_status))
        ),
    }

    # Determine overall status
    all_ok = all(c.status == "ok" for c in components.values())
    any_down = any(c.status == "down" for c in components.values())

    if all_ok:
        overall_status = "healthy"
        response.status_code = 200
    elif any_down:
        overall_status = "degraded"
        response.status_code = 503
    else:
        overall_status = "degraded"
        response.status_code = 503

    uptime_seconds = int(time.time() - startup_time)

    return HealthResponse(
        status=overall_status,
        components=components,
        version="0.1.0",
        uptime_seconds=uptime_seconds,
        timestamp=time.time(),
    )


async def _check_valkey(timeout: float) -> ComponentStatus:
    """Check Valkey health."""
    from butterscout.main import app_state

    start = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            is_healthy = await app_state.redis_client.ping()

        response_time_ms = int((time.perf_counter() - start) * 1000)

        if is_healthy:
            return ComponentStatus(status="ok", response_time_ms=response_time_ms)
        else:
            return ComponentStatus(status="down", error="Ping failed")

    except asyncio.TimeoutError:
        return ComponentStatus(status="down", error="Timeout")
    except Exception as e:
        return ComponentStatus(status="down", error=str(e))


async def _check_searxng(timeout: float) -> ComponentStatus:
    """Check SearXNG health."""
    from butterscout.main import app_state

    start = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            is_healthy = await app_state.searxng_client.health_check()

        response_time_ms = int((time.perf_counter() - start) * 1000)

        if is_healthy:
            return ComponentStatus(status="ok", response_time_ms=response_time_ms)
        else:
            return ComponentStatus(status="down", error="Health check failed")

    except asyncio.TimeoutError:
        return ComponentStatus(status="down", error="Timeout")
    except Exception as e:
        return ComponentStatus(status="down", error=str(e))


async def _check_crawl4ai(timeout: float) -> ComponentStatus:
    """Check Crawl4AI health."""
    from butterscout.main import app_state

    start = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            is_healthy = await app_state.crawl4ai_client.health_check()

        response_time_ms = int((time.perf_counter() - start) * 1000)

        if is_healthy:
            return ComponentStatus(status="ok", response_time_ms=response_time_ms)
        else:
            return ComponentStatus(status="down", error="Health check failed")

    except asyncio.TimeoutError:
        return ComponentStatus(status="down", error="Timeout")
    except Exception as e:
        return ComponentStatus(status="down", error=str(e))


async def _check_cache(timeout: float) -> ComponentStatus:
    """Check Cache Backend health."""
    from butterscout.main import app_state

    start = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            is_healthy = await app_state.cache_backend.health_check()

        response_time_ms = int((time.perf_counter() - start) * 1000)

        if is_healthy:
            return ComponentStatus(status="ok", response_time_ms=response_time_ms)
        else:
            return ComponentStatus(status="down", error="Health check failed")

    except asyncio.TimeoutError:
        return ComponentStatus(status="down", error="Timeout")
    except Exception as e:
        return ComponentStatus(status="down", error=str(e))
