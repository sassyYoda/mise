"""Reaper: periodically re-enqueue jobs past their visibility deadline (D-18).

Runs every :data:`REAPER_INTERVAL_SECONDS`. Logs at INFO when any jobs are
reaped so operators can see worker recovery in real time.
"""
from __future__ import annotations

import asyncio
import time

from shared.redis_keys import REAPER_INTERVAL_SECONDS
from shared.scheduler.lua import LuaScheduler
from shared.telemetry import get_logger, safe_error

log = get_logger(__name__)


async def reaper_loop(scheduler: LuaScheduler) -> None:
    """Periodic reaper: runs every ~10s, re-enqueues expired inflight jobs."""
    log.info("reaper_loop_started", interval_seconds=REAPER_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(REAPER_INTERVAL_SECONDS)
        now_ms = int(time.time() * 1000)
        try:
            reaped = await scheduler.reap(now_ms)
            if reaped:
                log.info(
                    "reaper_reenqueued_jobs",
                    count=len(reaped),
                    jobs=reaped,
                )
            else:
                log.debug("reaper_no_expired_jobs")
        except Exception as exc:  # noqa: BLE001 — log and continue; reaper must not die
            log.error("reaper_error", error=safe_error(exc))
