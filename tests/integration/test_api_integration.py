"""API integration tests."""
from __future__ import annotations

from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from butterscout.main import app


@pytest.fixture
def api_client() -> Iterator[TestClient]:
    """Provide TestClient with lifespan (startup/shutdown)."""
    with TestClient(app) as client:
        yield client


@pytest.mark.integration
def test_health_endpoint(api_client: TestClient) -> None:
    """Test health check returns proper structure"""
    response = api_client.get("/health")

    assert response.status_code in [200, 503]
    data = response.json()

    assert "status" in data
    assert "components" in data
    assert "version" in data


@pytest.mark.integration
def test_search_endpoint_validation(api_client: TestClient) -> None:
    """Test search endpoint validates input"""
    # Invalid request should fail
    response = api_client.post("/api/v1/search", json={})
    assert response.status_code == 422

    # Empty query should fail
    response = api_client.post("/api/v1/search", json={"query": ""})
    assert response.status_code == 422


@pytest.mark.integration
@pytest.mark.slow
def test_search_endpoint_success(api_client: TestClient) -> None:
    """Test successful search request (requires running services)"""
    response = api_client.post(
        "/api/v1/search",
        json={
            "query": "test query",
            "max_results": 3,
            "include_content": False,  # Faster without extraction
        },
    )

    # May succeed or fail depending on service availability
    # Just verify response structure
    if response.status_code == 200:
        data = response.json()
        assert "query" in data
        assert "results" in data
        assert "metadata" in data
        assert isinstance(data["results"], list)
        assert isinstance(data["metadata"], dict)


@pytest.mark.integration
def test_health_endpoint_structure(api_client: TestClient) -> None:
    """Test health endpoint returns expected structure"""
    response = api_client.get("/health")

    data = response.json()

    # Check status field
    assert data["status"] in ["healthy", "degraded", "unhealthy"]

    # Check components structure
    assert isinstance(data["components"], dict)

    # Check version
    assert "version" in data
    assert isinstance(data["version"], str)


@pytest.mark.integration
def test_search_validation_max_results(api_client: TestClient) -> None:
    """Test max_results validation"""
    # max_results too high
    response = api_client.post(
        "/api/v1/search",
        json={
            "query": "test",
            "max_results": 100,
        },
    )
    assert response.status_code == 422

    # max_results too low
    response = api_client.post(
        "/api/v1/search",
        json={
            "query": "test",
            "max_results": 0,
        },
    )
    assert response.status_code == 422

    # Valid max_results
    response = api_client.post(
        "/api/v1/search",
        json={
            "query": "test",
            "max_results": 10,
            "include_content": False,
        },
    )
    # May succeed or fail based on service availability, but shouldn't be validation error
    assert response.status_code != 422


@pytest.mark.integration
def test_search_validation_domains(api_client: TestClient) -> None:
    """Test domain validation"""
    # Too many domains
    response = api_client.post(
        "/api/v1/search",
        json={
            "query": "test",
            "options": {
                "domains": ["example.com"] * 25,
            },
        },
    )
    assert response.status_code == 422

    # Invalid domain (too short)
    response = api_client.post(
        "/api/v1/search",
        json={
            "query": "test",
            "options": {
                "domains": ["ab"],
            },
        },
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_metrics_endpoint(api_client: TestClient) -> None:
    """Test metrics endpoint returns Prometheus format"""
    response = api_client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]

    # Check for some expected metrics
    content = response.text
    assert "butterscout_" in content or "# HELP" in content


@pytest.mark.integration
def test_search_response_structure(api_client: TestClient) -> None:
    """Test search response has correct structure when successful"""
    response = api_client.post(
        "/api/v1/search",
        json={
            "query": "python programming",
            "max_results": 5,
            "include_content": False,
        },
    )

    # Only validate structure if request succeeds
    if response.status_code == 200:
        data = response.json()

        # Check top-level fields
        assert "query" in data
        assert "results" in data
        assert "metadata" in data

        # Check metadata structure
        metadata = data["metadata"]
        assert "search_time_ms" in metadata
        assert "cache_hit" in metadata
        assert "sources_queried" in metadata
        assert "api_version" in metadata

        # Check results structure if any
        if len(data["results"]) > 0:
            result = data["results"][0]
            assert "title" in result
            assert "url" in result
            assert "snippet" in result
            assert "metadata" in result
            assert "scores" in result
            assert "source" in result
