# Code Review: FastAPI Application & Health Endpoint

**Role:** You are a senior FastAPI backend engineer specializing in API architecture and service health monitoring.

## Task-Specific Checks

- [ ] Lifespan context manager handles startup/shutdown correctly
- [ ] All clients initialized on startup
- [ ] Config validated before initializing clients
- [ ] Graceful shutdown disconnects all clients
- [ ] Request ID middleware adds UUID to each request
- [ ] Request timing middleware measures duration
- [ ] Global exception handler catches all errors
- [ ] Error responses follow TECH SPEC format (error, metadata)
- [ ] Health check verifies all components (Valkey/Redis, SearXNG, Crawl4AI)
- [ ] Health check respects BS_HEALTH_TIMEOUT_MS per component
- [ ] Health check returns 200 if all OK, 503 if any down
- [ ] Component status includes timing and errors

## Critical Issues

1. **Missing Startup Validation** - Config not validated before use
2. **Connection Leaks** - Clients not disconnected on shutdown
3. **Missing Request ID** - No request tracking across logs
4. **Unhandled Exceptions** - Errors leak stack traces to clients
5. **Health Check Hangs** - No timeout per component
6. **Wrong Status Codes** - Health returns 200 when degraded
7. **Missing Error Context** - Error responses missing request_id
8. **Blocking Operations** - Sync operations in async handlers

## Testing

- [ ] Test: App starts successfully
- [ ] Test: Health endpoint returns correct structure
- [ ] Test: Request ID added to headers
- [ ] Test: Exceptions caught and formatted correctly
- [ ] Test: Health check respects timeouts
- [ ] Test: Shutdown disconnects clients

## Fix Priority
- **Critical**: Unhandled exceptions, connection leaks, missing validation
- **Major**: Health check issues, wrong status codes
- **Minor**: Log clarity, docstrings

## Output Format

**Verdict:** PASS / FAIL
**Critical Issues:** [List with fixes]
**Code Quality Score:** X/10
