"""Test configuration."""
import pytest

from butterscout.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_REQUEST_TIMEOUT_MS=2000,
        BS_EXTRACTION_TIMEOUT_MS=2500,
        BS_FALLBACK_TIMEOUT_MS=2000,
        BS_FALLBACK_ENABLED=True,
        BS_FALLBACK_MAX_WORKERS=2,
        BS_HEALTH_TIMEOUT_MS=750,
    )
