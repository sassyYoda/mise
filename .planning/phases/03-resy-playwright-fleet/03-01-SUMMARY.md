---
phase: 03-resy-playwright-fleet
plan: 01
subsystem: state-machine
tags: [resy, parser, registry, poll-status, coverage, tdd, sc5]
status: complete

# Dependency graph
requires:
  - phase: 02-state-machine-event-pipeline
    provides: "DiffEngine + MemoryStateStore + PARSER_REGISTRY + ParsedPoll/Slot; consumer._handle_completed; scripts/replay_raw.py and the three committed goldens"
  - phase: 01-foundation-admin-pre-conditions-opentable-polling
    provides: "AvailabilityRaw / PollCompleted wire schemas, services/poller/sources/<source>/ package + fixtures convention"
provides:
  - "services/state_machine/parsers/resy.py :: parse_resy — registered as PARSER_REGISTRY['resy'], derives coverage from the D-64 envelope"
  - "services/state_machine/parsers/resy.py :: envelope_coverage — the D-64 envelope validator, reusable by the Phase-3 adapter and canary"
  - "services/poller/sources/resy/fixtures.py — the ONE [ASSUMED] /4/find shape definition for the whole phase"
  - "shared.events.FAILED_POLL_STATUSES — the single registry of known non-success poll statuses"
  - "PollCompleted.status gains 'banned'; PollCompleted.context_id appended last"
  - "tests/unit/factories.py :: make_resy_envelope / make_resy_raw — D-64 envelope builders with per-entry status"
affects: [03-02-adapter, 03-03-pool, 03-05-canary, 04-notifier]

actuals:
  # chars/4 over the full contents of every changed source/test file (163_994 chars).
  # The same measure over the realized diff alone is ~20_200.
  tokens: 41000
  tasks: 3
  commits: 6

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Coverage derived from a per-request status envelope, not from declared request_params — a poll may only claim the (date, party_size) pairs that actually returned 200"
    - "Two-tier failure handling in a parser: poll-level unusability raises ParseError (UNKNOWN, closes nothing), per-slot defects `continue` (one bad slot may not blind a restaurant)"
    - "Time-of-day carried as an HH:MM string slice, never a parsed datetime, so no timezone renderer can perturb replayed wire bytes"
    - "Inverted status guard (`== \"success\" -> return`) instead of a failure allowlist, so a status added later is a failure by default"
    - "A source scan that matches string LITERALS of registry keys rather than prose, so a docstring naming a platform cannot trip the gate forbidding a branch on it"

key-files:
  created:
    - services/poller/sources/resy/__init__.py
    - services/poller/sources/resy/fixtures.py
    - services/state_machine/parsers/resy.py
    - tests/unit/test_tracer_resy_raw_to_event.py
    - tests/unit/test_parsers_resy.py
    - tests/unit/test_banned_marks_unknown.py
    - .planning/WINDOWS.md
  modified:
    - services/state_machine/parsers/__init__.py
    - services/state_machine/consumer.py
    - services/state_machine/README.md
    - shared/events.py
    - scripts/replay_raw.py
    - tests/unit/factories.py
    - tests/unit/test_events_schema.py
    - tests/unit/test_parsers_opentable.py

key-decisions:
  - "Slots take `date` and `party_size` from the ENVELOPE ENTRY that produced them, not from `slot.date.start` or `slot.size` — a slot in a bucket outside coverage would be opened and then never closed, because closure is bounded by coverage (D-38a)"
  - "`results.venues` must be a LIST or the poll is a ParseError. `venues: []` is a real observation (a fully booked venue); `results` with no `venues` key is a shape nobody has verified, and treating it as zero-slot would close every covered slot on unverified evidence"
  - "Per-slot type failures `continue`; only poll-level unusability raises. Raising on one malformed slot would convert a partial reading into a total blackout that recurs on every poll for as long as the venue serves that slot"
  - "The engine source scan asserts on quoted registry-key literals plus a total ban on `resy` in any casing, NOT on a case-insensitive search for every platform name — `engine.py` already carries `OpenTable` in a class docstring describing the [ASSUMED] schema, and that prose is not a source branch"
  - "Both `_handle_completed` functions branch on `== \"success\"`, not on membership in FAILED_POLL_STATUSES; the frozenset is the registry of KNOWN failures for logs and dashboards, kept in lockstep with the Literal by a schema test"
  - "`context_id` is appended as the LAST field of PollCompleted because field declaration order is the JSON wire order every historical polls.completed record encodes"

patterns-established:
  - "Pattern: every ParseError assertion in the matrix pins a message substring, so a future refactor cannot satisfy the test by raising the wrong error for the wrong reason"
  - "Pattern: a `model_construct` escape hatch reaches type guards that pydantic would otherwise make unreachable — defence in depth that is never exercised is defence nobody knows is broken"
  - "Pattern: an obsolete assertion (`resy is unsupported until Phase 3`) is rewritten to keep testing the property it was really guarding, not deleted"
  - "Pattern: the two-call-site divergence guard — one parametrized test drives BOTH consumers over the full status matrix and asserts they agree"

requirements-completed: []
requirements-advanced: [POLL-05, POLL-06]  # both left Pending — see Deviations

coverage:
  - id: T1
    description: "A Resy availability.raw message whose raw_response is the D-64 envelope produces an availability.events message through the Phase-2 DiffEngine with zero edits to engine.py (SC5)"
    requirement: POLL-05
    verification:
      - kind: unit
        ref: "tests/unit/test_tracer_resy_raw_to_event.py#test_second_poll_confirms_and_emits_without_expediting"
        status: pass
      - kind: unit
        ref: "tests/unit/test_tracer_resy_raw_to_event.py#test_confirmed_event_field_values_come_from_the_payload"
        status: pass
      - kind: command
        ref: "git diff --stat services/state_machine/engine.py -> empty"
        status: pass
    human_judgment: false
  - id: T2
    description: "PARSER_REGISTRY holds exactly opentable and resy, and a source scan proves engine.py names no source platform"
    requirement: POLL-05
    verification:
      - kind: unit
        ref: "tests/unit/test_tracer_resy_raw_to_event.py#test_parser_registry_holds_exactly_the_two_supported_sources"
        status: pass
      - kind: unit
        ref: "tests/unit/test_tracer_resy_raw_to_event.py#test_the_diff_engine_names_no_source_platform"
        status: pass
      - kind: unit
        ref: "tests/unit/test_tracer_resy_raw_to_event.py#test_engine_source_scan_is_not_vacuous"
        status: pass
    human_judgment: false
  - id: T3
    description: "PROBE POLL-05/empty — ParseError for a non-mapping payload, an empty requests list, and an envelope whose every entry is non-200; venues:[] parses to non-empty coverage and zero slots"
    requirement: POLL-05
    verification:
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_a_non_mapping_payload_raises_parse_error"
        status: pass
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_an_empty_requests_list_raises_parse_error"
        status: pass
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_an_envelope_with_no_200_entry_raises_parse_error"
        status: pass
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_empty_venues_is_a_truthful_zero_slot_observation"
        status: pass
    human_judgment: false
  - id: T4
    description: "PROBE POLL-05/ordering — parse_resy is order-stable, and two slots collapsing onto one slot_key increment DiffEngine.last_collision_count rather than being silently dropped"
    requirement: POLL-05
    verification:
      - kind: unit
        ref: "tests/unit/test_tracer_resy_raw_to_event.py#test_parse_resy_is_order_stable"
        status: pass
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_parsing_is_order_stable_across_repeated_calls"
        status: pass
      - kind: unit
        ref: "tests/unit/test_tracer_resy_raw_to_event.py#test_colliding_slots_are_counted_not_silently_dropped"
        status: pass
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_duplicate_slot_keys_are_both_emitted_for_the_engine_to_resolve"
        status: pass
    human_judgment: false
  - id: T5
    description: "PollCompleted accepts status='banned' and an optional context_id, and BOTH non-success consumers mark the restaurant UNKNOWN for banned"
    requirement: POLL-06
    verification:
      - kind: unit
        ref: "tests/unit/test_events_schema.py#test_polls_completed_accepts_banned"
        status: pass
      - kind: unit
        ref: "tests/unit/test_events_schema.py#test_polls_completed_accepts_a_context_id"
        status: pass
      - kind: unit
        ref: "tests/unit/test_banned_marks_unknown.py#test_consumer_marks_unknown_for_every_failed_status"
        status: pass
      - kind: unit
        ref: "tests/unit/test_banned_marks_unknown.py#test_replay_marks_unknown_for_every_failed_status"
        status: pass
      - kind: unit
        ref: "tests/unit/test_banned_marks_unknown.py#test_both_consumers_agree_on_every_status"
        status: pass
    human_judgment: false
  - id: T6
    description: "The three committed golden .events.jsonl files still replay byte-identical after the shared/events.py widening (STATE-06 regression)"
    requirement: POLL-06
    verification:
      - kind: unit
        ref: "tests/unit/test_replay_determinism.py (whole file)"
        status: pass
      - kind: command
        ref: "git diff --stat tests/fixtures/raw_streams/ -> empty"
        status: pass
    human_judgment: false
  - id: T7
    description: "The D-64 coverage rule — a mixed-status envelope reports only the pairs that returned 200, so a rate-limited date closes nothing"
    requirement: POLL-05
    verification:
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_coverage_holds_only_the_dates_that_actually_returned_200"
        status: pass
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_only_the_literal_integer_200_counts_as_an_observation"
        status: pass
    human_judgment: false
  - id: T8
    description: "booking_token is populated from slot.config.token and falls back to slot.config.id, recording WHICH FIELD supplied it — the live /4/find shape is [ASSUMED]"
    requirement: POLL-05
    verification:
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_booking_token_falls_back_to_config_id_when_token_is_absent"
        status: pass
      - kind: unit
        ref: "tests/unit/test_parsers_resy.py#test_an_empty_token_string_falls_through_to_config_id"
        status: pass
      - kind: backstop
        ref: "Human DevTools capture of a live /4/find response (docs/runbooks/resy-cookie-capture.md). Logged as WINDOWS.md entry 1; only a human can confirm whether config.token exists at all"
        status: pending
    human_judgment: true

metrics:
  duration_minutes: 18
  completed: 2026-09-05
  unit_tests_before: 291
  unit_tests_after: 379
  integration_tests: 62
---

# Phase 3 Plan 1: Resy Parser & Event Kernel Summary

Resy became a second *source* rather than a second *pipeline*: `parse_resy` is one entry in
`PARSER_REGISTRY`, `engine.py` is byte-for-byte unchanged, and a soft ban can no longer be read
as a healthy poll by either non-success consumer.

## What Was Built

**`services/state_machine/parsers/resy.py`** — normalises the D-64 envelope
(`{"requests": [{"date", "party_size", "status", "body"}, ...]}`) into a `ParsedPoll`. Its
defining property is that **coverage comes from the envelope, not from `request_params`**:
exactly the `(date, party_size)` pairs whose entry returned HTTP 200. This is the structural
fix for the defect class `parsers/opentable.py` still carries as a TODO — `request_params`
declares what a poll *intended* to ask, so using it makes a rate-limited date look
"observed and empty", and an observed-and-empty date closes every real slot on it.

The parser is total on its input by construction. Poll-level unusability raises `ParseError`
(→ UNKNOWN → closes nothing): a non-mapping payload, a missing/non-list/empty `requests`, an
envelope where nothing returned 200, a body that is not a mapping (the 403 challenge page is
HTML), a missing or non-mapping `results`, and a `results.venues` that is not a list. Every
*per-slot* defect `continue`s instead: a non-string `date.start`, a missing `config`, a
non-mapping `size` or `date`. One malformed slot may not blind a whole restaurant, and a raise
there would recur on every poll for as long as the venue serves that slot.

`time_slot` is an `HH:MM` string slice of `slot.date.start` — accepting `"YYYY-MM-DD HH:MM:SS"`,
an ISO `T` separator and a bare `"HH:MM:SS"` — validated against `^\d{2}:\d{2}$`. No `datetime`
is ever constructed, so no timezone renderer can perturb the wire bytes that byte-identical
replay depends on. `booking_token` prefers `config.token` and falls back to `config.id`
(research A2), and the one log line per poll names the FIELD that supplied it and never the
value (T-03-03).

**`services/poller/sources/resy/fixtures.py`** — the single `[ASSUMED]` `/4/find` shape
definition for the entire phase, each body carrying a `TODO(spike):` marker. A shape correction
after the DevTools capture is a one-file edit that fails loudly in one place.

**`shared.events`** — `PollCompleted.status` gained `"banned"`, `context_id: str | None` was
**appended last** (field declaration order is the JSON wire order every historical record
encodes), and `FAILED_POLL_STATUSES` is now the one registry of known non-success statuses.

**Both `_handle_completed` functions** — the consumer's and `scripts/replay_raw.py`'s — were
inverted from `not in ("error", "timeout")` to `== "success" -> return`.

**`tests/unit/test_tracer_resy_raw_to_event.py`** — the SC5 proof at the unit tier: two polls
9 000 ms apart, `Expedite` then `Emit`, with the same control flow as the OpenTable tracer,
plus a source scan of `engine.py` off disk.

## Key Decisions

1. **Slot `date`/`party_size` come from the envelope entry, not the slot body.** Closure is
   bounded by coverage (D-38a), so a slot in a bucket outside coverage would be opened and then
   never closed — a permanent leak. Taking both from the entry keeps every emitted slot inside a
   bucket the poll actually covered.

2. **`results.venues` must be a list.** `venues: []` is a real observation — a fully booked
   venue, which must close its slots. But `results` with no `venues` key is a shape nobody has
   verified against live Resy, and treating an unrecognised body as "zero availability" would
   close every covered slot on unverified evidence. The unrecognised case takes the recoverable
   UNKNOWN path instead. *This was the one genuine gap the Task 3 matrix exposed.*

3. **The status check is `== "success"`, not membership in `FAILED_POLL_STATUSES`.** An
   allowlist of failures is what created the B-7 bug in the first place; it would have re-created
   it one status at a time. The frozenset is the registry of *known* failures for logs and
   dashboards, and `test_failed_poll_statuses_covers_every_non_success_member_of_the_literal`
   forces it and the Literal to be edited together.

4. **The engine source scan matches string LITERALS, not prose.** `engine.py` already carries
   `OpenTable` in a class docstring describing the `[ASSUMED]` schema. A case-insensitive search
   for every platform name would fail on that comment, and "delete the docstring to pass the
   gate" is the wrong lesson. The gate matches `"<key>"` / `'<key>'` for every registry key —
   which is what a source branch is actually made of — plus B-7's stricter rule for the source
   this plan adds: no occurrence of `resy` in any casing, anywhere in the engine's code.

5. **`context_id` appended last.** Inserting it anywhere else would have rewritten the bytes of
   every historical `polls.completed` record for no benefit.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Two Phase-2 tests asserted `resy` was unregistered "until Phase 3"**
- **Found during:** Task 1 (GREEN)
- **Issue:** `tests/unit/test_parsers_opentable.py::test_resy_source_is_unsupported_until_phase_three`
  and `::test_registry_dispatches_opentable_without_the_engine_branching_on_source` asserted
  `set(PARSER_REGISTRY) == {"opentable"}`. Registering `parse_resy` — the whole point of the
  plan — necessarily broke both. A third test,
  `test_unsupported_source_error_is_a_parse_error`, went *quietly wrong*: it kept passing, but
  for a new and wrong reason (`parse_raw` now reached `parse_resy`, which raised a plain
  `ParseError` on the OpenTable body), so it no longer tested `UnsupportedSourceError` at all.
- **Fix:** Rewrote all three to keep testing the property they were really guarding. The
  dispatch-fallback tests now use `patch.dict(PARSER_REGISTRY)` to hide a *registered* key —
  `AvailabilityRaw.source` is a Literal, so an invented source name cannot reach the branch —
  and the registry test asserts the new two-key set. No test was skipped, xfailed or loosened.
- **Files modified:** `tests/unit/test_parsers_opentable.py`
- **Commit:** a8e4cea

**2. [Rule 2 - Missing critical] `results.venues` was not required to be a list**
- **Found during:** Task 3 (the matrix, working exactly as intended)
- **Issue:** A 200 whose `results` was a mapping with no `venues` key parsed as a truthful
  zero-slot observation. With coverage non-empty, that closes every stored slot in every covered
  bucket — total slot-state loss for a restaurant, triggered by a response shape nobody has
  verified against live Resy.
- **Fix:** `_results` became `_venues`, which raises `ParseError` unless `results.venues` is a
  list. Added `RESY_RESULTS_WITHOUT_VENUES_RESPONSE` so the matrix pins it.
- **Files modified:** `services/state_machine/parsers/resy.py`,
  `services/poller/sources/resy/fixtures.py`
- **Commit:** 4167fbb

### Additions beyond the plan's named artifacts

- **Four extra fixtures** (`RESY_RESULTS_NOT_A_MAPPING_RESPONSE`,
  `RESY_RESULTS_WITHOUT_VENUES_RESPONSE`, `RESY_MALFORMED_SLOTS_RESPONSE`,
  `RESY_DUPLICATE_SLOT_RESPONSE`) beyond the five the plan lists. Task 3 forbids inlining a
  payload dict in a test, and four matrix rows need bodies the five named fixtures do not
  provide. Keeping them in `fixtures.py` preserves the single-shape-definition property.
- **`envelope_coverage` is public** rather than module-private. It is the D-64 envelope
  validator, and 03-02's adapter and 03-05's canary both need it; the plan asked for "a
  module-private coverage helper", but a second copy in the adapter is exactly the two-call-site
  divergence D-67a exists to prevent.
- **`known_failure` log field** in `consumer._handle_completed` and an unrecognised-status
  warning in `replay_raw._handle_completed`. The plan's key_link wants `FAILED_POLL_STATUSES`
  flowing to both call sites, but the behaviour spec forbids using it as the branch predicate.
  These give the frozenset a real, non-vacuous use at both sites without an unused import
  (ruff F401) or the membership allowlist the spec rules out.

**3. [Rule 1 - Bug] POLL-05 / POLL-06 left Pending rather than marked complete**
- **Found during:** state update
- **Issue:** The plan frontmatter declares `requirements: [POLL-05, POLL-06]`, and
  `execute-plan` marks every frontmatter requirement complete. But REQUIREMENTS.md defines
  POLL-05 as "calls `/api/4/find` directly ... enforces <= 1 request / 45 s per restaurant per
  context and <= 80 req/min total" and POLL-06 as the response-signature canary with alerting.
  This plan built neither: there is no adapter, no rate limiter and no canary. Marking them Done
  would have made the traceability table claim a capability the codebase does not have, and the
  phase's own acceptance criteria (SC3, SC4) would then have no open requirement behind them.
- **Fix:** Both left `Pending`, following the 02-01 precedent ("Requirements STATE-02/04/06 left
  Pending — this plan ships only the pure core"). 03-02 (rate budget + 45 s floor) and 03-04/05
  (adapter + canary) close them.
- **Files modified:** none — the correction is the ABSENCE of a `requirements mark-complete` call
- **Commit:** this plan's docs commit

### Checkpoints

None. This plan is fully autonomous; no checkpoint task and no authentication gate was reached.

## Known Stubs

| File | What | Why it is intentional |
|------|------|-----------------------|
| `services/poller/sources/resy/fixtures.py` | Every `/4/find` body is `[ASSUMED]` from two independent public captures (research A1/A2), each with a `TODO(spike):` marker | No call to resy.com is permitted in this phase (CONTEXT.md domain boundary). The assumption is confined to ONE module by design, and `parse_resy` accepts both `config.token` and `config.id` precisely because the captures disagree. A human DevTools capture (`docs/runbooks/resy-cookie-capture.md`, human-gated) must confirm the shape before Resy polls production. Recorded as `.planning/WINDOWS.md` entry 1. |

No stub blocks this plan's goal: SC5 is proven end to end at the unit tier against the assumed
shape, and a shape correction changes one fixtures module plus the field-mapping assertions.

## Threat Flags

None. Every file this plan touched is covered by the plan's own `<threat_model>`; no new network
endpoint, auth path, file access pattern or schema change at a trust boundary was introduced
beyond the `PollCompleted` widening the register already names (T-03-02).

## Verification

| Gate | Result |
|------|--------|
| `uv run ruff check .` | pass |
| `uv run mypy shared/ services/ scripts/` | pass (44 source files) |
| `uv run pytest tests/unit -q` | 379 passed (was 291; +88) |
| `uv run pytest tests/integration -q -p no:cacheprovider` | 62 passed |
| `git diff --stat services/state_machine/engine.py` | empty (SC5) |
| `git diff --stat tests/fixtures/raw_streams/` | empty (STATE-06) |
| `sorted(PARSER_REGISTRY)` | `['opentable', 'resy']` |
| `sorted(FAILED_POLL_STATUSES)` | `['banned', 'error', 'timeout']` |
| `grep -c "def test_" tests/unit/test_parsers_resy.py` | 26 (>= 10 required) |

## TDD Gate Compliance

All three tasks followed RED → GREEN. Each `test(03-01)` commit was verified failing before its
`feat(03-01)` counterpart:

| Task | RED | GREEN |
|------|-----|-------|
| 1 (tracer) | 51f0e7b — `ModuleNotFoundError: services.state_machine.parsers.resy` | a8e4cea |
| 2 (banned) | 56dea37 — `ImportError: cannot import name 'FAILED_POLL_STATUSES'` | 17f711e |
| 3 (matrix) | e43a3be — `ImportError: RESY_RESULTS_WITHOUT_VENUES_RESPONSE`, then 1 behavioural failure | 4167fbb |

No REFACTOR commit was needed. The Task-1 tracer feedback gate ran autonomously: the tracer's
`<verify>` was re-run green before any expansion task began.

## Notes for Next Plan (03-02)

- `envelope_coverage` is the validator the adapter should build its envelope to satisfy; the
  adapter must emit `status` as a literal `int` (a string `"200"` is treated as non-observed by
  design) and `party_size` as a non-bool `int`.
- `PollCompleted.context_id` exists and is unused by any producer yet — 03-03's `ContextPool`
  should populate it so Grafana can attribute latency and bans per context.
- The poison-exception tuple in `consumer.handle_message` was NOT touched: `ParseError` is
  already in it, so a `ParseError` from `parse_resy` is treated as poison (log, drop, commit)
  rather than as a transient failure that would rewind the partition forever. Any new exception
  type a Phase-3 parser or adapter can raise must be added there.
- `services/state_machine/parsers/resy.py` is the fourth file scanned by
  `tests/unit/test_no_inline_sleep.py` (`parsers/*.py` glob) — it must stay free of
  `asyncio.sleep(` and `time.sleep(`.

## Self-Check: PASSED

All eight claimed artifacts exist on disk and all six claimed commits are reachable in
`git log --all`. Verified 2026-09-05.
