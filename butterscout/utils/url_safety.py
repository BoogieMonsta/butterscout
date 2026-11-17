"""Cheap URL safety checks that need no network access."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def blocked_hostname(hostname: str) -> bool:
    """Hostnames that always point at the local machine or cloud metadata."""
    return (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname == "metadata.google.internal"
    )


def is_obviously_unsafe_url(url: str) -> bool:
    """True for URLs that are unsafe to fetch without resolving DNS.

    Catches non-http(s) schemes, embedded credentials, local hostnames and literal
    non-global IPs. It does NOT catch hostnames that resolve to private addresses or
    redirects to them; that needs enforcement at the fetch itself.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return True
    if parsed.username or parsed.password:
        return True
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or blocked_hostname(hostname):
        return True
    try:
        return not ipaddress.ip_address(hostname).is_global
    except ValueError:
        return False
