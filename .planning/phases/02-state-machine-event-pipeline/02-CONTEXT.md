# Phase 2: State Machine & Event Pipeline - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning
**Mode:** Autonomous smart discuss — recommended answers accepted for every grey area (no human available; defaults chosen for consistency with PROJECT.md, REQUIREMENTS.md and Phase 1 decisions D-01..D-35)

<domain>
## Phase Boundary

Build `services/state_machine/`: a Kafka consumer that reads `availability.raw` (and `polls.completed` for error signals), normalises each source's raw payload into slot records, diffs them against Redis state with a tri-state AVAILABLE / UNAVAILABLE / UNKNOWN model, schedules a t+8s confirmation re-poll through the Redis ZSET scheduler (never `asyncio.sleep`), emits confirmed `availability.events` with atomic `SET NX EX` idempotency, persists confirmed events to the TimescaleDB `availability_events` hypertable, and ships `scripts/replay_raw.py` that regenerates a byte-identical `availability.events` stream from any raw offset range. Requirements: STATE-01..06.

Out of scope here: Resy raw payload parsing (Phase 3 registers a parser; Phase 2 ships the parser registry + OpenTable parser), notification fan-out (Phase 4), SSE (Phase 5).

</domain>

<decisions>
## Implementation Decisions

### Slot identity & payload normalisation
- **D-36:** A *slot* is identified by `(source, restaurant_id, date, party_size, time_slot, seat_type)`; `booking_token` is carried as data, not identity (tokens can rotate between polls for the same physical slot). Slot key string inside Redis hashes: `{time_slot}|{seat_type or '-'}`.
- **D-37:** Per-source parsers live in `services/state_machine/parsers/{opentable,resy}.py` behind a `parse_raw(raw: AvailabilityRaw) -> ParsedPoll` registry keyed by `raw.source`. `ParsedPoll` = `{restaurant_id, source, polled_at_epoch_ms, poll_id, coverage: set[(date, party_size)], slots: list[Slot]}`. The diff engine never branches on source (Phase 3 SC5). Phase 2 registers `opentable`; `resy` raises `UnsupportedSourceError` → treated as UNKNOWN until Phase 3 registers it.
- **D-38:** `coverage` (the `(date, party_size)` matrix the poll actually asked for, taken from `raw.request_params`) bounds the diff: a slot is only marked UNAVAILABLE if its `(date, party)` was covered by this poll and it is absent. Slots for uncovered dates/parties are untouched (prevents false closures when the date window rolls).
- **D-39:** Parser failures (missing `data`, GraphQL `errors` array, empty dict, non-JSON) → `ParseError` → the restaurant's tracked slots are marked UNKNOWN (`unknown_since_ms` set on the hash meta), nothing is removed, no events. A well-formed response with zero slots is a *valid* observation and closes covered slots.

### Redis state model (STATE-01) and tri-state (STATE-02)
- **D-40:** `avail:{restaurant_id}:{date}:{party_size}` is a Redis HASH (field = slot key, value = compact JSON `{state, token, first_seen_ms, first_poll_id, last_seen_ms, confirmed_ms, event_id}`) with `EXPIRE 90000` (25h) refreshed on every write. A HASH is the set of known slot tokens STATE-01 asks for plus the timestamps STATE-05 needs; there is no separate meta key per slot. Restaurant-level `avail:{restaurant_id}:meta` HASH carries `unknown_since_ms` / `last_success_ms`.
- **D-41:** Per-slot states: `PENDING` (seen once, awaiting confirmation), `AVAILABLE` (confirmed & emitted), `UNAVAILABLE` (gone; row closed in DB), `UNKNOWN` (last poll for the restaurant errored/unparseable — a flag on the restaurant meta, slots keep their last known state). Transitions: absent→PENDING (seen), PENDING→AVAILABLE (seen again ≥ 8s later → EMIT), PENDING→dropped (absent on next successful covered poll, no event — this is the false-positive guard), AVAILABLE→UNAVAILABLE (absent on a successful covered poll → close DB row), UNAVAILABLE/absent→PENDING (re-opened → new cycle, new event_id). Errors never move a slot toward UNAVAILABLE.
- **D-42:** All Redis access goes through `shared/redis_keys.py` constants/helpers (`avail_state_key`, `avail_meta_key`, `event_idempotency_key`, `sched_expedite_key`) — no inline key strings in services.

### Confirmation at t+8s via the ZSET scheduler (STATE-03)
- **D-43:** Confirmation is **stream-based**: the state machine never calls OpenTable/Resy itself. On PENDING it runs Lua `EXPEDITE_POLL_LUA`: if `{source}:{rid}` is in `sched:polls`, `ZADD LT` its score to `now_ms + 8000`; otherwise (job in flight) `SET sched:expedite:{source}:{rid} 1 EX 120`. `services/poller/scheduler.py` release path does `GETDEL sched:expedite:{job}` and, if present, releases with `now_ms + 8000` instead of the 90s±15% score. The expedited poll's `availability.raw` message confirms (or drops) every PENDING slot for that restaurant. Replay therefore reproduces confirmations from the raw stream alone (needed for D-49).
- **D-44:** Confirmation requires `polled_at_epoch_ms(confirming) - first_seen_ms >= 8000` (an accidental immediate duplicate poll does not confirm) — in replay the same rule applies, keyed off message timestamps.

### Event contract & emission idempotency (STATE-04)
- **D-45:** `shared/events.py` gains `AvailabilityEvent` (frozen, `extra="forbid"`): `event_id: UUID` (uuid5 over `NAMESPACE_MISE` + `"{source}:{rid}:{date}:{party}:{slot_key}:{first_poll_id}"` — deterministic), `event_type: Literal["slot_opened"]`, `source`, `restaurant_id`, `date`, `time_slot`, `party_size`, `seat_type`, `booking_token`, `first_seen_at_epoch_ms`, `confirmed_at_epoch_ms`, `produced_at_epoch_ms` (= confirming poll's `polled_at_epoch_ms`, NOT wall clock — deterministic; PERF-01 latency is measured from this detection timestamp), `confirming_poll_id`. Kafka key `{source}:{restaurant_id}` (D-29). Only `slot_opened` goes to Kafka; closures are DB-only updates.
- **D-46 (amended after code review CR-01/CR-02/WR-03):** Emission order per slot: diff → `SET event:{rid}:{date}:{party}:{slot_key}:{token} 1 NX EX 1200` (the claim key includes the slot key so two seat types sharing one booking token cannot collide; each component is percent-escaped so an embedded `:` cannot alias another key — review iteration 2 WR-04) → `send_and_wait` → idempotent DB insert → per-slot state flush → commit. Original wording: diff → `SET event:{rid}:{date}:{party}:{token} 1 NX EX 1200` (single command via `shared.redis_keys.set_nx_ex`; token = `booking_token or slot_key`) → `producer.send_and_wait` (acks=all) → write hash state `AVAILABLE` with `event_id` → after the whole message: `consumer.commit()` (manual, `enable_auto_commit=False`). On redelivery: NX fails AND hash says AVAILABLE → skip (chaos SC3 path, zero duplicates). NX fails AND hash still PENDING (crash between claim and hash write) → re-send the same deterministic `event_id` (downstream Layer-2 key in Phase 4 dedupes by event_id). Source tree must contain zero `SETNX`+`EXPIRE` pairs (unit test greps for it).
- **D-47:** Consumer: `AIOKafkaConsumer(["availability.raw", "polls.completed"], group_id="state-machine", enable_auto_commit=False, auto_offset_reset="earliest")`; one message processed at a time (single partition, per-restaurant ordering guaranteed by key). `polls.completed` with status `error|timeout` → mark restaurant UNKNOWN only.

### Persistence (STATE-05)
- **D-48:** On EMIT: `INSERT` into `availability_events` (`time`=confirmed_at, `restaurant_id`, `source`, `date`, `time_slot`, `party_size`, `seat_type`, `booking_token`, `first_seen_at`, `last_seen_at`=confirmed_at, `hours_before_service` = (service datetime in `America/New_York` − first_seen_at)/3600, `day_of_week` = service date `isoweekday()%7` (0=Sun … 6=Sat, matching the heatmap y-axis in Phase 6)). On AVAILABLE→UNAVAILABLE: `UPDATE ... SET last_seen_at, duration_seconds = last_seen_at − first_seen_at WHERE time=… AND restaurant_id=…` (hypertable UPDATE by primary key). Migration 0008 adds `event_id UUID` + unique index `(restaurant_id, event_id)` to `availability_events` for upsert safety. Writes are through `shared.db.get_async_session()`; a DB failure is logged and does not block the Kafka emit (metrics beat durability of the analytics row).

### Replay & determinism (STATE-06)
- **D-49:** The diff engine is a pure core: `services/state_machine/engine.py :: DiffEngine(store: StateStore)` with `async def process(parsed: ParsedPoll) -> list[AvailabilityEvent]` and `StateStore` protocol implemented by `RedisStateStore` (production) and `MemoryStateStore` (replay/tests). Side-effects (expedite, emit, persist, commit) live in `services/state_machine/consumer.py` around the engine.
- **D-50:** `scripts/replay_raw.py --from-offset A --to-offset B [--bootstrap …] | --input raw.jsonl` `[--output events.jsonl]` feeds messages through `DiffEngine(MemoryStateStore())`, dedupes by `event_id`, and writes one canonical `model_dump_json()` line per event. Test fixture streams live in `tests/fixtures/raw_streams/*.jsonl` (happy path, transient-error stream, flapping slot). CI test: two replays of the same fixture are byte-identical to each other and to the committed golden `*.events.jsonl`; the transient-error fixture yields zero events.

### Chaos & test strategy
- **D-51:** Integration test `tests/integration/test_state_machine_e2e.py` (testcontainers Kafka+Redis+Timescale): publish 2 raw polls 9s apart → exactly one `availability.events` message + one DB row; publish a third poll without the slot → row gets `duration_seconds`. Chaos test: run the consumer as a subprocess with `MISE_CRASH_AFTER=state_write` env hook (SIGKILL self after hash write, before commit), restart without the hook → zero duplicate events (assert by `event_id` count). Unit tests for parser, tri-state transitions, deterministic event_id, coverage bounding, and the SETNX grep.

### Amendments after research (02-RESEARCH.md §Blocking Corrections + §Open Questions — accepted 2026-09-05)
- **D-47a:** `AIOKafkaConsumer("availability.raw", "polls.completed", …)` — topics are varargs; construct inside `async def run()` (needs a running loop). `max_poll_records=1`.
- **D-48a:** Migration 0008 adds `event_id UUID NOT NULL` to `availability_events` and `UNIQUE INDEX (event_id, "time")` (a hypertable unique index must include the partitioning column). ORM primary key becomes `(time, event_id)`; `restaurant_id` is no longer part of the PK. Close-UPDATE predicate is `WHERE event_id = :event_id AND "time" = :confirmed_at` (single-chunk index scan). Migration 0008 also adds `COMMENT ON COLUMN availability_events.day_of_week IS '0=Sun .. 6=Sat (isoweekday() % 7)'` — D-48 convention wins over the stale inline comment in 0006.
- **D-38a:** Coverage is derived from the *effective* party size: `{(d, request_params["party_sizes"][0]) for d in request_params["dates"]}` because `build_request` sends only `partySize=party_sizes[0]` and the adapter does not loop. Mark with `# TODO(P3/POLL-02): widen to the full list when the adapter loops party sizes`. Unit test: a party-2-only poll never closes or drops a party-4 slot.
- **D-52 (Q1):** `restaurant_id` on the wire, in Redis keys, in `AvailabilityEvent`, and in `availability_events.restaurant_id` is the **platform id** (OpenTable rid / Resy venue id), exactly as `poll_log.restaurant_id` already is. The complete join key against `restaurants` is `(source, platform_id)`. Encode via `COMMENT ON COLUMN availability_events.restaurant_id`, a docstring on `AvailabilityEvent`, and a "How to join" note in `services/state_machine/README.md` for Phases 4/5/6. The DiffEngine performs no DB lookups (D-49 determinism).
- **D-53 (Q2):** Single consumer stays; UNKNOWN marking is monotonic in `polled_at_epoch_ms` (an older error never overrides a newer success) so replay is order-independent.
- **D-54 (Q3):** `NAMESPACE_MISE = UUID("629d45e6-9621-5f62-a1ea-dd826ede29f8")` hard-coded literal in `shared/events.py` with a "never change" docstring.
- **D-55 (Q4):** `scripts/replay_raw.py --to-offset` is **exclusive**; defaults to `end_offsets` when omitted; documented in `--help` and README; test asserts `[2,5) -> [2,3,4]`.
- **D-56 (Q5):** `ops/docker-compose.yml` is repointed from the withdrawn `bitnami/kafka:3.8` to the drop-in `bitnamilegacy/kafka:3.8` (all `KAFKA_CFG_*` vars unchanged) as a one-task fix in this phase so `make up` works again; Phase 7 may move to an official image with its production profile.

### Claude's Discretion
- Exact JSON field abbreviations inside the Redis hash values, structlog event names, Prometheus counter names (Phase 7 wires exporters; Phase 2 may define `Counter` objects in `shared/metrics.py` if convenient).
- `MISE_CRASH_AFTER` hook implementation detail; consumer poll timeout; how `polls.completed` and `availability.raw` are interleaved (single consumer with topic check is fine).
- Whether `hours_before_service` uses `zoneinfo` directly or a `shared/time.py` helper.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `shared/events.py` — `AvailabilityRaw` (poll_id, source, restaurant_id, polled_at_epoch_ms, raw_response, request_params) and `PollCompleted`; add `AvailabilityEvent` here (D-06 single source of truth).
- `shared/redis_keys.py` — `set_nx_ex()` (atomic SET NX EX), `job_descriptor()`, `SCHED_POLLS`, Lua scripts; `shared/scheduler/lua.py :: LuaScheduler` (EVALSHA + NOSCRIPT fallback) — extend with an `expedite()` method.
- `shared/kafka.py :: make_producer()` — idempotent `acks=all` producer factory; add `make_consumer()` alongside it with manual commit defaults.
- `shared/db.py` — `AvailabilityEvent` ORM (hypertable, PK `(time, restaurant_id)`), `get_async_session()`.
- `services/poller/sources/opentable/fixtures.py` — `OPENTABLE_SUCCESS_RESPONSE` shape: `data.availability[].availability[].timeSlots[] {time, seatingTypes[], token}`; `request_params = {rid, dates[], party_sizes[]}` from `services/poller/scheduler.py`. Note: the fixture has no per-party breakdown — the parser should treat each `timeSlots` entry as applying to every requested party size unless the payload carries `partySize`/`covers` (spike-dependent, keep tolerant).
- `services/poller/scheduler.py` — release path to modify for the expedite flag (D-43); `services/poller/main.py` — startup pattern (topic guard, producer/redis lifecycle) to mirror in `services/state_machine/main.py`.
- `tests/conftest.py` — `kafka_container`, `redis_container`, `timescale_container` module-scoped fixtures; `tests/integration/test_poller_smoke.py` — pattern for running migrations/topics in tests.

### Established Patterns
- Async-only: `redis.asyncio`, `aiokafka`, SQLAlchemy async; no `time.sleep`, no `requests`, no sync redis (CI greps enforce).
- Every Redis key/TTL constant in `shared/redis_keys.py`; every Kafka schema in `shared/events.py`; structlog via `shared.telemetry.get_logger`.
- Service entry: `python -m services.<name>` with `__main__.py` → `main.run()`; config via env in `services/<name>/config.py`.
- Migrations: Alembic files `migrations/versions/000N_*.py`, raw `op.execute` for Timescale specifics.

### Integration Points
- Consumes `availability.raw` + `polls.completed` (Phase 1 producer); produces `availability.events` (consumed by Phase 4 notifier and Phase 5 SSE).
- Writes `availability_events` hypertable (read by Phase 6 pattern model & heatmap CAGG).
- Touches `sched:polls` via expedite Lua; poller honours `sched:expedite:*` on release.
- Makefile: add `make state-machine` and `make replay ARGS=…`; README Status section update is Phase 7 but SUMMARY should list what is implemented.

</code_context>

<specifics>
## Specific Ideas

- Byte-identical replay is a portfolio artifact: keep `AvailabilityEvent` free of wall-clock fields (D-45) and document that in the model docstring.
- `services/state_machine/README.md` should include a state-transition table and the ordering diagram from D-46.

</specifics>

<deferred>
## Deferred Ideas

- Kafka transactional exactly-once (consume→produce) — revisit post-MVP; deterministic event_id + Layer-2 covers MVP.
- `slot_closed` Kafka events for the SSE feed — Phase 5 can read closures from DB if needed.
- Resy parser — Phase 3.

</deferred>
