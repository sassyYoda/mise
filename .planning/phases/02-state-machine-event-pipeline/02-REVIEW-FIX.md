---
phase: 02-state-machine-event-pipeline
fixed_at: 2026-09-05T09:05:00Z
review_path: .planning/phases/02-state-machine-event-pipeline/02-REVIEW.md
iteration: 1
findings_in_scope: 25
fixed: 25
skipped: 0
status: all_fixed
---

# Phase 2: Code Review Fix Report

**Fixed at:** 2026-09-05T09:05:00Z
**Source review:** `.planning/phases/02-state-machine-event-pipeline/02-REVIEW.md`
**Iteration:** 1

**Summary:**

| Severity | In scope | Fixed | Deferred |
|----------|----------|-------|----------|
| Critical | 3 | 3 | 0 |
| Warning | 15 | 15 | 0 |
| Info | 7 | 7 | 0 |
| **Total** | **25** | **25** | **0** |

Every finding was fixed. One purely documentary follow-up is deferred with a reason at the
bottom (amending the D-46 decision text in `02-CONTEXT.md`).

**Gates, all green after the last commit:**

| Gate | Result |
|------|--------|
| `uv run ruff check .` | All checks passed |
| `uv run mypy shared/ services/ scripts/` | Success: no issues found in 40 source files |
| `uv run pytest tests/unit -q` | **228 passed** (was 156) |
| `uv run pytest tests/integration -q -p no:cacheprovider` | **62 passed** (was 52) |

The replay goldens in `tests/fixtures/raw_streams/*.events.jsonl` are **byte-for-byte
unchanged** — see "Goldens" below.

---

## Fixed Issues

### CR-01: Two seating types share one booking token, so one confirmed event is silently dropped

**Files modified:** `shared/redis_keys.py`, `services/state_machine/consumer.py`,
`services/state_machine/README.md`, `tests/unit/test_emission_idempotency.py`,
`tests/unit/test_redis_keys_phase2.py`, `tests/unit/test_two_seat_types_one_token.py` (new)
**Commit:** `54372b1`

The Layer-1 claim key became `event:{rid}:{date}:{party}:{slot_key}:{token}` — the
human-readable variant the review offered, keeping `booking_token` in the key as data while
`slot_key` carries the identity `seat_type` contributes under D-36. Still one atomic
`SET … NX EX 1200`; `EVENT_IDEMPOTENCY_TTL_SECONDS` is untouched.

`tests/unit/test_two_seat_types_one_token.py` drives the real
`StateMachineConsumer._handle_raw` over the **unmodified** `OPENTABLE_SUCCESS_RESPONSE`
(`seatingTypes: ["bar", "standard"]`, one shared token) across two polls 9 s apart and asserts:
two `send_and_wait` calls with two distinct `event_id`s and one shared `booking_token`, two
`insert_event` calls, two distinct claim keys, and that `scripts/replay_raw.py` produces the
same two events **byte for byte** from the same input. Mutation-checked: reverting the key to
the token-only form fails three of its four tests.

`services/state_machine/README.md` documents the new key shape in both the emit-ordering
diagram and the Redis-keys table, with the reason.

### CR-02: `_flush()` persists the whole message, so later slots are AVAILABLE before their Kafka send

**Files modified:** `services/state_machine/store.py`, `services/state_machine/consumer.py`,
`services/state_machine/README.md`, `tests/unit/test_emit_flush_ordering.py` (new)
**Commit:** `446c975`

`BufferedStateStore.flush_slot()` makes exactly one slot durable; `_apply_emit` calls it
instead of the message-wide `_flush()`. The tail flush in `_handle_raw` still runs, for the
buffered writes no `Emit` covers (drops, closures, meta).

`tests/unit/test_emit_flush_ordering.py` snapshots the durable store at the moment of each
`send_and_wait` and asserts a later slot is still `PENDING` there; a second test kills the
producer on the **second** slot's send, asserts that slot survives the crash as `PENDING`, and
asserts a clean restart over the same durable state re-emits exactly it. Mutation-checked:
restoring the message-wide flush fails both.

**README crash table updated to match what the code guarantees.** The table now says
explicitly that it is *per slot*, and a new note explains why step 3 is scoped to one slot and
what a message-wide flush would have made false (rows 2 and 3, for every emit after the first).

### CR-03: Migration 0008 unconditionally deletes every pre-existing `availability_events` row

**Files modified:** `migrations/versions/0008_add_event_id_to_availability_events.py`,
`tests/integration/test_migration_0008.py`
**Commit:** `f77921c`

The `DELETE` is gone. `upgrade()` now runs `SELECT count(*) FROM availability_events` **before**
adding the column and raises a `RuntimeError` naming the row count and the two ways out
(archive + truncate deliberately, or backfill `event_id` yourself). Backfilling automatically is
not possible: `event_id` is uuid5 over `(source, rid, date, party, slot_key, first_poll_id)`
(D-45) and a pre-0008 row records neither `slot_key` nor `first_poll_id`.

`downgrade()` is unchanged and correct; its docstring now records that dropping `event_id` is
lossy, so a later upgrade will refuse until the rows are dealt with.

A new integration test downgrades, inserts a pre-0008 row, asserts `alembic upgrade head`
**fails** with the explicit message, asserts the row is **still there** afterwards, and restores
the schema.

### WR-01: The offset is committed after *any* handler exception, not just poison messages

**Files modified:** `services/state_machine/consumer.py`, `services/state_machine/README.md`,
`tests/unit/test_offset_commit_policy.py` (new)
**Commit:** `de8c498`

`handle_message` splits `except (ValidationError, ParseError)` (poison — log, discard, commit)
from `except Exception` (transient — log, discard, **return without committing**). README's
poison-message paragraph now describes both cases.

### WR-02: `_commit` catches only `CommitFailedError`, so a rebalance can kill the service

**Files modified:** `services/state_machine/consumer.py`, `tests/unit/test_offset_commit_policy.py`
**Commit:** `d7eafc7`

Catches `KafkaError`, which covers `CommitFailedError`, `IllegalStateError` and broker errors.
The exception hierarchy the fix depends on was verified at runtime and is pinned by a test.

### WR-03: A crash between the state flush and `insert_event` loses the analytics row forever

**Files modified:** `services/state_machine/consumer.py`, `services/state_machine/README.md`,
`tests/unit/test_emit_flush_ordering.py`
**Commit:** `c8e183b`

`insert_event` moved **before** the per-slot flush; it is idempotent via
`ON CONFLICT (event_id, "time") DO NOTHING`, so a duplicate attempt is free. README's diagram
swaps steps 3 and 4. This composes with CR-02 rather than conflicting with it: the guarantee
CR-02 restores is that a slot's record is not durable before *its own* send, which per-slot
flushing gives regardless of where the INSERT sits.

### WR-04: `main.run()` leaks the Redis client, scheduler and producer when startup fails partway

**Files modified:** `services/state_machine/main.py`, `tests/unit/test_state_machine_startup.py` (new)
**Commit:** `6cfad2d`

`AsyncExitStack`, with each resource registered the moment it exists. LIFO unwinding is
consumer → producer → Redis, matching the previous `finally`. Tests drive both partial-startup
failures the review named.

### WR-05: The SQLAlchemy async engine is never disposed

**Files modified:** `shared/db.py`, `services/state_machine/main.py`,
`tests/unit/test_state_machine_startup.py`
**Commit:** `5fb0453`

`shared.db.dispose_engine()` closes the pool and drops both singletons; it is a no-op with no
engine and safe to call twice. Registered on the exit stack *before* anything is acquired, so
LIFO disposes it last, against a live loop.

### WR-06: `CONFIRM_DELAY_MS` is documented as an environment variable but no code reads it

**Files modified:** `.env.example`, `services/state_machine/README.md`,
`tests/unit/test_confirm_delay_is_not_configurable.py` (new), `tests/unit/test_replay_determinism.py`
**Commits:** `8b7679b`, `76aa3b1`

Took the *delete the documentation* branch rather than the *add the env read* branch: the
replay goldens are only goldens if the confirmation window cannot be changed from the shell
running the replay. `.env.example` replaces the assignment with a note; the README row says
plainly that it is a compile-time constant.

`76aa3b1` corrects an existing test that pinned the literal line `CONFIRM_DELAY_MS=8000` — i.e.
it asserted the defect. It now asserts the window is still *explained* to an operator but never
as an assignment; the `MISE_CRASH_AFTER` "TEST ONLY" banner check is untouched. (`8b7679b` left
that test red for one commit; `76aa3b1` is the immediate follow-up.)

### WR-07: Two independent confirm-delay constants — replay and production can silently diverge

**Files modified:** `services/state_machine/models.py`, `scripts/replay_raw.py`,
`tests/unit/test_confirm_delay_is_not_configurable.py`, `tests/unit/test_replay_determinism.py`
**Commit:** `5377f6a`

`DEFAULT_CONFIRM_DELAY_MS` deleted; `replay_raw.py` imports `shared.redis_keys.CONFIRM_DELAY_MS`.

That tripped the existing replay import gate, which banned any import line *containing the
substring* `redis`. The gate was **sharpened, not relaxed**: it now resolves imported modules
from the AST and bans the `redis`/`sqlalchemy`/`asyncpg`/`psycopg` client libraries by root
module (`shared.redis_keys` is a pure constants module that imports the client only under
`TYPE_CHECKING`), and additionally bans constructing a client by any other route
(`from_url`, `create_async_engine`, `AIOKafkaProducer`, `get_engine`). Mutation-checked against
five separate violations, all of which it catches.

### WR-08: `effective_coverage` performs unguarded `int()` / `str()` conversions on untrusted payload data

**Files modified:** `services/state_machine/parsers/opentable.py`, `tests/unit/test_coverage_bounding.py`
**Commit:** `c258219`

`int(parties[0])` is guarded and re-raised as `ParseError`. Non-string dates are refused for the
mirror-image reason: `str()` never raises, so an int or a dict date silently became a coverage
entry matching no stored slot. A numeric string party size is still accepted.

### WR-09: A poll with empty/unreadable `request_params` reports success while observing nothing

**Files modified:** `services/state_machine/parsers/opentable.py`, `tests/unit/test_coverage_bounding.py`
**Commit:** `6196b69`

Took the stronger branch: `parse_opentable` raises `ParseError` on empty coverage, routing to
the D-39 UNKNOWN path (nothing removed, nothing closed, nothing emitted, UNKNOWN mark not
cleared). `effective_coverage`'s documented "empty set for an empty list" contract is unchanged,
so the existing coverage-bounding tests are untouched. The now-unreachable `fallback_party is
None` branch is gone. No fixture in `tests/fixtures/raw_streams/` has empty `request_params`, so
no golden is affected.

### WR-10: `RedisStateStore` mutations are two non-atomic round trips (HSET then EXPIRE)

**Files modified:** `shared/redis_keys.py`, `services/state_machine/store.py`,
`tests/unit/test_redis_state_store_atomicity.py` (new)
**Commit:** `ba8a0b2`

`hset_slot_with_ttl` / `hdel_slot_with_ttl` / `hset_meta_with_ttl`, each a single MULTI/EXEC,
with the redis-py casts staying in `shared/redis_keys.py` per D-42. The new guard is
behavioural rather than textual: it drives the real store against a recording client and fails
if any mutating command runs outside the transaction or if the `EXPIRE` is not in it. Verified
against the real Redis 7.2 container (`test_redis_state_store.py`, 7 passed).

### WR-11: Replay silently reads only partition 0

**Files modified:** `scripts/replay_raw.py`, `tests/integration/test_replay_offset_range.py`,
`services/state_machine/README.md`
**Commit:** `33c7e79`

Added `--partition`. A single-partition topic still needs no flag; a multi-partition topic with
no `--partition` is refused with an error naming the partitions, as are a non-existent partition
and a non-existent topic (a typo'd `--topic` used to look exactly like a stream that confirmed
nothing).

Implementation note: partitions are read with `AIOKafkaAdminClient`.
`AIOKafkaConsumer.partitions_for_topic` reads `_client.cluster`, which stays empty because this
consumer deliberately never subscribes, and `topics()` builds and discards a throwaway
`ClusterMetadata` — verified by reading the installed aiokafka source. The admin client is
metadata-only, so replay stays read-only by construction.

### WR-12: Malformed or tombstoned Kafka records crash the replay tool with a traceback

**Files modified:** `scripts/replay_raw.py`, `tests/unit/test_replay_determinism.py`
**Commit:** `c7f5fc7`

`records_to_envelopes` raises `InputError` naming topic and offset for a tombstone, a JSON
error, or a non-UTF-8 body, so `--from-offset` and `--input` now exit 1 identically.

### WR-13: The production crash-hook guard fails open when `ENV` is unset

**Files modified:** `services/state_machine/config.py`, `services/state_machine/main.py`,
`services/state_machine/README.md`, `tests/unit/test_state_machine_startup.py`,
`tests/integration/test_state_machine_chaos.py`
**Commit:** `94ee658`

`config.crash_hook_allowed()` reads the **raw** `ENV` and requires it to be explicitly one of
`dev`/`test`/`ci`/`local`. Reading the raw variable rather than `env_name()` is the point: the
`"dev"` default still exists for logging, but letting it also unlock a SIGKILL hook would make
an unconfigured production container the most permissive configuration there is. The chaos test
now names `ENV=test` when it arms the hook. Tests cover eight refused values (including unset,
blank, and three spellings of production) and six accepted ones.

### WR-14: A malformed job descriptor is never released from `sched:polls:inflight`

**Files modified:** `shared/scheduler/lua.py`, `services/poller/scheduler.py`,
`tests/integration/test_scheduler_claim_release.py`
**Commit:** `2484889`

`LuaScheduler.drop()` removes a job from the inflight ZSET without re-enqueuing it (a single
`ZREM` is already atomic, so no Lua). Both malformed-descriptor branches call it and log at
`error`. Integration tests cover the fix and also pin the reaper-resurrection behaviour that
made the leak permanent.

### WR-15: Integration tests mutate `os.environ` without restoring it

**Files modified:** `tests/integration/test_state_machine_chaos.py`,
`tests/integration/test_state_machine_e2e.py`,
`tests/integration/test_availability_events_persistence.py`
**Commit:** `a439ea8`

The two function-scoped tests take `monkeypatch`; the module-scoped wiring fixture uses
`pytest.MonkeyPatch.context()`. Subprocess environments are still snapshotted from
`os.environ`, which sees the patched values.

### IN-01: `SlotState.UNKNOWN` is never written, so the branch that tests for it is dead

**Files modified:** `services/state_machine/models.py`, `services/state_machine/engine.py`,
`services/state_machine/README.md`, `tests/unit/test_engine_tristate_unknown.py`
**Commit:** `feeada6`

Took the "drop the enum member" branch, which is what D-41 already says (UNKNOWN is
restaurant-level). A legacy or corrupt `"UNKNOWN"` hash field now fails `SlotRecord.from_json`,
which `RedisStateStore.get_slots` already handles by dropping the field — the slot re-enters
the PENDING cycle and must be confirmed again, which is the safe direction.

### IN-02: The crash hook's environment read is duplicated

**Files modified:** `services/state_machine/consumer.py`, `tests/unit/test_state_machine_startup.py`
**Commit:** `20fcaa0`

`consumer.py` imports `crash_after` from `config`; a test asserts `config.py` is the only file
in `services/`, `shared/` or `scripts/` that reads `MISE_CRASH_AFTER`.

### IN-03: `close_event` cannot tell "closed" from "row not found"

**Files modified:** `services/state_machine/persistence.py`,
`tests/integration/test_availability_events_persistence.py`
**Commit:** `079fcd1`

Captures `rowcount` (via a `CursorResult` cast — `Session.execute` is typed as returning the
base `Result`) and logs `availability_event_close_matched_no_row` at warning level. Still not an
error: the write is best effort by design (D-48). Two integration tests pin both directions.

### IN-04: `kafka-ui` is pinned to `:latest`, and the compose `version:` key is obsolete

**Files modified:** `ops/docker-compose.yml`, `tests/unit/test_compose_images_are_pinned.py` (new)
**Commit:** `91135fd`

Pinned to `provectuslabs/kafka-ui:v0.7.2` (tag pulled and verified to exist); `version:` removed;
`docker compose config` still validates. A unit test fails on any unpinned image or a reinstated
`version:` key.

### IN-05: `make lint` does not type-check `scripts/`

**Files modified:** `Makefile`, `pyproject.toml`, `uv.lock`, `scripts/seed_restaurants.py`,
`tests/unit/test_replay_determinism.py`
**Commit:** `5d15a9e`

`make lint` now runs `mypy shared/ services/ scripts/`. That surfaced three real errors in
`scripts/seed_restaurants.py` (a Phase 1 file): missing PyYAML stubs, fixed by adding
`types-PyYAML` to the dev group, and two `str | None` arguments. The latter needed an explicit
`is not None` ternary rather than `or`, because mypy types `optional or fallback` as optional —
verified with a `reveal_type` probe. A test fails if a future edit drops `scripts/` from the
mypy invocation.

### IN-06: The chaos test's observation loop hammers Kafka with a new consumer group per pass

**Files modified:** `tests/integration/test_state_machine_chaos.py`
**Commit:** `7b44fd2`

One consumer reads from the beginning for the whole 45 s window and accumulates; a single
`getmany(timeout_ms=1000)` paces the loop by itself, so no `sleep` is needed. The duplicate
assertion is unchanged and still fires on every pass.

### IN-07: Two slots colliding on one `(time_slot, seat_type)` are collapsed silently

**Files modified:** `services/state_machine/engine.py`, `services/state_machine/consumer.py`,
`tests/unit/test_slot_key_collisions.py` (new), `tests/unit/test_engine_purity.py`
**Commit:** `9752805`

`DiffEngine.last_collision_count` follows exactly the split `last_close_count` already uses: the
pure core counts, the shell logs (`slot_key_collisions`). Neither counter changes a diff
outcome, so replay stays byte-identical and `test_engine_purity` is unaffected. Tests cover a
real collision, the shipped `bar` + `standard` fixture shape (two slots, *not* a collision), and
the counter being reset between polls.

---

## Goldens

`tests/fixtures/raw_streams/*.events.jsonl` are **unchanged** — `git diff 3e0ea2d..HEAD --
tests/fixtures/` is empty, and `test_two_replays_are_byte_identical_and_match_the_golden` passes.

CR-01 did not require regenerating them. The claim key is a *consumer-shell* concern:
`scripts/replay_raw.py` never took a claim at all (it dedupes on `event_id`), so the replay
output was already the correct two-event stream and the goldens already reflect the fixed
behaviour. The bug was that production disagreed with them. The three committed fixtures also
each carry a single seating type per timeslot, so none of them exercises the collision anyway —
which is precisely why the new `test_two_seat_types_one_token.py` drives the *shipped*
`OPENTABLE_SUCCESS_RESPONSE` instead.

WR-07 (one shared `CONFIRM_DELAY_MS`) and WR-09 (empty coverage → `ParseError`) were both checked
against the fixture corpus before landing: the constant's value is unchanged at 8000, and every
fixture carries well-formed `request_params`.

## Deferred

**D-46 decision text (documentation only).** The review notes that D-46's literal wording in
`02-CONTEXT.md` — `SET event:{rid}:{date}:{party}:{token} … ; token = booking_token or slot_key`
— carries the same defect as the code did, and asks for the decision text to be amended
alongside. Not done here: `.planning/` decision records are locked context owned by the
orchestrator, and this agent does not commit `.planning/` files. The amendment needed is a
one-line change to D-46's key literal to
`event:{rid}:{date}:{party}:{slot_key}:{token}`, noting it follows from D-36 (slot identity
includes `seat_type`, `booking_token` is data). The code, the tests and
`services/state_machine/README.md` are already consistent with the corrected form, and the
`consumer.py` comment records the amendment inline as "D-46 as amended by CR-01".

## Notes for the reviewer

* **Two existing tests were changed rather than added to**, both because they pinned the defect
  itself rather than the intent. Neither was weakened, and both changes are called out above:
  the `.env.example` assertion (WR-06, commit `76aa3b1`) and the replay import gate (WR-07,
  commit `5377f6a`, which was made strictly stronger and mutation-checked against five
  violations). No test was disabled, skipped, or loosened.
* **No `time.sleep`, `requests`, or sync redis** was added anywhere; IN-06 removed the only
  place where a sleep would have been the obvious fix, in favour of a blocking `getmany`.
* **Mutation checks were run for both criticals** and for the sharpened replay gate — each new
  regression test was confirmed to fail against the pre-fix code before being committed.
* A concurrent agent was writing Phase 3 artifacts into this repo during the run (three
  interleaved `docs(03)` commits, plus scratch files under `tests/_research/` and `.mypyprobe/`
  that briefly broke an unscoped `ruff check .`). Those are not mine and were not touched; the
  scratch directories have since been removed by their owner, and the final unscoped
  `uv run ruff check .` is clean.

---

_Fixed: 2026-09-05T09:05:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
