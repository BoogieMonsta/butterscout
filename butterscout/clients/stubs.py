"""Test stubs for skipping startup dependencies."""

from __future__ import annotations

import time
from typing import Optional, cast

from pydantic import HttpUrl

from butterscout.clients.crawl4ai_client import Crawl4AIClient, MarkdownFilter
from butterscout.clients.redis_client import ValkeyClient
from butterscout.clients.searxng_client import SearXNGClient
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent, NormalizedSearchResult
from butterscout.models.requests import SearchRequest


class NoopValkeyClient(ValkeyClient):
    """Fail-open Valkey client for test/skip-startup mode."""

    async def connect(self) -> None:  # pragma: no cover - trivial
        self.valkey = None

    async def disconnect(self) -> None:  # pragma: no cover - trivial
        return

    async def ping(self) -> bool:
        return True

    async def get(self, key: str) -> Optional[str]:  # noqa: D401
        return None

    async def set(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> bool:
        return True

    async def delete(self, key: str) -> int:
        return 0

    async def eval(self, script: str, num_keys: int, *args: object) -> list[int]:
        # Allow requests by default; return minimal Lua-compatible response
        return [1, 0, int(time.time())]

    async def exists(self, key: str) -> bool:
        return False

    async def incr(self, key: str) -> int:
        return 1

    async def expire(self, key: str, seconds: int) -> bool:
        return True

    async def ttl(self, key: str) -> int:
        return -1


class StubSearXNGClient(SearXNGClient):
    """Stub SearXNG client that avoids network calls in test mode."""

    def __init__(self, settings: Settings):
        super().__init__(settings)

    async def connect(self) -> None:
        return

    async def disconnect(self) -> None:
        return

    async def search(self, request: SearchRequest, request_id: str) -> list[NormalizedSearchResult]:
        # Return a deterministic stub result; keep shape valid
        if request.max_results <= 0:
            return []
        return [
            NormalizedSearchResult(
                title="Stubbed result",
                url=cast(HttpUrl, "https://example.com"),
                snippet="Stubbed response (skip-startup mode)",
                score=1.0,
            )
        ]

    async def health_check(self) -> bool:
        return True


class StubCrawl4AIClient(Crawl4AIClient):
    """Stub Crawl4AI client for skip-startup mode."""

    def __init__(self, settings: Settings):
        super().__init__(settings)

    async def connect(self) -> None:
        return

    async def disconnect(self) -> None:
        return

    async def extract(
        self,
        url: HttpUrl,
        request_id: str,
        timeout_ms: int | None = None,
        markdown_filter: MarkdownFilter = "raw",
    ) -> ExtractedContent:
        return ExtractedContent(
            url=url,
            content="Stubbed content",
            word_count=2,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=1,
        )

    async def health_check(self) -> bool:
        return True


class StubTrafilaturaClient(TrafilaturaClient):
    """Stub Trafilatura client for skip-startup mode."""

    def __init__(self, settings: Settings):
        super().__init__(settings)

    async def connect(self) -> None:
        return

    async def disconnect(self) -> None:
        return

    async def extract(
        self,
        url: HttpUrl,
        request_id: str,
        timeout_ms: int | None = None,
    ) -> ExtractedContent:
        return ExtractedContent(
            url=url,
            content="Stubbed fallback content",
            word_count=3,
            extracted_by="trafilatura",
            extraction_ok=True,
            extraction_time_ms=1,
        )
