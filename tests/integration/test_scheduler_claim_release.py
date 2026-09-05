"""Integration: POLL-01 — Lua ZSET scheduler claim/release/reap."""
import time

import pytest
import redis.asyncio as redis

from shared.redis_keys import SCHED_POLLS, SCHED_POLLS_INFLIGHT
from shared.scheduler.lua import LuaScheduler


@pytest.fixture(scope="module")
def redis_url(redis_container):
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}"


@pytest.mark.asyncio
async def test_claim_release_cycle(redis_url):
    r = redis.from_url(redis_url, decode_responses=False)
    sched = LuaScheduler(r)
    await sched.start()
    now_ms = int(time.time() * 1000)
    # Clean slate
    await r.delete(SCHED_POLLS, SCHED_POLLS_INFLIGHT)
    # Seed one due job
    await r.zadd(SCHED_POLLS, {"opentable:42": now_ms - 1000})
    # Claim
    job = await sched.claim(now_ms)
    assert job == "opentable:42"
    # Job is now in inflight
    inflight = await r.zrange(SCHED_POLLS_INFLIGHT, 0, -1)
    assert b"opentable:42" in inflight
    # Release with next poll
    await sched.release(job, now_ms + 90_000)
    # Job back in sched:polls, inflight empty of this job
    polls = await r.zrange(SCHED_POLLS, 0, -1)
    assert b"opentable:42" in polls
    inflight_after = await r.zrange(SCHED_POLLS_INFLIGHT, 0, -1)
    assert b"opentable:42" not in inflight_after
    await r.aclose()


@pytest.mark.asyncio
async def test_reaper_requeues_expired_inflight(redis_url):
    r = redis.from_url(redis_url, decode_responses=False)
    sched = LuaScheduler(r)
    await sched.start()
    now_ms = int(time.time() * 1000)
    # Clean slate
    await r.delete(SCHED_POLLS, SCHED_POLLS_INFLIGHT)
    # Seed an expired inflight job (score in the past)
    await r.zadd(SCHED_POLLS_INFLIGHT, {"opentable:99": now_ms - 1000})
    reaped = await sched.reap(now_ms)
    assert "opentable:99" in reaped
    # Job re-enqueued to sched:polls
    polls = await r.zrange(SCHED_POLLS, 0, -1)
    assert b"opentable:99" in polls
    # Inflight cleared
    inflight = await r.zrange(SCHED_POLLS_INFLIGHT, 0, -1)
    assert b"opentable:99" not in inflight
    await r.aclose()


@pytest.mark.asyncio
async def test_claim_returns_none_when_empty(redis_url):
    r = redis.from_url(redis_url, decode_responses=False)
    sched = LuaScheduler(r)
    await sched.start()
    # Clear any leftover state
    await r.delete(SCHED_POLLS, SCHED_POLLS_INFLIGHT)
    now_ms = int(time.time() * 1000)
    job = await sched.claim(now_ms)
    assert job is None
    await r.aclose()


@pytest.mark.asyncio
async def test_drop_removes_a_malformed_job_without_re_enqueuing_it(redis_url):
    """WR-14: a job the poller cannot parse must leave the system, not loop forever.

    `continue`-ing past a malformed descriptor left it in `sched:polls:inflight` with a 60 s
    visibility score, so the reaper re-enqueued it into `sched:polls` at `now_ms`, it was
    claimed again immediately, warned about, and abandoned again — on every reaper cycle,
    with each pass also starving the queue of one claim slot.
    """
    r = redis.from_url(redis_url, decode_responses=False)
    sched = LuaScheduler(r)
    await sched.start()
    now_ms = int(time.time() * 1000)

    await r.delete(SCHED_POLLS, SCHED_POLLS_INFLIGHT)
    await r.zadd(SCHED_POLLS, {"garbage-no-colon": now_ms - 1000})

    assert await sched.claim(now_ms) == "garbage-no-colon"
    assert b"garbage-no-colon" in await r.zrange(SCHED_POLLS_INFLIGHT, 0, -1)

    assert await sched.drop("garbage-no-colon") is True

    assert await r.zrange(SCHED_POLLS_INFLIGHT, 0, -1) == []
    assert await r.zrange(SCHED_POLLS, 0, -1) == [], "drop must NOT re-enqueue"

    # The reaper has nothing left to resurrect, so the loop is genuinely broken.
    assert await sched.reap(now_ms + 120_000) == []
    assert await r.zrange(SCHED_POLLS, 0, -1) == []

    # Dropping something that is not there is a no-op, not an error.
    assert await sched.drop("garbage-no-colon") is False


@pytest.mark.asyncio
async def test_a_malformed_job_left_in_flight_is_resurrected_by_the_reaper(redis_url):
    """Pins the behaviour that made the leak permanent, so the fix cannot be reverted quietly."""
    r = redis.from_url(redis_url, decode_responses=False)
    sched = LuaScheduler(r)
    await sched.start()
    now_ms = int(time.time() * 1000)

    await r.delete(SCHED_POLLS, SCHED_POLLS_INFLIGHT)
    await r.zadd(SCHED_POLLS, {"garbage-no-colon": now_ms - 1000})
    await sched.claim(now_ms)

    # No drop: the reaper puts it straight back on the ready queue, forever.
    assert await sched.reap(now_ms + 120_000) == ["garbage-no-colon"]
    assert b"garbage-no-colon" in await r.zrange(SCHED_POLLS, 0, -1)

    await r.delete(SCHED_POLLS, SCHED_POLLS_INFLIGHT)
