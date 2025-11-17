"""Response models for the public API."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, HttpUrl


class ResultMetadata(BaseModel):
    domain: str
    word_count: Optional[int] = None
    extracted_by: Literal["crawl4ai", "trafilatura", "none"]
    extraction_ok: bool
    extraction_error: Optional[Literal["timeout", "network_error", "parse_error", "blocked"]] = None


class ResultScores(BaseModel):
    search_score: float
    rank: int


class SearchResult(BaseModel):
    title: str = Field(max_length=500)
    url: HttpUrl
    snippet: str = Field(max_length=1000)
    content: Optional[str] = Field(default=None, max_length=50000)
    metadata: ResultMetadata
    scores: ResultScores
    source: Literal["searxng"]


class ResponseMetadata(BaseModel):
    search_time_ms: int
    searxng_time_ms: Optional[int] = None
    extraction_time_ms: Optional[int] = None
    cache_hit: bool
    sources_queried: list[str]
    api_version: str = "v1"
    rate_limited: bool = False
    rate_limited_reason: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    metadata: ResponseMetadata


class ErrorDetails(BaseModel):
    component: Optional[str] = None
    timeout: Optional[bool] = None
    retry_after_ms: Optional[int] = None
    fields: Optional[list[str]] = None


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[ErrorDetails] = None


class ErrorMetadata(BaseModel):
    request_id: str
    api_version: str = "v1"
    timestamp: str


class ErrorResponse(BaseModel):
    error: ErrorBody
    metadata: ErrorMetadata
