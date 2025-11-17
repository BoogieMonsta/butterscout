"""Extraction orchestrator for parallel content extraction."""
from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import structlog

from butterscout.models.internal import ExtractedContent

if TYPE_CHECKING:
    from butterscout.clients.extraction_strategy import ExtractionStrategy
    from butterscout.config import Settings
    from butterscout.models.internal import NormalizedSearchResult

logger = structlog.get_logger()


class ExtractionOrchestrator:
    """Orchestrates parallel content extraction with concurrency control."""

    def __init__(
        self,
        extraction_strategy: ExtractionStrategy,
        settings: Settings,
    ):
        """Initialize the orchestrator.

        Args:
            extraction_strategy: Strategy for extracting content
            settings: Application settings
        """
        self.extraction_strategy = extraction_strategy
        self.settings = settings
        self.max_concurrent = settings.BS_MAX_CONCURRENT_EXTRACTIONS
        self.semaphore = asyncio.Semaphore(self.max_concurrent)

    async def extract_all(
        self,
        search_results: list[NormalizedSearchResult],
        request_id: str,
    ) -> list[ExtractedContent]:
        """Extract content from all search result URLs in parallel.

        Args:
            search_results: List of search results to extract
            request_id: Request ID for logging

        Returns:
            List of ExtractedContent (includes failed extractions)
        """
        start_time = time.perf_counter()

        logger.info(
            "extraction_orchestrator_start",
            request_id=request_id,
            url_count=len(search_results),
            max_concurrent=self.max_concurrent,
        )

        # Create extraction tasks
        tasks = [
            self._extract_with_semaphore(result.url, request_id)
            for result in search_results
        ]

        # Execute all tasks concurrently
        extracted_contents = await asyncio.gather(*tasks, return_exceptions=True)

        # Handle any unexpected exceptions
        results = []
        for idx, content in enumerate(extracted_contents):
            if isinstance(content, Exception):
                logger.error(
                    "extraction_unexpected_error",
                    request_id=request_id,
                    url=search_results[idx].url,
                    error=str(content),
                )
                # Create failed extraction result
                results.append(
                    ExtractedContent(
                        url=search_results[idx].url,
                        content="",
                        word_count=0,
                        extracted_by="none",
                        extraction_ok=False,
                        extraction_time_ms=0,
                        error=str(content),
                    )
                )
            else:
                results.append(content)

        # Calculate metrics
        total_time_ms = int((time.perf_counter() - start_time) * 1000)
        successful = sum(1 for r in results if r.extraction_ok)
        failed = len(results) - successful

        logger.info(
            "extraction_orchestrator_complete",
            request_id=request_id,
            total_urls=len(results),
            successful=successful,
            failed=failed,
            total_time_ms=total_time_ms,
        )

        return results

    async def _extract_with_semaphore(
        self,
        url: str,
        request_id: str,
    ) -> ExtractedContent:
        """Extract single URL with semaphore for concurrency control.

        Args:
            url: URL to extract
            request_id: Request ID

        Returns:
            ExtractedContent (never raises, returns failed result on error)
        """
        async with self.semaphore:
            try:
                return await self.extraction_strategy.extract(url, request_id)
            except Exception as e:
                logger.error(
                    "extraction_orchestrator_error",
                    request_id=request_id,
                    url=url,
                    error=str(e),
                )
                return ExtractedContent(
                    url=url,
                    content="",
                    word_count=0,
                    extracted_by="none",
                    extraction_ok=False,
                    extraction_time_ms=0,
                    error=str(e),
                )
