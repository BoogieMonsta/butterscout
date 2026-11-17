"""Tests for the MCP Streamable HTTP endpoint at /mcp."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from butterscout.main import app
from butterscout.models.internal import ExtractedContent, NormalizedSearchResult
from butterscout.state import app_state

BASE_URL = "http://localhost:8000"
ACCEPT = {"Accept": "application/json, text/event-stream"}
PROTOCOL = "2025-11-25"
DENY = (False, 30, 0, 60, 1234567890)


@contextmanager
def mcp_client(**settings: Any) -> Iterator[TestClient]:
    update = {"BS_MCP_ENABLED": True, "BS_API_KEY": None, "BS_MAX_RESULTS": 10}
    update.update(settings)
    with patch.object(app_state, "settings", app_state.settings.model_copy(update=update)):
        with TestClient(app, base_url=BASE_URL, follow_redirects=False) as client:
            yield client


def rpc(
    client: TestClient,
    method: str,
    params: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    path: str = "/mcp",
) -> Any:
    sent = {**ACCEPT, "MCP-Protocol-Version": PROTOCOL}
    if method == "initialize":
        sent.pop("MCP-Protocol-Version")
    sent.update(headers or {})
    return client.post(
        path,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers=sent,
    )


def call_tool(client: TestClient, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    response = rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.text
    result: dict[str, Any] = response.json()["result"]
    return result


def init_params(version: str = PROTOCOL) -> dict[str, Any]:
    return {
        "protocolVersion": version,
        "capabilities": {},
        "clientInfo": {"name": "pytest", "version": "1"},
    }


def test_mcp_is_404_when_disabled() -> None:
    with mcp_client(BS_MCP_ENABLED=False) as client:
        response = rpc(client, "initialize", init_params())
    assert response.status_code == 404


@pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"])
def test_initialize_is_200_without_redirect(version: str) -> None:
    with mcp_client() as client:
        response = rpc(client, "initialize", init_params(version))
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["protocolVersion"] == version
    assert result["serverInfo"]["name"] == "butterscout"


def test_trailing_slash_redirects_to_canonical_path() -> None:
    with mcp_client() as client:
        response = rpc(client, "initialize", init_params(), path="/mcp/")
    assert response.status_code == 307
    assert response.headers["location"].endswith("/mcp")


def test_tools_list_exposes_both_tools_with_schemas() -> None:
    with mcp_client() as client:
        response = rpc(client, "tools/list")
    assert response.status_code == 200, response.text
    tools = {tool["name"]: tool for tool in response.json()["result"]["tools"]}
    assert set(tools) == {"butterscout_search", "butterscout_extract"}
    assert tools["butterscout_search"]["inputSchema"]["required"] == ["query"]
    assert tools["butterscout_extract"]["inputSchema"]["required"] == ["url"]
    assert "ctx" not in tools["butterscout_search"]["inputSchema"]["properties"]
    assert tools["butterscout_search"]["annotations"]["readOnlyHint"] is True


def test_search_tool_returns_clipped_structured_results() -> None:
    long_text = "word " * 3000  # 15000 chars
    with mcp_client() as client:
        with (
            patch.object(
                app_state.searxng_client,
                "search",
                AsyncMock(
                    return_value=[
                        NormalizedSearchResult(
                            title="FastAPI",
                            url=HttpUrl("https://fastapi.tiangolo.com/"),
                            snippet="FastAPI framework",
                            score=0.9,
                        )
                    ]
                ),
            ),
            patch.object(
                app_state.extraction_strategy,
                "extract",
                AsyncMock(
                    return_value=ExtractedContent(
                        url=HttpUrl("https://fastapi.tiangolo.com/"),
                        content=long_text,
                        word_count=3000,
                        extracted_by="crawl4ai",
                        extraction_ok=True,
                        extraction_time_ms=5,
                    )
                ),
            ),
        ):
            result = call_tool(
                client, "butterscout_search", {"query": "fastapi docs", "max_results": 2}
            )
    assert result["isError"] is False
    data = result["structuredContent"]
    assert data["query"] == "fastapi docs"
    assert data["result_count"] == 1
    first = data["results"][0]
    assert first["url"] == "https://fastapi.tiangolo.com/"
    assert len(first["content"]) == 4000
    assert first["content_truncated"] is True


def test_search_tool_caps_max_results_at_server_limit() -> None:
    with mcp_client(BS_MAX_RESULTS=3) as client:
        result = call_tool(client, "butterscout_search", {"query": "x", "max_results": 25})
    assert result["isError"] is False
    assert result["structuredContent"]["max_results_applied"] == 3


def test_search_tool_rejects_bad_arguments() -> None:
    with mcp_client() as client:
        result = call_tool(client, "butterscout_search", {"query": "x", "max_results": 99})
    assert result["isError"] is True


def test_extract_tool_returns_content() -> None:
    with mcp_client() as client:
        result = call_tool(client, "butterscout_extract", {"url": "https://93.184.216.34/page"})
    assert result["isError"] is False, result
    data = result["structuredContent"]
    assert data["content"] == "Stubbed content"
    assert data["metadata"]["extracted_by"] == "crawl4ai"


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:6379/", "http://localhost/", "http://169.254.169.254/latest", "ftp://x.io/"],
)
def test_extract_tool_refuses_unsafe_urls(url: str) -> None:
    with mcp_client() as client:
        with patch.object(app_state.extraction_strategy, "extract", AsyncMock()) as extract:
            result = call_tool(client, "butterscout_extract", {"url": url})
    assert result["isError"] is True
    extract.assert_not_called()


def test_rate_limit_surfaces_as_tool_error() -> None:
    with mcp_client() as client:
        with patch(
            "butterscout.services.rate_limiter.RateLimiter.check_rate_limit",
            new=AsyncMock(return_value=DENY),
        ):
            result = call_tool(client, "butterscout_extract", {"url": "https://93.184.216.34/"})
    assert result["isError"] is True
    assert "rate limit" in result["content"][0]["text"].lower()
    assert "30s" in result["content"][0]["text"]


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 401),
        ({"x-api-key": "wrong"}, 401),
        ({"Authorization": "Bearer wrong"}, 401),
        ({"x-api-key": "secret"}, 200),
        ({"Authorization": "Bearer secret"}, 200),
    ],
)
def test_api_key_gate(headers: dict[str, str], status: int) -> None:
    with mcp_client(BS_API_KEY="secret") as client:
        response = rpc(client, "initialize", init_params(), headers=headers)
    assert response.status_code == status
    if status == 401:
        assert response.headers["WWW-Authenticate"].startswith("Bearer")


def test_api_key_is_passed_to_tools() -> None:
    with mcp_client(BS_API_KEY="secret") as client:
        response = rpc(
            client,
            "tools/call",
            {"name": "butterscout_extract", "arguments": {"url": "https://93.184.216.34/"}},
            headers={"Authorization": "Bearer secret"},
        )
    assert response.status_code == 200
    assert response.json()["result"]["isError"] is False


@pytest.mark.parametrize(
    "headers",
    [
        {"Host": "evil.example"},
        {"Origin": "http://evil.example"},
        {"Origin": "http://localhost:3000"},
    ],
)
def test_dns_rebinding_protection_rejects_foreign_host_or_origin(headers: dict[str, str]) -> None:
    with mcp_client() as client:
        response = rpc(client, "initialize", init_params(), headers=headers)
    assert response.status_code in (403, 421), response.text


def test_sequential_lifespans_each_get_a_working_manager() -> None:
    for _ in range(3):
        with mcp_client() as client:
            response = rpc(client, "initialize", init_params())
            assert response.status_code == 200
        assert app_state.mcp_session_manager is None
