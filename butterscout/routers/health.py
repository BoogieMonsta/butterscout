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


# /health is public and its Crawl4AI check renders a page in a real browser, so a flood
# of calls must not become a flood of renders. One refresh runs at a time; after it ends
# (however it ends) the next one waits this long, and callers get the last snapshot.
REFRESH_COOLDOWN_SECONDS = 10.0


class _Snapshot:
    """The last /health result and when the next refresh may start (one per process)."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.result: Optional[tuple[HealthResponse, int]] = None
        self.refreshing = False
        self.next_refresh_at = 0.0


_snapshot = _Snapshot()


@router.get("/health", response_model=HealthResponse)
async def health_check(response: Response) -> HealthResponse:
    """
    Health check endpoint, refreshed at most once per REFRESH_COOLDOWN_SECONDS.

    Returns 200 if all components are OK
    Returns 503 if any component is degraded/down, or while no recent result exists
    """
    if _snapshot.refreshing or time.monotonic() < _snapshot.next_refresh_at:
        if _snapshot.result is None:
            response.status_code = 503
            return HealthResponse(
                status="refreshing",
                components={},
                version="0.1.0",
                uptime_seconds=int(time.time() - startup_time),
                timestamp=time.time(),
            )
        body, status_code = _snapshot.result
        response.status_code = status_code
        return body

    # Reserve the refresh before any await, so concurrent callers never start a second one.
    _snapshot.refreshing = True
    try:
        body, status_code = await _run_checks()
        _snapshot.result = (body, status_code)
    except BaseException:
        # Cancelled (e.g. the caller left): do not keep serving an older snapshot forever.
        _snapshot.result = None
        raise
    finally:
        _snapshot.refreshing = False
        _snapshot.next_refresh_at = time.monotonic() + REFRESH_COOLDOWN_SECONDS
    response.status_code = status_code
    return body


async def _run_checks() -> tuple[HealthResponse, int]:
    """Check every dependency in parallel; return the response and its HTTP status."""
    # Import here to avoid circular import
    from butterscout.main import app_state

    timeout_ms = app_state.settings.BS_HEALTH_TIMEOUT_MS
    timeout_seconds = timeout_ms / 1000.0

    # Check all components in parallel
    valkey_task = asyncio.create_task(_check_valkey(timeout_seconds))
    cache_task = asyncio.create_task(_check_cache(timeout_seconds))
    searxng_task = asyncio.create_task(_check_searxng(timeout_seconds))
    crawl4ai_task = asyncio.create_task(_check_crawl4ai())

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

    overall_status = "healthy" if all_ok else "degraded"
    status_code = 200 if all_ok else 503

    uptime_seconds = int(time.time() - startup_time)

    body = HealthResponse(
        status=overall_status,
        components=components,
        version="0.1.0",
        uptime_seconds=uptime_seconds,
        timestamp=time.time(),
    )
    return body, status_code


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


async def _check_crawl4ai() -> ComponentStatus:
    """Check Crawl4AI health. The client's probe enforces BS_HEALTH_TIMEOUT_MS itself;
    a second timer here would cancel it first and hide its reason."""
    from butterscout.main import app_state

    start = time.perf_counter()
    try:
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
