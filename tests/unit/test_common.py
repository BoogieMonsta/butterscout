"""Unit tests for common utilities."""

from __future__ import annotations

from typing import Any

from butterscout.utils.common import stable_hash


def test_stable_hash_deterministic() -> None:
    """Test that stable_hash produces same output for same input."""
    payload: dict[str, Any] = {"query": "test", "max_results": 10}

    hash1 = stable_hash(payload)
    hash2 = stable_hash(payload)

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex digest length


def test_stable_hash_key_order_independent() -> None:
    """Test that key order doesn't affect hash."""
    payload1 = {"query": "test", "max_results": 10}
    payload2 = {"max_results": 10, "query": "test"}

    assert stable_hash(payload1) == stable_hash(payload2)


def test_stable_hash_different_values() -> None:
    """Test that different values produce different hashes."""
    payload1 = {"query": "test1"}
    payload2 = {"query": "test2"}

    assert stable_hash(payload1) != stable_hash(payload2)


def test_stable_hash_nested_objects() -> None:
    """Test hashing of nested objects."""
    payload: dict[str, Any] = {
        "query": "test",
        "options": {
            "max_results": 10,
            "include_content": True,
        },
    }

    hash_value = stable_hash(payload)
    assert len(hash_value) == 64
    assert stable_hash(payload) == hash_value


def test_stable_hash_empty_dict() -> None:
    """Test hashing empty dictionary."""
    payload: dict[str, Any] = {}
    hash_value = stable_hash(payload)

    assert len(hash_value) == 64
    assert stable_hash({}) == hash_value


def test_stable_hash_with_lists() -> None:
    """Test hashing with list values."""
    payload1 = {"domains": ["example.com", "test.com"]}
    payload2 = {"domains": ["example.com", "test.com"]}
    payload3 = {"domains": ["test.com", "example.com"]}

    # Same order = same hash
    assert stable_hash(payload1) == stable_hash(payload2)

    # Different order = different hash (lists are order-sensitive)
    assert stable_hash(payload1) != stable_hash(payload3)


def test_stable_hash_with_none_values() -> None:
    """Test hashing with None values."""
    payload1 = {"api_key": None, "query": "test"}
    payload2 = {"api_key": None, "query": "test"}

    assert stable_hash(payload1) == stable_hash(payload2)


def test_stable_hash_with_numbers() -> None:
    """Test hashing with different number types."""
    payload_int = {"count": 10}
    payload_float = {"count": 10.0}

    # JSON serialization treats 10 and 10.0 differently
    # so hashes should be different
    assert stable_hash(payload_int) != stable_hash(payload_float)


def test_stable_hash_with_booleans() -> None:
    """Test hashing with boolean values."""
    payload1 = {"enabled": True, "debug": False}
    payload2 = {"enabled": True, "debug": False}
    payload3 = {"enabled": False, "debug": True}

    assert stable_hash(payload1) == stable_hash(payload2)
    assert stable_hash(payload1) != stable_hash(payload3)


def test_stable_hash_unicode() -> None:
    """Test hashing with unicode characters."""
    payload1 = {"query": "test 你好 🔍"}
    payload2 = {"query": "test 你好 🔍"}

    assert stable_hash(payload1) == stable_hash(payload2)
    assert len(stable_hash(payload1)) == 64
