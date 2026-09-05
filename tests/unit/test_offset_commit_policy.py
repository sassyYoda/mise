"""Unit: WR-01/WR-02/CR-01 — what gets committed, and what a failing commit is allowed to do.

`handle_message` used one blanket `except Exception` and then committed unconditionally, so a
Redis timeout, a broker outage or a producer failure discarded the buffered state and marked
the message done. The message was fine; the world was not. For an `availability.raw` message
the next scheduled poll mostly heals the state, but for a `polls.completed` `error`/`timeout`
the UNKNOWN mark is lost permanently, together with any `Close` that had not run yet.

The single-message tests below are necessary but NOT sufficient, and pretending otherwise is
how CR-01 shipped: `commit.await_count == 0` for one message in isolation is true even when
the very next message commits an offset past it. The `run()`-driven tests at the bottom are
the ones that observe the group watermark.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiokafka import TopicPartition
from aiokafka.errors import CommitFailedError, IllegalStateError, KafkaError

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.state_machine.consumer import StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.store import BufferedStateStore, MemoryStateStore
from tests.unit.factories import make_raw

RID = 42
DATE = "2026-05-01"
PARTY = 2
T0 = 1_800_000_000_000
TOPIC = "availability.raw"


def _shell(monkeypatch: pytest.MonkeyPatch, *, redis_client: object | None = None) -> tuple[
    StateMachineConsumer, AsyncMock
]:
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    durable = MemoryStateStore()
    buffer = BufferedStateStore(durable)
    consumer = AsyncMock()
    # seek/pause/resume are SYNCHRONOUS on AIOKafkaConsumer; leaving them as AsyncMock
    # attributes would make the shell's cursor calls silently return un-awaited coroutines.
    consumer.seek = MagicMock()
    consumer.pause = MagicMock()
    consumer.resume = MagicMock()
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


# -- WR-02: every documented rebalance/broker outcome of `commit` must be survivable --


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        CommitFailedError("group membership changed"),
        IllegalStateError("partitions not assigned"),
        KafkaError("broker is unhappy"),
    ],
    ids=["commit_failed", "illegal_state", "kafka_error"],
)
async def test_a_failing_commit_never_kills_the_service(monkeypatch, exc) -> None:
    """`_commit` runs OUTSIDE handle_message's try, so an escape terminates run()."""
    shell, consumer = _shell(monkeypatch)
    consumer.commit.side_effect = exc

    await shell.handle_message(_good_msg())  # must not raise

    assert consumer.commit.await_count == 1


def test_illegal_state_error_is_a_sibling_of_commit_failed_not_a_subclass() -> None:
    """Pin the hierarchy the fix depends on: only `KafkaError` covers all three."""
    assert not issubclass(IllegalStateError, CommitFailedError)
    assert issubclass(IllegalStateError, KafkaError)
    assert issubclass(CommitFailedError, KafkaError)


# -- CR-01: the group watermark must never advance past a transiently failed offset --


class _Drained(Exception):
    """Sentinel raised by the fake consumer to end a bounded `run()`."""


class _FakeConsumer:
    """
    The smallest consumer that can observe the defect: a position, a commit log, and the
    three cursor operations the transient path uses.

    An `AsyncMock` cannot show this bug. The defect is not in what `handle_message` does to
    ONE message, it is in what the NEXT message's commit does to the group watermark, so the
    fixture has to model a position that advances on its own and a commit that records an
    absolute offset. Offsets are dense from 0, so `seek(tp, n)` is `position = n`.
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


async def _drive_three_messages(monkeypatch) -> _FakeConsumer:
    """Three messages; the middle one's Redis claim fails once, then recovers."""
    monkeypatch.setattr("services.state_machine.consumer.insert_event", AsyncMock())
    monkeypatch.setattr(
        "services.state_machine.consumer.TRANSIENT_RETRY_BACKOFF_SECONDS", 0.0
    )

    failures = {"remaining": 1}

    async def flaky_set(*args, **kwargs):
        if failures["remaining"]:
            failures["remaining"] -= 1
            raise ConnectionError("redis is down")
        return True

    redis_client = AsyncMock()
    redis_client.set.side_effect = flaky_set

    durable = MemoryStateStore()
    buffer = BufferedStateStore(durable)
    consumer = _FakeConsumer(
        [
            _raw_at(0, T0),               # opens the cycle: PENDING, no emit
            _raw_at(1, T0 + 9_000),       # confirms: emits, and the claim blows up
            _raw_at(2, T0 + 20_000),      # refresh: no emit
        ]
    )
    shell = StateMachineConsumer(
        consumer=consumer,  # type: ignore[arg-type]
        producer=AsyncMock(),
        redis_client=redis_client,  # type: ignore[arg-type]
        scheduler=AsyncMock(),
        engine=DiffEngine(buffer, confirm_delay_ms=8_000),
        store=durable,
        buffer=buffer,
    )

    with pytest.raises(_Drained):
        await asyncio.wait_for(shell.run(), timeout=10)
    return consumer


@pytest.mark.asyncio
async def test_the_watermark_never_advances_past_a_transiently_failed_offset(monkeypatch):
    """
    CR-01. Not committing the failed message is NOT enough to keep it.

    The consumer's position advances whether or not a commit happens, so the next message's
    `commit({tp: offset + 1})` sets the group's committed offset strictly past the failed one
    — which is then below the watermark and never redelivered. Before the `seek`, this ran
    `[1, 3]`: offset 1 was skipped permanently and its confirmed opening lost.
    """
    consumer = await _drive_three_messages(monkeypatch)

    assert consumer.commits == [1, 2, 3], (
        "the committed offsets must be contiguous: a gap means the watermark jumped over a "
        f"message that was never handled successfully. Got {consumer.commits}"
    )
    for committed in consumer.commits:
        # `commit(N)` asserts every offset below N is done. Nothing may be committed until
        # the failed offset has actually been handled.
        assert committed <= max(consumer.delivered) + 1


@pytest.mark.asyncio
async def test_a_transiently_failed_message_is_redelivered_in_process(monkeypatch):
    """The rewind must make the FAILED message the next one delivered, not the one after."""
    consumer = await _drive_three_messages(monkeypatch)

    assert consumer.seeks == [1], f"expected one rewind to offset 1, got {consumer.seeks}"
    assert consumer.delivered == [0, 1, 1, 2], (
        f"offset 1 must be re-delivered before offset 2; got {consumer.delivered}"
    )
