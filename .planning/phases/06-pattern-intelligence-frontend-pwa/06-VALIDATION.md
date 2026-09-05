---
phase: 06
slug: pattern-intelligence-frontend-pwa
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-05
---

# Phase 06 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> This phase has two test estates — Python (pytest) for PATTERN-01..03 and TypeScript (Vitest) for FE-01..07 —
> plus two script gates (`make web-build-offline`, `make lighthouse`). All four are phase gates.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (backend)** | pytest 9.x + pytest-asyncio (`asyncio_mode = "auto"`), testcontainers for integration |
| **Config file (backend)** | `pyproject.toml [tool.pytest.ini_options]`; containers in `tests/integration/conftest.py` (`timescale/timescaledb:2.17.2-pg16`) |
| **Framework (frontend)** | Vitest 4.1.11 + jsdom 30 + React Testing Library 16.3.3 + axe-core 4.13.0 — **no mock-service-worker** (D-118a: `vi.stubGlobal("fetch", …)` over typed fixtures) |
| **Config file (frontend)** | `web/vitest.config.mts` + `web/vitest.setup.ts` — **created in Wave 0 (plan 06-04, task 1)** |
| **Quick run command** | `cd web && npm test && cd .. && uv run pytest tests/unit -q` |
| **Full suite command** | `uv run pytest tests/unit tests/integration -q -p no:cacheprovider && cd web && npm test && npm run typecheck && npm run lint && npm run build` |
| **Extra script gates** | `make web-build-offline` (BC-2 prerender regression) · `make lighthouse` (FE-07 budget, median of 5) |
| **Estimated runtime** | quick ~30 s (frontend ~1 s, backend unit ~25 s); full ~6–9 min (testcontainers + two Next builds + 5 Lighthouse runs) |

**Backend quick run is `make test`** (`uv run pytest tests/unit -x -q -W error::RuntimeWarning`) — the
`RuntimeWarning`-as-error flag is a standing Phase 2 gate and must not be dropped.

---

## Sampling Rate

- **After every task commit:** run the quick command (`cd web && npm test && cd .. && uv run pytest tests/unit -q`).
  For a backend-only task the frontend half may be skipped; for a frontend-only task the backend half may be skipped.
- **After every plan (each plan is its own wave here):**
  `uv run ruff check . && uv run mypy shared/ services/ scripts/ && uv run pytest tests/unit -x -q -W error::RuntimeWarning`
  and, once `web/` exists (from plan 06-04 onward), `cd web && npm test && npm run typecheck && npm run lint && npm run build`
  plus `make web-build-offline`.
- **Before `/gsd-verify-work`:** the full suite command plus `make lighthouse`, all green.
- **Max feedback latency:** 30 seconds (quick command).

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 06-01-01 | 01 | 1 | PATTERN-01/02 | T-06-SC | Phase 4/5 artifacts proven present before Phase 6 edits them; plan halts rather than stubbing | unit | `uv run pytest tests/unit/test_phase6_preconditions.py -x -q` | ❌ W0 | ⬜ pending |
| 06-01-02 | 01 | 1 | PATTERN-01 | T-06-01 | Every claim carries n and CI; exact Wilson pair asserted | unit | `uv run pytest tests/unit/test_pattern_stats.py tests/unit/test_pattern_model.py -x -q` | ❌ W0 | ⬜ pending |
| 06-01-03 | 01 | 1 | PATTERN-01/02 | T-06-01 / T-06-02 / T-06-04 | Undetected rules omitted; no forbidden-certainty word in rendered output; purity gate | unit | `uv run pytest tests/unit -x -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 06-02-01 | 02 | 2 | PATTERN-02 | T-06-07 | CAGG real-time on, both weekday axes, re-aggregable duration columns | integration | `uv run pytest tests/integration/test_cagg_availability_events_hourly.py -x -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 06-02-02 | 02 | 2 | PATTERN-02 | T-06-08 | `sparse` boundary at 9 vs 10; 168 cells on empty input; keys in the one registry | unit | `uv run pytest tests/unit/test_redis_keys_phase6.py tests/unit/test_heatmap_densify.py -x -q` | ❌ W0 | ⬜ pending |
| 06-02-03 | 02 | 2 | PATTERN-01/02 | T-06-05 / T-06-06 / T-06-09 | Parameterised slug queries; cache holds no token; Redis outage degrades latency only | integration | `uv run pytest tests/integration/test_pattern_service_cache.py tests/integration/test_pattern_quartiles_match_sql.py -x -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 06-03-01 | 03 | 3 | PATTERN-02 | T-06-13 / T-06-14 | Routes expose aggregates only; `pattern_status` from the same cached value | integration | `uv run pytest tests/integration/test_pattern_routes.py -x -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 06-03-02 | 03 | 3 | PATTERN-03 | T-06-11 | Hook returns `None` on every failure path; sentence is ASCII; no token logged | unit | `uv run pytest tests/unit/test_pattern_hook.py tests/unit/test_templates.py -x -q` | ❌ W0 (templates: Phase 4 file, extended) | ⬜ pending |
| 06-03-03 | 03 | 3 | FE-06 | T-06-10 / T-06-12 / T-06-15 | Redirect URL from the API's own builder; HMAC verified before the Accept branch; server-driven retry | integration | `uv run pytest tests/unit/test_sse_retry_frame.py tests/integration/test_go_json_mode.py -x -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 06-04-01 | 04 | 4 | FE-01 | T-06-17 / T-06-18 / T-06-20 / T-06-21 / T-06-SC | Env allowlist, no bare fetch, no raw-HTML prop, no bundler flag, SW caches no credentialed route | script + unit | `make web-build-offline && cd web && npm test && npm run lint && npm run typecheck` | ❌ W0 | ⬜ pending |
| 06-04-02 | 04 | 4 | FE-07 | T-06-19 | Explicit image host and pathname; no theme persistence | unit | `cd web && npm test -- src/lib/format.test.ts && npm run typecheck` | ❌ W0 | ⬜ pending |
| 06-04-03 | 04 | 4 | FE-07 | T-06-16 | 44 px everywhere, label binding, no colour-only state, axe clean | unit | `cd web && npm test && npm run lint && npm run typecheck` | ❌ W0 | ⬜ pending |
| 06-05-01 | 05 | 5 | FE-04 | T-06-25 | `max` never recomputed; no client directive on the detail route | unit | `cd web && npm test -- src/lib/heatmap.test.ts && npm run build` | ❌ W0 | ⬜ pending |
| 06-05-02 | 05 | 5 | FE-04 | T-06-22 | Sparse beats the ramp at every count; one tab stop; labelled legend | unit | `cd web && npm test -- src/components/Heatmap.test.tsx` | ❌ W0 | ⬜ pending |
| 06-05-03 | 05 | 5 | FE-04 / PATTERN-02 | T-06-23 / T-06-24 / T-06-26 | Undetected rules omitted; text-only rendering; placeholder fallback on a ready-with-null report | unit | `cd web && npm test && npm run typecheck && npm run lint` | ❌ W0 | ⬜ pending |
| 06-06-01 | 06 | 6 | FE-02 | T-06-28 | 1 event/s cap applied before the DOM append; 50-event burst backstop | unit | `cd web && npm test -- src/lib/feed.test.ts` | ❌ W0 | ⬜ pending |
| 06-06-02 | 06 | 6 | FE-02 | T-06-27 / T-06-31 / T-06-32 | Exactly one EventSource per tab, no credentials, debounced search | unit | `cd web && npm test -- src/components/LiveFeed.test.tsx src/components/Search.test.tsx` | ❌ W0 | ⬜ pending |
| 06-06-03 | 06 | 6 | FE-02 | T-06-29 / T-06-30 | Sample data labelled visibly and accessibly; counter hidden rather than faked | unit + script | `cd web && npm test && make -C .. web-build-offline` | ❌ W0 | ⬜ pending |
| 06-07-01 | 07 | 7 | FE-03 | T-06-36 | Client rules mirror the API's; optional blanks omitted from the request body | unit | `cd web && npm test -- src/components/WatchForm src/app/watch` | ❌ W0 | ⬜ pending |
| 06-07-02 | 07 | 7 | FE-03 | T-06-37 | Preview equals backend-rendered samples byte for byte; SMS within the segment budget | unit | `uv run pytest tests/unit/test_notification_samples_fixture.py -x -q && cd web && npm test -- src/lib/preview.test.ts` | ❌ W0 | ⬜ pending |
| 06-07-03 | 07 | 7 | FE-01 / FE-03 | T-06-33 / T-06-34 / T-06-35 / T-06-38 | No credential in browser storage; subscription posted with the bearer token; offline queue honestly labelled and idempotent | unit | `cd web && npm test && npm run typecheck && npm run lint` | ❌ W0 | ⬜ pending |
| 06-08-01 | 08 | 8 | FE-06 | T-06-39 / T-06-40 | Redirect host allowlist with no substring match; no-referrer on every anchor | unit | `cd web && npm test -- src/lib/redirect-allowlist.test.ts src/app/go/go-page.test.tsx` | ❌ W0 | ⬜ pending |
| 06-08-02 | 08 | 8 | FE-05 | T-06-43 / T-06-44 / T-06-45 | Optimistic state keyed by id; exact rollback; idempotent no-ops | unit | `cd web && npm test -- src/components/WatchCard.test.tsx` | ❌ W0 | ⬜ pending |
| 06-08-03 | 08 | 8 | FE-05 | T-06-41 / T-06-42 | Token never stored or logged; expired and foreign tokens render identically | unit | `cd web && npm test && npm run typecheck && npm run lint` | ❌ W0 | ⬜ pending |
| 06-09-01 | 09 | 9 | FE-07 / FE-01 | T-06-47 / T-06-49 | Gate throws on a runtime error instead of comparing null; SW artifact asserted present | script | `make lighthouse` | ❌ W0 | ⬜ pending |
| 06-09-02 | 09 | 9 | FE-07 | T-06-50 | axe over six route shells; 44 px sweep with one documented exception; four UI-SPEC backstops | unit | `cd web && npm test -- src/app/a11y.test.tsx src/app/backstops.test.tsx src/components/tap-targets.test.tsx` | ❌ W0 | ⬜ pending |
| 06-09-03 | 09 | 9 | FE-01 / FE-07 | T-06-46 / T-06-48 | No secret documented under a public prefix; lab median never presented as a field p75 | script | `uv run pytest tests/unit -x -q -W error::RuntimeWarning && cd web && npm test && npm run build && npm run lint && npm run typecheck` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 for this phase spans two tasks, because the phase has two test estates and neither exists yet.

**Backend Wave 0 — plan 06-01, task 1 (and its fixtures in tasks 2–3):**

- [ ] `tests/unit/test_phase6_preconditions.py` — proves every Phase 4 / Phase 5 artifact this phase modifies exists, and resolves the Alembic head for 06-02's `down_revision`
- [ ] `tests/unit/factories.py :: make_event_obs` — added to the existing shared factory module
- [ ] `tests/fixtures/pattern/{48h_heavy,load_day,flat,sparse,gate_boundary}.json` — the five deterministic corpora every PATTERN-01/02 assertion is an exact number against
- [ ] `tests/unit/test_pattern_{stats,model,gating,summary_text,purity}.py` — cover PATTERN-01 and PATTERN-02
- [ ] `tests/integration/test_cagg_availability_events_hourly.py` — covers the PATTERN-02 CAGG claim (06-02 task 1)
- [ ] No framework install needed: pytest, pytest-asyncio and testcontainers are already in `uv.lock`

**Frontend Wave 0 — plan 06-04, task 1:**

- [ ] `web/` scaffold itself — nothing frontend can be tested before it exists
- [ ] `web/vitest.config.mts`, `web/vitest.setup.ts` — the config every FE-* row depends on
- [ ] `web/src/lib/api.ts` with `safeFetch` — the BC-2 mitigation every server component depends on
- [ ] `web/src/test/fixtures/api.ts` — typed fixtures replacing the mock-service-worker package (D-118a)
- [ ] `web/src/lib/gates.test.ts` — the four mechanical prohibitions (no bundler flag, no bare fetch, no raw-HTML prop, env allowlist)
- [ ] Makefile targets `web-install`, `web-dev`, `web-build`, `web-build-offline`, `web-test`
- [ ] `web/scripts/lighthouse.mjs` and the `lighthouse` make target — covers FE-07 (plan 06-09, task 1)
- [ ] Dev-dependency install needs the legacy peer resolution flag ONCE on this npm version (BC-9); the `web-install` target does not carry it
- [ ] Browsers: **already present** — the Playwright headless shell is on this machine; no browser install step is needed

**Cross-estate Wave 0 — plan 06-07, task 2:**

- [ ] `scripts/dump_notification_samples.py` and `web/src/test/fixtures/notification-samples.json` — the parity oracle that makes the FE-03 preview test possible at all

---

## Sampling Continuity

No three consecutive tasks lack an automated verify: every one of the 27 tasks in this phase carries an
`<automated>` command, and every command is a real runner invocation (pytest, Vitest or a make target) rather than a
manual instruction. No task uses a watch-mode flag.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Five consecutive Web Push notifications arrive on a real iPhone in Home-Screen standalone mode without the subscription being revoked | FE-01, ROADMAP Phase 4 SC3 | Requires a physical iOS device; a simulator does not exercise the Apple push service, and the revocation behaviour only appears on real hardware | `docs/runbooks/ios-pwa-push.md` (STATUS: pending-human) — install to the Home Screen, open from the Home Screen, complete the watch flow, enable notifications, trigger five sends, record each arrival with a timestamp |
| Largest-contentful-paint p75 on the production URL is at or under 2.5 s on mobile | FE-07 | p75 is a field metric requiring real-user data from a deployed origin; the local gate produces a five-run lab median, which is evidence of headroom, not the SLO | `docs/runbooks/lighthouse-p75.md` (STATUS: pending-human) — created in plan 06-09 task 3, records the deployed URL, the field-data source and the threshold |
| The three public environment variables are set on the hosting platform before the first production build | FE-01, FE-07 | Values are inlined into the client bundle at build time (BC-10); setting them requires access to the hosting project | `web/README.md` deploy section — the orchestrator's post-phase deploy step reads it |

Everything else in this phase — including the CAGG, the pattern model, all six routes, the service worker artifact,
the accessibility sweep and the performance budget — has automated verification.

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (backend in 06-01, frontend in 06-04, cross-estate parity oracle in 06-07)
- [x] No watch-mode flags
- [x] Feedback latency < 30 s (quick command)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
