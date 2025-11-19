from typing import cast

import pytest
from pydantic import HttpUrl

from butterscout.config import Settings
from butterscout.services.deduplicator import URLDeduplicator
from butterscout.services.ranker import Ranker


def _url(url_str: str) -> HttpUrl:
    """Helper to satisfy mypy for HttpUrl-typed model fields."""
    return cast(HttpUrl, url_str)


def test_url_normalization() -> None:
    """Test URL normalization removes tracking params and normalizes format"""
    assert (
        URLDeduplicator.normalize_url("https://WWW.Example.com/page/?utm_source=google&id=123")
        == "https://example.com/page?id=123"
    )

    assert URLDeduplicator.normalize_url("https://example.com/page/") == "https://example.com/page"

    assert (
        URLDeduplicator.normalize_url("https://example.com/page?b=2&a=1")
        == "https://example.com/page?a=1&b=2"
    )


def test_deduplication() -> None:
    """Test duplicate URLs are removed"""
    from butterscout.models.internal import NormalizedSearchResult

    results = [
        NormalizedSearchResult(
            title="Page 1",
            url=_url("https://example.com/page"),
            snippet="Snippet",
            score=0.9,
        ),
        NormalizedSearchResult(
            title="Page 1 Duplicate",
            url=_url("https://www.example.com/page/"),
            snippet="Snippet",
            score=0.8,
        ),
        NormalizedSearchResult(
            title="Page 2",
            url=_url("https://example.com/other"),
            snippet="Snippet",
            score=0.7,
        ),
    ]

    deduplicated = URLDeduplicator.deduplicate(results, "test-123")

    assert len(deduplicated) == 2
    assert deduplicated[0].title == "Page 1"  # Keep first occurrence


def test_ranker_applies_domain_boost(settings: Settings) -> None:
    """Test that allowed domains get ranking boost"""
    settings.BS_ALLOWED_DOMAINS = "example.com"
    ranker = Ranker(settings)

    from butterscout.models.responses import (
        ResultMetadata,
        ResultScores,
        SearchResult,
    )

    results = [
        SearchResult(
            title="Low score, boosted domain",
            url=_url("https://example.com/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="example.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.5, rank=1),
            source="searxng",
        ),
        SearchResult(
            title="High score, normal domain",
            url=_url("https://other.com/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="other.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.8, rank=2),
            source="searxng",
        ),
    ]

    ranked = ranker.rank(results, "test-123")

    # With 20% boost, 0.5 * 1.2 = 0.6, still less than 0.8
    # So order should be: other.com (0.8), example.com (0.6)
    assert str(ranked[0].url) == "https://other.com/page"
    assert str(ranked[1].url) == "https://example.com/page"


def test_ranker_blocks_domains(settings: Settings) -> None:
    """Test that blocked domains are removed"""
    settings.BS_BLOCKED_DOMAINS = "spam.com"
    ranker = Ranker(settings)

    from butterscout.models.responses import (
        ResultMetadata,
        ResultScores,
        SearchResult,
    )

    results = [
        SearchResult(
            title="Good site",
            url=_url("https://example.com/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="example.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.8, rank=1),
            source="searxng",
        ),
        SearchResult(
            title="Spam site",
            url=_url("https://spam.com/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="spam.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.9, rank=2),
            source="searxng",
        ),
    ]

    ranked = ranker.rank(results, "test-123")

    assert len(ranked) == 1
    assert str(ranked[0].url) == "https://example.com/page"


def test_url_normalization_deterministic() -> None:
    """URL normalization should be deterministic"""
    url = "https://example.com/page?b=2&a=1"
    results = [URLDeduplicator.normalize_url(url) for _ in range(3)]
    assert len(set(results)) == 1, "Normalization must be deterministic"


def test_url_normalization_multi_value_params() -> None:
    """Multi-value params should normalize consistently regardless of order"""
    url1 = "https://example.com?tag=python&tag=programming"
    url2 = "https://example.com?tag=programming&tag=python"
    norm1 = URLDeduplicator.normalize_url(url1)
    norm2 = URLDeduplicator.normalize_url(url2)
    # Should be equal regardless of original order (both sorted)
    assert norm1 == norm2


def test_url_normalization_fragments() -> None:
    """URL normalization should preserve fragments"""
    url = "https://example.com/page#section"
    norm = URLDeduplicator.normalize_url(url)
    assert "#section" in norm
    assert norm == "https://example.com/page#section"


def test_url_normalization_multiple_tracking_params() -> None:
    """All tracking params should be removed"""
    url = "https://example.com/page?utm_source=google&utm_medium=cpc&utm_campaign=test&id=123&fbclid=xyz&gclid=abc"
    norm = URLDeduplicator.normalize_url(url)
    # Only id should remain
    assert "id=123" in norm
    assert "utm_" not in norm
    assert "fbclid" not in norm
    assert "gclid" not in norm


def test_url_normalization_root_path() -> None:
    """Root paths should normalize consistently"""
    url1 = "https://example.com"
    url2 = "https://example.com/"
    norm1 = URLDeduplicator.normalize_url(url1)
    norm2 = URLDeduplicator.normalize_url(url2)
    assert norm1 == norm2


def test_url_normalization_case_insensitive() -> None:
    """URL normalization should be case insensitive"""
    url1 = "https://Example.COM/Page"
    url2 = "https://example.com/page"
    norm1 = URLDeduplicator.normalize_url(url1)
    norm2 = URLDeduplicator.normalize_url(url2)
    assert norm1 == norm2
    assert norm1 == "https://example.com/page"


def test_domain_matching_edge_cases(settings: Settings) -> None:
    """Domain matching should handle www. variations correctly and block subdomains"""
    settings.BS_BLOCKED_DOMAINS = "example.com"
    ranker = Ranker(settings)

    from butterscout.models.responses import ResultMetadata, ResultScores, SearchResult

    # Test that www., subdomains, and the base domain are all blocked
    results = [
        SearchResult(
            title="www version - should be blocked",
            url=_url("https://www.example.com/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="www.example.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.8, rank=1),
            source="searxng",
        ),
        SearchResult(
            title="subdomain version - should be blocked",
            url=_url("https://subdomain.example.com/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="subdomain.example.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.8, rank=2),
            source="searxng",
        ),
        SearchResult(
            title="Different domain - should NOT be blocked",
            url=_url("https://notexample.com/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="notexample.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.8, rank=3),
            source="searxng",
        ),
        SearchResult(
            title="Another different domain - should NOT be blocked",
            url=_url("https://other.org/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="other.org",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.8, rank=4),
            source="searxng",
        ),
    ]

    ranked = ranker.rank(results, "test-123")

    # www.example.com and subdomain.example.com should be blocked
    # notexample.com and other.org should NOT be blocked
    assert len(ranked) == 2
    urls = [str(r.url) for r in ranked]
    assert "https://notexample.com/page" in urls
    assert "https://other.org/page" in urls


def test_score_validation_zero(settings: Settings) -> None:
    """Ranker should handle zero scores gracefully"""
    ranker = Ranker(settings)

    from butterscout.models.responses import ResultMetadata, ResultScores, SearchResult

    result = SearchResult(
        title="Zero score",
        url=_url("https://example.com/page"),
        snippet="",
        content="",
        metadata=ResultMetadata(
            domain="example.com",
            word_count=0,
            extracted_by="none",
            extraction_ok=False,
        ),
        scores=ResultScores(search_score=0.0, rank=1),
        source="searxng",
    )

    score = ranker._calculate_score(result)
    assert score == 0.0


def test_score_validation_negative(settings: Settings) -> None:
    """Ranker should handle negative scores gracefully"""
    ranker = Ranker(settings)

    from butterscout.models.responses import ResultMetadata, ResultScores, SearchResult

    result = SearchResult(
        title="Negative score",
        url=_url("https://example.com/page"),
        snippet="",
        content="",
        metadata=ResultMetadata(
            domain="example.com",
            word_count=0,
            extracted_by="none",
            extraction_ok=False,
        ),
        scores=ResultScores(search_score=-0.5, rank=1),
        source="searxng",
    )

    score = ranker._calculate_score(result)
    assert score == 0.0  # Should be clamped to 0


def test_ranking_stability(settings: Settings) -> None:
    """Ranking should be stable for results with equal scores"""
    ranker = Ranker(settings)

    from butterscout.models.responses import ResultMetadata, ResultScores, SearchResult

    # Create results with identical scores
    results = []
    for i in range(5):
        results.append(
            SearchResult(
                title=f"Result {i}",
                url=_url(f"https://example.com/page{i}"),
                snippet="",
                content="",
                metadata=ResultMetadata(
                    domain="example.com",
                    word_count=0,
                    extracted_by="none",
                    extraction_ok=False,
                ),
                scores=ResultScores(search_score=0.5, rank=i),
                source="searxng",
            )
        )

    ranked = ranker.rank(results, "test-123")

    # With stable sorting, original order should be preserved for equal scores
    for i, result in enumerate(ranked):
        assert result.title == f"Result {i}"
        assert result.scores.rank == i + 1


def test_subdomain_matching_allowed(settings: Settings) -> None:
    """Allowed domain matching should work for subdomains"""
    settings.BS_ALLOWED_DOMAINS = "example.com"
    ranker = Ranker(settings)

    from butterscout.models.responses import ResultMetadata, ResultScores, SearchResult

    results = [
        SearchResult(
            title="Main domain",
            url=_url("https://example.com/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="example.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.5, rank=1),
            source="searxng",
        ),
        SearchResult(
            title="Subdomain",
            url=_url("https://blog.example.com/page"),
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="blog.example.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.5, rank=2),
            source="searxng",
        ),
    ]

    ranker.rank(results, "test-123")

    # Both should get domain boost
    # Check that both have higher scores (boosted from 0.5 to 0.6)
    score1 = ranker._calculate_score(results[0])
    score2 = ranker._calculate_score(results[1])
    assert score1 == pytest.approx(0.6)  # 0.5 * 1.2
    assert score2 == pytest.approx(0.6)  # 0.5 * 1.2


def test_combined_boosts(settings: Settings) -> None:
    """Domain boost and extraction boost should combine"""
    settings.BS_ALLOWED_DOMAINS = "example.com"
    ranker = Ranker(settings)

    from butterscout.models.responses import ResultMetadata, ResultScores, SearchResult

    result = SearchResult(
        title="Boosted domain with extraction",
        url=_url("https://example.com/page"),
        snippet="",
        content="Full content extracted",
        metadata=ResultMetadata(
            domain="example.com",
            word_count=1000,
            extracted_by="trafilatura",
            extraction_ok=True,
        ),
        scores=ResultScores(search_score=0.5, rank=1),
        source="searxng",
    )

    score = ranker._calculate_score(result)
    # 0.5 * 1.2 (domain) * 1.05 (extraction) = 0.63
    assert score == pytest.approx(0.63)


def test_extraction_boost(settings: Settings) -> None:
    """Extraction boost should be applied correctly"""
    ranker = Ranker(settings)

    from butterscout.models.responses import ResultMetadata, ResultScores, SearchResult

    result = SearchResult(
        title="Extracted content",
        url=_url("https://example.com/page"),
        snippet="",
        content="Full content extracted",
        metadata=ResultMetadata(
            domain="example.com",
            word_count=1000,
            extracted_by="trafilatura",
            extraction_ok=True,
        ),
        scores=ResultScores(search_score=0.5, rank=1),
        source="searxng",
    )

    score = ranker._calculate_score(result)
    # 0.5 * 1.05 = 0.525
    assert score == pytest.approx(0.525)
