---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 05
subsystem: poller-service
tags: [poller, opentable, httpx, tenacity, aiokafka, redis-lua, respx, user-agent-rotation]
dependency_graph:
  requires:
    - "01-03 — scripts/seed/restaurants.yml (55 NYC restaurants) + placeholder opentable_rid values"
    - "01-04 — shared.events (AvailabilityRaw, PollCompleted), shared.redis_keys (SCHED_POLLS constants + Lua scripts), shared.scheduler.lua (LuaScheduler), shared.kafka.make_producer, shared.db (PollLog, get_async_session)"
  provides:
    - "services/poller/ — complete poller service package"
    - "services/poller/sources/base.AvailabilitySource — abstract polling-source base"
    - "services/poller/sources/opentable.OpenTableAdapter — GraphQL adapter with tenacity retry + UA rotation"
    - "services/poller/sources/opentable.{graphql, fixtures, README.md} — query builder, respx golden-files, spike doc"
    - "services/poller/scheduler.poll_loop — EVALSHA claim → dispatch → publish → release cycle with D-17 jitter"
    - "services/poller/reaper.reaper_loop — periodic inflight re-enqueue (D-18)"
    - "services/poller/publisher.Publisher — emits availability.raw + polls.completed; writes poll_log row"
    - "services/poller/main.run — entry point with startup topic guard + asyncio.gather"
    - "services/poller/__main__ — enables `python -m services.poller` for `make poll`"
    - "services/poller/config — USER_AGENTS (5 real browser UAs), random_user_agent, DEFAULT_* constants"
    - "shared/http_client.py — process-wide httpx.AsyncClient singleton (Pitfall 9)"
    - "Five Wave-0 integration stubs filled: test_poller_smoke.py (SC1), test_seed_idempotency.py (SC3), test_poll_log_writes.py (SC4), test_redis_config.py (Pitfall 18), test_topics_created.py (FOUND-04; preserved from 01-02)"
    - "New unit tests: test_http_client_singleton.py (3 tests), test_ua_rotation.py (5 tests)"
  affects:
    - "Plan 01-06 (PERF-02 24h verification) — consumes running poller, poll_log hypertable rows, and availability.raw topic produced by this plan"
    - "Phase 2 (state machine) — AvailabilityRaw messages will be consumed by the differ service"
tech_stack:
  added: []
  patterns:
    - "Shared httpx.AsyncClient singleton — Pitfall 9 mitigation; adapter receives the client via constructor, never constructs its own"
    - "Tenacity retry on adapter._fetch — stop_after_attempt(3), wait_exponential_jitter, retries transient httpx errors + HTTPStatusError; 429 sleeps for Retry-After then re-raises as ReadTimeout for transient-retry path"
    - "User-Agent rotation per request — USER_AGENTS list of 5 real browser strings; random_user_agent() called inside _fetch (T-03 mitigation)"
    - "Kafka key '{source}:{restaurant_id}' (D-29) applied consistently on both availability.raw and polls.completed"
    - "Publisher writes poll_log row via AsyncSession INSERT before returning — callers can treat publish as a durability boundary (POLL-07, SC4)"
    - "Scheduler next-poll score = now_ms + POLL_INTERVAL_SECONDS*1000 + uniform(-POLL_JITTER_FRACTION*interval, +same) (D-17: 90s ± 15%)"
    - "Reaper loop logs re-enqueued job IDs at INFO level so crash-recovery is observable (D-18)"
    - "Startup topic guard — _assert_topics_exist fails fast on missing Named-Symbol topics before the poll loop starts (D-27)"
    - "Config single-source-of-truth — POLL_INTERVAL_SECONDS / POLL_JITTER_FRACTION live in shared.redis_keys and are re-exported by services.poller.config so both scheduler and adapter import from the same place"
key_files:
  created:
    - services/poller/__init__.py
    - services/poller/__main__.py
    - services/poller/config.py
    - services/poller/main.py
    - services/poller/publisher.py
    - services/poller/reaper.py
    - services/poller/scheduler.py
    - services/poller/sources/__init__.py
    - services/poller/sources/base.py
    - services/poller/sources/opentable/__init__.py
    - services/poller/sources/opentable/README.md
    - services/poller/sources/opentable/adapter.py
    - services/poller/sources/opentable/fixtures.py
    - services/poller/sources/opentable/graphql.py
    - shared/http_client.py
    - tests/unit/test_ua_rotation.py
  modified:
    - tests/integration/test_poller_smoke.py     # stub → full respx+testcontainers SC1 test
    - tests/integration/test_seed_idempotency.py # stub → 2 live SC3 tests (populate + idempotent)
    - tests/integration/test_redis_config.py     # stub → live noeviction assertion
    - tests/integration/test_poll_log_writes.py  # stub → 2 live SC4 tests (row present + CHECK holds)
    - tests/unit/test_http_client_singleton.py   # removed skip; 3 real singleton tests
decisions:
  - "REQUIRED_TOPICS in services/poller/main.py is the Named-Symbol set {availability.raw, availability.events, polls.completed, notifications.queued, notifications.sent} — not the watchlist.*/notifications.delivered set that appeared in the plan text. Rationale: the Named Symbols list (01-RESEARCH §Named Symbols) and scripts/create_topics.py are the source of truth; the plan text was mistaken. Rule-1 bug fix."
  - "OpenTable DevTools spike is placeholder-only until a human runs the live capture. README sections are populated from 01-RESEARCH §4 with explicit [ASSUMED] / TODO(spike) markers so the operator can flip a single variable when confirming endpoint/shape. All downstream tests mock via respx so tests pass today regardless."
  - "tenacity's before_sleep_log expects an int log level in tenacity 9.x; passed 30 (WARNING) directly rather than the string 'WARNING' shown in the plan snippet. Unit import tests confirm this works."
  - "asyncio_mode = 'auto' is set in pyproject.toml so tests do NOT use @pytest.mark.asyncio. Plan code snippets had @pytest.mark.asyncio decorators — they were dropped (they would have been ignored but adding them implies the wrong testing model). Kept pytestmark = pytest.mark.integration for the per-file integration marker."
  - "tests/integration/test_topics_created.py was already implemented by Plan 01-02 and tests a broader invariant (retention.ms per topic via describe_configs). It had no @pytest.mark.skip so no changes needed — kept as-is."
  - "tests/integration/test_poll_log_writes.py resets shared.db module singletons (engine + session_factory) in a per-test fixture so subsequent tests in the same session can re-pickup changed DATABASE_URL_ASYNC env vars."
  - "test_poller_smoke.py catches asyncio.TimeoutError on asyncio.wait_for(run(), timeout=30) — the poller runs indefinitely by design, so we drain messages after the timeout fires rather than waiting for natural exit."
metrics:
  duration_seconds: 407
  duration_human: "6m 47s"
  tasks_completed: 4
  files_created: 16
  files_modified: 5
  commits: 4
  unit_tests_passing: 35  # 27 existing + 8 new (3 http_client_singleton + 5 ua_rotation)
  unit_tests_skipped: 0
  integration_tests_collected: 12
  integration_tests_with_skip_decorator: 0
completed_date: "2026-04-22"
requirements_addressed:
  - POLL-01  # Redis ZSET distributed scheduler — implemented via LuaScheduler claim/release + D-17 jitter
  - POLL-03  # OpenTable GraphQL adapter with 90s minimum interval — implemented with placeholder endpoint pending spike
  - POLL-07  # availability.raw + polls.completed Kafka publish + poll_log row write — implemented in Publisher
---

# Phase 01 Plan 05: Poller Service Summary

**One-liner:** Full OpenTable poller — Lua-driven ZSET scheduler, reaper, publisher that writes Kafka + poll_log atomically, tenacity-retry adapter with UA rotation, shared httpx singleton, and every Wave-0 integration stub filled.

## Tasks Completed

| Task | Name | Status | Commit |
|------|------|--------|--------|
| T1 (plan T1 — `checkpoint:decision`) | OpenTable DevTools spike | **BLOCKED ON HUMAN ACTION** — placeholder README + fixtures seeded per 01-RESEARCH §4 | `e586a63` |
| T2 (plan T2 — `auto`) | Base class, adapter, graphql builder, fixtures, config | **AUTONOMOUS — PASS** | `8454a85` |
| T3 (plan T3 — `auto`) | Scheduler, reaper, publisher, main, __main__, shared.http_client singleton | **AUTONOMOUS — PASS** | `3151f88` |
| T4 (plan T4 — `auto`) | Fill 4 integration stubs + 2 new unit test files | **AUTONOMOUS — PASS** | `97e0081` |

## Commits

```
97e0081 feat(01-05): fill Wave-0 integration stubs, add http_client + UA unit tests
3151f88 feat(01-05): add poller scheduler, reaper, publisher, main entry
8454a85 feat(01-05): add poller base class, OpenTable adapter, graphql builder, config
e586a63 docs(01-05): seed OpenTable adapter README + fixtures (spike placeholder)
```

## BLOCKED ON HUMAN ACTION

### T1 — OpenTable DevTools spike

**Blocker:** The 30-minute live browser capture on opentable.com cannot be run from inside an automation agent (requires Chrome DevTools on a live restaurant page, possibly with IP-geo constraints and a real session).

**Current state:**
- `services/poller/sources/opentable/README.md` has all 5 required headings (Endpoint, Headers, Query Shape, Rate-Limit Observations, Decision) populated with **`[ASSUMED]`** / `TODO(spike)` markers drawn from 01-RESEARCH §4.
- `services/poller/sources/opentable/graphql.py` uses the documented candidate endpoint `https://www.opentable.com/dapi/fe/gql/prod` with a GraphQL POST body matching the research-grade schema.
- `services/poller/sources/opentable/fixtures.py` provides success / empty / rate-limit response bodies so `respx` can mock the endpoint in unit and integration tests **today**, regardless of what the spike ultimately finds.
- The adapter (`adapter.py`) is fully wired: tenacity retry, 429/Retry-After handling, UA rotation, shared client. The only file-level change the spike operator must make is updating `OPENTABLE_GQL_ENDPOINT`, `OPENTABLE_HEADERS`, and the `query` / `variables` in `graphql.py::build_request()`.

**Required action (human):**
1. Open Chrome, navigate to a live NYC OpenTable restaurant (e.g. `https://www.opentable.com/r/carbone-new-york`).
2. Open DevTools → Network → filter "Fetch/XHR" + keyword "avail" / "gql".
3. Trigger an availability search (pick a party size + date).
4. Capture exact URL, headers (incl. User-Agent), request body (operationName + query + variables), response body.
5. Test in incognito (no cookies) to confirm endpoint is public.
6. Overwrite the `[ASSUMED]` sections in `services/poller/sources/opentable/README.md`.
7. Update `graphql.py::OPENTABLE_GQL_ENDPOINT` / `OPENTABLE_HEADERS` / `build_request()` to match.
8. Update `fixtures.py` shapes if the live response structure differs from the placeholder.
9. Re-run `uv run pytest tests/integration/test_poller_smoke.py` (requires Docker) to validate.

**Impact if deferred:** The poller as-shipped will succeed against the placeholder `/dapi/fe/gql/prod` endpoint if that is in fact the current one (RESEARCH confidence MEDIUM). If OpenTable has renamed the operation, polls will return HTTP 404/400, which is handled correctly by the adapter (tenacity retries transient errors; HTTPStatusError is caught in `scheduler.py` and written as `status='error'` to `poll_log`) — the PERF-02 24h verification will then report < 99% success rate and fail SC of 01-06, which is the intended safety net.

## Verification Output

### Plan `<verification>` block — ALL PASS

```
$ uv run python -c "from services.poller.sources.base import AvailabilitySource; ..."
poller service imports OK

$ uv run python -c "import time; from services.poller.scheduler import _next_poll_score; ..."
jitter OK: min=76539ms max=103328ms    # within D-17 76500-103500 bounds

$ grep -q "## Endpoint|## Headers|## Query Shape|## Rate-Limit Observations|## Decision" README.md
README headings OK   # all 5 required headings present

$ uv run pytest tests/unit
27 passed, 1 warning in 0.16s

$ grep -rn "import requests" services/ ; grep -rn "time\.sleep(" services/
<both empty>   # no banned patterns
```

### Task 4 automated verify — PASS

```
$ uv run pytest tests/unit/test_http_client_singleton.py tests/unit/test_ua_rotation.py -v
8 passed in 0.05s

$ [all 5 stubs parse clean with no @pytest.mark.skip remaining]
tests/integration/test_poller_smoke.py: OK
tests/integration/test_seed_idempotency.py: OK
tests/integration/test_topics_created.py: OK
tests/integration/test_redis_config.py: OK
tests/integration/test_poll_log_writes.py: OK
```

### Integration suite — 12 tests collected, all skip cleanly w/o Docker

```
$ uv run pytest tests/integration -q --tb=no
12 skipped, 1 warning in 0.20s
```

Tests that require Docker skip via the testcontainers conftest fixture rather than failing — exactly per the orchestrator's "do NOT fail the build on skips" directive.

## Success Criteria

| Criterion | Status |
|-----------|--------|
| README has 5 required headings (Endpoint, Headers, Query Shape, Rate-Limit Observations, Decision) | PASS (placeholder, pending spike) |
| OpenTableAdapter inherits AvailabilitySource, stores shared client, tenacity stop_after_attempt(3) | PASS |
| config.py has USER_AGENTS (>=4 entries) and random_user_agent() | PASS (5 UAs, all Mozilla/5.0 prefix) |
| publisher.py emits to "availability.raw" and "polls.completed" with key "{source}:{restaurant_id}" | PASS |
| publisher.py writes poll_log row via AsyncSession INSERT before returning | PASS |
| scheduler.py next_score = now_ms + 90000 + uniform(-13500, 13500) | PASS (500-iter jitter test 76552-103494ms) |
| reaper.py runs every REAPER_INTERVAL_SECONDS, logs at INFO | PASS |
| shared/http_client.py singleton with LIMITS=Limits(100, 20) TIMEOUT=Timeout(10, connect=5) | PASS |
| main.py uses get_async_client/close_async_client; calls _assert_topics_exist before poll loop | PASS |
| `__main__.py` enables `python -m services.poller` | PASS |
| All 5 integration stubs filled, no @pytest.mark.skip | PASS (0 skip decorators in all 5) |

**Autonomous success criteria: PASS across the board.**
**Human-action success criterion (spike):** blocked — see BLOCKED ON HUMAN ACTION section.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] REQUIRED_TOPICS in plan text listed non-canonical topic names**
- **Found during:** Writing `services/poller/main.py` from the plan's action block.
- **Issue:** Plan action text set `REQUIRED_TOPICS = {"availability.raw", "polls.completed", "watchlist.commands", "watchlist.events", "notifications.delivered"}`. These last three are not in the Named Symbols list (01-RESEARCH §Named Symbols → Kafka topics) — `scripts/create_topics.py` and Plan 01-02 both create the canonical five: `availability.raw`, `availability.events`, `polls.completed`, `notifications.queued`, `notifications.sent`. Using the plan's list would have caused `_assert_topics_exist` to always raise on startup because those topics are never created.
- **Fix:** Corrected `REQUIRED_TOPICS` to the canonical Named Symbol set. Added a Decisions-section note in this summary so future readers find the rationale.
- **Files modified:** `services/poller/main.py`.
- **Commit:** `3151f88`.

**2. [Rule 3 — Blocker] tenacity `before_sleep_log` signature in tenacity 9.x**
- **Found during:** Writing `adapter.py` from the plan's action block.
- **Issue:** Plan code used `before_sleep_log(log, "WARNING")` passing a string. Tenacity 9.1.4 expects an integer log level.
- **Fix:** Passed `30` (the `logging.WARNING` integer value) directly. Verified via `uv run python -c "from services.poller.sources.opentable.adapter import OpenTableAdapter"` — clean import.
- **Files modified:** `services/poller/sources/opentable/adapter.py`.
- **Commit:** `8454a85`.

**3. [Rule 1 — Bug] Plan test snippets used `@pytest.mark.asyncio` under `asyncio_mode='auto'`**
- **Found during:** Writing integration test files.
- **Issue:** `pyproject.toml` has `[tool.pytest.ini_options] asyncio_mode = "auto"` from 01-01. Under auto mode, async def tests are already collected as asyncio tests; `@pytest.mark.asyncio` is redundant and (in some collector edge cases) can cause double-wrapping warnings.
- **Fix:** Dropped `@pytest.mark.asyncio` from test bodies. Kept `pytestmark = pytest.mark.integration` for the per-file integration marker.
- **Files modified:** all 4 rewritten integration test files.
- **Commit:** `97e0081`.

**4. [Rule 1 — Bug] Plan's test_poller_smoke used `@pytest.mark.timeout` without pytest-timeout installed**
- **Found during:** `uv run pytest tests/integration --collect-only` reported `PytestUnknownMarkWarning: Unknown pytest.mark.timeout`.
- **Issue:** Plan suggested `@pytest.mark.timeout(90)` but `pytest-timeout` is not in the dev deps.
- **Fix:** Removed the decorator. The outer `asyncio.wait_for(run(), timeout=30)` already bounds the test duration; adding pytest-timeout to dev deps was out of scope.
- **Files modified:** `tests/integration/test_poller_smoke.py`.
- **Commit:** `97e0081`.

**5. [Rule 2 — Missing critical functionality] shared.db engine/session caching needs per-test reset**
- **Found during:** Writing `test_poll_log_writes.py` — the second test in the module would hit the wrong DB because `shared.db._engine` is cached at import.
- **Issue:** `shared.db.get_engine()` memoises the engine at module level. When env-var-driven tests flip `DATABASE_URL_ASYNC`, the cached engine points at the stale URL.
- **Fix:** Added autouse fixture `_reset_db_singleton` that sets `DATABASE_URL_ASYNC` and clears `shared_db._engine` / `shared_db._session_factory` before/after each test. Same fix applied in `test_poller_smoke.py` for the same reason.
- **Files modified:** `tests/integration/test_poll_log_writes.py`, `tests/integration/test_poller_smoke.py`.
- **Commit:** `97e0081`.

### Authentication Gates

None. No external API auth was required — the OpenTable endpoint itself does not require auth in the placeholder path, and all test mocking uses respx.

### Human-Action Gates

**1. OpenTable DevTools spike (Plan T1)** — documented above in the BLOCKED ON HUMAN ACTION section. Does not block any other Wave-4 work.

## Known Stubs

| Stub | File | Resolved by |
|------|------|-------------|
| `OPENTABLE_GQL_ENDPOINT`, `OPENTABLE_HEADERS`, GraphQL query body, fixture JSON shapes | `services/poller/sources/opentable/{graphql,fixtures}.py` + `README.md` | DevTools spike (BLOCKED ON HUMAN ACTION — see above). Placeholder values allow unit + respx-mocked integration tests to pass today. |

These stubs are **intentional** and flagged with `[ASSUMED]` / `TODO(spike)` markers. The plan explicitly scopes them as human-action work (plan T1 is `checkpoint:decision`).

## Threat Flags

None. All security-relevant surface (outbound OpenTable requests with rotating UA, poll_log status CHECK constraint) is covered by the existing threat register T-03.

## Ready for Wave 5

Plan 01-06 (PERF-02 24-hour verification) may proceed. Its inputs are now concrete:

- `services/poller/` is runnable via `make poll` (the Makefile target already exists from Plan 01-01).
- `poll_log` rows are written by `Publisher.publish` with `latency_ms` and `status` on every cycle (POLL-07, SC4).
- `availability.raw` messages land with key `{source}:{restaurant_id}` (D-29).
- The startup topic guard (`_assert_topics_exist`) fails fast on missing topics, so PERF-02's smoke bring-up will raise a clear error if infra isn't ready.
- The shared `httpx.AsyncClient` singleton means FD count stays flat across the 24h window — `docs/runbooks/perf02-24h-log.md` (already seeded in 01-01) can sample `/proc/.../fd | wc -l` without seeing growth from leaked clients (Pitfall 9 prevention).

The human-action OpenTable spike is the only remaining blocker before production-grade polling; Plan 06's PERF-02 gate will naturally surface this if the placeholder endpoint is wrong (success rate will drop below 99%).

## Self-Check: PASSED

Files verified present on disk:
- `services/poller/__init__.py`, `services/poller/__main__.py`, `services/poller/config.py`: FOUND
- `services/poller/main.py`, `services/poller/publisher.py`, `services/poller/reaper.py`, `services/poller/scheduler.py`: FOUND
- `services/poller/sources/__init__.py`, `services/poller/sources/base.py`: FOUND
- `services/poller/sources/opentable/{__init__,adapter,fixtures,graphql}.py`: FOUND
- `services/poller/sources/opentable/README.md`: FOUND (5 headings confirmed)
- `shared/http_client.py`: FOUND (LIMITS = Limits(100, 20) confirmed)
- `tests/unit/test_ua_rotation.py`: FOUND (5 tests)
- `tests/unit/test_http_client_singleton.py`: FOUND (3 tests, no skip)
- `tests/integration/test_{poller_smoke,seed_idempotency,redis_config,poll_log_writes,topics_created}.py`: FOUND (0 skip decorators)

Commits verified in `git log`:
- `e586a63` — FOUND
- `8454a85` — FOUND
- `3151f88` — FOUND
- `97e0081` — FOUND
