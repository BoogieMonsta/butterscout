"""Privacy utilities for hashing sensitive data in logs."""

from __future__ import annotations

import hashlib


def hash_identifier(value: str | None, prefix: str = "") -> str:
    """Hash a sensitive identifier for logging.

    Creates a SHA256 hash of the value and returns the first 8 characters
    for compact log representation while maintaining privacy.

    Args:
        value: Value to hash (IP address, API key, etc.)
        prefix: Optional prefix for the hash (e.g., "ip:", "key:")

    Returns:
        Hashed value (8 chars) or "none" if value is None
    """
    if not value:
        return "none"

    # Use SHA256 for hashing
    hash_obj = hashlib.sha256(value.encode("utf-8"))
    hash_hex = hash_obj.hexdigest()

    # Return first 8 characters with optional prefix
    short_hash = hash_hex[:8]
    return f"{prefix}{short_hash}" if prefix else short_hash


def hash_client_ip(ip: str | None) -> str:
    """Hash client IP address for privacy-safe logging.

    Args:
        ip: Client IP address

    Returns:
        Hashed IP (format: "ip:abcd1234") or "none"
    """
    return hash_identifier(ip, prefix="ip:")


def hash_api_key(api_key: str | None) -> str:
    """Hash API key for privacy-safe logging.

    Args:
        api_key: API key value

    Returns:
        Hashed API key (format: "key:abcd1234") or "none"
    """
    return hash_identifier(api_key, prefix="key:")
