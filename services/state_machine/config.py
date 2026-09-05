"""
State machine service configuration (D-42, D-47a, D-51).

Single source of truth for the confirmation delay is `shared.redis_keys`; this module
re-exports it so the shell has one import path for config, mirroring the poller's idiom.

Every environment read below is a FUNCTION, not a module constant, and that is deliberate.
`services/poller/config.py` freezes KAFKA_BOOTSTRAP_SERVERS / REDIS_URL into module constants
at IMPORT time, so any integration test that imports the service during collection pins the
whole run to the localhost defaults instead of its testcontainers (02-02 deviation 1). Reading
lazily inside `run()` removes that footgun for this service permanently.
Named symbols: CONSUMER_GROUP_ID, kafka_bootstrap_servers, redis_url, database_url_async,
               env_name, crash_after, crash_hook_allowed, CRASH_HOOK_ENVS, CONFIRM_DELAY_MS
"""
from __future__ import annotations

import os

# Confirmation delay re-export (D-42, D-43 — single source of truth is shared/redis_keys.py)
from shared.redis_keys import CONFIRM_DELAY_MS  # noqa: F401 (re-exported for consumers)

# `__all__` makes the re-export explicit for mypy --strict, which otherwise refuses to let
# another module import CONFIRM_DELAY_MS from here.
__all__ = [
    "CONFIRM_DELAY_MS",
    "CONSUMER_GROUP_ID",
    "CRASH_HOOK_ENVS",
    "crash_after",
    "crash_hook_allowed",
    "database_url_async",
    "env_name",
    "kafka_bootstrap_servers",
    "redis_url",
]

# Kafka consumer group (D-47). This name is live offset state once events flow: renaming it
# makes a restarted service replay the whole topic from the earliest offset.
CONSUMER_GROUP_ID: str = "state-machine"


def kafka_bootstrap_servers() -> str:
    """Broker list. Default matches services/poller/config.py — the two must never disagree."""
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")


def redis_url() -> str:
    """Redis URL. Default matches services/poller/config.py."""
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def database_url_async() -> str:
    """asyncpg driver URL. Default matches services/poller/config.py (Named Symbol)."""
    return os.getenv(
        "DATABASE_URL_ASYNC",
        "postgresql+asyncpg://mise:mise@localhost:5432/mise",
    )


def env_name() -> str:
    """Deployment environment, defaulting to `dev` for logging and diagnostics."""
    return os.getenv("ENV", "dev")


# The ONLY environments in which the SIGKILL hook may be armed (T-02-04). An allowlist, not a
# denylist: `ENV == "prod"` let `ENV=production`, `ENV=PROD` and a container that forgot to set
# ENV at all start happily with a hook whose entire job is to kill the process mid-pipeline.
# A safety interlock must fail CLOSED.
CRASH_HOOK_ENVS: frozenset[str] = frozenset({"dev", "test", "ci", "local"})


def crash_hook_allowed() -> bool:
    """
    True only when ENV is EXPLICITLY set to a known non-production environment.

    Deliberately reads the raw variable rather than `env_name()`: the "dev" default exists so
    logging has something to say, and letting it also unlock a SIGKILL hook would mean an
    unconfigured production container is the most permissive configuration there is.
    """
    raw = os.getenv("ENV")
    return raw is not None and raw.strip().lower() in CRASH_HOOK_ENVS


def crash_after() -> str | None:
    """TEST ONLY (D-51): stage after which the consumer SIGKILLs itself. Unset everywhere else."""
    return os.getenv("MISE_CRASH_AFTER")
