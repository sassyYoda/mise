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
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.state_machine.consumer import StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.store import BufferedStateStore, MemoryStateStore
from shared.events import AvailabilityRaw
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
