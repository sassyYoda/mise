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
