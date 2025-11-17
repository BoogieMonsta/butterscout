"""Result assembler for combining search and extraction results."""
from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast
from urllib.parse import urlparse

from pydantic import HttpUrl
import structlog

if TYPE_CHECKING:
    from butterscout.models.internal import ExtractedContent, NormalizedSearchResult
    from butterscout.models.responses import SearchResult

logger = structlog.get_logger()


class ResultAssembler:
    """Assembles final search results from SERP + extracted content."""

    @staticmethod
    def assemble(
        search_results: list[NormalizedSearchResult],
        extracted_contents: list[ExtractedContent],
        include_content: bool,
        request_id: str,
    ) -> list[SearchResult]:
        """Combine search results with extracted content.

        Args:
            search_results: Normalized SERP results
            extracted_contents: Extracted page contents
            include_content: Whether to include full content
            request_id: Request ID for logging

        Returns:
            List of complete SearchResult objects
        """
        from butterscout.models.responses import ResultMetadata, ResultScores, SearchResult

        # Create URL -> ExtractedContent mapping
        content_map = {str(ec.url): ec for ec in extracted_contents}

        results = []

        for idx, search_result in enumerate(search_results):
            url_str = str(search_result.url)
            extracted = content_map.get(url_str)

            def _normalized_extractor(value: str | None) -> Literal["crawl4ai", "trafilatura", "none"]:
                if value in ("crawl4ai", "trafilatura"):
                    return cast(Literal["crawl4ai", "trafilatura"], value)
                return "none"

            # Determine extraction status
            if extracted and extracted.extraction_ok:
                extracted_by: Literal["crawl4ai", "trafilatura", "none"] = _normalized_extractor(
                    extracted.extracted_by
                )
                extraction_metadata = ResultMetadata(
                    domain=urlparse(url_str).netloc,
                    word_count=extracted.word_count,
                    extracted_by=extracted_by,
                    extraction_ok=True,
                )
                content = extracted.content if include_content else None
            else:
                # Extraction failed or not attempted
                extracted_by = _normalized_extractor(extracted.extracted_by if extracted else None)
                extraction_metadata = ResultMetadata(
                    domain=urlparse(url_str).netloc,
                    word_count=0,
                    extracted_by=extracted_by,
                    extraction_ok=False,
                )
                content = None

            # Create final result
            result = SearchResult(
                title=search_result.title,
                url=search_result.url,
                snippet=search_result.snippet,
                content=content,
                metadata=extraction_metadata,
                scores=ResultScores(
                    search_score=search_result.score,
                    rank=idx + 1,
                ),
                source=cast(Literal["searxng"], search_result.source),
            )

            results.append(result)

        logger.info(
            "results_assembled",
            request_id=request_id,
            total_results=len(results),
            with_content=sum(1 for r in results if r.content),
        )

        return results
