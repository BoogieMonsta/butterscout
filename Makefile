.PHONY: lint format typecheck test openapi-validate up down clean install dev

lint:
	uv run ruff check butterscout/ tests/

format:
	uv run ruff format butterscout/ tests/

typecheck:
	uv run mypy --strict butterscout/

test:
	uv run pytest tests/ -v --cov=butterscout --cov-report=term-missing

openapi-validate:
	uv run python -m openapi_spec_validator openapi.yaml

up:
	docker compose up -d

down:
	docker compose down

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov/ .venv/

install:
	uv sync --all-extras

dev:
	uv run uvicorn butterscout.main:app --reload --host 0.0.0.0 --port 8000
