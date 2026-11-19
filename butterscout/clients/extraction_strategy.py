"""Extraction strategy coordinator."""

from __future__ import annotations

from typing import Optional

import structlog
from pydantic import HttpUrl

from butterscout.clients.crawl4ai_client import (
    Crawl4AIBusyError,
    Crawl4AIClient,
    Crawl4AIUnavailableError,
    MarkdownFilter,
)
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import Settings
from butterscout.models.internal import Crawl4AIFailure, ExtractedContent
from butterscout.services.metrics import metrics_service

logger = structlog.get_logger()


def crawl4ai_failure(error: Exception) -> Crawl4AIFailure:
    """Whether Crawl4AI failed on this page, was at capacity, or is failing as a service."""
    if isinstance(error, Crawl4AIUnavailableError):
        return error.reason
    if isinstance(error, Crawl4AIBusyError):
        return "busy"
    return "page"


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
        markdown_filter: MarkdownFilter = "raw",
    ) -> ExtractedContent:
        """
        Extract content with fallback strategy.

        Try Crawl4AI first, fall back to Trafilatura on failure. When Crawl4AI fails,
        the result says why in ``crawl4ai_failure``, whichever extractor (if any)
        produced the content.

        Args:
            url: URL to extract
            request_id: Request ID for logging
            markdown_filter: Crawl4AI markdown mode; Trafilatura ignores it

        Returns:
            ExtractedContent with extraction results (always returns, never raises)
        """
        try:
            result = await self.crawl4ai.extract(
                url, request_id, timeout_ms=timeout_ms, markdown_filter=markdown_filter
            )
            metrics_service.record_extraction(
                extractor="crawl4ai",
                duration_seconds=result.extraction_time_ms / 1000.0,
                success=True,
            )
            return result

        except Exception as crawl_error:
            failure = crawl4ai_failure(crawl_error)
            logger.warning(
                "crawl4ai_failed_trying_fallback",
                request_id=request_id,
                url=url,
                failure=failure,
                error=str(crawl_error),
            )
            if failure == "page":
                reason = "timeout" if isinstance(crawl_error, TimeoutError) else "error"
            else:
                reason = failure
            metrics_service.record_extraction(
                extractor="crawl4ai", duration_seconds=0, success=False, reason=reason
            )

            if not (self.fallback_enabled and self.trafilatura):
                return _failed(url, str(crawl_error), failure)

            try:
                result = await self.trafilatura.extract(url, request_id, timeout_ms=timeout_ms)
            except Exception as fallback_error:
                logger.error(
                    "fallback_also_failed",
                    request_id=request_id,
                    url=url,
                    crawl_error=str(crawl_error),
                    fallback_error=str(fallback_error),
                )
                is_timeout = isinstance(fallback_error, TimeoutError)
                metrics_service.record_extraction(
                    extractor="trafilatura",
                    duration_seconds=0,
                    success=False,
                    reason="timeout" if is_timeout else "error",
                )
                return _failed(url, "Both extractors failed", failure)

            metrics_service.record_extraction(
                extractor="trafilatura",
                duration_seconds=result.extraction_time_ms / 1000.0,
                success=result.extraction_ok,
                reason=None if result.extraction_ok else "error",
            )
            return result.model_copy(update={"crawl4ai_failure": failure})


def _failed(url: HttpUrl, error: str, failure: Crawl4AIFailure) -> ExtractedContent:
    return ExtractedContent(
        url=url,
        content="",
        word_count=0,
        extracted_by="none",
        extraction_ok=False,
        extraction_time_ms=0,
        error=error,
        crawl4ai_failure=failure,
    )
