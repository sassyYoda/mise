---
phase: 02-state-machine-event-pipeline
reviewed: 2026-09-05T07:22:33Z
depth: standard
iteration: 2
previous_review: .planning/phases/02-state-machine-event-pipeline/02-REVIEW.iter1.md
files_reviewed: 67
files_reviewed_list:
  - .env.example
  - Makefile
  - migrations/versions/0008_add_event_id_to_availability_events.py
  - ops/docker-compose.yml
  - pyproject.toml
  - scripts/replay_raw.py
  - scripts/seed_restaurants.py
  - services/poller/scheduler.py
  - services/state_machine/README.md
  - services/state_machine/__init__.py
  - services/state_machine/__main__.py
  - services/state_machine/config.py
  - services/state_machine/consumer.py
  - services/state_machine/engine.py
  - services/state_machine/main.py
  - services/state_machine/models.py
  - services/state_machine/parsers/__init__.py
  - services/state_machine/parsers/errors.py
  - services/state_machine/parsers/opentable.py
  - services/state_machine/persistence.py
  - services/state_machine/store.py
  - shared/db.py
  - shared/events.py
  - shared/kafka.py
  - shared/redis_keys.py
  - shared/scheduler/lua.py
  - tests/fixtures/raw_streams/flapping.events.jsonl
  - tests/fixtures/raw_streams/flapping.jsonl
  - tests/fixtures/raw_streams/happy.events.jsonl
  - tests/fixtures/raw_streams/happy.jsonl
  - tests/fixtures/raw_streams/transient_errors.events.jsonl
  - tests/fixtures/raw_streams/transient_errors.jsonl
  - tests/integration/conftest.py
  - tests/integration/test_availability_events_persistence.py
  - tests/integration/test_expedite_lua.py
  - tests/integration/test_migration_0008.py
  - tests/integration/test_poller_expedite_release.py
  - tests/integration/test_redis_state_store.py
  - tests/integration/test_replay_offset_range.py
  - tests/integration/test_scheduler_claim_release.py
  - tests/integration/test_state_machine_chaos.py
  - tests/integration/test_state_machine_e2e.py
  - tests/unit/factories.py
  - tests/unit/test_compose_images_are_pinned.py
  - tests/unit/test_confirm_delay_is_not_configurable.py
  - tests/unit/test_coverage_bounding.py
  - tests/unit/test_emission_idempotency.py
  - tests/unit/test_emit_flush_ordering.py
  - tests/unit/test_engine_purity.py
  - tests/unit/test_engine_transitions.py
  - tests/unit/test_engine_tristate_unknown.py
  - tests/unit/test_event_id_determinism.py
  - tests/unit/test_events_schema.py
  - tests/unit/test_kafka_consumer_config.py
  - tests/unit/test_no_inline_sleep.py
  - tests/unit/test_no_setnx_expire_pairs.py
  - tests/unit/test_offset_commit_policy.py
  - tests/unit/test_parsers_opentable.py
  - tests/unit/test_redis_keys_phase2.py
  - tests/unit/test_redis_state_store_atomicity.py
  - tests/unit/test_replay_determinism.py
  - tests/unit/test_replay_zero_false_events.py
  - tests/unit/test_service_time_math.py
  - tests/unit/test_slot_key_collisions.py
  - tests/unit/test_state_machine_startup.py
  - tests/unit/test_tracer_raw_to_event.py
  - tests/unit/test_two_seat_types_one_token.py
findings:
  critical: 2
  warning: 9
  info: 6
  total: 17
status: issues_found
---

# Phase 2: Code Review Report (iteration 2)

**Reviewed:** 2026-09-05T07:22:33Z
**Depth:** standard
**Files Reviewed:** 67
**Status:** issues_found

## Summary

Gates re-verified at HEAD: `uv run ruff check .` clean, `uv run mypy shared/ services/ scripts/`
clean (40 source files), `uv run pytest tests/unit -q` **228 passed**. The integration suite was
left to the concurrent agent.

**Verification of iteration 1, finding by finding.** Nineteen of the twenty-five are genuinely
fixed, and several were fixed better than the review asked for:

* **CR-01 — fixed.** `event_idempotency_key` now takes `slot_key` as a mandatory positional and
  produces `event:{rid}:{date}:{party}:{slot_key}:{token}`. `test_two_seat_types_one_token.py`
  drives the real `_handle_raw` over the *unmodified* `OPENTABLE_SUCCESS_RESPONSE` and pins two
  sends, two distinct `event_id`s, two claim keys, two `insert_event` calls and byte-identical
  agreement with `scripts/replay_raw.py`. Reproduced green.
* **CR-02 — fixed.** `BufferedStateStore.flush_slot` exists, `_apply_emit` calls it, the tail
  `_flush()` remains for drops/closures/meta, and `test_emit_flush_ordering.py` snapshots the
  durable store at each send. I traced the crash-mid-emit, re-open-within-TTL and
  discard-on-failure paths and found no new loss window.
* **CR-03 — fixed.** The `DELETE` is gone; `upgrade()` counts first and raises with an actionable
  message; the integration test asserts the row survives.
* **WR-02, WR-04..WR-08, WR-10..WR-14, IN-01..IN-07 — fixed**, with real behavioural guards
  (the `_RecordingRedis` transaction test for WR-10 and the AST-resolved replay import gate for
  WR-07 are both stronger than what was asked for).

That is where the good news stops. Two defects survive, and one of them is the finding that was
reported as fixed:

1. **CR-01 (this iteration)** — **WR-01 was not actually fixed.** Not committing a transiently
   failed message does not prevent it being skipped: `run()` immediately consumes the next
   message, and *that* message's `commit({tp: offset+1})` sets the group watermark past the
   failed offset. Reproduced against the shipped code — commits land at `1, 2, 4` with offset 2
   never redelivered. The new unit test only asserts `commit.await_count == 0` for a single
   message in isolation, so it tests around the defect. The `polls.completed` UNKNOWN mark is
   still lost permanently, exactly as iteration 1 described.
2. **CR-02 (this iteration)** — the WR-01 refactor introduced a named `message_poison` branch
   that logs `error=str(exc)` for a pydantic `ValidationError`. Pydantic v2 embeds
   `input_value=...` in that string, so raw payload content — including a `booking_token` —
   lands in the log. T-02-03 says logs carry ids and counts only. Reproduced.

Beyond those: WR-08's fix introduced a second, smaller payload echo (`int()`'s `ValueError`
message names the offending value and it is logged as `poll_unparseable reason=...`); the
AsyncExitStack from WR-04 and `dispose_engine` from WR-05 never run on the real shutdown path
because nothing handles SIGTERM; four now-dead non-atomic Redis helpers survive WR-10 and are
pinned alive by a test with a stale rationale; and the review's explicit instruction to stop
trimming `seatingTypes` in the e2e/chaos fixtures was not carried out, so CR-01 and CR-02 have
no integration-level proof against real Redis and a real SIGKILL.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: WR-01 is not fixed — a transiently failed message is still skipped permanently

**File:** `services/state_machine/consumer.py:104-109` and `:140-152`;
`services/state_machine/README.md:118-121`
**Severity:** BLOCKER

**Issue:** `handle_message` now returns without committing on a transient failure, and both the
docstring (`:149-150`, "leave the offset where it is so a restart reprocesses this message
instead of skipping it") and the README (`:118-121`, "so a restart reprocesses the message
rather than skipping it") assert that as a guarantee. It is not one. `run()` is:

```python
while True:
    msg = await self.consumer.getone()
    await self.handle_message(msg)
```

Not committing does not stop the consumer's *position* advancing. The very next message is
consumed and, on success, commits `its own offset + 1` — a value strictly greater than the
failed offset. `AIOKafkaConsumer.commit({tp: N})` sets the committed offset to `N`; it is not a
high-water merge, but it does not need to be, because the later offset is already higher. The
failed message ends up below the committed watermark and is never redelivered.

Reproduced against the shipped code (three restaurants, one `ConnectionError` raised from
`redis.set` on the confirming emit of restaurant 42, offset 2):

```
[ERROR] message_handling_failed offset=2 topic=availability.raw error='redis is down'
commits (next-offset): [1, 2, 4]
highest committed: 4
=> offset 2 is BELOW the committed watermark, so a restart never redelivers it
```

The outcome is byte-identical to the pre-fix behaviour the review flagged: for a
`polls.completed` `error`/`timeout` message the UNKNOWN mark is lost permanently and any `Close`
that had not yet run is lost with it. Only the last message before a process death is actually
retried.

`tests/unit/test_offset_commit_policy.py:84-124` asserts `consumer.commit.await_count == 0` for
one message handled in isolation. That is true and irrelevant: it never drives `run()`, never
handles a *subsequent* message, and therefore cannot observe the watermark moving past the
failure. This is the definition of testing around a defect.

**Fix:** Make the offset actually stay put. The minimal correct form is to rewind the partition
so redelivery happens in-process, and to back off so a persistent outage does not spin:

```python
        except Exception as exc:  # noqa: BLE001 — transient infrastructure failure
            self._discard()
            log.error(
                "message_handling_failed",
                topic=msg.topic, partition=msg.partition, offset=msg.offset, error=type(exc).__name__,
            )
            # Rewind so THIS message is the next one delivered. Returning without a commit is
            # not enough: the consumer position has already advanced, and the next successful
            # message commits an offset past this one.
            self.consumer.seek(TopicPartition(msg.topic, msg.partition), msg.offset)
            await asyncio.sleep(TRANSIENT_BACKOFF_SECONDS)
            return
```

Add a regression test that drives at least three messages through `handle_message` (or a
bounded `run()`), fails the middle one transiently, and asserts that no committed offset ever
exceeds the failed message's offset — or, with the `seek` fix, that the failed message is
re-delivered. Then correct `README.md:118-121` and the docstring to describe what the code
does.

---

### CR-02: The `message_poison` log leaks raw payload content, including booking tokens

**File:** `services/state_machine/consumer.py:130-139`
**Severity:** BLOCKER

**Issue:** The WR-01 refactor split out an explicit poison branch that logs `error=str(exc)`
where `exc` is a pydantic `ValidationError`. Pydantic v2's `__str__` embeds the *offending
input value* in the rendered message. The module docstring (`consumer.py:14`) states "Logs carry
ids and counts only — never a booking token and never a payload body (T-02-03)"; this line
violates it directly, and `availability.raw` is producer-supplied data whose `raw_response`
carries every `token` OpenTable returned.

Reproduced:

```
>>> AvailabilityRaw.model_validate_json(payload_with_string_raw_response)
ValidationError -> "1 validation error for AvailabilityRaw\nraw_response\n
  Input should be an object [type=dict_type, input_value='SECRET-BOOKING-TOKEN-abc123', input_type=str]"
```

That whole string is what goes into the structured log under `error=`. A booking token is a
capability — it is what holds the reservation — so this is a credential in the log stream, and
any payload-shape drift (a nested `token` field landing in the wrong type) puts it there
without anyone doing anything wrong.

**Fix:** Log the *shape* of the failure, never its input. Pydantic gives a structured form that
can be stripped:

```python
        except (ValidationError, ParseError) as exc:
            self._discard()
            detail = (
                [f"{'.'.join(str(x) for x in e['loc'])}:{e['type']}" for e in exc.errors()]
                if isinstance(exc, ValidationError)
                else type(exc).__name__
            )
            log.error(
                "message_poison",
                topic=msg.topic, partition=msg.partition, offset=msg.offset,
                error=detail,          # field paths and error types only — never input_value
            )
```

Add a unit test that feeds a payload containing a sentinel token, captures the emitted log line,
and asserts the sentinel does not appear anywhere in it. Apply the same treatment to
`message_handling_failed` (`:142-148`), where `str(exc)` on an arbitrary driver exception can
also carry a query or a URL with credentials.

---

## Warnings

### WR-01: WR-08's `ParseError` message echoes producer-controlled payload data into the logs

**File:** `services/state_machine/parsers/opentable.py:46-48`;
logged at `services/state_machine/consumer.py:163-168`
**Severity:** WARNING

**Issue:** `services/state_machine/parsers/errors.py:14` states the contract: "Messages name the
defect only and never carry the payload body, so they are safe to log." The WR-08 fix broke it:

```python
    except (TypeError, ValueError) as exc:
        raise ParseError(f"request_params.party_sizes[0] is not an integer: {exc}") from exc
```

`int()`'s `ValueError` names the value. Reproduced:

```
ParseError -> request_params.party_sizes[0] is not an integer: invalid literal for int() with base 10: 'SECRET-abc123-token'
```

`_handle_raw` logs it as `poll_unparseable reason=str(exc)`. Same class of defect as CR-02, one
field narrower.

**Fix:** Name the defect and the type, not the value:

```python
    except (TypeError, ValueError) as exc:
        raise ParseError(
            f"request_params.party_sizes[0] is not an integer (got {type(parties[0]).__name__})"
        ) from exc
```

### WR-02: Nothing handles SIGTERM, so the AsyncExitStack and `dispose_engine` never run on shutdown

**File:** `services/state_machine/main.py:69-146`; `shared/db.py:180-192`
**Severity:** WARNING

**Issue:** `grep -rn "SIGTERM\|add_signal_handler" services shared scripts ops Makefile` returns
exactly one hit, and it is a comment in `consumer.py` explaining why the *crash hook* uses
SIGKILL. `state_machine.run()` never returns; the only exits are an exception or a signal. On
SIGTERM — which is what `docker stop`, `make down`, a Kubernetes eviction and the chaos test's
own `restarted.terminate()` all send — Python's default disposition terminates the process
immediately, so the `AsyncExitStack` never unwinds: `consumer.stop()`, `producer.stop()`,
`r.aclose()` and `dispose_engine()` are all skipped.

That makes WR-04 and WR-05 half-fixes. WR-04's stated scope was partial *startup* failure and it
delivers that. WR-05's was shutdown, and `shared/db.py:184` now asserts "Every long-running
service must await this on shutdown" — a requirement the service structurally cannot meet. The
in-flight producer batch (`linger_ms=20`) is also dropped rather than flushed.

**Fix:** Install a handler in `run()` and let the stack unwind:

```python
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, stop.set)
            ...
            runner = asyncio.create_task(state_machine.run())
            await asyncio.wait({runner, asyncio.create_task(stop.wait())},
                               return_when=asyncio.FIRST_COMPLETED)
            runner.cancel()
```

`services/poller/main.py` has the same gap, so the fix belongs in both entry points.

### WR-03: WR-10 left four dead non-atomic Redis helpers exported, and a test keeps them alive

**File:** `shared/redis_keys.py:88-110`; `tests/unit/test_redis_keys_phase2.py:127-133`
**Severity:** WARNING

**Issue:** WR-10 replaced every mutating call with `hset_slot_with_ttl` / `hdel_slot_with_ttl` /
`hset_meta_with_ttl`. Verified by grep, `hset_slot`, `hdel_slot`, `hset_meta` and `expire_key`
now have **zero** callers outside `shared/redis_keys.py` itself — only `hgetall_slots` is still
used. They are exactly the primitives whose pairwise use `shared/redis_keys.py:113-119` now
declares banned ("A mutation followed by a SEPARATE EXPIRE is the same non-atomic shape this
repo bans for SETNX+EXPIRE"), left in place as a two-line route back to the defect, and
`test_no_setnx_expire_pairs.py` only greps for `.setnx(` so it would not catch a reintroduction.

Worse, `test_hash_helpers_are_exported_so_store_needs_no_casts` asserts all five remain callable,
so a future cleanup pass will be told the dead code is load-bearing. Its docstring rationale
("D-42 / Pitfall 3: every cast lives in one module") is now satisfied by the `_with_ttl`
helpers, not by these.

**Fix:** Delete `hset_slot`, `hdel_slot`, `hset_meta` and `expire_key`; drop them from the
module's `Named symbols` docstring (`:8`); and rewrite the test to assert the *surviving*
surface:

```python
    for name in ("hgetall_slots", "hset_slot_with_ttl", "hdel_slot_with_ttl", "hset_meta_with_ttl"):
        assert callable(getattr(rk, name))
    for gone in ("hset_slot", "hdel_slot", "hset_meta", "expire_key"):
        assert not hasattr(rk, gone), f"{gone} is the non-atomic shape WR-10 removed"
```

### WR-04: The claim key concatenates untrusted fields with an unescaped `:`, so identities can still collide

**File:** `shared/redis_keys.py:64-77`
**Severity:** WARNING

**Issue:** `f"event:{restaurant_id}:{date}:{party_size}:{slot_key}:{token}"` where `slot_key` is
`f"{time_slot}|{seat_type or '-'}"` and both `time_slot`, `seat_type` and `token` come straight
from the payload (`parsers/opentable.py:136-149` only checks `isinstance(..., str)`). Because the
separator is not escaped and appears inside the values, two *distinct* slot identities can
produce one key — e.g. `slot_key="19:00|bar", token="a:b"` and `slot_key="19:00|bar:a",
token="b"` both render `event:42:D:2:19:00|bar:a:b`.

The consequence today is bounded rather than fatal, because `_crashed_mid_emit` reads the durable
record, finds it PENDING and re-sends instead of skipping — but that is an accident of the
recovery path, not a property of the key, and it is the same class of silent identity collapse
CR-01 was. The unit test at `test_redis_keys_phase2.py:125` even pins the ambiguity
(`event_idempotency_key(0, "", 0, "", "") == "event:0::0::"`).

**Fix:** Make the key injective. Either hash the tuple, or percent-escape each component:

```python
from urllib.parse import quote

def event_idempotency_key(restaurant_id, date, party_size, slot_key, token) -> str:
    parts = (str(restaurant_id), date, str(party_size), slot_key, token)
    return "event:" + ":".join(quote(p, safe="") for p in parts)
```

Add a property test asserting distinct component tuples never collide. `make_event_id`
(`shared/events.py:39`) has the identical shape and the same argument applies, but changing it
would invalidate every committed golden — so at minimum record the constraint there in a comment.

### WR-05: The review's integration-coverage instruction for CR-01/CR-02 was not carried out

**File:** `tests/integration/test_state_machine_chaos.py:47-50`;
`tests/integration/test_state_machine_e2e.py:55-65`
**Severity:** WARNING

**Issue:** Iteration 1 asked, in the CR-01 fix text, to "stop trimming `seatingTypes` in the
e2e/chaos fixtures", and in the CR-02 fix text to "extend the chaos test to a two-slot poll with
`MISE_CRASH_AFTER=kafka_send`, and assert that after the restart **both** `event_id`s appear
exactly once." Neither happened. Both fixtures still do:

```python
payload["data"]["availability"][0]["availability"][0]["timeSlots"][0]["seatingTypes"] = ["bar"]
```

with the chaos docstring still reading "so one poll pair means one event". Every proof that
per-slot claiming and per-slot flushing work is a unit test running against `MemoryStateStore`
and an `AsyncMock` producer with a hand-rolled `FakeRedis` that implements only `set`. The
multi-slot emit path has never been exercised against real Redis (where `flush_slot` issues a
real MULTI/EXEC per slot), a real broker, or a real SIGKILL — which is precisely the combination
CR-01 and CR-02 lived in.

**Fix:** Add one chaos case that keeps both seating types and arms `MISE_CRASH_AFTER=kafka_send`
(so the process dies between slot 1's send and slot 2's claim), then asserts after restart that
both `event_id`s appear exactly once on `availability.events` and both rows exist in
`availability_events`. Keep the single-seating-type case for the "exactly one event, exactly one
row" claim it pins.

### WR-06: `.env.example` still documents the crash-hook interlock as the `ENV=prod` check WR-13 removed

**File:** `.env.example:18`
**Severity:** WARNING

**Issue:**

```
# services/state_machine/main.py refuses to start when this is set and ENV=prod (T-02-04).
```

WR-13 replaced that denylist with `CRASH_HOOK_ENVS = {"dev","test","ci","local"}` and
`crash_hook_allowed()`, which refuses *everything else* including unset, blank, `staging` and
`production`. `services/state_machine/README.md:224-225` was updated; `.env.example` was not.
This is the same failure mode WR-06 itself was about — documentation asserting a behaviour the
code does not have — reintroduced by the WR-13 fix, and it is documentation about a safety
interlock, which is the worst place for it. An operator reading only this line would conclude
`ENV=staging` is a supported way to run with the hook armed.

**Fix:** Replace the line with the allowlist wording used in the README, and extend
`test_the_env_example_documents_the_confirmation_window_and_the_crash_hook`
(`tests/unit/test_replay_determinism.py:278`) to assert the banner names the allowlist rather
than `ENV=prod`.

### WR-07: The migration tests downgrade a shared schema and restore it outside their failure path

**File:** `tests/integration/test_migration_0008.py:163-197` and `:200-246`
**Severity:** WARNING

**Issue:** Both `test_downgrade_then_upgrade_restores_the_same_schema` and the new CR-03 guard
`test_a_non_empty_table_is_refused_not_deleted` run `alembic downgrade -1` against the
module-scoped container and then restore with `apply_migrations(env)` **after** their assertions,
not in a `try/finally`. Any assertion failure inside — for instance line 232's
`assert failed.returncode != 0`, which is exactly what fails if someone reintroduces the
`DELETE` — leaves the module's database at revision 0007 with no `event_id` column. Every later
test in the module (`test_event_id_column_is_uuid_not_null`, `test_unique_index_covers_...`,
`test_b3_guard_...`) then fails for an unrelated reason, burying the actual failure. The module
has no ordering guarantee, so which tests are collateral damage varies.

**Fix:** Wrap the downgrade in a fixture or `try/finally` that always re-applies head:

```python
    try:
        ...assertions...
    finally:
        await conn.execute('DELETE FROM availability_events WHERE "time" = $1', legacy_time)
        await conn.close()
        apply_migrations(env)          # always, even when an assertion failed
```

### WR-08: `_close` parses a stored `event_id` with an unguarded `UUID()` inside the pure core

**File:** `services/state_machine/engine.py:329-334`; `services/state_machine/models.py:99-110`
**Severity:** WARNING

**Issue:** `SlotRecord.from_json` accepts `event_id` as an arbitrary string with no validation;
`_close` then does `UUID(record.event_id)`. A corrupt or truncated hash field (the case
`RedisStateStore.get_slots:115` explicitly anticipates for *other* fields, dropping them with a
`slot_record_unreadable` warning) raises `ValueError` from inside `DiffEngine.process()`. That
escapes to `handle_message`'s blanket `except Exception`, takes the transient branch and —
per CR-01 above — the whole poll is silently dropped and never redelivered, for a single bad
character in one hash field.

It also breaks the module's own contract: `engine.py:4-7` claims the core "performs no I/O of any
kind" and is deterministic, but it is the only place that can raise on stored-data shape.

**Fix:** Validate at the boundary where the other fields already are, so a corrupt record is
dropped rather than fatal:

```python
    # models.py, SlotRecord.from_json
    event_id = raw["e"]
    if event_id is not None:
        UUID(event_id)          # raises ValueError -> get_slots drops the field, slot re-cycles
```

Alternatively guard in `_close` and return `None` (the branch for "no event id" already exists at
`engine.py:329`), logging the count from the shell as `last_close_count` does.

### WR-09: `effective_coverage`'s docstring now contradicts the caller WR-09 changed

**File:** `services/state_machine/parsers/opentable.py:32` vs `:110-114`
**Severity:** WARNING

**Issue:** The helper's docstring still promises "Returns an empty set when either list is empty
— an unbounded poll closes nothing." Since the WR-09 fix, `parse_opentable` turns that same
empty set into a `ParseError`, so an unbounded poll does not "close nothing" — it observes
nothing at all, marks the restaurant UNKNOWN, and drops every slot in a payload that may have
been full of real ones. That is the behaviour the review asked for, but the function's contract
now describes the opposite of what the module does with it, and the next reader will reuse
`effective_coverage` believing the empty set is benign.

**Fix:** Change the line to "Returns an empty set when either list is empty; `parse_opentable`
treats that as a `ParseError` (unbounded coverage is UNKNOWN, not a successful observation of
nothing) — see D-39." One sentence, no code change.

## Info

### IN-01: The `ParseError` arm of `handle_message`'s poison handler is unreachable

**File:** `services/state_machine/consumer.py:130`
**Issue:** `parse_raw` is the only `ParseError` source and `_handle_raw:158-169` already catches
it. `_handle_completed` does not parse. So `except (ValidationError, ParseError)` can only ever
fire on `ValidationError`, and the `ParseError` name suggests a routing that does not exist.
**Fix:** Drop `ParseError` from the tuple, or add a comment noting it is defence-in-depth for a
future parser called outside `_handle_raw`.

### IN-02: `_assert_topics_exist` and `topic_partitions` leak their admin client when `start()` raises

**File:** `services/state_machine/main.py:56-61`; `scripts/replay_raw.py:211-216`
**Issue:** Both do `await admin.start()` and only then enter `try/finally`. A broker that accepts
the socket and then fails the metadata handshake leaves the client's connections open — the same
shape WR-04 fixed one level up.
**Fix:** Move `start()` inside the `try`, or use `contextlib.AsyncExitStack`.

### IN-03: The new scheduler integration tests leak Redis connections

**File:** `tests/integration/test_scheduler_claim_release.py:79-108` and `:111-127`
**Issue:** Every pre-existing test in the file ends with `await r.aclose()`; neither WR-14 test
does, and `test_a_malformed_job_left_in_flight_is_resurrected_by_the_reaper` also does its ZSET
cleanup outside any `finally`, so a failed assertion leaves `sched:polls` seeded for the next
test in the module.
**Fix:** Add `await r.aclose()` and move the cleanup into `try/finally` (or into a fixture).

### IN-04: `run_offset_mode`'s "nothing to replay" message hides the partition it actually read

**File:** `scripts/replay_raw.py:369`
**Issue:** `where = topic if partition is None else f"{topic}[p{partition}]"` uses the *requested*
partition, not the one `resolve_partition` settled on. In the common single-partition case the
flag is omitted, so the exit-2 diagnostic never names the partition — which is the one fact WR-11
exists to make explicit.
**Fix:** Have `fetch_offset_range` return the resolved partition (or resolve it in
`run_offset_mode`) and print that.

### IN-05: `DiffEngine.last_close_count` is assigned only at the end of `process()`

**File:** `services/state_machine/engine.py:96-97`, `:106`, `:154`
**Issue:** `last_collision_count` is set early and `last_close_count` at the end, so an exception
mid-`process()` leaves a fresh collision count paired with the *previous* poll's close count.
Benign today (the shell reads both only after a successful `process()`), but the two counters
having different reset points is a latent trap for the Phase 3 canary that will consume them.
**Fix:** Reset both to `0` on the first line of `process()`.

### IN-06: `test_hash_helpers_are_exported_so_store_needs_no_casts` has a stale rationale

**File:** `tests/unit/test_redis_keys_phase2.py:127-133`
**Issue:** The docstring justifies the assertion with "every cast lives in one module", which is
now satisfied by the `_with_ttl` helpers the store actually calls. As written the test documents
the wrong invariant. Folded into the fix for WR-03.
**Fix:** See WR-03.

---

_Reviewed: 2026-09-05T07:22:33Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2 — iteration 1 preserved at `02-REVIEW.iter1.md`_
