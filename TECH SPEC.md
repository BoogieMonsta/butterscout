# Butterscout: Technical Specification

**Version:** 1.0 (MVP)  
**Last Updated:** 2025-11-17  
**Status:** Specification – Ready for implementation

---

## 1. Project Overview

### 1.1 Mission Statement

Butterscout is an open-source web search and extraction API built specifically for LLM agents and RAG systems. It takes a natural-language query, fans out across one or more search engines, fetches the top results, extracts the main content, and returns a clean, predictable JSON payload that’s easy for agents to consume.

The first goal is reliability and ergonomics, not cleverness: stable infrastructure that can be dropped into any agent stack as “the web tool”.

### 1.2 Positioning

- **vs Tavily**  
  - Tavily: Hosted, closed-source web tool for agents.  
  - Butterscout: Self-hosted, open-source service with a similar role (web access layer), focused on transparency and control.  
- **vs Perplexica**  
  - Perplexica: Full end-user search/answer engine (Perplexity-style UI).  
  - Butterscout: Headless, API-only component meant to sit underneath agents and applications.  
- **vs SearXNG**  
  - SearXNG: Meta-search engine returning SERPs and snippets.  
  - Butterscout: Builds on top of SearXNG to add content extraction, deduplication, basic ranking tuned for LLM consumption, and a stable JSON schema.  
- **vs Crawl4AI**  
  - Crawl4AI: Focused on crawling + extraction from URLs.  
  - Butterscout: Adds the search layer and orchestration to go from query → URLs → extracted content in a single API call.

---

## 2. Goals & Constraints

### 2.1 Functional Goals (MVP)
- Accept a natural-language query and optional filters.
- Use SearXNG to retrieve top search results.
- For each selected result, fetch and extract the main content.
- Deduplicate and lightly rank results.
- Return a JSON response that is:
  - Stable and documented.
  - Easy to consume from LLM tool-calling.
- Provide basic caching and rate-limiting.

### 2.2 Non-Functional Goals
- **Reliability:** Stable response shape; graceful degradation on partial failures.
- **Performance:** p95 response time for typical queries: ≤ 3 seconds for simple queries at default settings.
- **Resource awareness:** Designed to run on a single VPS (e.g. 2–4 vCPUs, 8–16 GB RAM).
- **Developer Experience (DX):**
  - Minimal but clear configuration.
  - Simple Docker Compose for local and production-like use.
  - OpenAPI docs.

### 2.3 Explicit Constraints / Non-Goals (for v0.1)
- No built-in LLM re-ranking on the main path (planned for v0.2).
- No multi-provider search orchestration beyond SearXNG in v0.1.
- No async/job-based mode (simple request/response only).
- No built-in GUI/dashboard.
- No hard guarantees about compliance with search engine ToS beyond what SearXNG itself supports (Butterscout treats SearXNG as an upstream).

---

## 3. MVP Scope

### 3.1 v0.1 – Core (Must-Have)

**Goal:** A single `/search` endpoint that reliably returns clean content for the top N results from SearXNG, with sane defaults, caching, and basic protection.

**Features:**
- **Search orchestration**
  - Integrate with a self-hosted SearXNG instance.
  - Normalize SERP items (title, URL, snippet, score).
- **Content extraction**
  - Integrate with a local Crawl4AI instance (primary extractor).
  - Provide a simple fallback extractor (Trafilatura) for non-HTML or failures.
  - Extract content in parallel for top N URLs.
- **Ranking & filtering**
  - Deduplicate results by URL.
  - Simple ranking based on:
    - SearXNG search score.
    - Optional domain-based boosts / blocks.
  - Filter out obviously useless results (empty content, tiny word count, etc.).
- **API surface**
  - `POST /api/v1/search`
  - `GET /health`
  - OpenAPI documentation.
- **Infra basics**
  - Docker Compose with:
    - Butterscout API
    - SearXNG
    - Valkey (Redis protocol)
    - Crawl4AI
  - Response caching in Valkey (configurable TTL).
  - IP-based rate limiting (configurable).
- **Observability**
  - Minimal logging.
  - Basic metrics:
    - total requests
    - cache hits
    - average/percentile durations
    - errors

### 3.2 v0.2 – LLM-Tuned (Should-Have)

Not part of the MVP, but the next step:

- Optional embedding-based re-ranking (local model).
- Optional LLM-based scoring for “deep” mode only.
- Search depth modes:
  - **fast:** URLs + snippets only, no extraction.
  - **balanced:** extract top N results (default).
  - **deep:** extract + semantic re-ranking (+ optional LLM scoring).
- First public eval script + small benchmark query set.

### 3.3 v0.3+ – Ecosystem (Nice-to-Have)

- TypeScript and Python SDKs.
- LangChain / LlamaIndex / MCP integrations.
- Query understanding / intent classification.
- Domain-specific modes (academic, news, coding).
- Web dashboard for testing and monitoring.
- Config API for dynamic tuning.

---

## 4. Technical Architecture

### 4.1 Components (v0.1)
- **API Layer (FastAPI):**
  - Exposes `/api/v1/search` and `/health`.
  - Handles request validation, auth (optional API keys), and rate limiting.
  - Serializes stable JSON responses.
- **Search Layer:**
  - Client for SearXNG:
    - Sends the user query.
    - Receives SERPs (title, URL, snippet, score).
    - Normalizes results into an internal model.
- **Extraction Layer:**
  - Client for Crawl4AI:
    - Given a URL, returns cleaned markdown/HTML + metadata.
    - Fallback extractor (Trafilatura / Readability) for when Crawl4AI fails or is not applicable.
    - Runs extraction concurrently across chosen URLs.
- **Ranking & Filtering:**
  - Deduplicates results by normalized URL (e.g. stripping query params where safe).
  - Filters out:
    - Empty / extremely short content.
    - Blocked domains (from config).
  - Orders results by:
    - SearXNG score (primary).
    - Simple heuristics (e.g. boost certain domains).
- **Caching & Rate Limiting:**
  - Valkey-backed cache keyed by (query, options) signature.
  - Configurable TTL (e.g. 1 hour).
  - Basic IP-based rate limit (e.g. X req/hour) using Valkey scripts.
- **Observability:**
  - Structured JSON logs (request id, user ip/hash, cache_hit flag, per-component timings).
  - Metrics: total/failed requests, cache hits, extraction failures, per-component latency histograms, rate-limit counts.
  - Suggested metric names (Prometheus):
    - `butterscout_requests_total{status,source}`
    - `butterscout_request_duration_seconds_bucket{component}` (histogram)
    - `butterscout_cache_hits_total`
    - `butterscout_extraction_failures_total{reason}`
    - `butterscout_rate_limited_total`
  - Metrics exposed at `/metrics` (Prometheus text format), guarded by config flag.
  - Log fields (JSON): `ts`, `level`, `msg`, `request_id`, `client_ip_hash`, `api_key_hash` (when used), `cache_hit`, `rate_limited`, `searxng_time_ms`, `extraction_time_ms`, `status_code`, `error_code`, `url_count`.
- **(Planned) LLM Layer (v0.2+):**
  - Optional re-ranking using:
    - Embedding similarity.
    - Optional LLM score for deep mode.
  - Not in v0.1 critical path.

### 4.2 Request Lifecycle (v0.1)

1. Client sends `POST /api/v1/search` with JSON body.
2. API layer:
   - Validates payload.
   - Applies auth / rate limiting.
   - Computes cache key and checks Valkey.
3. If cache hit:
   - Return cached response immediately.
4. If cache miss:
   1. Call SearXNG with the query (and optional filters).
   2. Normalize SERP items into internal objects.
   3. Select top N candidates.
   4. In parallel:
      - For each URL, call Crawl4AI → extracted content.
      - On failure, try fallback extractor.
      - Enforce per-URL timeout (default 2.5s) and per-request budget (default 6s).
      - Retry policy:
        - SearXNG: 1 retry on 5xx/timeout with jittered backoff (e.g. 100–300ms).
        - Crawl4AI: no retries; fall back immediately on failure/timeout.
   5. Deduplicate results by URL.
   6. Filter and rank results using simple heuristics.
   7. Build response JSON:
      - results array (title, URL, snippet, content, metadata).
      - metadata (timings, source info, cache flag).
   8. Store response in Valkey with TTL.
   9. Return response to client.

---

## 5. Technology Choices

### 5.1 Backend
- **Language:** Python 3.11+
- **Framework:** FastAPI
- **HTTP server:** Uvicorn / Gunicorn + Uvicorn workers
- **Config:** Pydantic-based settings (env vars + config file)

### 5.2 Search Provider (v0.1)
- **SearXNG:**
  - Self-hosted meta-search engine.
  - Configured as the sole upstream search provider in v0.1.
  - Butterscout communicates with SearXNG over HTTP.

Future versions may add additional providers (Brave, SerpAPI, etc.), but that is explicitly deferred.

### 5.3 Extraction
- **Primary:** Crawl4AI service (self-hosted).
- **Fallback:** Trafilatura extractor (Python library) in a small threadpool (default enabled, configurable).

### 5.4 Data & Infra
- **Cache / rate limit store:** Valkey (Redis protocol compatible)
- **Packaging:** Docker for all components
- **Orchestration:** Docker Compose for local + single-node prod deployments
- **Metrics:** Prometheus-compatible endpoint or internal stats exposed via FastAPI route (v0.2+)
- **Rate limiting:** Token bucket or sliding window (implementation: Valkey/Redis scripts).
- **Cache key:** hash of `query + normalized(options) + include_content + max_results`; TTL default 1h.

---

## 6. API Design (v0.1)

### 6.1 Endpoints

#### POST `/api/v1/search`  
_Main search endpoint._

**Request body (MVP):**
```jsonc
{
  "query": "what is retrieval augmented generation",
  "max_results": 10,             // optional, default 10, max 25 (hard cap)
  "include_content": true,       // optional, default true; if false, skip extraction and return URL/snippet only
  "extract_timeout_ms": 2500,    // optional per-URL extraction timeout; default 2500ms
  "options": {
    "domains": [],               // optional string[], whitelist
    "exclude_domains": [],       // optional string[], blacklist
    "freshness_days": null,      // optional number, passed through to SearXNG if supported
    "language": "en"             // optional, ISO 639-1; advisory; forwarded when upstream supports it
  }
}
```
Constraints:
- `query`: 1–512 UTF-8 chars; trimmed; reject empty/whitespace-only.
- `domains`/`exclude_domains`: max 20 entries each; each entry 3–255 chars; no wildcards for v0.1.
- `freshness_days`: must be positive integer if provided.

**Response (MVP):**
```jsonc
{
  "query": "what is retrieval augmented generation",
  "results": [
    {
      "title": "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
      "url": "https://arxiv.org/abs/2005.11401",
      "snippet": "We explore RAG models where the parametric memory is a pre-trained seq2seq...",
      "content": "Full extracted content in clean markdown (if include_content = true)...",
      "metadata": {
        "domain": "arxiv.org",
        "word_count": 1250,
        "extracted_by": "crawl4ai",
        "extraction_ok": true
      },
      "scores": {
        "search_score": 0.91,
        "rank": 1
        // future: "semantic_score": ..., "llm_relevance": ...
      },
      "source": "searxng"
    }
  ],
  "metadata": {
    "search_time_ms": 2340,              // total end-to-end
    "searxng_time_ms": 320,              // optional breakdown
    "extraction_time_ms": 1420,          // optional breakdown
    "cache_hit": false,
    "sources_queried": ["searxng"],
    "api_version": "v1",
    "rate_limited": false
  }
}
```
**Notes:**
- No `query_understanding` section in v0.1.
- No mandatory LLM-related fields.
- All optional future fields (e.g. semantic/LLM scores) must be additive and not break existing clients.
- Auth: optional API key header `x-api-key` (if configured). If not present when required, return `401` with machine-readable error body.

### 6.2 Defaults, Limits & Timeouts (v0.1)
- `max_results`: default 10, hard max 25.
- `include_content`: default true; when false, extraction layer is skipped entirely.
- Per-URL extraction timeout: 2.5s (configurable); per-request budget: 6s (configurable).
- SearXNG call timeout: 2s (configurable).
- Cache TTL: default 1h (configurable).
- Rate limits (sliding window via Valkey/Redis protocol): 60 req/hour per IP (default); 600 req/hour per API key (if auth enabled); optional global 10k req/hour (disabled by default).
- Request size limit: 32 KB JSON body; reject larger with 413.
- Concurrency: cap extracted URLs at `max_concurrent_extractions` (default 4) to protect upstreams.
- Rate limiting algorithm: sliding window (Valkey/Redis) keyed by API key when present, else IP; return `Retry-After` header and `retry_after_ms` in error body.
- Concurrency policy: `max_concurrent_extractions` per request, using asyncio semaphore; no global worker pool in v0.1 (single-node assumption).
- Cache invalidation: strictly TTL-based; no manual purge API in v0.1.

### 6.3 Schema Precision (v0.1)
- Types: `query` string (1–512 chars); `domains`/`exclude_domains` arrays of strings (each 3–255 chars); `language` ISO 639-1 or null.
- `max_results` int; default 10; min 1; max 25.
- `include_content` boolean.
- `options.freshness_days` nullable number; pass-through when supported upstream.
- `metadata` fields are required in success responses; timing breakdown fields may be null if not collected.
- Error body shape (all errors):
  ```json
  {
    "error": {
      "code": "string",          // e.g. VALIDATION_ERROR, RATE_LIMITED, UPSTREAM_TIMEOUT
      "message": "human-readable",
      "details": { "...": "..." } // optional; include component="searxng|crawl4ai|fallback", retry_after_ms, timeout=true, fields=[...]
    },
    "metadata": {
      "request_id": "uuid",
      "api_version": "v1",
      "timestamp": "ISO-8601"
    }
  }
  ```

**Error responses (MVP):**
- 400: validation error (Pydantic schema) — include field-level details.
- 401: missing/invalid API key.
- 403: IP blocked or domain policy violation.
- 429: rate limit exceeded (include `retry_after_ms`).
- 500: unhandled server error; avoid leaking stack traces in JSON.
- 502/504: upstream failures/timeouts; include which component failed (`searxng`, `crawl4ai`, `fallback_extractor`) and whether partial results were returned.

### 6.4 Partial Failure Handling
- If SearXNG fails, return 502/504 with empty results and `metadata.sources_queried` reflecting the attempted source.
- If extraction fails for some URLs, still return any successful results; mark each item with `metadata.extraction_ok=false` and `metadata.extracted_by=fallback|crawl4ai`.
- Timeouts should surface as `timeout=true` in error metadata; avoid truncating response schema.
- Always include `cache_hit` and `rate_limited` flags in metadata.

### 6.5 Auth & Rate-Limit Semantics
- Auth header: `x-api-key`. If configured and missing/invalid → 401 with `code="UNAUTHORIZED"`.
- Rate-limit keying: prefer API key when present; otherwise client IP. If both auth and IP limits exist, enforce both; return 429 with `Retry-After` header and `retry_after_ms` in body.
- CORS: allowlist from config; default `*` for dev only.
- Rate-limit headers: include `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`, and `Retry-After` (on 429).
- 401 responses include `WWW-Authenticate: ApiKey realm="Butterscout API"`.

#### GET `/health`  
_Health check endpoint for monitoring / orchestration._

**Response example:**
```json
{
  "status": "ok",
  "components": {
    "searxng": "ok",
    "crawl4ai": "ok",
    "valkey": "ok"
  },
  "version": "0.1.0"
}
```

---

## 7. Deployment

### 7.1 Local & Single-Node Deployment
- Docker Compose file with services:
  - butterscout-api
  - searxng
  - crawl4ai
-  - valkey (Redis protocol)
- Resource hints (Compose): butterscout-api `cpus: 1.5`, `mem_limit: 1.5g`; searxng `cpus: 1`, `mem_limit: 1g`; crawl4ai `cpus: 1`, `mem_limit: 1g`; valkey `mem_limit: 512m`.
- Recommended ulimits: nofile 65535 for API and SearXNG.
- Env vars for:
  - SearXNG URL
  - Crawl4AI URL
  - Valkey URL
  - Rate limit settings
  - Cache TTL
- Basic instructions:
  - `docker compose up`
  - Visit [http://localhost:8000/docs](http://localhost:8000/docs) for OpenAPI UI.
- Provide `.env.example` for easy bootstrap.

### 7.2 Configuration (env vars / settings)
- `BS_API_KEY` (optional): if set, require `x-api-key` to match.
- `BS_SEARXNG_URL` (required): base URL to SearXNG instance.
- `BS_CRAWL4AI_URL` (required): base URL to Crawl4AI.
- `BS_REDIS_URL` (required): Valkey/Redis protocol connection string.
- `BS_CACHE_TTL_SECONDS`: default 3600.
- `BS_RATE_LIMIT_PER_HOUR`: default 60.
- `BS_API_KEY_RATE_LIMIT_PER_HOUR`: default 600 (if auth enabled).
- `BS_GLOBAL_RATE_LIMIT_PER_HOUR`: default 10000 (disabled if unset).
- `BS_MAX_RESULTS`: default 10; max 25.
- `BS_MAX_CONCURRENT_EXTRACTIONS`: default 4.
- `BS_EXTRACTION_TIMEOUT_MS`: default 2500.
- `BS_REQUEST_TIMEOUT_MS`: default 6000 (end-to-end budget).
- `BS_LOG_LEVEL`: default `info`.
- `BS_ALLOWED_DOMAINS` / `BS_BLOCKED_DOMAINS`: comma-separated lists.
- `BS_RATE_LIMIT_ALGO`: default `sliding_window`.
- `BS_HEALTH_TIMEOUT_MS`: default 750 (per dependency check).
- `BS_ENABLE_METRICS`: default true.
- `BS_FALLBACK_ENABLED`: default true.
- `BS_FALLBACK_MAX_WORKERS`: default 2 (threadpool for Trafilatura).
- `BS_FALLBACK_TIMEOUT_MS`: default 2000.

### 7.2 Production Considerations  
(_Out of Scope for v0.1 Implementation, but Documented_)
- Horizontal scaling of butterscout-api behind a reverse proxy.
- External managed Valkey/Redis.
- External SearXNG / Crawl4AI clusters if necessary.
- TLS termination at a reverse proxy (Caddy, nginx, Traefik, etc.).
- Observability: ship logs to centralized sink; scrape Prometheus metrics; set uptime checks for `/health`.
- Security hardening: enable TLS everywhere; restrict SearXNG to trusted networks; configure CORS allowlist; enable reverse-proxy rate limits as a second barrier.

### 7.3 Data Handling & Privacy
- Persistent stores: Valkey only (cache + rate limit counters). No long-term storage of query results beyond TTL.
- Logs: avoid storing full extracted content; log URLs/domains, timings, error codes, cache hits, request ids.
- PII: assume queries may include PII; do not export logs externally without scrubber; ensure TLS in transit.
- Make TTL configurable per deployment for data minimization requirements.

### 7.4 Health Check Contract
- `/health` should:
  - Query Valkey `PING`, SearXNG lightweight request (e.g., `/status` or minimal search), Crawl4AI lightweight request.
  - Enforce per-component timeout `BS_HEALTH_TIMEOUT_MS` (default 750ms).
  - Return `200` if all components are `ok`; return `503` when any dependency is `degraded` or `down`; include component statuses in body plus `uptime_seconds` and `timestamp`.
  - Do not block on extraction; avoid heavy operations.

### 7.5 Dokploy on Hetzner (single-node)
- Provision: Hetzner CX31+ (2–4 vCPU, 8 GB RAM, 80+ GB SSD), Ubuntu 22.04. Open ports 80/443; restrict 8000/8080/6379 to local/VPC.
- Install Dokploy; add Docker Compose app using repo root (butterscout-api, searxng, crawl4ai, valkey). Use persistent volumes for Valkey and SearXNG configs.
- Secrets/env in Dokploy:
  - `BS_SEARXNG_URL=http://searxng:8080`
  - `BS_CRAWL4AI_URL=http://crawl4ai:11235`
  - `BS_REDIS_URL=redis://redis:6379/0`
  - `BS_API_KEY=<generated>` (optional)
  - `BS_RATE_LIMIT_PER_HOUR`, `BS_API_KEY_RATE_LIMIT_PER_HOUR`
  - `BS_REQUEST_TIMEOUT_MS=6000`, `BS_EXTRACTION_TIMEOUT_MS=2500`, `BS_MAX_CONCURRENT_EXTRACTIONS=4`
  - `BS_ALLOWED_DOMAINS` / `BS_BLOCKED_DOMAINS` (optional)
- Domains/TLS: point DNS A/AAAA to the server; in Dokploy enable HTTPS (Let’s Encrypt) and proxy to `butterscout-api:8000`; set `X-Forwarded-For` preservation.
- Health/monitoring: configure Dokploy health check on `/health` (timeout 1s, interval 15s); pipe container logs to Dokploy or external sink; expose `/metrics` internally only.
- Backups: snapshot SearXNG settings and Valkey volume as needed; config is otherwise stateless.

---

## 8. Testing & Evaluation

### 8.1 MVP Testing
- **Unit tests:**
  - Request validation.
  - Search client integration (mock SearXNG).
  - Extraction pipeline (mock Crawl4AI).
  - Ranking/deduplication logic.
- **Integration tests:**
  - Full query → SearXNG → Crawl4AI → response (against local instances).
  - Cache behavior (hit/miss, TTL).
- **Performance checks:**
  - p95 end-to-end latency ≤ 3s for default settings on representative queries (with cache cold).
  - Rate-limit behavior returns 429 with `retry_after_ms`.
- **Manual QA:**
  - A small set of hand-picked queries in categories:
    - Factual (general)
    - Technical (docs/coding)
    - News-like (recent)
  - Subjective assessment of:
    - Relevance
    - Content quality
    - Noise/spam incidence
- **CI/Test gates:**
  - `pytest` unit + integration (with mocked SearXNG/Crawl4AI; real local services optional).
  - Lint/type check: `ruff` + `mypy --strict` (or chosen strict subset).
  - Minimal perf sanity: script that runs 5 representative queries against local stack and asserts p95 < 3s and no 5xx responses.
  - OpenAPI schema generation matches spec (contract test).

### 8.2 Future Evals (v0.2+)

Not part of MVP, but desired later:

- **Scripted eval harness:**
  - Input: list of (query, expected answer / key facts).
  - Process: call Butterscout + an LLM; have a judge model assess correctness.
  - Basic metrics:
    - Top-k recall for relevant sources.
    - Coverage across domains.

---

## 9. Risks & Open Questions

### 9.1 Risks
- Upstream dependency fragility
  - SearXNG configuration or upstream search engines can change behavior.
  - Crawl4AI may break on certain JS-heavy sites.
- Legal / ToS concerns
  - Search engine terms of service may restrict scraping / automated use.
  - Butterscout relies on SearXNG’s compliance configuration; must clearly document that.
- Performance variability
  - Some sites will be slow or block crawling.
  - Need robust timeouts and partial-failure handling.

### 9.2 Open Questions (Intentionally Deferred)
- Should Butterscout ever talk directly to additional search providers (Brave, SerpAPI), or always through SearXNG?
- What is the minimal, stable way to expose “query understanding” to clients without locking into a specific implementation?
- Where should LLM-based scoring live long term?
  - Inside Butterscout?
  - As a separate “scoring microservice” that Butterscout can call?

_These do not need to be resolved for v0.1 and should not block implementation._

### 9.3 Assumptions
- SearXNG and Crawl4AI are reachable with low tail latency within the same network.
- Valkey is durable enough for the cache/rate-limit use case; eviction policy configured (e.g. `allkeys-lru`).
- Single locale focus (English) is acceptable for v0.1; other languages are best-effort via upstream SearXNG.
- Token bucket/sliding-window rate limiting in Valkey is sufficient for anticipated load of a single VPS deployment.

---

## 10. Roadmap (High-Level)

**Phase 1 – Skeleton (≈ 2–3 weeks actual coding time):**
- FastAPI skeleton with /health.
- SearXNG client.
- POST /api/v1/search returning only URLs/snippets (no extraction).
- Basic tests and logging.

**Phase 2 – Extraction & Ranking (≈ 2–3 weeks):**
- Crawl4AI integration and fallback extractor.
- Parallel extraction and result assembly.
- Deduplication and simple ranking.
- Valkey caching and rate limiting.
- OpenAPI docs.

**Phase 3 – Hardening (≈ 2–3 weeks):**
- Improve error handling and timeouts.
- Add minimal metrics.
- Refine config & docs.
- Internal eval notebook with hand-crafted queries.

**Phase 4 – v0.2+ (Future):**
- Embedding-based re-ranking.
- Optional LLM-based scoring for deep mode.
- Simple eval harness script.
- SDKs and ecosystem integrations.
