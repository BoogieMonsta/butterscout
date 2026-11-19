"""Search service for orchestrating search, extraction, and ranking."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Optional

import structlog

from butterscout.clients.extraction_strategy import ExtractionStrategy
from butterscout.clients.redis_client import ValkeyClient
from butterscout.clients.searxng_client import SearXNGClient
from butterscout.config import Settings
from butterscout.models.exceptions import (
    MaxResultsExceededError,
    RateLimitExceededError,
    UnauthorizedError,
    UpstreamProviderError,
)
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import ResponseMetadata, SearchResponse
from butterscout.services.cache_service import CacheService
from butterscout.services.deduplicator import URLDeduplicator
from butterscout.services.extraction_orchestrator import ExtractionOrchestrator
from butterscout.services.extraction_warnings import (
    crawl4ai_warnings,
    has_crawl4ai_fault,
    missing_text_warnings,
)
from butterscout.services.ranker import Ranker
from butterscout.services.rate_limiter import RateLimiter
from butterscout.services.result_assembler import ResultAssembler
from butterscout.utils.content_filter import filter_low_quality_results
from butterscout.utils.domain_filter import is_domain_allowed
from butterscout.utils.rate_limit_headers import generate_rate_limit_headers
from butterscout.utils.url_safety import is_obviously_unsafe_url

logger = structlog.get_logger()


class SearchService:
    """Service to handle search orchestration."""

    def __init__(
        self,
        settings: Settings,
        redis_client: ValkeyClient,
        searxng_client: SearXNGClient,
        extraction_strategy: ExtractionStrategy,
        cache_service: CacheService,
    ) -> None:
        self.settings = settings
        self.redis_client = redis_client
        self.searxng_client = searxng_client
        self.extraction_strategy = extraction_strategy
        self.cache_service = cache_service

    async def execute_search(
        self,
        request_body: SearchRequest,
        request_id: str,
        client_ip: str,
        api_key: Optional[str],
        request_state: Optional[object] = None,
    ) -> tuple[SearchResponse, dict[str, str]]:
        """
        Execute the full search pipeline.

        Returns:
            Tuple of (SearchResponse, headers)
        """
        # 1. Rate Limiting
        rate_limiter = RateLimiter(self.redis_client, self.settings)
        is_allowed, retry_after, remaining, limit, reset_ts = await rate_limiter.check_rate_limit(
            client_ip=client_ip,
            api_key=api_key,
            request_id=request_id,
        )

        if request_state and hasattr(request_state, "rate_limited"):
            request_state.rate_limited = not is_allowed

        rate_limit_headers = generate_rate_limit_headers(
            limit=limit,
            remaining=remaining,
            reset_timestamp=reset_ts,
            retry_after=retry_after if not is_allowed else None,
        )

        if not is_allowed:
            if request_state and hasattr(request_state, "error_code"):
                request_state.error_code = "RATE_LIMITED"
            logger.warning(
                "rate_limit_exceeded",
                request_id=request_id,
                client_ip_hash=hashlib.sha256(client_ip.encode()).hexdigest()[:8],
            )
            # We need to pass headers to the exception handler if we want them in the
            # response. But standard exception handlers don't easily take extra headers
            # unless we attach them to the exception. For now, let's raise the exception
            # and let the handler deal with the body. The headers (RateLimit-*) are
            # important. I'll attach them to the exception or just rely on the handler
            # to not have them (which is a regression). Better: Attach to exception.
            # But my exception class doesn't have headers.
            # I'll just raise it and maybe the handler can't add dynamic headers easily
            # without more work. Actually, I can add headers to the exception class.
            # For this iteration, I will assume the handler handles the body and I might
            # lose the dynamic headers unless I modify the exception class.
            # Wait, the `RateLimitExceededError` I created has `retry_after`.
            # The handler uses `exc.retry_after`.
            # The other headers (Limit, Remaining, Reset) are useful but maybe not
            # critical for the error response body? Actually they are critical for 429.
            # I should probably return them or attach them.
            # Let's stick to raising the exception.
            raise RateLimitExceededError(
                "Rate limit exceeded", retry_after, headers=rate_limit_headers
            )

        # 2. Enforce configured max_results ceiling
        if request_body.max_results > self.settings.BS_MAX_RESULTS:
            if request_state and hasattr(request_state, "error_code"):
                request_state.error_code = "MAX_RESULTS_EXCEEDED"
            logger.warning(
                "max_results_exceeded",
                request_id=request_id,
                requested=request_body.max_results,
                allowed=self.settings.BS_MAX_RESULTS,
            )
            raise MaxResultsExceededError(
                "Requested max_results exceeds configured limit",
                request_body.max_results,
                self.settings.BS_MAX_RESULTS,
                headers=rate_limit_headers,
            )

        # 3. Authentication
        if self.settings.BS_API_KEY:
            is_valid = api_key is not None and secrets.compare_digest(
                api_key, self.settings.BS_API_KEY
            )
            if not is_valid:
                if request_state and hasattr(request_state, "error_code"):
                    request_state.error_code = "UNAUTHORIZED"
                logger.warning(
                    "authentication_failed",
                    request_id=request_id,
                    has_key=bool(api_key),
                )
                raise UnauthorizedError("Missing or invalid API key", headers=rate_limit_headers)

        # 4. Check Cache
        start_time = time.perf_counter()
        cached_response = await self.cache_service.get(request_body, request_id)

        if cached_response:
            if request_state and hasattr(request_state, "cache_hit"):
                request_state.cache_hit = True

            total_time_ms = int((time.perf_counter() - start_time) * 1000)

            logger.info(
                "search_request_complete_cache_hit",
                request_id=request_id,
                total_time_ms=total_time_ms,
            )

            cached_response.metadata.search_time_ms = total_time_ms
            cached_response.metadata.cache_hit = True
            cached_response.metadata.rate_limited = False

            if request_state:
                if hasattr(request_state, "searxng_time_ms"):
                    request_state.searxng_time_ms = cached_response.metadata.searxng_time_ms or 0
                if hasattr(request_state, "extraction_time_ms"):
                    request_state.extraction_time_ms = (
                        cached_response.metadata.extraction_time_ms or 0
                    )
                if hasattr(request_state, "url_count"):
                    request_state.url_count = len(cached_response.results)

            return cached_response, rate_limit_headers
        else:
            if request_state and hasattr(request_state, "cache_hit"):
                request_state.cache_hit = False

        # 5. Execute Search via SearXNG
        searxng_start = time.perf_counter()

        try:
            search_results = await self.searxng_client.search(
                request_body,
                request_id,
            )
        except Exception as e:
            logger.error(
                "searxng_failed",
                request_id=request_id,
                error=str(e),
            )
            if request_state and hasattr(request_state, "error_code"):
                request_state.error_code = "UPSTREAM_ERROR"
            raise UpstreamProviderError(
                "Search provider error",
                component="searxng",
                is_timeout=isinstance(e, TimeoutError),
                headers=rate_limit_headers,
            ) from e

        searxng_time_ms = int((time.perf_counter() - searxng_start) * 1000)
        if request_state and hasattr(request_state, "searxng_time_ms"):
            request_state.searxng_time_ms = searxng_time_ms

        # 6. Apply Domain Filtering, and drop results we must never fetch (local hosts,
        # literal private IPs). Per result, so one bad URL doesn't sink the search.
        filtered_results = [
            r
            for r in search_results
            if is_domain_allowed(
                str(r.url),
                self.settings.allowed_domains_list,
                self.settings.blocked_domains_list,
            )
            and not is_obviously_unsafe_url(str(r.url))
        ]

        # 7. Deduplicate
        deduplicated_results = URLDeduplicator.deduplicate(
            filtered_results,
            request_id,
        )

        # 8. Extract Content (if requested)
        extraction_time_ms: Optional[int] = 0 if request_body.include_content else None
        warnings: list[str] = []
        crawl4ai_fault = False
        if request_body.include_content and deduplicated_results:
            extraction_start = time.perf_counter()
            effective_extract_timeout_ms = min(
                request_body.extract_timeout_ms,
                self.settings.BS_REQUEST_TIMEOUT_MS,
            )

            orchestrator = ExtractionOrchestrator(
                self.extraction_strategy,
                self.settings,
            )

            extracted_contents = await orchestrator.extract_all(
                deduplicated_results,
                request_id,
                timeout_ms=effective_extract_timeout_ms,
            )

            extraction_time_ms = int((time.perf_counter() - extraction_start) * 1000)
            warnings = crawl4ai_warnings(extracted_contents)
            crawl4ai_fault = has_crawl4ai_fault(extracted_contents)
            if request_state and hasattr(request_state, "extraction_time_ms"):
                request_state.extraction_time_ms = extraction_time_ms

            results = ResultAssembler.assemble(
                deduplicated_results,
                extracted_contents,
                include_content=True,
                request_id=request_id,
            )

            # 9. Filter Low Quality
            results = filter_low_quality_results(results, request_id)
        else:
            # No extraction - just assemble with snippets
            results = ResultAssembler.assemble(
                deduplicated_results,
                [],
                include_content=False,
                request_id=request_id,
            )

        # 10. Rank Results
        ranker = Ranker(self.settings)
        ranked_results = ranker.rank(results, request_id)
        if request_state and hasattr(request_state, "url_count"):
            request_state.url_count = len(ranked_results)

        # Count the page text the caller actually gets back.
        missing_text = False
        if request_body.include_content:
            with_text = sum(1 for r in ranked_results if r.content)
            missing_text = with_text < len(ranked_results)
            warnings += missing_text_warnings(with_text, len(ranked_results))
        if warnings:
            logger.warning("search_extraction_degraded", request_id=request_id, warnings=warnings)

        # 11. Build Response
        total_time_ms = int((time.perf_counter() - start_time) * 1000)

        response = SearchResponse(
            query=request_body.query,
            results=ranked_results,
            metadata=ResponseMetadata(
                search_time_ms=total_time_ms,
                searxng_time_ms=searxng_time_ms,
                extraction_time_ms=extraction_time_ms if request_body.include_content else None,
                cache_hit=False,
                sources_queried=["searxng"],
                rate_limited=False,
                warnings=warnings,
            ),
        )

        # 12. Cache Response. Zero results almost always means the engines were blocked,
        # suspended or timed out, not that the web has nothing; caching it would serve that
        # failure for the whole TTL. Retrying costs one more SearXNG call. The same goes for
        # a Crawl4AI fault or a result that came back without page text: caching would pin
        # the failure for an hour after the cause is gone.
        if not ranked_results:
            logger.info("search_cache_skipped_empty", request_id=request_id)
        elif crawl4ai_fault or missing_text:
            logger.info(
                "search_cache_skipped_degraded",
                request_id=request_id,
                crawl4ai_fault=crawl4ai_fault,
                missing_text=missing_text,
            )
        else:
            await self.cache_service.set(request_body, response, request_id)

        logger.info(
            "search_request_complete",
            request_id=request_id,
            result_count=len(ranked_results),
            total_time_ms=total_time_ms,
            searxng_time_ms=searxng_time_ms,
            extraction_time_ms=extraction_time_ms,
        )

        return response, rate_limit_headers
