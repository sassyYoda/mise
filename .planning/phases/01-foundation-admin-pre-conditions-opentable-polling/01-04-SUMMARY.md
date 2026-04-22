---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 04
subsystem: shared-kernel
tags: [shared, pydantic-v2, sqlalchemy-async, asyncpg, aiokafka, redis-lua, structlog, seed-scripts]
dependency_graph:
  requires:
    - "01-01 — shared/{events.py,redis_keys.py,telemetry.py} stubs + Wave-0 test scaffolding"
    - "01-02 — migrations 0002..0007 + timescaledb hypertables + Named Symbol column set for poll_log/availability_events"
  provides:
    - "shared/events.py — AvailabilityRaw, PollCompleted Pydantic v2 models with to_bytes()"
    - "shared/redis_keys.py — SCHED_POLLS, SCHED_POLLS_INFLIGHT, job(), set_nx_ex(), CLAIM/RELEASE/REAP Lua constants"
    - "shared/db.py — 6 SQLAlchemy 2.0 async ORM models + get_engine/get_async_session factory"
    - "shared/kafka.py — make_producer() AIOKafkaProducer factory with acks=all/idempotence=True/gzip/linger=20"
    - "shared/scheduler/lua.py — LuaScheduler with claim/release/reap via EVALSHA+NOSCRIPT fallback"
    - "shared/telemetry.py — configure_logging()/get_logger() with secret redaction processor"
    - "scripts/seed_restaurants.py — idempotent YAML upsert + sched:polls ZSET bootstrap"
    - "scripts/verify_seed.py — SC3 gate (>=50 restaurants AND ZCARD(sched:polls) >= 50)"
    - "tests/integration/test_scheduler_claim_release.py — live Redis claim/release/reap tests"
    - "tests/integration/test_hypertable_config.py — live TimescaleDB chunk_time_interval=1day test"
  affects:
    - "Plan 01-05 (poller service) — imports AvailabilityRaw/PollCompleted, LuaScheduler, make_producer, get_async_session"
    - "Plan 01-03 (admin/secrets) — parallel wave 3 peer; seed_restaurants.py consumes 01-03's scripts/seed/restaurants.yml"
    - "Plan 01-06 (PERF-02 verification) — reads from poll_log via shared.db.PollLog"
tech_stack:
  added: []
  patterns:
    - "Named Symbol fidelity: AvailabilityRaw/PollCompleted field names match REQUIREMENTS.md verbatim (poll_id, source, restaurant_id, polled_at_epoch_ms, raw_response, request_params, status, latency_ms, http_status, error)"
    - "Pydantic v2 ConfigDict(frozen=True, extra='forbid') — mutating a field or sending an unknown field both raise ValidationError"
    - "to_bytes() returns self.model_dump_json().encode('utf-8') — single source of truth for Kafka value serialization"
    - "Lua scripts live in shared.redis_keys as module-level string constants; shared.scheduler.lua.LuaScheduler wraps them with script_load + EVALSHA caching + NoScriptError fallback that re-loads and retries once"
    - "AIOKafkaProducer durability config: acks='all' + enable_idempotence=True + max_in_flight_requests_per_connection=5 + compression_type='gzip' + linger_ms=20 (Pitfall 11, D-02)"
    - "set_nx_ex uses exactly one r.set(key, value, nx=True, ex=ttl) call — NEVER two-command SETNX+EXPIRE (Pitfall 7) — unit-tested via AsyncMock.assert_called_once_with"
    - "seed_restaurants.py upsert idempotency keyed on UniqueConstraint(source, platform_id) via ON CONFLICT DO UPDATE; second run produces no duplicate rows (D-15)"
    - "Initial sched:polls score = now_ms + rand(0, 90_000) so 50 restaurants are spread across the 90s poll interval at bootstrap (D-17)"
    - "SQLAlchemy ORM column-level fidelity with migrations 0002-0007 — restaurants.id BigInteger, party_sizes ARRAY(Integer), poll_log.poll_id PG_UUID(as_uuid=True)"
key_files:
  created:
    - shared/kafka.py
    - shared/db.py
    - shared/scheduler/__init__.py
    - shared/scheduler/lua.py
    - scripts/seed_restaurants.py
    - scripts/verify_seed.py
    - tests/unit/test_kafka_config.py
  modified:
    - tests/unit/test_redis_keys.py           # + Lua-script + constant assertions (3 new tests)
    - tests/integration/test_scheduler_claim_release.py  # stub → live Redis tests (3 tests, no @pytest.mark.skip)
    - tests/integration/test_hypertable_config.py        # stub → live TimescaleDB test via alembic upgrade + asyncpg query
decisions:
  - "LuaScheduler NOSCRIPT fallback strategy is re-run script_load and retry ONCE, then propagate. Rationale: Redis only drops cached scripts on FLUSHSCRIPTS or crash-restart; one retry is sufficient and avoids unbounded retry loops."
  - "shared/scheduler/__init__.py is an empty package marker — no re-exports. Callers import directly from shared.scheduler.lua to avoid circular imports with shared.redis_keys (Lua string constants live in shared.redis_keys to keep a single source-of-truth module; LuaScheduler wraps them from the scheduler subpackage)."
  - "shared.db.get_engine() / get_async_session() return module-level singletons created on first call. Reason: services hold a single pooled engine; FastAPI lifespan wires teardown via engine.dispose() (callsite pattern deferred to Plan 05/07)."
  - "scripts/seed_restaurants.py uses raw SQL via text() for the INSERT ... ON CONFLICT upsert (not SQLAlchemy ORM). Reason: SQLAlchemy 2.0's ORM does not have a first-class Postgres ON CONFLICT syntax that handles ARRAY columns cleanly; raw SQL is the idiomatic approach and matches Alembic migration style."
  - "test_hypertable_config.py queries timescaledb_information.dimensions.time_interval (not chunk_time_interval). Reason: TimescaleDB 2.x renamed the column to time_interval in 2.13+; 2.17 (our stack) exposes it as time_interval which returns a timedelta. We convert to microseconds for the 86_400_000_000 assertion."
metrics:
  duration: "~3 minutes (13:19-13:22 UTC)"
  completed: "2026-04-22"
  tasks: 4
  commits: 4
  files_changed: 10
---

# Phase 01 Plan 04: Shared Kernel Summary

Fully implements the shared/ kernel modules — Pydantic v2 Kafka event schemas, SQLAlchemy 2.0 async ORM models for all six Phase-1 tables, AIOKafkaProducer factory with durability config, LuaScheduler wrapping the three ZSET Lua scripts via EVALSHA+NOSCRIPT fallback, structlog telemetry with secret redaction, and the idempotent seed_restaurants.py script; activates the previously-stubbed scheduler and hypertable integration tests so Wave 4 (poller service) consumes concrete types rather than stubs.

## Tasks Completed

| Task | Description | Commit |
|------|-------------|--------|
| T1 | Expand redis_keys unit tests (Lua script / constant assertions) | `1f49e48` |
| T2 | Add shared.kafka producer factory + test_kafka_config.py | `c6a96d7` |
| T3 | Add shared.db ORM models + shared.scheduler.lua LuaScheduler + fill scheduler/hypertable integration tests | `0b71d1d` |
| T4 | Add seed_restaurants.py (idempotent UPSERT + ZSET) and verify_seed.py | `6b76114` |

## Commits

- `1f49e48` test(01-04): expand redis_keys unit tests for Lua scripts and constants
- `c6a96d7` feat(01-04): add shared.kafka producer factory with durability config
- `0b71d1d` feat(01-04): add shared.db ORM models and shared.scheduler.lua LuaScheduler
- `6b76114` feat(01-04): add idempotent seed_restaurants.py and verify_seed.py

## Verification Output

### All shared kernel imports resolve

```
$ uv run python -c "from shared.events import AvailabilityRaw, PollCompleted; \
from shared.redis_keys import SCHED_POLLS, SCHED_POLLS_INFLIGHT, set_nx_ex; \
from shared.db import get_engine, get_async_session, PollLog, Restaurant; \
from shared.kafka import make_producer; \
from shared.scheduler.lua import LuaScheduler; \
from shared.telemetry import configure_logging, get_logger; \
print('All imports OK')"
All imports OK
```

### Unit tests — 19 passed, 2 skipped (out-of-scope Plan-05 stubs)

```
tests/unit/test_events_schema.py::test_availability_raw_event_to_bytes PASSED
tests/unit/test_events_schema.py::test_availability_raw_event_frozen PASSED
tests/unit/test_events_schema.py::test_polls_completed_event_extra_fields_forbidden PASSED
tests/unit/test_events_schema.py::test_polls_completed_event_optional_fields PASSED
tests/unit/test_kafka_config.py::test_make_producer_config PASSED
tests/unit/test_kafka_config.py::test_make_producer_defaults_to_env_var PASSED
tests/unit/test_redis_keys.py::test_sched_polls_constant PASSED
tests/unit/test_redis_keys.py::test_sched_polls_inflight_constant PASSED
tests/unit/test_redis_keys.py::test_job_descriptor_format PASSED
tests/unit/test_redis_keys.py::test_set_nx_ex_uses_single_atomic_call PASSED
tests/unit/test_redis_keys.py::test_set_nx_ex_returns_false_when_key_exists PASSED
tests/unit/test_redis_keys.py::test_lua_scripts_are_non_empty_strings PASSED
tests/unit/test_redis_keys.py::test_lua_claim_uses_zrangebyscore PASSED
tests/unit/test_redis_keys.py::test_constants_values PASSED
tests/unit/test_telemetry_redaction.py::test_redacts_twilio_auth_token PASSED
tests/unit/test_telemetry_redaction.py::test_redacts_hmac_secret PASSED
tests/unit/test_telemetry_redaction.py::test_redacts_vapid_private_key PASSED
tests/unit/test_telemetry_redaction.py::test_redacts_resy_accounts_json PASSED
tests/unit/test_telemetry_redaction.py::test_leaves_non_secret_fields_alone PASSED

2 skips: tests/unit/test_http_client_singleton.py — annotated "Wave-0 stub — shared.http_client
singleton implemented in Plan 05". Out-of-scope for this plan by design.

19 passed, 2 skipped in 0.08s
```

All tests filled in this plan pass with 0 skips. Success-criteria bullet "0 failures, 0 skips on the unit tests that were filled in this plan" is satisfied.

### Integration tests collect with no skips

```
$ uv run pytest tests/integration/test_scheduler_claim_release.py \
                tests/integration/test_hypertable_config.py --collect-only
<Module test_scheduler_claim_release.py>
  <Coroutine test_claim_release_cycle>
  <Coroutine test_reaper_requeues_expired_inflight>
  <Coroutine test_claim_returns_none_when_empty>
<Module test_hypertable_config.py>
  <Coroutine test_chunk_interval_is_one_day>
4 tests collected in 0.48s
```

No `@pytest.mark.skip` on any of the four integration tests — they run live against testcontainer Redis/TimescaleDB when Docker is available and skip via the container fixture when it is not.

### Seed scripts parse cleanly

```
$ python3 -c "import ast; ast.parse(open('scripts/seed_restaurants.py').read()); \
              ast.parse(open('scripts/verify_seed.py').read()); print('seed scripts parse OK')"
seed scripts parse OK
```

## Success Criteria — All PASS

| Criterion | Status |
|-----------|--------|
| All shared/ modules import without error | PASS |
| `uv run pytest tests/unit` — 0 failures, 0 skips on plan-filled tests | PASS (19/19 plan-filled tests) |
| `test_set_nx_ex_uses_single_atomic_call` confirms single nx=True,ex= call | PASS |
| `test_telemetry_redaction.py` confirms all 4 secret keys redacted | PASS |
| `shared/db.py PollLog` columns exactly: time, restaurant_id, source, status, latency_ms, http_status, error, poll_id | PASS (Named Symbols verbatim) |
| `shared/scheduler/lua.py LuaScheduler` has claim/release/reap using EVALSHA+NOSCRIPT fallback | PASS |
| `scripts/seed_restaurants.py` uses ON CONFLICT (source, platform_id) DO UPDATE; populates sched:polls | PASS |
| Integration test stubs fully implemented (no `@pytest.mark.skip`) | PASS (4 tests — claim/release/reap + reaper + claim-empty + chunk interval) |

## Deviations from Plan

None required — the plan as written was executable verbatim. Minor notes:

1. **T1 test stubs already activated.** The Plan-01 stubs shipped without `@pytest.mark.skip` on any of the `test_events_schema.py` / `test_redis_keys.py` / `test_telemetry_redaction.py` bodies, so the "remove skip" step was a no-op. The prescribed additional assertions (Lua-script non-emptiness, ZRANGEBYSCORE presence, constant values) were added as net-new tests.
2. **T3 TimescaleDB information view column name.** The plan's query used `chunk_time_interval` as the column name on `timescaledb_information.dimensions`; TimescaleDB 2.13+ renamed this to `time_interval` (returns a timedelta). Adjusted the test query accordingly — documented in the Decisions block above. Assertion logic (86_400_000_000 microseconds = 1 day) is unchanged.
3. **Seed not executed yet.** Per the plan's explicit note ("If 01-03 hasn't finished the YAML yet when you reach this step, the seeder code itself is the deliverable — defer running the actual seed to a later integration test gate"): 01-03 is running in parallel and the YAML file `scripts/seed/restaurants.yml` is not yet on disk. `seed_restaurants.py` is complete and parses cleanly; the live-run idempotency test (`tests/integration/test_seed_idempotency.py`) is the Wave-4/5 gate where the YAML will exist.

## Ready for Wave 4

All of the shared kernel contracts Plan 05 (poller service) and Plan 06 (PERF-02) consume are in place:

- `AvailabilityRaw` / `PollCompleted` with `to_bytes()` — used by the poller's publisher
- `make_producer()` — poller's Kafka producer factory
- `get_async_session()` — poller writes `poll_log` rows through this
- `LuaScheduler.claim/release/reap` — the poller's main loop
- `SCHED_POLLS` / `SCHED_POLLS_INFLIGHT` / `set_nx_ex` — scheduler key surface
- `configure_logging()` / `get_logger()` — structured logs with secret redaction
- `scripts/seed_restaurants.py` + `verify_seed.py` — SC3 gate once Plan 03 lands the YAML

**Wave 4 (Plan 05 — poller service) may proceed.**

## Self-Check: PASSED

Verified on disk:

- `shared/kafka.py` — FOUND
- `shared/db.py` — FOUND
- `shared/scheduler/__init__.py` — FOUND
- `shared/scheduler/lua.py` — FOUND
- `scripts/seed_restaurants.py` — FOUND
- `scripts/verify_seed.py` — FOUND
- `tests/unit/test_kafka_config.py` — FOUND
- tests/integration/test_scheduler_claim_release.py contains no `@pytest.mark.skip` — CONFIRMED
- tests/integration/test_hypertable_config.py contains no `@pytest.mark.skip` — CONFIRMED

Verified commits in `git log`:

- `1f49e48` — FOUND
- `c6a96d7` — FOUND
- `0b71d1d` — FOUND
- `6b76114` — FOUND
