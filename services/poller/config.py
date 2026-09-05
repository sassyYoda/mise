"""Poller service configuration (D-17, D-19, T-03, D-63).

Single source of truth for poll scheduling constants is `shared.redis_keys`;
this module re-exports the relevant names so downstream poller code has one
import path for config.

Every Resy setting below is read through a FUNCTION, never a module constant, and that is
deliberate. The module constants further down (KAFKA_BOOTSTRAP_SERVERS, REDIS_URL,
DATABASE_URL_ASYNC) freeze the environment at IMPORT time, so any integration test that
imports the poller during collection pins the whole run to the localhost defaults instead of
its testcontainers (the 02-02 deviation; `tests/integration/test_poller_expedite_release.py`
carries an explicit sys.modules eviction to work around it). Reading lazily means a
`monkeypatch.setenv` in one test cannot outlive that test, and `RESY_ENABLED` cannot be
frozen `false` by whichever module happened to import first.

The legacy constants are left exactly as they are: other modules import them and this plan
owns none of those call sites. `tests/unit/test_resy_config_lazy.py` scans this file and
fails if a NEW module-level `os.getenv` assignment appears.
"""
from __future__ import annotations

import os
import random

# Polling schedule re-exports (D-17, single source of truth — shared/redis_keys.py)
from shared.redis_keys import (  # noqa: F401 (re-exported for consumers)
    POLL_INTERVAL_SECONDS,
    POLL_JITTER_FRACTION,
)

# `__all__` makes the re-exports explicit for mypy --strict, which otherwise refuses to let
# another module import POLL_INTERVAL_SECONDS / POLL_JITTER_FRACTION from here.
__all__ = [
    "DATABASE_URL_ASYNC",
    "DEFAULT_DATE_RANGE_DAYS",
    "DEFAULT_PARTY_SIZES",
    "KAFKA_BOOTSTRAP_SERVERS",
    "POLL_INTERVAL_SECONDS",
    "POLL_JITTER_FRACTION",
    "REDIS_URL",
    "USER_AGENTS",
    "random_user_agent",
    "resy_enabled",
]

# Values a human writes into an .env file meaning "off". Anything not in this set and not
# empty is true, so a typo fails OPEN into the safe direction only for the flag whose
# default is already false: RESY_ENABLED must be set deliberately to launch Chromium.
_FALSEY: frozenset[str] = frozenset({"", "false", "0", "no", "off"})


def _env_bool(name: str, *, default: bool = False) -> bool:
    """Read a boolean env var. Unset/empty is `default`; `_FALSEY` members are False."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSEY


def resy_enabled() -> bool:
    """
    The single switch that keeps an unconfigured deployment from ever launching Chromium.

    False by default (D-63). While it is false the seed creates no `resy` restaurants row
    and enqueues no `resy:{venue_id}` job, so `poll_loop` never dispatches to the Resy
    adapter and the browser is never started.
    """
    return _env_bool("RESY_ENABLED", default=False)

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
