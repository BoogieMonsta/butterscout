# Butterscout v0.1 Development Prompts

**Complete parallel development workflow for implementing Butterscout v0.1 from specification.**

This directory contains 14 parallelizable implementation tasks and corresponding code review prompts to build Butterscout - an open-source web search and extraction API for LLM agents. Defaults align with TECH SPEC: 6s request budget, SearXNG 2s + 1 retry (100–300ms jitter), Crawl4AI no retries (Trafilatura fallback), per-request extraction concurrency only (4), rate limits 60/hr IP and 600/hr API key (optional global 10k/hr), cache key includes `max_results`, and `openapi.yaml` is the canonical contract.

## Directory Structure

```
.prompts/
├── tasks/              # Implementation task prompts (01-14)
│   ├── 01-foundation.md
│   ├── 02-redis-client.md
│   ├── 03-searxng-client.md
│   ├── 04-extraction-clients.md
│   ├── 05-extraction-orchestrator.md
│   ├── 06-caching-layer.md
│   ├── 07-rate-limiting.md
│   ├── 08-ranking-deduplication.md
│   ├── 09-fastapi-app-health.md
│   ├── 10-search-endpoint.md
│   ├── 11-logging-metrics.md
│   ├── 12-docker-compose.md
│   ├── 13-testing-suite.md
│   └── 14-e2e-integration.md
├── reviews/            # Code review prompts (01-14)
│   ├── 01-foundation-review.md
│   ├── 02-redis-client-review.md
│   └── ... (one review per task)
└── README.md           # This file
```

## Workflow

### Phase 1: Implementation

For each task, an agent/developer:

1. **Read the task prompt** from `tasks/XX-taskname.md`
2. **Implement all deliverables** listed in the task
3. **Run tests** and verify all requirements met
4. **Provide output** in the format specified in the task

**Example:**
```bash
# Agent reads task prompt
cat .prompts/tasks/01-foundation.md

# Agent implements the task
# - Creates all files listed
# - Implements all functionality
# - Writes tests

# Agent verifies completion
make test
make lint
make typecheck

# Agent provides completion report
```

### Phase 2: Code Review

After implementation, a reviewer agent:

1. **Read the review prompt** from `reviews/XX-taskname-review.md`
2. **Check all items** in the checklists
3. **FIX all issues found** (critical, major, AND minor)
4. **Verify fixes** by running tests
5. **Provide verdict** (PASS/FAIL) with changes made

**IMPORTANT:** Review prompts require ACTIVE FIXING of all issues, not just passive reporting.

### Phase 3: Final Validation

After all tasks complete:

1. Run end-to-end validation (Task 14)
2. Complete release checklist
3. Verify all integration points work
4. Sign off on v0.1 release

## Task Dependencies

Tasks are organized into 5 phases for maximum parallelization:

### **Phase 0: Foundation** (Sequential - ~6 hours)

**Must complete before starting other tasks.**

- **Task 01**: Project Foundation & Configuration
  - Dependencies: None
  - Deliverables: Project structure, config system, data models, pyproject.toml, Makefile

### **Phase 1: Core Infrastructure** (Parallel - ~12 hours total, ~4-5 hours with 3 agents)

**Can all run in parallel after Phase 0 completes.**

- **Task 02**: Valkey/Redis Client & Utilities
  - Dependencies: Task 01
  - Deliverables: Valkey/Redis client, key generation utilities

- **Task 03**: SearXNG Client
  - Dependencies: Task 01
  - Deliverables: HTTP client with retry logic, result normalization

- **Task 04**: Extraction Clients (Crawl4AI + Trafilatura fallback)
  - Dependencies: Task 01
  - Deliverables: Crawl4AI client, Trafilatura fallback, extraction strategy

### **Phase 2: Business Logic** (Parallel - ~16 hours total, ~5 hours with 4 agents)

**Can all run in parallel after Phase 1 completes.**

- **Task 05**: Extraction Orchestrator
  - Dependencies: Task 01, Task 04
  - Deliverables: Parallel extraction with concurrency control, result assembly

- **Task 06**: Caching Layer
  - Dependencies: Task 01, Task 02
  - Deliverables: Valkey-backed cache service, TTL management

- **Task 07**: Rate Limiting System
  - Dependencies: Task 01, Task 02
  - Deliverables: Sliding window rate limiter, header generation

- **Task 08**: Ranking & Deduplication
  - Dependencies: Task 01
  - Deliverables: URL deduplication, simple ranking, domain filtering

### **Phase 3: API & Observability** (Parallel - ~15 hours total, ~5 hours with 3 agents)

**Can all run in parallel after Phase 2 completes.**

- **Task 09**: FastAPI Application & Health Endpoint
  - Dependencies: Task 01, Task 02, Task 03, Task 04
  - Deliverables: FastAPI app with lifespan, health checks, middleware

- **Task 10**: Search Endpoint Implementation
  - Dependencies: Task 01, Task 03, Task 05, Task 06, Task 07, Task 08, Task 09
  - Deliverables: Complete /api/v1/search endpoint, request orchestration

- **Task 11**: Logging & Metrics
  - Dependencies: Task 01, Task 09
  - Deliverables: Structured JSON logging, Prometheus metrics

### **Phase 4: Infrastructure** (Parallel - ~12 hours total, ~6 hours with 2 agents)

**Can start after API is working (Tasks 09-10 complete).**

- **Task 12**: Docker Compose Setup
  - Dependencies: Task 01-11 (complete application)
  - Deliverables: Dockerfile, docker-compose.yml (fill actual Crawl4AI image tag), SearXNG config, README, `.env.example`

- **Task 13**: Testing Suite
  - Dependencies: Task 01-11 (complete application)
  - Deliverables: Unit tests, integration tests, fixtures, test configuration

### **Phase 5: Final Validation** (Sequential - ~5 hours)

**Must run after all previous tasks complete.**

- **Task 14**: End-to-End Integration & Validation
  - Dependencies: Task 01-13 (everything)
  - Deliverables: E2E tests, performance validation, OpenAPI contract tests, release checklist

## Parallelization Strategy

### Maximum Parallelization

With enough agents/developers, you can achieve significant time savings:

| Phase | Sequential Time | Parallel Time (with N agents) | Agents Needed |
|-------|----------------|-------------------------------|---------------|
| Phase 0 | 6 hours | 6 hours (1 agent) | 1 |
| Phase 1 | 12 hours | 5 hours (3 agents) | 3 |
| Phase 2 | 16 hours | 5 hours (4 agents) | 4 |
| Phase 3 | 15 hours | 5 hours (3 agents) | 3 |
| Phase 4 | 12 hours | 6 hours (2 agents) | 2 |
| Phase 5 | 5 hours | 5 hours (1 agent) | 1 |
| **Total** | **66 hours** | **32 hours** | **4 peak** |

**Optimal Strategy:** With 4 concurrent agents, complete in ~32 hours (~4 days at 8 hours/day).

### Realistic Timeline

**Week 1: Foundation + Core Infrastructure**
- Day 1-2: Task 01 (Foundation)
- Day 3-5: Tasks 02-04 in parallel (Core Infrastructure)

**Week 2: Business Logic + API Layer**
- Day 1-3: Tasks 05-08 in parallel (Business Logic)
- Day 4-5: Tasks 09-11 in parallel (API & Observability)

**Week 3: Infrastructure + Final Validation**
- Day 1-3: Tasks 12-13 in parallel (Docker + Testing)
- Day 4: Task 14 (E2E Integration)
- Day 5: Buffer for issues, final polish

**Total: 3 weeks with 2-4 concurrent developers**

## Tips for Success

### 1. Clear Contracts First

Before starting Phase 2, ensure Phase 1 components have clear interfaces:
- Valkey/Redis client API documented
- SearXNG client return types defined
- Extraction client interfaces agreed upon

### 2. Stub Dependencies

When working in parallel, stub dependencies you're waiting for:

```python
# Stub SearXNG client while waiting for Task 03
class SearXNGClient:
    async def search(self, request, request_id):
        # TODO: Replace with real implementation
        return [NormalizedSearchResult(...)]
```

### 3. Test Early and Often

- Run `make test` after each deliverable
- Don't wait until the end to test integration
- Use fixtures to mock dependencies

### 4. Follow the TECH SPEC

 All implementation decisions should reference TECH SPEC sections:
 - Timeouts (request budget 6s; SearXNG 2s + 1 retry 100–300ms; Crawl4AI 2.5s no retry; fallback Trafilatura 2s): TECH SPEC §6.2
 - Error handling: TECH SPEC §6.4
 - API schema: TECH SPEC §6.1, openapi.yaml
 - Rate limits (60/hr IP, 600/hr API key, optional global 10k/hr) and headers: TECH SPEC §6.2, §6.5
 - Cache key includes `max_results`, TTL 1h: TECH SPEC §5.4/§6.2
 - Health: per-component timeout 750ms, includes uptime/timestamp: TECH SPEC §7.4

### 5. Communication for Sequential Dependencies

**Task 10 (Search Endpoint)** has the most dependencies. Coordinate carefully:
- Wait for Tasks 03, 05, 06, 07, 08 to have stable interfaces
- Use stubs initially, then integrate
- Test incrementally as dependencies complete

### 6. Keep Tests Isolated

- Unit tests should not require Valkey/SearXNG/Crawl4AI
- Use mocks for external dependencies in unit tests
- Integration tests clearly marked with `@pytest.mark.integration`

### 7. Docker Comes Last

Task 12 (Docker Compose) should wait until the application works:
- Easier to debug without containers initially
- Docker setup validates that everything integrates correctly; remember to set the actual Crawl4AI image tag and include `.env.example`

### 8. Code Review Discipline

**Critical:** Review prompts require FIXING all issues, not just reporting them.

When reviewing:
1. Check EVERY item in checklists
2. Fix critical issues immediately
3. Fix major issues before PASS verdict
4. Document ALL fixes made
5. Run tests to verify fixes don't break anything
6. Only mark PASS when truly ready for production

## Example Session

### Sequential Workflow (Single Developer)

```bash
# Week 1
cd butterscout

# Day 1-2: Foundation
cat .prompts/tasks/01-foundation.md
# Implement...
make test && make lint && make typecheck
cat .prompts/reviews/01-foundation-review.md
# Review and fix...

# Day 3: Valkey Client
cat .prompts/tasks/02-redis-client.md
# Implement...
make test
cat .prompts/reviews/02-redis-client-review.md
# Review and fix...

# Continue through all tasks...
```

### Parallel Workflow (Multiple Agents)

```bash
# Phase 0 (Agent 1)
# Agent 1 completes Task 01

# Phase 1 (3 agents in parallel)
# Agent 1: Task 02 (Valkey)
# Agent 2: Task 03 (SearXNG)
# Agent 3: Task 04 (Extraction)

# Phase 2 (4 agents in parallel)
# Agent 1: Task 05 (Orchestrator)
# Agent 2: Task 06 (Caching)
# Agent 3: Task 07 (Rate Limiting)
# Agent 4: Task 08 (Ranking)

# Continue through phases...
```

## Integration Testing

After all tasks complete, verify integration:

```bash
# Start all services
docker compose up -d

# Wait for health checks
sleep 30

# Run E2E tests
pytest tests/e2e/ -v

# Run performance validation
pytest tests/e2e/test_performance.py -v

# Verify p95 ≤ 3s
# Run smoke tests
bash scripts/smoke_test.sh

# Check metrics
curl http://localhost:8000/metrics

# Manual testing
curl -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "what is retrieval augmented generation", "max_results": 5}'
```

## Quality Gates

Before marking v0.1 complete, ensure:

✅ All 14 tasks implemented and reviewed
✅ All tests passing (`make test`)
✅ Coverage ≥ 80% (`pytest --cov`)
✅ Lint passing (`make lint`)
✅ Type check passing (`make typecheck`)
✅ Docker Compose working (`docker compose up`)
✅ E2E tests passing (pytest tests/e2e/)
✅ Performance target met (p95 ≤ 3s)
✅ No 5xx errors on representative queries
✅ Release checklist complete
✅ Documentation up to date

## Troubleshooting

### Common Issues

**Issue:** "Tests fail with Valkey connection error"
- **Fix:** Start Valkey: `docker compose up redis -d`
- **Fix:** Check `BS_REDIS_URL` in .env

**Issue:** "Import errors after Task 01"
- **Fix:** Run `uv sync --all-extras` to install package dependencies
- **Fix:** Check `__init__.py` files exist in all packages

**Issue:** "Task 10 fails with missing dependencies"
- **Fix:** Ensure Tasks 03, 05-08 are complete first
- **Fix:** Use stubs for incomplete dependencies during development

**Issue:** "Docker build fails"
- **Fix:** Check Dockerfile base image and dependency installation
- **Fix:** Ensure pyproject.toml is valid

**Issue:** "Performance tests fail (p95 > 3s)"
- **Fix:** Check extraction timeout settings
- **Fix:** Verify concurrency limits (BS_MAX_CONCURRENT_EXTRACTIONS)
- **Fix:** Profile slow operations

## Support

- **TECH SPEC:** `TECH SPEC.md` - Complete technical specification
- **ENGINEERING GUIDE:** `ENGINEERING_GUIDE.md` - Development practices
- **OpenAPI Spec:** Will be generated at `/openapi.json`

## Success Metrics

v0.1 is complete when:

1. **Functionality:** All endpoints working per TECH SPEC
2. **Performance:** p95 latency ≤ 3 seconds
3. **Quality:** Test coverage ≥ 80%, no lint/type errors
4. **Documentation:** README complete, .env.example accurate
5. **Infrastructure:** Docker Compose working, health checks passing
6. **Observability:** Logs structured, metrics exposed
7. **Validation:** E2E tests passing, release checklist complete

**Estimated completion time:** 2-4 weeks with 1-4 developers

Good luck building Butterscout! 🦋🔍
