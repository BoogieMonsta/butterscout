"""Shared application state container."""

from __future__ import annotations

from typing import Optional

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.extraction_strategy import ExtractionStrategy
from butterscout.clients.redis_client import ValkeyClient
from butterscout.clients.searxng_client import SearXNGClient
from butterscout.clients.trafilatura_client import TrafilaturaClient
from butterscout.config import Settings
from butterscout.services.cache_backend import CacheBackend
from butterscout.services.cache_service import CacheService


class AppState:
    """Application state container."""

    settings: Settings
    redis_client: ValkeyClient
    searxng_client: SearXNGClient
    crawl4ai_client: Crawl4AIClient
    trafilatura_client: Optional[TrafilaturaClient]
    extraction_strategy: ExtractionStrategy
    cache_backend: CacheBackend
    cache_service: CacheService
    # Set only while the app lifespan is running with BS_MCP_ENABLED.
    mcp_session_manager: Optional[StreamableHTTPSessionManager] = None


app_state = AppState()
