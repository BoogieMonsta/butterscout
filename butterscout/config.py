"""Application configuration using Pydantic settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Upper bound for BS_REQUEST_TIMEOUT_MS, and so for any one extraction attempt. The
# Crawl4AI server's own per-crawl deadline (crawl4ai-config/config.yml) must stay above it.
MAX_REQUEST_TIMEOUT_MS = 6000


class Settings(BaseSettings):
    # Required service URLs
    BS_SEARXNG_URL: str = "http://localhost:8080"
    BS_CRAWL4AI_URL: str = "http://localhost:11235"
    # Crawl4AI 0.9+ answers its API only with this bearer token (its CRAWL4AI_API_TOKEN).
    BS_CRAWL4AI_API_TOKEN: Optional[str] = None
    BS_CACHE_TYPE: Literal["redis", "memory"] = "redis"
    BS_REDIS_URL: str = "redis://localhost:6379/0"

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
    # Fallback budget per page; never more than the caller's extract_timeout_ms. Replay
    # 2026-11-19 (60 pages): 2000 lost 3-5 more pages than the old fallback when Crawl4AI
    # was busy or down; 3000 recovered most of them (p95 +0.3-0.6 s).
    BS_FALLBACK_TIMEOUT_MS: int = 3000
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

    # Extraction configuration
    BS_EXTRACTION_EXCLUDE_SELECTORS: list[str] = [
        "nav",
        "header",
        "footer",
        ".advertisement",
        ".cookie-banner",
    ]

    # CORS configuration
    BS_CORS_ORIGINS: str = "*"  # comma-separated origins or "*" for all

    # Security settings
    BS_PRODUCTION_MODE: bool = False  # Enable strict security checks for production

    # MCP (Streamable HTTP at /mcp). Off unless explicitly enabled.
    BS_MCP_ENABLED: bool = False
    # Host header values accepted on /mcp (DNS-rebinding protection). "host:*" = any port.
    BS_MCP_ALLOWED_HOSTS: str = "localhost:*,127.0.0.1:*,[::1]:*"
    # Origin header values accepted on /mcp. Empty = only clients that send no Origin
    # (native MCP clients); browsers are refused.
    BS_MCP_ALLOWED_ORIGINS: str = ""

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
        if value <= 0 or value > MAX_REQUEST_TIMEOUT_MS:
            raise ValueError(
                f"BS_REQUEST_TIMEOUT_MS must be between 1 and {MAX_REQUEST_TIMEOUT_MS} ms"
            )
        return value

    @field_validator("BS_MAX_CONCURRENT_EXTRACTIONS")
    @classmethod
    def validate_max_concurrent_extractions(cls, value: int) -> int:
        if value < 1:
            raise ValueError("BS_MAX_CONCURRENT_EXTRACTIONS must be at least 1")
        return value

    @property
    def allowed_domains_list(self) -> list[str]:
        return [d.strip() for d in self.BS_ALLOWED_DOMAINS.split(",") if d.strip()]

    @property
    def blocked_domains_list(self) -> list[str]:
        return [d.strip() for d in self.BS_BLOCKED_DOMAINS.split(",") if d.strip()]

    @property
    def mcp_allowed_hosts_list(self) -> list[str]:
        return [h.strip() for h in self.BS_MCP_ALLOWED_HOSTS.split(",") if h.strip()]

    @property
    def mcp_allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.BS_MCP_ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins from comma-separated string."""
        if self.BS_CORS_ORIGINS == "*":
            return ["*"]
        return [origin.strip() for origin in self.BS_CORS_ORIGINS.split(",") if origin.strip()]


def validate_settings(settings: Settings) -> None:
    """Validate settings on startup, fail fast with clear errors."""
    errors: list[str] = []

    if not settings.BS_SEARXNG_URL.startswith(("http://", "https://")):
        errors.append("BS_SEARXNG_URL must start with http:// or https://")

    if not settings.BS_CRAWL4AI_URL.startswith(("http://", "https://")):
        errors.append("BS_CRAWL4AI_URL must start with http:// or https://")

    if not settings.BS_REDIS_URL.startswith(("redis://", "valkey://")):
        errors.append("BS_REDIS_URL must start with redis:// or valkey://")

    if settings.BS_MAX_RESULTS > 25:
        errors.append("BS_MAX_RESULTS cannot exceed 25")

    # Production mode security checks
    if settings.BS_PRODUCTION_MODE:
        # Check for insecure SearXNG secret key
        searxng_config_path = Path("searxng-config/settings.yml")
        if searxng_config_path.exists():
            try:
                with open(searxng_config_path, encoding="utf-8") as f:
                    config_content = f.read()
                    if "INSECURE_DEFAULT_CHANGE_IN_PRODUCTION" in config_content:
                        errors.append(
                            "SearXNG is using the insecure default secret_key. "
                            "Generate a new secret with: openssl rand -hex 32"
                        )
            except Exception:
                # If we can't read the file, just skip this check
                pass

        # Check for secure CORS configuration
        if settings.BS_CORS_ORIGINS == "*":
            errors.append(
                "BS_CORS_ORIGINS is set to '*' which allows all origins. "
                "In production, specify allowed origins explicitly."
            )

        # Check for API key in production
        if not settings.BS_API_KEY:
            errors.append(
                "BS_API_KEY is not set. "
                "In production, set a strong API key: openssl rand -base64 32"
            )

    if errors:
        raise ValueError("Configuration errors:\n  - " + "\n  - ".join(errors))


def load_settings() -> Settings:
    """Load and validate settings from environment variables."""
    try:
        # Settings() will load from env vars via model_config
        settings = Settings()
        validate_settings(settings)
        return settings
    except ValidationError as exc:
        raise ValueError(f"Invalid configuration: {exc}") from exc
