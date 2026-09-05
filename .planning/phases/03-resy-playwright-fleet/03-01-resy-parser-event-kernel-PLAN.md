---
phase: 03-resy-playwright-fleet
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - services/poller/sources/resy/__init__.py
  - services/poller/sources/resy/fixtures.py
  - services/state_machine/parsers/resy.py
  - services/state_machine/parsers/__init__.py
  - services/state_machine/consumer.py
  - services/state_machine/README.md
  - shared/events.py
  - scripts/replay_raw.py
  - tests/unit/factories.py
  - tests/unit/test_tracer_resy_raw_to_event.py
  - tests/unit/test_parsers_resy.py
  - tests/unit/test_events_schema.py
  - tests/unit/test_banned_marks_unknown.py
autonomous: true
requirements: [POLL-05, POLL-06]

estimate:
  tokens: 58000
  raw_tokens: 58000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "A Resy `availability.raw` message whose `raw_response` is the D-64 request envelope produces an `availability.events` message through the Phase-2 `DiffEngine` with zero edits to `services/state_machine/engine.py` (D-66, SC5, research B-7 restatement)."
    - "`PARSER_REGISTRY` holds exactly two keys — `opentable` and `resy` — and a source-scan assertion in `tests/unit/test_tracer_resy_raw_to_event.py` proves `services/state_machine/engine.py` names no source platform (D-66, D-67a)."
    - "PROBE POLL-05/empty: `parse_resy` raises `ParseError` for a non-mapping payload, an envelope with an empty `requests` list, and an envelope whose every entry has a non-200 `status`; an envelope whose only 200 entry carries `venues: []` parses to a `ParsedPoll` with non-empty `coverage` and zero slots (a fully booked venue closes slots; a blind poll closes nothing)."
    - "PROBE POLL-05/ordering: `parse_resy` is order-stable — two parses of the same envelope produce equal `coverage` frozensets and byte-identical `slots` tuples, and two observed slots that collapse onto one `slot_key` resolve last-parsed-wins with `DiffEngine.last_collision_count` incremented rather than silently dropped (D-36)."
    - "`PollCompleted` accepts `status='banned'` and an optional `context_id`, and BOTH non-success consumers — `services/state_machine/consumer.py` and `scripts/replay_raw.py` — mark the restaurant UNKNOWN for `banned` via the single `FAILED_POLL_STATUSES` frozenset (D-67a, research B-7)."
    - "The three committed golden `.events.jsonl` files still replay byte-identical after the `shared/events.py` widening (STATE-06 regression: `uv run pytest tests/unit/test_replay_determinism.py -q` exits 0)."
    - statement: "`booking_token` is populated from `slot.config.token` and falls back to `slot.config.id` when `token` is absent, recording which field supplied it — the live `/4/find` response shape is [ASSUMED] (research A1/A2) and only a human DevTools capture can confirm it."
      verification: backstop
  artifacts:
    - services/poller/sources/resy/__init__.py
    - services/poller/sources/resy/fixtures.py
    - services/state_machine/parsers/resy.py
    - tests/unit/test_tracer_resy_raw_to_event.py
    - tests/unit/test_parsers_resy.py
    - tests/unit/test_banned_marks_unknown.py
  key_links:
    - "`PARSER_REGISTRY['resy'] -> parse_resy` — the single wiring point that lets the unchanged `DiffEngine` diff Resy (D-66); breaking it makes every Resy poll an `UnsupportedSourceError`."
    - "`shared.events.FAILED_POLL_STATUSES` -> `consumer._handle_completed` AND `scripts/replay_raw.py::_handle_completed` — one frozenset, two call sites; a divergence makes a `banned` poll silently count as a success (D-67a)."
    - "`RESY_SUCCESS_RESPONSE` (fixtures) -> `make_resy_envelope` (factory) -> `parse_resy` — one [ASSUMED] shape definition feeding every Resy test in the phase; a shape drift here fails one file, not thirty."
  prohibitions:
    - "MUST NOT disable, skip, xfail, delete, or loosen an existing passing test to make a Phase 3 gate go green; an environment guard that skips with an explicit remediation message is the only acceptable skip."
---

<objective>
Register Resy in the Phase-2 parser registry and widen the poll-completion contract so a soft ban
can never be read as a success — without touching the diff engine.

Purpose: SC5 says Resy data must be diffed by the existing State Machine with no source-specific
branching. This plan proves that end to end at the unit tier, before any browser exists, so the
riskiest architectural claim of the phase is settled on the first commit.
Output: `services/state_machine/parsers/resy.py` registered in `PARSER_REGISTRY`, `[ASSUMED]` Resy
fixtures, `banned` + `context_id` on `PollCompleted`, `FAILED_POLL_STATUSES` shared by both
non-success consumers, and a tracer test that walks a Resy envelope to an `AvailabilityEvent`.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/03-resy-playwright-fleet/03-CONTEXT.md
@.planning/phases/03-resy-playwright-fleet/03-PATTERNS.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — a Resy envelope becomes an AvailabilityEvent through the unchanged engine</name>
  <files>services/poller/sources/resy/__init__.py, services/poller/sources/resy/fixtures.py, services/state_machine/parsers/resy.py, services/state_machine/parsers/__init__.py, tests/unit/factories.py, tests/unit/test_tracer_resy_raw_to_event.py</files>
  <read_first>
    - services/state_machine/parsers/opentable.py (the exact shape to copy: docstring, `effective_coverage`, defensive `.get()` walks, ParseError matrix, terminal `ParsedPoll`)
    - services/state_machine/parsers/__init__.py (PARSER_REGISTRY, parse_raw, the docstring line that says `resy` is unregistered until Phase 3)
    - services/state_machine/models.py (Slot, ParsedPoll, Slot.slot_key)
    - services/poller/sources/opentable/fixtures.py (fixture module docstring + `TODO(spike):` marker convention)
    - tests/unit/test_tracer_raw_to_event.py (the OpenTable tracer this one mirrors)
    - tests/unit/factories.py (make_raw, deterministic_poll_id)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-64, §D-66
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Assumptions Log A1/A2, §Pitfall 10
    - .planning/phases/03-resy-playwright-fleet/03-PATTERNS.md §`services/state_machine/parsers/resy.py`, §`services/poller/sources/resy/fixtures.py`
  </read_first>
  <behavior>
    - `make_resy_envelope(dates, party_sizes, bodies, statuses)` in `tests/unit/factories.py` builds the D-64 envelope `{"requests": [{"date", "party_size", "status", "body"}, ...]}` with entries ordered `(date, party_size)` ascending and no wall-clock read.
    - `parse_resy(raw)` with `RESY_SUCCESS_RESPONSE` in a single 200 entry -> `ParsedPoll` whose `coverage == frozenset({(date, party)})` and whose slots carry `time_slot` = `HH:MM` of `slot.date.start`, `seat_type` = `slot.config.type`, `booking_token` = `slot.config.token`.
    - Two `parse_resy` calls on the same envelope produce equal `coverage` and identical `slots` tuples (order stability).
    - Poll 1 at T0 yields exactly one `Expedite` and zero `Emit`; poll 2 at T0 + 9_000 ms yields `Emit` decisions and zero `Expedite` — identical control flow to the OpenTable tracer, proving the engine did not need to change.
    - A source-scan assertion reads `services/state_machine/engine.py` and asserts it names no source platform, and that `sorted(PARSER_REGISTRY)` is exactly the two-source list.
  </behavior>
  <action>
Create the `services/poller/sources/resy/` package (zero-byte `__init__.py`, matching the OpenTable
sibling) and `fixtures.py` holding the `[ASSUMED]` `/4/find` bodies per D-66 and research §A1:
`RESY_SUCCESS_RESPONSE`, `RESY_EMPTY_VENUES_RESPONSE`, `RESY_MISSING_RESULTS_RESPONSE`,
`RESY_RATE_LIMIT_RESPONSE`, and `RESY_CHALLENGE_HTML` (a string, not a dict — the 403 body is HTML).
Carry the module docstring convention from `services/poller/sources/opentable/fixtures.py`, including
a `TODO(spike):` marker above each body pointing at `docs/runbooks/resy-cookie-capture.md`. The
success body must exercise the documented walk `results.venues[].slots[]` with
`date.start` / `date.end`, `config.type` / `config.token`, and `size.min` / `size.max`, and must
contain at least two slots with different `config.type` values so the seat-type fan-out is real.
Add one slot that carries `config.id` but no `config.token` so the A2 fallback has a fixture.

Write `services/state_machine/parsers/resy.py` implementing `parse_resy(raw: AvailabilityRaw) ->
ParsedPoll` and a module-private coverage helper. Coverage is derived from the D-64 envelope, not
from `request_params`: exactly the `(date, party_size)` pairs of the entries whose `status` is 200.
This is the structural fix for the class of defect the OpenTable parser carries as a TODO — a poll
that never observed party 4 must never report party 4 as covered. Every walk uses `.get()` chains
and `isinstance` checks; a `KeyError` escaping here would halt the Kafka partition. Raise
`ParseError` (never a bare exception) for: a non-mapping payload, a missing or non-list `requests`
key, an empty `requests` list, an envelope with zero 200 entries, and a `results` value that is
present but not a mapping. `time_slot` is the `HH:MM` prefix of `slot.date.start` taken as a string
slice — never parsed into a `datetime`, so no timezone renderer can perturb it. `booking_token`
prefers `config.token` and falls back to `config.id`, and the parser logs once per poll which field
supplied it. The module reads no clock and draws no entropy (D-49). Name the decisions it implements
in the docstring (`D-64, D-66, D-39, D-49`) and list `Named symbols:` as the repo convention requires.

Register it: `PARSER_REGISTRY["resy"] = parse_resy` in `services/state_machine/parsers/__init__.py`
and update the `parse_raw` docstring, which still claims the source is unregistered.

Extend `tests/unit/factories.py` with `make_resy_envelope(...)` and a `make_resy_raw(...)` wrapper
over `make_raw(source="resy", ...)`, both requiring an explicit `polled_at_epoch_ms`.

Write `tests/unit/test_tracer_resy_raw_to_event.py` mirroring `tests/unit/test_tracer_raw_to_event.py`:
`DiffEngine(MemoryStateStore(), confirm_delay_ms=8_000)`, two polls 9_000 ms apart, assertions on
`Expedite` then `Emit`, plus the order-stability assertion and the two source-scan assertions
described in `<behavior>`. The source scan must read `engine.py` from disk, strip full-line comments
before matching (the `tests/unit/test_no_inline_sleep.py::_code_lines` helper is the template), and
carry a non-vacuity assertion that the file it read is non-empty.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_tracer_resy_raw_to_event.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_tracer_resy_raw_to_event.py -q` exits 0.
    - `uv run pytest tests/unit -q` exits 0 (156 pre-existing unit tests stay green).
    - `git diff --stat services/state_machine/engine.py` reports no changes (the SC5 claim).
    - `uv run python -c "from services.state_machine.parsers import PARSER_REGISTRY; print(sorted(PARSER_REGISTRY))"` prints exactly `['opentable', 'resy']`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>A Resy envelope walks from `AvailabilityRaw` to `AvailabilityEvent` through the Phase-2 engine with the engine untouched, and the test proving it is committed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: `banned` is a first-class non-success status in both consumers</name>
  <files>shared/events.py, services/state_machine/consumer.py, scripts/replay_raw.py, services/state_machine/README.md, tests/unit/test_events_schema.py, tests/unit/test_banned_marks_unknown.py</files>
  <read_first>
    - shared/events.py lines 42-108 (PollCompleted field order, the `extra="forbid"` config, the `AvailabilityEvent` wire-order docstring, the `NAMESPACE_MISE` module-constant idiom)
    - services/state_machine/consumer.py lines 180-200 (`_handle_completed` and the per-emit `_flush()` ordering the Phase-2 fixer established)
    - scripts/replay_raw.py lines 100-115 (`_handle_completed`)
    - tests/unit/test_events_schema.py, tests/unit/test_replay_determinism.py
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §B-7 (the reproduced ValidationErrors and the two hard-coded tuples)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-67, §D-67a
  </read_first>
  <behavior>
    - `PollCompleted(status="banned", ...)` validates; `PollCompleted(context_id="c0", ...)` validates; an unknown status still raises `ValidationError`.
    - `FAILED_POLL_STATUSES == frozenset({"error", "timeout", "banned"})` and `"success" not in FAILED_POLL_STATUSES`.
    - `consumer._handle_completed` calls `engine.mark_unknown` for `error`, `timeout`, AND `banned`, and returns early only for `success`.
    - `scripts/replay_raw.py::_handle_completed` behaves identically for the same four statuses.
    - A hypothetical future status string that is neither `success` nor a member of the frozenset still marks UNKNOWN — the check is `!= "success"`, not a membership allowlist.
    - Replaying the three committed golden fixtures still produces byte-identical `.events.jsonl` output.
  </behavior>
  <action>
In `shared/events.py`: widen `PollCompleted.status` to `Literal["success", "error", "timeout",
"banned"]` and append `context_id: str | None = None` as the LAST field — field declaration order is
the JSON wire order the golden replay files depend on, as the `AvailabilityEvent` docstring states,
so it may only be appended. Add the module constant `FAILED_POLL_STATUSES: Final[frozenset[str]] =
frozenset({"error", "timeout", "banned"})` following the `NAMESPACE_MISE` idiom, with a docstring
naming D-67a and explaining that it exists because two separate consumers previously hard-coded the
old two-status tuple and would have treated a soft ban as a success. Add both new names to the
module's `Named symbols:` docstring list.

In `services/state_machine/consumer.py::_handle_completed`: invert the check to return early only on
`completed.status == "success"`, so every present and future non-success status reaches
`mark_unknown`. Preserve the existing per-emit `await self._flush()` placement exactly — do not batch.

In `scripts/replay_raw.py::_handle_completed`: invert the same way, importing `FAILED_POLL_STATUSES`
rather than restating a tuple.

In `services/state_machine/README.md`: record that a non-success poll status marks the restaurant
UNKNOWN, that the set of non-success statuses lives in one frozenset, and that this is a consumer-side
change which leaves the diff engine untouched (SC5 forbids source branching in the diff logic, not a
status widening in the shell).

Extend `tests/unit/test_events_schema.py` with the four validation cases in `<behavior>`, and write
`tests/unit/test_banned_marks_unknown.py` driving both consumer functions with a stub engine that
records `mark_unknown` calls, asserting the full status matrix for each of the two call sites.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_events_schema.py tests/unit/test_banned_marks_unknown.py tests/unit/test_replay_determinism.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_events_schema.py tests/unit/test_banned_marks_unknown.py tests/unit/test_replay_determinism.py -q` exits 0.
    - `uv run pytest tests/unit -q` exits 0.
    - `git diff --stat tests/fixtures/raw_streams/` reports no changes to any committed golden file.
    - `uv run python -c "from shared.events import FAILED_POLL_STATUSES as f; print(sorted(f))"` prints `['banned', 'error', 'timeout']`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>`banned` validates, both consumers mark UNKNOWN for it through one shared frozenset, and every golden replay file is still byte-identical.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Full Resy parser matrix — coverage from the envelope, ParseError for everything unusable</name>
  <files>tests/unit/test_parsers_resy.py, services/state_machine/parsers/resy.py</files>
  <read_first>
    - tests/unit/test_parsers_opentable.py (the matrix style, frozen `RID`/`DATE`/`T0` constants, fixture imports)
    - services/state_machine/parsers/resy.py (as written in Task 1)
    - services/poller/sources/resy/fixtures.py (as written in Task 1)
    - services/state_machine/parsers/opentable.py lines 23-54 (the ParseError-on-unusable-input contract for coverage)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Validation Architecture rows for POLL-05/POLL-06 (the parser matrix and the envelope guard)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pitfall 10 (an empty 200 is not distinguishable from a fully booked venue at parse time)
  </read_first>
  <behavior>
    - success envelope -> `ParsedPoll` with slots; every field mapped per D-66.
    - envelope whose only 200 entry has `venues: []` -> `ParsedPoll`, coverage non-empty, `slots == ()`.
    - envelope whose only 200 entry is missing `results` -> `ParseError`.
    - payload that is not a mapping (a list, a string, `None`) -> `ParseError`.
    - `{"requests": []}` -> `ParseError`.
    - envelope where every entry has `status` 429 or 403 -> `ParseError` (a poll that observed nothing may not be reported as an observation).
    - mixed envelope: entries `[(d0,2,200), (d1,2,429), (d2,2,200)]` -> coverage is exactly `{(d0,2), (d2,2)}`, never `{(d0,2),(d1,2),(d2,2)}`.
    - a slot whose `config` carries `id` but no `token` -> `booking_token` equals the `id` value.
    - a slot with a non-string `date.start`, a missing `config`, or a non-mapping `size` -> that one slot is skipped, the rest of the poll still parses.
    - duplicate `(time_slot, seat_type)` in one payload -> both are emitted by the parser; the engine, not the parser, resolves the collision.
  </behavior>
  <action>
Write `tests/unit/test_parsers_resy.py` covering every row in `<behavior>` as an explicit named test,
importing bodies from `services/poller/sources/resy/fixtures.py` and never inlining a payload dict.
Use frozen constants (`RID = 4242`, `DATE = "2026-05-01"`, `T0 = 1_788_000_000_000`) and the
`make_resy_envelope` / `make_resy_raw` factories so no test reads a wall clock. Assert `ParseError`
with `pytest.raises` and assert on the message substring, so a future refactor cannot satisfy the
test by raising the wrong error.

Harden `services/state_machine/parsers/resy.py` against whatever the matrix exposes: per-slot type
guards must `continue`, not raise; poll-level unusability must raise `ParseError`. Add the mixed-status
coverage rule as an explicit, commented branch — this is the D-64 property that stops a rate-limited
date from being reported as observed-and-empty, which would close every real slot on that date.
Record in the module docstring that the envelope, not `request_params`, is the coverage source, and
why.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_parsers_resy.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_parsers_resy.py -q` exits 0 with at least 10 collected tests.
    - `uv run pytest tests/unit -q` exits 0.
    - `grep -c "def test_" tests/unit/test_parsers_resy.py` returns a value &gt;= 10.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>Every documented Resy payload shape either produces a truthful `ParsedPoll` or a `ParseError`, and coverage never claims a date the poll did not actually observe.</done>
</task>

</tasks>

## Artifacts this phase produces (plan 01)

| Kind | Symbol / path | Notes |
|------|---------------|-------|
| package | `services/poller/sources/resy/` | new package, zero-byte `__init__.py` |
| module | `services/poller/sources/resy/fixtures.py` | `[ASSUMED]` bodies |
| constant | `RESY_SUCCESS_RESPONSE` | dict |
| constant | `RESY_EMPTY_VENUES_RESPONSE` | dict |
| constant | `RESY_MISSING_RESULTS_RESPONSE` | dict |
| constant | `RESY_RATE_LIMIT_RESPONSE` | dict |
| constant | `RESY_CHALLENGE_HTML` | str (HTML, not JSON) |
| module | `services/state_machine/parsers/resy.py` | new parser |
| function | `parse_resy(raw: AvailabilityRaw) -> ParsedPoll` | registered parser |
| registry entry | `PARSER_REGISTRY["resy"]` | one dict entry |
| constant | `shared.events.FAILED_POLL_STATUSES: frozenset[str]` | `{error, timeout, banned}` |
| schema field | `PollCompleted.status` gains `"banned"` | Literal widened |
| schema field | `PollCompleted.context_id: str \| None = None` | appended last (wire order) |
| test factory | `tests/unit/factories.py :: make_resy_envelope` | D-64 envelope builder |
| test factory | `tests/unit/factories.py :: make_resy_raw` | `AvailabilityRaw` with `source="resy"` |
| test | `tests/unit/test_tracer_resy_raw_to_event.py` | SC5 unit proof |
| test | `tests/unit/test_parsers_resy.py` | parser matrix |
| test | `tests/unit/test_banned_marks_unknown.py` | both consumers |

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Resy `/4/find` body -> `parse_resy` | Untrusted third-party JSON crosses into the state machine; a raise here halts a Kafka partition |
| `polls.completed` -> state machine / replay | A status string decides whether a restaurant is marked UNKNOWN or left stale |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-03-01 | Denial of Service | `services/state_machine/parsers/resy.py` | high | mitigate | Every walk uses `.get()` + `isinstance`; unusable input becomes `ParseError` (-> UNKNOWN, D-39), never an escaping `KeyError`/`TypeError` that would stall the partition. Matrix-tested in Task 3 |
| T-03-02 | Tampering | `PollCompleted.status` consumers | high | mitigate | Invert both checks to `!= "success"` and share one `FAILED_POLL_STATUSES` frozenset, so a hostile or new status cannot be silently read as a healthy poll (research B-7) |
| T-03-03 | Information Disclosure | fixture + parser logging | medium | mitigate | `booking_token` is a third-party reservation handle: the parser logs only which FIELD supplied it, never the value, and never logs `raw_response` |
| T-03-04 | Repudiation | coverage derivation | high | mitigate | Coverage comes only from status-200 envelope entries, so a rate-limited date can never be recorded as "observed and empty" and close real slots |
| T-03-SC | Tampering | npm/pip/cargo installs | low | accept | This phase installs no new packages — every library is already pinned in `uv.lock` and was audited at Phase 1 (research §Package Legitimacy Audit: zero `[ASSUMED]`, zero `[SUS]`, zero `[SLOP]`). No install task exists in this plan |
</threat_model>

## Flagged assumptions (probe, unresolved — review manually)

None in this plan. The three `unclassified` edge-probe rows for POLL-02, POLL-06 and PERF-05 are
surfaced in plans 03-02, 03-05 and 03-07 respectively; they are recorded, not dropped.

<verification>
- `uv run pytest tests/unit -q` exits 0 with a collected count strictly greater than the pre-plan 156.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `git diff --stat services/state_machine/engine.py tests/fixtures/raw_streams/` is empty.
</verification>

<success_criteria>
- A Resy `availability.raw` envelope produces an `AvailabilityEvent` through the unchanged `DiffEngine` (SC5, unit tier).
- `PARSER_REGISTRY` gained exactly one key.
- `banned` marks UNKNOWN in both the consumer and the replay script.
- The golden replay files are byte-identical.
</success_criteria>

<output>
Create `.planning/phases/03-resy-playwright-fleet/03-01-SUMMARY.md` when done.
</output>
