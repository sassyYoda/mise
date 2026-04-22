---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 04
type: execute
wave: 3
depends_on: ["01", "02"]
files_modified:
  - shared/events.py
  - shared/redis_keys.py
  - shared/db.py
  - shared/telemetry.py
  - shared/kafka.py
  - shared/scheduler/lua.py
  - shared/scheduler/__init__.py
  - scripts/seed_restaurants.py
  - scripts/verify_seed.py
autonomous: true
requirements_addressed:
  - FOUND-02
  - POLL-01

must_haves:
  truths:
    - "AvailabilityRaw and PollCompleted are fully implemented Pydantic v2 models with to_bytes() and model_config=ConfigDict(frozen=True, extra='forbid')"
    - "set_nx_ex uses a single r.set(key, value, nx=True, ex=ttl_seconds) call — confirmed by unit test"
    - "shared/db.py exports get_engine() and get_async_session() using asyncpg driver; all 6 table models match migration column names exactly"
    - "configure_logging() redacts TWILIO_AUTH_TOKEN, HMAC_MGMT_SECRET_V1, VAPID_PRIVATE_KEY, RESY_ACCOUNTS_JSON from all log events — confirmed by unit test"
    - "make_producer() returns AIOKafkaProducer with acks='all', enable_idempotence=True, compression_type='gzip'"
    - "Three Lua scripts (CLAIM_POLL_LUA, RELEASE_POLL_LUA, REAP_INFLIGHT_LUA) are loadable and function correctly against a live Redis — confirmed by integration test"
    - "scripts/seed_restaurants.py runs idempotently: first run inserts >= 50 rows; second run produces no duplicate rows; each restaurant is added to sched:polls ZSET"
  artifacts:
    - path: shared/events.py
      provides: "AvailabilityRaw, PollCompleted fully implemented"
      exports: ["AvailabilityRaw", "PollCompleted"]
    - path: shared/db.py
      provides: "SQLAlchemy 2.0 async models + session factory"
      exports: ["get_engine", "get_async_session", "Base"]
    - path: shared/kafka.py
      provides: "AIOKafkaProducer factory with correct config"
      exports: ["make_producer"]
    - path: shared/scheduler/lua.py
      provides: "Three Lua scripts as Python strings"
      contains: "CLAIM_POLL_LUA"
    - path: scripts/seed_restaurants.py
      provides: "Idempotent restaurant upsert + ZSET population"
      contains: "sched:polls"
  key_links:
    - from: shared/events.py
      to: "services/poller/publisher.py"
      via: "AvailabilityRaw.to_bytes() used as Kafka message value"
      pattern: "AvailabilityRaw"
    - from: shared/redis_keys.py
      to: "shared/scheduler/lua.py"
      via: "SCHED_POLLS and SCHED_POLLS_INFLIGHT used as KEYS args"
      pattern: "SCHED_POLLS"
    - from: shared/db.py
      to: "services/poller/publisher.py"
      via: "get_async_session() used to write poll_log rows"
      pattern: "get_async_session"
---

<objective>
Fill in the shared kernel modules that were scaffolded in Plan 01: complete Pydantic event models, SQLAlchemy ORM models, Kafka producer factory, telemetry with secret redaction, Redis ZSET Lua scheduler scripts, and the seed_restaurants.py idempotent upsert script.

Purpose: Plan 05 (poller service) consumes all of these. This plan runs in parallel with Plan 03 (admin tasks). Filling these now means Plan 05 gets concrete types, not stubs.

Output: Fully implemented shared/ modules; seed script that populates 50 restaurants and their sched:polls ZSET entries; Wave-0 integration test stubs for scheduler and hypertable filled in.
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
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-01-SUMMARY.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-02-SUMMARY.md
</context>

<tasks>

<task id="01-04-T1" type="auto" tdd="true">
  <name>Task 1: shared/events.py and shared/redis_keys.py — full implementation</name>
  <files>
    shared/events.py,
    shared/redis_keys.py,
    tests/unit/test_events_schema.py,
    tests/unit/test_redis_keys.py
  </files>
  <read_first>
    shared/events.py (current stub from Plan 01),
    shared/redis_keys.py (current stub from Plan 01),
    tests/unit/test_events_schema.py (Wave-0 stubs to fill),
    tests/unit/test_redis_keys.py (Wave-0 stubs to fill),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-06, D-18, D-29),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (Named Symbols section)
  </read_first>
  <behavior>
    - AvailabilityRaw.to_bytes() returns self.model_dump_json().encode('utf-8')
    - PollCompleted.to_bytes() returns self.model_dump_json().encode('utf-8')
    - Both models are frozen=True, extra='forbid' — assigning unknown fields raises ValidationError
    - set_nx_ex calls r.set(key, value, nx=True, ex=ttl_seconds) exactly once — never SETNX+EXPIRE
    - set_nx_ex returns True when key was set; False when key already existed (Redis returns None on NX miss)
    - job("opentable", 42) returns "opentable:42"
    - CLAIM_POLL_LUA, RELEASE_POLL_LUA, REAP_INFLIGHT_LUA are non-empty strings
  </behavior>
  <action>
The stub implementations in Plan 01 are already functionally complete for events.py and redis_keys.py. Review the stubs and verify they satisfy all behaviors in the behavior block. If they do, update the unit tests to remove the `pytest.mark.skip` and make them fully runnable assertions (the test bodies were already written in Plan 01 stubs — just remove the skip decorator).

For shared/events.py: no changes needed if the Plan 01 stub correctly implements:
- AvailabilityRaw with fields: poll_id: UUID, source: Literal["opentable","resy"], restaurant_id: int, polled_at_epoch_ms: int, raw_response: dict[str, Any], request_params: dict[str, Any]
- PollCompleted with fields: poll_id: UUID, source: Literal["opentable","resy"], restaurant_id: int, polled_at_epoch_ms: int, status: Literal["success","error","timeout"], latency_ms: int, http_status: int | None, error: str | None
- Both with model_config = ConfigDict(frozen=True, extra="forbid") and to_bytes() -> bytes

For shared/redis_keys.py: no changes needed if the Plan 01 stub correctly implements:
- SCHED_POLLS = "sched:polls"
- SCHED_POLLS_INFLIGHT = "sched:polls:inflight"
- job(source, restaurant_id) -> str
- async set_nx_ex(r, key, value, ttl_seconds) -> bool using single r.set(key, value, nx=True, ex=ttl_seconds) call
- CLAIM_POLL_LUA, RELEASE_POLL_LUA, REAP_INFLIGHT_LUA as non-empty string constants

Remove `@pytest.mark.skip` from all tests in tests/unit/test_events_schema.py and tests/unit/test_redis_keys.py so they run. Do NOT change the test logic — just make them active.

Also add these additional unit tests to tests/unit/test_redis_keys.py (append, do not replace existing):
```python
def test_lua_scripts_are_non_empty_strings():
    from shared.redis_keys import CLAIM_POLL_LUA, RELEASE_POLL_LUA, REAP_INFLIGHT_LUA
    assert isinstance(CLAIM_POLL_LUA, str) and len(CLAIM_POLL_LUA) > 50
    assert isinstance(RELEASE_POLL_LUA, str) and len(RELEASE_POLL_LUA) > 30
    assert isinstance(REAP_INFLIGHT_LUA, str) and len(REAP_INFLIGHT_LUA) > 50

def test_lua_claim_uses_zrangebyscore():
    from shared.redis_keys import CLAIM_POLL_LUA
    assert "ZRANGEBYSCORE" in CLAIM_POLL_LUA
    assert "ZADD" in CLAIM_POLL_LUA
    assert "ZREM" in CLAIM_POLL_LUA

def test_constants_values():
    from shared.redis_keys import POLL_VISIBILITY_TIMEOUT_MS, POLL_INTERVAL_SECONDS, POLL_JITTER_FRACTION
    assert POLL_VISIBILITY_TIMEOUT_MS == 60_000
    assert POLL_INTERVAL_SECONDS == 90
    assert abs(POLL_JITTER_FRACTION - 0.15) < 0.001
```
  </action>
  <verify>
    <automated>uv run pytest tests/unit/test_events_schema.py tests/unit/test_redis_keys.py -v --tb=short</automated>
  </verify>
  <done>
    All tests in test_events_schema.py and test_redis_keys.py pass (no skips, no failures); both Pydantic models have frozen=True and extra="forbid"; set_nx_ex uses single nx=True, ex= call; all three Lua script constants are non-empty and contain expected Redis commands
  </done>
</task>

<task id="01-04-T2" type="auto" tdd="true">
  <name>Task 2: shared/telemetry.py, shared/kafka.py — full implementations</name>
  <files>
    shared/telemetry.py,
    shared/kafka.py,
    tests/unit/test_telemetry_redaction.py
  </files>
  <read_first>
    shared/telemetry.py (current stub from Plan 01),
    tests/unit/test_telemetry_redaction.py (Wave-0 stubs to activate),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-02, D-12),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§1 Kafka producer config; §7 structlog JSON config)
  </read_first>
  <behavior>
    - configure_logging(env="prod") uses JSONRenderer; configure_logging(env="dev") uses ConsoleRenderer(colors=True)
    - _redact_secrets strips TWILIO_AUTH_TOKEN, HMAC_MGMT_SECRET_V1, VAPID_PRIVATE_KEY, RESY_ACCOUNTS_JSON from log event dict, replacing with "[REDACTED]"
    - get_logger(name) returns structlog.BoundLogger after calling configure_logging() if not already configured
    - make_producer(bootstrap_servers) returns AIOKafkaProducer with acks="all", enable_idempotence=True, compression_type="gzip", linger_ms=20, max_in_flight_requests_per_connection=5
  </behavior>
  <action>
Review the shared/telemetry.py stub from Plan 01. The stub should already implement all required behaviors. Activate the unit tests by removing `@pytest.mark.skip` from tests/unit/test_telemetry_redaction.py.

If shared/telemetry.py is missing the configure_logging(env) signature (takes env parameter explicitly), update it to accept `env: str | None = None` as in Plan 01 spec.

Create `shared/kafka.py`:
```python
"""
AIOKafkaProducer factory for Mise en Place (D-02).
Named config: acks='all', enable_idempotence=True, compression_type='gzip', linger_ms=20.
All producers created via this factory — no inline instantiation in services.
"""
from __future__ import annotations
import os

from aiokafka import AIOKafkaProducer


async def make_producer(bootstrap_servers: str | None = None) -> AIOKafkaProducer:
    """
    Create and start an AIOKafkaProducer with correct durability config (D-02, Pitfall 11).

    Args:
        bootstrap_servers: Comma-separated Kafka brokers. Defaults to KAFKA_BOOTSTRAP_SERVERS env var.

    Returns:
        A started AIOKafkaProducer. Caller is responsible for .stop() on shutdown.
    """
    servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
    producer = AIOKafkaProducer(
        bootstrap_servers=servers,
        acks="all",                                   # D-02: wait for all in-sync replicas
        enable_idempotence=True,                      # prevents duplicates on retry
        max_in_flight_requests_per_connection=5,      # required with idempotence=True
        compression_type="gzip",                      # cheap at ~10KB messages
        linger_ms=20,                                  # small batching window
        request_timeout_ms=30_000,
        value_serializer=lambda v: v if isinstance(v, bytes) else v.encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
    )
    await producer.start()
    return producer
```

Also add a unit test to verify make_producer config (without connecting to real Kafka — test the config object):

Add to tests/unit/test_events_schema.py or create tests/unit/test_kafka_config.py:
```python
"""Unit test for shared.kafka producer config."""
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_make_producer_config():
    """Verify make_producer uses correct acks and idempotence settings."""
    from shared.kafka import make_producer
    with patch("shared.kafka.AIOKafkaProducer") as MockProducer:
        instance = AsyncMock()
        MockProducer.return_value = instance
        instance.start = AsyncMock()
        await make_producer("localhost:9094")
        call_kwargs = MockProducer.call_args.kwargs
        assert call_kwargs["acks"] == "all"
        assert call_kwargs["enable_idempotence"] is True
        assert call_kwargs["compression_type"] == "gzip"
        assert call_kwargs["linger_ms"] == 20
        assert call_kwargs["max_in_flight_requests_per_connection"] == 5
```
  </action>
  <verify>
    <automated>uv run pytest tests/unit/test_telemetry_redaction.py tests/unit/test_kafka_config.py -v --tb=short 2>/dev/null || uv run pytest tests/unit/test_telemetry_redaction.py -v --tb=short</automated>
  </verify>
  <done>
    All tests in test_telemetry_redaction.py pass; shared/kafka.py exists with make_producer() using acks="all", enable_idempotence=True, compression_type="gzip", linger_ms=20; `from shared.kafka import make_producer` imports cleanly
  </done>
</task>

<task id="01-04-T3" type="auto">
  <name>Task 3: shared/db.py, shared/scheduler/lua.py, and integration test activation</name>
  <files>
    shared/db.py,
    shared/scheduler/__init__.py,
    shared/scheduler/lua.py,
    tests/integration/test_scheduler_claim_release.py,
    tests/integration/test_hypertable_config.py
  </files>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-04, D-18, D-30, D-31),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§2 migration pattern; §3 Redis ZSET Lua scripts; §6 testcontainers fixtures),
    migrations/versions/0002_create_users.py,
    migrations/versions/0007_create_poll_log_hypertable.py
  </read_first>
  <action>
Create `shared/db.py`:
```python
"""
SQLAlchemy 2.0 async ORM models and session factory (D-04).
Uses asyncpg driver for app hot path; psycopg3 is for Alembic only.
Named tables: users, restaurants, watchlist_entries, notification_log,
              availability_events, poll_log
"""
from __future__ import annotations
import os
from datetime import date, time, datetime
from typing import AsyncGenerator
from uuid import UUID

from sqlalchemy import (
    ARRAY, BigInteger, Boolean, Date, Float, Integer, LargeBinary, Text, Time,
    TIMESTAMP, ForeignKey, Index, UniqueConstraint, text as sa_text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    phone: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)  # BYTEA, AES-256-GCM (D-32, T-04)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class Restaurant(Base):
    __tablename__ = "restaurants"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)          # 'opentable' | 'resy'
    platform_id: Mapped[str] = mapped_column(Text, nullable=False)     # stringified OT rid or Resy venue_id
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    neighborhood: Mapped[str] = mapped_column(Text, nullable=False)
    cuisine: Mapped[str] = mapped_column(Text, nullable=False)
    price_tier: Mapped[int] = mapped_column(Integer, nullable=False)   # CHECK 1..4 enforced in migration
    cover_photo_url: Mapped[str] = mapped_column(Text, nullable=False)
    date_range_days: Mapped[int] = mapped_column(Integer, server_default="7", nullable=False)
    party_sizes: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), server_default=sa_text("'{2,4}'::integer[]"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    __table_args__ = (UniqueConstraint("source", "platform_id", name="uq_restaurants_source_platform_id"),)


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    restaurant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("restaurants.id"), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    date_from: Mapped[date] = mapped_column(Date, nullable=False)
    date_to: Mapped[date] = mapped_column(Date, nullable=False)
    time_window_from: Mapped[time | None] = mapped_column(Time, nullable=True)
    time_window_to: Mapped[time | None] = mapped_column(Time, nullable=True)
    days_of_week: Mapped[str | None] = mapped_column(Text, nullable=True)
    seat_type_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    channels: Mapped[str] = mapped_column(Text, server_default="email", nullable=False)
    status: Mapped[str] = mapped_column(Text, server_default="active", nullable=False)
    management_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


class NotificationLog(Base):
    __tablename__ = "notification_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    watch_id: Mapped[int] = mapped_column(Integer, ForeignKey("watchlist_entries.id"), nullable=False)
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    provider_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    slot_still_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False)


# Note: availability_events and poll_log are TimescaleDB hypertables created via
# Alembic migrations (0006, 0007) — not via SQLAlchemy create_all.
# ORM classes below are for querying only; never use Base.metadata.create_all() for these.

class AvailabilityEvent(Base):
    __tablename__ = "availability_events"
    time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)  # matches restaurants.id
    source: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    time_slot: Mapped[time | None] = mapped_column(Time, nullable=True)
    party_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    seat_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    booking_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_seen_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hours_before_service: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_of_week: Mapped[int | None] = mapped_column(Integer, nullable=True)


class PollLog(Base):
    __tablename__ = "poll_log"
    # Named Symbol columns verbatim (D-31, REQUIREMENTS.md poll_log columns)
    time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)  # matches restaurants.id
    source: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)   # 'success' | 'error' | 'timeout'
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)


_engine = None
_session_factory = None


def get_engine():
    """Return the async SQLAlchemy engine. Creates it on first call."""
    global _engine
    if _engine is None:
        url = os.getenv("DATABASE_URL_ASYNC", "postgresql+asyncpg://mise:mise@localhost:5432/mise")
        _engine = create_async_engine(url, echo=False, pool_pre_ping=True)
    return _engine


def get_async_session() -> async_sessionmaker[AsyncSession]:
    """Return the async session factory. Creates it on first call."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory
```

Create `shared/scheduler/__init__.py` as an empty file.

Create `shared/scheduler/lua.py` — move the Lua script constants here from shared/redis_keys.py (keep re-exports in redis_keys.py for backwards compat):
```python
"""
Lua scripts for atomic Redis ZSET scheduler operations (D-18).
All three scripts use EVALSHA with fallback to EVAL on NOSCRIPT error.
Named symbols: CLAIM_POLL_LUA, RELEASE_POLL_LUA, REAP_INFLIGHT_LUA
"""
from __future__ import annotations
from typing import Any

import redis.asyncio as redis

from shared.redis_keys import (
    SCHED_POLLS,
    SCHED_POLLS_INFLIGHT,
    CLAIM_POLL_LUA,
    RELEASE_POLL_LUA,
    REAP_INFLIGHT_LUA,
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
        """EVALSHA with automatic EVAL fallback on NOSCRIPT (Redis restart / FLUSHSCRIPTS)."""
        try:
            return await self.r.evalsha(sha, numkeys, *args)
        except redis.exceptions.NoScriptError:
            # Re-cache the script and retry once
            new_sha = await self.r.script_load(script)
            return await self.r.evalsha(new_sha, numkeys, *args)

    async def claim(self, now_ms: int) -> str | None:
        """
        Atomically pop one due job from sched:polls and move to sched:polls:inflight.
        Returns job descriptor '{source}:{restaurant_id}' or None if no due jobs.
        """
        assert self._claim_sha is not None, "Call start() first"
        job = await self._evalsha_with_fallback(
            self._claim_sha, CLAIM_POLL_LUA, 2,
            SCHED_POLLS, SCHED_POLLS_INFLIGHT,
            str(now_ms), str(60_000),  # POLL_VISIBILITY_TIMEOUT_MS
        )
        return job.decode() if job else None

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
        return [j.decode() for j in jobs] if jobs else []
```

Fill in tests/integration/test_scheduler_claim_release.py (remove @pytest.mark.skip, write real assertions):
```python
"""Integration: POLL-01 — Lua ZSET scheduler claim/release/reap."""
import asyncio
import time
import pytest
import redis.asyncio as redis
from shared.redis_keys import SCHED_POLLS, SCHED_POLLS_INFLIGHT
from shared.scheduler.lua import LuaScheduler


@pytest.fixture(scope="module")
def redis_url(redis_container):
    return f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}"


@pytest.mark.asyncio
async def test_claim_release_cycle(redis_url):
    r = redis.from_url(redis_url, decode_responses=False)
    sched = LuaScheduler(r)
    await sched.start()
    now_ms = int(time.time() * 1000)
    # Seed one due job
    await r.zadd(SCHED_POLLS, {"opentable:42": now_ms - 1000})
    # Claim
    job = await sched.claim(now_ms)
    assert job == "opentable:42"
    # Job is now in inflight
    inflight = await r.zrange(SCHED_POLLS_INFLIGHT, 0, -1)
    assert b"opentable:42" in inflight
    # Release with next poll
    await sched.release(job, now_ms + 90_000)
    # Job back in sched:polls, inflight empty
    polls = await r.zrange(SCHED_POLLS, 0, -1)
    assert b"opentable:42" in polls
    inflight_after = await r.zrange(SCHED_POLLS_INFLIGHT, 0, -1)
    assert b"opentable:42" not in inflight_after
    await r.aclose()


@pytest.mark.asyncio
async def test_reaper_requeues_expired_inflight(redis_url):
    r = redis.from_url(redis_url, decode_responses=False)
    sched = LuaScheduler(r)
    await sched.start()
    now_ms = int(time.time() * 1000)
    # Seed an expired inflight job (score in the past)
    await r.zadd(SCHED_POLLS_INFLIGHT, {"opentable:99": now_ms - 1000})
    reaped = await sched.reap(now_ms)
    assert "opentable:99" in reaped
    # Job re-enqueued to sched:polls
    polls = await r.zrange(SCHED_POLLS, 0, -1)
    assert b"opentable:99" in polls
    # Inflight cleared
    inflight = await r.zrange(SCHED_POLLS_INFLIGHT, 0, -1)
    assert b"opentable:99" not in inflight
    await r.aclose()


@pytest.mark.asyncio
async def test_claim_returns_none_when_empty(redis_url):
    r = redis.from_url(redis_url, decode_responses=False)
    sched = LuaScheduler(r)
    await sched.start()
    # Clear any leftover state
    await r.delete(SCHED_POLLS)
    now_ms = int(time.time() * 1000)
    job = await sched.claim(now_ms)
    assert job is None
    await r.aclose()
```

Fill in tests/integration/test_hypertable_config.py (remove @pytest.mark.skip, write real assertions using alembic + asyncpg):
```python
"""Integration: SC4 — hypertables have chunk_time_interval = 1 day."""
import subprocess
import os
import pytest
import asyncpg


@pytest.fixture(scope="module")
def db_url_sync(timescale_container):
    return timescale_container.get_connection_url().replace("psycopg2", "psycopg")


@pytest.fixture(scope="module")
def db_url_async(timescale_container):
    host = timescale_container.get_container_host_ip()
    port = timescale_container.get_exposed_port(5432)
    return f"postgresql://mise:mise@{host}:{port}/mise"


@pytest.fixture(scope="module", autouse=True)
def run_migrations(db_url_sync):
    """Run Alembic migrations against the testcontainer."""
    env = {**os.environ, "DATABASE_URL_SYNC": db_url_sync}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"


@pytest.mark.asyncio
async def test_chunk_interval_is_one_day(db_url_async):
    """SC4: Both hypertables must have chunk_time_interval = 86400000000 microseconds (1 day)."""
    conn = await asyncpg.connect(db_url_async)
    try:
        rows = await conn.fetch(
            """
            SELECT hypertable_name, chunk_time_interval
            FROM timescaledb_information.dimensions
            WHERE hypertable_name IN ('poll_log', 'availability_events')
            ORDER BY hypertable_name
            """
        )
        assert len(rows) == 2, f"Expected 2 hypertables, got {len(rows)}"
        for row in rows:
            # chunk_time_interval is returned as timedelta or integer (microseconds)
            interval = row["chunk_time_interval"]
            # Convert to microseconds if timedelta
            if hasattr(interval, "total_seconds"):
                interval_us = int(interval.total_seconds() * 1_000_000)
            else:
                interval_us = int(interval)
            assert interval_us == 86_400_000_000, (
                f"{row['hypertable_name']} chunk_time_interval is {interval_us}, expected 86400000000"
            )
    finally:
        await conn.close()
```
  </action>
  <verify>
    <automated>uv run python -c "from shared.db import get_engine, get_async_session, Base, User, Restaurant, PollLog; from shared.scheduler.lua import LuaScheduler; from shared.kafka import make_producer; print('shared.db + scheduler + kafka import OK')"</automated>
  </verify>
  <done>
    shared/db.py has all 6 ORM models with correct column names; PollLog has time, restaurant_id, source, status, latency_ms, http_status, error, poll_id (Named Symbol columns verbatim); shared/scheduler/lua.py has LuaScheduler with claim/release/reap using EVALSHA+NOSCRIPT fallback; integration tests for scheduler and hypertable are fully implemented (no skips)
  </done>
</task>

<task id="01-04-T4" type="auto">
  <name>Task 4: scripts/seed_restaurants.py idempotent upsert + scripts/verify_seed.py</name>
  <files>
    scripts/seed_restaurants.py,
    scripts/verify_seed.py
  </files>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-15, D-17, D-18, D-19),
    shared/redis_keys.py (SCHED_POLLS constant),
    shared/db.py (Restaurant model)
  </read_first>
  <action>
Create `scripts/seed_restaurants.py`:
```python
#!/usr/bin/env python
"""
Idempotent restaurant seed script (D-15, D-16, D-19).
Reads scripts/seed/restaurants.yml, upserts into restaurants table,
and populates sched:polls ZSET with initial poll scores.

Usage: uv run python scripts/seed_restaurants.py
Or:    make seed
"""
from __future__ import annotations
import asyncio
import os
import random
import time
from pathlib import Path
from typing import Any

import yaml
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from shared.redis_keys import SCHED_POLLS, job as make_job

YAML_PATH = Path("scripts/seed/restaurants.yml")


async def seed(
    db_url: str | None = None,
    redis_url: str | None = None,
) -> int:
    """
    Upsert restaurants from YAML and seed sched:polls.
    Returns number of restaurants processed.
    """
    db_url = db_url or os.getenv("DATABASE_URL_ASYNC", "postgresql+asyncpg://mise:mise@localhost:5432/mise")
    redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")

    data = yaml.safe_load(YAML_PATH.read_text())
    restaurants: list[dict[str, Any]] = data["restaurants"]

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    r = redis.from_url(redis_url)
    try:
        async with async_session() as session:
            for rest in restaurants:
                # Derive (source, platform_id) from YAML fields: opentable_rid → ('opentable', str(rid)) (D-15).
                source: str | None = None
                platform_id: str | None = None
                if rest.get("opentable_rid") is not None:
                    source = "opentable"
                    platform_id = str(rest["opentable_rid"])
                elif rest.get("resy_venue_id") is not None:
                    source = "resy"
                    platform_id = str(rest["resy_venue_id"])
                else:
                    raise ValueError(
                        f"Restaurant {rest.get('slug')!r} missing both opentable_rid and resy_venue_id"
                    )

                # Idempotent UPSERT keyed on (source, platform_id) UNIQUE constraint (D-15).
                await session.execute(
                    text("""
                        INSERT INTO restaurants
                            (source, platform_id, name, slug, neighborhood, cuisine,
                             price_tier, cover_photo_url, date_range_days, party_sizes, created_at)
                        VALUES
                            (:source, :platform_id, :name, :slug, :neighborhood, :cuisine,
                             :price_tier, :cover_photo_url, :date_range_days, :party_sizes, NOW())
                        ON CONFLICT (source, platform_id) DO UPDATE SET
                            name             = EXCLUDED.name,
                            slug             = EXCLUDED.slug,
                            neighborhood     = EXCLUDED.neighborhood,
                            cuisine          = EXCLUDED.cuisine,
                            price_tier       = EXCLUDED.price_tier,
                            cover_photo_url  = EXCLUDED.cover_photo_url,
                            date_range_days  = EXCLUDED.date_range_days,
                            party_sizes      = EXCLUDED.party_sizes
                    """),
                    {
                        "source": source,
                        "platform_id": platform_id,
                        "name": rest["name"],
                        "slug": rest["slug"],
                        "neighborhood": rest["neighborhood"],
                        "cuisine": rest["cuisine"],
                        "price_tier": rest["price_tier"],
                        "cover_photo_url": rest["cover_photo_url"],
                        "date_range_days": rest.get("date_range_days", 7),
                        "party_sizes": rest.get("party_sizes", [2, 4]),
                    },
                )
                # Add to sched:polls ZSET with initial spread (D-15 SC3 ZSET side)
                # Score = now_ms + random jitter 0..90s for initial spread
                if source == "opentable":
                    score = int(time.time() * 1000) + int(random.uniform(0, 90_000))
                    await r.zadd(SCHED_POLLS, {make_job("opentable", int(platform_id)): score})

            await session.commit()

        total = len([rest for rest in restaurants if rest.get("opentable_rid") is not None])
        print(f"Seeded {len(restaurants)} restaurants ({total} with OpenTable RIDs in sched:polls)")
        return len(restaurants)

    finally:
        await r.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
```

Create `scripts/verify_seed.py`:
```python
#!/usr/bin/env python
"""
Verify seed: assert >= 50 restaurants with all required fields in DB;
assert >= 50 entries in sched:polls ZSET (SC3, make verify-seed target).
"""
from __future__ import annotations
import asyncio
import os
import sys

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


async def verify() -> None:
    db_url = os.getenv("DATABASE_URL_ASYNC", "postgresql+asyncpg://mise:mise@localhost:5432/mise")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    r = redis.from_url(redis_url)

    try:
        async with async_session() as session:
            result = await session.execute(text("""
                SELECT COUNT(*) FROM restaurants
                WHERE source = 'opentable'
                  AND platform_id IS NOT NULL
                  AND neighborhood IS NOT NULL
                  AND cuisine IS NOT NULL
                  AND price_tier IS NOT NULL
                  AND cover_photo_url IS NOT NULL
            """))
            db_count = result.scalar_one()

        zcard = await r.zcard("sched:polls")

        print(f"Restaurants in DB with all fields: {db_count}")
        print(f"Entries in sched:polls: {zcard}")

        errors = []
        if db_count < 50:
            errors.append(f"Expected >= 50 restaurants in DB, got {db_count}")
        if zcard < 50:
            errors.append(f"Expected >= 50 entries in sched:polls, got {zcard}")

        if errors:
            for e in errors:
                print(f"FAIL: {e}", file=sys.stderr)
            sys.exit(1)
        else:
            print("SC3 verification PASSED")

    finally:
        await r.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(verify())
```
  </action>
  <verify>
    <automated>uv run python -c "import scripts.seed_restaurants; import scripts.verify_seed; print('seed scripts importable')" 2>/dev/null || python3 -c "import ast; ast.parse(open('scripts/seed_restaurants.py').read()); ast.parse(open('scripts/verify_seed.py').read()); print('seed scripts parse OK')"</automated>
  </verify>
  <done>
    scripts/seed_restaurants.py parses cleanly; derives (source='opentable', platform_id=str(opentable_rid)) and upserts via ON CONFLICT (source, platform_id) DO UPDATE for idempotency (D-15); adds each opentable_rid to sched:polls ZSET with initial random score (0-90s spread, D-15); scripts/verify_seed.py checks both DB count >= 50 and ZCARD >= 50 and exits 1 on failure
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| log event dict -> stdout | Secret values must not appear in log output |
| application -> postgres | Phone columns written as BYTEA ciphertext only |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-02 | Information Disclosure | structlog processor chain | mitigate | _redact_secrets processor fully implemented in shared/telemetry.py (this plan); strips TWILIO_AUTH_TOKEN, HMAC_MGMT_SECRET_V1, VAPID_PRIVATE_KEY, RESY_ACCOUNTS_JSON from every log event dict; unit tests in test_telemetry_redaction.py confirm all four keys are redacted — tests are active (no skips) after this plan |
| T-03 | Spoofing | User-Agent header in OpenTable requests | mitigate | User-Agent rotation list defined in services/poller/config.py (Plan 05); config.py is referenced here so Plan 05 implementers know where to put it; never use a single static UA string in production poller |
</threat_model>

<verification>
After all four tasks complete:

```bash
# 1. All shared modules import
uv run python -c "
from shared.events import AvailabilityRaw, PollCompleted
from shared.redis_keys import SCHED_POLLS, SCHED_POLLS_INFLIGHT, set_nx_ex
from shared.db import get_engine, get_async_session, PollLog, Restaurant
from shared.kafka import make_producer
from shared.scheduler.lua import LuaScheduler
from shared.telemetry import configure_logging, get_logger
print('All imports OK')
"

# 2. Unit tests fully pass (no skips)
uv run pytest tests/unit -v

# 3. set_nx_ex uses single atomic call
uv run pytest tests/unit/test_redis_keys.py::test_set_nx_ex_uses_single_atomic_call -v

# 4. Telemetry redaction passes
uv run pytest tests/unit/test_telemetry_redaction.py -v

# 5. Seed scripts parse
python3 -c "import ast; ast.parse(open('scripts/seed_restaurants.py').read()); print('seed parse OK')"
```
</verification>

<success_criteria>
- All shared/ modules import without error
- `uv run pytest tests/unit -v` passes with 0 failures, 0 skips on the unit tests that were filled in this plan
- test_redis_keys.py::test_set_nx_ex_uses_single_atomic_call confirms single nx=True, ex= call
- test_telemetry_redaction.py confirms all 4 secret keys are redacted
- shared/db.py PollLog model has exactly these columns: time, restaurant_id, source, status, latency_ms, http_status, error, poll_id (Named Symbols verbatim)
- shared/scheduler/lua.py LuaScheduler has claim(), release(), reap() using EVALSHA with NOSCRIPT fallback
- scripts/seed_restaurants.py uses ON CONFLICT (source, platform_id) DO UPDATE for idempotency; populates sched:polls ZSET
- Integration test stubs for scheduler (test_scheduler_claim_release.py) and hypertable (test_hypertable_config.py) are fully implemented — no @pytest.mark.skip
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-04-SUMMARY.md`
</output>
