"""Tests for the Crawl4AI 0.9.x client (POST /crawl)."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx
import pytest
import respx
from httpx import Response
from pydantic import HttpUrl, TypeAdapter

from butterscout.clients.crawl4ai_client import (
    BODY_VISIBILITY_TIMEOUT_MS,
    RESPONSE_GRACE_SECONDS,
    Crawl4AIBusyError,
    Crawl4AIClient,
    Crawl4AIUnavailableError,
)
from butterscout.config import Settings

URL = TypeAdapter(HttpUrl).validate_python("https://example.com/page")


def _crawl_response(
    raw: Any = "", fit: Any = "", success: Any = True, error: str = ""
) -> dict[str, Any]:
    return {
        "success": True,
        "results": [
            {
                "success": success,
                "error_message": error,
                "markdown": {"raw_markdown": raw, "fit_markdown": fit},
            }
        ],
    }


async def _client(settings: Settings) -> Crawl4AIClient:
    client = Crawl4AIClient(settings)
    await client.connect()
    return client


def _crawl_route(settings: Settings) -> respx.Route:
    return respx.post(f"{settings.BS_CRAWL4AI_URL}/crawl")


@respx.mock
async def test_raw_extraction_sends_the_crawl_limits(settings: Settings) -> None:
    route = _crawl_route(settings).mock(
        return_value=Response(200, json=_crawl_response(raw="Whole page as markdown."))
    )
    client = await _client(settings)
    try:
        result = await client.extract(URL, "req", timeout_ms=1500)
    finally:
        await client.disconnect()

    assert result.extraction_ok is True
    assert result.extracted_by == "crawl4ai"
    assert result.content == "Whole page as markdown."
    body = json.loads(route.calls.last.request.content)
    assert body["urls"] == ["https://example.com/page"]
    assert body["crawler_config"]["type"] == "CrawlerRunConfig"
    params = body["crawler_config"]["params"]
    assert 1400 < params["page_timeout"] <= 1500
    # Crawl4AI's post-navigation visibility wait is not covered by page_timeout.
    assert params["body_visibility_timeout"] == BODY_VISIBILITY_TIMEOUT_MS
    assert params["cache_mode"] == "bypass"
    assert "markdown_generator" not in params


@respx.mock
async def test_fit_extraction_requests_pruning_and_returns_fit_markdown(
    settings: Settings,
) -> None:
    route = _crawl_route(settings).mock(
        return_value=Response(200, json=_crawl_response(raw="nav main footer", fit="main"))
    )
    client = await _client(settings)
    try:
        result = await client.extract(URL, "req", markdown_filter="fit")
    finally:
        await client.disconnect()

    assert result.content == "main"
    params = json.loads(route.calls.last.request.content)["crawler_config"]["params"]
    filter_type = params["markdown_generator"]["params"]["content_filter"]["type"]
    assert filter_type == "PruningContentFilterLXML"


@respx.mock
async def test_empty_fit_uses_raw_from_the_same_response(settings: Settings) -> None:
    _crawl_route(settings).mock(
        return_value=Response(200, json=_crawl_response(raw="Short page.", fit="  \n"))
    )
    client = await _client(settings)
    try:
        result = await client.extract(URL, "req", markdown_filter="fit")
    finally:
        await client.disconnect()
    assert result.content == "Short page."


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (_crawl_response(raw=" \n\t "), ValueError),
        (_crawl_response(success=False, error="Page.goto: Timeout 2000ms exceeded."), TimeoutError),
        (_crawl_response(success=False, error="net::ERR_NAME_NOT_RESOLVED"), ValueError),
    ],
)
@respx.mock
async def test_page_failures_stay_page_failures(
    settings: Settings, result: dict[str, Any], expected: type[Exception]
) -> None:
    _crawl_route(settings).mock(return_value=Response(200, json=result))
    client = await _client(settings)
    try:
        with pytest.raises(expected) as info:
            await client.extract(URL, "req")
    finally:
        await client.disconnect()
    assert not isinstance(info.value, (Crawl4AIUnavailableError, Crawl4AIBusyError))


@respx.mock
async def test_url_refused_by_crawl4ai_is_a_page_failure(settings: Settings) -> None:
    _crawl_route(settings).mock(
        return_value=Response(400, json={"detail": "URL blocked (SSRF protection): URL blocked"})
    )
    client = await _client(settings)
    try:
        with pytest.raises(ValueError, match="refused the URL") as info:
            await client.extract(URL, "req")
    finally:
        await client.disconnect()
    assert not isinstance(info.value, Crawl4AIUnavailableError)


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (httpx.ConnectError("refused"), "unreachable"),
        (httpx.ConnectTimeout("no route"), "unreachable"),
        (Response(401, json={"detail": "unauthorized"}), "auth"),
        (Response(403, json={"detail": "forbidden"}), "auth"),
        (Response(500, json={"detail": "boom"}), "server_error"),
        (Response(503, text="unavailable"), "server_error"),
        (
            Response(400, json={"detail": "Rejected config: field 'x' is not permitted"}),
            "api_mismatch",
        ),
        (Response(404, json={"detail": "Not Found"}), "api_mismatch"),
        (Response(422, json={"detail": "bad body"}), "api_mismatch"),
        (Response(200, text="<html>not json</html>"), "api_mismatch"),
        (Response(200, json=["not", "an", "object"]), "api_mismatch"),
        (Response(200, json={"success": True, "results": []}), "api_mismatch"),
        (Response(200, json=_crawl_response(raw="ok", success="false")), "api_mismatch"),
        (Response(200, json=_crawl_response(raw=42)), "api_mismatch"),
        (Response(200, json={"results": [{"success": True, "markdown": []}]}), "api_mismatch"),
        (Response(200, json={"results": [{"success": True, "markdown": ""}]}), "api_mismatch"),
    ],
)
@respx.mock
async def test_service_failures_are_typed_by_reason(
    settings: Settings, response: Any, reason: str
) -> None:
    route = _crawl_route(settings)
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)
    client = await _client(settings)
    try:
        with pytest.raises(Crawl4AIUnavailableError) as info:
            await client.extract(URL, "req")
    finally:
        await client.disconnect()
    assert info.value.reason == reason


@respx.mock
async def test_crawl4ai_shedding_load_is_busy(settings: Settings) -> None:
    _crawl_route(settings).mock(return_value=Response(429, json={"detail": "slow down"}))
    client = await _client(settings)
    try:
        with pytest.raises(Crawl4AIBusyError):
            await client.extract(URL, "req")
    finally:
        await client.disconnect()


@pytest.mark.parametrize("token", [None, "s3cret"])
@respx.mock
async def test_bearer_token_is_sent_only_when_configured(
    settings: Settings, token: str | None
) -> None:
    settings.BS_CRAWL4AI_API_TOKEN = token
    route = _crawl_route(settings).mock(return_value=Response(200, json=_crawl_response(raw="ok")))
    client = await _client(settings)
    try:
        await client.extract(URL, "req")
    finally:
        await client.disconnect()
    auth = route.calls.last.request.headers.get("authorization")
    assert auth == (f"Bearer {token}" if token else None)


class _Gate:
    """Fake /crawl: records each request's params and blocks until released."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.in_flight = 0
        self.most = 0
        self.params: list[dict[str, Any]] = []

    async def post(self, url: str, params: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        self.params.append(params)
        self.in_flight += 1
        self.most = max(self.most, self.in_flight)
        self.entered.set()
        try:
            await self.release.wait()
        finally:
            self.in_flight -= 1
        return {"success": True, "markdown": {"raw_markdown": "ok", "fit_markdown": ""}}


async def test_slot_limit_is_shared_across_concurrent_extracts(settings: Settings) -> None:
    settings.BS_MAX_CONCURRENT_EXTRACTIONS = 2
    client = await _client(settings)
    gate = _Gate()
    client._crawl_one = gate.post  # type: ignore[method-assign]
    try:
        # As if several searches ran at once: one shared client, many extracts.
        tasks = [asyncio.create_task(client.extract(URL, f"req-{i}")) for i in range(5)]
        await gate.entered.wait()
        await asyncio.sleep(0)
        assert gate.in_flight == 2
        gate.release.set()
        await asyncio.gather(*tasks)
    finally:
        await client.disconnect()
    assert gate.most == 2


async def test_minimum_budget_crawls_when_a_slot_is_free(settings: Settings) -> None:
    client = await _client(settings)
    gate = _Gate()
    gate.release.set()
    client._crawl_one = gate.post  # type: ignore[method-assign]
    try:
        result = await client.extract(URL, "req", timeout_ms=500)
    finally:
        await client.disconnect()
    assert result.extraction_ok is True
    assert 450 < gate.params[0]["page_timeout"] <= 500


async def test_slot_wait_is_capped_so_the_crawl_keeps_its_share(settings: Settings) -> None:
    settings.BS_MAX_CONCURRENT_EXTRACTIONS = 1
    client = await _client(settings)
    gate = _Gate()
    client._crawl_one = gate.post  # type: ignore[method-assign]
    try:
        holder = asyncio.create_task(client.extract(URL, "holder", timeout_ms=5000))
        await gate.entered.wait()
        started = time.perf_counter()
        with pytest.raises(Crawl4AIBusyError):
            await client.extract(URL, "waiter", timeout_ms=200)
        # Gave up after half its budget, not the whole of it.
        assert time.perf_counter() - started < 0.19
        gate.release.set()
        await holder
        # The holder released its slot: the next extract gets it with a full budget.
        result = await client.extract(URL, "later", timeout_ms=1000)
    finally:
        await client.disconnect()
    assert result.extraction_ok is True
    assert 900 < gate.params[-1]["page_timeout"] <= 1000


async def test_a_response_that_trickles_past_the_deadline_times_out(settings: Settings) -> None:
    """HTTPX read timeouts reset on every chunk; the hard deadline must still hold."""
    client = await _client(settings)
    assert client.client is not None

    async def trickle(*_args: Any, **_kwargs: Any) -> Response:
        await asyncio.sleep(10)
        raise AssertionError("unreachable")

    client.client.post = trickle  # type: ignore[method-assign]
    started = time.perf_counter()
    try:
        with pytest.raises(TimeoutError):
            await client.extract(URL, "req", timeout_ms=500)
    finally:
        await client.disconnect()
    assert time.perf_counter() - started < 0.5 + RESPONSE_GRACE_SECONDS + 0.2


@respx.mock
async def test_health_probe_renders_inline_page_with_the_search_fit_config(
    settings: Settings,
) -> None:
    def render(request: httpx.Request) -> Response:
        body = json.loads(request.content)
        assert body["urls"][0].startswith("raw:")
        generator = body["crawler_config"]["params"]["markdown_generator"]
        assert generator["params"]["content_filter"]["type"] == "PruningContentFilterLXML"
        text = body["urls"][0].removeprefix("raw:")
        return Response(200, json=_crawl_response(raw=text, fit=text))

    _crawl_route(settings).mock(side_effect=render)
    client = await _client(settings)
    try:
        assert await client.health_check() is True
    finally:
        await client.disconnect()


@pytest.mark.parametrize(
    ("response", "reason"),
    [
        (Response(200, json=_crawl_response(success=False, error="crashed")), "server_error"),
        # Fit came back empty: the filter config no longer works on this Crawl4AI.
        (
            Response(200, json=_crawl_response(raw="butterscout-health-probe", fit="")),
            "api_mismatch",
        ),
        (Response(401, json={"detail": "unauthorized"}), "auth"),
        (httpx.ConnectError("refused"), "unreachable"),
        (httpx.ReadTimeout("stuck"), "unresponsive"),
    ],
)
@respx.mock
async def test_health_probe_reports_why_crawl4ai_is_unusable(
    settings: Settings, response: Any, reason: str
) -> None:
    route = _crawl_route(settings)
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)
    client = await _client(settings)
    try:
        with pytest.raises(Crawl4AIUnavailableError) as info:
            await client.health_check()
    finally:
        await client.disconnect()
    assert info.value.reason == reason


@respx.mock
async def test_crawl4ai_deadline_504_is_a_page_timeout(settings: Settings) -> None:
    """A 504 is Crawl4AI's per-crawl deadline on this page, not Crawl4AI being down."""
    _crawl_route(settings).mock(return_value=Response(504, json={"detail": "timed out"}))
    client = await _client(settings)
    try:
        with pytest.raises(TimeoutError) as info:
            await client.extract(URL, "req")
    finally:
        await client.disconnect()
    assert not isinstance(info.value, (Crawl4AIUnavailableError, Crawl4AIBusyError))


async def test_a_slot_granted_after_the_cutoff_is_not_used(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the grant lands late (event loop stalled), do not crawl with a negative timeout."""
    import butterscout.clients.crawl4ai_client as module

    client = await _client(settings)
    gate = _Gate()
    gate.release.set()
    client._crawl_one = gate.post  # type: ignore[method-assign]
    real = time.perf_counter
    calls = {"n": 0}

    def stalled_clock() -> float:
        calls["n"] += 1
        # First call: start of the attempt. Later calls: the loop resumed 2 s later.
        return real() + (0 if calls["n"] == 1 else 2.0)

    monkeypatch.setattr(module.time, "perf_counter", stalled_clock)
    try:
        with pytest.raises(Crawl4AIBusyError):
            await client.extract(URL, "late", timeout_ms=500)
        monkeypatch.setattr(module.time, "perf_counter", real)
        # No crawl was sent, and the slot was given back.
        assert gate.params == []
        result = await client.extract(URL, "next", timeout_ms=500)
    finally:
        await client.disconnect()
    assert result.extraction_ok is True
    assert gate.params and gate.params[0]["page_timeout"] > 0
