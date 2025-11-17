"""Prometheus metrics collection service.

This module defines and manages all Prometheus metrics for Butterscout.

Metric Naming Convention:
- All metrics prefixed with "butterscout_"
- Use snake_case
- Counters end with "_total"
- Durations end with "_seconds"

Cardinality Guidelines:
- endpoint labels use route patterns (e.g., "/api/v1/search"), NOT raw URLs
- Avoid high-cardinality labels like full URLs, user IDs, or API keys
- Use fixed sets of values for labels (e.g., source="ip" or source="api_key")

Available Metrics:

Request Metrics:
- butterscout_requests_total: Total HTTP requests (labels: method, endpoint, status, source)
- butterscout_request_duration_seconds: Request latency histogram (labels: endpoint)
- butterscout_active_requests: Currently active requests (gauge)

Component Metrics:
- butterscout_searxng_duration_seconds: SearXNG request latency histogram
- butterscout_extraction_duration_seconds: Content extraction latency (labels: extractor)
- butterscout_extraction_failures_total: Failed extractions (labels: reason)

Cache Metrics:
- butterscout_cache_hits_total: Cache hit count
- butterscout_cache_misses_total: Cache miss count

Rate Limiting Metrics:
- butterscout_rate_limited_total: Rate limited requests (labels: key_type)

System Metrics:
- butterscout_uptime_seconds: Service uptime in seconds (gauge)

Histogram Buckets:
- Request duration: [0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0] seconds
- SearXNG duration: [0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0] seconds (covers 2s timeout + retry)
- Extraction duration: [0.5, 1.0, 2.0, 3.0, 5.0, 10.0] seconds
"""
from __future__ import annotations

import time

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

# Request metrics
requests_total = Counter(
    "butterscout_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status", "source"],  # source = ip | api_key
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
    buckets=[0.1, 0.5, 1.0, 2.0, 3.0, 5.0, 10.0],  # Extended to handle retries (2s * 2 attempts)
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
    """Prometheus metrics collection service."""

    def __init__(self) -> None:
        """Initialize metrics service."""
        self.start_time = time.time()

    def record_request(
        self, method: str, endpoint: str, status: int, duration_seconds: float, source: str = "ip"
    ) -> None:
        """Record HTTP request metrics.

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: Request endpoint path (normalized route pattern)
            status: HTTP status code
            duration_seconds: Request duration in seconds
            source: Request source type ("ip" or "api_key")
        """
        requests_total.labels(
            method=method, endpoint=endpoint, status=status, source=source
        ).inc()
        request_duration_seconds.labels(endpoint=endpoint).observe(duration_seconds)

    def record_searxng_request(self, duration_seconds: float) -> None:
        """Record SearXNG request timing.

        Args:
            duration_seconds: Request duration in seconds
        """
        searxng_duration_seconds.observe(duration_seconds)

    def record_extraction(
        self,
        extractor: str,
        duration_seconds: float,
        success: bool,
        reason: str | None = None,
    ) -> None:
        """Record content extraction metrics.

        Args:
            extractor: Name of extractor (crawl4ai, trafilatura)
            duration_seconds: Extraction duration in seconds
            success: Whether extraction succeeded
            reason: Failure reason if not successful (timeout, error, empty)
        """
        extraction_duration_seconds.labels(extractor=extractor).observe(duration_seconds)

        if not success and reason:
            extraction_failures_total.labels(reason=reason).inc()

    def record_cache_hit(self) -> None:
        """Record cache hit."""
        cache_hits_total.inc()

    def record_cache_miss(self) -> None:
        """Record cache miss."""
        cache_misses_total.inc()

    def record_rate_limit(self, key_type: str) -> None:
        """Record rate limit event.

        Args:
            key_type: Type of rate limit key (ip, api_key, global)
        """
        rate_limited_total.labels(key_type=key_type).inc()

    def increment_active_requests(self) -> None:
        """Increment active request count."""
        active_requests.inc()

    def decrement_active_requests(self) -> None:
        """Decrement active request count."""
        active_requests.dec()

    def update_uptime(self) -> None:
        """Update uptime gauge."""
        uptime_seconds.set(time.time() - self.start_time)


# Global metrics service instance
metrics_service = MetricsService()


def get_metrics() -> Response:
    """Return Prometheus metrics in text format.

    Returns:
        Response with Prometheus metrics in text format
    """
    metrics_service.update_uptime()
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST,
    )
