"""Demo of extraction orchestrator with graceful degradation."""
import asyncio
import time
from unittest.mock import AsyncMock

from butterscout.config import Settings
from butterscout.models.internal import ExtractedContent, NormalizedSearchResult
from butterscout.services.extraction_orchestrator import ExtractionOrchestrator
from butterscout.services.result_assembler import ResultAssembler
from butterscout.utils.content_filter import filter_low_quality_results


async def main():
    """Demonstrate extraction orchestrator capabilities."""
    print("=" * 80)
    print("Extraction Orchestrator Demo - Graceful Degradation")
    print("=" * 80)
    print()

    # Create test settings
    settings = Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_MAX_CONCURRENT_EXTRACTIONS=4,
        BS_REQUEST_TIMEOUT_MS=6000,
        BS_EXTRACTION_TIMEOUT_MS=2500,
        BS_FALLBACK_TIMEOUT_MS=2000,
        BS_FALLBACK_ENABLED=True,
    )

    # Mock extraction strategy to simulate various outcomes
    mock_strategy = AsyncMock()

    async def mock_extract(url: str, req_id: str) -> ExtractedContent:
        url_str = str(url)

        # Simulate different extraction scenarios
        if "timeout" in url_str:
            await asyncio.sleep(0.05)  # Simulate slow extraction
            return ExtractedContent(
                url=url,
                content="",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
                extraction_time_ms=50,
                error="Timeout",
            )
        elif "blocked" in url_str:
            await asyncio.sleep(0.01)
            return ExtractedContent(
                url=url,
                content="",
                word_count=0,
                extracted_by="none",
                extraction_ok=False,
                extraction_time_ms=10,
                error="Blocked by site",
            )
        elif "short" in url_str:
            await asyncio.sleep(0.02)
            return ExtractedContent(
                url=url,
                content="Too short",
                word_count=2,
                extracted_by="crawl4ai",
                extraction_ok=True,
                extraction_time_ms=20,
            )
        else:
            # Successful extraction
            await asyncio.sleep(0.03)
            return ExtractedContent(
                url=url,
                content=f"High-quality article content from {url_str}. " * 10,
                word_count=80,
                extracted_by="crawl4ai",
                extraction_ok=True,
                extraction_time_ms=30,
            )

    mock_strategy.extract = mock_extract

    # Create search results with various quality levels
    search_results = [
        NormalizedSearchResult(
            title="High Quality Article 1",
            url="https://example1.com/article",
            snippet="Great article about Python",
            score=0.95,
        ),
        NormalizedSearchResult(
            title="High Quality Article 2",
            url="https://example2.com/article",
            snippet="Comprehensive guide to async",
            score=0.92,
        ),
        NormalizedSearchResult(
            title="Timed Out Site",
            url="https://timeout.com/article",
            snippet="Slow loading page",
            score=0.88,
        ),
        NormalizedSearchResult(
            title="Blocked Site",
            url="https://blocked.com/article",
            snippet="This site blocks scrapers",
            score=0.85,
        ),
        NormalizedSearchResult(
            title="Short Content",
            url="https://short.com/article",
            snippet="Very brief article",
            score=0.82,
        ),
        NormalizedSearchResult(
            title="High Quality Article 3",
            url="https://example3.com/article",
            snippet="Deep dive into concurrency",
            score=0.80,
        ),
        NormalizedSearchResult(
            title="High Quality Article 4",
            url="https://example4.com/article",
            snippet="Best practices for orchestration",
            score=0.78,
        ),
        NormalizedSearchResult(
            title="Another Timeout",
            url="https://timeout2.com/article",
            snippet="Another slow site",
            score=0.75,
        ),
        NormalizedSearchResult(
            title="High Quality Article 5",
            url="https://example5.com/article",
            snippet="Advanced async patterns",
            score=0.72,
        ),
        NormalizedSearchResult(
            title="High Quality Article 6",
            url="https://example6.com/article",
            snippet="Performance optimization guide",
            score=0.70,
        ),
    ]

    print(f"📊 Starting extraction for {len(search_results)} URLs")
    print(f"⚙️  Concurrency limit: {settings.BS_MAX_CONCURRENT_EXTRACTIONS}")
    print()

    # Step 1: Extract content with orchestrator
    orchestrator = ExtractionOrchestrator(mock_strategy, settings)

    start_time = time.perf_counter()
    extracted_contents = await orchestrator.extract_all(search_results, "demo-123")
    extraction_time = (time.perf_counter() - start_time) * 1000

    print(f"⏱️  Total extraction time: {extraction_time:.1f}ms")
    print()

    # Show extraction results
    successful = sum(1 for ec in extracted_contents if ec.extraction_ok)
    failed = len(extracted_contents) - successful

    print(f"✅ Successful extractions: {successful}")
    print(f"❌ Failed extractions: {failed}")
    print()

    # Step 2: Assemble results
    print("🔨 Assembling results...")
    assembled_results = ResultAssembler.assemble(
        search_results,
        extracted_contents,
        include_content=True,
        request_id="demo-123",
    )
    print(f"   Assembled {len(assembled_results)} results")
    print()

    # Step 3: Filter low quality
    print("🔍 Filtering low-quality content...")
    filtered_results = filter_low_quality_results(assembled_results, "demo-123")
    removed = len(assembled_results) - len(filtered_results)
    print(f"   Removed {removed} low-quality results")
    print(f"   Final result count: {len(filtered_results)}")
    print()

    # Display final results summary
    print("=" * 80)
    print("Final Results Summary")
    print("=" * 80)
    print()

    for idx, result in enumerate(filtered_results, 1):
        status = "✅" if result.metadata.extraction_ok else "❌"
        content_len = len(result.content) if result.content else 0
        print(f"{idx}. {status} {result.title[:60]}")
        print(f"   URL: {result.url}")
        print(f"   Extractor: {result.metadata.extracted_by}")
        print(f"   Word count: {result.metadata.word_count or 0}")
        print(f"   Content length: {content_len} chars")
        print()

    # Performance metrics
    print("=" * 80)
    print("Performance Metrics")
    print("=" * 80)
    print()
    print(f"Total URLs processed: {len(search_results)}")
    print(f"Concurrency limit: {settings.BS_MAX_CONCURRENT_EXTRACTIONS}")
    print(f"Total time: {extraction_time:.1f}ms")
    print(f"Average per URL: {extraction_time / len(search_results):.1f}ms")
    print(f"Success rate: {successful / len(search_results) * 100:.1f}%")
    print()
    print("✨ Demo complete! The orchestrator handled partial failures gracefully.")
    print("   All results were returned, even when some extractions failed.")


if __name__ == "__main__":
    asyncio.run(main())
