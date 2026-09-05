---
phase: 03
slug: resy-playwright-fleet
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-05
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml [tool.pytest.ini_options]` — `testpaths = ["tests"]`, `pythonpath = ["."]`, marker `integration` |
| **Quick run command** | `uv run pytest tests/unit -x -q` (`make test`) |
| **Full suite command** | `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` (`make test-integration`) |
| **Lint gate (every plan)** | `uv run ruff check . && uv run mypy shared/ services/ scripts/` (`make lint`) |
| **Browser guard** | `tests/conftest.py :: _chromium_available()` — compares the INSTALLED directory against the revision `playwright/driver/package/browsers.json` declares, honours `PLAYWRIGHT_BROWSERS_PATH`. A glob would falsely pass on the stale sibling revision (research B-1) |
| **Container guard** | existing `tests/conftest.py :: _docker_available()` |
| **Fake server** | `tests/fakes/resy_stub.py` — in-process FastAPI + `uvicorn.Server` on an ephemeral port, five response modes via `POST /__ctl/mode`, header hit log via `GET /__ctl/hits` |
| **Estimated runtime** | unit tier ~5 s; browser tests measured at ~1 s each (3 tests + stub + real Chromium = 2.94 s end to end); container tests dominated by testcontainer startup |

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/unit -x -q` — every arithmetic, verdict, fingerprint-coherence, config-lazy and grep-gate property lives at the unit tier and needs neither a browser nor a container.
- **After every plan:** `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` plus `make lint` plus the three CI ban-greps.
- **After every wave:** full suite green; existing 156 unit / 52 integration tests must remain green — never disabled, never skipped to pass. An environment guard (`_docker_available`, `_chromium_available`) may skip with an explicit remediation message; nothing else may.
- **Before `/gsd-verify-work`:** full suite green, `pgrep -f ms-playwright | wc -l` reports 0, `git diff --stat tests/fixtures/raw_streams/` empty.
- **Max feedback latency:** ~5 s (unit tier).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 1 | POLL-05 | T-03-01 / T-03-04 | Unusable third-party JSON becomes `ParseError` → UNKNOWN, never an escaping exception that halts a partition; coverage never claims an unobserved date | unit | `uv run pytest tests/unit/test_tracer_resy_raw_to_event.py -q` | ❌ W0 | ⬜ pending |
| 03-01-02 | 01 | 1 | POLL-06 | T-03-02 | Every non-success poll status marks UNKNOWN through one shared frozenset; a soft ban can never read as healthy | unit | `uv run pytest tests/unit/test_events_schema.py tests/unit/test_banned_marks_unknown.py tests/unit/test_replay_determinism.py -q` | ⚠️ 2 of 3 exist | ⬜ pending |
| 03-01-03 | 01 | 1 | POLL-05 | T-03-01 / T-03-03 | Per-slot type guards skip; poll-level unusability raises; `booking_token` value never logged | unit | `uv run pytest tests/unit/test_parsers_resy.py -q` | ❌ W0 | ⬜ pending |
| 03-02-01 | 02 | 1 | POLL-02, POLL-05 | T-03-06 / T-03-07 / T-03-09 | The 80 rpm cap is enforced server-side, atomically, with a mandatory TTL; a refusal consumes no budget | integration | `uv run pytest tests/integration/test_rate_budget_lua.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 1 | POLL-06 | T-03-05 / T-03-08 | Eight secret-bearing key names redacted before any cookie code exists; one metric definition site | unit | `uv run pytest tests/unit/test_telemetry_redaction.py tests/unit/test_metrics_registry.py -q` | ⚠️ 1 of 2 exists | ⬜ pending |
| 03-02-03 | 02 | 1 | POLL-02 | T-03-09 | An absent/negative watch count degrades to the slowest tier rather than raising inside `poll_loop` | unit | `uv run pytest tests/unit/test_tier_cadence.py tests/unit/test_effective_interval.py tests/unit/test_jitter_bounds.py tests/unit/test_backoff_math.py -q` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 1 | POLL-05 | T-03-10 / T-03-12 / T-03-14 | Migration refuses rather than destroys; no fabricated venue id can reach the queue; `RESY_ENABLED` defaults false | integration | `uv run pytest tests/integration/test_migration_0009.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-03-02 | 03 | 1 | POLL-05 | T-03-11 / T-03-13 | Resolver refuses without credentials, makes zero network calls on `--dry-run`, writes only inside the repo via temp+rename | integration | `env -u RESY_API_KEY uv run python scripts/resolve_resy_venue_ids.py --dry-run; test $? -eq 2` | ❌ W0 | ⬜ pending |
| 03-03-03 | 03 | 1 | POLL-05 | T-03-14 | Every Resy setting is read at call time; an integer typo raises rather than silently defaulting | unit | `uv run pytest tests/unit/test_resy_config_lazy.py -q` | ❌ W0 | ⬜ pending |
| 03-04-01 | 04 | 2 | POLL-04 | T-03-15 / T-03-16 / T-03-17 / T-03-18 / T-03-19 | Coherent per-context identity, no headless marker, browser download is an explicit revision-verified step, shielded teardown, all traffic to 127.0.0.1 | integration | `uv run pytest tests/integration/test_stealth_applied.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-04-02 | 04 | 2 | POLL-04 | T-03-15 / T-03-16 | Every fingerprint row internally coherent; every `SCRIPT_ORDER` name real (mypy cannot catch it — the package is untyped) | unit | `uv run pytest tests/unit/test_fingerprints.py tests/unit/test_stealth_script_names.py -q` | ❌ W0 | ⬜ pending |
| 03-04-03 | 04 | 2 | POLL-04 | T-03-17 | A stale sibling browser revision is reported unavailable, so nine browser tests cannot silently pass against a broken launch | unit | `uv run pytest tests/unit/test_browser_guard.py -q` | ❌ W0 | ⬜ pending |
| 03-05-01 | 05 | 3 | POLL-04, POLL-05 | T-03-20 / T-03-22 / T-03-23 / T-03-26 | Cookies only in context memory; shielded teardown leaves zero processes; `.json()` guarded; no page load | integration | `uv run pytest tests/integration/test_context_pool.py tests/integration/test_resy_request_headers.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-05-02 | 05 | 3 | POLL-04 | T-03-24 / T-03-25 | Both cookie shapes reach `api.resy.com`; anonymous mode is logged once and labelled in metrics | integration | `uv run pytest tests/unit/test_resy_accounts.py tests/integration/test_anonymous_mode.py tests/integration/test_fingerprint_rotation.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-05-03 | 05 | 3 | POLL-06 | T-03-29 | A pure verdict, replayable with no Redis; a fully booked venue is not mistaken for a ban | unit + integration | `uv run pytest tests/unit/test_response_signature.py tests/unit/test_canary_verdict.py tests/integration/test_canary_window.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-05-04 | 05 | 3 | POLL-05 | T-03-26 | No wait anywhere under the Resy package — the floor, the cap and the backoff are all ZSET scores | unit | `uv run pytest tests/unit/test_no_inline_sleep_resy.py tests/unit/test_no_inline_sleep.py -q` | ❌ W0 | ⬜ pending |
| 03-06-01 | 06 | 4 | POLL-02, POLL-05 | T-03-27 / T-03-28 | SC3: a 429 becomes a backoff score and a recycle in one cycle; unknown sources are dropped, never leaked | integration | `uv run pytest tests/integration/test_429_backoff_and_recycle.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-06-02 | 06 | 4 | POLL-02, POLL-05 | T-03-27 / T-03-28 | Backoff beats expedite without stranding the flag; both rate gates refuse by rescheduling; no gate leaks a claimed job | integration | `uv run pytest tests/integration/test_release_precedence.py tests/integration/test_per_context_floor.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-06-03 | 06 | 4 | POLL-06 | T-03-29 / T-03-32 | A ban is counted, published as non-success with a `context_id`, and escalates to a source-scoped fleet pause; replay stays byte-identical | integration | `uv run pytest tests/integration/test_ban_reaction.py tests/integration/test_fleet_pause.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-06-04 | 06 | 4 | POLL-05, POLL-06 | T-03-30 / T-03-31 | SC5 at the integration tier; a disabled deployment launches no browser; teardown on every exit path | integration | `uv run pytest tests/integration/test_resy_e2e_state_machine.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-07-01 | 07 | 5 | PERF-05 | T-03-33 / T-03-35 | A 90 s soak drives the real fleet against the stub and produces a verdict that could have gone red | integration | `uv run pytest tests/integration/test_soak_ci.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-07-02 | 07 | 5 | PERF-05 | T-03-33 | Every gate boundary including the warm-up baseline is pinned; zero processes or too few samples exits 2, never 0 | unit | `uv run pytest tests/unit/test_soak_verdict.py tests/unit/test_soak_sampling.py -q` | ❌ W0 | ⬜ pending |
| 03-07-03 | 07 | 5 | PERF-05 | T-03-34 | Both the clean AND the leaking teardown are asserted, so the clean assertion cannot be vacuous | integration | `uv run pytest tests/integration/test_no_zombie_browsers.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 03-07-04 | 07 | 5 | PERF-05 | T-03-36 / T-03-37 / T-03-38 | Human-gated steps carry explicit pending-human banners; the public README claim names the enforcing code | doc-check | `test -f docs/runbooks/perf05-soak.md && test -f docs/runbooks/resy-cookie-capture.md && grep -q "pending-human" docs/runbooks/perf05-soak.md && grep -q "pending-human" docs/runbooks/resy-cookie-capture.md` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 is folded into the leading task of the plan that first needs each item; nothing is deferred to
a separate setup plan.

- [ ] **`uv run playwright install chromium`** — BLOCKING for every browser test. The cache held revision 1223 while the pinned `playwright==1.58.0` requires 1208, and every `chromium.launch()` failed (research B-1). Landed as `make browsers` in **03-04 Task 1**.
- [ ] `tests/conftest.py` — revision-aware `_chromium_available()` guard plus a function-scoped `browser` fixture with the shielded `finally` (**03-04 Task 1**).
- [ ] `tests/fakes/__init__.py` + `tests/fakes/resy_stub.py` + the `stub_base` fixture — the in-process uvicorn fake all nine browser tests and the soak point at (**03-04 Task 1**).
- [ ] `services/poller/sources/resy/fixtures.py` — the `[ASSUMED]` `/4/find` bodies with `TODO(spike)` markers for normal, empty-`venues`, missing-`results`, 429 and the 403 challenge HTML (**03-01 Task 1**).
- [ ] `shared/telemetry.py` redaction extension — must land BEFORE any cookie-handling code exists (**03-02 Task 2**, wave 1; cookie code arrives in 03-05, wave 3).
- [ ] `shared/metrics.py` with explicit histogram buckets (**03-02 Task 2**).
- [ ] `tests/unit/factories.py` — `make_resy_envelope` / `make_resy_raw`, so no Resy fixture reads a wall clock (**03-01 Task 1**).
- [ ] `scripts/seed/restaurants.yml` field split + `scripts/seed_restaurants.py` two-row seed — without these no Resy job can exist at all (**03-03 Task 1**).
- [ ] Framework install: **none**. pytest, pytest-asyncio, testcontainers, FastAPI, uvicorn, playwright, prometheus-client are all already pinned and installed; this phase adds zero packages.
- [ ] 30 new test files across the seven plans. Only `test_events_schema.py`, `test_replay_determinism.py` and `test_telemetry_redaction.py` already exist and are extended in place.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| The 12-hour Playwright soak run | PERF-05 | Twelve hours of wall clock against a live fleet; a hard ROADMAP gate before Resy runs in production. No agent can perform it | Follow `docs/runbooks/perf05-soak.md`. Prerequisites: infra up, `make browsers`, `RESY_ENABLED=true` with real accounts and resolved venue ids, free disk. Run `uv run python scripts/soak_playwright.py --duration 12h --sample-every 30s --venues 10`. PASS requires RSS ≤ baseline + 20 % (baseline = first sample at or after t + 2 min), Playwright PID spread ≤ 2, poll success rate ≥ 0.99. Record the result in the runbook's results table |
| Resy session-cookie capture into `RESY_ACCOUNTS_JSON` | POLL-04 | Requires a supervised human login to a third-party account; the project never automates account creation or login | Follow `docs/runbooks/resy-cookie-capture.md`. Cookies must use `domain=".resy.com"` or they never reach `api.resy.com`. Never commit the value |
| `RESY_API_KEY` and the auth-token header name capture | POLL-05 | A DevTools capture against a live browser session; the header name is corroborated but unverified (research A5) | Follow `docs/runbooks/resy-cookie-capture.md` §API key. Verify by pointing `RESY_API_BASE` at the live host and confirming a 200 with a non-empty `results.venues` |
| Numeric Resy `venue_id` resolution for the 31 Resy restaurants | POLL-05 | Needs a live `RESY_API_KEY`; the resolution endpoint is `[ASSUMED]` (research A4) | `uv run python scripts/resolve_resy_venue_ids.py` with the key set. Verify with the YAML count check in 03-03 Task 1's acceptance criteria, then re-run `make seed` |
| Residential proxy subscription and `RESY_PROXY_URL` | POLL-04 | Requires a paid third-party subscription | Follow `docs/runbooks/resy-cookie-capture.md` §Proxy. Verify by observing the egress IP from a single stub-backed poll with the proxy set |
| SC4's "sustained 30-minute production trace in Grafana" | POLL-05 | Grafana panels are Phase 7; this phase only exports the metrics | This phase's automated substitute is `tests/integration/test_rate_budget_lua.py` + `test_per_context_floor.py`, which prove the caps are enforced. The Grafana trace is deferred to Phase 7 with the metrics already exported on `METRICS_PORT` |

*Everything else in this phase has automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or an explicit Wave 0 dependency (23 of 23 tasks carry a runnable command)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify — every task in every plan carries one
- [x] Wave 0 covers all MISSING references (browser install, guard, stub, fixtures, redaction, metrics, factories, seed split)
- [x] No watch-mode flags
- [x] Feedback latency < 5 s at the unit tier
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
</content>
