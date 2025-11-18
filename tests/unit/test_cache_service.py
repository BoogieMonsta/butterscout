"""Unit tests for cache service."""
from __future__ import annotations

import asyncio
from typing import cast

import pytest
import pytest_asyncio
from pydantic import HttpUrl

from butterscout.clients.redis_client import ValkeyClient
from butterscout.config import Settings
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import ResponseMetadata, SearchResponse
from butterscout.services.cache_service import CacheService
from butterscout.utils.redis_keys import generate_cache_key


def _url(url_str: str) -> HttpUrl:
    return cast(HttpUrl, url_str)


@pytest.fixture
def settings() -> Settings:
    """Create test settings with short TTL for testing."""
    return Settings(
        BS_REDIS_URL="valkey://localhost:6379/1",  # Use DB 1 for tests
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_CACHE_TTL_SECONDS=3600,  # 1 hour default
    )


@pytest_asyncio.fixture
async def redis_client(settings: Settings) -> ValkeyClient:
    """Create Redis client fixture (not connected for unit tests)."""
    client = ValkeyClient(settings)
    return client


@pytest_asyncio.fixture
async def cache_service(redis_client: ValkeyClient, settings: Settings) -> CacheService:
    """Create cache service fixture."""
    return CacheService(redis_client, settings)


@pytest.mark.asyncio
async def test_cache_service_initialization(
    cache_service: CacheService, settings: Settings
) -> None:
    """Test that cache service initializes correctly."""
    assert cache_service.redis is not None
    assert cache_service.ttl_seconds == settings.BS_CACHE_TTL_SECONDS
    assert cache_service.settings is settings


@pytest.mark.asyncio
async def test_cache_miss_when_not_connected(cache_service: CacheService) -> None:
    """Test that cache miss is returned when Redis is not connected."""
    request = SearchRequest(query="test query")
    result = await cache_service.get(request, "test-123")

    # Should return None on error, not raise
    assert result is None


@pytest.mark.asyncio
async def test_cache_set_fails_gracefully_when_not_connected(
    cache_service: CacheService,
) -> None:
    """Test that cache set fails gracefully when Redis is not connected."""
    request = SearchRequest(query="test query")
    response = SearchResponse(
        query="test query",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    # Should return False on error, not raise
    success = await cache_service.set(request, response, "test-123")
    assert success is False


@pytest.mark.asyncio
async def test_invalidate_fails_gracefully_when_not_connected(
    cache_service: CacheService,
) -> None:
    """Test that cache invalidation fails gracefully when Redis is not connected."""
    request = SearchRequest(query="test query")

    # Should return False on error, not raise
    result = await cache_service.invalidate(request)
    assert result is False


