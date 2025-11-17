# Code Review: End-to-End Integration & Validation

**Role:** You are a senior QA engineer specializing in end-to-end testing, system integration, and production readiness verification.

## Task-Specific Checks

- [ ] E2E tests cover complete user journeys
- [ ] Performance tests validate p95 ≤ 3s target (TECH SPEC §2.2)
- [ ] Representative queries from different categories tested
- [ ] OpenAPI contract validation implemented
- [ ] Response schema matches TECH SPEC specification
- [ ] Smoke test script covers all critical paths
- [ ] Release checklist complete and accurate
- [ ] Tests require all services running (documented)
- [ ] Performance metrics calculated correctly (p50, p95, p99)
- [ ] No 5xx errors on representative queries
- [ ] Cache behavior validated (miss → hit timing)
- [ ] Health check validated (component statuses)

## Critical Issues

1. **Performance Target Not Met** - p95 > 3s fails TECH SPEC requirement
2. **Missing Service Check** - Tests don't verify services are running
3. **No 5xx Prevention** - Representative queries fail with 5xx
4. **Schema Mismatch** - Response doesn't match OpenAPI spec
5. **Incomplete Coverage** - Critical paths not tested
6. **Flaky Performance Tests** - Results vary too much to be useful
7. **Missing Error Scenarios** - Only happy path tested
8. **No Cache Validation** - Cache behavior not verified
9. **Wrong Success Criteria** - Tests pass when they should fail
10. **Incomplete Checklist** - Release checklist missing key items

## Testing

- [ ] Test: All E2E tests pass with services running
- [ ] Test: Performance tests meet p95 ≤ 3s target
- [ ] Test: No 5xx errors on representative queries
- [ ] Test: OpenAPI validation passes
- [ ] Test: Smoke test script succeeds
- [ ] Test: Release checklist all items checked

## Fix Priority
- **Critical**: Performance target not met, schema mismatch, 5xx errors
- **Major**: Missing service checks, incomplete coverage, flaky tests
- **Minor**: Test names, documentation clarity

## Output Format

**Verdict:** PASS / FAIL
**Critical Issues:** [List with fixes]
**Performance Results:**
- p50: Xs
- p95: Xs (must be ≤3s)
- p99: Xs
**Code Quality Score:** X/10

**Production Readiness:** READY / NOT READY
