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
    RESY_BASELINE_INTERVAL_SECONDS_DEFAULT,
    RESY_GLOBAL_RPM_DEFAULT,
)

# `__all__` makes the re-exports explicit for mypy --strict, which otherwise refuses to let
# another module import POLL_INTERVAL_SECONDS / POLL_JITTER_FRACTION from here.
__all__ = [
    "DATABASE_URL_ASYNC",
    "DEFAULT_DATE_RANGE_DAYS",
    "DEFAULT_PARTY_SIZES",
    "DEFAULT_RESY_AUTH_TOKEN_HEADER",
    "DEFAULT_RESY_CONTEXTS",
    "DEFAULT_RESY_DATE_RANGE_DAYS",
    "DEFAULT_RESY_PARTY_SIZES",
    "KAFKA_BOOTSTRAP_SERVERS",
    "POLL_INTERVAL_SECONDS",
    "POLL_JITTER_FRACTION",
    "REDIS_URL",
    "RESY_API_BASE_DEFAULT",
    "RESY_BASELINE_INTERVAL_SECONDS_DEFAULT",
    "RESY_GLOBAL_RPM_DEFAULT",
    "USER_AGENTS",
    "metrics_port",
    "poll_workers",
    "random_user_agent",
    "resy_accounts_json",
    "resy_api_base",
    "resy_api_key",
    "resy_auth_token_header",
    "resy_baseline_interval_seconds",
    "resy_contexts",
    "resy_date_range_days",
    "resy_enabled",
    "resy_global_rpm",
    "resy_party_sizes",
    "resy_proxy_url",
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


# =====================================================================================
# Resy fleet settings (D-61, D-62, D-63, D-64, D-69, D-72)
#
# Every reader below is a function. See the module docstring for why. `resy_enabled()`
# lives further up, next to `_env_bool`, because the seed script imports it on its own.
# =====================================================================================

RESY_API_BASE_DEFAULT: str = "https://api.resy.com"
# Research A5: the per-account token header is written as `x-resy-auth-token` in the one
# corroborating public client, but a sibling `X-Resy-Universal-Auth` also exists and may
# turn out to be the right one. The NAME lives here rather than in the adapter so the
# DevTools capture corrects one default, not a request builder.
DEFAULT_RESY_AUTH_TOKEN_HEADER: str = "X-Resy-Auth-Token"
DEFAULT_RESY_CONTEXTS: int = 4               # D-60: 1 browser, 4 contexts
DEFAULT_RESY_DATE_RANGE_DAYS: int = 3        # D-64: 3 days x party sizes = 3 requests/poll
DEFAULT_RESY_PARTY_SIZES: list[int] = [2]    # D-64
DEFAULT_METRICS_PORT: int = 9101             # D-69: Phase 7 scrapes this


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """
    Read an integer env var, or RAISE naming it. Never silently returns the default.

    Swallowing a typo into the default is the failure this exists to prevent: an operator
    who sets `RESY_GLOBAL_RPM=8O` (letter O) and gets 80 has been given the exact opposite
    of what they asked for, against a cap the public README commits to. The same argument
    holds for `RESY_CONTEXTS=0`, which starts a fleet that polls nothing and says nothing.

    An empty or whitespace-only value IS treated as unset: `RESY_CONTEXTS=` in a .env file
    is how a human writes "leave it alone", not a typo.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be an integer >= {minimum}, got {raw!r}. Refusing to fall back "
            f"to the default ({default}) — a typo that silently keeps the default is a "
            "setting that cannot be changed."
        ) from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}, got {value}")
    return value


def _env_str(name: str, default: str = "") -> str:
    """Read a string env var, treating whitespace-only as unset."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _env_optional_str(name: str) -> str | None:
    """Read an optional string env var. Unset, empty or whitespace-only is None.

    `RESY_API_KEY=` in a .env file means "not captured yet" (the key is human-gated —
    docs/runbooks/resy-cookie-capture.md), NOT "the key is the empty string". Returning
    `""` would send `Authorization: ResyAPI api_key=""` and turn a missing credential into
    a puzzling 401 instead of a clear precondition failure.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def resy_api_base() -> str:
    """Resy API origin. Overridable so integration tests point at the local stub (D-64).

    The trailing slash is stripped because every caller builds `f"{base}/4/find"`, and
    `https://api.resy.com//4/find` is a 404 that looks like an outage.
    """
    return _env_str("RESY_API_BASE", RESY_API_BASE_DEFAULT).rstrip("/")


def resy_api_key() -> str | None:
    """The Resy API key, or None when it has not been captured yet (human-gated).

    NEVER log or print this value. `shared/telemetry.py` redacts `RESY_API_KEY`,
    `api_key` and `authorization` from every structured event (D-61a), and no script in
    `scripts/` prints it — `scripts/resolve_resy_venue_ids.py` reports counts and slugs.
    """
    return _env_optional_str("RESY_API_KEY")


def resy_auth_token_header() -> str:
    """Header NAME carrying the per-account auth token (research A5 — see the default)."""
    return _env_str("RESY_AUTH_TOKEN_HEADER", DEFAULT_RESY_AUTH_TOKEN_HEADER)


def resy_accounts_json() -> str:
    """
    Raw `RESY_ACCOUNTS_JSON` (D-61). Empty string means ANONYMOUS MODE, not an error.

    A fleet that refuses to start without accounts cannot be exercised by the stub-backed
    integration tests or the soak script, which is where all of its behaviour is proven.
    The pool logs `resy_anonymous_mode` once and runs. The VALUE is a secret: it is
    redacted by `shared/telemetry.py` and must never reach a log line or a database row.
    """
    return _env_str("RESY_ACCOUNTS_JSON", "")


def resy_proxy_url() -> str | None:
    """Optional residential proxy, `http[s]://user:pass@host:port` (D-62). Unset = direct.

    Carries credentials in the URL. `shared/telemetry.py` MASKS rather than blanks it, so
    a log line can still say which proxy host was in use without leaking the password.
    """
    return _env_optional_str("RESY_PROXY_URL")


def resy_contexts() -> int:
    """Number of Playwright BrowserContexts in the pool (D-60). One browser, N contexts."""
    return _env_int("RESY_CONTEXTS", DEFAULT_RESY_CONTEXTS)


def resy_global_rpm() -> int:
    """Fleet-wide request cap per minute (D-65). The README promises this number publicly."""
    return _env_int("RESY_GLOBAL_RPM", RESY_GLOBAL_RPM_DEFAULT)


def resy_baseline_interval_seconds() -> int:
    """Resy's baseline poll cadence (D-57). Clamped to the 45 s POLL-05 floor downstream."""
    return _env_int(
        "RESY_BASELINE_INTERVAL_SECONDS", RESY_BASELINE_INTERVAL_SECONDS_DEFAULT
    )


def resy_date_range_days() -> int:
    """Days ahead each Resy poll covers (D-64). Days x party sizes = requests per poll."""
    return _env_int("RESY_DATE_RANGE_DAYS", DEFAULT_RESY_DATE_RANGE_DAYS)


def resy_party_sizes() -> list[int]:
    """
    Party sizes each Resy poll requests (D-64), as a comma-separated list. Default `[2]`.

    Raises rather than dropping a bad token: silently ignoring `2,two` would poll a
    narrower matrix than the operator asked for and report full coverage for it, which is
    the D-64 over-declaration bug this phase exists to avoid.
    """
    raw = os.getenv("RESY_PARTY_SIZES")
    if raw is None or not raw.strip():
        return list(DEFAULT_RESY_PARTY_SIZES)
    sizes: list[int] = []
    for token in raw.split(","):
        candidate = token.strip()
        if not candidate:
            continue
        try:
            sizes.append(int(candidate))
        except ValueError as exc:
            raise RuntimeError(
                f"RESY_PARTY_SIZES must be a comma-separated list of integers, got "
                f"{raw!r} (offending entry {candidate!r})"
            ) from exc
    if not sizes:
        return list(DEFAULT_RESY_PARTY_SIZES)
    if any(size < 1 for size in sizes):
        raise RuntimeError(f"RESY_PARTY_SIZES entries must be >= 1, got {raw!r}")
    return sizes


def metrics_port() -> int:
    """Prometheus exposition port for the poller (D-69). Phase 7 scrapes it."""
    return _env_int("METRICS_PORT", DEFAULT_METRICS_PORT)


def poll_workers() -> int:
    """
    Concurrent `poll_loop` tasks over the single ZSET (D-72, research Q2).

    `1 + RESY_CONTEXTS` when Resy is enabled, `1` when it is not — so the default
    configuration is byte-for-byte today's behaviour, a single serial loop. The claim Lua
    is atomic, so N workers over one scheduler is safe with no scheduler change.

    Documented caveat (Q2): the workers are NOT source-filtered, so a slow Resy poll can
    delay an OpenTable poll by at most one poll duration. Source-filtered claims are
    deferred; POLL-03's 90 s cadence has that much slack.

    An explicit `POLL_WORKERS` wins over both, because an operator who has measured their
    own box should not have to reason about `RESY_CONTEXTS` to change it.
    """
    override = os.getenv("POLL_WORKERS")
    if override is not None and override.strip():
        return _env_int("POLL_WORKERS", 1)
    if not resy_enabled():
        return 1
    return 1 + resy_contexts()
