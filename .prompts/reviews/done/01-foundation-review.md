# Code Review: Project Foundation & Configuration

**Role:** You are a senior Python architect specializing in project structure, Pydantic settings patterns, and FastAPI best practices.

## Task-Specific Checks

### Project Structure
- [ ] Directory structure follows Python package conventions
- [ ] `__init__.py` files present in all package directories
- [ ] Clear separation of concerns (models, services, clients, utils)
- [ ] No circular import dependencies
- [ ] Test directory mirrors source structure

### Pydantic Settings
- [ ] All env vars use correct type annotations
- [ ] Required vs optional fields correctly specified
- [ ] Default values are production-safe
- [ ] Validation methods use `@field_validator` correctly
- [ ] Settings class uses `BaseSettings` from `pydantic-settings`
- [ ] `model_config` properly configured for env loading
- [ ] Property methods for derived values (list parsing) work correctly

### Request/Response Models
- [ ] All constraints from TECH SPEC §6 implemented
- [ ] Field validators check exact requirements (1-512 chars, 1-25 max_results)
- [ ] Error messages are clear and actionable
- [ ] Optional fields use `Optional[T]` annotation
- [ ] Default values match TECH SPEC defaults
- [ ] Pydantic V2 syntax used (`Field`, validators, `model_dump`)

### Dependencies (pyproject.toml)
- [ ] All required packages listed with minimum versions
- [ ] Dev dependencies separated from production
- [ ] No unused or duplicate dependencies
- [ ] Version constraints allow minor updates (`>=`)
- [ ] Build system configured correctly

### Configuration Files
- [ ] `.env.example` includes ALL env vars from TECH SPEC
- [ ] `.env.example` has clear comments explaining each var
- [ ] `.env.example` values are safe placeholders (no real secrets)
- [ ] `Makefile` targets work and are well-documented
- [ ] `README.md` has clear quick start instructions

### Type Safety
- [ ] All functions have type annotations (params + return)
- [ ] No use of `Any` type without explicit justification
- [ ] Pydantic models used instead of raw dicts where appropriate
- [ ] Type stubs imported where needed (`from typing import ...`)

## Critical Issues to Watch For

1. **Missing Required Fields** - All TECH SPEC required settings must be present (BS_SEARXNG_URL, BS_CRAWL4AI_URL, BS_REDIS_URL)
2. **Incorrect Validation Logic** - Query trimming, empty string rejection, max_results bounds must be exact
3. **Unsafe Defaults** - Default rate limits, timeouts must match TECH SPEC precisely
4. **Type Annotation Errors** - Missing or incorrect type hints break mypy strict mode
5. **Import Errors** - Circular imports or missing `__init__.py` break package structure
6. **Pydantic V1 Syntax** - Must use Pydantic V2 (`model_dump`, not `dict()`)
7. **Missing Validators** - Domain/query validation must reject invalid input
8. **Hardcoded Values** - Configuration should be env-driven, not hardcoded
9. **Incomplete .env.example** - Missing any env var from settings.py
10. **Weak URL Validation** - URLs must be validated (http/https scheme)

## Testing Verification

- [ ] `make test` passes with 90%+ coverage for models/config
- [ ] `make lint` passes with no errors
- [ ] `make typecheck` passes with `--strict` mode
- [ ] Test: Empty query rejected with ValidationError
- [ ] Test: Query with only whitespace rejected
- [ ] Test: max_results=0 rejected
- [ ] Test: max_results=26 rejected
- [ ] Test: > 20 domains rejected
- [ ] Test: Settings load from env vars correctly
- [ ] Test: Invalid URL format raises ValueError
- [ ] Test: Cache key generation is stable for same inputs

## Review & Fix Process

**IMPORTANT:** This is an active code improvement task, not passive inspection.

### Your Responsibilities
1. **Identify Issues**: Check all items in the checklists above
2. **Fix Thoroughly**: Fix ALL issues found (critical, major, AND minor)
3. **Verify Fixes**: Run tests after fixes, check for regressions
4. **Document Changes**: List what was fixed in the output format below

**Do not just report issues - fix them completely before marking as PASS.**

### Fix Priority
- **Critical**: Must fix (missing required fields, broken validation, type errors)
- **Major**: Should fix (incorrect defaults, weak validation, missing tests)
- **Minor**: Fix if time permits (code style, comment clarity, example values)

## Output Format

**Verdict:** PASS / FAIL

**Critical Issues:**
1. [Issue] - [File:line] - [Fix applied]

**Configuration Issues:**
- [List any config/settings problems fixed]

**Validation Issues:**
- [List any Pydantic validation problems fixed]

**Type Safety Issues:**
- [List any type annotation problems fixed]

**Testing Issues:**
- [List any test coverage or correctness issues fixed]

**Code Quality Score:** X/10

**Summary:**
[Brief summary of review outcome and major improvements made]
