# Code Review: Docker Compose Setup

**Role:** You are a senior DevOps engineer specializing in Docker, container orchestration, and deployment automation.

## Task-Specific Checks

### Container & Build
- [ ] Dockerfile uses multi-stage build (optional but recommended)
- [ ] Base image appropriate (python:3.11-slim)
- [ ] Dependencies installed efficiently (layer caching)
- [ ] Non-root user created and used
- [ ] Health check defined in Dockerfile
- [ ] `.dockerignore` exists and excludes unnecessary files

### Service Configuration
- [ ] All services defined in docker-compose.yml
- [ ] Dependency order correct (depends_on with conditions)
- [ ] **Health checks for ALL services** (redis, searxng, crawl4ai, api)
- [ ] Health check conditions used in depends_on
- [ ] Resource limits set (cpu, memory) for all services
- [ ] **Resource reservations set** (minimum guaranteed resources)
- [ ] **ulimits (nofile: 65535) set for all services**
- [ ] **shm_size: "2gb" set for crawl4ai** (browser automation requirement)
- [ ] Restart policies configured (unless-stopped/always)

### Security
- [ ] **Security capabilities configured** (cap_drop/cap_add for searxng)
- [ ] No containers running as root unnecessarily
- [ ] Redis password protected in production
- [ ] No hardcoded secrets in compose files
- [ ] Internal ports not exposed in production

### Environment & Configuration
- [ ] Environment variables from .env or defaults
- [ ] `.env.example` provided and matches compose env
- [ ] Service URLs use Docker DNS (service names)
- [ ] All BS_* configuration options present
- [ ] SearXNG configuration provided and mounted
- [ ] Crawl4AI image/tag set (no placeholders)

### Data & Networking
- [ ] Volumes for persistence (Valkey/Redis, SearXNG)
- [ ] **Volume naming consistent** (redis_data, not redis-data)
- [ ] **Network naming consistent** (butterscout-network)
- [ ] Network isolation (private bridge network)
- [ ] Ports exposed only where needed

### Documentation
- [ ] README instructions tested and accurate
- [ ] Comments explain non-obvious configurations
- [ ] Production deployment notes included

## Critical Issues

1. **Running as Root** - Container runs as root (security risk)
2. **Missing Health Checks** - Services start before dependencies ready (REQUIRED for all services!)
3. **No Health Checks in Production** - Prod depends_on won't work without health checks
4. **No Resource Limits** - Containers can consume all resources
5. **No Resource Reservations** - Minimum resources not guaranteed
6. **Missing ulimits** - "Too many open files" errors under high load (REQUIRED: nofile 65535)
7. **No shm_size for crawl4ai** - Browser automation will crash (REQUIRED: 2gb)
8. **Missing Security Capabilities** - Containers over-privileged (need cap_drop/cap_add)
9. **Exposed Internal Ports in Prod** - Redis/SearXNG accessible from host (security risk)
10. **Missing Dependency Conditions** - App starts before dependencies healthy
11. **Hardcoded Secrets** - Secrets in compose file, not .env
12. **Wrong Base Image** - Using full Python image (bloated)
13. **No Health Check in Dockerfile** - Missing HEALTHCHECK directive
14. **Inefficient Layering** - Code copied before dependencies installed
15. **Missing .dockerignore** - Build context includes unnecessary files
16. **Inconsistent Naming** - Network/volume names differ between dev and prod

## Testing

- [ ] Test: `docker compose config` validates syntax
- [ ] Test: `docker build` succeeds
- [ ] Test: `docker compose up -d` starts all services
- [ ] Test: `docker compose ps` shows all services as "healthy"
- [ ] Test: API accessible at localhost:8000/health
- [ ] Test: Search endpoint works (POST /api/v1/search)
- [ ] Test: Services restart on failure (docker kill <container>)
- [ ] Test: Volumes persist data (docker compose down && up)
- [ ] Test: Resource limits enforced (`docker stats`)
- [ ] Test: ulimits applied (`docker exec <container> ulimit -n`)
- [ ] Test: Production compose works (`-f docker-compose.prod.yml`)

## Fix Priority
- **Critical**: Missing health checks (especially in prod), no ulimits, no shm_size for crawl4ai, running as root, no resource limits
- **Major**: Missing security caps, exposed ports in prod, no depends_on conditions, inconsistent naming, inefficient layers
- **Minor**: Missing .dockerignore, image optimization, README clarity, unpinned tags

## Output Format

**Verdict:** PASS / FAIL
**Critical Issues:** [List with fixes]
**Code Quality Score:** X/10
