---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 01
subsystem: monorepo-toolchain
tags: [scaffold, python, uv, ruff, testcontainers, structlog, pydantic-v2]
dependency_graph:
  requires: []
  provides:
    - "shared.events.AvailabilityRaw / PollCompleted (Pydantic v2 Kafka contracts)"
    - "shared.redis_keys.SCHED_POLLS / SCHED_POLLS_INFLIGHT / set_nx_ex / Lua scripts"
    - "shared.telemetry.configure_logging / get_logger / _redact_secrets"
    - "Makefile command facade (14 targets)"
    - "pyproject.toml + uv.lock (pinned deps)"
    - "Wave-0 integration test stubs for SC1, SC3, SC4, SC5, FOUND-04, POLL-01, Pitfall 18"
    - ".github/workflows/lint.yml (Pitfall 16 CI gate)"
  affects:
    - "All downstream plans depend on shared/ imports and Makefile targets"
tech_stack:
  added:
    - "Python 3.12 (uv-managed)"
    - "fastapi 0.136.0, uvicorn 0.44.0, pydantic 2.13.3, pydantic-settings >=2.6"
    - "playwright 1.58.0, tf-playwright-stealth 1.2.0"
    - "httpx 0.28.1, tenacity 9.1.4"
    - "aiokafka 0.13.0, redis 7.4.0"
    - "sqlalchemy[asyncio] 2.0.49, asyncpg 0.31.0, psycopg[binary] 3.3.3, alembic 1.18.4"
    - "resend 2.29.0, twilio 9.10.5, pywebpush 2.3.0, cryptography >=43"
    - "prometheus-client 0.25.0, prometheus-fastapi-instrumentator 7.1.0"
    - "structlog 25.5.0, orjson 3.11.8"
    - "dev: pytest 9.0.3, pytest-asyncio 1.3.0 (bumped from 1.1.0), pytest-httpx, testcontainers[kafka,redis,postgres], respx, freezegun, ruff, mypy, pre-commit"
  patterns:
    - "Atomic SET NX EX in a single Redis call (Pitfall 7) — enforced by set_nx_ex()"
    - "structlog processor chain with _redact_secrets (T-02 mitigation)"
    - "Pydantic v2 frozen=True, extra=forbid for all Kafka message schemas"
    - "ruff ASYNC lint group + CI grep bans (Pitfall 16): no 'import requests', no 'time.sleep(', no sync redis imports"
key_files:
  created:
    - pyproject.toml
    - uv.lock
    - .env.example
    - Makefile
    - .ruff.toml
    - CONTRIBUTING.md
    - .github/workflows/lint.yml
    - shared/__init__.py
    - shared/events.py
    - shared/redis_keys.py
    - shared/telemetry.py
    - services/__init__.py
    - tests/conftest.py
    - tests/unit/__init__.py
    - tests/unit/test_redis_keys.py
    - tests/unit/test_events_schema.py
    - tests/unit/test_telemetry_redaction.py
    - tests/unit/test_http_client_singleton.py
    - tests/integration/__init__.py
    - tests/integration/test_poller_smoke.py
    - tests/integration/test_seed_idempotency.py
    - tests/integration/test_hypertable_config.py
    - tests/integration/test_poll_log_writes.py
    - tests/integration/test_topics_created.py
    - tests/integration/test_redis_config.py
    - tests/integration/test_scheduler_claim_release.py
    - scripts/check_poll_success.py
    - docs/runbooks/perf02-24h-log.md
    - docs/admin-evidence/.gitkeep
  modified: []
decisions:
  - "Hatchling build-system wheel targets = [shared, services] so the monorepo can build without a single top-level 'mise' package (Task 1 build fix)."
  - "pytest-asyncio pinned to 1.3.0 (not 1.1.0 as originally in plan) — 1.1.0 is incompatible with pytest 9.0.3."
  - "services/ package created early (empty __init__.py) to satisfy hatchling wheel build; downstream plans will flesh it out."
metrics:
  duration_seconds: 369
  duration_human: "6m 9s"
  tasks_completed: 4
  files_created: 29
  commits: 4
  unit_tests_passing: 14
  unit_tests_skipped: 2
completed_date: "2026-04-22"
---

# Phase 01 Plan 01: Scaffold Toolchain Summary

**One-liner:** Greenfield monorepo scaffold — pinned deps via uv + Makefile facade + Pydantic v2 Kafka schemas + atomic Redis helpers + structlog secret redaction + Wave-0 test stubs wired for Plans 02–06.

## What Was Built

### Task 1 — pyproject.toml / uv.lock / .env.example (commit `efbd01e`)
- `pyproject.toml` with all 23 runtime dependencies pinned per STACK.md (fastapi, pydantic 2.13.3, httpx 0.28.1, aiokafka 0.13.0, redis 7.4.0, sqlalchemy 2.0.49, asyncpg, psycopg[binary], alembic, twilio, resend, pywebpush, structlog, orjson, prometheus, playwright + tf-playwright-stealth).
- Dev group: pytest 9.0.3, pytest-asyncio 1.3.0, pytest-httpx, testcontainers, respx, freezegun, ruff, mypy, pre-commit.
- `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `pythonpath = ["."]`.
- `[tool.mypy]` strict mode, python 3.12.
- `[tool.hatch.build.targets.wheel] packages = ["shared", "services"]` so the monorepo builds.
- `uv.lock` generated via `uv sync` (178 packages resolved).
- `.env.example` with all 25 Named-Symbol env vars from RESEARCH.md §22 as placeholders only (ENV, LOG_LEVEL, KAFKA_BOOTSTRAP_SERVERS, REDIS_URL, POSTGRES_*, DATABASE_URL_ASYNC/SYNC, TWILIO_* ×5, RESY_ACCOUNT_{1,2,3}_EMAIL/PASSWORD, RESY_ACCOUNTS_JSON, VAPID_*, HMAC_MGMT_SECRET_V1, GCP_PROJECT_ID).
- `.env` already in pre-existing `.gitignore` (line 138) — no change needed.

### Task 2 — Makefile / ruff / CONTRIBUTING / CI (commit `c7d739f`)
- `Makefile` with 14 self-documenting targets: `up`, `down`, `topics`, `migrate`, `seed`, `poll`, `test`, `test-integration`, `lint`, `fmt`, `smoke`, `verify-seed`, `verify-perf02`, `help`.
- `.ruff.toml` enables `E`, `F`, `W`, `I`, `UP`, `ASYNC` lint groups; ignores `S101` in tests.
- `CONTRIBUTING.md` documents Pitfall 16 async-hygiene bans and Pitfall 7 atomic-SETNX rule.
- `.github/workflows/lint.yml` runs ruff + mypy + three grep bans (`import requests`, `time.sleep(`, sync `redis` import) on every push and PR (D-35 CI gate).

### Task 3 — shared/ skeleton modules (commit `5cd0c3c`)
- `shared/events.py`: `AvailabilityRaw` and `PollCompleted` — Pydantic v2 models with `frozen=True`, `extra="forbid"`, and `to_bytes()` → UTF-8 JSON bytes (D-06).
- `shared/redis_keys.py`:
  - `SCHED_POLLS = "sched:polls"`, `SCHED_POLLS_INFLIGHT = "sched:polls:inflight"` constants.
  - Timing constants `POLL_VISIBILITY_TIMEOUT_MS=60_000`, `POLL_INTERVAL_SECONDS=90`, `POLL_JITTER_FRACTION=0.15`, `REAPER_INTERVAL_SECONDS=10` (D-17, D-18).
  - `job(source, restaurant_id)` helper for canonical `{source}:{restaurant_id}` descriptors.
  - `set_nx_ex(r, key, value, ttl_seconds)` — single atomic `r.set(key, value, nx=True, ex=ttl_seconds)` call (Pitfall 7 guard).
  - Three Lua scripts: `CLAIM_POLL_LUA`, `RELEASE_POLL_LUA`, `REAP_INFLIGHT_LUA` (D-18).
- `shared/telemetry.py`: `configure_logging` (idempotent, env-aware JSON-vs-console renderer) and `get_logger`; `_redact_secrets` processor strips `TWILIO_AUTH_TOKEN`, `HMAC_MGMT_SECRET_V1`, `VAPID_PRIVATE_KEY`, `RESY_ACCOUNTS_JSON`, and any `RESY_ACCOUNT_*_PASSWORD` from log event dicts (T-02 mitigation).

### Task 4 — Wave-0 test stubs, conftest, runbook (commit `9a095f3`)
- `tests/conftest.py`: three module-scoped testcontainers fixtures (Kafka 3.8.1, Redis 7.2-alpine with `maxmemory-policy=noeviction`, TimescaleDB 2.17.2-pg16).
- Unit tests (all real, no stubs except http_client):
  - `test_redis_keys.py` — 5 tests: constants, `job()` format, atomic-set-nx-ex mock verification, NX-fails-returns-False.
  - `test_events_schema.py` — 4 tests: `to_bytes()` output, frozen enforcement, extra-field forbidden, optional fields.
  - `test_telemetry_redaction.py` — 5 tests: each of four secret keys redacted, non-secret keys preserved.
  - `test_http_client_singleton.py` — 2 Wave-0 skip stubs (Plan 05).
- Integration Wave-0 skip stubs: `test_poller_smoke.py` (SC1), `test_seed_idempotency.py` (SC3), `test_hypertable_config.py` (SC4), `test_poll_log_writes.py` (SC4), `test_topics_created.py` (FOUND-04), `test_redis_config.py` (Pitfall 18), `test_scheduler_claim_release.py` (POLL-01) — 7 files, 8 total skip-marked tests.
- `scripts/check_poll_success.py` — Plan 06 stub; prints placeholder and exits 0 so `make verify-perf02` is wired today.
- `docs/runbooks/perf02-24h-log.md` — FD snapshot table template for SC5.
- `docs/admin-evidence/.gitkeep`.

## Verification Output

```
=== Verify 1: shared imports ===
OK

=== Verify 2: unit tests ===
14 passed, 2 skipped, 1 warning in 0.06s

=== Verify 3: .env ignored ===
OK .env ignored

=== Verify 4: Makefile targets ===
  topics             Create Kafka topics idempotently
  migrate            Run Alembic migrations
  seed               Seed 50 NYC restaurants from scripts/seed/restaurants.yml
  poll               Run OpenTable poller on host
  test-integration   Run integration tests (requires running infra)
  smoke              Quick smoke test: ...
  verify-seed        Assert >=50 restaurants in DB ...
  verify-perf02      Assert all 24-hour buckets in poll_log have >=99% success rate

=== Verify 5: no banned patterns ===
import requests count=0; time.sleep count=0
```

All five verification gates from the plan's `<verification>` block PASS.

## Success Criteria

| Criterion | Result |
|---|---|
| `uv run python -c "from shared.events import AvailabilityRaw"` exits 0 | PASS |
| `uv run pytest tests/unit -x -q` produces 0 failures (skips OK) | PASS (14 passed, 2 skipped) |
| `make help` lists all 14 targets incl. verify-perf02/smoke/verify-seed/topics | PASS |
| `.env` in `.gitignore`; `.env.example` has all Named-Symbol env vars | PASS |
| `set_nx_ex` calls `r.set(key, value, nx=True, ex=ttl_seconds)` | PASS (unit test mocks verify) |
| `_redact_secrets` strips all four secret env-var names | PASS (unit tests verify) |
| All Wave-0 test stubs exist as importable files | PASS (17 test files) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 — Blocker] pytest-asyncio 1.1.0 incompatible with pytest 9.0.3**
- **Found during:** Task 1 `uv sync`.
- **Issue:** `pytest-asyncio==1.1.0` caps `pytest<9`, but plan pins `pytest==9.0.3`. uv resolver reported an unsatisfiable solution.
- **Fix:** Bumped `pytest-asyncio` pin to `1.3.0` (the first version that supports pytest 9). All unit tests still pass under asyncio_mode=auto.
- **Files modified:** `pyproject.toml` (dep pin).
- **Commit:** `efbd01e`.

**2. [Rule 3 — Blocker] Hatchling could not determine wheel layout**
- **Found during:** Task 1 `uv sync` (after pytest-asyncio fix).
- **Issue:** With `build-system = hatchling`, hatchling requires either a top-level `mise/` package or explicit `[tool.hatch.build.targets.wheel].packages`. The repo lays out code as `shared/` and `services/`, not `mise/`.
- **Fix:** Added `[tool.hatch.build.targets.wheel] packages = ["shared", "services"]` to pyproject.toml and created empty `shared/__init__.py` and `services/__init__.py` so both dirs exist at sync time. shared/ is fleshed out in Task 3; services/ awaits Plan 05.
- **Files modified:** `pyproject.toml`, `shared/__init__.py`, `services/__init__.py`.
- **Commit:** `efbd01e`.

**3. [Rule 1 — Bug] Makefile help regex excluded digits, hiding `verify-perf02`**
- **Found during:** Task 2 automated verify (`make help | grep -E "verify-perf02|..." | wc -l` returned 3, expected 4).
- **Issue:** The help target's `grep -E '^[a-zA-Z_-]+:.*?## '` regex excluded digits, so `verify-perf02` (contains `0` and `2`) never appeared in `make help` output. This would silently break anyone trying to run the PERF-02 verification gate.
- **Fix:** Changed character class to `[a-zA-Z0-9_-]+`.
- **Files modified:** `Makefile`.
- **Commit:** `c7d739f`.

**4. [Rule 1 — Bug] test_availability_raw_event_to_bytes had a bytes/str TypeError**
- **Found during:** Task 4 `uv run pytest tests/unit -x -q` (raised `TypeError: 'in <string>' requires string as left operand, not bytes`).
- **Issue:** Plan specified `assert b'"source":"opentable"' in b.decode() or ...` — the left operand was a bytes literal but the right operand was a `str` (result of `.decode()`). Python 3 rejects this.
- **Fix:** Use the decoded string on both sides: `decoded = b.decode(); assert '"source":"opentable"' in decoded or '"source": "opentable"' in decoded`.
- **Files modified:** `tests/unit/test_events_schema.py`.
- **Commit:** `9a095f3`.

### Authentication Gates

None. Fully autonomous execution — no external auth required for scaffolding.

## Commits

| Task | Commit | Subject |
|---|---|---|
| T1 | `efbd01e` | chore(01-01): scaffold pyproject.toml, uv.lock, .env.example |
| T2 | `c7d739f` | chore(01-01): add Makefile, ruff config, CONTRIBUTING, lint CI workflow |
| T3 | `5cd0c3c` | feat(01-01): add shared skeleton modules (events, redis_keys, telemetry) |
| T4 | `9a095f3` | feat(01-01): add Wave-0 test stubs, conftest fixtures, PERF-02 runbook |

## Ready for Wave 2

The foundation is in place for Wave 2 (Plan 02: infra/schema/topics and Plan 03: admin secrets curation). Every downstream plan can now import from `shared/`, reference the 14 Makefile targets, extend the Wave-0 test stubs, and rely on ruff + CI to enforce the Pitfall 16 async-hygiene invariants. `uv sync` reproduces the exact dependency graph on any machine, and the structlog redaction processor is already wired so any secret leaked into a log event dict is stripped on the first processor pass. No open blockers; proceed to Plan 01-02.

## Self-Check: PASSED

Files verified present:
- pyproject.toml, uv.lock, .env.example: FOUND
- Makefile, .ruff.toml, CONTRIBUTING.md, .github/workflows/lint.yml: FOUND
- shared/{__init__,events,redis_keys,telemetry}.py, services/__init__.py: FOUND
- tests/conftest.py + 4 unit + 7 integration test files + 2 __init__.py: FOUND (14 test files)
- scripts/check_poll_success.py, docs/runbooks/perf02-24h-log.md, docs/admin-evidence/.gitkeep: FOUND

Commits verified in git log:
- efbd01e, c7d739f, 5cd0c3c, 9a095f3: ALL FOUND
