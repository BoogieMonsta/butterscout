"""Test data factories"""

from typing import Literal, cast
from pydantic import HttpUrl

from butterscout.models.internal import NormalizedSearchResult, ExtractedContent
from butterscout.models.responses import SearchResult, ResultMetadata, ResultScores


def _url(url_str: str) -> HttpUrl:
    """Helper to satisfy mypy for HttpUrl-typed model fields."""
    return cast(HttpUrl, url_str)


def create_search_result(
    title: str = "Test Result",
    url: str = "https://example.com",
    snippet: str = "Test snippet",
    score: float = 0.9,
) -> NormalizedSearchResult:
    """Factory for creating test search results"""
    return NormalizedSearchResult(
        title=title,
        url=_url(url),
        snippet=snippet,
        score=score,
    )


def create_extracted_content(
    url: str = "https://example.com",
    content: str = "Extracted content",
    word_count: int = 100,
    extracted_by: Literal["crawl4ai", "trafilatura", "none"] = "crawl4ai",
    extraction_ok: bool = True,
) -> ExtractedContent:
    """Factory for creating test extracted content"""
    return ExtractedContent(
        url=_url(url),
        content=content,
        word_count=word_count,
        extracted_by=extracted_by,
        extraction_ok=extraction_ok,
        extraction_time_ms=100,
    )


def create_api_search_result(
    title: str = "Test Result",
    url: str = "https://example.com",
    snippet: str = "Test snippet",
    content: str | None = "Test content",
    domain: str = "example.com",
    word_count: int = 50,
    extracted_by: Literal["crawl4ai", "trafilatura", "none"] = "crawl4ai",
    extraction_ok: bool = True,
    search_score: float = 0.9,
    rank: int = 1,
) -> SearchResult:
    """Factory for creating API search results"""
    return SearchResult(
        title=title,
        url=_url(url),
        snippet=snippet,
        content=content,
        metadata=ResultMetadata(
            domain=domain,
            word_count=word_count,
            extracted_by=extracted_by,
            extraction_ok=extraction_ok,
        ),
        scores=ResultScores(
            search_score=search_score,
            rank=rank,
        ),
        source="searxng",
    )
