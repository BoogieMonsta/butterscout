"""FastAPI application entry point (stub for foundation task)."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI

app = FastAPI(title="Butterscout API", version="0.1.0")


@app.get("/health")
async def health_stub() -> dict[str, Any]:
    """Placeholder health endpoint until full implementation."""
    return {"status": "ok"}
