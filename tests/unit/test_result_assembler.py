"""Tests for result assembler."""
from __future__ import annotations

import pytest

from butterscout.models.internal import ExtractedContent, NormalizedSearchResult
from butterscout.services.result_assembler import ResultAssembler


def test_result_assembler_with_content():
    """Test combining search + extraction results with content."""
    search_results = [
        NormalizedSearchResult(
            title="Test Article",
            url="https://example.com/article",
            snippet="This is a test snippet",
            score=0.95,
        ),
    ]

    extracted_contents = [
        ExtractedContent(
            url="https://example.com/article",
            content="Full content here with many words in it",
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
    assert results[0].title == "Test Article"
    assert str(results[0].url) == "https://example.com/article"
    assert results[0].snippet == "This is a test snippet"
    assert results[0].content == "Full content here with many words in it"
    assert results[0].metadata.word_count == 50
    assert results[0].metadata.extracted_by == "crawl4ai"
    assert results[0].metadata.extraction_ok is True
    assert results[0].metadata.domain == "example.com"
    assert results[0].scores.search_score == 0.95
    assert results[0].scores.rank == 1


def test_result_assembler_without_content():
    """Test assembler excludes content when include_content=False."""
    search_results = [
        NormalizedSearchResult(
            title="Test Article",
            url="https://example.com/article",
            snippet="This is a test snippet",
            score=0.95,
        ),
    ]

    extracted_contents = [
        ExtractedContent(
            url="https://example.com/article",
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
        include_content=False,
        request_id="test-123",
    )

    assert len(results) == 1
    assert results[0].content is None
    assert results[0].metadata.extraction_ok is True
    assert results[0].metadata.word_count == 50


def test_result_assembler_failed_extraction():
    """Test assembler handles failed extraction."""
    search_results = [
        NormalizedSearchResult(
            title="Test Article",
            url="https://example.com/article",
            snippet="This is a test snippet",
            score=0.95,
        ),
    ]

    extracted_contents = [
        ExtractedContent(
            url="https://example.com/article",
            content="",
            word_count=0,
            extracted_by="none",
            extraction_ok=False,
            extraction_time_ms=0,
            error="Timeout",
        ),
    ]

    results = ResultAssembler.assemble(
        search_results,
        extracted_contents,
        include_content=True,
        request_id="test-123",
    )

    assert len(results) == 1
    assert results[0].content is None
    assert results[0].metadata.extraction_ok is False
    assert results[0].metadata.extracted_by == "none"
    assert results[0].metadata.word_count == 0
    # Snippet should still be available
    assert results[0].snippet == "This is a test snippet"


def test_result_assembler_multiple_results():
    """Test assembler with multiple search results."""
    search_results = [
        NormalizedSearchResult(
            title="Article 1",
            url="https://example1.com/article",
            snippet="Snippet 1",
            score=0.95,
        ),
        NormalizedSearchResult(
            title="Article 2",
            url="https://example2.com/article",
            snippet="Snippet 2",
            score=0.85,
        ),
        NormalizedSearchResult(
            title="Article 3",
            url="https://example3.com/article",
            snippet="Snippet 3",
            score=0.75,
        ),
    ]

    extracted_contents = [
        ExtractedContent(
            url="https://example1.com/article",
            content="Content 1",
            word_count=30,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=100,
        ),
        ExtractedContent(
            url="https://example2.com/article",
            content="",
            word_count=0,
            extracted_by="none",
            extraction_ok=False,
            extraction_time_ms=0,
            error="Failed",
        ),
        ExtractedContent(
            url="https://example3.com/article",
            content="Content 3",
            word_count=40,
            extracted_by="trafilatura",
            extraction_ok=True,
            extraction_time_ms=150,
        ),
    ]

    results = ResultAssembler.assemble(
        search_results,
        extracted_contents,
        include_content=True,
        request_id="test-123",
    )

    assert len(results) == 3

    # First result - success
    assert results[0].content == "Content 1"
    assert results[0].metadata.extraction_ok is True
    assert results[0].scores.rank == 1

    # Second result - failed
    assert results[1].content is None
    assert results[1].metadata.extraction_ok is False
    assert results[1].scores.rank == 2

    # Third result - success with fallback
    assert results[2].content == "Content 3"
    assert results[2].metadata.extraction_ok is True
    assert results[2].metadata.extracted_by == "trafilatura"
    assert results[2].scores.rank == 3


def test_result_assembler_missing_extraction():
    """Test assembler when extraction is missing for a URL."""
    search_results = [
        NormalizedSearchResult(
            title="Article 1",
            url="https://example1.com/article",
            snippet="Snippet 1",
            score=0.95,
        ),
        NormalizedSearchResult(
            title="Article 2",
            url="https://example2.com/article",
            snippet="Snippet 2",
            score=0.85,
        ),
    ]

    # Only one extraction result
    extracted_contents = [
        ExtractedContent(
            url="https://example1.com/article",
            content="Content 1",
            word_count=30,
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

    assert len(results) == 2
    assert results[0].metadata.extraction_ok is True
    assert results[1].metadata.extraction_ok is False
    assert results[1].metadata.extracted_by == "none"
    assert results[1].content is None


def test_result_assembler_domain_extraction():
    """Test that domains are correctly extracted from URLs."""
    search_results = [
        NormalizedSearchResult(
            title="Article",
            url="https://blog.example.com/path/to/article",
            snippet="Snippet",
            score=0.95,
        ),
    ]

    extracted_contents = [
        ExtractedContent(
            url="https://blog.example.com/path/to/article",
            content="Content",
            word_count=30,
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

    assert results[0].metadata.domain == "blog.example.com"
