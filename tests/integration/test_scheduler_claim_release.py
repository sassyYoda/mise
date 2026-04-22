"""Integration: POLL-01 — Lua ZSET scheduler claim/release/reap. Stub filled by Plan 04."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 04 (shared kernel Lua scripts)")
async def test_claim_release_cycle(redis_container):
    """
    Load Lua scripts via script_load.
    ZADD sched:polls with score = now_ms - 1 (due immediately).
    Call CLAIM_POLL_LUA: assert returns 'opentable:42', job moved to inflight.
    Call RELEASE_POLL_LUA with next_score = now_ms + 90000.
    Assert sched:polls has the job back with the new score.
    Assert sched:polls:inflight is empty.
    """
    raise NotImplementedError


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 04 (shared kernel Lua scripts)")
async def test_reaper_requeues_expired_inflight(redis_container):
    """
    ZADD sched:polls:inflight with score = now_ms - 1 (expired).
    Call REAP_INFLIGHT_LUA with now_ms.
    Assert the job is back in sched:polls.
    Assert sched:polls:inflight is empty.
    """
    raise NotImplementedError
