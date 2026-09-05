"""
Single source of truth for ALL Redis key patterns and TTLs (D-18).
Any Redis access in services/ MUST import from here.
Named symbols: SCHED_POLLS, SCHED_POLLS_INFLIGHT, sched_expedite_key,
               CONFIRM_DELAY_MS, EXPEDITE_FLAG_TTL_SECONDS, EXPEDITE_POLL_LUA,
               avail_state_key, avail_meta_key, event_idempotency_key,
               AVAIL_STATE_TTL_SECONDS, EVENT_IDEMPOTENCY_TTL_SECONDS,
               hgetall_slots, hset_slot_with_ttl, hdel_slot_with_ttl, hset_meta_with_ttl,
               rate_minute_key, rate_ctx_venue_key, canary_key, backoff_key,
               RESY_PAUSED_KEY, WATCH_COUNT_HASH, TIER_OVERRIDE_HASH,
               watch_count_field, tier_override_field,
               RESY_RATE_TTL_SECONDS, RESY_CTX_FLOOR_SECONDS, RESY_PAUSE_TTL_SECONDS,
               CANARY_WINDOW_SIZE, CANARY_TTL_SECONDS,
               RESY_BASELINE_INTERVAL_SECONDS_DEFAULT, RESY_MIN_INTERVAL_SECONDS,
               RESY_GLOBAL_RPM_DEFAULT, BACKOFF_MAX_SECONDS,
               RATE_REFUSAL_RETRY_MS, FLEET_PAUSE_RETRY_MS, TIER_INTERVALS_SECONDS,
               tier_interval_seconds, effective_interval_seconds, jittered_score_ms,
               next_backoff_seconds, backoff_ttl_seconds, RESY_BUDGET_LUA,
               incrby, getdel_str, hget_field, lpush_sig, ltrim_window, lrange_window,
               set_str_ex, delete_key, canary_window_push
"""
from __future__ import annotations

import random
from collections.abc import Awaitable, Mapping
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

if TYPE_CHECKING:
    from redis.asyncio import Redis

# -- Scheduler ZSETs --
SCHED_POLLS = "sched:polls"              # score = next_poll_epoch_ms
SCHED_POLLS_INFLIGHT = "sched:polls:inflight"  # score = now_ms + visibility_ms

# -- Timing constants --
POLL_VISIBILITY_TIMEOUT_MS: int = 60_000   # 60s (D-18)
POLL_INTERVAL_SECONDS: int = 90            # D-17
POLL_JITTER_FRACTION: float = 0.15        # D-17 (±15%)
REAPER_INTERVAL_SECONDS: int = 10         # Claude discretion (D-18 range: 5-15s)


def job(source: str, restaurant_id: int) -> str:
    """Return canonical job descriptor '{source}:{restaurant_id}' (D-18, D-29)."""
    return f"{source}:{restaurant_id}"


async def set_nx_ex(r: Redis, key: str, value: str, ttl_seconds: int) -> bool:
    """
    Atomic SETNX+EX in a single Redis call (Pitfall 7).
    NEVER use two-command SETNX + EXPIRE.
    Returns True if key was set (did not exist), False if it already existed.
    """
    result = await r.set(key, value, nx=True, ex=ttl_seconds)
    return result is True


# -- Availability state (D-40, D-42, STATE-01) --
# TTL is KEY-level, not per-field: per-field hash TTL (HEXPIRE) is a Redis 7.4
# SERVER feature and the pinned server is redis:7.2-alpine, which answers
# "ERR unknown command 'HEXPIRE'". The key TTL must therefore be refreshed on
# every write (D-40, research Pitfall 6).
AVAIL_STATE_TTL_SECONDS: int = 90_000        # 25 h — one full service day plus slack
EVENT_IDEMPOTENCY_TTL_SECONDS: int = 1_200   # 20 min — Layer-1 duplicate suppression (D-46)


def avail_state_key(restaurant_id: int, date: str, party_size: int) -> str:
    """Return the HASH key holding known slot records for one (rid, date, party) (D-40)."""
    return f"avail:{restaurant_id}:{date}:{party_size}"


def avail_meta_key(restaurant_id: int) -> str:
    """Return the HASH key holding per-restaurant state-machine metadata (D-40)."""
    return f"avail:{restaurant_id}:meta"


def event_idempotency_key(
    restaurant_id: int, date: str, party_size: int, slot_key: str, token: str
) -> str:
    """
    Return the SET NX EX claim key for one emitted event (D-46 as amended, STATE-04).

    `slot_key` is MANDATORY and is what makes the claim unique per slot identity. D-36 puts
    `seat_type` inside slot identity while `booking_token` is only data, and OpenTable fans one
    timeslot out into one slot per seating type carrying the SAME token — so a claim keyed on
    `(rid, date, party, token)` alone collapses two distinct slots onto one key and silently
    drops the second confirmed opening. The token stays in the key (it distinguishes a rotated
    token within one slot cycle) but it can no longer be the only discriminator.

    Every component is percent-escaped, so the key is INJECTIVE (WR-04). `slot_key` is
    `f"{time_slot}|{seat_type or '-'}"` and both halves, like `token`, come straight from the
    payload — `parsers/opentable.py` only checks `isinstance(..., str)`. A plain join on `:`
    is therefore ambiguous whenever a value contains the separator, which a time slot always
    does: `slot_key="19:00|bar", token="a:b"` and `slot_key="19:00|bar:a", token="b"` both
    rendered `event:42:D:2:19:00|bar:a:b`. That is the same class of silent identity collapse
    the seat-type fix removed, arriving by a different route. `quote(..., safe="")` escapes
    `:` (and `%` itself), so the components can be recovered unambiguously and two distinct
    tuples can never render one key.

    The claim key is ephemeral (20 min TTL) and appears in no golden, so re-shaping it is
    free. `shared.events.make_event_id` has the identical concatenation and the identical
    argument, but its output is a PERMANENT uuid5 recorded in every committed golden and in
    the availability_events rows, so it is deliberately left alone; the constraint is
    recorded there in a comment.
    """
    parts = (str(restaurant_id), date, str(party_size), slot_key, token)
    return "event:" + ":".join(quote(part, safe="") for part in parts)


# -- Typed HASH helpers (D-42, research Pitfall 3) --
# redis-py types command methods as `Union[Awaitable[T], T]`, which `mypy --strict`
# refuses to `await` when T is concrete. Every cast lives here, exactly once, so
# services/state_machine/store.py contains none. Never suppress these awaits with a
# blanket type-suppression comment — that would hide real signature drift on a
# future redis-py bump.


async def hgetall_slots(r: Redis, key: str) -> dict[bytes, bytes]:
    """HGETALL every slot record under ``key``. Returns {} when the key is absent."""
    return await cast(Awaitable[dict[bytes, bytes]], r.hgetall(key))


# `hset_slot`, `hdel_slot`, `hset_meta` and `expire_key` used to live here. They were the
# bare mutations, and after WR-10 moved every caller onto the `_with_ttl` transactions below
# they had zero callers anywhere — while remaining a two-line route straight back to the
# defect those transactions exist to prevent (mutate now, EXPIRE later, and a key created
# with no TTL if anything interrupts the pair). `test_no_setnx_expire_pairs.py` only greps
# for `.setnx(`, so it would not have caught the reintroduction. They are deleted rather than
# deprecated, and `tests/unit/test_redis_keys_phase2.py` asserts they stay gone.


# -- Atomic mutate-and-refresh helpers (Pitfall 7) --
# A mutation followed by a SEPARATE EXPIRE is the same non-atomic shape this repo bans for
# SETNX+EXPIRE, just spelled differently: if the process dies (or the connection drops) between
# the two commands while the key is being CREATED, the hash is left with no TTL and never
# expires — a permanently stale slot record that suppresses real events. Every mutating call in
# services/state_machine/store.py goes through one of these, which issue both commands in a
# single MULTI/EXEC round trip. That also halves the round trips on the hot path.


async def hset_slot_with_ttl(
    r: Redis, key: str, field: str, value: str, ttl_seconds: int
) -> None:
    """HSET one slot record and refresh the key TTL in a single transaction."""
    async with r.pipeline(transaction=True) as pipe:
        pipe.hset(key, field, value)
        pipe.expire(key, ttl_seconds)
        await pipe.execute()


async def hdel_slot_with_ttl(r: Redis, key: str, field: str, ttl_seconds: int) -> None:
    """
    HDEL one slot record and refresh the key TTL in a single transaction.

    Removing the last field deletes the key naturally; an EXPIRE against an absent key is a
    no-op returning 0, so that case needs no special handling.
    """
    async with r.pipeline(transaction=True) as pipe:
        pipe.hdel(key, field)
        pipe.expire(key, ttl_seconds)
        await pipe.execute()


async def hset_meta_with_ttl(
    r: Redis, key: str, mapping: Mapping[str, str], ttl_seconds: int
) -> None:
    """HSET a whole metadata mapping and refresh the key TTL in a single transaction."""
    async with r.pipeline(transaction=True) as pipe:
        pipe.hset(key, mapping=dict(mapping))
        pipe.expire(key, ttl_seconds)
        await pipe.execute()


# -- Confirmation expedite (D-43, STATE-03) --
CONFIRM_DELAY_MS: int = 8_000            # D-43: a PENDING slot re-verifies at t+8s
EXPEDITE_FLAG_TTL_SECONDS: int = 120     # D-43: the in-flight flag expires on its own


def sched_expedite_key(job: str) -> str:
    """Return the expedite-flag key 'sched:expedite:{job}' for an in-flight poll (D-43)."""
    return f"sched:expedite:{job}"


# -- Lua scripts (D-18) --
CLAIM_POLL_LUA = """
-- KEYS[1] = sched:polls
-- KEYS[2] = sched:polls:inflight
-- ARGV[1] = now_ms
-- ARGV[2] = visibility_timeout_ms
local ready = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 1)
if #ready == 0 then
  return nil
end
local job = ready[1]
redis.call('ZREM', KEYS[1], job)
redis.call('ZADD', KEYS[2], tonumber(ARGV[1]) + tonumber(ARGV[2]), job)
return job
"""

RELEASE_POLL_LUA = """
-- KEYS[1] = sched:polls:inflight
-- KEYS[2] = sched:polls
-- ARGV[1] = job descriptor
-- ARGV[2] = next_poll_epoch_ms
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('ZADD', KEYS[2], tonumber(ARGV[2]), ARGV[1])
"""

REAP_INFLIGHT_LUA = """
-- KEYS[1] = sched:polls:inflight
-- KEYS[2] = sched:polls
-- ARGV[1] = now_ms
-- Returns the list of jobs that were re-enqueued (for logging).
local expired = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
for _, job in ipairs(expired) do
  redis.call('ZREM', KEYS[1], job)
  redis.call('ZADD', KEYS[2], ARGV[1], job)
end
return expired
"""

EXPEDITE_POLL_LUA = """
-- KEYS[1] = sched:polls
-- KEYS[2] = sched:expedite:{source}:{restaurant_id}
-- ARGV[1] = now_ms
-- ARGV[2] = job descriptor '{source}:{restaurant_id}'
-- ARGV[3] = confirm_delay_ms (8000)
-- ARGV[4] = expedite flag TTL seconds (120)
-- Returns 'zset' if the queued job was pulled forward, 'flag' if the job is in flight.
-- 'XX' is mandatory: without it a ZADD would resurrect an in-flight job into the
-- ready set, producing a duplicate concurrent poll for that restaurant.
-- 'LT' is mandatory: without it an already-sooner poll would be pushed later.
-- Plain ZADD and 'GT' are both wrong here.
local target = tonumber(ARGV[1]) + tonumber(ARGV[3])
if redis.call('ZSCORE', KEYS[1], ARGV[2]) then
  redis.call('ZADD', KEYS[1], 'XX', 'LT', target, ARGV[2])
  return 'zset'
else
  redis.call('SET', KEYS[2], '1', 'EX', tonumber(ARGV[4]))
  return 'flag'
end
"""


# ============================================================================
# Phase 3 — Resy fleet: rate budget, tier cadence, backoff, canary (D-57..D-65)
# ============================================================================
#
# Every key below carries an explicit TTL constant. The pinned server runs
# `maxmemory-policy noeviction` (tests/conftest.py sets it on the container to match
# ops), so a key written without an expiry is PERMANENT — there is no LRU sweep to
# save us. A per-minute rate counter or a per-context floor leaked once per poll adds
# a key per minute per (context, venue) forever, which is a slow denial of service
# against our own Redis (T-03-07).

# -- Global minute budget (POLL-05, D-65) --
RESY_RATE_TTL_SECONDS: int = 90       # > 60 s so a counter always outlives its own minute
RESY_GLOBAL_RPM_DEFAULT: int = 80     # the cap the public README commits to


def rate_minute_key(epoch_minute: int) -> str:
    """
    Return the minute-bucket counter key 'rate:resy:{epoch_minute}' (D-65, POLL-05).

    ``epoch_minute`` is ``now_ms // 60_000`` — integer division, never a float and never a
    formatted timestamp, so two callers a millisecond apart inside the same wall minute
    always land on the same key.
    """
    return f"rate:resy:{epoch_minute}"


# -- Per-restaurant per-context floor (POLL-05, D-65) --
RESY_CTX_FLOOR_SECONDS: int = 45      # >= 45 s between requests to one venue from one context


def rate_ctx_venue_key(context_id: str, venue_id: int) -> str:
    """
    Return the floor claim key 'rate:resy:ctx:{context_id}:{venue_id}' (D-65, POLL-05).

    Claimed with ``set_nx_ex(..., RESY_CTX_FLOOR_SECONDS)``. The claim is deliberately NOT
    refreshed on a hit: a sliding window would let a busy venue starve forever, and the
    floor is a minimum spacing, not a lease.
    """
    return f"rate:resy:ctx:{context_id}:{venue_id}"


# -- Soft-ban canary window (POLL-06, D-67) --
CANARY_WINDOW_SIZE: int = 20          # rolling baseline length (LPUSH + LTRIM 0..19)
CANARY_TTL_SECONDS: int = 3_600       # a stale baseline is worse than no baseline


def canary_key(venue_id: int) -> str:
    """Return the rolling response-signature LIST key 'canary:resy:{venue_id}' (D-67)."""
    return f"canary:resy:{venue_id}"


# -- Exponential backoff on 429/503/ban (POLL-02, D-59) --
BACKOFF_MAX_SECONDS: int = 1_800      # 30 min ceiling


def backoff_key(source: str, restaurant_id: int) -> str:
    """
    Return the backoff state key 'backoff:{source}:{restaurant_id}' (D-59).

    Holds the CURRENT backoff in seconds with a TTL of twice that value
    (``backoff_ttl_seconds``), so the key outlives the delay it describes but self-heals
    if the reset-on-success DEL is ever missed.
    """
    return f"backoff:{source}:{restaurant_id}"


# -- Fleet-wide pause (D-65) --
RESY_PAUSED_KEY = "resy:paused"       # presence = the whole Resy fleet is paused
RESY_PAUSE_TTL_SECONDS: int = 900     # 15 min — the pause lifts itself; no manual DEL required
FLEET_PAUSE_RETRY_MS: int = 60_000    # release a job this far out while the fleet is paused
RATE_REFUSAL_RETRY_MS: int = 5_000    # release a job this far out when the minute budget refuses

# -- Watch counts and admin tier override (D-58) --
# Both HASHes are WRITTEN by Phase 5 and only READ here. They are therefore untrusted input
# from this module's point of view: a missing field, a non-integer value or a negative count
# must degrade to the slowest tier, never raise inside poll_loop (T-03-09).
WATCH_COUNT_HASH = "watch:count"      # field '{source}:{restaurant_id}' -> active watch count
TIER_OVERRIDE_HASH = "tier:override"  # field '{source}:{restaurant_id}' -> 1 | 2 | 3


def watch_count_field(source: str, restaurant_id: int) -> str:
    """Return the `watch:count` HASH field '{source}:{restaurant_id}' (D-58)."""
    return f"{source}:{restaurant_id}"


def tier_override_field(source: str, restaurant_id: int) -> str:
    """Return the `tier:override` HASH field '{source}:{restaurant_id}' (D-58)."""
    return f"{source}:{restaurant_id}"


# -- Tier cadence arithmetic (POLL-02, D-57) --
# Pure functions: no clock, no IO, no entropy except the explicitly-seedable jitter draw.
# The tier result reaches production ONLY as a ZSET score through the poller's release path
# (`_next_poll_score`) — never as an `asyncio.sleep`, which would burn a worker slot.

RESY_BASELINE_INTERVAL_SECONDS_DEFAULT: int = 180  # RESY_BASELINE_INTERVAL_SECONDS default
RESY_MIN_INTERVAL_SECONDS: int = 45                # POLL-05 per-restaurant floor

# The literal POLL-02 tiers, keyed by the admin override value that selects each one (D-58).
TIER_INTERVALS_SECONDS: dict[int, int] = {1: 60, 2: 180, 3: 600}

# (baseline_seconds, minimum_seconds) per source.
# OpenTable's minimum EQUALS its baseline on purpose: POLL-03 fixes the heatmap collection
# cadence at 90 s, and watches may only speed a source up, never slow it down. An unknown
# source — which the `AvailabilityRaw.source` Literal makes unreachable today — degrades to
# the slowest baseline and the strictest known floor rather than raising in the poll loop.
_SOURCE_BASELINES: dict[str, tuple[int, int]] = {
    "opentable": (POLL_INTERVAL_SECONDS, POLL_INTERVAL_SECONDS),
    "resy": (RESY_BASELINE_INTERVAL_SECONDS_DEFAULT, RESY_MIN_INTERVAL_SECONDS),
}
_UNKNOWN_SOURCE_BASELINE = (RESY_BASELINE_INTERVAL_SECONDS_DEFAULT, POLL_INTERVAL_SECONDS)


def tier_interval_seconds(active_watches: int) -> int:
    """
    Return the POLL-02 tier interval for ``active_watches``: 60 / 180 / 600 seconds (D-57).

    Tier 1 (60 s) at >= 10 watches, tier 2 (180 s) at 3-9, tier 3 (600 s) at 0-2. A negative
    count is treated as 0 rather than raising: `watch:count` is written by Phase 5 and read
    here, and a poller that crashes on a bad hash value is a worse failure than one that
    polls a restaurant slowly (T-03-09).
    """
    watches = max(0, active_watches)
    if watches >= 10:
        return TIER_INTERVALS_SECONDS[1]
    if watches >= 3:
        return TIER_INTERVALS_SECONDS[2]
    return TIER_INTERVALS_SECONDS[3]


def effective_interval_seconds(
    source: str,
    active_watches: int,
    override: int | None = None,
    baseline_seconds: int | None = None,
) -> int:
    """
    Return the poll interval for one job: ``min(tier, baseline)`` raised to the source floor.

    `min` and not `max`: watches may only speed polling UP. OpenTable's baseline and minimum
    are both ``POLL_INTERVAL_SECONDS`` (90 s), so ten watches on an OpenTable restaurant do
    not drag the heatmap's 90 s collection cadence down to 60 s (POLL-03). Resy's baseline
    defaults to 180 s and its floor is 45 s (POLL-05) — the floor is the promise, so it is
    applied LAST and a caller-supplied ``baseline_seconds`` below it is clamped back up.

    ``override`` is the admin `tier:override` value (1 | 2 | 3, D-58): it selects the tier
    directly and still passes through the per-source clamp — an override may not buy a rate
    the public README forbids. ``None`` and any out-of-range value fall back to the computed
    tier, because an operator typo must not silently pick tier 1.
    """
    tier = TIER_INTERVALS_SECONDS.get(override, tier_interval_seconds(active_watches)) \
        if override is not None else tier_interval_seconds(active_watches)
    baseline, minimum = _SOURCE_BASELINES.get(source, _UNKNOWN_SOURCE_BASELINE)
    if baseline_seconds is not None:
        baseline = baseline_seconds
    return max(min(tier, baseline), minimum)


def jittered_score_ms(now_ms: int, interval_seconds: int) -> int:
    """
    Return ``now_ms + interval_ms +/- POLL_JITTER_FRACTION`` as an integer ZSET score (D-57).

    Jitter is the single reason a fleet of pollers does not synchronise into a thundering
    herd on the same wall second. ``POLL_JITTER_FRACTION`` (0.15) is the ONE definition of
    the +/- 15 % POLL-02 requires; `services/poller/scheduler.py` derives its own constants
    from it too. With a 15 % band the result is always strictly greater than ``now_ms`` for
    any positive interval, so a jittered score can never schedule a poll in the past.
    """
    interval_ms = interval_seconds * 1_000
    jitter_ms = interval_ms * POLL_JITTER_FRACTION
    return now_ms + interval_ms + int(random.uniform(-jitter_ms, jitter_ms))


def next_backoff_seconds(interval_seconds: int, consecutive_failures: int) -> int:
    """
    Return ``min(interval * 2 ** consecutive_failures, BACKOFF_MAX_SECONDS)`` (D-59).

    ``consecutive_failures`` is 0 for the FIRST failure, so the first backoff equals the
    normal interval and the sequence doubles from there. The 1800 s ceiling stops a
    long-banned restaurant from drifting to a next-poll score days out, from which it would
    never recover on its own.
    """
    exponent = max(0, consecutive_failures)
    # Annotated because mypy types `int ** int` as `Any` (a negative exponent would yield a
    # float); the `max(0, ...)` above is what makes the integer result real rather than assumed.
    doubled: int = interval_seconds * 2**exponent
    return min(doubled, BACKOFF_MAX_SECONDS)


def backoff_ttl_seconds(backoff_seconds: int) -> int:
    """
    Return the TTL for a `backoff:*` key: twice the backoff it holds (D-59).

    The key must outlive the delay it describes — otherwise the failure counter resets while
    the job is still waiting and the next failure restarts the ladder at 1x. Twice is the
    smallest factor that survives the jitter band with room to spare.
    """
    return 2 * backoff_seconds


# -- The minute budget, as ONE Lua script (POLL-05, D-65) --
RESY_BUDGET_LUA = """
-- KEYS[1] = rate:resy:{epoch_minute}
-- ARGV[1] = cost (number of requests this poll will make)
-- ARGV[2] = cap  (RESY_GLOBAL_RPM)
-- ARGV[3] = ttl seconds (RESY_RATE_TTL_SECONDS)
-- Returns {granted(0|1), count_after, remaining}
--
-- This is the ONLY place the 80 req/min cap the public README promises is enforced. Every
-- Resy request in the fleet passes through it before dispatch; a caller that skips it
-- breaks a commitment made to a third party, not merely an internal budget.
--
-- The refusal is deliberately CONSERVATIVE: with cost 3 and cap 80 the counter stops at 78
-- and leaves 2 unused rather than overshooting to 81. Never round in our own favour against
-- somebody else's infrastructure.
--
-- A refusal consumes nothing: the GET-and-compare happens before the INCRBY, so a refused
-- poll can be released back into the queue at now + RATE_REFUSAL_RETRY_MS with the budget
-- untouched, and the next minute starts clean.
--
-- INCRBY and EXPIRE must be in ONE script. A bare `INCR` followed by a separate `EXPIRE`
-- from Python is two round trips and two race windows: if the process died between them the
-- counter would have NO TTL at all (verified: `ttl == -1`), and under `noeviction` that key
-- is permanent — it would refuse every Resy poll for the rest of the server's life.
-- The EXPIRE is set only when `new == cost`, i.e. on the FIRST increment of this minute;
-- re-setting it on every increment would slide the window past the minute it describes.
local cur  = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost = tonumber(ARGV[1])
local cap  = tonumber(ARGV[2])
if cur + cost > cap then
  return {0, cur, cap - cur}
end
local new = redis.call('INCRBY', KEYS[1], cost)
if new == cost then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
end
return {1, new, cap - new}
"""


# -- Typed async helpers for the Phase 3 commands (research Pitfall 3) --
# Same rule as the Phase 2 block above: redis-py types command methods as
# `Union[Awaitable[T], T]`, which `mypy --strict` refuses to `await`. Every cast lives HERE,
# exactly once, so `services/poller/sources/resy/*.py` contains none.


async def incrby(r: Redis, key: str, amount: int) -> int:
    """INCRBY ``key`` by ``amount``, returning the value after the increment."""
    return await cast(Awaitable[int], r.incrby(key, amount))


async def getdel_str(r: Redis, key: str) -> bytes | None:
    """GETDEL ``key`` — read and remove in one atomic command. None when absent."""
    return await cast(Awaitable[bytes | None], r.getdel(key))


async def hget_field(r: Redis, key: str, field: str) -> bytes | None:
    """HGET one field from a HASH. None when either the key or the field is absent."""
    return await cast(Awaitable[bytes | None], r.hget(key, field))


async def lpush_sig(r: Redis, key: str, sig: str) -> int:
    """LPUSH one signature onto a canary window, returning the new list length."""
    return await cast(Awaitable[int], r.lpush(key, sig))


async def ltrim_window(r: Redis, key: str, stop: int) -> bool:
    """LTRIM a canary window to indices 0..``stop`` inclusive."""
    return await cast(Awaitable[bool], r.ltrim(key, 0, stop))


async def lrange_window(r: Redis, key: str) -> list[bytes]:
    """LRANGE the whole canary window, newest first. Returns [] when the key is absent."""
    return await cast(Awaitable[list[bytes]], r.lrange(key, 0, -1))


async def set_str_ex(r: Redis, key: str, value: str, ttl_seconds: int) -> bool:
    """
    SET ``key`` to ``value`` with a TTL in a single command (never SET then EXPIRE).

    Unlike ``set_nx_ex`` this OVERWRITES an existing key — it is the fleet-pause and
    backoff-state writer, where the newest value must win and the TTL must slide with it.
    """
    return await cast(Awaitable[bool], r.set(key, value, ex=ttl_seconds)) is True


async def delete_key(r: Redis, key: str) -> int:
    """DEL ``key``, returning the number of keys removed (0 when already absent)."""
    return await cast(Awaitable[int], r.delete(key))


async def canary_window_push(
    r: Redis, key: str, sig: str, size: int, ttl_seconds: int
) -> list[bytes]:
    """
    LPUSH + LTRIM + LRANGE + EXPIRE one canary window in a single MULTI/EXEC (D-67).

    The four commands are one transaction so a concurrent poll on the same venue cannot read
    a half-updated window — a baseline that is momentarily 21 entries long, or trimmed but
    not yet expiring, would feed the ban verdict a window nobody ever actually observed.
    Returns the window AFTER the push, newest first, which is exactly the baseline the pure
    verdict function consumes.
    """
    async with r.pipeline(transaction=True) as pipe:
        pipe.lpush(key, sig)
        pipe.ltrim(key, 0, size - 1)
        pipe.lrange(key, 0, -1)
        pipe.expire(key, ttl_seconds)
        results = await pipe.execute()
    return cast("list[bytes]", results[2])
