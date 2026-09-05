---
phase: 02-state-machine-event-pipeline
fixed_at: 2026-09-05T08:05:00Z
review_path: .planning/phases/02-state-machine-event-pipeline/02-REVIEW.md
iteration: 2
findings_in_scope: 17
fixed: 17
skipped: 0
status: all_fixed
---

# Phase 2: Code Review Fix Report (iteration 2)

**Fixed at:** 2026-09-05T08:05:00Z
**Source review:** `.planning/phases/02-state-machine-event-pipeline/02-REVIEW.md`
**Iteration:** 2

**Summary:**

| Severity | In scope | Fixed | Deferred |
|----------|----------|-------|----------|
| Critical (BLOCKER) | 2 | 2 | 0 |
| Warning | 9 | 9 | 0 |
| Info | 6 | 6 | 0 |
| **Total** | **17** | **17** | **0** |

Every finding was fixed. Two infos (IN-01, IN-06) were folded into the criticals/warnings they
belong to, as the review itself suggested; both are committed and described below. One purely
documentary follow-up is deferred with a reason at the bottom.

**Gates, all green after the last commit:**

| Gate | Result |
|------|--------|
| `uv run ruff check .` | All checks passed |
| `uv run mypy shared/ services/ scripts/` | Success: no issues found in 41 source files |
| `uv run pytest tests/unit -q` | **254 passed** (was 228) |
| `uv run pytest tests/integration -q -p no:cacheprovider` | **62 passed** (unchanged count, two tests materially strengthened) |

Gates were run in the **main checkout** (`workflow.use_worktrees` is `false` in
`.planning/config.json`, so no worktree was created and every edit, commit and gate ran on
`main` directly). The numbers above are reproducible from the tree as it stands.

The replay goldens in `tests/fixtures/raw_streams/*.events.jsonl` are **byte-for-byte
unchanged**: `git diff 53de387..HEAD -- tests/fixtures/` is empty.

---

## Fixed Issues

### CR-01: WR-01 is not fixed — a transiently failed message is still skipped permanently

**Files modified:** `services/state_machine/consumer.py`, `services/state_machine/README.md`,
`tests/unit/test_offset_commit_policy.py`
**Commit:** `8660a70`

The review was right and the diagnosis was exact. Not committing does not hold the offset,
because the consumer's *position* has already advanced; the next message's
`commit({tp: offset + 1})` sets the group watermark strictly past the failed offset.

`handle_message`'s transient arm now calls `_retry_later(msg)`, which `seek`s the partition
back to the failed offset and `pause`s it for a bounded backoff, resumed by a
`loop.call_later` timer. Both halves are load-bearing: the `seek` is what makes the failed
message the next one delivered, and the pause is what stops a dead Redis turning redelivery
into a hot loop. The pause is scoped to the affected partition, so any other assigned
partition keeps flowing. `run()` cancels any outstanding resume timers in a `finally`, so a
SIGTERM (see WR-02) never leaves a timer holding a consumer that is about to stop. A rebalance
between the failure and the rewind raises `IllegalStateError` from both `seek` and `pause`;
that is caught and logged, and is benign — the uncommitted offset is redelivered to the new
owner, which is the same outcome by a different route.

**The backoff is not `asyncio.sleep`.** `tests/unit/test_no_inline_sleep.py` bans an inline
sleep anywhere in `services/state_machine/`, and that gate was **not** touched, relaxed or
allowlisted. `consumer.pause()` + `resume()` is the primitive Kafka provides for exactly this
backpressure, and it parks the loop inside `getone()` rather than spinning.

The regression test is the one the review asked for: `_FakeConsumer` models a position, a
commit log and the three cursor operations, `run()` is driven over three messages with the
middle one's Redis claim failing once, and the test asserts the committed sequence is
contiguous and that offset 1 is re-delivered. **Mutation-checked:** with the `seek`/`pause`
removed it produces `commits == [1, 3]` and `seeks == []` — byte-for-byte the reviewer's
reproduction.

`README.md` and the `handle_message` docstring now state the real guarantee, including *why*
skipping the commit alone was never sufficient.

### CR-02: The `message_poison` log leaks raw payload content, including booking tokens

**Files modified:** `services/state_machine/consumer.py`,
`tests/unit/test_logs_never_carry_payload.py` (new)
**Commit:** `e992c10`

`_failure_shape(exc)` returns `["{field.path}:{error_type}", …]` for a `ValidationError` and a
dotted type name (`builtins.ConnectionError`) for anything else. Both `message_poison` and
`message_handling_failed` use it, per the review's instruction to treat the transient arm the
same way — a redis-py or asyncpg message can carry a DSN.

`tests/unit/test_logs_never_carry_payload.py` drives the real `handle_message` and captures
real structlog events via `structlog.testing.capture_logs()`. It asserts:

* the sentinel token is absent from the whole captured event stream, on both the poison and
  the transient path;
* the poison log **still** names the failing field and error type (`["raw_response:dict_type"]`)
  — redaction must not become silence;
* and, first in the file, that the sentinel really is present in `str(exc)`, so the leak tests
  cannot pass vacuously if pydantic ever stops embedding `input_value`.

**Mutation-checked:** three of its four tests fail against `error=str(exc)`.

**IN-01 folded in here.** `ParseError` stays in the poison tuple, with a comment recording why:
it is unreachable today (`parse_raw` is the only source and `_handle_raw` already catches it),
but since CR-01 the alternative branch *rewinds*, so a `ParseError` that ever did reach the
transient arm would be retried forever against a payload that can never decode. A dead branch
is now strictly safer than the live one.

### WR-01: WR-08's `ParseError` message echoes producer-controlled payload data

**Files modified:** `services/state_machine/parsers/opentable.py`,
`tests/unit/test_coverage_bounding.py`
**Commit:** `f9be1c6`

`int()`'s `ValueError` names the literal it could not parse, and `_handle_raw` logs the
`ParseError` verbatim as `poll_unparseable reason=…`. The message now names the defect and the
`type(...)__name__` only, restoring `parsers/errors.py`'s stated contract. Three new tests
assert the value never appears in the message while the field path and the offending type
still do.

### WR-02: Nothing handles SIGTERM, so the AsyncExitStack and `dispose_engine` never run

**Files modified:** `shared/shutdown.py` (new), `services/state_machine/main.py`,
`services/poller/main.py`, `tests/unit/test_graceful_shutdown.py` (new)
**Commit:** `534006d`

`shared.shutdown.run_until_signal(main)` installs `SIGTERM`/`SIGINT` handlers via
`loop.add_signal_handler`, and on a signal **cancels** the service coroutine so the caller's
`AsyncExitStack` / `finally` unwinds normally. It re-raises a genuine crash unchanged, cancels
its own waiter, removes its handlers, and cancels the inner task when the *caller* is
cancelled — which is the shape the e2e integration test produces. `ensure_future` rather than
`create_task` because the poller hands in an `asyncio.gather(...)`.

Installed in **both** entry points, as the review asked. SIGKILL remains uncatchable, which is
exactly why the chaos hook uses it, and the chaos test's `returncode == -SIGKILL` assertion is
unaffected.

Six tests cover: normal return, a crash propagating, a **real** `os.kill(SIGTERM)` reaching the
service as cancellation so its `finally` runs, handlers being removed again, an outer cancel
leaving no orphan, and a static guard that both entry points still call it.

### WR-03: WR-10 left four dead non-atomic Redis helpers exported

**Files modified:** `shared/redis_keys.py`, `tests/unit/test_redis_keys_phase2.py`
**Commit:** `7e58ed6`

`hset_slot`, `hdel_slot`, `hset_meta` and `expire_key` are deleted, along with their entries in
the module's `Named symbols` docstring; a comment records what was removed and why, since
`test_no_setnx_expire_pairs.py` only greps for `.setnx(` and would not catch a reintroduction.

**IN-06 folded in.** `test_hash_helpers_are_exported_so_store_needs_no_casts` is split into two
tests with corrected rationale: one asserts the *surviving* surface (`hgetall_slots` plus the
three `_with_ttl` transactions, which is what actually satisfies D-42), the other asserts the
four originals stay gone with a message naming the shape they represent.

### WR-04: The claim key concatenates untrusted fields with an unescaped `:`

**Files modified:** `shared/redis_keys.py`, `shared/events.py`,
`services/state_machine/README.md`, `tests/unit/test_redis_keys_phase2.py`,
`tests/unit/test_two_seat_types_one_token.py`
**Commit:** `c4ababb`

`event_idempotency_key` now percent-escapes every component (`quote(part, safe="")`), so the
key is injective: `quote` escapes `:` and `%` itself, no component's encoding can contain the
separator, and the join is unambiguous. The key is ephemeral (20 min TTL) and appears in no
golden, so reshaping it is free — the goldens are confirmed unchanged.

Two new tests: an injectivity sweep over 300 component tuples drawn from values that contain
the separator (`"a:b"`, `":"`, `"19:00|bar:a"`, `"%"`, `""`), and a numeric-component case. The
existing format test now pins the escaped form.

`test_two_seat_types_one_token.py`'s claim assertion changed from a substring check on
`"19:00|"` to *decoding* the slot component back and asserting the exact set
`{"19:00|bar", "19:00|standard"}` — strictly stronger than what it replaced, and necessary
because the old assertion pinned the unescaped format.

`shared.events.make_event_id` is deliberately **not** changed: its uuid5 output is permanent
and already recorded in every committed golden and every `availability_events` row. The
constraint, and the argument for why the residual risk is bounded (the ambiguity would have to
straddle `slot_key` / `first_poll_id`, and `first_poll_id` is a UUID string), is recorded in a
comment there — which is the minimum the review asked for.

### WR-05: The integration-coverage instruction for CR-01/CR-02 was not carried out

**Files modified:** `tests/integration/test_state_machine_chaos.py`,
`tests/integration/test_state_machine_e2e.py`
**Commit:** `c5955a0`

Both fixtures now use the shipped `OPENTABLE_SUCCESS_RESPONSE` **untrimmed**
(`seatingTypes: ["bar", "standard"]`), so both tests exercise the two-slot path against real
Redis, a real broker and TimescaleDB.

The chaos test needs **no second restart** — the runtime is unchanged. With
`MISE_CRASH_AFTER=state_write` and two slots, the SIGKILL lands after the *first* slot's
per-slot flush and before the second slot is claimed, which is exactly the window per-slot
flushing exists for. It asserts one event before the crash, then after one restart: both
events, both seat types, no duplicate `event_id`, and **both `availability_events` rows**. That
is the review's `kafka_send` scenario reached by a cheaper route, and it also proves the
iteration-1 CR-02 fix (per-slot rather than message-wide flushing) against a real crash for
the first time.

The e2e test asserts two events with distinct `event_id`s and **one shared `booking_token`**
(the fixture's whole point), one row each, and both closed with `duration_seconds == 20`. Its
readiness condition now waits for `closed == 2` rather than `> 0`, so the assertions cannot
race the second closure.

### WR-06: `.env.example` documents the crash-hook interlock as the removed `ENV=prod` check

**Files modified:** `.env.example`, `tests/unit/test_replay_determinism.py`
**Commit:** `2f4cdeb`

The banner now states the allowlist and that the interlock fails closed, so unset, blank,
`staging` and `production` are all refused. The banner test asserts `ENV=prod` is **absent**
and all four allowlist entries are present. **Mutation-checked** against the old wording.

### WR-07: The migration tests downgrade a shared schema and restore it outside their failure path

**Files modified:** `tests/integration/test_migration_0008.py`
**Commit:** `fdc26cb`

Both downgrade tests now restore head in a `finally`. The CR-03 guard is the important one:
`assert failed.returncode != 0` is exactly what fires if the `DELETE` is reintroduced, and that
failure used to leave the module-scoped database at revision 0007 so every later test in the
module failed for an unrelated reason.

### WR-08: `_close` parses a stored `event_id` with an unguarded `UUID()` inside the pure core

**Files modified:** `services/state_machine/models.py`, `services/state_machine/engine.py`,
`tests/unit/test_engine_tristate_unknown.py`
**Commit:** `f326e40`

Took the boundary branch: `SlotRecord.from_json` validates `event_id` where every other field
is already validated, so `RedisStateStore.get_slots` drops a corrupt record with its existing
`slot_record_unreadable` warning and the slot re-enters the PENDING cycle. `_close` keeps its
`UUID(...)` call, now total, with a comment saying why.

This interacts with CR-01 and the interaction is why it mattered more than the review's
WARNING rating suggested: before the boundary check, one bad character raised out of
`process()` into the transient arm, which now **rewinds and retries forever** against a record
that can never parse. Six tests cover four corruption shapes, the well-formed round trip, and
the end-to-end consequence (the corrupt record disappears, the sibling record survives).

### WR-09: `effective_coverage`'s docstring contradicts the caller

**Files modified:** `services/state_machine/parsers/opentable.py`
**Commit:** `69248f7`

One sentence, no code change, exactly as prescribed — plus a note that the old wording
described the pre-WR-09 behaviour, so the next reader knows it was not simply wrong.

### IN-01: The `ParseError` arm of the poison handler is unreachable

**Commit:** `e992c10` (folded into CR-02). Kept with a comment, for the reason given above:
after CR-01 the alternative branch is a permanent retry loop.

### IN-02: `_assert_topics_exist` and `topic_partitions` leak their admin client

**Files modified:** `services/state_machine/main.py`, `services/poller/main.py`,
`scripts/replay_raw.py`
**Commit:** `1bb9be8`

`await admin.start()` moved inside the `try` at all three sites. Verified from the installed
`aiokafka` source that `AIOKafkaAdminClient.close()` is safe on a client that never finished
starting (it guards on `_closed` and delegates to `AIOKafkaClient.close()`), so the `finally`
cannot mask the original error with a secondary one.

### IN-03: The new scheduler integration tests leak Redis connections

**Files modified:** `tests/integration/test_scheduler_claim_release.py`
**Commit:** `1b6e0ec`

Both WR-14 tests take a `try/finally` that deletes the ZSETs and calls `await r.aclose()`. The
reaper-resurrection test deliberately leaves a job on the ready queue, so its cleanup running
on the failure path is what stops a failed assertion seeding the next test in the module.

### IN-04: `run_offset_mode`'s "nothing to replay" message hides the partition it read

**Files modified:** `scripts/replay_raw.py`, `tests/integration/test_replay_offset_range.py`
**Commit:** `21e8b08`

Took the "resolve it in `run_offset_mode`" branch rather than changing
`fetch_offset_range`'s return type, which has ten call sites in the integration tests. The
resolved id is passed back down, where `resolve_partition` re-runs as a validating no-op. The
empty-range test now captures stderr and asserts the message names `{topic}[p0]`.

### IN-05: `DiffEngine.last_close_count` is assigned only at the end of `process()`

**Files modified:** `services/state_machine/engine.py`, `tests/unit/test_slot_key_collisions.py`
**Commit:** `c4b76a4`

Both counters reset on the first line. A new test drives `process()` against a store that
raises mid-diff and asserts neither counter survives. **Mutation-checked.**

### IN-06: `test_hash_helpers_are_exported…` has a stale rationale

**Commit:** `7e58ed6` (folded into WR-03), as the review directed.

---

## Verification

Every fix was verified by re-reading the changed region, then by the full static + unit gate;
the consumer and fixture changes and the final state were additionally verified against the
Docker integration suite. Mutation checks (confirming the new test fails against the pre-fix
code) were run for **CR-01, CR-02, WR-06 and IN-05**.

No test was disabled, skipped, weakened, or marked xfail. Three existing tests were **edited**,
each because the fix changed the observable value they pinned, and each was made stronger:

* `test_offset_commit_policy.py::_shell` — the mock consumer's `seek`/`pause`/`resume` became
  `MagicMock` rather than `AsyncMock`, because those methods are synchronous on
  `AIOKafkaConsumer`; leaving them async produced un-awaited coroutines.
* `test_two_seat_types_one_token.py` — substring check replaced by full decode-and-compare.
* `test_replay_determinism.py` — the `.env.example` banner assertion gained the allowlist
  requirement (WR-06's explicit instruction).

No `time.sleep`, `requests`, or synchronous redis was added anywhere in `services/` or
`shared/`. CR-01's backoff is deliberately **not** an `asyncio.sleep`: the repo's no-sleep gate
bans it service-wide, and that gate was left exactly as it was.

## Deferred

**D-46 / `02-CONTEXT.md` decision text (documentation only, one line).** D-46 was amended after
iteration 1 to `SET event:{rid}:{date}:{party}:{slot_key}:{token}`. WR-04 makes the components
**percent-escaped**, so the literal in the decision text is now one refinement behind the code
again. Not changed here for the same reason as last iteration: `.planning/` decision records are
locked context owned by the orchestrator, and this agent does not commit `.planning/` files. The
amendment needed is to note that each component is percent-escaped (`quote(part, safe="")`)
because `slot_key` and `token` are payload data and `slot_key` always contains a `:`. The code,
the tests, `shared/redis_keys.py`'s docstring and `services/state_machine/README.md` are
already consistent with the escaped form.

## Notes for the reviewer

* **Two findings compounded each other, and the compounding is the interesting part.** CR-01's
  rewind turns any exception escaping `process()` into an infinite retry loop rather than a
  silent drop. That makes WR-08 (the unguarded `UUID()` in the pure core) and IN-01 (the
  `ParseError` arm) materially more serious *after* CR-01 than before it, and both fixes are
  written to say so. A reviewer checking CR-01 in isolation would not see this.
* **The chaos test got stronger without getting slower.** Keeping `MISE_CRASH_AFTER=state_write`
  and un-trimming the fixture puts the SIGKILL between slot 1's flush and slot 2's claim, which
  is a better crash point for this purpose than the `kafka_send` variant the review suggested
  and needs only the one restart the existing test already performs.
* **`workflow.use_worktrees` is `false`**, so this run edited and committed on `main` in the
  main checkout, with no worktree, no temp branch and no recovery sentinel.
* A concurrent agent was writing Phase 3/4 planning artifacts throughout the run; four
  `docs(03)` / `docs(04)` commits are interleaved with the nineteen `fix(02)` commits in
  `git log`. Those are not mine, and nothing under `.planning/phases/03-*` or `04-*` was
  staged or touched. Only the files listed under each finding above were staged.

---

_Fixed: 2026-09-05T08:05:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
