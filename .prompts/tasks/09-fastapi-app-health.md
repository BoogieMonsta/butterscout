# Task 09: FastAPI Application & Health Endpoint

**Role:** You are a senior FastAPI backend engineer specializing in API architecture, middleware patterns, and service health monitoring.

## Context

Create the FastAPI application skeleton with proper lifecycle management, middleware, error handling, and a robust health check endpoint that verifies all dependencies.

Defaults to honor: health per-dependency timeout 750ms, include uptime_seconds and timestamp in health response, return 503 on degraded/unhealthy.

Refer to **[TECH SPEC.md]** §4.1, §6, §7.4 for complete details.

## Deliverables

### 1. FastAPI Application (`butterscout/main.py`)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import uuid
import time

from butterscout.config import Settings
from butterscout.clients.redis_client import RedisClient
from butterscout.clients.searxng_client import SearXNGClient
from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.clients.extraction_strategy import ExtractionStrategy
from butterscout.routers import health, search

# Configure structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
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
    """Application state container"""
    settings: Settings
    redis_client: RedisClient
    searxng_client: SearXNGClient
    crawl4ai_client: Crawl4AIClient
    trafilatura_client: Optional[TrafilaturaClient]
    extraction_strategy: ExtractionStrategy

app_state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown"""
    logger.info("butterscout_startup_begin")

    # Load settings
    app_state.settings = Settings()

    # Validate settings
    from butterscout.config import validate_settings
    validate_settings(app_state.settings)

    # Initialize clients
    app_state.redis_client = RedisClient(app_state.settings)
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

    logger.info("butterscout_startup_complete")

    yield

    # Shutdown
    logger.info("butterscout_shutdown_begin")

    await app_state.redis_client.disconnect()
    await app_state.searxng_client.disconnect()
    await app_state.crawl4ai_client.disconnect()
    if app_state.trafilatura_client:
        await app_state.trafilatura_client.disconnect()

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
    allow_origins=["*"],  # TODO: Configure from settings
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Add request ID to all requests"""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    # Add to logging context
    structlog.contextvars.bind_contextvars(request_id=request_id)

    start_time = time.perf_counter()

    response = await call_next(request)

    # Calculate request duration
    duration_ms = int((time.perf_counter() - start_time) * 1000)

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

    structlog.contextvars.clear_contextvars()

    return response

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions"""
    request_id = getattr(request.state, "request_id", "unknown")

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
                "timestamp": time.time(),
            },
        },
    )

# Include routers
app.include_router(health.router)
app.include_router(search.router, prefix="/api/v1")
```

### 2. Health Check Router (`butterscout/routers/health.py`)

```python
from fastapi import APIRouter, Response
from pydantic import BaseModel
import asyncio
import time

from butterscout.main import app_state
import structlog

logger = structlog.get_logger()

router = APIRouter(tags=["health"])

class ComponentStatus(BaseModel):
    """Status of individual component"""
    status: str  # "ok", "degraded", "down"
    response_time_ms: Optional[int] = None
    error: Optional[str] = None

class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    components: dict[str, ComponentStatus]
    version: str
    uptime_seconds: Optional[int] = None

startup_time = time.time()

@router.get("/health", response_model=HealthResponse)
async def health_check(response: Response):
    """
    Health check endpoint

    Returns 200 if all components are OK
    Returns 503 if any component is degraded/down
    """
    timeout_ms = app_state.settings.BS_HEALTH_TIMEOUT_MS
    timeout_seconds = timeout_ms / 1000.0

    # Check all components in parallel
    redis_task = asyncio.create_task(_check_redis(timeout_seconds))
    searxng_task = asyncio.create_task(_check_searxng(timeout_seconds))
    crawl4ai_task = asyncio.create_task(_check_crawl4ai(timeout_seconds))

    results = await asyncio.gather(
        redis_task,
        searxng_task,
        crawl4ai_task,
        return_exceptions=True,
    )

    redis_status, searxng_status, crawl4ai_status = results

    components = {
        "redis": redis_status if not isinstance(redis_status, Exception) else ComponentStatus(status="down", error=str(redis_status)),
        "searxng": searxng_status if not isinstance(searxng_status, Exception) else ComponentStatus(status="down", error=str(searxng_status)),
        "crawl4ai": crawl4ai_status if not isinstance(crawl4ai_status, Exception) else ComponentStatus(status="down", error=str(crawl4ai_status)),
    }

    # Determine overall status
    all_ok = all(c.status == "ok" for c in components.values())
    any_down = any(c.status == "down" for c in components.values())

    if all_ok:
        overall_status = "ok"
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
    )

async def _check_redis(timeout: float) -> ComponentStatus:
    """Check Redis health"""
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
    """Check SearXNG health"""
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
    """Check Crawl4AI health"""
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
```

### 3. Configuration Validation (`butterscout/config.py` - add this function)

```python
def validate_settings(settings: Settings) -> None:
    """Validate settings on startup, fail fast with clear errors"""
    errors = []

    if not settings.BS_SEARXNG_URL.startswith(("http://", "https://")):
        errors.append("BS_SEARXNG_URL must start with http:// or https://")

    if not settings.BS_CRAWL4AI_URL.startswith(("http://", "https://")):
        errors.append("BS_CRAWL4AI_URL must start with http:// or https://")

    if not settings.BS_REDIS_URL.startswith("redis://"):
        errors.append("BS_REDIS_URL must start with redis://")

    if settings.BS_MAX_RESULTS > 25:
        errors.append("BS_MAX_RESULTS cannot exceed 25")

    if settings.BS_MAX_RESULTS < 1:
        errors.append("BS_MAX_RESULTS must be at least 1")

    if settings.BS_MAX_CONCURRENT_EXTRACTIONS < 1:
        errors.append("BS_MAX_CONCURRENT_EXTRACTIONS must be at least 1")

    if errors:
        raise ValueError(f"Configuration errors:\n  - " + "\n  - ".join(errors))
```

## Key Implementation Details

### Lifecycle Management (TECH SPEC §7.4)

- Use FastAPI `lifespan` context manager
- Initialize all clients on startup
- Validate config before initializing
- Gracefully disconnect on shutdown

### Dependency Injection Pattern

- Use global `AppState` class for DI
- All routers access via `app_state`
- Alternative: Use FastAPI `Depends()` (can refactor later)

### Request ID Middleware

- Generate UUID for each request
- Add to logging context
- Include in response header
- Include in error responses

### Health Check Contract (TECH SPEC §7.4)

- Check Redis, SearXNG, Crawl4AI in parallel
- Enforce timeout per component (750ms default)
- Return 200 if all OK, 503 if any degraded/down
- Include component-level status and timing
- Include uptime_seconds

### Error Handling

- Global exception handler catches all unhandled errors
- Return standard error JSON format
- Log with request_id and full context
- Never leak stack traces to clients

## Testing Requirements

### Unit Tests (`tests/unit/test_app.py`)

```python
import pytest
from fastapi.testclient import TestClient
from butterscout.main import app

def test_health_endpoint_structure():
    """Test health endpoint returns correct structure"""
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code in [200, 503]
    data = response.json()

    assert "status" in data
    assert "components" in data
    assert "version" in data
    assert "redis" in data["components"]
    assert "searxng" in data["components"]
    assert "crawl4ai" in data["components"]

def test_request_id_header():
    """Test that request ID header is added"""
    client = TestClient(app)
    response = client.get("/health")

    assert "X-Request-ID" in response.headers
    assert "X-Response-Time" in response.headers
```

### Integration Tests

- Test full startup/shutdown cycle
- Test health check with real dependencies
- Test error handling paths

## Performance Requirements

- Health check: < 750ms total
- Startup time: < 5s
- Shutdown time: < 2s

## Output Format

When complete, provide:

1. ✅ All files created
2. ✅ App starts successfully
3. ✅ Health endpoint returns 200 or 503
4. 📊 Example health check responses (all OK, one down)
5. 📝 Startup logs showing initialization

## Dependencies

- **Task 01** (Project Foundation)
- **Task 02** (Redis Client)
- **Task 03** (SearXNG Client)
- **Task 04** (Extraction Clients)

## Time Estimate

4-5 hours

## Reference

- [TECH SPEC.md] §4.1: API Layer
- [TECH SPEC.md] §6: API Design
- [TECH SPEC.md] §7.4: Health Check Contract
