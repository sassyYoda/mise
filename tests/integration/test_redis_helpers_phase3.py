"""Integration: the Phase-3 typed Redis helpers, exercised against a live Redis 7.2.

Beyond the plan's named artifacts (see 03-02-SUMMARY.md, Deviations / Rule 2).

`shared/redis_keys.py` gained nine helpers in this plan and only `hget_field` was reachable
from the rate-budget tracer. The other eight would have shipped with zero executions — and
these are precisely the wrappers where a mistake is invisible to `mypy`: a `cast(Awaitable[T],
…)` asserts a return type to the type checker without checking it, so a wrong `T`, a
transposed argument or an `LTRIM 0, size` off-by-one all type-check cleanly and fail only in
production. `canary_window_push` is the sharpest case: its whole purpose is that four
commands land as ONE transaction, which is not a property any unit test can observe.

Phases 3-05 (canary), 03-06 (poller gate) and 04 build directly on these.
"""
import pytest
import redis.asyncio as redis

from shared.redis_keys import (
    BACKOFF_MAX_SECONDS,
    CANARY_TTL_SECONDS,
    CANARY_WINDOW_SIZE,
    RESY_PAUSE_TTL_SECONDS,
    RESY_PAUSED_KEY,
    TIER_OVERRIDE_HASH,
    WATCH_COUNT_HASH,
    backoff_key,
    backoff_ttl_seconds,
    canary_key,
    canary_window_push,
    delete_key,
    getdel_str,
    hget_field,
    incrby,
    lpush_sig,
    lrange_window,
    ltrim_window,
    next_backoff_seconds,
    set_str_ex,
    tier_override_field,
    watch_count_field,
)

pytestmark = pytest.mark.integration

VENUE_ID = 7007
SOURCE = "resy"


async def _client(redis_url):
    r = redis.from_url(redis_url, decode_responses=False)
    await r.delete(
        canary_key(VENUE_ID),
        backoff_key(SOURCE, VENUE_ID),
        RESY_PAUSED_KEY,
        WATCH_COUNT_HASH,
        TIER_OVERRIDE_HASH,
        "helpers:scratch",
    )
    return r


# --------------------------------------------------------------------------------------
# The canary window — one MULTI/EXEC (D-67)
# --------------------------------------------------------------------------------------


async def test_the_canary_window_never_grows_past_its_configured_size(redis_url):
    """25 pushes into a 20-entry window leave exactly 20 — the LTRIM bound is inclusive."""
    r = await _client(redis_url)
    key = canary_key(VENUE_ID)

    for i in range(25):
        window = await canary_window_push(
            r, key, f"200|{i}|1|1|1", CANARY_WINDOW_SIZE, CANARY_TTL_SECONDS
        )

    assert len(window) == CANARY_WINDOW_SIZE
    assert await r.llen(key) == CANARY_WINDOW_SIZE
    await r.delete(key)
    await r.aclose()


async def test_the_canary_window_returns_newest_first(redis_url):
    """LPUSH prepends, so index 0 is the signature just observed — the verdict depends on it."""
    r = await _client(redis_url)
    key = canary_key(VENUE_ID)

    await canary_window_push(r, key, "200|100|1|1|1", CANARY_WINDOW_SIZE, CANARY_TTL_SECONDS)
    window = await canary_window_push(
        r, key, "403|9|0|0|0", CANARY_WINDOW_SIZE, CANARY_TTL_SECONDS
    )

    assert window[0] == b"403|9|0|0|0", "the newest signature must be the head"
    assert window[1] == b"200|100|1|1|1"
    await r.delete(key)
    await r.aclose()


async def test_the_canary_window_carries_its_ttl_from_the_first_push(redis_url):
    """A window with no expiry is a permanent key under noeviction (T-03-07)."""
    r = await _client(redis_url)
    key = canary_key(VENUE_ID)

    await canary_window_push(r, key, "200|24|1|1|1", CANARY_WINDOW_SIZE, CANARY_TTL_SECONDS)

    assert await r.ttl(key) == CANARY_TTL_SECONDS
    await r.delete(key)
    await r.aclose()


async def test_a_concurrent_reader_never_sees_a_window_longer_than_the_bound(redis_url):
    """The LPUSH and the LTRIM are one transaction; a bare pair would expose a 21st entry."""
    r = await _client(redis_url)
    key = canary_key(VENUE_ID)

    for i in range(40):
        await canary_window_push(
            r, key, f"200|{i}|1|1|1", CANARY_WINDOW_SIZE, CANARY_TTL_SECONDS
        )
        assert await r.llen(key) <= CANARY_WINDOW_SIZE

    await r.delete(key)
    await r.aclose()


async def test_the_raw_list_helpers_agree_with_the_transactional_one(redis_url):
    """`lpush_sig` / `ltrim_window` / `lrange_window` compose to the same window."""
    r = await _client(redis_url)
    key = "helpers:scratch"

    for i in range(5):
        assert await lpush_sig(r, key, f"sig-{i}") == i + 1
    assert await ltrim_window(r, key, 2) is True
    window = await lrange_window(r, key)

    assert window == [b"sig-4", b"sig-3", b"sig-2"]
    assert await lrange_window(r, "helpers:absent") == []
    await r.delete(key)
    await r.aclose()


# --------------------------------------------------------------------------------------
# Backoff and fleet-pause state (D-59, D-65)
# --------------------------------------------------------------------------------------


async def test_a_backoff_key_round_trips_with_a_ttl_of_twice_its_value(redis_url):
    """The key must outlive the delay it holds, or the ladder silently restarts at 1x."""
    r = await _client(redis_url)
    key = backoff_key(SOURCE, VENUE_ID)
    backoff = next_backoff_seconds(180, 2)  # 720

    assert await set_str_ex(r, key, str(backoff), backoff_ttl_seconds(backoff)) is True

    assert int(await r.get(key)) == 720
    assert await r.ttl(key) == 1440
    await r.delete(key)
    await r.aclose()


async def test_set_str_ex_overwrites_and_slides_its_ttl(redis_url):
    """Unlike `set_nx_ex`, the newest backoff must win — the ladder only climbs by rewriting."""
    r = await _client(redis_url)
    key = backoff_key(SOURCE, VENUE_ID)

    await set_str_ex(r, key, "180", 360)
    await set_str_ex(r, key, str(BACKOFF_MAX_SECONDS), backoff_ttl_seconds(BACKOFF_MAX_SECONDS))

    assert int(await r.get(key)) == BACKOFF_MAX_SECONDS
    assert await r.ttl(key) == 3600
    await r.delete(key)
    await r.aclose()


async def test_delete_key_resets_the_backoff_and_is_idempotent(redis_url):
    """D-59 resets the ladder on the next successful poll; a double reset must not raise."""
    r = await _client(redis_url)
    key = backoff_key(SOURCE, VENUE_ID)
    await set_str_ex(r, key, "720", 1440)

    assert await delete_key(r, key) == 1
    assert await delete_key(r, key) == 0
    assert await r.get(key) is None
    await r.aclose()


async def test_the_fleet_pause_flag_expires_on_its_own(redis_url):
    """15 minutes, self-lifting: a pause that needs a manual DEL is a pause somebody forgets."""
    r = await _client(redis_url)

    await set_str_ex(r, RESY_PAUSED_KEY, "1", RESY_PAUSE_TTL_SECONDS)

    assert await r.ttl(RESY_PAUSED_KEY) == 900
    await r.delete(RESY_PAUSED_KEY)
    await r.aclose()


# --------------------------------------------------------------------------------------
# Counters and one-shot reads
# --------------------------------------------------------------------------------------


async def test_incrby_returns_the_value_after_the_increment(redis_url):
    r = await _client(redis_url)
    key = "helpers:scratch"

    assert await incrby(r, key, 3) == 3
    assert await incrby(r, key, 5) == 8
    assert await incrby(r, key, -8) == 0
    await r.delete(key)
    await r.aclose()


async def test_getdel_str_reads_and_removes_in_one_command(redis_url):
    """The consume-exactly-once primitive: a second read must return None, not the value."""
    r = await _client(redis_url)
    key = "helpers:scratch"
    await set_str_ex(r, key, "payload", 60)

    assert await getdel_str(r, key) == b"payload"
    assert await getdel_str(r, key) is None
    await r.aclose()


async def test_hget_field_reads_both_phase_five_hashes_and_tolerates_absence(redis_url):
    """A missing field returns None — this phase READS what Phase 5 has not yet written."""
    r = await _client(redis_url)
    await r.hset(WATCH_COUNT_HASH, watch_count_field(SOURCE, VENUE_ID), "12")

    assert await hget_field(r, WATCH_COUNT_HASH, watch_count_field(SOURCE, VENUE_ID)) == b"12"
    assert (
        await hget_field(r, TIER_OVERRIDE_HASH, tier_override_field(SOURCE, VENUE_ID)) is None
    )
    assert await hget_field(r, WATCH_COUNT_HASH, watch_count_field("opentable", 1)) is None
    await r.delete(WATCH_COUNT_HASH)
    await r.aclose()
