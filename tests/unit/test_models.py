"""Unit tests for Pydantic models."""

import pytest
from pydantic import ValidationError

from butterscout.models.internal import CacheKey
from butterscout.models.requests import SearchOptions, SearchRequest


@pytest.mark.unit
def test_search_request_validation() -> None:
    """Test request validation rules"""
    # Valid request
    req = SearchRequest(query="test query")
    assert req.query == "test query"
    assert req.max_results == 10  # Default

    # Empty query should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="")

    # Whitespace-only query should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="   ")

    # max_results over limit should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="test", max_results=100)

    # max_results under minimum should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="test", max_results=0)


@pytest.mark.unit
def test_search_options_validation() -> None:
    """Test search options validation"""
    # Too many domains should fail
    with pytest.raises(ValidationError):
        SearchOptions(domains=["example.com"] * 30)

    # Domain length validation (< 3 chars should fail)
    with pytest.raises(ValidationError):
        SearchOptions(domains=["ab"])  # Too short (2 chars)

    # Negative freshness should fail
    with pytest.raises(ValidationError):
        SearchOptions(freshness_days=-1)

    # Valid options should pass
    opts = SearchOptions(
        domains=["example.com", "test.com"],
        exclude_domains=["spam.com"],
        freshness_days=7,
        language="en",
    )
    assert len(opts.domains) == 2
    assert opts.freshness_days == 7


@pytest.mark.unit
def test_search_request_validation_query_whitespace() -> None:
    """Test that whitespace-only queries are rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(query="   ")


@pytest.mark.unit
def test_search_request_validation_query_empty() -> None:
    """Test that empty queries are rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(query="")


@pytest.mark.unit
def test_search_request_domains_length() -> None:
    """Test that > 20 domains are rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(
            query="test",
            options=SearchOptions(domains=["example.com"] * 21),
        )


@pytest.mark.unit
def test_search_request_max_results_cap_upper() -> None:
    """Test that max_results > 25 is rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(query="test", max_results=26)


@pytest.mark.unit
def test_search_request_max_results_cap_lower() -> None:
    """Test that max_results = 0 is rejected."""
    with pytest.raises(ValidationError):
        SearchRequest(query="test", max_results=0)


@pytest.mark.unit
def test_search_request_valid() -> None:
    """Test that valid requests are accepted."""
    request = SearchRequest(
        query="test query",
        max_results=10,
        include_content=True,
    )
    assert request.query == "test query"
    assert request.max_results == 10


@pytest.mark.unit
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


@pytest.mark.unit
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
