"""Integration tests for complete extraction flow."""
from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pydantic import HttpUrl

from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent, NormalizedSearchResult
from butterscout.services.extraction_orchestrator import ExtractionOrchestrator
from butterscout.services.result_assembler import ResultAssembler
from butterscout.utils.content_filter import filter_low_quality_results


def _url(url_str: str) -> HttpUrl:
    return cast(HttpUrl, url_str)


@pytest.mark.asyncio
async def test_complete_extraction_flow(settings: Settings) -> None:
    """Test complete flow: orchestration -> assembly -> filtering."""
    # Mock extraction strategy
    mock_strategy = AsyncMock()

    async def mock_extract(url: HttpUrl, req_id: str) -> ExtractedContent:
        # Simulate different outcomes for different URLs
        url_str = str(url)
        if "fail" in url_str:
            return ExtractedContent(
                url=url,
                content="",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
                extraction_time_ms=0,
                error="Network error",
            )
        elif "short" in url_str:
            return ExtractedContent(
                url=url,
                content="Short.",
                word_count=1,
                extracted_by="crawl4ai",
                extraction_ok=True,
                extraction_time_ms=50,
            )
        else:
            return ExtractedContent(
                url=url,
                content=f"This is good quality content from {url_str} with many words to pass the filter test.",
                word_count=50,
                extracted_by="crawl4ai",
                extraction_ok=True,
                extraction_time_ms=100,
            )

    mock_strategy.extract = mock_extract

    # Step 1: Search results
    search_results = [
        NormalizedSearchResult(
            title="Good Article 1",
            url=_url("https://example1.com/good"),
            snippet="Good snippet 1",
            score=0.95,
        ),
        NormalizedSearchResult(
            title="Failed Article",
            url=_url("https://example2.com/fail"),
            snippet="Failed snippet",
            score=0.85,
        ),
        NormalizedSearchResult(
            title="Short Article",
            url=_url("https://example3.com/short"),
            snippet="Short snippet",
            score=0.75,
        ),
        NormalizedSearchResult(
            title="Good Article 2",
            url=_url("https://example4.com/good"),
            snippet="Good snippet 2",
            score=0.65,
        ),
    ]

    # Step 2: Extract content
    orchestrator = ExtractionOrchestrator(mock_strategy, settings)
    extracted_contents = await orchestrator.extract_all(search_results, "test-123")

    assert len(extracted_contents) == 4

    # Step 3: Assemble results
    assembled_results = ResultAssembler.assemble(
        search_results,
        extracted_contents,
        include_content=True,
        request_id="test-123",
    )

    assert len(assembled_results) == 4
    assert assembled_results[0].metadata.extraction_ok is True
    assert assembled_results[1].metadata.extraction_ok is False
    assert assembled_results[2].metadata.extraction_ok is True
    assert assembled_results[3].metadata.extraction_ok is True

    # Step 4: Filter low quality
    filtered_results = filter_low_quality_results(assembled_results, "test-123")

    # Should keep: good article 1, failed article (has snippet), good article 2
    # Should remove: short article
    assert len(filtered_results) == 3
    assert str(filtered_results[0].url) == "https://example1.com/good"
    assert str(filtered_results[1].url) == "https://example2.com/fail"
    assert str(filtered_results[2].url) == "https://example4.com/good"


@pytest.mark.asyncio
async def test_large_batch_extraction(settings: Settings) -> None:
    """Test extraction with large number of URLs."""
    mock_strategy = AsyncMock()

    async def mock_extract(url: HttpUrl, req_id: str) -> ExtractedContent:
        # Add small delay to simulate real work
        await asyncio.sleep(0.01)

        return ExtractedContent(
            url=url,
            content=f"Content for {url}",
            word_count=100,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=100,
        )

    mock_strategy.extract = mock_extract

    # Create 20 search results
    search_results = [
        NormalizedSearchResult(
            title=f"Article {i}",
            url=_url(f"https://example{i}.com/article"),
            snippet=f"Snippet {i}",
            score=1.0 - i * 0.05,
        )
        for i in range(20)
    ]

    # Extract with concurrency control
    settings.BS_MAX_CONCURRENT_EXTRACTIONS = 4
    orchestrator = ExtractionOrchestrator(mock_strategy, settings)

    import time

    start = time.perf_counter()
    extracted_contents = await orchestrator.extract_all(search_results, "test-123")
    duration = time.perf_counter() - start

    assert len(extracted_contents) == 20
    assert all(ec.extraction_ok for ec in extracted_contents)

    # With concurrency=4 and 0.01s per extraction, should take ~0.05s
    # (20 extractions / 4 concurrent = 5 batches * 0.01s)
    # Add buffer for overhead
    assert duration < 0.5


@pytest.mark.asyncio
async def test_all_extractions_fail(settings: Settings) -> None:
    """Test flow when all extractions fail."""
    mock_strategy = AsyncMock()
    mock_strategy.extract = AsyncMock(
        side_effect=Exception("All extractions failed")
    )

    search_results = [
        NormalizedSearchResult(
            title="Article 1",
            url=_url("https://example1.com/article"),
            snippet="Snippet 1",
            score=0.95,
        ),
        NormalizedSearchResult(
            title="Article 2",
            url=_url("https://example2.com/article"),
            snippet="Snippet 2",
            score=0.85,
        ),
    ]

    orchestrator = ExtractionOrchestrator(mock_strategy, settings)
    extracted_contents = await orchestrator.extract_all(search_results, "test-123")

    # All extractions should be marked as failed
    assert len(extracted_contents) == 2
    assert all(not ec.extraction_ok for ec in extracted_contents)

    # Assemble results - should still work
    assembled_results = ResultAssembler.assemble(
        search_results,
        extracted_contents,
        include_content=True,
        request_id="test-123",
    )

    assert len(assembled_results) == 2
    # Should still have snippets available
    assert all(r.snippet for r in assembled_results)
    assert all(r.content is None for r in assembled_results)

    # Filter should keep results with failed extraction (they have snippets)
    filtered_results = filter_low_quality_results(assembled_results, "test-123")
    assert len(filtered_results) == 2


@pytest.mark.asyncio
async def test_content_optional_flag(settings: Settings) -> None:
    """Test that include_content flag works correctly."""
    mock_strategy = AsyncMock()

    async def mock_extract(url: HttpUrl, req_id: str) -> ExtractedContent:
        return ExtractedContent(
            url=url,
            content="This is the full content of the article.",
            word_count=50,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=100,
        )

    mock_strategy.extract = mock_extract

    search_results = [
        NormalizedSearchResult(
            title="Article",
            url=_url("https://example.com/article"),
            snippet="Snippet",
            score=0.95,
        ),
    ]

    orchestrator = ExtractionOrchestrator(mock_strategy, settings)
    extracted_contents = await orchestrator.extract_all(search_results, "test-123")

    # Test with include_content=False
    assembled_without_content = ResultAssembler.assemble(
        search_results,
        extracted_contents,
        include_content=False,
        request_id="test-123",
    )

    assert assembled_without_content[0].content is None
    assert assembled_without_content[0].metadata.word_count == 50

    # Test with include_content=True
    assembled_with_content = ResultAssembler.assemble(
        search_results,
        extracted_contents,
        include_content=True,
        request_id="test-123",
    )

    assert assembled_with_content[0].content == "This is the full content of the article."
    assert assembled_with_content[0].metadata.word_count == 50


@pytest.mark.asyncio
async def test_partial_failure_graceful_degradation(settings: Settings) -> None:
    """Test graceful degradation with partial failures."""
    mock_strategy = AsyncMock()

    call_count = 0

    async def mock_extract(url: HttpUrl, req_id: str) -> ExtractedContent:
        nonlocal call_count
        call_count += 1

        # Fail every other extraction
        if call_count % 2 == 0:
            raise Exception(f"Failed extraction {call_count}")

        return ExtractedContent(
            url=url,
            content=f"Successful content for {url}",
            word_count=100,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=100,
        )

    mock_strategy.extract = mock_extract

    search_results = [
        NormalizedSearchResult(
            title=f"Article {i}",
            url=_url(f"https://example{i}.com/article"),
            snippet=f"Snippet {i}",
            score=1.0 - i * 0.1,
        )
        for i in range(10)
    ]

    # Extract
    orchestrator = ExtractionOrchestrator(mock_strategy, settings)
    extracted_contents = await orchestrator.extract_all(search_results, "test-123")

    # Should have all results, half successful and half failed
    assert len(extracted_contents) == 10
    successful = sum(1 for ec in extracted_contents if ec.extraction_ok)
    failed = sum(1 for ec in extracted_contents if not ec.extraction_ok)

    assert successful == 5
    assert failed == 5

    # Assemble
    assembled_results = ResultAssembler.assemble(
        search_results,
        extracted_contents,
        include_content=True,
        request_id="test-123",
    )

    # Should have content for successful extractions
    with_content = sum(1 for r in assembled_results if r.content)
    without_content = sum(1 for r in assembled_results if r.content is None)

    assert with_content == 5
    assert without_content == 5
