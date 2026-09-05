"""Integration: STATE-01..05 — availability.raw becomes availability.events plus a hypertable row.

This is the phase's headline claim (D-51, ROADMAP SC4) proven against live Kafka, Redis 7.2
and TimescaleDB containers: two polls 9 s apart confirm the shipped fixture's slots and write
one analytics row each, a third poll that omits them closes every row with a
``duration_seconds`` and emits nothing, an errored ``polls.completed`` marks the restaurant
UNKNOWN without touching a slot, and the first sighting pulls the restaurant's next poll
forward through the ZSET scheduler rather than sleeping (D-43).

The payload is the SHIPPED fixture, ``seatingTypes: ["bar", "standard"]`` and all — it is NOT
trimmed to one seating type (WR-05). ``seat_type`` is part of slot identity (D-36), so one
timeslot is two slots sharing one booking token, and the confirming poll emits both. That is
the multi-slot emit path — a per-slot claim, a per-slot ``send_and_wait``, a per-slot
MULTI/EXEC flush — and against anything but real Redis and a real broker it was only ever
exercised by unit tests with a ``FakeRedis`` that implements ``set``.

Every ``polled_at_epoch_ms`` is set explicitly, so the 9 s confirmation window costs no real
time; nothing in this file waits out a wall-clock delay.

``services.state_machine`` is imported INSIDE the test body, never at module scope: the
service reads its Redis/Kafka/Postgres URLs lazily so a collection-time import cannot freeze
the localhost defaults into another test's run (see 02-02 deviation 1).
"""
from __future__ import annotations

import asyncio
import copy
import os
import time as _time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import asyncpg
import pytest
import redis.asyncio as aioredis
from aiokafka import AIOKafkaConsumer

from services.poller.sources.opentable.fixtures import (
    OPENTABLE_EMPTY_RESPONSE,
    OPENTABLE_SUCCESS_RESPONSE,
)
from shared.events import AvailabilityEvent, AvailabilityRaw, PollCompleted
from shared.kafka import make_producer
from shared.redis_keys import SCHED_POLLS, avail_meta_key, avail_state_key
from tests.integration.conftest import (
    apply_migrations,
    create_topics,
    reset_shared_db_singletons,
)

pytestmark = pytest.mark.integration

RID = 42
DATE = "2026-05-01"
PARTY = 2
JOB = f"opentable:{RID}"
CONFIRM_DELAY_MS = 8_000


# One timeslot, two seating types, one shared booking token: two slot identities (D-36).
EXPECTED_SLOTS = 2
EXPECTED_SEAT_TYPES = {"bar", "standard"}


def _success_response() -> dict[str, Any]:
    """The shipped fixture, untrimmed — deep-copied so no test can mutate the module global."""
    return copy.deepcopy(OPENTABLE_SUCCESS_RESPONSE)


def _raw(response: dict[str, Any], polled_at_epoch_ms: int) -> AvailabilityRaw:
    """Build an availability.raw message exactly as services/poller/publisher.py would."""
    return AvailabilityRaw(
        poll_id=UUID(int=polled_at_epoch_ms % (1 << 128)),
        source="opentable",
        restaurant_id=RID,
        polled_at_epoch_ms=polled_at_epoch_ms,
        raw_response=response,
        request_params={"rid": RID, "dates": [DATE], "party_sizes": [PARTY]},
    )


async def _await_condition(
    check: Callable[[], Awaitable[bool]],
    *,
    task: asyncio.Task[None],
    message: str,
    timeout_s: float = 90.0,
) -> None:
    """Poll ``check`` until it is true, failing fast if the service died on its own."""
    deadline = _time.monotonic() + timeout_s
    while _time.monotonic() < deadline:
        if task.done():
            task.result()  # re-raises whatever killed the service
            raise AssertionError("state machine exited before the assertion could be made")
        if await check():
            return
        await asyncio.sleep(0.25)
    raise AssertionError(message)


@pytest.mark.asyncio
async def test_raw_polls_become_one_event_one_row_and_a_closure(
    kafka_container, redis_url, db_urls, monkeypatch
):
    """The whole pipeline, end to end, on message timestamps alone."""
    kafka_bootstrap = kafka_container.get_bootstrap_server()

    # monkeypatch, not a bare os.environ assignment: an unrestored KAFKA_BOOTSTRAP_SERVERS /
    # REDIS_URL / DATABASE_URL_* silently binds every later test in the session to a container
    # that has already been torn down — an order-dependent failure (WR-15).
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", kafka_bootstrap)
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DATABASE_URL_ASYNC", db_urls["async"])
    monkeypatch.setenv("DATABASE_URL_SYNC", db_urls["sync"])
    reset_shared_db_singletons()

    env = {**os.environ}
    apply_migrations(env)
    create_topics(env)

    t0 = int(_time.time() * 1000)
    confirm_ms = t0 + 9_000
    close_ms = t0 + 20_000
    error_ms = t0 + 30_000

    # Clean slate, and a queued poll far in the future so the expedite has something to lower.
    r = aioredis.from_url(redis_url)
    await r.delete(avail_state_key(RID, DATE, PARTY), avail_meta_key(RID), SCHED_POLLS)
    await r.zadd(SCHED_POLLS, {JOB: t0 + 3_600_000})

    producer = await make_producer(kafka_bootstrap)
    try:
        for raw in (
            _raw(_success_response(), t0),
            _raw(_success_response(), confirm_ms),
            _raw(OPENTABLE_EMPTY_RESPONSE, close_ms),
        ):
            await producer.send_and_wait(
                "availability.raw", value=raw.to_bytes(), key=JOB
            )
        # Dated AFTER every raw poll so the monotonic UNKNOWN rule (D-53) makes the outcome
        # independent of the unfair getone() interleaving across the two topics (Pitfall 2).
        completed = PollCompleted(
            poll_id=UUID(int=error_ms % (1 << 128)),
            source="opentable",
            restaurant_id=RID,
            polled_at_epoch_ms=error_ms,
            status="error",
            latency_ms=1,
            http_status=500,
            error="boom",
        )
        await producer.send_and_wait(
            "polls.completed", value=completed.to_bytes(), key=JOB
        )
    finally:
        await producer.stop()

    from services.state_machine.main import run

    task: asyncio.Task[None] = asyncio.create_task(run())

    async def _closed_and_marked() -> bool:
        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            closed = await conn.fetchval(
                "SELECT count(*) FROM availability_events WHERE duration_seconds IS NOT NULL"
            )
        finally:
            await conn.close()
        marked = await r.hget(avail_meta_key(RID), "unknown_since_ms")
        # Both slots must be closed, not just the first: waiting on `> 0` would race the
        # second closure and make every assertion below flaky rather than wrong.
        return closed == EXPECTED_SLOTS and marked not in (None, b"", "")

    try:
        await _await_condition(
            _closed_and_marked,
            task=task,
            message="state machine never closed the row and marked the restaurant UNKNOWN",
        )
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # 1. One confirmed event per slot on the wire, timestamped by the confirming poll.
    consumer = AIOKafkaConsumer(
        "availability.events",
        bootstrap_servers=kafka_bootstrap,
        auto_offset_reset="earliest",
        group_id=f"e2e-drain-{_time.time_ns()}",
    )
    await consumer.start()
    try:
        batches = await consumer.getmany(timeout_ms=10_000, max_records=50)
        messages = [m for records in batches.values() for m in records]
    finally:
        await consumer.stop()

    assert len(messages) == EXPECTED_SLOTS, (
        f"expected one confirmed event per seating type, got {len(messages)}"
    )
    events = [AvailabilityEvent.model_validate_json(m.value) for m in messages]
    assert {event.seat_type for event in events} == EXPECTED_SEAT_TYPES
    assert len({event.event_id for event in events}) == EXPECTED_SLOTS, (
        "the two slots share one booking token, so a token-only identity collapses them"
    )
    assert len({event.booking_token for event in events}) == 1, (
        "the fixture's whole point: one token, two slot identities"
    )
    for event, message in zip(events, messages, strict=True):
        assert event.event_type == "slot_opened"
        assert event.restaurant_id == RID
        assert event.time_slot == "19:00"
        assert event.produced_at_epoch_ms == confirm_ms, (
            "produced_at must be poll time, not wall clock"
        )
        assert event.first_seen_at_epoch_ms == t0
        assert message.key is not None and message.key.decode() == JOB

    # 2. One analytics row per event, fully populated, and closed by the third poll.
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        rows = await conn.fetch(
            "SELECT * FROM availability_events WHERE event_id = ANY($1::uuid[])",
            [event.event_id for event in events],
        )
    finally:
        await conn.close()
    assert len(rows) == EXPECTED_SLOTS, (
        f"expected one hypertable row per event, got {len(rows)}"
    )
    for row in rows:
        assert row["restaurant_id"] == RID
        assert row["first_seen_at"] is not None
        assert row["last_seen_at"] is not None
        assert row["hours_before_service"] is not None
        assert row["day_of_week"] is not None
        assert row["duration_seconds"] == 20, "close must stamp last_seen_at - first_seen_at"

    # 3. The first sighting expedited the restaurant's next poll to first_poll + 8 s (D-43).
    score = await r.zscore(SCHED_POLLS, JOB)
    assert score is not None, "the queued poll disappeared from sched:polls"
    assert abs(score - (t0 + CONFIRM_DELAY_MS)) <= 50, f"score {score} not pulled to t0+8000"

    # 4. The errored poll marked the restaurant UNKNOWN and moved no slot (D-47).
    unknown_since = await r.hget(avail_meta_key(RID), "unknown_since_ms")
    assert unknown_since is not None
    assert int(unknown_since) == error_ms
    await r.aclose()
