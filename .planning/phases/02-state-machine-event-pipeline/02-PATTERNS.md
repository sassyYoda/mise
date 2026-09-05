# Phase 2: State Machine & Event Pipeline - Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 32 (new/modified)
**Analogs found:** 28 / 32

Scope drawn from 02-CONTEXT.md (D-36..D-56) and 02-RESEARCH.md (§Recommended Project Structure, §Blocking Corrections).

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/state_machine/__init__.py` | package | — | `services/poller/__init__.py` | exact |
| `services/state_machine/__main__.py` | entrypoint | — | `services/poller/__main__.py` | exact |
| `services/state_machine/main.py` | service lifecycle | event-driven | `services/poller/main.py` | exact |
| `services/state_machine/config.py` | config | — | `services/poller/config.py` | exact |
| `services/state_machine/consumer.py` | consumer shell (side effects) | event-driven / pub-sub | `services/poller/scheduler.py` (loop) + `services/poller/publisher.py` (emit+persist) | role-match |
| `services/state_machine/engine.py` | pure domain core | transform | *(none — new kind of module)* | no analog (see §No Analog Found) |
| `services/state_machine/models.py` | model (pure dataclasses/enum) | — | `shared/events.py` (declaration style) / `scripts/check_poll_success.py::HourlyBucket` | partial |
| `services/state_machine/store.py` | store / repository | CRUD (Redis) | `shared/scheduler/lua.py::LuaScheduler` | role-match |
| `services/state_machine/persistence.py` | persistence service | CRUD (SQL) | `services/poller/publisher.py` (step 3, lines 92-107) | exact |
| `services/state_machine/parsers/__init__.py` | registry / dispatch | transform | `services/poller/sources/base.py` (abstraction) + `services/poller/scheduler.py:86-97` (source dispatch) | partial |
| `services/state_machine/parsers/opentable.py` | parser | transform | `services/poller/sources/opentable/graphql.py` + `.../fixtures.py` (payload shape) | role-match |
| `services/state_machine/parsers/errors.py` | errors | — | *(none — repo has no custom exception module)* | no analog |
| `services/state_machine/README.md` | doc | — | `services/poller/sources/opentable/README.md` | role-match |
| `shared/events.py` (+`AvailabilityEvent`, `NAMESPACE_MISE`) | model | pub-sub schema | `shared/events.py::AvailabilityRaw` (same file) | exact |
| `shared/redis_keys.py` (+key helpers, +`EXPEDITE_POLL_LUA`, TTLs) | config / key registry | — | `shared/redis_keys.py::job`/`CLAIM_POLL_LUA` (same file) | exact |
| `shared/kafka.py` (+`make_consumer`) | factory | event-driven | `shared/kafka.py::make_producer` (same file) | exact |
| `shared/scheduler/lua.py` (+`LuaScheduler.expedite`) | service method | CRUD (Redis) | `LuaScheduler.claim` / `.release` (same file) | exact |
| `shared/db.py` (`AvailabilityEvent` ORM PK remap, +`event_id`) | model | CRUD | `shared/db.py::PollLog` (same file) | exact |
| `migrations/versions/0008_add_event_id_to_availability_events.py` | migration | — | `migrations/versions/0007_create_poll_log_hypertable.py` | exact |
| `scripts/replay_raw.py` | CLI script | batch / streaming | `scripts/check_poll_success.py` (exit-code CLI) + `scripts/create_topics.py` (aiokafka) | role-match |
| `services/poller/scheduler.py` (release path, line 138) | modification | event-driven | itself (lines 138-139) | exact |
| `ops/docker-compose.yml` (kafka image, D-56) | config | — | itself (line 5) | exact |
| `Makefile` (+`state-machine`, +`replay`) | config | — | `Makefile:20-21` (`poll` target) | exact |
| `tests/unit/test_parsers_opentable.py` | test | — | `tests/unit/test_ua_rotation.py` / `test_events_schema.py` | role-match |
| `tests/unit/test_engine_transitions.py` | test | — | `tests/unit/test_redis_keys.py` | role-match |
| `tests/unit/test_event_id_determinism.py` | test | — | `tests/unit/test_events_schema.py` | exact |
| `tests/unit/test_coverage_bounding.py` | test | — | `tests/unit/test_redis_keys.py` | role-match |
| `tests/unit/test_no_setnx_expire_pairs.py` | test (source grep) | file-I/O | `.github/workflows/lint.yml` ban-greps + `tests/unit/test_kafka_config.py` | partial |
| `tests/unit/test_replay_byte_identity.py` | test | file-I/O | *(none — no golden-file test exists)* | no analog |
| `tests/integration/test_state_machine_e2e.py` | test | event-driven | `tests/integration/test_poller_smoke.py` | exact |
| `tests/integration/test_expedite_lua.py` | test | CRUD (Redis) | `tests/integration/test_scheduler_claim_release.py` | exact |
| `tests/fixtures/raw_streams/*.jsonl` (+ `.events.jsonl` golden) | fixture data | file-I/O | `services/poller/sources/opentable/fixtures.py` (payload content only) | partial |

---

## Pattern Assignments

### `services/state_machine/main.py` (service lifecycle, event-driven)

**Analog:** `services/poller/main.py` — copy the whole shape: module docstring stating decisions, `REQUIRED_TOPICS` guard, resource construction inside `run()`, nested `try/finally` teardown.

**Module docstring + imports** (`services/poller/main.py:1-32`):
```python
"""Poller service entry point (D-05, D-08).
...
Startup guard: refuses to enter the poll loop unless all 5 Named-Symbol
Kafka topics exist — Plan 02 disables ``auto.create.topics.enable`` so a
missing topic would otherwise fail silently per-publish (D-27).
"""
from __future__ import annotations

import asyncio

import redis.asyncio as redis
from aiokafka.admin import AIOKafkaAdminClient

from services.poller.config import (
    KAFKA_BOOTSTRAP_SERVERS,
    REDIS_URL,
)
...
from shared.kafka import make_producer
from shared.scheduler.lua import LuaScheduler
from shared.telemetry import configure_logging, get_logger

log = get_logger(__name__)
```

**Topic startup guard** (`services/poller/main.py:36-62`) — reuse verbatim (same `REQUIRED_TOPICS` set; `availability.events` is already in it):
```python
async def _assert_topics_exist(bootstrap_servers: str) -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        existing = set(await admin.list_topics())
    finally:
        await admin.close()
    missing = REQUIRED_TOPICS - existing
    if missing:
        raise RuntimeError(
            f"Kafka topics missing: {sorted(missing)}. Run `make topics` first."
        )
```

**Lifecycle pattern** (`services/poller/main.py:65-105`) — note *all* async resources are built inside `run()` (this is exactly what B-1 requires for `AIOKafkaConsumer`):
```python
async def run() -> None:
    configure_logging()
    log.info("poller_starting")
    ...
    r = redis.from_url(REDIS_URL)
    scheduler = LuaScheduler(r)
    await scheduler.start()
    await _assert_topics_exist(KAFKA_BOOTSTRAP_SERVERS)
    producer = await make_producer(KAFKA_BOOTSTRAP_SERVERS)
    ...
    log.info("poller_ready", redis=REDIS_URL, kafka=KAFKA_BOOTSTRAP_SERVERS)
    try:
        await asyncio.gather(poll_loop(...), reaper_loop(scheduler))
    finally:
        await producer.stop()
        await r.aclose()
        log.info("poller_stopped")
```
State-machine version: `await consumer.start()` replaces `scheduler.start()`; teardown adds `await consumer.stop()` before `producer.stop()`. Log events: `state_machine_starting` / `state_machine_ready` / `state_machine_stopped`.

---

### `services/state_machine/__main__.py` (entrypoint)

**Analog:** `services/poller/__main__.py` (whole file, 7 lines) — copy verbatim with the name swapped:
```python
"""Allow ``python -m services.poller`` (D-08, Makefile ``make poll`` target)."""
from __future__ import annotations

import asyncio

from services.poller.main import run

asyncio.run(run())
```

---

### `services/state_machine/config.py` (config)

**Analog:** `services/poller/config.py` — env reads at module scope, re-export shared constants rather than redefining (D-42 mirrors D-17's "single source of truth is `shared.redis_keys`").

**Header + re-export pattern** (`services/poller/config.py:1-16`):
```python
"""Poller service configuration (D-17, D-19, T-03).

Single source of truth for poll scheduling constants is `shared.redis_keys`;
this module re-exports the relevant names so downstream poller code has one
import path for config.
"""
from __future__ import annotations

import os

from shared.redis_keys import (  # noqa: F401 (re-exported for consumers)
    POLL_INTERVAL_SECONDS,
    POLL_JITTER_FRACTION,
)
```

**Env constant pattern** (`services/poller/config.py:43-53`) — copy exact defaults so both services agree:
```python
KAFKA_BOOTSTRAP_SERVERS: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL_ASYNC: str = os.getenv(
    "DATABASE_URL_ASYNC",
    "postgresql+asyncpg://mise:mise@localhost:5432/mise",
)
```
Add: `CONFIRM_DELAY_MS` (re-exported from `shared.redis_keys`, per D-42), `MISE_CRASH_AFTER: str | None = os.getenv("MISE_CRASH_AFTER")`.

---

### `services/state_machine/consumer.py` (side-effect shell, event-driven)

**Analog A (loop skeleton):** `services/poller/scheduler.py::poll_loop`
**Analog B (emit + persist ordering):** `services/poller/publisher.py::Publisher.publish`

**Loop + defensive job/message parsing** (`services/poller/scheduler.py:40-70`):
```python
async def poll_loop(scheduler, opentable, publisher) -> None:
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
```
Adapt to: `async for msg in consumer:` (or `await consumer.getone()`), route on `msg.topic`, `log.warning("unparseable_message", topic=..., offset=...)` and still commit poison messages.

**Error-handling / never-die pattern** (`services/poller/scheduler.py:98-124` and `services/poller/reaper.py:34-35`) — the repo's house style is typed excepts narrowing to a `# noqa: BLE001` catch-all that logs and continues:
```python
        except Exception as exc:  # noqa: BLE001 — catch-all for operational robustness
            status = "error"
            error_str = str(exc)
            log.error("poll_failed", restaurant_id=restaurant_id, error=error_str)
```
Use this exact shape for the best-effort DB write (D-48: "a DB failure is logged and does not block the Kafka emit").

**Emit pattern — class holding the producer, Kafka key, Named-Symbol comments** (`services/poller/publisher.py:27-73`):
```python
class Publisher:
    """Emits Kafka events and persists ``poll_log`` rows (POLL-07)."""

    def __init__(self, producer: AIOKafkaProducer) -> None:
        self.producer = producer

    async def publish(self, ...) -> None:
        now_ms = int(time.time() * 1000)
        kafka_key = f"{source}:{restaurant_id}"  # Named Symbol: {source}:{restaurant_id}
        ...
        await self.producer.send(
            "availability.raw",  # Named Symbol
            value=raw_event.to_bytes(),
            key=kafka_key,
        )
        log.info("availability_raw_published", poll_id=str(poll_id), restaurant_id=restaurant_id)
```
**Two deliberate deviations for Phase 2** (planner must call these out):
1. Use `await self.producer.send_and_wait("availability.events", ...)` — **not** `send`. `shared/kafka.py:31` sets `linger_ms=20`, so `send` can return before the broker acks and `commit()` would run first (RESEARCH §Pattern 4).
2. `kafka_key` uses `restaurant_id` = platform rid (D-52), same value the poller already puts on the wire (`services/poller/scheduler.py:64-66` derives it from the job descriptor).

**Wall-clock rule:** `now_ms = int(time.time() * 1000)` (publisher.py:51) is correct in the poller and **forbidden** anywhere in `engine.py` / event fields — all Phase 2 timestamps come from `polled_at_epoch_ms` (D-45).

---

### `services/state_machine/store.py` — `RedisStateStore` / `MemoryStateStore` (store, CRUD)

**Analog:** `shared/scheduler/lua.py::LuaScheduler` — class wrapping `redis.Redis`, keys imported from `shared/redis_keys.py`, never inlined.

**Class shape** (`shared/scheduler/lua.py:24-40`):
```python
class LuaScheduler:
    """
    Atomic ZSET scheduler using EVALSHA with NOSCRIPT fallback.
    Implements D-18 visibility-timeout pattern.
    """

    def __init__(self, client: redis.Redis) -> None:
        self.r = client
        self._claim_sha: str | None = None
```

**Bytes-decoding pattern** (`shared/scheduler/lua.py:63-65`, `:84-86`) — `redis.from_url()` is used **without** `decode_responses`, so every read must be decoded defensively:
```python
        if job is None:
            return None
        return job.decode() if isinstance(job, (bytes, bytearray)) else str(job)
```
Apply identically to `HGETALL` results in `RedisStateStore.get_slots()` before `json.loads`.

**Typing note (mypy strict):** redis-py awaitables need the `cast` used at `shared/scheduler/lua.py:47`:
```python
            return await cast(Awaitable[Any], self.r.evalsha(sha, numkeys, *args))
```

**Protocol/ABC precedent:** `services/poller/sources/base.py:9-24` is the repo's existing "swap the implementation" abstraction (`AvailabilitySource(ABC)` with `@abstractmethod async def poll`). D-49 asks for `typing.Protocol` instead of ABC — keep the docstring style ("Concrete implementations: ... (P1), ... (P3)") from that file.

---

### `services/state_machine/persistence.py` (persistence, CRUD)

**Analog:** `services/poller/publisher.py:92-107` — the only async-SQLAlchemy write in the repo.

```python
        # 3. Write poll_log row synchronously before returning (SC4, POLL-07).
        session_factory = get_async_session()
        async with session_factory() as session:
            await session.execute(
                insert(PollLog).values(
                    time=datetime.now(UTC),
                    restaurant_id=restaurant_id,
                    source=source,
                    ...
                    poll_id=poll_id,
                )
            )
            await session.commit()
```
Imports to copy (`services/poller/publisher.py:13-22`):
```python
from datetime import UTC, datetime
from sqlalchemy import insert
from shared.db import PollLog, get_async_session
```
Phase 2 changes: `insert(AvailabilityEvent)` from `sqlalchemy.dialects.postgresql` so `.on_conflict_do_nothing(index_elements=["event_id", "time"])` is available (B-2: the arbiter must include `time`); close path uses `update(AvailabilityEvent).where(AvailabilityEvent.event_id == ..., AvailabilityEvent.time == ...)` (B-3). Wrap the whole block in the `except Exception ... log.error(...)` best-effort shape from `services/poller/scheduler.py:115-122`.

---

### `services/state_machine/parsers/` (registry + opentable parser, transform)

**Analog A — source dispatch:** `services/poller/scheduler.py:86-97` is the existing `if source == "opentable": ... else: log.warning("unknown_source", source=source)`. The registry replaces this with a dict lookup raising `UnsupportedSourceError` (D-37).

**Analog B — payload shape:** `services/poller/sources/opentable/fixtures.py:15-34` is the authoritative structure the parser must walk (and the fixture the unit tests should import):
```python
OPENTABLE_SUCCESS_RESPONSE: dict[str, Any] = {
    "data": {
        "availability": [
            {
                "restaurantId": 42,
                "availability": [
                    {
                        "date": "2026-05-01",
                        "timeSlots": [
                            {"time": "19:00", "seatingTypes": ["bar", "standard"], "token": "abc123-reservation-token"}
                        ],
                    }
                ],
            }
        ]
    }
}
```
Also import `OPENTABLE_EMPTY_RESPONSE` (`fixtures.py:38-47`, a *valid* zero-slot observation per D-39) and `OPENTABLE_RATE_LIMIT_RESPONSE` (`fixtures.py:51-58`, has an `errors` array and no `data` → `ParseError`). These three fixtures cover D-39's whole matrix with no new test data.

**Tolerance docstring style** (`fixtures.py:1-8`) — carry the same `[ASSUMED]` / `TODO(spike)` honesty into the parser:
```python
"""
Shapes are [ASSUMED] per 01-RESEARCH.md §4 — update from
services/poller/sources/opentable/README.md ## Query Shape after the
DevTools spike confirms the live response schema.
"""
```

**Coverage source** (`services/poller/scheduler.py:79-83`) — the exact dict the parser receives:
```python
        request_params: dict[str, Any] = {
            "rid": restaurant_id,
            "dates": [d.isoformat() for d in dates],
            "party_sizes": list(DEFAULT_PARTY_SIZES),
        }
```
Per D-38a/B-4 use only `party_sizes[0]`, because `services/poller/sources/opentable/graphql.py:45-47` sends `"partySize": party_sizes[0]` and `adapter.py:105` (`return await self._fetch(rid, dates, party_sizes)`) does not loop.

---

### `shared/events.py` — `+ AvailabilityEvent`, `+ NAMESPACE_MISE` (model, pub-sub schema)

**Analog:** `shared/events.py::AvailabilityRaw` (same file, lines 14-27) — copy the config, field-ordering discipline and `to_bytes()` verbatim:
```python
class AvailabilityRaw(BaseModel):
    """Emitted to availability.raw for each completed OpenTable or Resy poll."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_id: UUID
    source: Literal["opentable", "resy"]
    restaurant_id: int
    polled_at_epoch_ms: int
    raw_response: dict[str, Any]
    request_params: dict[str, Any]

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")
```
Notes for the new model: declaration order **is** wire order (RESEARCH §Pattern 7) so field order is load-bearing for byte-identical replay; `Literal["opentable", "resy"]` for `source`; `Literal["slot_opened"]` for `event_type`; keep the header docstring's `Named symbols:` line updated (`shared/events.py:1-5`) — that line is the file's index.

---

### `shared/redis_keys.py` — `+ avail_state_key`, `avail_meta_key`, `event_idempotency_key`, `sched_expedite_key`, `EXPEDITE_POLL_LUA`, TTLs

**Analog:** the same file. Three sub-patterns to copy exactly:

**Section-comment + typed constants** (`shared/redis_keys.py:13-21`):
```python
# -- Scheduler ZSETs --
SCHED_POLLS = "sched:polls"              # score = next_poll_epoch_ms
SCHED_POLLS_INFLIGHT = "sched:polls:inflight"  # score = now_ms + visibility_ms

# -- Timing constants --
POLL_VISIBILITY_TIMEOUT_MS: int = 60_000   # 60s (D-18)
POLL_INTERVAL_SECONDS: int = 90            # D-17
```
Add `# -- Availability state (D-40, D-42) --` and `AVAIL_STATE_TTL_SECONDS: int = 90_000  # 25h (STATE-01)`, `EVENT_IDEMPOTENCY_TTL_SECONDS: int = 1_200  # 20min (STATE-04)`, `EXPEDITE_FLAG_TTL_SECONDS: int = 120`, `CONFIRM_DELAY_MS: int = 8_000`.

**Key-builder function** (`shared/redis_keys.py:24-26`) — one-line docstring naming the decision:
```python
def job(source: str, restaurant_id: int) -> str:
    """Return canonical job descriptor '{source}:{restaurant_id}' (D-18, D-29)."""
    return f"{source}:{restaurant_id}"
```

**Lua script constant with a KEYS/ARGV header comment block** (`shared/redis_keys.py:40-53`) — `EXPEDITE_POLL_LUA` must follow this exact documentation form:
```python
CLAIM_POLL_LUA = """
-- KEYS[1] = sched:polls
-- KEYS[2] = sched:polls:inflight
-- ARGV[1] = now_ms
-- ARGV[2] = visibility_timeout_ms
local ready = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 1)
if #ready == 0 then
  return nil
end
...
"""
```

**`set_nx_ex` already exists** (`shared/redis_keys.py:29-36`) — D-46 must call it, not re-implement:
```python
async def set_nx_ex(r: Redis, key: str, value: str, ttl_seconds: int) -> bool:
    """
    Atomic SETNX+EX in a single Redis call (Pitfall 7).
    NEVER use two-command SETNX + EXPIRE.
    """
    result = await r.set(key, value, nx=True, ex=ttl_seconds)
    return result is True
```

---

### `shared/scheduler/lua.py` — `+ LuaScheduler.expedite()`

**Analog:** `LuaScheduler.release()` (same file, lines 67-74) — copy structure exactly, including the `assert ... is not None, "Call start() first"` guard:
```python
    async def release(self, job: str, next_poll_ms: int) -> None:
        """Move job from inflight back to sched:polls with new next_poll score."""
        assert self._release_sha is not None, "Call start() first"
        await self._evalsha_with_fallback(
            self._release_sha, RELEASE_POLL_LUA, 2,
            SCHED_POLLS_INFLIGHT, SCHED_POLLS,
            job, str(next_poll_ms),
        )
```
Also add `self._expedite_sha: str | None = None` in `__init__` (mirror line 32-34) and `self._expedite_sha = await self.r.script_load(EXPEDITE_POLL_LUA)` in `start()` (mirror lines 38-40). Return value decoding follows `claim()` lines 63-65.

---

### `services/poller/scheduler.py` (modify release path — D-43)

**Analog:** itself. Current code (lines 138-139):
```python
        next_score = _next_poll_score(int(time.time() * 1000))
        await scheduler.release(job, next_score)
```
Becomes a `GETDEL sched:expedite:{job}` check selecting `now_ms + CONFIRM_DELAY_MS` instead of `_next_poll_score(...)`. Keep `_next_poll_score` (lines 30-32) untouched as the default branch; the expedite key comes from `shared.redis_keys.sched_expedite_key(job)`. Note `poll_loop`'s signature currently has no Redis handle — it takes `scheduler: LuaScheduler` (line 41), so the `GETDEL` belongs on `LuaScheduler` (e.g. `consume_expedite(job)`) rather than plumbing a new client through.

---

### `shared/db.py` — `AvailabilityEvent` ORM PK remap (B-3)

**Analog:** the same file. Current declaration (lines 109-123) and the `PollLog` UUID column (line 138) give both halves:
```python
class AvailabilityEvent(Base):
    __tablename__ = "availability_events"
    time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)
```
```python
    poll_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
```
Change: drop `primary_key=True` from `restaurant_id`; add `event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False, primary_key=True)`. Keep the standing comment at lines 105-107 in place:
```python
# Note: availability_events and poll_log are TimescaleDB hypertables created via
# Alembic migrations (0006, 0007) — not via SQLAlchemy create_all.
# ORM classes below are for querying only; never use Base.metadata.create_all() for these.
```

---

### `migrations/versions/0008_add_event_id_to_availability_events.py` (migration)

**Analog:** `migrations/versions/0007_create_poll_log_hypertable.py` (header, revision chain, UUID import, `op.execute` for Timescale specifics) and `0006` (the anti-autogenerate comment).

**Header + chain** (`0007:1-10`):
```python
"""0007: Create poll_log hypertable (chunk_time_interval = 1 day, D-33)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None
```
0008 sets `revision = "0008"`, `down_revision = "0007"`.

**Mandatory warning comment** (`0006:30`, quoted verbatim — reproduce in 0008):
```python
    # NEVER use `alembic revision --autogenerate` on a hypertable (Pitfall 12, D-33)
```

**Raw-SQL style for Timescale-specific DDL** (`0006:31-35`):
```python
    op.execute(
        "SELECT create_hypertable('availability_events', 'time', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )
    op.create_index("ix_avail_events_restaurant_time", "availability_events", ["restaurant_id", "time"])
```
0008 does: `op.add_column("availability_events", sa.Column("event_id", UUID(as_uuid=True), nullable=False))` (table is empty, no backfill), `op.create_index("uq_availability_events_event_id_time", "availability_events", ["event_id", "time"], unique=True)` (B-2 — `time` is mandatory), and `op.execute("COMMENT ON COLUMN availability_events.day_of_week IS '0=Sun .. 6=Sat (isoweekday() %% 7)'")` plus the `restaurant_id` platform-id comment (D-52). Note the stale `# 0=Mon..6=Sun` at `0006:27` is what this comment overrides (B-5). Write a real `downgrade()` — every existing migration has one (`0006:38-40`).

---

### `scripts/replay_raw.py` (CLI script, batch)

**Analog A — script header + exit codes + `main()`:** `scripts/check_poll_success.py:1-32, 63-79`:
```python
#!/usr/bin/env python
"""
SC5 / PERF-02: Assert >= 99% poll success rate in every hourly bucket over last 24h.

Usage: uv run python scripts/check_poll_success.py
Or:    make verify-perf02

Exit codes:
  0 — ...
"""
from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
```
```python
def main() -> None:
    exit_code = asyncio.run(check())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
```
The docstring is where D-55 (`--to-offset` exclusive) must be documented; every script in the repo carries a `Usage:` + `Or: make <target>` pair, so add `make replay` to the Makefile in the same task.

**Analog B — aiokafka in a script:** `scripts/create_topics.py:22-27` for the bootstrap env default:
```python
BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
```
**Analog C — bounded consumption:** no repo analog; use RESEARCH §Pattern 5 verbatim (`group_id=None`, `start()` before `assign()`, sync `assign`/`seek`, async `end_offsets`/`position`, break on empty `getmany`).

---

### `Makefile` (+ `state-machine`, + `replay`)

**Analog:** `Makefile:20-21` — every target has a `## ` help comment (the `help` target greps for it at line 48) and must be added to `.PHONY` (line 3):
```make
poll: ## Run OpenTable poller on host
	uv run python -m services.poller
```

---

### `tests/integration/test_state_machine_e2e.py` (test, event-driven)

**Analog:** `tests/integration/test_poller_smoke.py` — the full container-wiring recipe. Copy lines 25-80 nearly verbatim.

**Marker + container fixtures** (`:25-45`):
```python
pytestmark = pytest.mark.integration


async def test_end_to_end_emit_within_60s(kafka_container, redis_container, timescale_container):
    kafka_bootstrap = kafka_container.get_bootstrap_server()
    redis_url = (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}"
    )
    db_url_sync = timescale_container.get_connection_url().replace("psycopg2", "psycopg")
    db_url_async = db_url_sync.replace("postgresql+psycopg://", "postgresql+asyncpg://")
```

**Env + singleton reset** (`:47-61`) — mandatory, otherwise `shared.db` keeps the previous engine:
```python
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = kafka_bootstrap
    os.environ["REDIS_URL"] = redis_url
    os.environ["DATABASE_URL_ASYNC"] = db_url_async
    os.environ["DATABASE_URL_SYNC"] = db_url_sync

    import shared.db as shared_db

    shared_db._engine = None
    shared_db._session_factory = None
```

**Migrations + topics via subprocess** (`:63-80`):
```python
    env = {**os.environ}
    result = subprocess.run(["uv", "run", "alembic", "upgrade", "head"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"
    result = subprocess.run(["uv", "run", "python", "scripts/create_topics.py"], env=env, capture_output=True, text=True)
    assert result.returncode == 0, f"create_topics failed: {result.stderr}"
```
This `subprocess.run(["uv", "run", ...], env=env)` idiom is also the model for D-51's chaos test (`env={**os.environ, "MISE_CRASH_AFTER": "state_write"}`, `subprocess.Popen`, expect a non-zero/`-SIGKILL` returncode).

**Run-then-timeout + drain** (`:99-124`):
```python
        try:
            await asyncio.wait_for(run(), timeout=30)
        except TimeoutError:
            pass  # Expected — the poller runs indefinitely
    ...
    consumer = AIOKafkaConsumer(
        "availability.raw",
        bootstrap_servers=kafka_bootstrap,
        auto_offset_reset="earliest",
        group_id=f"smoke-test-{_time.time_ns()}",
    )
    await consumer.start()
    try:
        batches = await consumer.getmany(timeout_ms=10_000, max_records=10)
        messages = [m for records in batches.values() for m in records]
        assert messages, "No messages on availability.raw within timeout"
    finally:
        await consumer.stop()
```
Note this drain call at line 109-114 is already the **varargs** form B-1 requires — copy it, not D-47's literal list.

---

### `tests/integration/test_expedite_lua.py` (test, CRUD)

**Analog:** `tests/integration/test_scheduler_claim_release.py:1-40` — module-scoped `redis_url` fixture derived from the container, clean-slate deletes, byte comparisons:
```python
@pytest.fixture(scope="module")
def redis_url(redis_container):
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}"


@pytest.mark.asyncio
async def test_claim_release_cycle(redis_url):
    r = redis.from_url(redis_url, decode_responses=False)
    sched = LuaScheduler(r)
    await sched.start()
    now_ms = int(time.time() * 1000)
    await r.delete(SCHED_POLLS, SCHED_POLLS_INFLIGHT)
    await r.zadd(SCHED_POLLS, {"opentable:42": now_ms - 1000})
    ...
    assert b"opentable:42" in inflight
    await r.aclose()
```
Assertions compare **bytes literals** (`b"opentable:42"`) because `decode_responses=False`. The expedite test asserts: `ZADD XX LT` lowers an existing score; `XX` does not create an absent member; `LT` does not raise an earlier score; absent member instead sets `sched:expedite:{job}` with a TTL ≈ 120.

---

### `tests/unit/*` (tests)

**Analog A — constant/helper assertions + `AsyncMock` for Redis:** `tests/unit/test_redis_keys.py:1-45`:
```python
from unittest.mock import AsyncMock

import pytest

from shared.redis_keys import (SCHED_POLLS, job, set_nx_ex)


@pytest.mark.asyncio
async def test_set_nx_ex_uses_single_atomic_call():
    """set_nx_ex MUST call r.set with nx=True and ex= in a single call (Pitfall 7)."""
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    result = await set_nx_ex(mock_redis, "testkey", "testval", 60)
    mock_redis.set.assert_called_once_with("testkey", "testval", nx=True, ex=60)
```
Also copy the Lua-content assertion idiom (`test_redis_keys.py:55-58`) for `EXPEDITE_POLL_LUA`:
```python
def test_lua_claim_uses_zrangebyscore():
    from shared.redis_keys import CLAIM_POLL_LUA
    assert "ZRANGEBYSCORE" in CLAIM_POLL_LUA
```
→ `assert "XX" in EXPEDITE_POLL_LUA and "LT" in EXPEDITE_POLL_LUA`.

**Analog B — schema tests (frozen / extra=forbid / to_bytes):** `tests/unit/test_events_schema.py:9-47`:
```python
def test_availability_raw_event_frozen():
    evt = AvailabilityRaw(...)
    with pytest.raises(Exception):
        evt.restaurant_id = 99  # type: ignore[misc]


def test_polls_completed_event_extra_fields_forbidden():
    with pytest.raises(Exception):
        PollCompleted(..., unknown_field="oops")
```
Add for `AvailabilityEvent`: same two tests plus determinism (`uuid5` stable across constructions) and byte-stability (`a.model_dump_json() == b.model_dump_json()` from a reversed input dict).

**Note on `pytest.mark.asyncio`:** async tests carry the explicit marker (`test_redis_keys.py:30`) even though `asyncio_mode = "auto"` — follow the existing files.

---

## Shared Patterns

### Logging
**Source:** `shared/telemetry.py:71-74`, used at `services/poller/scheduler.py:22-24`
**Apply to:** every new module in `services/state_machine/`, and `scripts/replay_raw.py` (or plain `print` for CLI output, per `scripts/check_poll_success.py`).
```python
from shared.telemetry import get_logger

log = get_logger(__name__)
...
log.info("availability_raw_published", poll_id=str(poll_id), restaurant_id=restaurant_id)
```
Convention: snake_case event name as the first positional arg, everything else as kwargs; `UUID`s stringified.

### Module header docstring
**Source:** `shared/redis_keys.py:1-5`, `shared/kafka.py:1-5`, `shared/events.py:1-5`
**Apply to:** every new `shared/` and `services/state_machine/` module.
```python
"""
Single source of truth for ALL Redis key patterns and TTLs (D-18).
Any Redis access in services/ MUST import from here.
Named symbols: SCHED_POLLS, SCHED_POLLS_INFLIGHT
"""
from __future__ import annotations
```
Every file: `from __future__ import annotations` on the first import line, a decision ID (`D-nn`) cited in the docstring, and a `Named symbols:` line.

### Factory functions with env fallback
**Source:** `shared/kafka.py:13-37`
**Apply to:** the new `make_consumer()` in the same file — same signature style, same env default, same "caller owns `.stop()`" contract, same inline `#` comments justifying each kwarg.
```python
async def make_producer(bootstrap_servers: str | None = None) -> AIOKafkaProducer:
    """
    Create and start an AIOKafkaProducer with correct durability config (D-02, Pitfall 11).
    ...
    Returns:
        A started AIOKafkaProducer. Caller is responsible for .stop() on shutdown.
    """
    servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
    producer = AIOKafkaProducer(
        bootstrap_servers=servers,
        acks="all",                                   # D-02: wait for all in-sync replicas
        enable_idempotence=True,                      # prevents duplicates on retry
        compression_type="gzip",                      # cheap at ~10KB messages
        linger_ms=20,                                  # small batching window
        request_timeout_ms=30_000,
        value_serializer=lambda v: v if isinstance(v, bytes) else v.encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
    )
    await producer.start()
    return producer
```
`make_consumer` deviations: `*topics` varargs (B-1), `group_id`, `enable_auto_commit=False`, `auto_offset_reset="earliest"`, `max_poll_records=1`; **no** `value_deserializer` if the replay path wants raw bytes.

### Error handling (best-effort, service must not die)
**Source:** `services/poller/reaper.py:34-35` and `services/poller/scheduler.py:115-122`
**Apply to:** the DB write path (D-48 "logged and does not block the emit") and the consumer's top-level message loop.
```python
        except Exception as exc:  # noqa: BLE001 — log and continue; reaper must not die
            log.error("reaper_error", error=str(exc))
```

### Redis client construction
**Source:** `services/poller/main.py:75`, `tests/integration/test_scheduler_claim_release.py:21`
**Apply to:** `services/state_machine/main.py` and every Redis integration test.
```python
r = redis.from_url(REDIS_URL)          # decode_responses defaults to False → decode manually
...
await r.aclose()                        # aclose(), not close()
```
Import must be `import redis.asyncio as redis` — bare `import redis` fails the CI grep (`.github/workflows/lint.yml:25-27`).

### CI ban-greps (mypy strict + lint constraints)
**Source:** `.ruff.toml` and `.github/workflows/lint.yml`
**Apply to:** all `services/state_machine/**` and `shared/**` code.
- no `time.sleep(`, no `import requests`, no bare `import redis` in `services/`, `shared/`
- `line-length = 120`, ruff `["E","F","W","I","UP","ASYNC"]`
- `mypy --strict` over `shared/ services/` → every function annotated, redis awaitables need `cast(Awaitable[Any], ...)` (`shared/scheduler/lua.py:47`)
- `scripts/**` is exempt only from `ASYNC240`; `tests/**` from `S101, ASYNC221, ASYNC240`

---

## No Analog Found

Planner should use RESEARCH.md patterns (not a codebase file) for these:

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `services/state_machine/engine.py` | pure domain core | transform | No pure functional-core/`Protocol`-injected module exists. Nearest structural precedent is `services/poller/sources/base.py` (ABC-based swap point). Use RESEARCH §Pattern 1 verbatim. |
| `services/state_machine/parsers/errors.py` | errors | — | Repo defines no custom exceptions anywhere (`grep` finds only library exceptions). New convention: plain `class ParseError(Exception)` / `UnsupportedSourceError(ParseError)`. |
| `tests/unit/test_replay_byte_identity.py` + `tests/fixtures/raw_streams/*` | test / fixture | file-I/O | `tests/fixtures/` does not exist; the only fixture precedent is the Python-literal `services/poller/sources/opentable/fixtures.py`. Golden-file `.jsonl` comparison is new. Use RESEARCH §Pattern 7. |
| `scripts/replay_raw.py` bounded-consumption core | script | streaming | No repo code uses `assign`/`seek`/`end_offsets`. Use RESEARCH §Pattern 5 (verified recipe). Argparse also has no precedent — no existing script takes CLI args. |

---

## Metadata

**Analog search scope:** `services/`, `shared/`, `scripts/`, `tests/`, `migrations/versions/`, `ops/`, `Makefile`, `.ruff.toml`
**Files scanned:** 24 read in full or in targeted ranges (all 12 poller/shared source modules, 3 migrations, 5 tests, 3 scripts, Makefile/.ruff.toml)
**Pattern extraction date:** 2026-09-05
