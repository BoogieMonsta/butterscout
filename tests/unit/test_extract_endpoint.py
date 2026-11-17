"""Unit tests for the direct extract endpoint."""

from __future__ import annotations

from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from butterscout.models.internal import ExtractedContent


@pytest.fixture
def mock_extract_state() -> Generator[MagicMock, None, None]:
    """Mock app_state for extract endpoint tests."""
    with patch("butterscout.routers.extract.app_state") as mock_state:
        mock_state.settings = MagicMock()
        mock_state.settings.BS_API_KEY = None
        mock_state.settings.BS_RATE_LIMIT_PER_HOUR = 60
        mock_state.settings.BS_API_KEY_RATE_LIMIT_PER_HOUR = 600
        mock_state.settings.BS_GLOBAL_RATE_LIMIT_PER_HOUR = 10000
        mock_state.settings.BS_REQUEST_TIMEOUT_MS = 6000
        mock_state.settings.allowed_domains_list = []
        mock_state.settings.blocked_domains_list = []
        mock_state.redis_client = MagicMock()
        mock_state.extraction_strategy = MagicMock()
        yield mock_state


@pytest.mark.asyncio
async def test_extract_reads_one_public_url(mock_extract_state: MagicMock) -> None:
    from butterscout.main import app

    mock_extract_state.extraction_strategy.extract = AsyncMock(
        return_value=ExtractedContent(
            url=HttpUrl("https://93.184.216.34/page"),
            content="# Example\n\nExtracted text",
            word_count=3,
            extracted_by="trafilatura",
            extraction_ok=True,
            extraction_time_ms=42,
        )
    )

    with patch("butterscout.routers.extract.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/extract",
            json={"url": "https://93.184.216.34/page", "max_characters": 80_000},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "https://93.184.216.34/page"
    assert data["canonical_url"] == "https://93.184.216.34/page"
    assert data["content"] == "# Example\n\nExtracted text"
    assert data["metadata"]["domain"] == "93.184.216.34"
    assert data["metadata"]["extracted_by"] == "trafilatura"


@pytest.mark.asyncio
async def test_extract_blocks_private_urls(mock_extract_state: MagicMock) -> None:
    from butterscout.main import app

    with patch("butterscout.routers.extract.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post("/api/v1/extract", json={"url": "http://127.0.0.1:8000"})

    assert response.status_code == 400
    mock_extract_state.extraction_strategy.extract.assert_not_called()


@pytest.mark.asyncio
async def test_extract_requires_api_key_when_configured(
    mock_extract_state: MagicMock,
) -> None:
    from butterscout.main import app

    mock_extract_state.settings.BS_API_KEY = "secret"

    with patch("butterscout.routers.extract.RateLimiter") as mock_limiter_class:
        mock_limiter = mock_limiter_class.return_value
        mock_limiter.check_rate_limit = AsyncMock(
            return_value=(True, None, 59, 60, 1234567890)
        )

        client = TestClient(app, raise_server_exceptions=False)
        response = client.post(
            "/api/v1/extract", json={"url": "https://93.184.216.34/page"}
        )

    assert response.status_code == 401
    mock_extract_state.extraction_strategy.extract.assert_not_called()
