# Code Review: Redis Client & Utilities

**Role:** You are a senior backend engineer specializing in Redis, async Python patterns, and distributed caching strategies.

## Task-Specific Checks

### Redis Client Implementation
- [ ] Connection pool configured with appropriate limits (max_connections=20)
- [ ] Async/await used correctly throughout
- [ ] Connection lifecycle managed properly (connect/disconnect)
- [ ] All Redis operations check if client is connected
- [ ] Error handling doesn't swallow exceptions silently
- [ ] Timeout configurations appropriate for use case
- [ ] `decode_responses=True` set for string handling

### Key Generation
- [ ] Cache keys use stable hashing (SHA256)
- [ ] Keys follow naming convention: `bs:<namespace>:<identifier>`
- [ ] Query normalization is consistent (lowercase, strip)
- [ ] Options hash includes all relevant parameters
- [ ] Domain lists are sorted before hashing
- [ ] Key generation is deterministic (same input → same key)

### Connection Management
- [ ] Singleton pattern implemented correctly (if used)
- [ ] No memory leaks from unclosed connections
- [ ] Graceful shutdown on app termination
- [ ] Thread-safe if needed
- [ ] Connection errors logged with context

### Error Handling
- [ ] Specific exceptions for Redis connection failures
- [ ] Clear error messages with troubleshooting hints
- [ ] Operations don't fail silently on Redis errors
- [ ] Retry logic not needed (fail fast for cache)

## Critical Issues to Watch For

1. **Connection Leaks** - Connections not properly closed lead to resource exhaustion
2. **Non-Deterministic Keys** - Unstable cache keys break caching effectiveness
3. **Missing Connection Checks** - Operations fail with cryptic errors if not connected
4. **Synchronous Blocking** - Using sync Redis client in async code blocks event loop
5. **Incorrect Async Usage** - Missing `await` on async Redis operations
6. **Poor Error Handling** - Swallowing Redis errors makes debugging impossible
7. **Key Collision Risk** - Weak hashing or missing namespaces cause key conflicts
8. **Memory Leaks** - Not closing connections in exception paths
9. **Missing TTL** - Keys without expiration can fill Redis memory
10. **Race Conditions** - Concurrent access to connection pool not handled

## Testing Verification

- [ ] Tests pass with real Redis connection
- [ ] Test: Connection succeeds with valid URL
- [ ] Test: Ping returns True when connected
- [ ] Test: Operations raise error when not connected
- [ ] Test: Get/set/delete work correctly
- [ ] Test: TTL expiration works
- [ ] Test: Cache keys identical for same request
- [ ] Test: Cache keys different for different requests
- [ ] Test: Connection cleanup on disconnect
- [ ] Test: Rate limit key format correct

## Review & Fix Process

**IMPORTANT:** This is an active code improvement task, not passive inspection.

### Your Responsibilities
1. **Identify Issues**: Check all items in the checklists above
2. **Fix Thoroughly**: Fix ALL issues found (critical, major, AND minor)
3. **Verify Fixes**: Run tests after fixes, check for regressions
4. **Document Changes**: List what was fixed in the output format below

**Do not just report issues - fix them completely before marking as PASS.**

### Fix Priority
- **Critical**: Connection leaks, non-deterministic keys, missing awaits
- **Major**: Poor error handling, missing connection checks, weak tests
- **Minor**: Code style, docstring clarity, log message improvements

## Output Format

**Verdict:** PASS / FAIL

**Critical Issues:**
1. [Issue] - [File:line] - [Fix applied]

**Async/Redis Issues:**
- [List any async or Redis-specific problems fixed]

**Key Generation Issues:**
- [List any cache key stability or hashing problems fixed]

**Testing Issues:**
- [List any test coverage or correctness issues fixed]

**Code Quality Score:** X/10

**Summary:**
[Brief summary of review outcome and major improvements made]
