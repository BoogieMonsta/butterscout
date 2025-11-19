"""Unit tests for Redis key generation utilities."""

from __future__ import annotations

from butterscout.models.requests import SearchOptions, SearchRequest
from butterscout.utils.redis_keys import (
    generate_cache_key,
    generate_global_rate_limit_key,
    generate_rate_limit_key,
)


def test_cache_key_stability() -> None:
    """Cache keys must be identical for same request."""
    req1 = SearchRequest(query="test query", max_results=10)
    req2 = SearchRequest(query="test query", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 == key2


def test_cache_key_uniqueness() -> None:
    """Different requests must produce different keys."""
    req1 = SearchRequest(query="query 1", max_results=10)
    req2 = SearchRequest(query="query 2", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2


def test_cache_key_format() -> None:
    """Cache keys should follow naming convention."""
    req = SearchRequest(query="test", max_results=10)
    key = generate_cache_key(req)

    assert key.startswith("bs:cache:")
    # SHA256 hash is 64 characters hex
    assert len(key) == len("bs:cache:") + 64


def test_cache_key_case_normalization() -> None:
    """Cache keys should normalize query case."""
    req1 = SearchRequest(query="Test Query", max_results=10)
    req2 = SearchRequest(query="test query", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    # Keys should be the same because query is normalized to lowercase
    assert key1 == key2


def test_cache_key_whitespace_normalization() -> None:
    """Cache keys should normalize whitespace."""
    req1 = SearchRequest(query="  test query  ", max_results=10)
    req2 = SearchRequest(query="test query", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    # Keys should be the same because query whitespace is stripped
    assert key1 == key2


def test_cache_key_different_max_results() -> None:
    """Different max_results should produce different keys."""
    req1 = SearchRequest(query="test", max_results=5)
    req2 = SearchRequest(query="test", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2


def test_cache_key_different_include_content() -> None:
    """Different include_content should produce different keys."""
    req1 = SearchRequest(query="test", max_results=10, include_content=True)
    req2 = SearchRequest(query="test", max_results=10, include_content=False)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2


def test_cache_key_domain_ordering() -> None:
    """Cache keys should be stable regardless of domain order."""
    options1 = SearchOptions(domains=["example.com", "test.com"])
    options2 = SearchOptions(domains=["test.com", "example.com"])

    req1 = SearchRequest(query="test", max_results=10, options=options1)
    req2 = SearchRequest(query="test", max_results=10, options=options2)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    # Keys should be the same because domains are sorted
    assert key1 == key2


def test_cache_key_different_domains() -> None:
    """Different domains should produce different keys."""
    options1 = SearchOptions(domains=["example.com"])
    options2 = SearchOptions(domains=["test.com"])

    req1 = SearchRequest(query="test", max_results=10, options=options1)
    req2 = SearchRequest(query="test", max_results=10, options=options2)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2


def test_cache_key_exclude_domains() -> None:
    """Different exclude_domains should produce different keys."""
    options1 = SearchOptions(exclude_domains=["spam.com"])
    options2 = SearchOptions(exclude_domains=["ads.com"])

    req1 = SearchRequest(query="test", max_results=10, options=options1)
    req2 = SearchRequest(query="test", max_results=10, options=options2)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2


def test_cache_key_freshness_days() -> None:
    """Different freshness_days should produce different keys."""
    options1 = SearchOptions(freshness_days=7)
    options2 = SearchOptions(freshness_days=30)

    req1 = SearchRequest(query="test", max_results=10, options=options1)
    req2 = SearchRequest(query="test", max_results=10, options=options2)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2


def test_cache_key_language() -> None:
    """Different language should produce different keys."""
    options1 = SearchOptions(language="en")
    options2 = SearchOptions(language="es")

    req1 = SearchRequest(query="test", max_results=10, options=options1)
    req2 = SearchRequest(query="test", max_results=10, options=options2)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2


def test_rate_limit_key_format() -> None:
    """Rate limit keys should follow naming convention."""
    key = generate_rate_limit_key("192.168.1.1", "ip")
    assert key.startswith("bs:ratelimit:ip:")

    # Hash is truncated to 16 characters
    hash_part = key.split(":")[-1]
    assert len(hash_part) == 16


def test_rate_limit_key_ip_type() -> None:
    """Rate limit keys for IPs should use ip type."""
    key = generate_rate_limit_key("192.168.1.1", "ip")
    assert "bs:ratelimit:ip:" in key


def test_rate_limit_key_api_key_type() -> None:
    """Rate limit keys for API keys should use api_key type."""
    key = generate_rate_limit_key("sk_test_123", "api_key")
    assert "bs:ratelimit:api_key:" in key


def test_rate_limit_key_stability() -> None:
    """Same identifier should produce same rate limit key."""
    key1 = generate_rate_limit_key("192.168.1.1", "ip")
    key2 = generate_rate_limit_key("192.168.1.1", "ip")

    assert key1 == key2


def test_rate_limit_key_uniqueness() -> None:
    """Different identifiers should produce different keys."""
    key1 = generate_rate_limit_key("192.168.1.1", "ip")
    key2 = generate_rate_limit_key("192.168.1.2", "ip")

    assert key1 != key2


def test_rate_limit_key_type_affects_key() -> None:
    """Different key types should produce different keys for same identifier."""
    key1 = generate_rate_limit_key("test123", "ip")
    key2 = generate_rate_limit_key("test123", "api_key")

    assert key1 != key2


def test_global_rate_limit_key_format() -> None:
    """Global rate limit key should follow naming convention."""
    key = generate_global_rate_limit_key()
    assert key == "bs:ratelimit:global"


def test_global_rate_limit_key_stability() -> None:
    """Global rate limit key should always be the same."""
    key1 = generate_global_rate_limit_key()
    key2 = generate_global_rate_limit_key()

    assert key1 == key2
    assert key1 == "bs:ratelimit:global"


def test_global_rate_limit_key_namespaced_by_limit() -> None:
    """Global rate limit key can be namespaced by limit to avoid collisions."""
    key = generate_global_rate_limit_key(5)
    assert key == "bs:ratelimit:global:5"
    assert key != generate_global_rate_limit_key()
