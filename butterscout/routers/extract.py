"""Direct URL extraction endpoint."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from butterscout.models.requests import ExtractRequest
from butterscout.models.responses import ExtractResponse
from butterscout.services.extract_service import extract_url
from butterscout.utils.request_helpers import get_client_ip

router = APIRouter(tags=["extract"])


@router.post("/extract", response_model=ExtractResponse)
async def extract(
    request_body: ExtractRequest,
    request: Request,
    x_api_key: Optional[str] = Header(None, alias="x-api-key"),
) -> JSONResponse:
    """Extract clean content from one public URL without running a search first."""
    response, headers = await extract_url(
        request_body,
        client_ip=get_client_ip(request),
        api_key=x_api_key,
        request_id=getattr(request.state, "request_id", "unknown"),
        request_state=request.state,
    )
    return JSONResponse(content=response.model_dump(mode="json"), headers=headers)
