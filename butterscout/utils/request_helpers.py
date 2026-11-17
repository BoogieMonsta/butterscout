"""Request helper utilities."""

from __future__ import annotations

from typing import Mapping, Optional

from fastapi import Request


def resolve_api_key(headers: Mapping[str, str]) -> Optional[str]:
    """Return the API key from ``x-api-key`` or, failing that, ``Authorization: Bearer``.

    Bearer support lets MCP clients that only know bearer tokens (e.g. Codex's
    ``--bearer-token-env-var``) authenticate the same way as REST clients.
    """
    key = headers.get("x-api-key")
    if key:
        return key
    authorization = headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def get_client_ip(request: Request) -> str:
    """Extract client IP from request headers or connection."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def get_normalized_endpoint(request: Request) -> str:
    """Get normalized endpoint path for metrics to avoid high cardinality."""
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if isinstance(route_path, str):
        return route_path

    return request.url.path
