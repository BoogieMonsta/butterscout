FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Development stage
FROM base AS development

# Install all dependencies including dev extras
RUN uv sync --all-extras

# Development runs as root for easier volume mounting
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "butterscout.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Production stage
FROM base AS production

# Install only production dependencies
RUN uv sync --no-dev

# Copy application code
COPY butterscout/ ./butterscout/

# Create non-root user
RUN useradd -m -u 1000 butterscout && \
    chown -R butterscout:butterscout /app

USER butterscout

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["uv", "run", "uvicorn", "butterscout.main:app", "--host", "0.0.0.0", "--port", "8000"]
