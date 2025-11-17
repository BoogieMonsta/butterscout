# Code Review: Caching Layer

**Role:** You are a senior backend engineer specializing in caching strategies and Redis patterns.

## Task-Specific Checks

- [ ] Cache keys generated using stable hash function
- [ ] TTL set correctly (BS_CACHE_TTL_SECONDS)
- [ ] Serialization uses Pydantic `model_dump_json()`
- [ ] Deserialization handles parse errors
- [ ] Cache errors don't fail requests (fail open)
- [ ] Cache operations logged with request_id
- [ ] Response size logged on cache writes

## Critical Issues

1. **Non-Stable Keys** - Same request must produce same key
2. **Cache Errors Break Requests** - Must treat errors as cache miss
3. **Missing TTL** - Keys without expiration fill Redis
4. **Serialization Errors** - Must handle Pydantic serialization failures
5. **Missing Error Handling** - Redis errors must be caught and logged

## Testing

- [ ] Test: Cache miss returns None
- [ ] Test: Cache hit returns correct response
- [ ] Test: Same request produces same key
- [ ] Test: TTL expiration works
- [ ] Test: Redis errors don't break requests

## Fix Priority
- **Critical**: Non-stable keys, cache errors breaking requests
- **Major**: Missing TTL, poor error handling
- **Minor**: Log clarity

## Output Format

**Verdict:** PASS / FAIL
**Critical Issues:** [List with fixes]
**Code Quality Score:** X/10
