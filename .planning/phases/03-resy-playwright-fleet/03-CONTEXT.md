# Phase 3: Resy & Playwright Fleet - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning
**Mode:** Autonomous smart discuss — recommended answers accepted for every grey area (no human available; defaults chosen for consistency with PROJECT.md, REQUIREMENTS.md, Phase 1 D-01..D-35 and Phase 2 D-36..D-56)

<domain>
## Phase Boundary

Add Resy as a second polling source inside the existing poller service: a Playwright context pool (1 browser, 4 contexts) with `tf-playwright-stealth`, per-context fingerprint rotation, optional residential proxy, pre-authenticated sessions loaded from env, direct calls to Resy's internal `/4/find` availability API through the browser's request context, a Redis-enforced global cap of <= 80 req/min and >= 45 s per restaurant per context, a soft-ban canary metric (`scrape_ban_total`) with context recycling and fleet pause, tier-based cadence (60 s / 3 min / 10 min by active-watch count) with +/-15 % jitter and exponential backoff on 429/503, the Resy parser registered in the Phase 2 parser registry (no source branching in the diff engine), and the 12-hour soak tooling (PERF-05). Requirements: POLL-02, POLL-04, POLL-05, POLL-06, PERF-05.

**Human-gated (build around, do not block):** real Resy accounts/cookies (FOUND-06), the Resy API key/headers DevTools capture, a residential proxy subscription, and the 12-hour production soak run. Every one of these is env-driven with a documented placeholder; the code paths are exercised locally against a fixture-backed stub server with real headless Chromium.

Out of scope: watchlist CRUD that *produces* the active-watch counts (Phase 5 — this phase defines and reads the Redis contract with a default of 0), notification fan-out (Phase 4), Grafana panels (Phase 7 — this phase exports the Prometheus metrics).

</domain>

<decisions>
## Implementation Decisions

### Tier-based cadence, jitter and backoff (POLL-02)
- **D-57:** `shared/redis_keys.py` gains `tier_interval_seconds(active_watches: int) -> int` returning 60 (>= 10 watches), 180 (3–9), 600 (0–2) — the literal POLL-02 tiers — and `effective_interval_seconds(source, active_watches, override)`: `min(tier, baseline[source])` floored by the per-source minimum. Baselines: OpenTable 90 s (`POLL_INTERVAL_SECONDS`, POLL-03 floor — watches can only speed polling up, never slow the heatmap data collection down), Resy 180 s default (`RESY_BASELINE_INTERVAL_SECONDS`) floored at 45 s (POLL-05). Jitter stays +/-15 % (`POLL_JITTER_FRACTION`).
- **D-58:** Active-watch counts are read from the Redis HASH `watch:count` (field `{source}:{restaurant_id}`, value = integer count of active watchlist entries) — written by Phase 5, read here with default 0. Admin tier override: HASH `tier:override` (field `{source}:{restaurant_id}`, value 1|2|3) wins over the computed tier when present (Phase 5 admin route writes it). Both keys live in `shared/redis_keys.py`.
- **D-59:** Exponential backoff on 429/503 (and on a canary ban): per-job key `backoff:{source}:{rid}` holding the current backoff seconds (TTL = 2x its value); next attempt = `min(interval * 2^n, 1800 s)`; reset (DEL) on the next successful poll. Backoff is applied in the poller release path as the ZSET score — never `asyncio.sleep`. The Phase 2 expedite flag (`sched:expedite:*`) is honoured *only* when no backoff is active.

### Playwright context pool and fingerprints (POLL-04)
- **D-60:** `services/poller/sources/resy/pool.py :: ContextPool` — one `async_playwright()` Chromium `Browser`, `N = RESY_CONTEXTS` (default 4) `BrowserContext`s, acquisition via `asyncio.Semaphore(N)` + an `asyncio.Queue` of idle contexts (no custom pool framework). Each context is created with a fingerprint from `services/poller/sources/resy/fingerprints.py` (rotation table of `{user_agent, viewport, locale, timezone_id, device_scale_factor}` — >= 6 entries, chosen round-robin per context creation) and `tf-playwright-stealth` applied (`Stealth().apply_stealth_async(context)` — verify the exact 1.2.0 API in research). Context recycle triggers: canary ban, `pages_served >= 500`, age >= 2 h, or an unrecoverable Playwright error. Recycling closes the context and creates a fresh one with the next fingerprint and the next account's cookies.
- **D-61:** Sessions are pre-authenticated from env `RESY_ACCOUNTS_JSON` (JSON array of `{"email": "...", "cookies": ...}` where `cookies` is EITHER the `.env.example`/Phase 1 runbook shape — a `{name: value}` object, expanded to Playwright cookies with `domain=".resy.com"`, `path="/"`, `secure=true` — OR an explicit Playwright cookie list `[{"name","value","domain","path",...}]`; both are accepted and validated by a small pydantic model in `services/poller/sources/resy/accounts.py`), injected via `context.add_cookies(...)`; cookies exist only in context memory (never DB, never logs — `shared/telemetry.py` redaction covers `cookie`/`auth_token`/`x-resy-auth-token`). Accounts are assigned to contexts round-robin; with fewer accounts than contexts the accounts repeat. If `RESY_ACCOUNTS_JSON` is empty/unset the fleet starts in **anonymous mode** (contexts without cookies) and logs a `resy_anonymous_mode` warning once — the pool still runs so the stub-backed tests and the soak script work without secrets.
- **D-62:** Optional residential proxy via `RESY_PROXY_URL` (`http[s]://user:pass@host:port`) passed as Playwright `proxy=` at browser launch; unset = direct. No proxy rotation logic in this phase.
- **D-63:** Resy jobs enter `sched:polls` only when `RESY_ENABLED=true` (`scripts/seed_restaurants.py` enqueues `resy:{resy_venue_id}` for every restaurant that has one, in addition to the OpenTable job; default `RESY_ENABLED=false`). The poller's `poll_loop` dispatches by a `{source: adapter}` registry (replacing the `if source == "opentable"` branch) and the Resy adapter is only constructed when `RESY_ENABLED=true`, so an unconfigured deployment never launches Chromium.

### Resy availability call, rate limiting (POLL-05)
- **D-64:** `services/poller/sources/resy/adapter.py :: ResyAdapter(AvailabilitySource)` polls via the context's `request` (Playwright `APIRequestContext`, which shares cookies, UA and TLS fingerprint with the context) — no HTML page loads: `GET {RESY_API_BASE}/4/find?lat=0&long=0&day={YYYY-MM-DD}&party_size={n}&venue_id={venue_id}` with headers `Authorization: ResyAPI api_key="{RESY_API_KEY}"`, `X-Resy-Auth-Token` (from the injected cookie/env), `X-Origin: https://resy.com`, `Accept: application/json`. `RESY_API_BASE` defaults to `https://api.resy.com` and is overridable so tests point at the local stub. One request per (date, party) pair; the date range and party matrix follow Phase 1 D-19 but the per-poll request count is bounded by the rate budget — the adapter polls `RESY_DATE_RANGE_DAYS` (default 3) x party sizes `[2]` by default so one poll = 3 requests. `raw_response` is an envelope `{"requests": [{"date": ..., "party_size": ..., "status": ..., "body": {...}}]}` so `request_params["party_sizes"]` is truthful (fixes the Phase 2 B-4 class of bug for Resy from day one) and `coverage` in the parser is derived from the envelope entries with status 200.
- **D-65:** Global cap enforced **at the scheduler before dispatch** (ARCHITECTURE Pattern): Lua/atomic `INCR rate:resy:{epoch_minute}` + `EXPIRE 90` returning the new count; if the count (plus the requests this poll will make) would exceed `RESY_GLOBAL_RPM` (default 80) the job is released back with `now + 5000 ms` (no sleep) and the budget is not consumed. Per-restaurant per-context floor: `SET rate:resy:ctx:{context_id}:{venue_id} 1 NX EX 45` — if it already exists the pool picks another idle context; if none is eligible the job is released with `now + 5000 ms`. The confirmation re-poll from Phase 2 counts against the same budget.
- **D-66:** Slot identity for Resy: `time_slot` = `HH:MM` of `slot.date.start` (venue-local), `seat_type` = `slot.config.type`, `booking_token` = `slot.config.token`; `services/state_machine/parsers/resy.py :: parse_resy` is registered in `PARSER_REGISTRY["resy"]`. Response shape is `[ASSUMED]` from public captures (`results.venues[].slots[] {date{start,end}, config{type,token}, size{min,max}}`) — fixtures carry the `TODO(spike)` marker like the OpenTable ones; an unparseable body is `ParseError` → UNKNOWN exactly as D-39.

### Soft-ban canary and fleet health (POLL-06)
- **D-67:** `services/poller/sources/resy/canary.py :: ResponseSignature` = `(http_status, body_len_bucket, has_results_key, venues_count, has_slots_key)` computed per request. Rolling baseline per venue kept in Redis LIST `canary:resy:{venue_id}` (last 20 signatures, LPUSH+LTRIM). Ban verdict: HTTP 403/429 with a Resy challenge body, OR three consecutive `200` responses whose venues_count is 0 / `results` missing while the baseline majority had venues, OR body_len < 20 % of the baseline median. A ban increments the Prometheus counter `scrape_ban_total{source="resy",reason=...}`, publishes `polls.completed` with `status="banned"` (add `"banned"` to `PollCompleted.status` and to `poll_log.status` semantics — no migration needed, the column is TEXT), marks the context poisoned (recycle), and applies D-59 backoff to the job. `PollCompleted` also gains an optional `context_id: str | None` for Grafana per-context latency.
- **D-68:** If every context is poisoned within a 5-minute window the fleet sets `resy:paused 1 EX 900`; the scheduler skips Resy jobs while the key exists (releases them `+60 s`, no dispatch) and logs `resy_fleet_paused` at ERROR (Sentry hook is Phase 7). The state machine sees no raw messages during the pause, so slots stay in their last state (UNKNOWN via `polls.completed{status=banned}` per D-53).
- **D-69:** Prometheus metrics are defined once in `shared/metrics.py` (`prometheus_client` is already pinned): `scrape_ban_total`, `poll_latency_seconds{source}` histogram, `poll_total{source,status}` counter, `resy_context_recycles_total{reason}`, `resy_rate_budget_remaining` gauge, `playwright_contexts_active` gauge. The poller exposes them on `METRICS_PORT` (default 9101) via `prometheus_client.start_http_server` started inside `run()` — Phase 7 scrapes it.

### Soak test tooling (PERF-05)
- **D-70:** `scripts/soak_playwright.py --duration 12h --sample-every 30s --venues 10 [--stub]` runs the pool against the stub (`--stub`) or real Resy (needs env), sampling the poller's RSS (`resource.getrusage` for self + `ps -o rss= -p <pid>` via `asyncio.create_subprocess_exec` for Chromium children), Chromium process count (`pgrep -f chrom` via subprocess), poll success rate from `poll_log`, and `playwright_contexts_active`; writes `logs/soak-<ts>.jsonl` and a final verdict: PASS iff RSS <= baseline + 20 %, Chromium PID count stable (max - min <= 2), success rate >= 99 %. Exit codes 0/1/2 like `check_poll_success.py`. A CI-sized variant (`--duration 90s --stub`) runs as an integration test. The 12-hour run itself is **pending-human** and documented in `docs/runbooks/perf05-soak.md` with a `STATUS: pending-human-run` banner.

### Test strategy
- **D-71:** `tests/fakes/resy_stub.py` — a FastAPI app (FastAPI + uvicorn are already dependencies) serving `GET /4/find` from fixture JSON in `services/poller/sources/resy/fixtures.py`, with control endpoints `POST /__ctl/mode {normal|rate_limited|banned_empty|error_500}` and a hit log; integration tests start it with `uvicorn.Server` in-process on a random port and launch headless Chromium against it (`RESY_API_BASE=http://127.0.0.1:{port}`). Tests: pool acquires/recycles (page counter, ban), fingerprint rotation applies per context (assert `navigator.userAgent` via `context.new_page().evaluate`), stealth applied (`navigator.webdriver` is false/undefined), 45 s per-context floor and 80 rpm cap (drive the minute counter directly, no waiting), 429 → backoff score + recycle within one cycle (SC3), canary ban verdict, end-to-end Resy raw -> state machine event with no source branching (SC5), soak 90 s variant. Unit tests: tier math, backoff math, signature bucketing, parser matrix (including the D-64 envelope), `no_sleep` grep extended to the new package. Chromium is pre-installed on this machine (`playwright install chromium`); a `make browsers` target documents it and the tests **skip with a clear reason only if Chromium is genuinely absent** (environment guard, same as the Docker guard).

### Amendments after research (03-RESEARCH.md §Blocking Corrections B-1..B-9 + §Open Questions — accepted 2026-09-05)
- **D-71a (B-1):** Playwright 1.58.0 pins Chromium revision 1208; `uv run playwright install chromium` is an explicit Wave 0 task and `make browsers`. The test guard checks the pinned revision via `playwright`'s own driver metadata (not a cache-dir glob) and skips with an explicit reason only when that exact revision is absent.
- **D-60a (B-2, B-3):** `tf-playwright-stealth` has no `Stealth` class and its page-level `stealth_async` clobbers the fingerprint with an incoherent random one. Instead: build the stealth options from *our* fingerprint entry and install the package's shipped JS once per context via `context.add_init_script(...)` (the research-verified recipe) so `navigator.webdriver === undefined` and UA/platform/languages/hardwareConcurrency/deviceMemory/WebGL stay coherent for every page created later. Fingerprint coherence is a unit-tested property (`fingerprints.py` entries must agree on OS/browser/version across UA, platform, sec-ch-ua).
- **D-64a (B-9, Q1):** `context.request` is Node's HTTP client, not Chromium — it shares cookies but not TLS/header fingerprints. Set realistic headers explicitly per context via `extra_http_headers` (Accept-Language, sec-ch-ua*, Sec-Fetch-*, Referer `https://resy.com/`, X-Origin) plus the Resy auth headers per request. Keep `context.request` (PERF-05 needs page-free polling); isolate the transport in a single `ResyAdapter._fetch(ctx, url, headers) -> APIResponse` method so a future page-hosted `fetch()` is a one-method change. Record the tradeoff in `services/poller/sources/resy/README.md`.
- **D-63a (B-4):** `scripts/seed/restaurants.yml` `resy_venue_id` values are URL slugs today. Rename that field to `resy_url_slug` (string) and add `resy_venue_id` (integer or null; null for all 55 until resolved). The seed only creates the Resy `restaurants` row and enqueues `resy:{venue_id}` when a numeric id is present AND `RESY_ENABLED=true`. `scripts/resolve_resy_venue_ids.py` (human-gated: needs `RESY_API_KEY`; endpoint `[ASSUMED]` `GET /3/venue?url_slug={slug}&location=ny`) fills the numeric ids and is documented in `docs/runbooks/resy-cookie-capture.md` as a pending-human step. `poll_loop` must release a malformed job (`ZREM` from inflight) rather than leak it.
- **D-63b (B-5, Q3):** Migration 0009 replaces `UNIQUE(slug)` on `restaurants` with `UNIQUE(slug, source)` (drop `ix_restaurants_slug`, add `uq_restaurants_slug_source`), so one logical restaurant keeps the same human slug across sources; `(source, platform_id)` remains the upsert/join key (D-52). Phase 5/6 look up by slug and receive one row per source.
- **D-61a (B-6):** `shared/telemetry.py` redaction is extended to `cookie`, `cookies`, `set-cookie`, `auth_token`, `x-resy-auth-token`, `authorization`, `api_key`, `resy_api_key`, `proxy` / `resy_proxy_url` (URL credentials masked) — unit-tested with the eight secret keys from research.
- **D-67a (B-7):** Adding `banned` to `PollCompleted.status` also requires `services/state_machine/consumer.py` and `scripts/replay_raw.py` to treat `banned` like `error`/`timeout` (UNKNOWN, never success) — use a shared `FAILED_POLL_STATUSES` frozenset in `shared/events.py`. SC5 is asserted as: a Resy raw message produces an `availability.events` message through the *unchanged* `DiffEngine` (diff of `engine.py` vs Phase 2 is empty).
- **D-70a (B-8):** Memory sampling uses `ps -o rss= -p <pid>` (KB, both macOS/Linux) for the poller process and for every Chromium process found by matching the exact Playwright executable path (`pgrep -f "<ms-playwright chromium dir>"`), never `pgrep -f chrom`; `getrusage` is not used (high-water mark only). RSS growth compares the sum against the sample at t+2 min (post-warm-up baseline).
- **D-72 (Q2):** `services/poller/main.py` runs `POLL_WORKERS` concurrent `poll_loop` tasks over the single ZSET (default `1 + RESY_CONTEXTS` when Resy is enabled, else 1); the claim Lua is atomic so this is safe without changes. Documented caveat: a slow Resy poll can delay an OpenTable poll by at most one poll duration; source-filtered claims are deferred.
- **D-67b (Q4):** `ResponseSignature.body_len_bucket = 0 if n == 0 else int(log2(n))`, and the raw `body_len` is stored alongside so the "< 20 % of median" rule uses raw bytes.
- **Q5:** stale `chromium-1223` cache dirs are left alone; the soak runbook notes the disk footprint.

### Claude's Discretion
- Exact fingerprint table entries; structlog event names; whether `ContextPool` exposes an async context manager or explicit `acquire()/release()`.
- Exact stub fixture contents beyond the `[ASSUMED]` shape; how the stub simulates a Resy challenge page for the 403 path.
- How `services/poller/main.py` wires optional Resy start/stop (lifespan ordering, `browser.close()` in `finally`).

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `services/poller/sources/base.py :: AvailabilitySource` (poll(rid, dates, party_sizes) -> raw dict) — ResyAdapter implements it; `services/poller/sources/opentable/adapter.py` shows tenacity retry + 429 handling to mirror.
- `services/poller/scheduler.py :: poll_loop` — dispatch point (currently `if source == "opentable"`), release path with the Phase 2 expedite hook (`sched:expedite:*`), `_next_poll_score` — extend with tier/backoff/rate budget.
- `shared/redis_keys.py` — key registry, `set_nx_ex`, Lua scripts, `job()`; add the new keys/helpers here. `shared/scheduler/lua.py :: LuaScheduler` — claim/release/reap/expedite.
- `shared/events.py :: PollCompleted/AvailabilityRaw` — extend `status` Literal with `banned`, add `context_id`.
- `services/state_machine/parsers/__init__.py :: PARSER_REGISTRY` and `models.py :: ParsedPoll/Slot` — register `parse_resy`; `parsers/opentable.py` is the template (coverage from request_params, ParseError matrix).
- `scripts/check_poll_success.py` — exit-code convention for the soak verdict; `tests/integration/test_poller_smoke.py` + `tests/integration/conftest.py` — container fixtures and the env-freeze workaround (read service config lazily!).
- `services/poller/config.py` — currently freezes env at import (logged in `.planning/deferred-items.md`); new Resy config must be read through functions.

### Established Patterns
- Async-only; all Redis via `redis.asyncio`; no `time.sleep`; Prometheus client already pinned; structlog redaction of secrets in `shared/telemetry.py`.
- Adapters never create their own HTTP clients (D-05); for Resy the analogous rule is "never create a browser outside `ContextPool`".

### Integration Points
- Poller: new `services/poller/sources/resy/{adapter,pool,fingerprints,canary,fixtures,README}.py`; `main.py` lifespan; `scheduler.py` dispatch/release; `seed_restaurants.py` Resy jobs (RESY_ENABLED).
- State machine: `parsers/resy.py` registered; no engine changes (SC5 proof = an integration test that a Resy raw message produces an event through the unchanged engine).
- Ops: `.env.example` Resy block (`RESY_ENABLED`, `RESY_API_BASE`, `RESY_API_KEY`, `RESY_ACCOUNTS_JSON`, `RESY_PROXY_URL`, `RESY_CONTEXTS`, `RESY_GLOBAL_RPM`, `RESY_BASELINE_INTERVAL_SECONDS`, `RESY_DATE_RANGE_DAYS`, `METRICS_PORT`), Makefile `make browsers`, `make soak`.

</code_context>

<specifics>
## Specific Ideas

- The README's Legal & Ethical Scraping section already promises the 80 req/min cap and 45 s floor; this phase makes both enforced in code and cites the enforcing functions from `services/poller/sources/resy/README.md`.
- "Simulate a 429 and watch the context recycle within one poll cycle" (SC3) should be a single integration test that reads like the demo.

</specifics>

<deferred>
## Deferred Ideas

- Proxy rotation / multiple proxies; automatic re-login when cookies expire (needs credentials; ToS-sensitive) — post-MVP.
- Weekly selector smoke test against live Resy — Phase 7 CI (needs accounts).
- Splitting the poller into per-source processes — only if Chromium memory forces it.

</deferred>
