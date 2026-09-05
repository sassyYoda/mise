"""Integration: POLL-05 — one Resy job's whole scheduling decision against a live Redis 7.2.

The tracer for plan 03-02. It drives the complete pre-dispatch decision end to end —
`watch:count` -> tier -> effective interval -> jittered ZSET score -> minute budget ->
per-context floor — against the module-scoped container, because every property that
matters here is a property of Redis's atomicity, not of Python's arithmetic:

* **boundary** — the budget grants when `current + cost == cap` and refuses at `cap + 1`,
  and a refusal consumes NONE of the budget (D-65).
* **adjacency** — two claims that touch exactly (the same `(context_id, venue_id)`, or a
  request landing exactly on the cap) resolve to exactly one winner. `SET NX EX` returns
  `None`, not `False`, for the loser, which is why `set_nx_ex` compares `result is True`.
* **precision** — `epoch_minute` is `now_ms // 60_000` (integer division), the jitter band
  is +/- 15 % and never nets negative, and the TTL is the integer 90.
* **concurrency** — 30 concurrent calls at cost 3 against cap 80 grant exactly 26 and
  refuse 4, and the counter carries a TTL after the FIRST increment. A bare `INCR` with a
  separate `EXPIRE` would leave `ttl == -1` — a permanent key under `noeviction`.

The 80 req/min cap and the 45 s floor are promises the public README makes to a third
party. This file is the evidence that they hold under concurrency rather than in prose.
"""
import asyncio
import time

import pytest
import redis.asyncio as redis

from shared.redis_keys import (
    RESY_BUDGET_LUA,
    RESY_CTX_FLOOR_SECONDS,
    RESY_GLOBAL_RPM_DEFAULT,
    RESY_RATE_TTL_SECONDS,
    TIER_OVERRIDE_HASH,
    WATCH_COUNT_HASH,
    effective_interval_seconds,
    hget_field,
    jittered_score_ms,
    rate_ctx_venue_key,
    rate_minute_key,
    set_nx_ex,
    tier_override_field,
    watch_count_field,
)

pytestmark = pytest.mark.integration

SOURCE = "resy"
VENUE_ID = 4242
CONTEXT_ID = "ctx-0"
COST = 3


async def _fresh(redis_url, minute):
    """Return a client and the budget SHA over a clean Phase-3 keyspace."""
    r = redis.from_url(redis_url, decode_responses=False)
    await r.delete(
        rate_minute_key(minute),
        rate_ctx_venue_key(CONTEXT_ID, VENUE_ID),
        WATCH_COUNT_HASH,
        TIER_OVERRIDE_HASH,
    )
    sha = await r.script_load(RESY_BUDGET_LUA)
    return r, sha


async def _budget(r, sha, minute, cost, cap=RESY_GLOBAL_RPM_DEFAULT):
    """Run RESY_BUDGET_LUA once, returning (granted, count_after, remaining) as ints."""
    granted, count_after, remaining = await r.evalsha(
        sha, 1, rate_minute_key(minute), str(cost), str(cap), str(RESY_RATE_TTL_SECONDS)
    )
    return int(granted), int(count_after), int(remaining)


def _minute(now_ms: int) -> int:
    """The rate key's bucket: integer division, never a formatted timestamp."""
    return now_ms // 60_000


# --------------------------------------------------------------------------------------
# The tracer itself
# --------------------------------------------------------------------------------------


async def test_one_resy_job_decides_its_next_poll_end_to_end(redis_url):
    """watch:count -> tier -> interval -> jitter -> budget -> floor, in one pass."""
    now_ms = int(time.time() * 1000)
    minute = _minute(now_ms)
    r, sha = await _fresh(redis_url, minute)

    # Phase 5 writes these; this phase only reads them.
    await r.hset(WATCH_COUNT_HASH, watch_count_field(SOURCE, VENUE_ID), "12")

    raw_watches = await hget_field(r, WATCH_COUNT_HASH, watch_count_field(SOURCE, VENUE_ID))
    raw_override = await hget_field(r, TIER_OVERRIDE_HASH, tier_override_field(SOURCE, VENUE_ID))
    assert raw_watches == b"12"
    assert raw_override is None, "no override written, so the computed tier must be used"

    interval = effective_interval_seconds(SOURCE, int(raw_watches), override=None)
    assert interval == 60, "12 watches is tier 1, and 60 s clears Resy's 45 s floor"

    score = jittered_score_ms(now_ms, interval)
    assert now_ms + 51_000 <= score <= now_ms + 69_000  # 60 s +/- 15 %
    assert score > now_ms, "a jittered score may never schedule a poll in the past"

    granted, count_after, remaining = await _budget(r, sha, minute, COST)
    assert (granted, count_after, remaining) == (1, COST, RESY_GLOBAL_RPM_DEFAULT - COST)

    assert await set_nx_ex(
        r, rate_ctx_venue_key(CONTEXT_ID, VENUE_ID), "1", RESY_CTX_FLOOR_SECONDS
    ) is True

    await r.aclose()


async def test_an_admin_override_wins_over_the_watch_count(redis_url):
    """`tier:override` = 3 slows a 12-watch restaurant to 180 s (Resy's baseline clamp)."""
    now_ms = int(time.time() * 1000)
    r, sha = await _fresh(redis_url, _minute(now_ms))
    await r.hset(WATCH_COUNT_HASH, watch_count_field(SOURCE, VENUE_ID), "12")
    await r.hset(TIER_OVERRIDE_HASH, tier_override_field(SOURCE, VENUE_ID), "3")

    raw_watches = await hget_field(r, WATCH_COUNT_HASH, watch_count_field(SOURCE, VENUE_ID))
    raw_override = await hget_field(r, TIER_OVERRIDE_HASH, tier_override_field(SOURCE, VENUE_ID))

    interval = effective_interval_seconds(
        SOURCE, int(raw_watches), override=int(raw_override)
    )
    # Tier 3 is 600 s but Resy's baseline is 180 s, and min(tier, baseline) wins.
    assert interval == 180
    await r.aclose()


# --------------------------------------------------------------------------------------
# PROBE POLL-05/boundary
# --------------------------------------------------------------------------------------


async def test_the_budget_grants_when_current_plus_cost_equals_the_cap_exactly(redis_url):
    """cap 80, current 77, cost 3 -> the last grant of the minute, landing exactly on 80."""
    now_ms = int(time.time() * 1000)
    minute = _minute(now_ms)
    r, sha = await _fresh(redis_url, minute)
    await r.set(rate_minute_key(minute), "77", ex=RESY_RATE_TTL_SECONDS)

    granted, count_after, remaining = await _budget(r, sha, minute, COST)

    assert granted == 1
    assert count_after == RESY_GLOBAL_RPM_DEFAULT
    assert remaining == 0
    await r.aclose()


async def test_the_budget_refuses_at_cap_plus_one_and_consumes_nothing(redis_url):
    """cap 80, current 78, cost 3 would reach 81 — refused, and 78 is left untouched."""
    now_ms = int(time.time() * 1000)
    minute = _minute(now_ms)
    r, sha = await _fresh(redis_url, minute)
    await r.set(rate_minute_key(minute), "78", ex=RESY_RATE_TTL_SECONDS)

    granted, count_after, remaining = await _budget(r, sha, minute, COST)

    assert granted == 0
    assert count_after == 78, "a refusal reports the CURRENT count, not a speculative one"
    assert remaining == 2, "the refusal is conservative: 2 requests of headroom go unused"
    assert int(await r.get(rate_minute_key(minute))) == 78, "a refusal consumes no budget"
    await r.aclose()


async def test_a_cost_of_one_still_fits_where_a_cost_of_three_did_not(redis_url):
    """The refusal is about THIS poll's cost, not a blanket close of the minute."""
    now_ms = int(time.time() * 1000)
    minute = _minute(now_ms)
    r, sha = await _fresh(redis_url, minute)
    await r.set(rate_minute_key(minute), "78", ex=RESY_RATE_TTL_SECONDS)

    assert (await _budget(r, sha, minute, 3))[0] == 0
    granted, count_after, remaining = await _budget(r, sha, minute, 1)

    assert (granted, count_after, remaining) == (1, 79, 1)
    await r.aclose()


# --------------------------------------------------------------------------------------
# PROBE POLL-05/precision — the TTL, and the epoch-minute arithmetic
# --------------------------------------------------------------------------------------


async def test_the_ttl_is_set_on_the_first_increment_only(redis_url):
    """90 s after the first INCRBY; the second must NOT slide the window past its minute."""
    now_ms = int(time.time() * 1000)
    minute = _minute(now_ms)
    r, sha = await _fresh(redis_url, minute)

    await _budget(r, sha, minute, COST)
    first_ttl = await r.ttl(rate_minute_key(minute))
    assert first_ttl == RESY_RATE_TTL_SECONDS, "a bare INCR would leave ttl == -1 forever"

    await r.expire(rate_minute_key(minute), 30)  # simulate 60 s of the window elapsing
    await _budget(r, sha, minute, COST)

    assert await r.ttl(rate_minute_key(minute)) == 30, (
        "the EXPIRE fires only when new == cost; re-setting it every call would make one "
        "busy minute's counter immortal"
    )
    await r.aclose()


async def test_the_epoch_minute_is_integer_division_of_now_ms(redis_url):
    """Two callers a millisecond apart inside one wall minute share one counter key."""
    now_ms = int(time.time() * 1000)
    base_minute_ms = (now_ms // 60_000) * 60_000
    minute = _minute(base_minute_ms)
    r, sha = await _fresh(redis_url, minute)

    assert _minute(base_minute_ms) == _minute(base_minute_ms + 59_999)
    assert _minute(base_minute_ms + 60_000) == minute + 1

    await _budget(r, sha, _minute(base_minute_ms), COST)
    await _budget(r, sha, _minute(base_minute_ms + 59_999), COST)

    assert int(await r.get(rate_minute_key(minute))) == 2 * COST
    await r.delete(rate_minute_key(minute))
    await r.aclose()


# --------------------------------------------------------------------------------------
# PROBE POLL-05/adjacency — the per-context floor
# --------------------------------------------------------------------------------------


async def test_the_context_floor_grants_once_and_then_returns_falsy(redis_url):
    """`SET NX EX 45` returns None (not False) for the loser — `set_nx_ex` maps it to False."""
    now_ms = int(time.time() * 1000)
    r, _ = await _fresh(redis_url, _minute(now_ms))
    key = rate_ctx_venue_key(CONTEXT_ID, VENUE_ID)

    assert await set_nx_ex(r, key, "1", RESY_CTX_FLOOR_SECONDS) is True
    raw_second = await r.set(key, "1", nx=True, ex=RESY_CTX_FLOOR_SECONDS)
    assert raw_second is None, "redis-py returns None, not False; `result is True` is why"
    assert await set_nx_ex(r, key, "1", RESY_CTX_FLOOR_SECONDS) is False
    await r.aclose()


async def test_the_context_floor_ttl_does_not_slide(redis_url):
    """A refused claim leaves the original expiry alone — the floor is spacing, not a lease."""
    now_ms = int(time.time() * 1000)
    r, _ = await _fresh(redis_url, _minute(now_ms))
    key = rate_ctx_venue_key(CONTEXT_ID, VENUE_ID)

    await set_nx_ex(r, key, "1", RESY_CTX_FLOOR_SECONDS)
    await r.expire(key, 20)  # simulate 25 s of the floor elapsing
    await set_nx_ex(r, key, "1", RESY_CTX_FLOOR_SECONDS)

    assert await r.ttl(key) == 20, "a sliding floor would starve a busy venue forever"
    await r.aclose()


async def test_two_simultaneous_claims_on_one_context_venue_pair_yield_one_winner(redis_url):
    """Neither both-succeed nor both-fail: exactly one of eight concurrent claims wins."""
    now_ms = int(time.time() * 1000)
    r, _ = await _fresh(redis_url, _minute(now_ms))
    key = rate_ctx_venue_key(CONTEXT_ID, VENUE_ID)

    results = await asyncio.gather(
        *(set_nx_ex(r, key, "1", RESY_CTX_FLOOR_SECONDS) for _ in range(8))
    )

    assert sum(results) == 1, f"expected exactly one winner, got {results}"
    await r.delete(key)
    await r.aclose()


# --------------------------------------------------------------------------------------
# PROBE POLL-05/concurrency
# --------------------------------------------------------------------------------------


async def test_thirty_concurrent_polls_at_cost_three_grant_exactly_twenty_six(redis_url):
    """80 / 3 = 26.67 -> 26 grants (78 consumed) and 4 refusals. Never 27, never 81."""
    now_ms = int(time.time() * 1000)
    minute = _minute(now_ms)
    r, sha = await _fresh(redis_url, minute)

    outcomes = await asyncio.gather(*(_budget(r, sha, minute, COST) for _ in range(30)))

    granted = [o for o in outcomes if o[0] == 1]
    refused = [o for o in outcomes if o[0] == 0]
    assert len(granted) == 26
    assert len(refused) == 4
    assert int(await r.get(rate_minute_key(minute))) == 78
    assert all(o == (0, 78, 2) for o in refused)
    assert await r.ttl(rate_minute_key(minute)) == RESY_RATE_TTL_SECONDS
    await r.aclose()


async def test_the_counter_never_exceeds_the_cap_under_concurrency(redis_url):
    """The invariant the README promises: the minute counter is never > 80, ever."""
    now_ms = int(time.time() * 1000)
    minute = _minute(now_ms)
    r, sha = await _fresh(redis_url, minute)

    for _ in range(3):
        await asyncio.gather(*(_budget(r, sha, minute, COST) for _ in range(15)))
        assert int(await r.get(rate_minute_key(minute))) <= RESY_GLOBAL_RPM_DEFAULT

    await r.aclose()
