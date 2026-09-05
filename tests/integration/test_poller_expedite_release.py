"""Integration: STATE-03 — the poller release path consumes the expedite flag.

Drives one real iteration of ``services.poller.scheduler.poll_loop`` against a live
Redis 7.2 container with a stub adapter/publisher, so the branch under test is the
production release code and not a re-implementation of it.
"""
import asyncio
import sys
import time
from typing import Any

import pytest
import redis.asyncio as redis

from services.poller.scheduler import poll_loop
from shared.redis_keys import (
    CONFIRM_DELAY_MS,
    SCHED_POLLS,
    SCHED_POLLS_INFLIGHT,
    sched_expedite_key,
)
from shared.scheduler.lua import LuaScheduler

pytestmark = pytest.mark.integration

JOB = "opentable:42"

# services/poller/config.py freezes REDIS_URL / KAFKA_BOOTSTRAP_SERVERS into module
# constants at IMPORT time. Importing poll_loop here pulls that module in during
# collection, before test_poller_smoke.py sets those env vars — which would pin the
# smoke test's poller to the localhost defaults instead of its testcontainers. Evict
# the poller modules on teardown so a later import re-reads the environment.
_POLLER_MODULES = (
    "services.poller.main",
    "services.poller.scheduler",
    "services.poller.config",
)


@pytest.fixture(scope="module", autouse=True)
def _restore_poller_module_import_state():
    yield
    for name in _POLLER_MODULES:
        sys.modules.pop(name, None)


class _StubAdapter:
    """Stands in for OpenTableAdapter — never touches the network."""

    async def poll(self, rid: int, dates: Any, party_sizes: Any) -> dict[str, Any]:
        return {"data": {"availability": []}}


class _StubPublisher:
    """Stands in for Publisher — records calls, writes nothing."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def publish(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


async def _run_one_release(redis_url: str, *, set_flag: bool) -> tuple[int, float]:
    """Seed one due job, run poll_loop until it releases, return (now_ms, released_score)."""
    r = redis.from_url(redis_url, decode_responses=False)
    await r.delete(SCHED_POLLS, SCHED_POLLS_INFLIGHT, sched_expedite_key(JOB))

    sched = LuaScheduler(r)
    await sched.start()

    now_ms = int(time.time() * 1000)
    await r.zadd(SCHED_POLLS, {JOB: now_ms - 1_000})
    if set_flag:
        await r.set(sched_expedite_key(JOB), "1", ex=120)

    publisher = _StubPublisher()
    task = asyncio.create_task(poll_loop(sched, _StubAdapter(), publisher))  # type: ignore[arg-type]
    try:
        deadline = time.monotonic() + 20
        score = None
        while time.monotonic() < deadline:
            score = await r.zscore(SCHED_POLLS, JOB)
            if score is not None and score > now_ms:
                break
            await asyncio.sleep(0.05)
        assert score is not None and score > now_ms, "poll_loop never released the job"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert publisher.calls, "poll_loop must publish before releasing"
    await r.aclose()
    return now_ms, score


@pytest.mark.asyncio
async def test_release_with_expedite_flag_uses_confirm_delay(redis_url):
    """With the flag set, the job is released at now_ms + 8000 (not the 90s jitter band)."""
    now_ms, score = await _run_one_release(redis_url, set_flag=True)

    # The loop re-reads the clock at release time, so allow for elapsed wall time.
    assert now_ms + CONFIRM_DELAY_MS <= score <= now_ms + CONFIRM_DELAY_MS + 20_000
    assert score < now_ms + 76_500, "expedited release must not land in the jitter band"


@pytest.mark.asyncio
async def test_release_without_flag_uses_the_jitter_band(redis_url):
    """With no flag, the default D-17 90s +/- 15% score is used and the flag path is inert."""
    now_ms, score = await _run_one_release(redis_url, set_flag=False)

    assert now_ms + 76_500 <= score <= now_ms + 103_500 + 20_000
    assert score > now_ms + 76_500 - 1


@pytest.mark.asyncio
async def test_expedite_flag_is_consumed_by_the_release(redis_url):
    """The flag is a one-shot: after the release it is gone, so the next cycle is normal."""
    r = redis.from_url(redis_url, decode_responses=False)
    await _run_one_release(redis_url, set_flag=True)

    assert await r.get(sched_expedite_key(JOB)) is None
    await r.aclose()
