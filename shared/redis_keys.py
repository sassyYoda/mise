"""
Single source of truth for ALL Redis key patterns and TTLs (D-18).
Any Redis access in services/ MUST import from here.
Named symbols: SCHED_POLLS, SCHED_POLLS_INFLIGHT, sched_expedite_key,
               CONFIRM_DELAY_MS, EXPEDITE_FLAG_TTL_SECONDS, EXPEDITE_POLL_LUA
"""
from __future__ import annotations

from typing import TYPE_CHECKING

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
