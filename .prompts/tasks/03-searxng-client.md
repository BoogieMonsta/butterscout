# Task 03: SearXNG Client

**Role:** You are a senior Python backend engineer specializing in HTTP client integration, API resilience patterns, and search engine integration.

## Context

Implement the SearXNG client that fetches search results and normalizes them into Butterscout's internal format. This client needs robust error handling, retry logic, and proper timeout management per TECH SPEC requirements.

Key defaults to honor: 2s per-attempt timeout; 1 retry (2 attempts total) on timeout/5xx/429 with 100–300ms jittered backoff.

Refer to **[TECH SPEC.md]** §4.1, §4.2, §6 for complete details.

## Deliverables

### 1. SearXNG Client (`butterscout/clients/searxng_client.py`)

```python
import httpx
from typing import List, Optional
from butterscout.config import Settings
from butterscout.models.internal import NormalizedSearchResult
from butterscout.models.requests import SearchRequest
import structlog

logger = structlog.get_logger()

class SearXNGClient:
    """Client for SearXNG meta-search engine"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.BS_SEARXNG_URL.rstrip("/")
        self.timeout = httpx.Timeout(
            connect=5.0,
            read=settings.BS_REQUEST_TIMEOUT_MS / 1000.0,
            write=5.0,
            pool=5.0,
        )
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize HTTP client"""
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
            ),
        )

    async def disconnect(self) -> None:
        """Close HTTP client"""
        if self.client:
            await self.client.aclose()

    async def search(
        self,
        request: SearchRequest,
        request_id: str
    ) -> List[NormalizedSearchResult]:
        """
        Execute search query against SearXNG

        Args:
            request: Search request with query and options
            request_id: Request ID for logging

        Returns:
            List of normalized search results

        Raises:
            httpx.HTTPError: On network/HTTP errors
            ValueError: On invalid response format
        """
        if not self.client:
            raise RuntimeError("SearXNG client not connected")

        # Build search params
        params = {
            "q": request.query,
            "format": "json",
            "safesearch": 0,
        }

        # Add language if specified
        if request.options.language:
            params["language"] = request.options.language

        # Add time range if specified (convert days to SearXNG format)
        if request.options.freshness_days:
            if request.options.freshness_days <= 1:
                params["time_range"] = "day"
            elif request.options.freshness_days <= 7:
                params["time_range"] = "week"
            elif request.options.freshness_days <= 30:
                params["time_range"] = "month"
            else:
                params["time_range"] = "year"

        logger.info(
            "searxng_request",
            request_id=request_id,
            query=request.query,
            language=request.options.language,
        )

        # Execute with retry on 5xx/timeout
        attempt = 0
        last_error = None

        while attempt < 2:  # 1 retry = 2 total attempts
            try:
                response = await self.client.get(
                    f"{self.base_url}/search",
                    params=params,
                )
                response.raise_for_status()

                # Parse and normalize results
                data = response.json()
                results = self._normalize_results(data, request.max_results)

                logger.info(
                    "searxng_success",
                    request_id=request_id,
                    result_count=len(results),
                    attempt=attempt + 1,
                )

                return results

            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_error = e
                attempt += 1

                if attempt < 2 and self._should_retry(e):
                    # Jittered backoff: 100-300ms
                    import random
                    import asyncio
                    await asyncio.sleep(random.uniform(0.1, 0.3))

                    logger.warning(
                        "searxng_retry",
                        request_id=request_id,
                        attempt=attempt + 1,
                        error=str(e),
                    )
                else:
                    break

        # All retries failed
        logger.error(
            "searxng_failed",
            request_id=request_id,
            error=str(last_error),
            attempts=attempt + 1,
        )
        raise last_error

    def _should_retry(self, error: Exception) -> bool:
        """Determine if error is retryable"""
        if isinstance(error, httpx.TimeoutException):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            # Retry on 5xx errors only
            return 500 <= error.response.status_code < 600
        return False

    def _normalize_results(
        self,
        data: dict,
        max_results: int
    ) -> List[NormalizedSearchResult]:
        """
        Normalize SearXNG response to internal format

        Args:
            data: Raw SearXNG JSON response
            max_results: Maximum number of results to return

        Returns:
            List of normalized search results
        """
        results = []

        raw_results = data.get("results", [])[:max_results]

        for idx, item in enumerate(raw_results):
            try:
                # Calculate score (SearXNG doesn't always provide scores)
                # Use inverse of position as fallback
                score = item.get("score", 1.0 / (idx + 1))

                result = NormalizedSearchResult(
                    title=item.get("title", "No title"),
                    url=item["url"],  # Required field
                    snippet=item.get("content", "")[:500],  # Limit snippet length
                    score=float(score),
                    source="searxng",
                )
                results.append(result)

            except (KeyError, ValueError) as e:
                logger.warning(
                    "searxng_result_parse_error",
                    error=str(e),
                    item=item,
                )
                continue

        return results

    async def health_check(self) -> bool:
        """
        Check if SearXNG is responsive

        Returns:
            True if healthy, False otherwise
        """
        if not self.client:
            return False

        try:
            response = await self.client.get(
                f"{self.base_url}/",
                timeout=httpx.Timeout(
                    self.settings.BS_HEALTH_TIMEOUT_MS / 1000.0
                ),
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("searxng_health_check_failed", error=str(e))
            return False
```

### 2. Domain Filtering (`butterscout/utils/domain_filter.py`)

Implement domain whitelist/blacklist logic:

```python
from typing import List
from urllib.parse import urlparse

def is_domain_allowed(
    url: str,
    allowed_domains: List[str],
    blocked_domains: List[str],
) -> bool:
    """
    Check if URL's domain passes filtering rules

    Args:
        url: Full URL to check
        allowed_domains: Whitelist (empty = allow all)
        blocked_domains: Blacklist

    Returns:
        True if domain is allowed
    """
    try:
        domain = urlparse(url).netloc.lower()

        # Remove www. prefix for comparison
        if domain.startswith("www."):
            domain = domain[4:]

        # Check blacklist first
        if blocked_domains:
            for blocked in blocked_domains:
                blocked_clean = blocked.lower().lstrip("www.")
                if domain == blocked_clean or domain.endswith(f".{blocked_clean}"):
                    return False

        # Check whitelist if present
        if allowed_domains:
            for allowed in allowed_domains:
                allowed_clean = allowed.lower().lstrip("www.")
                if domain == allowed_clean or domain.endswith(f".{allowed_clean}"):
                    return True
            return False  # Not in whitelist

        return True  # No whitelist = allow all (except blacklisted)

    except Exception:
        return False  # Invalid URL = block
```

## Key Implementation Details

### Retry Logic (TECH SPEC §4.2)

- **1 retry on 5xx/timeout** with jittered backoff (100-300ms)
- No retries on 4xx errors
- Total attempts: 2 (initial + 1 retry)

### Timeout Configuration

- Connect timeout: 5s
- Read timeout: From `BS_REQUEST_TIMEOUT_MS` setting
- Health check timeout: From `BS_HEALTH_TIMEOUT_MS` (750ms default)

### Score Normalization

SearXNG score handling:
- Use provided score if available
- Fallback: `1.0 / (position + 1)` (position-based score)
- Ensure score is between 0.0 and 1.0

### Error Handling

- Log all errors with structured logging
- Include request_id in all log entries
- Raise exceptions, don't swallow them
- Distinguish between retryable and non-retryable errors

## Testing Requirements

### Unit Tests (`tests/unit/test_searxng_client.py`)

```python
import pytest
import httpx
import respx
from butterscout.clients.searxng_client import SearXNGClient

@pytest.mark.asyncio
@respx.mock
async def test_searxng_search_success(settings):
    """Test successful search request"""
    mock_response = {
        "results": [
            {
                "title": "Test Result",
                "url": "https://example.com",
                "content": "Test content",
                "score": 0.95,
            }
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    request = SearchRequest(query="test query")
    results = await client.search(request, request_id="test-123")

    assert len(results) == 1
    assert results[0].title == "Test Result"
    assert results[0].url == "https://example.com"

@pytest.mark.asyncio
@respx.mock
async def test_searxng_retry_on_timeout(settings):
    """Test retry logic on timeout"""
    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        side_effect=[
            httpx.TimeoutException("Timeout"),
            httpx.Response(200, json={"results": []}),
        ]
    )

    client = SearXNGClient(settings)
    await client.connect()

    request = SearchRequest(query="test")
    results = await client.search(request, request_id="test-123")

    # Should succeed on retry
    assert isinstance(results, list)

@pytest.mark.asyncio
async def test_domain_filter():
    """Test domain filtering logic"""
    from butterscout.utils.domain_filter import is_domain_allowed

    # Test whitelist
    assert is_domain_allowed(
        "https://example.com/page",
        allowed_domains=["example.com"],
        blocked_domains=[],
    )

    assert not is_domain_allowed(
        "https://other.com/page",
        allowed_domains=["example.com"],
        blocked_domains=[],
    )

    # Test blacklist
    assert not is_domain_allowed(
        "https://spam.com/page",
        allowed_domains=[],
        blocked_domains=["spam.com"],
    )
```

### Integration Tests

- Test against real SearXNG instance (local Docker)
- Test various query types
- Test timeout handling
- Test domain filtering with real results

## Performance Requirements

- Search latency: < 2s (configurable, per TECH SPEC)
- Health check: < 750ms
- Connection pool supports concurrent requests

## Output Format

When complete, provide:

1. ✅ All files created
2. ✅ Tests passing
3. 📊 Example search results (show normalized format)
4. 📝 Retry behavior demonstration

## Dependencies

- **Task 01** (Project Foundation) - Requires config and models

## Time Estimate

4-5 hours

## Reference

- [TECH SPEC.md] §4.1: Components - Search Layer
- [TECH SPEC.md] §4.2: Request Lifecycle - SearXNG integration
- [TECH SPEC.md] §5.2: Search Provider
- [TECH SPEC.md] §6.2: Defaults, Limits & Timeouts
