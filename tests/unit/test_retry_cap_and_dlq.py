"""Unit: CR-01 (iteration 3) — the rewind is bounded, and a retry never re-sends an acked event.

Iteration 2 fixed the silent drop by rewinding the partition to the failed offset. That fix was
correct and is still here; what it lacked was a floor. The failure taxonomy had exactly two
arms — `ValidationError`/`ParseError` → poison, and EVERYTHING ELSE → transient — and
"everything else" is not a synonym for "transient". It includes `AttributeError`, `KeyError`, a
Redis `WRONGTYPE`, an `UnknownTopicOrPartitionError` after someone deletes a topic, and every
programming bug that will ever be introduced into `engine.py` or `store.py`. None of those
succeeds on retry, so iteration 2's silent data loss became a permanently stalled partition —
for a single-partition topic, a total pipeline outage whose only symptom is two log lines at
0.5 Hz, forever, with nothing to page on.

The second consequence was worse than the stall. When the permanent failure landed AFTER a
slot's `send_and_wait` — `_flush_slot` is the live example — every retry re-executed the emit:
`set_nx_ex` returns False, `_crashed_mid_emit` reads a record still PENDING (because
`_discard()` threw the buffered write away), answers True, and the event goes out again. About
43k duplicate events a day. Phase 4's Layer-2 key dedupes the notification; nothing dedupes the
topic, the insert attempt, or the log stream.

Both tests drive the real `run()` loop, because neither defect is visible in a single
`handle_message` call: one is about what the loop does over repeated deliveries, the other
about what the SECOND delivery does with the first delivery's side effects.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiokafka import TopicPartition
from redis.exceptions import ResponseError
from structlog.testing import capture_logs

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.state_machine.config import DEFAULT_MAX_MESSAGE_ATTEMPTS, max_message_attempts
from services.state_machine.consumer import DLQ_TOPIC, EVENTS_TOPIC, StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.models import SlotState
from services.state_machine.store import BufferedStateStore, MemoryStateStore
from shared.events import AvailabilityEvent
from tests.unit.factories import make_raw

RID = 42
DATE = "2026-05-01"
PARTY = 2
T0 = 1_800_000_000_000
T1 = T0 + 9_000
TOPIC = "availability.raw"
BAR = "19:00|bar"
STANDARD = "19:00|standard"


class _Drained(Exception):
    """Sentinel raised by the fake consumer to end a bounded `run()`."""


class _FakeConsumer:
    """A position, a commit log, and the three SYNCHRONOUS cursor operations.

    An `AsyncMock` cannot show either defect here: the retry cap is a property of the loop
    across repeated deliveries of one offset, which needs a position that a `seek` can move.
    """

    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self._messages = messages
        self._position = 0
        self._paused: set[TopicPartition] = set()
        self._resumed = asyncio.Event()
        self.commits: list[int] = []
        self.delivered: list[int] = []
        self.seeks: list[int] = []

    async def getone(self) -> SimpleNamespace:
        tp = TopicPartition(TOPIC, 0)
        while tp in self._paused:
            self._resumed.clear()
            await self._resumed.wait()
        if self._position >= len(self._messages):
            raise _Drained
        msg = self._messages[self._position]
        self._position += 1
        self.delivered.append(msg.offset)
        return msg

    async def commit(self, offsets: dict[TopicPartition, int]) -> None:
        self.commits.extend(offsets.values())

    def seek(self, tp: TopicPartition, offset: int) -> None:
        self.seeks.append(offset)
        self._position = offset

    def pause(self, tp: TopicPartition) -> None:
        self._paused.add(tp)

    def resume(self, tp: TopicPartition) -> None:
        self._paused.discard(tp)
        self._resumed.set()


def _raw_at(offset: int, polled_at_epoch_ms: int) -> SimpleNamespace:
    return SimpleNamespace(
        topic=TOPIC,
        partition=0,
        offset=offset,
        value=make_raw(
            rid=RID,
            dates=[DATE],
            parties=[PARTY],
            response=OPENTABLE_SUCCESS_RESPONSE,
            polled_at_epoch_ms=polled_at_epoch_ms,
        ).to_bytes(),
    )


class _FakeRedis:
    """`set_nx_ex` semantics only: True on a fresh key, None on a taken one."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}

    async def set(
        self, key: str, value: str, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


# -- 1. A permanent failure is retried exactly N times, dead-lettered, and committed past --


class _PermanentlyBrokenStore(MemoryStateStore):
    """A Redis that will never work again for this key — a WRONGTYPE, not a timeout."""

    async def get_slots(self, rid: int, date: str, party: int):  # type: ignore[override]
        raise ResponseError("WRONGTYPE Operation against a key holding the wrong kind of value")


@pytest.mark.asyncio
async def test_a_permanent_failure_is_retried_exactly_n_times_then_committed_past(
    monkeypatch,
) -> None:
    """Before the cap this ran forever: `commits == []` and the partition never moved again."""
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    monkeypatch.setattr("services.state_machine.consumer.TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0)

    max_attempts = 3
    store = _PermanentlyBrokenStore()
    producer = AsyncMock()
    consumer = _FakeConsumer([_raw_at(0, T0)])
    shell = StateMachineConsumer(
        consumer=consumer,  # type: ignore[arg-type]
        producer=producer,
        redis_client=_FakeRedis(),  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(store, confirm_delay_ms=8_000),
        store=store,
        max_attempts=max_attempts,
    )

    with capture_logs() as captured:
        with pytest.raises(_Drained):
            await asyncio.wait_for(shell.run(), timeout=10)

    assert consumer.delivered == [0, 0, 0], (
        f"expected exactly {max_attempts} deliveries of the poisoned offset, "
        f"got {consumer.delivered}"
    )
    assert consumer.commits == [1], (
        "the partition must move past a message that can never succeed; an uncommitted offset "
        f"here is a permanent outage. Got {consumer.commits}"
    )

    attempts = [e for e in captured if e["event"] == "message_handling_failed"]
    assert [e["attempt"] for e in attempts] == [1, 2, 3]
    assert all(e["error"] == "redis.exceptions.ResponseError" for e in attempts)

    exhausted = next(e for e in captured if e["event"] == "message_retries_exhausted")
    assert exhausted["attempts"] == max_attempts
    assert exhausted["metric"] == "state_machine_messages_dead_lettered_total"


@pytest.mark.asyncio
async def test_the_exhausted_message_is_published_to_the_dead_letter_topic(monkeypatch) -> None:
    """Committing past a message without preserving it would be the iteration-2 drop again."""
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    monkeypatch.setattr("services.state_machine.consumer.TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0)

    store = _PermanentlyBrokenStore()
    producer = AsyncMock()
    poisoned = _raw_at(0, T0)
    consumer = _FakeConsumer([poisoned])
    shell = StateMachineConsumer(
        consumer=consumer,  # type: ignore[arg-type]
        producer=producer,
        redis_client=_FakeRedis(),  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(store, confirm_delay_ms=8_000),
        store=store,
        max_attempts=2,
    )

    with capture_logs() as captured:
        with pytest.raises(_Drained):
            await asyncio.wait_for(shell.run(), timeout=10)

    dlq_calls = [c for c in producer.send_and_wait.await_args_list if c.args[0] == DLQ_TOPIC]
    assert len(dlq_calls) == 1, f"expected exactly one DLQ publish, got {len(dlq_calls)}"
    call = dlq_calls[0]
    assert call.kwargs["value"] == poisoned.value, "the DLQ record must carry the ORIGINAL bytes"
    headers = dict(call.kwargs["headers"])
    assert headers["original_topic"] == TOPIC.encode()
    assert headers["original_offset"] == b"0"
    assert headers["attempts"] == b"2"
    assert headers["error"] == b"redis.exceptions.ResponseError"

    dead_lettered = next(e for e in captured if e["event"] == "message_dead_lettered")
    assert dead_lettered["dlq_topic"] == DLQ_TOPIC


@pytest.mark.asyncio
async def test_a_dead_dlq_never_recreates_the_stall(monkeypatch) -> None:
    """The DLQ is best effort: if it is down too, the commit still has to happen."""
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    monkeypatch.setattr("services.state_machine.consumer.TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0)

    store = _PermanentlyBrokenStore()
    producer = AsyncMock()
    producer.send_and_wait.side_effect = ConnectionError("the broker is gone as well")
    consumer = _FakeConsumer([_raw_at(0, T0)])
    shell = StateMachineConsumer(
        consumer=consumer,  # type: ignore[arg-type]
        producer=producer,
        redis_client=_FakeRedis(),  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(store, confirm_delay_ms=8_000),
        store=store,
        max_attempts=2,
    )

    with capture_logs() as captured:
        with pytest.raises(_Drained):
            await asyncio.wait_for(shell.run(), timeout=10)

    assert consumer.commits == [1], "a failed DLQ publish must not re-stall the partition"
    assert any(e["event"] == "dead_letter_publish_failed" for e in captured)


# -- 2. A retry after a partial emit sends the REMAINING slot only --


class _FlakyFlushBuffer(BufferedStateStore):
    """Fails the first per-slot flush, exactly where the reviewer's reproduction failed.

    This is the dangerous window: `_flush_slot` runs AFTER `send_and_wait`, so the broker has
    already accepted the event when the failure hits.
    """

    def __init__(self, durable: MemoryStateStore) -> None:
        super().__init__(durable)
        self.failures_remaining = 1

    async def flush_slot(self, rid: int, date: str, party: int, key: str) -> None:
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise ResponseError("OOM command not allowed when used memory > 'maxmemory'")
        await super().flush_slot(rid, date, party, key)


@pytest.mark.asyncio
async def test_a_retry_after_a_partial_emit_sends_the_remaining_slot_only(monkeypatch) -> None:
    """The duplicate-per-retry defect, on the two-slot payload that produces it in production."""
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    monkeypatch.setattr("services.state_machine.consumer.TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0)

    durable = MemoryStateStore()
    buffer = _FlakyFlushBuffer(durable)
    producer = AsyncMock()
    consumer = _FakeConsumer([_raw_at(0, T0), _raw_at(1, T1)])
    shell = StateMachineConsumer(
        consumer=consumer,  # type: ignore[arg-type]
        producer=producer,
        redis_client=_FakeRedis(),  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(buffer, confirm_delay_ms=8_000),
        store=durable,
        buffer=buffer,
        max_attempts=5,
    )

    with pytest.raises(_Drained):
        await asyncio.wait_for(shell.run(), timeout=10)

    sent = [
        AvailabilityEvent.model_validate_json(call.kwargs["value"])
        for call in producer.send_and_wait.await_args_list
        if call.args[0] == EVENTS_TOPIC
    ]
    assert [e.seat_type for e in sent] == ["bar", "standard"], (
        "the retry re-sent an event the broker had already acked. Every retry does this, so a "
        f"permanent failure here is ~43k duplicates a day. Got {[e.seat_type for e in sent]}"
    )
    assert len({e.event_id for e in sent}) == 2, "two distinct slots, two distinct event ids"

    # The retry did not merely skip the send — it finished the work.
    states = {k: v.state for k, v in (await durable.get_slots(RID, DATE, PARTY)).items()}
    assert states == {BAR: SlotState.AVAILABLE, STANDARD: SlotState.AVAILABLE}
    assert consumer.commits == [1, 2], f"both messages must commit; got {consumer.commits}"
    assert consumer.delivered == [0, 1, 1], f"offset 1 retried once; got {consumer.delivered}"


@pytest.mark.asyncio
async def test_the_acked_set_is_cleared_when_the_offset_advances(monkeypatch) -> None:
    """Retry accounting must not leak across messages, or a later emit would be suppressed."""
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    durable = MemoryStateStore()
    buffer = BufferedStateStore(durable)
    shell = StateMachineConsumer(
        consumer=AsyncMock(),
        producer=AsyncMock(),
        redis_client=_FakeRedis(),  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(buffer, confirm_delay_ms=8_000),
        store=durable,
        buffer=buffer,
    )

    await shell.handle_message(_raw_at(0, T0))
    await shell.handle_message(_raw_at(1, T1))
    assert shell._acked_event_ids, "the confirming poll emitted, so ids were recorded"

    await shell.handle_message(_raw_at(2, T1 + 9_000))
    assert shell._acked_event_ids == set(), "a new offset must reset the retry accounting"
    assert shell._attempts == 0


# -- The cap itself is configurable, and refuses a value that would disable it --


def test_the_cap_defaults_to_five(monkeypatch) -> None:
    monkeypatch.delenv("STATE_MACHINE_MAX_ATTEMPTS", raising=False)
    assert max_message_attempts() == DEFAULT_MAX_MESSAGE_ATTEMPTS == 5


def test_the_cap_is_read_from_the_environment(monkeypatch) -> None:
    monkeypatch.setenv("STATE_MACHINE_MAX_ATTEMPTS", "12")
    assert max_message_attempts() == 12


@pytest.mark.parametrize("value", ["0", "-1", "many", "5.5"], ids=["zero", "negative", "word", "float"])
def test_a_cap_that_would_break_the_policy_is_refused(monkeypatch, value: str) -> None:
    """A typo must not quietly restore the unbounded retry, nor dead-letter on first hiccup."""
    monkeypatch.setenv("STATE_MACHINE_MAX_ATTEMPTS", value)
    with pytest.raises(RuntimeError, match="STATE_MACHINE_MAX_ATTEMPTS"):
        max_message_attempts()
