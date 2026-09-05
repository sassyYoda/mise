# Phase 2: State Machine & Event Pipeline - Research

**Researched:** 2026-09-05
**Domain:** Stateful Kafka stream processing — tri-state availability diff, Redis-backed state store, deterministic event emission, TimescaleDB persistence, offset-range replay
**Confidence:** HIGH (every library API claim in this document was executed against the packages in `.venv` and against live Redis 7.2 / TimescaleDB 2.17.2 / Kafka cp-7.6.0 containers this session)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Slot identity & payload normalisation**
- **D-36:** A *slot* is identified by `(source, restaurant_id, date, party_size, time_slot, seat_type)`; `booking_token` is carried as data, not identity (tokens can rotate between polls for the same physical slot). Slot key string inside Redis hashes: `{time_slot}|{seat_type or '-'}`.
- **D-37:** Per-source parsers live in `services/state_machine/parsers/{opentable,resy}.py` behind a `parse_raw(raw: AvailabilityRaw) -> ParsedPoll` registry keyed by `raw.source`. `ParsedPoll` = `{restaurant_id, source, polled_at_epoch_ms, poll_id, coverage: set[(date, party_size)], slots: list[Slot]}`. The diff engine never branches on source (Phase 3 SC5). Phase 2 registers `opentable`; `resy` raises `UnsupportedSourceError` → treated as UNKNOWN until Phase 3 registers it.
- **D-38:** `coverage` (the `(date, party_size)` matrix the poll actually asked for, taken from `raw.request_params`) bounds the diff: a slot is only marked UNAVAILABLE if its `(date, party)` was covered by this poll and it is absent. Slots for uncovered dates/parties are untouched (prevents false closures when the date window rolls).
- **D-39:** Parser failures (missing `data`, GraphQL `errors` array, empty dict, non-JSON) → `ParseError` → the restaurant's tracked slots are marked UNKNOWN (`unknown_since_ms` set on the hash meta), nothing is removed, no events. A well-formed response with zero slots is a *valid* observation and closes covered slots.

**Redis state model (STATE-01) and tri-state (STATE-02)**
- **D-40:** `avail:{restaurant_id}:{date}:{party_size}` is a Redis HASH (field = slot key, value = compact JSON `{state, token, first_seen_ms, first_poll_id, last_seen_ms, confirmed_ms, event_id}`) with `EXPIRE 90000` (25h) refreshed on every write. A HASH is the set of known slot tokens STATE-01 asks for plus the timestamps STATE-05 needs; there is no separate meta key per slot. Restaurant-level `avail:{restaurant_id}:meta` HASH carries `unknown_since_ms` / `last_success_ms`.
- **D-41:** Per-slot states: `PENDING` (seen once, awaiting confirmation), `AVAILABLE` (confirmed & emitted), `UNAVAILABLE` (gone; row closed in DB), `UNKNOWN` (last poll for the restaurant errored/unparseable — a flag on the restaurant meta, slots keep their last known state). Transitions: absent→PENDING (seen), PENDING→AVAILABLE (seen again ≥ 8s later → EMIT), PENDING→dropped (absent on next successful covered poll, no event — this is the false-positive guard), AVAILABLE→UNAVAILABLE (absent on a successful covered poll → close DB row), UNAVAILABLE/absent→PENDING (re-opened → new cycle, new event_id). Errors never move a slot toward UNAVAILABLE.
- **D-42:** All Redis access goes through `shared/redis_keys.py` constants/helpers (`avail_state_key`, `avail_meta_key`, `event_idempotency_key`, `sched_expedite_key`) — no inline key strings in services.

**Confirmation at t+8s via the ZSET scheduler (STATE-03)**
- **D-43:** Confirmation is **stream-based**: the state machine never calls OpenTable/Resy itself. On PENDING it runs Lua `EXPEDITE_POLL_LUA`: if `{source}:{rid}` is in `sched:polls`, `ZADD LT` its score to `now_ms + 8000`; otherwise (job in flight) `SET sched:expedite:{source}:{rid} 1 EX 120`. `services/poller/scheduler.py` release path does `GETDEL sched:expedite:{job}` and, if present, releases with `now_ms + 8000` instead of the 90s±15% score. The expedited poll's `availability.raw` message confirms (or drops) every PENDING slot for that restaurant. Replay therefore reproduces confirmations from the raw stream alone (needed for D-49).
- **D-44:** Confirmation requires `polled_at_epoch_ms(confirming) - first_seen_ms >= 8000` (an accidental immediate duplicate poll does not confirm) — in replay the same rule applies, keyed off message timestamps.

**Event contract & emission idempotency (STATE-04)**
- **D-45:** `shared/events.py` gains `AvailabilityEvent` (frozen, `extra="forbid"`): `event_id: UUID` (uuid5 over `NAMESPACE_MISE` + `"{source}:{rid}:{date}:{party}:{slot_key}:{first_poll_id}"` — deterministic), `event_type: Literal["slot_opened"]`, `source`, `restaurant_id`, `date`, `time_slot`, `party_size`, `seat_type`, `booking_token`, `first_seen_at_epoch_ms`, `confirmed_at_epoch_ms`, `produced_at_epoch_ms` (= confirming poll's `polled_at_epoch_ms`, NOT wall clock — deterministic; PERF-01 latency is measured from this detection timestamp), `confirming_poll_id`. Kafka key `{source}:{restaurant_id}` (D-29). Only `slot_opened` goes to Kafka; closures are DB-only updates.
- **D-46:** Emission order per slot: diff → `SET event:{rid}:{date}:{party}:{token} 1 NX EX 1200` (single command via `shared.redis_keys.set_nx_ex`; token = `booking_token or slot_key`) → `producer.send_and_wait` (acks=all) → write hash state `AVAILABLE` with `event_id` → after the whole message: `consumer.commit()` (manual, `enable_auto_commit=False`). On redelivery: NX fails AND hash says AVAILABLE → skip (chaos SC3 path, zero duplicates). NX fails AND hash still PENDING (crash between claim and hash write) → re-send the same deterministic `event_id` (downstream Layer-2 key in Phase 4 dedupes by event_id). Source tree must contain zero `SETNX`+`EXPIRE` pairs (unit test greps for it).
- **D-47:** Consumer: `AIOKafkaConsumer(["availability.raw", "polls.completed"], group_id="state-machine", enable_auto_commit=False, auto_offset_reset="earliest")`; one message processed at a time (single partition, per-restaurant ordering guaranteed by key). `polls.completed` with status `error|timeout` → mark restaurant UNKNOWN only.

**Persistence (STATE-05)**
- **D-48:** On EMIT: `INSERT` into `availability_events` (`time`=confirmed_at, `restaurant_id`, `source`, `date`, `time_slot`, `party_size`, `seat_type`, `booking_token`, `first_seen_at`, `last_seen_at`=confirmed_at, `hours_before_service` = (service datetime in `America/New_York` − first_seen_at)/3600, `day_of_week` = service date `isoweekday()%7` (0=Sun … 6=Sat, matching the heatmap y-axis in Phase 6)). On AVAILABLE→UNAVAILABLE: `UPDATE ... SET last_seen_at, duration_seconds = last_seen_at − first_seen_at WHERE time=… AND restaurant_id=…` (hypertable UPDATE by primary key). Migration 0008 adds `event_id UUID` + unique index `(restaurant_id, event_id)` to `availability_events` for upsert safety. Writes are through `shared.db.get_async_session()`; a DB failure is logged and does not block the Kafka emit (metrics beat durability of the analytics row).

**Replay & determinism (STATE-06)**
- **D-49:** The diff engine is a pure core: `services/state_machine/engine.py :: DiffEngine(store: StateStore)` with `async def process(parsed: ParsedPoll) -> list[AvailabilityEvent]` and `StateStore` protocol implemented by `RedisStateStore` (production) and `MemoryStateStore` (replay/tests). Side-effects (expedite, emit, persist, commit) live in `services/state_machine/consumer.py` around the engine.
- **D-50:** `scripts/replay_raw.py --from-offset A --to-offset B [--bootstrap …] | --input raw.jsonl` `[--output events.jsonl]` feeds messages through `DiffEngine(MemoryStateStore())`, dedupes by `event_id`, and writes one canonical `model_dump_json()` line per event. Test fixture streams live in `tests/fixtures/raw_streams/*.jsonl` (happy path, transient-error stream, flapping slot). CI test: two replays of the same fixture are byte-identical to each other and to the committed golden `*.events.jsonl`; the transient-error fixture yields zero events.

**Chaos & test strategy**
- **D-51:** Integration test `tests/integration/test_state_machine_e2e.py` (testcontainers Kafka+Redis+Timescale): publish 2 raw polls 9s apart → exactly one `availability.events` message + one DB row; publish a third poll without the slot → row gets `duration_seconds`. Chaos test: run the consumer as a subprocess with `MISE_CRASH_AFTER=state_write` env hook (SIGKILL self after hash write, before commit), restart without the hook → zero duplicate events (assert by `event_id` count). Unit tests for parser, tri-state transitions, deterministic event_id, coverage bounding, and the SETNX grep.

### Claude's Discretion
- Exact JSON field abbreviations inside the Redis hash values, structlog event names, Prometheus counter names (Phase 7 wires exporters; Phase 2 may define `Counter` objects in `shared/metrics.py` if convenient).
- `MISE_CRASH_AFTER` hook implementation detail; consumer poll timeout; how `polls.completed` and `availability.raw` are interleaved (single consumer with topic check is fine).
- Whether `hours_before_service` uses `zoneinfo` directly or a `shared/time.py` helper.

### Deferred Ideas (OUT OF SCOPE)
- Kafka transactional exactly-once (consume→produce) — revisit post-MVP; deterministic event_id + Layer-2 covers MVP.
- `slot_closed` Kafka events for the SSE feed — Phase 5 can read closures from DB if needed.
- Resy parser — Phase 3.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description (verbatim from REQUIREMENTS.md) | Research Support |
|----|---------------------------------------------|------------------|
| STATE-01 | Redis availability state set (`avail:{restaurant_id}:{date}:{party_size}`) tracks currently known slot tokens per (restaurant, date, party) with 25-hour TTL | §Redis State Store — HASH + key-level `EXPIRE 90000` verified on Redis 7.2; per-field `HEXPIRE` is **not** available on the pinned server (§Pitfall 6) |
| STATE-02 | State machine consumes `availability.raw`; computes tri-state diff (appeared / disappeared / unchanged) against current Redis state | §Pattern 1 (pure `DiffEngine` + `StateStore` protocol), §Pattern 2 (coverage bounding), §Pitfall 1 (party-size coverage mismatch — verified defect) |
| STATE-03 | For newly appeared slots, state machine schedules confirmation poll at t+8 seconds via Redis ZSET (not inline `asyncio.sleep`); confirmation poll re-verifies against source, and only confirmed slots emit `availability.events` | §Pattern 3 + verified `EXPEDITE_POLL_LUA` (`ZADD XX LT` / `GETDEL` executed against live Redis 7.2 — exact outputs in §Code Examples) |
| STATE-04 | Emission-layer idempotency — `SET NX EX` on key `event:{rid}:{date}:{party}:{token}` (20-minute TTL) prevents duplicate event emission across consecutive polls and consumer redelivery | §Pattern 4 (emit ordering), existing `shared/redis_keys.py::set_nx_ex`, §Code Examples (verified `SET … NX EX 1200` returns `OK` then `nil`) |
| STATE-05 | `availability.events` persist to TimescaleDB `availability_events` hypertable with `first_seen_at`, `last_seen_at`, `duration_seconds`, `hours_before_service`, `day_of_week` | §Blocking Correction B-2 / B-3 (unique-index and PK constraints on hypertables, both reproduced live), §Code Examples (upsert + chunk-pruned close), §Pattern 6 (`zoneinfo` service-time math) |
| STATE-06 | Replay script — given an `availability.raw` Kafka offset range, replays state machine and produces identical `availability.events` output (portfolio artifact) | §Pattern 5 + verified bounded-consumption recipe (`group_id=None` + `assign` + `seek` + `end_offsets`, executed against cp-kafka 7.6.0), §Pattern 7 (byte-stable `model_dump_json()`) |
</phase_requirements>

---

## Summary

Phase 2 is not a "new library" phase — it introduces **zero new dependencies**. Every package it needs (`aiokafka==0.13.0`, `redis==7.4.0`, `sqlalchemy[asyncio]==2.0.49`, `asyncpg==0.31.0`, `pydantic==2.13.3`, `alembic==1.18.4`, `testcontainers 4.14.2`, `pytest-asyncio 1.3.0`) is already pinned in `pyproject.toml` and installed in `.venv`. The entire research risk therefore sits in **exact API semantics** and in **five locked-decision statements that do not compile or do not run as written**. Those five are enumerated in §Blocking Corrections and each was reproduced live this session — they are not stylistic quibbles, they are `TypeError` / `ERROR: cannot create a unique index` / `duplicate key value violates unique constraint` failures that would surface at execution time.

The three highest-cost surprises, in order:
1. **`AIOKafkaConsumer` takes `*topics` as varargs, not a list.** D-47's literal `AIOKafkaConsumer(["availability.raw", "polls.completed"], …)` raises `TypeError: unhashable type: 'list'` at construction. Verified.
2. **TimescaleDB refuses a unique index that omits the partitioning column.** D-48's `unique index (restaurant_id, event_id)` fails with `ERROR: cannot create a unique index without the column "time" (used in partitioning)`. Verified against `timescale/timescaledb:2.17.2-pg16`.
3. **`availability.raw.restaurant_id` carries the OpenTable *platform rid*, not `restaurants.id`.** `scripts/seed_restaurants.py:109` seeds `make_job("opentable", int(platform_id))` into `sched:polls`, and `services/poller/scheduler.py` passes that value straight through as `rid` and into `request_params["rid"]`. Every Redis key, event payload and hypertable row Phase 2 writes will therefore be keyed on the platform rid. Phase 4/5/6 must join through `restaurants(source, platform_id)`, not `restaurants.id`. This must be decided in Phase 2, not discovered in Phase 4.

Beyond those, the phase is well-served by patterns already in the repo: `shared/scheduler/lua.py::LuaScheduler` gives the EVALSHA-with-NOSCRIPT-fallback shape for `EXPEDITE_POLL_LUA` verbatim; `shared/redis_keys.py::set_nx_ex` already implements STATE-04's atomic primitive; `services/poller/main.py` gives the startup-guard/lifecycle shape for `services/state_machine/main.py`. The one genuinely new engineering problem is **byte-identical replay**, and Pydantic v2's `model_dump_json()` was verified to be deterministic (declaration-order field emission, input-dict-order-insensitive, `Z`-suffixed datetimes, stable float repr) — combined with D-45's wall-clock-free event contract, byte-identical replay is achievable without a custom serializer.

**Primary recommendation:** Plan Wave 0 as "correct the five locked-decision defects + write migration 0008 + establish `tests/fixtures/raw_streams/`", then build `DiffEngine` as a pure, Redis-free, DB-free core behind a `StateStore` protocol and drive **all** correctness tests (transient-error → zero events, flapping, coverage bounding, deterministic `event_id`) through `MemoryStateStore` in `tests/unit/` where they run in milliseconds. Reserve testcontainers for exactly three integration tests: e2e emit+persist, chaos kill -9, and replay byte-identity.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Raw payload → normalised slots | Stream processor (`parsers/`) | — | Source-specific shape knowledge must not leak into the diff engine (D-37, Phase 3 SC5) |
| Tri-state diff / transition decision | Pure domain core (`engine.py`) | — | Must run with no I/O so replay and unit tests are deterministic (D-49) |
| Current availability state | Redis (HASH, 25h TTL) | In-memory (`MemoryStateStore`) for replay | Survives consumer restart; TTL bounds unbounded growth (STATE-01) |
| Confirmation scheduling (t+8s) | Redis ZSET `sched:polls` (owned by poller) | Redis string flag `sched:expedite:*` when job is in-flight | Latency budget too tight for a Kafka round-trip; scheduler already owns poll issuance (ARCHITECTURE.md §Pattern 3, Anti-Pattern 3) |
| Emission idempotency (Layer 1) | Redis string `event:*` `SET NX EX 1200` | Deterministic `event_id` (Layer 1.5) | Redis key is the fast path; `uuid5` makes the *content* idempotent even if the key expires or Redis is flushed (STATE-04) |
| Event durability / ordering | Kafka `availability.events`, key `{source}:{rid}` | — | Downstream Phase 4 + Phase 5 consumers; single partition preserves per-restaurant order (D-29, D-45) |
| Offset progress | Kafka consumer group `state-machine`, manual commit | — | Commit-after-side-effects is the only at-least-once-safe ordering (PITFALLS.md §Pitfall 4) |
| Analytics rows (`availability_events`) | TimescaleDB hypertable | — | Read by Phase 6 pattern model + heatmap CAGG; explicitly best-effort so a DB outage cannot stall the emit path (D-48) |
| Replay / offset-range reconstruction | Standalone script (`scripts/replay_raw.py`) | `MemoryStateStore` | No consumer group, no Redis, no DB — otherwise the run is not reproducible (D-50) |

---

## Project Constraints (from CLAUDE.md and CI)

`./CLAUDE.md` embeds the stack-research document rather than a directive list; the enforceable directives live in `.ruff.toml`, `pyproject.toml [tool.mypy]`, `Makefile`, and `.github/workflows/lint.yml`. All were read this session.

| Constraint | Source | Enforcement |
|------------|--------|-------------|
| No `import requests` / `from requests ` in `services/`, `shared/` | `.github/workflows/lint.yml` step `ban_requests_import` | `! grep -rn "^import requests\|^from requests " services/ shared/` [VERIFIED: .github/workflows/lint.yml:19-21] |
| No `time.sleep(` anywhere in `services/`, `shared/` | `.github/workflows/lint.yml` step `ban_time_sleep_in_async` | `! grep -rn "time\.sleep(" services/ shared/` [VERIFIED: .github/workflows/lint.yml:22-24] |
| No sync redis import in `services/`, `shared/` | `.github/workflows/lint.yml` step `ban_sync_redis_import` | `! grep -rEn "^import redis$\|^from redis import " services/ shared/` [VERIFIED: .github/workflows/lint.yml:25-27] — note `import redis.asyncio as redis` passes; `import redis` alone does not |
| `ruff check .` clean, `line-length = 120`, `select = ["E","F","W","I","UP","ASYNC"]` | `.ruff.toml:1-6` | `make lint` |
| `mypy shared/ services/` clean under `strict = true`, `python_version = "3.12"` | `pyproject.toml [tool.mypy]` | `make lint` — see §Pitfall 3 for the redis-py typing trap this creates |
| `scripts/**` is exempt only from `ASYNC240`; the ban-greps do **not** cover `scripts/` | `.ruff.toml [lint.per-file-ignores]` + CI grep paths | `scripts/replay_raw.py` is not grep-scanned, but should still be async-clean for consistency |
| Async-only stack: `redis.asyncio`, `aiokafka`, SQLAlchemy async | D-03/D-04/D-05 (locked in Phase 1) | Reviewed per-file |
| Every Redis key pattern and TTL declared in `shared/redis_keys.py` | D-18, D-42 | `tests/unit/test_redis_keys.py` precedent |
| Every Kafka message schema declared in `shared/events.py` | D-06 | `tests/unit/test_events_schema.py` precedent |
| Alembic migrations only; never `--autogenerate` against a hypertable | D-30, D-33, PITFALLS.md §Pitfall 12 | Migration `0006` comment: `# NEVER use \`alembic revision --autogenerate\` on a hypertable (Pitfall 12, D-33)` [VERIFIED: migrations/versions/0006_create_availability_events_hypertable.py:30] |

---

## Blocking Corrections to Locked Decisions

> These are not alternatives to locked decisions — they are defects in the *literal wording* of locked decisions that were reproduced as hard runtime errors this session. The planner MUST encode the corrected form in PLAN.md tasks; the intent of each decision is preserved.

### B-1 — `AIOKafkaConsumer` topics are varargs, not a list (D-47)

`aiokafka/consumer/consumer.py` declares `def __init__(self, *topics, loop=None, …)`; `inspect` reports `topics kind: VAR_POSITIONAL`. Executed inside a running loop:

```
LIST form ERROR: TypeError unhashable type: 'list'
VARARG form subscription = frozenset({'availability.raw', 'polls.completed'})
```
[VERIFIED: aiokafka 0.13.0 in .venv — executed 2026-09-05]

**Corrected form:**
```python
consumer = AIOKafkaConsumer(
    "availability.raw", "polls.completed",
    bootstrap_servers=..., group_id="state-machine",
    enable_auto_commit=False, auto_offset_reset="earliest",
    max_poll_records=1,
)
```
Second gotcha in the same constructor: `AIOKafkaConsumer` calls `get_running_loop()` in `__init__` and raises `RuntimeError: The object should be created within an async function or provide loop directly.` if constructed at module import time. [VERIFIED: aiokafka/util.py:89 via traceback] Construct it inside `async def run()`, exactly as `services/poller/main.py` does for the producer.

### B-2 — A unique index on a hypertable must include `time` (D-48)

D-48 specifies `unique index (restaurant_id, event_id)`. Executed against `timescale/timescaledb:2.17.2-pg16`:

```
=== TEST A: unique index WITHOUT time (D-48 literal) ===
ERROR:  cannot create a unique index without the column "time" (used in partitioning)
=== TEST B: unique index WITH time ===
CREATE INDEX
```
[VERIFIED: live TimescaleDB 2.17.2 container — executed 2026-09-05]

`ON CONFLICT` inherits the restriction — an arbiter that omits `time` fails with `ERROR: there is no unique or exclusion constraint matching the ON CONFLICT specification`. [VERIFIED: same session]

**Corrected form for migration 0008:** `UNIQUE INDEX uq_availability_events_event_id_time ON availability_events (event_id, "time")`. Every `ON CONFLICT` and every close-`UPDATE` must name `time` in the predicate.

### B-3 — PK `(time, restaurant_id)` collides when one poll confirms two slots (D-48, `shared/db.py`)

`shared/db.py` declares:

```python
class AvailabilityEvent(Base):
    __tablename__ = "availability_events"
    time: Mapped[datetime] = mapped_column(TIMESTAMP(timezone=True), nullable=False, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, primary_key=True)
```
[VERIFIED: shared/db.py:109-112 — quoted verbatim]

Migration `0006` never creates that primary key — it creates only `op.create_index("ix_avail_events_restaurant_time", "availability_events", ["restaurant_id", "time"])` [VERIFIED: migrations/versions/0006_create_availability_events_hypertable.py:35 — quoted verbatim], a non-unique index. So the ORM PK is declarative-only today.

That is load-bearing, because D-45 sets `confirmed_at_epoch_ms` to the *confirming poll's* `polled_at_epoch_ms` — identical for every slot confirmed by that one poll. Adding the declared PK to the DB produces, on the second slot:

```
ERROR:  duplicate key value violates unique constraint "2_2_availability_events_pkey"
DETAIL:  Key ("time", restaurant_id)=(2026-05-02 23:00:00+00, 42) already exists.
```
[VERIFIED: live TimescaleDB 2.17.2 — two slots, same restaurant, same `time`]

The same shape breaks D-48's close-`UPDATE`: `WHERE time=… AND restaurant_id=…` matches *every* slot confirmed in that poll, so closing one slot would stamp `duration_seconds` on all of them.

**Corrected form:** migration 0008 adds `event_id UUID NOT NULL` (table is empty — no backfill needed) plus `UNIQUE (event_id, "time")`; remap the ORM `primary_key=True` to `time` + `event_id` and drop it from `restaurant_id`. Close by `WHERE event_id = :event_id AND "time" = :confirmed_at` — verified to use an index scan on a single chunk (plan in §Code Examples). Omitting `time` from that `WHERE` degrades to a bitmap scan across **every** chunk. [VERIFIED: `EXPLAIN` output, both forms, same session]

### B-4 — `request_params["party_sizes"]` over-states what the poll actually covered (D-38)

`services/poller/scheduler.py` builds:

```python
request_params: dict[str, Any] = {
    "rid": restaurant_id,
    "dates": [d.isoformat() for d in dates],
    "party_sizes": list(DEFAULT_PARTY_SIZES),
}
```
[VERIFIED: services/poller/scheduler.py:79-83 — quoted verbatim], with `DEFAULT_PARTY_SIZES: list[int] = [2, 4]` [VERIFIED: services/poller/config.py:20 — quoted verbatim].

But `OpenTableAdapter.poll` is a single call — `return await self._fetch(rid, dates, party_sizes)` [VERIFIED: services/poller/sources/opentable/adapter.py:105 — quoted verbatim] — and `build_request` sends only:

```python
        "variables": {
            "restaurantIds": [rid],
            "partySize": party_sizes[0],  # Primary party size; adapter loops for multiple
```
[VERIFIED: services/poller/sources/opentable/graphql.py:45-47 — quoted verbatim; the trailing comment is aspirational, the adapter does **not** loop]

So a poll declaring coverage of `{2, 4}` actually observed only party size `2`. Under D-38 as written, every party-4 slot is "covered and absent" on every single poll → guaranteed false closures on every cycle, and every party-4 PENDING slot is dropped before it can ever confirm.

**Corrected form:** the OpenTable parser must derive coverage as `{(d, request_params["party_sizes"][0]) for d in request_params["dates"]}` — the *effective* party size — not the declared list. Add a `# TODO(P3/POLL-02)` marker: when Phase 3 makes the adapter loop party sizes, coverage widens to the full list. Add a unit test asserting that a party-2-only poll never closes a party-4 slot; this test is the regression guard for the Phase 3 change.

### B-5 — `day_of_week` convention conflicts with the migration comment (D-48)

Migration 0006 annotates the column `sa.Column("day_of_week", sa.Integer, nullable=True),  # 0=Mon..6=Sun` [VERIFIED: migrations/versions/0006_create_availability_events_hypertable.py:27 — quoted verbatim]. D-48 specifies `isoweekday()%7` (0=Sun … 6=Sat). Verified mapping:

```
2026-05-03 weekday()= 6 isoweekday()= 7 isoweekday()%7= 0 Sun
2026-05-04 weekday()= 0 isoweekday()= 1 isoweekday()%7= 1 Mon
2026-05-09 weekday()= 5 isoweekday()= 6 isoweekday()%7= 6 Sat
```
[VERIFIED: Python 3.12.13 `datetime.date` — executed 2026-09-05]

D-48 wins (it is the locked decision and matches the Phase 6 heatmap y-axis). Migration 0008 must include `op.execute("COMMENT ON COLUMN availability_events.day_of_week IS '0=Sun .. 6=Sat (isoweekday() % 7)'")` and the stale inline comment in 0006 must be corrected in a follow-up comment, not silently left to mislead Phase 6.

---

## Standard Stack

### Core — all already pinned, no installation required

| Library | Version (verified installed) | Purpose | Why Standard |
|---------|------------------------------|---------|--------------|
| `aiokafka` | 0.13.0 | Consumer for `availability.raw` + `polls.completed`, producer for `availability.events` | D-02 locked; pure-asyncio API, no background thread to reason about at 400 events/day |
| `redis` (`redis.asyncio`) | 7.4.0 | State HASHes, idempotency strings, expedite ZSET/flag, Lua | D-03 locked; `aioredis` is dead (merged into redis-py 4.2) |
| `sqlalchemy[asyncio]` | 2.0.49 | `availability_events` insert/update via `AsyncSession` | D-04 locked; `shared/db.py` already wires `async_sessionmaker` |
| `asyncpg` | 0.31.0 | Async PG driver for the hot path | D-04 locked |
| `pydantic` | 2.13.3 | `AvailabilityEvent` schema + byte-stable `model_dump_json()` | D-06 locked; determinism verified (§Pattern 7) |
| `alembic` | 1.18.4 | Migration 0008 (`event_id` + unique index) | D-30 locked |
| `structlog` | 25.5.0 | `shared.telemetry.get_logger` | D-12 locked |

[VERIFIED: `importlib.metadata.version()` for each, executed against `/Users/aryanahuja/projects/mise/.venv` 2026-09-05]

### Supporting (test tier)

| Library | Version (verified installed) | Purpose | When to Use |
|---------|------------------------------|---------|-------------|
| `pytest` | 9.0.3 | Runner | All |
| `pytest-asyncio` | 1.3.0 | `asyncio_mode = "auto"` | All async tests |
| `testcontainers` | 4.14.2 | Ephemeral Kafka/Redis/Timescale | Integration tier only (3 tests) |
| `freezegun` | 1.5.5 | Not needed — D-44/D-45 are message-timestamp driven, never wall-clock | Avoid; see §Pitfall 8 |
| `respx` | 0.23.1 | Not needed in Phase 2 — the state machine makes no HTTP calls (D-43 is stream-based) | Skip |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Two topics on one consumer (D-47) | Two `AIOKafkaConsumer` instances, one per topic | One consumer is simpler and D-47 locks it, **but** `getone()` on a multi-topic subscription is not fair — see §Pitfall 2 for the required mitigation |
| Redis HASH per `(rid, date, party)` (D-40) | Redis JSON / RedisStack | HASH + key-level `EXPIRE` needs no modules and works on the pinned `redis:7.2-alpine`; `HEXPIRE` does not exist there (§Pitfall 6) |
| `INSERT … ON CONFLICT DO NOTHING` for the analytics row | Plain `INSERT` + swallow `IntegrityError` | `ON CONFLICT` is one round-trip and keeps the session usable; a raised `IntegrityError` aborts the transaction and forces a rollback |
| Kafka transactions (exactly-once consume→produce) | `AIOKafkaProducer(transactional_id=…)` | Explicitly deferred in CONTEXT.md §Deferred Ideas; the `SET NX EX` + deterministic `uuid5` pair covers MVP |

**Installation:** none. `uv sync --frozen` already provides everything.

---

## Package Legitimacy Audit

**Phase 2 installs zero new external packages.** Every import is either stdlib (`uuid`, `zoneinfo`, `json`, `signal`, `os`, `argparse`, `dataclasses`, `typing`) or an already-pinned dependency verified present in `.venv` this session.

| Package | Registry | Already pinned | Verified installed version | Verdict | Disposition |
|---------|----------|----------------|----------------------------|---------|-------------|
| `aiokafka` | PyPI | `pyproject.toml` `aiokafka==0.13.0` | 0.13.0 | OK | Approved (pre-existing) |
| `redis` | PyPI | `pyproject.toml` `redis==7.4.0` | 7.4.0 | OK | Approved (pre-existing) |
| `sqlalchemy[asyncio]` | PyPI | `pyproject.toml` `sqlalchemy[asyncio]==2.0.49` | 2.0.49 | OK | Approved (pre-existing) |
| `asyncpg` | PyPI | `pyproject.toml` `asyncpg==0.31.0` | 0.31.0 | OK | Approved (pre-existing) |
| `pydantic` | PyPI | `pyproject.toml` `pydantic==2.13.3` | 2.13.3 | OK | Approved (pre-existing) |
| `alembic` | PyPI | `pyproject.toml` `alembic==1.18.4` | 1.18.4 | OK | Approved (pre-existing) |
| `structlog` | PyPI | `pyproject.toml` `structlog==25.5.0` | 25.5.0 | OK | Approved (pre-existing) |
| `testcontainers` | PyPI | dev group `testcontainers[kafka,redis,postgres]>=4.8` | 4.14.2 | OK | Approved (pre-existing) |
| `pytest-asyncio` | PyPI | dev group `pytest-asyncio==1.3.0` | 1.3.0 | OK | Approved (pre-existing) |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

**If the plan proposes any package not in the table above, it is out of Phase 2 scope** and must be gated behind a `checkpoint:human-verify` task. `orjson==3.11.8` is present in the project but must **not** be substituted for `model_dump_json()` in the replay path — see §Pitfall 7.

---

## Architecture Patterns

### System Architecture Diagram

```
                          ┌───────────────────────────────────────┐
   Kafka                  │      services/state_machine/          │
   availability.raw ─────▶│  consumer.py  (side-effect shell)     │
   polls.completed  ─────▶│                                       │
                          │   1. route by msg.topic               │
                          │      ├─ polls.completed(error|timeout)│──▶ Redis: avail:{rid}:meta
                          │      │                                │      HSET unknown_since_ms
                          │      └─ availability.raw              │
                          │            │                          │
                          │            ▼                          │
                          │   2. parsers/registry.parse_raw()     │
                          │      opentable.py | resy.py(P3)       │
                          │            │                          │
                          │      ParseError ──────────────────────│──▶ Redis: mark UNKNOWN,
                          │            │                          │      emit nothing
                          │            ▼                          │
                          │   3. engine.DiffEngine.process()      │
                          │      ── PURE. no I/O. ──              │
                          │      reads/writes via StateStore ─────│◀──▶ RedisStateStore
                          │            │                          │      avail:{rid}:{date}:{party}
                          │            │                          │      HASH, EXPIRE 90000
                          │            ▼                          │
                          │      decisions: [Expedite | Emit |    │
                          │                  Close | NoOp]        │
                          │            │                          │
                          │   4a. Expedite ───────────────────────│──▶ Redis Lua EXPEDITE_POLL_LUA
                          │        (slot → PENDING)               │      ZADD XX LT sched:polls
                          │                                       │      else SET sched:expedite:* EX 120
                          │                                       │           │
                          │   4b. Emit  (PENDING→AVAILABLE,       │           │  poller release path
                          │        Δt ≥ 8000ms)                   │           │  GETDEL → re-poll at +8s
                          │        ├ SET event:… NX EX 1200 ──────│──▶ Redis  │
                          │        ├ producer.send_and_wait ──────│──▶ Kafka availability.events
                          │        ├ store.mark_available() ──────│──▶ Redis  ▼
                          │        └ INSERT ON CONFLICT ──────────│──▶ Timescale availability_events
                          │                                       │
                          │   4c. Close (AVAILABLE→UNAVAILABLE)   │
                          │        └ UPDATE … WHERE event_id AND  │──▶ Timescale (duration_seconds)
                          │                        "time"         │
                          │                                       │
                          │   5. consumer.commit({tp: off+1})     │──▶ Kafka __consumer_offsets
                          └───────────────────────────────────────┘
                                        ▲
                                        │ same engine, no I/O shell
                          ┌─────────────┴─────────────────────────┐
   raw.jsonl / offsets ──▶│  scripts/replay_raw.py                │──▶ events.jsonl
                          │  group_id=None + assign + seek        │    (byte-identical)
                          │  DiffEngine(MemoryStateStore())       │
                          └───────────────────────────────────────┘
```

Trace the primary use case by following the arrows: a raw poll enters at top-left, is parsed, diffed against Redis, produces a PENDING slot that expedites the next poll to t+8s; the expedited poll re-enters at the same top-left arrow and this time the diff yields Emit, which fans out to the idempotency key, Kafka, Redis state, and the hypertable, before a single offset commit closes the message. The replay path reuses the identical middle box with the I/O shell removed.

### Recommended Project Structure

```
services/state_machine/
├── __init__.py
├── __main__.py            # asyncio.run(main.run())  — mirrors services/poller/__main__.py
├── main.py                # lifecycle: topic guard, redis, producer, consumer, gather
├── config.py              # env: KAFKA_BOOTSTRAP_SERVERS, REDIS_URL, DATABASE_URL_ASYNC,
│                          #      CONFIRM_DELAY_MS=8000, MISE_CRASH_AFTER
├── consumer.py            # side-effect shell: route, expedite, emit, persist, commit
├── engine.py              # DiffEngine + StateStore Protocol + decision dataclasses  (PURE)
├── store.py               # RedisStateStore, MemoryStateStore
├── models.py              # Slot, ParsedPoll, SlotState enum   (PURE)
├── persistence.py         # insert_event / close_event  (SQLAlchemy async)
├── parsers/
│   ├── __init__.py        # registry: parse_raw(raw) dispatch on raw.source
│   ├── opentable.py       # data.availability[].availability[].timeSlots[]
│   └── errors.py          # ParseError, UnsupportedSourceError
└── README.md              # state-transition table + D-46 ordering diagram (CONTEXT §Specifics)

shared/
├── events.py              # + AvailabilityEvent, NAMESPACE_MISE
├── redis_keys.py          # + avail_state_key, avail_meta_key, event_idempotency_key,
│                          #   sched_expedite_key, EXPEDITE_POLL_LUA, TTL constants
├── kafka.py               # + make_consumer()
└── scheduler/lua.py       # + LuaScheduler.expedite()

scripts/replay_raw.py
migrations/versions/0008_add_event_id_to_availability_events.py
tests/fixtures/raw_streams/{happy,transient_errors,flapping}.jsonl
tests/fixtures/raw_streams/{happy,transient_errors,flapping}.events.jsonl   # golden
```

### Pattern 1: Pure functional core, imperative shell (D-49)

**What:** `DiffEngine.process(parsed) -> list[Decision]` performs *no* I/O. All state access goes through a `StateStore` `Protocol`; all effects are returned as data for `consumer.py` to execute.

**When to use:** Whenever the same logic must run in production (Redis-backed) and in replay (memory-backed) and produce identical output. This is the mechanism that makes STATE-06 achievable at all.

**Why it matters here:** if `DiffEngine` touched Redis, `scripts/replay_raw.py` would need a Redis instance and its output would depend on leftover state — byte-identity would be unprovable in CI.

```python
# services/state_machine/engine.py
from typing import Protocol

class StateStore(Protocol):
    async def get_slots(self, rid: int, date: str, party: int) -> dict[str, SlotRecord]: ...
    async def put_slot(self, rid: int, date: str, party: int, key: str, rec: SlotRecord) -> None: ...
    async def drop_slot(self, rid: int, date: str, party: int, key: str) -> None: ...
    async def get_meta(self, rid: int) -> MetaRecord: ...
    async def put_meta(self, rid: int, meta: MetaRecord) -> None: ...
```

Returning `list[Decision]` (rather than emitting inline) is what lets the chaos test crash *between* decisions deterministically.

### Pattern 2: Coverage-bounded closure (D-38, corrected per B-4)

**What:** Never infer "gone" from "absent" alone. Only close a slot whose `(date, party_size)` appears in the poll's **effective** coverage set.

```python
def effective_coverage(request_params: dict[str, Any]) -> set[tuple[str, int]]:
    """OpenTable adapter issues ONE GraphQL call with partySize=party_sizes[0]
    (services/poller/sources/opentable/graphql.py:47). Declared party_sizes is [2, 4]
    but only [0] is actually observed. TODO(P3/POLL-02): widen when the adapter loops.
    """
    dates = request_params.get("dates") or []
    parties = request_params.get("party_sizes") or []
    if not dates or not parties:
        return set()
    return {(d, int(parties[0])) for d in dates}
```

**Anti-pattern this replaces:** `coverage = set(product(dates, party_sizes))` — reads correctly, closes every party-4 slot on every poll.

### Pattern 3: Expedite through the scheduler, never `asyncio.sleep` (D-43, STATE-03)

**What:** The state machine lowers the *existing* poll's due-score rather than issuing a poll. Two cases, one Lua script, one round-trip:
- Job sitting in `sched:polls` → `ZADD sched:polls XX LT (now+8000) {job}`. `XX` refuses to create a member that is not there (so an in-flight job is not resurrected); `LT` refuses to *raise* a score (so an already-sooner poll is not delayed).
- Job absent (currently in `sched:polls:inflight`) → `SET sched:expedite:{job} 1 EX 120`, which the poller's release path consumes with `GETDEL`.

**Why not `ZADD GT`/plain `ZADD`:** plain `ZADD` would resurrect an in-flight job into the ready set, producing a concurrent duplicate poll; `GT` would push the poll *later*.

All four semantics were executed against live Redis 7.2 — outputs in §Code Examples.

**Poller-side change (`services/poller/scheduler.py:138`):** today the release is unconditional:
```python
        next_score = _next_poll_score(int(time.time() * 1000))
        await scheduler.release(job, next_score)
```
[VERIFIED: services/poller/scheduler.py:138-139 — quoted verbatim]. It becomes: `GETDEL sched:expedite:{job}`; if the value is non-`None`, `next_score = now_ms + 8000`, else the existing jittered score. `GETDEL` returns the value then `nil` on the second call, so the flag is consumed exactly once. [VERIFIED: live Redis 7.2]

### Pattern 4: Emit ordering — claim, send, record, commit (D-46, STATE-04)

The order is not arbitrary; each step is chosen so that a crash at any point is safe:

| Crash point | Redis `event:*` | Kafka | Redis state | Offset | Restart behaviour |
|-------------|-----------------|-------|-------------|--------|-------------------|
| before `SET NX` | absent | none | PENDING | uncommitted | full re-diff, emits once |
| after `SET NX`, before send | present | none | PENDING | uncommitted | NX fails + state PENDING → **re-send** same deterministic `event_id` (Layer-2 dedupes in P4) |
| after send, before state write | present | sent | PENDING | uncommitted | same as above — one duplicate on the wire, identical `event_id` |
| after state write, before commit | present | sent | AVAILABLE | uncommitted | NX fails + state AVAILABLE → **skip**. This is the D-51 chaos path. Zero duplicates. |
| after commit | present | sent | AVAILABLE | committed | not redelivered |

Verified premise: with `enable_auto_commit=False`, consuming offsets 0,1,2 and committing only `{tp: 1}` causes a restarted consumer in the same group to resume at offset **1**. Output: `after partial commit, restart resumes at offset: 1 (consumed [0, 1, 2] )` [VERIFIED: aiokafka 0.13.0 against cp-kafka 7.6.0 — executed 2026-09-05]. `commit()` takes the offset of the **next** record (`msg.offset + 1`), per its own docstring: `await consumer.commit({tp: msg.offset + 1})` [VERIFIED: `inspect.getdoc(AIOKafkaConsumer.commit)`].

Use `send_and_wait`, not `send`. `send` returns a future that resolves after the batch flushes; with `linger_ms=20` on the shared producer factory [VERIFIED: shared/kafka.py:31 — `linger_ms=20,                                  # small batching window`], a `send`-then-`commit` sequence can commit the offset before the broker has acked. `send_and_wait` returns `RecordMetadata` with `.offset`, `.topic`, `.timestamp` populated. [VERIFIED: live cp-kafka — `send_and_wait returns: RecordMetadata offset= 0 topic= availability.raw ts= 1788582742899`]

### Pattern 5: Bounded offset-range replay without a consumer group (D-50, STATE-06)

**What:** `scripts/replay_raw.py` must not join the `state-machine` group (that would move production offsets) and must stop at a precise offset. The recipe, executed end-to-end this session:

```python
consumer = AIOKafkaConsumer(bootstrap_servers=bs, group_id=None, enable_auto_commit=False)
await consumer.start()                       # start BEFORE assign
tp = TopicPartition("availability.raw", 0)
consumer.assign([tp])                        # sync call; incompatible with subscribe()
lo = (await consumer.beginning_offsets([tp]))[tp]
hi = (await consumer.end_offsets([tp]))[tp]  # last offset + 1
consumer.seek(tp, from_offset)               # sync call
while (await consumer.position(tp)) < to_offset:
    batches = await consumer.getmany(timeout_ms=2000, max_records=100)
    if not batches:
        break                                # no more data — do not spin
    for records in batches.values():
        for rec in records:
            if rec.offset >= to_offset:
                break
            yield rec
await consumer.stop()
```

Verified output against a 6-message topic:
```
beginning_offsets: {TopicPartition(topic='availability.raw', partition=0): 0} end_offsets: {TopicPartition(topic='availability.raw', partition=0): 6}
bounded replay offsets [2,5): [2, 3, 4]
offsets_for_times(t0): {TopicPartition(...): OffsetAndTimestamp(offset=0, timestamp=1788582742899)}
```
[VERIFIED: aiokafka 0.13.0 against cp-kafka 7.6.0 — executed 2026-09-05]

Notes the planner must encode: `assign()` and `seek()` are **synchronous**; `end_offsets`/`beginning_offsets`/`position`/`offsets_for_times` are coroutines; `end_offsets` returns *last offset + 1* (so `--to-offset` should be treated as exclusive to match); `offsets_for_times` exists and works, giving a free `--from-timestamp` variant if wanted. `assign()` raises `IllegalStateError` if `subscribe()` was called first.

`--input raw.jsonl` mode is the CI-friendly path (no broker), and is what the byte-identity test should use; the offset-range mode is the portfolio demo. Both feed the same generator into the same `DiffEngine`.

### Pattern 6: `zoneinfo` service-time math (D-48, Claude's discretion)

```python
from datetime import datetime, date, time as dtime, UTC
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")

def hours_before_service(service_date: date, slot: dtime, first_seen_ms: int) -> float:
    service_dt = datetime.combine(service_date, slot, tzinfo=NY)
    first_seen = datetime.fromtimestamp(first_seen_ms / 1000, tz=UTC)
    return (service_dt - first_seen).total_seconds() / 3600.0
```

Verified behaviour:
```
normal:  (5.0,  '2026-05-01T19:00:00-04:00', '2026-05-01T23:00:00+00:00')
dst-day: (29.0, '2026-03-08T19:00:00-04:00', '2026-03-08T23:00:00+00:00')
```
[VERIFIED: Python 3.12.13 `zoneinfo`, executed 2026-09-05]

DST edges are benign for this domain because dinner service times (17:00–23:00) never fall in the 01:00–03:00 transition window. For completeness: on the spring-forward day, the non-existent local 02:30 resolves to `2026-03-08T02:30:00-05:00` (silently, no exception), and the ambiguous fall-back 01:30 resolves to the pre-transition instant unless `fold=1` is set. [VERIFIED: same session] Put a one-line docstring note stating the 17:00–23:00 assumption rather than adding fold-handling code.

`day_of_week = service_date.isoweekday() % 7` (see B-5).

### Pattern 7: Byte-stable `model_dump_json()` (D-45, D-50)

Pydantic v2 `model_dump_json()` was verified deterministic in all three ways STATE-06 depends on:

```
json: {"event_id":"629d45e6-9621-5f62-a1ea-dd826ede29f8","event_type":"slot_opened","source":"opentable","restaurant_id":42,"hours":12.0,"when":"2026-05-01T19:00:00Z","opt":null}
byte-stable roundtrip: True
order-insensitive: True
```
[VERIFIED: pydantic 2.13.3 — executed 2026-09-05]

- **Field order follows model declaration order**, not input-dict order. Constructing from a reversed dict produced identical bytes.
- **No whitespace** — `model_dump_json()` emits compact separators by default.
- **`datetime` → RFC-3339 with `Z`** for UTC (`"2026-05-01T19:00:00Z"`). D-45 avoids `datetime` fields entirely by using `*_epoch_ms: int`, which is safer still.
- **Floats use Python's shortest-repr** (`0.3333333333333333`) — stable across runs on the same interpreter. D-45's event has no float field; keep it that way.
- **`None` → `null`**, and optional fields are emitted (not omitted) unless `exclude_none=True`. Do **not** pass `exclude_none` / `exclude_unset` in the replay path — they make output depend on construction style.

`uuid5` determinism confirmed: `uuid.uuid5(NS, "opentable:42:2026-05-01:2:19:00|bar:abc")` returned `f42d3b2a-d4ed-5b77-a3a7-27cee31747c4` on repeated calls. [VERIFIED: Python 3.12.13]

Define `NAMESPACE_MISE` as a module-level literal UUID in `shared/events.py` (e.g. derived once via `uuid5(NAMESPACE_URL, "https://mise.place/events")` and then **hard-coded**), never recomputed at import — a future URL change would silently invalidate every historical `event_id`.

### Anti-Patterns to Avoid

- **`await asyncio.sleep(8)` inside the consumer** to wait for confirmation. Blocks the partition, loses the pending confirmation on crash, bypasses the rate limiter. (ARCHITECTURE.md §Anti-Pattern 3.) D-43 exists precisely to avoid this. Note `asyncio.sleep` is *not* caught by the CI `time.sleep(` grep — a reviewer must catch it.
- **Sharing one Redis key for state and idempotency.** Different lifecycles (25h vs 20min); flushing state to debug would silently disable dedup. (ARCHITECTURE.md §Anti-Pattern 2.)
- **Emitting from the parser or the poller.** Diff logic must be replayable and restart-safe; it belongs in a separate stateful service. (ARCHITECTURE.md §Anti-Pattern 1.)
- **Wall-clock (`time.time()`) anywhere inside `DiffEngine`.** Every timestamp in a decision must come from `polled_at_epoch_ms` on the message. A single `time.time()` in the engine breaks byte-identical replay, and the failure is *intermittent* — the worst kind.
- **Querying watchlists from the state machine.** `availability.events` is user-agnostic; fanout is Phase 4's job. (ARCHITECTURE.md §Anti-Pattern 5.)
- **`alembic revision --autogenerate` for migration 0008.** It does not understand hypertables and will propose dropping/recreating the table. Hand-write it, following the `op.execute` style of 0006. (PITFALLS.md §Pitfall 12, D-33.)

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic idempotency claim | `if not await r.exists(k): await r.set(k, 1); await r.expire(k, 1200)` | `shared.redis_keys.set_nx_ex(r, key, "1", 1200)` — already exists | Two-command SETNX+EXPIRE deadlocks on crash between commands; PITFALLS.md §Pitfall 7 makes zero occurrences a phase-exit criterion (SC3) |
| Lowering a scheduled job's due time | read `ZSCORE`, compare in Python, `ZADD` | `ZADD sched:polls XX LT <score> <job>` in Lua | Read-compare-write races with the poller's `claim`; `XX LT` is atomic and server-side. Verified working on Redis 7.2 |
| Consume-once flag | `GET` then `DEL` | `GETDEL` | Two commands allow a double-expedite under concurrent release |
| EVALSHA + script reload on `NOSCRIPT` | new try/except per script | `shared.scheduler.lua.LuaScheduler._evalsha_with_fallback` — already exists | Redis restart or `SCRIPT FLUSH` silently breaks every EVALSHA; the fallback is already written and tested |
| Deterministic event identity | hash of `str(dict)` / `json.dumps(..., sort_keys=True)` | `uuid.uuid5(NAMESPACE_MISE, canonical_string)` | RFC-4122 name-based UUID, stable across processes and Python versions, and fits the `UUID` column type |
| Canonical JSON for replay | custom serializer / `orjson.dumps(..., OPT_SORT_KEYS)` | `AvailabilityEvent.model_dump_json()` | Verified byte-stable; a second serializer means two schemas to keep in sync, and `orjson` sorting would *change* field order away from the Kafka wire format |
| Analytics-row idempotency | `SELECT` then `INSERT` | `pg_insert(...).on_conflict_do_nothing(index_elements=["event_id","time"])` | Race-free single round-trip; SQLAlchemy 2.0.49 renders it correctly (verified) |
| Timezone arithmetic | `timedelta(hours=-5)` / `pytz` | stdlib `zoneinfo.ZoneInfo("America/New_York")` | Fixed offsets are wrong half the year; `pytz` requires `localize()` and is superseded by PEP 615 |
| Test-time waiting for the 8s gap | `await asyncio.sleep(9)` in tests | publish fixtures with hand-set `polled_at_epoch_ms` 9000ms apart | D-44 is defined on message timestamps, so the whole 8s rule is testable with zero wall-clock. Turns a 9-second test into a 9-millisecond one |

**Key insight:** almost every primitive this phase needs already exists in `shared/` from Phase 1 (`set_nx_ex`, `LuaScheduler`, `make_producer`, `get_async_session`, `get_logger`). The phase's job is to *extend* those modules (`make_consumer`, `LuaScheduler.expedite`, `avail_*_key`), not to introduce parallel implementations in `services/state_machine/`. D-42 makes this explicit for Redis keys; apply the same discipline to Kafka and DB access.

---

## Common Pitfalls

### Pitfall 1: Coverage over-declaration silently closes every party-4 slot
**What goes wrong:** Every poll marks all party-size-4 slots UNAVAILABLE; PENDING party-4 slots are dropped before they can confirm; no party-4 event is ever emitted, and the DB fills with 0-duration closures.
**Why it happens:** `request_params["party_sizes"]` is `[2, 4]` but `build_request` sends only `party_sizes[0]`. The mismatch is invisible in the fixture because `OPENTABLE_SUCCESS_RESPONSE` carries no `partySize` field at all.
**How to avoid:** Derive coverage from the effective party size (see B-4 / Pattern 2).
**Warning signs:** `availability_events` rows with `duration_seconds` ≈ 90 and `party_size = 4`; zero party-4 emissions in a 24h window.

### Pitfall 2: One consumer, two topics — `getone()` is not fair
**What goes wrong:** A `polls.completed{status:"error"}` for restaurant X is processed *after* a later successful `availability.raw` for X, re-marking a healthy restaurant UNKNOWN and suppressing real events until the next success.
**Why it happens:** `getone()` returns from whichever partition has prefetched data. In the verified run, all six `availability.raw` messages were returned before either `polls.completed` message:
```
topics seen: [('availability.raw', 0), ..., ('availability.raw', 5), ('polls.completed', 0), ('polls.completed', 1)]
```
[VERIFIED: aiokafka 0.13.0 against cp-kafka 7.6.0 — executed 2026-09-05]
**How to avoid:** Make the UNKNOWN mark *monotonic in poll time*: on `polls.completed`, only set `unknown_since_ms` if `polled_at_epoch_ms > meta.last_success_ms`. On a successful `availability.raw`, set `last_success_ms = polled_at_epoch_ms` and clear `unknown_since_ms`. This makes the outcome order-independent, which is also required for replay determinism.
**Warning signs:** `unknown_since_ms` set on a restaurant whose most recent raw poll succeeded.

### Pitfall 3: mypy strict rejects `await` on redis-py HASH commands
**What goes wrong:** `make lint` fails on every hash operation the state store makes.
**Why it happens:** redis-py types command methods as `Union[Awaitable[T], T]`. When `T` is `Any` the union collapses and `await` is accepted; when `T` is concrete it does not. Exact behaviour under `mypy --strict`:
```
probe3.py:4: error: Incompatible types in "await" (actual type "Awaitable[str | None] | str | None", ...)  [misc]   # hget
probe3.py:5: error: Incompatible types in "await" (actual type "Awaitable[dict[Any, Any]] | dict[Any, Any]", ...)  [misc]   # hgetall
probe3.py:6: error: Incompatible types in "await" (actual type "Awaitable[int] | int", ...)  [misc]   # hdel
probe3.py:7: error: Incompatible types in "await" (actual type "Awaitable[int] | int", ...)  [misc]   # hset
Found 4 errors in 1 file (checked 1 source file)
```
while `zscore`, `zadd`, `getdel` and `set` produce **no** error. [VERIFIED: mypy 1.x `--strict` against redis 7.4.0 — executed 2026-09-05]
**How to avoid:** the `cast(Awaitable[T], …)` pattern already used in `shared/scheduler/lua.py:47` — and it yields *precise* types, not `Any`:
```python
n: int = await cast(Awaitable[int], r.hset(key, mapping=fields))
rec: dict[bytes, bytes] = await cast(Awaitable[dict[bytes, bytes]], r.hgetall(key))
one = await cast(Awaitable[bytes | None], r.hget(key, field))
d: int = await cast(Awaitable[int], r.hdel(key, field))
```
```
Revealed type is "int" / "dict[bytes, bytes]" / "bytes | None"
Success: no issues found in 1 source file
```
[VERIFIED: same session]
**Cleanest structure:** put each cast **once**, inside a typed helper in `shared/redis_keys.py` (`hset_slot`, `hgetall_slots`, `hdel_slot`), exactly as `set_nx_ex` already does for `SET`. Then `store.py` contains zero `cast` calls and D-42 is satisfied by construction. Never reach for `# type: ignore[misc]` — it hides real signature drift on a future redis-py bump.

### Pitfall 4: Kafka rebalance mid-processing → `CommitFailedError`
**What goes wrong:** A slow DB write pushes processing past `max_poll_interval_ms` (default 300000 ms); the group rebalances; `commit()` raises `CommitFailedError`; the message is reprocessed.
**Why it happens:** Defaults favour throughput over safety (PITFALLS.md §Pitfall 10).
**How to avoid:** `max_poll_records=1` (verified accepted kwarg, default `None`); keep the DB write best-effort with its own timeout per D-48 so a Postgres stall cannot extend processing; catch `CommitFailedError` explicitly, log it, and let the redelivery path handle it — the `SET NX EX` + AVAILABLE-state check makes redelivery a no-op.
**Warning signs:** `CommitFailedError` in logs; consumer lag sawtooth.

### Pitfall 5: `restaurant_id` means two different things
**What goes wrong:** Phase 6's heatmap joins `availability_events.restaurant_id = restaurants.id` and returns zero rows, because the column actually holds OpenTable platform rids.
**Why it happens:** `scripts/seed_restaurants.py:109` seeds `{make_job("opentable", int(platform_id)): score}` [VERIFIED: scripts/seed_restaurants.py:109 — quoted verbatim], and `services/poller/scheduler.py` splits that job descriptor and passes the value straight through to `opentable.poll(rid=restaurant_id, …)` and into `request_params["rid"]`.
**How to avoid:** decide explicitly in Phase 2 (see §Open Questions Q1) and write the choice into a `COMMENT ON COLUMN` in migration 0008 plus a docstring on `AvailabilityEvent`. Do not let it stay implicit.
**Warning signs:** `SELECT count(*) FROM availability_events e JOIN restaurants r ON r.id = e.restaurant_id` returns 0 while the table is non-empty.

### Pitfall 6: `HEXPIRE` does not exist on the pinned Redis server
**What goes wrong:** Reaching for per-field HASH TTLs (a natural fit for per-slot expiry) fails at runtime, not at lint time, because redis-py 7.4.0 *has* the client method.
**Why it happens:** Per-field hash TTL is a Redis **7.4 server** feature; `conftest.py` pins `RedisContainer(image="redis:7.2-alpine")` and `ops/docker-compose.yml` pins `image: redis:7.2-alpine`. Live result:
```
ERR unknown command 'HEXPIRE', with args beginning with: 'avail:42:2026-05-01:2' '60' 'FIELDS' '1' '19:00|bar'
```
[VERIFIED: redis:7.2-alpine container — executed 2026-09-05]
**How to avoid:** key-level `EXPIRE 90000` refreshed on every write, exactly as D-40 specifies. Verified working: `EXPIRE` → `1`, `TTL` → `90000`.
**Warning signs:** `ResponseError: unknown command 'HEXPIRE'` at first write.

### Pitfall 7: A second serializer in the replay path
**What goes wrong:** `scripts/replay_raw.py` writes with `orjson.dumps(event.model_dump())` while the consumer writes to Kafka with `event.model_dump_json()`. The two differ in datetime/UUID rendering and field order; the golden file drifts from the wire format and the byte-identity test proves nothing about production.
**How to avoid:** one code path — `AvailabilityEvent.to_bytes()` on the model (mirroring `AvailabilityRaw.to_bytes` at `shared/events.py:25-26`), used by both the producer and the replay writer. The replay file is `to_bytes().decode() + "\n"` per line.
**Warning signs:** golden file diffs that are pure key reordering.

### Pitfall 8: Wall-clock leaking into the engine
**What goes wrong:** Replay output differs between runs; CI byte-identity flakes ~1 run in 20.
**Why it happens:** any `time.time()`, `datetime.now()`, `uuid4()`, or `random` inside `DiffEngine` or the parsers.
**How to avoid:** a unit test that greps `services/state_machine/engine.py`, `models.py`, and `parsers/` for `time.time(`, `datetime.now(`, `uuid4(`, `random.` and asserts zero matches — the same shape as the SETNX grep test D-51 already requires. This is cheap and it is the only mechanical guard against the flakiest failure in the phase.
**Warning signs:** `test_replay_byte_identical` passes locally and fails in CI, or vice versa.

### Pitfall 9: `ops/docker-compose.yml` pins a Kafka image that no longer exists
**What goes wrong:** `make up` fails on a clean machine with `failed to resolve reference "docker.io/bitnami/kafka:3.8": not found`. Any Phase 2 manual verification that depends on `make up` is blocked.
**Why it happens:** Bitnami withdrew their free Docker Hub catalogue; the tag moved to `bitnamilegacy/`. Live check:
```
docker pull bitnami/kafka:3.8 → Error response from daemon: failed to resolve reference "docker.io/bitnami/kafka:3.8": not found
bitnamilegacy/kafka:3.8 EXISTS
apache/kafka:3.8.0 EXISTS
confluentinc/cp-kafka:7.6.0 EXISTS
```
[VERIFIED: `docker manifest inspect`, executed 2026-09-05]
**How to avoid:** the testcontainers tier is unaffected (`conftest.py` uses `confluentinc/cp-kafka:7.6.0`, which resolves and is cached locally), so this does **not** block automated Phase 2 tests. But if any plan task says "run `make up`", add a companion task to repoint `ops/docker-compose.yml` to `apache/kafka:3.8.1` (KRaft-native, needs `KAFKA_` env names rather than Bitnami's `KAFKA_CFG_` names) or `bitnamilegacy/kafka:3.8` (drop-in, keeps every existing `KAFKA_CFG_*` var). Flag to the user before changing infra outside the phase boundary.
**Warning signs:** `make up` failing while `make test-integration` passes.

### Pitfall 10: Empty-response ambiguity
**What goes wrong:** A soft-banned or sanitised `200 OK` with `{"data": {"availability": []}}` is treated as a valid observation (D-39: "a well-formed response with zero slots is a *valid* observation and closes covered slots") and mass-closes every slot for that restaurant.
**Why it happens:** POLL-06 soft-ban canary is Phase 3; Phase 2 has no signal to distinguish a genuinely empty restaurant from a sanitised response.
**How to avoid:** honour D-39 as written (it is locked and correct for MVP), but log a distinct structlog event on any poll that closes more than N slots at once, so the Phase 3 canary has a training signal and the behaviour is auditable. Do not add heuristics that make the diff non-deterministic.
**Warning signs:** a burst of `AVAILABLE→UNAVAILABLE` transitions across many restaurants in the same minute.

---

## Code Examples

### `EXPEDITE_POLL_LUA` — verified against live Redis 7.2

```lua
-- KEYS[1] = sched:polls
-- KEYS[2] = sched:expedite:{source}:{restaurant_id}
-- ARGV[1] = now_ms
-- ARGV[2] = job descriptor '{source}:{restaurant_id}'
-- ARGV[3] = confirm_delay_ms (8000)
-- ARGV[4] = expedite flag TTL seconds (120)
-- Returns 'zset' if the queued job was pulled forward, 'flag' if the job is in flight.
local target = tonumber(ARGV[1]) + tonumber(ARGV[3])
if redis.call('ZSCORE', KEYS[1], ARGV[2]) then
  redis.call('ZADD', KEYS[1], 'XX', 'LT', target, ARGV[2])
  return 'zset'
else
  redis.call('SET', KEYS[2], '1', 'EX', tonumber(ARGV[4]))
  return 'flag'
end
```

Live transcript (Redis 7.2.16, `now_ms=1000`, `confirm_delay_ms=8000`):
```
=== setup ===
ZADD sched:polls 100000 opentable:42        → 1
=== EXPEDITE lua (job present) ===
EVAL ...                                     → zset
ZSCORE sched:polls opentable:42              → 9000
=== LT must not raise score ===
ZADD sched:polls XX LT 99999999 opentable:42 → 0
ZSCORE sched:polls opentable:42              → 9000
=== XX must not create missing member ===
ZADD sched:polls XX LT 5000 opentable:99     → 0
ZSCORE sched:polls opentable:99              → (nil)
=== flag path (job in flight) ===
ZREM sched:polls opentable:42                → 1
EVAL ...                                     → flag
=== GETDEL twice ===
GETDEL sched:expedite:opentable:42           → 1
GETDEL sched:expedite:opentable:42           → (nil)
```
[VERIFIED: redis:7.2-alpine container — executed 2026-09-05]

Wire it as a fourth script on `LuaScheduler`, following the existing `_evalsha_with_fallback` shape at `shared/scheduler/lua.py:42-50`.

### Redis state HASH with 25h TTL — verified

```
HSET "avail:42:2026-05-01:2" "19:00|bar" '{"s":"P","t":"tok","f":1}'  → 1
EXPIRE "avail:42:2026-05-01:2" 90000                                  → 1
TTL "avail:42:2026-05-01:2"                                           → 90000
HGETALL "avail:42:2026-05-01:2"                                       → 19:00|bar / {"s":"P","t":"tok","f":1}
```
[VERIFIED: redis:7.2-alpine — executed 2026-09-05]

### Layer-1 idempotency claim — verified

```
SET "event:42:2026-05-01:2:tok1" 1 NX EX 1200  → OK
SET "event:42:2026-05-01:2:tok1" 1 NX EX 1200  → (nil)
TTL "event:42:2026-05-01:2:tok1"               → 1200
```
[VERIFIED: redis:7.2-alpine — executed 2026-09-05]. `shared/redis_keys.py:29-36` already wraps this:
```python
async def set_nx_ex(r: Redis, key: str, value: str, ttl_seconds: int) -> bool:
    """
    Atomic SETNX+EX in a single Redis call (Pitfall 7).
    NEVER use two-command SETNX + EXPIRE.
    Returns True if key was set (did not exist), False if it already existed.
    """
    result = await r.set(key, value, nx=True, ex=ttl_seconds)
    return result is True
```
[VERIFIED: shared/redis_keys.py:29-36 — quoted verbatim]

### Migration 0008 (hand-written; never autogenerate)

```python
"""0008: Add event_id + unique (event_id, time) to availability_events (D-48, corrected)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Table is empty at this point (Phase 1 never wrote to it) — no backfill needed.
    op.add_column("availability_events", sa.Column("event_id", PG_UUID(as_uuid=True), nullable=True))
    op.execute("DELETE FROM availability_events WHERE event_id IS NULL")
    op.alter_column("availability_events", "event_id", nullable=False)
    # TimescaleDB: a UNIQUE index MUST include the partitioning column "time".
    # `CREATE UNIQUE INDEX ... (restaurant_id, event_id)` fails with
    # 'cannot create a unique index without the column "time" (used in partitioning)'.
    op.create_index(
        "uq_availability_events_event_id_time",
        "availability_events",
        ["event_id", "time"],
        unique=True,
    )
    op.execute(
        "COMMENT ON COLUMN availability_events.day_of_week IS "
        "'0=Sun .. 6=Sat (service_date.isoweekday() %% 7) — matches Phase 6 heatmap y-axis (D-48)'"
    )


def downgrade() -> None:
    op.drop_index("uq_availability_events_event_id_time", table_name="availability_events")
    op.drop_column("availability_events", "event_id")
```

### Insert + close, both chunk-pruned — verified plans

SQLAlchemy 2.0.49 renders the upsert correctly:
```python
from sqlalchemy.dialects.postgresql import insert as pg_insert
stmt = pg_insert(AvailabilityEvent).values(...).on_conflict_do_nothing(
    index_elements=["event_id", "time"]
)
# → INSERT INTO availability_events (...) VALUES (...) ON CONFLICT (event_id, time) DO NOTHING
```
[VERIFIED: sqlalchemy 2.0.49 compiled SQL — executed 2026-09-05]

Close by `event_id` **and** `time` (single chunk, index scan):
```
Custom Scan (HypertableModify)
  ->  Update on availability_events
        Update on _hyper_1_1_chunk availability_events_1
        ->  Result
              ->  Index Scan using _hyper_1_1_chunk_uq_ae_rid_event_time on _hyper_1_1_chunk
                    Index Cond: ((restaurant_id = 42) AND (event_id = 'f42d...') AND ("time" = '2026-05-01 23:00:00+00'))
```
Close by `event_id` alone (every chunk, bitmap scan — do not do this):
```
Custom Scan (HypertableModify)
  ->  Update on availability_events
        Update on _hyper_1_1_chunk availability_events_1
        Update on _hyper_1_2_chunk availability_events_2
        ->  Result
              ->  Append
                    ->  Bitmap Heap Scan on _hyper_1_1_chunk ...
                    ->  Bitmap Heap Scan on _hyper_1_2_chunk ...
```
[VERIFIED: `EXPLAIN (COSTS OFF)` on TimescaleDB 2.17.2 — executed 2026-09-05]

The `RedisStateStore` slot record therefore **must** carry `confirmed_ms` alongside `event_id` (D-40 already lists both) so the close path can reconstruct the `time` key without a DB lookup.

### `make_consumer()` for `shared/kafka.py`

```python
async def make_consumer(
    *topics: str,
    group_id: str,
    bootstrap_servers: str | None = None,
) -> AIOKafkaConsumer:
    """Create and start a manual-commit consumer (D-47, Pitfall 4/10).

    MUST be called from inside a running event loop: AIOKafkaConsumer.__init__
    calls get_running_loop() and raises RuntimeError otherwise.
    Topics are *varargs* — passing a list raises TypeError: unhashable type: 'list'.
    """
    servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=servers,
        group_id=group_id,
        enable_auto_commit=False,      # Pitfall 4 — manual commit only
        auto_offset_reset="earliest",  # D-47
        max_poll_records=1,            # Pitfall 10 — one message at a time
        isolation_level="read_uncommitted",
    )
    await consumer.start()
    return consumer
```
All kwargs verified present in `AIOKafkaConsumer.__init__` with the stated defaults (`enable_auto_commit=True`, `auto_offset_reset='latest'`, `max_poll_records=None`, `max_poll_interval_ms=300000`). [VERIFIED: `inspect.signature` on aiokafka 0.13.0]

### Chaos-test crash hook (D-51)

```python
# services/state_machine/consumer.py
import os, signal
_CRASH_AFTER = os.getenv("MISE_CRASH_AFTER")   # e.g. "state_write"

def _maybe_crash(stage: str) -> None:
    """Test-only SIGKILL hook. No-op unless MISE_CRASH_AFTER matches."""
    if _CRASH_AFTER == stage:
        os.kill(os.getpid(), signal.SIGKILL)    # uncatchable — no finally, no flush
```
Call sites: `_maybe_crash("nx_claim")`, `_maybe_crash("kafka_send")`, `_maybe_crash("state_write")`, `_maybe_crash("commit")`. `SIGKILL` (not `SIGTERM`) is required — a catchable signal would let `AIOKafkaConsumer.stop()` run and commit the offset, which is exactly the behaviour the test must prevent. The test drives it as a subprocess:

```python
proc = subprocess.Popen(
    ["uv", "run", "python", "-m", "services.state_machine"],
    env={**os.environ, "MISE_CRASH_AFTER": "state_write", ...},
)
proc.wait(timeout=60)
assert proc.returncode == -signal.SIGKILL   # -9 confirms the hook fired, not a clean exit
# restart WITHOUT the hook, then assert exactly one availability.events record per event_id
```
Asserting `returncode == -9` matters: without it, a test where the hook never fires passes vacuously.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `SETNX key` + `EXPIRE key ttl` | `SET key val NX EX ttl` | Redis 2.6.12 | The two-command form deadlocks on crash between commands; SC3 makes zero occurrences a phase gate |
| `ZADD` then read-compare-write to lower a score | `ZADD key XX LT score member` | Redis 6.2 | Atomic conditional score lowering; safe against a concurrent `claim` |
| `GET` + `DEL` | `GETDEL key` | Redis 6.2 | Single-command consume-once |
| `aioredis` | `redis.asyncio` (redis-py ≥ 4.2) | 2022 | `aioredis` archived; STACK.md §What NOT to Use bans it |
| `pytz` + `localize()` | stdlib `zoneinfo` (PEP 615) | Python 3.9 | No dependency, correct DST handling via the system tz database |
| Pydantic v1 `.json()` | Pydantic v2 `.model_dump_json()` | Pydantic 2.0 | Rust-backed, compact separators, RFC-3339 `Z` datetimes — the byte-stability STATE-06 relies on |
| `SELECT` then `INSERT` | `INSERT … ON CONFLICT` | PostgreSQL 9.5 | Race-free; SQLAlchemy 2.0's `postgresql.insert` renders it directly |
| Per-field HASH TTL unavailable | `HEXPIRE` (Redis **server** 7.4+) | 2024 | **Not usable here** — the pinned server is `redis:7.2-alpine`; redis-py 7.4.0 is the *client* version and does not imply server support |

**Deprecated / outdated in this context:**
- `bitnami/kafka:3.8` — withdrawn from Docker Hub; `ops/docker-compose.yml` still pins it (§Pitfall 9).
- `AIOKafkaProducer(max_in_flight_requests_per_connection=…)` — the kwarg does not exist in aiokafka; already fixed at `shared/kafka.py:28-29` with the comment `# NOTE: aiokafka has no max_in_flight_requests_per_connection kwarg; it` / `# enforces the idempotence-safe in-flight limit internally.` [VERIFIED: shared/kafka.py:28-29 — quoted verbatim]. Do not reintroduce it in `make_consumer`.
- `freezegun` for the t+8s rule — obsolete by design, since D-44/D-45 key everything off message timestamps.

---

## Runtime State Inventory

*(Not a rename/refactor/migration phase in the string-replacement sense, but Phase 2 does introduce new runtime state and modifies a live scheduler contract, so the categories are answered explicitly.)*

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | **New** Redis keys created by this phase: `avail:{rid}:{date}:{party}` HASHes (TTL 90000s), `avail:{rid}:meta` HASHes, `event:{rid}:{date}:{party}:{token}` strings (TTL 1200s), `sched:expedite:{source}:{rid}` strings (TTL 120s). **Existing** `sched:polls` ZSET is mutated (score lowered) by the expedite path. No existing key is renamed or deleted. | Declare all four patterns + TTLs in `shared/redis_keys.py` (D-42); no data migration |
| Live service config | `ops/docker-compose.yml` needs a `state-machine` note only if services are containerised — they are not at MVP (D-08: infra-only compose, services run on host). Kafka topic `availability.events` **already exists** from Phase 1 (`scripts/create_topics.py`, 1 partition, retention 604800000 ms) — no topic creation needed. Consumer group `state-machine` is created implicitly on first `start()`. | None — but `services/state_machine/main.py` should reuse the `_assert_topics_exist` startup guard from `services/poller/main.py:45-62` |
| OS-registered state | None. Services are launched by `make` / `uv run python -m services.<name>`; nothing is registered with launchd/systemd/pm2. | None — verified by reading `Makefile` (targets: `up down migrate seed poll test test-integration lint fmt smoke verify-seed verify-perf02 help topics`) |
| Secrets / env vars | New env vars, all non-secret: `CONFIRM_DELAY_MS` (default 8000), `MISE_CRASH_AFTER` (test-only, unset in prod). Reuses existing `KAFKA_BOOTSTRAP_SERVERS`, `REDIS_URL`, `DATABASE_URL_ASYNC`. | Add both to `.env.example` with comments; `MISE_CRASH_AFTER` must be documented as test-only |
| Build artifacts / installed packages | No new packages → no `uv.lock` change, no reinstall. Migration 0008 changes the DB schema, so any environment that has already run `alembic upgrade head` needs a re-run. | Add `make migrate` to the phase's verification steps |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker engine | testcontainers integration + chaos tests | ✓ | 29.4.0 | none — `conftest.py::_docker_available()` skips the tests |
| Docker Compose | `make up` local infra | ✓ | v5.1.2 | — |
| `uv` | `uv run` in subprocess-based tests and Makefile | ✓ | 0.11.7 | — |
| Python | project runtime | ✓ | 3.12.13 (in `.venv`; matches `requires-python = ">=3.12,<3.13"`) | — |
| `alembic` CLI | migration 0008 apply | ✓ | 1.18.4 | — |
| `confluentinc/cp-kafka:7.6.0` | `conftest.py::kafka_container` | ✓ | resolves + cached locally | `apache/kafka:3.8.1` (also cached) |
| `redis:7.2-alpine` | `conftest.py::redis_container` | ✓ | resolves + cached locally | — |
| `timescale/timescaledb:2.17.2-pg16` | `conftest.py::timescale_container` | ✓ | resolves + cached locally | — |
| `bitnami/kafka:3.8` | `ops/docker-compose.yml` (`make up` only) | ✗ | withdrawn from Docker Hub | `bitnamilegacy/kafka:3.8` (drop-in, same `KAFKA_CFG_*` vars) or `apache/kafka:3.8.1` (needs `KAFKA_*` var renames) |
| OpenTable live endpoint | **not required** — Phase 2 makes no HTTP calls | n/a | — | `OPENTABLE_SUCCESS_RESPONSE` fixture is sufficient |

[VERIFIED: `docker --version`, `docker compose version`, `uv --version`, `.venv/bin/python --version`, `alembic --version`, `docker manifest inspect` — all executed 2026-09-05]

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** `bitnami/kafka:3.8` — affects `make up` only, not the automated test tier. See §Pitfall 9.

**Blocking upstream note (not an environment gap, but a plan input):** the OpenTable DevTools spike from Phase 1 is still open (`.planning/STATE.md`: *"01-05 OpenTable DevTools spike deferred to human action: placeholder endpoint/headers/fixtures seeded … with [ASSUMED]/TODO(spike) markers"*). Every OpenTable payload shape the Phase 2 parser targets is therefore `[ASSUMED]`. Mitigation: keep `parsers/opentable.py` tolerant (`.get()` chains, never index-assume), drive its tests from `OPENTABLE_SUCCESS_RESPONSE` / `OPENTABLE_EMPTY_RESPONSE` / `OPENTABLE_RATE_LIMIT_RESPONSE`, and confine all shape knowledge to that one module so the post-spike fix is a single-file change. The `DiffEngine` must be testable entirely from `ParsedPoll` fixtures that never mention OpenTable — that isolation is what keeps the spike from blocking this phase.

---

## Validation Architecture

*(`workflow.nyquist_validation` is `true` in `.planning/config.json` — this section is required.)*

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `pythonpath = ["."]`, marker `integration` registered |
| Quick run command | `uv run pytest tests/unit -x -q` (`make test`) — currently 27 passed in 0.06s |
| Full suite command | `uv run pytest tests/unit tests/integration -v` (`make test-integration`) |
| Container fixtures | `tests/conftest.py` — module-scoped `kafka_container`, `redis_container`, `timescale_container`, each guarded by `_docker_available()` |

[VERIFIED: `pyproject.toml`, `tests/conftest.py`, and a live `pytest tests/unit -q` run → `27 passed, 1 warning in 0.06s`, executed 2026-09-05]

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| STATE-01 | Redis key/TTL constants exist and render correctly (`avail_state_key`, `avail_meta_key`, `event_idempotency_key`, `sched_expedite_key`, TTL 90000/1200/120) | unit | `pytest tests/unit/test_redis_keys_phase2.py -x` | ❌ Wave 0 |
| STATE-01 | HASH round-trip + 25h TTL refresh against real Redis | integration | `pytest tests/integration/test_redis_state_store.py -x` | ❌ Wave 0 |
| STATE-02 | absent→PENDING, PENDING→AVAILABLE(≥8s), PENDING→dropped, AVAILABLE→UNAVAILABLE, re-open→new event_id | unit | `pytest tests/unit/test_diff_engine_transitions.py -x` | ❌ Wave 0 |
| STATE-02 | Error/timeout `polls.completed` never moves a slot toward UNAVAILABLE; UNKNOWN is monotonic in poll time (Pitfall 2) | unit | `pytest tests/unit/test_diff_engine_tristate.py -x` | ❌ Wave 0 |
| STATE-02 | Coverage bounding — a party-2-only poll never closes a party-4 slot; a rolled date window never closes out-of-window slots (B-4) | unit | `pytest tests/unit/test_coverage_bounding.py -x` | ❌ Wave 0 |
| STATE-02 | OpenTable parser: success / empty / GraphQL-errors / missing-`data` / non-dict → correct `ParsedPoll` or `ParseError`; `resy` → `UnsupportedSourceError` | unit | `pytest tests/unit/test_parsers_opentable.py -x` | ❌ Wave 0 |
| STATE-03 | `EXPEDITE_POLL_LUA`: queued job → `ZADD XX LT`; in-flight job → expedite flag; `LT` never raises a score; `XX` never creates a member | integration | `pytest tests/integration/test_expedite_lua.py -x` | ❌ Wave 0 |
| STATE-03 | Poller release path consumes the flag with `GETDEL` and releases at `now+8000` instead of the jittered score | integration | `pytest tests/integration/test_poller_expedite_release.py -x` | ❌ Wave 0 |
| STATE-03 | No `asyncio.sleep(` in `services/state_machine/` (STATE-03 "not inline sleep") | unit | `pytest tests/unit/test_no_inline_sleep.py -x` | ❌ Wave 0 |
| STATE-04 | Zero two-command `SETNX`+`EXPIRE` in the source tree (SC3) | unit | `pytest tests/unit/test_no_setnx_expire.py -x` | ❌ Wave 0 |
| STATE-04 | `event_id` is a deterministic `uuid5` — same inputs → same UUID across processes; differing `first_poll_id` → different UUID | unit | `pytest tests/unit/test_event_id_determinism.py -x` | ❌ Wave 0 |
| STATE-04 | Redelivery of the same message emits nothing when the hash says AVAILABLE | unit | `pytest tests/unit/test_emission_idempotency.py -x` | ❌ Wave 0 |
| STATE-04 | **SC3 chaos:** subprocess with `MISE_CRASH_AFTER=state_write`, SIGKILL (assert `returncode == -9`), restart clean → exactly one record per `event_id` | integration | `pytest tests/integration/test_state_machine_chaos.py -x` | ❌ Wave 0 |
| STATE-05 | Migration 0008 applies; `event_id` NOT NULL; unique index `(event_id, time)` exists; a `(restaurant_id, event_id)`-only unique index is proven to fail (B-2 regression guard) | integration | `pytest tests/integration/test_migration_0008.py -x` | ❌ Wave 0 |
| STATE-05 | `hours_before_service` (America/New_York) and `day_of_week` (`isoweekday()%7`, 0=Sun) computed correctly, incl. a DST-adjacent date | unit | `pytest tests/unit/test_service_time_math.py -x` | ❌ Wave 0 |
| STATE-05 | **SC4:** confirmed event → hypertable row with all five columns; subsequent closure sets `last_seen_at` + `duration_seconds`; two slots confirmed by the same poll produce two distinct rows (B-3 regression guard) | integration | `pytest tests/integration/test_availability_events_persistence.py -x` | ❌ Wave 0 |
| STATE-06 | **SC2:** two replays of `tests/fixtures/raw_streams/happy.jsonl` are byte-identical to each other and to `happy.events.jsonl` | unit | `pytest tests/unit/test_replay_determinism.py -x` | ❌ Wave 0 |
| STATE-06 | **SC1:** `tests/fixtures/raw_streams/transient_errors.jsonl` replay yields **zero** events; `flapping.jsonl` yields exactly one | unit | `pytest tests/unit/test_replay_zero_false_events.py -x` | ❌ Wave 0 |
| STATE-06 | No wall-clock / randomness in `engine.py`, `models.py`, `parsers/` (`time.time(`, `datetime.now(`, `uuid4(`, `random.`) — Pitfall 8 | unit | `pytest tests/unit/test_engine_purity.py -x` | ❌ Wave 0 |
| STATE-06 | Offset-range replay against a live broker returns exactly `[from, to)` | integration | `pytest tests/integration/test_replay_offset_range.py -x` | ❌ Wave 0 |
| STATE-01..06 | **D-51 e2e:** 2 raw polls 9s apart → exactly 1 Kafka event + 1 DB row; 3rd poll without the slot → row gains `duration_seconds` | integration | `pytest tests/integration/test_state_machine_e2e.py -x` | ❌ Wave 0 |
| all | `AvailabilityEvent` frozen, `extra="forbid"`, `to_bytes()` round-trips | unit | `pytest tests/unit/test_events_schema.py -x` | ✅ extend existing |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit -x -q` (sub-second today; keep it under ~5s by keeping every diff-engine test on `MemoryStateStore`)
- **Per wave merge:** `uv run pytest tests/unit tests/integration -v` plus `make lint` (`ruff check .` + `mypy shared/ services/`) and the three CI ban-greps
- **Phase gate:** full suite green + all four ROADMAP success criteria demonstrated before `/gsd-verify-work`

### Wave 0 Gaps

- [ ] `tests/fixtures/raw_streams/happy.jsonl` + `happy.events.jsonl` (golden) — covers STATE-06 SC2
- [ ] `tests/fixtures/raw_streams/transient_errors.jsonl` + golden (empty) — covers STATE-06 SC1
- [ ] `tests/fixtures/raw_streams/flapping.jsonl` + golden — covers STATE-02/STATE-04
- [ ] `tests/unit/factories.py` — `make_raw(rid, dates, parties, slots, polled_at_epoch_ms)` builder so every fixture sets `polled_at_epoch_ms` explicitly (no wall-clock, no `asyncio.sleep` in tests)
- [ ] `tests/integration/conftest.py` — module-scoped helper that runs `alembic upgrade head` + `scripts/create_topics.py` against the containers (currently duplicated inline in `test_poller_smoke.py:65-80` and `test_hypertable_config.py:22-30`); extract before adding four more integration files
- [ ] All 20 test files listed above (none exist)
- [ ] Framework install: none needed — pytest 9.0.3, pytest-asyncio 1.3.0, testcontainers 4.14.2 all present

**Nyquist note:** the phase's riskiest properties (zero false events, byte-identical replay, deterministic `event_id`, purity) are all provable at the **unit** tier against `MemoryStateStore`, which means they can be sampled on every commit rather than every wave. Push everything that does not strictly need a container into `tests/unit/`; the four integration tests that genuinely need one (expedite Lua, persistence, chaos, e2e) are the only ones that should pay container startup cost.

---

## Security Domain

`security_enforcement` is not set to `false` in `.planning/config.json`, so this section applies.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No user-facing surface in this phase; all inputs come from internal Kafka topics |
| V3 Session Management | no | No sessions |
| V4 Access Control | no | No multi-tenant data path; `availability.events` is user-agnostic by design (ARCHITECTURE.md §Anti-Pattern 5) |
| V5 Input Validation | **yes** | Pydantic v2 with `extra="forbid"` on `AvailabilityRaw` / `PollCompleted` / `AvailabilityEvent`; parsers must treat `raw_response` as untrusted third-party JSON |
| V6 Cryptography | no | `uuid5` is an identifier, not a security control — do not describe it as one; no keys, no encryption in this phase |
| V7 Error Handling & Logging | **yes** | `shared.telemetry` already redacts `TWILIO_AUTH_TOKEN`, `HMAC_MGMT_SECRET_V1`, `VAPID_PRIVATE_KEY`, `RESY_ACCOUNTS_JSON` [VERIFIED: shared/telemetry.py:23-28]; never log a full `raw_response` at INFO |
| V8 Data Protection | partial | `booking_token` is a third-party reservation handle — treat as sensitive-ish: never log it at INFO, and keep the Redis TTLs bounded (already: 25h state, 20min idempotency) |
| V12 Files & Resources | **yes** | `scripts/replay_raw.py` takes `--input`/`--output` paths from argv — a developer tool, but resolve paths and refuse to write outside the repo by default |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed / hostile `raw_response` from a scraped third party crashes the consumer and stalls the partition | Denial of Service | `parsers/` must never index-assume; wrap in `ParseError` and route to UNKNOWN (D-39). A single unhandled `KeyError` halts the whole pipeline |
| Unbounded Redis growth from ever-new slot keys | Denial of Service | `EXPIRE 90000` refreshed on every write (D-40) + `maxmemory-policy noeviction` (D-03) so idempotency keys are never silently evicted mid-TTL (PITFALLS.md §Pitfall 18) |
| Log injection / secret leakage via `raw_response` echoed into structlog | Information Disclosure | Log `poll_id` + counts, never the payload; `_redact_secrets` runs on every log call but only matches known key names |
| Duplicate 3 AM notifications from at-least-once redelivery | Repudiation / trust | Layer-1 `SET NX EX` + deterministic `event_id`; Layer-2 in Phase 4 (PITFALLS.md §Pitfall 4) |
| Expedite flag used to force unbounded poll frequency | Denial of Service (self-inflicted, and a ToS risk) | `ZADD XX LT` cannot pull a poll earlier than `now+8000`, `XX` cannot resurrect an in-flight job, and the flag has `EX 120`. The 90s floor from POLL-03 still governs the steady state — verify in the expedite integration test that a burst of PENDING slots produces at most one expedited poll per restaurant |
| `MISE_CRASH_AFTER` left enabled in a deployed environment | Denial of Service | Default `None`; assert it is unset in `services/state_machine/main.py` when `ENV == "prod"`, and never list it in `.env.example` without a `# TEST ONLY` banner |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | OpenTable response shape is `data.availability[].availability[].timeSlots[] {time, seatingTypes[], token}` | §Pattern 2, parser design | Parser rewrite. Source is `services/poller/sources/opentable/fixtures.py`, whose own docstring says *"Shapes are [ASSUMED] per 01-RESEARCH.md §4"* and carries `TODO(spike)` markers. Confined to one module by design |
| A2 | OpenTable timeslots carry no per-party breakdown, so a slot applies to the poll's effective party size | §Pattern 2 | If the live payload *does* carry `partySize`/`covers`, the parser should prefer it; keep the coverage function tolerant of both |
| A3 | `availability_events` is empty in every environment, so migration 0008 needs no backfill | §Code Examples (migration) | If any environment has rows, `alter_column … nullable=False` fails. The `DELETE … WHERE event_id IS NULL` guard in the migration handles it; D-31 states the table is *"empty at P1 — writes are Phase 2"* |
| A4 | Restaurant service times fall in 17:00–23:00 local, so DST-transition hours never occur | §Pattern 6 | A 01:00–03:00 service slot on a transition day would compute `hours_before_service` off by up to 1h. Low impact (analytics only), documented in the helper docstring |
| A5 | One `availability.raw` message per poll, single partition, so per-restaurant ordering is guaranteed | §Pattern 4, D-47 | Verified for Phase 1's design (`scripts/create_topics.py` sets `num_partitions=1` for all five topics), but a future repartition would break the ordering assumption. Note it in `services/state_machine/README.md` |
| A6 | The `state-machine` consumer group has exactly one member at MVP | §Pattern 4 | Two members on a 1-partition topic means one idles; three would rebalance-thrash. Harmless at MVP, but the README should say "scale by partition count, not replica count" |
| A7 | `getone()` unfairness between the two subscribed topics is a prefetch artifact and not a strict ordering guarantee in either direction | §Pitfall 2 | The monotonic-UNKNOWN mitigation makes the behaviour order-independent, so this assumption does not need to hold |

---

## Open Questions

1. **Q1 — Does `restaurant_id` mean the OpenTable platform rid or `restaurants.id`?** *(highest-impact open item; must be settled before any DB write is coded)*
   - What we know: `scripts/seed_restaurants.py:109` seeds `make_job("opentable", int(platform_id))`, so the ZSET member, the job descriptor, `AvailabilityRaw.restaurant_id`, `request_params["rid"]`, the Kafka key `{source}:{restaurant_id}`, and the already-written `poll_log.restaurant_id` rows all carry the **platform rid**. Meanwhile `availability_events.restaurant_id` and `watchlist_entries.restaurant_id` are `BigInteger` columns that read semantically like `restaurants.id` (which is `autoincrement=True`).
   - What's unclear: whether Phase 6's heatmap and Phase 4's watchlist fanout were envisaged joining on `restaurants.id` or on `(source, platform_id)`.
   - **Recommendation:** keep the platform rid end-to-end in Phase 2 — it matches the raw stream, matches the `poll_log` precedent, and keeps `DiffEngine` free of any DB lookup (which is a hard requirement for D-49/D-50 determinism). Both `availability_events` and `poll_log` already carry a `source` column, so `(source, restaurant_id)` is a complete join key against `restaurants(source, platform_id::bigint)`. Encode the decision as: (a) a `COMMENT ON COLUMN availability_events.restaurant_id` in migration 0008, (b) a docstring line on `shared.events.AvailabilityEvent`, (c) an explicit note in `services/state_machine/README.md` telling Phase 4/5/6 how to join. If instead the DB id is wanted on the wire, that is a **Phase 1 change** (resolve `platform_id → id` at seed time or at poll time) and should be raised with the user, not decided here.

2. **Q2 — Should `polls.completed` and `availability.raw` share one consumer?**
   - What we know: D-47 locks a single consumer and CONTEXT.md §Claude's Discretion explicitly says *"how `polls.completed` and `availability.raw` are interleaved (single consumer with topic check is fine)"*. Verified: `getone()` drained all `availability.raw` before any `polls.completed`.
   - What's unclear: nothing blocking.
   - **Recommendation:** keep the single consumer (D-47) and make UNKNOWN monotonic in `polled_at_epoch_ms` (§Pitfall 2). This is strictly better than two consumers, because it also makes replay order-independent.

3. **Q3 — What is `NAMESPACE_MISE`?**
   - What we know: D-45 names it but does not define it. `uuid5` requires a fixed namespace UUID.
   - **Recommendation:** hard-code a literal in `shared/events.py`, e.g. `NAMESPACE_MISE = UUID("629d45e6-9621-5f62-a1ea-dd826ede29f8")` (this session's `uuid5(NAMESPACE_URL, "https://mise.place/events")`), with a docstring stating it must never change — every historical `event_id` depends on it. Do **not** compute it at import.

4. **Q4 — Does `--to-offset` include or exclude the endpoint?**
   - What we know: `end_offsets` returns *last offset + 1*, so an exclusive upper bound composes naturally.
   - **Recommendation:** treat `--to-offset` as **exclusive** and default it to `end_offsets` when omitted; state it in `--help` and in `services/state_machine/README.md`. Add a test asserting `[2,5) → [2,3,4]` (already verified working).

5. **Q5 — Should `ops/docker-compose.yml` be repointed off the withdrawn `bitnami/kafka:3.8` in this phase?**
   - What we know: it does not block Phase 2's automated tests (testcontainers uses cp-kafka), but it does block `make up`.
   - **Recommendation:** treat as a one-task fix inside Phase 2 (swap to `bitnamilegacy/kafka:3.8`, a drop-in that keeps every `KAFKA_CFG_*` var) **only if** the plan contains a manual step that needs `make up`. Otherwise capture it as a deferred item for Phase 7 (DEPLOY). It is infra outside the phase boundary — flag rather than silently change.

---

## Sources

### Primary (HIGH confidence — executed against the pinned artifacts this session, 2026-09-05)
- `.venv` package introspection — `inspect.signature` / `inspect.getdoc` on `AIOKafkaConsumer.__init__`, `.commit`, `.getone`, `.getmany`, `.seek`, `.assign`, `.subscribe`, `.end_offsets`, `.beginning_offsets`, `.position`, `.offsets_for_times`, `AIOKafkaProducer.send`/`.send_and_wait`; `redis.asyncio.Redis.zadd`/`.getdel`/`.hset`/`.hget`/`.hgetall`/`.hdel`/`.expire`/`.set`
- Live `confluentinc/cp-kafka:7.6.0` via testcontainers — two-topic subscribe, manual-commit offset semantics, partial-commit restart behaviour, bounded `assign`+`seek`+`end_offsets` replay, `offsets_for_times`
- Live `redis:7.2-alpine` — `EXPEDITE_POLL_LUA`, `ZADD XX LT`, `GETDEL`, `HSET`+`EXPIRE`+`TTL`, `SET NX EX`, `HEXPIRE` rejection
- Live `timescale/timescaledb:2.17.2-pg16` — unique-index partitioning-column rule, `ON CONFLICT` arbiter rule, PK collision on `(time, restaurant_id)`, `EXPLAIN` chunk-pruning for both close forms
- `mypy 1.x --strict` against `redis==7.4.0` — exact error set for HASH commands and the `cast(Awaitable[T], …)` resolution
- `pydantic==2.13.3` — `model_dump_json()` field order, order-insensitivity, datetime/float/null rendering; `uuid.uuid5` repeatability
- `sqlalchemy==2.0.49` — compiled `ON CONFLICT DO NOTHING` / `DO UPDATE` SQL
- Python 3.12.13 `zoneinfo` / `datetime` — America/New_York arithmetic, `isoweekday()%7`, DST edge behaviour
- `docker manifest inspect` — image availability for `bitnami/kafka:3.8`, `bitnamilegacy/kafka:3.8`, `apache/kafka:3.8.0`, `confluentinc/cp-kafka:7.6.0`
- Repository source read this session: `shared/{events,redis_keys,kafka,db,telemetry}.py`, `shared/scheduler/lua.py`, `services/poller/{main,config,scheduler,publisher}.py`, `services/poller/sources/{base,opentable/adapter,opentable/graphql,opentable/fixtures}.py`, `scripts/{create_topics,seed_restaurants,verify_seed}.py`, `migrations/versions/0006_create_availability_events_hypertable.py`, `tests/conftest.py`, `tests/integration/{test_poller_smoke,test_hypertable_config}.py`, `tests/unit/test_events_schema.py`, `pyproject.toml`, `.ruff.toml`, `Makefile`, `ops/docker-compose.yml`, `.github/workflows/lint.yml`

### Secondary (MEDIUM confidence — project research, authored 2026-04-20)
- `.planning/research/ARCHITECTURE.md` §Pattern 2 (raw/refined split with replay), §Pattern 3 (confirmation poll with state-machine ownership), §Data Flow (happy path + failure path 2), §Anti-Patterns 1/2/3/5
- `.planning/research/PITFALLS.md` §Pitfall 3 (flapping / tri-state), §Pitfall 4 (at-least-once duplicates), §Pitfall 7 (non-atomic SETNX), §Pitfall 10 (`max.poll.interval.ms`), §Pitfall 12 (hypertable chunk interval), §Pitfall 18 (Redis eviction)
- `.planning/phases/01-.../01-CONTEXT.md` D-01..D-35 (locked stack and infrastructure decisions)
- `.planning/REQUIREMENTS.md`, `.planning/ROADMAP.md` §Phase 2, `.planning/STATE.md`

### Tertiary (LOW confidence — flagged in §Assumptions Log)
- OpenTable GraphQL payload shape — `[ASSUMED]` placeholders from Phase 1's deferred DevTools spike; not verified against a live endpoint in this session

---

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — zero new packages; every version confirmed via `importlib.metadata` against the project `.venv`
- Library API semantics (Kafka / Redis / Pydantic / SQLAlchemy / TimescaleDB): **HIGH** — every claim executed, with transcripts quoted inline
- Blocking corrections B-1..B-5: **HIGH** — each reproduced as a concrete runtime error or a verbatim source quote
- Architecture patterns: **HIGH** — derived from locked decisions plus project research plus the verified primitives
- Pitfalls: **HIGH** for 1–9 (all verified); **MEDIUM** for 10 (depends on the un-spiked OpenTable payload)
- OpenTable payload shape: **LOW** — `[ASSUMED]`, isolated to `parsers/opentable.py` by design

**Research date:** 2026-09-05
**Valid until:** 2026-10-05 (30 days — every dependency is exact-pinned; the only external drift risk is Docker Hub image availability, already flagged in §Pitfall 9)
