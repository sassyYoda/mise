"""Unit: WR-01 — a poison message is committed, a transient failure is NOT.

`handle_message` used one blanket `except Exception` and then committed unconditionally, so a
Redis timeout, a broker outage or a producer failure discarded the buffered state and marked
the message done. The message was fine; the world was not. For an `availability.raw` message
the next scheduled poll mostly heals the state, but for a `polls.completed` `error`/`timeout`
the UNKNOWN mark is lost permanently, together with any `Close` that had not run yet.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.state_machine.consumer import StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.store import BufferedStateStore, MemoryStateStore
from tests.unit.factories import make_raw

RID = 42
DATE = "2026-05-01"
PARTY = 2
T0 = 1_800_000_000_000


def _shell(monkeypatch: pytest.MonkeyPatch, *, redis_client: object | None = None) -> tuple[
    StateMachineConsumer, AsyncMock
]:
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    durable = MemoryStateStore()
    buffer = BufferedStateStore(durable)
    consumer = AsyncMock()
    shell = StateMachineConsumer(
        consumer=consumer,
        producer=AsyncMock(),
        redis_client=redis_client or AsyncMock(),  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(buffer, confirm_delay_ms=8_000),
        store=durable,
        buffer=buffer,
    )
    return shell, consumer


def _msg(value: bytes, topic: str = "availability.raw") -> SimpleNamespace:
    return SimpleNamespace(topic=topic, partition=0, offset=7, value=value)


def _good_msg() -> SimpleNamespace:
    return _msg(
        make_raw(
            rid=RID,
            dates=[DATE],
            parties=[PARTY],
            response=OPENTABLE_SUCCESS_RESPONSE,
            polled_at_epoch_ms=T0,
        ).to_bytes()
    )


@pytest.mark.asyncio
async def test_a_well_formed_message_commits(monkeypatch) -> None:
    shell, consumer = _shell(monkeypatch)

    await shell.handle_message(_good_msg())

    assert consumer.commit.await_count == 1


@pytest.mark.asyncio
async def test_an_undecodable_payload_is_poison_and_commits(monkeypatch) -> None:
    """Poison never decodes, so committing is the only thing that keeps the partition moving."""
    shell, consumer = _shell(monkeypatch)

    await shell.handle_message(_msg(b"{not json at all"))

    assert consumer.commit.await_count == 1, "a poison message must not stall the partition"


@pytest.mark.asyncio
async def test_a_transient_failure_does_not_commit(monkeypatch) -> None:
    """A broken Redis is not a broken message: leave the offset for the next attempt."""
    redis_client = AsyncMock()
    redis_client.set.side_effect = ConnectionError("redis is down")
    shell, consumer = _shell(monkeypatch, redis_client=redis_client)

    # First poll opens the cycle; the confirming poll reaches the claim and blows up there.
    await shell.handle_message(_good_msg())
    consumer.commit.reset_mock()
    await shell.handle_message(_msg(
        make_raw(
            rid=RID,
            dates=[DATE],
            parties=[PARTY],
            response=OPENTABLE_SUCCESS_RESPONSE,
            polled_at_epoch_ms=T0 + 9_000,
        ).to_bytes()
    ))

    assert consumer.commit.await_count == 0, (
        "a transient infrastructure failure was committed, so the message will never be "
        "redelivered and the observation is lost"
    )


@pytest.mark.asyncio
async def test_a_transient_failure_on_polls_completed_does_not_commit(monkeypatch) -> None:
    """The expensive case: an uncommitted UNKNOWN mark can still be recovered on restart."""
    shell, consumer = _shell(monkeypatch)
    shell.engine.mark_unknown = AsyncMock(side_effect=TimeoutError("redis timeout"))  # type: ignore[method-assign]

    await shell.handle_message(
        _msg(
            b'{"poll_id":"00000000-0000-4000-8000-000000000001","source":"opentable",'
            b'"restaurant_id":42,"polled_at_epoch_ms":1800000000000,"status":"error",'
            b'"latency_ms":1,"http_status":500,"error":"boom"}',
            topic="polls.completed",
        )
    )

    assert consumer.commit.await_count == 0
