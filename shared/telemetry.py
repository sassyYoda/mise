"""
Structured logging via structlog (D-12, D-13).
Named symbol: configure_logging, get_logger, safe_error
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


def _redact_secrets(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Strips values matching sensitive env-var names from log event dicts (T-02).
    Applied on every log call.
    """
    _REDACTED = "[REDACTED]"
    _SECRET_KEYS = {
        "TWILIO_AUTH_TOKEN",
        "HMAC_MGMT_SECRET_V1",
        "VAPID_PRIVATE_KEY",
        "RESY_ACCOUNTS_JSON",
    }
    for k in list(event_dict.keys()):
        if k in _SECRET_KEYS or k.startswith("RESY_ACCOUNT_") and k.endswith("_PASSWORD"):
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
