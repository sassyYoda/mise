---
phase: 02-state-machine-event-pipeline
verified: 2026-09-05T00:00:00Z
status: passed
score: 12/12 must-haves verified
behavior_unverified: 0
overrides_applied: 0
---

# Phase 2: State Machine & Event Pipeline Verification Report

**Phase Goal:** The State Machine consumes `availability.raw`, diffs against Redis state with tri-state `AVAILABLE / UNAVAILABLE / UNKNOWN`, schedules confirmation re-polls at t+8s via Redis ZSET (not inline sleep), and emits `availability.events` to Kafka with atomic `SET NX EX` idempotency — producing zero false events under simulated transient-error streams.
**Verified:** 2026-09-05
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | State machine consumes `availability.raw` and computes tri-state diff (PENDING/AVAILABLE/UNAVAILABLE/UNKNOWN) against Redis state | ✓ VERIFIED | `services/state_machine/engine.py::DiffEngine.process` implements the full transition table; `services/state_machine/consumer.py::_handle_raw` calls it from a live Kafka consumer; `tests/integration/test_state_machine_e2e.py::test_raw_polls_become_one_event_one_row_and_a_closure` passes against a live broker+Redis+Postgres (independently re-run, PASSED) |
| 2 | Confirmation re-poll scheduled at t+8s via Redis ZSET, never inline sleep | ✓ VERIFIED | `EXPEDITE_POLL_LUA` in `shared/redis_keys.py` does `ZADD XX LT` to `now_ms+8000`; `services/poller/scheduler.py` release path calls `consume_expedite` and releases at `now_ms + CONFIRM_DELAY_MS`; `tests/unit/test_no_inline_sleep.py` greps `services/state_machine/` for `asyncio.sleep(`/`time.sleep(` — independently re-run, zero matches (grep exit 1) |
| 3 | Only confirmed slots (elapsed ≥ 8000ms) emit `availability.events`; a PENDING slot dropped on next covered poll never emits (false-positive guard) | ✓ VERIFIED | `engine.py::_confirm_or_wait` gates on `elapsed < confirm_delay_ms`; the false-positive drop path removes PENDING records with no decision; `tests/unit/test_engine_transitions.py`, `test_engine_tristate_unknown.py` cover both paths (156 unit tests independently re-run, all pass) |
| 4 | Emission-layer idempotency via atomic `SET NX EX` on `event:{rid}:{date}:{party}:{token}`, 20-min TTL; zero two-command SETNX+EXPIRE in source tree | ✓ VERIFIED | `shared/redis_keys.py::set_nx_ex` issues a single `r.set(key, value, nx=True, ex=ttl)`; `EVENT_IDEMPOTENCY_TTL_SECONDS=1200`; `tests/unit/test_no_setnx_expire_pairs.py` greps `services/`, `shared/`, `scripts/` for `.setnx(` — independently re-run via `grep -rn "SETNX\|setnx"`, zero occurrences found |
| 5 | Simulated transient-error stream (timeout, 5xx, empty payload, GraphQL errors) produces 0 false `availability.events` (ROADMAP SC1) | ✓ VERIFIED | `tests/fixtures/raw_streams/transient_errors.jsonl` independently inspected — carries a timeout, an `error` status, a GraphQL `errors` array, an empty `{}` payload, and a legitimate sighting whose confirmation never arrives; independently ran `uv run python scripts/replay_raw.py --input transient_errors.jsonl` → 0-byte output, matching the committed 0-byte golden |
| 6 | Replay of a raw offset range regenerates byte-identical `availability.events` without re-polling (ROADMAP SC2, STATE-06) | ✓ VERIFIED | Independently ran `replay_raw.py --input happy.jsonl` twice — outputs byte-identical to each other and to the committed `happy.events.jsonl` golden (`diff` clean both ways); `replay()` instantiates `DiffEngine(MemoryStateStore())` — no Redis/Postgres/Kafka consumer group reached (confirmed via `import` grep and `sys.modules` check in `test_replay_determinism.py`) |
| 7 | `kill -9` chaos between diff and emit produces zero duplicate events on restart | ✓ VERIFIED | `tests/integration/test_state_machine_chaos.py::test_sigkill_before_commit_produces_no_duplicate_events` independently re-run in isolation — PASSED (50.71s, actual SIGKILL fired and confirmed via subprocess return code before assertions) |
| 8 | Layer-1 claim (`SET NX EX`) plus the AVAILABLE hash state makes redelivery a no-op | ✓ VERIFIED | `consumer.py::_apply_emit` + `_crashed_mid_emit`: claim fails + record AVAILABLE → skip; claim fails + record PENDING → re-send same deterministic `event_id`; `tests/unit/test_emission_idempotency.py` covers all three claim outcomes (independently re-run, pass) |
| 9 | `availability.events` persist to TimescaleDB `availability_events` hypertable with populated `first_seen_at`, `last_seen_at`, `duration_seconds`, `hours_before_service`, `day_of_week` (ROADMAP SC4) | ✓ VERIFIED | `services/state_machine/persistence.py::insert_event`/`close_event` populate all five columns; migration `0008_add_event_id_to_availability_events.py` adds `event_id` + `UNIQUE INDEX (event_id, "time")`; `tests/integration/test_availability_events_persistence.py::test_inserted_row_carries_the_derived_analytics_columns` and `test_close_stamps_duration_from_the_rows_own_first_seen_at` independently re-run — PASSED, asserting real non-null values (`hours_before_service==5.0`, `day_of_week==5`, `duration_seconds==3600`) |
| 10 | Event identity (`event_id`) is a deterministic `uuid5` stable across processes | ✓ VERIFIED | `shared/events.py::make_event_id` uses hard-coded `NAMESPACE_MISE`; `tests/unit/test_event_id_determinism.py` spawns a fresh interpreter subprocess and compares ids (independently re-run, pass) |
| 11 | Coverage bounding: closure/drop only applies to `(date, party_size)` buckets the poll actually covered (effective party size) | ✓ VERIFIED | `engine.py::process` only iterates buckets in `parsed.coverage` for closure; `services/state_machine/parsers/opentable.py::effective_coverage` derives from `party_sizes[0]`; `tests/unit/test_coverage_bounding.py` passes (independently re-run) |
| 12 | Resy (`source='resy'`) is UNKNOWN until Phase 3 registers a parser — no crash, no false state change | ✓ VERIFIED | `services/state_machine/parsers/__init__.py::parse_raw` raises `UnsupportedSourceError` for unregistered sources; `consumer.py::_handle_raw` catches `ParseError`-family and marks UNKNOWN only |

**Score:** 12/12 truths verified (0 present, behavior-unverified)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `shared/events.py` | `AvailabilityEvent`, `NAMESPACE_MISE`, `make_event_id` | ✓ VERIFIED | Present, frozen, `extra="forbid"`, declaration order = wire order |
| `services/state_machine/models.py` | `SlotState`, `Slot`, `ParsedPoll`, decisions | ✓ VERIFIED | Present and imported by engine.py |
| `services/state_machine/engine.py` | `StateStore` Protocol + `DiffEngine` | ✓ VERIFIED | Pure, no I/O, no clock reads (mechanically enforced by `test_engine_purity.py`) |
| `services/state_machine/store.py` | `MemoryStateStore`, `RedisStateStore`, `BufferedStateStore` | ✓ VERIFIED | All three present, protocol-conformant |
| `services/state_machine/parsers/opentable.py` | `parse_opentable`, `effective_coverage` | ✓ VERIFIED | Present with one documented `TODO(P3/POLL-02)` referencing formal follow-up work |
| `services/state_machine/consumer.py` | `StateMachineConsumer` | ✓ VERIFIED | Implements D-46 emission order exactly: claim → send_and_wait → flush(state write) → insert_event → commit |
| `services/state_machine/persistence.py` | `insert_event`, `close_event`, `hours_before_service`, `day_of_week` | ✓ VERIFIED | All present, best-effort (DB failure logged, never blocks emit) |
| `services/state_machine/main.py` | service lifecycle | ✓ VERIFIED | Topic guard, prod refusal of `MISE_CRASH_AFTER` (independently tested), ordered teardown |
| `migrations/versions/0008_add_event_id_to_availability_events.py` | `event_id` + `(event_id, time)` unique index | ✓ VERIFIED | Present; `alembic upgrade head` idempotency and downgrade round-trip covered by integration tests |
| `scripts/replay_raw.py` | offset-range + jsonl replay | ✓ VERIFIED | Present, `--help` output confirms `--to-offset` exclusivity contract; independently exercised on all three fixtures |
| `tests/fixtures/raw_streams/{happy,transient_errors,flapping}.jsonl` + goldens | fixture corpus | ✓ VERIFIED | All 6 files present; independently regenerated and diffed against goldens, all match |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| `consumer.py` | `shared/redis_keys.py` | `set_nx_ex` Layer-1 claim | ✓ WIRED | `event_idempotency_key` + `set_nx_ex` called directly in `_apply_emit` |
| `consumer.py` | `shared/scheduler/lua.py` | `scheduler.expedite(job, now_ms)` | ✓ WIRED | Called in `_apply_expedite` |
| `consumer.py` | `engine.py` | `DiffEngine.process` | ✓ WIRED | Shell owns all I/O, engine returns decisions consumed by `_apply` |
| `services/poller/scheduler.py` | `shared/scheduler/lua.py` | `consume_expedite` before choosing next score | ✓ WIRED | Confirmed via source read and integration test `test_poller_expedite_release.py` |
| `scripts/replay_raw.py` | `services/state_machine/engine.py` | `DiffEngine(MemoryStateStore())` | ✓ WIRED | Confirmed via `grep -n "DiffEngine(" scripts/replay_raw.py` and passing behavior |
| `shared/db.py` | migration 0008 | `(time, event_id)` PK match | ✓ WIRED | ORM PK matches unique index; confirmed by `test_migration_0008.py` |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Replay determinism (byte-identical, twice) | `uv run python scripts/replay_raw.py --input tests/fixtures/raw_streams/happy.jsonl` (run twice, diffed against each other and golden) | Identical byte streams both ways | ✓ PASS |
| Zero false events under transient-error stream | same script against `transient_errors.jsonl` | 0-byte output matching 0-byte golden | ✓ PASS |
| Flapping stream yields exactly one event | same script against `flapping.jsonl` | 1 line, matches golden | ✓ PASS |
| `MISE_CRASH_AFTER` refused in prod | `MISE_CRASH_AFTER=state_write ENV=prod uv run python -c "...run()..."` | `RuntimeError` raised naming the variable | ✓ PASS |
| Zero two-command SETNX+EXPIRE in tree | `grep -rn "SETNX\|setnx" services/ shared/ scripts/` | No matches | ✓ PASS |
| Zero inline async/sync sleep in state machine | `grep -rn "asyncio.sleep\|time.sleep" services/state_machine/` | No matches (exit 1) | ✓ PASS |
| Full unit suite | `uv run pytest tests/unit -q` | 156 passed | ✓ PASS |
| Full integration suite | `uv run pytest tests/integration -q -p no:cacheprovider` | 52 passed (111.00s) | ✓ PASS |
| Chaos SIGKILL test in isolation | `uv run pytest tests/integration/test_state_machine_chaos.py -v` | 1 passed (50.71s) | ✓ PASS |
| Persistence + e2e tests in isolation | `uv run pytest tests/integration/test_state_machine_e2e.py tests/integration/test_availability_events_persistence.py -v` | 7 passed | ✓ PASS |
| Lint | `uv run ruff check .` | All checks passed | ✓ PASS |
| Type check | `uv run mypy shared/ services/` | Success, no issues (35 files) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| STATE-01 | 02-02, 02-03 | Redis availability state set with 25h TTL | ✓ SATISFIED | `RedisStateStore` + `AVAIL_STATE_TTL_SECONDS=90000`, TTL refreshed on every write |
| STATE-02 | 02-01, 02-03 | Consumes `availability.raw`, tri-state diff | ✓ SATISFIED | `DiffEngine.process` + `StateMachineConsumer._handle_raw` |
| STATE-03 | 02-02, 02-03 | Confirmation re-poll at t+8s via ZSET, only confirmed slots emit | ✓ SATISFIED | `EXPEDITE_POLL_LUA` + `_confirm_or_wait` elapsed gate; zero inline sleep confirmed |
| STATE-04 | 02-01, 02-02, 02-03 | `SET NX EX` idempotency, 20-min TTL | ✓ SATISFIED | `set_nx_ex` single atomic call; chaos test proves zero duplicates |
| STATE-05 | 02-02, 02-03 | Persist to TimescaleDB with 5 analytics columns | ✓ SATISFIED | Migration 0008 + `persistence.py`; independently verified via test rerun |
| STATE-06 | 02-01, 02-04 | Replay script produces byte-identical output | ✓ SATISFIED | Independently reproduced byte-identical replay and zero-false-events proof |

REQUIREMENTS.md traceability table cross-checked: all 6 STATE-* IDs marked `[x]` and `Complete` for Phase 2, matching plan frontmatter `requirements:` declarations across 02-01..02-04. No orphaned requirements found for Phase 2.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `services/state_machine/parsers/opentable.py` | 34 | `TODO(P3/POLL-02): widen to the full party_sizes list...` | ℹ️ Info | Referenced to formal follow-up (Phase 3 / POLL-02); not a blocker per debt-marker gate (references formal work); backed by a regression test (`test_coverage_bounding.py`) |

No `TBD`, `FIXME`, or `XXX` markers found in any Phase 2 file. No stub returns, no hardcoded empty arrays feeding rendering, no placeholder strings.

### Deviations Noted (from SUMMARY, cross-checked against code — none are gaps)

- `BufferedStateStore` was added beyond the plan's literal text to fix a real lost-event window (engine writes through its store during diff, which would otherwise record AVAILABLE before the Kafka send). Verified present and wired into `consumer.py`/`main.py`; chaos test independently re-run and passes.
- Fixture payloads (`happy.jsonl`, `flapping.jsonl`, tracer tests) were deliberately trimmed to one seating type to make "exactly one event" literally true, since `seat_type` is part of slot identity (D-36) and the stock 2-seating-type fixture would yield two. The two-slots-one-poll case is independently covered by `test_two_slots_from_one_poll_write_two_rows_sharing_a_time` (re-run, passes).
- `02-VALIDATION.md` frontmatter still shows `status: draft` (not updated to `validated`) — a workflow bookkeeping field, not a code-correctness gap. Does not affect the truths verified above.

### Human Verification Required

None. Every ROADMAP success criterion (SC1-SC4) and every STATE-01..06 requirement was independently reproduced against live code, live containers (Kafka, Redis, TimescaleDB), or direct command execution — no item required subjective/visual judgment.

### Gaps Summary

No gaps found. All 12 derived observable truths (covering ROADMAP SC1-SC4 and STATE-01..06) were independently verified by reading the implementation and re-running commands/tests myself (not by trusting SUMMARY.md narration): full unit suite (156 passed), full integration suite (52 passed) including the SIGKILL chaos test, ruff/mypy clean, two independent replay runs producing byte-identical output matching committed goldens, a zero-byte transient-error replay, a one-line flapping replay, a direct grep proving zero two-command SETNX+EXPIRE and zero inline sleeps, and a live `MISE_CRASH_AFTER`+`ENV=prod` refusal check.

---

*Verified: 2026-09-05*
*Verifier: Claude (gsd-verifier)*
