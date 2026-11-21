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

from butterscout.clients.public_only import public_only_transport
from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent

logger = structlog.get_logger()

# Memory bound on one fetched page. Real search results measured up to 1.5 MB.
MAX_BODY_BYTES = 5_000_000
MAX_REDIRECTS = 5


class TrafilaturaClient:
    """Fallback content extractor using Trafilatura library.

    Each extraction has one deadline covering admission, fetch and parse. Parsing runs in
    threads, which cannot be cancelled, and parse time depends on page structure (1 MB of
    tiny elements took ~6 s), so admission is bounded instead: a fixed number of
    extractions hold a permit, and a parse keeps its permit until its thread really ends,
    even after its caller stopped waiting.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.max_workers = settings.BS_FALLBACK_MAX_WORKERS
        self.executor: Optional[ThreadPoolExecutor] = None
        self.http_client: Optional[httpx.AsyncClient] = None
        # Twice the parse threads, so fetches can overlap parses.
        self._permits = asyncio.Semaphore(2 * self.max_workers)

    async def connect(self) -> None:
        """Initialize thread pool and HTTP client."""
        # Compressed bodies are decoded before any size check could stop them (a 28 KiB
        # gzip chunk expanded to 8 MiB), so ask for none and refuse any.
        headers = {"Accept-Encoding": "identity"}
        if self.settings.BS_FALLBACK_USER_AGENT:
            headers["User-Agent"] = self.settings.BS_FALLBACK_USER_AGENT
        self.executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix="trafilatura",
        )
        self.http_client = httpx.AsyncClient(
            # No HTTPX phase timers: extract() owns the clock, and a phase timer firing first
            # would turn the timeout into a generic fetch failure.
            timeout=None,
            follow_redirects=False,
            headers=headers,
            # Every connection, redirects included, goes only to public addresses. With an
            # explicit transport HTTPX also ignores proxy environment variables.
            transport=public_only_transport(),
        )

    async def disconnect(self) -> None:
        """Shutdown thread pool and close HTTP client."""
        if self.http_client:
            await self.http_client.aclose()  # first: running parses already have their HTML
        if self.executor:
            # Joining threads blocks; a running parse may take seconds.
            await asyncio.to_thread(self.executor.shutdown, wait=True, cancel_futures=True)

    def budget_ms(self, timeout_ms: Optional[int]) -> int:
        """The fallback's own budget: its setting, never more than the caller asked for."""
        budget = min(self.settings.BS_FALLBACK_TIMEOUT_MS, self.settings.BS_REQUEST_TIMEOUT_MS)
        return min(budget, timeout_ms) if timeout_ms else budget

    async def extract(
        self,
        url: HttpUrl,
        request_id: str,
        timeout_ms: Optional[int] = None,
    ) -> ExtractedContent:
        """
        Extract content using Trafilatura (fallback extractor).

        Args:
            url: URL to extract
            request_id: Request ID for logging
            timeout_ms: The caller's per-page budget; the fallback uses at most this, and at
                most BS_FALLBACK_TIMEOUT_MS

        Raises:
            TimeoutError: No permit, fetch or parse within the budget
            Exception: On fetch or extraction failures
        """
        if not self.executor or not self.http_client:
            raise RuntimeError("Trafilatura client not connected")

        start_time = time.perf_counter()
        logger.info("trafilatura_extract_start", request_id=request_id, url=url)
        # One deadline, on the event loop's clock (time.monotonic), for the caller's timer
        # and for the worker's check.
        deadline = asyncio.get_running_loop().time() + self.budget_ms(timeout_ms) / 1000.0
        try:
            async with asyncio.timeout_at(deadline):
                content = await self._fetch_and_parse(str(url), deadline)
        except (TimeoutError, httpx.TimeoutException) as e:
            logger.warning("trafilatura_timeout", request_id=request_id, url=url)
            raise TimeoutError(f"Trafilatura extraction timeout: {url}") from e
        except httpx.RequestError as e:
            logger.warning(
                "trafilatura_request_error", request_id=request_id, url=url, error=str(e)
            )
            raise RuntimeError(f"Trafilatura fetch failed: {e}") from e
        except Exception as e:
            logger.error("trafilatura_extract_error", request_id=request_id, url=url, error=str(e))
            raise

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

    async def _fetch_and_parse(self, url: str, deadline: float) -> Optional[str]:
        """Take a permit, fetch, then parse in a thread. The permit is released when the
        work ends: here if it never reached the thread, else when the parse finishes."""
        assert self.executor is not None
        await self._permits.acquire()
        handed_to_thread = False
        try:
            html = await self._fetch(url)
            loop = asyncio.get_running_loop()
            parse = loop.run_in_executor(self.executor, _parse_unless_expired, html, deadline)
            parse.add_done_callback(self._release_after_parse)
            handed_to_thread = True
            # Shielded: a caller that stops waiting must not mark the parse done (and so
            # release its permit) while the thread is still busy with it.
            return await asyncio.shield(parse)
        finally:
            if not handed_to_thread:
                self._permits.release()

    def _release_after_parse(self, parse: asyncio.Future[Optional[str]]) -> None:
        self._permits.release()
        if not parse.cancelled():
            parse.exception()  # retrieved here, so an abandoned failure is not logged as lost

    async def _fetch(self, url: str) -> str:
        """GET the page: redirects followed by hand (bodies unread), no compression, at
        most MAX_BODY_BYTES."""
        assert self.http_client is not None
        request = self.http_client.build_request("GET", url)
        for _ in range(MAX_REDIRECTS + 1):
            response = await self.http_client.send(request, stream=True)
            try:
                if response.is_redirect:
                    if response.next_request is None:
                        raise ValueError("Redirect without a location")
                    request = response.next_request
                    continue
                response.raise_for_status()
                encoding = response.headers.get("content-encoding", "identity").strip().lower()
                if encoding not in ("", "identity"):
                    raise ValueError(f"Refused a compressed response ({encoding})")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > MAX_BODY_BYTES:
                        raise ValueError(f"Page larger than {MAX_BODY_BYTES} bytes")
                    body += chunk
                return body.decode(response.encoding or "utf-8", errors="replace")
            finally:
                await response.aclose()
        raise ValueError(f"More than {MAX_REDIRECTS} redirects")


def _parse(html: str) -> Optional[str]:
    result: Optional[str] = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        no_fallback=False,
        output_format="txt",
    )
    return result


def _parse_unless_expired(html: str, deadline: float) -> Optional[str]:
    """Runs in a worker thread. A job that waited in the queue past its deadline is
    skipped: its caller has already given up (or is about to, on the same clock)."""
    if time.monotonic() >= deadline:
        raise TimeoutError("Fallback parse expired before it started")
    return _parse(html)
