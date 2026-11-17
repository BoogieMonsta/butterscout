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

2. **Start all services:**
   ```bash
   docker compose -f docker-compose.selfhost.yml up -d
   ```

3. **Visit the API documentation:**
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
- Timeouts: SearXNG 2s (+1 retry), Crawl4AI 2.5s, fallback 2s, request budget 6s
- Rate limits: 60 req/hr per IP; 600 req/hr per API key; optional global 10k/hr
- Extraction concurrency: 4 URLs per request
- Cache TTL: 1h

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
