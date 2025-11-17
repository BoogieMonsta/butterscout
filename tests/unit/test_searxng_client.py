"""Unit tests for SearXNG client."""
from typing import Any

import pytest
import httpx
import respx

from butterscout.clients.searxng_client import SearXNGClient
from butterscout.config import Settings
from butterscout.models.requests import SearchRequest, SearchOptions


@pytest.mark.asyncio
@respx.mock
async def test_searxng_search_success(settings: Settings) -> None:
    """Test successful search request."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Test Result 1",
                "url": "https://example.com/page1",
                "content": "This is a test content snippet for the first result",
                "score": 0.95,
            },
            {
                "title": "Test Result 2",
                "url": "https://example.com/page2",
                "content": "This is a test content snippet for the second result",
                "score": 0.85,
            },
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test query")
        results = await client.search(request, request_id="test-123")

        assert len(results) == 2
        assert results[0].title == "Test Result 1"
        assert str(results[0].url) == "https://example.com/page1"
        assert results[0].score == 0.95
        assert results[0].source == "searxng"
        assert results[1].title == "Test Result 2"
        assert results[1].score == 0.85
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_search_with_language(settings: Settings) -> None:
    """Test search request with language parameter."""
    mock_response: dict[str, Any] = {"results": []}

    route = respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(
            query="bonjour", options=SearchOptions(language="fr")
        )
        await client.search(request, request_id="test-123")

        # Verify language parameter was passed
        assert route.calls.last.request.url.params["language"] == "fr"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_search_with_freshness(settings: Settings) -> None:
    """Test search request with freshness parameter."""
    mock_response: dict[str, Any] = {"results": []}

    route = respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        # Test day range
        request = SearchRequest(
            query="test", options=SearchOptions(freshness_days=1)
        )
        await client.search(request, request_id="test-123")
        assert route.calls.last.request.url.params["time_range"] == "day"

        # Test week range
        request = SearchRequest(
            query="test", options=SearchOptions(freshness_days=7)
        )
        await client.search(request, request_id="test-124")
        assert route.calls.last.request.url.params["time_range"] == "week"

        # Test month range
        request = SearchRequest(
            query="test", options=SearchOptions(freshness_days=30)
        )
        await client.search(request, request_id="test-125")
        assert route.calls.last.request.url.params["time_range"] == "month"

        # Test year range
        request = SearchRequest(
            query="test", options=SearchOptions(freshness_days=365)
        )
        await client.search(request, request_id="test-126")
        assert route.calls.last.request.url.params["time_range"] == "year"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_retry_on_timeout(settings: Settings) -> None:
    """Test retry logic on timeout."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Success after retry",
                "url": "https://example.com",
                "content": "Test content",
            }
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        side_effect=[
            httpx.TimeoutException("Timeout"),
            httpx.Response(200, json=mock_response),
        ]
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")
        results = await client.search(request, request_id="test-123")

        # Should succeed on retry
        assert isinstance(results, list)
        assert len(results) == 1
        assert results[0].title == "Success after retry"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_retry_on_5xx_error(settings: Settings) -> None:
    """Test retry logic on 5xx server error."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Success after retry",
                "url": "https://example.com",
                "content": "Test content",
            }
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        side_effect=[
            httpx.Response(503, text="Service Unavailable"),
            httpx.Response(200, json=mock_response),
        ]
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")
        results = await client.search(request, request_id="test-123")

        # Should succeed on retry
        assert isinstance(results, list)
        assert len(results) == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_retry_on_429_error(settings: Settings) -> None:
    """Test retry logic on 429 rate limit error."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Success after retry",
                "url": "https://example.com",
                "content": "Test content",
            }
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        side_effect=[
            httpx.Response(429, text="Too Many Requests"),
            httpx.Response(200, json=mock_response),
        ]
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")
        results = await client.search(request, request_id="test-123")

        # Should succeed on retry
        assert isinstance(results, list)
        assert len(results) == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_no_retry_on_4xx_error(settings: Settings) -> None:
    """Test that 4xx errors are not retried."""
    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(400, text="Bad Request")
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")

        with pytest.raises(httpx.HTTPStatusError):
            await client.search(request, request_id="test-123")

        # Verify only one attempt was made (no retry)
        assert len(respx.calls) == 1
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_max_retries_exceeded(settings: Settings) -> None:
    """Test that retries stop after max attempts."""
    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        side_effect=[
            httpx.TimeoutException("Timeout"),
            httpx.TimeoutException("Timeout"),
            httpx.TimeoutException("Timeout"),  # This should never be reached
        ]
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")

        with pytest.raises(httpx.TimeoutException):
            await client.search(request, request_id="test-123")

        # Verify exactly 2 attempts were made (1 initial + 1 retry)
        assert len(respx.calls) == 2
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_normalize_results_with_missing_fields(settings: Settings) -> None:
    """Test normalization of results with missing optional fields."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                # Only required field
                "url": "https://example.com/page1",
            },
            {
                "title": "Has Title",
                "url": "https://example.com/page2",
                # No content or score
            },
            {
                "title": "Full Result",
                "url": "https://example.com/page3",
                "content": "Full content",
                "score": 0.95,
            },
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")
        results = await client.search(request, request_id="test-123")

        assert len(results) == 3

        # First result: no title, no content, position-based score
        assert results[0].title == "No title"
        assert results[0].snippet == ""
        assert results[0].score == 1.0  # position 0: 1.0 / (0 + 1) = 1.0

        # Second result: has title, position-based score
        assert results[1].title == "Has Title"
        assert results[1].snippet == ""
        assert results[1].score == 0.5  # position 1: 1.0 / (1 + 1) = 0.5

        # Third result: all fields present
        assert results[2].title == "Full Result"
        assert results[2].snippet == "Full content"
        assert results[2].score == 0.95
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_max_results_limit(settings: Settings) -> None:
    """Test that max_results is respected."""
    # Create 15 mock results
    mock_results = [
        {
            "title": f"Result {i}",
            "url": f"https://example.com/page{i}",
            "content": f"Content {i}",
            "score": 1.0 - (i * 0.05),
        }
        for i in range(15)
    ]

    mock_response: dict[str, Any] = {"results": mock_results}

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        # Request only 5 results
        request = SearchRequest(query="test", max_results=5)
        results = await client.search(request, request_id="test-123")

        # Should only get 5 results, not all 15
        assert len(results) == 5
        assert results[0].title == "Result 0"
        assert results[4].title == "Result 4"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_snippet_truncation(settings: Settings) -> None:
    """Test that long snippets are truncated to 500 characters."""
    long_content = "A" * 1000  # 1000 character string

    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Long Content",
                "url": "https://example.com",
                "content": long_content,
            }
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")
        results = await client.search(request, request_id="test-123")

        assert len(results) == 1
        # Snippet should be truncated to 500 chars
        assert len(results[0].snippet) == 500
        assert results[0].snippet == "A" * 500
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_invalid_result_skipped(settings: Settings) -> None:
    """Test that invalid results are skipped with warning."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Valid Result",
                "url": "https://example.com/valid",
                "content": "Valid content",
            },
            {
                "title": "Invalid - no URL",
                "content": "Missing URL field",
                # Missing required 'url' field
            },
            {
                "title": "Another Valid",
                "url": "https://example.com/valid2",
                "content": "More valid content",
            },
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")
        results = await client.search(request, request_id="test-123")

        # Should get 2 valid results, invalid one skipped
        assert len(results) == 2
        assert results[0].title == "Valid Result"
        assert results[1].title == "Another Valid"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_health_check_success(settings: Settings) -> None:
    """Test successful health check."""
    respx.get(f"{settings.BS_SEARXNG_URL}/").mock(
        return_value=httpx.Response(200, text="OK")
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        is_healthy = await client.health_check()
        assert is_healthy is True
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_health_check_failure(settings: Settings) -> None:
    """Test failed health check."""
    respx.get(f"{settings.BS_SEARXNG_URL}/").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        is_healthy = await client.health_check()
        assert is_healthy is False
    finally:
        await client.disconnect()


@pytest.mark.asyncio
async def test_searxng_health_check_not_connected(settings: Settings) -> None:
    """Test health check when client not connected."""
    client = SearXNGClient(settings)
    # Don't call connect()

    is_healthy = await client.health_check()
    assert is_healthy is False


@pytest.mark.asyncio
async def test_searxng_search_not_connected(settings: Settings) -> None:
    """Test that search fails when client not connected."""
    client = SearXNGClient(settings)
    # Don't call connect()

    request = SearchRequest(query="test")

    with pytest.raises(RuntimeError, match="SearXNG client not connected"):
        await client.search(request, request_id="test-123")


@pytest.mark.asyncio
@respx.mock
async def test_searxng_empty_results(settings: Settings) -> None:
    """Test handling of empty results from SearXNG."""
    mock_response: dict[str, Any] = {"results": []}

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")
        results = await client.search(request, request_id="test-123")

        assert isinstance(results, list)
        assert len(results) == 0
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_domain_whitelist(settings: Settings) -> None:
    """Test domain filtering with whitelist."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Allowed Result 1",
                "url": "https://example.com/page1",
                "content": "Content from example.com",
            },
            {
                "title": "Blocked Result",
                "url": "https://blocked.com/page",
                "content": "Content from blocked.com",
            },
            {
                "title": "Allowed Result 2",
                "url": "https://subdomain.example.com/page2",
                "content": "Content from subdomain",
            },
            {
                "title": "Another Allowed",
                "url": "https://allowed.org/page",
                "content": "Content from allowed.org",
            },
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        # Only allow example.com and allowed.org
        request = SearchRequest(
            query="test",
            options=SearchOptions(domains=["example.com", "allowed.org"]),
        )
        results = await client.search(request, request_id="test-123")

        # Should get 3 results (2 from example.com including subdomain, 1 from allowed.org)
        assert len(results) == 3
        assert results[0].title == "Allowed Result 1"
        assert "example.com" in str(results[0].url)
        assert results[1].title == "Allowed Result 2"
        assert "subdomain.example.com" in str(results[1].url)
        assert results[2].title == "Another Allowed"
        assert "allowed.org" in str(results[2].url)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_domain_blacklist(settings: Settings) -> None:
    """Test domain filtering with blacklist."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Good Result 1",
                "url": "https://example.com/page1",
                "content": "Content from example.com",
            },
            {
                "title": "Spam Result",
                "url": "https://spam.com/page",
                "content": "Spam content",
            },
            {
                "title": "Ads Result",
                "url": "https://ads.example.net/page",
                "content": "Ads content",
            },
            {
                "title": "Good Result 2",
                "url": "https://legitimate.org/page",
                "content": "Legitimate content",
            },
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        # Block spam.com and ads.example.net
        request = SearchRequest(
            query="test",
            options=SearchOptions(
                exclude_domains=["spam.com", "ads.example.net"]),
        )
        results = await client.search(request, request_id="test-123")

        # Should get 2 results (spam.com and ads.example.net blocked)
        assert len(results) == 2
        assert results[0].title == "Good Result 1"
        assert "example.com" in str(results[0].url)
        assert results[1].title == "Good Result 2"
        assert "legitimate.org" in str(results[1].url)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_domain_whitelist_and_blacklist(settings: Settings) -> None:
    """Test domain filtering with both whitelist and blacklist."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Allowed Result",
                "url": "https://example.com/page1",
                "content": "Content from example.com",
            },
            {
                "title": "Blocked by blacklist",
                "url": "https://ads.example.com/page",
                "content": "Ads subdomain",
            },
            {
                "title": "Not in whitelist",
                "url": "https://other.com/page",
                "content": "Other domain",
            },
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        # Whitelist example.com but blacklist ads.example.com
        request = SearchRequest(
            query="test",
            options=SearchOptions(
                domains=["example.com"], exclude_domains=["ads.example.com"]
            ),
        )
        results = await client.search(request, request_id="test-123")

        # Should get only 1 result (example.com allowed, but ads.example.com blocked)
        assert len(results) == 1
        assert results[0].title == "Allowed Result"
        assert "example.com" in str(results[0].url)
        assert "ads.example.com" not in str(results[0].url)
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_invalid_url_scheme_filtered(settings: Settings) -> None:
    """Test that non-http/https URLs are filtered out."""
    mock_response: dict[str, Any] = {
        "results": [
            {
                "title": "Valid HTTP",
                "url": "https://example.com/page1",
                "content": "Valid content",
            },
            {
                "title": "JavaScript URL",
                "url": "javascript:alert('xss')",
                "content": "Malicious content",
            },
            {
                "title": "File URL",
                "url": "file:///etc/passwd",
                "content": "File content",
            },
            {
                "title": "Valid HTTP 2",
                "url": "http://example.org/page",
                "content": "More valid content",
            },
        ]
    }

    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")
        results = await client.search(request, request_id="test-123")

        # Should only get the 2 valid http/https results
        assert len(results) == 2
        assert results[0].title == "Valid HTTP"
        assert results[1].title == "Valid HTTP 2"
    finally:
        await client.disconnect()


@pytest.mark.asyncio
@respx.mock
async def test_searxng_invalid_json_response(settings: Settings) -> None:
    """Test handling of invalid JSON response from SearXNG."""
    respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
        return_value=httpx.Response(200, text="This is not JSON")
    )

    client = SearXNGClient(settings)
    await client.connect()

    try:
        request = SearchRequest(query="test")

        with pytest.raises(ValueError, match="SearXNG returned invalid JSON"):
            await client.search(request, request_id="test-123")
    finally:
        await client.disconnect()
