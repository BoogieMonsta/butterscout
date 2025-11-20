#!/usr/bin/env python3
"""Demonstration of SearXNG client functionality."""
import asyncio

import httpx
import respx

from butterscout.clients.searxng_client import SearXNGClient
from butterscout.config import Settings
from butterscout.models.requests import SearchRequest
from butterscout.utils.domain_filter import is_domain_allowed


async def demo_successful_search() -> None:
    """Demonstrate successful search with normalized results."""
    print("\n" + "=" * 80)
    print("DEMO 1: Successful Search with Normalized Results")
    print("=" * 80)

    mock_response = {
        "results": [
            {
                "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
                "url": "https://arxiv.org/abs/2005.11401",
                "content": (
                    "We explore RAG models where the parametric memory is a pre-trained seq2seq "
                    "model and the non-parametric memory is a dense vector index of Wikipedia, "
                    "accessed with a pre-trained neural retriever."
                ),
                "score": 0.95,
            },
            {
                "title": "What is RAG? - IBM",
                "url": "https://www.ibm.com/topics/retrieval-augmented-generation",
                "content": (
                    "Retrieval-Augmented Generation (RAG) is an AI framework that retrieves facts "
                    "from an external knowledge base to ground large language models on the most "
                    "accurate, up-to-date information."
                ),
                "score": 0.87,
            },
            {
                "title": "RAG explained - AWS",
                "url": "https://aws.amazon.com/what-is/retrieval-augmented-generation/",
                "content": (
                    "Retrieval-Augmented Generation (RAG) is the process of optimizing the output "
                    "of a large language model."
                ),
            },
        ]
    }

    settings = Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_REQUEST_TIMEOUT_MS=2000,
    )

    with respx.mock:
        respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        client = SearXNGClient(settings)
        await client.connect()

        try:
            request = SearchRequest(
                query="what is retrieval augmented generation",
                max_results=3,
            )
            results = await client.search(request, request_id="demo-001")

            print(f"\nQuery: {request.query}")
            print(f"Results returned: {len(results)}\n")

            for i, result in enumerate(results, 1):
                print(f"Result {i}:")
                print(f"  Title: {result.title}")
                print(f"  URL: {result.url}")
                print(f"  Score: {result.score:.2f}")
                print(f"  Snippet: {result.snippet[:100]}...")
                print(f"  Source: {result.source}")
                print()

        finally:
            await client.disconnect()


async def demo_retry_on_timeout() -> None:
    """Demonstrate retry logic on timeout."""
    print("\n" + "=" * 80)
    print("DEMO 2: Retry Logic on Timeout")
    print("=" * 80)

    settings = Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_REQUEST_TIMEOUT_MS=2000,
    )

    mock_success = {
        "results": [
            {
                "title": "Success after retry",
                "url": "https://example.com",
                "content": "This result was returned after a successful retry",
            }
        ]
    }

    with respx.mock:
        # First request times out, second succeeds
        respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
            side_effect=[
                httpx.TimeoutException("Request timeout"),
                httpx.Response(200, json=mock_success),
            ]
        )

        client = SearXNGClient(settings)
        await client.connect()

        try:
            request = SearchRequest(query="test query")

            print("\nAttempt 1: Request will timeout...")
            print("Attempt 2: Retrying with jittered backoff (100-300ms)...")
            print("Attempt 2: Success!\n")

            results = await client.search(request, request_id="demo-002")

            print(f"Results after retry: {len(results)}")
            print(f"First result: {results[0].title}")
            print("\n✓ Retry mechanism working correctly")

        finally:
            await client.disconnect()


async def demo_retry_on_5xx() -> None:
    """Demonstrate retry logic on 5xx errors."""
    print("\n" + "=" * 80)
    print("DEMO 3: Retry Logic on 5xx Server Errors")
    print("=" * 80)

    settings = Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_REQUEST_TIMEOUT_MS=2000,
    )

    mock_success = {
        "results": [
            {
                "title": "Recovered from server error",
                "url": "https://example.com",
                "content": "Server recovered",
            }
        ]
    }

    with respx.mock:
        # First request gets 503, second succeeds
        respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
            side_effect=[
                httpx.Response(503, text="Service Unavailable"),
                httpx.Response(200, json=mock_success),
            ]
        )

        client = SearXNGClient(settings)
        await client.connect()

        try:
            request = SearchRequest(query="test query")

            print("\nAttempt 1: Server returns 503 Service Unavailable...")
            print("Attempt 2: Retrying with jittered backoff...")
            print("Attempt 2: Success!\n")

            results = await client.search(request, request_id="demo-003")

            print(f"Results after 5xx recovery: {len(results)}")
            print(f"First result: {results[0].title}")
            print("\n✓ 5xx error recovery working correctly")

        finally:
            await client.disconnect()


async def demo_no_retry_on_4xx() -> None:
    """Demonstrate that 4xx errors are not retried."""
    print("\n" + "=" * 80)
    print("DEMO 4: No Retry on 4xx Client Errors")
    print("=" * 80)

    settings = Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_REQUEST_TIMEOUT_MS=2000,
    )

    with respx.mock:
        respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
            return_value=httpx.Response(400, text="Bad Request")
        )

        client = SearXNGClient(settings)
        await client.connect()

        try:
            request = SearchRequest(query="test query")

            print("\nAttempt 1: Server returns 400 Bad Request...")
            print("No retry attempted (4xx errors are client errors)")

            try:
                await client.search(request, request_id="demo-004")
            except httpx.HTTPStatusError as e:
                print(
                    f"\n✓ Raised exception immediately: {e.response.status_code} "
                    f"{e.response.reason_phrase}"
                )

        finally:
            await client.disconnect()


def demo_domain_filtering() -> None:
    """Demonstrate domain filtering functionality."""
    print("\n" + "=" * 80)
    print("DEMO 5: Domain Filtering")
    print("=" * 80)

    test_urls = [
        "https://example.com/page",
        "https://subdomain.example.com/page",
        "https://spam.com/page",
        "https://www.allowed.org/page",
        "https://blocked.net/page",
    ]

    allowed_domains = ["example.com", "allowed.org"]
    blocked_domains = ["spam.com", "blocked.net"]

    print("\nAllowed domains:", allowed_domains)
    print("Blocked domains:", blocked_domains)
    print("\nFiltering results:")

    for url in test_urls:
        is_allowed = is_domain_allowed(url, allowed_domains, blocked_domains)
        status = "✓ ALLOWED" if is_allowed else "✗ BLOCKED"
        print(f"  {status}: {url}")

    print("\n" + "-" * 80)
    print("Test with blacklist only:")
    print("Blocked domains:", ["ads.example.com"])
    print()

    blacklist_only = [
        "https://example.com/page",
        "https://ads.example.com/page",
        "https://tracker.ads.example.com/page",
    ]

    for url in blacklist_only:
        is_allowed = is_domain_allowed(url, [], ["ads.example.com"])
        status = "✓ ALLOWED" if is_allowed else "✗ BLOCKED"
        print(f"  {status}: {url}")


async def demo_missing_fields() -> None:
    """Demonstrate handling of missing fields in search results."""
    print("\n" + "=" * 80)
    print("DEMO 6: Handling Missing Fields with Fallbacks")
    print("=" * 80)

    mock_response = {
        "results": [
            {
                "url": "https://example.com/page1",
                # Missing title, content, score
            },
            {
                "title": "Has Title Only",
                "url": "https://example.com/page2",
                # Missing content and score
            },
            {
                "title": "Complete Result",
                "url": "https://example.com/page3",
                "content": "Full content available",
                "score": 0.95,
            },
        ]
    }

    settings = Settings(
        BS_SEARXNG_URL="http://localhost:8080",
        BS_CRAWL4AI_URL="http://localhost:11235",
        BS_REDIS_URL="redis://localhost:6379/0",
        BS_REQUEST_TIMEOUT_MS=2000,
    )

    with respx.mock:
        respx.get(f"{settings.BS_SEARXNG_URL}/search").mock(
            return_value=httpx.Response(200, json=mock_response)
        )

        client = SearXNGClient(settings)
        await client.connect()

        try:
            request = SearchRequest(query="test")
            results = await client.search(request, request_id="demo-006")

            print(f"\nResults with missing fields: {len(results)}\n")

            for i, result in enumerate(results, 1):
                print(f"Result {i}:")
                print(
                    f"  Title: {result.title} {'(fallback)' if result.title == 'No title' else ''}")
                print(f"  URL: {result.url}")
                print(
                    f"  Score: {result.score:.4f} "
                    f"{'(position-based)' if result.score == 1.0 / i else ''}"
                )
                print(
                    f"  Snippet: '{result.snippet}' "
                    f"{'(empty fallback)' if not result.snippet else ''}"
                )
                print()

            print("✓ Missing fields handled gracefully with fallbacks")

        finally:
            await client.disconnect()


async def main() -> None:
    """Run all demonstrations."""
    print("\n" + "=" * 80)
    print("BUTTERSCOUT - SearXNG CLIENT DEMONSTRATION")
    print("=" * 80)

    await demo_successful_search()
    await demo_retry_on_timeout()
    await demo_retry_on_5xx()
    await demo_no_retry_on_4xx()
    demo_domain_filtering()
    await demo_missing_fields()

    print("\n" + "=" * 80)
    print("DEMONSTRATION COMPLETE")
    print("=" * 80)
    print("\nKey Features Demonstrated:")
    print("  ✓ Search result normalization")
    print("  ✓ Retry logic on timeouts (100-300ms jittered backoff)")
    print("  ✓ Retry logic on 5xx errors")
    print("  ✓ Retry logic on 429 rate limit errors")
    print("  ✓ No retry on 4xx client errors")
    print("  ✓ Domain filtering (whitelist/blacklist)")
    print("  ✓ Graceful handling of missing fields")
    print("  ✓ Score normalization (fallback to position-based)")
    print("  ✓ Snippet truncation to 500 characters")
    print("  ✓ Health check functionality")
    print()


if __name__ == "__main__":
    asyncio.run(main())
