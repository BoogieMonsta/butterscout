"""Unit tests for health endpoint."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_health_endpoint_structure_mocked() -> None:
    """Test health endpoint returns correct structure with mocked dependencies."""
    # Mock the clients
    with patch("butterscout.main.app_state") as mock_app_state:
        # Setup mock settings
        mock_settings = MagicMock()
        mock_settings.BS_HEALTH_TIMEOUT_MS = 750
        mock_app_state.settings = mock_settings

        # Setup mock clients with successful health checks
        mock_app_state.redis_client.ping = AsyncMock(return_value=True)
        mock_app_state.cache_backend.health_check = AsyncMock(return_value=True)
        mock_app_state.searxng_client.health_check = AsyncMock(return_value=True)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(return_value=True)

        # Import after patching to avoid import errors
        from fastapi import Response

        from butterscout.routers.health import health_check

        response = Response()
        result = await health_check(response)

        # Verify structure
        assert result.status == "healthy"
        assert "valkey" in result.components
        assert "cache" in result.components
        assert "searxng" in result.components
        assert "crawl4ai" in result.components
        assert result.version == "0.1.0"
        assert result.uptime_seconds >= 0
        assert result.timestamp > 0
        assert response.status_code == 200

        # Verify component status
        assert result.components["valkey"].status == "ok"
        assert result.components["cache"].status == "ok"
        assert result.components["searxng"].status == "ok"
        assert result.components["crawl4ai"].status == "ok"


@pytest.mark.asyncio
async def test_health_endpoint_degraded_state() -> None:
    """Test health endpoint returns 503 when a component is down."""
    with patch("butterscout.main.app_state") as mock_app_state:
        # Setup mock settings
        mock_settings = MagicMock()
        mock_settings.BS_HEALTH_TIMEOUT_MS = 750
        mock_app_state.settings = mock_settings

        # Setup mock clients - redis is down
        mock_app_state.redis_client.ping = AsyncMock(return_value=False)
        mock_app_state.cache_backend.health_check = AsyncMock(return_value=True)
        mock_app_state.searxng_client.health_check = AsyncMock(return_value=True)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(return_value=True)

        from fastapi import Response

        from butterscout.routers.health import health_check

        response = Response()
        result = await health_check(response)

        # Verify degraded state
        assert result.status == "degraded"
        assert response.status_code == 503
        assert result.components["valkey"].status == "down"
        assert result.components["cache"].status == "ok"
        assert result.components["searxng"].status == "ok"
        assert result.components["crawl4ai"].status == "ok"


@pytest.mark.asyncio
async def test_health_endpoint_timeout_handling() -> None:
    """Test health endpoint handles timeouts correctly."""
    with patch("butterscout.main.app_state") as mock_app_state:
        # Setup mock settings
        mock_settings = MagicMock()
        mock_settings.BS_HEALTH_TIMEOUT_MS = 750
        mock_app_state.settings = mock_settings

        # Setup mock clients - redis times out
        import asyncio

        async def timeout_func() -> bool:
            await asyncio.sleep(2)  # Simulate timeout
            return True

        mock_app_state.redis_client.ping = timeout_func
        mock_app_state.cache_backend.health_check = AsyncMock(return_value=True)
        mock_app_state.searxng_client.health_check = AsyncMock(return_value=True)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(return_value=True)

        from fastapi import Response

        from butterscout.routers.health import health_check

        response = Response()
        result = await health_check(response)

        # Verify timeout is handled
        assert result.status == "degraded"
        assert response.status_code == 503
        assert result.components["valkey"].status == "down"
        assert result.components["valkey"].error == "Timeout"


@pytest.mark.asyncio
async def test_health_reports_why_crawl4ai_is_unusable() -> None:
    """A failed browser probe marks Crawl4AI down with its reason, not just "failed"."""
    from butterscout.clients.crawl4ai_client import Crawl4AIUnavailableError

    with patch("butterscout.main.app_state") as mock_app_state:
        mock_app_state.settings = MagicMock(BS_HEALTH_TIMEOUT_MS=750)
        mock_app_state.redis_client.ping = AsyncMock(return_value=True)
        mock_app_state.cache_backend.health_check = AsyncMock(return_value=True)
        mock_app_state.searxng_client.health_check = AsyncMock(return_value=True)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(
            side_effect=Crawl4AIUnavailableError("auth", "HTTP 401; check BS_CRAWL4AI_API_TOKEN")
        )
        from fastapi import Response

        from butterscout.routers.health import health_check

        response = Response()
        result = await health_check(response)

    assert result.status == "degraded"
    assert response.status_code == 503
    crawl4ai = result.components["crawl4ai"]
    assert crawl4ai.status == "down"
    assert crawl4ai.error is not None and "BS_CRAWL4AI_API_TOKEN" in crawl4ai.error


def test_liveness_does_not_depend_on_crawl4ai() -> None:
    """Container healthchecks hit /health/live: Crawl4AI down must not take the API down."""
    from fastapi.testclient import TestClient

    from butterscout.main import app

    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def _mocked_state(mock_app_state: MagicMock) -> None:
    mock_app_state.settings = MagicMock(BS_HEALTH_TIMEOUT_MS=750)
    mock_app_state.redis_client.ping = AsyncMock(return_value=True)
    mock_app_state.cache_backend.health_check = AsyncMock(return_value=True)
    mock_app_state.searxng_client.health_check = AsyncMock(return_value=True)
    mock_app_state.crawl4ai_client.health_check = AsyncMock(return_value=True)


def _dependency_calls(mock_app_state: MagicMock) -> list[int]:
    return [
        mock_app_state.redis_client.ping.await_count,
        mock_app_state.cache_backend.health_check.await_count,
        mock_app_state.searxng_client.health_check.await_count,
        mock_app_state.crawl4ai_client.health_check.await_count,
    ]


def test_a_flood_of_health_calls_refreshes_once() -> None:
    """/health is public and renders a browser page; repeated calls reuse one result."""
    from fastapi.testclient import TestClient

    from butterscout.main import app

    with patch("butterscout.main.app_state") as mock_app_state:
        _mocked_state(mock_app_state)
        client = TestClient(app)
        responses = [client.get("/health") for _ in range(20)]

    assert {r.status_code for r in responses} == {200}
    assert _dependency_calls(mock_app_state) == [1, 1, 1, 1]


@pytest.mark.asyncio
async def test_a_failing_probe_is_cached_with_its_reason_too() -> None:
    from fastapi import Response

    from butterscout.clients.crawl4ai_client import Crawl4AIUnavailableError
    from butterscout.routers.health import health_check

    with patch("butterscout.main.app_state") as mock_app_state:
        _mocked_state(mock_app_state)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(
            side_effect=Crawl4AIUnavailableError("unresponsive", "probe did not finish in time")
        )
        first, second = Response(), Response()
        a = await health_check(first)
        b = await health_check(second)

    assert first.status_code == second.status_code == 503
    assert a is b
    assert a.components["crawl4ai"].error is not None
    assert "unresponsive" in a.components["crawl4ai"].error
    assert mock_app_state.crawl4ai_client.health_check.await_count == 1


@pytest.mark.asyncio
async def test_callers_during_a_refresh_do_not_start_another() -> None:
    from fastapi import Response

    from butterscout.routers.health import health_check

    gate = asyncio.Event()

    async def slow_probe() -> bool:
        await gate.wait()
        return True

    with patch("butterscout.main.app_state") as mock_app_state:
        _mocked_state(mock_app_state)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(side_effect=slow_probe)
        refresh = asyncio.create_task(health_check(Response()))
        await asyncio.sleep(0)
        waiting = Response()
        during = await health_check(waiting)
        gate.set()
        await refresh

    assert waiting.status_code == 503 and during.status == "refreshing"
    assert mock_app_state.crawl4ai_client.health_check.await_count == 1


@pytest.mark.asyncio
async def test_after_the_cooldown_a_new_refresh_sees_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import Response

    import butterscout.routers.health as health

    monkeypatch.setattr(health, "REFRESH_COOLDOWN_SECONDS", 0.05)
    with patch("butterscout.main.app_state") as mock_app_state:
        _mocked_state(mock_app_state)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(return_value=False)
        down = Response()
        await health.health_check(down)
        mock_app_state.crawl4ai_client.health_check = AsyncMock(return_value=True)
        still_cached = Response()
        await health.health_check(still_cached)
        await asyncio.sleep(0.06)
        recovered = Response()
        body = await health.health_check(recovered)

    assert (down.status_code, still_cached.status_code, recovered.status_code) == (503, 503, 200)
    assert body.status == "healthy"


@pytest.mark.asyncio
async def test_a_cancelled_refresh_drops_the_old_snapshot_and_keeps_the_cooldown() -> None:
    """Otherwise repeated cancellations could keep serving an old 200 forever."""
    from fastapi import Response

    from butterscout.routers.health import _snapshot, health_check

    gate = asyncio.Event()
    entered = asyncio.Event()

    async def stuck_probe() -> bool:
        entered.set()
        await gate.wait()
        return True

    with patch("butterscout.main.app_state") as mock_app_state:
        _mocked_state(mock_app_state)
        await health_check(Response())  # a good snapshot exists
        _snapshot.next_refresh_at = 0.0  # cooldown over: the next call refreshes
        mock_app_state.crawl4ai_client.health_check = AsyncMock(side_effect=stuck_probe)
        refresh = asyncio.create_task(health_check(Response()))
        await entered.wait()
        refresh.cancel()
        with pytest.raises(asyncio.CancelledError):
            await refresh
        after = Response()
        body = await health_check(after)

    assert after.status_code == 503 and body.status == "refreshing"
    assert mock_app_state.crawl4ai_client.health_check.await_count == 1


def test_a_stalled_crawl4ai_is_reported_by_the_real_probe_once() -> None:
    """Real client, stalled transport: the probe's own reason must survive (a second timer
    in the router would cancel it first) and the cooldown must hold."""
    import httpx
    from fastapi.testclient import TestClient

    from butterscout.clients.crawl4ai_client import Crawl4AIClient
    from butterscout.config import Settings
    from butterscout.main import app

    calls: list[str] = []

    async def stalled(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        await asyncio.sleep(5)
        return httpx.Response(200, json={})

    settings = Settings(BS_CRAWL4AI_URL="http://crawl4ai:11235", BS_HEALTH_TIMEOUT_MS=150)
    with patch("butterscout.main.app_state") as mock_app_state:
        _mocked_state(mock_app_state)
        mock_app_state.settings = settings
        crawl4ai = Crawl4AIClient(settings)
        crawl4ai.client = httpx.AsyncClient(transport=httpx.MockTransport(stalled))
        mock_app_state.crawl4ai_client = crawl4ai
        client = TestClient(app)
        first = client.get("/health")
        second = client.get("/health")
        live = client.get("/health/live")

    assert first.status_code == second.status_code == 503
    error = first.json()["components"]["crawl4ai"]["error"]
    assert "unresponsive" in error
    assert second.json() == first.json()
    assert calls == ["/crawl"]
    assert live.status_code == 200
