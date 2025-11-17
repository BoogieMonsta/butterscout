"""Content quality filtering utilities."""
from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from butterscout.models.responses import SearchResult

logger = structlog.get_logger()

MIN_WORD_COUNT = 10  # TECH SPEC §4.1 - filter extremely short content


def filter_low_quality_results(
    results: list[SearchResult],
    request_id: str,
) -> list[SearchResult]:
    """Filter out results with low-quality or empty content.

    Args:
        results: List of search results
        request_id: Request ID for logging

    Returns:
        Filtered list of results
    """
    filtered = []

    for result in results:
        # Keep result if extraction failed (still has snippet)
        if not result.metadata.extraction_ok:
            filtered.append(result)
            continue

        # Filter out results with very short content
        if (
            result.content
            and result.metadata.word_count is not None
            and result.metadata.word_count < MIN_WORD_COUNT
        ):
            logger.debug(
                "filtered_short_content",
                request_id=request_id,
                url=result.url,
                word_count=result.metadata.word_count,
            )
            continue

        filtered.append(result)

    logger.info(
        "content_filtering_complete",
        request_id=request_id,
        original_count=len(results),
        filtered_count=len(filtered),
        removed=len(results) - len(filtered),
    )

    return filtered
