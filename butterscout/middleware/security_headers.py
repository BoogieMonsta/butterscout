"""Security headers middleware for adding standard security headers to responses."""
from __future__ import annotations

from typing import Awaitable, Callable

from fastapi import Request, Response


async def add_security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Add security headers to all responses.

    Headers added:
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-Frame-Options: Prevents clickjacking attacks
    - X-XSS-Protection: Enables browser XSS protection (legacy support)
    - Referrer-Policy: Controls referrer information
    - Content-Security-Policy: Basic CSP to prevent XSS

    Args:
        request: Incoming request
        call_next: Next middleware/handler in chain

    Returns:
        Response with security headers added
    """
    response = await call_next(request)

    # Prevent MIME type sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"

    # Prevent clickjacking attacks
    response.headers["X-Frame-Options"] = "DENY"

    # Enable XSS protection (legacy, but still useful for older browsers)
    response.headers["X-XSS-Protection"] = "1; mode=block"

    # Control referrer information
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

    # Basic Content Security Policy
    # This is a minimal CSP that allows same-origin resources
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )

    # Note: Strict-Transport-Security (HSTS) should be added by reverse proxy
    # when HTTPS is enabled, not by the application itself

    return response
