"""SearXNG client for search orchestration."""
import asyncio
import random
import time
from typing import Optional, cast

import httpx
from pydantic import HttpUrl
import structlog

from butterscout.config import Settings
from butterscout.models.internal import NormalizedSearchResult
from butterscout.models.requests import SearchRequest
from butterscout.services.metrics import metrics_service
from butterscout.utils.domain_filter import is_domain_allowed

logger = structlog.get_logger()


class SearXNGClient:
    """Client for SearXNG meta-search engine."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.BS_SEARXNG_URL.rstrip("/")
        # Per spec: 2s per attempt for SearXNG
        self.timeout = httpx.Timeout(2.0)
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
            ),
        )

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()

    async def search(
        self, request: SearchRequest, request_id: str
    ) -> list[NormalizedSearchResult]:
        """
        Execute search query against SearXNG.

        Args:
            request: Search request with query and options
            request_id: Request ID for logging

        Returns:
            List of normalized search results

        Raises:
            httpx.HTTPError: On network/HTTP errors
            ValueError: On invalid response format
        """
        if not self.client:
            raise RuntimeError("SearXNG client not connected")

        # Build search params
        params: dict[str, str] = {
            "q": request.query,
            "format": "json",
            "safesearch": "0",
        }

        # Add language if specified
        if request.options.language:
            params["language"] = request.options.language

        # Add time range if specified (convert days to SearXNG format)
        if request.options.freshness_days:
            if request.options.freshness_days <= 1:
                params["time_range"] = "day"
            elif request.options.freshness_days <= 7:
                params["time_range"] = "week"
            elif request.options.freshness_days <= 30:
                params["time_range"] = "month"
            else:
                params["time_range"] = "year"

        logger.info(
            "searxng_request",
            request_id=request_id,
            query=request.query,
            language=request.options.language,
        )

        # Track request duration for metrics
        start_time = time.perf_counter()

        # Execute with retry on 5xx/timeout
        attempt = 0
        last_error = None

        while attempt < 2:  # 1 retry = 2 total attempts
            try:
                response = await self.client.get(
                    f"{self.base_url}/search",
                    params=params,
                )
                response.raise_for_status()

                # Parse and normalize results
                try:
                    data = response.json()
                except ValueError as json_err:
                    logger.error(
                        "searxng_invalid_json",
                        request_id=request_id,
                        error=str(json_err),
                        response_text=response.text[:500],
                    )
                    raise ValueError(
                        f"SearXNG returned invalid JSON: {json_err}"
                    ) from json_err

                results = self._normalize_results(
                    data,
                    request.max_results,
                    request.options.domains,
                    request.options.exclude_domains,
                    request_id,
                )

                # Record metrics
                duration_seconds = time.perf_counter() - start_time
                metrics_service.record_searxng_request(duration_seconds)

                logger.info(
                    "searxng_success",
                    request_id=request_id,
                    result_count=len(results),
                    attempt=attempt + 1,
                )

                return results

            except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
                last_error = e
                attempt += 1

                if attempt < 2 and self._should_retry(e):
                    # Jittered backoff: 100-300ms
                    await asyncio.sleep(random.uniform(0.1, 0.3))

                    logger.warning(
                        "searxng_retry",
                        request_id=request_id,
                        attempt=attempt + 1,
                        error=str(e),
                    )
                else:
                    break

        # All retries failed
        logger.error(
            "searxng_failed",
            request_id=request_id,
            error=str(last_error),
            attempts=attempt + 1,
        )
        raise last_error  # type: ignore[misc]

    def _should_retry(self, error: Exception) -> bool:
        """Determine if error is retryable."""
        if isinstance(error, httpx.TimeoutException):
            return True
        if isinstance(error, httpx.HTTPStatusError):
            # Retry on 5xx and 429 errors
            return (
                500 <= error.response.status_code < 600
                or error.response.status_code == 429
            )
        return False

    def _normalize_results(
        self,
        data: dict[str, object],
        max_results: int,
        allowed_domains: list[str],
        blocked_domains: list[str],
        request_id: str,
    ) -> list[NormalizedSearchResult]:
        """
        Normalize SearXNG response to internal format.

        Args:
            data: Raw SearXNG JSON response
            max_results: Maximum number of results to return
            allowed_domains: Whitelist of allowed domains (empty = allow all)
            blocked_domains: Blacklist of blocked domains
            request_id: Request ID for logging

        Returns:
            List of normalized and filtered search results
        """
        results: list[NormalizedSearchResult] = []

        # Note: We fetch more results initially to account for filtering
        # Fetch up to 2x max_results to ensure we have enough after filtering
        raw_results = cast(list[dict[str, object]], data.get("results", []))
        fetch_limit = min(max_results * 2, len(raw_results))
        raw_results = raw_results[:fetch_limit]

        for idx, item in enumerate(raw_results):
            try:
                # Calculate score (SearXNG doesn't always provide scores)
                # Use inverse of position as fallback
                score_value = item.get("score")
                score = float(score_value) if isinstance(score_value, (int, float, str)) else 1.0 / (
                    idx + 1
                )

                # Validate URL scheme (only http/https allowed)
                url_obj = item.get("url")
                if not isinstance(url_obj, str):
                    logger.warning(
                        "searxng_missing_url",
                        request_id=request_id,
                        position=idx,
                    )
                    continue
                url = url_obj  # Required field
                if not url.lower().startswith(("http://", "https://")):
                    logger.warning(
                        "searxng_invalid_url_scheme",
                        url=url,
                        position=idx,
                    )
                    continue

                # Apply domain filtering
                if not is_domain_allowed(url, allowed_domains, blocked_domains):
                    logger.debug(
                        "searxng_domain_filtered",
                        request_id=request_id,
                        url=url,
                        position=idx,
                    )
                    continue

                title_val = item.get("title")
                title = title_val if isinstance(title_val, str) else "No title"

                content_val = item.get("content")
                snippet = content_val if isinstance(content_val, str) else ""
                snippet = snippet[:500]

                result = NormalizedSearchResult(
                    title=title,
                    url=cast(HttpUrl, url),
                    snippet=snippet,
                    score=float(score),
                    source="searxng",
                )
                results.append(result)

                # Stop once we have enough results after filtering
                if len(results) >= max_results:
                    break

            except (KeyError, ValueError) as e:
                logger.warning(
                    "searxng_result_parse_error",
                    error=str(e),
                    item=item,
                )
                continue

        return results

    async def health_check(self) -> bool:
        """
        Check if SearXNG is responsive.

        Returns:
            True if healthy, False otherwise
        """
        if not self.client:
            return False

        try:
            response = await self.client.get(
                f"{self.base_url}/",
                timeout=httpx.Timeout(self.settings.BS_HEALTH_TIMEOUT_MS / 1000.0),
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("searxng_health_check_failed", error=str(e))
            return False
