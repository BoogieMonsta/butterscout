"""Internal data models for orchestration."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, HttpUrl


class NormalizedSearchResult(BaseModel):
    """Internal model for search results from SearXNG."""

    title: str
    url: HttpUrl
    snippet: str
    score: float
    source: str = "searxng"


class ExtractedContent(BaseModel):
    """Internal model for extracted content."""

    url: HttpUrl
    content: str
    word_count: int
    extracted_by: str
    extraction_ok: bool
    extraction_time_ms: int
    error: Optional[str] = None


class CacheKey(BaseModel):
    """Cache key components."""

    query: str
    max_results: int
    include_content: bool
    options_hash: str

    def to_redis_key(self) -> str:
        import hashlib

        parts = f"{self.query}:{self.max_results}:{self.include_content}:{self.options_hash}"
        return f"bs:cache:{hashlib.sha256(parts.encode()).hexdigest()}"


class HealthComponent(BaseModel):
    status: str
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    last_success: Optional[datetime] = None
