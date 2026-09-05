---
phase: 02-state-machine-event-pipeline
plan: 02
subsystem: infra
tags: [redis, lua, kafka, timescaledb, alembic, mypy-strict, tdd]

# Dependency graph
requires:
  - phase: 01-foundation-admin-pre-conditions-opentable-polling
    provides: "shared/redis_keys.py (SCHED_POLLS, set_nx_ex, CLAIM_POLL_LUA), shared/scheduler/lua.py LuaScheduler, shared/kafka.py make_producer, migrations 0006/0007, tests/conftest.py container fixtures"
provides:
  - "EXPEDITE_POLL_LUA + LuaScheduler.expedite/consume_expedite — a PENDING slot pulls its restaurant's next poll forward to t+8s through the existing ZSET scheduler"
  - "Poller release path that consumes the expedite flag exactly once and falls back to the D-17 jitter band"
  - "Phase 2 Redis key/TTL registry: avail_state_key, avail_meta_key, event_idempotency_key, sched_expedite_key + four TTL constants"
  - "Five typed async HASH helpers that keep every cast(Awaitable[T], ...) in one module so store.py needs none"
  - "make_consumer(*topics, group_id=...) — varargs, manual-commit AIOKafkaConsumer factory"
  - "Migration 0008: event_id UUID NOT NULL + hypertable-legal UNIQUE (event_id, time) + column-semantics comments"
  - "AvailabilityEvent ORM primary key (time, event_id), matching the migration"
  - "tests/integration/conftest.py — apply_migrations / create_topics / redis_url / db_urls for every Phase 2 integration file"
  - "Permanent source-grep gate proving zero two-command SETNX+EXPIRE claims (ROADMAP SC3, mechanical half)"
affects: [02-03-consumer-shell-persistence, 02-04-replay-determinism, 03-resy, 04-notifier, 06-pattern-intelligence]

actuals:
  tokens: 16100
  tasks: 3
  commits: 6

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Server-side atomicity for cross-service handshakes: ZSCORE + conditional ZADD XX LT in one Lua round trip, never a read-compare-write in Python"
    - "Every mypy-strict cast for a third-party client lives once, in the module that owns the key namespace"
    - "Negative-control regression guards: assert the server REJECTS the wrong schema shape, not just that the right one works"
    - "Content gates strip full-line comments before matching, so an explanatory comment can never satisfy or break the gate"

key-files:
  created:
    - migrations/versions/0008_add_event_id_to_availability_events.py
    - tests/integration/conftest.py
    - tests/integration/test_expedite_lua.py
    - tests/integration/test_poller_expedite_release.py
    - tests/integration/test_migration_0008.py
    - tests/unit/test_redis_keys_phase2.py
    - tests/unit/test_kafka_consumer_config.py
    - tests/unit/test_no_setnx_expire_pairs.py
  modified:
    - shared/redis_keys.py
    - shared/scheduler/lua.py
    - shared/kafka.py
    - shared/db.py
    - services/poller/scheduler.py
    - ops/docker-compose.yml

key-decisions:
  - "The expedite is server-side atomic: ZSCORE + conditional ZADD XX LT in one Lua round trip, because a read-compare-write in Python would race the poller's CLAIM"
  - "XX is mandatory (never resurrect an in-flight job into a duplicate concurrent poll); LT is mandatory (never push an already-sooner poll later); plain ZADD and GT are both wrong"
  - "consume_expedite lives on LuaScheduler rather than a new Redis handle, because poll_loop's signature only carries the scheduler"
  - "availability_events PK is (time, event_id); restaurant_id left the PK because every slot confirmed by one poll shares that poll's time (research B-3)"
  - "availability_events.restaurant_id is the SOURCE PLATFORM id, recorded in the database itself via COMMENT ON COLUMN plus an ORM docstring (D-52)"
  - "Requirements STATE-01/03/05 left Pending — this plan ships primitives and schema; the state store, consumer shell and persistence land in 02-03"

patterns-established:
  - "Pattern: an integration module that imports service code must restore sys.modules on teardown, because services/poller/config.py freezes env vars at import time"
  - "Pattern: prove a schema constraint is real by asserting the server's rejection message ('used in partitioning'), so no future maintainer 'simplifies' the index away"
  - "Pattern: mechanical architecture gates (SETNX, type-suppression, image pin) are validated with a mutation probe before being trusted"

requirements-completed: []

coverage:
  - id: D1
    description: "A queued job is pulled forward to exactly now_ms + 8000 via ZADD XX LT"
    requirement: STATE-03
    verification:
      - kind: integration
        ref: "tests/integration/test_expedite_lua.py#test_queued_job_is_pulled_forward_to_confirm_delay"
        status: pass
    human_judgment: false
  - id: D2
    description: "LT never raises an already-earlier score; XX never resurrects an in-flight job into the ready set"
    requirement: STATE-03
    verification:
      - kind: integration
        ref: "tests/integration/test_expedite_lua.py#test_lt_guard_never_raises_an_already_earlier_score"
        status: pass
      - kind: integration
        ref: "tests/integration/test_expedite_lua.py#test_xx_guard_never_resurrects_an_inflight_job"
        status: pass
      - kind: integration
        ref: "tests/integration/test_expedite_lua.py#test_expedite_never_pulls_a_poll_below_the_confirm_delay"
        status: pass
    human_judgment: false
  - id: D3
    description: "The in-flight branch leaves a flag with a 120 s TTL that GETDEL consumes exactly once; an absent flag returns False rather than raising"
    requirement: STATE-03
    verification:
      - kind: integration
        ref: "tests/integration/test_expedite_lua.py#test_consume_expedite_is_exactly_once"
        status: pass
      - kind: integration
        ref: "tests/integration/test_expedite_lua.py#test_consume_expedite_on_an_absent_flag_returns_false"
        status: pass
    human_judgment: false
  - id: D4
    description: "The real poller release path uses now_ms + CONFIRM_DELAY_MS when the flag is set and the 90s +/- 15% jitter band when it is not"
    requirement: STATE-03
    verification:
      - kind: integration
        ref: "tests/integration/test_poller_expedite_release.py#test_release_with_expedite_flag_uses_confirm_delay"
        status: pass
      - kind: integration
        ref: "tests/integration/test_poller_expedite_release.py#test_release_without_flag_uses_the_jitter_band"
        status: pass
      - kind: integration
        ref: "tests/integration/test_poller_expedite_release.py#test_expedite_flag_is_consumed_by_the_release"
        status: pass
    human_judgment: false
  - id: D5
    description: "Threat T-02-01: a five-call expedite burst yields exactly one ZSET member at one score, so PENDING slots cannot compound into repeated pulled-forward polls"
    verification:
      - kind: integration
        ref: "tests/integration/test_expedite_lua.py#test_a_burst_of_expedites_yields_one_member_at_one_score"
        status: pass
    human_judgment: false
  - id: D6
    description: "Every Phase 2 Redis key pattern and TTL is declared once in shared/redis_keys.py; builders are total, adjacency-safe and touch no Redis"
    requirement: STATE-01
    verification:
      - kind: unit
        ref: "tests/unit/test_redis_keys_phase2.py#test_adjacent_party_sizes_never_collide"
        status: pass
      - kind: unit
        ref: "tests/unit/test_redis_keys_phase2.py#test_key_builders_are_total_and_touch_no_redis"
        status: pass
      - kind: unit
        ref: "tests/unit/test_redis_keys_phase2.py#test_availability_ttl_constants"
        status: pass
      - kind: unit
        ref: "tests/unit/test_redis_keys_phase2.py#test_hash_helpers_are_exported_so_store_needs_no_casts"
        status: pass
    human_judgment: false
  - id: D7
    description: "make_consumer builds a manual-commit consumer from varargs topics and is constructible only inside a running loop (research B-1)"
    verification:
      - kind: unit
        ref: "tests/unit/test_kafka_consumer_config.py#test_make_consumer_config"
        status: pass
      - kind: unit
        ref: "tests/unit/test_kafka_consumer_config.py#test_real_consumer_accepts_varargs_and_rejects_a_list"
        status: pass
      - kind: unit
        ref: "tests/unit/test_kafka_consumer_config.py#test_consumer_construction_outside_a_running_loop_raises"
        status: pass
    human_judgment: false
  - id: D8
    description: "Migration 0008 applies on a live hypertable: event_id is uuid NOT NULL and the unique index covers (event_id, time)"
    requirement: STATE-05
    verification:
      - kind: integration
        ref: "tests/integration/test_migration_0008.py#test_event_id_column_is_uuid_not_null"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0008.py#test_unique_index_covers_event_id_and_time"
        status: pass
    human_judgment: false
  - id: D9
    description: "Research B-2 and B-3 carry standing regression guards: a time-less unique index is rejected by the server, and two slots confirmed by one poll write two rows"
    requirement: STATE-05
    verification:
      - kind: integration
        ref: "tests/integration/test_migration_0008.py#test_b2_guard_unique_index_without_time_is_rejected"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0008.py#test_b3_guard_one_poll_confirming_two_slots_writes_two_rows"
        status: pass
    human_judgment: false
  - id: D10
    description: "Idempotency edge (STATE-05): re-running upgrade head is a no-op and downgrade -1 followed by upgrade head restores the same schema; ON CONFLICT (event_id, time) inserts once"
    requirement: STATE-05
    verification:
      - kind: integration
        ref: "tests/integration/test_migration_0008.py#test_reapplying_head_is_a_no_op"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0008.py#test_downgrade_then_upgrade_restores_the_same_schema"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0008.py#test_on_conflict_event_id_time_is_idempotent"
        status: pass
    human_judgment: false
  - id: D11
    description: "Column semantics are recorded in the database itself: day_of_week is 0=Sun..6=Sat (B-5) and restaurant_id is the source platform id (D-52)"
    verification:
      - kind: integration
        ref: "tests/integration/test_migration_0008.py#test_column_comments_record_the_semantics"
        status: pass
    human_judgment: false
  - id: D12
    description: "The source tree provably contains zero two-command SETNX+EXPIRE idempotency claims (ROADMAP SC3, mechanical half)"
    verification:
      - kind: unit
        ref: "tests/unit/test_no_setnx_expire_pairs.py#test_no_two_command_setnx_expire_pairs"
        status: pass
      - kind: unit
        ref: "tests/unit/test_no_setnx_expire_pairs.py#test_set_nx_ex_is_a_single_atomic_call"
        status: pass
    human_judgment: false
  - id: D13
    description: "`make up` resolves its Kafka image again — bitnamilegacy/kafka:3.8 with every KAFKA_CFG_* variable unchanged"
    verification:
      - kind: command
        ref: "docker compose -f ops/docker-compose.yml config | grep bitnamilegacy/kafka:3.8"
        status: pass
    human_judgment: false
  - id: D14
    description: "A ZADD XX LT against sched:polls while the poller concurrently runs CLAIM_POLL_LUA never produces a duplicate concurrent poll"
    verification: []
    human_judgment: true
    rationale: "Backstop truth. The XX guard makes the dangerous interleaving structurally impossible (a claimed job is ZREM'd from sched:polls, so XX finds no member and takes the flag branch), and test_xx_guard_never_resurrects_an_inflight_job proves that branch. A true concurrent-race test would need a multi-process harness with deterministic interleaving, which is out of scope for this plan."

# Metrics
duration: 14min
completed: 2026-09-05
status: complete
---

# Phase 2 Plan 02: Shared Kernel, Expedite & Schema Summary

**The confirmation handshake now exists as a server-side-atomic Redis primitive — a PENDING slot pulls its restaurant's next poll forward to exactly t+8s and the poller consumes that intent exactly once — and the three schema defects research reproduced as hard runtime errors are fixed with standing regression guards.**

## Performance

- **Duration:** 14 min
- **Started:** 2026-09-05T05:24Z
- **Completed:** 2026-09-05T05:38Z
- **Tasks:** 3
- **Files modified:** 14 (8 created, 6 modified), 1078 insertions

## Accomplishments

- **The expedite handshake is proven against a live Redis 7.2 container, including both guards that make it safe.** `EXPEDITE_POLL_LUA` performs `ZSCORE` and the conditional `ZADD XX LT` in one round trip. `XX` means an in-flight job is never resurrected into the ready set (which would be a duplicate concurrent poll against a third party); `LT` means an already-sooner poll is never pushed later. Both are asserted as behaviour, not as code review.
- **The threat-model mitigation is a test, not a promise.** T-02-01 (self-inflicted DoS / third-party ToS risk) is guarded by `test_a_burst_of_expedites_yields_one_member_at_one_score`: five PENDING slots in one poll leave exactly one ZSET member at one score, so a burst cannot compound into five pulled-forward polls.
- **The poller release test drives the real `poll_loop`,** not a re-implementation of its release branch — it seeds a due job, runs the production coroutine against a live Redis, and asserts the released score lands at `now_ms + 8000` with the flag set and inside the 90 s ± 15 % jitter band without it.
- **Research B-2 and B-3 now have negative-control regression guards.** The suite asserts the server *rejects* `CREATE UNIQUE INDEX ... (restaurant_id, event_id)` with `used in partitioning`, and that two slots sharing one poll's `time` both insert. These prove the constraint is real rather than folklore, so no future maintainer simplifies the index away.
- **`mypy --strict` stays clean with zero type suppressions.** All five HASH helpers use the precise `cast(Awaitable[int])` / `cast(Awaitable[dict[bytes, bytes]])` forms, so `services/state_machine/store.py` in plan 02-03 can be written with no casts at all and D-42 is satisfied by construction.
- **Column semantics now live in the database.** `day_of_week` carries the `0=Sun .. 6=Sat` comment that supersedes migration 0006's stale note, and `restaurant_id` carries the D-52 statement that it holds the source platform id and that the join key against `restaurants` is `(source, platform_id)` — the defect that would otherwise have made Phase 6's heatmap join return zero rows.
- Unit suite grew 95 → 111; integration suite grew 12 → 30. `ruff`, `mypy --strict`, all three CI ban-greps and `docker compose config` are green.

## Task Commits

Each task was committed atomically with its TDD gates:

1. **Task 1 (tracer, tdd): a PENDING slot pulls the next poll forward to t+8s**
   - RED: `b12c7a2` (test) — `tests/integration/conftest.py` + the three expedite test files
   - GREEN: `4420836` (feat) — `EXPEDITE_POLL_LUA`, `LuaScheduler.expedite`/`consume_expedite`, poller release branch
2. **Task 2 (tdd): Redis state-key registry, typed HASH helpers, manual-commit consumer factory**
   - RED: `d7e2edd` (test) — availability keys, `make_consumer` config, SETNX source gate
   - GREEN: `c9390b9` (feat) — `avail_*_key`, TTL constants, five HASH helpers, `make_consumer`
3. **Task 3 (tdd): migration 0008, ORM primary-key remap, Kafka image repoint**
   - RED: `dc19d1a` (test) — schema, B-2/B-3 guards, comments, downgrade round trip
   - GREEN: `529fef3` (feat) — migration 0008, `AvailabilityEvent` PK remap, `bitnamilegacy/kafka:3.8`

**Plan metadata:** see the `docs(02-02)` commit carrying this SUMMARY, STATE.md and ROADMAP.md.

## Files Created/Modified

**Created**
- `migrations/versions/0008_add_event_id_to_availability_events.py` — `event_id UUID NOT NULL`, `uq_availability_events_event_id_time`, two `COMMENT ON COLUMN` statements, a real `downgrade()`, and the reproduced anti-autogenerate warning
- `tests/integration/conftest.py` — `reset_shared_db_singletons`, `apply_migrations`, `create_topics`, `redis_url`, `db_urls`
- `tests/integration/test_expedite_lua.py` — 7 tests: XX, LT, flag TTL, exactly-once GETDEL, absent-flag edge, burst guard, below-delay prohibition
- `tests/integration/test_poller_expedite_release.py` — 3 tests driving one real `poll_loop` release iteration
- `tests/integration/test_migration_0008.py` — 8 tests including both negative controls and the downgrade round trip
- `tests/unit/test_redis_keys_phase2.py` — 14 tests: key strings, TTLs, Lua content, adjacency and empty edges
- `tests/unit/test_kafka_consumer_config.py` — 5 tests: factory kwargs, varargs form, live B-1 `TypeError`, no-loop `RuntimeError`
- `tests/unit/test_no_setnx_expire_pairs.py` — 3 tests: the permanent source-grep gate plus a guard-the-guard non-vacuity check

**Modified**
- `shared/redis_keys.py` — availability section (2 TTL constants, 3 key builders, 5 typed HASH helpers), expedite section (2 constants, `sched_expedite_key`), `EXPEDITE_POLL_LUA`, updated `Named symbols:` header
- `shared/scheduler/lua.py` — `_expedite_sha` slot, `script_load` in `start()`, `expedite()` and `consume_expedite()`
- `shared/kafka.py` — `make_consumer` factory, updated module docstring
- `shared/db.py` — `AvailabilityEvent` PK remapped to `(time, event_id)`, `restaurant_id` dropped from the PK, class docstring recording B-3 and the close-UPDATE predicate, D-52 comment on `restaurant_id`
- `services/poller/scheduler.py` — release branch consumes the expedite flag and logs `poll_expedited`; `_next_poll_score` untouched as the default
- `ops/docker-compose.yml` — Kafka image repointed with a comment recording why the tag moved

## Decisions Made

- **`consume_expedite` lives on `LuaScheduler`** rather than being plumbed as a new Redis handle through `poll_loop`, because `poll_loop`'s signature only carries the scheduler. Adding a parameter would have changed a public signature for one `GETDEL`.
- **The expedite is a Lua script rather than Python logic.** A read-compare-write (`ZSCORE`, then decide, then `ZADD`) would race the poller's `CLAIM_POLL_LUA` on the same job: the job could be claimed between the read and the write, and the write would then resurrect an in-flight job into the ready set. One round trip removes the window entirely.
- **The prohibition is enforced by the `LT` flag itself.** `test_expedite_never_pulls_a_poll_below_the_confirm_delay` seeds a score already earlier than `now_ms` and asserts the expedite leaves it alone — the expedite can only ever pull a poll forward to `now_ms + 8000`, never below it and never later.
- **Both `restaurant_id` semantics statements are duplicated deliberately** — once in `COMMENT ON COLUMN` (found by anyone inspecting the database) and once in the ORM docstring (found by anyone reading `shared/db.py`). Pitfall 5 is a silent-wrong-answer defect; redundancy is cheap next to a Phase 6 heatmap that returns zero rows.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] New integration module silently broke `test_poller_smoke.py` in full-suite runs**
- **Found during:** Task 3 (full integration suite run)
- **Issue:** `tests/integration/test_poller_expedite_release.py` imports `poll_loop` at module level, which transitively imports `services/poller/config.py`. That module freezes `REDIS_URL` and `KAFKA_BOOTSTRAP_SERVERS` into module constants at **import time**. Because collection happens before any test runs, `config` was imported and frozen at the `localhost:6379` default before `test_poller_smoke.py` set `REDIS_URL` to its testcontainer. The smoke test then failed with `OSError: Connect call failed ('127.0.0.1', 6379)` — but only in a full-suite run, passing in isolation. This is precisely the class of failure that looks like flakiness and gets re-run rather than fixed.
- **Fix:** A module-scoped autouse teardown fixture in the *new* file evicts `services.poller.{main,scheduler,config}` from `sys.modules`, so any later import re-reads the environment. The existing test files were not edited, per the plan's instruction.
- **Files modified:** `tests/integration/test_poller_expedite_release.py`
- **Verification:** `uv run pytest tests/integration -q -p no:cacheprovider` → 30 passed (was 29 passed / 1 failed).
- **Committed in:** `529fef3`
- **Note for 02-03:** the underlying import-time env freeze in `services/poller/config.py` is still there. Plan 02-03 adds `services/state_machine/main.py` and will import service code from integration tests again; the same teardown discipline applies, or the constants should become functions. Logged to `deferred-items.md`.

**2. [Rule 3 - Blocking] Two of the plan's own mechanical gates were tripped by the explanatory comments the plan asked for**
- **Found during:** Tasks 1 and 2
- **Issue:** Two acceptance criteria are literal greps: `grep "'GT'"` must be absent from the Lua content assertion, and `grep -rn "type: ignore" shared/redis_keys.py | wc -l` must be `0`. But the plan also instructs the code to *explain* that `GT` is wrong and that `type: ignore` must never be used. Writing the mandated comment breaks the mandated gate.
- **Fix:** Applied the plan's own stated principle (Task 2: "Strip full-line comments before matching so an explanatory comment can never satisfy or break the gate"). The Lua content test now strips `--` comment lines before asserting, so the comment explaining why `GT` is wrong survives. For the `type: ignore` gate, which is an external grep I cannot make comment-aware, the comment was reworded to "Never suppress these awaits with a blanket type-suppression comment" — same meaning, gate returns 0.
- **Files modified:** `tests/unit/test_redis_keys_phase2.py`, `shared/redis_keys.py`
- **Verification:** `grep -rn "type: ignore" shared/redis_keys.py | wc -l` → 0; `uv run pytest tests/unit -q` → 111 passed.
- **Committed in:** `4420836`, `c9390b9`

### Decisions Taken Autonomously (no human in the loop)

**3. Requirements STATE-01 / STATE-03 / STATE-05 left `Pending` in REQUIREMENTS.md**
- The plan frontmatter lists all three, but each requirement's text describes behaviour that this plan only supplies the primitives for. STATE-01 requires that Redis state "tracks currently known slot tokens" — this plan declares the keys, TTLs and helpers, but `RedisStateStore` lands in 02-03. STATE-03 requires that "only confirmed slots emit `availability.events`" — the expedite mechanism is complete and proven, but nothing emits yet. STATE-05 requires that "`availability.events` persist to TimescaleDB" — the schema is ready and correct, but the persistence path is 02-03.
- Marking them Done after plan 2 of 4 would put a false green in the traceability matrix and mislead the phase verifier. `requirements-completed` is `[]`, with the evidence recorded in the `coverage:` block above so the verifier can close all three once 02-03 lands. This follows the precedent set by 02-01.

**4. Two grep-count acceptance criteria return 2 rather than the stated 1**
- `grep -c "max_poll_records=1" shared/kafka.py` and `grep -c "enable_auto_commit=False" shared/kafka.py` each return 2, not 1. The second occurrence in each case is the module header docstring (`Named consumer config: enable_auto_commit=False, auto_offset_reset='earliest', max_poll_records=1`), written to mirror the file's existing `Named producer config:` header style.
- The criteria's intent is "the kwarg is present", and the duplicate is documentation of exactly that config. Kept, because deleting the header line to satisfy a counting gate would trade a real readability convention for a number.

---

**Total deviations:** 2 auto-fixed (1 bug, 1 blocking) + 2 autonomous decisions recorded
**Impact on plan:** No scope change. Deviation 1 is a genuine latent defect in the repo's test isolation that this plan's new file was the first to expose; deviation 2 is an internal contradiction between the plan's comment instructions and its own grep gates, resolved in favour of keeping both the comment and the gate.

## TDD Gate Compliance

All three tasks have clean RED → GREEN gate pairs: `b12c7a2`→`4420836`, `d7e2edd`→`c9390b9`, `dc19d1a`→`529fef3`.

Two RED phases contained tests that passed on first run. Per the fail-fast rule neither was waved through:

| Unexpectedly passing test | Why it passed | Mutation probe | Result |
|---|---|---|---|
| `test_no_two_command_setnx_expire_pairs` + `test_set_nx_ex_is_a_single_atomic_call` | Standing architectural gates — the tree was already compliant, so green is the correct initial state | Rewrote `set_nx_ex` as `r.setnx(...)` + `r.expire(...)` | Both FAILED, then passed again after revert (`git diff` confirmed clean) |
| `test_b2_guard_unique_index_without_time_is_rejected` | It asserts a TimescaleDB *server* behaviour that holds independently of migration 0008 | n/a — this is a negative control by construction; it would only pass vacuously if the table were not a hypertable, which `test_hypertable_config.py` independently pins | Correct as-is |

## Known Stubs

None. No hardcoded empty values, placeholder strings, or unwired components were introduced. Every symbol this plan creates is fully implemented and exercised by a test that runs against a live container or a real constructor.

The HASH helpers (`hset_slot`, `hgetall_slots`, `hdel_slot`, `hset_meta`, `expire_key`) have no production call site yet — plan 02-03's `RedisStateStore` is their consumer. They are not stubs: each is a complete one-line wrapper whose entire purpose is to own the `cast` so the caller needs none, and their existence and callability is asserted by `test_hash_helpers_are_exported_so_store_needs_no_casts`.

## Threat Flags

None beyond the one the plan already models. T-02-01 (the state machine lowering another service's scheduled poll time, a self-inflicted DoS and third-party ToS risk) is **mitigated and tested**, not merely dispositioned:

| Mitigation | Evidence |
|---|---|
| Cannot pull a poll earlier than `now_ms + CONFIRM_DELAY_MS` | `test_queued_job_is_pulled_forward_to_confirm_delay`, `test_expedite_never_pulls_a_poll_below_the_confirm_delay` |
| Cannot resurrect an in-flight job into a concurrent poll | `test_xx_guard_never_resurrects_an_inflight_job` |
| Flag self-expires within 120 s | `test_xx_guard_never_resurrects_an_inflight_job` asserts `1 <= TTL <= 120` |
| A burst cannot compound | `test_a_burst_of_expedites_yields_one_member_at_one_score` |

No new network endpoint, auth path or file access was introduced. Migration 0008 is a schema change at a trust boundary, but it only *narrows* what can be written (adds a NOT NULL column and a uniqueness constraint).

## Issues Encountered

- The full-suite-only smoke test failure (deviation 1) was the one real investigation. It presented as an unrelated pre-existing test breaking, which the scope-boundary rule would normally exclude — but it was directly caused by this plan's new file, so it was in scope and fixed rather than deferred.
- No auth gates, no architectural escalations, no fix-attempt limits reached.

## User Setup Required

None. No new dependency, env var, or external service. One infrastructure note: anyone who has already run `alembic upgrade head` needs to re-run it (or `make migrate`) to pick up migration 0008, and `make up` now pulls `bitnamilegacy/kafka:3.8` instead of the withdrawn `bitnami/kafka:3.8`.

## Next Phase Readiness

**Ready for plan 02-03 (consumer shell + persistence):**
- `make_consumer("availability.raw", "polls.completed", group_id="state-machine")` is ready to be called from inside `async def run()`.
- `avail_state_key` / `avail_meta_key` / the five HASH helpers are ready for `RedisStateStore` — it should contain zero `cast` calls and zero inline key strings.
- `event_idempotency_key` + the Phase 1 `set_nx_ex` give the D-46 Layer-1 claim in one call; `EVENT_IDEMPOTENCY_TTL_SECONDS` is 1200.
- `scheduler.expedite(job, now_ms)` is the call the shell makes on an `Expedite` decision from `DiffEngine`; the poller side of the handshake is already live.
- `AvailabilityEvent` ORM and migration 0008 agree on `(time, event_id)`; the close-UPDATE predicate must name both (`WHERE event_id = :event_id AND "time" = :confirmed_at`) or it degrades to a bitmap scan across every chunk.
- `tests/integration/conftest.py` gives the new integration files `apply_migrations`, `create_topics`, `redis_url` and `db_urls`.

**Carried forward, not blocking:**
- `services/poller/config.py` freezes env vars at import time (see deviation 1) — 02-03 must apply the same `sys.modules` teardown discipline in any integration test that imports service code.
- TTL on availability HASHes is key-level and must be refreshed on **every** write, because `HEXPIRE` does not exist on the pinned `redis:7.2-alpine`. 02-03's store is responsible for that refresh.
- The `restaurant_id`-means-platform-id decision (D-52) still needs the "How to join" note in `services/state_machine/README.md` that 02-CONTEXT calls for; the database-level comments are in place.

---
*Phase: 02-state-machine-event-pipeline*
*Completed: 2026-09-05*

## Self-Check: PASSED

All 9 claimed files verified present on disk; all 6 claimed commits verified in `git log`.
Final gate re-run at completion: `ruff check .` clean, `mypy shared/ services/` clean (30 files),
`pytest tests/unit -q` 111 passed, `pytest tests/integration -q -p no:cacheprovider` 30 passed,
all three CI ban-greps empty, `docker compose -f ops/docker-compose.yml config` prints
`bitnamilegacy/kafka:3.8`.
