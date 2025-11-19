from typing import List
from urllib.parse import urlparse

import structlog

from butterscout.config import Settings
from butterscout.models.responses import SearchResult

logger = structlog.get_logger()


class Ranker:
    """Simple ranking system for search results"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.allowed_domains = settings.allowed_domains_list
        self.blocked_domains = settings.blocked_domains_list

    def rank(self, results: List[SearchResult], request_id: str) -> List[SearchResult]:
        """
        Rank and sort search results

        Ranking factors (v0.1 - simple):
        1. Search score from SearXNG (primary)
        2. Domain boosts/blocks from config
        3. Content extraction success (minor boost)

        Args:
            results: List of search results
            request_id: Request ID for logging

        Returns:
            Sorted list of results
        """
        # Filter blocked domains first
        filtered_results = self._filter_blocked_domains(results, request_id)

        # Calculate ranking scores with original index for stable sorting
        scored_results = []
        for idx, result in enumerate(filtered_results):
            score = self._calculate_score(result)
            # Include original index to ensure stable sorting for equal scores
            scored_results.append((score, idx, result))

        # Sort by score (descending), then by original index (ascending) for stability
        scored_results.sort(key=lambda x: (x[0], -x[1]), reverse=True)

        # Update rank numbers
        ranked_results = []
        for rank_idx, (_score, _original_idx, result) in enumerate(scored_results):
            result.scores.rank = rank_idx + 1
            ranked_results.append(result)

        logger.info(
            "ranking_complete",
            request_id=request_id,
            result_count=len(ranked_results),
        )

        return ranked_results

    def _calculate_score(self, result: SearchResult) -> float:
        """
        Calculate ranking score for result

        Args:
            result: Search result

        Returns:
            Ranking score (higher = better)
        """
        # Validate and normalize search score
        try:
            score = float(result.scores.search_score or 0.0)
        except (ValueError, TypeError):
            logger.warning(
                "invalid_search_score",
                url=result.url,
                score=result.scores.search_score,
            )
            score = 0.0

        # Check for NaN or Infinity
        if score != score:  # NaN check
            logger.warning("nan_search_score", url=result.url)
            score = 0.0
        elif score == float("inf") or score == float("-inf"):
            logger.warning("infinite_search_score", url=result.url, score=score)
            score = 1.0 if score > 0 else 0.0

        # Clamp to valid range [0.0, 1.0]
        if score < 0.0:
            logger.warning("negative_search_score", url=result.url, score=score)
            score = 0.0
        elif score > 1.0:
            logger.debug("search_score_above_one", url=result.url, score=score)
            # Don't clamp high scores - allow them to be boosted
            pass

        # Apply domain boost if in allowed list
        if self.allowed_domains:
            domain = urlparse(str(result.url)).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]

            for allowed_domain in self.allowed_domains:
                allowed_clean = allowed_domain.lower()
                if allowed_clean.startswith("www."):
                    allowed_clean = allowed_clean[4:]

                if domain == allowed_clean or domain.endswith(f".{allowed_clean}"):
                    score *= 1.2  # 20% boost
                    break

        # Minor boost for successful extraction
        if result.metadata.extraction_ok and result.content:
            score *= 1.05  # 5% boost

        return score

    def _filter_blocked_domains(
        self, results: List[SearchResult], request_id: str
    ) -> List[SearchResult]:
        """
        Remove results from blocked domains

        Args:
            results: List of results
            request_id: Request ID

        Returns:
            Filtered list
        """
        if not self.blocked_domains:
            return results

        filtered = []
        blocked_count = 0

        for result in results:
            domain = urlparse(str(result.url)).netloc.lower()
            if domain.startswith("www."):
                domain = domain[4:]

            is_blocked = False
            for blocked_domain in self.blocked_domains:
                blocked_clean = blocked_domain.lower()
                if blocked_clean.startswith("www."):
                    blocked_clean = blocked_clean[4:]

                if domain == blocked_clean or domain.endswith(f".{blocked_clean}"):
                    is_blocked = True
                    blocked_count += 1
                    logger.debug(
                        "blocked_domain_filtered",
                        request_id=request_id,
                        url=result.url,
                        domain=domain,
                    )
                    break

            if not is_blocked:
                filtered.append(result)

        if blocked_count > 0:
            logger.info(
                "blocked_domains_removed",
                request_id=request_id,
                blocked_count=blocked_count,
            )

        return filtered
