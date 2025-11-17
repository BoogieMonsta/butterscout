# Code Review: SearXNG Client

**Role:** You are a senior backend engineer specializing in HTTP client integration, retry logic, and API resilience patterns.

## Task-Specific Checks

### HTTP Client Configuration
- [ ] Timeouts configured correctly (connect, read, write, pool)
- [ ] Connection pooling enabled with appropriate limits
- [ ] `follow_redirects` set appropriately
- [ ] Client lifecycle managed (connect/disconnect)
- [ ] httpx AsyncClient used (not sync Client)

### Retry Logic (TECH SPEC §4.2)
- [ ] Exactly 1 retry on 5xx/timeout (2 total attempts)
- [ ] Jittered backoff between 100-300ms
- [ ] No retry on 4xx errors
- [ ] Retry logic doesn't mask original error
- [ ] Attempt count logged

### Request Building
- [ ] Query parameter encoding correct
- [ ] Language parameter passed when specified
- [ ] freshness_days converted to time_range correctly
- [ ] Request format = "json"
- [ ] No hardcoded values (use settings)

### Response Parsing
- [ ] JSON parsing has error handling
- [ ] Missing fields handled gracefully
- [ ] Score normalization correct (fallback to 1/(position+1))
- [ ] URL validation (valid HTTP URL)
- [ ] Snippet truncation to reasonable length (500 chars)
- [ ] Results limited to max_results

### Domain Filtering Integration
- [ ] Domain filter applied correctly
- [ ] Whitelist/blacklist logic correct
- [ ] www. prefix handled
- [ ] Subdomain matching works

## Critical Issues to Watch For

1. **Missing Retries** - Must retry once on 5xx/timeout per TECH SPEC
2. **Infinite Retry Loop** - Retry logic must have hard limit
3. **Missing Timeout** - Requests can hang indefinitely
4. **Incorrect Async Usage** - Missing `await` or using sync httpx
5. **Poor Error Handling** - Raw exceptions not caught and logged
6. **Score Calculation Errors** - Division by zero, negative scores
7. **URL Validation Missing** - Invalid URLs crash downstream
8. **Request ID Missing** - Logging without request context
9. **Hardcoded URLs** - Not using settings.BS_SEARXNG_URL
10. **Health Check Timeout** - Health check must use BS_HEALTH_TIMEOUT_MS

## Testing Verification

- [ ] Tests use respx or httpx mocking
- [ ] Test: Successful search returns normalized results
- [ ] Test: Retry happens on timeout
- [ ] Test: Retry happens on 5xx
- [ ] Test: No retry on 4xx
- [ ] Test: Score fallback when not provided
- [ ] Test: freshness_days converted correctly
- [ ] Test: Health check works
- [ ] Test: Health check respects timeout
- [ ] Test: Domain filtering applied

## Review & Fix Process

**IMPORTANT:** Fix ALL issues found (critical, major, AND minor). Verify fixes work with tests.

### Fix Priority
- **Critical**: Missing retries, incorrect timeout, broken async
- **Major**: Poor error handling, missing tests, score calculation errors
- **Minor**: Log clarity, code style, docstring improvements

## Output Format

**Verdict:** PASS / FAIL

**Critical Issues:**
1. [Issue] - [File:line] - [Fix applied]

**HTTP Client Issues:**
- [List HTTP/retry/timeout problems fixed]

**Parsing Issues:**
- [List response parsing problems fixed]

**Code Quality Score:** X/10

**Summary:**
[Brief summary of improvements]
