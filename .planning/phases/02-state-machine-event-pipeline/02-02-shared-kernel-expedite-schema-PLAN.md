---
phase: 02-state-machine-event-pipeline
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - shared/redis_keys.py
  - shared/scheduler/lua.py
  - shared/kafka.py
  - shared/db.py
  - services/poller/scheduler.py
  - migrations/versions/0008_add_event_id_to_availability_events.py
  - ops/docker-compose.yml
  - tests/integration/conftest.py
  - tests/integration/test_expedite_lua.py
  - tests/integration/test_poller_expedite_release.py
  - tests/integration/test_migration_0008.py
  - tests/unit/test_redis_keys_phase2.py
  - tests/unit/test_kafka_consumer_config.py
  - tests/unit/test_no_setnx_expire_pairs.py
autonomous: true
requirements: [STATE-01, STATE-03, STATE-05]

estimate:
  tokens: 32000
  raw_tokens: 32000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "A PENDING slot pulls its restaurant's next poll forward to `now_ms + 8000` — `EXPEDITE_POLL_LUA` runs `ZADD sched:polls XX LT` when the job is queued, and sets `sched:expedite:{source}:{rid}` with a 120 s TTL when the job is in flight (D-43; STATE-03)."
    - "The poller release path consumes the expedite flag with a single `GETDEL` and releases at `now_ms + CONFIRM_DELAY_MS` instead of the 90 s +/- 15% jittered score; a second release finds no flag and uses the jittered score (D-43; STATE-03)."
    - "`LT` never raises an already-earlier score and `XX` never resurrects an in-flight job into the ready set — verified against a live Redis 7.2 container (research §Code Examples)."
    - "Every Redis key pattern and TTL this phase introduces is declared once in `shared/redis_keys.py`: `avail_state_key`, `avail_meta_key`, `event_idempotency_key`, `sched_expedite_key`, `AVAIL_STATE_TTL_SECONDS=90000`, `EVENT_IDEMPOTENCY_TTL_SECONDS=1200`, `EXPEDITE_FLAG_TTL_SECONDS=120`, `CONFIRM_DELAY_MS=8000` (D-42; STATE-01, STATE-04)."
    - "`make_consumer` builds an `AIOKafkaConsumer` from varargs topics with `enable_auto_commit=False`, `auto_offset_reset='earliest'`, `max_poll_records=1`, and is constructible only inside a running loop (D-47a / research B-1)."
    - "Migration 0008 applies cleanly on a TimescaleDB hypertable, adds `event_id UUID NOT NULL`, and creates `UNIQUE INDEX uq_availability_events_event_id_time (event_id, \"time\")` — an index omitting `time` is proven to be rejected by the server (D-48a / research B-2; STATE-05)."
    - "`shared.db.AvailabilityEvent` has primary key `(time, event_id)` and `restaurant_id` is no longer part of the primary key, so one poll confirming two slots writes two rows instead of colliding (D-48a / research B-3; STATE-05)."
    - "`availability_events.day_of_week` carries a column comment reading `0=Sun .. 6=Sat`, overriding the stale `0=Mon..6=Sun` note in migration 0006 (D-48 / research B-5)."
    - "`availability_events.restaurant_id` carries a column comment stating it holds the source platform id and that the join key against `restaurants` is `(source, platform_id)` (D-52; research Pitfall 5)."
    - "`make up` resolves its Kafka image — `ops/docker-compose.yml` points at `bitnamilegacy/kafka:3.8` with every `KAFKA_CFG_*` variable unchanged (D-56 / research Pitfall 9)."
    - "idempotency (STATE-05): applying migration 0008 twice via `alembic upgrade head` is a no-op the second time, and `alembic downgrade -1` followed by `upgrade head` restores the same schema."
    - "empty (STATE-01): `avail_state_key`, `avail_meta_key`, `event_idempotency_key` and `sched_expedite_key` are pure string builders that never touch Redis, so they are total on every input and have no empty-input failure mode; `consume_expedite` on an absent flag returns `False` rather than raising."
    - "adjacency (STATE-01): `avail_state_key(42,'2026-05-01',2)` and `avail_state_key(42,'2026-05-01',4)` are distinct strings that never collide, and `event_idempotency_key` for two slots of the same `(rid, date, party)` differing only in token are distinct."
    - "concurrency (STATE-05): the expedite claim is server-side atomic — a read-compare-write in Python would race the poller's `claim`; the Lua script performs `ZSCORE` and the conditional `ZADD` in one round trip and `GETDEL` consumes the flag exactly once."
    - statement: "A `ZADD XX LT` against `sched:polls` while the poller is concurrently running `CLAIM_POLL_LUA` on the same job never produces a duplicate concurrent poll for that restaurant."
      verification: backstop
  prohibitions:
    - "Must not use the confirmation-expedite path to drive a restaurant's poll frequency below the project's published rate-limit posture: the expedite may only pull a queued poll forward, never below `now_ms + CONFIRM_DELAY_MS`, never resurrect an in-flight job, and the flag must expire on its own within `EXPEDITE_FLAG_TTL_SECONDS`."
  artifacts:
    - path: "shared/redis_keys.py"
      provides: "Phase 2 key builders, TTL constants, EXPEDITE_POLL_LUA, typed HASH helpers (D-42)"
      contains: "EXPEDITE_POLL_LUA"
    - path: "shared/scheduler/lua.py"
      provides: "LuaScheduler.expedite / LuaScheduler.consume_expedite (D-43)"
      contains: "async def expedite"
    - path: "shared/kafka.py"
      provides: "make_consumer manual-commit factory (D-47a)"
      contains: "async def make_consumer"
    - path: "migrations/versions/0008_add_event_id_to_availability_events.py"
      provides: "event_id column + (event_id, time) unique index + column comments (D-48a)"
      contains: "uq_availability_events_event_id_time"
    - path: "tests/integration/conftest.py"
      provides: "shared migrate + create-topics helper for every Phase 2 integration test"
      exports: ["apply_migrations", "create_topics", "reset_shared_db_singletons"]
  key_links:
    - from: "services/poller/scheduler.py"
      to: "shared/scheduler/lua.py"
      via: "release path calls scheduler.consume_expedite(job) before choosing the next score"
      pattern: "consume_expedite"
    - from: "shared/scheduler/lua.py"
      to: "shared/redis_keys.py"
      via: "EXPEDITE_POLL_LUA + sched_expedite_key imported, never inlined (D-42)"
      pattern: "EXPEDITE_POLL_LUA"
    - from: "shared/db.py"
      to: "migrations/versions/0008_add_event_id_to_availability_events.py"
      via: "ORM primary key (time, event_id) must match the migration's unique index"
      pattern: "event_id"
---

<objective>
Extend the Phase 1 shared kernel with everything the state machine needs from the outside world, and
fix the three schema-level defects research reproduced as hard runtime errors. Deliverables: the
expedite path that lets a PENDING slot pull the next poll forward to t+8s through the existing ZSET
scheduler; the Phase 2 Redis key/TTL registry with mypy-clean HASH helpers; a manual-commit Kafka
consumer factory; migration 0008 with the hypertable-legal unique index; and the `bitnamilegacy`
Kafka image repoint that makes `make up` work again.

Purpose: plan 02-03 wires these primitives into the consumer shell. Every one of them is a
correction of a locked-decision statement that does not run as literally written (research B-1, B-2,
B-3, B-5) or a primitive whose atomicity is load-bearing (the expedite Lua).
Output: 4 modified `shared/` and `services/poller/` modules, migration 0008, the compose fix, a
shared integration conftest, and 6 test files.
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
@shared/redis_keys.py
@shared/scheduler/lua.py
@shared/kafka.py
@services/poller/scheduler.py
@migrations/versions/0006_create_availability_events_hypertable.py
@tests/integration/test_scheduler_claim_release.py
@tests/integration/test_poller_smoke.py
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end "a PENDING slot pulls the next poll forward to t+8s" — one path only</name>

  <precondition>The Docker daemon is reachable (`docker info` exits 0); the `redis:7.2-alpine` image resolves. Without it the testcontainers fixtures in `tests/conftest.py` skip and this task's integration verification is vacuous.</precondition>

  <read_first>
shared/redis_keys.py in full (section-comment style, `job()`, `set_nx_ex`, `CLAIM_POLL_LUA` KEYS/ARGV
header form — the new Lua must match it exactly); shared/scheduler/lua.py in full (`__init__` sha
slots, `start()`, `_evalsha_with_fallback`, `claim`, `release`, and the bytes-decoding idiom at lines
63-65); services/poller/scheduler.py lines 26-32 and 126-139 (the release path being modified and
`_next_poll_score`, which must stay as the default branch);
.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md §Pattern 3 and §Code Examples
(`EXPEDITE_POLL_LUA` with the live Redis 7.2 transcript — copy the script verbatim);
tests/integration/test_scheduler_claim_release.py (module-scoped `redis_url` fixture, clean-slate
deletes, bytes-literal assertions).
  </read_first>

  <files>shared/redis_keys.py, shared/scheduler/lua.py, services/poller/scheduler.py, tests/integration/conftest.py, tests/integration/test_expedite_lua.py, tests/integration/test_poller_expedite_release.py, tests/unit/test_redis_keys_phase2.py</files>

  <behavior>
    - Queued job: with `sched:polls` holding `opentable:42` at score `now+100000`, `LuaScheduler.expedite("opentable:42", now_ms)` returns `"zset"` and `ZSCORE sched:polls opentable:42` equals `now_ms + 8000`.
    - `LT` guard: a second `expedite` at a later `now_ms` that would raise the score leaves the score unchanged.
    - `XX` guard: `expedite` on a job absent from `sched:polls` returns `"flag"`, does NOT create the member (`ZSCORE` is nil), and sets `sched:expedite:opentable:42` with a TTL between 1 and 120.
    - `consume_expedite("opentable:42")` returns `True` the first time and `False` the second time (single-command `GETDEL`).
    - Poller release: with the expedite flag set, one `poll_loop` iteration releases the job at a score within 50 ms of `now_ms + 8000`; with no flag set, the released score falls inside the 90 s +/- 15% jitter band (`now_ms + 76500` to `now_ms + 103500`).
    - One expedite per restaurant per cycle: calling `expedite` five times for the same queued job leaves exactly one ZSET member with one score — a burst of PENDING slots cannot compound into five pulled-forward polls.
    - Key builders: `sched_expedite_key("opentable:42") == "sched:expedite:opentable:42"`, and `CONFIRM_DELAY_MS == 8000`, `EXPEDITE_FLAG_TTL_SECONDS == 120`.
  </behavior>

  <action>
Write the failing integration and unit tests first, then implement.

In `shared/redis_keys.py`, add a `# -- Confirmation expedite (D-43, STATE-03) --` section with
`CONFIRM_DELAY_MS: int = 8_000`, `EXPEDITE_FLAG_TTL_SECONDS: int = 120`, and
`sched_expedite_key(job: str) -> str` returning `f"sched:expedite:{job}"` with a one-line docstring
naming D-43. Add `EXPEDITE_POLL_LUA` verbatim from 02-RESEARCH.md §Code Examples, keeping the
`-- KEYS[n] = ...` / `-- ARGV[n] = ...` header comment block exactly as `CLAIM_POLL_LUA` has it. The
script takes `KEYS[1]=sched:polls`, `KEYS[2]=sched:expedite:{job}`, `ARGV[1]=now_ms`,
`ARGV[2]=job descriptor`, `ARGV[3]=confirm_delay_ms`, `ARGV[4]=flag ttl seconds`; it returns the
string `zset` after a `ZADD KEYS[1] XX LT (now_ms + confirm_delay_ms) job` when `ZSCORE` finds the
job, otherwise the string `flag` after `SET KEYS[2] '1' EX ttl`. `XX` is mandatory so an in-flight
job is never resurrected into the ready set (that would be a concurrent duplicate poll); `LT` is
mandatory so an already-sooner poll is never pushed later. Plain `ZADD` and `GT` are both wrong here.

In `shared/scheduler/lua.py`, add `self._expedite_sha: str | None = None` to `__init__`, load it in
`start()` via `script_load(EXPEDITE_POLL_LUA)`, and add
`async def expedite(self, job: str, now_ms: int) -> str` mirroring `release()` exactly — the
`assert self._expedite_sha is not None, "Call start() first"` guard, `_evalsha_with_fallback` with
`numkeys=2`, and the bytes-decoding return idiom from `claim()`. Add
`async def consume_expedite(self, job: str) -> bool` performing a single `GETDEL` on
`sched_expedite_key(job)` and returning `True` when the returned value is not `None`. Use
`cast(Awaitable[Any], ...)` for the redis-py call exactly as line 47 does — `mypy --strict` rejects a
bare `await` on redis-py commands. The `GETDEL` lives on `LuaScheduler` rather than being plumbed as
a new Redis handle through `poll_loop`, because `poll_loop`'s signature only carries the scheduler.

In `services/poller/scheduler.py`, replace the two-line release at the end of the loop body: compute
`now_ms = int(time.time() * 1000)` once, then
`next_score = now_ms + CONFIRM_DELAY_MS if await scheduler.consume_expedite(job) else _next_poll_score(now_ms)`,
and log a `poll_expedited` structlog event on the expedited branch with `restaurant_id` and
`next_score`. Leave `_next_poll_score` untouched as the default branch. Import `CONFIRM_DELAY_MS`
from `shared.redis_keys` (D-42 — never inline the constant).

Create `tests/integration/conftest.py` holding the helpers currently duplicated inline in
`tests/integration/test_poller_smoke.py` lines 63-80 and `test_hypertable_config.py`:
`reset_shared_db_singletons()` (sets `shared.db._engine` and `shared.db._session_factory` to `None`),
`apply_migrations(env)` (`subprocess.run(["uv", "run", "alembic", "upgrade", "head"], env=env, capture_output=True, text=True)`
asserting `returncode == 0`), `create_topics(env)` (same shape for `scripts/create_topics.py`), and a
`redis_url(redis_container)` / `db_urls(timescale_container)` fixture pair built from the container
accessors. Do NOT edit the existing integration test files — they keep working as-is; the helpers are
for the four new Phase 2 integration files.

Write `tests/integration/test_expedite_lua.py` and `tests/integration/test_poller_expedite_release.py`
following the `tests/integration/test_scheduler_claim_release.py` shape: `pytestmark =
pytest.mark.integration`, module-scoped `redis_url`, explicit `await r.delete(SCHED_POLLS,
SCHED_POLLS_INFLIGHT)` clean slate, bytes-literal assertions because `redis.from_url` defaults to
`decode_responses=False`, and `await r.aclose()` at the end. The release test drives one iteration of
the real release logic rather than re-implementing it. Write `tests/unit/test_redis_keys_phase2.py`
asserting the key-builder strings, the constants, and that `EXPEDITE_POLL_LUA` contains both the
`XX` and `LT` flags and the `GETDEL`-free single `SET ... EX` form, mirroring the Lua-content
assertion idiom already in `tests/unit/test_redis_keys.py`.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/unit/test_redis_keys_phase2.py -q && uv run pytest tests/integration/test_expedite_lua.py tests/integration/test_poller_expedite_release.py -q -p no:cacheprovider && uv run ruff check . && uv run mypy shared/ services/</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/integration/test_expedite_lua.py -q -p no:cacheprovider` exits 0 with at least 4 tests passing and 0 skipped.
    - `uv run pytest tests/integration/test_poller_expedite_release.py -q -p no:cacheprovider` exits 0.
    - `uv run pytest tests/unit -q` exits 0 (all pre-existing unit tests still pass).
    - `grep -c "EXPEDITE_POLL_LUA" shared/redis_keys.py` is 1 or greater and `grep -c "'XX'" shared/redis_keys.py` is 1 or greater.
    - `grep -c "async def expedite" shared/scheduler/lua.py` outputs 1 and `grep -c "async def consume_expedite" shared/scheduler/lua.py` outputs 1.
    - `grep -c "consume_expedite" services/poller/scheduler.py` outputs 1.
    - `grep -rn "sched:expedite:" services/ | wc -l` outputs 0 — the pattern exists only in `shared/redis_keys.py` (D-42).
    - `uv run ruff check . && uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>

  <reversibility rating="costly">
    The expedite contract is a two-service handshake: the state machine writes the flag / lowers the
    score, the poller consumes it. Changing the key name or the semantics later requires a
    coordinated change in both services plus a Redis key drain.
  </reversibility>

  <done>
    A queued poll can be pulled forward to exactly `now_ms + 8000` and an in-flight poll leaves a
    self-expiring flag the poller consumes exactly once, both proven against a live Redis 7.2
    container, with the poller's jittered default branch untouched.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Phase 2 Redis state-key registry, typed HASH helpers, and the manual-commit Kafka consumer factory</name>

  <read_first>
shared/redis_keys.py as extended in Task 1; shared/kafka.py in full (`make_producer` signature style,
env fallback, inline kwarg-justifying comments, the `max_in_flight_requests_per_connection` note that
must NOT be reintroduced); .planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md
§Blocking Correction B-1, §Pitfall 3 (the exact `cast(Awaitable[T], ...)` forms that satisfy
`mypy --strict` for HASH commands), §Pitfall 4, §Pitfall 6, §Code Examples (`make_consumer`);
tests/unit/test_redis_keys.py and tests/unit/test_kafka_config.py (assertion idioms to mirror).
  </read_first>

  <files>shared/redis_keys.py, shared/kafka.py, tests/unit/test_redis_keys_phase2.py, tests/unit/test_kafka_consumer_config.py, tests/unit/test_no_setnx_expire_pairs.py</files>

  <behavior>
    - `avail_state_key(42, "2026-05-01", 2) == "avail:42:2026-05-01:2"` and `avail_meta_key(42) == "avail:42:meta"`.
    - `event_idempotency_key(42, "2026-05-01", 2, "tok1") == "event:42:2026-05-01:2:tok1"`; two different tokens for the same `(rid, date, party)` produce two different keys.
    - `AVAIL_STATE_TTL_SECONDS == 90_000`, `EVENT_IDEMPOTENCY_TTL_SECONDS == 1_200`.
    - `make_consumer("a", "b", group_id="g")` passes both topics as varargs (a list argument would raise `TypeError: unhashable type: 'list'`), and the constructed consumer reports `enable_auto_commit` false, `auto_offset_reset` "earliest", `max_poll_records` 1.
    - `make_consumer` called outside a running event loop raises `RuntimeError` — construction must happen inside `async def run()`.
    - Source-tree guard: zero call sites of the deprecated two-command claim form anywhere in `services/`, `shared/`, or `scripts/`; every idempotency claim routes through `shared.redis_keys.set_nx_ex`.
  </behavior>

  <action>
In `shared/redis_keys.py`, add a `# -- Availability state (D-40, D-42, STATE-01) --` section with
`AVAIL_STATE_TTL_SECONDS: int = 90_000` (25 h) and `EVENT_IDEMPOTENCY_TTL_SECONDS: int = 1_200`
(20 min), plus the builders `avail_state_key(restaurant_id: int, date: str, party_size: int) -> str`,
`avail_meta_key(restaurant_id: int) -> str`, and
`event_idempotency_key(restaurant_id: int, date: str, party_size: int, token: str) -> str`, each with
a one-line docstring naming its decision id. Add the four typed HASH helpers that keep every
`cast(Awaitable[T], ...)` in one file so `services/state_machine/store.py` needs none:
`hset_slot(r, key, field, value) -> int`, `hgetall_slots(r, key) -> dict[bytes, bytes]`,
`hdel_slot(r, key, field) -> int`, `hset_meta(r, key, mapping) -> int`, and
`expire_key(r, key, ttl_seconds) -> bool`. Use the precise cast targets from 02-RESEARCH.md
§Pitfall 3 — `Awaitable[int]`, `Awaitable[dict[bytes, bytes]]`, `Awaitable[bytes | None]` — never a
`type: ignore`, which would hide real signature drift on a future redis-py bump. Add a comment on the
TTL constant stating that per-field hash TTL (`HEXPIRE`) is a Redis 7.4 SERVER feature and the pinned
server is `redis:7.2-alpine`, so TTL is key-level and must be refreshed on every write (D-40,
research Pitfall 6).

In `shared/kafka.py`, add `async def make_consumer(*topics: str, group_id: str,
bootstrap_servers: str | None = None) -> AIOKafkaConsumer` exactly as 02-RESEARCH.md §Code Examples
specifies: topics as VARARGS (the locked D-47 wording passes a list, which raises `TypeError:
unhashable type: 'list'` — that is research correction B-1), `enable_auto_commit=False`,
`auto_offset_reset="earliest"`, `max_poll_records=1`, `isolation_level="read_uncommitted"`, `await
consumer.start()` before returning, and a docstring stating that it MUST be called from inside a
running event loop because `AIOKafkaConsumer.__init__` calls `get_running_loop()`. Match
`make_producer`'s env-fallback and caller-owns-`.stop()` contract. Do not add a `value_deserializer` —
the shell wants raw bytes. Do not add `max_in_flight_requests_per_connection`; the existing note in
this file explains why it does not exist in aiokafka. Update the module header docstring.

Write `tests/unit/test_kafka_consumer_config.py` asserting the constructor kwargs (build the consumer
inside an async test, assert on its config, then `await consumer.stop()` without ever starting a
broker connection — or assert on the factory's introspected defaults if starting requires a broker;
if `start()` needs a broker, assert instead that a list-typed topics argument raises `TypeError` and
that the module source names the three required kwargs). Extend
`tests/unit/test_redis_keys_phase2.py` with the key-builder and TTL assertions.

Write `tests/unit/test_no_setnx_expire_pairs.py`: walk every `.py` file under `services/`, `shared/`,
and `scripts/` and assert zero regex matches for the deprecated redis-py two-command claim method
call (the method name preceded by a dot and followed by an open parenthesis, case-insensitive), and
assert that `shared/redis_keys.py` defines `set_nx_ex` using a single `r.set(...)` call carrying both
`nx=True` and `ex=`. Strip full-line comments before matching so an explanatory comment can never
satisfy or break the gate. This test is ROADMAP Phase 2 success criterion 3's mechanical half and
must stay green for the rest of the project.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/unit -q && uv run ruff check . && uv run mypy shared/ services/</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/unit -q` exits 0 with zero failures.
    - `uv run pytest tests/unit/test_no_setnx_expire_pairs.py -q` exits 0.
    - `grep -c "async def make_consumer" shared/kafka.py` outputs 1.
    - `grep -c "max_poll_records=1" shared/kafka.py` outputs 1 and `grep -c "enable_auto_commit=False" shared/kafka.py` outputs 1.
    - `grep -c "AVAIL_STATE_TTL_SECONDS: int = 90_000" shared/redis_keys.py` outputs 1.
    - `grep -c "def event_idempotency_key" shared/redis_keys.py` outputs 1.
    - `grep -rn "type: ignore" shared/redis_keys.py | wc -l` outputs 0.
    - `uv run mypy shared/ services/` exits 0 with no errors reported for HASH command awaits.
  </acceptance_criteria>

  <reversibility rating="costly">
    Redis key patterns and TTLs become live data as soon as the state machine runs. Renaming a key
    later orphans the existing keyspace until the 25 h / 20 min TTLs drain it.
  </reversibility>

  <done>
    Every Phase 2 Redis key pattern and TTL is declared once in `shared/redis_keys.py` with
    `mypy --strict`-clean HASH helpers, a varargs manual-commit consumer factory exists, and a
    permanent source-grep gate proves the deprecated two-command idempotency claim appears nowhere.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Migration 0008, the AvailabilityEvent ORM primary-key remap, and the Kafka image repoint</name>

  <precondition>`availability_events` is empty in every environment this migration touches (Phase 1 never wrote to it, per PROJECT decision D-31). The migration carries a `DELETE FROM availability_events WHERE event_id IS NULL` guard so a non-empty table degrades to a truncation of unbackfillable rows rather than a failed `ALTER`.</precondition>

  <read_first>
migrations/versions/0006_create_availability_events_hypertable.py in full (the column list, the
stale `# 0=Mon..6=Sun` comment on line 27, the anti-autogenerate warning on line 30, the raw
`op.execute` style, and the real `downgrade()`);
migrations/versions/0007_create_poll_log_hypertable.py lines 1-10 (header, revision chain, UUID
import); shared/db.py lines 105-138 (the `AvailabilityEvent` declaration to remap and the `PollLog`
UUID column to copy); .planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md §Blocking
Corrections B-2, B-3, B-5, §Code Examples (Migration 0008 body, verified `EXPLAIN` plans), §Pitfall 5,
§Pitfall 9; ops/docker-compose.yml lines 1-30; tests/integration/test_hypertable_config.py and the
new tests/integration/conftest.py from Task 1.
  </read_first>

  <files>migrations/versions/0008_add_event_id_to_availability_events.py, shared/db.py, ops/docker-compose.yml, tests/integration/test_migration_0008.py</files>

  <behavior>
    - `alembic upgrade head` on a fresh TimescaleDB container applies 0008 and exits 0.
    - After upgrade, `availability_events.event_id` exists, is `uuid`, and is `NOT NULL`.
    - A unique index named `uq_availability_events_event_id_time` exists over `(event_id, "time")`.
    - Attempting `CREATE UNIQUE INDEX ... ON availability_events (restaurant_id, event_id)` fails with a message containing `used in partitioning` — the B-2 regression guard proving the constraint is real, not folklore.
    - Two rows with the same `("time", restaurant_id)` but different `event_id` both insert successfully — the B-3 regression guard for one poll confirming two slots.
    - `INSERT ... ON CONFLICT (event_id, "time") DO NOTHING` run twice inserts exactly one row.
    - `col_description` for `availability_events.day_of_week` contains `0=Sun`, and for `restaurant_id` contains `platform`.
    - `alembic downgrade -1` then `alembic upgrade head` leaves the same schema (idempotency edge).
  </behavior>

  <action>
Hand-write `migrations/versions/0008_add_event_id_to_availability_events.py` following
02-RESEARCH.md §Code Examples exactly: `revision = "0008"`, `down_revision = "0007"`, the
`from sqlalchemy.dialects.postgresql import UUID as PG_UUID` import, and reproduce migration 0006's
anti-autogenerate warning comment verbatim — alembic autogenerate does not understand hypertables and
will propose dropping and recreating the table (D-33, PITFALLS Pitfall 12). `upgrade()` adds
`event_id` nullable, runs the `DELETE ... WHERE event_id IS NULL` guard, alters it to `nullable=False`,
then creates `uq_availability_events_event_id_time` over `["event_id", "time"]` with `unique=True`.
Add a comment above that index recording the verified server error a `time`-less unique index
produces on a hypertable, so no future maintainer "simplifies" it away (research B-2). Then two
`op.execute` column comments: `day_of_week` becomes `'0=Sun .. 6=Sat (service_date.isoweekday() %% 7)
— matches the Phase 6 heatmap y-axis (D-48)'` (note the doubled percent sign — alembic passes the
string through a format step), and `restaurant_id` becomes a comment stating it holds the SOURCE
PLATFORM ID (OpenTable rid / Resy venue id), matching `poll_log.restaurant_id`, and that the complete
join key against `restaurants` is `(source, platform_id)` (D-52, research Pitfall 5). Write a real
`downgrade()` dropping the index and the column — every existing migration has one.

In `shared/db.py`, remap the `AvailabilityEvent` ORM class: drop `primary_key=True` from
`restaurant_id`, add `event_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False,
primary_key=True)` copying the `PollLog.poll_id` column style, so the declarative primary key becomes
`(time, event_id)` and matches the migration's unique index. Keep the standing "hypertables are
created via Alembic, never `create_all`" comment block above the class untouched. Add a short comment
on `restaurant_id` repeating the D-52 platform-id meaning so a reader of the ORM sees it without
opening the migration.

In `ops/docker-compose.yml`, change the Kafka service image from `bitnami/kafka:3.8` to
`bitnamilegacy/kafka:3.8` and leave every `KAFKA_CFG_*` environment variable, the volume mount path,
the healthcheck, and the port mappings exactly as they are — the legacy repo is a drop-in for the
withdrawn Bitnami catalogue entry (D-56, research Pitfall 9). Add a one-line comment above the image
recording why the tag moved and that Phase 7 may move to an official image with its production
profile.

Write `tests/integration/test_migration_0008.py` using the `tests/integration/conftest.py` helpers:
run migrations against the Timescale container, then assert every behaviour above via
`information_schema` / `pg_indexes` / `col_description` queries, including the two negative-control
cases (the `time`-less unique index must raise, and the duplicate `(time, restaurant_id)` insert must
succeed). Assert on the substring `used in partitioning` from the raised error rather than the whole
message.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/integration/test_migration_0008.py -q -p no:cacheprovider && uv run ruff check . && uv run mypy shared/ services/</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/integration/test_migration_0008.py -q -p no:cacheprovider` exits 0 with 0 skipped.
    - `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 — the 12 pre-existing integration tests still pass after the ORM primary-key remap.
    - `grep -c "uq_availability_events_event_id_time" migrations/versions/0008_add_event_id_to_availability_events.py` is 2 or greater (created in `upgrade`, dropped in `downgrade`).
    - `grep -c "revision = \"0008\"" migrations/versions/0008_add_event_id_to_availability_events.py` outputs 1 and `grep -c "down_revision = \"0007\"" ...` outputs 1.
    - `grep -c "0=Sun" migrations/versions/0008_add_event_id_to_availability_events.py` is 1 or greater.
    - `grep -c "primary_key=True" shared/db.py` accounts for exactly two on the `AvailabilityEvent` class (`time` and `event_id`) — `grep -A6 "class AvailabilityEvent" shared/db.py | grep -c "primary_key=True"` outputs 2.
    - `grep -c "image: bitnamilegacy/kafka:3.8" ops/docker-compose.yml` outputs 1.
    - Region-scoped negative gate (image lines only, so an explanatory comment cannot break it): `grep -E "^\s*image:" ops/docker-compose.yml | grep -c "bitnami/kafka:3.8"` outputs 0.
    - `grep -c "KAFKA_CFG_" ops/docker-compose.yml` is 12 or greater — no environment variable was lost in the repoint.
    - `uv run ruff check . && uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>

  <reversibility rating="one-way">
    Migration 0008 changes the shape of a hypertable that Phases 4, 5 and 6 will read. It has a real
    `downgrade()` and the table is empty today, so reversal is cheap right now and expensive once
    events start landing.
  </reversibility>

  <done>
    Migration 0008 applies on a live TimescaleDB container with a hypertable-legal unique index, the
    ORM primary key matches it, both B-2 and B-3 have standing regression guards, the column
    semantics for `day_of_week` and `restaurant_id` are recorded in the database itself, and
    `make up` resolves its Kafka image again.
  </done>
</task>

</tasks>

<threat_model>
Only one task in this plan touches a boundary worth recording.

| Boundary | Description |
|----------|-------------|
| state machine to poller, via Redis `sched:polls` / `sched:expedite:*` | One service lowers another service's scheduled poll time. Abuse or a bug here changes outbound traffic to a third party. |

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-02-01 | Denial of Service (self-inflicted, third-party ToS risk) | `EXPEDITE_POLL_LUA`, `services/poller/scheduler.py` release path | medium | mitigate | `ZADD XX LT` cannot pull a poll earlier than `now_ms + CONFIRM_DELAY_MS`, `XX` cannot resurrect an in-flight job into a concurrent poll, the flag carries `EX 120`, and `tests/integration/test_expedite_lua.py` asserts a five-call burst yields exactly one ZSET member at one score. |
</threat_model>

<artifacts_this_phase_produces>
## Artifacts this phase produces (this plan's share)

**New files**
- `migrations/versions/0008_add_event_id_to_availability_events.py`
- `tests/integration/conftest.py`
- `tests/integration/test_expedite_lua.py`
- `tests/integration/test_poller_expedite_release.py`
- `tests/integration/test_migration_0008.py`
- `tests/unit/test_redis_keys_phase2.py`
- `tests/unit/test_kafka_consumer_config.py`
- `tests/unit/test_no_setnx_expire_pairs.py`

**Modified files**
- `shared/redis_keys.py`
- `shared/scheduler/lua.py`
- `shared/kafka.py`
- `shared/db.py`
- `services/poller/scheduler.py`
- `ops/docker-compose.yml`

**Symbols created**

| Symbol | Kind | Module |
|--------|------|--------|
| `CONFIRM_DELAY_MS` (8000) | module constant | `shared/redis_keys.py` |
| `EXPEDITE_FLAG_TTL_SECONDS` (120) | module constant | `shared/redis_keys.py` |
| `AVAIL_STATE_TTL_SECONDS` (90000) | module constant | `shared/redis_keys.py` |
| `EVENT_IDEMPOTENCY_TTL_SECONDS` (1200) | module constant | `shared/redis_keys.py` |
| `avail_state_key(restaurant_id, date, party_size)` | key builder | `shared/redis_keys.py` |
| `avail_meta_key(restaurant_id)` | key builder | `shared/redis_keys.py` |
| `event_idempotency_key(restaurant_id, date, party_size, token)` | key builder | `shared/redis_keys.py` |
| `sched_expedite_key(job)` | key builder | `shared/redis_keys.py` |
| `EXPEDITE_POLL_LUA` | Lua script constant | `shared/redis_keys.py` |
| `hset_slot`, `hgetall_slots`, `hdel_slot`, `hset_meta`, `expire_key` | typed async Redis helpers | `shared/redis_keys.py` |
| `LuaScheduler.expedite(job, now_ms) -> str` | method (returns `"zset"` or `"flag"`) | `shared/scheduler/lua.py` |
| `LuaScheduler.consume_expedite(job) -> bool` | method (`GETDEL`) | `shared/scheduler/lua.py` |
| `make_consumer(*topics, group_id, bootstrap_servers=None)` | async factory | `shared/kafka.py` |
| `AvailabilityEvent.event_id` | ORM column, part of PK `(time, event_id)` | `shared/db.py` |
| `uq_availability_events_event_id_time` | unique index | migration 0008 |
| `availability_events.event_id` | `uuid NOT NULL` column | migration 0008 |
| `reset_shared_db_singletons`, `apply_migrations`, `create_topics`, `redis_url`, `db_urls` | test helpers / fixtures | `tests/integration/conftest.py` |

**Redis keys introduced (contract for downstream phases)**
- `sched:expedite:{source}:{restaurant_id}` — string `"1"`, TTL 120 s, consumed with `GETDEL`
- `avail:{restaurant_id}:{date}:{party_size}` — HASH, key-level TTL 90000 s
- `avail:{restaurant_id}:meta` — HASH, key-level TTL 90000 s
- `event:{restaurant_id}:{date}:{party_size}:{token}` — string, TTL 1200 s
</artifacts_this_phase_produces>

<verification>
- `uv run pytest tests/unit -q` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 with 0 skips on a machine with Docker (12 pre-existing plus 3 new files).
- `uv run ruff check . && uv run mypy shared/ services/` exits 0.
- The three CI ban-greps still return nothing: `grep -rn "^import requests\|^from requests " services/ shared/`, `grep -rn "time\.sleep(" services/ shared/`, `grep -rEn "^import redis$|^from redis import " services/ shared/`.
- `docker compose -f ops/docker-compose.yml config` exits 0 and prints `bitnamilegacy/kafka:3.8`.
</verification>

<success_criteria>
- A PENDING slot can pull its restaurant's next poll forward to t+8s through the ZSET scheduler with
  no inline sleep and no direct HTTP call from the state machine (STATE-03).
- Every Phase 2 Redis key pattern and TTL lives in `shared/redis_keys.py` (STATE-01, D-42).
- Migration 0008 gives `availability_events` a hypertable-legal unique key that survives one poll
  confirming two slots (STATE-05, research B-2 and B-3).
- The source tree provably contains zero two-command idempotency claims (ROADMAP SC3, mechanical half).
- `make up` resolves every image on a clean machine.
</success_criteria>

<output>
Create `.planning/phases/02-state-machine-event-pipeline/02-02-SUMMARY.md` when done.
</output>
