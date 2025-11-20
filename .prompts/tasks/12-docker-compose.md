# Task 12: Docker Compose Setup

**Role:** You are a senior DevOps engineer specializing in Docker, container orchestration, and local development environments.

## Context

Create the complete Docker Compose setup for running Butterscout locally with all dependencies (SearXNG, Crawl4AI, Valkey/Redis). This should provide a one-command development and single-node production environment. Use the actual Crawl4AI image/tag (replace placeholder) and supply `.env.example` for defaults.

Refer to **[TECH SPEC.md]** §7, **[ENGINEERING_GUIDE.md]** §40-42 for complete details.

## Deliverables

### 1. Dockerfile (`Dockerfile`)

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml ./

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Install Python dependencies
RUN uv sync

# Copy application code
COPY butterscout/ ./butterscout/

# Create non-root user
RUN useradd -m -u 1000 butterscout && \
    chown -R butterscout:butterscout /app

USER butterscout

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uvicorn", "butterscout.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2. Docker Compose (`docker-compose.yml`)

```yaml
version: "3.9"

services:
  butterscout-api:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: butterscout-api
    ports:
      - "8000:8000"
    environment:
      BS_SEARXNG_URL: http://searxng:8080
      BS_CRAWL4AI_URL: http://crawl4ai:11235
      BS_REDIS_URL: redis://redis:6379/0

      # Authentication (optional)
      BS_API_KEY: ${BS_API_KEY:-}

      # Cache settings
      BS_CACHE_TTL_SECONDS: ${BS_CACHE_TTL_SECONDS:-3600}

      # Rate limiting
      BS_RATE_LIMIT_PER_HOUR: ${BS_RATE_LIMIT_PER_HOUR:-60}
      BS_API_KEY_RATE_LIMIT_PER_HOUR: ${BS_API_KEY_RATE_LIMIT_PER_HOUR:-600}
      BS_GLOBAL_RATE_LIMIT_PER_HOUR: ${BS_GLOBAL_RATE_LIMIT_PER_HOUR:-}

      # Extraction settings
      BS_MAX_RESULTS: ${BS_MAX_RESULTS:-10}
      BS_MAX_CONCURRENT_EXTRACTIONS: ${BS_MAX_CONCURRENT_EXTRACTIONS:-4}
      BS_EXTRACTION_TIMEOUT_MS: ${BS_EXTRACTION_TIMEOUT_MS:-2500}
      BS_FALLBACK_ENABLED: ${BS_FALLBACK_ENABLED:-true}
      BS_FALLBACK_TIMEOUT_MS: ${BS_FALLBACK_TIMEOUT_MS:-2000}
      BS_FALLBACK_MAX_WORKERS: ${BS_FALLBACK_MAX_WORKERS:-2}
      BS_REQUEST_TIMEOUT_MS: ${BS_REQUEST_TIMEOUT_MS:-6000}

      # Observability
      BS_LOG_LEVEL: ${BS_LOG_LEVEL:-info}
      BS_ENABLE_METRICS: ${BS_ENABLE_METRICS:-true}

      # Health check
      BS_HEALTH_TIMEOUT_MS: ${BS_HEALTH_TIMEOUT_MS:-750}

      # Domain filtering
      BS_ALLOWED_DOMAINS: ${BS_ALLOWED_DOMAINS:-}
      BS_BLOCKED_DOMAINS: ${BS_BLOCKED_DOMAINS:-}

    depends_on:
      searxng:
        condition: service_healthy
      crawl4ai:
        condition: service_started
      redis:
        condition: service_healthy
    networks:
      - butterscout
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '1.5'
          memory: 1536M
        reservations:
          cpus: '0.5'
          memory: 512M
    ulimits:
      nofile:
        soft: 65535
        hard: 65535

  searxng:
    image: searxng/searxng:latest
    container_name: butterscout-searxng
    environment:
      - BASE_URL=http://searxng:8080/
      - INSTANCE_NAME=butterscout-searxng
    ports:
      - "8080:8080"
    volumes:
      - ./searxng-config:/etc/searxng:rw
      - searxng-data:/var/lib/searxng
    networks:
      - butterscout
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1024M
        reservations:
          cpus: '0.25'
          memory: 256M
    ulimits:
      nofile:
        soft: 65535
        hard: 65535
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s

  crawl4ai:
    # TODO: Update with actual Crawl4AI Docker image when available
    # This is a placeholder - check Crawl4AI docs for official image
    image: unclecode/crawl4ai:latest
    container_name: butterscout-crawl4ai
    ports:
      - "11235:11235"
    networks:
      - butterscout
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 1024M
        reservations:
          cpus: '0.25'
          memory: 256M
    # healthcheck:
    #   test: ["CMD", "curl", "-f", "http://localhost:11235/health"]
    #   interval: 30s
    #   timeout: 10s
    #   retries: 3

  redis:
    image: redis:7-alpine
    container_name: butterscout-redis
    command:
      - redis-server
      - --save ""
      - --appendonly no
      - --maxmemory 512mb
      - --maxmemory-policy allkeys-lru
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - butterscout
    restart: unless-stopped
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.1'
          memory: 128M
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3

networks:
  butterscout:
    driver: bridge

volumes:
  redis-data:
  searxng-data:
```

### 3. SearXNG Configuration (`searxng-config/settings.yml`)

```yaml
# SearXNG configuration for Butterscout

use_default_settings: true

general:
  instance_name: "butterscout-searxng"
  enable_metrics: false

search:
  safe_search: 0
  autocomplete: ""
  default_lang: "en"
  formats:
    - html
    - json

server:
  port: 8080
  bind_address: "0.0.0.0"
  secret_key: "changeme_in_production"
  limiter: false
  image_proxy: false

ui:
  static_use_hash: true
  default_theme: simple
  theme_args:
    simple_style: dark

enabled_engines:
  # Enable major search engines
  - google
  - bing
  - duckduckgo

# Disable engines that require API keys
disabled_engines:
  - wikipedia
```

### 4. Docker Compose Override for Development (`docker-compose.override.yml`)

```yaml
# Development overrides
# This file is automatically loaded with docker-compose.yml

version: "3.9"

services:
  butterscout-api:
    build:
      context: .
      dockerfile: Dockerfile
      target: development
    volumes:
      # Mount source code for hot reload
      - ./butterscout:/app/butterscout:ro
      - ./tests:/app/tests:ro
    environment:
      BS_LOG_LEVEL: debug
    command: ["uvicorn", "butterscout.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

  # Expose ports for direct access during development
  searxng:
    ports:
      - "8080:8080"

  redis:
    ports:
      - "6379:6379"

  crawl4ai:
    ports:
      - "11235:11235"
```

### 5. Multi-stage Development Dockerfile (optional)

Update Dockerfile to support development target:

```dockerfile
FROM python:3.11-slim as base

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

COPY pyproject.toml ./

# Development stage
FROM base as development

RUN uv sync --all-extras

USER root
CMD ["uv", "run", "uvicorn", "butterscout.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Production stage
FROM base as production

RUN uv sync

COPY butterscout/ ./butterscout/

RUN useradd -m -u 1000 butterscout && \
    chown -R butterscout:butterscout /app

USER butterscout

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "butterscout.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 6. README Updates (`README.md` additions)

Add to README:

```markdown
## Quick Start with Docker Compose

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+

### Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/BoogieMonsta/butterscout.git
   cd butterscout
   ```

2. Copy environment template:
   ```bash
   cp .env.example .env
   ```

3. Start all services:
   ```bash
   docker compose up -d
   ```

4. Wait for services to be healthy (~30 seconds):
   ```bash
   docker compose ps
   ```

5. Visit the API documentation:
   ```
   http://localhost:8000/docs
   ```

### Testing the API

```bash
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "what is retrieval augmented generation", "max_results": 5}'
```

### Viewing Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f butterscout-api
```

### Stopping Services

```bash
docker compose down
```

### Troubleshooting

**Issue: SearXNG not responding**
```bash
docker compose logs searxng
docker compose restart searxng
```

**Issue: Crawl4AI connection refused**
- Check if Crawl4AI service is running: `docker compose ps crawl4ai`
- Check logs: `docker compose logs crawl4ai`

**Issue: Valkey connection error**
```bash
docker compose exec redis redis-cli ping
```
```

### 7. GitHub Actions CI (`.github/workflows/ci.yml`)

```yaml
name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  test:
    runs-on: ubuntu-latest

    services:
      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 6379:6379

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install uv
        run: curl -LsSf https://astral.sh/uv/install.sh | sh

      - name: Install dependencies
        run: |
          export PATH="$HOME/.local/bin:$PATH"
          uv sync --all-extras

      - name: Lint
        run: make lint

      - name: Type check
        run: make typecheck

      - name: Run tests
        run: make test
        env:
          BS_REDIS_URL: redis://localhost:6379/0

  docker-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Build Docker image
        run: docker build -t butterscout:test .

      - name: Test Docker image
        run: |
          docker run -d --name test-api \
            -e BS_SEARXNG_URL=http://searxng:8080 \
            -e BS_CRAWL4AI_URL=http://crawl4ai:11235 \
            -e BS_REDIS_URL=redis://redis:6379 \
            butterscout:test

          sleep 5
          docker logs test-api
          docker stop test-api
```

## Key Implementation Details

### Service Dependencies (TECH SPEC §7.1)

- `butterscout-api` depends on: `redis`, `searxng`, `crawl4ai`
- Use health checks to ensure dependencies are ready
- Set proper startup order with `depends_on` + `condition`

### Resource Limits (TECH SPEC §7.1)

Per TECH SPEC recommendations:
- API: 1.5 CPUs, 1.5GB RAM
- SearXNG: 1 CPU, 1GB RAM
- Crawl4AI: 1 CPU, 1GB RAM
- Valkey: 0.5 CPU, 512MB RAM

Total: ~4 vCPUs, ~4GB RAM

### Valkey Configuration

- No persistence (`--save "" --appendonly no`) for cache-only use
- LRU eviction policy (`allkeys-lru`)
- 512MB max memory
- Suitable for cache + rate limiting

### Network Isolation

- All services on private `butterscout` bridge network
- Only API exposed on host (port 8000)
- Internal ports not exposed (or exposed only in dev)

### Volume Persistence

- `redis-data`: Valkey data (optional, for rate limit persistence)
- `searxng-data`: SearXNG settings
- `searxng-config`: Custom SearXNG configuration (bind mount)

## Testing Requirements

### Docker Build Tests

```bash
# Build image
docker build -t butterscout:test .

# Verify image size (should be reasonable)
docker images butterscout:test

# Test container starts
docker run --rm butterscout:test --help
```

### Docker Compose Tests

```bash
# Start services
docker compose up -d

# Check all services are healthy
docker compose ps

# Test API health endpoint
curl http://localhost:8000/health

# Test search endpoint
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "test", "max_results": 3}'

# Check logs for errors
docker compose logs

# Cleanup
docker compose down -v
```

## Performance Requirements

- Container startup: < 30s (including dependency health checks)
- Image size: < 500MB (Python slim base + dependencies)
- Memory usage at idle: < 500MB per container

## Output Format

When complete, provide:

1. ✅ All Docker files created
2. ✅ `docker compose up` successfully starts all services
3. ✅ Health checks pass
4. ✅ API accessible at http://localhost:8000
5. 📊 Example showing:
   - `docker compose ps` output
   - Successful search request
   - Container resource usage (`docker stats`)
6. 📝 README instructions tested

## Dependencies

- **Task 01-11** (All previous tasks - need complete app)

## Time Estimate

4-5 hours

## Reference

- [TECH SPEC.md] §7.1: Local & Single-Node Deployment
- [TECH SPEC.md] §7.5: Dokploy on Hetzner
- [ENGINEERING_GUIDE.md] §40: Docker Compose (local/single-node)
