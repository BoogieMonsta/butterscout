# Butterscout

**The Search Backend for AI Agents**

Open-source search and extraction API. Self-host or use our managed service.

Butterscout orchestrates **SearXNG** (for search) and **Crawl4AI** (for extraction) to provide a unified, LLM-ready API for web research.

> **Note**: A managed version with zero-ops deployment is in development. [Follow for updates](https://github.com/BoogieMonsta/butterscout/discussions).

## Why Butterscout?

**Tavily charges $0.01/search. Serper starts at $50/month. Both are black boxes.**

Butterscout gives you:
- **$12/month** on Hetzner for unlimited self-hosted searches
- **Full transparency**: See exactly what was searched and why
- **Agent-optimized output**: Clean JSON designed for LLM context windows
- **Your infrastructure**: Data never leaves your servers

## Features

- **Unified API**: One endpoint for Search + Scrape + Rerank
- **Smart Extraction**: Uses `Crawl4AI` to convert messy HTML into clean Markdown
- **Rate Limiting**: Built-in Redis-backed rate limiting
- **Caching**: Deduplicates requests to save bandwidth and time
- **LLM-Ready**: Returns optimized JSON for context windows

## Quickstart (Local Testing)

1. **Clone the repository:**
   ```bash
   git clone https://github.com/BoogieMonsta/butterscout.git
   cd butterscout
   ```

2. **Give Crawl4AI an API token** (Crawl4AI 0.9+ refuses API calls without one, and
   compose stops with an error if it is missing):
   ```bash
   echo "BS_CRAWL4AI_API_TOKEN=$(openssl rand -hex 32)" >> .env
   ```

3. **Start all services:**
   ```bash
   docker compose -f docker-compose.selfhost.yml up -d
   ```

4. **Visit the API documentation:**
   ```
   http://localhost:8000/docs
   ```

### Testing the API

**Health check:**
```bash
curl http://localhost:8000/health
```

**Metrics (if enabled):**
```bash
curl http://localhost:8000/metrics
```

## Production Configuration

For production deployments, configure via `.env` file:

```bash
# Create .env from template
cp .env.example .env

# Edit .env and set:
# - BS_CRAWL4AI_API_TOKEN=$(openssl rand -hex 32)   (required)
# - REDIS_PASSWORD=$(openssl rand -base64 32)
# - SEARXNG_SECRET_KEY=$(openssl rand -hex 32)
# - BS_API_KEY=$(openssl rand -base64 32)
# - BS_CORS_ORIGINS=https://yourdomain.com
# - BS_LOG_LEVEL=warning

# Start services (automatically loads .env)
docker compose -f docker-compose.selfhost.yml up -d
```

See `.env.example` for all available configuration options.

## Defaults & Limits
- `max_results`: default 10, max 25
- Timeouts, per page: Crawl4AI gets `extract_timeout_ms` (2.5 s) plus 1 s to send its answer;
  a page it fails on goes to the fallback (Trafilatura) with up to min(`extract_timeout_ms`,
  `BS_FALLBACK_TIMEOUT_MS` = 3 s) for waiting, fetching and parsing together. That is about
  6 s worst case by default, ~2 s at 500 ms, ~10 s at 6000 ms. SearXNG (2 s, +1 retry) runs
  first, and search waits for its slowest page; there is no request-wide deadline.
- Fallback pages: at most 5 MB, no compression (`Accept-Encoding: identity`; compressed
  answers are refused, since decoding happens before any size check), at most 5 redirects,
  public addresses only (see below).
  At most 2 x `BS_FALLBACK_MAX_WORKERS` fallback extractions at once; a parse keeps its slot
  until its thread finishes, even after its caller gave up.
- `BS_FALLBACK_USER_AGENT`: the User-Agent the fallback sends. Unset, it is HTTPX's default,
  which some sites refused in testing; an honest bot name of your own got more of them. The
  fallback does not pretend to be a browser.
- Rate limits: 60 req/hr per IP; 600 req/hr per API key; optional global 10k/hr
- Extraction concurrency: 8 Crawl4AI pages at once across all requests in the compose files
  (`BS_MAX_CONCURRENT_EXTRACTIONS`, about 2 per Crawl4AI CPU); a page that waits past its
  timeout for a free slot goes to the fallback extractor
- Cache TTL: 1h. Not cached: searches with zero results, searches where Crawl4AI itself
  failed, and searches where any result came back without page text

### When extraction is degraded

Butterscout falls back to Trafilatura when Crawl4AI fails, so results keep coming even when
Crawl4AI is down. To keep that from hiding the failure:

- `/health` renders a tiny inline page through Crawl4AI's browser with the same filter
  config search uses, so `crawl4ai` shows `down` with a reason (`auth: … check
  BS_CRAWL4AI_API_TOKEN`, `unreachable`, `api_mismatch: fit markdown is empty …`) when
  Crawl4AI cannot actually extract, not only when its port is closed. `/health` is for
  diagnosis; container healthchecks use `/health/live`, so a Crawl4AI outage does not take
  the API itself offline while the fallback can still serve.
- Search and extract responses carry factual `warnings` (REST: `metadata.warnings`) when
  Crawl4AI itself failed (unreachable, token rejected, server errors, request format
  rejected), when Crawl4AI produced none of 3+ pages for any reason (e.g. starved or
  throttled), and when at least half the results have no page text. MCP clients are told to
  pass these on to the user. A page that just waited too long for a free Crawl4AI slot is
  counted in metrics, not warned about.
- Known limit: the fallback (Trafilatura) can return a site's human-verification page or
  JavaScript notice as `content` and report the extraction as successful. A phrase-based
  detector was tried on paper and dropped: short real pages use the same words.
- `butterscout_extraction_failures_total{extractor="crawl4ai"}` counts Crawl4AI failures by
  reason (`timeout`, `error`, `busy`, `unreachable`, `auth`, …); each one sent a page to the
  fallback.
- Crawl4AI keeps working on a page after Butterscout gives up, and some of its waits ignore
  per-request timeouts. `crawl4ai-config/config.yml` (upstream's config with one change) caps
  each crawl at 8 s server-side; without it, sustained load made normal pages fail.

### When search returns nothing or junk

SearXNG scrapes public engines, so results depend on the engine code being current and on the
engines tolerating your IP. From one IP, engines regularly get rate-limited or CAPTCHA'd and
SearXNG suspends them for minutes to a day. The template enables Google, Google CSE,
DuckDuckGo, Brave and Yahoo so results survive any one of them dropping out; Bing is off
because it returns unrelated pages for technical queries.

To see which engines are failing right now:

```bash
curl -s "http://127.0.0.1:8080/search?q=test&format=json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["unresponsive_engines"])'
```

Engines break when the sites change their pages, so update SearXNG first (this also clears
suspensions):

```bash
docker compose pull searxng && docker compose up -d searxng
```

## Performance

Tested on Hetzner CPX32 (4 vCPU, 8GB RAM) with default settings:

| Metric | Value |
|--------|-------|
| p50 latency | ~1.2s |
| p95 latency | ~2.8s |
| p99 latency | ~3.5s |
| Test coverage | 88%+ |
| Cache hit speedup | ~50x |

*Measured with 10 concurrent requests, DuckDuckGo + Bing engines, extraction enabled.*

## Usage Examples

> **Note:** Replace `localhost:8000` with your deployment URL in production.

### cURL (basic)
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"latest llama3 news","max_results":5}'
```

### cURL (with API key)
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: your-api-key-here' \
  -d '{"query":"latest llama3 news","max_results":5}'
```

### Python (httpx)
```python
import httpx, os

api_key = os.getenv("BS_API_KEY")
headers = {"x-api-key": api_key} if api_key else {}

resp = httpx.post(
    "http://localhost:8000/api/v1/search",
    json={"query": "latest llama3 news", "max_results": 5},
    headers=headers,
    timeout=10,
)
resp.raise_for_status()
print(resp.json())
```

### TypeScript (fetch)
```typescript
const apiKey = process.env.BS_API_KEY;
const headers: Record<string, string> = {
  "Content-Type": "application/json",
};
if (apiKey) headers["x-api-key"] = apiKey;

const response = await fetch("http://localhost:8000/api/v1/search", {
  method: "POST",
  headers,
  body: JSON.stringify({
    query: "latest llama3 news",
    max_results: 5,
  }),
});

if (!response.ok) throw new Error(`HTTP ${response.status}`);
const data = await response.json();
console.log(data);
```

## MCP (for agent harnesses)

Butterscout can serve the [Model Context Protocol](https://modelcontextprotocol.io) over
Streamable HTTP at `http://localhost:8000/mcp`, with two read-only tools:

- `butterscout_search`: search + extracted page text (each result clipped to 4,000
  characters; `content_truncated` marks clipped results; `warnings` says when extraction was
  degraded; `max_results` is capped at `BS_MAX_RESULTS`). Default 5 results ≈ 20k characters
  of content; 10 ≈ 40k.
- `butterscout_extract`: clean Markdown/text for one public URL (default 20,000 characters,
  up to 80,000).

It is **off by default** (`BS_MCP_ENABLED=false`). The development compose override turns it
on and binds every port to `127.0.0.1`. The endpoint is stateless (no session ids, safe
across `uvicorn --reload`) and only accepts `Host` values in `BS_MCP_ALLOWED_HOSTS` and
`Origin` values in `BS_MCP_ALLOWED_ORIGINS` (empty = no browsers), to block DNS rebinding.
Tool calls share the REST rate limit (one per call) and API-key rules.

Register it:

```bash
claude mcp add --scope user --transport http butterscout http://localhost:8000/mcp
codex mcp add butterscout --url http://localhost:8000/mcp
```

OpenCode 2.x (`~/.config/opencode/opencode.json`):

```json
{ "mcp": { "servers": { "butterscout": {
  "type": "remote", "url": "http://localhost:8000/mcp", "oauth": false } } } }
```

If `BS_API_KEY` is set, `/mcp` answers 401 without a key. Send it as `x-api-key` or
`Authorization: Bearer <key>` (REST accepts both too): Claude
`--header "Authorization: Bearer $BS_API_KEY"`, Codex `--bearer-token-env-var BS_API_KEY`,
OpenCode `"headers": {"Authorization": "Bearer <key>"}`. Without a configured header, Claude
treats a 401 as a cue to start OAuth, which Butterscout does not offer. This keyed setup is
documented but has not been tested end to end in a harness.

Local and private addresses: Crawl4AI's browser sends its HTTP(S) traffic through Crawl4AI's
own egress proxy (0.9.5), which refuses non-global addresses, redirects included. The fallback
checks each new connection itself: it resolves the host once, refuses it if any answer is not
a public unicast address, and dials only the checked addresses, so redirects and changing DNS
answers are covered too (`butterscout/clients/public_only.py`). `/extract` also checks the URL
up front for a clearer error. "Public" means globally routable: a home device with a global
IPv6 address would not count as private (the default Docker network has no IPv6 route out).

## Documentation

- **[openapi.yaml](openapi.yaml)** - OpenAPI specification
- **API Docs** - http://localhost:8000/docs (when running)
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Development setup and contribution guidelines
- **[TECH SPEC.md](TECH%20SPEC.md)** - Product and operations specifications
- **[deployment/](deployment/)** - Maintainer deployment (CI/CD, production configs)

## Roadmap

**v0.1 (Current)**: Core search + extraction API with SearXNG and Crawl4AI

**v0.2 (Next)**:
- Framework integrations (LangChain, LlamaIndex, Goose)
- Brave Search API as optional provider
- Embedding-based re-ranking

**v0.3+**:
- Python and TypeScript SDKs
- Search depth modes (fast/balanced/deep)
- LLM-based relevance scoring
