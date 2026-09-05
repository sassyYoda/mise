"""
Structured logging via structlog (D-12, D-13).
Named symbols: configure_logging, get_logger, safe_error, _redact_secrets
"""
from __future__ import annotations

import logging
import os
import re
import sys
from typing import Any, cast

import structlog

_CONFIGURED = False

# --- safe_error: the ONE way a service renders an exception into a log field (CR-03) ---

_SCRUBBED = "[redacted]"

# SQLAlchemy's `StatementError.__str__` appends the statement AND its bound parameters,
# because `hide_parameters` defaults to False:
#
#   (builtins.Exception) value too long
#   [SQL: INSERT INTO availability_events (booking_token) VALUES (%(booking_token)s)]
#   [parameters: {'booking_token': 'SECRET-BOOKING-TOKEN-abc123'}]
#   (Background on this error at: https://sqlalche.me/e/20/...)
#
# Everything from the first `[SQL:` / `[parameters:` / `[cached since` marker to the end of
# the string is dropped wholesale rather than matched bracket-by-bracket: a parameter dict can
# contain `]`, so a balanced-bracket pattern is not safe here and a truncating one is.
_SQL_DETAIL_RE = re.compile(r"\s*\[(?:SQL|parameters|cached since)\b.*", re.IGNORECASE | re.DOTALL)

# Pydantic v2 renders the OFFENDING INPUT into a ValidationError message:
#   Input should be a valid dictionary [type=dict_type, input_value='SECRET…', input_type=str]
# `repr` escapes newlines, so the value can never span lines and "to end of line" is total.
_INPUT_VALUE_RE = re.compile(r"input_value=[^\n]*")

# Postgres puts the offending VALUES in DETAIL, e.g.
#   DETAIL: Key (booking_token)=(SECRET-BOOKING-TOKEN-abc123) already exists.
_PG_DETAIL_RE = re.compile(r"^(\s*)(DETAIL|CONTEXT|HINT):[^\n]*", re.IGNORECASE | re.MULTILINE)

# A log field is a diagnostic, not a transcript. Bounded so one pathological driver message
# cannot make a log line unbounded in length (WR-03).
_MAX_MESSAGE_CHARS = 300


def safe_error(exc: BaseException) -> str:
    """
    Render an exception as `module.ClassName: <scrubbed message>` for a log field (CR-03).

    `error=str(exc)` is never safe in this codebase and `services/state_machine/persistence.py`
    was the proof: `insert_event`'s bound parameters contain `booking_token`, and a booking
    token is a capability — it is what holds the reservation. Every DBAPI error raised during
    `session.execute` (a constraint violation, a length error, a connection reset wrapped as
    `OperationalError`) arrives as a `StatementError` with those parameters attached, so the
    token went to the log stream on EVERY failed insert, by construction. That breaches the
    contract stated in `consumer.py`'s module docstring (T-02-03: "Logs carry ids and counts
    only — never a booking token"), and `_redact_secrets` below does not cover it: that
    processor matches env-var KEY NAMES, not secret values embedded in a message string.

    Three things are stripped, each because a real driver puts payload there:

    * everything from SQLAlchemy's `[SQL: …]` / `[parameters: …]` marker onward;
    * pydantic's `input_value=…` up to end of line;
    * Postgres `DETAIL:` / `CONTEXT:` / `HINT:` lines, which quote the offending values.

    What survives is the exception type and the human-readable reason, which is what makes a
    failure diagnosable. This is deliberately WEAKER than
    `services.state_machine.consumer._failure_shape`, which discards the message entirely.
    Use `_failure_shape` for a failure raised while handling PRODUCER-SUPPLIED data (the
    message is attacker-influenced); use `safe_error` for a failure raised by OUR OWN
    infrastructure, where the reason text is the whole diagnostic value.
    """
    message = _SQL_DETAIL_RE.sub("", str(exc))
    message = _INPUT_VALUE_RE.sub(f"input_value={_SCRUBBED}", message)
    message = _PG_DETAIL_RE.sub(rf"\1\2: {_SCRUBBED}", message)
    # Collapse to a single line: a multi-line value in a structured log field is unreadable in
    # the JSON renderer and unsearchable in the console one.
    message = " ".join(message.split())
    if len(message) > _MAX_MESSAGE_CHARS:
        message = message[:_MAX_MESSAGE_CHARS] + "…[truncated]"
    qualified = f"{type(exc).__module__}.{type(exc).__name__}"
    return f"{qualified}: {message}" if message else qualified


_REDACTED = "[REDACTED]"

# Exact env-var names (Phase 1, T-02). Matched case-SENSITIVELY: these are env vars, and an
# env var's name is its exact spelling.
_SECRET_KEYS = frozenset(
    {
        "TWILIO_AUTH_TOKEN",
        "HMAC_MGMT_SECRET_V1",
        "VAPID_PRIVATE_KEY",
        "RESY_ACCOUNTS_JSON",
    }
)

# Phase 3 (D-61a, research B-6). These are HTTP HEADER names as much as env-var names, and a
# header's casing is whatever the peer sent — `Cookie`, `cookie` and `COOKIE` are one header.
# Matched case-INSENSITIVELY for that reason. Research reproduced six of these eight leaking
# in full against the pre-Phase-3 redactor, before any cookie-handling code existed.
_SECRET_KEYS_CI = frozenset(
    {
        "cookie",
        "cookies",
        "set-cookie",
        "auth_token",
        "x-resy-auth-token",
        "authorization",
        "api_key",
        "resy_api_key",
    }
)

# Proxy URLs are masked rather than blanked: WHICH proxy host was in play is a real
# diagnostic during a soft-ban incident, while the credentials in the userinfo segment are a
# purchased subscription's password.
_PROXY_KEYS_CI = frozenset({"proxy_url", "resy_proxy_url", "proxy"})

# `scheme://` followed by an OPTIONAL `userinfo@` segment. The userinfo group stops at the
# first `/` so a path component containing `@` is never mistaken for credentials, and it is
# greedy within the authority so a password containing an escaped `@` is still fully covered.
_PROXY_URL_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)([^/@]*@)?")


def _mask_proxy_credentials(value: Any) -> str:
    """
    Return ``value`` with any URL userinfo segment replaced by the redaction sentinel.

    A proxy URL is masked rather than blanked because WHICH proxy host was in play is a real
    diagnostic during a soft-ban incident — an operator needs to know the fleet was egressing
    through `residential.example.net` — while the userinfo segment is a purchased
    subscription's password.

    Fails CLOSED: a non-string, or a value that does not parse as `scheme://…`, is redacted
    wholesale rather than emitted on the hope that it carries no password. A value under a
    proxy key that this function cannot understand is exactly the case where guessing is
    unsafe. A well-formed URL with no userinfo is returned untouched — there is nothing to
    hide, and hiding it anyway would be the over-breadth this redactor avoids.
    """
    if not isinstance(value, str):
        return _REDACTED
    match = _PROXY_URL_RE.match(value)
    if match is None:
        return _REDACTED
    if match.group(2) is None:
        return value
    return f"{match.group(1)}{_REDACTED}@{value[match.end():]}"


def _redact_secrets(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Strip values matching sensitive key names from log event dicts (T-02, T-03-05, D-61a).

    Applied on EVERY log call, so it stays pure and allocation-cheap: one `lower()` per key
    and no work at all for the overwhelmingly common case of a benign field.

    This redactor is **key-name based**, which is a real and permanent limitation: it cannot
    save a caller who logs a whole header mapping under a benign key such as
    `headers=` or `raw_response=`. That is precisely why `services/poller/sources/resy/`
    is forbidden from logging `raw_response`, a `booking_token`, or a header dict at INFO —
    the ban is the control; this function is only the backstop. It is also deliberately NOT
    over-broad: `cookie_count` is a count, and a redactor that swallowed it would destroy
    the diagnostics an incident depends on while training readers to ignore `[REDACTED]`.

    The Resy secrets it covers are a THIRD PARTY's credentials, replayed under a human's
    supervision. They may not reach Postgres, Kafka, `poll_log`, a structlog line, or a file
    on disk.
    """
    for k in list(event_dict.keys()):
        lowered = k.lower()
        if lowered in _PROXY_KEYS_CI:
            event_dict[k] = _mask_proxy_credentials(event_dict[k])
        elif (
            k in _SECRET_KEYS
            or lowered in _SECRET_KEYS_CI
            or (k.startswith("RESY_ACCOUNT_") and k.endswith("_PASSWORD"))
        ):
            event_dict[k] = _REDACTED
    return event_dict


def configure_logging(env: str | None = None) -> None:
    """Call once at service startup. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    env = env or os.getenv("ENV", "dev")
    log_level_name = os.getenv("LOG_LEVEL", "INFO" if env == "prod" else "DEBUG").upper()
    log_level = getattr(logging, log_level_name, logging.DEBUG)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_secrets,
    ]

    if env == "prod":
        renderer: list[Any] = [structlog.processors.JSONRenderer()]
    else:
        renderer = [structlog.dev.ConsoleRenderer(colors=True)]

    structlog.configure(
        processors=shared_processors + renderer,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a structlog BoundLogger for the given name."""
    configure_logging()
    return cast(structlog.BoundLogger, structlog.get_logger(name))
