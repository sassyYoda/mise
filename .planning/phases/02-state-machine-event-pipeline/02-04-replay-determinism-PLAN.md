---
phase: 02-state-machine-event-pipeline
plan: 04
type: execute
wave: 2
depends_on: ["02-01", "02-02"]
files_modified:
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
  - Makefile
  - .env.example
autonomous: true
requirements: [STATE-06]

estimate:
  tokens: 30000
  raw_tokens: 30000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Two consecutive replays of `tests/fixtures/raw_streams/happy.jsonl` produce byte-identical output, and that output is byte-identical to the committed golden `happy.events.jsonl` (D-50; ROADMAP SC2, STATE-06)."
    - "Replaying `tests/fixtures/raw_streams/transient_errors.jsonl` (timeout, 5xx, empty payload, GraphQL errors array) produces ZERO events — transient errors flow to UNKNOWN and never flip a slot to UNAVAILABLE (D-39, D-41; ROADMAP SC1)."
    - "Replaying `tests/fixtures/raw_streams/flapping.jsonl` produces exactly one event: a slot seen, gone, and seen again yields one confirmed opening, not three (D-41; STATE-02)."
    - "Replay runs the exact production `DiffEngine` over `MemoryStateStore` — no Redis, no Postgres, no Kafka consumer group, no network — so a replay can never mutate production state (D-49, D-50)."
    - "Serialisation goes through the single `AvailabilityEvent.to_bytes()` code path used by the producer; there is no second serializer, no `orjson`, and no `exclude_none` or `exclude_unset` in the replay writer (research Pitfall 7, Pattern 7)."
    - "`--to-offset` is EXCLUSIVE and defaults to the topic's `end_offsets`; a `[2, 5)` request yields offsets 2, 3 and 4 (D-55; verified in research §Pattern 5)."
    - "Offset-range mode uses `group_id=None` with `assign` + `seek`, never `subscribe`, so it cannot move the `state-machine` group's committed offsets (D-50; research §Pattern 5)."
    - "Events are de-duplicated by `event_id` before being written, so a replay whose range overlaps a prior emission still yields one line per distinct event (D-50)."
    - "`make replay ARGS=...` and `make state-machine` exist as documented Makefile targets and appear in `make help` (CONTEXT §Integration Points)."
    - "empty (STATE-06): replaying an empty input file, or a range where `--from-offset == --to-offset`, produces an empty output file and a non-crashing exit; the golden `transient_errors.events.jsonl` is itself an empty file."
    - "adjacency (STATE-06): the `[from, to)` boundary is half-open — offset `to` is never consumed, and `from == to` consumes nothing."
    - "ordering (STATE-06): output line order is the engine's decision order (sorted by `(date, party_size, slot_key)`) within each message and input order across messages, so line order is fully specified and reproducible."
  prohibitions:
    - "Must not let `scripts/replay_raw.py` mutate any production state: it must never join or commit to a Kafka consumer group, never open a Redis or Postgres connection, and never write an output file outside the repository root unless an explicit absolute path is given — replay is read-only by construction, and a portfolio demo that silently corrupts the live pipeline is the failure this forbids."
  artifacts:
    - path: "scripts/replay_raw.py"
      provides: "offset-range and jsonl replay producing byte-identical availability.events output (STATE-06)"
      contains: "to-offset"
    - path: "tests/fixtures/raw_streams/happy.jsonl"
      provides: "two-poll confirmation stream, the SC2 byte-identity fixture"
    - path: "tests/fixtures/raw_streams/transient_errors.jsonl"
      provides: "timeout / 5xx / empty / graphql-error stream, the SC1 zero-false-events fixture"
    - path: "tests/fixtures/raw_streams/flapping.jsonl"
      provides: "seen-gone-seen stream proving one event, not three"
    - path: "tests/unit/test_replay_determinism.py"
      provides: "two-run byte-identity plus golden-file comparison (ROADMAP SC2)"
  key_links:
    - from: "scripts/replay_raw.py"
      to: "services/state_machine/engine.py"
      via: "the script instantiates the production DiffEngine over MemoryStateStore — same code path as the consumer (D-49)"
      pattern: "DiffEngine\\(|MemoryStateStore\\("
    - from: "scripts/replay_raw.py"
      to: "shared/events.py"
      via: "each output line is AvailabilityEvent.to_bytes().decode() — the single serializer (research Pitfall 7)"
      pattern: "to_bytes\\(\\)"
    - from: "tests/unit/test_replay_determinism.py"
      to: "tests/fixtures/raw_streams/happy.events.jsonl"
      via: "golden-file byte comparison"
      pattern: "happy\\.events\\.jsonl"
---

<objective>
Ship `scripts/replay_raw.py` and the golden fixture corpus that turn STATE-06 from a claim into a
proof: given a raw stream, the state machine regenerates a byte-identical `availability.events`
stream without re-polling OpenTable. The same fixtures also carry ROADMAP success criterion 1 —
the transient-error stream must yield exactly zero events.

Purpose: byte-identical replay is the portfolio artifact of this phase and the mechanical guarantee
that the diff engine is deterministic. It is also the debugging tool the rest of the project uses:
any production incident can be re-run offline from a Kafka offset range.
Output: one CLI script, six fixture files (three inputs, three committed goldens), three test files,
and the Makefile / `.env.example` wiring.
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
@.planning/phases/02-state-machine-event-pipeline/02-01-SUMMARY.md
@.planning/phases/02-state-machine-event-pipeline/02-02-SUMMARY.md
@scripts/check_poll_success.py
@scripts/create_topics.py
@Makefile
@.env.example
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end "raw.jsonl in, byte-identical events.jsonl out" — one path only</name>

  <read_first>
scripts/check_poll_success.py lines 1-32 and 63-79 (the repo's script header form: shebang, docstring
with `Usage:` plus `Or: make <target>`, an `Exit codes:` block, and the `main()` / `if __name__ ==
"__main__":` pair — reproduce it exactly); scripts/create_topics.py lines 22-27 (the
`KAFKA_BOOTSTRAP_SERVERS` env default); services/state_machine/engine.py, models.py, store.py,
parsers/__init__.py from plan 02-01; shared/events.py `AvailabilityRaw` and `AvailabilityEvent`;
.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md §Pattern 5, §Pattern 7, §Pitfall 7,
§Pitfall 8, §Security Domain (the V12 files-and-resources row about argv-supplied paths);
.planning/phases/02-state-machine-event-pipeline/02-CONTEXT.md D-49, D-50, D-55.
  </read_first>

  <files>scripts/replay_raw.py, tests/fixtures/raw_streams/happy.jsonl, tests/fixtures/raw_streams/happy.events.jsonl, tests/unit/test_replay_determinism.py</files>

  <behavior>
    - `uv run python scripts/replay_raw.py --input tests/fixtures/raw_streams/happy.jsonl --output OUT1` exits 0 and writes one line per emitted event.
    - Running the same command again into `OUT2` produces a file byte-identical to `OUT1`.
    - Both are byte-identical to the committed `tests/fixtures/raw_streams/happy.events.jsonl`.
    - Each output line parses back into an `AvailabilityEvent` via `model_validate_json` and re-serialises to the same bytes.
    - Replaying an empty input file exits 0 and writes a zero-byte output file (the empty edge).
    - The script imports nothing from `redis`, `sqlalchemy`, or `services.state_machine.consumer` in `--input` mode.
  </behavior>

  <action>
Write the failing determinism test first, then the script, then generate the golden.

Author `tests/fixtures/raw_streams/happy.jsonl` by hand as newline-delimited JSON where each line is
`{"topic": "<kafka topic>", "value": {<the message body>}}`. The tagged-envelope shape is what lets a
single fixture carry both `availability.raw` and `polls.completed` messages, which the transient-error
fixture in Task 2 needs. `happy.jsonl` holds two `availability.raw` lines for rid 42, date
2026-05-01, `request_params` `{"rid": 42, "dates": ["2026-05-01"], "party_sizes": [2, 4]}`, payload
shaped like `OPENTABLE_SUCCESS_RESPONSE`, with `polled_at_epoch_ms` 1788000000000 and 1788000009000
and two fixed `poll_id` UUID literals. Every timestamp and every UUID in every fixture is a hard-coded
literal — nothing generated at author time — because the golden files must stay reproducible forever.

Write `scripts/replay_raw.py` with the repo's script header form: shebang, a docstring opening with
`STATE-06: replay an availability.raw stream through the production DiffEngine and regenerate a
byte-identical availability.events stream`, a `Usage:` block, an `Or: make replay ARGS=...` line, and
an `Exit codes:` block (0 success, 1 usage or I/O error, 2 no messages found in the requested range).
Use `argparse` with a mutually exclusive required group of `--input FILE` and `--from-offset N`, plus
`--to-offset N`, `--topic` (default `availability.raw`), `--bootstrap`, and `--output FILE` (default
stdout). The `--to-offset` help text must state that the bound is EXCLUSIVE and defaults to the
topic's end offsets (D-55). This task implements `--input` mode only; `--from-offset` may parse and
exit 1 with a "not yet implemented" message until Task 3.

The replay core is a single generator feeding `DiffEngine(MemoryStateStore(), confirm_delay_ms=CONFIRM_DELAY_MS)`:
for each `availability.raw` envelope, validate into `AvailabilityRaw`, `parse_raw` it, and on a parse
failure call `engine.mark_unknown(...)` and continue; for each `polls.completed` envelope with status
`error` or `timeout`, call `engine.mark_unknown(...)`. Collect `Emit` decisions in order, skip any
whose `event_id` was already written (de-duplicate by `event_id`), and write
`event.to_bytes().decode() + "\n"` per line. That single serializer is mandatory: a second one
(`orjson`, `json.dumps(sort_keys=True)`, or `model_dump()` with `exclude_none`) would produce a
golden file that no longer matches the bytes the producer puts on the wire, and the byte-identity
test would then prove nothing about production (research Pitfall 7). Never pass `exclude_none` or
`exclude_unset` — they make the output depend on how the model was constructed.

Resolve `--output` with `Path(...).resolve()` and refuse to write outside the repository root unless
the caller passed an absolute path, printing a clear error and exiting 1 — the script takes a path
from argv and is a developer tool, so this is the cheap guard (research §Security Domain V12). In
`--input` mode import nothing from `redis`, `sqlalchemy`, or the consumer module; the whole point of
D-49 is that replay needs none of them. Keep the script `async`-clean and annotated; `scripts/**` is
exempt only from `ASYNC240`, so `ruff` still applies.

Generate `tests/fixtures/raw_streams/happy.events.jsonl` by running the script once and committing
the output verbatim. Then write `tests/unit/test_replay_determinism.py`: run the replay twice into
`tmp_path`, assert the two outputs are byte-equal to each other and to the committed golden, assert
each line round-trips through `AvailabilityEvent.model_validate_json` to identical bytes, and assert
the empty-input case. Invoke the script in-process by importing its replay function rather than
shelling out, so the test stays in the millisecond tier.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/unit/test_replay_determinism.py -q && uv run ruff check . && uv run mypy shared/ services/</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/unit/test_replay_determinism.py -q` exits 0.
    - `uv run python scripts/replay_raw.py --input tests/fixtures/raw_streams/happy.jsonl --output /tmp/r1.jsonl` exits 0, and `cmp /tmp/r1.jsonl tests/fixtures/raw_streams/happy.events.jsonl` exits 0.
    - Running the command twice into two files and comparing with `cmp` exits 0.
    - `wc -l < tests/fixtures/raw_streams/happy.events.jsonl` outputs 1.
    - `grep -c "to-offset" scripts/replay_raw.py` is 1 or greater and `grep -ci "exclusive" scripts/replay_raw.py` is 1 or greater.
    - Import-line-scoped negative gate: `grep -cE "^(import|from) (redis|sqlalchemy)" scripts/replay_raw.py` outputs 0.
    - Import-line-scoped negative gate: `grep -cE "^(import|from) orjson" scripts/replay_raw.py` outputs 0.
    - `uv run ruff check .` exits 0.
  </acceptance_criteria>

  <reversibility rating="one-way">
    Once `happy.events.jsonl` is committed as a golden, any later change to `NAMESPACE_MISE`, the
    `event_id` recipe, or the `AvailabilityEvent` field order invalidates it. That is the intended
    ratchet — the golden is the tripwire for accidental wire-format drift.
  </reversibility>

  <done>
    `scripts/replay_raw.py --input` regenerates a byte-identical `availability.events` stream from a
    committed raw fixture, twice in a row and matching the committed golden, using the production
    `DiffEngine` and the single production serializer, with no Redis, Postgres, or Kafka in the path.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Transient-error and flapping fixtures — the zero-false-events proof</name>

  <read_first>
scripts/replay_raw.py and tests/fixtures/raw_streams/happy.jsonl from Task 1;
services/poller/sources/opentable/fixtures.py (`OPENTABLE_EMPTY_RESPONSE`,
`OPENTABLE_RATE_LIMIT_RESPONSE` — the shapes the error fixture reuses);
shared/events.py `PollCompleted` (status literals `success` / `error` / `timeout`);
.planning/phases/02-state-machine-event-pipeline/02-CONTEXT.md D-39, D-41, D-50;
.planning/ROADMAP.md Phase 2 Success Criteria 1 and 2.
  </read_first>

  <files>tests/fixtures/raw_streams/transient_errors.jsonl, tests/fixtures/raw_streams/transient_errors.events.jsonl, tests/fixtures/raw_streams/flapping.jsonl, tests/fixtures/raw_streams/flapping.events.jsonl, tests/unit/test_replay_zero_false_events.py</files>

  <behavior>
    - `transient_errors.jsonl` replayed yields ZERO events, and `transient_errors.events.jsonl` is a zero-byte committed golden.
    - The transient-error stream contains at least four distinct failure modes: a `polls.completed` line with `status="timeout"`, a `polls.completed` line with `status="error"` and `http_status=503`, an `availability.raw` line whose payload is `OPENTABLE_RATE_LIMIT_RESPONSE` (a GraphQL `errors` array and no `data`), and an `availability.raw` line whose payload is `{}`.
    - The stream also contains a legitimate first sighting whose confirmation never arrives because the following polls all fail — proving a PENDING slot is never promoted by an error.
    - After the error burst, one successful poll arrives that omits the slot; the PENDING record is dropped and still no event is emitted.
    - `flapping.jsonl` (slot seen at t0, absent at t0+90s, seen again at t0+180s, seen again at t0+189s) replays to exactly ONE event, whose `first_seen_at_epoch_ms` is t0+180s — not t0.
    - Both fixtures are order-independent: replaying `transient_errors.jsonl` with the two `polls.completed` lines moved to the end of the file still yields zero events (the D-53 monotonic-UNKNOWN property).
  </behavior>

  <action>
Hand-author `tests/fixtures/raw_streams/transient_errors.jsonl` using the same tagged-envelope line
format as Task 1, with every `polled_at_epoch_ms` and every `poll_id` a fixed literal. Cover the four
failure modes above plus the "PENDING never promoted by an error" and "PENDING dropped on the next
clean covered poll" sequences. This file is ROADMAP Phase 2 success criterion 1 in data form: a
transient error must flow to UNKNOWN and must never flip a slot to UNAVAILABLE or promote it to
AVAILABLE.

Hand-author `tests/fixtures/raw_streams/flapping.jsonl` as the seen / gone / seen / confirmed
sequence with 90-second gaps, so the second sighting starts a fresh cycle whose `first_poll_id`
differs from the first — which is exactly why it yields a new `event_id` and why the total is one
event rather than three.

Generate both goldens by running the script and committing the output verbatim.
`transient_errors.events.jsonl` will be a zero-byte file; commit it anyway so the test compares
against an artifact rather than against an assertion about emptiness, and so a future regression that
starts emitting shows up as a diff.

Write `tests/unit/test_replay_zero_false_events.py` asserting: zero events from the transient stream;
byte-equality with the empty golden; exactly one event from the flapping stream with the expected
`first_seen_at_epoch_ms`; byte-equality with the flapping golden; and the order-independence case,
built by reading the transient fixture, reordering its `polls.completed` lines to the end in memory,
and replaying the reordered stream.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/unit/test_replay_zero_false_events.py tests/unit/test_replay_determinism.py -q</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/unit/test_replay_zero_false_events.py -q` exits 0.
    - `uv run python scripts/replay_raw.py --input tests/fixtures/raw_streams/transient_errors.jsonl --output /tmp/t.jsonl` exits 0 and `wc -c < /tmp/t.jsonl` outputs 0.
    - `wc -c < tests/fixtures/raw_streams/transient_errors.events.jsonl` outputs 0.
    - `wc -l < tests/fixtures/raw_streams/flapping.events.jsonl` outputs 1.
    - `grep -c "timeout" tests/fixtures/raw_streams/transient_errors.jsonl` is 1 or greater and `grep -c "503" tests/fixtures/raw_streams/transient_errors.jsonl` is 1 or greater.
    - `uv run python -c "import json,sys;[json.loads(l) for l in open('tests/fixtures/raw_streams/transient_errors.jsonl')]"` exits 0 (every line is valid JSON).
    - `uv run pytest tests/unit -q` exits 0.
  </acceptance_criteria>

  <reversibility rating="costly">
    The fixtures and their goldens become the phase's regression contract; changing a fixture means
    regenerating its golden and re-justifying the expected event count.
  </reversibility>

  <done>
    A simulated transient-error stream provably produces zero `availability.events`, and a flapping
    slot produces exactly one — both pinned by committed golden files rather than by assertions about
    counts alone.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Bounded offset-range replay against a live broker, plus Makefile and env wiring</name>

  <precondition>The Docker daemon is reachable (`docker info` exits 0) and `confluentinc/cp-kafka:7.6.0` resolves; without it the offset-range integration test skips and its verification is vacuous.</precondition>

  <read_first>
scripts/replay_raw.py from Tasks 1-2;
.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md §Pattern 5 in full (the verified
`group_id=None` + `assign` + `seek` + `end_offsets` recipe, including which calls are synchronous and
which are coroutines, and the verified `[2,5) -> [2,3,4]` transcript);
.planning/phases/02-state-machine-event-pipeline/02-CONTEXT.md D-50, D-55; Makefile lines 1-3 and
20-21 and 47-48 (the `.PHONY` list, the `## ` help-comment convention, and the `help` target's grep);
.env.example in full; tests/integration/conftest.py and tests/integration/test_poller_smoke.py
(container wiring).
  </read_first>

  <files>scripts/replay_raw.py, tests/integration/test_replay_offset_range.py, Makefile, .env.example</files>

  <behavior>
    - Against a live Kafka container seeded with 6 `availability.raw` messages, `--from-offset 2 --to-offset 5` consumes exactly offsets 2, 3 and 4.
    - Omitting `--to-offset` consumes through the topic's end offsets and stops rather than blocking forever.
    - `--from-offset 3 --to-offset 3` consumes nothing and exits 2 (no messages in range).
    - The replay consumer reports `group_id is None`, so no `__consumer_offsets` entry is created for it — asserted by checking that the `state-machine` group's committed offsets are unchanged after a replay.
    - `make help` lists both `state-machine` and `replay`, and `make replay ARGS="--help"` prints the usage block including the exclusive `--to-offset` note.
  </behavior>

  <action>
Implement `--from-offset` mode in `scripts/replay_raw.py` using the verified recipe from
02-RESEARCH.md §Pattern 5 exactly: construct `AIOKafkaConsumer(bootstrap_servers=..., group_id=None,
enable_auto_commit=False)`, `await consumer.start()` BEFORE `consumer.assign([tp])`, note that
`assign` and `seek` are synchronous while `beginning_offsets`, `end_offsets` and `position` are
coroutines, default `--to-offset` to the value from `end_offsets` when omitted, loop on
`await consumer.getmany(timeout_ms=2000, max_records=100)` breaking out on an empty batch so the
script never spins, and stop consuming at the first record whose offset reaches the exclusive upper
bound. `group_id=None` is not an optimisation — it is what stops a portfolio demo from moving the
production `state-machine` group's committed offsets. Never call `subscribe()`; `assign()` raises
`IllegalStateError` if it was called first. Feed the resulting records into the same generator and
the same `DiffEngine` the `--input` path uses, so both modes are one code path.

Add two Makefile targets following the existing `## ` help-comment convention and add both names to
the `.PHONY` line: `state-machine: ## Run the state machine consumer on host` running
`uv run python -m services.state_machine`, and `replay: ## Replay availability.raw through the state
machine (ARGS="--input tests/fixtures/raw_streams/happy.jsonl")` running
`uv run python scripts/replay_raw.py $(ARGS)`.

Add to `.env.example`, each with a short comment: `CONFIRM_DELAY_MS=8000` (confirmation window, D-43)
and `MISE_CRASH_AFTER=` with a `# TEST ONLY — SIGKILLs the state machine after the named stage; must
be unset in any deployed environment` banner above it.

Write `tests/integration/test_replay_offset_range.py`: seed a topic with 6 messages using a plain
producer, then assert the three range cases and the group-offset-untouched case. Use the
`tests/integration/conftest.py` helpers for container wiring and mark the module
`pytestmark = pytest.mark.integration`.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/integration/test_replay_offset_range.py -q -p no:cacheprovider && uv run pytest tests/unit -q && uv run ruff check .</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/integration/test_replay_offset_range.py -q -p no:cacheprovider` exits 0 with 0 skipped.
    - `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` exits 0 across the whole suite.
    - `make help` output contains both `state-machine` and `replay`.
    - `grep -c "^replay:" Makefile` outputs 1 and `grep -c "^state-machine:" Makefile` outputs 1.
    - `grep -c "replay" Makefile | head -1` is 1 or greater and `grep "^.PHONY" Makefile | grep -c "replay"` outputs 1.
    - `grep -c "group_id=None" scripts/replay_raw.py` outputs 1 and the call-site-scoped negative gate `grep -c "consumer.subscribe(" scripts/replay_raw.py` outputs 0.
    - `grep -c "CONFIRM_DELAY_MS" .env.example` outputs 1 and `grep -c "TEST ONLY" .env.example` is 1 or greater.
    - `uv run python scripts/replay_raw.py --help` exits 0 and its output contains the word `exclusive`.
    - `uv run ruff check .` exits 0.
  </acceptance_criteria>

  <reversibility rating="reversible">
    CLI flags, Makefile targets and env documentation; all trivially editable.
  </reversibility>

  <done>
    A bounded, half-open Kafka offset range replays through the production diff engine without
    touching the `state-machine` consumer group, and `make replay` / `make state-machine` are
    documented, discoverable targets.
  </done>
</task>

</tasks>

<threat_model>
| Boundary | Description |
|----------|-------------|
| developer argv to filesystem and Kafka | `scripts/replay_raw.py` takes file paths and broker addresses from the command line. |

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-02-05 | Tampering | `scripts/replay_raw.py` `--output` | low | mitigate | Resolve the path and refuse to write outside the repository root unless an explicit absolute path is supplied; exit 1 with a clear message. |
| T-02-06 | Tampering | `scripts/replay_raw.py` Kafka access | medium | mitigate | `group_id=None` plus `assign`/`seek` (never `subscribe`) means the tool cannot commit offsets; the integration test asserts the `state-machine` group's committed offsets are unchanged after a replay. |
</threat_model>

<artifacts_this_phase_produces>
## Artifacts this phase produces (this plan's share)

**New files**
- `scripts/replay_raw.py`
- `tests/fixtures/raw_streams/happy.jsonl`
- `tests/fixtures/raw_streams/happy.events.jsonl` (golden, 1 line)
- `tests/fixtures/raw_streams/transient_errors.jsonl`
- `tests/fixtures/raw_streams/transient_errors.events.jsonl` (golden, 0 bytes)
- `tests/fixtures/raw_streams/flapping.jsonl`
- `tests/fixtures/raw_streams/flapping.events.jsonl` (golden, 1 line)
- `tests/unit/test_replay_determinism.py`
- `tests/unit/test_replay_zero_false_events.py`
- `tests/integration/test_replay_offset_range.py`

**Modified files**
- `Makefile`
- `.env.example`

**CLI flags created (`scripts/replay_raw.py`)**

| Flag | Meaning |
|------|---------|
| `--input FILE` | Replay a tagged-envelope jsonl stream (no broker needed) — mutually exclusive with `--from-offset` |
| `--from-offset N` | Inclusive lower bound of a Kafka offset range |
| `--to-offset N` | EXCLUSIVE upper bound; defaults to the topic's `end_offsets` (D-55) |
| `--topic T` | Source topic, default `availability.raw` |
| `--bootstrap SERVERS` | Broker list, default `KAFKA_BOOTSTRAP_SERVERS` env or `localhost:9094` |
| `--output FILE` | Output path, default stdout; refused outside the repo root unless absolute |

**Exit codes:** 0 success, 1 usage or I/O error, 2 no messages found in the requested range.

**Fixture line format (tagged envelope)**
`{"topic": "availability.raw" | "polls.completed", "value": { ...message body... }}`

**Makefile targets created**
- `state-machine` — `uv run python -m services.state_machine`
- `replay` — `uv run python scripts/replay_raw.py $(ARGS)`

**Environment variables documented in `.env.example`**
- `CONFIRM_DELAY_MS=8000`
- `MISE_CRASH_AFTER=` (TEST ONLY)
</artifacts_this_phase_produces>

<verification>
- `uv run pytest tests/unit -q` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
- `uv run ruff check . && uv run mypy shared/ services/` exits 0 (the script lives in `scripts/`, which
  mypy does not scan, but `ruff` does).
- Two consecutive `make replay ARGS="--input tests/fixtures/raw_streams/happy.jsonl --output X"` runs
  produce `cmp`-identical files that also match the committed golden.
- `git status --porcelain tests/fixtures/raw_streams/` is empty after running the full suite — no test
  rewrites a golden in place.
</verification>

<success_criteria>
- Given a raw offset range or a raw jsonl fixture, `scripts/replay_raw.py` regenerates a byte-identical
  `availability.events` stream without re-polling OpenTable, proven in CI (ROADMAP SC2, STATE-06).
- The simulated transient-error stream produces zero false events (ROADMAP SC1).
- Replay cannot mutate production Kafka, Redis, or Postgres state.
- `make replay` and `make state-machine` are documented, discoverable targets.
</success_criteria>

<output>
Create `.planning/phases/02-state-machine-event-pipeline/02-04-SUMMARY.md` when done.
</output>
