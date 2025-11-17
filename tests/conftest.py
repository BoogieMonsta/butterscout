"""Test configuration."""
import pytest

from butterscout.config import Settings


@pytest.fixture
def settings() -> Settings:
    """Provide test settings."""
    return Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_REQUEST_TIMEOUT_MS=2000,
        BS_HEALTH_TIMEOUT_MS=750,
    )
