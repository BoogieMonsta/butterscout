# Task 06: Caching Layer

**Role:** You are a senior backend engineer specializing in caching strategies, Redis patterns, and high-performance data retrieval.

## Context

Implement TTL-based response caching in Redis to reduce load on upstream services and improve response times. The cache must generate stable keys and handle serialization efficiently. Defaults: TTL 1h; cache key = hash(query + normalized options + include_content + max_results); JSON/MessagePack acceptable.

Refer to **[TECH SPEC.md]** §4.1, §4.2, §5.4, §6.2, §7.2 for complete details.

## Deliverables

### 1. Cache Service (`butterscout/services/cache_service.py`)

```python
import json
from typing import Optional
from butterscout.clients.redis_client import RedisClient
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import SearchResponse
from butterscout.utils.redis_keys import generate_cache_key
from butterscout.config import Settings
import structlog

logger = structlog.get_logger()

class CacheService:
    """Response caching service using Redis"""

    def __init__(self, redis_client: RedisClient, settings: Settings):
        self.redis = redis_client
        self.ttl_seconds = settings.BS_CACHE_TTL_SECONDS
        self.settings = settings

    async def get(
        self,
        request: SearchRequest,
        request_id: str
    ) -> Optional[SearchResponse]:
        """
        Get cached response if available

        Args:
            request: Search request
            request_id: Request ID for logging

        Returns:
            Cached SearchResponse or None if cache miss
        """
        cache_key = generate_cache_key(request)

        try:
            cached_json = await self.redis.get(cache_key)

            if cached_json:
                logger.info(
                    "cache_hit",
                    request_id=request_id,
                    cache_key=cache_key[:16] + "...",
                )
                # Deserialize from JSON
                data = json.loads(cached_json)
                return SearchResponse(**data)

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
            # On cache errors, treat as cache miss
            return None

    async def set(
        self,
        request: SearchRequest,
        response: SearchResponse,
        request_id: str
    ) -> bool:
        """
        Store response in cache

        Args:
            request: Original search request
            response: Response to cache
            request_id: Request ID for logging

        Returns:
            True if successfully cached
        """
        cache_key = generate_cache_key(request)

        try:
            # Serialize to JSON
            response_json = response.model_dump_json()

            # Store with TTL
            success = await self.redis.set(
                cache_key,
                response_json,
                ttl_seconds=self.ttl_seconds,
            )

            if success:
                logger.info(
                    "cache_set",
                    request_id=request_id,
                    cache_key=cache_key[:16] + "...",
                    ttl_seconds=self.ttl_seconds,
                    response_size_bytes=len(response_json),
                )
            else:
                logger.warning(
                    "cache_set_failed",
                    request_id=request_id,
                    cache_key=cache_key[:16] + "...",
                )

            return success

        except Exception as e:
            logger.error(
                "cache_set_error",
                request_id=request_id,
                error=str(e),
            )
            # Don't fail request on cache errors
            return False

    async def invalidate(self, request: SearchRequest) -> bool:
        """
        Manually invalidate cache entry

        Args:
            request: Search request to invalidate

        Returns:
            True if key was deleted
        """
        cache_key = generate_cache_key(request)
        try:
            deleted = await self.redis.delete(cache_key)
            return deleted > 0
        except Exception as e:
            logger.error("cache_invalidate_error", error=str(e))
            return False
```

### 2. Cache Middleware (`butterscout/middleware/cache_middleware.py`)

Optional: Middleware to handle caching transparently (can be implemented later):

```python
# NOTE: This can be implemented as part of the endpoint logic
# or as explicit middleware. For v0.1, direct service calls are sufficient.
# This file is a placeholder for future enhancement.
```

## Key Implementation Details

### Cache Key Generation (TECH SPEC §5.4)

Cache key must include:
- Query (normalized: lowercase, trimmed)
- `max_results`
- `include_content` flag
- Options hash (domains, exclude_domains, freshness, language)

**Critical:** Keys MUST be stable - same request = same key

### TTL Strategy (TECH SPEC §6.2)

- Default TTL: 1 hour (3600 seconds)
- Configurable via `BS_CACHE_TTL_SECONDS`
- TTL-based expiration only (no manual invalidation in v0.1)

### Serialization

- Use Pydantic's `model_dump_json()` for serialization
- Use Pydantic model constructor for deserialization
- This ensures type safety and validation

### Error Handling

- **Never fail request on cache errors**
- Cache miss on read errors
- Log errors but continue
- Treat cache as optional optimization

### Cache Size Considerations

- Log response size on cache writes
- Typical response: 5-50 KB
- Redis default max value: 512 MB (plenty)
- Consider compression for very large responses (future enhancement)

## Testing Requirements

### Unit Tests (`tests/unit/test_cache_service.py`)

```python
import pytest
from butterscout.services.cache_service import CacheService
from butterscout.models.requests import SearchRequest
from butterscout.models.responses import SearchResponse, ResponseMetadata

@pytest.mark.asyncio
async def test_cache_miss(redis_client, settings):
    """Test cache miss returns None"""
    cache = CacheService(redis_client, settings)

    request = SearchRequest(query="test query")
    result = await cache.get(request, "test-123")

    assert result is None

@pytest.mark.asyncio
async def test_cache_hit(redis_client, settings):
    """Test cache hit returns stored response"""
    cache = CacheService(redis_client, settings)

    request = SearchRequest(query="test query")

    # Create and cache response
    original_response = SearchResponse(
        query="test query",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    await cache.set(request, original_response, "test-123")

    # Retrieve from cache
    cached_response = await cache.get(request, "test-123")

    assert cached_response is not None
    assert cached_response.query == "test query"
    assert cached_response.metadata.search_time_ms == 100

@pytest.mark.asyncio
async def test_cache_key_stability(redis_client, settings):
    """Test that identical requests produce same cache key"""
    cache = CacheService(redis_client, settings)

    req1 = SearchRequest(query="test", max_results=10)
    req2 = SearchRequest(query="test", max_results=10)

    from butterscout.utils.redis_keys import generate_cache_key

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 == key2

@pytest.mark.asyncio
async def test_cache_ttl_expiration(redis_client, settings):
    """Test that cache entries expire after TTL"""
    import asyncio

    # Use short TTL for test
    settings.BS_CACHE_TTL_SECONDS = 1
    cache = CacheService(redis_client, settings)

    request = SearchRequest(query="test")
    response = SearchResponse(
        query="test",
        results=[],
        metadata=ResponseMetadata(
            search_time_ms=100,
            cache_hit=False,
            sources_queried=["searxng"],
        ),
    )

    await cache.set(request, response, "test-123")

    # Should be cached immediately
    cached = await cache.get(request, "test-123")
    assert cached is not None

    # Wait for expiration
    await asyncio.sleep(2)

    # Should be expired
    cached = await cache.get(request, "test-123")
    assert cached is None

@pytest.mark.asyncio
async def test_cache_handles_errors_gracefully(redis_client, settings):
    """Test that cache errors don't break requests"""
    cache = CacheService(redis_client, settings)

    # Disconnect Redis to simulate error
    await redis_client.disconnect()

    request = SearchRequest(query="test")

    # Should return None on error, not raise
    result = await cache.get(request, "test-123")
    assert result is None
```

### Integration Tests (`tests/integration/test_cache_integration.py`)

- Test with real Redis instance
- Verify TTL behavior over time
- Test large responses (1000+ results)
- Test concurrent cache operations

## Performance Requirements

- Cache get: < 5ms (local Redis)
- Cache set: < 10ms (local Redis)
- Serialization: < 50ms for typical response
- No memory leaks from cached objects

## Output Format

When complete, provide:

1. ✅ All files created
2. ✅ Tests passing (unit + integration)
3. 📊 Performance metrics:
   - Cache hit/miss latency
   - Serialization timing
   - TTL verification
4. 📝 Example showing:
   - Cache miss → upstream → cache set
   - Cache hit → fast response

## Dependencies

- **Task 01** (Project Foundation)
- **Task 02** (Redis Client)

## Time Estimate

3-4 hours

## Reference

- [TECH SPEC.md] §4.1: Caching & Rate Limiting
- [TECH SPEC.md] §4.2: Request Lifecycle - Cache check
- [TECH SPEC.md] §5.4: Redis usage
- [TECH SPEC.md] §6.2: Cache TTL configuration
- [TECH SPEC.md] §7.2: BS_CACHE_TTL_SECONDS
