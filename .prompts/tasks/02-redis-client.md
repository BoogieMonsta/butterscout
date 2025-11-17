# Task 02: Redis Client & Utilities

**Role:** You are a senior Python backend engineer specializing in Redis, caching strategies, and async I/O patterns.

## Context

Build the Redis client layer that will power both caching and rate limiting in Butterscout. This needs to be production-ready with proper connection pooling, error handling, and health checks.

Refer to **[TECH SPEC.md]** §5.4, §7.2 for complete details.

## Deliverables

### 1. Redis Client (`butterscout/clients/redis_client.py`)

Implement async Redis client with connection pooling:

```python
import redis.asyncio as redis
from typing import Optional
from butterscout.config import Settings

class RedisClient:
    """Async Redis client with connection pooling"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.redis: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Establish Redis connection pool"""
        self.redis = await redis.from_url(
            self.settings.BS_REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=20,
            socket_keepalive=True,
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )

    async def disconnect(self) -> None:
        """Close Redis connection pool"""
        if self.redis:
            await self.redis.close()

    async def ping(self) -> bool:
        """Health check - returns True if Redis is responsive"""
        if not self.redis:
            return False
        try:
            await self.redis.ping()
            return True
        except Exception:
            return False

    async def get(self, key: str) -> Optional[str]:
        """Get value by key"""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        return await self.redis.get(key)

    async def set(
        self,
        key: str,
        value: str,
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """Set key-value with optional TTL"""
        if not self.redis:
            raise RuntimeError("Redis not connected")

        if ttl_seconds:
            return await self.redis.setex(key, ttl_seconds, value)
        else:
            return await self.redis.set(key, value)

    async def delete(self, key: str) -> int:
        """Delete key, returns number of keys deleted"""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        return await self.redis.delete(key)

    async def exists(self, key: str) -> bool:
        """Check if key exists"""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        return await self.redis.exists(key) > 0

    async def incr(self, key: str) -> int:
        """Increment integer value at key"""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        return await self.redis.incr(key)

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration on key"""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        return await self.redis.expire(key, seconds)

    async def ttl(self, key: str) -> int:
        """Get TTL of key in seconds (-1 = no expiry, -2 = doesn't exist)"""
        if not self.redis:
            raise RuntimeError("Redis not connected")
        return await self.redis.ttl(key)
```

### 2. Redis Key Utilities (`butterscout/utils/redis_keys.py`)

Create standardized key generation:

```python
import hashlib
from butterscout.models.requests import SearchRequest

def generate_cache_key(request: SearchRequest) -> str:
    """Generate stable cache key from search request"""
    # Create options hash for cache key
    options_str = (
        f"{sorted(request.options.domains)}"
        f"{sorted(request.options.exclude_domains)}"
        f"{request.options.freshness_days}"
        f"{request.options.language}"
    )
    options_hash = hashlib.md5(options_str.encode()).hexdigest()[:8]

    # Combine all cache-relevant params
    cache_parts = (
        f"{request.query.lower().strip()}"
        f":{request.max_results}"
        f":{request.include_content}"
        f":{options_hash}"
    )

    # Generate SHA256 hash for key
    key_hash = hashlib.sha256(cache_parts.encode()).hexdigest()
    return f"bs:cache:{key_hash}"

def generate_rate_limit_key(
    identifier: str,
    key_type: str = "ip"
) -> str:
    """Generate rate limit key

    Args:
        identifier: IP address or API key
        key_type: "ip" or "api_key"
    """
    hashed = hashlib.sha256(identifier.encode()).hexdigest()[:16]
    return f"bs:ratelimit:{key_type}:{hashed}"

def generate_global_rate_limit_key() -> str:
    """Generate global rate limit key"""
    return "bs:ratelimit:global"
```

### 3. Connection Management (`butterscout/utils/redis_manager.py`)

Implement lifecycle management and dependency injection:

```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from butterscout.clients.redis_client import RedisClient
from butterscout.config import Settings

# Global instance
_redis_client: Optional[RedisClient] = None

def get_redis_client() -> RedisClient:
    """Get singleton Redis client instance"""
    global _redis_client
    if _redis_client is None:
        raise RuntimeError("Redis client not initialized")
    return _redis_client

async def init_redis(settings: Settings) -> RedisClient:
    """Initialize Redis client on startup"""
    global _redis_client
    _redis_client = RedisClient(settings)
    await _redis_client.connect()
    return _redis_client

async def close_redis() -> None:
    """Close Redis connection on shutdown"""
    global _redis_client
    if _redis_client:
        await _redis_client.disconnect()
        _redis_client = None

@asynccontextmanager
async def redis_lifespan(
    settings: Settings
) -> AsyncGenerator[RedisClient, None]:
    """Lifespan context manager for FastAPI"""
    client = await init_redis(settings)
    try:
        yield client
    finally:
        await close_redis()
```

## Key Implementation Details

### Connection Pool Configuration

- **max_connections=20**: Sufficient for single-node deployment
- **socket_keepalive=True**: Prevent connection drops
- **retry_on_timeout=True**: Auto-retry transient failures
- **decode_responses=True**: Work with strings, not bytes

### Error Handling

All Redis operations should:
1. Check if client is connected
2. Raise clear errors on connection issues
3. Log errors with context (key, operation)
4. Never swallow exceptions silently

### Key Naming Convention

Follow pattern: `bs:<namespace>:<identifier>`

- Cache: `bs:cache:<sha256-hash>`
- Rate limit: `bs:ratelimit:<type>:<hashed-identifier>`
- Global rate limit: `bs:ratelimit:global`

### Cache Key Stability

**Critical:** Cache keys MUST be stable across requests with identical parameters:
- Normalize query (lowercase, strip whitespace)
- Sort domain lists
- Hash options consistently
- Use deterministic hash function (SHA256)

## Testing Requirements

### Unit Tests (`tests/unit/test_redis_client.py`)

```python
import pytest
from butterscout.clients.redis_client import RedisClient
from butterscout.config import Settings

@pytest.mark.asyncio
async def test_redis_connection():
    """Test Redis connection and ping"""
    settings = Settings(
        BS_REDIS_URL="redis://localhost:6379/0",
        # ... other required settings
    )
    client = RedisClient(settings)
    await client.connect()

    assert await client.ping() is True

    await client.disconnect()

@pytest.mark.asyncio
async def test_redis_get_set():
    """Test basic get/set operations"""
    client = await setup_redis_client()

    # Set value
    await client.set("test:key", "test_value", ttl_seconds=10)

    # Get value
    value = await client.get("test:key")
    assert value == "test_value"

    # Check TTL
    ttl = await client.ttl("test:key")
    assert 0 < ttl <= 10

@pytest.mark.asyncio
async def test_redis_operations_require_connection():
    """Test that operations fail gracefully when not connected"""
    settings = Settings(BS_REDIS_URL="redis://localhost:6379")
    client = RedisClient(settings)

    with pytest.raises(RuntimeError, match="Redis not connected"):
        await client.get("test:key")
```

### Integration Tests (`tests/integration/test_redis_integration.py`)

- Test against real Redis instance (use Docker for CI)
- Test connection pool under load
- Test TTL expiration works correctly
- Test concurrent operations don't interfere

### Key Generation Tests (`tests/unit/test_redis_keys.py`)

```python
def test_cache_key_stability():
    """Cache keys must be identical for same request"""
    from butterscout.utils.redis_keys import generate_cache_key
    from butterscout.models.requests import SearchRequest

    req1 = SearchRequest(query="test query", max_results=10)
    req2 = SearchRequest(query="test query", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 == key2

def test_cache_key_uniqueness():
    """Different requests must produce different keys"""
    req1 = SearchRequest(query="query 1", max_results=10)
    req2 = SearchRequest(query="query 2", max_results=10)

    key1 = generate_cache_key(req1)
    key2 = generate_cache_key(req2)

    assert key1 != key2

def test_rate_limit_key_format():
    """Rate limit keys should follow naming convention"""
    from butterscout.utils.redis_keys import generate_rate_limit_key

    key = generate_rate_limit_key("192.168.1.1", "ip")
    assert key.startswith("bs:ratelimit:ip:")
```

## Performance Requirements

- Connection establishment: < 100ms
- Ping latency: < 5ms (local deployment)
- Get/Set operations: < 10ms (local deployment)
- Connection pool should support 100+ concurrent operations

## Output Format

When complete, provide:

1. ✅ All files created
2. ✅ Tests passing (unit + integration if Redis available)
3. 📊 Performance benchmark:
   - 1000 get/set operations timing
   - Connection pool under concurrent load
4. 📝 Example usage showing:
   - Client initialization
   - Cache key generation
   - Basic CRUD operations

## Dependencies

- **Task 01** (Project Foundation) - Requires config and models

## Time Estimate

3-4 hours

## Reference

- [TECH SPEC.md] §5.4: Data & Infra - Redis usage
- [TECH SPEC.md] §7.2: Configuration - Redis URL
- [ENGINEERING_GUIDE.md] §10: Testing Strategy - Integration tests
