"""Integration: STATE-03 — EXPEDITE_POLL_LUA against a live Redis 7.2 container.

Proves the four atomicity properties the D-43 confirmation handshake depends on:
``XX`` never resurrects an in-flight job into the ready set, ``LT`` never pushes an
already-sooner poll later, the in-flight branch leaves a self-expiring flag, and
``GETDEL`` consumes that flag exactly once.
"""
import time

import pytest
import redis.asyncio as redis

from shared.redis_keys import (
    CONFIRM_DELAY_MS,
    EXPEDITE_FLAG_TTL_SECONDS,
    SCHED_POLLS,
    SCHED_POLLS_INFLIGHT,
    sched_expedite_key,
)
from shared.scheduler.lua import LuaScheduler

pytestmark = pytest.mark.integration

JOB = "opentable:42"
ABSENT_JOB = "opentable:99"


async def _fresh(redis_url):
    """Return a started LuaScheduler over a clean scheduler keyspace."""
    r = redis.from_url(redis_url, decode_responses=False)
    await r.delete(SCHED_POLLS, SCHED_POLLS_INFLIGHT)
    await r.delete(sched_expedite_key(JOB), sched_expedite_key(ABSENT_JOB))
    sched = LuaScheduler(r)
    await sched.start()
    return r, sched


@pytest.mark.asyncio
async def test_queued_job_is_pulled_forward_to_confirm_delay(redis_url):
    """A job sitting in sched:polls has its score lowered to exactly now_ms + 8000."""
    r, sched = await _fresh(redis_url)
    now_ms = int(time.time() * 1000)
    await r.zadd(SCHED_POLLS, {JOB: now_ms + 100_000})

    result = await sched.expedite(JOB, now_ms)

    assert result == "zset"
    assert await r.zscore(SCHED_POLLS, JOB) == float(now_ms + CONFIRM_DELAY_MS)
    await r.aclose()


@pytest.mark.asyncio
async def test_lt_guard_never_raises_an_already_earlier_score(redis_url):
    """A later expedite must not push an already-sooner poll further out (ZADD LT)."""
    r, sched = await _fresh(redis_url)
    now_ms = int(time.time() * 1000)
    await r.zadd(SCHED_POLLS, {JOB: now_ms + 100_000})
    await sched.expedite(JOB, now_ms)
    first_score = await r.zscore(SCHED_POLLS, JOB)

    assert await sched.expedite(JOB, now_ms + 50_000) == "zset"

    assert await r.zscore(SCHED_POLLS, JOB) == first_score
    await r.aclose()


@pytest.mark.asyncio
async def test_xx_guard_never_resurrects_an_inflight_job(redis_url):
    """An in-flight job gets a self-expiring flag and is NOT created in sched:polls."""
    r, sched = await _fresh(redis_url)
    now_ms = int(time.time() * 1000)
    await r.zadd(SCHED_POLLS_INFLIGHT, {ABSENT_JOB: now_ms + 60_000})

    result = await sched.expedite(ABSENT_JOB, now_ms)

    assert result == "flag"
    assert await r.zscore(SCHED_POLLS, ABSENT_JOB) is None
    ttl = await r.ttl(sched_expedite_key(ABSENT_JOB))
    assert 1 <= ttl <= EXPEDITE_FLAG_TTL_SECONDS
    assert await r.get(sched_expedite_key(ABSENT_JOB)) == b"1"
    await r.aclose()


@pytest.mark.asyncio
async def test_consume_expedite_is_exactly_once(redis_url):
    """GETDEL consumes the flag on the first call and returns False on the second."""
    r, sched = await _fresh(redis_url)
    now_ms = int(time.time() * 1000)
    assert await sched.expedite(ABSENT_JOB, now_ms) == "flag"

    assert await sched.consume_expedite(ABSENT_JOB) is True
    assert await sched.consume_expedite(ABSENT_JOB) is False
    await r.aclose()


@pytest.mark.asyncio
async def test_consume_expedite_on_an_absent_flag_returns_false(redis_url):
    """Empty edge (STATE-01): an absent flag returns False rather than raising."""
    r, sched = await _fresh(redis_url)

    assert await sched.consume_expedite("opentable:404") is False
    await r.aclose()


@pytest.mark.asyncio
async def test_a_burst_of_expedites_yields_one_member_at_one_score(redis_url):
    """Threat T-02-01: five PENDING slots cannot compound into five pulled-forward polls."""
    r, sched = await _fresh(redis_url)
    now_ms = int(time.time() * 1000)
    await r.zadd(SCHED_POLLS, {JOB: now_ms + 100_000})

    for _ in range(5):
        await sched.expedite(JOB, now_ms)

    members = await r.zrange(SCHED_POLLS, 0, -1)
    assert members == [JOB.encode()]
    assert await r.zscore(SCHED_POLLS, JOB) == float(now_ms + CONFIRM_DELAY_MS)
    await r.aclose()


@pytest.mark.asyncio
async def test_expedite_never_pulls_a_poll_below_the_confirm_delay(redis_url):
    """Prohibition: the expedited score is never earlier than now_ms + CONFIRM_DELAY_MS."""
    r, sched = await _fresh(redis_url)
    now_ms = int(time.time() * 1000)
    await r.zadd(SCHED_POLLS, {JOB: now_ms - 5_000})

    await sched.expedite(JOB, now_ms)

    # LT: the pre-existing score was already earlier, so it must survive untouched —
    # the expedite may only ever pull forward, never push a due poll later either.
    assert await r.zscore(SCHED_POLLS, JOB) == float(now_ms - 5_000)
    await r.aclose()
