"""Factual warnings for when extraction was degraded.

Falling back to Trafilatura keeps results coming but hides the failure: nobody learns
that the main extractor is down, or that results came back as bare snippets. These
warnings travel in the response (the MCP instructions tell agents to relay them). They
are fixed strings: raw extractor errors can carry internal service URLs. A page that
waited too long for a Crawl4AI slot ("busy") is counted in metrics, not warned about,
unless Crawl4AI produced none of the pages at all.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from butterscout.models.internal import CRAWL4AI_FAULTS, ExtractedContent

_FAULTS = {
    "unreachable": "Crawl4AI could not be reached",
    "unresponsive": "Crawl4AI did not respond in time",
    "auth": "Crawl4AI rejected Butterscout's token (check BS_CRAWL4AI_API_TOKEN)",
    "server_error": "Crawl4AI returned server errors",
    "api_mismatch": "Crawl4AI rejected the request format (Crawl4AI version mismatch?)",
}
# One page failing is normal (bot walls, slow sites). Crawl4AI producing none of several
# pages usually is not: e.g. a starved Crawl4AI times out or queues on every page without
# raising a service fault. Weak evidence of an outage, so it warns but does not block caching.
_NONE_PRODUCED_MIN = 3


def has_crawl4ai_fault(contents: Sequence[ExtractedContent]) -> bool:
    """True when Crawl4AI itself failed for any of these pages."""
    return any(c.crawl4ai_failure in CRAWL4AI_FAULTS for c in contents)


def crawl4ai_warnings(contents: Sequence[ExtractedContent]) -> list[str]:
    """Warnings about Crawl4AI failing as a service (or on every page)."""
    total = len(contents)
    counts: Counter[str] = Counter(c.crawl4ai_failure for c in contents if c.crawl4ai_failure)
    warnings = [
        f"{cause} for {counts[key]} of {total} pages; their text came from the fallback "
        "extractor or is missing."
        for key, cause in _FAULTS.items()
        if counts[key]
    ]
    if total >= _NONE_PRODUCED_MIN and not warnings and all(c.crawl4ai_failure for c in contents):
        rescued = sum(c.extraction_ok for c in contents)
        warnings.append(
            f"Crawl4AI produced none of {total} pages ({counts['page']} failed or timed out, "
            f"{counts['busy']} busy or throttled); the fallback extractor "
            f"supplied text for {rescued} of them."
        )
    return warnings


def missing_text_warnings(with_text: int, total: int) -> list[str]:
    """A warning when at least half the returned results have no page text."""
    missing = total - with_text
    if total and missing * 2 >= total:
        return [f"{missing} of {total} results have no page text, only the search snippet."]
    return []
