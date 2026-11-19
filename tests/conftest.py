"""Test configuration."""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from butterscout.clients.crawl4ai_client import Crawl4AIClient
from butterscout.clients.redis_client import ValkeyClient
from butterscout.clients.searxng_client import SearXNGClient
from butterscout.config import Settings


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    """Create event loop for async tests"""
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def settings() -> Settings:
    """Test settings with safe defaults"""
    return Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/15",  # Use test database
        BS_API_KEY=None,
        BS_RATE_LIMIT_PER_HOUR=1000,
        BS_MAX_RESULTS=10,
        BS_MAX_CONCURRENT_EXTRACTIONS=4,
        BS_CACHE_TTL_SECONDS=60,
        BS_LOG_LEVEL="warning",  # Reduce noise in tests
        BS_REQUEST_TIMEOUT_MS=2000,
        BS_EXTRACTION_TIMEOUT_MS=2500,
        BS_FALLBACK_TIMEOUT_MS=2000,
        BS_FALLBACK_ENABLED=True,
        BS_FALLBACK_MAX_WORKERS=2,
        BS_HEALTH_TIMEOUT_MS=750,
    )


@pytest.fixture
async def redis_client(settings: Settings) -> AsyncGenerator[ValkeyClient, None]:
    """Valkey/Redis client for integration tests"""
    client = ValkeyClient(settings)
    await client.connect()

    yield client

    # Cleanup: flush test database
    if client.valkey:
        await client.valkey.flushdb()
    await client.disconnect()


@pytest.fixture
def mock_redis_client() -> ValkeyClient:
    """Mock Valkey/Redis client for unit tests"""
    mock_client = AsyncMock(spec=ValkeyClient)
    mock_client.get = AsyncMock(return_value=None)
    mock_client.set = AsyncMock(return_value=True)
    mock_client.delete = AsyncMock(return_value=1)
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.incr = AsyncMock(return_value=1)
    mock_client.exists = AsyncMock(return_value=True)
    mock_client.connect = AsyncMock(return_value=None)
    mock_client.disconnect = AsyncMock(return_value=None)
    mock_client.valkey = MagicMock()
    return mock_client


@pytest.fixture
def mock_searxng_client() -> SearXNGClient:
    """Mock SearXNG client for unit tests"""
    from typing import cast

    from pydantic import HttpUrl

    from butterscout.models.internal import NormalizedSearchResult

    def _url(url_str: str) -> HttpUrl:
        return cast(HttpUrl, url_str)

    mock_client = MagicMock(spec=SearXNGClient)
    mock_client.search = AsyncMock(
        return_value=[
            NormalizedSearchResult(
                title="Test Result",
                url=_url("https://example.com"),
                snippet="Test snippet",
                score=0.9,
            )
        ]
    )
    mock_client.health_check = AsyncMock(return_value=True)
    return mock_client


@pytest.fixture
def mock_crawl4ai_client() -> Crawl4AIClient:
    """Mock Crawl4AI client for unit tests"""
    from typing import cast

    from pydantic import HttpUrl

    from butterscout.models.internal import ExtractedContent

    def _url(url_str: str) -> HttpUrl:
        return cast(HttpUrl, url_str)

    mock_client = MagicMock(spec=Crawl4AIClient)
    mock_client.extract = AsyncMock(
        return_value=ExtractedContent(
            url=_url("https://example.com"),
            content="Extracted content here",
            word_count=100,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=100,
        )
    )
    mock_client.health_check = AsyncMock(return_value=True)
    return mock_client


@pytest.fixture
async def app_client() -> AsyncGenerator[TestClient, None]:
    """FastAPI test client"""
    from butterscout.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def _fresh_health_snapshot() -> Iterator[None]:
    """/health caches its last result for a cooldown; every test starts without one."""
    from butterscout.routers.health import _snapshot

    _snapshot.reset()
    yield
    _snapshot.reset()
