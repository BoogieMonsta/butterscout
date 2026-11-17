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
    # True when `content` was clipped (to SEARCH_CONTENT_MAX_CHARS here, or further by
    # a client-facing adapter such as the MCP tool). Defaults False so cached responses
    # written before this field existed still load.
    content_truncated: bool = False


SEARCH_CONTENT_MAX_CHARS = 50000


class ResultScores(BaseModel):
    search_score: float
    rank: int


class SearchResult(BaseModel):
    title: str = Field(max_length=500)
    url: HttpUrl
    snippet: str = Field(max_length=1000)
    content: Optional[str] = Field(default=None, max_length=SEARCH_CONTENT_MAX_CHARS)
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


class ExtractMetadata(BaseModel):
    domain: str
    word_count: int
    extracted_by: Literal["crawl4ai", "trafilatura", "none"]
    extraction_ok: bool
    extraction_error: Optional[str] = None
    extraction_time_ms: int


class ExtractResponse(BaseModel):
    url: HttpUrl
    canonical_url: HttpUrl
    title: str
    content: Optional[str] = Field(default=None, max_length=80000)
    metadata: ExtractMetadata


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
