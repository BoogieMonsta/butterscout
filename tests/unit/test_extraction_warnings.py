"""Tests for extraction warnings: which conditions warn, and what the counts say."""

from __future__ import annotations

from typing import Optional

from pydantic import HttpUrl

from butterscout.models.internal import ExtractedContent
from butterscout.services.extraction_warnings import (
    crawl4ai_warnings,
    has_crawl4ai_fault,
    missing_text_warnings,
)


def _page(failure: Optional[str], ok: bool = True) -> ExtractedContent:
    return ExtractedContent(
        url=HttpUrl("https://example.com/"),
        content="text" if ok else "",
        word_count=1 if ok else 0,
        extracted_by="crawl4ai" if failure is None else ("trafilatura" if ok else "none"),
        extraction_ok=ok,
        extraction_time_ms=1,
        crawl4ai_failure=failure,  # type: ignore[arg-type]
    )


def test_no_warning_when_crawl4ai_worked_or_single_pages_failed() -> None:
    assert crawl4ai_warnings([_page(None), _page(None)]) == []
    assert crawl4ai_warnings([_page(None), _page("page", ok=False), _page(None)]) == []
    assert crawl4ai_warnings([]) == []


def test_busy_is_not_a_warning_or_a_fault() -> None:
    pages = [_page("busy"), _page("busy", ok=False), _page(None)]
    assert crawl4ai_warnings(pages) == []
    assert has_crawl4ai_fault(pages) is False


def test_each_service_fault_warns_once_with_its_count() -> None:
    pages = [_page("auth"), _page("auth", ok=False), _page("unreachable"), _page(None)]
    warnings = crawl4ai_warnings(pages)
    assert len(warnings) == 2
    (auth,) = [w for w in warnings if "BS_CRAWL4AI_API_TOKEN" in w]
    (down,) = [w for w in warnings if "could not be reached" in w]
    assert "2 of 4 pages" in auth and "1 of 4 pages" in down
    assert has_crawl4ai_fault(pages) is True


def test_crawl4ai_producing_nothing_warns_whatever_the_reason() -> None:
    # A starved Crawl4AI: every page timed out or queued; no service fault was raised.
    assert crawl4ai_warnings([_page("page"), _page("busy")]) == []  # too few to judge
    pages = [_page("page"), _page("busy"), _page("busy", ok=False)]
    (warning,) = crawl4ai_warnings(pages)
    assert "none of 3 pages" in warning
    assert (
        "1 failed or timed out, 2 busy or throttled" in warning and "text for 2 of them" in warning
    )
    # Weak evidence of a fault: it warns, but does not count as one (cache stays allowed).
    assert has_crawl4ai_fault(pages) is False


def test_one_crawl4ai_success_means_no_starvation_warning() -> None:
    assert crawl4ai_warnings([_page("page"), _page("busy"), _page(None)]) == []


def test_warnings_never_include_raw_error_text() -> None:
    page = _page("server_error").model_copy(update={"error": "http://crawl4ai:11235 exploded"})
    assert "11235" not in " ".join(crawl4ai_warnings([page]))


def test_missing_text_warns_from_half_the_results() -> None:
    assert missing_text_warnings(with_text=5, total=5) == []
    assert missing_text_warnings(with_text=3, total=5) == []
    (warning,) = missing_text_warnings(with_text=2, total=4)
    assert warning.startswith("2 of 4 results have no page text")
    assert missing_text_warnings(with_text=0, total=1)
    assert missing_text_warnings(with_text=0, total=0) == []
