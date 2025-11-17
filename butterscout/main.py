"""FastAPI application entry point."""
from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.extraction_strategy import ExtractionStrategy
from butterscout.clients.redis_client import ValkeyClient
from butterscout.clients.searxng_client import SearXNGClient
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import Settings, validate_settings
from butterscout.routers import health, search

# Configure structured logging
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=False,
)

logger = structlog.get_logger()


# Global state for dependency injection
class AppState:
    """Application state container."""

    settings: Settings
    redis_client: ValkeyClient
    searxng_client: SearXNGClient
    crawl4ai_client: Crawl4AIClient
    trafilatura_client: Optional[TrafilaturaClient]
    extraction_strategy: ExtractionStrategy


app_state = AppState()

# Load and validate settings early (needed for CORS configuration)
app_state.settings = Settings()  # type: ignore[call-arg]
validate_settings(app_state.settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("butterscout_startup_begin")

    # Initialize clients
    app_state.redis_client = ValkeyClient(app_state.settings)
    await app_state.redis_client.connect()

    app_state.searxng_client = SearXNGClient(app_state.settings)
    await app_state.searxng_client.connect()

    app_state.crawl4ai_client = Crawl4AIClient(app_state.settings)
    await app_state.crawl4ai_client.connect()

    # Initialize fallback if enabled
    if app_state.settings.BS_FALLBACK_ENABLED:
        app_state.trafilatura_client = TrafilaturaClient(app_state.settings)
        await app_state.trafilatura_client.connect()
    else:
        app_state.trafilatura_client = None

    # Initialize extraction strategy
    app_state.extraction_strategy = ExtractionStrategy(
        crawl4ai=app_state.crawl4ai_client,
        trafilatura=app_state.trafilatura_client,
        settings=app_state.settings,
    )

    # Set startup time for health endpoint after successful initialization
    from butterscout.routers import health

    health.startup_time = time.time()

    logger.info("butterscout_startup_complete")

    yield

    # Shutdown - disconnect all clients with error isolation
    logger.info("butterscout_shutdown_begin")

    # Collect all clients to disconnect
    clients_to_disconnect = [
        ("valkey", app_state.redis_client),
        ("searxng", app_state.searxng_client),
        ("crawl4ai", app_state.crawl4ai_client),
    ]
    if app_state.trafilatura_client:
        clients_to_disconnect.append(("trafilatura", app_state.trafilatura_client))

    # Disconnect each client, continuing even if one fails
    for client_name, client in clients_to_disconnect:
        try:
            await client.disconnect()
            logger.info(f"{client_name}_disconnected")
        except Exception as e:
            logger.error(
                f"{client_name}_disconnect_failed",
                error=str(e),
                exc_info=True,
            )

    logger.info("butterscout_shutdown_complete")


# Create FastAPI app
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


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Add request ID to all requests."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    request.state.start_time = time.perf_counter()

    # Add to logging context
    structlog.contextvars.bind_contextvars(request_id=request_id)

    try:
        response = await call_next(request)

        # Calculate request duration
        duration_ms = int((time.perf_counter() - request.state.start_time) * 1000)

        # Add headers
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration_ms}ms"

        # Log request
        logger.info(
            "http_request",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )

        return response
    except Exception:
        # Store duration for the exception handler to include in headers
        request.state.response_time_ms = int(
            (time.perf_counter() - request.state.start_time) * 1000
        )
        raise
    finally:
        structlog.contextvars.clear_contextvars()


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions."""
    request_id = getattr(request.state, "request_id", "unknown")
    response_time_ms = getattr(request.state, "response_time_ms", None)

    logger.error(
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
        headers={
            "X-Request-ID": request_id,
            **(
                {"X-Response-Time": f"{response_time_ms}ms"}
                if response_time_ms is not None
                else {}
            ),
        },
    )


# Include routers
app.include_router(health.router)
app.include_router(search.router, prefix="/api/v1")
