"""Unit tests for privacy utilities."""
from __future__ import annotations

from butterscout.utils.privacy import hash_api_key, hash_client_ip, hash_identifier


def test_hash_identifier() -> None:
    """Test basic identifier hashing."""
    result = hash_identifier("test_value")

    # Should return 8-character hash
    assert len(result) == 8
    assert isinstance(result, str)

    # Same input should produce same hash (deterministic)
    result2 = hash_identifier("test_value")
    assert result == result2

    # Different input should produce different hash
    result3 = hash_identifier("different_value")
    assert result != result3


def test_hash_identifier_with_prefix() -> None:
    """Test identifier hashing with prefix."""
    result = hash_identifier("192.168.1.1", prefix="ip:")

    # Should have prefix followed by 8-char hash
    assert result.startswith("ip:")
    assert len(result) == 11  # "ip:" (3) + hash (8)


def test_hash_identifier_none() -> None:
    """Test hashing None values."""
    result = hash_identifier(None)
    assert result == "none"

    result_with_prefix = hash_identifier(None, prefix="ip:")
    assert result_with_prefix == "none"


def test_hash_client_ip() -> None:
    """Test client IP hashing."""
    result = hash_client_ip("192.168.1.100")

    # Should have ip: prefix
    assert result.startswith("ip:")
    assert len(result) == 11

    # None should return "none"
    assert hash_client_ip(None) == "none"


def test_hash_api_key() -> None:
    """Test API key hashing."""
    result = hash_api_key("sk_test_1234567890")

    # Should have key: prefix
    assert result.startswith("key:")
    assert len(result) == 12

    # None should return "none"
    assert hash_api_key(None) == "none"


def test_hash_privacy() -> None:
    """Test that hashes don't reveal original values."""
    ip = "192.168.1.100"
    api_key = "sk_live_secret_key_12345"

    hashed_ip = hash_client_ip(ip)
    hashed_key = hash_api_key(api_key)

    # Original values should not appear in hash
    assert ip not in hashed_ip
    assert api_key not in hashed_key

    # Hashes should be consistent
    assert hashed_ip == hash_client_ip(ip)
    assert hashed_key == hash_api_key(api_key)
