# Code Review: Extraction Orchestrator

**Role:** You are a senior async Python engineer specializing in concurrency control and distributed systems patterns.

## Task-Specific Checks

### Concurrency Control
- [ ] Semaphore initialized with BS_MAX_CONCURRENT_EXTRACTIONS
- [ ] Semaphore used correctly in async context manager
- [ ] No more than max_concurrent extractions run simultaneously
- [ ] Semaphore applied per-request, not globally

### Graceful Degradation
- [ ] `asyncio.gather` uses `return_exceptions=True`
- [ ] Exceptions converted to failed ExtractedContent objects
- [ ] Never raises exceptions (always returns list)
- [ ] Partial failures don't break entire request
- [ ] Failed extractions logged with context

### Result Assembly
- [ ] URL matching between search results and extracted content correct
- [ ] Missing extractions handled (content=None)
- [ ] Extraction metadata populated correctly
- [ ] Domain extracted from URL correctly
- [ ] Rank numbers assigned sequentially

### Content Quality Filtering
- [ ] Minimum word count check (10 words)
- [ ] Empty content filtered appropriately
- [ ] Failed extractions retained (still have snippet)

## Critical Issues to Watch For

1. **Concurrency Not Limited** - Must use semaphore, not unlimited concurrency
2. **Exceptions Not Caught** - Must catch all exceptions, never fail request
3. **Blocking Operations** - Must use async/await throughout
4. **URL Mismatch** - Extracted content not matched to correct search result
5. **Missing Timing** - Extraction timing not measured
6. **Memory Leaks** - Tasks not properly cleaned up
7. **Race Conditions** - Shared state not protected
8. **Empty Results Not Handled** - Must handle zero search results gracefully
9. **Metrics Not Recorded** - Success/failure counts not logged
10. **Request Budget Not Enforced** - Should track total time vs BS_REQUEST_TIMEOUT_MS

## Testing Verification

- [ ] Test: Parallel extraction works with semaphore
- [ ] Test: Exceptions don't break orchestrator
- [ ] Test: Partial failures handled gracefully
- [ ] Test: Result assembly matches URLs correctly
- [ ] Test: Content filtering removes short content
- [ ] Test: Metrics logged correctly

## Review & Fix Process

**IMPORTANT:** Fix ALL issues. Test concurrency behavior.

### Fix Priority
- **Critical**: Concurrency not limited, exceptions not caught
- **Major**: Poor error handling, missing tests
- **Minor**: Log clarity, docstrings

## Output Format

**Verdict:** PASS / FAIL

**Critical Issues:**
1. [Issue] - [File:line] - [Fix]

**Concurrency Issues:**
- [List problems fixed]

**Code Quality Score:** X/10
