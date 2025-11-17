"""Search endpoint implementation."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from butterscout.models.requests import SearchRequest
from butterscout.models.responses import ResponseMetadata, SearchResponse
from butterscout.services.cache_service import CacheService
from butterscout.services.deduplicator import URLDeduplicator
from butterscout.services.extraction_orchestrator import ExtractionOrchestrator
from butterscout.services.rate_limiter import RateLimiter
from butterscout.services.ranker import Ranker
from butterscout.services.result_assembler import ResultAssembler
from butterscout.utils.content_filter import filter_low_quality_results
from butterscout.utils.domain_filter import is_domain_allowed
from butterscout.utils.rate_limit_headers import generate_rate_limit_headers
from butterscout.state import app_state

logger = structlog.get_logger()

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    request_body: SearchRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
) -> JSONResponse:
    """
    Main search endpoint

    Execute web search with content extraction.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    start_time = time.perf_counter()

    logger.info(
        "search_request_begin",
        request_id=request_id,
        query=request_body.query,
        max_results=request_body.max_results,
        include_content=request_body.include_content,
    )

    # 1. Rate Limiting (applied before auth to include headers on 401)
    client_ip = request.client.host if request.client else "unknown"
    rate_limiter = RateLimiter(app_state.redis_client, app_state.settings)
    is_allowed, retry_after, remaining, limit, reset_ts = await rate_limiter.check_rate_limit(
        client_ip=client_ip,
        api_key=x_api_key,
        request_id=request_id,
    )

    rate_limit_headers = generate_rate_limit_headers(
        limit=limit,
        remaining=remaining,
        reset_timestamp=reset_ts,
        retry_after=retry_after if not is_allowed else None,
    )

    if not is_allowed:
        logger.warning(
            "rate_limit_exceeded",
            request_id=request_id,
            client_ip_hash=hashlib.sha256(client_ip.encode()).hexdigest()[:8],
        )
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "code": "RATE_LIMITED",
                    "message": "Rate limit exceeded",
                    "details": {
                        "retry_after_ms": retry_after * 1000 if retry_after else None,
                    },
                },
                "metadata": {
                    "request_id": request_id,
                    "api_version": "v1",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            },
            headers=rate_limit_headers,
        )

    # 2. Authentication (if required)
    if app_state.settings.BS_API_KEY:
        if not x_api_key or x_api_key != app_state.settings.BS_API_KEY:
            logger.warning(
                "authentication_failed",
                request_id=request_id,
                has_key=bool(x_api_key),
            )
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Missing or invalid API key",
                        "details": {},
                    },
                    "metadata": {
                        "request_id": request_id,
                        "api_version": "v1",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                },
                headers={
                    **rate_limit_headers,
                    "WWW-Authenticate": 'ApiKey realm="Butterscout API"',
                },
            )

    # 3. Check Cache
    cache_service = CacheService(app_state.redis_client, app_state.settings)
    cached_response = await cache_service.get(request_body, request_id)

    if cached_response:
        total_time_ms = int((time.perf_counter() - start_time) * 1000)

        logger.info(
            "search_request_complete_cache_hit",
            request_id=request_id,
            total_time_ms=total_time_ms,
        )

        cached_response.metadata.cache_hit = True
        cached_response.metadata.search_time_ms = total_time_ms
        cached_response.metadata.rate_limited = False

        return JSONResponse(
            content=cached_response.model_dump(mode="json"),
            headers=rate_limit_headers,
        )

    # 4. Execute Search via SearXNG
    searxng_start = time.perf_counter()

    try:
        search_results = await app_state.searxng_client.search(
            request_body,
            request_id,
        )
    except Exception as e:
        logger.error(
            "searxng_failed",
            request_id=request_id,
            error=str(e),
        )
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": "UPSTREAM_ERROR",
                    "message": "Search provider error",
                    "details": {
                        "component": "searxng",
                        "timeout": isinstance(e, TimeoutError),
                    },
                },
                "metadata": {
                    "request_id": request_id,
                    "api_version": "v1",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            },
            headers=rate_limit_headers,
        )

    searxng_time_ms = int((time.perf_counter() - searxng_start) * 1000)

    # 5. Apply Domain Filtering
    filtered_results = [
        r
        for r in search_results
        if is_domain_allowed(
            str(r.url),
            app_state.settings.allowed_domains_list,
            app_state.settings.blocked_domains_list,
        )
    ]

    # 6. Deduplicate
    deduplicated_results = URLDeduplicator.deduplicate(
        filtered_results,
        request_id,
    )

    # 7. Extract Content (if requested)
    extraction_time_ms: Optional[int] = 0 if request_body.include_content else None
    if request_body.include_content and deduplicated_results:
        extraction_start = time.perf_counter()

        orchestrator = ExtractionOrchestrator(
            app_state.extraction_strategy,
            app_state.settings,
        )

        extracted_contents = await orchestrator.extract_all(
            deduplicated_results,
            request_id,
        )

        extraction_time_ms = int((time.perf_counter() - extraction_start) * 1000)

        results = ResultAssembler.assemble(
            deduplicated_results,
            extracted_contents,
            include_content=True,
            request_id=request_id,
        )

        # 8. Filter Low Quality
        results = filter_low_quality_results(results, request_id)
    else:
        # No extraction - just assemble with snippets
        results = ResultAssembler.assemble(
            deduplicated_results,
            [],
            include_content=False,
            request_id=request_id,
        )

    # 9. Rank Results
    ranker = Ranker(app_state.settings)
    ranked_results = ranker.rank(results, request_id)

    # 10. Build Response
    total_time_ms = int((time.perf_counter() - start_time) * 1000)

    response = SearchResponse(
        query=request_body.query,
        results=ranked_results,
        metadata=ResponseMetadata(
            search_time_ms=total_time_ms,
            searxng_time_ms=searxng_time_ms,
            extraction_time_ms=extraction_time_ms
            if request_body.include_content
            else None,
            cache_hit=False,
            sources_queried=["searxng"],
            rate_limited=False,
        ),
    )

    # 11. Cache Response
    await cache_service.set(request_body, response, request_id)

    logger.info(
        "search_request_complete",
        request_id=request_id,
        result_count=len(ranked_results),
        total_time_ms=total_time_ms,
        searxng_time_ms=searxng_time_ms,
        extraction_time_ms=extraction_time_ms,
    )

    return JSONResponse(
        content=response.model_dump(mode="json"),
        headers=rate_limit_headers,
    )
