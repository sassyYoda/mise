---
phase: 02-state-machine-event-pipeline
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - shared/events.py
  - services/state_machine/__init__.py
  - services/state_machine/models.py
  - services/state_machine/engine.py
  - services/state_machine/store.py
  - services/state_machine/parsers/__init__.py
  - services/state_machine/parsers/errors.py
  - services/state_machine/parsers/opentable.py
  - tests/unit/factories.py
  - tests/unit/test_tracer_raw_to_event.py
  - tests/unit/test_engine_transitions.py
  - tests/unit/test_coverage_bounding.py
  - tests/unit/test_engine_tristate_unknown.py
  - tests/unit/test_parsers_opentable.py
  - tests/unit/test_event_id_determinism.py
  - tests/unit/test_engine_purity.py
  - tests/unit/test_events_schema.py
autonomous: true
requirements: [STATE-02, STATE-04, STATE-06]

estimate:
  tokens: 34000
  raw_tokens: 34000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Two `availability.raw` OpenTable polls of the same slot, 9000 ms apart by `polled_at_epoch_ms`, produce exactly one `AvailabilityEvent` through `DiffEngine` + `MemoryStateStore` (D-41, D-44; STATE-02)."
    - "A first sighting of a slot produces an `Expedite` decision and NO event — `PENDING` never emits (D-41; STATE-03 half, the effect side lands in 02-02/02-03)."
    - "A slot that is absent on the next successful covered poll while still `PENDING` is dropped with no event — this is the false-positive guard (D-41; ROADMAP SC1)."
    - "`event_id` is `uuid5(NAMESPACE_MISE, '{source}:{rid}:{date}:{party}:{slot_key}:{first_poll_id}')` and is byte-identical across processes and repeated construction (D-45, D-54; STATE-04)."
    - "A parser failure (missing `data`, GraphQL `errors` array, empty dict, non-dict payload) raises `ParseError`, marks the restaurant meta UNKNOWN, removes nothing, and emits nothing (D-39; ROADMAP SC1)."
    - "`source='resy'` raises `UnsupportedSourceError` and is treated as UNKNOWN until Phase 3 registers a parser (D-37)."
    - "Coverage is the effective party size only — a poll declaring `party_sizes=[2,4]` closes and drops nothing for party 4 (D-38a / research B-4; STATE-02)."
    - "An UNKNOWN mark is monotonic in `polled_at_epoch_ms`: an older error observation never overrides a newer success (D-53; research Pitfall 2)."
    - "adjacency (STATE-01/STATE-04): two slots in one poll whose `(time_slot, seat_type)` are equal collapse to one `slot_key` field (last parsed wins, deterministically); two slots differing only in `seat_type` remain two separate fields and two separate `event_id`s."
    - "empty (STATE-01/STATE-04): a well-formed poll carrying zero slots for a covered `(date, party)` is a valid observation that closes covered slots and produces no `Emit`; a restaurant with no prior state and zero slots yields an empty decision list."
    - "ordering (STATE-01/STATE-04/STATE-06): `DiffEngine.process` returns decisions sorted by `(date, party_size, slot_key)`, so equal-comparing slots have a specified, stable output order and replay line order is reproducible."
    - statement: "Under a Kafka group rebalance mid-message the `CommitFailedError` path is caught, logged, and left to redelivery, where the Layer-1 claim plus AVAILABLE hash state makes reprocessing a no-op (research Pitfall 4)."
      verification: backstop
  prohibitions:
    - "Must not emit an `availability.events` message for a slot that was not observed by two independent successful covered polls at least `confirm_delay_ms` apart — a notification for a table that was never really open is worse than a missed one."
  artifacts:
    - path: "shared/events.py"
      provides: "AvailabilityEvent wire schema, NAMESPACE_MISE, make_event_id (D-45, D-54)"
      contains: "class AvailabilityEvent(BaseModel)"
    - path: "services/state_machine/models.py"
      provides: "Slot, ParsedPoll, SlotState, SlotRecord, MetaRecord, Expedite/Emit/Close decisions (D-36, D-37, D-41)"
      contains: "class SlotState"
    - path: "services/state_machine/engine.py"
      provides: "StateStore Protocol + pure DiffEngine (D-49)"
      contains: "class DiffEngine"
    - path: "services/state_machine/store.py"
      provides: "MemoryStateStore for replay and unit tests (D-49)"
      contains: "class MemoryStateStore"
    - path: "services/state_machine/parsers/opentable.py"
      provides: "parse_opentable + effective_coverage (D-37, D-38a)"
      contains: "def effective_coverage"
    - path: "tests/unit/factories.py"
      provides: "make_raw / make_parsed builders with explicit polled_at_epoch_ms (no wall clock in tests)"
      exports: ["make_raw", "make_parsed", "make_slot"]
  key_links:
    - from: "services/state_machine/engine.py"
      to: "services/state_machine/models.py"
      via: "DiffEngine.process consumes ParsedPoll and returns Decision dataclasses"
      pattern: "from services\\.state_machine\\.models import"
    - from: "services/state_machine/engine.py"
      to: "shared/events.py"
      via: "Emit decision carries a fully-built AvailabilityEvent built with make_event_id"
      pattern: "make_event_id"
    - from: "services/state_machine/parsers/__init__.py"
      to: "services/state_machine/parsers/opentable.py"
      via: "PARSER_REGISTRY dispatch on raw.source — the engine never branches on source (D-37)"
      pattern: "PARSER_REGISTRY"
---

<objective>
Build the pure, I/O-free heart of the state machine: the `AvailabilityEvent` wire contract, the
OpenTable parser, and the tri-state `DiffEngine` running against an in-memory `StateStore`. This is
the phase's tracer — raw OpenTable JSON in, a confirmed `AvailabilityEvent` out, proven by a unit
test that never touches Redis, Kafka, Postgres, the network, or the wall clock.

Purpose: everything downstream (the Kafka consumer shell in 02-03, the replay tool in 02-04) reuses
this exact core unchanged. Determinism proven here is what makes byte-identical replay (STATE-06)
achievable at all — if the engine did I/O or read the clock, replay could not be proven in CI.
Output: `shared/events.py` extensions, `services/state_machine/{models,engine,store,parsers}`,
and 8 unit test files that run in milliseconds.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/02-state-machine-event-pipeline/02-CONTEXT.md
@.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md
@.planning/phases/02-state-machine-event-pipeline/02-PATTERNS.md
@shared/events.py
@services/poller/sources/opentable/fixtures.py
@services/poller/scheduler.py
@tests/unit/test_events_schema.py
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end "raw OpenTable poll becomes a confirmed AvailabilityEvent" — one path only</name>

  <read_first>
shared/events.py (AvailabilityRaw declaration style, ConfigDict, to_bytes — copy verbatim shape);
services/poller/sources/opentable/fixtures.py (OPENTABLE_SUCCESS_RESPONSE — the exact payload the
parser must walk); services/poller/scheduler.py lines 78-83 (the `request_params` dict the parser
receives); services/poller/sources/opentable/graphql.py lines 40-50 (proof that only
`party_sizes[0]` is sent); .planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md
§Pattern 1, §Pattern 2, §Pattern 7 and §Blocking Corrections B-4;
.planning/phases/02-state-machine-event-pipeline/02-PATTERNS.md §`shared/events.py`,
§`services/state_machine/parsers/`, §Module header docstring; tests/unit/test_events_schema.py
(existing assertion idioms).
  </read_first>

  <files>shared/events.py, services/state_machine/__init__.py, services/state_machine/models.py, services/state_machine/parsers/errors.py, services/state_machine/parsers/opentable.py, services/state_machine/parsers/__init__.py, services/state_machine/engine.py, services/state_machine/store.py, tests/unit/factories.py, tests/unit/test_tracer_raw_to_event.py</files>

  <behavior>
    - Test 1 (the tracer): build two `AvailabilityRaw` messages from `OPENTABLE_SUCCESS_RESPONSE` for rid 42, date 2026-05-01, `request_params={"rid":42,"dates":["2026-05-01"],"party_sizes":[2,4]}`, with `polled_at_epoch_ms` 1788000000000 and 1788000009000 (9000 ms apart). Feed both through `parse_raw` then `DiffEngine(MemoryStateStore(), confirm_delay_ms=8000).process(...)`. First call returns exactly one `Expedite` and zero `Emit`. Second call returns exactly one `Emit` and zero `Expedite`.
    - Test 2: the emitted `AvailabilityEvent` has `event_type == "slot_opened"`, `source == "opentable"`, `restaurant_id == 42`, `date == "2026-05-01"`, `time_slot == "19:00"`, `party_size == 2`, `seat_type == "bar"`, `booking_token == "abc123-reservation-token"`, `first_seen_at_epoch_ms == 1788000000000`, `confirmed_at_epoch_ms == 1788000009000`, `produced_at_epoch_ms == 1788000009000`, and `confirming_poll_id` equal to the second message's `poll_id`.
    - Test 3: `event.to_bytes()` is byte-identical when the same event is rebuilt from a field dict in reversed key order (declaration order is wire order).
    - Test 4: running the identical two-message sequence a second time against a fresh `MemoryStateStore` produces an `AvailabilityEvent` with the same `event_id` and the same `to_bytes()` output.
  </behavior>

  <action>
Write the failing tracer test first, then implement until green.

In `shared/events.py`: add `NAMESPACE_MISE: Final[UUID] = UUID("629d45e6-9621-5f62-a1ea-dd826ede29f8")`
with a docstring stating it must NEVER change because every historical `event_id` derives from it
(D-54); add `make_event_id(source: str, restaurant_id: int, date: str, party_size: int, slot_key: str,
first_poll_id: str) -> UUID` returning `uuid5(NAMESPACE_MISE, f"{source}:{restaurant_id}:{date}:{party_size}:{slot_key}:{first_poll_id}")`
(D-45); add `class AvailabilityEvent(BaseModel)` with `model_config = ConfigDict(frozen=True,
extra="forbid")` and fields declared in exactly this order, because declaration order is the JSON wire
order that byte-identical replay depends on: `event_id: UUID`, `event_type: Literal["slot_opened"]`,
`source: Literal["opentable", "resy"]`, `restaurant_id: int`, `date: str`, `time_slot: str`,
`party_size: int`, `seat_type: str | None`, `booking_token: str | None`,
`first_seen_at_epoch_ms: int`, `confirmed_at_epoch_ms: int`, `produced_at_epoch_ms: int`,
`confirming_poll_id: UUID`; plus `to_bytes()` mirroring `AvailabilityRaw.to_bytes` exactly. Use `str`
for `date` and `time_slot` (never `datetime`) so no timezone renderer can perturb the bytes. The class
docstring must state that `restaurant_id` is the platform id (OpenTable rid / Resy venue id) and that
the complete join key against `restaurants` is `(source, platform_id)` (D-52), and that the model
carries no wall-clock field by design (D-45). Update the `Named symbols:` line in the module header.

In `services/state_machine/models.py`: `SlotState(str, Enum)` with members `PENDING`, `AVAILABLE`,
`UNAVAILABLE`, `UNKNOWN` (D-41); frozen slotted dataclasses `Slot(date: str, party_size: int,
time_slot: str, seat_type: str | None, booking_token: str | None)` with a `slot_key` property
returning `f"{self.time_slot}|{self.seat_type or '-'}"` (D-36); `ParsedPoll(restaurant_id: int,
source: str, polled_at_epoch_ms: int, poll_id: UUID, coverage: frozenset[tuple[str, int]],
slots: tuple[Slot, ...])` (D-37); `SlotRecord(state: SlotState, token: str | None, first_seen_ms: int,
first_poll_id: str, last_seen_ms: int, confirmed_ms: int | None, event_id: str | None)` with
`to_json()` / `from_json()` using stable compact keys `s,t,f,p,l,c,e` (D-40 — abbreviations are
Claude's discretion, but they must round-trip exactly); `MetaRecord(unknown_since_ms: int | None,
last_success_ms: int | None)` (D-40); and the decision dataclasses `Expedite(source, restaurant_id)`,
`Emit(event: AvailabilityEvent, idempotency_token: str, date: str, party_size: int, slot_key: str)`,
`Close(event_id: UUID, restaurant_id: int, date: str, party_size: int, slot_key: str,
confirmed_at_epoch_ms: int, last_seen_at_epoch_ms: int)`, with `Decision = Expedite | Emit | Close`.
Also declare `DEFAULT_CONFIRM_DELAY_MS: int = 8_000` here so this module has zero imports from
`shared.redis_keys` (that module is being extended in parallel by plan 02-02 — a cross-import would
be a wave-1 race).

In `services/state_machine/parsers/errors.py`: `class ParseError(Exception)` and
`class UnsupportedSourceError(ParseError)`.

In `services/state_machine/parsers/opentable.py`: `effective_coverage(request_params: dict[str, Any])
-> frozenset[tuple[str, int]]` returning `frozenset((d, int(parties[0])) for d in dates)` and an empty
frozenset when either list is empty — carry a `# TODO(P3/POLL-02): widen to the full party_sizes list
when the adapter loops party sizes` marker and a docstring citing
`services/poller/sources/opentable/graphql.py` as the reason (D-38a, research B-4). Then
`parse_opentable(raw: AvailabilityRaw) -> ParsedPoll` that walks
`raw_response["data"]["availability"][*]["availability"][*]["timeSlots"][*]` using `.get()` chains
only — never index-assume — producing one `Slot` per `(date, seatingType)` pair for the effective
party size, with `booking_token` from the timeslot `token` field. Raise `ParseError` when
`raw_response` is not a dict, is empty, has no `data` key, has a truthy `errors` key, or when `data`
is not a mapping. A well-formed payload with an empty `availability` array is a VALID zero-slot
observation, not an error (D-39). Prefer a per-timeslot `partySize`/`covers` field if the live payload
ever carries one, falling back to the effective party size (research assumption A2). Reproduce the
`[ASSUMED]` / `TODO(spike)` honesty banner from `services/poller/sources/opentable/fixtures.py` in the
module docstring.

In `services/state_machine/parsers/__init__.py`: `PARSER_REGISTRY: dict[str, Callable[[AvailabilityRaw],
ParsedPoll]] = {"opentable": parse_opentable}` and `parse_raw(raw: AvailabilityRaw) -> ParsedPoll`
raising `UnsupportedSourceError` for any unregistered source (`resy` until Phase 3) (D-37).

In `services/state_machine/engine.py`: `class StateStore(Protocol)` with `async def get_slots(rid: int,
date: str, party: int) -> dict[str, SlotRecord]`, `put_slot(rid, date, party, key, rec) -> None`,
`drop_slot(rid, date, party, key) -> None`, `get_meta(rid) -> MetaRecord`, `put_meta(rid, meta) -> None`;
and `class DiffEngine` taking `(store: StateStore, confirm_delay_ms: int)` — `confirm_delay_ms` is a
REQUIRED argument, no default, so the engine never imports a constant from a module another wave-1
plan is editing. `async def process(self, parsed: ParsedPoll) -> list[Decision]` implements the tracer
path only for now: an unseen slot becomes `SlotRecord(state=PENDING, first_seen_ms=polled_at,
first_poll_id=str(poll_id), last_seen_ms=polled_at)` and yields one `Expedite`; a `PENDING` slot seen
again with `parsed.polled_at_epoch_ms - rec.first_seen_ms >= self.confirm_delay_ms` becomes
`AVAILABLE` and yields an `Emit` carrying an `AvailabilityEvent` whose `confirmed_at_epoch_ms` and
`produced_at_epoch_ms` are both `parsed.polled_at_epoch_ms` (never the wall clock) and whose
`event_id` comes from `make_event_id(..., first_poll_id=rec.first_poll_id)`. `Emit.idempotency_token`
is `slot.booking_token or slot.slot_key` (D-46). Return decisions sorted by
`(date, party_size, slot_key)` so output order is specified and stable. This module must contain no
clock read, no randomness, and no I/O of any kind — all state access goes through `self.store`
(D-49; the mechanical guard lands in Task 3).

In `services/state_machine/store.py`: `class MemoryStateStore` implementing `StateStore` over two
plain dicts keyed by `(rid, date, party)` and `rid`. No TTL semantics — TTL is a Redis concern and
`RedisStateStore` arrives in plan 02-03.

In `tests/unit/factories.py`: `make_raw(rid, dates, parties, response, polled_at_epoch_ms, poll_id=None,
source="opentable") -> AvailabilityRaw`, `make_slot(...) -> Slot`, and `make_parsed(...) -> ParsedPoll`.
Every builder REQUIRES an explicit `polled_at_epoch_ms` — there is no default and no clock read, so no
test can accidentally depend on real time or need a real 8-second wait.

Every new module gets `from __future__ import annotations` as the first import, a header docstring
citing its decision ids, and a `Named symbols:` line, per 02-PATTERNS.md §Module header docstring.
Keep every line at or under 120 characters and fully annotate every function for `mypy --strict`.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/unit/test_tracer_raw_to_event.py -x -q && uv run ruff check . && uv run mypy shared/ services/</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/unit/test_tracer_raw_to_event.py -x -q` exits 0 with 4 or more tests passing.
    - `uv run pytest tests/unit -q` exits 0 and reports at least 31 passing tests (27 pre-existing plus the new file).
    - `uv run ruff check . && uv run mypy shared/ services/` exits 0.
    - `grep -c "class AvailabilityEvent(BaseModel)" shared/events.py` outputs 1.
    - `grep -c "629d45e6-9621-5f62-a1ea-dd826ede29f8" shared/events.py` outputs 1.
    - `grep -c "class DiffEngine" services/state_machine/engine.py` outputs 1.
    - `grep -c "class MemoryStateStore" services/state_machine/store.py` outputs 1.
    - `grep -c "PARSER_REGISTRY" services/state_machine/parsers/__init__.py` is 1 or greater.
    - `uv run python -c "from shared.events import make_event_id as m; print(str(m('opentable',42,'2026-05-01',2,'19:00|bar','p1')))"` prints the same UUID string on two consecutive invocations.
    - Import/code-line-scoped negative gate: `grep -rhE "^(import|from) requests" services/state_machine/ | wc -l` outputs 0 and `grep -rhvE "^\s*#" services/state_machine/ --include=*.py | grep -c "time\.sleep("` outputs 0.
  </acceptance_criteria>

  <reversibility rating="one-way">
    `NAMESPACE_MISE`, the `event_id` canonical-string recipe, and the `AvailabilityEvent` field
    declaration order are permanent: every historical event id and every committed golden replay file
    derives from them. Changing any of the three later invalidates all prior events and all goldens.
  </reversibility>

  <done>
    A pure `DiffEngine` driven by `MemoryStateStore` turns two OpenTable raw polls 9000 ms apart into
    exactly one deterministic `AvailabilityEvent`, with zero I/O and zero clock reads, and the whole
    unit suite plus `ruff` and `mypy --strict` are green.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Expand the tri-state transition matrix, coverage bounding, and monotonic UNKNOWN</name>

  <read_first>
services/state_machine/engine.py and services/state_machine/models.py as written in Task 1;
.planning/phases/02-state-machine-event-pipeline/02-CONTEXT.md D-38, D-38a, D-39, D-41, D-53;
.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md §Pattern 2, §Pitfall 1, §Pitfall 2,
§Pitfall 10; tests/unit/factories.py.
  </read_first>

  <files>services/state_machine/engine.py, services/state_machine/models.py, tests/unit/test_engine_transitions.py, tests/unit/test_coverage_bounding.py, tests/unit/test_engine_tristate_unknown.py</files>

  <behavior>
    - PENDING dropped: slot seen once, then absent on the next successful covered poll → the record is removed, zero decisions, zero events (the ROADMAP SC1 false-positive guard).
    - Confirmation window: a second poll only 3000 ms after the first (below `confirm_delay_ms`) does NOT confirm — the slot stays PENDING and a second `Expedite` is issued (D-44).
    - AVAILABLE to UNAVAILABLE: a confirmed slot absent on the next successful covered poll yields exactly one `Close` carrying the original `event_id` and `confirmed_at_epoch_ms`, plus `last_seen_at_epoch_ms` equal to the closing poll's `polled_at_epoch_ms`.
    - Re-open: after a `Close`, the same `(date, party, slot_key)` reappearing starts a fresh cycle whose eventual `event_id` differs from the first because `first_poll_id` differs.
    - Coverage bounding: a poll with `request_params={"dates":["2026-05-01"],"party_sizes":[2,4]}` never closes and never drops a stored party-4 slot, and never closes a party-2 slot for `2026-05-02` (out-of-window date).
    - Empty edge: a well-formed poll with zero slots for a covered `(date, party)` closes covered AVAILABLE slots and drops covered PENDING slots; with no prior state it returns an empty decision list.
    - Adjacency edge: two timeslots in one payload with identical `time` and identical seating type collapse to one hash field; two identical times with different seating types stay two records with two distinct `event_id`s.
    - Ordering edge: for a payload containing several slots the returned decision list is sorted by `(date, party_size, slot_key)` and is identical across repeated runs.
    - Monotonic UNKNOWN: `mark_unknown(rid, polled_at_epoch_ms)` sets `meta.unknown_since_ms` only when `polled_at_epoch_ms > meta.last_success_ms`; a successful poll sets `last_success_ms` and clears `unknown_since_ms`. Applying an older error after a newer success is a no-op, so the outcome is order-independent.
    - Errors never advance a slot toward UNAVAILABLE: an UNKNOWN mark leaves every stored `SlotRecord` untouched.
  </behavior>

  <action>
Extend `DiffEngine.process` to the full D-41 transition table. Compute
`covered = parsed.coverage` once; build `seen: dict[str, Slot]` from `parsed.slots` grouped by
`(date, party_size)`. For each stored `(date, party)` bucket whose pair is in `covered`, any stored
record absent from `seen` is handled by state: `PENDING` → `store.drop_slot` and no decision;
`AVAILABLE` → `store.put_slot` with `state=UNAVAILABLE` and `last_seen_ms=parsed.polled_at_epoch_ms`
plus one `Close` decision carrying the stored `event_id` and `confirmed_ms`; `UNAVAILABLE` → no-op.
Buckets whose `(date, party)` is NOT in `covered` are never iterated for closure (D-38) — that
guard is what stops every party-4 slot being closed on every poll (research B-4). A slot that is
present and stored as `UNAVAILABLE` starts a brand-new cycle: overwrite with a fresh `PENDING`
record whose `first_poll_id` is the current poll id, so the eventual `event_id` differs from the
previous cycle's (D-41). Errors must never move a slot toward `UNAVAILABLE`.

Add `async def mark_unknown(self, restaurant_id: int, polled_at_epoch_ms: int) -> None` and
`async def mark_success(self, restaurant_id: int, polled_at_epoch_ms: int) -> None` to `DiffEngine`,
both operating only through `self.store` on the `MetaRecord`. `mark_unknown` writes
`unknown_since_ms` only if `polled_at_epoch_ms` is strictly greater than the stored
`last_success_ms` (treating `None` as negative infinity); `mark_success` sets `last_success_ms` and
clears `unknown_since_ms`. `process` calls `mark_success` for every successfully parsed poll. This
monotonicity is what makes the two-topic consumer order-independent and replay reproducible
(D-53, research Pitfall 2).

Add an audit hook for the mass-closure prohibition: when a single `process` call produces more
`Close` decisions than a module-level `MASS_CLOSURE_AUDIT_THRESHOLD: int = 5`, attach that count to
the returned decision list by way of a `DiffEngine.last_close_count: int` attribute that the shell
in 02-03 logs as a distinct structlog event. Do not add heuristics that change the diff outcome —
the diff must stay deterministic (research Pitfall 10). Keep every mutation inside `self.store` and
keep the module free of clock reads and randomness.

Write the three test files with the behaviours above, driving everything through
`tests/unit/factories.py` builders with explicit `polled_at_epoch_ms` values — never a real delay,
never `freezegun`.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/unit/test_engine_transitions.py tests/unit/test_coverage_bounding.py tests/unit/test_engine_tristate_unknown.py -x -q && uv run mypy shared/ services/</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/unit -q` exits 0 with no failures and no skips.
    - `tests/unit/test_coverage_bounding.py` contains a test asserting a party-4 stored slot survives a `party_sizes=[2,4]` poll; `uv run pytest tests/unit/test_coverage_bounding.py -q` exits 0.
    - `grep -c "def mark_unknown" services/state_machine/engine.py` outputs 1 and `grep -c "def mark_success" services/state_machine/engine.py` outputs 1.
    - `grep -c "MASS_CLOSURE_AUDIT_THRESHOLD" services/state_machine/engine.py` is 1 or greater.
    - `uv run ruff check . && uv run mypy shared/ services/` exits 0.
    - Running `uv run pytest tests/unit -q` twice in a row yields identical pass counts (no order dependence).
  </acceptance_criteria>

  <reversibility rating="reversible">
    Transition-table details are internal to the engine and covered by unit tests; changing them
    later costs a test update, not a data migration.
  </reversibility>

  <done>
    Every D-41 transition, the D-38a coverage bound, and D-53 monotonic UNKNOWN are implemented and
    unit-proven, including the empty, adjacency, and ordering edge cases; no test waits on real time.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Parser failure matrix, event_id determinism, and the mechanical purity guard</name>

  <read_first>
services/state_machine/parsers/opentable.py and services/state_machine/engine.py from Tasks 1-2;
services/poller/sources/opentable/fixtures.py (all three fixture constants);
.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md §Pitfall 8 and §Pattern 7;
.planning/phases/02-state-machine-event-pipeline/02-CONTEXT.md D-39, D-45, D-54;
tests/unit/test_events_schema.py (the frozen / extra-forbid idioms to mirror).
  </read_first>

  <files>services/state_machine/parsers/opentable.py, tests/unit/test_parsers_opentable.py, tests/unit/test_event_id_determinism.py, tests/unit/test_events_schema.py, tests/unit/test_engine_purity.py</files>

  <behavior>
    - `OPENTABLE_SUCCESS_RESPONSE` parses to a `ParsedPoll` with 2 slots (one per seating type) and coverage `{("2026-05-01", 2)}`.
    - `OPENTABLE_EMPTY_RESPONSE` parses to a `ParsedPoll` with 0 slots and non-empty coverage — a valid observation, not an error (D-39).
    - `OPENTABLE_RATE_LIMIT_RESPONSE` (has `errors`, no `data`) raises `ParseError`.
    - `{}`, `{"data": None}`, `{"data": []}`, and a non-dict payload each raise `ParseError`.
    - `parse_raw` on `source="resy"` raises `UnsupportedSourceError`, and `UnsupportedSourceError` is a subclass of `ParseError` so one handler covers both.
    - `make_event_id` returns an identical UUID for identical inputs and a different UUID when only `first_poll_id` differs; the value is stable across a fresh interpreter (asserted via a subprocess invocation).
    - `AvailabilityEvent` is frozen (assignment raises) and rejects an unknown field (`extra="forbid"`); `to_bytes()` round-trips through `model_validate_json` to an equal model.
    - Purity: `services/state_machine/engine.py`, `services/state_machine/models.py`, and every file under `services/state_machine/parsers/` contain zero occurrences of the four wall-clock/randomness tokens.
  </behavior>

  <action>
Harden `parse_opentable` against every payload in the failure matrix using `.get()` chains and
explicit `isinstance` checks — a single unhandled `KeyError` would halt the whole partition
(research §Security Domain, denial-of-service row). Raise `ParseError` with a short message naming
the defect (`missing data key`, `graphql errors present`, `payload not a mapping`) and never include
the payload body in the message, so the message can be logged without leaking third-party content.

Write `tests/unit/test_parsers_opentable.py` covering the full matrix above, importing the three
fixture constants from `services/poller/sources/opentable/fixtures.py` rather than inventing new
payloads.

Write `tests/unit/test_event_id_determinism.py` asserting the uuid5 recipe is stable within the
process and across a fresh interpreter, by shelling out with `subprocess.run(["uv", "run", "python",
"-c", ...])` and comparing the printed UUID to the in-process value. Also assert that changing only
`first_poll_id` changes the id, which is what makes a re-opened slot a distinct event.

Extend `tests/unit/test_events_schema.py` with the frozen, extra-forbid, and `to_bytes` round-trip
tests for `AvailabilityEvent`, plus a byte-stability test that builds the same event from a reversed
field dict and asserts identical `to_bytes()` output (research §Pattern 7).

Write `tests/unit/test_engine_purity.py` as a source-grep guard. Define the banned-token list as a
module-level constant inside the TEST file and assert zero matches across `engine.py`, `models.py`,
and every `parsers/*.py`. This is the only mechanical guard against the flakiest failure mode in the
phase — a single clock read inside the engine makes replay byte-identity fail roughly one CI run in
twenty (research §Pitfall 8). The banned tokens are the `time` module clock call, the `datetime`
now-call, the `uuid4` constructor, and the `random` module attribute prefix.
<!-- planner-discipline-allow: time.time( -->
<!-- planner-discipline-allow: datetime.now( -->
<!-- planner-discipline-allow: uuid4( -->
<!-- planner-discipline-allow: random. -->
Strip full-line comments before counting so a future explanatory comment in a scanned module cannot
silently satisfy or break the gate.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/unit -q && uv run ruff check . && uv run mypy shared/ services/</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/unit -q` exits 0 with zero failures and zero skips.
    - `uv run pytest tests/unit/test_engine_purity.py -q` exits 0.
    - Region-scoped negative gate (code lines only): `grep -hvE "^\s*#" services/state_machine/engine.py services/state_machine/models.py services/state_machine/parsers/*.py | grep -cE "time\.time\(|datetime\.now\(|uuid4\(|random\."` outputs 0.
    - `grep -c "UnsupportedSourceError" services/state_machine/parsers/__init__.py` is 1 or greater.
    - `uv run python -c "from services.state_machine.parsers import parse_raw"` exits 0.
    - `uv run ruff check . && uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>

  <reversibility rating="reversible">
    Parser tolerance and test guards are additive; the OpenTable payload shape is still `[ASSUMED]`
    pending the Phase 1 DevTools spike and is deliberately confined to one module so the post-spike
    fix is a single-file change.
  </reversibility>

  <done>
    The parser survives every malformed-payload case as a `ParseError`, `event_id` determinism is
    proven across processes, `AvailabilityEvent` schema guarantees are asserted, and a mechanical
    grep gate keeps the engine free of wall-clock and randomness forever.
  </done>
</task>

</tasks>

<flagged_assumptions>
## Flagged Assumptions (unclassified probe edges — surfaced, not dropped)

Two edge-probe rows came back `unclassified` and are recorded here rather than silently resolved.
They are carried forward for `/gsd-verify-work` review.

| Requirement | Probe | Planner assumption | Where it is exercised |
|-------------|-------|--------------------|----------------------|
| STATE-02 | unclassified — review manually | The tri-state diff's only ambiguous axis is what an *unparseable* poll does to stored slots. Assumed answer per D-39/D-41: it marks restaurant meta UNKNOWN and touches no `SlotRecord`. If review decides an unparseable poll should also age out stale PENDING slots, that is a new decision, not a bug fix. | `tests/unit/test_engine_tristate_unknown.py` (Task 2) |
| STATE-03 | unclassified — review manually | The confirmation mechanism's ambiguous axis is what happens when a restaurant has several PENDING slots at once. Assumed answer: one expedite per restaurant per poll (the ZSET score is per-job, not per-slot), so a burst of PENDING slots produces at most one pulled-forward poll. | `Expedite` de-duplication in `DiffEngine.process` (Task 1/2); asserted end-to-end in 02-02 `tests/integration/test_expedite_lua.py` |

Canon-referral breadcrumbs (surfaced prohibitions NOT minted here): untrusted third-party JSON
handling and third-party-token log hygiene are canon input-validation / information-disclosure
concerns covered by `/gsd-secure-phase` and the existing `shared/telemetry.py` redaction list; not
minted as bespoke prohibitions.
</flagged_assumptions>

<artifacts_this_phase_produces>
## Artifacts this phase produces (this plan's share)

**New files**
- `services/state_machine/__init__.py`
- `services/state_machine/models.py`
- `services/state_machine/engine.py`
- `services/state_machine/store.py`
- `services/state_machine/parsers/__init__.py`
- `services/state_machine/parsers/errors.py`
- `services/state_machine/parsers/opentable.py`
- `tests/unit/factories.py`
- `tests/unit/test_tracer_raw_to_event.py`
- `tests/unit/test_engine_transitions.py`
- `tests/unit/test_coverage_bounding.py`
- `tests/unit/test_engine_tristate_unknown.py`
- `tests/unit/test_parsers_opentable.py`
- `tests/unit/test_event_id_determinism.py`
- `tests/unit/test_engine_purity.py`

**Modified files**
- `shared/events.py`
- `tests/unit/test_events_schema.py`

**Symbols created**

| Symbol | Kind | Module |
|--------|------|--------|
| `NAMESPACE_MISE` | module constant (`UUID`) | `shared/events.py` |
| `make_event_id(source, restaurant_id, date, party_size, slot_key, first_poll_id) -> UUID` | function | `shared/events.py` |
| `AvailabilityEvent` | pydantic model (frozen, `extra="forbid"`) | `shared/events.py` |
| `AvailabilityEvent.event_id / event_type / source / restaurant_id / date / time_slot / party_size / seat_type / booking_token / first_seen_at_epoch_ms / confirmed_at_epoch_ms / produced_at_epoch_ms / confirming_poll_id` | model fields (declaration order is wire order) | `shared/events.py` |
| `AvailabilityEvent.to_bytes() -> bytes` | method | `shared/events.py` |
| `SlotState` (`PENDING`/`AVAILABLE`/`UNAVAILABLE`/`UNKNOWN`) | str enum | `services/state_machine/models.py` |
| `Slot`, `Slot.slot_key` | frozen dataclass + property | `services/state_machine/models.py` |
| `ParsedPoll` | frozen dataclass | `services/state_machine/models.py` |
| `SlotRecord`, `SlotRecord.to_json()`, `SlotRecord.from_json()` | frozen dataclass + codecs | `services/state_machine/models.py` |
| `MetaRecord` | frozen dataclass | `services/state_machine/models.py` |
| `Expedite`, `Emit`, `Close`, `Decision` | decision dataclasses + union alias | `services/state_machine/models.py` |
| `DEFAULT_CONFIRM_DELAY_MS` | module constant (8000) | `services/state_machine/models.py` |
| `StateStore` | `typing.Protocol` | `services/state_machine/engine.py` |
| `DiffEngine`, `.process()`, `.mark_unknown()`, `.mark_success()`, `.last_close_count` | class + methods | `services/state_machine/engine.py` |
| `MASS_CLOSURE_AUDIT_THRESHOLD` | module constant (5) | `services/state_machine/engine.py` |
| `MemoryStateStore` | class implementing `StateStore` | `services/state_machine/store.py` |
| `ParseError`, `UnsupportedSourceError` | exceptions | `services/state_machine/parsers/errors.py` |
| `PARSER_REGISTRY`, `parse_raw(raw) -> ParsedPoll` | registry + dispatch | `services/state_machine/parsers/__init__.py` |
| `effective_coverage(request_params)`, `parse_opentable(raw)` | functions | `services/state_machine/parsers/opentable.py` |
| `make_raw`, `make_slot`, `make_parsed` | test builders | `tests/unit/factories.py` |
</artifacts_this_phase_produces>

<verification>
- `uv run pytest tests/unit -q` exits 0 (27 pre-existing plus roughly 30 new tests).
- `uv run ruff check . && uv run mypy shared/ services/` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` still exits 0 (12 pre-existing tests unaffected — this plan adds no integration surface).
- `grep -rhvE "^\s*#" services/state_machine/ --include=*.py | grep -cE "asyncio\.sleep\(|time\.sleep\("` outputs 0.
- The engine has zero imports from `redis`, `aiokafka`, or `sqlalchemy` (import-line-scoped):
  `grep -rhE "^(import|from) (redis|aiokafka|sqlalchemy|shared\.redis_keys)" services/state_machine/engine.py services/state_machine/models.py services/state_machine/parsers/ | wc -l` outputs 0.
</verification>

<success_criteria>
- Two raw OpenTable polls 9000 ms apart yield exactly one deterministic `AvailabilityEvent` through
  `DiffEngine` + `MemoryStateStore` (STATE-02, STATE-04).
- Transient-error and unparseable polls yield zero events and never move a slot toward UNAVAILABLE
  (ROADMAP SC1 groundwork).
- A party-2-only poll never closes or drops a party-4 slot (research B-4 regression guard).
- `event_id` is reproducible across processes and the event's JSON bytes are stable (STATE-06
  groundwork).
- The engine, models, and parsers are mechanically proven free of wall-clock and randomness.
</success_criteria>

<output>
Create `.planning/phases/02-state-machine-event-pipeline/02-01-SUMMARY.md` when done.
</output>
