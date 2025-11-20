import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import httpx
from butterscout.clients.searxng_client import SearXNGClient
from butterscout.config import Settings
from butterscout.models.requests import SearchRequest

@pytest.mark.asyncio
async def test_searxng_retry_logic_network_error():
    """Test that SearXNG client retries on network errors (RequestError)."""
    settings = Settings()
    client = SearXNGClient(settings)

    # Mock the internal httpx client
    mock_httpx_client = AsyncMock(spec=httpx.AsyncClient)
    client.client = mock_httpx_client

    # Setup the mock to raise RequestError (connection error) first, then succeed
    mock_response = MagicMock()
    mock_response.json.return_value = {"results": []}
    mock_response.status_code = 200
    mock_response.raise_for_status.return_value = None

    # First call raises ConnectError (subclass of RequestError), second call returns success
    mock_httpx_client.get.side_effect = [
        httpx.ConnectError("Connection refused"),
        mock_response
    ]

    request = SearchRequest(query="test")

    # Run search
    results = await client.search(request, "req-123")

    # Verify it called get twice (retry happened)
    assert mock_httpx_client.get.call_count == 2
    assert results == []

@pytest.mark.asyncio
async def test_searxng_retry_exhausted():
    """Test that SearXNG client raises exception after retries are exhausted."""
    settings = Settings()
    client = SearXNGClient(settings)

    mock_httpx_client = AsyncMock(spec=httpx.AsyncClient)
    client.client = mock_httpx_client

    # Always raise ConnectError
    mock_httpx_client.get.side_effect = httpx.ConnectError("Connection refused")

    request = SearchRequest(query="test")

    with pytest.raises(httpx.ConnectError):
        await client.search(request, "req-123")

    # Should have tried 2 times (initial + 1 retry)
    assert mock_httpx_client.get.call_count == 2
