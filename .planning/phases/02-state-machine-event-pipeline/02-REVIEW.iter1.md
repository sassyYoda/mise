---
phase: 02-state-machine-event-pipeline
reviewed: 2026-09-05T06:40:00Z
depth: standard
files_reviewed: 56
files_reviewed_list:
  - .env.example
  - Makefile
  - migrations/versions/0008_add_event_id_to_availability_events.py
  - ops/docker-compose.yml
  - scripts/replay_raw.py
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
  - tests/integration/test_state_machine_chaos.py
  - tests/integration/test_state_machine_e2e.py
  - tests/unit/factories.py
  - tests/unit/test_coverage_bounding.py
  - tests/unit/test_emission_idempotency.py
  - tests/unit/test_engine_purity.py
  - tests/unit/test_engine_transitions.py
  - tests/unit/test_engine_tristate_unknown.py
  - tests/unit/test_event_id_determinism.py
  - tests/unit/test_events_schema.py
  - tests/unit/test_kafka_consumer_config.py
  - tests/unit/test_no_inline_sleep.py
  - tests/unit/test_no_setnx_expire_pairs.py
  - tests/unit/test_parsers_opentable.py
  - tests/unit/test_redis_keys_phase2.py
  - tests/unit/test_replay_determinism.py
  - tests/unit/test_replay_zero_false_events.py
  - tests/unit/test_service_time_math.py
  - tests/unit/test_tracer_raw_to_event.py
findings:
  critical: 3
  warning: 15
  info: 7
  total: 25
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-09-05T06:40:00Z
**Depth:** standard
**Files Reviewed:** 56
**Status:** issues_found

## Summary

`ruff check .` and `mypy --strict shared/ services/` are both clean, the async-only bans
(`time.sleep(`, `import requests`, sync redis) hold across `services/`, `shared/` and `scripts/`,
and the guard tests (`test_engine_purity`, `test_no_inline_sleep`, `test_no_setnx_expire_pairs`)
are written to fail loudly rather than vacuously. The pure-core / imperative-shell split is real:
the engine reads no clock and draws no entropy.

That is where the good news stops. Two defects in the emit path break the single property this
phase exists to guarantee — *a confirmed opening is never lost* — and both were reproduced
against the shipped code, not merely reasoned about:

1. **CR-01** — the shipped OpenTable fixture (`seatingTypes: ["bar", "standard"]` sharing one
   `token`) makes two distinct slots collapse onto one Layer-1 claim key. Running the real
   `StateMachineConsumer` over that payload emits **one** event and silently discards the other
   (`emit_skipped_duplicate`), while `scripts/replay_raw.py` — which does not use claim keys —
   emits **two**. So the same input produces a different event stream in production and in
   replay, which also breaks the STATE-06 byte-identity claim.
2. **CR-02** — `_flush()` is message-wide, not per-emit. The first `Emit` in a poll makes every
   *other* slot's `AVAILABLE` record durable before those slots have been sent to Kafka. The
   `BufferedStateStore` docstring and the README crash table (rows 2 and 3, "Redis state:
   PENDING") are therefore false for every emit after the first in a multi-slot poll, and a
   SIGKILL in that window loses those openings permanently.

Both are masked by the test corpus: the e2e and chaos tests deliberately trim the fixture to a
single seating type ("so one poll pair means one event"), the persistence test bypasses the shell
and calls `insert_event` directly with *distinct* tokens, and every replay golden has exactly one
seating type per timeslot. The two-slots-in-one-poll case is asserted only below the shell.

Beyond the emit path: the offset is committed after *any* handler exception (not just poison
messages), `_commit` catches only one of the two rebalance exceptions aiokafka documents,
startup leaks resources on partial failure, the SQLAlchemy engine is never disposed, and
`CONFIRM_DELAY_MS` is documented in three places as an environment variable that no code reads.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Two seating types share one booking token, so one confirmed event is silently dropped

**File:** `services/state_machine/consumer.py:196-210`, `services/state_machine/engine.py:290`, `shared/redis_keys.py:63-65`

**Issue:** The Layer-1 claim key is
`event:{rid}:{date}:{party}:{booking_token or slot_key}`. It does **not** include the slot key.
`parse_opentable` fans one timeslot out into one `Slot` **per seating type**, all carrying the
*same* `token` from the payload (`services/state_machine/parsers/opentable.py:113-124`). The
shipped fixture is exactly this shape:

```python
# services/poller/sources/opentable/fixtures.py
{"time": "19:00", "seatingTypes": ["bar", "standard"], "token": "abc123-reservation-token"}
```

Both slots confirm on the same poll and produce two `Emit` decisions with two distinct
`event_id`s — but they compute the same claim key. The second `set_nx_ex` fails, and because
CR-02 has already flushed the second slot's record to `AVAILABLE`, `_crashed_mid_emit` returns
`False` and the emit is **skipped**, not re-sent. The event never reaches Kafka, never reaches
`availability_events`, and is never retried: the slot is now `AVAILABLE` in Redis, so every
subsequent poll takes the `_refresh_available` path.

Reproduced by driving the real `StateMachineConsumer._handle_raw` over two polls 9 s apart built
from `OPENTABLE_SUCCESS_RESPONSE`:

```
events sent  : 1
   seat_type= bar event_id= ce581f8b-cc85-59a6-8676-01d78ca747b4
claim keys   : ['event:42:2026-05-01:2:abc123-reservation-token']
durable state: {'19:00|bar': AVAILABLE, '19:00|standard': AVAILABLE}
db inserts   : 1
log          : emit_skipped_duplicate event_id=0d9198b1-... (the 'standard' slot)
```

`scripts/replay_raw.py` on the same input emits both events (it dedupes on `event_id`, not on a
claim key), so production and replay disagree — a direct STATE-06 violation. D-46's literal
wording (`token = booking_token or slot_key`) carries the same defect, so the decision text needs
amending alongside the code.

**Fix:** Make the claim key unique per slot cycle. The deterministic `event_id` already is
exactly that:

```python
# shared/redis_keys.py
def event_idempotency_key(event_id: str) -> str:
    """SET NX EX claim key for one emitted event; event_id is unique per slot cycle (D-46)."""
    return f"event:{event_id}"

# services/state_machine/consumer.py
claim_key = event_idempotency_key(str(event.event_id))
```

If the human-readable shape must be kept, include the slot key:
`f"event:{rid}:{date}:{party}:{slot_key}:{token}"`. Either way, add a unit test that drives
`_handle_raw` over the unmodified `OPENTABLE_SUCCESS_RESPONSE` and asserts **two** sends with two
distinct `event_id`s, and stop trimming `seatingTypes` in the e2e/chaos fixtures.

---

### CR-02: `_flush()` persists the whole message, so later slots are AVAILABLE before their Kafka send

**File:** `services/state_machine/consumer.py:229` and `264-267`; `services/state_machine/store.py:159-173`

**Issue:** `DiffEngine.process()` runs to completion first, so **all** of the message's state
writes are already sitting in the `BufferedStateStore` before any decision is applied. `_apply_emit`
then calls `self._flush()`, which flushes *every* buffered write — including the `AVAILABLE`
records of slots whose `send_and_wait` has not happened yet.

Reproduced with two independent slots (distinct tokens, so CR-01 is not in play), snapshotting the
durable store at the moment of each send:

```
at send of 19:00: durable state = {'19:00|bar': PENDING,   '20:00|bar': PENDING}
at send of 20:00: durable state = {'19:00|bar': AVAILABLE, '20:00|bar': AVAILABLE}   <-- already durable
```

A SIGKILL between those two lines leaves `20:00` durably `AVAILABLE` with an `event_id`, its claim
key unset, and its event never sent. On redelivery the engine reads `AVAILABLE`, takes
`_refresh_available`, and produces no `Emit` at all — the opening is lost for good. That is
verbatim the outcome `store.py:163-169` says `BufferedStateStore` exists to prevent, and it makes
README rows 2 and 3 ("Redis state: PENDING") false for every emit after the first. The chaos test
does not catch it because its fixture is trimmed to a single slot.

**Fix:** Flush only the slot being emitted, at its own step 3. Give `BufferedStateStore` a scoped
flush and have `_apply_emit` use it, leaving the message-wide flush for the tail of `_handle_raw`:

```python
# store.py
async def flush_slot(self, rid: int, date: str, party: int, key: str) -> None:
    rec = self._slots.pop((rid, date, party, key), _MISSING)
    if rec is _MISSING:
        return
    if rec is None:
        await self.inner.drop_slot(rid, date, party, key)
    else:
        await self.inner.put_slot(rid, date, party, key, rec)

# consumer.py, _apply_emit, replacing `await self._flush()`
if self.buffer is not None:
    await self.buffer.flush_slot(
        event.restaurant_id, decision.date, decision.party_size, decision.slot_key
    )
```

Then extend the chaos test to a two-slot poll with `MISE_CRASH_AFTER=kafka_send`, and assert that
after the restart **both** `event_id`s appear exactly once.

---

### CR-03: Migration 0008 unconditionally deletes every pre-existing `availability_events` row

**File:** `migrations/versions/0008_add_event_id_to_availability_events.py:33`

**Issue:**

```python
op.execute("DELETE FROM availability_events WHERE event_id IS NULL")
```

`event_id` was added `nullable=True` two lines earlier, so *every* existing row matches this
predicate. On any database where Phase 1 (or a manual backfill, or a partial Phase 2 run against a
pre-0008 schema) wrote rows, `alembic upgrade head` destroys the entire hypertable's contents with
no backup, no count, and no log. The comment asserts "the table is empty at this point" — that is
an assumption about one environment, enforced nowhere, and a migration that silently destroys data
when the assumption is wrong is not a safe migration.

**Fix:** Fail loudly instead of deleting; let the operator decide:

```python
count = op.get_bind().execute(
    sa.text("SELECT count(*) FROM availability_events")
).scalar_one()
if count:
    raise RuntimeError(
        f"availability_events holds {count} pre-0008 rows that cannot be backfilled with a "
        "deterministic event_id. Truncate deliberately, or backfill, then re-run 0008."
    )
```

---

## Warnings

### WR-01: The offset is committed after *any* handler exception, not just poison messages

**File:** `services/state_machine/consumer.py:112-130`

**Issue:** The blanket `except Exception` covers connection errors, Redis timeouts, broker
outages and producer failures — not only unparseable payloads. Every one of them discards the
buffered state and then commits the offset, so the message is never redelivered. For an
`availability.raw` message the next scheduled poll mostly heals the state, but for a
`polls.completed` `error`/`timeout` message the UNKNOWN mark is lost permanently, and any
`Close` that had not yet run is lost with it. The README frames this as poison-message handling;
the implementation does not distinguish poison from transient.

**Fix:** Commit only on decoding/parse failures; let infrastructure failures redeliver.

```python
except (ValidationError, ParseError) as exc:      # poison: log, discard, commit
    self._discard(); log.error("message_poison", ...)
except Exception as exc:                          # transient: do NOT commit
    self._discard()
    log.error("message_handling_failed", ..., error=str(exc))
    return                                        # skip the commit below
await self._commit(msg)
```

### WR-02: `_commit` catches only `CommitFailedError`, so a rebalance can kill the service

**File:** `services/state_machine/consumer.py:274-291`

**Issue:** The docstring says "A group rebalance mid-message makes this raise; log it and let
redelivery happen", but `AIOKafkaConsumer.commit` documents *two* rebalance outcomes:
`CommitFailedError` (membership changed) and `IllegalStateError` (**"If partitions not
assigned"**), plus a generic `KafkaError` for broker-side failures. `IllegalStateError` is a
sibling of `CommitFailedError` under `KafkaError`, not a subclass (verified). And `_commit` is
called *outside* `handle_message`'s try block, so an uncaught commit exception propagates through
`run()` and terminates the process.

**Fix:** `except (CommitFailedError, IllegalStateError, KafkaError) as exc:` — or catch
`KafkaError`, which covers all three.

### WR-03: A crash between the state flush and `insert_event` loses the analytics row forever

**File:** `services/state_machine/consumer.py:229-232`

**Issue:** Order is flush → `insert_event`. A crash (or the `state_write` hook) in that window
leaves the slot durably `AVAILABLE` and the Kafka event sent, but no DB row. On redelivery the
engine produces no `Emit`, so `insert_event` is never retried, and the later `Close` UPDATE
silently matches zero rows — the opening exists on the wire and in Redis but never in
`availability_events`. Best-effort persistence (D-48) covers a *failed* insert, not a
*never-attempted* one.

**Fix:** Move `insert_event` before the flush (it is idempotent via `ON CONFLICT DO NOTHING`, so
a duplicate attempt is harmless), or add a reconciliation path that inserts when a `Close`
UPDATE reports `rowcount == 0`.

### WR-04: `main.run()` leaks the Redis client, scheduler and producer when startup fails partway

**File:** `services/state_machine/main.py:76-102`

**Issue:** The module docstring claims "nested try/finally teardown", but there is exactly one
`try/finally`, and it starts at line 112 — after Redis, the scheduler, the producer and the
consumer have all been constructed. If `_assert_topics_exist` raises (the documented "missing
topic" path), the Redis connection is never closed; if `make_consumer` raises, the producer is
left started as well.

**Fix:** Wrap each acquisition in nested try/finally (or use `contextlib.AsyncExitStack`) so the
teardown matches the docstring.

### WR-05: The SQLAlchemy async engine is never disposed

**File:** `services/state_machine/main.py:112-118`, `shared/db.py:151-176`

**Issue:** `persistence.insert_event` / `close_event` create the module-global engine on first
use; nothing ever calls `await get_engine().dispose()`. On shutdown the asyncpg pool's
connections are garbage-collected against a closing loop, which produces "Event loop is closed" /
unclosed-connection noise and leaves server-side sessions to time out.

**Fix:** Add a `dispose_engine()` helper in `shared/db.py` and await it in `main.run()`'s
`finally`, alongside `r.aclose()`.

### WR-06: `CONFIRM_DELAY_MS` is documented as an environment variable but no code reads it

**File:** `shared/redis_keys.py:102`, `services/state_machine/README.md:183` and `:187`, `.env.example:14`

**Issue:** `.env.example` and the README's Environment table both present `CONFIRM_DELAY_MS` as a
tunable with a default of `8000`, and the README states "Every variable is read lazily, inside
`run()`". It is a hardcoded module constant; `os.getenv("CONFIRM_DELAY_MS")` appears nowhere.
Setting it in a deployment or a test silently does nothing, which is the most expensive class of
configuration bug to debug.

**Fix:** Either add `config.confirm_delay_ms()` reading the env with an 8000 default and pass it
to `DiffEngine`, or delete the entry from `.env.example` and mark the README row "compile-time
constant, not an environment variable".

### WR-07: Two independent confirm-delay constants — replay and production can silently diverge

**File:** `services/state_machine/models.py:17-19`, `scripts/replay_raw.py:47` and `:114`, `shared/redis_keys.py:102`

**Issue:** `models.DEFAULT_CONFIRM_DELAY_MS = 8_000` and `redis_keys.CONFIRM_DELAY_MS = 8_000`
are separate literals. Production (`main.py`) uses the second; `replay_raw.replay()` defaults to
the first. They agree today only by coincidence — the `models.py` comment openly says the
duplication exists to avoid an import edge that no longer conflicts. Changing one leaves every
golden file and the byte-identity test asserting a confirmation window production no longer uses.

**Fix:** Delete `DEFAULT_CONFIRM_DELAY_MS` and import `CONFIRM_DELAY_MS` from `shared.redis_keys`
in `replay_raw.py`; or, at minimum, add a unit test asserting the two are equal.

### WR-08: `effective_coverage` performs unguarded `int()` / `str()` conversions on untrusted payload data

**File:** `services/state_machine/parsers/opentable.py:35-39`

**Issue:** `int(parties[0])` raises `ValueError` or `TypeError` for a non-numeric or non-scalar
element, and neither is a `ParseError`. The file's own docstring says "one unhandled KeyError here
would halt the whole Kafka partition". The exception escapes `parse_raw`, bypasses the
`except ParseError` UNKNOWN path in `_handle_raw`, is swallowed by the blanket handler in
`handle_message`, and the offset is committed — so the restaurant is neither marked UNKNOWN nor
retried. `request_params` is producer-controlled data, not a validated schema.

**Fix:**

```python
try:
    party = int(parties[0])
except (TypeError, ValueError) as exc:
    raise ParseError("request_params.party_sizes[0] is not an integer") from exc
```

### WR-09: A poll with empty/unreadable `request_params` reports success while observing nothing

**File:** `services/state_machine/parsers/opentable.py:32-39`, `services/state_machine/engine.py:94`

**Issue:** When `dates` or `party_sizes` is missing or empty, `effective_coverage` returns an
empty frozenset, `fallback_party` is `None`, and `parse_opentable` returns a `ParsedPoll` with
**zero slots and zero coverage** — even when the payload was full of real slots. `process()` still
calls `mark_success`, clearing any UNKNOWN mark, and nothing is logged. A publisher regression
that drops `request_params` therefore renders the restaurant permanently blind while its meta
record reports perfect health.

**Fix:** Treat unbounded coverage as a `ParseError` (→ UNKNOWN), or at minimum emit a
`log.warning("poll_without_coverage", restaurant_id=..., poll_id=...)` and skip `mark_success`.

### WR-10: `RedisStateStore` mutations are two non-atomic round trips (HSET then EXPIRE)

**File:** `services/state_machine/store.py:119-127` and `140-156`

**Issue:** Every mutating call issues `HSET`/`HDEL` and then a separate `EXPIRE`, with no pipeline
or transaction. This is structurally the Pitfall-7 shape the repo bans elsewhere: if the process
dies (or the connection drops) between the two commands while the key is being created, the hash
is left with **no TTL** and never expires. `tests/unit/test_no_setnx_expire_pairs.py` only greps
for `.setnx(`, so it does not see this. It also doubles the round trips on the hot path.

**Fix:** Use a single pipeline/transaction:

```python
async def put_slot(self, rid, date, party, key, rec) -> None:
    state_key = avail_state_key(rid, date, party)
    async with self.r.pipeline(transaction=True) as pipe:
        pipe.hset(state_key, key, rec.to_json())
        pipe.expire(state_key, AVAIL_STATE_TTL_SECONDS)
        await pipe.execute()
```
(Keep the redis-py casts in `shared/redis_keys.py` per D-42.)

### WR-11: Replay silently reads only partition 0

**File:** `scripts/replay_raw.py:196-251` (`partition: int = 0`), called from `run_offset_mode:287`

**Issue:** `fetch_offset_range` hardcodes partition 0 and `run_offset_mode` never overrides it.
The README's scaling section explicitly contemplates raising the partition count later; the first
time that happens, `--from-offset` replays a fraction of the stream and exits 0 as though it had
replayed everything. Offsets are also per-partition, so `--from-offset N` means different messages
on different partitions.

**Fix:** Enumerate `consumer.partitions_for_topic(topic)` and assign all of them (or add a
required `--partition` flag), and refuse with a clear error when the topic has more than one
partition and no partition was named.

### WR-12: Malformed or tombstoned Kafka records crash the replay tool with a traceback

**File:** `scripts/replay_raw.py:267-270`

**Issue:** `json.loads(record.value.decode("utf-8"))` is unguarded. A non-JSON record raises
`JSONDecodeError` and a tombstone (`record.value is None`) raises `AttributeError`; `main()`
catches only `(InputError, OSError, ValidationError, KafkaError)`, so both escape as an unhandled
traceback. The documented exit-code contract ("1 — usage or I/O error") is not honoured, and the
`--input` path (which *does* wrap failures in `InputError`) behaves differently from the
`--from-offset` path for the same defect.

**Fix:** Wrap the decode and raise `InputError(f"{topic}[{record.offset}]: {exc}")`.

### WR-13: The production crash-hook guard fails open when `ENV` is unset

**File:** `services/state_machine/main.py:66-70`, `services/state_machine/config.py:57-64`

**Issue:** T-02-04's guard is `if crash_after() is not None and env_name() == "prod"`. `env_name()`
defaults to `"dev"`, so a production container that forgets `ENV`, or sets `ENV=production` /
`ENV=PROD`, starts happily with a `SIGKILL` hook armed on a live event pipeline. A safety
interlock should fail closed.

**Fix:** Invert it — allow the hook only on an explicit allowlist:

```python
if crash_after() is not None and env_name().lower() not in {"dev", "test", "ci"}:
    raise RuntimeError(...)
```

### WR-14: A malformed job descriptor is never released from `sched:polls:inflight`

**File:** `services/poller/scheduler.py:62-73`

**Issue:** The comment says "Don't re-enqueue malformed jobs — drop them from inflight", but the
`continue` does neither: the job stays in `sched:polls:inflight` with a 60 s visibility score.
`REAP_INFLIGHT_LUA` then re-enqueues it into `sched:polls` at `now_ms`, it is claimed again
immediately, warned about, and abandoned again — forever, on every reaper cycle, and each pass
also starves the queue of one claim slot.

**Fix:** Remove it explicitly, e.g. `await scheduler.drop(job)` (a `ZREM` on
`SCHED_POLLS_INFLIGHT` via a new `shared/scheduler/lua.py` method), and log at `error`.

### WR-15: Integration tests mutate `os.environ` without restoring it

**File:** `tests/integration/test_state_machine_chaos.py:102-105`, `tests/integration/test_state_machine_e2e.py:107-110`, `tests/integration/test_availability_events_persistence.py:56-58`

**Issue:** `KAFKA_BOOTSTRAP_SERVERS`, `REDIS_URL` and both `DATABASE_URL_*` are assigned into the
live process environment and never rolled back. Any later test in the same session that reads
those variables (or any service imported later) silently binds to a container that has already
been torn down — an order-dependent failure that only appears when the suite is run in a different
order or with `-p no:randomly` removed.

**Fix:** Use `monkeypatch.setenv` (function scope) or a fixture that snapshots and restores
`os.environ` around the module.

## Info

### IN-01: `SlotState.UNKNOWN` is never written, so the branch that tests for it is dead

**File:** `services/state_machine/models.py:28`, `services/state_machine/engine.py:110`

**Issue:** No code path ever constructs a `SlotRecord(state=SlotState.UNKNOWN)` — UNKNOWN lives on
`MetaRecord` per D-41. The `record.state in (SlotState.UNAVAILABLE, SlotState.UNKNOWN)` test can
never see UNKNOWN, and a hypothetical UNKNOWN record would also fall through both closure branches
in `process()` and persist forever.
**Fix:** Drop the enum member (documenting UNKNOWN as meta-only) or add an explicit closure branch.

### IN-02: The crash hook's environment read is duplicated

**File:** `services/state_machine/config.py:62-64`, `services/state_machine/consumer.py:53-60`

**Issue:** `config.crash_after()` and `consumer._crash_after()` are byte-identical readers of
`MISE_CRASH_AFTER`; `main.run()`'s guard consults only the first. Two readers of one safety-
critical variable is one too many.
**Fix:** Import `crash_after` from `config` in `consumer.py`.

### IN-03: `close_event` cannot tell "closed" from "row not found"

**File:** `services/state_machine/persistence.py:115-149`

**Issue:** The UPDATE's `rowcount` is discarded, so a close against a missing row (see WR-03) logs
`availability_event_closed` exactly as a successful one does.
**Fix:** `result = await session.execute(statement)` and log a warning when `result.rowcount == 0`.

### IN-04: `kafka-ui` is pinned to `:latest`, and the compose `version:` key is obsolete

**File:** `ops/docker-compose.yml:1`, `:74`

**Issue:** `provectuslabs/kafka-ui:latest` makes `make up` non-reproducible (and is the one image
in the file that is not pinned, in a phase whose whole point was pinning `bitnamilegacy/kafka:3.8`).
`version: "3.9"` is ignored by Compose v2 and emits a deprecation warning.
**Fix:** Pin a tag; delete the `version:` key.

### IN-05: `make lint` does not type-check `scripts/`

**File:** `Makefile:36-37`

**Issue:** `mypy shared/ services/` leaves `scripts/replay_raw.py` — 397 lines of code the
byte-identity guarantee depends on — outside `strict` checking.
**Fix:** `uv run mypy shared/ services/ scripts/`.

### IN-06: The chaos test's observation loop hammers Kafka with a new consumer group per pass

**File:** `tests/integration/test_state_machine_chaos.py:159-171`

**Issue:** For 45 s the loop calls `_drain_events`, which starts a fresh consumer with a unique
`group_id` each time and returns as soon as any record is available — so the loop spins, creating
tens of throwaway consumer groups and adding ~45 s of wall clock to every CI run.
**Fix:** Drain once, then `await asyncio.sleep(1)` between checks, and reuse a single consumer.

### IN-07: Two slots colliding on one `(time_slot, seat_type)` are collapsed silently

**File:** `services/state_machine/engine.py:65-75`

**Issue:** `_group_by_bucket` resolves the collision last-wins with no diagnostic. The resolution
is deterministic and documented, but the case is exactly the payload-shape surprise that the
`[ASSUMED]` OpenTable schema warns about, and it would disappear without a trace.
**Fix:** `log`-free core is correct; instead count collisions on `DiffEngine` and have the shell
log the count, as `last_close_count` already does.

---

_Reviewed: 2026-09-05T06:40:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
