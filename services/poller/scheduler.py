"""Main poll loop: EVALSHA CLAIM -> dispatch -> publish -> EVALSHA RELEASE.

Implements D-18 (visibility-timeout claim/release) and D-17 (next poll score =
``now_ms + 90_000 + uniform(-13_500, 13_500)`` — 90s +/- 15% jitter).
"""
from __future__ import annotations

import asyncio
import random
import time
import uuid
from datetime import date, timedelta
from typing import Any

import httpx

from services.poller.config import DEFAULT_DATE_RANGE_DAYS, DEFAULT_PARTY_SIZES
from services.poller.publisher import Publisher
from services.poller.sources.opentable.adapter import OpenTableAdapter
from shared.redis_keys import POLL_INTERVAL_SECONDS, POLL_JITTER_FRACTION
from shared.scheduler.lua import LuaScheduler
from shared.telemetry import get_logger

log = get_logger(__name__)

_INTERVAL_MS: int = POLL_INTERVAL_SECONDS * 1000  # 90_000 ms
_JITTER_MS: int = int(_INTERVAL_MS * POLL_JITTER_FRACTION)  # +/- 13_500 ms


def _next_poll_score(now_ms: int) -> int:
    """D-17: next score = ``now_ms + 90_000 + uniform(-13_500, 13_500)``."""
    return now_ms + _INTERVAL_MS + int(random.uniform(-_JITTER_MS, _JITTER_MS))


def _build_dates(days: int = DEFAULT_DATE_RANGE_DAYS) -> list[date]:
    today = date.today()
    return [today + timedelta(days=i) for i in range(days)]


async def poll_loop(
    scheduler: LuaScheduler,
    opentable: OpenTableAdapter,
    publisher: Publisher,
) -> None:
    """Continuously pop due jobs, dispatch polls, and re-enqueue with next score.

    Empty queue -> sleeps 1s before retrying (no busy-loop).
    D-20: NO confirmation poll at P1. Raw emit only.
    """
    log.info("poll_loop_started")
    while True:
        now_ms = int(time.time() * 1000)
        job = await scheduler.claim(now_ms)
        if job is None:
            await asyncio.sleep(1)
            continue

        parts = job.split(":", 1)
        if len(parts) != 2:
            log.warning("invalid_job_descriptor", job=job)
            # Don't re-enqueue malformed jobs — drop them from inflight.
            continue

        source, rid_str = parts
        try:
            restaurant_id = int(rid_str)
        except ValueError:
            log.warning("invalid_restaurant_id", job=job)
            continue

        poll_id = uuid.uuid4()
        t_start = time.monotonic()

        status: str = "error"
        raw_response: dict[str, Any] = {}
        http_status: int | None = None
        error_str: str | None = None
        dates = _build_dates()
        request_params: dict[str, Any] = {
            "rid": restaurant_id,
            "dates": [d.isoformat() for d in dates],
            "party_sizes": list(DEFAULT_PARTY_SIZES),
        }

        try:
            if source == "opentable":
                raw_response = await opentable.poll(
                    rid=restaurant_id,
                    dates=dates,
                    party_sizes=DEFAULT_PARTY_SIZES,
                )
                status = "success"
                http_status = 200
            else:
                log.warning("unknown_source", source=source)
                status = "error"
                error_str = f"Unknown source: {source}"
        except httpx.HTTPStatusError as exc:
            status = "error"
            http_status = exc.response.status_code
            error_str = f"HTTP {http_status}: {exc}"
            log.error(
                "poll_http_error",
                restaurant_id=restaurant_id,
                http_status=http_status,
            )
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            status = "timeout"
            error_str = str(exc)
            log.error(
                "poll_timeout",
                restaurant_id=restaurant_id,
                error=error_str,
            )
        except Exception as exc:  # noqa: BLE001 — catch-all for operational robustness
            status = "error"
            error_str = str(exc)
            log.error(
                "poll_failed",
                restaurant_id=restaurant_id,
                error=error_str,
            )
        finally:
            latency_ms = int((time.monotonic() - t_start) * 1000)

        await publisher.publish(
            poll_id=poll_id,
            source=source,
            restaurant_id=restaurant_id,
            raw_response=raw_response,
            request_params=request_params,
            status=status,
            latency_ms=latency_ms,
            http_status=http_status,
            error=error_str,
        )

        next_score = _next_poll_score(int(time.time() * 1000))
        await scheduler.release(job, next_score)
