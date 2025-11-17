# Task 10: Search Endpoint Implementation

**Role:** You are a senior FastAPI backend engineer specializing in RESTful API design, request/response handling, and API error patterns.

## Context

Implement the main `/api/v1/search` endpoint that orchestrates the entire search pipeline: cache check → SearXNG → extraction → ranking → response assembly → caching. This is the core feature of Butterscout.

Defaults to honor: request budget ~6s; SearXNG 2s + 1 retry (100–300ms); Crawl4AI 2.5s no retry with Trafilatura fallback 2s; per-request extraction concurrency 4 (no global semaphore); rate limits 60/hr IP, 600/hr API key (optional global 10k/hr) with X-RateLimit-* and Retry-After headers; cache key includes `max_results` and TTL 1h; respond per openapi.yaml/TECH SPEC metadata and error schema; include `cache_hit`/`rate_limited` flags.

Refer to **[TECH SPEC.md]** §4.2, §6.1, §6.3, §6.4 for complete details.

## Deliverables

### 1. Search Router (`butterscout/routers/search.py`)

```python
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from typing import Optional
import time
import hashlib

from butterscout.main import app_state
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import SearchResponse, ResponseMetadata, ErrorResponse
from butterscout.services.cache_service import CacheService
from butterscout.services.rate_limiter import RateLimiter
from butterscout.services.extraction_orchestrator import ExtractionOrchestrator
from butterscout.services.result_assembler import ResultAssembler
from butterscout.services.deduplicator import URLDeduplicator
from butterscout.services.ranker import Ranker
from butterscout.utils.domain_filter import is_domain_allowed
from butterscout.utils.rate_limit_headers import generate_rate_limit_headers
from butterscout.utils.content_filter import filter_low_quality_results
import structlog

logger = structlog.get_logger()

router = APIRouter(tags=["search"])

@router.post("/search", response_model=SearchResponse)
async def search(
    request_body: SearchRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
):
    """
    Main search endpoint

    Execute web search with content extraction

    Args:
        request_body: Search request parameters
        request: FastAPI request object
        x_api_key: Optional API key for authentication

    Returns:
        SearchResponse with results and metadata
    """
    request_id = request.state.request_id
    start_time = time.perf_counter()

    logger.info(
        "search_request_begin",
        request_id=request_id,
        query=request_body.query,
        max_results=request_body.max_results,
        include_content=request_body.include_content,
    )

    # 1. Authentication (if required)
    if app_state.settings.BS_API_KEY:
        if not x_api_key or x_api_key != app_state.settings.BS_API_KEY:
            logger.warning(
                "authentication_failed",
                request_id=request_id,
                has_key=bool(x_api_key),
            )
            raise HTTPException(
                status_code=401,
                detail={
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Missing or invalid API key",
                        "details": {},
                    },
                    "metadata": {
                        "request_id": request_id,
                        "api_version": "v1",
                        "timestamp": time.time(),
                    },
                },
                headers={"WWW-Authenticate": 'ApiKey realm="Butterscout API"'},
            )

    # 2. Rate Limiting
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter = RateLimiter(app_state.redis_client, app_state.settings)

    is_allowed, retry_after, remaining, limit = await rate_limiter.check_rate_limit(
        client_ip=client_ip,
        api_key=x_api_key,
        request_id=request_id,
    )

    if not is_allowed:
        logger.warning(
            "rate_limit_exceeded",
            request_id=request_id,
            client_ip=hashlib.sha256(client_ip.encode()).hexdigest()[:8],
        )

        headers = generate_rate_limit_headers(limit, 0, retry_after)

        raise HTTPException(
            status_code=429,
            detail={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Rate limit exceeded",
                    "details": {
                        "retry_after_ms": retry_after * 1000 if retry_after else None,
                    },
                },
                "metadata": {
                    "request_id": request_id,
                    "api_version": "v1",
                    "timestamp": time.time(),
                },
            },
            headers=headers,
        )

    # 3. Check Cache
    cache_service = CacheService(app_state.redis_client, app_state.settings)
    cached_response = await cache_service.get(request_body, request_id)

    if cached_response:
        # Cache hit - return immediately
        total_time_ms = int((time.perf_counter() - start_time) * 1000)

        logger.info(
            "search_request_complete_cache_hit",
            request_id=request_id,
            total_time_ms=total_time_ms,
        )

        # Update metadata
        cached_response.metadata.cache_hit = True
        cached_response.metadata.search_time_ms = total_time_ms

        # Add rate limit headers
        headers = generate_rate_limit_headers(limit, remaining)
        return JSONResponse(
            content=cached_response.model_dump(),
            headers=headers,
        )

    # 4. Execute Search via SearXNG
    searxng_start = time.perf_counter()

    try:
        search_results = await app_state.searxng_client.search(
            request_body,
            request_id,
        )
    except Exception as e:
        logger.error(
            "searxng_failed",
            request_id=request_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=502,
            detail={
                "error": {
                    "code": "UPSTREAM_ERROR",
                    "message": "Search provider error",
                    "details": {
                        "component": "searxng",
                        "timeout": isinstance(e, TimeoutError),
                    },
                },
                "metadata": {
                    "request_id": request_id,
                    "api_version": "v1",
                    "timestamp": time.time(),
                },
            },
        )

    searxng_time_ms = int((time.perf_counter() - searxng_start) * 1000)

    # 5. Apply Domain Filtering
    filtered_results = [
        r for r in search_results
        if is_domain_allowed(
            str(r.url),
            app_state.settings.allowed_domains_list,
            app_state.settings.blocked_domains_list,
        )
    ]

    # 6. Deduplicate
    deduplicated_results = URLDeduplicator.deduplicate(
        filtered_results,
        request_id,
    )

    # 7. Extract Content (if requested)
    extraction_time_ms = 0

    if request_body.include_content and deduplicated_results:
        extraction_start = time.perf_counter()

        orchestrator = ExtractionOrchestrator(
            app_state.extraction_strategy,
            app_state.settings,
        )

        extracted_contents = await orchestrator.extract_all(
            deduplicated_results,
            request_id,
        )

        extraction_time_ms = int((time.perf_counter() - extraction_start) * 1000)

        # 8. Assemble Results
        results = ResultAssembler.assemble(
            deduplicated_results,
            extracted_contents,
            include_content=True,
            request_id=request_id,
        )

        # 9. Filter Low Quality
        results = filter_low_quality_results(results, request_id)
    else:
        # No extraction - just assemble with snippets
        results = ResultAssembler.assemble(
            deduplicated_results,
            [],
            include_content=False,
            request_id=request_id,
        )

    # 10. Rank Results
    ranker = Ranker(app_state.settings)
    ranked_results = ranker.rank(results, request_id)

    # 11. Build Response
    total_time_ms = int((time.perf_counter() - start_time) * 1000)

    response = SearchResponse(
        query=request_body.query,
        results=ranked_results,
        metadata=ResponseMetadata(
            search_time_ms=total_time_ms,
            searxng_time_ms=searxng_time_ms,
            extraction_time_ms=extraction_time_ms if request_body.include_content else None,
            cache_hit=False,
            sources_queried=["searxng"],
            rate_limited=False,
        ),
    )

    # 12. Cache Response
    await cache_service.set(request_body, response, request_id)

    logger.info(
        "search_request_complete",
        request_id=request_id,
        result_count=len(ranked_results),
        total_time_ms=total_time_ms,
        searxng_time_ms=searxng_time_ms,
        extraction_time_ms=extraction_time_ms,
    )

    # Add rate limit headers
    headers = generate_rate_limit_headers(limit, remaining)

    return JSONResponse(
        content=response.model_dump(),
        headers=headers,
    )
```

## Key Implementation Details

### Request Lifecycle (TECH SPEC §4.2)

**Exact order:**
1. Validate request (automatic via Pydantic)
2. Authenticate (if API key required)
3. Rate limit check
4. Cache check → return if hit
5. SearXNG search
6. Domain filtering
7. Deduplication
8. Content extraction (parallel, if `include_content=True`)
9. Result assembly
10. Content quality filtering
11. Ranking
12. Response building
13. Cache storage
14. Return response

### Error Responses (TECH SPEC §6.3)

All errors return standardized JSON:
```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable message",
    "details": { /* optional context */ }
  },
  "metadata": {
    "request_id": "uuid",
    "api_version": "v1",
    "timestamp": 1234567890.0
  }
}
```

**Error codes:**
- `UNAUTHORIZED` (401) - Missing/invalid API key
- `VALIDATION_ERROR` (400) - Invalid request body
- `RATE_LIMITED` (429) - Rate limit exceeded
- `UPSTREAM_ERROR` (502) - SearXNG/Crawl4AI failure
- `INTERNAL_SERVER_ERROR` (500) - Unexpected error

### Partial Failure Handling (TECH SPEC §6.4)

- If SearXNG fails: Return 502
- If some extractions fail: Still return successful ones
- Mark failed extractions with `extraction_ok=false`
- Never fail entire request due to extraction failures

### Authentication (TECH SPEC §6.5)

- Optional API key via `x-api-key` header
- Only required if `BS_API_KEY` env var is set
- 401 response includes `WWW-Authenticate` header

### Rate Limit Headers (TECH SPEC §6.5)

Always include:
- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`

On 429:
- Add `Retry-After` header

## Testing Requirements

### Unit Tests (`tests/unit/test_search_endpoint.py`)

```python
import pytest
from fastapi.testclient import TestClient
from butterscout.main import app

def test_search_validation():
    """Test request validation"""
    client = TestClient(app)

    # Empty query should fail
    response = client.post("/api/v1/search", json={"query": ""})
    assert response.status_code == 422

    # Too many results should fail
    response = client.post("/api/v1/search", json={
        "query": "test",
        "max_results": 100,
    })
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_search_cache_hit(mock_cache):
    """Test that cache hits return immediately"""
    # Mock cache to return result
    # Verify SearXNG is not called
    pass

@pytest.mark.asyncio
async def test_search_without_content():
    """Test search with include_content=false"""
    client = TestClient(app)

    response = client.post("/api/v1/search", json={
        "query": "test query",
        "include_content": False,
    })

    assert response.status_code == 200
    data = response.json()

    # Results should have no content
    for result in data["results"]:
        assert result["content"] is None

@pytest.mark.asyncio
async def test_rate_limit_headers():
    """Test that rate limit headers are included"""
    client = TestClient(app)

    response = client.post("/api/v1/search", json={"query": "test"})

    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers
```

### Integration Tests

- Test full search pipeline end-to-end
- Test with real SearXNG + Crawl4AI
- Test cache behavior (miss → set → hit)
- Test rate limiting across multiple requests
- Test partial extraction failures

## Performance Requirements

- Total p95 latency: ≤ 3s (balanced mode, default settings)
- Cache hit response: < 100ms
- SearXNG call: < 2s
- Extraction (4 concurrent): < 2.5s per URL

## Output Format

When complete, provide:

1. ✅ Endpoint implemented and working
2. ✅ Tests passing
3. 📊 Example requests/responses:
   - Successful search with content
   - Successful search without content
   - Cache hit response
   - Rate limit 429 response
   - Authentication 401 response
4. 📝 Performance timing breakdown

## Dependencies

- **Task 01** (Project Foundation)
- **Task 03** (SearXNG Client)
- **Task 05** (Extraction Orchestrator)
- **Task 06** (Caching Layer)
- **Task 07** (Rate Limiting)
- **Task 08** (Ranking & Deduplication)
- **Task 09** (FastAPI App & Health)

## Time Estimate

5-6 hours

## Reference

- [TECH SPEC.md] §4.2: Request Lifecycle
- [TECH SPEC.md] §6.1: API Design - POST /api/v1/search
- [TECH SPEC.md] §6.3: Schema Precision - Error responses
- [TECH SPEC.md] §6.4: Partial Failure Handling
- [TECH SPEC.md] §6.5: Auth & Rate-Limit Semantics
