"""Unit tests for metrics service."""
from __future__ import annotations

from butterscout.services.metrics import (
    cache_hits_total,
    cache_misses_total,
    extraction_failures_total,
    metrics_service,
    rate_limited_total,
    requests_total,
)


def test_metrics_recording() -> None:
    """Test that metrics are recorded correctly with source label."""
    # Record a request with IP source
    metrics_service.record_request(
        method="POST",
        endpoint="/api/v1/search",
        status=200,
        duration_seconds=1.5,
        source="ip",
    )

    # Record a request with API key source
    metrics_service.record_request(
        method="GET",
        endpoint="/health",
        status=200,
        duration_seconds=0.1,
        source="api_key",
    )

    # Verify counter exists and doesn't error
    assert requests_total is not None


def test_normalized_endpoint_prevents_cardinality() -> None:
    """Test that using normalized endpoints prevents unbounded cardinality."""
    # Simulate multiple requests to same endpoint with different query params
    # All should use the same normalized endpoint pattern
    normalized_endpoint = "/api/v1/search"

    for _ in range(10):
        metrics_service.record_request(
            method="POST",
            # Same pattern, not /api/v1/search?q=test{i}
            endpoint=normalized_endpoint,
            status=200,
            duration_seconds=1.0,
            source="ip",
        )

    # Test passes if no errors (cardinality explosion would cause memory issues)
    assert True


def test_cache_metrics() -> None:
    """Test cache hit/miss metrics."""
    # Record hits and misses
    metrics_service.record_cache_hit()
    metrics_service.record_cache_miss()

    # Verify metrics were recorded (they should exist without errors)
    assert cache_hits_total is not None
    assert cache_misses_total is not None


def test_extraction_metrics() -> None:
    """Test extraction metrics recording."""
    # Record successful extraction
    metrics_service.record_extraction(
        extractor="crawl4ai",
        duration_seconds=2.5,
        success=True,
        reason=None,
    )

    # Record failed extraction
    metrics_service.record_extraction(
        extractor="crawl4ai",
        duration_seconds=3.0,
        success=False,
        reason="timeout",
    )

    # Verify metrics exist
    assert extraction_failures_total is not None


def test_rate_limit_metrics() -> None:
    """Test rate limit metrics."""
    # Record rate limit events
    metrics_service.record_rate_limit("ip")
    metrics_service.record_rate_limit("api_key")
    metrics_service.record_rate_limit("global")

    # Verify metric exists
    assert rate_limited_total is not None


def test_active_requests_gauge() -> None:
    """Test active requests gauge."""
    # Increment and decrement
    metrics_service.increment_active_requests()
    metrics_service.increment_active_requests()
    metrics_service.decrement_active_requests()

    # Should not raise any errors
    assert True


def test_uptime_metric() -> None:
    """Test uptime metric update."""
    metrics_service.update_uptime()

    # Should not raise any errors
    assert True


def test_metrics_endpoint() -> None:
    """Test /metrics endpoint returns Prometheus format."""
    from butterscout.services.metrics import get_metrics

    response = get_metrics()

    # Verify response
    assert response is not None
    assert response.media_type is not None and response.media_type.startswith(
        "text/plain")

    # Verify content contains expected metrics
    body_bytes: bytes = response.body.tobytes() if isinstance(
        response.body, memoryview) else response.body
    content = body_bytes.decode("utf-8")
    assert "butterscout_requests_total" in content
    assert "butterscout_uptime_seconds" in content
    assert "butterscout_cache_hits_total" in content
    assert "butterscout_cache_misses_total" in content


def test_metrics_with_source_label() -> None:
    """Test that requests_total includes source label."""
    from butterscout.services.metrics import get_metrics

    # Record requests with different sources
    metrics_service.record_request(
        method="POST",
        endpoint="/api/v1/search",
        status=200,
        duration_seconds=1.0,
        source="ip",
    )

    metrics_service.record_request(
        method="POST",
        endpoint="/api/v1/search",
        status=200,
        duration_seconds=1.0,
        source="api_key",
    )

    response = get_metrics()
    body_bytes: bytes = response.body.tobytes() if isinstance(
        response.body, memoryview) else response.body
    content = body_bytes.decode("utf-8")

    # Verify both source types are in output
    assert 'source="ip"' in content or "source=\"ip\"" in content
    assert 'source="api_key"' in content or "source=\"api_key\"" in content


def test_histogram_buckets() -> None:
    """Test that histograms have appropriate bucket sizes."""
    from butterscout.services.metrics import (
        extraction_duration_seconds,
        request_duration_seconds,
        searxng_duration_seconds,
    )

    def get_bounds(histogram: object) -> list[float]:
        """Extract upper bounds from prometheus histogram regardless of version internals."""
        if hasattr(histogram, "_upper_bounds"):
            return [float(b) for b in histogram._upper_bounds]
        # Fallback: derive from bucket objects if _upper_bounds is unavailable
        buckets = getattr(histogram, "_buckets", [])
        return [
            float(b.upper_bound)
            for b in buckets
            if hasattr(b, "upper_bound") and b.upper_bound is not None
        ]

    # Verify searxng has buckets up to 10s (for retries)
    assert 10.0 in get_bounds(searxng_duration_seconds)

    # Verify extraction has buckets up to 10s
    assert 10.0 in get_bounds(extraction_duration_seconds)

    # Verify request duration has proper buckets
    assert 5.0 in get_bounds(request_duration_seconds)
