"""Extraction strategy coordinator."""

from __future__ import annotations

from typing import Optional

import structlog
from pydantic import HttpUrl

from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent
from butterscout.services.metrics import metrics_service

logger = structlog.get_logger()


class ExtractionStrategy:
    """Coordinates between Crawl4AI and Trafilatura fallback."""

    def __init__(
        self,
        crawl4ai: Crawl4AIClient,
        trafilatura: Optional[TrafilaturaClient],
        settings: Settings,
    ):
        self.crawl4ai = crawl4ai
        self.trafilatura = trafilatura
        self.fallback_enabled = settings.BS_FALLBACK_ENABLED

    async def extract(
        self,
        url: HttpUrl,
        request_id: str,
        timeout_ms: int | None = None,
    ) -> ExtractedContent:
        """
        Extract content with fallback strategy.

        Try Crawl4AI first, fall back to Trafilatura on failure.

        Args:
            url: URL to extract
            request_id: Request ID for logging

        Returns:
            ExtractedContent with extraction results (always returns, never raises)
        """
        # Try Crawl4AI first
        try:
            result = await self.crawl4ai.extract(url, request_id, timeout_ms=timeout_ms)
            # Record metrics
            metrics_service.record_extraction(
                extractor="crawl4ai",
                duration_seconds=result.extraction_time_ms / 1000.0,
                success=result.extraction_ok,
                reason=None if result.extraction_ok else "error",
            )
            return result

        except Exception as crawl_error:
            logger.warning(
                "crawl4ai_failed_trying_fallback",
                request_id=request_id,
                url=url,
                error=str(crawl_error),
            )

            # Record crawl4ai failure
            is_timeout = isinstance(crawl_error, TimeoutError)
            metrics_service.record_extraction(
                extractor="crawl4ai",
                duration_seconds=0,
                success=False,
                reason="timeout" if is_timeout else "error",
            )

            # Try fallback if enabled
            if self.fallback_enabled and self.trafilatura:
                try:
                    result = await self.trafilatura.extract(url, request_id, timeout_ms=timeout_ms)
                    # Record trafilatura metrics
                    metrics_service.record_extraction(
                        extractor="trafilatura",
                        duration_seconds=result.extraction_time_ms / 1000.0,
                        success=result.extraction_ok,
                        reason=None if result.extraction_ok else "error",
                    )
                    return result
                except Exception as fallback_error:
                    logger.error(
                        "fallback_also_failed",
                        request_id=request_id,
                        url=url,
                        crawl_error=str(crawl_error),
                        fallback_error=str(fallback_error),
                    )
                    # Record trafilatura failure
                    is_timeout = isinstance(fallback_error, TimeoutError)
                    metrics_service.record_extraction(
                        extractor="trafilatura",
                        duration_seconds=0,
                        success=False,
                        reason="timeout" if is_timeout else "error",
                    )
                    # Return failed extraction
                    return ExtractedContent(
                        url=url,
                        content="",
                        word_count=0,
                        extracted_by="none",
                        extraction_ok=False,
                        extraction_time_ms=0,
                        error="Both extractors failed",
                    )
            else:
                # No fallback available, return failed extraction
                return ExtractedContent(
                    url=url,
                    content="",
                    word_count=0,
                    extracted_by="none",
                    extraction_ok=False,
                    extraction_time_ms=0,
                    error=str(crawl_error),
                )
