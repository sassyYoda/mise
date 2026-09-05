---
phase: 02
slug: state-machine-event-pipeline
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: validated
nyquist_compliant: true
wave_0_complete: true
created: 2026-09-05
updated: 2026-09-05
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"`), testcontainers 4.14.2, run through `uv` — never bare `python` / `pytest` |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `pythonpath = ["."]`, `integration` marker registered |
| **Quick run command** | `uv run pytest tests/unit -q` (`make test`) |
| **Full suite command** | `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` (`make test-integration`) |
| **Lint gate (every task)** | `uv run ruff check . && uv run mypy shared/ services/` (`make lint`) |
| **Container fixtures** | `tests/conftest.py` — module-scoped `kafka_container` (`confluentinc/cp-kafka:7.6.0`), `redis_container` (`redis:7.2-alpine`), `timescale_container` (`timescale/timescaledb:2.17.2-pg16`), each guarded by `_docker_available()` |
| **Estimated runtime** | unit tier < 5 s; integration tier ~1 min (container startup dominates) |
| **Baseline at plan time** | 27 unit tests passing, 12 integration tests passing — both must stay green; never skip or disable a test to go green |

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/unit -q` plus `uv run ruff check . && uv run mypy shared/ services/`
- **After every plan wave:** `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` plus the three CI ban-greps (`^import requests`, `time.sleep(`, bare `import redis`) over `services/` and `shared/`
- **Before `/gsd-verify-work`:** full suite green and all four ROADMAP Phase 2 success criteria demonstrated
- **Max feedback latency:** < 5 s (unit tier), < 90 s (integration tier)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | STATE-02, STATE-04 | — | N/A | unit | `uv run pytest tests/unit/test_tracer_raw_to_event.py -x -q` | ✅ exists | ✅ green |
| 02-01-02 | 01 | 1 | STATE-02 | — | N/A | unit | `uv run pytest tests/unit/test_engine_transitions.py tests/unit/test_coverage_bounding.py tests/unit/test_engine_tristate_unknown.py -x -q` | ✅ exists | ✅ green |
| 02-01-03 | 01 | 1 | STATE-04, STATE-06 | T-02-02 | Malformed third-party JSON collapses to `ParseError`, never an unhandled exception that stalls the partition | unit | `uv run pytest tests/unit -q` | ✅ exists | ✅ green |
| 02-02-01 | 02 | 1 | STATE-03 | T-02-01 | Expedite can only pull a queued poll forward to `now+8000`; `XX` cannot resurrect an in-flight job; flag self-expires in 120 s | integration | `uv run pytest tests/integration/test_expedite_lua.py tests/integration/test_poller_expedite_release.py -q -p no:cacheprovider` | ✅ exists | ✅ green |
| 02-02-02 | 02 | 1 | STATE-01, STATE-04 | — | Zero two-command idempotency claims in the source tree (ROADMAP SC3 mechanical half) | unit | `uv run pytest tests/unit -q` | ✅ exists | ✅ green |
| 02-02-03 | 02 | 1 | STATE-05 | — | N/A | integration | `uv run pytest tests/integration/test_migration_0008.py -q -p no:cacheprovider` | ✅ exists | ✅ green |
| 02-03-01 | 03 | 2 | STATE-01, STATE-02, STATE-03, STATE-04, STATE-05 | T-02-02, T-02-03 | Poison message logs and commits without stalling; no `booking_token` or `raw_response` at INFO | integration | `uv run pytest tests/integration/test_state_machine_e2e.py -q -p no:cacheprovider` | ✅ exists | ✅ green |
| 02-03-02 | 03 | 2 | STATE-04, STATE-05 | T-02-04 | `MISE_CRASH_AFTER` refused when `ENV=prod`; SIGKILL asserted via `returncode == -9` so the test cannot pass vacuously | integration | `uv run pytest tests/integration/test_state_machine_chaos.py tests/integration/test_availability_events_persistence.py -q -p no:cacheprovider` | ✅ exists | ✅ green |
| 02-03-03 | 03 | 2 | STATE-01, STATE-03, STATE-04 | — | No inline async sleep anywhere in the service (STATE-03 gate) | unit + integration | `uv run pytest tests/unit -q && uv run pytest tests/integration/test_redis_state_store.py -q -p no:cacheprovider` | ✅ exists | ✅ green |
| 02-04-01 | 04 | 2 | STATE-06 | T-02-05 | `--output` refused outside the repository root unless absolute | unit | `uv run pytest tests/unit/test_replay_determinism.py -q` | ✅ exists | ✅ green |
| 02-04-02 | 04 | 2 | STATE-06 | — | N/A | unit | `uv run pytest tests/unit/test_replay_zero_false_events.py -q` | ✅ exists | ✅ green |
| 02-04-03 | 04 | 2 | STATE-06 | T-02-06 | `group_id=None` + `assign`/`seek`; replay provably cannot move the `state-machine` group's offsets | integration | `uv run pytest tests/integration/test_replay_offset_range.py -q -p no:cacheprovider` | ✅ exists | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity check:** 12 of 12 tasks carry an `<automated>` verify command. There is no
run of 3 consecutive tasks without automated feedback — the Nyquist condition holds.

---

## Requirement → Proof Map

| Req | Proving test(s) | Plan / task |
|-----|-----------------|-------------|
| STATE-01 | `tests/unit/test_redis_keys_phase2.py`, `tests/integration/test_redis_state_store.py`, `tests/unit/test_redis_state_store_atomicity.py` (review-fix WR-10) | 02-02-02, 02-03-03 |
| STATE-02 | `tests/unit/test_engine_transitions.py`, `test_coverage_bounding.py`, `test_engine_tristate_unknown.py`, `test_parsers_opentable.py`, `tests/unit/test_slot_key_collisions.py` (review-fix IN-07) | 02-01-02, 02-01-03 |
| STATE-03 | `tests/integration/test_expedite_lua.py`, `test_poller_expedite_release.py`, `tests/unit/test_no_inline_sleep.py`, `tests/unit/test_confirm_delay_is_not_configurable.py` (review-fix WR-06/WR-07) | 02-02-01, 02-03-03 |
| STATE-04 | `tests/unit/test_event_id_determinism.py`, `test_emission_idempotency.py`, `test_no_setnx_expire_pairs.py`, `tests/integration/test_state_machine_chaos.py`, `tests/unit/test_two_seat_types_one_token.py` (review-fix CR-01), `tests/unit/test_emit_flush_ordering.py` (review-fix CR-02/WR-03), `tests/unit/test_offset_commit_policy.py` (review-fix WR-01/WR-02) | 02-01-03, 02-02-02, 02-03-02, 02-03-03 |
| STATE-05 | `tests/integration/test_migration_0008.py`, `test_availability_events_persistence.py`, `tests/unit/test_service_time_math.py` (review-fix CR-03, IN-03 assertions folded into these files) | 02-02-03, 02-03-02 |
| STATE-06 | `tests/unit/test_replay_determinism.py`, `test_replay_zero_false_events.py`, `test_engine_purity.py`, `tests/integration/test_replay_offset_range.py` (review-fix WR-11/WR-12) | 02-01-03, 02-04-01, 02-04-02, 02-04-03 |

| ROADMAP success criterion | Proving test |
|---------------------------|--------------|
| SC1 — transient-error stream yields 0 false events | `tests/unit/test_replay_zero_false_events.py` (02-04-02) |
| SC2 — byte-identical replay from an offset range | `tests/unit/test_replay_determinism.py` + `tests/integration/test_replay_offset_range.py` (02-04-01, 02-04-03) |
| SC3 — kill -9 yields 0 duplicates; 0 two-command claims in tree | `tests/integration/test_state_machine_chaos.py` + `tests/unit/test_no_setnx_expire_pairs.py` (02-03-02, 02-02-02) |
| SC4 — events persist with all five analytics columns | `tests/integration/test_availability_events_persistence.py` + `test_state_machine_e2e.py` (02-03-02, 02-03-01) |

---

## Wave 0 Requirements

No separate Wave 0 plan is needed — pytest, pytest-asyncio and testcontainers are already installed
and green, and every task in this phase is `tdd="true"`, writing its own failing test before its
implementation. The two shared scaffolds below are created inside the FIRST task of their plan and
are prerequisites for everything after them:

- [x] `tests/unit/factories.py` — `make_raw` / `make_slot` / `make_parsed` builders that REQUIRE an
      explicit `polled_at_epoch_ms`, so no test reads the wall clock or waits 9 real seconds.
      Created by **02-01 Task 1**; consumed by every unit test in plans 01 and 04.
- [x] `tests/integration/conftest.py` — `reset_shared_db_singletons`, `apply_migrations`,
      `create_topics`, `redis_url`, `db_urls`, extracted from the inline duplication in
      `tests/integration/test_poller_smoke.py` and `test_hypertable_config.py`. Created by
      **02-02 Task 1**; consumed by all 7 new integration tests in plans 02, 03 and 04.
- [x] `tests/fixtures/raw_streams/` — the directory does not exist today; created by **02-04 Task 1**.
- [ ] Framework install: none needed. Phase 2 introduces **zero** new packages (02-RESEARCH.md
      §Package Legitimacy Audit) — `uv sync --frozen` already provides everything.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `make up` boots the stack with the repointed Kafka image | D-56 | Needs a machine that has not cached the withdrawn `bitnami/kafka:3.8` tag; CI uses testcontainers with `cp-kafka` and never exercises the compose file | On a clean Docker cache run `make up`, wait for the healthcheck, then `make topics` and confirm exit 0 |
| OpenTable payload shape matches the live endpoint | STATE-02 (parser tier) | Blocked on the Phase 1 DevTools spike, which is still open per `.planning/STATE.md`; every payload shape is `[ASSUMED]` and confined to `parsers/opentable.py` by design | After the spike, diff the captured response against `services/poller/sources/opentable/fixtures.py` and update that one module plus its unit test |

Everything else in this phase has automated verification.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — 12/12
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (`factories.py`, integration `conftest.py`, fixture dir)
- [x] No watch-mode flags — every command is a single-shot run
- [x] Feedback latency < 5 s on the unit tier
- [x] `nyquist_compliant: true` set in frontmatter
- [x] All Per-Task Verification Map rows confirmed against disk: referenced test files exist, `uv run pytest tests/unit -q` independently re-run and shows 228 passed (2026-09-05)
- [x] Integration rows (52→62 passing) accepted as green on the evidence in 02-VERIFICATION.md; integration suite not re-run here per instruction (another agent running it concurrently)
- [x] STATE-01..06 each have at least one automated proof, including 8 review-fix regression tests added by 02-REVIEW-FIX.md (CR-01, CR-02, CR-03, WR-01/02/03/06/07/10/11/12, IN-03, IN-07)
- [x] No gaps found requiring new test generation — audit filled 0 gaps

**Approval:** approved 2026-09-05
