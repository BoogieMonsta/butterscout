# Code Review: Logging & Metrics

**Role:** You are a senior backend engineer specializing in observability, structured logging, and Prometheus metrics.

## Task-Specific Checks

- [ ] Structured logging configured (JSON output)
- [ ] All required log fields present (ts, level, msg, request_id)
- [ ] Prometheus metrics use correct types (Counter, Histogram, Gauge)
- [ ] Metric names follow naming convention (butterscout_, snake_case, _total/_seconds)
- [ ] Histogram buckets appropriate for use case
- [ ] Metrics recorded at correct points in code
- [ ] Metrics endpoint secured (auth if BS_API_KEY set)
- [ ] Metrics can be disabled (BS_ENABLE_METRICS)
- [ ] No unbounded cardinality in labels
- [ ] Uptime gauge updated regularly

## Critical Issues

1. **Missing Request ID** - Logs without request context are useless
2. **Wrong Metric Type** - Using Counter for latency, Gauge for totals
3. **Unbounded Cardinality** - Labels with unlimited values (full URLs, user IDs)
4. **Metrics Not Recorded** - Key operations don't update metrics
5. **JSON Logging Not Configured** - Plain text logs in production
6. **Missing Fields** - Required log fields not present (TECH SPEC §4.1)
7. **Metrics Endpoint Unsecured** - Publicly accessible metrics leak info
8. **Wrong Bucket Sizes** - Histogram buckets don't match actual latencies
9. **Synchronous Operations** - Metrics recording blocks request
10. **Memory Leaks** - Metrics with high cardinality fill memory

## Testing

- [ ] Test: Metrics recorded correctly
- [ ] Test: Logs are valid JSON
- [ ] Test: Request ID in all logs
- [ ] Test: Metrics endpoint returns Prometheus format
- [ ] Test: Metrics endpoint auth works
- [ ] Test: Uptime gauge updates

## Fix Priority
- **Critical**: Missing request ID, wrong metric types, unbounded cardinality
- **Major**: Metrics not recorded, unsecured endpoint
- **Minor**: Bucket sizes, log formatting

## Output Format

**Verdict:** PASS / FAIL
**Critical Issues:** [List with fixes]
**Code Quality Score:** X/10
