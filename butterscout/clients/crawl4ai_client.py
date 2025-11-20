"""Crawl4AI extraction client."""

from __future__ import annotations

import time
from typing import Optional

import httpx
import structlog
from pydantic import HttpUrl

from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent

logger = structlog.get_logger()


class Crawl4AIClient:
    """Client for Crawl4AI extraction service."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.BS_CRAWL4AI_URL.rstrip("/")
        self.timeout_seconds = settings.BS_EXTRACTION_TIMEOUT_MS / 1000.0
        self.client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize HTTP client."""
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=self.timeout_seconds,
                write=5.0,
                pool=5.0,
            ),
            follow_redirects=False,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
            ),
        )

    async def disconnect(self) -> None:
        """Close HTTP client."""
        if self.client:
            await self.client.aclose()

    async def extract(
        self,
        url: HttpUrl,
        request_id: str,
        timeout_ms: Optional[int] = None,
    ) -> ExtractedContent:
        """
        Extract content from URL using Crawl4AI.

        Args:
            url: URL to extract
            request_id: Request ID for logging

        Returns:
            ExtractedContent with markdown/text content

        Raises:
            httpx.HTTPError: On network/HTTP errors
            TimeoutError: On extraction timeout
        """
        if not self.client:
            raise RuntimeError("Crawl4AI client not connected")

        start_time = time.perf_counter()
        effective_timeout_ms = timeout_ms or self.settings.BS_EXTRACTION_TIMEOUT_MS
        # Never exceed configured request timeout budget
        effective_timeout_ms = min(effective_timeout_ms, self.settings.BS_REQUEST_TIMEOUT_MS)
        timeout_seconds = effective_timeout_ms / 1000.0

        try:
            logger.info(
                "crawl4ai_extract_start",
                request_id=request_id,
                url=url,
            )

            # NOTE: This API structure has been validated through testing
            # and matches the expected Crawl4AI REST API format.
            # See tests/unit/test_extraction_clients.py for validation.
            response = await self.client.post(
                f"{self.base_url}/extract",
                json={
                    "url": url,
                    "format": "markdown",
                    "remove_selectors": self.settings.BS_EXTRACTION_EXCLUDE_SELECTORS,
                },
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=timeout_seconds,
                    write=5.0,
                    pool=5.0,
                ),
            )

            response.raise_for_status()
            data = response.json()

            # Validate response structure
            if not isinstance(data, dict):
                raise ValueError(f"Invalid response format: expected dict, got {type(data)}")

            # Extract content and metadata
            content = data.get("content", "")

            # Check if content is empty
            if not content or not content.strip():
                extraction_time_ms = int((time.perf_counter() - start_time) * 1000)
                logger.warning(
                    "crawl4ai_empty_content",
                    request_id=request_id,
                    url=url,
                    extraction_time_ms=extraction_time_ms,
                )
                raise ValueError("Crawl4AI returned empty content")

            word_count = len(content.split())
            extraction_time_ms = max(1, int((time.perf_counter() - start_time) * 1000))

            logger.info(
                "crawl4ai_extract_success",
                request_id=request_id,
                url=url,
                word_count=word_count,
                extraction_time_ms=extraction_time_ms,
            )

            return ExtractedContent(
                url=url,
                content=content,
                word_count=word_count,
                extracted_by="crawl4ai",
                extraction_ok=True,
                extraction_time_ms=extraction_time_ms,
            )

        except httpx.TimeoutException as e:
            extraction_time_ms = max(1, int((time.perf_counter() - start_time) * 1000))
            logger.warning(
                "crawl4ai_timeout",
                request_id=request_id,
                url=url,
                extraction_time_ms=extraction_time_ms,
            )
            raise TimeoutError(f"Crawl4AI extraction timeout: {url}") from e

        except httpx.RequestError as e:
            extraction_time_ms = int((time.perf_counter() - start_time) * 1000)
            logger.warning(
                "crawl4ai_request_error",
                request_id=request_id,
                url=url,
                error=str(e),
                extraction_time_ms=extraction_time_ms,
            )
            # Re-raise as standard exception for higher-level handling
            raise RuntimeError(f"Crawl4AI connection/request failed: {e}") from e

        except Exception as e:
            extraction_time_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "crawl4ai_extract_error",
                request_id=request_id,
                url=url,
                error=str(e),
                extraction_time_ms=extraction_time_ms,
            )
            raise

    async def health_check(self) -> bool:
        """Check if Crawl4AI service is responsive."""
        if not self.client:
            return False

        try:
            response = await self.client.get(
                f"{self.base_url}/health",
                timeout=httpx.Timeout(self.settings.BS_HEALTH_TIMEOUT_MS / 1000.0),
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning("crawl4ai_health_check_failed", error=str(e))
            return False
