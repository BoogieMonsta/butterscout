# Butterscout Docker Guide

This guide covers everything you need to know about running Butterscout with Docker and Docker Compose.

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Configuration](#configuration)
- [Development](#development)
- [Production](#production)
- [Troubleshooting](#troubleshooting)
- [Advanced Topics](#advanced-topics)

## Quick Start

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- 4GB RAM minimum, 8GB recommended

### Start All Services

```bash
# Clone the repository
git clone https://github.com/BoogieMonsta/butterscout.git
cd butterscout

# Copy environment template
cp .env.example .env

# Start all services
docker compose up -d

# Check service status
docker compose ps

# View logs
docker compose logs -f
```

The API will be available at http://localhost:8000

## Architecture

Butterscout runs as a multi-container application with the following services:

### Service Overview

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| butterscout-api | Custom (built from source) | 8000 | Main API server |
| butterscout-searxng | searxng/searxng:latest | 8080* | Meta-search engine |
| butterscout-crawl4ai | unclecode/crawl4ai:latest | 11235* | Content extraction |
| butterscout-redis | redis:7-alpine | 6379* | Cache & rate limiting |

*Ports only exposed in development mode

### Network Architecture

```
                    ┌─────────────────┐
                    │   Internet      │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  Port 8000      │
                    │  (API only)     │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │  butterscout bridge network  │
              │                              │
    ┌─────────▼─────────┐         ┌─────────▼─────────┐
    │  butterscout-api  │────────▶│ butterscout-redis │
    │                   │         │                   │
    └─────────┬─────────┘         └───────────────────┘
              │
        ┌─────┴─────┐
        │           │
   ┌────▼────┐  ┌──▼────────┐
   │ searxng │  │ crawl4ai  │
   │         │  │           │
   └─────────┘  └───────────┘
```

### Resource Limits

Default resource limits per service:

**butterscout-api:**
- CPU: 0.5-1.5 cores
- Memory: 512MB-1.5GB

**searxng:**
- CPU: 0.25-1.0 cores
- Memory: 256MB-1GB

**crawl4ai:**
- CPU: 0.25-1.0 cores
- Memory: 256MB-1GB

**redis:**
- CPU: 0.1-0.5 cores
- Memory: 128MB-512MB

**Total Resources:**
- CPU: ~1-4 cores
- Memory: ~1.1-4.0GB

## Configuration

### Environment Variables

All configuration is done via environment variables. See `.env.example` for all available options.

**Key Configuration:**

```bash
# Service URLs (configured automatically by docker-compose)
BS_SEARXNG_URL=http://searxng:8080
BS_CRAWL4AI_URL=http://crawl4ai:11235
BS_REDIS_URL=redis://redis:6379/0

# Optional API key authentication
BS_API_KEY=your-secret-key-here

# Rate limiting
BS_RATE_LIMIT_PER_HOUR=60              # Per IP
BS_API_KEY_RATE_LIMIT_PER_HOUR=600     # Per API key
BS_GLOBAL_RATE_LIMIT_PER_HOUR=10000    # Global

# Search & extraction
BS_MAX_RESULTS=10
BS_MAX_CONCURRENT_EXTRACTIONS=4
BS_EXTRACTION_TIMEOUT_MS=2500

# Observability
BS_LOG_LEVEL=info                      # debug, info, warning, error
BS_ENABLE_METRICS=true

# CORS
BS_CORS_ORIGINS=*                      # Comma-separated origins
```

### SearXNG Configuration

SearXNG is configured via `searxng-config/settings.yml`. Key settings:

```yaml
server:
  secret_key: "changeme_in_production"  # IMPORTANT: Change in production!

search:
  safe_search: 0                        # 0=off, 1=moderate, 2=strict
  default_lang: "en"

engines:
  - name: google
    disabled: false
  - name: bing
    disabled: false
  - name: duckduckgo
    disabled: false
```

**To customize search engines:**

1. Edit `searxng-config/settings.yml`
2. Add/remove engines
3. Restart SearXNG: `docker compose restart searxng`

### Redis Configuration

Redis is configured for cache-only operation:

- No persistence (data lost on restart)
- 512MB max memory
- LRU eviction policy
- Optimized for cache + rate limiting

## Development

### Development Mode

`docker-compose.override.yml` provides development features:

- **Hot reload**: Code changes automatically reload the API
- **Debug logging**: Verbose output for troubleshooting
- **Exposed ports**: Direct access to all services
- **Volume mounts**: Source code mounted for live editing

**Start development environment:**

```bash
docker compose up
```

This automatically loads both `docker-compose.yml` and `docker-compose.override.yml`.

**View live logs:**

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f butterscout-api
```

**Make code changes:**

1. Edit files in `butterscout/`
2. Changes automatically reload
3. Check logs for reload confirmation

**Run commands in containers:**

```bash
# Python shell
docker compose exec butterscout-api uv run python

# Run tests
docker compose exec butterscout-api uv run pytest

# Check dependencies
docker compose exec butterscout-api uv run pip list
```

### Local Testing Without Docker

For faster iteration during development:

```bash
# Install dependencies
uv sync --all-extras

# Start dependencies only
docker compose up -d searxng crawl4ai redis

# Run API locally
uv run uvicorn butterscout.main:app --reload

# Run tests
uv run pytest
```

## Production

### Production Deployment

For production, use the production compose file to override development settings:

```bash
# Use production configuration
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Production differences:**
- No volume mounts (code from image)
- No exposed internal ports
- Production logging level
- Always restart policy

### Pre-Production Checklist

1. **Set a strong API key:**
   ```bash
   export BS_API_KEY=$(openssl rand -base64 32)
   echo "BS_API_KEY=$BS_API_KEY" >> .env
   ```

2. **Update SearXNG secret:**
   ```bash
   # Generate a new secret
   openssl rand -hex 32
   # Edit searxng-config/settings.yml and replace server.secret_key
   ```

3. **Configure CORS:**
   ```bash
   echo "BS_CORS_ORIGINS=https://yourdomain.com" >> .env
   ```

4. **Set log level:**
   ```bash
   echo "BS_LOG_LEVEL=warning" >> .env
   ```

5. **Review rate limits:**
   ```bash
   # Adjust based on your needs
   echo "BS_RATE_LIMIT_PER_HOUR=100" >> .env
   echo "BS_API_KEY_RATE_LIMIT_PER_HOUR=1000" >> .env
   ```

6. **Configure domain filtering (optional):**
   ```bash
   echo "BS_BLOCKED_DOMAINS=example.com,spam.com" >> .env
   echo "BS_ALLOWED_DOMAINS=trusted.com,safe.com" >> .env
   ```

7. **Run security validation:**
   ```bash
   ./scripts/validate-production.sh
   ```
   This script checks for common security issues and misconfigurations.

### Health Checks

All services include health checks:

```bash
# Check all services
docker compose ps

# Test API health
curl http://localhost:8000/health

# Test Redis
docker compose exec redis redis-cli ping

# Test SearXNG
curl http://localhost:8080/
```

### Monitoring

**Prometheus metrics:**

```bash
# View metrics
curl http://localhost:8000/metrics
```

**Container stats:**

```bash
# Live resource usage
docker stats

# Service-specific
docker stats butterscout-api
```

### Backup and Restore

**Redis data (if persistence enabled):**

```bash
# Backup
docker compose exec redis redis-cli SAVE
docker compose cp redis:/data/dump.rdb ./backup-dump.rdb

# Restore
docker compose cp ./backup-dump.rdb redis:/data/dump.rdb
docker compose restart redis
```

**SearXNG settings:**

```bash
# Backup
tar -czf searxng-backup.tar.gz searxng-config/

# Restore
tar -xzf searxng-backup.tar.gz
docker compose restart searxng
```

### Updating

**Update to latest images:**

```bash
# Pull latest images
docker compose pull

# Rebuild custom image
docker compose build --no-cache butterscout-api

# Restart with new images
docker compose up -d

# Remove old images
docker image prune -f
```

## Troubleshooting

### Common Issues

#### API won't start

```bash
# Check logs
docker compose logs butterscout-api

# Common causes:
# 1. Dependencies not ready
docker compose ps  # Check all services are healthy

# 2. Port already in use
lsof -i :8000

# 3. Environment variables missing
docker compose config  # Validate configuration
```

#### SearXNG connection errors

```bash
# Check SearXNG is running
docker compose ps searxng

# Check health
docker compose exec searxng curl -f http://localhost:8080/

# View logs
docker compose logs searxng

# Restart
docker compose restart searxng
```

#### Crawl4AI timeouts

```bash
# Check service is running
docker compose ps crawl4ai

# View logs
docker compose logs crawl4ai

# Increase timeout
echo "BS_EXTRACTION_TIMEOUT_MS=5000" >> .env
docker compose up -d
```

#### Redis connection refused

```bash
# Check Redis is running
docker compose ps redis

# Test connection
docker compose exec redis redis-cli ping

# Check logs
docker compose logs redis

# Restart
docker compose restart redis
```

#### Out of memory errors

```bash
# Check current usage
docker stats

# Increase Redis limit (if needed)
# Edit docker-compose.yml:
#   redis:
#     command:
#       - --maxmemory 1024mb

# Restart
docker compose up -d
```

### Debug Mode

Enable debug logging for troubleshooting:

```bash
# Set debug level
echo "BS_LOG_LEVEL=debug" >> .env

# Restart API
docker compose restart butterscout-api

# Watch debug logs
docker compose logs -f butterscout-api
```

### Performance Issues

**Check resource usage:**

```bash
docker stats
```

**Increase API workers:**

```bash
# Edit docker-compose.yml command:
CMD ["uvicorn", "butterscout.main:app", "--workers", "4", ...]

# Adjust resource limits
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 2048M
```

**Optimize extraction concurrency:**

```bash
echo "BS_MAX_CONCURRENT_EXTRACTIONS=8" >> .env
docker compose restart butterscout-api
```

## Testing

### CI/CD Testing Configuration

For automated testing in CI/CD pipelines, use `docker-compose.test.yml`:

```bash
# Start services with test-friendly config
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d

# Run the test suite from the host/CI runner
BS_SEARXNG_URL=http://localhost:8080 \
BS_CRAWL4AI_URL=http://localhost:11235 \
BS_REDIS_URL=redis://localhost:6379/0 \
BS_SKIP_STARTUP=1 \
uv run pytest

# Tear down when finished
docker compose -f docker-compose.yml -f docker-compose.test.yml down -v
```

**Test configuration features:**
- Faster timeouts for quicker feedback
- Reduced resource limits for parallel testing
- Ephemeral tmpfs volumes (no persistence)
- Debug logging enabled
- No exposed ports (internal only)
- Disabled rate limiting

**Example CI workflow:**

```yaml
# .github/workflows/test.yml
name: Test
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Start services
        run: docker compose -f docker-compose.yml -f docker-compose.test.yml up -d
      - name: Run tests
        run: |
          BS_SEARXNG_URL=http://localhost:8080 \
          BS_CRAWL4AI_URL=http://localhost:11235 \
          BS_REDIS_URL=redis://localhost:6379/0 \
          BS_SKIP_STARTUP=1 \
          uv run pytest
      - name: Cleanup
        run: docker compose down -v
```

## Advanced Topics

### Custom Network Configuration

**Use existing network:**

```yaml
networks:
  butterscout:
    external: true
    name: my-existing-network
```

**Static IPs:**

```yaml
services:
  butterscout-api:
    networks:
      butterscout:
        ipv4_address: 172.28.0.10

networks:
  butterscout:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
```

### SSL/TLS Termination

Use a reverse proxy for HTTPS:

**nginx example:**

```nginx
upstream butterscout {
    server localhost:8000;
}

server {
    listen 443 ssl;
    server_name api.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://butterscout;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### Multi-Host Deployment

Deploy services across multiple hosts using Docker Swarm or Kubernetes.

**Docker Swarm example:**

```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml butterscout

# Check services
docker stack services butterscout

# Scale API
docker service scale butterscout_butterscout-api=3
```

### Custom Build

**Build with specific Python version:**

```dockerfile
FROM python:3.12-slim AS base
# ... rest of Dockerfile
```

**Add additional dependencies:**

```dockerfile
FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*
```

### Environment-Specific Configurations

**Staging environment:**

```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d
```

**docker-compose.staging.yml:**

```yaml
services:
  butterscout-api:
    environment:
      BS_LOG_LEVEL: debug
      BS_ENABLE_METRICS: "true"
      BS_RATE_LIMIT_PER_HOUR: 1000
```

## Getting Help

- **Documentation**: See [README.md](README.md)
- **API Docs**: http://localhost:8000/docs
- **Issues**: https://github.com/BoogieMonsta/butterscout/issues
- **Tech Spec**: [TECH SPEC.md](TECH%20SPEC.md)
- **Engineering Guide**: [ENGINEERING_GUIDE.md](ENGINEERING_GUIDE.md)

## License

See [LICENSE](LICENSE) file in the repository root.
