"""Trafilatura fallback extraction client."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import httpx
import structlog
import trafilatura
from pydantic import HttpUrl

from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent

logger = structlog.get_logger()


class TrafilaturaClient:
    """Fallback content extractor using Trafilatura library."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.timeout_seconds = settings.BS_FALLBACK_TIMEOUT_MS / 1000.0
        self.max_workers = settings.BS_FALLBACK_MAX_WORKERS
        self.executor: Optional[ThreadPoolExecutor] = None
        self.http_client: Optional[httpx.AsyncClient] = None

    async def connect(self) -> None:
        """Initialize thread pool and HTTP client."""
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="trafilatura",
        )
        self.http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout_seconds),
            follow_redirects=True,
        )

    async def disconnect(self) -> None:
        """Shutdown thread pool and close HTTP client."""
        if self.executor:
            self.executor.shutdown(wait=True)
        if self.http_client:
            await self.http_client.aclose()

    async def extract(self, url: HttpUrl, request_id: str) -> ExtractedContent:
        """
        Extract content using Trafilatura (fallback extractor).

        Args:
            url: URL to extract
            request_id: Request ID for logging

        Returns:
            ExtractedContent with extracted text

        Raises:
            Exception: On extraction failures
        """
        if not self.executor or not self.http_client:
            raise RuntimeError("Trafilatura client not connected")

        start_time = time.perf_counter()

        try:
            logger.info(
                "trafilatura_extract_start",
                request_id=request_id,
                url=url,
            )

            # Fetch HTML
            response = await self.http_client.get(str(url))
            response.raise_for_status()
            html = response.text

            # Run Trafilatura in thread pool (it's CPU-bound) with timeout
            loop = asyncio.get_event_loop()
            try:
                content = await asyncio.wait_for(
                    loop.run_in_executor(
                        self.executor,
                        self._extract_sync,
                        html,
                    ),
                    timeout=self.timeout_seconds,
                )
            except asyncio.TimeoutError as e:
                raise TimeoutError(f"Trafilatura extraction timeout: {url}") from e

            if not content or not content.strip():
                raise ValueError("Trafilatura returned empty content")

            word_count = len(content.split())
            extraction_time_ms = int((time.perf_counter() - start_time) * 1000)

            logger.info(
                "trafilatura_extract_success",
                request_id=request_id,
                url=url,
                word_count=word_count,
                extraction_time_ms=extraction_time_ms,
            )

            return ExtractedContent(
                url=url,
                content=content,
                word_count=word_count,
                extracted_by="trafilatura",
                extraction_ok=True,
                extraction_time_ms=extraction_time_ms,
            )

        except Exception as e:
            extraction_time_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(
                "trafilatura_extract_error",
                request_id=request_id,
                url=url,
                error=str(e),
                extraction_time_ms=extraction_time_ms,
            )
            raise

    def _extract_sync(self, html: str) -> Optional[str]:
        """
        Synchronous extraction with Trafilatura.

        Runs in thread pool executor.
        """
        return trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
            output_format="txt",
        )
