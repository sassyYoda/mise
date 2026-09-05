"""
Single source of truth for ALL Redis key patterns and TTLs (D-18).
Any Redis access in services/ MUST import from here.
Named symbols: SCHED_POLLS, SCHED_POLLS_INFLIGHT, sched_expedite_key,
               CONFIRM_DELAY_MS, EXPEDITE_FLAG_TTL_SECONDS, EXPEDITE_POLL_LUA,
               avail_state_key, avail_meta_key, event_idempotency_key,
               AVAIL_STATE_TTL_SECONDS, EVENT_IDEMPOTENCY_TTL_SECONDS,
               hgetall_slots, hset_slot_with_ttl, hdel_slot_with_ttl, hset_meta_with_ttl
"""
from __future__ import annotations

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
