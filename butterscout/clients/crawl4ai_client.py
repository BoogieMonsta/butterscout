"""Crawl4AI extraction client (Crawl4AI 0.9.x server, POST /crawl)."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Literal, Optional

import httpx
import structlog
from pydantic import HttpUrl

from butterscout.config import Settings
from butterscout.models.internal import Crawl4AIFault, ExtractedContent

logger = structlog.get_logger()

# "raw" is the whole page as markdown; "fit" prunes nav, footers and other low-text
# blocks. Fit can also drop link lists and short bullet lists.
MarkdownFilter = Literal["raw", "fit"]

# A Crawl4AI attempt waits at most this share of its budget for a free slot, so the crawl
# itself always keeps the rest (no 1 ms crawls when a slot frees up at the last moment).
SLOT_WAIT_SHARE = 0.5
# Crawl4AI gets the time left as its page timeout; we allow this much more for it to turn
# the page into markdown and send it back, inside one hard deadline.
RESPONSE_GRACE_SECONDS = 1.0
# After navigation, Crawl4AI waits for the body to be visible: 30 s by default, even when
# told to ignore visibility, and not covered by page_timeout. A page that hid its body
# for 20 s held a tab for 20 s; with this cap it returned the same text in 0.7 s.
BODY_VISIBILITY_TIMEOUT_MS = 1000

# The exact markdown config search uses. The health probe requests it too: an unknown
# type is silently accepted by Crawl4AI (fit comes back empty), so a renamed filter
# would otherwise turn every search into raw markdown without a sound.
FIT_GENERATOR = {
    "type": "DefaultMarkdownGenerator",
    "params": {"content_filter": {"type": "PruningContentFilterLXML", "params": {}}},
}
_PROBE_MARKER = "butterscout-health-probe"
_PROBE_PAGE = (
    "raw:<html><body><article><h1>Butterscout probe</h1><p>"
    f"{_PROBE_MARKER}: this paragraph checks that the content filter keeps ordinary prose. "
    "It has enough words to read as the main text of a page rather than navigation or "
    "boilerplate.</p></article></body></html>"
)


class Crawl4AIUnavailableError(RuntimeError):
    """Crawl4AI itself is failing (not one page): unreachable, auth, server or API errors."""

    def __init__(self, reason: Crawl4AIFault, detail: str):
        self.reason: Crawl4AIFault = reason
        super().__init__(f"Crawl4AI {reason}: {detail}")


class Crawl4AIBusyError(TimeoutError):
    """No Crawl4AI slot freed up in time, or Crawl4AI itself refused for load (HTTP 429)."""


class Crawl4AIClient:
    """Client for the Crawl4AI extraction service.

    One instance is shared by the whole app, so its slot limit
    (BS_MAX_CONCURRENT_EXTRACTIONS) caps in-flight Crawl4AI pages across all
    concurrent searches and extracts, not per request.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.BS_CRAWL4AI_URL.rstrip("/")
        self.client: Optional[httpx.AsyncClient] = None
        self._slots = asyncio.Semaphore(settings.BS_MAX_CONCURRENT_EXTRACTIONS)

    async def connect(self) -> None:
        """Initialize HTTP client."""
        headers = {}
        if self.settings.BS_CRAWL4AI_API_TOKEN:
            headers["Authorization"] = f"Bearer {self.settings.BS_CRAWL4AI_API_TOKEN}"
        self.client = httpx.AsyncClient(
            headers=headers,
            follow_redirects=False,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
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
        markdown_filter: MarkdownFilter = "raw",
    ) -> ExtractedContent:
        """
        Extract content from URL using Crawl4AI.

        The budget is one deadline for this Crawl4AI attempt: waiting for a slot (at most
        half of it), then the crawl. Crawl4AI is told to stop loading the page when the
        budget runs out, because it does not stop when we hang up. Fallback extraction
        has its own timeouts on top of this.

        Args:
            url: URL to extract
            request_id: Request ID for logging
            timeout_ms: Attempt budget (defaults to BS_EXTRACTION_TIMEOUT_MS)
            markdown_filter: "fit" for pruned markdown, "raw" for the whole page

        Raises:
            Crawl4AIBusyError: No slot freed up in time, or Crawl4AI refused for load
            Crawl4AIUnavailableError: Crawl4AI itself failed
            TimeoutError: The page did not load, or Crawl4AI did not answer, in time
            ValueError: The page failed or produced no content
        """
        if not self.client:
            raise RuntimeError("Crawl4AI client not connected")

        budget_s = (
            min(
                timeout_ms or self.settings.BS_EXTRACTION_TIMEOUT_MS,
                self.settings.BS_REQUEST_TIMEOUT_MS,
            )
            / 1000.0
        )
        start_time = time.perf_counter()
        deadline = start_time + budget_s
        slot_cutoff = start_time + budget_s * SLOT_WAIT_SHARE

        try:
            async with asyncio.timeout(budget_s * SLOT_WAIT_SHARE):
                await self._slots.acquire()
        except TimeoutError as e:
            logger.warning("crawl4ai_busy", request_id=request_id, url=url)
            raise Crawl4AIBusyError("No Crawl4AI slot freed up in time") from e

        try:
            # A grant can land just after the cutoff (e.g. the event loop stalled):
            # crawling then would get less than its share, or a negative timeout.
            now = time.perf_counter()
            remaining_ms = int((deadline - now) * 1000)
            if now > slot_cutoff or remaining_ms <= 0:
                raise Crawl4AIBusyError("Crawl4AI slot granted too late")
            params: dict[str, Any] = {
                "page_timeout": remaining_ms,
                "body_visibility_timeout": min(BODY_VISIBILITY_TIMEOUT_MS, remaining_ms),
                "cache_mode": "bypass",
            }
            if markdown_filter == "fit":
                params["markdown_generator"] = FIT_GENERATOR
            result = await self._crawl_one(
                str(url), params, remaining_ms / 1000.0 + RESPONSE_GRACE_SECONDS
            )
        finally:
            self._slots.release()

        if result["success"] is False:
            message = str(result.get("error_message") or "unknown error")
            if "timeout" in message.lower():
                raise TimeoutError(f"Crawl4AI page timeout: {url}")
            raise ValueError(f"Crawl4AI could not crawl the page: {message[:200]}")

        markdown = result["markdown"]
        content = markdown["fit_markdown"] if markdown_filter == "fit" else ""
        # Pruning can remove everything on a short page; the raw markdown came back in
        # the same response, so use it rather than failing over to another extractor.
        if not content.strip():
            content = markdown["raw_markdown"]
        if not content.strip():
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

    async def health_check(self) -> bool:
        """Render a tiny inline page through a real browser with search's fit config.

        GET /health answers even when every browser is stuck, so it cannot tell a
        working Crawl4AI from a dead one. An inline ``raw:`` page needs no network and
        takes tens of milliseconds when the browser pool works. Does not take a slot.

        Raises:
            Crawl4AIUnavailableError: With the reason Crawl4AI is not usable
        """
        if not self.client:
            raise Crawl4AIUnavailableError("unreachable", "client not connected")
        timeout_ms = self.settings.BS_HEALTH_TIMEOUT_MS
        params = {
            "page_timeout": timeout_ms,
            "body_visibility_timeout": min(BODY_VISIBILITY_TIMEOUT_MS, timeout_ms),
            "cache_mode": "bypass",
            "markdown_generator": FIT_GENERATOR,
        }
        try:
            result = await self._crawl_one(_PROBE_PAGE, params, timeout_ms / 1000.0)
        except TimeoutError as e:  # includes Crawl4AIBusyError (HTTP 429)
            raise Crawl4AIUnavailableError("unresponsive", "probe did not finish in time") from e
        except ValueError as e:
            raise Crawl4AIUnavailableError("server_error", f"probe rejected: {e}") from e
        if result["success"] is False:
            raise Crawl4AIUnavailableError("server_error", "probe page did not render")
        if _PROBE_MARKER not in result["markdown"]["fit_markdown"]:
            raise Crawl4AIUnavailableError(
                "api_mismatch", "fit markdown is empty; check the content filter config"
            )
        return True

    async def _crawl_one(
        self, url: str, params: dict[str, Any], timeout_s: float
    ) -> dict[str, Any]:
        """POST one URL to /crawl within a hard wall-clock limit; return its validated result.

        HTTPX timeouts apply per connection phase and per chunk, so a slow trickle could
        outlast them; the asyncio deadline bounds the whole exchange.
        """
        assert self.client is not None
        body = {"urls": [url], "crawler_config": {"type": "CrawlerRunConfig", "params": params}}
        try:
            async with asyncio.timeout(timeout_s):
                response = await self.client.post(
                    f"{self.base_url}/crawl", json=body, timeout=httpx.Timeout(timeout_s)
                )
        except httpx.ConnectTimeout as e:
            raise Crawl4AIUnavailableError("unreachable", "connect timed out") from e
        except (TimeoutError, httpx.TimeoutException) as e:
            raise TimeoutError(f"Crawl4AI did not answer within {timeout_s:.1f}s") from e
        except httpx.RequestError as e:
            raise Crawl4AIUnavailableError("unreachable", type(e).__name__) from e
        return _validated_result(response)


def _validated_result(response: httpx.Response) -> dict[str, Any]:
    """Map a /crawl response to its single result, or raise a typed error.

    Contract (Crawl4AI 0.9.5): 200 with ``results[0]``, whose ``success`` is a bool and
    whose markdown fields are strings (or null). 400 means Crawl4AI refused either the
    URL (its SSRF guard; a page problem) or our config ("Rejected config"; an API
    mismatch). 429 means Crawl4AI is shedding load.
    """
    status = response.status_code
    if status in (401, 403):
        raise Crawl4AIUnavailableError("auth", f"HTTP {status}; check BS_CRAWL4AI_API_TOKEN")
    if status == 429:
        raise Crawl4AIBusyError("Crawl4AI refused for load (HTTP 429)")
    if status == 504:
        # Crawl4AI's own per-crawl deadline (limits.wall_clock_s): this page took too long.
        raise TimeoutError("Crawl4AI's crawl deadline passed (HTTP 504)")
    if status >= 500:
        raise Crawl4AIUnavailableError("server_error", f"HTTP {status}")
    if status == 400:
        detail = response.text[:200]
        if "Rejected config" in detail:
            raise Crawl4AIUnavailableError("api_mismatch", detail)
        raise ValueError(f"Crawl4AI refused the URL: {detail}")
    if status != 200:
        raise Crawl4AIUnavailableError("api_mismatch", f"HTTP {status}")

    try:
        data = response.json()
    except ValueError as e:
        raise Crawl4AIUnavailableError("api_mismatch", "response is not JSON") from e
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list) or not results or not isinstance(results[0], dict):
        raise Crawl4AIUnavailableError("api_mismatch", "response has no results")
    result: dict[str, Any] = results[0]
    if not isinstance(result.get("success"), bool):
        raise Crawl4AIUnavailableError("api_mismatch", "result.success is not a boolean")

    markdown = result.get("markdown")
    if markdown is None:
        markdown = {}
    if not isinstance(markdown, dict):
        raise Crawl4AIUnavailableError("api_mismatch", "result.markdown is not an object")
    fields = {}
    for name in ("raw_markdown", "fit_markdown"):
        value = markdown.get(name)
        if value is not None and not isinstance(value, str):
            raise Crawl4AIUnavailableError("api_mismatch", f"markdown.{name} is not a string")
        fields[name] = value or ""
    result["markdown"] = fields
    return result
