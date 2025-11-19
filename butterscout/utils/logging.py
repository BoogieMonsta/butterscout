"""Structured logging configuration using structlog.

This module configures structured JSON logging for Butterscout per Tech Spec requirements.

Required Log Fields (TECH SPEC.md line 166):
- ts: Timestamp (ISO 8601 format, UTC)
- level: Log level (debug, info, warning, error)
- msg: Log message/event name
- request_id: Unique request identifier (UUID)
- client_ip_hash: Hashed client IP (format: "ip:abcd1234")
- api_key_hash: Hashed API key (format: "key:abcd1234") or "none"
- cache_hit: Boolean indicating cache hit/miss
- rate_limited: Boolean indicating if request was rate limited
- searxng_time_ms: Time spent in SearXNG request (milliseconds)
- extraction_time_ms: Time spent in content extraction (milliseconds)
- status_code: HTTP response status code
- error_code: Application error code (if applicable)
- url_count: Number of URLs processed in request

Privacy:
- Client IPs and API keys are hashed using SHA256 (first 8 chars)
- Original values never appear in logs
- Hashing is deterministic for correlation across logs

Output Format:
- JSON with fields above
- One log entry per line
- Timestamp in ISO 8601 UTC format
- Suitable for log aggregation tools (ELK, Splunk, Datadog)
"""

from __future__ import annotations

import logging
import sys
from typing import cast

import structlog


def configure_logging(log_level: str = "info") -> None:
    """Configure structured logging with JSON output.

    Sets up structlog with:
    - JSON renderer for machine-readable output
    - ISO 8601 timestamps in UTC
    - Automatic log level filtering
    - Context variable merging (for request_id, etc.)
    - Exception stack trace formatting

    Args:
        log_level: Log level (debug, info, warning, error)
    """
    # Map string to logging level
    level_map = {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }

    level = level_map.get(log_level.lower(), logging.INFO)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Configure standard logging to use structlog
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get structured logger instance.

    Args:
        name: Optional logger name

    Returns:
        Configured structlog logger instance
    """
    if name:
        return cast(structlog.BoundLogger, structlog.get_logger(name))
    # structlog returns a BoundLogger[Any]; callers expect BoundLogger
    return cast(structlog.BoundLogger, structlog.get_logger())
