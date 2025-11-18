from typing import List
from urllib.parse import parse_qs, urlencode, urlparse

import structlog

from butterscout.models.internal import NormalizedSearchResult

logger = structlog.get_logger()

class URLDeduplicator:
    """Deduplicate search results by normalized URL"""

    @staticmethod
    def normalize_url(url: str) -> str:
        """
        Normalize URL for deduplication

        - Convert to lowercase
        - Remove www. prefix
        - Remove trailing slashes
        - Remove common tracking parameters
        - Sort query parameters

        Args:
            url: Raw URL

        Returns:
            Normalized URL string
        """
        parsed = urlparse(url.lower())

        # Remove www. prefix from domain
        domain = parsed.netloc
        if domain.startswith("www."):
            domain = domain[4:]

        # Remove common tracking parameters
        tracking_params = {
            "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
            "fbclid", "gclid", "msclkid",
            "ref", "referrer", "source",
        }

        query_params = parse_qs(parsed.query)
        filtered_params = {
            k: v for k, v in query_params.items()
            if k not in tracking_params
        }

        # Flatten list values and sort for deterministic output
        # parse_qs returns {'key': ['value']} so we need to flatten
        sorted_params = []
        for k, v_list in sorted(filtered_params.items()):
            for v in sorted(v_list):  # Also sort values for multi-value params
                sorted_params.append((k, v))

        normalized_query = urlencode(sorted_params)

        # Remove trailing slash from path
        path = parsed.path.rstrip("/") if parsed.path != "/" else ""

        # Reconstruct URL
        normalized = f"{parsed.scheme}://{domain}{path}"
        if normalized_query:
            normalized += f"?{normalized_query}"
        if parsed.fragment:
            normalized += f"#{parsed.fragment}"

        return normalized

    @staticmethod
    def deduplicate(
        results: List[NormalizedSearchResult],
        request_id: str
    ) -> List[NormalizedSearchResult]:
        """
        Remove duplicate URLs from results

        Keep the first occurrence (highest ranked from search)

        Args:
            results: List of search results
            request_id: Request ID for logging

        Returns:
            Deduplicated list
        """
        seen_urls = set()
        deduplicated = []

        for result in results:
            normalized = URLDeduplicator.normalize_url(str(result.url))

            if normalized not in seen_urls:
                seen_urls.add(normalized)
                deduplicated.append(result)
            else:
                logger.debug(
                    "duplicate_url_removed",
                    request_id=request_id,
                    url=str(result.url),
                    normalized=normalized,
                )

        logger.info(
            "deduplication_complete",
            request_id=request_id,
            original_count=len(results),
            deduplicated_count=len(deduplicated),
            removed=len(results) - len(deduplicated),
        )

        return deduplicated
