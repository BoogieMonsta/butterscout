# Butterscout

A self-hosted web search & extraction API for LLM agents.

- 🔎 **Search** via SearXNG (meta-search)
- 🧹 **Clean extraction** via Crawl4AI + fallback extractor
- 📦 **LLM-ready JSON** with stable schema
- ⚙️ **Easy to run**: Docker Compose (API + SearXNG + Valkey + Crawl4AI)

Butterscout turns a natural-language query into a list of URLs with extracted content, ready for use in tools, agents, and RAG pipelines.

## Quickstart with Docker Compose

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+

### Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/butterscout.git
   cd butterscout
   ```

2. **Configure environment (optional):**
   ```bash
   cp .env.example .env
   # Edit .env to set BS_API_KEY and other settings if needed
   ```

3. **Start all services:**
   ```bash
   docker compose up -d
   ```

   This will start:
   - `butterscout-api` - Main API server (port 8000)
   - `butterscout-searxng` - SearXNG meta-search engine (port 8080)
   - `butterscout-crawl4ai` - Crawl4AI extraction service (port 11235)
   - `butterscout-redis` - Redis cache and rate limiter (port 6379)

4. **Wait for services to be healthy (~30-60 seconds):**
   ```bash
   docker compose ps
   ```

   All services should show "healthy" or "running" status.

5. **Visit the API documentation:**
   ```
   http://localhost:8000/docs
   ```

### Testing the API

**Basic search:**
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"what is retrieval augmented generation","max_results":5}'
```

**With API key (if configured):**
```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H 'Content-Type: application/json' \
  -H 'x-api-key: your-api-key-here' \
  -d '{"query":"what is retrieval augmented generation","max_results":5}'
```

**Check health:**
```bash
curl http://localhost:8000/health
```

**View metrics (if enabled):**
```bash
curl http://localhost:8000/metrics
```

### Managing Services

**View logs:**
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f butterscout-api
docker compose logs -f searxng
docker compose logs -f crawl4ai
docker compose logs -f redis
```

**Stop services:**
```bash
docker compose down
```

**Stop and remove volumes:**
```bash
docker compose down -v
```

**Restart a specific service:**
```bash
docker compose restart butterscout-api
```

**Rebuild after code changes:**
```bash
docker compose up -d --build
```

### Development Mode

The included `docker-compose.override.yml` enables development mode with:
- Hot reload for code changes
- Debug logging
- All ports exposed for direct access

Simply use `docker compose up` and your changes to `butterscout/` will automatically reload.

### Troubleshooting

**Issue: SearXNG not responding**
```bash
docker compose logs searxng
docker compose restart searxng
```

**Issue: Crawl4AI connection refused**
```bash
# Check if service is running
docker compose ps crawl4ai

# Check logs
docker compose logs crawl4ai

# Restart service
docker compose restart crawl4ai
```

**Issue: Redis connection error**
```bash
# Test Redis connectivity
docker compose exec redis redis-cli ping
# Should return: PONG

# Check Redis logs
docker compose logs redis
```

**Issue: API not starting**
```bash
# Check API logs
docker compose logs butterscout-api

# Check if dependencies are healthy
docker compose ps

# Restart API
docker compose restart butterscout-api
```

**Issue: Port already in use**
```bash
# Find what's using the port (e.g., 8000)
lsof -i :8000

# Either stop the conflicting service or change the port in docker-compose.yml
```

### Resource Usage

Expected resource usage at idle:
- API: ~200-500MB RAM
- SearXNG: ~100-300MB RAM
- Crawl4AI: ~200-400MB RAM
- Redis: ~50-100MB RAM

Total: ~0.5-1.3GB RAM, 1-2 CPU cores under load

### Production Deployment

For production deployment:

1. **Set a strong API key:**
   ```bash
   export BS_API_KEY=$(openssl rand -base64 32)
   echo "BS_API_KEY=$BS_API_KEY" >> .env
   ```

2. **Update SearXNG secret:**
   ```bash
   # Generate a new secret
   openssl rand -hex 32
   # Edit searxng-config/settings.yml and replace the secret_key
   ```

3. **Configure CORS origins:**
   ```bash
   echo "BS_CORS_ORIGINS=https://yourdomain.com" >> .env
   ```

4. **Validate production configuration:**
   ```bash
   ./scripts/validate-production.sh
   ```
   This checks for common security issues before deployment.

5. **Use production compose file:**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```
   (This skips the development overrides)

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

## Documentation

- **[DOCKER.md](DOCKER.md)** - Complete Docker and Docker Compose guide
- **[TECH SPEC.md](TECH%20SPEC.md)** - Product and operations specifications
- **[ENGINEERING_GUIDE.md](ENGINEERING_GUIDE.md)** - Development process and quality standards
- **[openapi.yaml](openapi.yaml)** - OpenAPI specification
- **API Docs** - http://localhost:8000/docs (when running)

## Development

- CI: Lint, type check, tests, OpenAPI validation (`.github/workflows/ci.yml`)
- Recommended local stack: Docker Compose (API + SearXNG + Crawl4AI + Redis)
- See **[DOCKER.md](DOCKER.md)** for detailed setup and configuration
