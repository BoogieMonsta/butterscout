# Task 04: Extraction Clients (Crawl4AI + Trafilatura Fallback)

**Role:** You are a senior Python backend engineer specializing in web scraping, content extraction, and async I/O patterns with fallback strategies.

## Context

Implement both the primary Crawl4AI HTTP client and the fallback Trafilatura extractor. The system must gracefully degrade from Crawl4AI to Trafilatura when needed, with proper timeout handling and error classification.

Key defaults to honor: Crawl4AI per-URL timeout 2.5s, no retries (fail fast); fallback Trafilatura in a small threadpool with 2s timeout; fallback gated by config flag.

Refer to **[TECH SPEC.md]** §4.1, §4.2, §5.3, §6.2 for complete details.

## Deliverables

### 1. Crawl4AI Client (`butterscout/clients/crawl4ai_client.py`)

```python
import httpx
from typing import Optional
from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent
import structlog
import time

logger = structlog.get_logger()

class Crawl4AIClient:
    """Client for Crawl4AI extraction service"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.BS_CRAWL4AI_URL.rstrip("/")
        self.timeout_seconds = settings.BS_EXTRACTION_TIMEOUT_MS / 1000.0
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize HTTP client"""
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=self.timeout_seconds,
                write=5.0,
                pool=5.0,
            ),
            follow_redirects=False,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
            ),
        )

    async def disconnect(self) -> None:
        """Close HTTP client"""
        if self.client:
            await self.client.aclose()

    async def extract(
        self,
        url: str,
        request_id: str
    ) -> ExtractedContent:
        """
        Extract content from URL using Crawl4AI

        Args:
            url: URL to extract
            request_id: Request ID for logging

        Returns:
            ExtractedContent with markdown/text content

        Raises:
            httpx.HTTPError: On network/HTTP errors
            TimeoutError: On extraction timeout
        """
        if not self.client:
            raise RuntimeError("Crawl4AI client not connected")

        start_time = time.perf_counter()

        try:
            logger.info(
                "crawl4ai_extract_start",
                request_id=request_id,
                url=url,
            )

            # TODO: Adjust this API call based on actual Crawl4AI API
            # This is a placeholder structure
            response = await self.client.post(
                f"{self.base_url}/extract",
                json={
                    "url": url,
                    "format": "markdown",
                    "remove_selectors": [
                        "nav",
                        "header",
                        "footer",
                        ".advertisement",
                        ".cookie-banner",
                    ],
                },
            )

            response.raise_for_status()
            data = response.json()

            # Extract content and metadata
            content = data.get("content", "")
            word_count = len(content.split())

            extraction_time_ms = int((time.perf_counter() - start_time) * 1000)

            logger.info(
                "crawl4ai_extract_success",
                request_id=request_id,
                url=url,
                word_count=word_count,
                extraction_time_ms=extraction_time_ms,
            )

            return ExtractedContent(
                url=url,
                content=content,
                word_count=word_count,
                extracted_by="crawl4ai",
                extraction_ok=True,
                extraction_time_ms=extraction_time_ms,
            )

        except httpx.TimeoutException as e:
            extraction_time_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning(
                "crawl4ai_timeout",
                request_id=request_id,
                url=url,
                extraction_time_ms=extraction_time_ms,
            )
            raise TimeoutError(f"Crawl4AI extraction timeout: {url}") from e

        except Exception as e:
            extraction_time_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "crawl4ai_extract_error",
                request_id=request_id,
                url=url,
                error=str(e),
                extraction_time_ms=extraction_time_ms,
            )
            raise

    async def health_check(self) -> bool:
        """Check if Crawl4AI service is responsive"""
        if not self.client:
            return False

        try:
            response = await self.client.get(
                f"{self.base_url}/health",
                timeout=httpx.Timeout(
                    self.settings.BS_HEALTH_TIMEOUT_MS / 1000.0
                ),
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("crawl4ai_health_check_failed", error=str(e))
            return False
```

### 2. Trafilatura Fallback Extractor (`butterscout/clients/trafilatura_client.py`)

```python
import trafilatura
import httpx
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent
import structlog
import time
import asyncio

logger = structlog.get_logger()

class TrafilaturaClient:
    """Fallback content extractor using Trafilatura library"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.timeout_seconds = settings.BS_FALLBACK_TIMEOUT_MS / 1000.0
        self.max_workers = settings.BS_FALLBACK_MAX_WORKERS
        self.executor: Optional[ThreadPoolExecutor] = None
        self.http_client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize thread pool and HTTP client"""
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="trafilatura",
        )
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
        )

    async def disconnect(self) -> None:
        """Shutdown thread pool and close HTTP client"""
        if self.executor:
            self.executor.shutdown(wait=True)
        if self.http_client:
            await self.http_client.aclose()

    async def extract(
        self,
        url: str,
        request_id: str
    ) -> ExtractedContent:
        """
        Extract content using Trafilatura (fallback extractor)

        Args:
            url: URL to extract
            request_id: Request ID for logging

        Returns:
            ExtractedContent with extracted text

        Raises:
            Exception: On extraction failures
        """
        if not self.executor or not self.http_client:
            raise RuntimeError("Trafilatura client not connected")

        start_time = time.perf_counter()

        try:
            logger.info(
                "trafilatura_extract_start",
                request_id=request_id,
                url=url,
            )

            # Fetch HTML
            response = await self.http_client.get(url)
            response.raise_for_status()
            html = response.text

            # Run Trafilatura in thread pool (it's CPU-bound)
            loop = asyncio.get_event_loop()
            content = await loop.run_in_executor(
                self.executor,
                self._extract_sync,
                html,
            )

            if not content:
                raise ValueError("Trafilatura returned empty content")

            word_count = len(content.split())
            extraction_time_ms = int((time.perf_counter() - start_time) * 1000)

            logger.info(
                "trafilatura_extract_success",
                request_id=request_id,
                url=url,
                word_count=word_count,
                extraction_time_ms=extraction_time_ms,
            )

            return ExtractedContent(
                url=url,
                content=content,
                word_count=word_count,
                extracted_by="trafilatura",
                extraction_ok=True,
                extraction_time_ms=extraction_time_ms,
            )

        except Exception as e:
            extraction_time_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "trafilatura_extract_error",
                request_id=request_id,
                url=url,
                error=str(e),
                extraction_time_ms=extraction_time_ms,
            )
            raise

    def _extract_sync(self, html: str) -> Optional[str]:
        """
        Synchronous extraction with Trafilatura

        Runs in thread pool executor
        """
        return trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            output_format="txt",
        )
```

### 3. Extraction Strategy (`butterscout/clients/extraction_strategy.py`)

Coordinate between Crawl4AI and fallback:

```python
from typing import Optional
from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.models.internal import ExtractedContent
from butterscout.config import Settings
import structlog

logger = structlog.get_logger()

class ExtractionStrategy:
    """Coordinates between Crawl4AI and Trafilatura fallback"""

    def __init__(
        self,
        crawl4ai: Crawl4AIClient,
        trafilatura: Optional[TrafilaturaClient],
        settings: Settings
    ):
        self.crawl4ai = crawl4ai
        self.trafilatura = trafilatura
        self.fallback_enabled = settings.BS_FALLBACK_ENABLED

    async def extract(
        self,
        url: str,
        request_id: str
    ) -> ExtractedContent:
        """
        Extract content with fallback strategy

        Try Crawl4AI first, fall back to Trafilatura on failure
        """
        # Try Crawl4AI first
        try:
            return await self.crawl4ai.extract(url, request_id)

        except Exception as crawl_error:
            logger.warning(
                "crawl4ai_failed_trying_fallback",
                request_id=request_id,
                url=url,
                error=str(crawl_error),
            )

            # Try fallback if enabled
            if self.fallback_enabled and self.trafilatura:
                try:
                    return await self.trafilatura.extract(url, request_id)
                except Exception as fallback_error:
                    logger.error(
                        "fallback_also_failed",
                        request_id=request_id,
                        url=url,
                        crawl_error=str(crawl_error),
                        fallback_error=str(fallback_error),
                    )
                    # Return failed extraction
                    return ExtractedContent(
                        url=url,
                        content="",
                        word_count=0,
                        extracted_by="none",
                        extraction_ok=False,
                        extraction_time_ms=0,
                        error="Both extractors failed",
                    )
            else:
                # No fallback available, return failed extraction
                return ExtractedContent(
                    url=url,
                    content="",
                    word_count=0,
                    extracted_by="none",
                    extraction_ok=False,
                    extraction_time_ms=0,
                    error=str(crawl_error),
                )
```

## Key Implementation Details

### Timeout Handling

- **Crawl4AI**: `BS_EXTRACTION_TIMEOUT_MS` (default 2500ms)
- **Trafilatura**: `BS_FALLBACK_TIMEOUT_MS` (default 2000ms)
- Both must respect timeouts strictly - no silent hangs

### Fallback Strategy (TECH SPEC §4.1, §4.2)

1. Always try Crawl4AI first (primary)
2. On any Crawl4AI failure (timeout, error, empty), try Trafilatura
3. If both fail, return `ExtractedContent` with `extraction_ok=False`
4. Never raise exceptions - always return result object

### Content Quality Filters

- Minimum word count: 10 words (filter later in pipeline)
- Remove navigation, headers, footers, ads
- Extract main content only

### Thread Safety

- Trafilatura runs in ThreadPoolExecutor (CPU-bound)
- Default 2 workers to avoid CPU saturation
- Async wrapper properly awaits executor results

## Testing Requirements

### Unit Tests (`tests/unit/test_extraction_clients.py`)

```python
import pytest
import httpx
import respx
from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.trafilatura_client import TrafilaturaClient

@pytest.mark.asyncio
@respx.mock
async def test_crawl4ai_success(settings):
    """Test successful Crawl4AI extraction"""
    mock_response = {
        "content": "This is extracted content from Crawl4AI",
        "metadata": {},
    }

    respx.post(f"{settings.BS_CRAWL4AI_URL}/extract").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = Crawl4AIClient(settings)
    await client.connect()

    result = await client.extract("https://example.com", "test-123")

    assert result.extraction_ok is True
    assert result.extracted_by == "crawl4ai"
    assert result.word_count > 0

@pytest.mark.asyncio
async def test_trafilatura_extraction():
    """Test Trafilatura fallback extractor"""
    # This requires actual HTTP request or mocking
    # For now, test the sync extraction function
    from butterscout.clients.trafilatura_client import TrafilaturaClient

    html = """
    <html><body>
    <article>This is the main content of the article.</article>
    <nav>Navigation links</nav>
    </body></html>
    """

    client = TrafilaturaClient(settings)
    await client.connect()

    content = client._extract_sync(html)
    assert "main content" in content.lower()
    assert "navigation" not in content.lower()

@pytest.mark.asyncio
async def test_extraction_strategy_fallback():
    """Test fallback from Crawl4AI to Trafilatura"""
    # Mock Crawl4AI to fail
    # Mock Trafilatura to succeed
    # Verify fallback happens
    pass  # Implement with proper mocking
```

## Performance Requirements

- Crawl4AI extraction: < 2.5s per URL (configurable)
- Trafilatura fallback: < 2s per URL
- Thread pool: Support 2-4 concurrent Trafilatura extractions

## Output Format

When complete, provide:

1. ✅ All files created
2. ✅ Tests passing
3. 📊 Extraction comparison:
   - Sample URL extracted by both methods
   - Timing comparison
   - Content quality comparison
4. 📝 Fallback behavior demonstration

## Dependencies

- **Task 01** (Project Foundation) - Requires config and models

## Time Estimate

5-6 hours

## Reference

- [TECH SPEC.md] §4.1: Components - Extraction Layer
- [TECH SPEC.md] §4.2: Request Lifecycle - Extraction with fallback
- [TECH SPEC.md] §5.3: Extraction technology choices
- [TECH SPEC.md] §6.2: Timeouts
