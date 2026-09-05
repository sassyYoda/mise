"""
Structured logging via structlog (D-12, D-13).
Named symbol: configure_logging, get_logger
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any, cast

import structlog

_CONFIGURED = False


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
