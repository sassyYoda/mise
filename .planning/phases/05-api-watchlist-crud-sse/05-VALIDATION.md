---
phase: 05
slug: api-watchlist-crud-sse
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-05
---

# Phase 05 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"`), testcontainers, freezegun — all pinned and installed; this phase adds no dependency |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `pythonpath = ["."]`, marker `integration`) |
| **Quick run command** | `make test` → `uv run pytest tests/unit -x -q -W error::RuntimeWarning` |
| **Full suite command** | `make test-integration` → `uv run pytest tests/unit tests/integration -v` (add `-p no:cacheprovider` when running the integration tier directly) |
| **Lint gate** | `make lint` → `uv run ruff check . && uv run mypy shared/ services/ scripts/` |
| **Estimated runtime** | unit tier seconds; integration tier minutes (testcontainers bring up Kafka, Redis and TimescaleDB) |

**Two test tiers, and which one a module may use (BC-1 / D-104a).** `httpx.ASGITransport` buffers the
whole response and never runs lifespan, so it may be used ONLY for plain request/response routes with
dependencies overridden. Anything that streams or reads lifespan state runs against the in-process
`uvicorn.Server` fixture (`tests/integration/conftest.py :: live_api`, added in 05-01). Every test
module states its tier and the reason in its docstring.

---

## Sampling Rate

- **After every task commit:** `make test` — the whole unit tier, which covers every validator, the
  token rotation, the SSE framing and hub semantics, the client-IP resolution and every grep gate.
- **After every plan wave:** `make test-integration` plus `make lint`.
- **Before `/gsd-verify-work`:** full suite green, `make api-smoke` executed (and its CI form,
  `tests/integration/test_api_smoke_script.py`, green), `docs/api.md` walkthrough verified.
- **Max feedback latency:** the unit tier, run after every task commit.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 05-01-01 | 01 | 1 | API-01 | — | Wave-0 gate halts on any missing Phase 3/4 artifact, naming the owning decision id | unit | `uv run pytest tests/unit/test_phase5_preconditions.py tests/unit/test_service_time_math.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 05-01-02 | 01 | 1 | API-01 | T-05-01 / T-05-02 / T-05-03 / T-05-04 | No traceback or exception message reaches the log sink; token-bearing paths logged redacted; client IP from the second-to-last hop | unit | `uv run pytest tests/unit/test_request_log.py tests/unit/test_client_ip.py tests/unit/test_api_logs_never_carry_payload.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 05-01-03 | 01 | 1 | API-03 | T-05-05 / T-05-06 / T-05-08 | Public metrics carry no user-identifying label; readiness cannot hang; one registry serves the endpoint | unit + integration | `uv run pytest tests/unit/test_metrics_registry.py tests/unit/test_api_async_only.py -q && uv run pytest tests/integration/test_api_plumbing.py tests/integration/test_metrics.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-02-01 | 02 | 2 | WATCH-01 | T-05-10 / T-05-13 / T-05-14 | Token minted server-side and never stored; named conflict targets; zero-watch sibling still recounted | integration | `uv run pytest tests/integration/test_watch_crud.py tests/integration/test_restaurant_merge.py tests/integration/test_watch_counts.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-02-02 | 02 | 2 | WATCH-02 | T-05-16 | Every input bounded; `extra="forbid"`; "today" is a New York date | unit | `uv run pytest tests/unit/test_watch_models.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 05-02-03 | 02 | 2 | WATCH-02 | T-05-12 | Repeat and concurrent creates collapse to one row via a partial unique index | integration | `uv run pytest tests/integration/test_watch_dedupe.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-03-01 | 03 | 3 | WATCH-06 | T-05-17 / T-05-18 / T-05-25 | 60/min per real client; spoofed leading hop cannot escape the bucket; increment and expire are one script | unit + integration | `uv run pytest tests/unit/test_redis_keys_phase5.py tests/unit/test_rate_limit_window.py tests/unit/test_no_setnx_expire_pairs.py -q && uv run pytest tests/integration/test_rate_limit.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-03-02 | 03 | 3 | WATCH-05 | T-05-19 / T-05-20 | Phone at rest is AES-256-GCM ciphertext; only a two-digit mask ever leaves the API | integration | `uv run pytest tests/integration/test_phone_ciphertext.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-03-03 | 03 | 3 | API-01 | T-05-21 / T-05-22 / T-05-23 / T-05-24 | Purpose-checked Bearer; https-and-allowlisted push endpoints; cross-user revoke is 404 | unit + integration | `uv run pytest tests/unit/test_push_endpoint_validation.py -q && uv run pytest tests/integration/test_push_subscribe.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-04-01 | 04 | 4 | WATCH-03 | T-05-27 / T-05-28 / T-05-29 / T-05-30 | Path token verified with the manage purpose before any query; one indistinguishable 401; token re-minted | integration | `uv run pytest tests/integration/test_manage_route.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-04-02 | 04 | 4 | WATCH-04 | T-05-26 / T-05-31 / T-05-32 | User-scoped predicate gives 404 not 403; omitted PATCH fields never clear a filter | unit + integration | `uv run pytest tests/unit/test_watch_update_model.py -q && uv run pytest tests/integration/test_watch_lifecycle.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-04-03 | 04 | 4 | WATCH-03 | T-05-33 | Previous-version token verifies through grace and fails at cutoff; the script prints no key material | unit | `uv run pytest tests/unit/test_token_rotation.py tests/unit/test_rotate_script.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 05-05-01 | 05 | 5 | API-02 | T-05-35 / T-05-38 / T-05-39 | One groupless consumer per process, never committed; a dead pump is visible to readiness | integration | `uv run pytest tests/unit/test_feed_consumer_config.py -q && uv run pytest tests/integration/test_sse_live.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-05-02 | 05 | 5 | API-02 | T-05-36 / T-05-40 | A slow client degrades only its own stream; limits are clamped | unit + integration | `uv run pytest tests/unit/test_sse_framing.py tests/unit/test_feed_hub.py tests/unit/test_api_async_only.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 05-05-03 | 05 | 5 | API-03 | T-05-40 / T-05-41 / T-05-42 | Bound parameters throughout; deterministic pagination; streaming excluded from the latency histogram | integration | `uv run pytest tests/integration/test_restaurants_api.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-06-01 | 06 | 6 | API-03 | T-05-44 / T-05-45 / T-05-47 / T-05-48 / T-05-50 | Constant-time non-short-circuiting credential check; 404 when unconfigured; delete refused with active watches | unit + integration | `uv run pytest tests/unit/test_admin_guard.py -q && uv run pytest tests/integration/test_admin.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-06-02 | 06 | 6 | API-03 | T-05-49 / T-05-51 / T-05-53 | Override written with the platform id; admin client closed on every path; health degrades per section | integration | `uv run pytest tests/integration/test_admin.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 05-06-03 | 06 | 6 | API-01 | T-05-52 | The documented walkthrough runs in CI and prints no secret; the route contract is snapshot-pinned | unit + integration | `uv run pytest tests/unit/test_openapi_snapshot.py -q && uv run pytest tests/integration/test_api_smoke_script.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** every task in every plan carries an `<automated>` verify. There is no run of
three consecutive tasks without one.

---

## Wave 0 Requirements

Wave 0 is a **precondition-verification task** (05-01 Task 1), not a scaffold wave: Phase 5 consumes
nine artifacts that Phases 3 and 4 own, and none may be redefined here.

- [ ] `tests/unit/test_phase5_preconditions.py` — asserts, each with the owning decision id and plan
      in its failure message: `shared/tokens.py` (D-82 / 04-01), `shared/crypto.py` (D-85 / 04-01),
      `shared/metrics.py` (D-69 / 03-02), the `watch:count` and `tier:override` helpers in
      `shared/redis_keys.py` (D-58 / 03-02), `services/api/app.py :: create_app` (D-84 / 04-04),
      `EmailProvider` (D-78 / 04-05), a migration establishing `uq_restaurants_slug_source`
      (D-63b / 03-03), a migration establishing `push_subscriptions` and `users.phone_hash`
      (D-85 / 04-02), and that `shared/db.py :: Restaurant.slug` no longer declares a single-column
      uniqueness (research §Sequencing trap 1).
- [ ] `tests/integration/conftest.py` — the `live_api` in-process uvicorn fixture (**BC-1; blocks
      every SSE assertion in 05-05**) and the `api_app` fixture built on the existing
      `reset_shared_db_singletons()` env-freeze workaround.
- [ ] `tests/unit/factories.py` — extended with a `watch_create_payload` builder and a feed-event
      builder for the hub tests.
- [ ] `tests/unit/test_api_async_only.py` — a new grep gate scoped to `services/api/**` with its
      non-vacuity companion.
- [ ] `tests/unit/test_no_setnx_expire_pairs.py` — its scanned directory tuple already covers
      `services/api`; add the non-vacuity assertion that a module from this phase is in the scanned
      set.
- [ ] Framework install: **none needed** — pytest, pytest-asyncio, testcontainers, freezegun and
      respx are all pinned and installed. This phase adds zero packages.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| SSE first-event latency measured through the deployed URL rather than a local socket | API-02 (ROADMAP SC3) | Requires a deployed service and its request-timeout setting, which is Phase 7 work; locally the same path measures ~18 ms end to end against a 500 ms budget | `docs/runbooks/sse-cloudrun.md` (`STATUS: pending-human`), written in 05-06 |
| `docs/api.md` curl walkthrough executed by a human against a running stack | API-01 / API-03 | The documentation is a portfolio artifact and its prose is judged, not just its exit code | `make api-smoke` — the same script is run in CI by `tests/integration/test_api_smoke_script.py`, so only the prose review is genuinely manual |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency: unit tier after every task commit
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
