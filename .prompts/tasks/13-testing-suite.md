# Task 13: Testing Suite

**Role:** You are a senior QA engineer specializing in Python testing, pytest, integration testing, and test-driven development.

## Context

Build a comprehensive testing suite covering unit tests, integration tests, and fixtures. This ensures code quality, catches regressions, and provides confidence for future changes.

Refer to **[TECH SPEC.md]** §8.1, **[ENGINEERING_GUIDE.md]** §10 for complete details.

## Deliverables

### 1. Test Configuration (`pytest.ini`)

```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_functions = test_*
python_classes = Test*

# Markers
markers =
    unit: Unit tests (fast, no external dependencies)
    integration: Integration tests (requires Valkey/Redis, may require SearXNG/Crawl4AI)
    slow: Slow tests (> 1 second)

# Asyncio
asyncio_mode = auto

# Coverage
addopts =
    --verbose
    --strict-markers
    --tb=short
    --cov=butterscout
    --cov-report=term-missing
    --cov-report=html
    --cov-fail-under=80

# Ignore
norecursedirs = .git .tox dist build *.egg
```

### 2. Pytest Fixtures (`tests/conftest.py`)

```python
import pytest
import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

from butterscout.config import Settings
from butterscout.clients.redis_client import RedisClient
from butterscout.clients.searxng_client import SearXNGClient
from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.trafilatura_client import TrafilaturaClient

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()

@pytest.fixture
def settings() -> Settings:
    """Test settings with safe defaults"""
    return Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/15",  # Use test database
        BS_API_KEY=None,
        BS_RATE_LIMIT_PER_HOUR=1000,
        BS_MAX_RESULTS=10,
        BS_MAX_CONCURRENT_EXTRACTIONS=4,
        BS_CACHE_TTL_SECONDS=60,
        BS_LOG_LEVEL="warning",  # Reduce noise in tests
    )

@pytest.fixture
async def redis_client(settings: Settings) -> AsyncGenerator[RedisClient, None]:
    """Valkey/Redis client for integration tests"""
    client = RedisClient(settings)
    await client.connect()

    yield client

    # Cleanup: flush test database
    if client.redis:
        await client.redis.flushdb()
    await client.disconnect()

@pytest.fixture
def mock_redis_client() -> RedisClient:
    """Mock Valkey/Redis client for unit tests"""
    mock_client = MagicMock(spec=RedisClient)
    mock_client.get = AsyncMock(return_value=None)
    mock_client.set = AsyncMock(return_value=True)
    mock_client.delete = AsyncMock(return_value=1)
    mock_client.ping = AsyncMock(return_value=True)
    return mock_client

@pytest.fixture
def mock_searxng_client() -> SearXNGClient:
    """Mock SearXNG client for unit tests"""
    from butterscout.models.internal import NormalizedSearchResult

    mock_client = MagicMock(spec=SearXNGClient)
    mock_client.search = AsyncMock(
        return_value=[
            NormalizedSearchResult(
                title="Test Result",
                url="https://example.com",
                snippet="Test snippet",
                score=0.9,
            )
        ]
    )
    mock_client.health_check = AsyncMock(return_value=True)
    return mock_client

@pytest.fixture
def mock_crawl4ai_client() -> Crawl4AIClient:
    """Mock Crawl4AI client for unit tests"""
    from butterscout.models.internal import ExtractedContent

    mock_client = MagicMock(spec=Crawl4AIClient)
    mock_client.extract = AsyncMock(
        return_value=ExtractedContent(
            url="https://example.com",
            content="Extracted content here",
            word_count=100,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=100,
        )
    )
    mock_client.health_check = AsyncMock(return_value=True)
    return mock_client

@pytest.fixture
async def app_client():
    """FastAPI test client"""
    from fastapi.testclient import TestClient
    from butterscout.main import app

    with TestClient(app) as client:
        yield client
```

### 3. Unit Tests - Models (`tests/unit/test_models.py`)

```python
import pytest
from pydantic import ValidationError
from butterscout.models.requests import SearchRequest, SearchOptions
from butterscout.models.responses import SearchResponse

def test_search_request_validation():
    """Test request validation rules"""
    # Valid request
    req = SearchRequest(query="test query")
    assert req.query == "test query"
    assert req.max_results == 10  # Default

    # Empty query should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="")

    # Whitespace-only query should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="   ")

    # max_results over limit should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="test", max_results=100)

    # max_results under minimum should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="test", max_results=0)

def test_search_options_validation():
    """Test search options validation"""
    # Too many domains should fail
    with pytest.raises(ValidationError):
        SearchOptions(domains=["example.com"] * 30)

    # Domain length validation
    with pytest.raises(ValidationError):
        SearchOptions(domains=["a.b"])  # Too short

    # Negative freshness should fail
    with pytest.raises(ValidationError):
        SearchOptions(freshness_days=-1)
```

### 4. Unit Tests - Services (`tests/unit/test_services.py`)

```python
import pytest
from butterscout.services.deduplicator import URLDeduplicator
from butterscout.services.ranker import Ranker
from butterscout.utils.redis_keys import generate_cache_key
from butterscout.models.requests import SearchRequest

def test_url_normalization():
    """Test URL normalization removes tracking params"""
    url1 = "https://WWW.Example.com/page/?utm_source=google&id=123"
    url2 = "https://example.com/page?id=123"

    assert URLDeduplicator.normalize_url(url1) == URLDeduplicator.normalize_url(url2)

def test_deduplication():
    """Test duplicate URLs are removed"""
    from butterscout.models.internal import NormalizedSearchResult

    results = [
        NormalizedSearchResult(
            title="Page 1",
            url="https://example.com/page",
            snippet="Snippet",
            score=0.9,
        ),
        NormalizedSearchResult(
            title="Page 1 Duplicate",
            url="https://www.example.com/page/",
            snippet="Snippet",
            score=0.8,
        ),
    ]

    deduplicated = URLDeduplicator.deduplicate(results, "test-123")

    assert len(deduplicated) == 1
    assert deduplicated[0].title == "Page 1"

def test_cache_key_stability():
    """Cache keys must be identical for same request"""
    req1 = SearchRequest(query="test query", max_results=10)
    req2 = SearchRequest(query="test query", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 == key2

def test_cache_key_uniqueness():
    """Different requests must produce different keys"""
    req1 = SearchRequest(query="query 1", max_results=10)
    req2 = SearchRequest(query="query 2", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2
```

### 5. Integration Tests (`tests/integration/test_cache_integration.py`)

```python
import pytest
from butterscout.services.cache_service import CacheService
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import SearchResponse, ResponseMetadata

@pytest.mark.integration
@pytest.mark.asyncio
async def test_cache_round_trip(redis_client, settings):
    """Test cache set and get cycle"""
    cache = CacheService(redis_client, settings)

    request = SearchRequest(query="integration test query")

    # Cache miss initially
    result = await cache.get(request, "test-123")
    assert result is None

    # Create and cache response
    response = SearchResponse(
        query="integration test query",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    success = await cache.set(request, response, "test-123")
    assert success is True

    # Cache hit
    cached = await cache.get(request, "test-123")
    assert cached is not None
    assert cached.query == "integration test query"

@pytest.mark.integration
@pytest.mark.asyncio
async def test_rate_limiter_integration(redis_client, settings):
    """Test rate limiter with real Valkey/Redis"""
    from butterscout.services.rate_limiter import RateLimiter

    settings.BS_RATE_LIMIT_PER_HOUR = 5
    limiter = RateLimiter(redis_client, settings)

    # Make 5 requests (at limit)
    for i in range(5):
        is_allowed, _, _, _ = await limiter.check_rate_limit(
            client_ip="192.168.1.1",
            api_key=None,
            request_id=f"test-{i}",
        )
        assert is_allowed is True

    # 6th request should be blocked
    is_allowed, retry_after, remaining, limit = await limiter.check_rate_limit(
        client_ip="192.168.1.1",
        api_key=None,
        request_id="test-6",
    )

    assert is_allowed is False
    assert retry_after is not None
    assert remaining == 0
```

### 6. API Integration Tests (`tests/integration/test_api_integration.py`)

```python
import pytest
from fastapi.testclient import TestClient
from butterscout.main import app

@pytest.mark.integration
def test_health_endpoint():
    """Test health check returns proper structure"""
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code in [200, 503]
    data = response.json()

    assert "status" in data
    assert "components" in data
    assert "version" in data

@pytest.mark.integration
def test_search_endpoint_validation():
    """Test search endpoint validates input"""
    client = TestClient(app)

    # Invalid request should fail
    response = client.post("/api/v1/search", json={})
    assert response.status_code == 422

    # Empty query should fail
    response = client.post("/api/v1/search", json={"query": ""})
    assert response.status_code == 422

@pytest.mark.integration
@pytest.mark.slow
def test_search_endpoint_success():
    """Test successful search request (requires running services)"""
    client = TestClient(app)

    response = client.post(
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
```

### 7. Performance Tests (`tests/performance/test_perf.py`)

```python
import pytest
import time
import asyncio
from butterscout.services.cache_service import CacheService
from butterscout.models.requests import SearchRequest

@pytest.mark.slow
@pytest.mark.asyncio
async def test_cache_performance(redis_client, settings):
    """Test cache operations are fast enough"""
    cache = CacheService(redis_client, settings)

    request = SearchRequest(query="performance test")

    # Measure get operation
    start = time.perf_counter()
    await cache.get(request, "perf-test")
    get_duration = time.perf_counter() - start

    assert get_duration < 0.01  # < 10ms

@pytest.mark.slow
def test_url_normalization_performance():
    """Test URL normalization is fast"""
    from butterscout.services.deduplicator import URLDeduplicator

    urls = [
        f"https://example{i}.com/page?utm_source=google&id={i}"
        for i in range(1000)
    ]

    start = time.perf_counter()
    for url in urls:
        URLDeduplicator.normalize_url(url)
    duration = time.perf_counter() - start

    # Should handle 1000 URLs in < 100ms
    assert duration < 0.1
    assert duration / len(urls) < 0.001  # < 1ms per URL
```

### 8. Test Utilities (`tests/utils/factories.py`)

```python
"""Test data factories"""

from butterscout.models.internal import NormalizedSearchResult, ExtractedContent
from butterscout.models.responses import SearchResult, ResultMetadata, ResultScores

def create_search_result(
    title: str = "Test Result",
    url: str = "https://example.com",
    snippet: str = "Test snippet",
    score: float = 0.9,
) -> NormalizedSearchResult:
    """Factory for creating test search results"""
    return NormalizedSearchResult(
        title=title,
        url=url,
        snippet=snippet,
        score=score,
    )

def create_extracted_content(
    url: str = "https://example.com",
    content: str = "Extracted content",
    word_count: int = 100,
    extracted_by: str = "crawl4ai",
    extraction_ok: bool = True,
) -> ExtractedContent:
    """Factory for creating test extracted content"""
    return ExtractedContent(
        url=url,
        content=content,
        word_count=word_count,
        extracted_by=extracted_by,
        extraction_ok=extraction_ok,
        extraction_time_ms=100,
    )
```

## Key Implementation Details

### Test Organization (ENGINEERING_GUIDE §10)

**Directory structure:**
```
tests/
├── conftest.py           # Shared fixtures
├── unit/                 # Fast, no external deps
│   ├── test_models.py
│   ├── test_services.py
│   └── test_utils.py
├── integration/          # Requires Valkey/Redis, maybe SearXNG
│   ├── test_cache_integration.py
│   ├── test_api_integration.py
│   └── test_rate_limit_integration.py
├── performance/          # Performance benchmarks
│   └── test_perf.py
└── utils/
    └── factories.py      # Test data factories
```

### Test Markers

- `@pytest.mark.unit` - Fast unit tests (default)
- `@pytest.mark.integration` - Requires external services
- `@pytest.mark.slow` - Tests taking > 1 second

### Coverage Target (ENGINEERING_GUIDE §10)

- Minimum 80% overall coverage
- 90%+ for core business logic
- Exclude: main.py startup code, type stubs

### Mocking Strategy

- Unit tests: Mock all external dependencies
- Integration tests: Use real Valkey/Redis, mock HTTP clients (or use local services)
- Use `AsyncMock` for async functions
- Use `respx` for HTTP client mocking

## Testing Requirements

### Run Tests Locally

```bash
# All tests
make test

# Unit tests only (fast)
pytest -m unit

# Integration tests (requires Valkey/Redis)
pytest -m integration

# With coverage
pytest --cov --cov-report=html
open htmlcov/index.html
```

### CI Requirements

- All tests must pass
- Coverage ≥ 80%
- No test warnings
- Tests complete in < 5 minutes

## Performance Requirements

- Unit test suite: < 10 seconds
- Integration test suite: < 30 seconds
- Performance tests: < 60 seconds
- Total test time: < 2 minutes

## Output Format

When complete, provide:

1. ✅ All test files created
2. ✅ Tests passing: `make test`
3. 📊 Coverage report: `pytest --cov`
4. 📊 Test timing: `pytest --durations=10`
5. 📝 Example showing:
   - Successful test run
   - Coverage above 80%
   - Test organization

## Dependencies

- **Task 01-12** (All previous tasks)

## Time Estimate

6-8 hours

## Reference

- [TECH SPEC.md] §8.1: MVP Testing
- [ENGINEERING_GUIDE.md] §10: Testing Strategy
