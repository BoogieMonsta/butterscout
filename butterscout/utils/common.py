"""Shared utility helpers."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict


def stable_hash(payload: Dict[str, Any]) -> str:
    """Generate a stable SHA256 hash for a JSON-serializable payload."""
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode()).hexdigest()
