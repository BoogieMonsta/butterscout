# Task 14: End-to-End Integration & Validation

**Role:** You are a senior QA engineer specializing in end-to-end testing, system integration validation, and production readiness verification.

## Context

This is the final integration task that validates the entire system works together correctly. Run end-to-end tests, performance validation, OpenAPI contract verification, and create a final release checklist.

Refer to **[TECH SPEC.md]** §8.1, **[ENGINEERING_GUIDE.md]** §10 for complete details.

## Deliverables

### 1. E2E Test Script (`tests/e2e/test_full_pipeline.py`)

```python
"""
End-to-end tests for complete search pipeline

These tests require all services running (SearXNG, Crawl4AI, Redis)
Run with: docker compose up -d && pytest tests/e2e/
"""

import pytest
import time
import httpx
from typing import List, Dict

BASE_URL = "http://localhost:8000"

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_search_pipeline_with_content():
    """Test complete search with content extraction"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BASE_URL}/api/v1/search",
            json={
                "query": "what is retrieval augmented generation",
                "max_results": 5,
                "include_content": True,
            },
        )

        assert response.status_code == 200, f"Failed: {response.text}"

        data = response.json()

        # Verify response structure
        assert "query" in data
        assert "results" in data
        assert "metadata" in data

        # Verify results
        assert len(data["results"]) > 0, "No results returned"
        assert len(data["results"]) <= 5

        for result in data["results"]:
            assert "title" in result
            assert "url" in result
            assert "snippet" in result
            assert "content" in result  # Should have content
            assert "metadata" in result
            assert "scores" in result

            # Check metadata fields
            assert "domain" in result["metadata"]
            assert "extraction_ok" in result["metadata"]

            # Check scores
            assert "search_score" in result["scores"]
            assert "rank" in result["scores"]

        # Verify metadata
        metadata = data["metadata"]
        assert metadata["cache_hit"] is False  # First request
        assert metadata["search_time_ms"] > 0
        assert metadata["searxng_time_ms"] > 0
        assert metadata["extraction_time_ms"] > 0
        assert "searxng" in metadata["sources_queried"]

        print(f"✓ Search completed in {metadata['search_time_ms']}ms")
        print(f"  - SearXNG: {metadata['searxng_time_ms']}ms")
        print(f"  - Extraction: {metadata['extraction_time_ms']}ms")
        print(f"  - Results: {len(data['results'])}")

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_cache_behavior():
    """Test that caching works correctly"""
    query = f"test query {int(time.time())}"  # Unique query

    async with httpx.AsyncClient(timeout=30.0) as client:
        # First request (cache miss)
        response1 = await client.post(
            f"{BASE_URL}/api/v1/search",
            json={"query": query, "max_results": 3, "include_content": False},
        )

        assert response1.status_code == 200
        data1 = response1.json()
        assert data1["metadata"]["cache_hit"] is False
        time1 = data1["metadata"]["search_time_ms"]

        # Second request (cache hit)
        response2 = await client.post(
            f"{BASE_URL}/api/v1/search",
            json={"query": query, "max_results": 3, "include_content": False},
        )

        assert response2.status_code == 200
        data2 = response2.json()
        assert data2["metadata"]["cache_hit"] is True
        time2 = data2["metadata"]["search_time_ms"]

        # Cache hit should be faster
        assert time2 < time1, f"Cache hit ({time2}ms) not faster than miss ({time1}ms)"

        print(f"✓ Cache working: miss={time1}ms, hit={time2}ms")

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_rate_limiting():
    """Test rate limiting works"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Make requests until rate limited (max 60 per hour default)
        # In tests, we can't wait an hour, so we'll just verify headers exist

        response = await client.post(
            f"{BASE_URL}/api/v1/search",
            json={"query": "rate limit test", "include_content": False},
        )

        assert response.status_code == 200

        # Check rate limit headers
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

        print(f"✓ Rate limit headers present")
        print(f"  - Limit: {response.headers['X-RateLimit-Limit']}")
        print(f"  - Remaining: {response.headers['X-RateLimit-Remaining']}")

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_health_check():
    """Test health endpoint reports component status"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{BASE_URL}/health")

        assert response.status_code in [200, 503]

        data = response.json()

        assert "status" in data
        assert "components" in data
        assert "version" in data

        # Check all required components
        components = data["components"]
        assert "redis" in components
        assert "searxng" in components
        assert "crawl4ai" in components

        # Each component should have status
        for name, component in components.items():
            assert "status" in component
            assert component["status"] in ["ok", "degraded", "down"]

        print(f"✓ Health check: {data['status']}")
        for name, comp in components.items():
            print(f"  - {name}: {comp['status']}")

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_search_without_content():
    """Test search without content extraction (faster)"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{BASE_URL}/api/v1/search",
            json={
                "query": "python programming",
                "max_results": 10,
                "include_content": False,
            },
        )

        assert response.status_code == 200

        data = response.json()

        # Should have results but no content
        assert len(data["results"]) > 0

        for result in data["results"]:
            assert result["content"] is None
            assert result["snippet"]  # Should still have snippet

        # Should be faster without extraction
        assert data["metadata"]["search_time_ms"] < 3000

        # extraction_time_ms should be null or zero
        extraction_time = data["metadata"].get("extraction_time_ms")
        assert extraction_time is None or extraction_time == 0

        print(f"✓ Search without content: {data['metadata']['search_time_ms']}ms")
```

### 2. Performance Validation Script (`tests/e2e/test_performance.py`)

```python
"""
Performance validation tests

Target: p95 latency ≤ 3s for default settings (TECH SPEC §2.2)
"""

import pytest
import httpx
import time
import statistics
from typing import List

BASE_URL = "http://localhost:8000"

# Representative queries from different categories
TEST_QUERIES = [
    "what is machine learning",  # Factual
    "python asyncio tutorial",   # Technical
    "latest AI news 2024",       # News-like
    "docker compose best practices",  # Technical docs
    "retrieval augmented generation",  # Academic/technical
]

@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.asyncio
async def test_performance_p95_latency():
    """
    Test that p95 latency is ≤ 3s for default settings

    TECH SPEC §2.2 requirement
    """
    latencies: List[float] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in TEST_QUERIES:
            # Add timestamp to avoid cache hits
            unique_query = f"{query} {int(time.time() * 1000)}"

            start = time.perf_counter()

            response = await client.post(
                f"{BASE_URL}/api/v1/search",
                json={
                    "query": unique_query,
                    "max_results": 10,  # Default
                    "include_content": True,  # Default
                },
            )

            duration = time.perf_counter() - start

            assert response.status_code == 200, f"Request failed: {response.text}"

            latencies.append(duration)

            print(f"Query: '{query}' - {duration:.2f}s")

    # Calculate statistics
    p50 = statistics.median(latencies)
    p95 = statistics.quantiles(latencies, n=100)[94] if len(latencies) > 1 else latencies[0]
    p99 = max(latencies)

    print("\nPerformance Summary:")
    print(f"  p50: {p50:.2f}s")
    print(f"  p95: {p95:.2f}s")
    print(f"  p99: {p99:.2f}s")

    # TECH SPEC requirement: p95 ≤ 3s
    assert p95 <= 3.0, f"p95 latency ({p95:.2f}s) exceeds 3s target"

    print(f"\n✓ Performance target met: p95 = {p95:.2f}s ≤ 3.0s")

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_no_5xx_errors():
    """Ensure no 5xx errors on representative queries"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        for query in TEST_QUERIES:
            response = await client.post(
                f"{BASE_URL}/api/v1/search",
                json={"query": query, "max_results": 5},
            )

            assert response.status_code < 500, f"5xx error on query '{query}': {response.status_code}"

    print(f"✓ No 5xx errors on {len(TEST_QUERIES)} queries")
```

### 3. OpenAPI Contract Validation (`tests/e2e/test_openapi_contract.py`)

```python
"""
Validate that API implementation matches OpenAPI specification
"""

import pytest
import httpx
import json

BASE_URL = "http://localhost:8000"

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_openapi_spec_available():
    """Test that OpenAPI spec is accessible"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{BASE_URL}/openapi.json")

        assert response.status_code == 200
        spec = response.json()

        # Verify basic structure
        assert "openapi" in spec
        assert "info" in spec
        assert "paths" in spec

        # Verify required endpoints exist
        assert "/health" in spec["paths"]
        assert "/api/v1/search" in spec["paths"]
        assert "/metrics" in spec["paths"]

        print(f"✓ OpenAPI spec available")
        print(f"  - Version: {spec['info']['version']}")
        print(f"  - Endpoints: {len(spec['paths'])}")

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_search_endpoint_matches_spec():
    """Test that search endpoint response matches OpenAPI spec"""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{BASE_URL}/api/v1/search",
            json={
                "query": "test",
                "max_results": 3,
            },
        )

        assert response.status_code == 200

        data = response.json()

        # Verify response schema matches TECH SPEC §6.1
        required_fields = ["query", "results", "metadata"]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

        # Verify result schema
        if data["results"]:
            result = data["results"][0]
            result_fields = [
                "title", "url", "snippet", "content",
                "metadata", "scores", "source"
            ]
            for field in result_fields:
                assert field in result, f"Missing result field: {field}"

        # Verify metadata schema
        metadata = data["metadata"]
        metadata_fields = [
            "search_time_ms", "cache_hit", "sources_queried",
            "api_version", "rate_limited"
        ]
        for field in metadata_fields:
            assert field in metadata, f"Missing metadata field: {field}"

        print(f"✓ Response schema matches specification")
```

### 4. Release Checklist (`RELEASE_CHECKLIST.md`)

```markdown
# Butterscout v0.1 Release Checklist

## Code Quality

- [ ] All tasks (01-14) completed
- [ ] All tests passing (`make test`)
- [ ] Test coverage ≥ 80% (`pytest --cov`)
- [ ] No linting errors (`make lint`)
- [ ] No type errors (`make typecheck`)
- [ ] Code formatted (`make format`)

## Functionality

- [ ] POST /api/v1/search endpoint working
- [ ] GET /health endpoint working
- [ ] GET /metrics endpoint working
- [ ] Request validation working (400 on invalid input)
- [ ] Authentication working (if BS_API_KEY set)
- [ ] Rate limiting working (429 response + headers)
- [ ] Caching working (cache hit/miss behavior)
- [ ] Content extraction working (Crawl4AI + fallback)
- [ ] Ranking and deduplication working
- [ ] Domain filtering working

## Performance

- [ ] p95 latency ≤ 3s (run `pytest tests/e2e/test_performance.py`)
- [ ] No 5xx errors on representative queries
- [ ] Cache hit response < 100ms
- [ ] Health check < 750ms

## Infrastructure

- [ ] Docker Compose working (`docker compose up`)
- [ ] All services healthy (SearXNG, Crawl4AI, Redis)
- [ ] API accessible at http://localhost:8000
- [ ] OpenAPI docs accessible at http://localhost:8000/docs
- [ ] Prometheus metrics accessible at http://localhost:8000/metrics

## Documentation

- [ ] README.md complete with:
  - Quick start instructions
  - API examples
  - Configuration reference
  - Deployment instructions
- [ ] .env.example complete and accurate
- [ ] OpenAPI specification accurate
- [ ] ENGINEERING_GUIDE.md followed

## Observability

- [ ] Structured JSON logs working
- [ ] All required log fields present (request_id, timings, etc.)
- [ ] Prometheus metrics exposed
- [ ] Health check includes component statuses

## Configuration

- [ ] All env vars documented in .env.example
- [ ] Config validation working (fails fast on invalid config)
- [ ] Default values sensible for production

## Security

- [ ] No secrets in code or git history
- [ ] API key authentication working (if enabled)
- [ ] Rate limiting prevents abuse
- [ ] No sensitive data in logs
- [ ] Error responses don't leak stack traces

## Testing

- [ ] Unit tests passing (fast, < 10s)
- [ ] Integration tests passing (with Redis)
- [ ] E2E tests passing (with all services)
- [ ] Performance tests passing

## Final Validation

- [ ] Run full E2E test suite: `pytest tests/e2e/ -v`
- [ ] Manual smoke test: Query API with real search
- [ ] Check logs for errors
- [ ] Verify metrics collecting
- [ ] Review OpenAPI docs

## Sign-off

- [ ] All checklist items completed
- [ ] No known critical bugs
- [ ] Ready for v0.1 release

**Version:** 0.1.0
**Date:** ____________
**Signed:** ____________
```

### 5. Smoke Test Script (`scripts/smoke_test.sh`)

```bash
#!/bin/bash
set -e

BASE_URL="${BASE_URL:-http://localhost:8000}"

echo "🧪 Running Butterscout smoke tests..."
echo "Base URL: $BASE_URL"
echo ""

# Test 1: Health Check
echo "1. Testing health endpoint..."
HEALTH=$(curl -s -w "%{http_code}" $BASE_URL/health)
HTTP_CODE="${HEALTH: -3}"

if [ "$HTTP_CODE" == "200" ] || [ "$HTTP_CODE" == "503" ]; then
    echo "   ✓ Health endpoint responding ($HTTP_CODE)"
else
    echo "   ✗ Health endpoint failed ($HTTP_CODE)"
    exit 1
fi

# Test 2: Search without content
echo "2. Testing search without content..."
SEARCH_RESPONSE=$(curl -s -w "%{http_code}" -X POST $BASE_URL/api/v1/search \
    -H "Content-Type: application/json" \
    -d '{"query": "test", "max_results": 3, "include_content": false}')

HTTP_CODE="${SEARCH_RESPONSE: -3}"
RESPONSE_BODY="${SEARCH_RESPONSE:0:${#SEARCH_RESPONSE}-3}"

if [ "$HTTP_CODE" == "200" ]; then
    echo "   ✓ Search working ($HTTP_CODE)"

    # Check response has results
    RESULT_COUNT=$(echo "$RESPONSE_BODY" | jq '.results | length')
    echo "   ✓ Returned $RESULT_COUNT results"
else
    echo "   ✗ Search failed ($HTTP_CODE)"
    echo "$RESPONSE_BODY" | jq '.'
    exit 1
fi

# Test 3: Metrics endpoint
echo "3. Testing metrics endpoint..."
METRICS=$(curl -s -w "%{http_code}" $BASE_URL/metrics)
HTTP_CODE="${METRICS: -3}"

if [ "$HTTP_CODE" == "200" ]; then
    echo "   ✓ Metrics endpoint responding ($HTTP_CODE)"
else
    echo "   ⚠ Metrics endpoint: $HTTP_CODE (may be disabled)"
fi

# Test 4: OpenAPI docs
echo "4. Testing OpenAPI docs..."
OPENAPI=$(curl -s -w "%{http_code}" $BASE_URL/openapi.json)
HTTP_CODE="${OPENAPI: -3}"

if [ "$HTTP_CODE" == "200" ]; then
    echo "   ✓ OpenAPI docs available ($HTTP_CODE)"
else
    echo "   ✗ OpenAPI docs failed ($HTTP_CODE)"
    exit 1
fi

echo ""
echo "✅ All smoke tests passed!"
```

## Key Implementation Details

### E2E Test Requirements

- All services must be running (Docker Compose up)
- Tests should be realistic user scenarios
- Verify complete request/response flow
- Check error handling paths

### Performance Target (TECH SPEC §2.2)

**p95 latency ≤ 3 seconds** for:
- Default settings (max_results=10, include_content=true)
- Cold cache
- Typical queries

### OpenAPI Contract

- Endpoint paths match spec
- Request/response schemas match
- Error responses match format
- Headers present (rate limit, request ID)

## Testing Requirements

### Run E2E Tests

```bash
# Start all services
docker compose up -d

# Wait for services to be healthy
sleep 30

# Run E2E tests
pytest tests/e2e/ -v

# Run performance tests
pytest tests/e2e/test_performance.py -v

# Run smoke test
bash scripts/smoke_test.sh
```

### CI Integration

E2E tests in CI:
```yaml
- name: Run E2E Tests
  run: |
    docker compose up -d
    sleep 30
    pytest tests/e2e/ -v
    docker compose down
```

## Performance Requirements

- E2E test suite: < 5 minutes
- Performance tests: < 3 minutes (5 queries)
- Smoke tests: < 30 seconds

## Output Format

When complete, provide:

1. ✅ All E2E tests passing
2. ✅ Performance validation passing (p95 ≤ 3s)
3. ✅ OpenAPI contract validation passing
4. ✅ Smoke test script passing
5. ✅ Release checklist completed
6. 📊 Performance summary:
   - p50, p95, p99 latencies
   - No 5xx errors
7. 📊 Test coverage report
8. 📝 Final validation report

## Dependencies

- **Task 01-13** (All previous tasks - complete system)

## Time Estimate

4-5 hours

## Reference

- [TECH SPEC.md] §2.2: Non-Functional Goals - Performance
- [TECH SPEC.md] §8.1: MVP Testing
- [ENGINEERING_GUIDE.md] §10: Testing Strategy
