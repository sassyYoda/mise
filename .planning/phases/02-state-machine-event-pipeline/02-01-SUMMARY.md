---
phase: 02-state-machine-event-pipeline
plan: 01
subsystem: api
tags: [pydantic, uuid5, state-machine, diff-engine, parser-registry, determinism, tdd]

# Dependency graph
requires:
  - phase: 01-foundation-admin-pre-conditions-opentable-polling
    provides: "AvailabilityRaw wire schema, OpenTable payload fixtures, request_params shape from services/poller/scheduler.py"
provides:
  - "AvailabilityEvent wire contract with declaration order as JSON wire order (byte-stable)"
  - "NAMESPACE_MISE + make_event_id — deterministic uuid5 event ids, stable across processes"
  - "Pure DiffEngine implementing the full D-41 tri-state transition table over a StateStore Protocol"
  - "MemoryStateStore for replay and unit tests"
  - "PARSER_REGISTRY + tolerant OpenTable parser with coverage bounded to the effective party size"
  - "tests/unit/factories.py — clock-free deterministic builders for every downstream unit test"
  - "Mechanical source-grep purity gate keeping the core free of wall-clock reads and entropy"
affects: [02-02-shared-kernel-expedite-schema, 02-03-consumer-shell-persistence, 02-04-replay-determinism, 03-resy, 04-notifier]

actuals:
  tokens: 17700
  tasks: 3
  commits: 6

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Functional core / imperative shell (Protocol seam, decisions returned as data)"
    - "Registry dispatch on message source instead of if/elif branching"
    - "Deterministic uuid5 identity derived from the FIRST sighting, not the confirming one"
    - "Source-grep unit test as a permanent architectural guard"

key-files:
  created:
    - services/state_machine/models.py
    - services/state_machine/engine.py
    - services/state_machine/store.py
    - services/state_machine/parsers/opentable.py
    - services/state_machine/parsers/__init__.py
    - services/state_machine/parsers/errors.py
    - tests/unit/factories.py
    - tests/unit/test_engine_purity.py
  modified:
    - shared/events.py
    - tests/unit/test_events_schema.py

key-decisions:
  - "DiffEngine is a pure functional core: no IO, no clock read, no entropy; all state through a StateStore Protocol (D-49)"
  - "SlotState uses enum.StrEnum instead of the plan's (str, Enum) — ruff UP042 rejects the mixin form on py312"
  - "One timeslot with two seatingTypes is TWO slots and therefore TWO events; Expedite is de-duplicated to one per restaurant per poll"
  - "Decisions are returned sorted by (date, party_size, slot_key) with Expedite sorted first via a sentinel key, so output order is fully specified"
  - "mark_unknown keeps the EARLIEST onset across repeated errors, making pure error sequences order-independent as well as error-after-success"
  - "STATE-02/04/06 left Pending in REQUIREMENTS.md — this plan ships only the pure core"

patterns-established:
  - "Pattern: every unit-test builder REQUIRES an explicit polled_at_epoch_ms and derives poll ids with uuid5, so no test can depend on real time or need a real 8-second wait"
  - "Pattern: parser tolerance via .get() chains plus isinstance checks only — a ragged payload entry is skipped, never allowed to raise and halt a Kafka partition"
  - "Pattern: ParseError messages name the defect only and never echo the third-party payload body, so they are safe to log"
  - "Pattern: architectural invariants that fail intermittently (clock leakage) are enforced by a source-grep test, not by review"

requirements-completed: []

coverage:
  - id: D1
    description: "Two availability.raw OpenTable polls of the same slot 9000 ms apart produce exactly one AvailabilityEvent per observed slot through DiffEngine + MemoryStateStore"
    requirement: STATE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_tracer_raw_to_event.py#test_second_poll_confirms_and_emits_without_expediting"
        status: pass
      - kind: unit
        ref: "tests/unit/test_tracer_raw_to_event.py#test_confirmed_event_field_values"
        status: pass
    human_judgment: false
  - id: D2
    description: "A first sighting produces an Expedite decision and no event; PENDING never emits"
    requirement: STATE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_tracer_raw_to_event.py#test_first_poll_expedites_and_emits_nothing"
        status: pass
      - kind: unit
        ref: "tests/unit/test_engine_transitions.py#test_second_sighting_below_confirm_delay_does_not_confirm"
        status: pass
    human_judgment: false
  - id: D3
    description: "A slot absent on the next successful covered poll while still PENDING is dropped with no event (false-positive guard)"
    requirement: STATE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_engine_transitions.py#test_pending_slot_absent_on_next_covered_poll_is_dropped_with_no_event"
        status: pass
    human_judgment: false
  - id: D4
    description: "event_id is uuid5(NAMESPACE_MISE, '{source}:{rid}:{date}:{party}:{slot_key}:{first_poll_id}') and is identical across processes and repeated construction"
    requirement: STATE-04
    verification:
      - kind: unit
        ref: "tests/unit/test_event_id_determinism.py#test_event_id_is_stable_across_a_fresh_interpreter"
        status: pass
      - kind: unit
        ref: "tests/unit/test_event_id_determinism.py#test_changing_only_the_first_poll_id_changes_the_event_id"
        status: pass
    human_judgment: false
  - id: D5
    description: "Parser failures (missing data, GraphQL errors array, empty dict, non-dict payload) raise ParseError, remove nothing and emit nothing"
    verification:
      - kind: unit
        ref: "tests/unit/test_parsers_opentable.py#test_malformed_payloads_raise_parse_error"
        status: pass
      - kind: unit
        ref: "tests/unit/test_parsers_opentable.py#test_non_mapping_payload_raises_parse_error"
        status: pass
      - kind: unit
        ref: "tests/unit/test_engine_tristate_unknown.py#test_unknown_mark_leaves_every_slot_record_untouched"
        status: pass
    human_judgment: false
  - id: D6
    description: "source='resy' raises UnsupportedSourceError, a subclass of ParseError, until Phase 3 registers a parser"
    verification:
      - kind: unit
        ref: "tests/unit/test_parsers_opentable.py#test_resy_source_is_unsupported_until_phase_three"
        status: pass
    human_judgment: false
  - id: D7
    description: "Coverage is the effective party size only — a poll declaring party_sizes=[2,4] closes and drops nothing for party 4"
    requirement: STATE-02
    verification:
      - kind: unit
        ref: "tests/unit/test_coverage_bounding.py#test_party_two_poll_never_closes_a_party_four_slot"
        status: pass
      - kind: unit
        ref: "tests/unit/test_coverage_bounding.py#test_party_two_poll_never_drops_a_pending_party_four_slot"
        status: pass
    human_judgment: false
  - id: D8
    description: "An UNKNOWN mark is monotonic in polled_at_epoch_ms: an older error never overrides a newer success"
    verification:
      - kind: unit
        ref: "tests/unit/test_engine_tristate_unknown.py#test_older_error_after_newer_success_is_a_no_op"
        status: pass
      - kind: unit
        ref: "tests/unit/test_engine_tristate_unknown.py#test_repeated_errors_keep_the_earliest_onset_in_either_order"
        status: pass
    human_judgment: false
  - id: D9
    description: "Adjacency, empty and ordering edges: duplicate (time_slot, seat_type) collapse to one field, differing seat types stay two events, a zero-slot poll closes and drops, and decisions sort by (date, party_size, slot_key)"
    requirement: STATE-04
    verification:
      - kind: unit
        ref: "tests/unit/test_engine_transitions.py#test_duplicate_time_and_seat_type_collapse_to_one_field"
        status: pass
      - kind: unit
        ref: "tests/unit/test_engine_transitions.py#test_same_time_different_seat_types_stay_two_events"
        status: pass
      - kind: unit
        ref: "tests/unit/test_engine_transitions.py#test_empty_poll_closes_available_and_drops_pending_together"
        status: pass
      - kind: unit
        ref: "tests/unit/test_engine_transitions.py#test_decisions_are_sorted_and_reproducible"
        status: pass
    human_judgment: false
  - id: D10
    description: "AvailabilityEvent JSON bytes are stable — declaration order is wire order and a reversed input dict yields identical bytes"
    requirement: STATE-06
    verification:
      - kind: unit
        ref: "tests/unit/test_events_schema.py#test_availability_event_wire_order_follows_declaration_order"
        status: pass
      - kind: unit
        ref: "tests/unit/test_tracer_raw_to_event.py#test_replaying_the_same_polls_is_byte_identical"
        status: pass
    human_judgment: false
  - id: D11
    description: "The engine, models and parsers are mechanically proven free of wall-clock reads, entropy, IO imports and event-loop blocking"
    verification:
      - kind: unit
        ref: "tests/unit/test_engine_purity.py#test_engine_models_and_parsers_contain_no_clock_or_randomness"
        status: pass
      - kind: unit
        ref: "tests/unit/test_engine_purity.py#test_core_never_imports_io_libraries"
        status: pass
    human_judgment: false
  - id: D12
    description: "Under a Kafka group rebalance mid-message the CommitFailedError path is caught, logged and left to redelivery"
    verification: []
    human_judgment: true
    rationale: "Backstop truth for the consumer shell, which lands in plan 02-03. No consumer exists in this plan, so there is nothing to exercise yet."

# Metrics
duration: 13min
completed: 2026-09-05
status: complete
---

# Phase 2 Plan 01: Core Diff Engine Summary

**A pure, IO-free tri-state DiffEngine that turns two raw OpenTable polls 9000 ms apart into one deterministic `AvailabilityEvent`, with a uuid5 event identity that is byte-identical across processes and a grep test that keeps the clock out forever.**

## Performance

- **Duration:** 13 min
- **Started:** 2026-09-05T05:10:22Z
- **Completed:** 2026-09-05T05:23:00Z
- **Tasks:** 3
- **Files modified:** 17 (15 created, 2 modified)

## Accomplishments

- **The tracer works end to end in milliseconds.** `parse_raw` → `DiffEngine(MemoryStateStore(), confirm_delay_ms=8000)` turns two `AvailabilityRaw` messages into a confirmed `AvailabilityEvent` without touching Redis, Kafka, Postgres, the network, or the wall clock. The whole unit suite runs in 0.15 s.
- **Event identity is permanent and reproducible.** `NAMESPACE_MISE` is a hard-coded literal with a never-change docstring, and `make_event_id` is proven stable both in-process and in a fresh interpreter subprocess. Keying on the *first* poll id means a re-opened slot is a genuinely new event while a redelivered confirmation reproduces the old id exactly.
- **The full D-41 transition table is implemented and unit-proven**, including the false-positive guard (PENDING dropped, never emitted), the sub-delay non-confirmation, AVAILABLE→UNAVAILABLE closure carrying the original `event_id`, and the re-open cycle.
- **The research B-4 landmine is defused and guarded.** Coverage derives from the *effective* party size (`party_sizes[0]`), so a party-2-only poll neither closes nor drops party-4 slots. Two regression tests pin this ahead of the Phase 3 change that makes the adapter loop party sizes.
- **UNKNOWN marking is monotonic**, so the two-topic consumer in 02-03 is order-independent and replay is reproducible regardless of `getone()` fairness.
- **Determinism is mechanically enforced, not reviewed.** `tests/unit/test_engine_purity.py` greps `engine.py`, `models.py` and `parsers/*.py` for clock reads, entropy, IO imports and event-loop blocking, stripping full-line comments first.
- Unit suite grew 27 → 89 passing tests; `ruff`, `mypy --strict` and the 12 pre-existing integration tests are all green.

## Task Commits

Each task was committed atomically, TDD gates included:

1. **Task 1 (tracer, tdd): raw OpenTable poll becomes a confirmed AvailabilityEvent**
   - RED: `c207e89` (test) — tracer test + `tests/unit/factories.py`
   - GREEN: `4156ab6` (feat) — `shared/events.py` additions, models, parsers, engine, store
2. **Task 2 (tdd): tri-state transition matrix, coverage bounding, monotonic UNKNOWN**
   - RED: `c5c5a81` (test) — three test files covering every transition and edge
   - GREEN: `590ba6b` (feat) — full transition table, `mark_unknown`/`mark_success`, mass-closure audit count
3. **Task 3 (tdd): parser failure matrix, event_id determinism, mechanical purity guard**
   - `6eac674` (test) — see TDD Gate Compliance below for why this task has no separate GREEN commit

**Plan metadata:** see the `docs(02-01)` commit that carries this SUMMARY, STATE.md and ROADMAP.md.

## Files Created/Modified

**Created**
- `services/state_machine/__init__.py` — package marker with decision-id docstring
- `services/state_machine/models.py` — `SlotState` (StrEnum), `Slot`/`slot_key`, `ParsedPoll`, `SlotRecord` with compact `s,t,f,p,l,c,e` JSON codecs, `MetaRecord`, `Expedite`/`Emit`/`Close`/`Decision`, `DEFAULT_CONFIRM_DELAY_MS`
- `services/state_machine/engine.py` — `StateStore` Protocol, `DiffEngine.process/mark_unknown/mark_success`, `MASS_CLOSURE_AUDIT_THRESHOLD`, `last_close_count`
- `services/state_machine/store.py` — `MemoryStateStore` over two plain dicts, no TTL semantics
- `services/state_machine/parsers/errors.py` — `ParseError`, `UnsupportedSourceError`
- `services/state_machine/parsers/opentable.py` — `effective_coverage` (D-38a) and a tolerant `parse_opentable`
- `services/state_machine/parsers/__init__.py` — `PARSER_REGISTRY` and `parse_raw` dispatch
- `tests/unit/factories.py` — `make_raw`/`make_slot`/`make_parsed`, all requiring an explicit `polled_at_epoch_ms`
- `tests/unit/test_tracer_raw_to_event.py`, `test_engine_transitions.py`, `test_coverage_bounding.py`, `test_engine_tristate_unknown.py`, `test_parsers_opentable.py`, `test_event_id_determinism.py`, `test_engine_purity.py`

**Modified**
- `shared/events.py` — `NAMESPACE_MISE`, `make_event_id`, `AvailabilityEvent` (frozen, `extra="forbid"`, declaration order = wire order), updated `Named symbols:` header
- `tests/unit/test_events_schema.py` — frozen / extra-forbid / `to_bytes` round-trip / reversed-input byte-stability / null-emission tests for `AvailabilityEvent`

## Decisions Made

- **Expedite is de-duplicated to one per restaurant per poll.** The scheduler ZSET score is per job, not per slot, so a burst of PENDING slots must pull exactly one poll forward. This resolves the plan's `STATE-03` flagged assumption in the direction 02-CONTEXT D-43 implies.
- **Decision ordering is a total order.** `Emit`/`Close` sort by `(date, party_size, slot_key)`; `Expedite` carries no slot coordinates so it sorts first via a sentinel key. Without a total order the returned list would be only partially specified and replay line order would not be reproducible.
- **`mark_unknown` keeps the earliest onset** across repeated errors (`min`), which makes pure error sequences order-independent as well as the error-after-success case D-53 requires, and matches the field name `unknown_since_ms`.
- **A slot record found in `UNAVAILABLE` (or the defensive `UNKNOWN`) state and observed again starts a brand-new cycle** with the current poll id, which is what makes the re-opened event id differ.
- **`Close` is suppressed when an AVAILABLE record carries no `event_id`.** The state still transitions to UNAVAILABLE, but there is no DB row to close, so emitting a `Close` with a fabricated id would be worse than emitting nothing.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `SlotState(str, Enum)` rejected by ruff UP042**
- **Found during:** Task 1 (models.py)
- **Issue:** The plan specifies `SlotState(str, Enum)`. Ruff rule `UP042` (in the repo's selected `UP` set) rejects the `str`+`Enum` mixin on py312 and the lint gate is mandatory before every commit.
- **Fix:** Used `enum.StrEnum`, which is the py312 stdlib form of exactly the same thing — still a `str` subclass, `.value` and `SlotState("PENDING")` behave identically, so the Redis serialisation contract is unchanged.
- **Files modified:** `services/state_machine/models.py`
- **Verification:** `uv run ruff check .` clean; `SlotRecord.to_json`/`from_json` round-trip asserted through every transition test.
- **Committed in:** `4156ab6`

**2. [Rule 1 - Bug] Plan text says "exactly one Emit"; the fixture yields two**
- **Found during:** Task 1 (tracer test)
- **Issue:** Task 1 Test 1 says the confirming poll returns "exactly one `Emit`", but `OPENTABLE_SUCCESS_RESPONSE` carries `seatingTypes: ["bar", "standard"]`, and Task 3 of the same plan explicitly requires that payload to parse to **2 slots** (one per seating type). Since `seat_type` is part of slot identity (D-36), two slots must produce two events. The two statements cannot both hold.
- **Fix:** Followed D-36 and Task 3 — the confirming poll emits **two** events (`bar`, `standard`, in `slot_key` order) with two distinct `event_id`s. Task 1 Test 2's field assertions are made against the `bar` event, exactly as the plan's expected values describe. `Expedite`, by contrast, genuinely is one per restaurant per poll.
- **Files modified:** `tests/unit/test_tracer_raw_to_event.py`
- **Verification:** `test_second_poll_confirms_and_emits_without_expediting` pins the count at 2 and the order at `[bar, standard]`; `test_same_time_different_seat_types_stay_two_events` pins the two distinct ids.
- **Committed in:** `c207e89` / `4156ab6`

**3. [Rule 3 - Blocking] Determinism subprocess uses `sys.executable`, not `uv run python`**
- **Found during:** Task 3 (`test_event_id_determinism.py`)
- **Issue:** The plan suggests `subprocess.run(["uv", "run", "python", "-c", ...])`. Shelling out through `uv` inside a test makes the assertion depend on `uv` being on PATH and on dependency resolution succeeding, turning a determinism assertion into an environment assertion.
- **Fix:** Used `sys.executable`, which is the same venv interpreter `uv run` would select, in a genuinely fresh process — which is the property under test.
- **Files modified:** `tests/unit/test_event_id_determinism.py`
- **Verification:** `test_event_id_is_stable_across_a_fresh_interpreter` passes; the plan's own `uv run python -c` acceptance command was also run twice manually and printed `21b2421d-b3cb-5572-9988-830d4e6c4a3c` both times.
- **Committed in:** `6eac674`

### Decisions Taken Autonomously (no human in the loop)

**4. Requirements STATE-02 / STATE-04 / STATE-06 left `Pending` in REQUIREMENTS.md**
- The plan frontmatter lists these three, but each is only half-delivered here by the plan's own admission: STATE-04's requirement text is the `SET NX EX` emission claim (plan 02-02/02-03), STATE-06 is the replay script (plan 02-04), and STATE-02's consumer side is the shell in 02-03. This plan's own success criteria say "STATE-06 groundwork".
- Marking them `Done` after plan 1 of 4 would put a false green in the traceability matrix and mislead the phase verifier. `requirements-completed` is therefore `[]`, with the pure-core evidence recorded in the `coverage:` block above so the phase verifier can close them once 02-02..02-04 land.

---

**Total deviations:** 3 auto-fixed (1 bug, 2 blocking) + 1 autonomous decision recorded
**Impact on plan:** No scope change. Deviation 2 is a genuine internal inconsistency in the plan text resolved in favour of the locked decision (D-36) and the fixture; the other two are mechanical.

## TDD Gate Compliance

Tasks 1 and 2 have clean RED → GREEN gate pairs (`c207e89`→`4156ab6`, `c5c5a81`→`590ba6b`).

**Task 3 has no separate GREEN commit, and this is intentional.** Its tests passed on first run because the plan's *Task 1* `<action>` already mandated the complete `ParseError` matrix (`payload not a mapping`, `empty payload`, `graphql errors present`, `missing data key`, `data not a mapping`) and `.get()`-chain tolerance, which shipped in `4156ab6`. Task 3's action ("harden `parse_opentable`") was therefore already satisfied.

Per the fail-fast rule, an unexpectedly-passing RED phase was **not** waved through. Two mutation probes confirmed the tests are not vacuous:

| Mutation | Expected | Result |
|---|---|---|
| Add `def _probe() -> float: return time.time()` to `engine.py` | purity gate fails | `test_engine_models_and_parsers_contain_no_clock_or_randomness` FAILED |
| Delete the `if payload.get("errors"): raise ParseError(...)` guard from `parse_opentable` | parser matrix fails | `test_malformed_payloads_raise_parse_error[payload4]` FAILED |

Both mutations were reverted and the full suite re-confirmed at 89 passed. Note that `test_rate_limit_response_raises_parse_error` survived the second mutation because `OPENTABLE_RATE_LIMIT_RESPONSE` has no `data` key and so still raises via the `missing data key` guard — the parametrised `payload4` case exists precisely to cover the `errors`-specific path.

## Known Stubs

None. No hardcoded empty values, placeholder strings, or unwired components were introduced.

The one carried-forward `TODO` is inherited, deliberate and documented in the plan:

- `services/state_machine/parsers/opentable.py` — `# TODO(P3/POLL-02): widen to the full party_sizes list when the adapter loops party sizes`. This is not a stub: `effective_coverage` is fully implemented and correct for today's single-party adapter, and `tests/unit/test_coverage_bounding.py` is the regression guard for the Phase 3 widening.
- The OpenTable payload shape remains `[ASSUMED]` pending the Phase 1 DevTools spike (a Phase 1 human gate, not new debt). The parser docstring carries the same `[ASSUMED]` / `TODO(spike)` banner as `services/poller/sources/opentable/fixtures.py`, and the tolerance tests mean a shape surprise degrades to `ParseError` + UNKNOWN rather than a crashed partition.

## Threat Flags

None. This plan adds no network endpoint, no auth path, no file access and no schema change. The two security-relevant behaviours it *does* add are both hardening: untrusted third-party JSON is walked with `.get()` chains and `isinstance` checks only (denial-of-service row of the research Security Domain), and `ParseError` messages name the defect without echoing the payload body, so a booking token cannot reach the logs through an exception message — asserted by `test_parse_error_message_never_echoes_the_payload`.

## Issues Encountered

- **Ruff isort reclassified `shared` as first-party** once `services/state_machine/` existed as a real package, which reordered imports in two already-committed test files. Resolved with `ruff check --fix`; the reordering rides along in `6eac674`.
- No other issues. No auth gates, no architectural decisions requiring escalation, no fix-attempt limits reached.

## User Setup Required

None — no external service configuration required. This plan is pure in-process code and adds no dependency, no env var and no infrastructure.

## Next Phase Readiness

**Ready for the rest of Wave 1 and Wave 2:**
- `shared/events.py :: AvailabilityEvent` is frozen and byte-stable — 02-03 can publish it and 02-04 can golden-file it as-is.
- `DiffEngine` + `StateStore` Protocol are complete and unchanged-by-design: 02-03 implements `RedisStateStore` against the same five methods, 02-04 reuses `MemoryStateStore` verbatim.
- `Emit.idempotency_token` (`booking_token or slot_key`) is ready for the D-46 `SET NX EX` claim in 02-02/02-03.
- `DiffEngine.last_close_count` and `MASS_CLOSURE_AUDIT_THRESHOLD` are ready for the distinct structlog audit event 02-03 must log (research Pitfall 10).
- `tests/unit/factories.py` gives every later plan clock-free builders.

**Carried forward, not blocking this plan:**
- The `resy` parser is deliberately absent; `parse_raw` raises `UnsupportedSourceError` until Phase 3 registers one.
- `shared/redis_keys.py` is untouched here on purpose (`DEFAULT_CONFIRM_DELAY_MS` lives in `models.py`) to avoid a wave-1 write race with 02-02. Whoever wires the shell should decide whether the constant moves.
- The OpenTable DevTools spike (Phase 1 human gate) still governs whether the `[ASSUMED]` payload walk matches reality.

---
*Phase: 02-state-machine-event-pipeline*
*Completed: 2026-09-05*

## Self-Check: PASSED

All 18 claimed files verified present on disk; all 7 claimed commits verified in `git log`.
Final gate re-run at completion: `ruff check .` clean, `mypy shared/ services/` clean (30 files),
`pytest tests/unit -q` 89 passed, `pytest tests/integration -q` 12 passed.
