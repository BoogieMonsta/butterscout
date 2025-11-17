# Code Review: Search Endpoint Implementation

**Role:** You are a senior FastAPI backend engineer specializing in RESTful API design and request orchestration.

## Task-Specific Checks

- [ ] Request lifecycle follows exact order from TECH SPEC §4.2
- [ ] Authentication checked if BS_API_KEY set
- [ ] Rate limiting applied before cache check
- [ ] Cache checked before SearXNG call
- [ ] Domain filtering applied to search results
- [ ] Deduplication happens before extraction
- [ ] Extraction only runs if include_content=True
- [ ] Ranking applied to final results
- [ ] Response cached after completion
- [ ] Rate limit headers added to all responses
- [ ] Error responses follow TECH SPEC format
- [ ] Partial failures handled gracefully (extraction errors don't fail request)
- [ ] Request ID propagated through all operations

## Critical Issues

1. **Wrong Lifecycle Order** - Must follow TECH SPEC §4.2 exactly
2. **Missing Authentication** - API key not checked when required
3. **Cache After Rate Limit** - Must rate limit first
4. **Exceptions Not Caught** - Upstream errors not handled
5. **Missing Rate Limit Headers** - Headers required on all responses
6. **Wrong Error Format** - Errors don't match TECH SPEC schema
7. **Extraction Failures Break Request** - Must handle partial failures
8. **Missing Request Tracing** - request_id not passed to services
9. **Cache Miss Doesn't Cache** - Response not stored after generation
10. **Blocking Operations** - Sync code in async handler

## Testing

- [ ] Test: Authentication works
- [ ] Test: Rate limiting blocks over limit
- [ ] Test: Cache hit returns immediately
- [ ] Test: Cache miss fetches and caches
- [ ] Test: include_content=False skips extraction
- [ ] Test: Extraction failures don't break request
- [ ] Test: Domain filtering applied
- [ ] Test: Rate limit headers present
- [ ] Test: Error format correct

## Fix Priority
- **Critical**: Wrong lifecycle order, missing auth, broken error handling
- **Major**: Missing headers, cache issues, test coverage
- **Minor**: Log clarity, docstrings

## Output Format

**Verdict:** PASS / FAIL
**Critical Issues:** [List with fixes]
**Code Quality Score:** X/10
