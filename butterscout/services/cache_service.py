"""Response caching service using Redis/Valkey."""
from __future__ import annotations

import json
from typing import Optional

import structlog

from butterscout.config import Settings
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import SearchResponse
from butterscout.services.cache_backend import CacheBackend
from butterscout.services.metrics import metrics_service
from butterscout.utils.redis_keys import generate_cache_key

logger = structlog.get_logger()


class CacheService:
    """Service for caching search results."""

    def __init__(self, backend: CacheBackend, settings: Settings):
        """Initialize cache service.

        Args:
            backend: CacheBackend instance for cache storage
            settings: Application settings with cache configuration
        """
        self.backend = backend
        self.settings = settings

    async def get(
        self, request: SearchRequest, request_id: str
    ) -> Optional[SearchResponse]:
        """Get cached response if available.

        Args:
            request: Search request to look up in cache
            request_id: Request ID for logging

        Returns:
            Cached SearchResponse or None if cache miss or error
        """
        cache_key = generate_cache_key(request)

        try:
            cached_json = await self.backend.get(cache_key)

            if cached_json:
                metrics_service.record_cache_hit()
                logger.info(
                    "cache_hit",
                    request_id=request_id,
                    cache_key=cache_key[:16] + "...",
                )
                # Deserialize from JSON using Pydantic
                data = json.loads(cached_json)
                return SearchResponse(**data)

            metrics_service.record_cache_miss()
            logger.info(
                "cache_miss",
                request_id=request_id,
                cache_key=cache_key[:16] + "...",
            )
            return None

        except Exception as e:
            logger.error(
                "cache_get_error",
                request_id=request_id,
                error=str(e),
            )
            # On cache errors, treat as cache miss - never fail the request
            return None

    async def set(
        self, request: SearchRequest, response: SearchResponse, request_id: str
    ) -> bool:
        """Store response in cache with TTL.

        Args:
            request: Original search request (used to generate cache key)
            response: Response to cache
            request_id: Request ID for logging

        Returns:
            True if successfully cached, False on error
        """
        cache_key = generate_cache_key(request)

        try:
            # Serialize to JSON using Pydantic's model_dump_json
            response_json = response.model_dump_json()

            # Store with TTL
            await self.backend.set(
                cache_key,
                response_json,
                ttl=self.settings.BS_CACHE_TTL_SECONDS,
            )

            logger.info(
                "cache_set",
                request_id=request_id,
                cache_key=cache_key[:16] + "...",
                ttl_seconds=self.settings.BS_CACHE_TTL_SECONDS,
                response_size_bytes=len(response_json),
            )
            return True

        except Exception as e:
            logger.error(
                "cache_set_error",
                request_id=request_id,
                error=str(e),
            )
            # Don't fail request on cache errors
            return False

    async def invalidate(self, request: SearchRequest) -> bool:
        """Manually invalidate cache entry.

        Args:
            request: Search request to invalidate from cache

        Returns:
            True if key was deleted, False otherwise
        """
        cache_key = generate_cache_key(request)
        try:
            deleted = await self.backend.delete(cache_key)
            return deleted > 0
        except Exception as e:
            logger.error("cache_invalidate_error", error=str(e))
            return False
