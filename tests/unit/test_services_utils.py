"""Unit tests for services and utilities."""
import pytest

from butterscout.models.requests import SearchRequest
from butterscout.services.deduplicator import URLDeduplicator
from butterscout.utils.redis_keys import generate_cache_key


@pytest.mark.unit
def test_url_normalization() -> None:
    """Test URL normalization removes tracking params"""
    url1 = "https://WWW.Example.com/page/?utm_source=google&id=123"
    url2 = "https://example.com/page?id=123"

    assert URLDeduplicator.normalize_url(url1) == URLDeduplicator.normalize_url(url2)


@pytest.mark.unit
def test_deduplication() -> None:
    """Test duplicate URLs are removed"""
    from typing import cast

    from pydantic import HttpUrl

    from butterscout.models.internal import NormalizedSearchResult

    def _url(url_str: str) -> HttpUrl:
        return cast(HttpUrl, url_str)

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
    ]

    deduplicated = URLDeduplicator.deduplicate(results, "test-123")

    assert len(deduplicated) == 1
    assert deduplicated[0].title == "Page 1"


@pytest.mark.unit
def test_cache_key_stability() -> None:
    """Cache keys must be identical for same request"""
    req1 = SearchRequest(query="test query", max_results=10)
    req2 = SearchRequest(query="test query", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 == key2


@pytest.mark.unit
def test_cache_key_uniqueness() -> None:
    """Different requests must produce different keys"""
    req1 = SearchRequest(query="query 1", max_results=10)
    req2 = SearchRequest(query="query 2", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2


@pytest.mark.unit
def test_url_normalization_removes_tracking_params() -> None:
    """All tracking parameters should be removed"""
    url = "https://example.com/page?utm_source=google&utm_medium=cpc&id=123&fbclid=xyz"
    normalized = URLDeduplicator.normalize_url(url)

    # Only id should remain
    assert "id=123" in normalized
    assert "utm_" not in normalized
    assert "fbclid" not in normalized


@pytest.mark.unit
def test_url_normalization_case_insensitive() -> None:
    """URL normalization should be case insensitive"""
    url1 = "https://Example.COM/Page"
    url2 = "https://example.com/page"

    norm1 = URLDeduplicator.normalize_url(url1)
    norm2 = URLDeduplicator.normalize_url(url2)

    assert norm1 == norm2
    assert norm1 == "https://example.com/page"


@pytest.mark.unit
def test_url_normalization_removes_www() -> None:
    """www. prefix should be removed"""
    url1 = "https://www.example.com/page"
    url2 = "https://example.com/page"

    norm1 = URLDeduplicator.normalize_url(url1)
    norm2 = URLDeduplicator.normalize_url(url2)

    assert norm1 == norm2
    assert "www." not in norm1


@pytest.mark.unit
def test_url_normalization_trailing_slash() -> None:
    """Trailing slashes should be removed"""
    url1 = "https://example.com/page/"
    url2 = "https://example.com/page"

    norm1 = URLDeduplicator.normalize_url(url1)
    norm2 = URLDeduplicator.normalize_url(url2)

    assert norm1 == norm2
    assert norm1 == "https://example.com/page"


@pytest.mark.unit
def test_url_normalization_query_param_order() -> None:
    """Query parameters should be sorted for consistent normalization"""
    url1 = "https://example.com/page?b=2&a=1"
    url2 = "https://example.com/page?a=1&b=2"

    norm1 = URLDeduplicator.normalize_url(url1)
    norm2 = URLDeduplicator.normalize_url(url2)

    assert norm1 == norm2
    assert norm1 == "https://example.com/page?a=1&b=2"


@pytest.mark.unit
def test_cache_key_format() -> None:
    """Cache keys should have the correct format"""
    req = SearchRequest(query="test", max_results=10)
    key = generate_cache_key(req)

    # Should start with bs:cache: prefix
    assert key.startswith("bs:cache:")

    # Should contain a hash (SHA256 is 64 chars)
    hash_part = key.replace("bs:cache:", "")
    assert len(hash_part) == 64
    assert all(c in "0123456789abcdef" for c in hash_part)
