"""Poller service configuration (D-17, D-19, T-03).

Single source of truth for poll scheduling constants is `shared.redis_keys`;
this module re-exports the relevant names so downstream poller code has one
import path for config.
"""
from __future__ import annotations

import os
import random

# Polling schedule re-exports (D-17, single source of truth — shared/redis_keys.py)
from shared.redis_keys import (  # noqa: F401 (re-exported for consumers)
    POLL_INTERVAL_SECONDS,
    POLL_JITTER_FRACTION,
)

# Date and party size defaults for OpenTable polling (D-19)
DEFAULT_DATE_RANGE_DAYS: int = 7
DEFAULT_PARTY_SIZES: list[int] = [2, 4]

# User-Agent rotation list (T-03 — rotate per request to avoid fingerprinting).
# Must contain >=4 real browser strings; all entries unique.
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


def random_user_agent() -> str:
    """Return a random User-Agent from USER_AGENTS (T-03 mitigation)."""
    return random.choice(USER_AGENTS)


# Kafka settings
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")

# Redis settings
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Database settings (Named Symbol: DATABASE_URL_ASYNC — asyncpg driver URL)
DATABASE_URL_ASYNC: str = os.getenv(
    "DATABASE_URL_ASYNC",
    "postgresql+asyncpg://mise:mise@localhost:5432/mise",
)
