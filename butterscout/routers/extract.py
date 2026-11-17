"""Direct URL extraction endpoint."""

from __future__ import annotations

import asyncio
import ipaddress
import secrets
import socket
from typing import Optional
from urllib.parse import urlparse

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from butterscout.models.exceptions import (
    RateLimitExceededError,
    UnauthorizedError,
    UpstreamProviderError,
)
from butterscout.models.requests import ExtractRequest
from butterscout.models.responses import ExtractMetadata, ExtractResponse
from butterscout.services.rate_limiter import RateLimiter
from butterscout.state import app_state
from butterscout.utils.domain_filter import is_domain_allowed
from butterscout.utils.rate_limit_headers import generate_rate_limit_headers
from butterscout.utils.request_helpers import get_client_ip

logger = structlog.get_logger()

router = APIRouter(tags=["extract"])


@router.post("/extract", response_model=ExtractResponse)
async def extract(
    request_body: ExtractRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
) -> JSONResponse:
    """Extract clean content from one public URL without running a search first."""
    request_id = getattr(request.state, "request_id", "unknown")
    client_ip = get_client_ip(request)
    headers = await _check_access(client_ip, x_api_key, request_id, request)

    url = str(request_body.url)
    await assert_public_url(url)
    if not is_domain_allowed(
        url,
        app_state.settings.allowed_domains_list,
        app_state.settings.blocked_domains_list,
    ):
        raise HTTPException(status_code=403, detail="Domain is not allowed")

    logger.info("extract_request_begin", request_id=request_id, url=url)

    result = await app_state.extraction_strategy.extract(
        request_body.url,
        request_id,
        timeout_ms=min(
            request_body.extract_timeout_ms, app_state.settings.BS_REQUEST_TIMEOUT_MS
        ),
    )

    if not result.extraction_ok or not result.content.strip():
        if hasattr(request.state, "error_code"):
            request.state.error_code = "UPSTREAM_ERROR"
        raise UpstreamProviderError(
            result.error or "Content extraction failed",
            component="extract",
            is_timeout=(result.error or "").lower() == "timeout",
            headers=headers,
        )

    content = result.content.strip()
    truncated = content[: request_body.max_characters]
    domain = urlparse(str(result.url)).hostname or urlparse(url).hostname or ""
    response = ExtractResponse(
        url=request_body.url,
        canonical_url=result.url,
        title=domain or str(result.url),
        content=truncated,
        metadata=ExtractMetadata(
            domain=domain,
            word_count=_word_count(truncated),
            extracted_by=result.extracted_by,  # type: ignore[arg-type]
            extraction_ok=True,
            extraction_error=None,
            extraction_time_ms=result.extraction_time_ms,
        ),
    )

    if hasattr(request.state, "extraction_time_ms"):
        request.state.extraction_time_ms = result.extraction_time_ms
    if hasattr(request.state, "url_count"):
        request.state.url_count = 1

    return JSONResponse(content=response.model_dump(mode="json"), headers=headers)


async def _check_access(
    client_ip: str,
    api_key: Optional[str],
    request_id: str,
    request: Request,
) -> dict[str, str]:
    rate_limiter = RateLimiter(app_state.redis_client, app_state.settings)
    is_allowed, retry_after, remaining, limit, reset_ts = (
        await rate_limiter.check_rate_limit(
            client_ip=client_ip,
            api_key=api_key,
            request_id=request_id,
        )
    )
    if hasattr(request.state, "rate_limited"):
        request.state.rate_limited = not is_allowed

    headers = generate_rate_limit_headers(
        limit=limit,
        remaining=remaining,
        reset_timestamp=reset_ts,
        retry_after=retry_after if not is_allowed else None,
    )
    if not is_allowed:
        if hasattr(request.state, "error_code"):
            request.state.error_code = "RATE_LIMITED"
        raise RateLimitExceededError(
            "Rate limit exceeded", retry_after, headers=headers
        )

    if app_state.settings.BS_API_KEY:
        is_valid = api_key is not None and secrets.compare_digest(
            api_key, app_state.settings.BS_API_KEY
        )
        if not is_valid:
            if hasattr(request.state, "error_code"):
                request.state.error_code = "UNAUTHORIZED"
            raise UnauthorizedError("Missing or invalid API key", headers=headers)

    return headers


async def assert_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400, detail="Only http and https URLs can be extracted"
        )
    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=400, detail="URLs with embedded credentials are not allowed"
        )
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if not hostname or _blocked_hostname(hostname):
        raise HTTPException(
            status_code=400, detail="URL points to a local or private host"
        )

    try:
        ipaddress.ip_address(hostname)
        addresses = [hostname]
    except ValueError:
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
        except socket.gaierror as exc:
            raise HTTPException(
                status_code=400, detail=f"Could not resolve {hostname}"
            ) from exc
        addresses = [str(info[4][0]) for info in infos]

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise HTTPException(
                status_code=400, detail="URL resolves to a local or private address"
            )


def _blocked_hostname(hostname: str) -> bool:
    return (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname.endswith(".local")
        or hostname == "metadata.google.internal"
    )


def _word_count(value: str) -> int:
    return len([part for part in value.split() if part])
