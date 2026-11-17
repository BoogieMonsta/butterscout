"""MCP (Streamable HTTP) adapter: exposes Butterscout search and extraction as tools.

Served at exactly ``/mcp`` by :class:`McpHttpEndpoint`. Stateless JSON mode, so uvicorn
reloads never strand a client's session. Tools call the same services as the REST
endpoints in-process, so rate limits, API-key checks and URL safety rules are shared.
"""

from __future__ import annotations

import secrets
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator, Optional

import structlog
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import ToolAnnotations
from pydantic import BaseModel, Field, ValidationError
from starlette.datastructures import Headers
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from butterscout.config import Settings
from butterscout.models.exceptions import (
    DomainNotAllowedError,
    InvalidUrlError,
    MaxResultsExceededError,
    RateLimitExceededError,
    UnauthorizedError,
    UpstreamProviderError,
)
from butterscout.models.requests import ExtractRequest, SearchOptions, SearchRequest
from butterscout.models.responses import ExtractResponse
from butterscout.services.extract_service import extract_url
from butterscout.services.search_service import SearchService
from butterscout.state import app_state
from butterscout.utils.request_helpers import get_client_ip, resolve_api_key

logger = structlog.get_logger()

# Per-result content budget for search results returned to a model. Keeps a default
# 5-result search to roughly 20k characters of page content.
MCP_CONTENT_MAX_CHARS = 4000

mcp = MCPServer(
    name="butterscout",
    version="0.1.0",
    instructions=(
        "Web search and page extraction backed by a self-hosted SearXNG + Crawl4AI stack. "
        "Use butterscout_search to find sources (each result includes clean page text, "
        "clipped to 4000 characters; content_truncated tells you when). Use "
        "butterscout_extract to read one URL in full."
    ),
)

_READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True, idempotent_hint=True)


class McpSearchResult(BaseModel):
    rank: int
    title: str
    url: str
    snippet: str
    content: Optional[str] = None
    content_truncated: bool = False
    domain: str
    extracted_by: str


class McpSearchResponse(BaseModel):
    query: str
    result_count: int
    cache_hit: bool
    search_time_ms: int
    max_results_applied: int
    results: list[McpSearchResult]


@mcp.tool(
    name="butterscout_search",
    title="Butterscout web search",
    description=(
        "Search the web via SearXNG and return ranked results with clean page content "
        "extracted by Crawl4AI (Trafilatura fallback). max_results is capped at the "
        "server limit."
    ),
    annotations=_READ_ONLY,
)
async def butterscout_search(
    query: Annotated[str, Field(min_length=1, max_length=512, description="Search query.")],
    ctx: Context[Any, Any],
    max_results: Annotated[int, Field(ge=1, le=25, description="Results wanted.")] = 5,
    include_content: Annotated[
        bool, Field(description="Extract page text for each result (slower).")
    ] = True,
    extract_timeout_ms: Annotated[
        int, Field(ge=500, le=6000, description="Per-page extraction timeout.")
    ] = 2500,
    domains: Annotated[
        Optional[list[str]], Field(max_length=20, description="Only these domains.")
    ] = None,
    exclude_domains: Annotated[
        Optional[list[str]], Field(max_length=20, description="Never these domains.")
    ] = None,
    freshness_days: Annotated[
        Optional[int], Field(gt=0, description="Only results from the last N days.")
    ] = None,
    language: Annotated[
        Optional[str], Field(min_length=2, max_length=2, description="ISO 639-1 code.")
    ] = "en",
) -> McpSearchResponse:
    started = time.perf_counter()
    request = _http_request(ctx)
    request_id = _request_id(request)
    applied = min(max_results, app_state.settings.BS_MAX_RESULTS)
    try:
        body = SearchRequest(
            query=query,
            max_results=applied,
            include_content=include_content,
            extract_timeout_ms=extract_timeout_ms,
            options=SearchOptions(
                domains=domains or [],
                exclude_domains=exclude_domains or [],
                freshness_days=freshness_days,
                language=language,
            ),
        )
        service = SearchService(
            settings=app_state.settings,
            redis_client=app_state.redis_client,
            searxng_client=app_state.searxng_client,
            extraction_strategy=app_state.extraction_strategy,
            cache_service=app_state.cache_service,
        )
        response, _headers = await service.execute_search(
            request_body=body,
            request_id=request_id,
            client_ip=_client_ip(request),
            api_key=_api_key(request),
            request_state=request.state if request is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a tool error or re-raised
        _log_call("butterscout_search", request_id, started, error=exc)
        raise _to_tool_error(exc) from exc

    results = []
    for item in response.results:
        content = item.content
        truncated = item.metadata.content_truncated
        if content is not None and len(content) > MCP_CONTENT_MAX_CHARS:
            content = content[:MCP_CONTENT_MAX_CHARS]
            truncated = True
        results.append(
            McpSearchResult(
                rank=item.scores.rank,
                title=item.title,
                url=str(item.url),
                snippet=item.snippet,
                content=content,
                content_truncated=truncated,
                domain=item.metadata.domain,
                extracted_by=item.metadata.extracted_by,
            )
        )
    _log_call("butterscout_search", request_id, started, result_count=len(results))
    return McpSearchResponse(
        query=response.query,
        result_count=len(results),
        cache_hit=response.metadata.cache_hit,
        search_time_ms=response.metadata.search_time_ms,
        max_results_applied=applied,
        results=results,
    )


@mcp.tool(
    name="butterscout_extract",
    title="Butterscout page extraction",
    description=(
        "Extract clean Markdown/text from one public http(s) URL using Crawl4AI with a "
        "Trafilatura fallback. Local and private addresses are refused."
    ),
    annotations=_READ_ONLY,
)
async def butterscout_extract(
    url: Annotated[str, Field(description="Public http or https URL.")],
    ctx: Context[Any, Any],
    extract_timeout_ms: Annotated[
        int, Field(ge=500, le=6000, description="Extraction timeout.")
    ] = 2500,
    max_characters: Annotated[
        int, Field(ge=1000, le=80000, description="Clip content to this many characters.")
    ] = 20000,
) -> ExtractResponse:
    started = time.perf_counter()
    request = _http_request(ctx)
    request_id = _request_id(request)
    try:
        body = ExtractRequest.model_validate(
            {"url": url, "extract_timeout_ms": extract_timeout_ms, "max_characters": max_characters}
        )
        response, _headers = await extract_url(
            body,
            client_ip=_client_ip(request),
            api_key=_api_key(request),
            request_id=request_id,
            request_state=request.state if request is not None else None,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a tool error or re-raised
        _log_call("butterscout_extract", request_id, started, error=exc)
        raise _to_tool_error(exc) from exc
    _log_call("butterscout_extract", request_id, started, result_count=1)
    return response


def _to_tool_error(exc: Exception) -> Exception:
    """Map known failures to a ToolError (isError result with a clear message).

    Unknown exceptions are returned unchanged; the SDK reports them to the client only as
    "Error executing tool" and logs the traceback.
    """
    if isinstance(exc, RateLimitExceededError):
        wait = f" Retry after {int(exc.retry_after)}s." if exc.retry_after else ""
        return ToolError(f"Butterscout rate limit exceeded.{wait}")
    if isinstance(exc, UnauthorizedError):
        return ToolError("Missing or invalid Butterscout API key.")
    if isinstance(exc, MaxResultsExceededError):
        return ToolError(f"max_results {exc.requested} exceeds the server limit {exc.allowed}.")
    if isinstance(exc, (InvalidUrlError, DomainNotAllowedError)):
        return ToolError(exc.message)
    if isinstance(exc, UpstreamProviderError):
        reason = "timed out" if exc.is_timeout else "failed"
        return ToolError(f"Upstream {exc.component} {reason}: {exc.message}")
    if isinstance(exc, ValidationError):
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or 'input'}: {err['msg']}"
            for err in exc.errors()
        )
        return ToolError(f"Invalid arguments: {problems}")
    return exc


def _http_request(ctx: Context[Any, Any]) -> Optional[Request]:
    request = ctx.request_context.request
    return request if isinstance(request, Request) else None


def _request_id(request: Optional[Request]) -> str:
    if request is None:
        return "unknown"
    return str(getattr(request.state, "request_id", "unknown"))


def _client_ip(request: Optional[Request]) -> str:
    return get_client_ip(request) if request is not None else "unknown"


def _api_key(request: Optional[Request]) -> Optional[str]:
    return resolve_api_key(request.headers) if request is not None else None


def _log_call(
    tool: str,
    request_id: str,
    started: float,
    *,
    result_count: int = 0,
    error: Optional[Exception] = None,
) -> None:
    logger.info(
        "mcp_tool_call",
        tool=tool,
        request_id=request_id,
        outcome="ok" if error is None else type(error).__name__,
        result_count=result_count,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


@asynccontextmanager
async def run_mcp(settings: Settings) -> AsyncIterator[None]:
    """Run a fresh MCP session manager for one app lifespan.

    A session manager's ``run()`` works once per instance, and the FastAPI app is a
    module singleton whose lifespan can run many times (each ``with TestClient(app)``),
    so a new manager is built every time. ``streamable_http_app()`` creates it.
    """
    if not settings.BS_MCP_ENABLED:
        yield
        return
    mcp.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.mcp_allowed_hosts_list,
            allowed_origins=settings.mcp_allowed_origins_list,
        ),
    )
    manager = mcp.session_manager
    async with manager.run():
        app_state.mcp_session_manager = manager
        logger.info("mcp_enabled", path="/mcp", allowed_hosts=settings.mcp_allowed_hosts_list)
        try:
            yield
        finally:
            app_state.mcp_session_manager = None


class McpHttpEndpoint:
    """Raw ASGI endpoint for ``/mcp``.

    Registered as a plain Route (not a Mount) so ``POST /mcp`` is served directly
    instead of being redirected to ``/mcp/``.
    """

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        settings = app_state.settings
        if not settings.BS_MCP_ENABLED:
            await JSONResponse({"detail": "Not Found"}, status_code=404)(scope, receive, send)
            return
        manager = app_state.mcp_session_manager
        if manager is None:
            await JSONResponse(
                {"detail": "MCP is not running"}, status_code=503
            )(scope, receive, send)
            return
        if settings.BS_API_KEY and not _key_matches(Headers(scope=scope), settings.BS_API_KEY):
            await JSONResponse(
                {"detail": "Missing or invalid API key"},
                status_code=401,
                headers={"WWW-Authenticate": 'Bearer realm="Butterscout API"'},
            )(scope, receive, send)
            return
        await manager.handle_request(scope, receive, send)


def _key_matches(headers: Headers, expected: str) -> bool:
    key = resolve_api_key(headers)
    return key is not None and secrets.compare_digest(key, expected)
