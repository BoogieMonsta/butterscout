import pytest
from pydantic import ValidationError

from butterscout.models.internal import CacheKey
from butterscout.models.requests import SearchOptions, SearchRequest


def test_search_request_validation_query_whitespace() -> None:
    """Test that whitespace-only queries are rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(query="   ")


def test_search_request_validation_query_empty() -> None:
    """Test that empty queries are rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(query="")


def test_search_request_domains_length() -> None:
    """Test that > 20 domains are rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(
            query="test",
            options=SearchOptions(domains=["example.com"] * 21),
        )


def test_search_request_max_results_cap_upper() -> None:
    """Test that max_results > 25 is rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(query="test", max_results=26)


def test_search_request_max_results_cap_lower() -> None:
    """Test that max_results = 0 is rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(query="test", max_results=0)


def test_search_request_valid() -> None:
    """Test that valid requests are accepted."""
    request = SearchRequest(
        query="test query",
        max_results=10,
        include_content=True,
    )
    assert request.query == "test query"
    assert request.max_results == 10


def test_cache_key_stable() -> None:
    """Test that cache keys are stable for same inputs."""
    key1 = CacheKey(
        query="test query",
        max_results=10,
        include_content=True,
        options_hash="abc123",
    ).to_redis_key()
    key2 = CacheKey(
        query="test query",
        max_results=10,
        include_content=True,
        options_hash="abc123",
    ).to_redis_key()

    assert key1 == key2


def test_cache_key_different_for_different_inputs() -> None:
    """Test that cache keys differ for different inputs."""
    key1 = CacheKey(
        query="test query",
        max_results=10,
        include_content=True,
        options_hash="abc123",
    ).to_redis_key()
    key2 = CacheKey(
        query="different query",
        max_results=10,
        include_content=True,
        options_hash="abc123",
    ).to_redis_key()

    assert key1 != key2
