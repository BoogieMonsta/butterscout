# Butterscout Engineering Guide
**Audience:** Solo contributor  
**Scope:** Process, quality bar, and tooling for a solid v0.1 release.

## Process & Planning
- Work from the spec: TECH SPEC.md (product/ops) + openapi.yaml (API contract). Treat both as source of truth.
- Thin-slice delivery: validation → SearXNG client → extraction wrapper → ranking/dedupe → response assembly → cache/rate limit → logging/metrics.
- For each feature: capture a short RFC (inputs/outputs/edge cases), then implement with tests, update OpenAPI if needed, and regenerate docs.

## Testing Strategy
- Unit: request validation, cache key generation, rate limiting logic, ranking/deduping, extraction orchestrator with mocked clients.
- Integration (local): search path with mocked SearXNG/Crawl4AI; cache hit/miss; rate limit behavior; health endpoint.
- Perf sanity: script 5 representative queries against local stack; assert p95 < 3s, no 5xx.
- Contract: validate openapi.yaml; assert FastAPI routes match schema (e.g., using schema-based tests).

## Tooling & CI Gates
- Lint: `ruff check`
- Format: `ruff format` (or `black` if preferred—choose one)
- Types: `mypy --strict` (or near-strict)
- Tests: `pytest` (unit + integration)
- OpenAPI: `openapi-spec-validator` or `spectral lint` on openapi.yaml
- Make targets: `make lint`, `make format`, `make typecheck`, `make test`, `make openapi-validate`, `make up` (compose)

## Observability Baseline
- Structured logs (JSON): request_id, client_ip_hash, api_key_hash, cache_hit, rate_limited, searxng_time_ms, extraction_time_ms, status_code, error_code, url_count.
- Metrics (Prometheus): request totals, latency histograms per component, cache hits, extraction failures by reason, rate-limited counts. Expose `/metrics` (auth optional via config).
- Health: `/health` with component statuses, uptime_seconds, timestamp.

## Config Discipline
- Env-driven settings with defaults; provide `.env.example`.
- Required: `BS_SEARXNG_URL`, `BS_CRAWL4AI_URL`, `BS_REDIS_URL`.
- Recommended overrides: timeouts, rate limits, max_results, concurrency.
- Startup validation: fail fast if required env missing or invalid.

## Development Approach (Agent-Friendly)
- Start from openapi.yaml → generate/update routers/types → implement handlers to satisfy contract.
- Keep a “done checklist” per feature: tests added, docs updated, OpenAPI regenerated, lint/typecheck/pytest pass, perf sanity (if relevant).
- Prefer fail-fast defaults (strict validation, timeouts, backpressure via semaphores).

## Docker Compose (local/single-node)
Example services (verify Crawl4AI image/tag when available):
```yaml
version: "3.9"
services:
  butterscout-api:
    build: .
    ports: ["8000:8000"]
    environment:
      BS_SEARXNG_URL: http://searxng:8080
      BS_CRAWL4AI_URL: http://crawl4ai:11235
      BS_REDIS_URL: redis://redis:6379/0
      BS_API_KEY: ${BS_API_KEY:-}
      BS_RATE_LIMIT_PER_HOUR: 60
      BS_API_KEY_RATE_LIMIT_PER_HOUR: 600
      BS_MAX_RESULTS: 10
      BS_MAX_CONCURRENT_EXTRACTIONS: 4
      BS_EXTRACTION_TIMEOUT_MS: 2500
      BS_FALLBACK_ENABLED: "true"
      BS_FALLBACK_TIMEOUT_MS: 2000
      BS_REQUEST_TIMEOUT_MS: 6000
    depends_on: [searxng, crawl4ai, redis]

  searxng:
    image: searxng/searxng:latest
    environment:
      - BASE_URL=http://searxng:8080/
    ports: ["8080:8080"]

  crawl4ai:
    image: <set-crawl4ai-image>
    ports: ["11235:11235"]

  redis:
    image: valkey/valkey:latest
    command: ["valkey-server", "--save", "", "--appendonly", "no"]
    ports: ["6379:6379"]
    volumes: ["redis-data:/data"]

volumes:
  redis-data:
```
In prod (Dokploy/Hetzner): add TLS termination and restrict internal ports (8080/6379/11235) to the local network; persist Valkey and SearXNG config volumes.

## Language Choice Rationale
- Python + FastAPI fits SearXNG/Crawl4AI integrations, async IO, small ops footprint. Ecosystem support (aiohttp/httpx, Pydantic) simplifies the MVP.
- SDKs can be added later in TS/Python; core service remains in Python for now.

## Notes on TDD vs Pragmatic Testing
- Use TDD where logic is tricky (rate limiting, cache keys, ranking, orchestration). Otherwise, write focused tests immediately after adding code.
- Avoid overkill: keep integration tests fast with local/mock services; rely on perf sanity instead of heavy load tests.
