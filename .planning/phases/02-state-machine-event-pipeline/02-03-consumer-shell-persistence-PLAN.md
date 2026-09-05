---
phase: 02-state-machine-event-pipeline
plan: 03
type: execute
wave: 2
depends_on: ["02-01", "02-02"]
files_modified:
  - services/state_machine/config.py
  - services/state_machine/store.py
  - services/state_machine/persistence.py
  - services/state_machine/consumer.py
  - services/state_machine/main.py
  - services/state_machine/__main__.py
  - services/state_machine/README.md
  - tests/integration/test_state_machine_e2e.py
  - tests/integration/test_state_machine_chaos.py
  - tests/integration/test_availability_events_persistence.py
  - tests/integration/test_redis_state_store.py
  - tests/unit/test_service_time_math.py
  - tests/unit/test_emission_idempotency.py
  - tests/unit/test_no_inline_sleep.py
autonomous: true
requirements: [STATE-01, STATE-02, STATE-03, STATE-04, STATE-05]

estimate:
  tokens: 40000
  raw_tokens: 40000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Publishing two `availability.raw` messages 9000 ms apart (by `polled_at_epoch_ms`) to a live Kafka broker produces exactly one message on `availability.events` and exactly one `availability_events` row (D-51; ROADMAP SC4)."
    - "A third poll omitting the slot updates that same row with `last_seen_at` and `duration_seconds` and emits nothing to Kafka — closures are DB-only (D-45, D-48; ROADMAP SC4)."
    - "The emit order per slot is exactly: atomic `SET event:{rid}:{date}:{party}:{token} 1 NX EX 1200` via `shared.redis_keys.set_nx_ex`, then `producer.send_and_wait('availability.events', ...)` with `acks=all`, then the Redis hash write to `AVAILABLE`, then the best-effort DB write, and only after the whole message `consumer.commit({tp: msg.offset + 1})` (D-46; STATE-04)."
    - "Killing the consumer with SIGKILL after the hash write and before the offset commit, then restarting it clean, yields exactly one `availability.events` record per `event_id` — redelivery finds the claim taken and the hash already AVAILABLE, and skips (D-46, D-51; ROADMAP SC3)."
    - "`RedisStateStore` writes `avail:{rid}:{date}:{party}` as a HASH and refreshes the key-level TTL to 90000 s on every write; `HEXPIRE` is never used because the pinned server is Redis 7.2 (D-40; STATE-01, research Pitfall 6)."
    - "`polls.completed` with status `error` or `timeout` marks the restaurant meta UNKNOWN and nothing else — no slot moves toward UNAVAILABLE and no event is emitted (D-47; ROADMAP SC1)."
    - "`hours_before_service` uses `zoneinfo.ZoneInfo('America/New_York')` for the service datetime and `day_of_week` is `service_date.isoweekday() % 7` with 0 meaning Sunday (D-48, research B-5, Pattern 6; STATE-05)."
    - "The persisted row carries populated `first_seen_at`, `last_seen_at`, `duration_seconds`, `hours_before_service`, and `day_of_week` (STATE-05; ROADMAP SC4)."
    - "A DB failure is logged and does not block the Kafka emit or the offset commit — metrics beat durability of the analytics row (D-48)."
    - "`services/state_machine/` contains zero occurrences of an inline asynchronous sleep used to wait out the confirmation delay — confirmation is stream-based through the ZSET scheduler (D-43; STATE-03)."
    - "adjacency (STATE-04/STATE-05): two slots confirmed by the same poll share `confirmed_at_epoch_ms` and therefore the same row `time`, yet write two distinct rows and two distinct Kafka messages because the primary key is `(time, event_id)` (research B-3)."
    - "empty (STATE-04): a message whose diff yields no `Emit` performs no Redis claim, no Kafka send, and still commits its offset — a poison or no-op message never stalls the partition."
    - "ordering (STATE-04): decisions for one message are applied in the engine's sorted order, so the `availability.events` message order for a single poll is reproducible."
    - "idempotency (STATE-05): the analytics insert is `INSERT ... ON CONFLICT (event_id, \"time\") DO NOTHING`, so replaying the same event twice leaves exactly one row; the close `UPDATE` names both `event_id` and `\"time\"` so it prunes to a single chunk (research B-2, B-3, §Code Examples EXPLAIN)."
    - "concurrency (STATE-05): `enable_auto_commit=False` plus commit-after-side-effects means an interrupted process re-reads the message; the Layer-1 claim plus the AVAILABLE hash state makes reprocessing a no-op rather than a duplicate."
    - "`MISE_CRASH_AFTER` is a test-only hook: `main.run()` refuses to start when it is set and `ENV` is `prod`."
  prohibitions:
    - "Must not emit an `availability.events` message for a slot that was not observed by two independent successful covered polls at least `CONFIRM_DELAY_MS` apart — a notification for a table that was never really open is worse than a missed one."
    - "Must not mass-close a restaurant's availability without leaving an auditable record of the closure burst: a poll that closes more than `MASS_CLOSURE_AUDIT_THRESHOLD` slots at once must log a distinct structlog event carrying the restaurant id, the poll id, and the count, so a sanitised or soft-banned response stays distinguishable after the fact from a genuinely full restaurant."
  artifacts:
    - path: "services/state_machine/consumer.py"
      provides: "side-effect shell: route by topic, expedite, claim, send, record, persist, commit (D-46, D-47)"
      contains: "class StateMachineConsumer"
    - path: "services/state_machine/persistence.py"
      provides: "insert_event / close_event upsert + service-time math (D-48)"
      contains: "def hours_before_service"
    - path: "services/state_machine/store.py"
      provides: "RedisStateStore alongside MemoryStateStore (D-40, D-49)"
      contains: "class RedisStateStore"
    - path: "services/state_machine/main.py"
      provides: "lifecycle: topic guard, redis, scheduler, producer, consumer, teardown"
      contains: "async def run"
    - path: "services/state_machine/README.md"
      provides: "state-transition table, D-46 ordering diagram, D-52 join note for Phases 4/5/6"
      contains: "PENDING"
  key_links:
    - from: "services/state_machine/consumer.py"
      to: "shared/redis_keys.py"
      via: "Layer-1 claim through set_nx_ex on event_idempotency_key — never an inline key string (D-42, D-46)"
      pattern: "set_nx_ex"
    - from: "services/state_machine/consumer.py"
      to: "shared/scheduler/lua.py"
      via: "Expedite decisions call LuaScheduler.expedite(job, now_ms) (D-43)"
      pattern: "\\.expedite\\("
    - from: "services/state_machine/consumer.py"
      to: "services/state_machine/engine.py"
      via: "the shell owns all I/O; DiffEngine.process returns decisions the shell executes (D-49)"
      pattern: "DiffEngine"
    - from: "services/state_machine/persistence.py"
      to: "shared/db.py"
      via: "pg_insert(AvailabilityEvent).on_conflict_do_nothing(index_elements=['event_id','time'])"
      pattern: "on_conflict_do_nothing"
---

<objective>
Wrap the pure core from 02-01 in its imperative shell and stand up the runnable service. This plan
delivers `RedisStateStore`, the TimescaleDB persistence layer, the Kafka consumer that executes the
engine's decisions in the crash-safe order D-46 specifies, the service entry point, and the four
integration tests that prove the phase's hardest guarantees against live containers: end-to-end emit
plus persist, kill -9 with zero duplicates, closure with `duration_seconds`, and Redis HASH TTL.

Purpose: this is where the phase becomes a running system. Everything the engine decided in memory
now has to survive a broker, a Redis restart, a Postgres stall, and an uncatchable SIGKILL between
any two steps.
Output: 6 new `services/state_machine/` modules plus a README, and 7 test files.
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
@services/poller/main.py
@services/poller/publisher.py
@services/poller/config.py
@tests/integration/test_poller_smoke.py
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end "Kafka availability.raw becomes availability.events plus a hypertable row" — one path only</name>

  <precondition>The Docker daemon is reachable (`docker info` exits 0) and the `confluentinc/cp-kafka:7.6.0`, `redis:7.2-alpine`, and `timescale/timescaledb:2.17.2-pg16` images resolve; migration 0008 from plan 02-02 is on `head`. Without all three the integration verification skips and is vacuous.</precondition>

  <read_first>
services/poller/main.py in full (module docstring form, `REQUIRED_TOPICS`, `_assert_topics_exist`,
resources constructed INSIDE `run()`, nested try/finally teardown — mirror it exactly);
services/poller/config.py lines 1-16 and 43-53 (re-export discipline and the env defaults both
services must agree on); services/poller/publisher.py lines 27-107 (the emit-then-persist class shape
and the SQLAlchemy write); services/state_machine/engine.py, models.py, store.py from plan 02-01;
shared/redis_keys.py and shared/scheduler/lua.py and shared/kafka.py as extended by plan 02-02;
.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md §Pattern 4 (the crash-point table),
§Pattern 6, §Pitfall 2, §Pitfall 3, §Pitfall 4, §Code Examples (`make_consumer`, insert/close with
verified EXPLAIN plans); .planning/phases/02-state-machine-event-pipeline/02-PATTERNS.md
§`services/state_machine/main.py`, §`consumer.py`, §`store.py`, §`persistence.py`,
§`tests/integration/test_state_machine_e2e.py`; tests/integration/conftest.py from plan 02-02.
  </read_first>

  <files>services/state_machine/config.py, services/state_machine/store.py, services/state_machine/persistence.py, services/state_machine/consumer.py, services/state_machine/main.py, services/state_machine/__main__.py, tests/integration/test_state_machine_e2e.py</files>

  <behavior>
    - Publish two `availability.raw` messages for rid 42 built from `OPENTABLE_SUCCESS_RESPONSE`, with `polled_at_epoch_ms` 9000 ms apart, to a live Kafka container; run the state machine until it idles; then drain `availability.events` from a throwaway consumer group. Exactly one message arrives.
    - The drained message parses as `AvailabilityEvent` with `event_type == "slot_opened"` and `produced_at_epoch_ms` equal to the second poll's `polled_at_epoch_ms` (not the wall clock).
    - Exactly one `availability_events` row exists for that `event_id`, with non-null `first_seen_at`, `last_seen_at`, `hours_before_service`, and `day_of_week`.
    - After the first poll only, `ZSCORE sched:polls opentable:42` has been pulled to within 50 ms of `first_polled_at + 8000` (or the expedite flag exists if the job was in flight).
    - Publishing a `polls.completed` message with `status="error"` sets `unknown_since_ms` on `avail:42:meta` and changes no slot record.
  </behavior>

  <action>
Write the failing end-to-end integration test first, then implement until it is green.

`services/state_machine/config.py` mirrors `services/poller/config.py`: `from __future__ import
annotations`, a header docstring citing D-42 and D-47a, env reads at module scope for
`KAFKA_BOOTSTRAP_SERVERS`, `REDIS_URL`, `DATABASE_URL_ASYNC` (copy the poller's exact defaults so the
two services never disagree), `CONSUMER_GROUP_ID: str = "state-machine"`, `ENV: str =
os.getenv("ENV", "dev")`, `MISE_CRASH_AFTER: str | None = os.getenv("MISE_CRASH_AFTER")`, and a
re-export of `CONFIRM_DELAY_MS` from `shared.redis_keys` with a `# noqa: F401` comment matching the
poller's re-export idiom (D-42 single source of truth).

`services/state_machine/store.py` gains `class RedisStateStore` implementing the `StateStore`
protocol from `engine.py`, taking a `redis.asyncio.Redis` in its constructor and using ONLY the typed
helpers `hgetall_slots`, `hset_slot`, `hdel_slot`, `hset_meta`, `expire_key` and the key builders
`avail_state_key` / `avail_meta_key` from `shared.redis_keys` — no inline key strings and no local
`cast` calls (D-42, research Pitfall 3). Decode every value defensively with the
`value.decode() if isinstance(value, (bytes, bytearray)) else str(value)` idiom from
`shared/scheduler/lua.py`, because `redis.from_url` defaults to `decode_responses=False`. Every write
path refreshes the key-level TTL to `AVAIL_STATE_TTL_SECONDS`; do not reach for per-field hash TTL —
that command does not exist on the pinned Redis 7.2 server. When `hdel_slot` removes the last field
the key disappears naturally; do not special-case it. Keep `MemoryStateStore` untouched.

`services/state_machine/persistence.py` provides `hours_before_service(service_date: date,
slot: dt_time, first_seen_ms: int) -> float` using `ZoneInfo("America/New_York")` for the service
datetime and UTC for `first_seen_at`, with a docstring recording the 17:00-23:00 service-window
assumption that makes DST transition hours unreachable (research Pattern 6, assumption A4);
`day_of_week(service_date: date) -> int` returning `service_date.isoweekday() % 7` so 0 is Sunday and
the value lines up with the Phase 6 heatmap y-axis (D-48, research B-5); `async def
insert_event(event: AvailabilityEvent) -> None` using `sqlalchemy.dialects.postgresql.insert` with
`.on_conflict_do_nothing(index_elements=["event_id", "time"])` — the arbiter MUST name `time` because
a hypertable unique index must include the partitioning column (research B-2); and
`async def close_event(event_id: UUID, confirmed_at: datetime, last_seen_at: datetime) -> None`
issuing an `update(...).where(AvailabilityEvent.event_id == ..., AvailabilityEvent.time == ...)` that
sets `last_seen_at` and `duration_seconds = int((last_seen_at - first_seen_at).total_seconds())`.
Naming `time` in that predicate is what prunes the update to a single chunk; omitting it degrades to a
bitmap scan across every chunk (research §Code Examples, verified EXPLAIN). Both functions go through
`shared.db.get_async_session()` and wrap their body in the repo's best-effort
`except Exception as exc:  # noqa: BLE001` log-and-continue shape from `services/poller/reaper.py`, so
a Postgres stall can never block the Kafka emit (D-48).

`services/state_machine/consumer.py` holds `class StateMachineConsumer` constructed with the started
consumer, producer, redis client, `LuaScheduler`, `DiffEngine`, and `StateStore`. `async def run()`
loops on `await self.consumer.getone()`; `handle_message(msg)` routes on `msg.topic`. For
`availability.raw`: validate into `AvailabilityRaw`, call `parse_raw`, and on `ParseError` or
`UnsupportedSourceError` call `engine.mark_unknown(...)` and commit without emitting (D-39, D-37).
For `polls.completed`: validate into `PollCompleted` and call `engine.mark_unknown` only when
`status` is `error` or `timeout` (D-47). Then execute each decision in the returned order:
`Expedite` calls `scheduler.expedite(job(source, rid), now_ms)`; `Emit` runs the D-46 order exactly —
`set_nx_ex(redis, event_idempotency_key(...), "1", EVENT_IDEMPOTENCY_TTL_SECONDS)`, then
`await producer.send_and_wait("availability.events", value=event.to_bytes(), key=f"{source}:{rid}")`,
then the store write marking the slot AVAILABLE with its `event_id`, then the best-effort
`insert_event`. Use `send_and_wait`, never `send`: the shared producer factory sets `linger_ms=20`, so
a bare `send` can return before the broker acks and the offset commit would overtake it. When the
claim fails, branch on the stored state: hash already `AVAILABLE` means a completed prior attempt, so
skip entirely; hash still `PENDING` means a crash between claim and hash write, so re-send the same
deterministic `event_id` and let the Phase 4 Layer-2 key dedupe it (D-46). `Close` calls
`close_event` and writes the UNAVAILABLE record. After the whole message, and only then,
`await self.consumer.commit({TopicPartition(msg.topic, msg.partition): msg.offset + 1})`; catch
`CommitFailedError` explicitly, log it, and continue — redelivery is safe by construction (research
Pitfall 4). Wrap the per-message body in the repo's log-and-continue catch-all so a poison message
commits and never stalls the partition. Log a distinct `mass_closure_detected` structlog event
carrying `restaurant_id`, `poll_id` and the count whenever `engine.last_close_count` exceeds
`MASS_CLOSURE_AUDIT_THRESHOLD`, so a sanitised or soft-banned response leaves an audit trail for the
Phase 3 canary. Never log `booking_token` or a full `raw_response` at INFO.

`services/state_machine/main.py` mirrors `services/poller/main.py` structurally: `configure_logging()`,
a `state_machine_starting` log, `redis.from_url(REDIS_URL)`, `LuaScheduler(r)` plus `await
scheduler.start()`, the `_assert_topics_exist` guard reusing the same `REQUIRED_TOPICS` set,
`make_producer(...)`, then `make_consumer("availability.raw", "polls.completed",
group_id=CONSUMER_GROUP_ID, bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS)`. Every async resource is
constructed inside `run()` — the consumer constructor calls `get_running_loop()` and raises at module
import time otherwise (research B-1). Build `RedisStateStore(r)`, `DiffEngine(store,
confirm_delay_ms=CONFIRM_DELAY_MS)` and `StateMachineConsumer(...)`, log `state_machine_ready`, then
`await sm.run()` inside a try/finally that stops the consumer, then the producer, then closes redis
with `aclose()`, logging `state_machine_stopped`. Before anything else, refuse to start when
`MISE_CRASH_AFTER` is set and `ENV == "prod"`, raising a `RuntimeError` naming the variable.

`services/state_machine/__main__.py` is the 7-line poller entrypoint copied with the name swapped.

Write `tests/integration/test_state_machine_e2e.py` following `tests/integration/test_poller_smoke.py`
lines 25-124: `pytestmark = pytest.mark.integration`, the three container fixtures, env vars set from
the container accessors, `reset_shared_db_singletons()` from the shared conftest, `apply_migrations` +
`create_topics`, publish the fixtures with a plain producer, `await asyncio.wait_for(run(), timeout=30)`
inside a `TimeoutError` swallow, then drain with a uniquely-named throwaway group and assert against
Kafka, Redis and Postgres. Set message `polled_at_epoch_ms` values explicitly 9000 ms apart — never
wait 9 real seconds.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/integration/test_state_machine_e2e.py -q -p no:cacheprovider && uv run ruff check . && uv run mypy shared/ services/</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/integration/test_state_machine_e2e.py -q -p no:cacheprovider` exits 0 with 0 skipped.
    - `uv run pytest tests/unit -q` exits 0 — the pure core is unchanged by this task.
    - `uv run python -c "import services.state_machine.main"` exits 0 (no module-scope consumer construction).
    - `grep -c "class StateMachineConsumer" services/state_machine/consumer.py` outputs 1.
    - `grep -c "class RedisStateStore" services/state_machine/store.py` outputs 1.
    - `grep -c "send_and_wait" services/state_machine/consumer.py` is 1 or greater and `grep -cE "producer\.send\(" services/state_machine/consumer.py` outputs 0.
    - `grep -c "on_conflict_do_nothing" services/state_machine/persistence.py` outputs 1.
    - `grep -c "enable_auto_commit" services/state_machine/consumer.py` outputs 0 — the setting lives in `shared/kafka.py::make_consumer` only.
    - String-literal-scoped negative gate: `grep -rnE '"avail:|f"avail:|"event:|f"event:' services/state_machine/store.py services/state_machine/consumer.py | wc -l` outputs 0 — every key comes from `shared.redis_keys` (D-42).
    - `uv run ruff check . && uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>

  <reversibility rating="costly">
    The `availability.events` wire payload and the Kafka key convention become a contract with
    Phase 4 (notifier) and Phase 5 (SSE) the moment events start flowing. The consumer group name
    `state-machine` also becomes live offset state.
  </reversibility>

  <done>
    `uv run python -m services.state_machine` consumes `availability.raw`, emits one confirmed
    `availability.events` message per genuine slot opening, writes the matching hypertable row, and
    commits its offset only after every side effect — proven end-to-end against live Kafka, Redis and
    TimescaleDB containers.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Crash-safety, closure, and service-time correctness</name>

  <precondition>The Docker daemon is reachable and `uv` is on PATH inside the test process, because the chaos test launches `uv run python -m services.state_machine` as a subprocess.</precondition>

  <read_first>
services/state_machine/consumer.py and persistence.py from Task 1;
.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md §Pattern 4 (the full crash-point
table — each row is a test case), §Code Examples (chaos-test crash hook, insert/close EXPLAIN plans),
§Pattern 6; .planning/phases/02-state-machine-event-pipeline/02-CONTEXT.md D-46, D-48, D-51;
tests/integration/test_poller_smoke.py lines 63-80 (the `subprocess.run(["uv", "run", ...], env=env)`
idiom the chaos test extends to `subprocess.Popen`); tests/integration/conftest.py.
  </read_first>

  <files>services/state_machine/consumer.py, services/state_machine/persistence.py, tests/integration/test_state_machine_chaos.py, tests/integration/test_availability_events_persistence.py, tests/unit/test_service_time_math.py</files>

  <behavior>
    - Chaos: the service is launched as a subprocess with `MISE_CRASH_AFTER=state_write`; it exits with `returncode == -9` (proving the hook actually fired rather than the test passing vacuously); relaunched without the hook it processes the same offsets again and the total count of `availability.events` records is exactly one per distinct `event_id`.
    - Two slots confirmed by one poll write two distinct `availability_events` rows sharing the same `time` value (the B-3 regression guard).
    - `insert_event` called twice with the same event leaves exactly one row (`ON CONFLICT (event_id, "time") DO NOTHING`).
    - `close_event` sets `last_seen_at` and a `duration_seconds` equal to the whole-second difference from `first_seen_at`, and touches no other row from the same poll.
    - A DB outage (session factory pointed at a closed port) during `insert_event` logs an error and returns normally — the caller still emits and still commits.
    - `hours_before_service(date(2026,5,1), time(19,0), first_seen_ms_for_2026_05_01T23_00Z)` equals 5.0; the DST-adjacent case `date(2026,3,8)` with the same slot time yields 29.0.
    - `day_of_week(date(2026,5,3))` is 0 (Sunday), `date(2026,5,4)` is 1 (Monday), `date(2026,5,9)` is 6 (Saturday).
  </behavior>

  <action>
Add the crash hook to `services/state_machine/consumer.py` exactly as 02-RESEARCH.md §Code Examples
specifies: a module-level `_CRASH_AFTER = os.getenv("MISE_CRASH_AFTER")` and a
`_maybe_crash(stage: str) -> None` that sends `signal.SIGKILL` to `os.getpid()` when the stage
matches. SIGKILL is required, not SIGTERM: a catchable signal would let `AIOKafkaConsumer.stop()` run
and commit the offset, which is precisely the behaviour the test must prevent. Call it at the four
stages `nx_claim`, `kafka_send`, `state_write`, and `commit`, each immediately AFTER the named step
completes. Give the helper a docstring marking it test-only and noting that `main.run()` refuses to
start with it set in prod.

Round out `persistence.py`: make `close_event` compute `duration_seconds` from the row's stored
`first_seen_at` rather than from a caller-supplied value, so a close can never disagree with the
insert; keep both `event_id` and `time` in the `WHERE` clause.

Write `tests/integration/test_state_machine_chaos.py` driving the subprocess pattern: publish the two
raw messages, `subprocess.Popen(["uv", "run", "python", "-m", "services.state_machine"],
env={**os.environ, "MISE_CRASH_AFTER": "state_write", ...})`, `proc.wait(timeout=60)`, assert
`proc.returncode == -signal.SIGKILL` first (without this assertion a run where the hook never fired
would pass vacuously), then relaunch without the hook under a timeout, then drain
`availability.events` and assert that the multiset of `event_id` values has no duplicates. This is
ROADMAP Phase 2 success criterion 3.

Write `tests/integration/test_availability_events_persistence.py` covering the two-slots-one-poll
case, the double-insert idempotency case, the close case with `duration_seconds`, and the DB-outage
best-effort case. This is ROADMAP Phase 2 success criterion 4.

Write `tests/unit/test_service_time_math.py` with the exact numeric expectations above, including the
DST-adjacent date, so the timezone math is pinned without a container.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/unit/test_service_time_math.py -q && uv run pytest tests/integration/test_state_machine_chaos.py tests/integration/test_availability_events_persistence.py -q -p no:cacheprovider</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/integration/test_state_machine_chaos.py -q -p no:cacheprovider` exits 0 with 0 skipped.
    - `uv run pytest tests/integration/test_availability_events_persistence.py -q -p no:cacheprovider` exits 0.
    - `uv run pytest tests/unit -q` exits 0.
    - `grep -c "signal.SIGKILL" services/state_machine/consumer.py` is 1 or greater.
    - `grep -c "_maybe_crash" services/state_machine/consumer.py` is 5 or greater (definition plus four call sites).
    - `grep -c "returncode == -signal.SIGKILL\|returncode == -9" tests/integration/test_state_machine_chaos.py` is 1 or greater.
    - `grep -c "isoweekday" services/state_machine/persistence.py` outputs 1.
    - `grep -c "America/New_York" services/state_machine/persistence.py` outputs 1.
    - `uv run ruff check . && uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>

  <reversibility rating="reversible">
    The crash hook and the persistence helpers are internal; changing stage names costs a test edit.
  </reversibility>

  <done>
    A SIGKILL between the hash write and the offset commit produces zero duplicate events on restart,
    one poll confirming two slots writes two rows, closures stamp `duration_seconds`, and the
    New-York service-time math is pinned by unit test including a DST-adjacent date.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Redis state-store durability, emission-idempotency unit proof, service README, and the no-inline-sleep gate</name>

  <precondition>The Docker daemon is reachable for the Redis-backed store test; the unit tests in this task need no container.</precondition>

  <read_first>
services/state_machine/store.py and consumer.py from Tasks 1-2; shared/redis_keys.py as extended by
plan 02-02 (the typed HASH helpers and TTL constants);
.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md §Pitfall 6, §Pattern 4 (the crash
table that the README diagram reproduces), §Assumptions Log A5 and A6, §Open Questions Q1;
.planning/phases/02-state-machine-event-pipeline/02-CONTEXT.md D-40, D-41, D-46, D-52, §Specific
Ideas; services/poller/sources/opentable/README.md (the repo's service-README tone);
tests/unit/test_redis_keys.py (the `AsyncMock` idiom for asserting a single Redis call).
  </read_first>

  <files>services/state_machine/store.py, services/state_machine/README.md, tests/integration/test_redis_state_store.py, tests/unit/test_emission_idempotency.py, tests/unit/test_no_inline_sleep.py</files>

  <behavior>
    - `RedisStateStore.put_slot` then `get_slots` round-trips a `SlotRecord` byte-for-byte through the compact JSON codec, against a live Redis 7.2 container.
    - After any write, `TTL avail:42:2026-05-01:2` is 90000 or within a second of it, and a second write refreshes it back up.
    - `drop_slot` removes the field; removing the last field makes the key vanish (`EXISTS` returns 0).
    - `get_slots` on an absent key returns an empty dict, and `get_meta` on an absent restaurant returns a `MetaRecord` with both fields `None` (the empty-input edge).
    - The store issues no per-field hash TTL command — asserted by source grep, because that command exists in the redis-py client but not on the pinned 7.2 server and would fail only at runtime.
    - Emission idempotency (unit, `AsyncMock` Redis): with the claim returning `False` and the stored record `AVAILABLE`, the shell performs no Kafka send; with the claim returning `False` and the stored record `PENDING`, the shell sends exactly once with the same `event_id`; with the claim returning `True`, the shell sends exactly once. The claim itself is a single `r.set(key, "1", nx=True, ex=1200)` call.
    - `services/state_machine/` contains zero inline asynchronous sleeps used as a confirmation delay.
  </behavior>

  <action>
Finish `RedisStateStore`: make `get_meta` synthesise an empty `MetaRecord` for a missing key rather
than raising, refresh the key TTL on every mutating call, and keep every key string coming from
`shared.redis_keys`. Add a short module comment recording that key-level `EXPIRE` is deliberate
because per-field hash TTL is a Redis 7.4 server feature and the pinned server is `redis:7.2-alpine`
(D-40, research Pitfall 6).

Write `tests/integration/test_redis_state_store.py` following the
`tests/integration/test_scheduler_claim_release.py` shape (module-scoped `redis_url`, explicit
clean-slate deletes, `await r.aclose()`), covering the round-trip, the TTL refresh, the field drop,
and both empty-input cases.

Write `tests/unit/test_emission_idempotency.py` using `unittest.mock.AsyncMock` for the Redis client
and the producer, mirroring the single-call assertion idiom in `tests/unit/test_redis_keys.py`. Assert
the three claim outcomes above and assert the producer mock's call count in each. Assert the claim is
made with `nx=True` and `ex=1200` in one call.

Write `tests/unit/test_no_inline_sleep.py` as a source-grep gate over `services/state_machine/**.py`:
zero matches for an inline asynchronous sleep call, because STATE-03 requires confirmation to be
stream-based through the ZSET scheduler and the CI ban-greps do not catch the async variant — only a
test can. Strip full-line comments before counting. Also assert zero matches for the synchronous
sleep call, duplicating the CI gate at the unit tier so a developer sees it before pushing.

Write `services/state_machine/README.md` containing: a one-paragraph purpose statement; the full
D-41 state-transition table with columns `From`, `Trigger`, `To`, `Emits`; the D-46 ordering diagram
rendered as an ASCII pipeline with the crash-point table from 02-RESEARCH.md §Pattern 4 reproduced
verbatim, since that table is the argument for why the order is what it is; a `## How to join`
section stating that `restaurant_id` everywhere in this service is the SOURCE PLATFORM ID and that
Phases 4, 5 and 6 must join `restaurants` on `(source, platform_id)`, never on `restaurants.id`
(D-52, research Q1); a `## Scaling` note recording that the topic has one partition so the service
scales by partition count, not replica count, and that a second group member would simply idle
(research A5, A6); a `## Replay` line pointing at `uv run python scripts/replay_raw.py --help` and
stating that `--to-offset` is EXCLUSIVE and defaults to the topic end offsets (D-55); and a
`## Environment` table listing `KAFKA_BOOTSTRAP_SERVERS`, `REDIS_URL`, `DATABASE_URL_ASYNC`,
`CONFIRM_DELAY_MS`, and `MISE_CRASH_AFTER` with the last one marked TEST ONLY.
  </action>

  <verify>
    <automated>cd /Users/aryanahuja/projects/mise && uv run pytest tests/unit -q && uv run pytest tests/integration/test_redis_state_store.py -q -p no:cacheprovider && uv run ruff check . && uv run mypy shared/ services/</automated>
  </verify>

  <acceptance_criteria>
    - `uv run pytest tests/unit -q` exits 0 with zero failures and zero skips.
    - `uv run pytest tests/integration/test_redis_state_store.py -q -p no:cacheprovider` exits 0 with 0 skipped.
    - `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 across all files.
    - Region-scoped negative gate (code lines only): `grep -hvE "^\s*#" services/state_machine/*.py services/state_machine/parsers/*.py | grep -cE "asyncio\.sleep\("` outputs 0.
    - `grep -c "PENDING" services/state_machine/README.md` is 3 or greater and `grep -c "platform" services/state_machine/README.md` is 1 or greater.
    - `grep -c "to-offset" services/state_machine/README.md` is 1 or greater.
    - `grep -c "MISE_CRASH_AFTER" services/state_machine/README.md` is 1 or greater.
    - `uv run ruff check . && uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>

  <reversibility rating="reversible">
    Documentation and test gates; freely editable.
  </reversibility>

  <done>
    The Redis-backed store is proven durable with a refreshed 25-hour key TTL, emission idempotency is
    unit-proven for all three claim outcomes, an inline-sleep gate protects STATE-03 forever, and the
    service README records the transition table, the emit ordering rationale, and the platform-id
    join rule that Phases 4, 5 and 6 depend on.
  </done>
</task>

</tasks>

<threat_model>
| Boundary | Description |
|----------|-------------|
| third-party scraped JSON to state machine | `raw_response` is untrusted third-party content entering the parser and the logs. |
| test-only crash hook to deployed runtime | `MISE_CRASH_AFTER` can SIGKILL the process if it leaks into a deployed environment. |

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-02-02 | Denial of Service | `parsers/opentable.py` to `consumer.handle_message` | high | mitigate | Every payload access is a `.get()` chain, all failures collapse to `ParseError`, and the per-message body has a log-and-continue catch-all that still commits, so a hostile payload cannot stall the partition. |
| T-02-03 | Information Disclosure | `consumer.py` structlog calls | medium | mitigate | Log `poll_id`, `restaurant_id` and counts only; never `booking_token` and never a full `raw_response` at INFO. `shared/telemetry.py` redaction stays in force. |
| T-02-04 | Denial of Service | `MISE_CRASH_AFTER` in `main.run()` | medium | mitigate | Defaults to unset; `main.run()` raises a `RuntimeError` naming the variable when it is set and `ENV == "prod"`; the README marks it TEST ONLY. |
</threat_model>

<artifacts_this_phase_produces>
## Artifacts this phase produces (this plan's share)

**New files**
- `services/state_machine/config.py`
- `services/state_machine/persistence.py`
- `services/state_machine/consumer.py`
- `services/state_machine/main.py`
- `services/state_machine/__main__.py`
- `services/state_machine/README.md`
- `tests/integration/test_state_machine_e2e.py`
- `tests/integration/test_state_machine_chaos.py`
- `tests/integration/test_availability_events_persistence.py`
- `tests/integration/test_redis_state_store.py`
- `tests/unit/test_service_time_math.py`
- `tests/unit/test_emission_idempotency.py`
- `tests/unit/test_no_inline_sleep.py`

**Modified files**
- `services/state_machine/store.py` (adds `RedisStateStore` beside `MemoryStateStore`)

**Symbols created**

| Symbol | Kind | Module |
|--------|------|--------|
| `KAFKA_BOOTSTRAP_SERVERS`, `REDIS_URL`, `DATABASE_URL_ASYNC`, `CONSUMER_GROUP_ID`, `ENV`, `MISE_CRASH_AFTER`, `CONFIRM_DELAY_MS` (re-export) | config constants | `services/state_machine/config.py` |
| `RedisStateStore` | class implementing `StateStore` | `services/state_machine/store.py` |
| `hours_before_service(service_date, slot, first_seen_ms) -> float` | function | `services/state_machine/persistence.py` |
| `day_of_week(service_date) -> int` | function | `services/state_machine/persistence.py` |
| `insert_event(event) -> None` | async function (upsert) | `services/state_machine/persistence.py` |
| `close_event(event_id, confirmed_at, last_seen_at) -> None` | async function | `services/state_machine/persistence.py` |
| `StateMachineConsumer`, `.run()`, `.handle_message()` | class + methods | `services/state_machine/consumer.py` |
| `_CRASH_AFTER`, `_maybe_crash(stage)` | test-only crash hook (stages `nx_claim`, `kafka_send`, `state_write`, `commit`) | `services/state_machine/consumer.py` |
| `REQUIRED_TOPICS`, `_assert_topics_exist`, `run()` | startup guard + lifecycle | `services/state_machine/main.py` |

**Environment variables introduced**

| Name | Default | Notes |
|------|---------|-------|
| `CONFIRM_DELAY_MS` | 8000 | Confirmation window; single source of truth is `shared.redis_keys` |
| `MISE_CRASH_AFTER` | unset | TEST ONLY — SIGKILLs the process after the named stage; refused when `ENV=prod` |
| `ENV` | `dev` | Guards the crash hook |

**Kafka surface**
- Consumes `availability.raw` and `polls.completed` in consumer group `state-machine` (manual commit)
- Produces `availability.events` with key `{source}:{restaurant_id}`
</artifacts_this_phase_produces>

<verification>
- `uv run pytest tests/unit -q` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 with 0 skipped on a Docker-enabled machine.
- `uv run ruff check . && uv run mypy shared/ services/` exits 0.
- The three CI ban-greps return nothing over `services/` and `shared/`.
- `uv run python -m services.state_machine` started against a `make up` stack logs `state_machine_ready` and exits cleanly on interrupt.
</verification>

<success_criteria>
- Two raw polls 9 s apart produce exactly one Kafka event and one hypertable row; a third poll without
  the slot stamps `duration_seconds` (ROADMAP SC4, STATE-05).
- A kill -9 between diff and commit produces zero duplicate events on restart (ROADMAP SC3, STATE-04).
- Transient errors and unparseable payloads flow to UNKNOWN and never flip a slot to UNAVAILABLE
  (ROADMAP SC1, STATE-02).
- Confirmation is stream-based with no inline sleep anywhere in the service (STATE-03).
- All Redis state lives under the `shared/redis_keys.py` contract with a refreshed 25-hour TTL
  (STATE-01).
</success_criteria>

<output>
Create `.planning/phases/02-state-machine-event-pipeline/02-03-SUMMARY.md` when done.
</output>
