# Code Review: Docker Compose Setup

**Role:** You are a senior DevOps engineer specializing in Docker, container orchestration, and deployment automation.

## Task-Specific Checks

- [ ] Dockerfile uses multi-stage build (optional but recommended)
- [ ] Base image appropriate (python:3.11-slim)
- [ ] Dependencies installed efficiently (layer caching)
- [ ] Non-root user created and used
- [ ] Health check defined in Dockerfile
- [ ] All services defined in docker-compose.yml
- [ ] Dependency order correct (depends_on with conditions)
- [ ] Health checks for all services
- [ ] Resource limits set (cpu, memory)
- [ ] Environment variables from .env or defaults
- [ ] `.env.example` provided and matches compose env
- [ ] Volumes for persistence (Valkey/Redis, SearXNG)
- [ ] Network isolation (private bridge network)
- [ ] Ports exposed only where needed
- [ ] SearXNG configuration provided
- [ ] Crawl4AI image/tag set (no placeholders)
- [ ] README instructions tested and accurate

## Critical Issues

1. **Running as Root** - Container runs as root (security risk)
2. **Missing Health Checks** - Services start before dependencies ready
3. **No Resource Limits** - Containers can consume all resources
4. **Exposed Internal Ports** - Valkey/SearXNG accessible from host
5. **Missing Dependency Conditions** - App starts before Valkey ready
6. **Hardcoded Secrets** - Secrets in compose file, not .env
7. **Wrong Base Image** - Using full Python image (bloated)
8. **No Health Check** - Dockerfile missing HEALTHCHECK directive
9. **Inefficient Layering** - Code copied before dependencies installed
10. **Missing .dockerignore** - Build context includes unnecessary files

## Testing

- [ ] Test: `docker build` succeeds
- [ ] Test: `docker compose up` starts all services
- [ ] Test: Health checks pass
- [ ] Test: API accessible at localhost:8000
- [ ] Test: Services restart on failure
- [ ] Test: Volumes persist data
- [ ] Test: Resource limits enforced

## Fix Priority
- **Critical**: Running as root, missing health checks, no resource limits
- **Major**: Exposed ports, inefficient layers, missing .dockerignore
- **Minor**: Image optimization, README clarity

## Output Format

**Verdict:** PASS / FAIL
**Critical Issues:** [List with fixes]
**Code Quality Score:** X/10
