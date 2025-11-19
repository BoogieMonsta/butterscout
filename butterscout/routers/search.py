"""Search endpoint implementation."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from butterscout.models.requests import SearchRequest
from butterscout.models.responses import SearchResponse
from butterscout.services.search_service import SearchService
from butterscout.state import app_state
from butterscout.utils.request_helpers import get_client_ip

logger = structlog.get_logger()

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
async def search(
    request_body: SearchRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
) -> JSONResponse:
    """
    Main search endpoint

    Execute web search with content extraction.
    """
    request_id = getattr(request.state, "request_id", "unknown")
    
    # Initialize service (can be moved to app_state for better DI)
    search_service = SearchService(
        settings=app_state.settings,
        redis_client=app_state.redis_client,
        searxng_client=app_state.searxng_client,
        extraction_strategy=app_state.extraction_strategy,
    )

    logger.info(
        "search_request_begin",
        request_id=request_id,
        query=request_body.query,
        max_results=request_body.max_results,
        include_content=request_body.include_content,
    )

    client_ip = get_client_ip(request)

    response, headers = await search_service.execute_search(
        request_body=request_body,
        request_id=request_id,
        client_ip=client_ip,
        api_key=x_api_key,
        request_state=request.state,
    )

    return JSONResponse(
        content=response.model_dump(mode="json"),
        headers=headers,
    )
