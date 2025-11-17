"""Application configuration using Pydantic settings."""
from __future__ import annotations

from typing import Optional

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Required service URLs
    BS_SEARXNG_URL: str
    BS_CRAWL4AI_URL: str
    BS_REDIS_URL: str

    # Optional auth
    BS_API_KEY: Optional[str] = None

    # Cache settings
    BS_CACHE_TTL_SECONDS: int = 3600

    # Rate limiting
    BS_RATE_LIMIT_PER_HOUR: int = 60
    BS_API_KEY_RATE_LIMIT_PER_HOUR: int = 600
    BS_GLOBAL_RATE_LIMIT_PER_HOUR: int = 10000

    # Extraction settings
    BS_MAX_RESULTS: int = 10
    BS_MAX_CONCURRENT_EXTRACTIONS: int = 4
    BS_EXTRACTION_TIMEOUT_MS: int = 2500
    BS_FALLBACK_TIMEOUT_MS: int = 2000
    BS_REQUEST_TIMEOUT_MS: int = 6000

    # Observability
    BS_LOG_LEVEL: str = "info"
    BS_ENABLE_METRICS: bool = True

    # Fallback extractor
    BS_FALLBACK_ENABLED: bool = True
    BS_FALLBACK_MAX_WORKERS: int = 2

    # Health check
    BS_HEALTH_TIMEOUT_MS: int = 750

    # Domain filtering
    BS_ALLOWED_DOMAINS: str = ""  # comma-separated
    BS_BLOCKED_DOMAINS: str = ""  # comma-separated

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
    )

    @field_validator("BS_MAX_RESULTS")
    @classmethod
    def validate_max_results(cls, value: int) -> int:
        if value > 25 or value < 1:
            raise ValueError("BS_MAX_RESULTS must be between 1 and 25")
        return value

    @field_validator("BS_EXTRACTION_TIMEOUT_MS")
    @classmethod
    def validate_extraction_timeout(cls, value: int) -> int:
        if value <= 0 or value > 6000:
            raise ValueError("BS_EXTRACTION_TIMEOUT_MS must be between 1 and 6000 ms")
        return value

    @field_validator("BS_REQUEST_TIMEOUT_MS")
    @classmethod
    def validate_request_timeout(cls, value: int) -> int:
        if value <= 0 or value > 6000:
            raise ValueError("BS_REQUEST_TIMEOUT_MS must be between 1 and 6000 ms")
        return value

    @property
    def allowed_domains_list(self) -> list[str]:
        return [d.strip() for d in self.BS_ALLOWED_DOMAINS.split(",") if d.strip()]

    @property
    def blocked_domains_list(self) -> list[str]:
        return [d.strip() for d in self.BS_BLOCKED_DOMAINS.split(",") if d.strip()]


def validate_settings(settings: Settings) -> None:
    """Validate settings on startup, fail fast with clear errors."""
    errors: list[str] = []

    if not settings.BS_SEARXNG_URL.startswith(("http://", "https://")):
        errors.append("BS_SEARXNG_URL must start with http:// or https://")

    if not settings.BS_CRAWL4AI_URL.startswith(("http://", "https://")):
        errors.append("BS_CRAWL4AI_URL must start with http:// or https://")

    if not settings.BS_REDIS_URL.startswith("redis://"):
        errors.append("BS_REDIS_URL must start with redis://")

    if settings.BS_MAX_RESULTS > 25:
        errors.append("BS_MAX_RESULTS cannot exceed 25")

    if errors:
        raise ValueError("Configuration errors:\n  - " + "\n  - ".join(errors))


def load_settings() -> Settings:
    """Load and validate settings from environment variables."""
    try:
        # Settings() will load from env vars via model_config
        settings = Settings()  # type: ignore[call-arg]
        validate_settings(settings)
        return settings
    except ValidationError as exc:
        raise ValueError(f"Invalid configuration: {exc}") from exc
