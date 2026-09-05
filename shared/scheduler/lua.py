"""
Lua scripts for atomic Redis ZSET scheduler operations (D-18).
All three scripts use EVALSHA with fallback to EVAL on NOSCRIPT error.
Named symbols: CLAIM_POLL_LUA, RELEASE_POLL_LUA, REAP_INFLIGHT_LUA (re-exported from shared.redis_keys)
"""
from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, cast

import redis.asyncio as redis
from redis.exceptions import NoScriptError

from shared.redis_keys import (
    CLAIM_POLL_LUA,
    POLL_VISIBILITY_TIMEOUT_MS,
    REAP_INFLIGHT_LUA,
    RELEASE_POLL_LUA,
    SCHED_POLLS,
    SCHED_POLLS_INFLIGHT,
)


class LuaScheduler:
    """
    Atomic ZSET scheduler using EVALSHA with NOSCRIPT fallback.
    Implements D-18 visibility-timeout pattern.
    """

    def __init__(self, client: redis.Redis) -> None:
        self.r = client
        self._claim_sha: str | None = None
        self._release_sha: str | None = None
        self._reap_sha: str | None = None

    async def start(self) -> None:
        """Load Lua scripts into Redis and cache SHAs."""
        self._claim_sha = await self.r.script_load(CLAIM_POLL_LUA)
        self._release_sha = await self.r.script_load(RELEASE_POLL_LUA)
        self._reap_sha = await self.r.script_load(REAP_INFLIGHT_LUA)

    async def _evalsha_with_fallback(
        self, sha: str, script: str, numkeys: int, *args: Any
    ) -> Any:
        """EVALSHA with automatic re-load fallback on NOSCRIPT (Redis restart / FLUSHSCRIPTS)."""
        try:
            return await cast(Awaitable[Any], self.r.evalsha(sha, numkeys, *args))
        except NoScriptError:
            new_sha = await self.r.script_load(script)
            return await cast(Awaitable[Any], self.r.evalsha(new_sha, numkeys, *args))

    async def claim(self, now_ms: int) -> str | None:
        """
        Atomically pop one due job from sched:polls and move to sched:polls:inflight.
        Returns job descriptor '{source}:{restaurant_id}' or None if no due jobs.
        """
        assert self._claim_sha is not None, "Call start() first"
        job = await self._evalsha_with_fallback(
            self._claim_sha, CLAIM_POLL_LUA, 2,
            SCHED_POLLS, SCHED_POLLS_INFLIGHT,
            str(now_ms), str(POLL_VISIBILITY_TIMEOUT_MS),
        )
        if job is None:
            return None
        return job.decode() if isinstance(job, (bytes, bytearray)) else str(job)

    async def release(self, job: str, next_poll_ms: int) -> None:
        """Move job from inflight back to sched:polls with new next_poll score."""
        assert self._release_sha is not None, "Call start() first"
        await self._evalsha_with_fallback(
            self._release_sha, RELEASE_POLL_LUA, 2,
            SCHED_POLLS_INFLIGHT, SCHED_POLLS,
            job, str(next_poll_ms),
        )

    async def reap(self, now_ms: int) -> list[str]:
        """Re-enqueue expired inflight jobs (worker crash recovery). Returns re-enqueued job IDs."""
        assert self._reap_sha is not None, "Call start() first"
        jobs = await self._evalsha_with_fallback(
            self._reap_sha, REAP_INFLIGHT_LUA, 2,
            SCHED_POLLS_INFLIGHT, SCHED_POLLS,
            str(now_ms),
        )
        if not jobs:
            return []
        return [j.decode() if isinstance(j, (bytes, bytearray)) else str(j) for j in jobs]
