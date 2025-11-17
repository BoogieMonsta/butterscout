import pytest
from pydantic import ValidationError

from butterscout.config import Settings, validate_settings


def test_settings_validation_invalid_searxng_url() -> None:
    """Test that invalid SearXNG URL is rejected."""
    with pytest.raises(ValueError, match="BS_SEARXNG_URL must start with"):
        validate_settings(
            Settings(
                BS_SEARXNG_URL="invalid",
                BS_CRAWL4AI_URL="http://crawl4ai:11235",
                BS_REDIS_URL="redis://localhost:6379/0",
            )
        )


def test_settings_validation_invalid_crawl4ai_url() -> None:
    """Test that invalid Crawl4AI URL is rejected."""
    with pytest.raises(ValueError, match="BS_CRAWL4AI_URL must start with"):
        validate_settings(
            Settings(
                BS_SEARXNG_URL="http://searxng:8080",
                BS_CRAWL4AI_URL="invalid",
                BS_REDIS_URL="redis://localhost:6379/0",
            )
        )


def test_settings_validation_invalid_redis_url() -> None:
    """Test that invalid Redis URL is rejected."""
    with pytest.raises(ValueError, match="BS_REDIS_URL must start with"):
        validate_settings(
            Settings(
                BS_SEARXNG_URL="http://searxng:8080",
                BS_CRAWL4AI_URL="http://crawl4ai:11235",
                BS_REDIS_URL="invalid",
            )
        )


def test_settings_validation_max_results_cap() -> None:
    """Test that BS_MAX_RESULTS > 25 is rejected."""
    with pytest.raises(ValidationError):
        Settings(
            BS_SEARXNG_URL="http://searxng:8080",
            BS_CRAWL4AI_URL="http://crawl4ai:11235",
            BS_REDIS_URL="redis://localhost:6379/0",
            BS_MAX_RESULTS=26,
        )


def test_settings_load_valid() -> None:
    """Test that valid settings load correctly."""
    settings = Settings(
        BS_SEARXNG_URL="http://searxng:8080",
        BS_CRAWL4AI_URL="http://crawl4ai:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
    )
    validate_settings(settings)
    assert settings.BS_SEARXNG_URL == "http://searxng:8080"
    assert settings.BS_MAX_RESULTS == 10  # default
    assert settings.BS_CACHE_TTL_SECONDS == 3600  # default


def test_allowed_blocked_domains_parsing() -> None:
    """Test that comma-separated domains are parsed correctly."""
    settings = Settings(
        BS_SEARXNG_URL="http://searxng:8080",
        BS_CRAWL4AI_URL="http://crawl4ai:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_ALLOWED_DOMAINS="example.com, foo.com ",
        BS_BLOCKED_DOMAINS="bad.com",
    )
    assert settings.allowed_domains_list == ["example.com", "foo.com"]
    assert settings.blocked_domains_list == ["bad.com"]


def test_allowed_blocked_domains_empty() -> None:
    """Test that empty domain lists work correctly."""
    settings = Settings(
        BS_SEARXNG_URL="http://searxng:8080",
        BS_CRAWL4AI_URL="http://crawl4ai:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
    )
    assert settings.allowed_domains_list == []
    assert settings.blocked_domains_list == []
