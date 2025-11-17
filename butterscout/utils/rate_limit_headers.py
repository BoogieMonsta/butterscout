"""Rate limit HTTP headers generation."""
from typing import Dict, Optional


def generate_rate_limit_headers(
    limit: int,
    remaining: int,
    reset_timestamp: int,
    retry_after: Optional[int] = None,
) -> Dict[str, str]:
    """Generate standard rate limit headers.

    Args:
        limit: Total requests allowed per window
        remaining: Remaining requests in window
        reset_timestamp: Unix timestamp when rate limit resets
        retry_after: Seconds until retry (if rate limited)

    Returns:
        Dictionary of HTTP headers
    """
    headers = {
        "X-RateLimit-Limit": str(limit),
        "X-RateLimit-Remaining": str(max(0, remaining)),
        "X-RateLimit-Reset": str(reset_timestamp),
    }

    if retry_after is not None:
        headers["Retry-After"] = str(retry_after)

    return headers
