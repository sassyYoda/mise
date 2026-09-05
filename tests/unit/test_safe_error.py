"""Unit: CR-03 / T-02-03 — `shared.telemetry.safe_error` is the only safe way to log an exception.

`error=str(exc)` was never safe in this codebase, and `services/state_machine/persistence.py`
was the proof rather than the exception: `insert_event` binds `booking_token` as a statement
parameter, SQLAlchemy's `StatementError.__str__` renders bound parameters by default
(`hide_parameters=False`), and every DBAPI failure during `session.execute` arrives as a
`StatementError`. The token therefore went into the log stream on EVERY failed insert, by
construction — a live capability, since a booking token is what holds the reservation.

These tests pin the three places a driver actually puts payload, and each is written against a
REAL exception object from the pinned library rather than a hand-written string, so the test
fails if SQLAlchemy or pydantic ever changes its rendering (which is how a scrubber goes
vacuous without anyone noticing).
"""
from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import StatementError

from shared.telemetry import safe_error

SENTINEL = "SECRET-BOOKING-TOKEN-abc123"


def _statement_error() -> StatementError:
    """A real SQLAlchemy StatementError shaped exactly like `insert_event`'s failure."""
    return StatementError(
        "value too long for type character varying(64)",
        "INSERT INTO availability_events (booking_token) VALUES (%(booking_token)s)",
        {"booking_token": SENTINEL},
        Exception("value too long for type character varying(64)"),
    )


def test_the_sentinel_really_is_in_the_raw_sqlalchemy_text() -> None:
    """Without this the scrubbing tests could pass because the token was never in play."""
    assert SENTINEL in str(_statement_error()), (
        "SQLAlchemy no longer renders bound parameters; the tests below would be vacuous"
    )


def test_sqlalchemy_bound_parameters_never_survive() -> None:
    rendered = safe_error(_statement_error())

    assert SENTINEL not in rendered, f"a live booking token reached the log field: {rendered!r}"
    assert "[parameters:" not in rendered and "[SQL:" not in rendered


def test_the_reason_survives_so_the_failure_is_still_diagnosable() -> None:
    """Redaction must not become silence — that is how a scrubber gets reverted."""
    rendered = safe_error(_statement_error())

    assert "sqlalchemy.exc.StatementError" in rendered
    assert "value too long" in rendered


class _Model(BaseModel):
    x: dict


def test_pydantic_input_value_never_survives() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _Model(x=SENTINEL)  # type: ignore[arg-type]
    assert SENTINEL in str(excinfo.value), "pydantic no longer embeds input_value"

    rendered = safe_error(excinfo.value)

    assert SENTINEL not in rendered
    assert "input_value=[redacted]" in rendered
    assert "dict_type" in rendered, "the error TYPE is the diagnostic and must survive"


@pytest.mark.parametrize("keyword", ["DETAIL", "CONTEXT", "HINT"])
def test_postgres_detail_lines_never_survive(keyword: str) -> None:
    """Postgres quotes the OFFENDING VALUES in DETAIL, which is where a token lands."""
    exc = ValueError(
        f'duplicate key value violates unique constraint "ix"\n'
        f"{keyword}:  Key (booking_token)=({SENTINEL}) already exists."
    )

    rendered = safe_error(exc)

    assert SENTINEL not in rendered, f"{keyword} leaked the offending value: {rendered!r}"
    assert "duplicate key value violates unique constraint" in rendered


def test_the_result_is_one_line_and_bounded() -> None:
    """A log field is a diagnostic, not a transcript (WR-03: unbounded failure lines)."""
    exc = RuntimeError("x" * 5_000 + "\nsecond line")

    rendered = safe_error(exc)

    assert "\n" not in rendered
    assert len(rendered) < 400, f"unbounded log field: {len(rendered)} chars"
    assert rendered.endswith("…[truncated]")


def test_an_exception_with_no_message_still_names_its_type() -> None:
    assert safe_error(RuntimeError()) == "builtins.RuntimeError"
