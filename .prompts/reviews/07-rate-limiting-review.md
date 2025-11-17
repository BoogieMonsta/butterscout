# Code Review: Rate Limiting System

**Role:** You are a senior backend engineer specializing in API rate limiting and DoS prevention.

## Task-Specific Checks

- [ ] Sliding window algorithm implemented correctly (Redis ZSET)
- [ ] Old entries removed before counting (ZREMRANGEBYSCORE)
- [ ] Rate limit tiers work (IP, API key, global)
- [ ] Retry-after calculated correctly
- [ ] Rate limit headers generated correctly
- [ ] Fail-open on Redis errors (don't block traffic)
- [ ] Key expiration set (window + buffer)

## Critical Issues

1. **Wrong Algorithm** - Must use sliding window, not token bucket
2. **No Cleanup** - Old entries not removed, counts grow forever
3. **Fail Closed** - Redis errors block all traffic
4. **Incorrect Retry-After** - Wrong calculation breaks clients
5. **Missing Expiration** - Keys never expire, fill Redis
6. **Race Conditions** - Concurrent checks not handled atomically

## Testing

- [ ] Test: Allows requests within limit
- [ ] Test: Blocks requests over limit
- [ ] Test: Retry-after calculated correctly
- [ ] Test: API key gets higher limit than IP
- [ ] Test: Redis errors don't block requests
- [ ] Test: Headers generated correctly

## Fix Priority
- **Critical**: Wrong algorithm, fail closed, no cleanup
- **Major**: Incorrect retry-after, missing tests
- **Minor**: Header naming, log clarity

## Output Format

**Verdict:** PASS / FAIL
**Critical Issues:** [List with fixes]
**Code Quality Score:** X/10
