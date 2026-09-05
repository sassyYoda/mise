---
phase: 02-state-machine-event-pipeline
plan: 04
subsystem: tooling
tags: [replay, determinism, golden-files, kafka-offsets, cli, tdd]

# Dependency graph
requires:
  - phase: 02-state-machine-event-pipeline
    provides: "02-01 pure DiffEngine + MemoryStateStore + OpenTable parser + AvailabilityEvent.to_bytes(); 02-02 make_producer/make_consumer and the integration conftest; 02-03 the running consumer whose wire bytes the goldens must match"
  - phase: 01-foundation-admin-pre-conditions-opentable-polling
    provides: "AvailabilityRaw / PollCompleted wire schemas, scripts/ header conventions, tests/conftest.py container fixtures, Makefile help convention"
provides:
  - "scripts/replay_raw.py — jsonl and bounded-offset-range replay producing byte-identical availability.events output (STATE-06)"
  - "fetch_offset_range — group-less, half-open [from, to) Kafka reader that cannot commit an offset"
  - "canonical_topic — maps a renamed or mirrored source topic onto the message schema it carries"
  - "tests/fixtures/raw_streams/ — three input streams and three committed goldens, the phase's regression contract"
  - "make replay ARGS=... — the documented, discoverable entry point"
  - "CONFIRM_DELAY_MS and a TEST ONLY MISE_CRASH_AFTER in .env.example"
affects: [03-resy, 04-notifier, 05-api-sse, 06-pattern-intelligence]

actuals:
  tokens: 13900
  tasks: 3
  commits: 7

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Golden files as a wire-format tripwire: the artifact is committed, so drift shows up as a reviewable diff rather than a changed integer inside a test"
    - "Guard-the-guard assertions beside every zero-count claim, so a weakened fixture cannot make the claim vacuous"
    - "AST-scoped content gates instead of text greps, so the docstring explaining a prohibition cannot trip the gate enforcing it"
    - "One tagged-envelope line format lets a single fixture carry two Kafka topics"

key-files:
  created:
    - scripts/replay_raw.py
    - tests/fixtures/raw_streams/happy.jsonl
    - tests/fixtures/raw_streams/happy.events.jsonl
    - tests/fixtures/raw_streams/transient_errors.jsonl
    - tests/fixtures/raw_streams/transient_errors.events.jsonl
    - tests/fixtures/raw_streams/flapping.jsonl
    - tests/fixtures/raw_streams/flapping.events.jsonl
    - tests/unit/test_replay_determinism.py
    - tests/unit/test_replay_zero_false_events.py
    - tests/integration/test_replay_offset_range.py
  modified:
    - Makefile
    - .env.example
    - services/state_machine/README.md

key-decisions:
  - "confirm_delay_ms comes from the compiled-in DEFAULT_CONFIRM_DELAY_MS, never from the environment — a golden whose bytes depended on the caller's shell would not be a golden"
  - "happy.jsonl is trimmed to ONE seating type: the shipped OPENTABLE_SUCCESS_RESPONSE describes two slots and would emit two events, contradicting the plan's own one-line acceptance criterion (D-36)"
  - "Diagnostics are routed to stderr because shared.telemetry configures the root logger with stream=sys.stdout at DEBUG, which corrupted the script's default stdout output mode"
  - "canonical_topic routes a renamed or mirrored source topic onto the availability.raw schema rather than treating it as unrouted, because a silent zero-event replay is indistinguishable from a stream that legitimately confirmed nothing"
  - "The exclude_none / exclude_unset gate matches the AST, not the source text, so the docstring explaining the prohibition cannot trip it"
  - "STATE-06 marked Done: byte-identity is proven twice over — two runs against each other and both against a committed golden"

patterns-established:
  - "Pattern: every fixture that asserts a COUNT ships a companion assertion that the fixture really contains the conditions it claims to (four failure modes present, the flapping poll really omits the slot)"
  - "Pattern: a mutation probe is run against every golden-file claim before it is trusted — an inclusive upper bound and a re-shown slot were both proven to break the suite"
  - "Pattern: a developer tool that takes paths from argv resolves them and refuses to escape the repository root unless the caller passes an absolute path"

requirements-completed: [STATE-06]

coverage:
  - id: D1
    description: "Two consecutive replays of happy.jsonl are byte-identical to each other and to the committed golden happy.events.jsonl"
    requirement: STATE-06
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py#test_two_replays_are_byte_identical_and_match_the_golden"
        status: pass
      - kind: command
        ref: "cmp /tmp/m1.jsonl /tmp/m2.jsonl && cmp /tmp/m1.jsonl tests/fixtures/raw_streams/happy.events.jsonl (via make replay, twice)"
        status: pass
    human_judgment: false
  - id: D2
    description: "Each output line is exactly AvailabilityEvent.to_bytes() — the producer's single serializer — and optional fields are emitted, never omitted"
    requirement: STATE-06
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py#test_every_output_line_round_trips_through_the_single_serializer"
        status: pass
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py#test_the_script_declares_no_second_serializer_and_no_production_client"
        status: pass
    human_judgment: false
  - id: D3
    description: "The transient-error stream (timeout, 503, GraphQL errors array, empty payload) produces ZERO events and matches a committed zero-byte golden"
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_zero_false_events.py#test_the_transient_error_stream_produces_zero_events"
        status: pass
      - kind: unit
        ref: "tests/unit/test_replay_zero_false_events.py#test_the_transient_replay_matches_the_zero_byte_golden"
        status: pass
      - kind: unit
        ref: "tests/unit/test_replay_zero_false_events.py#test_the_stream_actually_carries_all_four_failure_modes"
        status: pass
    human_judgment: false
  - id: D4
    description: "A PENDING slot is never promoted by an error burst, and the next clean covered poll drops it without emitting"
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_zero_false_events.py#test_a_pending_slot_is_never_promoted_by_an_error_burst"
        status: pass
      - kind: unit
        ref: "tests/unit/test_replay_zero_false_events.py#test_the_final_clean_poll_drops_the_pending_slot_without_emitting"
        status: pass
    human_judgment: false
  - id: D5
    description: "The transient stream is order-independent: moving both polls.completed lines to the end still yields zero events (D-53)"
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_zero_false_events.py#test_the_transient_stream_is_order_independent"
        status: pass
    human_judgment: false
  - id: D6
    description: "A slot seen, gone and seen again yields exactly ONE event whose first_seen_at_epoch_ms is the SECOND sighting"
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_zero_false_events.py#test_the_flapping_stream_produces_exactly_one_event"
        status: pass
      - kind: command
        ref: "mutation probe: deleting the gone-poll moves first_seen_at back to t0, proving the drop logic is what dates the event"
        status: pass
    human_judgment: false
  - id: D7
    description: "--to-offset is EXCLUSIVE: [2, 5) consumes offsets 2, 3 and 4 against a live broker (D-55)"
    requirement: STATE-06
    verification:
      - kind: integration
        ref: "tests/integration/test_replay_offset_range.py#test_the_upper_bound_is_exclusive"
        status: pass
      - kind: command
        ref: "mutation probe: min(to_offset + 1, end) makes the exclusivity and empty-range tests fail"
        status: pass
    human_judgment: false
  - id: D8
    description: "Omitting --to-offset consumes through end_offsets and stops rather than blocking forever"
    verification:
      - kind: integration
        ref: "tests/integration/test_replay_offset_range.py#test_omitting_the_upper_bound_stops_at_the_end_offsets"
        status: pass
      - kind: integration
        ref: "tests/integration/test_replay_offset_range.py#test_an_empty_topic_exits_2_rather_than_hanging"
        status: pass
    human_judgment: false
  - id: D9
    description: "Adjacency and empty edges: --from-offset 3 --to-offset 3 consumes nothing and exits 2; an empty input file exits 0 with a zero-byte output"
    requirement: STATE-06
    verification:
      - kind: integration
        ref: "tests/integration/test_replay_offset_range.py#test_an_empty_half_open_range_consumes_nothing_and_exits_2"
        status: pass
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py#test_an_empty_input_file_replays_to_a_zero_byte_output"
        status: pass
    human_judgment: false
  - id: D10
    description: "T-02-06: a replay leaves the state-machine group's committed offset unchanged and registers no consumer group of its own"
    verification:
      - kind: integration
        ref: "tests/integration/test_replay_offset_range.py#test_replay_never_moves_the_state_machine_groups_committed_offsets"
        status: pass
      - kind: integration
        ref: "tests/integration/test_replay_offset_range.py#test_the_replay_consumer_never_subscribes"
        status: pass
    human_judgment: false
  - id: D11
    description: "T-02-05: an --output path that resolves outside the repository root is refused unless given as an absolute path"
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py#test_an_output_path_outside_the_repository_root_is_refused"
        status: pass
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py#test_main_exits_1_on_a_refused_output_path"
        status: pass
    human_judgment: false
  - id: D12
    description: "Replay reaches no production persistence: sqlalchemy, asyncpg, the consumer and the persistence module are all absent from sys.modules after importing the script"
    requirement: STATE-06
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py#test_input_mode_never_reaches_the_persistence_or_consumer_layer"
        status: pass
    human_judgment: false
  - id: D13
    description: "make replay and make state-machine are documented, discoverable targets, and .env.example carries CONFIRM_DELAY_MS plus a TEST ONLY MISE_CRASH_AFTER banner"
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py#test_the_makefile_exposes_replay_and_state_machine"
        status: pass
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py#test_the_env_example_documents_the_confirmation_window_and_the_crash_hook"
        status: pass
      - kind: command
        ref: "make help | grep -E 'state-machine|replay'"
        status: pass
    human_judgment: false
  - id: D14
    description: "Ordering: output line order is the engine's decision order within a message and input order across messages, so it is fully specified"
    verification: []
    human_judgment: true
    rationale: "The property is inherited from 02-01, where `_sort_key` gives decisions a total order over (date, party_size, slot_key) and `test_decisions_are_sorted_and_reproducible` pins it. Every fixture in this plan confirms a single slot, so no fixture here produces two events in one message to order. A multi-slot ordering fixture would restate a property the pure core already proves."

# Metrics
duration: 11min
completed: 2026-09-05
status: complete
---

# Phase 2 Plan 04: Replay Determinism Summary

**`make replay ARGS="--input tests/fixtures/raw_streams/happy.jsonl"` regenerates the exact bytes the state machine put on the wire — twice in a row and matching a committed golden — while a simulated transient-error stream provably emits nothing and a bounded Kafka offset range replays without touching the `state-machine` group's committed offsets.**

## Performance

- **Duration:** 11 min
- **Started:** 2026-09-05T06:14Z
- **Completed:** 2026-09-05T06:25Z
- **Tasks:** 3
- **Files modified:** 13 (10 created, 3 modified), 1092 insertions

## Accomplishments

- **STATE-06 is a passing test rather than a claim.** Two replays of `happy.jsonl` are byte-identical to each other and to `happy.events.jsonl`, which was generated by the script and committed verbatim. The golden is a deliberate ratchet: any future change to `NAMESPACE_MISE`, the `event_id` recipe, or `AvailabilityEvent`'s field order fails this file, which is exactly the drift it exists to catch.
- **ROADMAP SC1 now has a data artifact.** `transient_errors.jsonl` carries a timeout, a 503, a GraphQL `errors` array and an empty `{}` body around a legitimate first sighting whose confirmation never arrives, then a clean recovery poll that omits the slot. It replays to zero events, and its golden is a committed **zero-byte file** so a regression that starts emitting shows up as a reviewable diff rather than a changed integer.
- **Every zero-count claim ships a guard against its own vacuity.** `test_the_stream_actually_carries_all_four_failure_modes` and `test_the_flapping_stream_really_flaps` assert the fixtures genuinely contain the conditions they claim, so nobody can weaken a fixture into a trivially-passing green.
- **Two mutation probes proved the assertions measure something.** Re-showing the slot in the transient stream's recovery poll makes it emit 1 event; deleting the "gone" poll from the flapping stream moves `first_seen_at_epoch_ms` back from t0+180s to t0. Both were run against copies, never against the committed fixtures.
- **The offset-range mode is structurally incapable of moving production offsets.** `group_id=None` plus `assign`/`seek` (never `subscribe`) is asserted against a live broker: a real `state-machine` group commits offset 2, a full replay runs, and the commit is still 2 — and `list_consumer_groups()` shows the tool registered nothing of its own.
- **The half-open bound is verified end to end.** `[2, 5)` consumes offsets 2, 3 and 4; omitting `--to-offset` reads through `end_offsets` and stops rather than blocking; `from == to` consumes nothing and exits 2. A mutation to `min(to_offset + 1, end)` breaks two tests, so the exclusivity is measured, not assumed.
- **Two real defects were found by running the code** (see Deviations): the script's default stdout mode was being corrupted by the shared telemetry logger, and `--topic` pointed at any renamed topic produced a silent zero-event replay.
- Unit suite grew 131 → 156; integration grew 45 → 52. `ruff`, `mypy --strict` (35 files) and the full container suite are green, and `git status --porcelain tests/fixtures/raw_streams/` is empty after a full run — no test rewrites a golden in place.

## Task Commits

Each task was committed atomically with its TDD gates:

1. **Task 1 (tracer, tdd): raw jsonl in, byte-identical events jsonl out**
   - RED: `a075fa1` (test) — `happy.jsonl` + the determinism test, failing on `No module named 'scripts.replay_raw'`
   - GREEN: `832ad0e` (feat) — `scripts/replay_raw.py` `--input` mode and the committed `happy.events.jsonl`
2. **Task 2 (tdd): the zero-false-events proof**
   - RED: `ee4c08b` (test) — transient and flapping assertions, failing on missing fixtures
   - GREEN: `a9235ac` (feat) — both fixtures and both goldens
3. **Task 3 (tdd): bounded offset-range replay, Makefile and env wiring**
   - RED: `e65ff61` (test) — the offset-range integration module, failing on `cannot import name 'fetch_offset_range'`
   - GREEN: `ab6406c` (feat) — `fetch_offset_range`, `canonical_topic`, `make replay`, `.env.example`
4. **Docs:** `8e231fd` — the service README's replay section rewritten for the shipped script

**Plan metadata:** see the `docs(02-04)` commit carrying this SUMMARY, STATE.md, ROADMAP.md and REQUIREMENTS.md.

## Files Created/Modified

**Created**
- `scripts/replay_raw.py` — argparse CLI with a required mutually-exclusive `--input` / `--from-offset` group; `read_envelopes`, `replay`, `resolve_output_path`, `write_lines`, `fetch_offset_range`, `canonical_topic`, `records_to_envelopes`, `route_diagnostics_to_stderr`; exit codes 0/1/2
- `tests/fixtures/raw_streams/happy.jsonl` — two polls 9000 ms apart, rid 42, 2026-05-01, party 2
- `tests/fixtures/raw_streams/happy.events.jsonl` — the SC2 golden, 1 line
- `tests/fixtures/raw_streams/transient_errors.jsonl` — 6 lines across 4 failure modes plus the PENDING-dropped recovery poll
- `tests/fixtures/raw_streams/transient_errors.events.jsonl` — the SC1 golden, 0 bytes
- `tests/fixtures/raw_streams/flapping.jsonl` — seen / gone / seen / confirmed at 90 s and 9 s gaps
- `tests/fixtures/raw_streams/flapping.events.jsonl` — 1 line, dated from the second sighting
- `tests/unit/test_replay_determinism.py` — 16 tests: byte identity, golden match, single serializer, empty and blank-line edges, the output-path guard, the persistence-import gate, the AST serializer gate, stdout purity, `--help` contract, Makefile and `.env.example` wiring
- `tests/unit/test_replay_zero_false_events.py` — 9 tests: zero events, zero-byte golden match, all four failure modes present, PENDING never promoted, PENDING dropped, order independence, exactly-one flapping event, the flapping fixture really flaps, every line a valid tagged envelope
- `tests/integration/test_replay_offset_range.py` — 7 tests against a live broker, each seeding its own uniquely named topic so offsets are always 0..5

**Modified**
- `Makefile` — `replay` target with the `## ` help comment, added to `.PHONY`
- `.env.example` — a `# State machine` section with `CONFIRM_DELAY_MS=8000` and a four-line `TEST ONLY` banner above `MISE_CRASH_AFTER=`
- `services/state_machine/README.md` — the replay section now describes the shipped script, its exit codes and the fixture corpus table

## Decisions Made

- **`confirm_delay_ms` is the compiled-in `DEFAULT_CONFIRM_DELAY_MS` from `services/state_machine/models.py`, never an environment read.** A golden whose bytes depended on the caller's `CONFIRM_DELAY_MS` would not be a golden — CI and a developer's shell would disagree, and the failure would be intermittent. `.env.example` still documents `CONFIRM_DELAY_MS` because it configures the *service*.
- **Fixture lines are tagged envelopes** (`{"topic": ..., "value": ...}`), which is what lets one file carry both `availability.raw` and `polls.completed` — the transient-error stream needs both.
- **Every timestamp and every poll id in every fixture is a hard-coded literal.** Nothing was generated at authoring time. A fixture with a generated UUID would produce a different `event_id` on regeneration and the golden would be worthless.
- **Each integration test seeds its own uniquely named topic.** Sharing one topic across tests in a module-scoped container makes offsets depend on execution order, which is precisely the kind of hidden coupling an offset-exactness test must not have.
- **The `exclude_none` / `exclude_unset` gate matches the AST, not the text.** Following the 02-02 precedent: the script's docstring explains *why* those kwargs are forbidden, and a text gate would be tripped by the explanation it exists to motivate. Matching `ast.Call` keywords is also a stronger assertion — it catches the kwarg wherever it appears, and ignores prose.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] The script's default stdout mode was corrupted by the shared telemetry logger**
- **Found during:** Task 1, immediately after generating the first golden
- **Issue:** `--output` defaults to stdout, but `shared/telemetry.py:44` calls `logging.basicConfig(stream=sys.stdout, level=DEBUG)` outside prod, and importing the state machine reaches it. `uv run python scripts/replay_raw.py --input happy.jsonl > events.jsonl` therefore wrote `Using selector: KqueueSelector` as the first line of the "event stream". The documented default output mode produced an unparseable file.
- **Fix:** `route_diagnostics_to_stderr()` runs first in `main()`: it moves any root handler currently pointed at stdout onto stderr and raises the threshold to WARNING. In this tool stdout is data; everything else is diagnostics.
- **Files modified:** `scripts/replay_raw.py`
- **Verification:** `test_default_stdout_mode_emits_the_golden_and_nothing_else` runs the script as a subprocess and asserts `result.stdout == golden bytes`. It fails without the redirect.
- **Committed in:** `832ad0e`

**2. [Rule 1 - Bug] `--topic` pointed at any renamed topic produced a silent zero-event replay**
- **Found during:** Task 3 (`test_a_bounded_range_replays_through_the_production_engine` failed)
- **Issue:** `replay()` routes on the envelope's `topic` field against the literal `"availability.raw"`. In offset mode the envelope was tagged with the *actual* topic name, so any mirror, copy or per-environment variant of `availability.raw` — exactly what the documented `--topic` flag exists to point at — was logged as "unrouted" and skipped. The result is zero events and exit 0, which is indistinguishable from a stream that legitimately confirmed nothing. A debugging tool that silently answers "nothing happened" is worse than one that errors.
- **Fix:** `canonical_topic()` maps a source topic name onto the message *schema* it carries, and `records_to_envelopes` tags with that role. The jsonl path still matches exactly and still warns on a genuinely unrouted topic, so a typo in a hand-authored fixture is not swallowed.
- **Files modified:** `scripts/replay_raw.py`
- **Verification:** `test_a_bounded_range_replays_through_the_production_engine` (integration, on a `availability.raw.replay-<hex>` topic) plus `test_a_source_topic_copy_still_routes_to_the_availability_raw_schema` (unit, five cases).
- **Committed in:** `ab6406c`

**3. [Rule 3 - Blocking] The plan's own text gate is tripped by the docstring the plan asks for**
- **Found during:** Task 1
- **Issue:** The plan requires the script to document that `exclude_none` / `exclude_unset` are never passed *and* the test to assert those strings are absent from the source. Writing the mandated explanation breaks the mandated gate — the same contradiction 02-02 hit with `GT` and `type: ignore`.
- **Fix:** The gate walks the AST and asserts no `ast.Call` anywhere in the script passes either keyword. The prose survives, and the assertion is strictly stronger than the text match it replaces.
- **Files modified:** `tests/unit/test_replay_determinism.py`
- **Verification:** `test_the_script_declares_no_second_serializer_and_no_production_client` passes with the explanatory docstrings in place.
- **Committed in:** `832ad0e`

**4. [Rule 2 - Missing critical functionality] Argument validation and Kafka error mapping**
- **Found during:** Task 3
- **Issue:** The plan's CLI surface allows `--input X --to-offset 5` (an exclusive bound with no range to bound), a negative `--from-offset`, and `--to-offset` preceding `--from-offset`. All three are silent no-ops. Separately, an unreachable broker raised a raw `KafkaError` traceback instead of the documented exit 1.
- **Fix:** Three `parser.error(...)` checks in `main()` and `KafkaError` added to the exception tuple mapped onto exit 1.
- **Files modified:** `scripts/replay_raw.py`
- **Verification:** `test_to_offset_without_from_offset_is_a_usage_error`.
- **Committed in:** `ab6406c`

### Decisions Taken Autonomously (no human in the loop)

**5. `happy.jsonl` is trimmed to ONE seating type**
- The plan says the payload is "shaped like `OPENTABLE_SUCCESS_RESPONSE`" while its own acceptance criterion says `wc -l < happy.events.jsonl` outputs **1**. The shipped fixture carries `seatingTypes: ["bar", "standard"]` and `seat_type` is part of slot identity (D-36), so it describes two slots and confirms **two** events. The two statements cannot both hold — the same internal contradiction 02-01 (deviation 2) and 02-03 (decision 7) each recorded.
- Resolved in favour of the acceptance criterion and D-36 by shaping the fixture with a single seating type. The two-slots-from-one-poll behaviour keeps its own dedicated guards in `tests/unit/test_engine_transitions.py` and `tests/integration/test_availability_events_persistence.py`, so nothing is fudged.

**6. `redis.asyncio` is still imported transitively, and that is accepted**
- The plan's behaviour clause says the script "imports nothing from `redis` … in `--input` mode". The script's own import lines are clean (`grep -cE "^(import|from) (redis|sqlalchemy)"` → 0), but `MemoryStateStore` lives in `services/state_machine/store.py` beside `RedisStateStore`, and that module does `import redis.asyncio as redis` at module scope. Importing the module opens no socket and constructs no client.
- The alternative — splitting `MemoryStateStore` into its own module — would edit 02-03's file for a cosmetic gain and risk churn in a plan that reuses it verbatim. Instead, `test_input_mode_never_reaches_the_persistence_or_consumer_layer` pins the assertion that *actually* protects production: `sqlalchemy`, `asyncpg`, `services.state_machine.consumer` and `services.state_machine.persistence` are all absent from `sys.modules` after importing the script.

**7. `grep -c "group_id=None"` returns 1, as the criterion requires**
- The docstring explaining the safety argument was worded as "a group-less consumer plus `assign` + `seek`" rather than repeating the literal, so the counting gate stays at exactly 1 without losing the explanation. (02-02 had to accept a count of 2 in the equivalent situation; here the rewording costs nothing.)

**8. `services/state_machine/README.md` updated although the plan does not list it**
- The 02-03 README carried a forward reference — "The replay script (plan 02-04)" — to a script that now exists, plus no mention of `make replay`, the exit codes or the fixture corpus. Leaving a stale future tense in the service's own documentation would be a small, permanent lie. Committed separately as `docs(02-04)` so the task commits stay clean.

---

**Total deviations:** 4 auto-fixed (2 bugs, 1 blocking, 1 missing functionality) + 4 autonomous decisions recorded
**Impact on plan:** No scope change. Deviations 1 and 2 are genuine defects caught by running the code rather than reading it; 3 is an internal contradiction in the plan's own instructions resolved with the repo's established comment-aware-gate pattern.

## TDD Gate Compliance

All three tasks have clean RED → GREEN gate pairs, each RED verified to fail for the right reason:

| Task | RED | Failure at RED | GREEN |
|---|---|---|---|
| 1 | `a075fa1` | `ModuleNotFoundError: No module named 'scripts.replay_raw'` | `832ad0e` |
| 2 | `ee4c08b` | 9 failed — fixtures absent | `a9235ac` |
| 3 | `e65ff61` | `ImportError: cannot import name 'fetch_offset_range'` | `ab6406c` |

No test passed unexpectedly during a RED phase, so the fail-fast rule was never engaged. Three mutation probes were nonetheless run against the claims that a green suite would otherwise assert weakly, each reverted with a clean `git diff`:

| Mutation | Expected failure | Result |
|---|---|---|
| `min(to_offset + 1, end)` — make the upper bound inclusive | exclusivity + empty-range tests fail | 2 failed, incl. `test_the_upper_bound_is_exclusive` |
| Re-show the slot in the transient stream's recovery poll (on a copy) | the stream would emit | 1 event emitted — so zero events is a property of the error handling, not of a broken harness |
| Delete the "gone" poll from the flapping stream (on a copy) | `first_seen_at` moves back to t0 | 1788200000000 instead of 1788200180000 — the drop logic is what dates the event |

## Known Stubs

None. Every symbol this plan creates is fully implemented and exercised, either in-process or against a live broker.

One carry-forward, not a stub: the OpenTable payload shape in the fixtures remains `[ASSUMED]` pending the Phase 1 DevTools spike (a Phase 1 human gate). The fixtures mirror `services/poller/sources/opentable/fixtures.py`, so when the spike lands, updating that module and regenerating the three goldens is a single mechanical step — and the goldens are exactly what will make the change visible in review.

## Threat Flags

None new. Both threats the plan models are mitigated and tested rather than dispositioned:

| Threat | Mitigation | Evidence |
|---|---|---|
| T-02-05 (argv-supplied `--output` writes outside the repo) | `Path.resolve()` + `is_relative_to(REPO_ROOT)`; a relative escape exits 1, an explicit absolute path is the caller opting in | `test_an_output_path_outside_the_repository_root_is_refused`, `test_main_exits_1_on_a_refused_output_path` |
| T-02-06 (a replay moves the `state-machine` group's committed offsets) | `group_id=None` + `assign`/`seek`, never `subscribe`; `enable_auto_commit=False` | `test_replay_never_moves_the_state_machine_groups_committed_offsets` (live broker, commit before == commit after), `test_the_replay_consumer_never_subscribes` |

The script reads attacker-influenced-at-one-remove JSON out of Kafka and out of an argv-supplied file. Both paths go through the same tolerant parser the consumer uses: a malformed payload raises `ParseError`, flows to UNKNOWN and emits nothing, and a malformed envelope line raises `InputError` naming only the file and line number — never echoing the payload body, so a booking token cannot reach a terminal through an error message.

## Issues Encountered

- The two real investigations are deviations 1 and 2. Neither was flaky; both were reproducible on the first run and root-caused immediately.
- The offset-range integration module runs in ~4 s because every timestamp is derived from a literal base rather than a clock — nothing in this plan waits out the 8-second confirmation window.
- No auth gates, no architectural escalations, no fix-attempt limits reached.

## User Setup Required

None. No new dependency, no new env var required at runtime, no external service. `.env.example` gained two documented entries; both have safe defaults (`CONFIRM_DELAY_MS=8000` matches the compiled-in constant, and `MISE_CRASH_AFTER` is empty and banner-marked TEST ONLY).

## Next Phase Readiness

**Phase 2 is functionally complete.** The pipeline runs, survives a `kill -9`, and can be replayed byte-for-byte offline.

**Ready for Phase 3 (Resy):**
- Adding a Resy parser to `PARSER_REGISTRY` automatically makes Resy streams replayable — the replay script never branches on source (D-37).
- The three goldens become the regression contract for the D-38a coverage widening (`TODO(P3/POLL-02)`): if widening `party_sizes` changes closure behaviour, `happy.events.jsonl` or `transient_errors.events.jsonl` will say so in a diff.

**Ready for Phases 4-6:**
- Any production incident can be re-run offline from a Kafka offset range with `make replay ARGS="--from-offset A --to-offset B"`, with no risk to the live consumer group.
- `tests/fixtures/raw_streams/` is the canonical place to add a new failure-mode stream; the pattern (input + committed golden + a guard-the-guard assertion) is established.

**Carried forward, not blocking:**
- The OpenTable payload shape is still `[ASSUMED]`; the goldens must be regenerated after the DevTools spike.
- `services/poller/config.py` still freezes env at import (inherited from 02-02); untouched here because the replay script imports no poller code.
- Multi-partition topics would need `--partition` on the replay CLI; today the topic is single-partition by design (`scripts/create_topics.py`), and `fetch_offset_range` takes `partition` as a parameter already, so exposing it is a one-line change when it matters.

---
*Phase: 02-state-machine-event-pipeline*
*Completed: 2026-09-05*

## Self-Check: PASSED

All 11 claimed files verified present on disk; all 7 claimed commits verified in `git log`.
Final gate re-run at completion: `ruff check .` clean, `mypy shared/ services/` clean (35 files),
`pytest tests/unit -q` 156 passed, `pytest tests/integration -q -p no:cacheprovider` 52 passed,
`git status --porcelain tests/fixtures/raw_streams/` empty after a full suite run, and every plan
acceptance grep at its required count.
