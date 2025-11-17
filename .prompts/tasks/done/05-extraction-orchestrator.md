# Task 05: Extraction Orchestrator

**Role:** You are a senior Python backend engineer specializing in async I/O orchestration, concurrency control, and resilient distributed systems patterns.

## Context

Build the extraction orchestrator that coordinates parallel content extraction across multiple URLs with semaphore-based concurrency control, timeout enforcement, and graceful degradation. This is a critical component that must handle partial failures elegantly.

Key defaults to honor: per-request concurrency cap = 4 (no global semaphore), per-URL timeouts: Crawl4AI 2.5s with no retries (fallback immediately), Trafilatura fallback 2s, fit within ~6s total budget.

Refer to **[TECH SPEC.md]** §4.1, §4.2, §6.2, §6.4 for complete details.

## Deliverables

### 1. Extraction Orchestrator (`butterscout/services/extraction_orchestrator.py`)

```python
import asyncio
from typing import List
from butterscout.clients.extraction_strategy import ExtractionStrategy
from butterscout.models.internal import NormalizedSearchResult, ExtractedContent
from butterscout.config import Settings
import structlog
import time

logger = structlog.get_logger()

class ExtractionOrchestrator:
    """Orchestrates parallel content extraction with concurrency control"""

    def __init__(
        self,
        extraction_strategy: ExtractionStrategy,
        settings: Settings
    ):
        self.extraction_strategy = extraction_strategy
        self.settings = settings
        self.max_concurrent = settings.BS_MAX_CONCURRENT_EXTRACTIONS
        self.semaphore = asyncio.Semaphore(self.max_concurrent)

    async def extract_all(
        self,
        search_results: List[NormalizedSearchResult],
        request_id: str
    ) -> List[ExtractedContent]:
        """
        Extract content from all search result URLs in parallel

        Args:
            search_results: List of search results to extract
            request_id: Request ID for logging

        Returns:
            List of ExtractedContent (includes failed extractions)
        """
        start_time = time.perf_counter()

        logger.info(
            "extraction_orchestrator_start",
            request_id=request_id,
            url_count=len(search_results),
            max_concurrent=self.max_concurrent,
        )

        # Create extraction tasks
        tasks = [
            self._extract_with_semaphore(result.url, request_id)
            for result in search_results
        ]

        # Execute all tasks concurrently
        extracted_contents = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any unexpected exceptions
        results = []
        for idx, content in enumerate(extracted_contents):
            if isinstance(content, Exception):
                logger.error(
                    "extraction_unexpected_error",
                    request_id=request_id,
                    url=search_results[idx].url,
                    error=str(content),
                )
                # Create failed extraction result
                results.append(
                    ExtractedContent(
                        url=search_results[idx].url,
                        content="",
                        word_count=0,
                        extracted_by="none",
                        extraction_ok=False,
                        extraction_time_ms=0,
                        error=str(content),
                    )
                )
            else:
                results.append(content)

        # Calculate metrics
        total_time_ms = int((time.perf_counter() - start_time) * 1000)
        successful = sum(1 for r in results if r.extraction_ok)
        failed = len(results) - successful

        logger.info(
            "extraction_orchestrator_complete",
            request_id=request_id,
            total_urls=len(results),
            successful=successful,
            failed=failed,
            total_time_ms=total_time_ms,
        )

        return results

    async def _extract_with_semaphore(
        self,
        url: str,
        request_id: str
    ) -> ExtractedContent:
        """
        Extract single URL with semaphore for concurrency control

        Args:
            url: URL to extract
            request_id: Request ID

        Returns:
            ExtractedContent (never raises, returns failed result on error)
        """
        async with self.semaphore:
            try:
                return await self.extraction_strategy.extract(url, request_id)
            except Exception as e:
                logger.error(
                    "extraction_orchestrator_error",
                    request_id=request_id,
                    url=url,
                    error=str(e),
                )
                return ExtractedContent(
                    url=url,
                    content="",
                    word_count=0,
                    extracted_by="none",
                    extraction_ok=False,
                    extraction_time_ms=0,
                    error=str(e),
                )
```

### 2. Result Assembly (`butterscout/services/result_assembler.py`)

Combine search results with extracted content:

```python
from typing import List
from butterscout.models.internal import NormalizedSearchResult, ExtractedContent
from butterscout.models.responses import SearchResult, ResultMetadata, ResultScores
from urllib.parse import urlparse
import structlog

logger = structlog.get_logger()

class ResultAssembler:
    """Assembles final search results from SERP + extracted content"""

    @staticmethod
    def assemble(
        search_results: List[NormalizedSearchResult],
        extracted_contents: List[ExtractedContent],
        include_content: bool,
        request_id: str
    ) -> List[SearchResult]:
        """
        Combine search results with extracted content

        Args:
            search_results: Normalized SERP results
            extracted_contents: Extracted page contents
            include_content: Whether to include full content
            request_id: Request ID for logging

        Returns:
            List of complete SearchResult objects
        """
        # Create URL -> ExtractedContent mapping
        content_map = {str(ec.url): ec for ec in extracted_contents}

        results = []

        for idx, search_result in enumerate(search_results):
            url_str = str(search_result.url)
            extracted = content_map.get(url_str)

            # Determine extraction status
            if extracted and extracted.extraction_ok:
                extraction_metadata = ResultMetadata(
                    domain=urlparse(url_str).netloc,
                    word_count=extracted.word_count,
                    extracted_by=extracted.extracted_by,
                    extraction_ok=True,
                )
                content = extracted.content if include_content else None
            else:
                # Extraction failed or not attempted
                extraction_metadata = ResultMetadata(
                    domain=urlparse(url_str).netloc,
                    word_count=0,
                    extracted_by="none" if not extracted else extracted.extracted_by,
                    extraction_ok=False,
                )
                content = None

            # Create final result
            result = SearchResult(
                title=search_result.title,
                url=url_str,
                snippet=search_result.snippet,
                content=content,
                metadata=extraction_metadata,
                scores=ResultScores(
                    search_score=search_result.score,
                    rank=idx + 1,
                ),
                source=search_result.source,
            )

            results.append(result)

        logger.info(
            "results_assembled",
            request_id=request_id,
            total_results=len(results),
            with_content=sum(1 for r in results if r.content),
        )

        return results
```

### 3. Content Quality Filter (`butterscout/utils/content_filter.py`)

Filter out low-quality extractions:

```python
from typing import List
from butterscout.models.responses import SearchResult
import structlog

logger = structlog.get_logger()

MIN_WORD_COUNT = 10  # TECH SPEC §4.1 - filter extremely short content

def filter_low_quality_results(
    results: List[SearchResult],
    request_id: str
) -> List[SearchResult]:
    """
    Filter out results with low-quality or empty content

    Args:
        results: List of search results
        request_id: Request ID for logging

    Returns:
        Filtered list of results
    """
    filtered = []

    for result in results:
        # Keep result if extraction failed (still has snippet)
        if not result.metadata.extraction_ok:
            filtered.append(result)
            continue

        # Filter out results with very short content
        if result.content and result.metadata.word_count < MIN_WORD_COUNT:
            logger.debug(
                "filtered_short_content",
                request_id=request_id,
                url=result.url,
                word_count=result.metadata.word_count,
            )
            continue

        filtered.append(result)

    logger.info(
        "content_filtering_complete",
        request_id=request_id,
        original_count=len(results),
        filtered_count=len(filtered),
        removed=len(results) - len(filtered),
    )

    return filtered
```

## Key Implementation Details

### Concurrency Control (TECH SPEC §6.2)

- Use `asyncio.Semaphore` with `BS_MAX_CONCURRENT_EXTRACTIONS` (default 4)
- This protects upstream services from overload
- Applies per-request, not global

### Graceful Degradation (TECH SPEC §6.4)

- **Never raise exceptions** from orchestrator
- Always return `ExtractedContent` objects
- Mark failed extractions with `extraction_ok=False`
- Include error message in `error` field
- Partial results are still returned

### Timeout Enforcement

- Individual URL timeouts handled by extraction clients
- Overall request budget: `BS_REQUEST_TIMEOUT_MS` (6s default)
- If approaching budget, log warning but continue

### Error Handling Strategy

1. Try extraction (Crawl4AI → fallback if enabled)
2. On any error, return failed `ExtractedContent`
3. `asyncio.gather` with `return_exceptions=True`
4. Convert exceptions to failed result objects
5. Never fail entire request due to one bad URL

## Testing Requirements

### Unit Tests (`tests/unit/test_extraction_orchestrator.py`)

```python
import pytest
from unittest.mock import AsyncMock
from butterscout.services.extraction_orchestrator import ExtractionOrchestrator

@pytest.mark.asyncio
async def test_orchestrator_parallel_extraction(settings):
    """Test parallel extraction of multiple URLs"""
    mock_strategy = AsyncMock()
    mock_strategy.extract = AsyncMock(
        side_effect=lambda url, req_id: ExtractedContent(
            url=url,
            content=f"Content for {url}",
            word_count=100,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=100,
        )
    )

    orchestrator = ExtractionOrchestrator(mock_strategy, settings)

    search_results = [
        NormalizedSearchResult(
            title="Test 1",
            url="https://example1.com",
            snippet="Snippet 1",
            score=0.9,
        ),
        NormalizedSearchResult(
            title="Test 2",
            url="https://example2.com",
            snippet="Snippet 2",
            score=0.8,
        ),
    ]

    results = await orchestrator.extract_all(search_results, "test-123")

    assert len(results) == 2
    assert all(r.extraction_ok for r in results)

@pytest.mark.asyncio
async def test_orchestrator_handles_failures():
    """Test that orchestrator handles extraction failures gracefully"""
    mock_strategy = AsyncMock()
    mock_strategy.extract = AsyncMock(
        side_effect=Exception("Extraction failed")
    )

    orchestrator = ExtractionOrchestrator(mock_strategy, settings)

    search_results = [
        NormalizedSearchResult(
            title="Test",
            url="https://example.com",
            snippet="Snippet",
            score=0.9,
        ),
    ]

    results = await orchestrator.extract_all(search_results, "test-123")

    assert len(results) == 1
    assert results[0].extraction_ok is False
    assert results[0].error

@pytest.mark.asyncio
async def test_result_assembler():
    """Test combining search + extraction results"""
    from butterscout.services.result_assembler import ResultAssembler

    search_results = [
        NormalizedSearchResult(
            title="Test",
            url="https://example.com",
            snippet="Snippet",
            score=0.9,
        ),
    ]

    extracted_contents = [
        ExtractedContent(
            url="https://example.com",
            content="Full content here",
            word_count=50,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=100,
        ),
    ]

    results = ResultAssembler.assemble(
        search_results,
        extracted_contents,
        include_content=True,
        request_id="test-123",
    )

    assert len(results) == 1
    assert results[0].content == "Full content here"
    assert results[0].metadata.extraction_ok is True
```

### Integration Tests

- Test with multiple URLs (10+)
- Verify concurrency is limited to semaphore value
- Test with mix of successful and failed extractions
- Verify timing stays within budget

## Performance Requirements

- Handle up to 25 concurrent URL extractions
- Respect semaphore limit (default 4 concurrent)
- Total extraction time: < 3s for balanced mode
- No memory leaks from failed tasks

## Output Format

When complete, provide:

1. ✅ All files created
2. ✅ Tests passing
3. 📊 Performance metrics:
   - 10 URLs extracted with concurrency=4
   - Timing breakdown
   - Success/failure counts
4. 📝 Example showing graceful degradation

## Dependencies

- **Task 01** (Project Foundation)
- **Task 04** (Extraction Clients)

## Time Estimate

4-5 hours

## Reference

- [TECH SPEC.md] §4.1: Extraction Layer
- [TECH SPEC.md] §4.2: Request Lifecycle - Parallel extraction
- [TECH SPEC.md] §6.2: Concurrency limits
- [TECH SPEC.md] §6.4: Partial Failure Handling
