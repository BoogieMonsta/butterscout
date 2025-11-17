# Code Review: Extraction Clients

**Role:** You are a senior Python engineer specializing in web scraping, async I/O, and fallback strategies.

## Task-Specific Checks

### Crawl4AI Client
- [ ] HTTP client configured with correct timeout (BS_EXTRACTION_TIMEOUT_MS)
- [ ] Request format matches Crawl4AI API
- [ ] Error handling distinguishes timeout vs other errors
- [ ] Extraction timing measured and logged
- [ ] Health check implemented and respects BS_HEALTH_TIMEOUT_MS

### Trafilatura Client
- [ ] ThreadPoolExecutor configured correctly (BS_FALLBACK_MAX_WORKERS)
- [ ] Async wrapper properly awaits executor
- [ ] Sync extraction function runs in executor (not blocking event loop)
- [ ] HTTP client for fetching HTML configured
- [ ] Trafilatura options set correctly (no comments, include tables)

### Extraction Strategy
- [ ] Always tries Crawl4AI first
- [ ] Falls back to Trafilatura on any Crawl4AI failure
- [ ] Returns ExtractedContent with extraction_ok=False on all failures
- [ ] Never raises exceptions (graceful degradation)
- [ ] Fallback respects BS_FALLBACK_ENABLED setting
- [ ] Logs failures with reason (timeout, error, empty)

### Content Quality
- [ ] Word count calculated correctly
- [ ] Content cleaned (no navigation, ads)
- [ ] Empty content handled gracefully
- [ ] Error messages preserved in result

## Critical Issues to Watch For

1. **Blocking Event Loop** - Trafilatura must run in ThreadPoolExecutor, not main thread
2. **Missing Fallback** - Must try fallback on Crawl4AI failure
3. **Exceptions Not Caught** - Strategy must never raise, always return result
4. **Timeout Not Enforced** - Extractions can hang without timeout
5. **Memory Leaks** - ThreadPoolExecutor not shut down properly
6. **Missing await** - Async functions not awaited
7. **Incorrect Timing** - Extraction time not measured or logged
8. **Empty Content Not Handled** - Empty extractions should mark extraction_ok=False
9. **Health Check Missing** - Services need health checks
10. **Wrong Timeout Used** - Must use correct timeout setting (extraction vs fallback)

## Testing Verification

- [ ] Test: Crawl4AI successful extraction works
- [ ] Test: Fallback works when Crawl4AI fails
- [ ] Test: Both failing returns extraction_ok=False
- [ ] Test: Trafilatura runs in thread pool (doesn't block)
- [ ] Test: Timeouts enforced
- [ ] Test: Content cleaning works (removes nav/ads)
- [ ] Test: Word count calculated correctly

## Review & Fix Process

**IMPORTANT:** Fix ALL issues (critical, major, minor). Test thoroughly.

### Fix Priority
- **Critical**: Blocking event loop, missing fallback, exceptions not caught
- **Major**: Timeout not enforced, poor error handling
- **Minor**: Log clarity, docstrings

## Output Format

**Verdict:** PASS / FAIL

**Critical Issues:**
1. [Issue] - [File:line] - [Fix]

**Extraction Issues:**
- [List problems fixed]

**Code Quality Score:** X/10
