# Task 11: Logging & Metrics

**Role:** You are a senior backend engineer specializing in observability, structured logging, Prometheus metrics, and production monitoring.

## Context

Implement structured JSON logging and Prometheus metrics to provide visibility into Butterscout's operation. This is critical for debugging, monitoring, and understanding system behavior in production.

Refer to **[TECH SPEC.md]** §4.1, §4.2, §6.4, **[ENGINEERING_GUIDE.md]** §24-25 for complete details.

## Deliverables

### 1. Metrics Service (`butterscout/services/metrics.py`)

```python
from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
from fastapi import Response
import time

# Request metrics
requests_total = Counter(
    "butterscout_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

request_duration_seconds = Histogram(
    "butterscout_request_duration_seconds",
    "Request duration in seconds",
    ["endpoint"],
    buckets=[0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
)

# Component-specific metrics
searxng_duration_seconds = Histogram(
    "butterscout_searxng_duration_seconds",
    "SearXNG request duration",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0],
)

extraction_duration_seconds = Histogram(
    "butterscout_extraction_duration_seconds",
    "Content extraction duration per URL",
    ["extractor"],  # crawl4ai, trafilatura
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0],
)

extraction_failures_total = Counter(
    "butterscout_extraction_failures_total",
    "Failed content extractions",
    ["reason"],  # timeout, error, empty
)

# Cache metrics
cache_hits_total = Counter(
    "butterscout_cache_hits_total",
    "Cache hit count",
)

cache_misses_total = Counter(
    "butterscout_cache_misses_total",
    "Cache miss count",
)

# Rate limiting metrics
rate_limited_total = Counter(
    "butterscout_rate_limited_total",
    "Rate limited request count",
    ["key_type"],  # ip, api_key, global
)

# System metrics
active_requests = Gauge(
    "butterscout_active_requests",
    "Currently active requests",
)

uptime_seconds = Gauge(
    "butterscout_uptime_seconds",
    "Service uptime in seconds",
)

class MetricsService:
    """Prometheus metrics collection service"""

    def __init__(self):
        self.start_time = time.time()

    def record_request(self, method: str, endpoint: str, status: int, duration_seconds: float):
        """Record HTTP request metrics"""
        requests_total.labels(method=method, endpoint=endpoint, status=status).inc()
        request_duration_seconds.labels(endpoint=endpoint).observe(duration_seconds)

    def record_searxng_request(self, duration_seconds: float):
        """Record SearXNG request timing"""
        searxng_duration_seconds.observe(duration_seconds)

    def record_extraction(self, extractor: str, duration_seconds: float, success: bool, reason: str = None):
        """Record content extraction metrics"""
        extraction_duration_seconds.labels(extractor=extractor).observe(duration_seconds)

        if not success and reason:
            extraction_failures_total.labels(reason=reason).inc()

    def record_cache_hit(self):
        """Record cache hit"""
        cache_hits_total.inc()

    def record_cache_miss(self):
        """Record cache miss"""
        cache_misses_total.inc()

    def record_rate_limit(self, key_type: str):
        """Record rate limit event"""
        rate_limited_total.labels(key_type=key_type).inc()

    def increment_active_requests(self):
        """Increment active request count"""
        active_requests.inc()

    def decrement_active_requests(self):
        """Decrement active request count"""
        active_requests.dec()

    def update_uptime(self):
        """Update uptime gauge"""
        uptime_seconds.set(time.time() - self.start_time)

# Global metrics service instance
metrics_service = MetricsService()

def get_metrics() -> Response:
    """Return Prometheus metrics in text format"""
    metrics_service.update_uptime()
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
```

### 2. Metrics Endpoint (`butterscout/routers/metrics.py`)

```python
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import Response
from typing import Optional

from butterscout.services.metrics import get_metrics
from butterscout.main import app_state
import structlog

logger = structlog.get_logger()

router = APIRouter(tags=["metrics"])

async def verify_metrics_access(x_api_key: Optional[str] = Header(None, alias="x-api-key")):
    """Verify access to metrics endpoint (if auth enabled)"""
    if app_state.settings.BS_API_KEY:
        # If API key is configured, require it for metrics
        if not x_api_key or x_api_key != app_state.settings.BS_API_KEY:
            raise HTTPException(status_code=401, detail="Unauthorized")

@router.get("/metrics", dependencies=[Depends(verify_metrics_access)])
async def metrics_endpoint():
    """
    Prometheus metrics endpoint

    Returns metrics in Prometheus text format

    Access control:
    - If BS_API_KEY is set, requires authentication
    - Otherwise, publicly accessible (use reverse proxy to restrict)
    """
    if not app_state.settings.BS_ENABLE_METRICS:
        raise HTTPException(status_code=404, detail="Metrics disabled")

    return get_metrics()
```

### 3. Logging Configuration (`butterscout/utils/logging.py`)

```python
import structlog
import logging
import sys
from typing import Any

def configure_logging(log_level: str = "info"):
    """
    Configure structured logging with JSON output

    Args:
        log_level: Log level (debug, info, warning, error)
    """
    # Map string to logging level
    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }

    level = level_map.get(log_level.lower(), logging.INFO)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Configure standard logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

def get_logger(name: str = None) -> structlog.BoundLogger:
    """Get structured logger instance"""
    if name:
        return structlog.get_logger(name)
    return structlog.get_logger()
```

### 4. Integration with Main App (`butterscout/main.py` updates)

Add to main.py:

```python
from butterscout.utils.logging import configure_logging
from butterscout.services.metrics import metrics_service
from butterscout.routers import metrics as metrics_router

# In lifespan startup:
configure_logging(app_state.settings.BS_LOG_LEVEL)

# Include metrics router:
app.include_router(metrics_router.router)

# Update request middleware to record metrics:
@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Record request metrics"""
    metrics_service.increment_active_requests()
    start_time = time.perf_counter()

    response = await call_next(request)

    duration = time.perf_counter() - start_time
    metrics_service.decrement_active_requests()

    metrics_service.record_request(
        method=request.method,
        endpoint=request.url.path,
        status=response.status_code,
        duration_seconds=duration,
    )

    return response
```

### 5. Metrics Integration in Services

Update services to record metrics:

**In CacheService:**
```python
if cached_json:
    metrics_service.record_cache_hit()
else:
    metrics_service.record_cache_miss()
```

**In SearXNG Client:**
```python
metrics_service.record_searxng_request(duration_seconds)
```

**In Extraction Strategy:**
```python
metrics_service.record_extraction(
    extractor="crawl4ai",
    duration_seconds=duration,
    success=extraction_ok,
    reason="timeout" if timeout else "error",
)
```

**In RateLimiter:**
```python
if not is_allowed:
    metrics_service.record_rate_limit(key_type)
```

## Key Implementation Details

### Structured Logging (ENGINEERING_GUIDE §24)

**Required log fields:**
- `ts`: ISO 8601 timestamp
- `level`: Log level (info, warning, error)
- `msg`: Message/event name
- `request_id`: Request UUID (from middleware)

**Additional context fields:**
- `client_ip_hash`: SHA256 hash (first 8 chars)
- `api_key_hash`: SHA256 hash (first 8 chars, when used)
- `cache_hit`: Boolean
- `rate_limited`: Boolean
- `searxng_time_ms`: SearXNG latency
- `extraction_time_ms`: Extraction latency
- `status_code`: HTTP status
- `error_code`: Error code (if error)
- `url_count`: Number of URLs processed

### Prometheus Metrics (TECH SPEC §4.1)

**Metric naming:**
- Prefix: `butterscout_`
- Use snake_case
- Include units in name (`_seconds`, `_total`)

**Metric types:**
- **Counter**: Monotonically increasing (requests, errors)
- **Histogram**: Observations with buckets (latency)
- **Gauge**: Current value (active requests, uptime)

### Metrics Endpoint Security

- If `BS_API_KEY` is set, require auth for `/metrics`
- Can be disabled via `BS_ENABLE_METRICS=false`
- In production, restrict via reverse proxy

### Performance Considerations

- Metrics recording is O(1) and very fast
- Structured logging has minimal overhead (< 1ms)
- Use histograms with sensible buckets (don't create too many)

## Testing Requirements

### Unit Tests (`tests/unit/test_metrics.py`)

```python
import pytest
from butterscout.services.metrics import metrics_service, requests_total

def test_metrics_recording():
    """Test that metrics are recorded correctly"""
    initial_count = requests_total._value._value

    metrics_service.record_request(
        method="POST",
        endpoint="/api/v1/search",
        status=200,
        duration_seconds=1.5,
    )

    # Counter should increment
    new_count = requests_total._value._value
    assert new_count > initial_count

def test_cache_metrics():
    """Test cache hit/miss metrics"""
    from butterscout.services.metrics import cache_hits_total, cache_misses_total

    initial_hits = cache_hits_total._value._value
    initial_misses = cache_misses_total._value._value

    metrics_service.record_cache_hit()
    metrics_service.record_cache_miss()

    assert cache_hits_total._value._value == initial_hits + 1
    assert cache_misses_total._value._value == initial_misses + 1

def test_metrics_endpoint():
    """Test /metrics endpoint returns Prometheus format"""
    from fastapi.testclient import TestClient
    from butterscout.main import app

    client = TestClient(app)
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "butterscout_requests_total" in response.text
    assert "butterscout_uptime_seconds" in response.text
```

### Integration Tests

- Test metrics accumulation over multiple requests
- Test logging output format (valid JSON)
- Verify request_id propagation through logs

## Performance Requirements

- Metrics recording: < 0.1ms per call
- Logging: < 1ms per log statement
- No memory leaks from unbounded cardinality

## Output Format

When complete, provide:

1. ✅ All files created
2. ✅ Metrics endpoint working (`curl /metrics`)
3. 📊 Example metrics output
4. 📊 Example structured log entries (JSON)
5. 📝 Grafana query examples:
   - Request rate: `rate(butterscout_requests_total[5m])`
   - p95 latency: `histogram_quantile(0.95, rate(butterscout_request_duration_seconds_bucket[5m]))`
   - Cache hit rate: `rate(butterscout_cache_hits_total[5m]) / (rate(butterscout_cache_hits_total[5m]) + rate(butterscout_cache_misses_total[5m]))`

## Dependencies

- **Task 01** (Project Foundation)
- **Task 09** (FastAPI App & Health)

## Time Estimate

4-5 hours

## Reference

- [TECH SPEC.md] §4.1: Observability
- [TECH SPEC.md] §4.2: Logging requirements
- [ENGINEERING_GUIDE.md] §24: Observability Baseline - Structured logs
- [ENGINEERING_GUIDE.md] §25: Observability Baseline - Prometheus metrics
