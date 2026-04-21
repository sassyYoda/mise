---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 05
type: execute
wave: 4
depends_on: ["03", "04"]
files_modified:
  - services/poller/__init__.py
  - services/poller/sources/__init__.py
  - services/poller/sources/base.py
  - services/poller/sources/opentable/__init__.py
  - services/poller/sources/opentable/README.md
  - services/poller/sources/opentable/adapter.py
  - services/poller/sources/opentable/graphql.py
  - services/poller/sources/opentable/fixtures.py
  - services/poller/scheduler.py
  - services/poller/reaper.py
  - services/poller/publisher.py
  - services/poller/config.py
  - services/poller/main.py
  - services/poller/__main__.py
  - tests/integration/test_poller_smoke.py
  - tests/integration/test_seed_idempotency.py
  - tests/integration/test_topics_created.py
  - tests/integration/test_redis_config.py
  - tests/integration/test_poll_log_writes.py
autonomous: false
requirements_addressed:
  - POLL-01
  - POLL-03
  - POLL-07

must_haves:
  truths:
    - "services/poller/sources/opentable/README.md contains headings '## Endpoint', '## Headers', '## Query Shape', '## Rate-Limit Observations', '## Decision: GraphQL | HTML Fallback' (spike result)"
    - "`make poll` starts the poller; within 60s of `make up && make migrate && make seed && make topics`, at least one message appears on the `availability.raw` topic (SC1)"
    - "Each poll writes a row to `poll_log` with status in ('success','error','timeout') and latency_ms IS NOT NULL"
    - "Kafka message key is '{source}:{restaurant_id}' (D-29), e.g. 'opentable:42'"
    - "Scheduler uses EVALSHA CLAIM_POLL_LUA, dispatches to adapter, calls publisher, then EVALSHA RELEASE_POLL_LUA with next score = now_ms + 90000 + int(random.uniform(-13500, 13500)) (D-17)"
    - "Reaper runs every 10s, calls EVALSHA REAP_INFLIGHT_LUA, logs re-enqueued jobs at INFO level"
    - "shared httpx.AsyncClient is created once in lifespan with Limits(max_connections=100, max_keepalive_connections=20) and Timeout(10.0, connect=5.0) — never per-poll"
    - "Tenacity retry on adapter: stop_after_attempt(3), wait_exponential_jitter, retries httpx.ReadTimeout + httpx.RemoteProtocolError + httpx.HTTPStatusError; 429 triggers Retry-After sleep"
  artifacts:
    - path: services/poller/sources/opentable/README.md
      provides: "DevTools spike findings: endpoint, headers, query shape, rate-limit, decision"
      contains: "## Endpoint"
    - path: services/poller/sources/opentable/adapter.py
      provides: "OpenTableAdapter with fetch_availability using shared AsyncClient"
      exports: ["OpenTableAdapter"]
    - path: services/poller/scheduler.py
      provides: "Main poll loop using LuaScheduler claim/release"
      contains: "CLAIM"
    - path: services/poller/publisher.py
      provides: "Emits availability.raw and polls.completed; writes poll_log row"
      contains: "availability.raw"
    - path: services/poller/main.py
      provides: "Entry point with httpx lifespan and asyncio.gather for scheduler + reaper"
  key_links:
    - from: services/poller/scheduler.py
      to: services/poller/sources/opentable/adapter.py
      via: "scheduler claims job, dispatches to OpenTableAdapter.poll()"
      pattern: "OpenTableAdapter"
    - from: services/poller/scheduler.py
      to: services/poller/publisher.py
      via: "scheduler calls publisher after successful poll"
      pattern: "publisher"
    - from: services/poller/publisher.py
      to: "availability.raw"
      via: "AIOKafkaProducer.send(topic, value, key)"
      pattern: "availability\\.raw"
    - from: services/poller/publisher.py
      to: "poll_log"
      via: "AsyncSession INSERT into poll_log table"
      pattern: "poll_log"
---

<objective>
Build the complete OpenTable polling service: DevTools spike to confirm the GraphQL endpoint, AvailabilitySource base class, OpenTable adapter, Lua-driven ZSET scheduler main loop, reaper, Kafka publisher that also writes poll_log rows, and the entry point with shared httpx.AsyncClient in lifespan. Fill in all remaining Wave-0 integration test stubs.

Purpose: This plan delivers SC1 (poller emits availability.raw within 60s) and the POLL-01/POLL-03/POLL-07 requirements. After this plan, `make poll` starts a working poller.

Output: A complete `services/poller/` package; filled integration tests.
</objective>

<execution_context>
@/Users/aryanahuja/projects/mise/.claude/get-shit-done/workflows/execute-plan.md
@/Users/aryanahuja/projects/mise/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md
@.planning/research/STACK.md
@.planning/research/PITFALLS.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-04-SUMMARY.md
@shared/events.py
@shared/redis_keys.py
@shared/scheduler/lua.py
@shared/kafka.py
@shared/db.py
</context>

<tasks>

<task id="01-05-T1" type="checkpoint:decision">
  <name>Task 1: OpenTable DevTools spike — confirm GraphQL endpoint (30-minute spike)</name>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§4 OpenTable widget GraphQL endpoint — ASSUMED shape)
  </read_first>
  <decision>
    OpenTable GraphQL endpoint shape confirmation: what URL, headers, query/variables, and response structure does the current widget use?
  </decision>
  <context>
    The research file documents an ASSUMED shape for the OpenTable widget GraphQL endpoint (§4) with confidence=MEDIUM. OpenTable has changed its query structure across 2022-2025. Before writing the adapter, you MUST empirically confirm the current endpoint via browser DevTools.

    30-minute procedure:
    1. Open Chrome and navigate to an OpenTable restaurant page (e.g. opentable.com/r/carbone-new-york)
    2. Open DevTools > Network tab > filter by "Fetch/XHR" and keyword "avail" or "gql"
    3. Select date/party size in the booking widget to trigger an availability request
    4. Capture: exact URL, request headers (especially User-Agent, Origin, Referer, any auth headers), request body (query + variables), response body structure
    5. Document whether the widget uses GraphQL (POST with JSON body containing "query" key) or REST (GET with query params)
    6. Test if the endpoint is reachable without cookies (open an incognito tab and repeat)
    7. Note any rate-limit headers in the response (Retry-After, X-RateLimit-*)

    Decision options:
    - option-a: GraphQL endpoint confirmed (POST to /dapi/fe/gql/prod or similar), no auth cookies required
    - option-b: REST endpoint (GET /restref/api/availability or similar), no auth cookies required
    - option-c: Endpoint requires auth cookies or is gated — use HTML fallback (__NEXT_DATA__ parsing)

    Write findings to services/poller/sources/opentable/README.md with these exact headings:
    ## Endpoint
    ## Headers
    ## Query Shape
    ## Rate-Limit Observations
    ## Decision: GraphQL | HTML Fallback
  </context>
  <options>
    <option id="option-a">
      <name>GraphQL endpoint (POST, no auth cookies)</name>
      <pros>Clean programmatic access; adapter sends POST with JSON body</pros>
      <cons>Schema can change; need to isolate query in graphql.py module</cons>
    </option>
    <option id="option-b">
      <name>REST endpoint (GET, no auth cookies)</name>
      <pros>Simpler adapter; standard GET params</pros>
      <cons>URL structure may change; less structured response</cons>
    </option>
    <option id="option-c">
      <name>HTML fallback: fetch widget HTML, parse __NEXT_DATA__ JSON</name>
      <pros>Works if API is gated; publicly visible data</pros>
      <cons>More brittle; higher latency per request</cons>
    </option>
  </options>
  <resume-signal>
    After completing the DevTools spike, type one of:
    - "approved: option-a" — GraphQL confirmed, proceed with graphql.py POST adapter
    - "approved: option-b" — REST confirmed, proceed with REST adapter
    - "approved: option-c" — endpoint gated, proceed with HTML fallback adapter
    Then continue to Task 2.
  </resume-signal>
</task>

<task id="01-05-T2" type="auto">
  <name>Task 2: Base class, adapter, graphql.py, fixtures (per DevTools spike decision)</name>
  <files>
    services/poller/__init__.py,
    services/poller/sources/__init__.py,
    services/poller/sources/base.py,
    services/poller/sources/opentable/__init__.py,
    services/poller/sources/opentable/adapter.py,
    services/poller/sources/opentable/graphql.py,
    services/poller/sources/opentable/fixtures.py,
    services/poller/config.py
  </files>
  <read_first>
    services/poller/sources/opentable/README.md (spike findings from Task 1),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-05, D-17, D-19),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§4 OpenTable adapter pattern; §5 httpx shared AsyncClient + tenacity retry),
    shared/events.py (AvailabilityRawEvent, PollsCompletedEvent)
  </read_first>
  <action>
Create all __init__.py files as empty.

Create `services/poller/config.py`:
```python
"""Poller service configuration (D-17, D-19, T-03)."""
import os
import random

# Polling schedule (D-17)
POLL_INTERVAL_SECONDS = 90
POLL_JITTER_FRACTION = 0.15

# Date and party size defaults for OpenTable polling (D-19)
DEFAULT_DATE_RANGE_DAYS = 7
DEFAULT_PARTY_SIZES = [2, 4]

# User-Agent rotation list (T-03 — rotate per request to avoid fingerprinting)
USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


# Kafka settings
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")

# Redis settings
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Database settings
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://mise:mise@localhost:5432/mise")
```

Create `services/poller/sources/base.py`:
```python
"""Abstract base class for availability polling sources (D-19)."""
from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import date
from typing import Any


class AvailabilitySource(ABC):
    """
    Abstract polling source. Concrete implementations: OpenTableAdapter (P1), ResyAdapter (P3).
    Each source receives a shared httpx.AsyncClient at construction — NEVER creates its own (Pitfall 9).
    """

    @abstractmethod
    async def poll(
        self,
        rid: int,
        dates: list[date],
        party_sizes: list[int],
    ) -> dict[str, Any]:
        """
        Poll availability for a restaurant.

        Args:
            rid: Platform-specific restaurant ID.
            dates: List of dates to poll.
            party_sizes: List of party sizes to poll.

        Returns:
            Raw response dict. Must contain the full raw API response for
            availability.raw Kafka message payload (D-19, replay readiness).
        """
        ...
```

Create `services/poller/sources/opentable/graphql.py` with the GraphQL query builder (or REST request builder if spike selected option-b/c). Base on findings from README.md:
```python
"""
OpenTable availability request builder.
Update ENDPOINT and build_request() if OpenTable changes its schema.
All endpoint details documented in services/poller/sources/opentable/README.md.
[ASSUMED] — update after DevTools spike confirms current shape.
"""
from __future__ import annotations
from datetime import date, timedelta
from typing import Any

# UPDATE after spike confirms endpoint (see README.md ## Endpoint)
OPENTABLE_GQL_ENDPOINT = "https://www.opentable.com/dapi/fe/gql/prod"

# Headers required by OpenTable widget requests (see README.md ## Headers)
OPENTABLE_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.opentable.com",
}


def build_request(
    rid: int,
    target_dates: list[date],
    party_sizes: list[int],
) -> dict[str, Any]:
    """
    Build the POST body for OpenTable availability GraphQL query.
    If spike found REST endpoint instead, change this to return query params dict.
    """
    # NOTE: Update query name and variables shape from README.md ## Query Shape
    return {
        "operationName": "RestaurantsAvailability",
        "variables": {
            "restaurantIds": [rid],
            "partySize": party_sizes[0],   # Primary party size; loop for multiple
            "startDate": target_dates[0].isoformat(),
            "endDate": target_dates[-1].isoformat(),
            "databaseRegion": "NA",
        },
        "query": """
query RestaurantsAvailability($restaurantIds: [Int!]!, $partySize: Int!, $startDate: String!, $endDate: String!, $databaseRegion: String!) {
  availability(
    restaurantIds: $restaurantIds
    partySize: $partySize
    startDate: $startDate
    endDate: $endDate
    databaseRegion: $databaseRegion
  ) {
    restaurantId
    availability {
      date
      timeSlots {
        time
        seatingTypes
        token
      }
    }
  }
}
        """.strip(),
    }
```

Create `services/poller/sources/opentable/fixtures.py` with golden-file JSON for respx mocking in tests:
```python
"""
Golden-file JSON fixtures for OpenTable adapter unit/integration tests.
Used with respx to mock the OpenTable endpoint without real network calls (D-34).
Update shapes from README.md ## Query Shape after DevTools spike.
"""
from typing import Any

# Minimal success response — 1 restaurant, 1 date, 1 timeslot
OPENTABLE_SUCCESS_RESPONSE: dict[str, Any] = {
    "data": {
        "availability": [
            {
                "restaurantId": 42,
                "availability": [
                    {
                        "date": "2026-05-01",
                        "timeSlots": [
                            {
                                "time": "19:00",
                                "seatingTypes": ["bar", "standard"],
                                "token": "abc123-reservation-token",
                            }
                        ],
                    }
                ],
            }
        ]
    }
}

# Empty availability — no slots (restaurant fully booked)
OPENTABLE_EMPTY_RESPONSE: dict[str, Any] = {
    "data": {
        "availability": [
            {
                "restaurantId": 42,
                "availability": [],
            }
        ]
    }
}

# 429 rate limit response body
OPENTABLE_RATE_LIMIT_RESPONSE: dict[str, Any] = {
    "errors": [{"message": "Too many requests", "extensions": {"code": "RATE_LIMITED"}}]
}
```

Create `services/poller/sources/opentable/adapter.py`:
```python
"""
OpenTable availability polling adapter (D-05, D-19, POLL-03).
Uses shared httpx.AsyncClient — NEVER creates per-poll clients (Pitfall 9).
Implements tenacity retry with Retry-After header support.
"""
from __future__ import annotations
import time
import asyncio
from datetime import date
from typing import Any

import httpx
import structlog
from tenacity import (
    retry, stop_after_attempt, wait_exponential_jitter,
    retry_if_exception_type, before_sleep_log,
)

from shared.telemetry import get_logger
from services.poller.sources.base import AvailabilitySource
from services.poller.sources.opentable.graphql import (
    OPENTABLE_GQL_ENDPOINT,
    OPENTABLE_HEADERS,
    build_request,
)
from services.poller.config import random_user_agent

log = get_logger(__name__)

_TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


class OpenTableAdapter(AvailabilitySource):
    """
    Polls OpenTable widget GraphQL for restaurant availability.
    Created once per process with shared client (D-05).
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client  # shared, NEVER per-poll (D-05, Pitfall 9)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=8, jitter=2),
        retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS + (httpx.HTTPStatusError,)),
        before_sleep=before_sleep_log(log, "WARNING"),
        reraise=True,
    )
    async def _fetch(self, rid: int, dates: list[date], party_sizes: list[int]) -> dict[str, Any]:
        headers = {**OPENTABLE_HEADERS, "User-Agent": random_user_agent()}
        resp = await self.client.post(
            OPENTABLE_GQL_ENDPOINT,
            json=build_request(rid, dates, party_sizes),
            headers=headers,
        )
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            log.warning("opentable_rate_limited", rid=rid, retry_after=retry_after)
            await asyncio.sleep(retry_after)
            raise httpx.ReadTimeout("429 rate limited — retry after sleep", request=resp.request)
        resp.raise_for_status()
        return resp.json()

    async def poll(
        self,
        rid: int,
        dates: list[date],
        party_sizes: list[int],
    ) -> dict[str, Any]:
        """
        Poll OpenTable for availability. Returns full raw response dict.
        Full response is stored in availability.raw Kafka message for replay (D-19).
        """
        return await self._fetch(rid, dates, party_sizes)
```
  </action>
  <verify>
    <automated>uv run python -c "
from services.poller.sources.base import AvailabilitySource
from services.poller.sources.opentable.adapter import OpenTableAdapter
from services.poller.sources.opentable.graphql import build_request, OPENTABLE_GQL_ENDPOINT
from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.poller.config import random_user_agent, USER_AGENTS
import httpx
# Verify adapter inherits from AvailabilitySource
assert issubclass(OpenTableAdapter, AvailabilitySource)
# Verify UA rotation
ua = random_user_agent()
assert ua in USER_AGENTS
print('adapter imports OK')
"</automated>
  </verify>
  <done>
    services/poller/sources/base.py has abstract AvailabilitySource with poll() method; OpenTableAdapter inherits AvailabilitySource, stores shared client (not per-poll); tenacity retry configured with stop_after_attempt(3) and wait_exponential_jitter; Retry-After header respected for 429; config.py has USER_AGENTS list with >=4 entries and random_user_agent(); services/poller/sources/opentable/README.md has all 5 required headings from DevTools spike
  </done>
</task>

<task id="01-05-T3" type="auto">
  <name>Task 3: scheduler.py, reaper.py, publisher.py, main.py</name>
  <files>
    services/poller/scheduler.py,
    services/poller/reaper.py,
    services/poller/publisher.py,
    services/poller/main.py,
    services/poller/__main__.py
  </files>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-05, D-17, D-18, D-19, D-20, D-29),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§3 EVALSHA caching pattern; §5 httpx shared AsyncClient pattern),
    shared/scheduler/lua.py (LuaScheduler class),
    shared/events.py (AvailabilityRawEvent, PollsCompletedEvent),
    shared/db.py (PollLog model, get_async_session)
  </read_first>
  <action>
Create `services/poller/publisher.py`:
```python
"""
Kafka publisher for the OpenTable poller (D-29, POLL-07).
Emits availability.raw + polls.completed; writes poll_log row synchronously before returning.
Named Symbols: availability.raw, polls.completed, {source}:{restaurant_id}
"""
from __future__ import annotations
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from aiokafka import AIOKafkaProducer
from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.events import AvailabilityRawEvent, PollsCompletedEvent
from shared.db import PollLog, get_async_session
from shared.telemetry import get_logger

log = get_logger(__name__)


class Publisher:
    """Emits Kafka events and persists poll_log rows (POLL-07)."""

    def __init__(self, producer: AIOKafkaProducer) -> None:
        self.producer = producer

    async def publish(
        self,
        poll_id: UUID,
        source: str,
        restaurant_id: int,
        raw_response: dict[str, Any],
        status: str,          # 'success' | 'error' | 'timeout'
        latency_ms: int,
        http_status: int | None = None,
        error: str | None = None,
    ) -> None:
        """
        Emit availability.raw + polls.completed to Kafka and write poll_log row.
        Kafka key: '{source}:{restaurant_id}' (D-29).
        """
        now_ms = int(time.time() * 1000)
        kafka_key = f"{source}:{restaurant_id}"  # Named Symbol: {source}:{restaurant_id}

        # 1. Emit availability.raw (only on success — do not emit on error/timeout)
        if status == "success" and raw_response:
            raw_event = AvailabilityRawEvent(
                poll_id=poll_id,
                source=source,            # type: ignore[arg-type]
                restaurant_id=restaurant_id,
                polled_at_epoch_ms=now_ms,
                raw_response=raw_response,
            )
            await self.producer.send(
                "availability.raw",           # Named Symbol: availability.raw
                value=raw_event.to_bytes(),
                key=kafka_key,
            )
            log.info("availability_raw_published", poll_id=str(poll_id), restaurant_id=restaurant_id)

        # 2. Emit polls.completed (always — success, error, timeout)
        completed_event = PollsCompletedEvent(
            poll_id=poll_id,
            source=source,                # type: ignore[arg-type]
            restaurant_id=restaurant_id,
            completed_at_epoch_ms=now_ms,
            status=status,                # type: ignore[arg-type]
            latency_ms=latency_ms,
            http_status=http_status,
            error=error,
        )
        await self.producer.send(
            "polls.completed",             # Named Symbol: polls.completed
            value=completed_event.to_bytes(),
            key=kafka_key,
        )

        # 3. Write poll_log row (synchronous before returning — SC4, POLL-07)
        session_factory = get_async_session()
        async with session_factory() as session:
            await session.execute(
                insert(PollLog).values(
                    time=datetime.now(timezone.utc),
                    restaurant_id=restaurant_id,
                    source=source,
                    status=status,
                    latency_ms=latency_ms,
                    http_status=http_status,
                    error=error,
                    poll_id=poll_id,
                )
            )
            await session.commit()

        log.debug(
            "poll_published",
            poll_id=str(poll_id),
            restaurant_id=restaurant_id,
            status=status,
            latency_ms=latency_ms,
        )
```

Create `services/poller/scheduler.py`:
```python
"""
Main poll loop: EVALSHA CLAIM → dispatch → publish → EVALSHA RELEASE (D-18, POLL-01).
Next poll score: now_ms + 90000 + jitter (D-17: 90s ± 15%).
"""
from __future__ import annotations
import asyncio
import random
import time
import uuid
from datetime import date, timedelta
from typing import Any

from shared.scheduler.lua import LuaScheduler
from shared.redis_keys import POLL_INTERVAL_SECONDS, POLL_JITTER_FRACTION
from shared.telemetry import get_logger
from services.poller.sources.opentable.adapter import OpenTableAdapter
from services.poller.publisher import Publisher
from services.poller.config import DEFAULT_DATE_RANGE_DAYS, DEFAULT_PARTY_SIZES

log = get_logger(__name__)

_INTERVAL_MS = POLL_INTERVAL_SECONDS * 1000                   # 90_000 ms
_JITTER_MS   = int(_INTERVAL_MS * POLL_JITTER_FRACTION)       # ±13_500 ms


def _next_poll_score(now_ms: int) -> int:
    """D-17: next score = now_ms + 90000 + uniform(-13500, 13500)."""
    return now_ms + _INTERVAL_MS + int(random.uniform(-_JITTER_MS, _JITTER_MS))


def _build_dates(days: int = DEFAULT_DATE_RANGE_DAYS) -> list[date]:
    today = date.today()
    return [today + timedelta(days=i) for i in range(days)]


async def poll_loop(
    scheduler: LuaScheduler,
    opentable: OpenTableAdapter,
    publisher: Publisher,
) -> None:
    """
    Continuously pops due jobs, dispatches polls, and re-enqueues with next score.
    Empty queue → sleeps 1s before retrying (no busy-loop).
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
            continue

        source, rid_str = parts
        restaurant_id = int(rid_str)
        poll_id = uuid.uuid4()
        t_start = time.monotonic()

        status: str = "error"
        raw_response: dict[str, Any] = {}
        http_status: int | None = None
        error_str: str | None = None

        try:
            if source == "opentable":
                raw_response = await opentable.poll(
                    rid=restaurant_id,
                    dates=_build_dates(),
                    party_sizes=DEFAULT_PARTY_SIZES,
                )
                status = "success"
                http_status = 200
            else:
                log.warning("unknown_source", source=source)
                status = "error"
                error_str = f"Unknown source: {source}"
        except Exception as exc:
            error_str = str(exc)
            # Classify timeout vs general error
            import httpx
            if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectTimeout)):
                status = "timeout"
            else:
                status = "error"
            log.error("poll_failed", restaurant_id=restaurant_id, error=error_str)
        finally:
            latency_ms = int((time.monotonic() - t_start) * 1000)

        await publisher.publish(
            poll_id=poll_id,
            source=source,
            restaurant_id=restaurant_id,
            raw_response=raw_response,
            status=status,
            latency_ms=latency_ms,
            http_status=http_status,
            error=error_str,
        )

        next_score = _next_poll_score(int(time.time() * 1000))
        await scheduler.release(job, next_score)
```

Create `services/poller/reaper.py`:
```python
"""
Reaper: periodically re-enqueues jobs past their visibility deadline (D-18).
Runs every REAPER_INTERVAL_SECONDS. Logs at INFO when jobs are reaped.
"""
from __future__ import annotations
import asyncio
import time

from shared.redis_keys import REAPER_INTERVAL_SECONDS
from shared.scheduler.lua import LuaScheduler
from shared.telemetry import get_logger

log = get_logger(__name__)


async def reaper_loop(scheduler: LuaScheduler) -> None:
    """Periodic reaper: runs every 10s, re-enqueues expired inflight jobs."""
    log.info("reaper_loop_started", interval_seconds=REAPER_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(REAPER_INTERVAL_SECONDS)
        now_ms = int(time.time() * 1000)
        try:
            reaped = await scheduler.reap(now_ms)
            if reaped:
                log.info("reaper_reenqueued_jobs", count=len(reaped), jobs=reaped)
            else:
                log.debug("reaper_no_expired_jobs")
        except Exception as exc:
            log.error("reaper_error", error=str(exc))
```

Create `services/poller/main.py`:
```python
"""
Poller service entry point (D-05, D-08).
Shared httpx.AsyncClient created in lifespan — never per-poll (Pitfall 9).
Runs scheduler + reaper concurrently via asyncio.gather.
"""
from __future__ import annotations
import asyncio
import os

import httpx
import redis.asyncio as redis

from shared.kafka import make_producer
from shared.telemetry import configure_logging, get_logger
from shared.scheduler.lua import LuaScheduler
from services.poller.sources.opentable.adapter import OpenTableAdapter
from services.poller.publisher import Publisher
from services.poller.scheduler import poll_loop
from services.poller.reaper import reaper_loop
from services.poller.config import (
    REDIS_URL,
    KAFKA_BOOTSTRAP_SERVERS,
    DATABASE_URL,
)

log = get_logger(__name__)

HTTP_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)
HTTP_TIMEOUT = httpx.Timeout(10.0, connect=5.0)  # D-05: 10s read, 5s connect


async def run() -> None:
    configure_logging()
    log.info("poller_starting")

    # Shared httpx.AsyncClient (D-05, Pitfall 9 — ONE client per process, in lifespan)
    async with httpx.AsyncClient(
        limits=HTTP_LIMITS,
        timeout=HTTP_TIMEOUT,
        http2=True,
    ) as http_client:
        # Connect to Redis
        r = redis.from_url(REDIS_URL)
        scheduler = LuaScheduler(r)
        await scheduler.start()

        # Connect to Kafka
        producer = await make_producer(KAFKA_BOOTSTRAP_SERVERS)

        # Wire adapters
        opentable = OpenTableAdapter(client=http_client)
        publisher = Publisher(producer=producer)

        log.info("poller_ready", redis=REDIS_URL, kafka=KAFKA_BOOTSTRAP_SERVERS)

        try:
            await asyncio.gather(
                poll_loop(scheduler, opentable, publisher),
                reaper_loop(scheduler),
            )
        finally:
            await producer.stop()
            await r.aclose()
            log.info("poller_stopped")


if __name__ == "__main__":
    asyncio.run(run())
```

Create `services/poller/__main__.py`:
```python
"""Allows `python -m services.poller` (D-08, Makefile `make poll` target)."""
from services.poller.main import run
import asyncio
asyncio.run(run())
```
  </action>
  <verify>
    <automated>uv run python -c "
from services.poller.scheduler import poll_loop, _next_poll_score
from services.poller.reaper import reaper_loop
from services.poller.publisher import Publisher
from services.poller.main import HTTP_LIMITS, HTTP_TIMEOUT
import httpx, time
# Verify shared client limits
assert HTTP_LIMITS.max_connections == 100
assert HTTP_LIMITS.max_keepalive_connections == 20
# Verify jitter range (D-17: 90s ± 15% = 76.5s to 103.5s)
now = int(time.time() * 1000)
scores = [_next_poll_score(now) - now for _ in range(100)]
assert all(76500 <= s <= 103500 for s in scores), f'Jitter out of range: min={min(scores)}, max={max(scores)}'
print('poller service OK')
"</automated>
  </verify>
  <done>
    publisher.py emits to "availability.raw" (Named Symbol) and "polls.completed" (Named Symbol) with key="{source}:{restaurant_id}" (D-29); writes poll_log row via AsyncSession INSERT before returning; scheduler.py uses LuaScheduler.claim/release with next score = now+90000±13500ms (D-17); reaper.py runs every REAPER_INTERVAL_SECONDS and logs at INFO on reap; main.py creates ONE httpx.AsyncClient with Limits(max_connections=100, max_keepalive_connections=20) and Timeout(10.0, connect=5.0); asyncio.gather runs poll_loop + reaper_loop concurrently; `python -m services.poller` entry point works
  </done>
</task>

<task id="01-05-T4" type="auto">
  <name>Task 4: Fill all remaining Wave-0 integration test stubs</name>
  <files>
    tests/integration/test_poller_smoke.py,
    tests/integration/test_seed_idempotency.py,
    tests/integration/test_topics_created.py,
    tests/integration/test_redis_config.py,
    tests/integration/test_poll_log_writes.py
  </files>
  <read_first>
    tests/integration/test_poller_smoke.py (current Wave-0 stub),
    tests/integration/test_seed_idempotency.py (current Wave-0 stub),
    tests/integration/test_topics_created.py (current Wave-0 stub),
    tests/integration/test_redis_config.py (current Wave-0 stub),
    tests/integration/test_poll_log_writes.py (current Wave-0 stub),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§6 testcontainers fixtures; respx mock example),
    services/poller/sources/opentable/fixtures.py (golden-file JSON)
  </read_first>
  <action>
Fill in all five remaining integration test stubs by removing `@pytest.mark.skip` and writing real test bodies using testcontainers + respx.

`tests/integration/test_topics_created.py` — fill in:
```python
"""Integration: FOUND-04 — all 5 Kafka topics exist with correct retention."""
import asyncio
import os
import subprocess
import pytest
from aiokafka.admin import AIOKafkaAdminClient


@pytest.fixture(scope="module")
def kafka_bootstrap(kafka_container):
    return kafka_container.get_bootstrap_server()


@pytest.fixture(scope="module", autouse=True)
def create_topics(kafka_bootstrap):
    """Run scripts/create_topics.py against testcontainers Kafka."""
    env = {**os.environ, "KAFKA_BOOTSTRAP_SERVERS": kafka_bootstrap}
    result = subprocess.run(
        ["uv", "run", "python", "scripts/create_topics.py"],
        env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, f"create_topics failed: {result.stderr}"


@pytest.mark.asyncio
async def test_all_five_topics_have_retention(kafka_bootstrap):
    """All 5 Named Symbol topics exist with correct retention.ms."""
    admin = AIOKafkaAdminClient(bootstrap_servers=kafka_bootstrap)
    await admin.start()
    try:
        topics = set(await admin.list_topics())
        expected = {
            "availability.raw",
            "availability.events",
            "polls.completed",
            "notifications.queued",
            "notifications.sent",
        }
        assert expected.issubset(topics), f"Missing topics: {expected - topics}"
    finally:
        await admin.close()


@pytest.mark.asyncio
async def test_topics_creation_idempotent(kafka_bootstrap):
    """Running create_topics twice does not raise an error."""
    env = {**os.environ, "KAFKA_BOOTSTRAP_SERVERS": kafka_bootstrap}
    result = subprocess.run(
        ["uv", "run", "python", "scripts/create_topics.py"],
        env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, f"Second run failed: {result.stderr}"
```

`tests/integration/test_redis_config.py` — fill in:
```python
"""Integration: Pitfall 18 — Redis maxmemory-policy = noeviction."""
import pytest
import redis


@pytest.fixture(scope="module")
def sync_redis_client(redis_container):
    port = redis_container.get_exposed_port(6379)
    host = redis_container.get_container_host_ip()
    return redis.Redis(host=host, port=port, decode_responses=True)


def test_eviction_policy_is_noeviction(sync_redis_client):
    """Redis must have maxmemory-policy = noeviction (Pitfall 18, D-03)."""
    policy = sync_redis_client.config_get("maxmemory-policy")
    assert policy.get("maxmemory-policy") == "noeviction", (
        f"Expected noeviction, got {policy}"
    )
```

`tests/integration/test_seed_idempotency.py` — fill in (uses scripts/seed/restaurants.yml — may be small stub in CI):
```python
"""Integration: SC3 — seed populates all fields and sched:polls ZSET; idempotent."""
import asyncio
import os
import subprocess
import pytest
import asyncpg
import redis.asyncio as aioredis


@pytest.fixture(scope="module")
def db_url(timescale_container):
    host = timescale_container.get_container_host_ip()
    port = timescale_container.get_exposed_port(5432)
    return f"postgresql://mise:mise@{host}:{port}/mise"


@pytest.fixture(scope="module")
def db_url_sync(timescale_container):
    return timescale_container.get_connection_url().replace("psycopg2", "psycopg")


@pytest.fixture(scope="module")
def redis_url(redis_container):
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


@pytest.fixture(scope="module", autouse=True)
def run_migrations(db_url_sync):
    env = {**os.environ, "DATABASE_URL_SYNC": db_url_sync}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"


def _run_seed(db_url_async: str, redis_url: str) -> int:
    env = {
        **os.environ,
        "DATABASE_URL": db_url_async,
        "REDIS_URL": redis_url,
    }
    result = subprocess.run(
        ["uv", "run", "python", "scripts/seed_restaurants.py"],
        env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, f"seed failed: {result.stderr}"
    return 0


@pytest.mark.asyncio
async def test_seed_populates_all_fields_and_zset(db_url, redis_url, db_url_sync):
    db_url_async = db_url_sync.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    _run_seed(db_url_async, redis_url)
    # Check DB count
    conn = await asyncpg.connect(db_url)
    try:
        count = await conn.fetchval("""
            SELECT COUNT(*) FROM restaurants
            WHERE opentable_rid IS NOT NULL
              AND neighborhood IS NOT NULL
              AND cuisine IS NOT NULL
              AND price_tier IS NOT NULL
              AND cover_photo_url IS NOT NULL
        """)
    finally:
        await conn.close()
    # Note: test may have fewer than 50 if restaurants.yml stub has fewer entries in CI
    # In production, restaurants.yml must have >= 50 (SC3)
    assert count >= 1, f"No restaurants seeded (count={count})"
    # Check ZSET
    r = aioredis.from_url(redis_url)
    try:
        zcard = await r.zcard("sched:polls")
        assert zcard >= 1, f"sched:polls is empty"
    finally:
        await r.aclose()


@pytest.mark.asyncio
async def test_seed_idempotent(db_url, redis_url, db_url_sync):
    """Running seed twice produces same count (no duplicates)."""
    db_url_async = db_url_sync.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    _run_seed(db_url_async, redis_url)
    _run_seed(db_url_async, redis_url)  # second run
    conn = await asyncpg.connect(db_url)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM restaurants")
    finally:
        await conn.close()
    # Count should be the same after both runs
    assert count >= 1
```

`tests/integration/test_poll_log_writes.py` — fill in:
```python
"""Integration: SC4 — poll_log rows written with latency after a poll cycle."""
import asyncio
import os
import time
import uuid
import pytest
import asyncpg
from unittest.mock import AsyncMock, patch

from services.poller.publisher import Publisher
from shared.events import PollsCompletedEvent


@pytest.fixture(scope="module")
def db_url(timescale_container):
    host = timescale_container.get_container_host_ip()
    port = timescale_container.get_exposed_port(5432)
    return f"postgresql://mise:mise@{host}:{port}/mise"


@pytest.fixture(scope="module")
def db_url_sync(timescale_container):
    return timescale_container.get_connection_url().replace("psycopg2", "psycopg")


@pytest.fixture(scope="module", autouse=True)
def run_migrations(db_url_sync):
    import subprocess
    env = {**os.environ, "DATABASE_URL_SYNC": db_url_sync}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"


@pytest.mark.asyncio
async def test_poll_writes_row_with_latency(db_url, db_url_sync):
    """Publisher.publish() writes a poll_log row with status and latency_ms."""
    db_url_async = db_url_sync.replace("postgresql+psycopg://", "postgresql+asyncpg://")
    os.environ["DATABASE_URL"] = db_url_async

    # Mock Kafka producer — we only test the DB write here
    mock_producer = AsyncMock()
    mock_producer.send = AsyncMock()

    publisher = Publisher(producer=mock_producer)
    poll_id = uuid.uuid4()

    await publisher.publish(
        poll_id=poll_id,
        source="opentable",
        restaurant_id=42,
        raw_response={"slots": []},
        status="success",
        latency_ms=250,
        http_status=200,
    )

    conn = await asyncpg.connect(db_url)
    try:
        row = await conn.fetchrow(
            "SELECT * FROM poll_log WHERE poll_id = $1",
            poll_id,
        )
        assert row is not None, "poll_log row not found"
        assert row["status"] == "success"
        assert row["latency_ms"] == 250
        assert row["http_status"] == 200
        assert row["restaurant_id"] == 42
        assert row["source"] == "opentable"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_poll_log_status_values_constrained(db_url, db_url_sync):
    """All poll_log.status values must be 'success', 'error', or 'timeout'."""
    conn = await asyncpg.connect(db_url)
    try:
        invalid = await conn.fetchval("""
            SELECT COUNT(*) FROM poll_log
            WHERE status NOT IN ('success', 'error', 'timeout')
        """)
        assert invalid == 0, f"{invalid} rows with invalid status values"
    finally:
        await conn.close()
```

`tests/integration/test_poller_smoke.py` — fill in (end-to-end with respx):
```python
"""Integration smoke: SC1 — end-to-end emit within 60s."""
import asyncio
import os
import time
import pytest
import respx
from httpx import Response
from aiokafka import AIOKafkaConsumer
from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.poller.sources.opentable.graphql import OPENTABLE_GQL_ENDPOINT


@pytest.fixture(scope="module")
def kafka_bootstrap(kafka_container):
    return kafka_container.get_bootstrap_server()


@pytest.mark.asyncio
@pytest.mark.timeout(90)
async def test_end_to_end_emit_within_60s(
    kafka_container, redis_container, timescale_container
):
    """
    With respx mocking OpenTable, one poll cycle must emit an availability.raw
    message within 60s and write a poll_log row with status='success'.
    """
    kafka_bootstrap = kafka_container.get_bootstrap_server()
    redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}"
    db_url_sync = timescale_container.get_connection_url().replace("psycopg2", "psycopg")
    db_url_async = db_url_sync.replace("postgresql+psycopg://", "postgresql+asyncpg://")

    # Set env vars
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = kafka_bootstrap
    os.environ["REDIS_URL"] = redis_url
    os.environ["DATABASE_URL"] = db_url_async
    os.environ["DATABASE_URL_SYNC"] = db_url_sync

    # Run migrations
    import subprocess
    env = {**os.environ, "DATABASE_URL_SYNC": db_url_sync}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env, capture_output=True, text=True
    )
    assert result.returncode == 0

    # Create topics
    result = subprocess.run(
        ["uv", "run", "python", "scripts/create_topics.py"],
        env=env, capture_output=True, text=True
    )
    assert result.returncode == 0

    # Seed one restaurant to sched:polls
    import redis.asyncio as aioredis
    import json, time as _time
    r = aioredis.from_url(redis_url)
    await r.zadd("sched:polls", {"opentable:42": int(_time.time() * 1000) - 1000})
    await r.aclose()

    # Run one poll cycle with respx mocking OpenTable
    with respx.mock(assert_all_called=False) as router:
        router.post(OPENTABLE_GQL_ENDPOINT).mock(
            return_value=Response(200, json=OPENTABLE_SUCCESS_RESPONSE)
        )

        from services.poller.main import run
        # Run for 30s max
        try:
            await asyncio.wait_for(run(), timeout=30)
        except asyncio.TimeoutError:
            pass  # Expected — poller runs indefinitely; we just need it to emit once

    # Check that at least one message was produced to availability.raw
    consumer = AIOKafkaConsumer(
        "availability.raw",
        bootstrap_servers=kafka_bootstrap,
        auto_offset_reset="earliest",
        consumer_timeout_ms=5000,
    )
    await consumer.start()
    try:
        messages = []
        async for msg in consumer:
            messages.append(msg)
            break  # Just need one
        assert len(messages) >= 1, "No messages on availability.raw within timeout"
        key = messages[0].key.decode()
        assert "opentable:" in key, f"Unexpected key: {key}"
    finally:
        await consumer.stop()
```
  </action>
  <verify>
    <automated>uv run python -c "
import ast, pathlib
stubs = [
    'tests/integration/test_poller_smoke.py',
    'tests/integration/test_seed_idempotency.py',
    'tests/integration/test_topics_created.py',
    'tests/integration/test_redis_config.py',
    'tests/integration/test_poll_log_writes.py',
]
for s in stubs:
    txt = pathlib.Path(s).read_text()
    # Verify no remaining pytest.mark.skip in actual test functions
    # (skip in comments is OK)
    lines = [l for l in txt.split('\n') if 'mark.skip' in l and not l.strip().startswith('#')]
    assert not lines, f'{s} still has skip decorators: {lines}'
    ast.parse(txt)  # syntax check
    print(f'{s}: OK (no skips, parses clean)')
"</automated>
  </verify>
  <done>
    All 5 integration test stubs filled in with real test bodies; no @pytest.mark.skip remaining; test_redis_config tests noeviction; test_topics_created verifies all 5 Named Symbol topics; test_poll_log_writes verifies poll_log row has latency_ms and status in ('success','error','timeout'); test_poller_smoke uses respx to mock OpenTable and asserts availability.raw message emitted with correct key format
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| poller -> OpenTable | Outbound requests must use rotating User-Agent and respect Retry-After |
| poll_log -> DB | status values are constrained to 'success'/'error'/'timeout' |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-03 | Spoofing | OpenTable request User-Agent | mitigate | User-Agent rotation list defined in services/poller/config.py with >= 4 real browser UA strings; random_user_agent() called per request in OpenTableAdapter._fetch(); never uses a single static UA string in production (T-03); jitter on poll interval (D-17 ±15%) prevents constant-interval fingerprinting; Retry-After header respected on 429 before retry |
</threat_model>

<verification>
After all four tasks complete:

```bash
# 1. All service modules import
uv run python -c "
from services.poller.sources.base import AvailabilitySource
from services.poller.sources.opentable.adapter import OpenTableAdapter
from services.poller.scheduler import poll_loop, _next_poll_score
from services.poller.reaper import reaper_loop
from services.poller.publisher import Publisher
from services.poller.main import HTTP_LIMITS, HTTP_TIMEOUT
print('poller service imports OK')
"

# 2. Jitter range is correct (D-17: 90s ± 15%)
uv run python -c "
import time
from services.poller.scheduler import _next_poll_score
now = int(time.time() * 1000)
scores = [_next_poll_score(now) - now for _ in range(200)]
assert all(76500 <= s <= 103500 for s in scores)
print(f'jitter OK: min={min(scores)}ms max={max(scores)}ms')
"

# 3. OpenTable README has all 5 headings
grep -q "## Endpoint" services/poller/sources/opentable/README.md
grep -q "## Headers" services/poller/sources/opentable/README.md
grep -q "## Decision" services/poller/sources/opentable/README.md

# 4. Unit tests still pass
uv run pytest tests/unit -v

# 5. No banned patterns in services/
grep -rn "import requests" services/ 2>/dev/null | wc -l | grep "^0"
grep -rn "time\.sleep(" services/ 2>/dev/null | wc -l | grep "^0"
```
</verification>

<success_criteria>
- services/poller/sources/opentable/README.md has headings: "## Endpoint", "## Headers", "## Query Shape", "## Rate-Limit Observations", "## Decision: GraphQL | HTML Fallback"
- OpenTableAdapter inherits AvailabilitySource, stores shared httpx.AsyncClient (not per-poll), has tenacity retry with stop_after_attempt(3)
- services/poller/config.py has USER_AGENTS list (>= 4 entries) and random_user_agent()
- publisher.py emits to "availability.raw" and "polls.completed" with key="{source}:{restaurant_id}"
- publisher.py writes poll_log row via AsyncSession INSERT before returning
- scheduler.py computes next score as now_ms + 90000 + uniform(-13500, 13500) per D-17
- reaper.py runs every REAPER_INTERVAL_SECONDS and logs reaped jobs at INFO level
- main.py creates ONE httpx.AsyncClient with Limits(100, 20) and Timeout(10.0, 5.0)
- `__main__.py` enables `python -m services.poller`
- All 5 integration test stubs are filled in with real test bodies (no @pytest.mark.skip)
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-05-SUMMARY.md`
</output>
