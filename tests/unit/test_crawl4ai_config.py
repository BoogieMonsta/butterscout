"""Guard for the Crawl4AI config Butterscout mounts over the upstream one."""

from __future__ import annotations

import re
from pathlib import Path

from butterscout.clients.crawl4ai_client import RESPONSE_GRACE_SECONDS
from butterscout.config import MAX_REQUEST_TIMEOUT_MS

CONFIG = Path(__file__).parents[2] / "crawl4ai-config" / "config.yml"


def test_crawl_deadline_ends_abandoned_work_without_cutting_live_attempts() -> None:
    """Crawl4AI keeps crawling after we hang up; its own deadline is what ends that work.

    It must outlast Butterscout's longest attempt (or live crawls get cut), and stay short
    (or abandoned crawls pile up: at 300 s, sustained load failed normal pages for ~45 s).
    """
    match = re.search(r"^  wall_clock_s: (\d+)", CONFIG.read_text(), re.MULTILINE)
    assert match, "limits.wall_clock_s not found in the mounted Crawl4AI config"
    wall_clock_s = int(match.group(1))
    longest_attempt_s = MAX_REQUEST_TIMEOUT_MS / 1000 + RESPONSE_GRACE_SECONDS
    assert longest_attempt_s < wall_clock_s <= 10
