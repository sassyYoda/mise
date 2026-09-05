---
phase: 02-state-machine-event-pipeline
fixed_at: 2026-09-05T08:22:00Z
review_path: .planning/phases/02-state-machine-event-pipeline/02-REVIEW.md
iteration: 3
findings_in_scope: 16
fixed: 13
skipped: 3
status: partial
---

# Phase 2: Code Review Fix Report (iteration 3, final)

**Fixed at:** 2026-09-05T08:22:00Z
**Source review:** `.planning/phases/02-state-machine-event-pipeline/02-REVIEW.md`
**Iteration:** 3 (scoped: MUST-FIX only, with WR-01 / WR-05 deferred by instruction)

**Summary:**

| Severity | In review | Fixed | Deferred |
|----------|-----------|-------|----------|
| Critical (BLOCKER) | 3 | 3 | 0 |
| Warning | 7 | 5 | 2 |
| Info | 6 | 5 | 1 |
| **Total** | **16** | **13** | **3** |

All three blockers are fixed. The two warnings the scope explicitly deferred (WR-01, WR-05) and
one info that turned out not to be a one-liner (IN-03) are recorded in
`.planning/deferred-items.md` with their reproductions and the reason each was not folded in.

**Gates, all green at HEAD:**

| Gate | Result |
|------|--------|
| `uv run ruff check .` | All checks passed |
| `uv run mypy shared/ services/ scripts/` | Success: no issues found in 41 source files |
| `uv run pytest tests/unit -q` | **291 passed** (was 254) |
| `uv run pytest tests/unit -q -W error::RuntimeWarning` | **291 passed**, 1 warning — the pre-existing testcontainers `DeprecationWarning`. The three `RuntimeWarning`s WR-04 named are gone. |
| `uv run pytest tests/integration -q -p no:cacheprovider` | **62 passed** (unchanged count; the new `availability.dlq` topic and both `REQUIRED_TOPICS` guards are exercised by `test_topics_created` and by the e2e/chaos fixtures) |

Gates ran in the **main checkout**. `workflow.use_worktrees` is `false` in
`.planning/config.json`, so no worktree was created, no temp branch, no recovery sentinel —
every edit, commit and gate ran on `main` directly, and the numbers above are reproducible from
the tree as it stands.

The replay goldens are **byte-for-byte unchanged**: `git diff a3a3e87..HEAD -- tests/fixtures/`
is empty. Nothing in this iteration touches `make_event_id`'s output (see WR-01, deferred).

---

## Fixed Issues

### CR-01: The rewind has no attempt cap, and re-sends the event on every retry

**Files modified:** `services/state_machine/consumer.py`, `services/state_machine/config.py`,
`services/state_machine/main.py`, `services/state_machine/README.md`,
`services/poller/main.py`, `scripts/create_topics.py`, `.env.example`,
`tests/unit/test_retry_cap_and_dlq.py` (new), `tests/integration/test_topics_created.py`
**Commit:** `485c446`

The review's diagnosis was exact on both halves, and the second half was the expensive one.

**The cap.** Retries are counted per `(topic, partition, offset)` and bounded by
`STATE_MACHINE_MAX_ATTEMPTS` (default 5). Only the head of a partition can be under retry — the
rewind makes the failed offset the next one delivered — so a single key plus a counter is the
whole state and it cannot grow. The key is compared on entry to `handle_message`, so a new
offset resets the accounting without needing a success hook.

On exhaustion the message becomes poison: `message_retries_exhausted` at ERROR carrying the
attempt count, the failure **shape** and `metric=state_machine_messages_dead_lettered_total`;
then the ORIGINAL bytes to `availability.dlq` with `original_topic` / `original_partition` /
`original_offset` / `attempts` / `error` headers; then the commit. The DLQ carries the payload
because a dead-letter record redacted down to a failure shape is an audit trail nobody can
replay from — and unlike a log line it is a Kafka topic with the same trust boundary as
`availability.raw`, which already holds those bytes. What the DLQ adds is 7-day retention over
the raw topic's 24 hours: a message that poisoned the pipeline on a Friday night is still there
on Monday.

The publish is **best effort** and the commit happens either way. A dead-letter topic that is
itself unavailable must not be able to re-create the stall the whole mechanism exists to end.
`availability.dlq` is created by `scripts/create_topics.py` (7 d) and guarded at startup by
**both** services' `REQUIRED_TOPICS`, so a deployment that skipped `make topics` fails
immediately rather than at the moment the pipeline is already poisoned.

The cap refuses `0`, a negative and a non-integer with a startup `RuntimeError` rather than
silently correcting them. `STATE_MACHINE_MAX_ATTEMPTS=0` would dead-letter every message on its
first hiccup, which is worse than either failure mode the cap arbitrates between, and a typo
must not quietly restore the unbounded retry.

**The duplicate re-send.** This is the part the review reproduced at ~43k events/day, and it
needed a different fix from the cap. When the failure lands *after* `send_and_wait` —
`_flush_slot` is the live example — the retry finds `set_nx_ex` False, `_crashed_mid_emit`
reads a record still PENDING (because `_discard()` threw the buffered write away) and answers
True, so the event goes out again on **every** retry. The shell now records each `event_id` the
**broker acked** for the offset under retry, and a retry skips the send for those
(`emit_skipped_already_acked`) while still running the remaining steps. Running them matters:
the INSERT and the per-slot state write are both idempotent, and skipping them would leave the
slot PENDING with its event already on the wire — the one state the D-46 ordering exists to
avoid. The id is recorded only **after** the ack, so a send the broker never took is not
suppressed.

Eleven tests drive the real `run()` loop, because neither defect is visible in a single
`handle_message` call. **Mutation-checked, both halves:**

* removing the cap makes `test_a_permanent_failure_is_retried_exactly_n_times_then_committed_past`
  spin to its 10-second `wait_for` timeout — the reviewer's `ended: TimeoutError` verbatim;
* removing the acked-set makes the partial-emit test send `['bar', 'bar', 'standard']` instead
  of `['bar', 'standard']`.

**Not done, deliberately:** the review also suggested exponential backoff with jitter. That is a
behaviour change to the backoff constant with no finding attached to it, and the flat 2 s is
what `tests/unit/test_no_inline_sleep.py`'s pause/resume story is written around. Left alone
rather than folded into a blocker fix.

### CR-02: `AttributeError` escapes the store, so a non-string `event_id` reaches the retry loop

**Files modified:** `services/state_machine/store.py`, `services/state_machine/models.py`,
`tests/unit/test_engine_tristate_unknown.py`
**Commit:** `292f2f4`

Both halves of the review's fix, because they do different jobs. `SlotRecord.from_json` now
rejects a non-string `event_id` with a `ValueError` of its own, which makes the boundary
**total** — `UUID()` raises `AttributeError` out of `hex.replace(...)`, not `ValueError`, so
`"e": 42` used to skip `get_slots`'s except clause entirely. `RedisStateStore.get_slots` also
gains `AttributeError` to its tuple as defence in depth: that catch is deliberately by
CONSEQUENCE ("this field is unreadable"), not by the exception type today's validator happens
to raise, so a future validator cannot silently reopen the hole. It stays a widened tuple
rather than a bare `Exception`, which would swallow a genuine bug in the store itself.

The tests routed around the gap and no longer can. The boundary test asserts a single
`ValueError` instead of the permissive `(ValueError, TypeError, AttributeError)` tuple that let
the `number` case pass while escaping the store; and the **store-level** test — the one that
actually proves the drop — is parametrised over the same six shapes (`garbage`, `truncated`,
`empty`, `number`, `bool`, `list`) instead of the one string case.

**Mutation-checked:** reverting the isinstance guard fails 3 boundary cases; reverting the guard
and the store catch together fails 6.

### CR-03: `insert_event`'s `error=str(exc)` writes the booking token into the log stream

**Files modified:** `shared/telemetry.py`, `services/state_machine/persistence.py`,
`services/state_machine/consumer.py`, `services/poller/reaper.py`,
`services/poller/scheduler.py`, `tests/unit/test_safe_error.py` (new),
`tests/unit/test_logs_never_carry_payload.py`
**Commit:** `424634f` — WR-03 and WR-07 folded in, as instructed.

`shared.telemetry.safe_error(exc)` returns `module.ClassName: <scrubbed message>` and strips the
three places a real driver puts payload:

| Stripped | Why |
|----------|-----|
| everything from `[SQL:` / `[parameters:` / `[cached since` to the end | SQLAlchemy renders bound parameters by default (`hide_parameters=False`), and `insert_event` binds `booking_token`. Truncating rather than bracket-matching because a parameter dict can contain `]`. |
| `input_value=` to end of line | pydantic v2 embeds the offending input; `repr` escapes newlines, so end-of-line is total. |
| `DETAIL:` / `CONTEXT:` / `HINT:` lines | Postgres quotes the offending VALUES there (`Key (booking_token)=(…) already exists`). |

It also collapses to one line and bounds the length at 300 chars, which is the other half of
WR-03's complaint that the failure line was unbounded.

**One deliberate divergence from the review's suggested fix, and the reason for it.**
`safe_error` is *weaker* than `consumer._failure_shape`, which discards the message entirely.
Routing `consumer.py`'s branches through `safe_error` would have **regressed** the CR-02 fix
from iteration 2: `test_a_transient_driver_error_logs_no_connection_string` puts a sentinel
inside a `ConnectionError` message (`redis://user:SECRET@cache:6379`), and `safe_error` keeps
message text. So the split is by trust boundary, and both docstrings say so:

* `_failure_shape` for a failure raised while handling **producer-supplied** data — the message
  is attacker-influenced, so only the shape survives;
* `safe_error` for a failure raised by **our own infrastructure**, where the reason text
  ("value too long for type character varying(64)") is the whole diagnostic value.

WR-07's commit branch therefore takes `_failure_shape(exc)`, which is what the review's own fix
prescribed and is strictly stronger than the alternative. Applied elsewhere in `services/`:
`persistence.insert_event` and `close_event`, the `poll_unparseable` reason, and the poller's
`reaper_error` / `poll_failed` / `poll_timeout` log fields. `polls.completed`'s `error_str` wire
field is deliberately untouched — it is a message payload, not a log line.

Nine `safe_error` tests build **real** SQLAlchemy and pydantic exceptions rather than
hand-written strings, each with a guard asserting the sentinel really is in the raw text, so the
scrubber cannot go vacuous if either library changes its rendering.
`test_logs_never_carry_payload.py` gains the end-to-end guards the review asked for: a failed
`insert_event` whose bound parameters carry the sentinel, a failed `close_event`, and the commit
branch.

**Mutation-checked:** three tests fail against `str(exc)` in `persistence.py`, one against
`str(exc)` in the commit branch.

### WR-02: The `KNOWN CONSTRAINT` comment states a safety property that is false

**Files modified:** `shared/events.py`, `tests/unit/test_slot_key_collisions.py`
**Commit:** `4a23b7c`

The old comment claimed the ambiguity had to straddle `slot_key` and `first_poll_id` and that
`first_poll_id` being a UUID therefore blocked it. Both halves were wrong, and a wrong comment
on a permanent identity recipe is worse than no comment — it is what the next engineer consults
before deciding whether the recipe needs changing.

It now says the truth: `date`, `party_size` and `slot_key` are three **adjacent** unescaped
components, all three payload-derived with nothing but an `isinstance` check, so a collision is
constructible from response data alone; `slot_key` is itself a lossy join that collapses
identities before the recipe is called; the recipe is frozen not because the risk is bounded but
because the output is permanent; and any change must escape every component, regenerate the
goldens and carry a Redis cutover in one commit. It cross-references WR-01 in
`.planning/deferred-items.md`.

Two tests make the constraint **executable** rather than prose, and they are written so that the
day WR-01 lands they fail loudly and must be deleted deliberately rather than forgotten.

### WR-03: `close_event` renders the SQL statement into the log

**Commit:** `424634f` (folded into CR-03, as the review directed). Covered by `safe_error`, plus
the length bound, plus `test_a_failed_close_never_logs_the_statement`.

### WR-04: `test_emit_flush_ordering.py` uses an unfaithful consumer mock

**Files modified:** `tests/unit/test_emit_flush_ordering.py`, `Makefile`
**Commit:** `6ae223d`

`_FakeConsumer` models the real cursor surface — `seek`/`pause`/`resume` synchronous,
`commit` a coroutine — and records its calls. The second consequence the review named was the
important one: with the bare `AsyncMock`, the transient path in
`test_a_crash_on_the_second_send_leaves_that_slot_pending_and_it_re_emits` was a no-op that only
*looked* exercised. That test now **asserts** the rewind (seek to offset 0, partition paused,
nothing committed), which was unwritable before. `_settle()` cancels the real `call_later(2.0)`
timer the transient path arms against a loop pytest-asyncio closes immediately afterwards.

`make test` now runs with `-W error::RuntimeWarning`. Not added to `pyproject.toml`: the
integration suite's containers emit their own warnings, so the gate is scoped to the code we
own. All three `RuntimeWarning`s are gone from the unit suite.

### WR-06: `_resume_partition` swallows only `KafkaError`

**Files modified:** `services/state_machine/consumer.py`,
`tests/unit/test_partition_resume.py` (new)
**Commit:** `3b9b47d`

The callback now catches `Exception`, logs `partition_resume_failed` through structlog with the
failure shape, and **re-schedules itself** so a transient race does not park the partition
permanently — bounded by `MAX_RESUME_ATTEMPTS = 3`, after which `partition_resume_abandoned`
fires once with a named metric placeholder. Bounded because the callback re-arms its own timer:
against a consumer that is genuinely gone, an unbounded chain is a log flood with no end, and
"never silent" must not become "never quiet".

`_retry_later`'s tuple is widened to `Exception` for the reason the review gave, which is worse
than the `_resume_partition` case: it is raised from inside the transient `except` block, so
nothing above catches it and `run()` terminates outright. A `KafkaError` stays a silent no-op —
the partition is somebody else's problem now, which is not an incident.

Four tests. **Mutation-checked:** narrowing either catch back fails three of them.

### WR-07: `offset_commit_failed` still uses `str(exc)`

**Commit:** `424634f` (folded into the CR-03 sweep). Now `_failure_shape(exc)`, with the commit
branch added to `test_logs_never_carry_payload.py` so the rule is enforced rather than
remembered — the test puts a sentinel in a `KafkaError` message and asserts the logged value is
exactly `"aiokafka.errors.KafkaError"`.

### IN-01, IN-02, IN-04, IN-05, IN-06

**Files modified:** `shared/shutdown.py`, `services/state_machine/consumer.py`,
`services/state_machine/README.md`, `tests/integration/test_migration_0008.py`,
`tests/unit/test_graceful_shutdown.py`
**Commit:** `89dc776`

**IN-05 is the only behavioural one and it is a real bug.** `run_until_signal` installed
`SIGTERM`/`SIGINT` two statements *before* the `try` whose `finally` removes them, so a raising
`ensure_future(main)` left both signals bound to `stop.set` for the rest of the process,
silently disarming their default disposition. Handler installation and both `ensure_future`
calls now live inside the `try`. **Mutation-checked:** hoisting either back out fails the new
test, which is the failure path the existing six covered only the happy side of.

IN-01 records the schema dependency `_failure_shape`'s `loc` safety rests on, naming the fix
(cap to `loc[0]`) for whoever tightens `raw_response`. IN-02 is a deploy note for the
percent-escaped claim key's 20-minute duplicate window — self-healing, Layer-2 still covers the
notification, written down so nobody spends an afternoon on it. IN-04 records that
`_resume_handles` is bounded by the assignment size rather than by traffic. IN-06 wraps the
migration test's cleanup `DELETE` in `contextlib.suppress(Exception)` so a connection failure in
the `finally` cannot replace the `AssertionError` that fired.

---

## Deferred

All three are recorded in `.planning/deferred-items.md` with their reproductions, so none has to
be rediscovered. Commit `3503628`.

### WR-01: slot identity is not injective (deferred by scope instruction)

Escaping `Slot.slot_key` changes stored Redis hash field names **and, through
`make_event_id`, every `event_id`**. That requires regenerating all of
`tests/fixtures/raw_streams/*.events.jsonl` — files that exist precisely to pin byte-identical
replay (STATE-06) — plus a documented Redis-state cutover, in one commit. That is a planned
change with its own verification, not a review fix.

Both reproductions are now **executable tests** (WR-02's commit), and the false safety claim
that used to sit on `make_event_id` is corrected, so the constraint cannot drift back into
comforting prose while this waits.

### WR-05: the poller's `gather` leaks a live sibling task (deferred by scope instruction)

A `TaskGroup` changes the exception type the caller sees (`ExceptionGroup`), so
`run_until_signal`'s re-raise contract, the six shutdown unit tests and both entry points need
re-verifying together. Out of scope for a pass whose remit was the state machine, and the
failure only occurs when a poller loop crashes outright, at which point the process is going
down anyway.

### IN-03: `run_offset_mode` resolves the partition twice (not a one-liner)

The scope admitted INFO items that are one-liners; this one is not. `fetch_offset_range` has ten
call sites in the integration tests, so changing its signature or return type is a wider edit
than an INFO rating justifies, for a two-round-trip saving in a one-shot CLI.

---

## Verification

Every fix was verified by re-reading the changed region, then by the full static + unit gate.
The integration suite was run once at the end, green at 62.

**Mutation checks** (confirming the new test fails against the pre-fix code) were run for
**CR-01 (both halves independently), CR-02 (single and double), CR-03 (persistence and the
commit branch), WR-06 (both catches) and IN-05**. Each is described under its finding above.

No test was disabled, skipped, weakened or marked xfail. Three existing tests were **edited**,
each because the fix changed the value they pinned, and each was made stronger:

* `test_an_unparseable_event_id_is_rejected_at_the_boundary` — `pytest.raises((ValueError,
  TypeError, AttributeError))` narrowed to `pytest.raises(ValueError)`. The permissive tuple was
  how CR-02 hid.
* `test_a_corrupt_event_id_is_dropped_by_the_store_not_raised` — one hard-coded string case
  replaced by the same six-shape parametrisation as the boundary test.
* `test_a_crash_on_the_second_send_leaves_that_slot_pending_and_it_re_emits` — gained assertions
  on the rewind that the bare `AsyncMock` made unwritable.

`test_all_five_topics_have_retention` was renamed to `test_every_named_topic_has_retention` and
gained `availability.dlq`; its assertions are unchanged in strength.

No `time.sleep`, `requests` or synchronous redis was added anywhere in `services/` or `shared/`.
No `asyncio.sleep` was added in `services/state_machine/` — `tests/unit/test_no_inline_sleep.py`
was not touched, relaxed or allowlisted, and CR-01's retry cap needed no timing primitive at all
(it is a counter; the existing pause/resume backoff is unchanged).

## Notes for the reviewer

* **The two halves of CR-01 needed different fixes, and only one of them is the cap.** Bounding
  the retry stops the stall but does nothing about the duplicates — a message that fails after
  `send_and_wait` still re-sends on each of its five attempts. The acked-`event_id` set is what
  makes the retry idempotent, and it is the piece that would be easiest to drop while believing
  CR-01 was addressed. Its mutation check (`['bar', 'bar', 'standard']`) is the one to look at.
* **CR-03's fix is a split, not a single helper.** Routing `consumer.py` through `safe_error`
  would have regressed iteration 2's CR-02: `safe_error` keeps message text, and a redis-py
  `ConnectionError` message can carry a DSN. Two renderers with an explicit trust-boundary rule
  is the answer; a single one is a regression in one direction or the other.
* **`availability.dlq` is now guarded by the poller too.** Both services declare the identical
  `REQUIRED_TOPICS` set by convention, and splitting them would make the poller's guard silently
  drift from the state machine's. The poller does not publish to the DLQ; it just refuses to
  start without it, which is the same bargain it already makes for `notifications.*`.
* **`workflow.use_worktrees` is `false`**, so this run edited and committed on `main` in the main
  checkout, with no worktree, no temp branch and no recovery sentinel.
* A concurrent Phase 4 researcher was writing planning artifacts throughout; four `docs(04)` /
  `docs(phase-4)` commits are interleaved with my eight `fix(02)` commits in `git log`. Those are
  not mine. Nothing under `.planning/phases/04-*` was staged or touched — only the files listed
  under each finding above, plus `.planning/deferred-items.md`.

---

_Fixed: 2026-09-05T08:22:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 3 (final)_
