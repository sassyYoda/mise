---
phase: 02-state-machine-event-pipeline
reviewed: 2026-09-05T07:58:30Z
depth: standard
iteration: 3
previous_review: .planning/phases/02-state-machine-event-pipeline/02-REVIEW.iter2.md
files_reviewed: 41
files_reviewed_list:
  - .env.example
  - migrations/versions/0008_add_event_id_to_availability_events.py
  - scripts/replay_raw.py
  - services/poller/main.py
  - services/poller/scheduler.py
  - services/state_machine/README.md
  - services/state_machine/config.py
  - services/state_machine/consumer.py
  - services/state_machine/engine.py
  - services/state_machine/main.py
  - services/state_machine/models.py
  - services/state_machine/parsers/opentable.py
  - services/state_machine/persistence.py
  - services/state_machine/store.py
  - shared/db.py
  - shared/events.py
  - shared/kafka.py
  - shared/redis_keys.py
  - shared/scheduler/lua.py
  - shared/shutdown.py
  - shared/telemetry.py
  - tests/integration/test_migration_0008.py
  - tests/integration/test_replay_offset_range.py
  - tests/integration/test_scheduler_claim_release.py
  - tests/integration/test_state_machine_chaos.py
  - tests/integration/test_state_machine_e2e.py
  - tests/unit/test_coverage_bounding.py
  - tests/unit/test_emit_flush_ordering.py
  - tests/unit/test_engine_tristate_unknown.py
  - tests/unit/test_graceful_shutdown.py
  - tests/unit/test_logs_never_carry_payload.py
  - tests/unit/test_no_inline_sleep.py
  - tests/unit/test_offset_commit_policy.py
  - tests/unit/test_redis_keys_phase2.py
  - tests/unit/test_replay_determinism.py
  - tests/unit/test_slot_key_collisions.py
  - tests/unit/test_two_seat_types_one_token.py
findings:
  critical: 3
  warning: 7
  info: 6
  total: 16
status: issues_found
---

# Phase 2: Code Review Report (iteration 3, final)

**Reviewed:** 2026-09-05T07:58:30Z
**Depth:** standard
**Files Reviewed:** 41 (`git diff 53de387..HEAD`, plus the unchanged phase-2 modules named in the focus list)
**Status:** issues_found

## Summary

Gates re-verified at HEAD: `uv run ruff check .` clean, `uv run mypy shared/ services/ scripts/`
clean (41 source files), `uv run pytest tests/unit -q` **254 passed** (with three
`RuntimeWarning`s — see WR-04). The integration suite was left to the concurrent agent.

**Verification of iteration 2, finding by finding.** Fifteen of the seventeen are genuinely
fixed, and three are fixed better than the review asked for:

* **CR-01 (offset rewind) — fixed, and correctly.** `_retry_later` does
  `consumer.seek(tp, msg.offset)` + `consumer.pause(tp)` + `loop.call_later(2.0, resume)`. I
  checked this against the pinned aiokafka 0.13.0 rather than trusting the comment:
  `Fetcher.seek_to` deletes the partition's prefetched buffer, and `FetchResult.check_assignment`
  refuses to yield records for a paused partition, so the rewind really does make the failed
  message the next one `getone()` returns. The new `_FakeConsumer` test drives `run()` over three
  messages and asserts `commits == [1, 2, 3]` and `delivered == [0, 1, 1, 2]` — a real regression
  guard, not the `await_count == 0` tautology it replaced. Reproduced green.
* **CR-02 (payload in logs) — fixed *in `consumer.py`*.** `_failure_shape` renders
  `loc:type` pairs for a `ValidationError` and a dotted type name otherwise, and
  `test_logs_never_carry_payload.py` drives the real handler with a sentinel token and asserts it
  is absent from the captured structlog events. It also pins that pydantic still embeds
  `input_value`, so the test cannot go vacuous. See CR-03 for where the same defect survives.
* **WR-02 (SIGTERM) — fixed.** `shared/shutdown.py` is a genuinely careful piece of work:
  `ensure_future` (not `create_task`) so the poller's `gather` future works, handler removal in
  `finally`, an outer-cancel path, and a Windows/worker-thread degradation. Both entry points
  use it and a source-grep test pins that they keep doing so.
* **WR-05 (fixture trimming) — fixed, exactly as asked.** Both the e2e and chaos fixtures are
  now the untrimmed `seatingTypes: ["bar", "standard"]`, the chaos test asserts one event before
  the SIGKILL and both events plus both `availability_events` rows after, and the e2e wait
  condition was tightened from `bool(closed)` to `closed == 2` so it cannot race the second
  closure.
* **WR-01, WR-03, WR-06..WR-09, IN-01..IN-06 — fixed**, all with behavioural or source-grep
  guards rather than comment-only changes.

**Determinism answer (asked explicitly):** the percent-escaped claim key changes no golden.
`scripts/replay_raw.py` never calls `event_idempotency_key` (grep: zero hits), the key has a
20-minute TTL and appears in no fixture, and `tests/fixtures/raw_streams/*.events.jsonl` are
untouched in the diff. `test_replay_determinism.py` passes. Confirmed safe.

That is where the good news stops. Three defects survive, all of them consequences of *how*
CR-01 and CR-02 were fixed rather than of whether they were fixed:

1. **CR-01 (this iteration)** — the rewind has no attempt cap. Every exception that is not a
   `ValidationError`/`ParseError` is assumed transient and retried **forever**. A permanent
   error therefore converts iteration 2's silent data loss into a permanently stalled
   partition, and when the failure lands after a slot's `send_and_wait` it re-sends the event
   on every retry. Both reproduced against the shipped code.
2. **CR-02 (this iteration)** — WR-08's boundary validation is incomplete. `UUID()` raises
   `AttributeError` (not `ValueError`/`TypeError`) for a non-string, `RedisStateStore.get_slots`
   does not catch `AttributeError`, so a stored `"e": 42` escapes the store and lands in the
   retry-forever branch — the exact outcome the WR-08 comment says it removed. The new test
   *lists* `AttributeError` in its `pytest.raises` tuple, and the store-level test only exercises
   the string case, so it tests around the gap.
3. **CR-03 (this iteration)** — CR-02's redaction was applied only to `consumer.py`.
   `persistence.py:106-112` still logs `error=str(exc)` on a SQLAlchemy exception, and
   `StatementError.__str__` renders `[SQL: ...] [parameters: ...]` — whose parameters include
   `booking_token`. That is the one place in the codebase where a failure message is *guaranteed*
   to contain a live token. Reproduced.

Beyond those: WR-04's percent-escaping does not actually make slot identity injective, because
`slot_key` is itself a lossy join of two payload fields (both collisions reproduced below); the
`KNOWN CONSTRAINT` comment added to `make_event_id` states a safety property that is false; a
unit test leaves an unfaithful consumer mock that emits three `RuntimeWarning`s per run and
schedules an orphan 2-second timer; and the poller's `gather` still leaks a live sibling task
when one child raises.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: The rewind has no attempt cap, so a permanent error stalls the partition forever — and re-sends the event on every retry

**File:** `services/state_machine/consumer.py:181-212` and `:215-257`
**Severity:** BLOCKER

**Issue:** The failure taxonomy in `handle_message` has exactly two arms: `ValidationError |
ParseError` → poison (commit and move on), and **everything else** → transient (rewind, pause
2 s, resume, retry). There is no third arm and no counter. "Everything else" is not a synonym
for "transient": it includes `AttributeError`, `KeyError`, `TypeError`, an
`UnknownTopicOrPartitionError` after someone deletes `availability.events`, a
`MessageSizeTooLargeError`, a Redis `WRONGTYPE`/`OOM command not allowed` `ResponseError`, and
every programming bug that will ever be introduced into `engine.py` or `store.py`. None of
those will ever succeed on retry.

Iteration 2's defect was *skip the message* (silent loss). This iteration's is *never make
progress*, which for a single-partition topic is a total pipeline outage that nothing pages on:
the only symptom is `message_handling_failed` + `message_retry_scheduled` at 0.5 Hz, forever,
with no attempt number and no counter to alert from.

The second consequence is worse than the stall. When the permanent failure lands *after* a
slot's `send_and_wait` — the `_flush_slot` MULTI/EXEC is the live example — every retry
re-executes the emit: `set_nx_ex` returns False, `_crashed_mid_emit` reads a durable record that
is still PENDING (because `_discard()` threw the buffered write away), returns True, and the
event goes out again. Reproduced against the shipped code with `_flush_slot` raising a
permanent Redis `ResponseError`:

```
# real TRANSIENT_RETRY_BACKOFF_SECONDS = 2.0, 7 seconds of wall clock
ended: TimeoutError
kafka sends: 4          # one per retry, forever — ~43k duplicate events/day
commits: [1]            # offset 1 is never committed and never will be
deliveries: 5
```

Phase 4's Layer-2 key dedupes the *notification*, but nothing dedupes the topic, the analytics
insert attempt, or the log stream, and the partition never moves again.

**Fix:** Bound the retry and escalate to poison. Track attempts per `(tp, offset)`, and after N
tries log a distinct terminal event, commit, and move on (or produce to a dead-letter topic):

```python
MAX_TRANSIENT_ATTEMPTS = 10

        except Exception as exc:  # noqa: BLE001 — presumed transient infrastructure failure
            self._discard()
            key = (msg.topic, msg.partition, msg.offset)
            attempts = self._attempts.get(key, 0) + 1
            self._attempts = {key: attempts}      # only the head of a partition can be retried
            log.error(
                "message_handling_failed",
                topic=msg.topic, partition=msg.partition, offset=msg.offset,
                error=_failure_shape(exc), attempt=attempts,
            )
            if attempts >= MAX_TRANSIENT_ATTEMPTS:
                # Not transient after all. Stalling the partition forever is not a safer
                # failure than dropping one observation — it drops every LATER one too.
                log.error("message_retries_exhausted", topic=msg.topic,
                          partition=msg.partition, offset=msg.offset, attempts=attempts)
                await self._commit(msg)
                return
            self._retry_later(msg)
            return
```

Clear `self._attempts` on a successful `handle_message`, make the backoff exponential with
jitter (a flat 2.0 s puts every consumer in lockstep against a dependency that just came back),
and add a regression test that drives `run()` with a *permanently* failing dependency and
asserts the loop terminates and commits rather than spinning.

---

### CR-02: WR-08's boundary validation misses `AttributeError`, so a non-string `event_id` still reaches the retry-forever branch

**File:** `services/state_machine/models.py:103-116`; `services/state_machine/store.py:115`;
`tests/unit/test_engine_tristate_unknown.py:157-180`
**Severity:** BLOCKER

**Issue:** `SlotRecord.from_json` now validates with a bare `UUID(event_id)`. `UUID()` does not
raise `ValueError` for a non-string — it raises `AttributeError` from `hex.replace(...)`:

```
UUID(5)        -> AttributeError: 'int' object has no attribute 'replace'
UUID(['a'])    -> AttributeError: 'list' object has no attribute 'replace'
UUID(True)     -> AttributeError: 'bool' object has no attribute 'replace'
```

`RedisStateStore.get_slots:115` catches `(ValueError, KeyError, TypeError)`. `AttributeError` is
in none of them, so it escapes the store. Reproduced against the shipped code with a single
corrupt hash field:

```
ESCAPED get_slots: AttributeError 'int' object has no attribute 'replace'
```

From there it escapes `DiffEngine.process()`, hits `handle_message`'s blanket `except
Exception`, and — per CR-01 — the whole poll is rewound and retried against a record that can
never parse, forever. That is verbatim the outcome the WR-08 comment at `models.py:110-111`
claims it removed ("raised ValueError out of `process()`, into `handle_message`'s transient
branch, and the whole poll was retried forever against a record that can never parse").

The tests know about this and route around it. `test_an_unparseable_event_id_is_rejected_at_the_boundary`
parametrises a `"number"` case and writes `pytest.raises((ValueError, TypeError, AttributeError))`
— so the author saw the `AttributeError` — while the *store-level* test that actually proves the
drop, `test_a_corrupt_event_id_is_dropped_by_the_store_not_raised`, only uses `"broken"`, a
string, which raises `ValueError`. The one case that escapes is the one the end-to-end test
omits.

**Fix:** Make the boundary total, and widen the store's catch so a future validator cannot
reopen the hole:

```python
        # models.py, SlotRecord.from_json
        event_id = raw["e"]
        if event_id is not None:
            if not isinstance(event_id, str):
                raise ValueError(f"event_id must be a string, got {type(event_id).__name__}")
            UUID(event_id)
```

```python
        # store.py, RedisStateStore.get_slots
            except (ValueError, KeyError, TypeError, AttributeError):
```

Then extend `test_a_corrupt_event_id_is_dropped_by_the_store_not_raised` to run the same
parametrisation as the boundary test (`garbage`, `truncated`, `empty`, `number`), so every case
is proven to drop rather than raise.

---

### CR-03: `insert_event`'s `error=str(exc)` writes the booking token into the log stream

**File:** `services/state_machine/persistence.py:106-112` (and `:161-166`)
**Severity:** BLOCKER

**Issue:** CR-02 (iteration 2) was fixed in `consumer.py` only. `persistence.py` still does:

```python
    except Exception as exc:  # noqa: BLE001 — best effort: never block the emit or the commit
        log.error("availability_event_insert_failed", ..., error=str(exc))
```

SQLAlchemy's `StatementError.__str__` appends the statement **and its bound parameters**
(`hide_parameters` defaults to `False`), and `insert_event`'s parameter dict at `:78-96`
contains `"booking_token": event.booking_token`. Reproduced:

```
(builtins.Exception) value too long
[SQL: INSERT INTO availability_events (booking_token) VALUES (%(booking_token)s)]
[parameters: {'booking_token': 'SECRET-BOOKING-TOKEN-abc123'}]
```

Every DBAPI error raised during `session.execute` — a constraint violation, a type/length error,
a connection reset mid-statement wrapped as `OperationalError` — arrives as a `StatementError`
with the parameters attached. This is a strictly *worse* instance than the one CR-02 fixed:
`consumer.py`'s leak needed payload-shape drift to put a token in the wrong field, whereas here
the token is a bound parameter by construction on every single insert. It breaches the same
contract (`consumer.py:13`, T-02-03: "Logs carry ids and counts only — never a booking token")
and `shared/telemetry.py:23-28`'s `_redact_secrets` does not cover it (it matches env-var *key
names*, not values inside an `error` string).

`close_event:161-166` has the identical shape; its parameters are only ids and timestamps, so
the value at risk is lower, but the statement text still goes to the log.

**Fix:** Route both through the redactor `consumer.py` already has, or disable parameter
rendering at the engine:

```python
    # persistence.py — import the existing helper rather than growing a second one
    from services.state_machine.consumer import _failure_shape   # or move it to shared/
    ...
    except Exception as exc:  # noqa: BLE001
        log.error("availability_event_insert_failed", event_id=str(event.event_id),
                  restaurant_id=event.restaurant_id, error=_failure_shape(exc))
```

and, as defence in depth, `create_async_engine(url, ..., hide_parameters=True)` in
`shared/db.py:163` so no future `str(exc)` anywhere can render bound parameters. Extend
`tests/unit/test_logs_never_carry_payload.py` with a case that makes `insert_event` fail with a
`StatementError` carrying a sentinel token and asserts the sentinel is absent from the captured
logs — the existing tests cover only `consumer.py`, which is why this survived.

---

## Warnings

### WR-01: WR-04's percent-escaping does not make slot identity injective — `slot_key` is itself a lossy join

**File:** `shared/redis_keys.py:64-94`; `services/state_machine/models.py:52-55`;
`services/state_machine/README.md:154-161`
**Severity:** WARNING

**Issue:** `event_idempotency_key` now escapes each of its five components, and the docstring
(`:84-85`) and README (`:154`) both claim the result is injective: "two distinct tuples can never
render one key". That is true of the *tuple*, and irrelevant, because the `slot_key` element of
the tuple has already collapsed two distinct identities before the function is called.
`Slot.slot_key` is `f"{self.time_slot}|{self.seat_type or '-'}"`, and `time_slot` and
`seat_type` both come straight from the OpenTable response with only an `isinstance` check
(`parsers/opentable.py:149-154`, `_seating_types` does `str(s)`). Reproduced:

```
Slot(time_slot="19:00|bar", seat_type=None)   -> slot_key "19:00|bar|-"
Slot(time_slot="19:00",     seat_type="bar|-") -> slot_key "19:00|bar|-"
slot_key COLLIDE: True
claim key COLLIDE: True
```

The same collapsed `slot_key` is also the Redis **hash field**, so the two identities share one
`SlotRecord`, and it is the `slot_key` fed to `make_event_id`, so they share one `event_id` too.
`DiffEngine.last_collision_count` only counts slots that collide *within one parsed poll*, so
across polls this is silent. The escaping fix moved the ambiguity one layer down rather than
removing it, and the documentation now asserts a property the code does not have — which is the
failure mode WR-06 was about, reintroduced by the WR-04 fix.

**Fix:** Escape at the point the composite is built, not after:

```python
    # models.py
    from urllib.parse import quote

    @property
    def slot_key(self) -> str:
        """Redis hash field: percent-escaped `{time_slot}|{seat_type or '-'}` (D-36, WR-01)."""
        return f"{quote(self.time_slot, safe='')}|{quote(self.seat_type or '-', safe='')}"
```

Note this **does** change stored hash field names and, through `make_event_id`, every
`event_id` — so it must be done together with regenerating
`tests/fixtures/raw_streams/*.events.jsonl` and a documented Redis-state cutover, or deferred
with the constraint recorded honestly. Either way, correct the two places that currently claim
injectivity.

### WR-02: The `KNOWN CONSTRAINT` comment on `make_event_id` states a safety property that is false

**File:** `shared/events.py:38-50`
**Severity:** WARNING

**Issue:** The comment justifies leaving `make_event_id` unescaped with: "The residual risk is
bounded: the ambiguity needs `slot_key` and `first_poll_id`, and `first_poll_id` is a UUID
string, so no attacker-controlled value can straddle that boundary."

Both halves are wrong. The recipe is
`f"{source}:{restaurant_id}:{date}:{party_size}:{slot_key}:{first_poll_id}"`, and the ambiguity
does not need the `first_poll_id` boundary at all — `date`, `party_size` and `slot_key` are three
*adjacent* fields and all three come from the OpenTable response (`date_entry.get("date")`,
`_slot_party_size`, `time_slot`/`seatingTypes`), each isinstance-checked and nothing more.
Reproduced:

```
make_event_id('opentable', 42, '2026-05-01',   2,  '19:00|bar', 'pid')
make_event_id('opentable', 42, '2026-05-01:2', 19, '00|bar',    'pid')
both -> e4423afb-dbfa-5dd8-88f9-b23e332f2dad     # COLLIDE: True
```

Two distinct openings sharing one `event_id` means the second is deduped away by the Layer-2
key and never notified — the exact class of silent loss the original CR-01 was. A wrong comment
on a permanent identity recipe is worse than no comment: it is what the next engineer will
consult before deciding whether the recipe needs changing.

**Fix:** Replace the last three sentences with the truth — the components are adjacent,
payload-derived and unescaped, so collisions are constructible from response data alone; the
recipe is frozen only because the goldens and the `availability_events` rows encode it; and any
change must escape every component and regenerate the goldens in the same commit. Add a unit
test that pins the *known* collision so the constraint is executable rather than prose.

### WR-03: `close_event` renders the SQL statement into the log on every failure

**File:** `services/state_machine/persistence.py:161-166`
**Severity:** WARNING

**Issue:** Same shape as CR-03 with a lower-value payload: `error=str(exc)` on a SQLAlchemy
exception emits `[SQL: UPDATE availability_events SET ...] [parameters: ...]`. The parameters
here are an `event_id` and two timestamps, so no capability leaks, but the statement text in a
log line is still a contract breach ("ids and counts only") and it makes the failure line
unbounded in length.

**Fix:** Covered by CR-03's fix — route through `_failure_shape` and/or set
`hide_parameters=True` on the engine.

### WR-04: `test_emit_flush_ordering.py` uses an unfaithful consumer mock, emitting three `RuntimeWarning`s and an orphan timer per run

**File:** `tests/unit/test_emit_flush_ordering.py:87`, `:148-152`, `:200`
**Severity:** WARNING

**Issue:** `test_offset_commit_policy.py:44-48` explicitly patches the cursor methods and says
why: "seek/pause/resume are SYNCHRONOUS on AIOKafkaConsumer; leaving them as AsyncMock attributes
would make the shell's cursor calls silently return un-awaited coroutines." `test_emit_flush_ordering.py`
passes a bare `AsyncMock()` and does not. Every unit run reports it:

```
services/state_machine/consumer.py:233: RuntimeWarning: coroutine '_execute_mock_call' was never awaited
    self.consumer.seek(topic_partition, msg.offset)
services/state_machine/consumer.py:234: RuntimeWarning: ... self.consumer.pause(topic_partition)
```

Two consequences. The transient path in `test_a_crash_on_the_second_send_leaves_that_slot_pending_and_it_re_emits`
is a no-op that only *looks* exercised, so if the rewind ever regresses this test will not
notice; and `_retry_later` still schedules a real `call_later(2.0, ...)` against a loop
pytest-asyncio closes immediately after, leaving a handle holding a reference to the mock.
Warnings that are normal are warnings nobody reads — this is exactly how CR-01's `AttributeError`
would hide.

**Fix:** Apply the same three lines the offset test uses, and consider `filterwarnings = error`
for `RuntimeWarning` in `pyproject.toml` so an un-awaited coroutine fails the suite:

```python
    consumer = AsyncMock()
    consumer.seek = MagicMock()
    consumer.pause = MagicMock()
    consumer.resume = MagicMock()
```

### WR-05: The poller's `gather` still leaks a live sibling task when one loop raises

**File:** `services/poller/main.py:97-112`
**Severity:** WARNING

**Issue:** `run_until_signal(asyncio.gather(poll_loop(...), reaper_loop(...)))`. `asyncio.gather`
without `return_exceptions=True` completes as soon as one child raises and **does not cancel the
other**. In `run_until_signal:63-65` the `runner.done()` branch re-raises immediately, and the
`finally`'s `if not runner.done(): runner.cancel()` is therefore skipped. So when `poll_loop`
dies, `reaper_loop` is still running when the `finally` at `main.py:111-113` executes
`await producer.stop()` and `await r.aclose()` — the reaper then issues Lua calls against a
closed Redis and its exception is never retrieved.

This shape predates the WR-02 fix, but the fix rewrote exactly this expression and the new
`shared/shutdown.py` is where the cancellation policy now lives, so it belongs here.

**Fix:** Use a `TaskGroup` (3.11+) so a failing child cancels its siblings, or cancel explicitly
in `run_until_signal`'s `finally` regardless of `runner.done()` when `runner` is a `gather`
future. The `TaskGroup` form is the smaller change:

```python
            async def _both() -> None:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(poll_loop(scheduler, opentable, publisher))
                    tg.create_task(reaper_loop(scheduler))

            await run_until_signal(_both())
```

### WR-06: `_resume_partition` swallows only `KafkaError`, so any other failure leaves the partition paused forever with no log

**File:** `services/state_machine/consumer.py:259-266`
**Severity:** WARNING

**Issue:** `_resume_partition` is a `call_later` callback, so it runs outside any task and
outside `handle_message`'s handlers. It pops its handle *first* and then calls
`self.consumer.resume(tp)` under `except KafkaError: return`. Anything else — an
`AssertionError` from aiokafka's `SubscriptionState._assigned_state` (`assert self._subscription
is not None` / `assert ... assignment is not None`, both reachable during a stop/rebalance
race), or an `AttributeError` against a half-closed consumer — is not caught. The loop's default
exception handler logs it to the `asyncio` logger, not to structlog, and by then the handle has
already been removed from `_resume_handles`, so **nothing will ever try to resume that partition
again**. The service stays up, `getone()` blocks forever, and the only trace is an
`asyncio`-logger line that the structlog JSON pipeline does not format.

`_retry_later:235` has the narrower version of the same problem (`except (KafkaError,
ValueError)`; an `AssertionError` from `pause` escapes `handle_message` and terminates `run()`).

**Fix:** Catch broadly in a callback that has nowhere to propagate to, log through structlog,
and do not lose the retry:

```python
    def _resume_partition(self, topic_partition: TopicPartition) -> None:
        self._resume_handles.pop(topic_partition, None)
        try:
            self.consumer.resume(topic_partition)
        except KafkaError:
            return                      # reassigned elsewhere; nothing to resume
        except Exception as exc:        # noqa: BLE001 — a callback has no caller to raise to
            log.error("partition_resume_failed", topic=topic_partition.topic,
                      partition=topic_partition.partition, error=_failure_shape(exc))
```

Widen `_retry_later`'s tuple to `Exception` for the same reason.

### WR-07: `offset_commit_failed` is the one branch in `consumer.py` that still uses `str(exc)`

**File:** `services/state_machine/consumer.py:468-475`
**Severity:** WARNING

**Issue:** `_failure_shape` exists precisely so no branch reaches for `str(exc)` again — its
docstring says so at `:68` — and `_commit` is the one that still does. A `KafkaError` carries no
booking token, so the impact today is low, but broker error strings routinely carry hostnames,
ports and (with SASL configured in a later phase) principal names, and the value of the
`_failure_shape` discipline is that it is unconditional. A future reader copying the nearest
example copies the wrong one.

**Fix:** `error=_failure_shape(exc)`, and add the commit branch to
`test_logs_never_carry_payload.py` so the rule is enforced rather than remembered.

## Info

### IN-01: `_failure_shape`'s `loc` is payload-free only by accident of the current schema

**File:** `services/state_machine/consumer.py:81-85`
**Issue:** `error['loc']` is safe today because `AvailabilityRaw.raw_response` and
`request_params` are `dict[str, Any]`, which produces no nested errors. The moment either is
tightened to a real model, `loc` will contain payload-supplied dict keys and the redaction
silently weakens.
**Fix:** Note the dependency in the docstring, and cap the rendered `loc` to the top-level field
name (`error['loc'][0]`) if the schema is ever tightened.

### IN-02: The claim-key reshape has an unbounded-duplicate window at deploy time

**File:** `shared/redis_keys.py:93-94`
**Issue:** Claims written by the old build use `event:42:2026-05-01:2:19:00|bar:tok1`; the new
build looks up `event:42:2026-05-01:2:19%3A00%7Cbar:tok1`. For the 20-minute
`EVENT_IDEMPOTENCY_TTL_SECONDS` after the rollout, every in-flight claim misses and Layer-1
suppression is off. The `event_id` is unchanged so Layer-2 covers it, but the topic sees the
duplicates.
**Fix:** One line in the phase's deploy notes / `README.md` operational section.

### IN-03: `run_offset_mode` now resolves the partition twice

**File:** `scripts/replay_raw.py:373-375`
**Issue:** `resolve_partition` is called, then `fetch_offset_range` calls it again internally
(the comment at `:372` acknowledges this as "a validating no-op"). Each call builds and starts
its own `AIOKafkaAdminClient` and issues a `describe_topics`. Harmless in a CLI, but it is two
broker round trips and two connections where one would do.
**Fix:** Give `fetch_offset_range` a way to accept an already-resolved partition, or have it
return the resolved id.

### IN-04: `_resume_handles` is never pruned when a partition is revoked

**File:** `services/state_machine/consumer.py:138`, `:245-250`
**Issue:** Entries are removed only by `_resume_partition` firing or by `run()`'s `finally`.
A partition rewound and paused, then revoked by a rebalance before the timer fires, leaves its
`TopicPartition` key in the dict until the resume callback runs and no-ops. Bounded by the
partition count, so it is a tidiness issue rather than a leak.
**Fix:** Clear stale keys in a `ConsumerRebalanceListener`, or note that the dict is bounded by
the assignment size.

### IN-05: `run_until_signal` leaks installed signal handlers if `ensure_future` raises

**File:** `shared/shutdown.py:49-60`
**Issue:** The handlers are installed at `:50-55`, but the `try` whose `finally` removes them
does not start until `:61`. If `asyncio.ensure_future(main)` raises (a non-awaitable `main` — the
one way this is reachable), `SIGTERM`/`SIGINT` stay bound to `stop.set` for the rest of the
process, silently disarming the default disposition. `test_the_signal_handlers_are_removed_again`
covers only the happy path.
**Fix:** Move the two `ensure_future` calls inside the `try`, or install the handlers as the
first statement of the `try`.

### IN-06: The migration test's inner `finally` can mask the assertion that fired

**File:** `tests/integration/test_migration_0008.py:252-256`
**Issue:** The WR-07 fix is right, but the innermost `finally` runs `await conn.execute('DELETE
...')` before `await conn.close()`. If the failure that reached the `finally` was itself a
connection failure, the `DELETE` raises and replaces the original `AssertionError` — the same
class of buried-failure problem WR-07 set out to fix, one level down.
**Fix:** `with contextlib.suppress(Exception):` around the cleanup `DELETE`, or move it above
`conn.close()` inside its own `try`.

---

_Reviewed: 2026-09-05T07:58:30Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 3 (final) — iteration 1 at `02-REVIEW.iter1.md`, iteration 2 at `02-REVIEW.iter2.md`_
