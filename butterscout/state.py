"""Shared application state container."""

from __future__ import annotations

from typing import Optional

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


app_state = AppState()
