"""Unit: CR-02 / T-02-03 — no log line may ever carry payload content.

`services/state_machine/consumer.py`'s module docstring states the contract: "Logs carry ids
and counts only — never a booking token and never a payload body". The poison branch broke it
with `error=str(exc)`: pydantic v2 renders the OFFENDING INPUT into a `ValidationError`'s
message, so a `raw_response` carrying a booking token put that token straight into the log
stream. A booking token is a capability — it is what holds the reservation.

Every test here drives the REAL `handle_message` and captures the REAL structlog events, so
it fails if any future branch reaches for `str(exc)` again.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest
from aiokafka.errors import KafkaError
from pydantic import ValidationError
from sqlalchemy.exc import StatementError
from structlog.testing import capture_logs

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.state_machine.consumer import StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.persistence import close_event, insert_event
from services.state_machine.store import BufferedStateStore, MemoryStateStore
from shared.events import AvailabilityEvent, AvailabilityRaw, make_event_id
from tests.unit.factories import make_raw

SENTINEL = "SECRET-BOOKING-TOKEN-abc123"
RID = 42
DATE = "2026-05-01"
PARTY = 2
T0 = 1_800_000_000_000


def _shell(monkeypatch, *, redis_client=None) -> StateMachineConsumer:
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    monkeypatch.setattr(
        "services.state_machine.consumer.TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0
    )
    durable = MemoryStateStore()
    buffer = BufferedStateStore(durable)
    consumer = AsyncMock()
    consumer.seek = MagicMock()
    consumer.pause = MagicMock()
    consumer.resume = MagicMock()
    return StateMachineConsumer(
        consumer=consumer,
        producer=AsyncMock(),
        redis_client=redis_client or AsyncMock(),  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(buffer, confirm_delay_ms=8_000),
        store=durable,
        buffer=buffer,
    )


def _poisoned_bytes() -> bytes:
    """A well-formed envelope whose `raw_response` is a STRING holding a booking token.

    This is the drift case, not a contrived one: any payload-shape change that lands a token
    where an object is expected produces exactly this, and nobody has done anything wrong.
    """
    return json.dumps(
        {
            "poll_id": "00000000-0000-4000-8000-000000000001",
            "source": "opentable",
            "restaurant_id": RID,
            "polled_at_epoch_ms": T0,
            "raw_response": SENTINEL,
            "request_params": {"dates": [DATE], "party_sizes": [PARTY]},
        }
    ).encode()


def _msg(value: bytes, topic: str = "availability.raw") -> SimpleNamespace:
    return SimpleNamespace(topic=topic, partition=0, offset=11, value=value)


def _flatten(captured: list[dict]) -> str:
    return json.dumps(captured, default=str)


def test_the_sentinel_really_is_in_the_raw_exception_text() -> None:
    """Without this the leak tests could pass because the token was never in play at all."""
    with pytest.raises(ValidationError) as excinfo:
        AvailabilityRaw.model_validate_json(_poisoned_bytes())
    assert SENTINEL in str(excinfo.value), (
        "pydantic no longer embeds input_value; the leak tests below would be vacuous"
    )


@pytest.mark.asyncio
async def test_a_poison_message_logs_no_payload_content(monkeypatch) -> None:
    shell = _shell(monkeypatch)

    with capture_logs() as captured:
        await shell.handle_message(_msg(_poisoned_bytes()))

    events = [entry["event"] for entry in captured]
    assert "message_poison" in events, f"expected the poison branch, got {events}"
    assert SENTINEL not in _flatten(captured), (
        "the raw payload — a live booking token — was written to the log stream"
    )


@pytest.mark.asyncio
async def test_the_poison_log_still_names_the_failing_field_and_type(monkeypatch) -> None:
    """Redaction must not become silence: the shape is what makes the failure diagnosable."""
    shell = _shell(monkeypatch)

    with capture_logs() as captured:
        await shell.handle_message(_msg(_poisoned_bytes()))

    poison = next(e for e in captured if e["event"] == "message_poison")
    assert poison["error"] == ["raw_response:dict_type"]
    assert poison["offset"] == 11 and poison["topic"] == "availability.raw"


@pytest.mark.asyncio
async def test_a_transient_driver_error_logs_no_connection_string(monkeypatch) -> None:
    """A redis-py / asyncpg message can carry a DSN, so the transient arm is the same risk."""
    redis_client = AsyncMock()
    redis_client.set.side_effect = ConnectionError(
        f"Error connecting to redis://user:{SENTINEL}@cache:6379"
    )
    shell = _shell(monkeypatch, redis_client=redis_client)

    good = _msg(
        make_raw(
            rid=RID,
            dates=[DATE],
            parties=[PARTY],
            response=OPENTABLE_SUCCESS_RESPONSE,
            polled_at_epoch_ms=T0,
        ).to_bytes()
    )
    await shell.handle_message(good)

    with capture_logs() as captured:
        await shell.handle_message(
            _msg(
                make_raw(
                    rid=RID,
                    dates=[DATE],
                    parties=[PARTY],
                    response=OPENTABLE_SUCCESS_RESPONSE,
                    polled_at_epoch_ms=T0 + 9_000,
                ).to_bytes()
            )
        )

    events = [entry["event"] for entry in captured]
    assert "message_handling_failed" in events, f"expected the transient branch, got {events}"
    assert SENTINEL not in _flatten(captured)
    failed = next(e for e in captured if e["event"] == "message_handling_failed")
    assert failed["error"] == "builtins.ConnectionError"


# -- CR-03 (iteration 3): the DATABASE path is where a token leaked by construction --


def _statement_error() -> StatementError:
    """A real SQLAlchemy StatementError shaped exactly like `insert_event`'s failure.

    Not a hand-written string: `hide_parameters` defaults to False, so the token is rendered
    by the library itself. If SQLAlchemy ever stops doing that, this test goes vacuous and the
    guard below catches it.
    """
    return StatementError(
        "value too long for type character varying(64)",
        "INSERT INTO availability_events (booking_token) VALUES (%(booking_token)s)",
        {"booking_token": SENTINEL},
        Exception("value too long for type character varying(64)"),
    )


def _event() -> AvailabilityEvent:
    return AvailabilityEvent(
        event_id=make_event_id("opentable", RID, DATE, PARTY, "19:00|bar", "pid"),
        event_type="slot_opened",
        source="opentable",
        restaurant_id=RID,
        date=DATE,
        time_slot="19:00",
        party_size=PARTY,
        seat_type="bar",
        booking_token=SENTINEL,
        first_seen_at_epoch_ms=T0,
        confirmed_at_epoch_ms=T0 + 9_000,
        produced_at_epoch_ms=T0 + 9_000,
        confirming_poll_id=UUID("00000000-0000-4000-8000-000000000002"),
    )


def _install_failing_session(monkeypatch) -> None:
    """Make every `session.execute` raise the StatementError above."""

    class _Session:
        async def __aenter__(self):  # noqa: ANN204 - test double
            return self

        async def __aexit__(self, *exc_info):  # noqa: ANN002, ANN204 - test double
            return False

        async def execute(self, statement):  # noqa: ANN001, ANN202 - test double
            raise _statement_error()

        async def commit(self) -> None:
            raise AssertionError("commit must not be reached after a failing execute")

    monkeypatch.setattr(
        "services.state_machine.persistence.get_async_session", lambda: _Session
    )


@pytest.mark.asyncio
async def test_a_failed_insert_never_logs_the_booking_token(monkeypatch) -> None:
    """The one place a token was in the log by CONSTRUCTION, not by payload drift.

    `insert_event` binds `booking_token` as a statement parameter, and SQLAlchemy renders
    bound parameters into `StatementError.__str__`. `error=str(exc)` therefore wrote a live
    capability to the log stream on every single failed insert.
    """
    assert SENTINEL in str(_statement_error()), (
        "SQLAlchemy no longer renders bound parameters; this test would be vacuous"
    )
    _install_failing_session(monkeypatch)

    with capture_logs() as captured:
        await insert_event(_event())  # best effort: must swallow, never raise

    events = [entry["event"] for entry in captured]
    assert "availability_event_insert_failed" in events, f"expected the failure log, got {events}"
    assert SENTINEL not in _flatten(captured), (
        "the booking token — a live capability — was written to the log stream"
    )
    failed = next(e for e in captured if e["event"] == "availability_event_insert_failed")
    assert "sqlalchemy.exc.StatementError" in failed["error"], (
        "redaction must not become silence: the failure has to stay diagnosable"
    )
    assert "value too long" in failed["error"]


@pytest.mark.asyncio
async def test_a_failed_close_never_logs_the_statement(monkeypatch) -> None:
    """WR-03: same shape, lower-value parameters — but the SQL text is still a payload body."""
    _install_failing_session(monkeypatch)
    when = datetime.fromtimestamp(T0 / 1000, tz=UTC)

    with capture_logs() as captured:
        await close_event(
            event_id=UUID("00000000-0000-4000-8000-000000000003"),
            confirmed_at=when,
            last_seen_at=when,
        )

    failed = next(e for e in captured if e["event"] == "availability_event_close_failed")
    assert "[SQL:" not in failed["error"] and "[parameters:" not in failed["error"]
    assert SENTINEL not in _flatten(captured)


# -- WR-07: the commit branch was the last `str(exc)` in consumer.py --


@pytest.mark.asyncio
async def test_a_failing_commit_logs_only_the_failure_shape(monkeypatch) -> None:
    """A broker error string carries hostnames and ports today, SASL principals later."""
    shell = _shell(monkeypatch)
    shell.consumer.commit.side_effect = KafkaError(  # type: ignore[union-attr]
        f"NodeNotReady: broker kafka://user:{SENTINEL}@node-1:9092"
    )

    good = _msg(
        make_raw(
            rid=RID,
            dates=[DATE],
            parties=[PARTY],
            response=OPENTABLE_SUCCESS_RESPONSE,
            polled_at_epoch_ms=T0,
        ).to_bytes()
    )
    with capture_logs() as captured:
        await shell.handle_message(good)

    failed = next(e for e in captured if e["event"] == "offset_commit_failed")
    assert failed["error"] == "aiokafka.errors.KafkaError", (
        f"the commit branch must log the SHAPE, not the message: {failed['error']!r}"
    )
    assert SENTINEL not in _flatten(captured)
