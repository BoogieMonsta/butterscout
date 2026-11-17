"""Characterization tests for POST /api/v1/extract.

These pin the observable HTTP contract (status, body shape, headers, check order) so the
extract logic can move into a shared service without changing behaviour. They patch the
shared ``app_state`` object and the ``RateLimiter`` class itself, not router-local names.
"""

from __future__ import annotations

from typing import Any, Generator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import HttpUrl

from butterscout.main import app  # also loads settings into app_state
from butterscout.models.internal import ExtractedContent
from butterscout.state import app_state

PUBLIC_URL = "https://93.184.216.34/page"
ALLOW = (True, None, 59, 60, 1234567890)
DENY = (False, 30, 0, 60, 1234567890)


def _settings(**update: Any) -> Any:
    base = {
        "BS_API_KEY": None,
        "BS_ALLOWED_DOMAINS": "",
        "BS_BLOCKED_DOMAINS": "",
        "BS_REQUEST_TIMEOUT_MS": 6000,
    }
    base.update(update)
    return app_state.settings.model_copy(update=base)


@pytest.fixture
def extract_env() -> Generator[MagicMock, None, None]:
    strategy = MagicMock()
    strategy.extract = AsyncMock(
        return_value=ExtractedContent(
            url=HttpUrl(PUBLIC_URL),
            content="  # Example\n\nExtracted text  ",
            word_count=3,
            extracted_by="crawl4ai",
            extraction_ok=True,
            extraction_time_ms=42,
        )
    )
    with (
        patch.object(app_state, "settings", _settings()),
        patch.object(app_state, "redis_client", MagicMock(), create=True),
        patch.object(app_state, "extraction_strategy", strategy, create=True),
    ):
        yield strategy


def _post(
    body: dict[str, Any],
    limiter: tuple[Any, ...] = ALLOW,
    headers: Optional[dict[str, str]] = None,
) -> Any:
    with patch(
        "butterscout.services.rate_limiter.RateLimiter.check_rate_limit",
        new=AsyncMock(return_value=limiter),
    ):
        client = TestClient(app, raise_server_exceptions=False)
        return client.post("/api/v1/extract", json=body, headers=headers or {})


def test_success_shape_and_rate_limit_headers(extract_env: MagicMock) -> None:
    response = _post({"url": PUBLIC_URL})
    assert response.status_code == 200
    data = response.json()
    assert data == {
        "url": PUBLIC_URL,
        "canonical_url": PUBLIC_URL,
        "title": "93.184.216.34",
        "content": "# Example\n\nExtracted text",
        "metadata": {
            "domain": "93.184.216.34",
            "word_count": 4,
            "extracted_by": "crawl4ai",
            "extraction_ok": True,
            "extraction_error": None,
            "extraction_time_ms": 42,
        },
    }
    assert response.headers["X-RateLimit-Limit"] == "60"
    assert response.headers["X-RateLimit-Remaining"] == "59"
    assert response.headers["X-RateLimit-Reset"] == "1234567890"


def test_max_characters_truncates(extract_env: MagicMock) -> None:
    extract_env.extract.return_value = ExtractedContent(
        url=HttpUrl(PUBLIC_URL),
        content="x" * 5000,
        word_count=1,
        extracted_by="trafilatura",
        extraction_ok=True,
        extraction_time_ms=1,
    )
    response = _post({"url": PUBLIC_URL, "max_characters": 1000})
    assert response.status_code == 200
    assert len(response.json()["content"]) == 1000


def test_timeout_is_capped_by_request_timeout(extract_env: MagicMock) -> None:
    with patch.object(app_state, "settings", _settings(BS_REQUEST_TIMEOUT_MS=1000)):
        _post({"url": PUBLIC_URL, "extract_timeout_ms": 6000})
    assert extract_env.extract.await_args.kwargs["timeout_ms"] == 1000


def test_non_http_scheme_is_422_from_model(extract_env: MagicMock) -> None:
    response = _post({"url": "ftp://example.com/"})
    assert response.status_code == 422
    extract_env.extract.assert_not_called()


@pytest.mark.parametrize(
    ("url", "detail"),
    [
        ("https://user:pw@93.184.216.34/", "URLs with embedded credentials are not allowed"),
        ("http://localhost:8000/", "URL points to a local or private host"),
        ("http://127.0.0.1:8000/", "URL resolves to a local or private address"),
        ("http://169.254.169.254/latest", "URL resolves to a local or private address"),
        ("http://10.0.0.1/", "URL resolves to a local or private address"),
    ],
)
def test_unsafe_urls_are_400_detail(extract_env: MagicMock, url: str, detail: str) -> None:
    response = _post({"url": url})
    assert response.status_code == 400
    assert response.json() == {"detail": detail}
    extract_env.extract.assert_not_called()


def test_blocked_domain_is_403_detail(extract_env: MagicMock) -> None:
    with patch.object(app_state, "settings", _settings(BS_BLOCKED_DOMAINS="93.184.216.34")):
        response = _post({"url": PUBLIC_URL})
    assert response.status_code == 403
    assert response.json() == {"detail": "Domain is not allowed"}
    extract_env.extract.assert_not_called()


def test_rate_limit_is_429_envelope_and_checked_first(extract_env: MagicMock) -> None:
    response = _post({"url": "http://127.0.0.1/"}, limiter=DENY)
    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["error"]["details"] == {"retry_after_ms": 30000}
    assert response.headers["Retry-After"] == "30"
    assert response.headers["X-RateLimit-Remaining"] == "0"


def test_missing_key_is_401_envelope_before_url_checks(extract_env: MagicMock) -> None:
    with patch.object(app_state, "settings", _settings(BS_API_KEY="secret")):
        response = _post({"url": "http://127.0.0.1/"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.headers["WWW-Authenticate"] == 'ApiKey realm="Butterscout API"'
    assert response.headers["X-RateLimit-Limit"] == "60"


def test_x_api_key_is_accepted(extract_env: MagicMock) -> None:
    with patch.object(app_state, "settings", _settings(BS_API_KEY="secret")):
        response = _post({"url": PUBLIC_URL}, headers={"x-api-key": "secret"})
    assert response.status_code == 200


def test_upstream_failure_is_502_envelope(extract_env: MagicMock) -> None:
    extract_env.extract.return_value = ExtractedContent(
        url=HttpUrl(PUBLIC_URL),
        content="",
        word_count=0,
        extracted_by="none",
        extraction_ok=False,
        extraction_time_ms=5,
        error="timeout",
    )
    response = _post({"url": PUBLIC_URL})
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "UPSTREAM_ERROR"
    assert body["error"]["message"] == "timeout"
    assert body["error"]["details"] == {"component": "extract", "timeout": True}
    assert response.headers["X-RateLimit-Limit"] == "60"
