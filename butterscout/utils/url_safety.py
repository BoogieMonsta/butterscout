"""Cheap URL safety checks that need no network access."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_V4_COMPATIBLE = ipaddress.ip_network("::/96")


def is_public_address(address: str) -> bool:
    """True only for a public unicast address.

    `is_global` alone is not enough: Python counts multicast, deprecated site-local IPv6,
    and the IPv4 inside NAT64 or IPv4-compatible IPv6 as global, so `64:ff9b::a00:1`
    (10.0.0.1) would pass.
    """
    ip = ipaddress.ip_address(address)
    forms: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = [ip]
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.is_site_local:
            return False
        if ip.ipv4_mapped is not None:
            forms.append(ip.ipv4_mapped)
        elif ip in _NAT64 or ip in _V4_COMPATIBLE:
            forms.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return all(form.is_global and not form.is_multicast for form in forms)


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
    non-public IPs. It does not resolve DNS: both extractors refuse local and private
    addresses when they connect (see butterscout/clients/public_only.py).
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
        return not is_public_address(hostname)
    except ValueError:
        return False
