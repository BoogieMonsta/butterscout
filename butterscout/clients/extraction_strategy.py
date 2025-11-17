"""Extraction strategy coordinator."""
from __future__ import annotations

from typing import Optional

import structlog
from pydantic import HttpUrl

from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent

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

    async def extract(self, url: HttpUrl, request_id: str) -> ExtractedContent:
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
            return await self.crawl4ai.extract(url, request_id)

        except Exception as crawl_error:
            logger.warning(
                "crawl4ai_failed_trying_fallback",
                request_id=request_id,
                url=url,
                error=str(crawl_error),
            )

            # Try fallback if enabled
            if self.fallback_enabled and self.trafilatura:
                try:
                    return await self.trafilatura.extract(url, request_id)
                except Exception as fallback_error:
                    logger.error(
                        "fallback_also_failed",
                        request_id=request_id,
                        url=url,
                        crawl_error=str(crawl_error),
                        fallback_error=str(fallback_error),
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
