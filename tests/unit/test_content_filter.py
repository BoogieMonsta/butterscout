"""Tests for content quality filter."""

from __future__ import annotations

from typing import cast

from pydantic import HttpUrl

from butterscout.models.responses import ResultMetadata, ResultScores, SearchResult
from butterscout.utils.content_filter import MIN_WORD_COUNT, filter_low_quality_results


def _url(url_str: str) -> HttpUrl:
    return cast(HttpUrl, url_str)


def test_filter_keeps_good_content() -> None:
    """Test that filter keeps results with sufficient word count."""
    results = [
        SearchResult(
            title="Good Article",
            url=_url("https://example.com/article"),
            snippet="This is a good article",
            content="This is good content with more than ten words here to test the filter.",
            metadata=ResultMetadata(
                domain="example.com",
                word_count=50,
                extracted_by="crawl4ai",
                extraction_ok=True,
            ),
            scores=ResultScores(search_score=0.95, rank=1),
            source="searxng",
        ),
    ]

    filtered = filter_low_quality_results(results, "test-123")

    assert len(filtered) == 1
    assert filtered[0].metadata.word_count == 50


def test_filter_removes_short_content() -> None:
    """Test that filter removes results with very short content."""
    results = [
        SearchResult(
            title="Short Article",
            url=_url("https://example.com/article"),
            snippet="This is a short article",
            content="Too short",
            metadata=ResultMetadata(
                domain="example.com",
                word_count=2,
                extracted_by="crawl4ai",
                extraction_ok=True,
            ),
            scores=ResultScores(search_score=0.95, rank=1),
            source="searxng",
        ),
    ]

    filtered = filter_low_quality_results(results, "test-123")

    assert len(filtered) == 0


def test_filter_keeps_failed_extractions() -> None:
    """Test that filter keeps results where extraction failed (still have snippet)."""
    results = [
        SearchResult(
            title="Failed Extraction",
            url=_url("https://example.com/article"),
            snippet="This is a useful snippet that should be kept",
            content=None,
            metadata=ResultMetadata(
                domain="example.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.95, rank=1),
            source="searxng",
        ),
    ]

    filtered = filter_low_quality_results(results, "test-123")

    assert len(filtered) == 1
    assert filtered[0].metadata.extraction_ok is False


def test_filter_mixed_results() -> None:
    """Test filter with mix of good, bad, and failed extractions."""
    results = [
        SearchResult(
            title="Good Article",
            url=_url("https://example1.com/article"),
            snippet="Good snippet",
            content=(
                "This is good content with many words here to pass the filter test successfully."
            ),
            metadata=ResultMetadata(
                domain="example1.com",
                word_count=50,
                extracted_by="crawl4ai",
                extraction_ok=True,
            ),
            scores=ResultScores(search_score=0.95, rank=1),
            source="searxng",
        ),
        SearchResult(
            title="Short Article",
            url=_url("https://example2.com/article"),
            snippet="Short snippet",
            content="Too short",
            metadata=ResultMetadata(
                domain="example2.com",
                word_count=2,
                extracted_by="crawl4ai",
                extraction_ok=True,
            ),
            scores=ResultScores(search_score=0.85, rank=2),
            source="searxng",
        ),
        SearchResult(
            title="Failed Article",
            url=_url("https://example3.com/article"),
            snippet="Failed snippet",
            content=None,
            metadata=ResultMetadata(
                domain="example3.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.75, rank=3),
            source="searxng",
        ),
        SearchResult(
            title="Another Good Article",
            url=_url("https://example4.com/article"),
            snippet="Another good snippet",
            content=(
                "This is another good article with sufficient "
                "content to pass the minimum word count."
            ),
            metadata=ResultMetadata(
                domain="example4.com",
                word_count=35,
                extracted_by="trafilatura",
                extraction_ok=True,
            ),
            scores=ResultScores(search_score=0.65, rank=4),
            source="searxng",
        ),
    ]

    filtered = filter_low_quality_results(results, "test-123")

    assert len(filtered) == 3
    # Should keep: good article, failed extraction, another good article
    # Should remove: short article
    assert str(filtered[0].url) == "https://example1.com/article"
    assert str(filtered[1].url) == "https://example3.com/article"
    assert str(filtered[2].url) == "https://example4.com/article"


def test_filter_boundary_word_count() -> None:
    """Test filter at the boundary of MIN_WORD_COUNT."""
    results = [
        SearchResult(
            title="At Minimum",
            url=_url("https://example1.com/article"),
            snippet="At minimum",
            content="This has exactly ten words in it to test boundary.",
            metadata=ResultMetadata(
                domain="example1.com",
                word_count=MIN_WORD_COUNT,
                extracted_by="crawl4ai",
                extraction_ok=True,
            ),
            scores=ResultScores(search_score=0.95, rank=1),
            source="searxng",
        ),
        SearchResult(
            title="Below Minimum",
            url=_url("https://example2.com/article"),
            snippet="Below minimum",
            content="This has nine words to test boundary case.",
            metadata=ResultMetadata(
                domain="example2.com",
                word_count=MIN_WORD_COUNT - 1,
                extracted_by="crawl4ai",
                extraction_ok=True,
            ),
            scores=ResultScores(search_score=0.85, rank=2),
            source="searxng",
        ),
    ]

    filtered = filter_low_quality_results(results, "test-123")

    assert len(filtered) == 1
    assert filtered[0].metadata.word_count == MIN_WORD_COUNT


def test_filter_empty_input() -> None:
    """Test filter with empty list."""
    results: list[SearchResult] = []

    filtered = filter_low_quality_results(results, "test-123")

    assert len(filtered) == 0


def test_filter_none_word_count() -> None:
    """Test filter handles None word_count gracefully."""
    results = [
        SearchResult(
            title="Article",
            url=_url("https://example.com/article"),
            snippet="Snippet",
            content="Some content",
            metadata=ResultMetadata(
                domain="example.com",
                word_count=None,
                extracted_by="crawl4ai",
                extraction_ok=True,
            ),
            scores=ResultScores(search_score=0.95, rank=1),
            source="searxng",
        ),
    ]

    # Should keep result if word_count is None (defensive)
    filtered = filter_low_quality_results(results, "test-123")

    assert len(filtered) == 1
