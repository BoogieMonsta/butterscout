"""FastAPI application entry point with metrics and logging."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Awaitable, Callable, Optional

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.routing import Route

from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.extraction_strategy import ExtractionStrategy
from butterscout.clients.redis_client import ValkeyClient
from butterscout.clients.searxng_client import SearXNGClient
from butterscout.clients.stubs import (
    NoopValkeyClient,
    StubCrawl4AIClient,
    StubSearXNGClient,
    StubTrafilaturaClient,
)
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import load_settings
from butterscout.mcp_server import McpHttpEndpoint, run_mcp
from butterscout.middleware.security_headers import add_security_headers
from butterscout.models.exceptions import (
    DomainNotAllowedError,
    InvalidUrlError,
    MaxResultsExceededError,
    RateLimitExceededError,
    UnauthorizedError,
    UpstreamProviderError,
)
from butterscout.routers import extract, health, search
from butterscout.routers import metrics as metrics_router
from butterscout.services.metrics import metrics_service
from butterscout.state import app_state
from butterscout.utils.logging import configure_logging
from butterscout.utils.privacy import hash_api_key, hash_client_ip
from butterscout.utils.request_helpers import (
    get_client_ip,
    get_normalized_endpoint,
    resolve_api_key,
)

__all__ = ["app", "app_state"]

# Load and validate settings early (needed for CORS configuration)
app_state.settings = load_settings()
configure_logging(app_state.settings.BS_LOG_LEVEL)
logger = structlog.get_logger()


def _should_skip_startup() -> bool:
    """Detect when startup should be skipped (tests)."""
    return bool(
        os.environ.get("PYTEST_CURRENT_TEST")
        or os.environ.get("BS_SKIP_STARTUP", "").lower() in {"1", "true", "yes"}
    )


async def uptime_updater() -> None:
    """Background task to update uptime gauge every 60 seconds."""
    task_logger = structlog.get_logger()
    task_logger.info("uptime_updater_started")

    try:
        while True:
            metrics_service.update_uptime()
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        task_logger.info("uptime_updater_stopped")
        raise


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: startup and shutdown."""
    logger.info("butterscout_startup_begin")

    if _should_skip_startup():
        logger.info("butterscout_startup_skip", reason="test_mode")
        # Initialize lightweight test clients to satisfy handlers without external dependencies
        from butterscout.services.cache_backend import MemoryBackend
        from butterscout.services.cache_service import CacheService

        app_state.redis_client = NoopValkeyClient(app_state.settings)
        app_state.searxng_client = StubSearXNGClient(app_state.settings)
        app_state.crawl4ai_client = StubCrawl4AIClient(app_state.settings)
        app_state.trafilatura_client = (
            StubTrafilaturaClient(app_state.settings)
            if app_state.settings.BS_FALLBACK_ENABLED
            else None
        )
        app_state.extraction_strategy = ExtractionStrategy(
            crawl4ai=app_state.crawl4ai_client,
            trafilatura=app_state.trafilatura_client,
            settings=app_state.settings,
        )
        # Initialize cache backend for test mode
        app_state.cache_backend = MemoryBackend()
        app_state.cache_service = CacheService(app_state.cache_backend, app_state.settings)

        health.startup_time = time.time()
        async with run_mcp(app_state.settings):
            yield
        logger.info("butterscout_shutdown_skip", reason="test_mode")
        return

    metrics_service.start_time = time.time()
    uptime_task: Optional[asyncio.Task[None]] = None

    # Initialize clients
    app_state.redis_client = ValkeyClient(app_state.settings)
    app_state.searxng_client = SearXNGClient(app_state.settings)
    app_state.crawl4ai_client = Crawl4AIClient(app_state.settings)

    # Initialize cache backend based on configuration
    # Note: Redis is still connected even with memory cache, as RateLimiter depends on it
    from butterscout.services.cache_backend import MemoryBackend, RedisBackend
    from butterscout.services.cache_service import CacheService

    if app_state.settings.BS_CACHE_TYPE == "memory":
        logger.info("cache_backend_selected", backend="memory")
        app_state.cache_backend = MemoryBackend()
    else:
        logger.info("cache_backend_selected", backend="redis")
        app_state.cache_backend = RedisBackend(app_state.redis_client)

    # Connect clients
    await app_state.redis_client.connect()
    logger.info("redis_client_connected")

    await app_state.searxng_client.connect()
    logger.info("searxng_client_connected")

    await app_state.crawl4ai_client.connect()
    logger.info("crawl4ai_client_connected")

    # Initialize cache service
    app_state.cache_service = CacheService(app_state.cache_backend, app_state.settings)

    if app_state.settings.BS_FALLBACK_ENABLED:
        app_state.trafilatura_client = TrafilaturaClient(app_state.settings)
        await app_state.trafilatura_client.connect()
        logger.info("trafilatura_client_connected")
    else:
        app_state.trafilatura_client = None
        logger.info("trafilatura_fallback_disabled")

    app_state.extraction_strategy = ExtractionStrategy(
        crawl4ai=app_state.crawl4ai_client,
        trafilatura=app_state.trafilatura_client,
        settings=app_state.settings,
    )

    # Set startup time for health endpoint after successful initialization
    health.startup_time = time.time()

    if app_state.settings.BS_ENABLE_METRICS:
        uptime_task = asyncio.create_task(uptime_updater())
        logger.info("uptime_updater_task_created")

    logger.info("butterscout_startup_complete")

    try:
        async with run_mcp(app_state.settings):
            yield
    finally:
        logger.info("butterscout_shutdown_begin")

        if uptime_task:
            uptime_task.cancel()
            try:
                await uptime_task
            except asyncio.CancelledError:
                logger.info("uptime_updater_cancelled")

        clients_to_disconnect = [
            ("valkey", getattr(app_state, "redis_client", None)),
            ("searxng", getattr(app_state, "searxng_client", None)),
            ("crawl4ai", getattr(app_state, "crawl4ai_client", None)),
        ]
        if getattr(app_state, "trafilatura_client", None):
            clients_to_disconnect.append(("trafilatura", app_state.trafilatura_client))

        for client_name, client in clients_to_disconnect:
            if not client:
                continue
            try:
                await client.disconnect()
                logger.info(f"{client_name}_disconnected")
            except Exception as e:  # noqa: BLE001
                logger.error(
                    f"{client_name}_disconnect_failed",
                    error=str(e),
                    exc_info=True,
                )

        logger.info("butterscout_shutdown_complete")


app = FastAPI(
    title="Butterscout API",
    description="Open-source web search and extraction API for LLM agents",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=app_state.settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# Security headers middleware
@app.middleware("http")
async def security_headers_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Add security headers to all responses."""
    return await add_security_headers(request, call_next)


@app.middleware("http")
async def request_id_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Add request ID, metrics, and comprehensive logging to all requests."""
    metrics_enabled = getattr(app_state.settings, "BS_ENABLE_METRICS", True)

    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    request.state.start_time = time.perf_counter()

    client_ip = get_client_ip(request)
    api_key = resolve_api_key(request.headers)

    client_ip_hash = hash_client_ip(client_ip)
    api_key_hash = hash_api_key(api_key) if api_key else "none"
    source = "api_key" if api_key else "ip"

    request.state.cache_hit = False
    request.state.rate_limited = False
    request.state.searxng_time_ms = 0
    request.state.extraction_time_ms = 0
    request.state.url_count = 0
    request.state.error_code = None

    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        client_ip_hash=client_ip_hash,
        api_key_hash=api_key_hash,
    )

    if metrics_enabled:
        metrics_service.increment_active_requests()

    response: Optional[Response] = None
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception as e:  # noqa: BLE001
        log = structlog.get_logger()
        log.error("middleware_exception", error=str(e), exc_info=True)
        status_code = 500
        raise
    finally:
        duration_seconds = time.perf_counter() - request.state.start_time
        duration_ms = int(duration_seconds * 1000)

        normalized_endpoint = get_normalized_endpoint(request)

        if metrics_enabled:
            metrics_service.decrement_active_requests()
            metrics_service.record_request(
                method=request.method,
                endpoint=normalized_endpoint,
                status=status_code,
                duration_seconds=duration_seconds,
                source=source,
            )

        log = structlog.get_logger()
        log.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            endpoint=normalized_endpoint,
            status_code=status_code,
            duration_ms=duration_ms,
            cache_hit=getattr(request.state, "cache_hit", False),
            rate_limited=getattr(request.state, "rate_limited", False),
            searxng_time_ms=getattr(request.state, "searxng_time_ms", 0),
            extraction_time_ms=getattr(request.state, "extraction_time_ms", 0),
            url_count=getattr(request.state, "url_count", 0),
            error_code=getattr(request.state, "error_code", None),
        )

        if response:
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{duration_ms}ms"

        structlog.contextvars.clear_contextvars()

    return response if response else JSONResponse(status_code=status_code, content={})


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions."""
    request_id = getattr(request.state, "request_id", "unknown")
    start_time = getattr(request.state, "start_time", None)

    headers = {"X-Request-ID": request_id}
    if start_time is not None:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        headers["X-Response-Time"] = f"{duration_ms}ms"

    log = structlog.get_logger()
    log.error(
        "unhandled_exception",
        request_id=request_id,
        path=request.url.path,
        error=str(exc),
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
                "details": {},
            },
            "metadata": {
                "request_id": request_id,
                "api_version": "v1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        },
        headers=headers,
    )


@app.exception_handler(RateLimitExceededError)
async def rate_limit_handler(request: Request, exc: RateLimitExceededError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    headers = exc.headers.copy()
    if exc.retry_after:
        headers["Retry-After"] = str(int(exc.retry_after))

    return JSONResponse(
        status_code=429,
        content={
            "error": {
                "code": "RATE_LIMITED",
                "message": exc.message,
                "details": {
                    "retry_after_ms": exc.retry_after * 1000 if exc.retry_after else None,
                },
            },
            "metadata": {
                "request_id": request_id,
                "api_version": "v1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        },
        headers=headers,
    )


@app.exception_handler(MaxResultsExceededError)
async def max_results_handler(request: Request, exc: MaxResultsExceededError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "MAX_RESULTS_EXCEEDED",
                "message": exc.message,
                "details": {
                    "requested": exc.requested,
                    "allowed": exc.allowed,
                },
            },
            "metadata": {
                "request_id": request_id,
                "api_version": "v1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        },
        headers=exc.headers,
    )


@app.exception_handler(UnauthorizedError)
async def unauthorized_handler(request: Request, exc: UnauthorizedError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    headers = exc.headers.copy()
    headers["WWW-Authenticate"] = 'ApiKey realm="Butterscout API"'

    return JSONResponse(
        status_code=401,
        content={
            "error": {
                "code": "UNAUTHORIZED",
                "message": exc.message,
                "details": {},
            },
            "metadata": {
                "request_id": request_id,
                "api_version": "v1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        },
        headers=headers,
    )


@app.exception_handler(UpstreamProviderError)
async def upstream_error_handler(request: Request, exc: UpstreamProviderError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "code": "UPSTREAM_ERROR",
                "message": exc.message,
                "details": {
                    "component": exc.component,
                    "timeout": exc.is_timeout,
                },
            },
            "metadata": {
                "request_id": request_id,
                "api_version": "v1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        },
        headers=exc.headers,
    )


@app.exception_handler(InvalidUrlError)
async def invalid_url_handler(request: Request, exc: InvalidUrlError) -> JSONResponse:
    # Same body shape the extract endpoint returned via HTTPException.
    return JSONResponse(status_code=400, content={"detail": exc.message}, headers=exc.headers)


@app.exception_handler(DomainNotAllowedError)
async def domain_not_allowed_handler(
    request: Request, exc: DomainNotAllowedError
) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": exc.message}, headers=exc.headers)


# Include routers
app.include_router(health.router)
app.include_router(search.router, prefix="/api/v1")
app.include_router(extract.router, prefix="/api/v1")
app.include_router(metrics_router.create_metrics_router(app_state.settings))
# MCP Streamable HTTP. A plain Route (not a Mount) so POST /mcp gets no 307 to /mcp/.
# The endpoint answers 404 itself while BS_MCP_ENABLED is false.
app.router.routes.append(Route("/mcp", endpoint=McpHttpEndpoint()))
