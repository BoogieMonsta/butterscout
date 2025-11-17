"""Request models for the public API."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SearchOptions(BaseModel):
    domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)
    freshness_days: Optional[int] = Field(default=None, gt=0)
    language: Optional[str] = Field(default="en", min_length=2, max_length=2)

    @field_validator("domains", "exclude_domains")
    @classmethod
    def validate_domains(cls, value: list[str]) -> list[str]:
        if len(value) > 20:
            raise ValueError("domains/exclude_domains cannot exceed 20 entries")
        for domain in value:
            if not (3 <= len(domain) <= 255):
                raise ValueError("Domain length must be between 3 and 255 characters")
        return value

    @field_validator("language")
    @classmethod
    def validate_language(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if len(value) != 2:
            raise ValueError("language must be a 2-letter ISO 639-1 code")
        return value


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    max_results: int = Field(default=10, ge=1, le=25)
    include_content: bool = Field(default=True)
    extract_timeout_ms: int = Field(default=2500, ge=500, le=6000)
    options: SearchOptions = Field(default_factory=SearchOptions)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Query cannot be empty or whitespace-only")
        return value
