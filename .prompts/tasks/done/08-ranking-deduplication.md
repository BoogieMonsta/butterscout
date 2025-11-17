# Task 08: Ranking & Deduplication

**Role:** You are a senior backend engineer specializing in search relevance, ranking algorithms, and data deduplication strategies.

## Context

Implement URL deduplication and simple ranking logic to order search results by relevance. This includes URL normalization, domain-based filtering, and score-based sorting.

Refer to **[TECH SPEC.md]** §4.1, §4.2, §6 for complete details.

## Deliverables

### 1. URL Deduplication (`butterscout/services/deduplicator.py`)

```python
from typing import List
from urllib.parse import urlparse, parse_qs, urlencode
from butterscout.models.internal import NormalizedSearchResult
import structlog

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

        # Sort query parameters for consistency
        normalized_query = urlencode(sorted(filtered_params.items()))

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
```

### 2. Ranking Service (`butterscout/services/ranker.py`)

```python
from typing import List
from urllib.parse import urlparse
from butterscout.models.responses import SearchResult
from butterscout.config import Settings
import structlog

logger = structlog.get_logger()

class Ranker:
    """Simple ranking system for search results"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.allowed_domains = settings.allowed_domains_list
        self.blocked_domains = settings.blocked_domains_list

    def rank(
        self,
        results: List[SearchResult],
        request_id: str
    ) -> List[SearchResult]:
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

        # Calculate ranking scores
        scored_results = []
        for result in filtered_results:
            score = self._calculate_score(result)
            scored_results.append((score, result))

        # Sort by score (descending)
        scored_results.sort(key=lambda x: x[0], reverse=True)

        # Update rank numbers
        ranked_results = []
        for idx, (score, result) in enumerate(scored_results):
            result.scores.rank = idx + 1
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
        # Start with search score (0.0 - 1.0)
        score = result.scores.search_score

        # Apply domain boost if in allowed list
        if self.allowed_domains:
            domain = urlparse(result.url).netloc.lower().lstrip("www.")
            for allowed_domain in self.allowed_domains:
                allowed_clean = allowed_domain.lower().lstrip("www.")
                if domain == allowed_clean or domain.endswith(f".{allowed_clean}"):
                    score *= 1.2  # 20% boost
                    break

        # Minor boost for successful extraction
        if result.metadata.extraction_ok and result.content:
            score *= 1.05  # 5% boost

        return score

    def _filter_blocked_domains(
        self,
        results: List[SearchResult],
        request_id: str
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
            domain = urlparse(result.url).netloc.lower().lstrip("www.")

            is_blocked = False
            for blocked_domain in self.blocked_domains:
                blocked_clean = blocked_domain.lower().lstrip("www.")
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
```

## Key Implementation Details

### URL Normalization Strategy (TECH SPEC §4.1)

**Normalization steps:**
1. Convert to lowercase
2. Remove `www.` prefix from domain
3. Remove trailing slashes from path
4. Remove common tracking parameters (utm_*, fbclid, gclid, etc.)
5. Sort remaining query parameters alphabetically
6. Keep fragments (may be meaningful)

**Goal:** Same logical page = same normalized URL

### Deduplication Strategy

- Keep **first occurrence** (highest ranked from SearXNG)
- Use normalized URLs for comparison
- Log removed duplicates at debug level

### Simple Ranking (v0.1)

**Ranking factors:**
1. **Search score** (primary) - from SearXNG
2. **Domain whitelist boost** - 20% boost if in `allowed_domains`
3. **Extraction success boost** - 5% boost if content extracted successfully

**Note:** More sophisticated ranking (embeddings, LLM scoring) deferred to v0.2+

### Domain Filtering Integration

- Apply domain filters from config
- Blocked domains removed entirely
- Allowed domains get ranking boost

## Testing Requirements

### Unit Tests (`tests/unit/test_ranking_dedup.py`)

```python
import pytest
from butterscout.services.deduplicator import URLDeduplicator
from butterscout.services.ranker import Ranker

def test_url_normalization():
    """Test URL normalization removes tracking params and normalizes format"""
    assert URLDeduplicator.normalize_url(
        "https://WWW.Example.com/page/?utm_source=google&id=123"
    ) == "https://example.com/page?id=123"

    assert URLDeduplicator.normalize_url(
        "https://example.com/page/"
    ) == "https://example.com/page"

    assert URLDeduplicator.normalize_url(
        "https://example.com/page?b=2&a=1"
    ) == "https://example.com/page?a=1&b=2"

def test_deduplication():
    """Test duplicate URLs are removed"""
    from butterscout.models.internal import NormalizedSearchResult

    results = [
        NormalizedSearchResult(
            title="Page 1",
            url="https://example.com/page",
            snippet="Snippet",
            score=0.9,
        ),
        NormalizedSearchResult(
            title="Page 1 Duplicate",
            url="https://www.example.com/page/",
            snippet="Snippet",
            score=0.8,
        ),
        NormalizedSearchResult(
            title="Page 2",
            url="https://example.com/other",
            snippet="Snippet",
            score=0.7,
        ),
    ]

    deduplicated = URLDeduplicator.deduplicate(results, "test-123")

    assert len(deduplicated) == 2
    assert deduplicated[0].title == "Page 1"  # Keep first occurrence

def test_ranker_applies_domain_boost(settings):
    """Test that allowed domains get ranking boost"""
    settings.BS_ALLOWED_DOMAINS = "example.com"
    ranker = Ranker(settings)

    from butterscout.models.responses import (
        SearchResult, ResultMetadata, ResultScores
    )

    results = [
        SearchResult(
            title="Low score, boosted domain",
            url="https://example.com/page",
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="example.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.5, rank=1),
            source="searxng",
        ),
        SearchResult(
            title="High score, normal domain",
            url="https://other.com/page",
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="other.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.8, rank=2),
            source="searxng",
        ),
    ]

    ranked = ranker.rank(results, "test-123")

    # With 20% boost, 0.5 * 1.2 = 0.6, still less than 0.8
    # So order should be: other.com (0.8), example.com (0.6)
    assert ranked[0].url == "https://other.com/page"
    assert ranked[1].url == "https://example.com/page"

def test_ranker_blocks_domains(settings):
    """Test that blocked domains are removed"""
    settings.BS_BLOCKED_DOMAINS = "spam.com"
    ranker = Ranker(settings)

    results = [
        SearchResult(
            title="Good site",
            url="https://example.com/page",
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="example.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.8, rank=1),
            source="searxng",
        ),
        SearchResult(
            title="Spam site",
            url="https://spam.com/page",
            snippet="",
            content="",
            metadata=ResultMetadata(
                domain="spam.com",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
            ),
            scores=ResultScores(search_score=0.9, rank=2),
            source="searxng",
        ),
    ]

    ranked = ranker.rank(results, "test-123")

    assert len(ranked) == 1
    assert ranked[0].url == "https://example.com/page"
```

## Performance Requirements

- URL normalization: < 1ms per URL
- Deduplication: O(n) time complexity
- Ranking: O(n log n) for sorting
- Support 1000+ results efficiently

## Output Format

When complete, provide:

1. ✅ All files created
2. ✅ Tests passing
3. 📊 Example showing:
   - Before/after deduplication
   - Before/after ranking
   - Domain filtering in action
4. 📝 Performance timing for 100 results

## Dependencies

- **Task 01** (Project Foundation)

## Time Estimate

3-4 hours

## Reference

- [TECH SPEC.md] §4.1: Ranking & Filtering
- [TECH SPEC.md] §4.2: Deduplicate and rank results
- [TECH SPEC.md] §6: Domain filtering
