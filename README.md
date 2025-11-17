# Butterscout

A self-hosted web search & extraction API for LLM agents.

- 🔎 **Search** via SearXNG (meta-search)
- 🧹 **Clean extraction** via Crawl4AI + fallback extractor
- 📦 **LLM-ready JSON** with stable schema
- ⚙️ **Easy to run**: Docker Compose (API + SearXNG + Redis + Crawl4AI)

Butterscout turns a natural-language query into a list of URLs with extracted content, ready for use in tools, agents, and RAG pipelines.

## Quickstart (local Compose)
1. Copy `.env.example` to `.env` and set secrets (optional `BS_API_KEY`).
2. Run `docker compose up`.
3. Open http://localhost:8000/docs for OpenAPI UI.
4. Test:
   ```bash
   curl -X POST http://localhost:8000/api/v1/search \
     -H 'Content-Type: application/json' \
     ${BS_API_KEY:+-H "x-api-key: $BS_API_KEY"} \
     -d '{"query":"what is retrieval augmented generation","max_results":5}'
   ```

### Defaults & Limits (v0.1)
- `max_results`: default 10, max 25
- Timeouts: SearXNG 2s (+1 retry), Crawl4AI 2.5s, fallback 2s, request budget 6s
- Rate limits: 60 req/hr per IP; 600 req/hr per API key; optional global 10k/hr
- Extraction concurrency: 4 URLs per request
- Cache TTL: 1h

## Clients (snippets)
- **cURL:** see above
- **Python (httpx):**
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

## Development
- Specs: `TECH SPEC.md` (product/ops), `openapi.yaml` (contract), `ENGINEERING_GUIDE.md` (process/quality)
- CI: OpenAPI validation (`.github/workflows/ci.yml`)
- Recommended local stack: Docker Compose (API + SearXNG + Crawl4AI + Redis)
