# Code Review: Ranking & Deduplication

**Role:** You are a senior backend engineer specializing in search relevance and ranking algorithms.

## Task-Specific Checks

- [ ] URL normalization handles all cases (www., trailing slash, query params)
- [ ] Tracking parameters removed (utm_*, fbclid, gclid)
- [ ] Query parameters sorted alphabetically
- [ ] Deduplication keeps first occurrence (highest ranked)
- [ ] Ranking applies correct factors (search score, domain boost, extraction boost)
- [ ] Domain filtering blocks/boosts correctly
- [ ] Score calculation handles edge cases (0 score, missing fields)

## Critical Issues

1. **Non-Deterministic Normalization** - Same URL produces different normalized forms
2. **Duplicate Removal Breaks Ranking** - Removing wrong occurrence
3. **Domain Matching Bugs** - Subdomain logic incorrect (www., wildcards)
4. **Score Calculation Errors** - Division by zero, negative scores
5. **Ranking Unstable** - Same input produces different order

## Testing

- [ ] Test: URL normalization is deterministic
- [ ] Test: Tracking params removed
- [ ] Test: Query params sorted
- [ ] Test: Duplicates removed (keeps first)
- [ ] Test: Domain boost applied correctly
- [ ] Test: Blocked domains filtered
- [ ] Test: Ranking order stable

## Fix Priority
- **Critical**: Non-deterministic behavior, domain matching bugs
- **Major**: Score calculation errors, missing tests
- **Minor**: Code style, comments

## Output Format

**Verdict:** PASS / FAIL
**Critical Issues:** [List with fixes]
**Code Quality Score:** X/10
