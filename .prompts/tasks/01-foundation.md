# Task 01: Project Foundation & Configuration

**Role:** You are a senior Python backend engineer specializing in FastAPI application architecture and configuration management.

## Context

This is the foundation task for Butterscout - an open-source web search and extraction API for LLM agents. This task establishes the project structure, configuration system, and core data models that all other components will depend on.

Refer to **[TECH SPEC.md]** §4.1, §5, §6 and **[ENGINEERING_GUIDE.md]** §9 for complete details.

## Deliverables

### 1. Project Structure (`/`)

Create a clean, maintainable Python project layout:

```
butterscout/
├── pyproject.toml           # Poetry/pip config with all dependencies
├── .env.example             # Example environment variables
├── Makefile                 # Common dev tasks
├── README.md                # Basic project overview
├── butterscout/
│   ├── __init__.py
│   ├── main.py             # FastAPI app entry point
│   ├── config.py           # Pydantic settings
│   ├── models/
│   │   ├── __init__.py
│   │   ├── requests.py     # Request models
│   │   ├── responses.py    # Response models
│   │   └── internal.py     # Internal data models
│   └── utils/
│       ├── __init__.py
│       └── common.py       # Shared utilities
└── tests/
    ├── __init__.py
    ├── conftest.py
    └── unit/
        └── __init__.py
```

### 2. Configuration System (`butterscout/config.py`)

Implement env-driven Pydantic settings with:
- All required env vars from TECH SPEC §7.2
- Type-safe defaults
- Startup validation that fails fast
- Clear error messages for missing/invalid config

```python
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Required settings
    BS_SEARXNG_URL: str
    BS_CRAWL4AI_URL: str
    BS_REDIS_URL: str

    # Optional auth
    BS_API_KEY: Optional[str] = None

    # Cache settings
    BS_CACHE_TTL_SECONDS: int = 3600

    # Rate limiting
    BS_RATE_LIMIT_PER_HOUR: int = 60
    BS_API_KEY_RATE_LIMIT_PER_HOUR: int = 600
    BS_GLOBAL_RATE_LIMIT_PER_HOUR: int = 10000

    # Extraction settings
    BS_MAX_RESULTS: int = 10
    BS_MAX_CONCURRENT_EXTRACTIONS: int = 4
    BS_EXTRACTION_TIMEOUT_MS: int = 2500
    BS_FALLBACK_TIMEOUT_MS: int = 2000
    BS_REQUEST_TIMEOUT_MS: int = 6000

    # Observability
    BS_LOG_LEVEL: str = "info"
    BS_ENABLE_METRICS: bool = True

    # Fallback extractor
    BS_FALLBACK_ENABLED: bool = True
    BS_FALLBACK_MAX_WORKERS: int = 2

    # Health check
    BS_HEALTH_TIMEOUT_MS: int = 750

    # Domain filtering
    BS_ALLOWED_DOMAINS: str = ""  # comma-separated
    BS_BLOCKED_DOMAINS: str = ""  # comma-separated

    class Config:
        env_file = ".env"
        case_sensitive = True

    @property
    def allowed_domains_list(self) -> list[str]:
        return [d.strip() for d in self.BS_ALLOWED_DOMAINS.split(",") if d.strip()]

    @property
    def blocked_domains_list(self) -> list[str]:
        return [d.strip() for d in self.BS_BLOCKED_DOMAINS.split(",") if d.strip()]
```

### 3. Request Models (`butterscout/models/requests.py`)

Implement Pydantic models matching TECH SPEC §6.1 schema:

```python
from pydantic import BaseModel, Field, field_validator
from typing import Optional

class SearchOptions(BaseModel):
    domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=20)
    freshness_days: Optional[int] = Field(default=None, gt=0)
    language: str = Field(default="en", min_length=2, max_length=2)

    @field_validator("domains", "exclude_domains")
    def validate_domain_length(cls, v):
        for domain in v:
            if not (3 <= len(domain) <= 255):
                raise ValueError(f"Domain length must be 3-255 chars: {domain}")
        return v

class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    max_results: int = Field(default=10, ge=1, le=25)
    include_content: bool = Field(default=True)
    extract_timeout_ms: int = Field(default=2500, gt=0)
    options: SearchOptions = Field(default_factory=SearchOptions)

    @field_validator("query")
    def validate_query(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("Query cannot be empty or whitespace-only")
        return v
```

### 4. Response Models (`butterscout/models/responses.py`)

Implement response schemas from TECH SPEC §6.1:

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal

class ResultMetadata(BaseModel):
    domain: str
    word_count: int
    extracted_by: Literal["crawl4ai", "trafilatura", "none"]
    extraction_ok: bool

class ResultScores(BaseModel):
    search_score: float
    rank: int

class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    content: Optional[str] = None
    metadata: ResultMetadata
    scores: ResultScores
    source: str

class ResponseMetadata(BaseModel):
    search_time_ms: int
    searxng_time_ms: Optional[int] = None
    extraction_time_ms: Optional[int] = None
    cache_hit: bool
    sources_queried: list[str]
    api_version: str = "v1"
    rate_limited: bool = False

class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
    metadata: ResponseMetadata

class ErrorDetails(BaseModel):
    component: Optional[str] = None
    timeout: Optional[bool] = None
    retry_after_ms: Optional[int] = None
    fields: Optional[list[str]] = None

class ErrorResponse(BaseModel):
    error: dict  # {code, message, details}
    metadata: dict  # {request_id, api_version, timestamp}
```

### 5. Internal Models (`butterscout/models/internal.py`)

Create internal data structures:

```python
from pydantic import BaseModel, HttpUrl
from typing import Optional
from datetime import datetime

class NormalizedSearchResult(BaseModel):
    """Internal model for search results from SearXNG"""
    title: str
    url: HttpUrl
    snippet: str
    score: float
    source: str = "searxng"

class ExtractedContent(BaseModel):
    """Internal model for extracted content"""
    url: HttpUrl
    content: str
    word_count: int
    extracted_by: str
    extraction_ok: bool
    extraction_time_ms: int
    error: Optional[str] = None

class CacheKey(BaseModel):
    """Cache key components"""
    query: str
    max_results: int
    include_content: bool
    options_hash: str

    def to_redis_key(self) -> str:
        import hashlib
        parts = f"{self.query}:{self.max_results}:{self.include_content}:{self.options_hash}"
        return f"bs:cache:{hashlib.sha256(parts.encode()).hexdigest()}"
```

### 6. Environment Template (`.env.example`)

Create complete example based on TECH SPEC §7.2 and ENGINEERING_GUIDE docker-compose example:

```env
# Required - Service URLs
BS_SEARXNG_URL=http://searxng:8080
BS_CRAWL4AI_URL=http://crawl4ai:11235
BS_REDIS_URL=redis://redis:6379/0

# Optional - Authentication
BS_API_KEY=

# Cache
BS_CACHE_TTL_SECONDS=3600

# Rate Limiting
BS_RATE_LIMIT_PER_HOUR=60
BS_API_KEY_RATE_LIMIT_PER_HOUR=600
BS_GLOBAL_RATE_LIMIT_PER_HOUR=10000

# Extraction
BS_MAX_RESULTS=10
BS_MAX_CONCURRENT_EXTRACTIONS=4
BS_EXTRACTION_TIMEOUT_MS=2500
BS_FALLBACK_ENABLED=true
BS_FALLBACK_TIMEOUT_MS=2000
BS_FALLBACK_MAX_WORKERS=2
BS_REQUEST_TIMEOUT_MS=6000

# Observability
BS_LOG_LEVEL=info
BS_ENABLE_METRICS=true

# Health Check
BS_HEALTH_TIMEOUT_MS=750

# Domain Filtering (comma-separated)
BS_ALLOWED_DOMAINS=
BS_BLOCKED_DOMAINS=
```

### 7. Makefile (`Makefile`)

Provide dev convenience targets per ENGINEERING_GUIDE §16:

```makefile
.PHONY: lint format typecheck test openapi-validate up down

lint:
	ruff check butterscout/ tests/

format:
	ruff format butterscout/ tests/

typecheck:
	mypy --strict butterscout/

test:
	pytest tests/ -v --cov=butterscout --cov-report=term-missing

openapi-validate:
	@echo "OpenAPI validation will be added with API implementation"

up:
	docker compose up -d

down:
	docker compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov/

install:
	pip install -e ".[dev]"

dev:
	uvicorn butterscout.main:app --reload --host 0.0.0.0 --port 8000
```

### 8. Dependencies (`pyproject.toml`)

Create complete dependency specification:

```toml
[project]
name = "butterscout"
version = "0.1.0"
description = "Open-source web search and extraction API for LLM agents"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn[standard]>=0.24.0",
    "pydantic>=2.5.0",
    "pydantic-settings>=2.1.0",
    "httpx>=0.25.0",
    "redis>=5.0.0",
    "trafilatura>=1.6.0",
    "prometheus-client>=0.19.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
    "mypy>=1.7.0",
    "types-redis>=4.6.0",
]

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.build_meta"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_configs = true

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = "test_*.py"
python_functions = "test_*"
addopts = "-v --strict-markers"
```

### 9. Basic README (`README.md`)

```markdown
# Butterscout

Open-source web search and extraction API built for LLM agents and RAG systems.

## Quick Start

1. Copy environment template:
   ```bash
   cp .env.example .env
   ```

2. Start services:
   ```bash
   make up
   ```

3. Visit API docs: http://localhost:8000/docs

## Development

```bash
# Install dependencies
make install

# Run linting
make lint

# Run tests
make test

# Run type checking
make typecheck
```

## Documentation

- [TECH SPEC.md](./TECH%20SPEC.md) - Technical specification
- [ENGINEERING_GUIDE.md](./ENGINEERING_GUIDE.md) - Development practices

## License

MIT
```

## Key Implementation Details

### Configuration Validation

Implement startup validation that fails fast:

```python
def validate_settings(settings: Settings) -> None:
    """Validate settings on startup, fail fast with clear errors"""
    errors = []

    if not settings.BS_SEARXNG_URL.startswith(("http://", "https://")):
        errors.append("BS_SEARXNG_URL must start with http:// or https://")

    if not settings.BS_CRAWL4AI_URL.startswith(("http://", "https://")):
        errors.append("BS_CRAWL4AI_URL must start with http:// or https://")

    if not settings.BS_REDIS_URL.startswith("redis://"):
        errors.append("BS_REDIS_URL must start with redis://")

    if settings.BS_MAX_RESULTS > 25:
        errors.append("BS_MAX_RESULTS cannot exceed 25")

    if errors:
        raise ValueError(f"Configuration errors:\n  - " + "\n  - ".join(errors))
```

### Request Validation

Follow TECH SPEC §6.1 constraints precisely:
- Query: 1-512 UTF-8 chars, trimmed, reject empty/whitespace
- Domains/exclude_domains: max 20 entries, 3-255 chars each
- max_results: 1-25 hard cap
- freshness_days: must be positive integer if provided

### Type Safety

Use strict mypy configuration:
- Enable `--strict` mode
- No `Any` types without explicit annotation
- All function signatures fully typed
- Use `Optional[T]` for nullable fields

## Testing Requirements

### Unit Tests (`tests/unit/test_config.py`, `tests/unit/test_models.py`)

```python
def test_settings_validation():
    """Test config validation catches invalid URLs"""
    with pytest.raises(ValueError):
        Settings(
            BS_SEARXNG_URL="invalid",
            BS_CRAWL4AI_URL="http://crawl4ai:11235",
            BS_REDIS_URL="redis://localhost:6379"
        )

def test_search_request_validation():
    """Test request model validation"""
    # Empty query should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="   ")

    # Too many domains should fail
    with pytest.raises(ValidationError):
        SearchRequest(
            query="test",
            options=SearchOptions(domains=["example.com"] * 21)
        )

    # max_results over limit should fail
    with pytest.raises(ValidationError):
        SearchRequest(query="test", max_results=26)

def test_cache_key_generation():
    """Test cache key is stable and unique"""
    from butterscout.models.internal import CacheKey

    key1 = CacheKey(
        query="test query",
        max_results=10,
        include_content=True,
        options_hash="abc123"
    )

    key2 = CacheKey(
        query="test query",
        max_results=10,
        include_content=True,
        options_hash="abc123"
    )

    assert key1.to_redis_key() == key2.to_redis_key()
```

- Test all Pydantic validators work correctly
- Test config loading from env vars
- Test request/response serialization
- Test cache key generation is stable
- Test error response formatting

### Coverage Target

- Minimum 90% coverage for models and config
- All validation logic must be tested

## Performance Requirements

- Config loading: < 100ms
- Model validation: < 1ms per request
- No blocking I/O in model code

## Output Format

When complete, provide:

1. ✅ Confirmation all files created
2. 📊 Directory tree output (using `tree` or `find`)
3. ✅ Tests passing: `make test`
4. ✅ Type check passing: `make typecheck`
5. ✅ Lint passing: `make lint`
6. 📝 Example of loading config and validating a request

## Dependencies

- **None** - This is the foundation task

## Time Estimate

4-6 hours

## Reference

- [TECH SPEC.md] §4.1: Components
- [TECH SPEC.md] §5: Technology Choices
- [TECH SPEC.md] §6.1: API Design - Request/Response schemas
- [TECH SPEC.md] §6.2: Defaults, Limits & Timeouts
- [TECH SPEC.md] §6.3: Schema Precision
- [TECH SPEC.md] §7.2: Configuration (env vars)
- [ENGINEERING_GUIDE.md] §9: Config Discipline
- [ENGINEERING_GUIDE.md] §16: Tooling & CI Gates
