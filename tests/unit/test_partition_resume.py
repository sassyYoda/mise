"""Unit: WR-06 — a partition must never be left paused silently.

`_resume_partition` is a `loop.call_later` callback, so it runs outside any task and outside
`handle_message`'s handlers: there is no caller for an exception to propagate to. It used to
catch only `KafkaError`, and it pops its handle from `_resume_handles` FIRST. So anything else
— an `AssertionError` from aiokafka's `SubscriptionState._assigned_state` (`assert
self._subscription is not None`, reachable during a stop/rebalance race), or an
`AttributeError` against a half-closed consumer — went to the loop's default exception handler,
which writes to the `asyncio` logger rather than through the structlog JSON pipeline, with the
handle already gone. Nothing would ever try to resume that partition again: the service stays
up, `getone()` blocks forever, and the only trace is a line the log pipeline does not format.

`_retry_later` had the narrower version of the same defect (`except (KafkaError, ValueError)`),
and there an escape is worse: it is raised from inside the transient `except` block, so nothing
above catches it and `run()` terminates outright.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiokafka import TopicPartition
from aiokafka.errors import IllegalStateError
from structlog.testing import capture_logs

from services.state_machine.consumer import MAX_RESUME_ATTEMPTS, StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.store import BufferedStateStore, MemoryStateStore

TOPIC = "availability.raw"
TP = TopicPartition(TOPIC, 0)


def _shell(monkeypatch: pytest.MonkeyPatch) -> tuple[StateMachineConsumer, MagicMock]:
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    monkeypatch.setattr("services.state_machine.consumer.TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0)
    durable = MemoryStateStore()
    buffer = BufferedStateStore(durable)
    consumer = AsyncMock()
    consumer.seek = MagicMock()
    consumer.pause = MagicMock()
    consumer.resume = MagicMock()
    shell = StateMachineConsumer(
        consumer=consumer,
        producer=AsyncMock(),
        redis_client=AsyncMock(),  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(buffer, confirm_delay_ms=8_000),
        store=durable,
        buffer=buffer,
    )
    return shell, consumer


@pytest.mark.asyncio
async def test_a_non_kafka_resume_failure_is_logged_and_retried(monkeypatch) -> None:
    """The failure that used to vanish into the asyncio logger with the handle already popped."""
    shell, consumer = _shell(monkeypatch)
    consumer.resume.side_effect = AssertionError("subscription is None")

    with capture_logs() as captured:
        shell._resume_partition(TP)

    failed = next(e for e in captured if e["event"] == "partition_resume_failed")
    assert failed["error"] == "builtins.AssertionError"
    assert failed["topic"] == TOPIC and failed["partition"] == 0
    assert failed["attempt"] == 1
    assert TP in shell._resume_handles, (
        "the partition was left paused with no pending resume — getone() now blocks forever"
    )

    for handle in shell._resume_handles.values():
        handle.cancel()


@pytest.mark.asyncio
async def test_a_permanently_failing_resume_is_abandoned_loudly_not_silently(monkeypatch) -> None:
    """Bounded: a self-rescheduling timer against a dead consumer must not flood forever."""
    shell, consumer = _shell(monkeypatch)
    consumer.resume.side_effect = AssertionError("subscription is None")

    with capture_logs() as captured:
        shell._resume_partition(TP)
        # Drain the chain of zero-delay re-schedules the callback arms for itself. A real
        # (tiny) sleep rather than sleep(0): call_later handles fire from the loop's timer
        # queue, and a bare yield does not reliably drain a chain of them.
        await asyncio.sleep(0.05)

    attempts = [e for e in captured if e["event"] == "partition_resume_failed"]
    assert len(attempts) == MAX_RESUME_ATTEMPTS, (
        f"expected exactly {MAX_RESUME_ATTEMPTS} bounded attempts, got {len(attempts)}"
    )
    abandoned = next(e for e in captured if e["event"] == "partition_resume_abandoned")
    assert abandoned["metric"] == "state_machine_partition_resume_abandoned_total"
    assert not shell._resume_handles, "a timer chain outlived the abandonment"


@pytest.mark.asyncio
async def test_a_lost_assignment_stays_a_silent_no_op(monkeypatch) -> None:
    """A `KafkaError` means the partition is somebody else's problem now — not an incident."""
    shell, consumer = _shell(monkeypatch)
    consumer.resume.side_effect = IllegalStateError("partitions not assigned")

    with capture_logs() as captured:
        shell._resume_partition(TP)

    assert not [e for e in captured if e["event"].startswith("partition_resume")]
    assert not shell._resume_handles


@pytest.mark.asyncio
async def test_a_non_kafka_rewind_failure_never_escapes_handle_message(monkeypatch) -> None:
    """`_retry_later` runs inside an `except` block: an escape terminates `run()`."""
    shell, consumer = _shell(monkeypatch)
    consumer.pause.side_effect = AssertionError("assignment is None")
    msg = SimpleNamespace(topic=TOPIC, partition=0, offset=3, value=b"{not json at all}")

    with capture_logs() as captured:
        # Must not raise. Poison would commit; this is the transient arm, reached by making
        # the rewind itself fail.
        shell._retry_later(msg)

    rewind_failed = next(e for e in captured if e["event"] == "transient_retry_rewind_failed")
    assert rewind_failed["error"] == "builtins.AssertionError"
    assert not shell._resume_handles
