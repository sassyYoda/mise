"""Integration: STATE-04 — kill -9 between the state write and the offset commit (D-46, D-51).

ROADMAP Phase 2 success criterion 3. The service is launched as a real subprocess with the
test-only ``MISE_CRASH_AFTER=state_write`` hook, so the kill is an uncatchable SIGKILL landing
after the Kafka send and the Redis state write but before the offset commit — the single worst
moment in the pipeline. Restarted clean, it re-reads the same offsets and must produce exactly
one ``availability.events`` record per ``event_id``.

The ``returncode == -SIGKILL`` assertion is load-bearing: without it, a run where the hook never
fired would pass vacuously.
"""
from __future__ import annotations

import copy
import os
import signal
import subprocess
import time as _time
from collections import Counter
from typing import Any
from uuid import UUID

import pytest
import redis.asyncio as aioredis
from aiokafka import AIOKafkaConsumer

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from shared.events import AvailabilityEvent, AvailabilityRaw
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
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _single_slot_response() -> dict[str, Any]:
    """The shipped fixture trimmed to one seating type, so one poll pair means one event."""
    payload = copy.deepcopy(OPENTABLE_SUCCESS_RESPONSE)
    payload["data"]["availability"][0]["availability"][0]["timeSlots"][0]["seatingTypes"] = [
        "standard"
    ]
    return payload


def _raw(polled_at_epoch_ms: int) -> AvailabilityRaw:
    return AvailabilityRaw(
        poll_id=UUID(int=polled_at_epoch_ms % (1 << 128)),
        source="opentable",
        restaurant_id=RID,
        polled_at_epoch_ms=polled_at_epoch_ms,
        raw_response=_single_slot_response(),
        request_params={"rid": RID, "dates": [DATE], "party_sizes": [PARTY]},
    )


def _launch(env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        ["uv", "run", "python", "-m", "services.state_machine"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


async def _drain_events(bootstrap: str) -> list[AvailabilityEvent]:
    consumer = AIOKafkaConsumer(
        "availability.events",
        bootstrap_servers=bootstrap,
        auto_offset_reset="earliest",
        group_id=f"chaos-drain-{_time.time_ns()}",
    )
    await consumer.start()
    try:
        batches = await consumer.getmany(timeout_ms=10_000, max_records=100)
        return [
            AvailabilityEvent.model_validate_json(m.value)
            for records in batches.values()
            for m in records
        ]
    finally:
        await consumer.stop()


@pytest.mark.asyncio
async def test_sigkill_before_commit_produces_no_duplicate_events(
    kafka_container, redis_url, db_urls, monkeypatch
):
    """SC3: crash after the state write, restart clean, and still emit exactly once."""
    bootstrap = kafka_container.get_bootstrap_server()

    # monkeypatch, not a bare os.environ assignment: an unrestored KAFKA_BOOTSTRAP_SERVERS /
    # REDIS_URL / DATABASE_URL_* silently binds every later test in the session to a container
    # that has already been torn down — an order-dependent failure (WR-15). The subprocess
    # environment is still snapshotted from os.environ below, which sees the patched values.
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", bootstrap)
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DATABASE_URL_ASYNC", db_urls["async"])
    monkeypatch.setenv("DATABASE_URL_SYNC", db_urls["sync"])
    reset_shared_db_singletons()

    base_env = {**os.environ}
    apply_migrations(base_env)
    create_topics(base_env)

    t0 = int(_time.time() * 1000)
    r = aioredis.from_url(redis_url)
    await r.delete(avail_state_key(RID, DATE, PARTY), avail_meta_key(RID), SCHED_POLLS)
    await r.zadd(SCHED_POLLS, {JOB: t0 + 3_600_000})

    producer = await make_producer(bootstrap)
    try:
        for polled_at in (t0, t0 + 9_000):
            await producer.send_and_wait(
                "availability.raw", value=_raw(polled_at).to_bytes(), key=JOB
            )
    finally:
        await producer.stop()

    # 1. Run with the crash hook armed. The confirming poll emits, writes state, then dies.
    # ENV must be named explicitly: the crash-hook interlock fails closed, so an unset ENV
    # refuses to arm the hook rather than defaulting to "dev" (WR-13, T-02-04).
    crashing = _launch({**base_env, "MISE_CRASH_AFTER": "state_write", "ENV": "test"})
    try:
        crashing.wait(timeout=120)
    except subprocess.TimeoutExpired:  # pragma: no cover - diagnostic path
        crashing.kill()
        stdout, stderr = crashing.communicate()
        pytest.fail(
            "crash hook never fired within 120s; "
            f"stdout={stdout.decode()[-2000:]!r} stderr={stderr.decode()[-2000:]!r}"
        )
    # `uv run` sits between pytest and the interpreter, so the SIGKILL surfaces either as the
    # raw negative signal (python as the direct child) or as uv's own 128 + signal exit code.
    # Both prove the hook fired; a 0 or a 1 would mean the process died some other way.
    killed = (
        crashing.returncode == -signal.SIGKILL
        or crashing.returncode == 128 + signal.SIGKILL
    )
    assert killed, (
        f"expected an uncatchable SIGKILL (-{signal.SIGKILL} or {128 + signal.SIGKILL}), "
        f"got {crashing.returncode}. Without this the whole test would pass vacuously."
    )

    after_crash = await _drain_events(bootstrap)
    assert len(after_crash) == 1, "the confirming poll must have emitted before the crash"

    # The offset was never committed, so the same message is still pending redelivery.
    state = await r.hgetall(avail_state_key(RID, DATE, PARTY))
    assert state, "the state write must have landed before the SIGKILL"

    # 2. Restart clean. The redelivered message must not produce a second event.
    restarted = _launch(base_env)
    # ONE consumer for the whole observation window, reading from the beginning and
    # accumulating. The previous shape called _drain_events in a tight loop, and that helper
    # returns as soon as any record is available — so the loop spun, created tens of throwaway
    # consumer groups, and hammered the broker for 45 s. A single getmany with a 1 s timeout
    # paces the loop by itself and needs no sleep (IN-06).
    watcher = AIOKafkaConsumer(
        "availability.events",
        bootstrap_servers=bootstrap,
        auto_offset_reset="earliest",
        group_id=f"chaos-watch-{_time.time_ns()}",
    )
    await watcher.start()
    try:
        seen: list[AvailabilityEvent] = []
        observation_end = _time.monotonic() + 45
        while _time.monotonic() < observation_end:
            if restarted.poll() is not None:
                stdout, stderr = restarted.communicate()
                pytest.fail(
                    f"restarted service exited with {restarted.returncode}; "
                    f"stderr={stderr.decode()[-2000:]!r}"
                )
            batches = await watcher.getmany(timeout_ms=1_000, max_records=100)
            seen.extend(
                AvailabilityEvent.model_validate_json(m.value)
                for records in batches.values()
                for m in records
            )
            assert len(seen) <= 1, f"redelivery emitted a duplicate: {len(seen)} events"
        assert restarted.poll() is None, "the restarted service must stay up without the hook"
    finally:
        await watcher.stop()
        restarted.terminate()
        try:
            restarted.wait(timeout=30)
        except subprocess.TimeoutExpired:  # pragma: no cover - diagnostic path
            restarted.kill()

    events = await _drain_events(bootstrap)
    counts = Counter(str(event.event_id) for event in events)
    duplicates = {event_id: n for event_id, n in counts.items() if n > 1}
    assert duplicates == {}, f"redelivery produced duplicate events: {duplicates}"
    assert len(events) == 1, f"expected exactly one event after the restart, got {len(events)}"
    await r.aclose()
