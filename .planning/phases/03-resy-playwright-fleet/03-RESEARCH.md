# Phase 3: Resy & Playwright Fleet - Research

**Researched:** 2026-09-05
**Domain:** Headless-browser polling fleet (Playwright context pool + stealth + fingerprint rotation), Redis-enforced distributed rate limiting, soft-ban signature canary, Prometheus instrumentation, long-run memory/PID soak tooling
**Confidence:** HIGH for every library-API and in-repo claim (all executed or read this session); LOW for the Resy `/4/find` payload shape (no live calls permitted — `[ASSUMED]`, isolated to fixtures + one parser by design)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Tier-based cadence, jitter and backoff (POLL-02)
- **D-57:** `shared/redis_keys.py` gains `tier_interval_seconds(active_watches: int) -> int` returning 60 (>= 10 watches), 180 (3–9), 600 (0–2) — the literal POLL-02 tiers — and `effective_interval_seconds(source, active_watches, override)`: `min(tier, baseline[source])` floored by the per-source minimum. Baselines: OpenTable 90 s (`POLL_INTERVAL_SECONDS`, POLL-03 floor — watches can only speed polling up, never slow the heatmap data collection down), Resy 180 s default (`RESY_BASELINE_INTERVAL_SECONDS`) floored at 45 s (POLL-05). Jitter stays +/-15 % (`POLL_JITTER_FRACTION`).
- **D-58:** Active-watch counts are read from the Redis HASH `watch:count` (field `{source}:{restaurant_id}`, value = integer count of active watchlist entries) — written by Phase 5, read here with default 0. Admin tier override: HASH `tier:override` (field `{source}:{restaurant_id}`, value 1|2|3) wins over the computed tier when present (Phase 5 admin route writes it). Both keys live in `shared/redis_keys.py`.
- **D-59:** Exponential backoff on 429/503 (and on a canary ban): per-job key `backoff:{source}:{rid}` holding the current backoff seconds (TTL = 2x its value); next attempt = `min(interval * 2^n, 1800 s)`; reset (DEL) on the next successful poll. Backoff is applied in the poller release path as the ZSET score — never `asyncio.sleep`. The Phase 2 expedite flag (`sched:expedite:*`) is honoured *only* when no backoff is active.

#### Playwright context pool and fingerprints (POLL-04)
- **D-60:** `services/poller/sources/resy/pool.py :: ContextPool` — one `async_playwright()` Chromium `Browser`, `N = RESY_CONTEXTS` (default 4) `BrowserContext`s, acquisition via `asyncio.Semaphore(N)` + an `asyncio.Queue` of idle contexts (no custom pool framework). Each context is created with a fingerprint from `services/poller/sources/resy/fingerprints.py` (rotation table of `{user_agent, viewport, locale, timezone_id, device_scale_factor}` — >= 6 entries, chosen round-robin per context creation) and `tf-playwright-stealth` applied (`Stealth().apply_stealth_async(context)` — verify the exact 1.2.0 API in research). Context recycle triggers: canary ban, `pages_served >= 500`, age >= 2 h, or an unrecoverable Playwright error. Recycling closes the context and creates a fresh one with the next fingerprint and the next account's cookies.
- **D-61:** Sessions are pre-authenticated from env `RESY_ACCOUNTS_JSON` (JSON array of `{"email": "...", "cookies": ...}` where `cookies` is EITHER the `.env.example`/Phase 1 runbook shape — a `{name: value}` object, expanded to Playwright cookies with `domain=".resy.com"`, `path="/"`, `secure=true` — OR an explicit Playwright cookie list `[{"name","value","domain","path",...}]`; both are accepted and validated by a small pydantic model in `services/poller/sources/resy/accounts.py`), injected via `context.add_cookies(...)`; cookies exist only in context memory (never DB, never logs — `shared/telemetry.py` redaction covers `cookie`/`auth_token`/`x-resy-auth-token`). Accounts are assigned to contexts round-robin; with fewer accounts than contexts the accounts repeat. If `RESY_ACCOUNTS_JSON` is empty/unset the fleet starts in **anonymous mode** (contexts without cookies) and logs a `resy_anonymous_mode` warning once — the pool still runs so the stub-backed tests and the soak script work without secrets.
- **D-62:** Optional residential proxy via `RESY_PROXY_URL` (`http[s]://user:pass@host:port`) passed as Playwright `proxy=` at browser launch; unset = direct. No proxy rotation logic in this phase.
- **D-63:** Resy jobs enter `sched:polls` only when `RESY_ENABLED=true` (`scripts/seed_restaurants.py` enqueues `resy:{resy_venue_id}` for every restaurant that has one, in addition to the OpenTable job; default `RESY_ENABLED=false`). The poller's `poll_loop` dispatches by a `{source: adapter}` registry (replacing the `if source == "opentable"` branch) and the Resy adapter is only constructed when `RESY_ENABLED=true`, so an unconfigured deployment never launches Chromium.

#### Resy availability call, rate limiting (POLL-05)
- **D-64:** `services/poller/sources/resy/adapter.py :: ResyAdapter(AvailabilitySource)` polls via the context's `request` (Playwright `APIRequestContext`, which shares cookies, UA and TLS fingerprint with the context) — no HTML page loads: `GET {RESY_API_BASE}/4/find?lat=0&long=0&day={YYYY-MM-DD}&party_size={n}&venue_id={venue_id}` with headers `Authorization: ResyAPI api_key="{RESY_API_KEY}"`, `X-Resy-Auth-Token` (from the injected cookie/env), `X-Origin: https://resy.com`, `Accept: application/json`. `RESY_API_BASE` defaults to `https://api.resy.com` and is overridable so tests point at the local stub. One request per (date, party) pair; the date range and party matrix follow Phase 1 D-19 but the per-poll request count is bounded by the rate budget — the adapter polls `RESY_DATE_RANGE_DAYS` (default 3) x party sizes `[2]` by default so one poll = 3 requests. `raw_response` is an envelope `{"requests": [{"date": ..., "party_size": ..., "status": ..., "body": {...}}]}` so `request_params["party_sizes"]` is truthful (fixes the Phase 2 B-4 class of bug for Resy from day one) and `coverage` in the parser is derived from the envelope entries with status 200.
- **D-65:** Global cap enforced **at the scheduler before dispatch** (ARCHITECTURE Pattern): Lua/atomic `INCR rate:resy:{epoch_minute}` + `EXPIRE 90` returning the new count; if the count (plus the requests this poll will make) would exceed `RESY_GLOBAL_RPM` (default 80) the job is released back with `now + 5000 ms` (no sleep) and the budget is not consumed. Per-restaurant per-context floor: `SET rate:resy:ctx:{context_id}:{venue_id} 1 NX EX 45` — if it already exists the pool picks another idle context; if none is eligible the job is released with `now + 5000 ms`. The confirmation re-poll from Phase 2 counts against the same budget.
- **D-66:** Slot identity for Resy: `time_slot` = `HH:MM` of `slot.date.start` (venue-local), `seat_type` = `slot.config.type`, `booking_token` = `slot.config.token`; `services/state_machine/parsers/resy.py :: parse_resy` is registered in `PARSER_REGISTRY["resy"]`. Response shape is `[ASSUMED]` from public captures (`results.venues[].slots[] {date{start,end}, config{type,token}, size{min,max}}`) — fixtures carry the `TODO(spike)` marker like the OpenTable ones; an unparseable body is `ParseError` → UNKNOWN exactly as D-39.

#### Soft-ban canary and fleet health (POLL-06)
- **D-67:** `services/poller/sources/resy/canary.py :: ResponseSignature` = `(http_status, body_len_bucket, has_results_key, venues_count, has_slots_key)` computed per request. Rolling baseline per venue kept in Redis LIST `canary:resy:{venue_id}` (last 20 signatures, LPUSH+LTRIM). Ban verdict: HTTP 403/429 with a Resy challenge body, OR three consecutive `200` responses whose venues_count is 0 / `results` missing while the baseline majority had venues, OR body_len < 20 % of the baseline median. A ban increments the Prometheus counter `scrape_ban_total{source="resy",reason=...}`, publishes `polls.completed` with `status="banned"` (add `"banned"` to `PollCompleted.status` and to `poll_log.status` semantics — no migration needed, the column is TEXT), marks the context poisoned (recycle), and applies D-59 backoff to the job. `PollCompleted` also gains an optional `context_id: str | None` for Grafana per-context latency.
- **D-68:** If every context is poisoned within a 5-minute window the fleet sets `resy:paused 1 EX 900`; the scheduler skips Resy jobs while the key exists (releases them `+60 s`, no dispatch) and logs `resy_fleet_paused` at ERROR (Sentry hook is Phase 7). The state machine sees no raw messages during the pause, so slots stay in their last state (UNKNOWN via `polls.completed{status=banned}` per D-53).
- **D-69:** Prometheus metrics are defined once in `shared/metrics.py` (`prometheus_client` is already pinned): `scrape_ban_total`, `poll_latency_seconds{source}` histogram, `poll_total{source,status}` counter, `resy_context_recycles_total{reason}`, `resy_rate_budget_remaining` gauge, `playwright_contexts_active` gauge. The poller exposes them on `METRICS_PORT` (default 9101) via `prometheus_client.start_http_server` started inside `run()` — Phase 7 scrapes it.

#### Soak test tooling (PERF-05)
- **D-70:** `scripts/soak_playwright.py --duration 12h --sample-every 30s --venues 10 [--stub]` runs the pool against the stub (`--stub`) or real Resy (needs env), sampling the poller's RSS (`resource.getrusage` for self + `ps -o rss= -p <pid>` via `asyncio.create_subprocess_exec` for Chromium children), Chromium process count (`pgrep -f chrom` via subprocess), poll success rate from `poll_log`, and `playwright_contexts_active`; writes `logs/soak-<ts>.jsonl` and a final verdict: PASS iff RSS <= baseline + 20 %, Chromium PID count stable (max - min <= 2), success rate >= 99 %. Exit codes 0/1/2 like `check_poll_success.py`. A CI-sized variant (`--duration 90s --stub`) runs as an integration test. The 12-hour run itself is **pending-human** and documented in `docs/runbooks/perf05-soak.md` with a `STATUS: pending-human-run` banner.

#### Test strategy
- **D-71:** `tests/fakes/resy_stub.py` — a FastAPI app (FastAPI + uvicorn are already dependencies) serving `GET /4/find` from fixture JSON in `services/poller/sources/resy/fixtures.py`, with control endpoints `POST /__ctl/mode {normal|rate_limited|banned_empty|error_500}` and a hit log; integration tests start it with `uvicorn.Server` in-process on a random port and launch headless Chromium against it (`RESY_API_BASE=http://127.0.0.1:{port}`). Tests: pool acquires/recycles (page counter, ban), fingerprint rotation applies per context (assert `navigator.userAgent` via `context.new_page().evaluate`), stealth applied (`navigator.webdriver` is false/undefined), 45 s per-context floor and 80 rpm cap (drive the minute counter directly, no waiting), 429 → backoff score + recycle within one cycle (SC3), canary ban verdict, end-to-end Resy raw -> state machine event with no source branching (SC5), soak 90 s variant. Unit tests: tier math, backoff math, signature bucketing, parser matrix (including the D-64 envelope), `no_sleep` grep extended to the new package. Chromium is pre-installed on this machine (`playwright install chromium`); a `make browsers` target documents it and the tests **skip with a clear reason only if Chromium is genuinely absent** (environment guard, same as the Docker guard).

### Claude's Discretion
- Exact fingerprint table entries; structlog event names; whether `ContextPool` exposes an async context manager or explicit `acquire()/release()`.
- Exact stub fixture contents beyond the `[ASSUMED]` shape; how the stub simulates a Resy challenge page for the 403 path.
- How `services/poller/main.py` wires optional Resy start/stop (lifespan ordering, `browser.close()` in `finally`).

### Deferred Ideas (OUT OF SCOPE)
- Proxy rotation / multiple proxies; automatic re-login when cookies expire (needs credentials; ToS-sensitive) — post-MVP.
- Weekly selector smoke test against live Resy — Phase 7 CI (needs accounts).
- Splitting the poller into per-source processes — only if Chromium memory forces it.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| POLL-02 | Three tiers (60 s ≥10 watches / 3 min 3–9 / 10 min 1–2) with ±15 % jitter and exponential backoff on 429/503 | §Pattern 2 (tier + backoff in the release path), §Code Examples "Budget Lua" and "Backoff key", verified Redis `HGET`/`SET EX`/`DEL` semantics; verified that `APIRequestContext` **returns** a 429 rather than raising, so backoff is triggerable from `response.status` |
| POLL-04 | Playwright pool (1 browser, 4 contexts), pre-authenticated sessions, `tf-playwright-stealth`, fingerprint rotation, realistic request headers | §B-1..B-3 (Chromium revision, stealth API, fingerprint clobbering), §Pattern 3 (`ContextPool`), §Pattern 4 (coherent context-level stealth — verified `navigator.webdriver === undefined` with the fingerprint preserved), §B-9 + §Pattern 5 (the header set `APIRequestContext` actually emits, captured on the wire) |
| POLL-05 | Call `/4/find` directly (no HTML pages); ≤ 1 req / 45 s per restaurant per context; ≤ 80 req/min total | §Pattern 5 (`context.request.get` verified end to end against a local stub), §Pattern 6 (budget Lua executed against Redis 7.2.16: cost=3, cap=80 → 26 grants then refusal), verified `SET NX EX 45` returns `None` on the second attempt and does **not** slide the TTL |
| POLL-06 | Soft-ban canary on response-signature drift; alert on anomaly | §Pattern 7 (`ResponseSignature` computable purely from `APIResponse.status` / `.headers` / `.text()` — all verified), §Code Examples "canary LIST" (`LPUSH`+`LTRIM`+`LRANGE` executed), §B-7 (the `banned` status needs two more call sites than D-67 names) |
| PERF-05 | 12-hour soak: RSS ≤ baseline+20 %, stable Chromium PID count, success ≥ 99 % | §B-8 (`getrusage` is a high-water mark and cannot detect growth; `pgrep -f chrom` over-matches), §Pattern 8 (verified process tree + measured RSS at 4 contexts vs 4 pages), §Pitfall 1 (zombie leak reproduced: 6 orphaned processes survived the Python process) |
</phase_requirements>

---

## Summary

Every dependency this phase needs is already pinned and installed; **no new package is introduced**, so the package-legitimacy surface is zero. What is *not* already true is the browser binary: `playwright==1.58.0` pins Chromium revision **1208**, and the machine carried only revision **1223** (installed by some newer Playwright), so the very first `chromium.launch()` failed. That is fixed and verified (§B-1), and it is the single highest-value thing `make browsers` must encode.

The three findings that most change the plan are all about *what the locked decisions assume versus what the pinned libraries actually do*. First, `tf-playwright-stealth==1.2.0` has no `Stealth` class at all — its public surface is `stealth_async(page, config)`, it operates **per page, not per context**, and, worse, it silently overwrites the context's fingerprint with a randomly generated and internally incoherent one (Chrome 96 on Windows, `accept-encoding: compres`, `referer: http://www.hotbot.com`, a Qualcomm Adreno GPU under a Windows UA). Applying it as shipped would make the fleet *more* detectable than doing nothing, and would defeat D-60's fingerprint rotation outright. The verified replacement — build the stealth `opts` from *our* fingerprint and install the JS patches once per context with `context.add_init_script(...)` — is strictly better, satisfies D-60's intent exactly, and was measured working (`navigator.webdriver === undefined`, UA/platform/languages/hardwareConcurrency/deviceMemory/WebGL all coherent, applying to every page in the context). Second, `APIRequestContext` does **not** share Chromium's network stack: the raw bytes on the wire are the Playwright Node driver's, with lowercase header names, `accept-encoding: gzip,deflate,br` (no `zstd`), no `sec-ch-*`, no `Sec-Fetch-*` and no `Accept-Language`. D-64's "shares … TLS fingerprint with the context" is false, and POLL-04's "realistic request headers" therefore has to be satisfied explicitly via per-context `extra_http_headers` — which was verified to flow through into `context.request` calls. Third, the Resy seed data cannot produce a job: all 31 non-null `resy_venue_id` values in `scripts/seed/restaurants.yml` are **slugs**, not numeric ids, so `poll_loop`'s `int(rid_str)` raises and `AvailabilityRaw.restaurant_id: int` refuses them; and a second `restaurants` row for the same restaurant violates `UNIQUE(slug)`.

The good news dominates the risk. Contexts are nearly free (2–7 ms to create, 3 ms to close, no extra OS process); **pages** are what cost memory (455 MB with 4 empty contexts versus 1 168 MB with 4 pages open). D-64's "no HTML page loads" is therefore not just a politeness choice, it is the single design decision that makes PERF-05 achievable, and the research recommends keeping it despite the TLS caveat. A full context recycle measured ~5 ms, so SC3's "recycle within one poll cycle" is trivially satisfiable. The zombie-process failure mode was reproduced deliberately (cancel a task without a `finally` and six Chromium/node processes outlive the interpreter) and the mitigation — `await asyncio.shield(browser.close())` in `finally` — was verified to leave zero. Redis 7.2.16 executed the whole rate-limit and canary primitive set on the first try. `prometheus_client==0.25.0`'s `start_http_server` returns `(WSGIServer, Thread)` so it is cleanly shutdownable, and tests can read the registry with `get_sample_value` without any HTTP. And the entire D-71 test shape — in-process `uvicorn.Server` on an ephemeral port plus real headless Chromium — runs green in **2.94 s**.

**Primary recommendation:** Keep every locked decision's *intent*; encode the nine corrections in §Blocking Corrections verbatim. Wave 0 must (a) add `make browsers` running `uv run playwright install chromium` and a `_chromium_available()` guard that compares the installed revision against `playwright/driver/package/browsers.json`, (b) mint numeric placeholder Resy venue ids in `restaurants.yml` exactly as Phase 1 minted `opentable_rid: 900000001`, and (c) extend `shared/telemetry.py`'s redactor before a single cookie is handled.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tier cadence / jitter / backoff arithmetic | Pure functions in `shared/redis_keys.py` | — | Must be unit-testable with no clock and no IO, exactly as Phase 2's engine is (D-49 precedent) |
| Global 80 rpm budget + 45 s per-context floor | Redis (server-side Lua / `SET NX EX`) | Poller scheduler | ARCHITECTURE.md §5: "rate limits enforced at the poll scheduler, not at the Playwright worker — the worker is too late to be polite". Atomicity must live in Redis, not in Python |
| Browser/context lifecycle, fingerprints, stealth | Poller process (`ContextPool`) | Chromium child processes | One browser per process; contexts are the isolation unit. Nothing outside `ContextPool` may construct a browser (the Resy analogue of D-05) |
| The HTTP call to `/4/find` | Playwright **Node driver** (not Chromium) | — | Verified on the wire (§B-9). This tier owns headers and TLS; Chromium owns only the cookie jar and the UA default |
| Response-signature canary verdict | Pure function in `canary.py` | Redis LIST (rolling baseline) | Verdict must be replayable from a signature list in a unit test; Redis only stores the window |
| Ban → recycle → backoff reaction | Poller scheduler + `ContextPool` | Redis (`backoff:*`, `resy:paused`) | Reaction is scheduling, so it belongs where the ZSET score is written — never `asyncio.sleep` |
| Slot normalisation (Resy → `ParsedPoll`) | `services/state_machine/parsers/resy.py` | `PARSER_REGISTRY` | Phase 2 built the registry precisely so Phase 3 adds one entry and touches no engine code |
| Metric definition | `shared/metrics.py` (module-level, once) | Poller process (`start_http_server`) | A single definition site prevents `Duplicated timeseries in CollectorRegistry` (§Pitfall 6) |
| RSS / PID sampling | `scripts/soak_playwright.py` (out-of-process `ps`) | — | Must observe the *whole* process tree; in-process `getrusage` cannot see Chromium children (§B-8) |

---

## Project Constraints (from CLAUDE.md and CI)

`./CLAUDE.md` embeds the stack-research document rather than a directive list; the enforceable directives live in `.ruff.toml`, `pyproject.toml [tool.mypy]`, `Makefile`, and `.github/workflows/lint.yml`. All were read this session.

| Constraint | Source | Enforcement / note for this phase |
|------------|--------|-----------------------------------|
| No `import requests` / `from requests ` in `services/`, `shared/` | `.github/workflows/lint.yml:18-20` — `! grep -rn "^import requests\|^from requests " services/ shared/` [VERIFIED: .github/workflows/lint.yml:18-20] | Not at risk — Playwright is used, not `requests` |
| No `time.sleep(` in `services/`, `shared/` | `.github/workflows/lint.yml:21-23` — `! grep -rn "time\.sleep(" services/ shared/` [VERIFIED] | **At risk**: the 45 s floor and the 80 rpm cap invite a sleep. Both must be release-path scores (D-59, D-65) |
| No sync redis import | `.github/workflows/lint.yml:24-26` — `! grep -rEn "^import redis$\|^from redis import " services/ shared/` [VERIFIED] | `import redis.asyncio as redis` passes; `import redis` alone does not |
| `ruff check .` clean, `line-length = 120`, `select = ["E","F","W","I","UP","ASYNC"]` | `.ruff.toml:1-6` — verbatim: `line-length = 120` / `target-version = "py312"` / `select = ["E", "F", "W", "I", "UP", "ASYNC"]` [VERIFIED: .ruff.toml:1-6] | `ASYNC` rules will flag blocking calls in async defs; `scripts/**` is exempt from `ASYNC240` only |
| `mypy shared/ services/` clean under `strict = true`, `python_version = "3.12"`, `ignore_missing_imports = true` | `pyproject.toml:52-55` — verbatim: `[tool.mypy]` / `python_version = "3.12"` / `strict = true` / `ignore_missing_imports = true` [VERIFIED: pyproject.toml:52-55] | Playwright ships `py.typed`; `playwright_stealth` does **not** — see §Pitfall 7 |
| Every Redis key pattern and TTL declared in `shared/redis_keys.py` | D-18, D-42, D-57, D-58 | New keys: `rate:resy:{minute}`, `rate:resy:ctx:{ctx}:{venue}`, `canary:resy:{venue}`, `backoff:{source}:{rid}`, `resy:paused`, `watch:count`, `tier:override` |
| Every Kafka message schema declared in `shared/events.py` | D-06 | `PollCompleted.status` gains `"banned"`; `context_id: str \| None = None` added |
| No two-command `SETNX` + `EXPIRE` anywhere | `tests/unit/test_no_setnx_expire_pairs.py` scans `("services", "shared", "scripts")` | The 45 s floor MUST be `SET … NX EX 45` (verified working); the minute budget MUST be one Lua script |

---

## Blocking Corrections to Locked Decisions

> These are not alternatives to locked decisions — they are defects in the *literal wording* of locked decisions that were reproduced as hard runtime errors or verbatim source contradictions this session. The planner MUST encode the corrected form in PLAN.md tasks; the intent of each decision is preserved in every case.

### B-1 — The installed Chromium is the wrong revision for `playwright==1.58.0` (D-71)

D-71 states *"Chromium is pre-installed on this machine (`playwright install chromium`)"*. It was not — the cache held revision **1223**, installed by a newer Playwright, while 1.58.0 pins **1208**:

```
playwright._impl._errors.Error: BrowserType.launch: Executable doesn't exist at
/Users/aryanahuja/Library/Caches/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-mac-arm64/chrome-headless-shell
╔════════════════════════════════════════════════════════════╗
║ Looks like Playwright was just installed or updated.       ║
║ Please run the following command to download new browsers: ║
║     playwright install                                     ║
╚════════════════════════════════════════════════════════════╝
```
[VERIFIED: executed 2026-09-05 in `/Users/aryanahuja/projects/mise`]

The pinned revision is declared in the driver bundle:

```
chromium 1208 installByDefault= True
chromium-headless-shell 1208 installByDefault= True
```
[VERIFIED: `.venv/lib/python3.12/site-packages/playwright/driver/package/browsers.json`, read this session]

**Correction.** `uv run playwright install chromium` is a **required Wave 0 task**, not documentation. It took 6.0 s and produced `chromium-1208` (330 MB) + `chromium_headless_shell-1208` (187 MB); after it, launch succeeded in 1.38 s cold. `make browsers` must run it, and D-71's environment guard must compare the installed directory against the driver's declared revision, not merely glob for "a chromium":

```python
rev = next(b["revision"] for b in json.loads(
    (Path(playwright.__file__).parent / "driver/package/browsers.json").read_text()
)["browsers"] if b["name"] == "chromium")
available = (Path.home() / "Library/Caches/ms-playwright" / f"chromium-{rev}").exists()
```
A glob-based guard would have found `chromium-1223` and reported "available" while every launch failed.

### B-2 — `Stealth().apply_stealth_async(context)` does not exist in `tf-playwright-stealth==1.2.0` (D-60)

```
ImportError: cannot import name 'Stealth' from 'playwright_stealth'
(/Users/…/site-packages/playwright_stealth/__init__.py). Did you mean: 'stealth'?
public: ['StealthConfig', 'core', 'properties', 'stealth', 'stealth_async', 'stealth_sync']
```
[VERIFIED: executed 2026-09-05]

The real signature is `stealth_async(page: Page, config: StealthConfig = None)` — it takes a **Page**, not a BrowserContext, and does not propagate:

```
C2 post-stealth navigator.webdriver: None          # the page stealth was applied to
C10 second page in same ctx navigator.webdriver: True   # a sibling page in the SAME context
```
[VERIFIED: executed against `channel="chromium"` headless, 2026-09-05]

**Correction.** Apply the stealth JS **once per context** with `BrowserContext.add_init_script(...)` (verified to cover every page in the context, including pages created later — see §Pattern 4). D-60's stated intent (per-context stealth) is preserved; only the call changes.

### B-3 — `tf-playwright-stealth`'s own fingerprint is random, incoherent, and clobbers D-60's rotation table (D-60)

`stealth_async` does two things: `page.set_extra_http_headers(properties.as_dict()["header"])` and `page.add_init_script(combine_scripts(...))` [VERIFIED: `playwright_stealth/stealth.py:36-43`, read this session]. Both are driven by a `Properties()` object that is regenerated at random on every call:

```
0 Mozilla/5.0 (Windows NT 10.0) … | haw,*;q=0.5   | http://odiasearch.com  | {'vendor': 'Qualcomm Inc.', 'renderer': 'Qualcomm Adreno OpenGL Engine'}
1 Mozilla/5.0 (Windows NT 10.0) … | sk,*;q=0.5    | http://www.draze.com   | {'vendor': 'Qualcomm Inc.', 'renderer': 'Qualcomm Adreno OpenGL Engine'}
2 Mozilla/5.0 (Macintosh; Intel …| en-IL,*;q=0.5 | http://www.polymeta.com| {'vendor': 'AMD', 'renderer': 'AMD Radeon Pro 5600M OpenGL Engine'}
```
and its default header block contains `"accept-encoding": "compres"` (not a valid token), `"referer": "http://www.hotbot.com"`, and `Chrome/96.0.4664.45` — a 2021 build. [VERIFIED: `Properties(browser_type=BrowserType.CHROME).as_dict()`, executed three times, 2026-09-05]

Applied as shipped, it overwrote a macOS Chrome 140 context with a Linux identity while the HTTP `User-Agent` header still said macOS:

```
C3 post-stealth navigator.userAgent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)
C4 post-stealth navigator.platform: Linux x86_x64      # note: not a real Chrome value
C5 post-stealth navigator.languages: ['mwl', '*']      # Mirandese
C9 headers the stub saw:  Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) …
```
[VERIFIED: executed 2026-09-05]

A JS/HTTP UA mismatch plus `navigator.platform === "Linux x86_x64"` are, individually, harder bot signals than `navigator.webdriver`. Additionally, `StealthConfig`'s `vendor`, `renderer`, `nav_user_agent`, `nav_platform`, `languages`, `nav_vendor` and `run_on_insecure_origins` fields are **dead**: every shipped script reads `opts.*` (the `Properties` dict), and `_stealth_config.py` never references `self.vendor`/`self.renderer`/`self.nav_user_agent`/`self.nav_platform`/`self.languages`/`self.nav_vendor`. [VERIFIED: `grep -rn "self\.vendor\|self\.renderer\|self\.nav_user_agent\|self\.nav_platform\|self\.languages\|self\.nav_vendor" core/_stealth_config.py` → **no matches**; `grep -rn "opts\." js/` → 17 matches, executed this session]

**Correction.** Do not call `stealth_async` and do not use `StealthConfig` for fingerprint values. Build the `opts` object from `fingerprints.py` and compose the script list yourself from `playwright_stealth.core._stealth_config.SCRIPTS` (§Pattern 4). Verified result on a real origin: `navigator.webdriver = None`, UA/platform/languages/`hardwareConcurrency`/`deviceMemory`/WebGL vendor+renderer all match the chosen fingerprint, and the patch applies to a second page created afterwards in the same context.

### B-4 — Every `resy_venue_id` in the seed file is a slug, so no Resy job can exist (D-63, D-64)

```
total entries: 55
resy_venue_id non-null: 31
numeric resy_venue_id: 0
sample non-numeric: ['carbone-new-york-new-york', 'lilia-brooklyn', 'don-angie-new-york', 'rezdora-new-york', 'via-carota-new-york']
```
[VERIFIED: parsed `scripts/seed/restaurants.yml` this session]

Verbatim from the file: `    resy_venue_id: "carbone-new-york-new-york"` [VERIFIED: scripts/seed/restaurants.yml:55] and `    resy_venue_id: "lilia-brooklyn"` [VERIFIED: scripts/seed/restaurants.yml:64].

D-63's job descriptor `resy:{resy_venue_id}` therefore fails at three separate points, all reproduced:

```
poll_loop int(rid_str)               -> ValueError invalid literal for int() with base 10: 'carbone-new-york-new-york'
AvailabilityRaw(restaurant_id=slug)  -> ValidationError ['restaurant_id', "Input should be a valid integer, unable to parse string as an integer"]
```
[VERIFIED: executed 2026-09-05]

The failure is silent-but-permanent: `poll_loop` logs `invalid_restaurant_id` and `continue`s **without releasing the job**, so it stays in `sched:polls:inflight` until the reaper re-enqueues it, forever. Verbatim from the source:

```python
        source, rid_str = parts
        try:
            restaurant_id = int(rid_str)
        except ValueError:
            log.warning("invalid_restaurant_id", job=job)
            continue
```
[VERIFIED: services/poller/scheduler.py:68-73]

Resy's own `/4/find` also takes a **numeric** `venue_id`, not a slug [CITED: https://github.com/Alkaar/resy-booking-bot/blob/master/src/main/scala/com/resy/ResyApi.scala — `"lat" -> "0", "long" -> "0", "day" -> date, "party_size" -> partySize.toString, "venue_id" -> venueId.toString`].

**Correction.** Mint numeric placeholder Resy venue ids in `restaurants.yml` exactly as Phase 1 minted OpenTable ones (`opentable_rid: 900000001  # TODO(01-05 spike): replace with live rid from OpenTable DevTools` [VERIFIED: scripts/seed/restaurants.yml:54]). Add `resy_venue_id_numeric: 800000001  # TODO(03 spike): replace with the live numeric venue_id from Resy DevTools`, keep the existing slug under a renamed `resy_slug` key for the human-capture runbook, and seed the job from the numeric field. **Do not widen `restaurant_id` to `str`** — that would break `AvailabilityRaw`, `PollCompleted`, `AvailabilityEvent`, `poll_log.restaurant_id` (`BigInteger`) and every committed golden replay file, i.e. all of Phase 2.

### B-5 — Seeding a second `restaurants` row for Resy violates `UNIQUE(slug)` (D-63)

`seed_restaurants.py` inserts exactly **one** row per YAML entry and prefers OpenTable, so the Resy branch is currently unreachable:

```python
                if rest.get("opentable_rid") is not None:
                    source = "opentable"
                    platform_id = str(rest["opentable_rid"])
                elif rest.get("resy_venue_id") is not None:
                    source = "resy"
                    platform_id = str(rest["resy_venue_id"])
```
[VERIFIED: scripts/seed_restaurants.py:55-60]

D-63 requires a Resy job *"in addition to the OpenTable job"*, which means a second row with `source='resy'`. That collides:

```
ERROR:  duplicate key value violates unique constraint "restaurants_slug_key"
DETAIL:  Key (slug)=(carbone) already exists.
```
[VERIFIED: reproduced against `postgres:16-alpine` with the schema from migration 0003, executed 2026-09-05]

The constraint is doubled in the migration: `sa.Column("slug", sa.Text, nullable=False, unique=True)` [VERIFIED: migrations/versions/0003_create_restaurants.py:18] and `op.create_index("ix_restaurants_slug", "restaurants", ["slug"], unique=True)` [VERIFIED: migrations/versions/0003_create_restaurants.py:38].

**Correction.** Give the Resy row a distinct slug (`f"{slug}-resy"`) in the seed script. Do **not** drop or widen the unique index — Phase 6's public URLs are slug-keyed and a `(source, slug)` composite would let two rows share a public URL. Note in `services/poller/sources/resy/README.md` that the `(source, platform_id)` join key (D-52) is what Phase 4/5/6 must use, not the slug.

### B-6 — `shared/telemetry.py` does **not** redact cookies, auth tokens, or the proxy URL (D-61)

D-61 asserts *"`shared/telemetry.py` redaction covers `cookie`/`auth_token`/`x-resy-auth-token`"*. The redactor matches only four exact key names:

```python
    _SECRET_KEYS = {
        "TWILIO_AUTH_TOKEN",
        "HMAC_MGMT_SECRET_V1",
        "VAPID_PRIVATE_KEY",
        "RESY_ACCOUNTS_JSON",
    }
```
[VERIFIED: shared/telemetry.py:23-28]

Executed against a representative event dict:

```
cookie                     -> auth_token=SECRET
auth_token                 -> SECRET
x-resy-auth-token          -> SECRET
authorization              -> ResyAPI api_key="SECRET"
RESY_API_KEY               -> SECRET
RESY_PROXY_URL             -> http://user:pass@proxy:8080
RESY_ACCOUNTS_JSON         -> [REDACTED]
RESY_ACCOUNT_1_PASSWORD    -> [REDACTED]
```
[VERIFIED: executed 2026-09-05 — six of eight secret-bearing keys leak in full, including the proxy URL with embedded credentials]

**Correction.** Extend `_redact_secrets` **before any cookie-handling code is written** (Wave 0): add case-insensitive matching for `cookie`, `cookies`, `auth_token`, `x-resy-auth-token`, `authorization`, `set-cookie`, plus exact `RESY_API_KEY` and `RESY_PROXY_URL`. PITFALLS.md §Threats already demands a scrubber for *"`cookie`, `authorization`, `x-auth` headers"*. Extend `tests/unit/test_telemetry_redaction.py` with each new key.

### B-7 — Adding `"banned"` to the Literal is not sufficient; two consumers hard-code the old tuple (D-67)

Today the field rejects it and rejects the new one:

```
PollCompleted(status='banned')   -> ValidationError ['status', "Input should be 'success', 'error' or 'timeout'"]
PollCompleted(context_id='c0')   -> ValidationError ['context_id', "Extra inputs are not permitted"]
```
[VERIFIED: executed 2026-09-05 against `shared/events.py:57-71`, whose field is declared verbatim as `    status: Literal["success", "error", "timeout"]` — shared/events.py:65]

Widening the Literal alone leaves a **silent** bug: both consumers treat anything that is not `error`/`timeout` as a success and return without marking the restaurant UNKNOWN.

```python
        if completed.status not in ("error", "timeout"):
```
[VERIFIED: services/state_machine/consumer.py:189]

```python
    if completed.status in ("error", "timeout"):
        await engine.mark_unknown(completed.restaurant_id, completed.polled_at_epoch_ms)
```
[VERIFIED: scripts/replay_raw.py:107-109]

**Correction.** Invert both checks to `if completed.status == "success": return` / `if completed.status != "success":` so every present and future non-success status marks UNKNOWN, and note it in `services/state_machine/README.md`. This is a **two-line consumer change and does not violate SC5** — SC5 forbids *source-specific branching in the diff logic*, and `DiffEngine` is untouched. Restate the SC5 proof accordingly: the test must assert that `services/state_machine/engine.py` contains no occurrence of `"resy"` and that `PARSER_REGISTRY` gained exactly one entry — **not** that `services/state_machine/` is byte-identical.

Two things D-67 gets right and that were confirmed: `poll_log.status` is `sa.Column("status", sa.Text, nullable=False)` with no CHECK constraint [VERIFIED: migrations/versions/0007_create_poll_log_hypertable.py:19], so **no migration is needed**; and the committed golden replay files contain zero `polls.completed` records (`grep -c "polls.completed" tests/fixtures/raw_streams/*.events.jsonl` → `0` for all three), so widening `PollCompleted` **cannot** perturb byte-identical replay (STATE-06). [VERIFIED: executed 2026-09-05]

### B-8 — `resource.getrusage` cannot detect a leak, and `pgrep -f chrom` counts the developer's own browser (D-70)

`ru_maxrss` is a **high-water mark** — it never decreases, so "RSS ≤ baseline + 20 %" computed from it is unfalsifiable after the first spike. It also reports in different units per platform, and `RUSAGE_CHILDREN` reports the max of any single *reaped* child, not a sum:

```
macOS: RUSAGE_SELF ru_maxrss raw: 30474240        (bytes)
Linux: ru_maxrss raw: 12332  /  VmHWM: 8992 kB    (KiB)
macOS: RUSAGE_CHILDREN ru_maxrss raw (end): 230162432
```
[VERIFIED: executed on darwin/arm64 and inside `python:3.12-slim` via Docker, 2026-09-05]

`ps -o rss=` reports **KiB on both platforms** and gives *current* RSS:

```
ps rss for a process holding 200MiB: 222880 -> KiB
ru_maxrss: 228278272 = 228.3 MB (bytes on macOS)
```
[VERIFIED: executed 2026-09-05]

`pgrep -f chrom` over-matches badly. With **no** Playwright browser running, the developer machine already answered 4:

```
[baseline] self ru_maxrss=30.6 MB  pgrep(ms-playwright)=0  pgrep(chromium-ish)=4
[after launch] …                   pgrep(ms-playwright)=6  pgrep(chromium-ish)=6
```
[VERIFIED: executed 2026-09-05] — the launched binary is literally named `Google Chrome for Testing.app`, so any name-based pattern collides with a real Chrome.

**Correction.** (1) Sample **current** RSS with `ps -o rss= -p <pid>` (KiB, both platforms) for the poller pid and every Chromium pid; use `resource.getrusage` only as a diagnostic annotation in the JSONL, never in the verdict. (2) Match on the path token `ms-playwright`, not on `chrom` — verified `pgrep -f ms-playwright` = 0 at baseline, 6 with a browser, 11 with four pages, 0 after `browser.close()`. (3) `ps` and `pgrep` are **absent** from `python:3.12-slim` (`ps: MISSING`, `pgrep: MISSING` [VERIFIED: executed in Docker, 2026-09-05]) — the soak script needs a `/proc/<pid>/statm` + `/proc/*/cmdline` fallback, or the CI image must install `procps`.

### B-9 — `APIRequestContext` does not share Chromium's TLS/HTTP fingerprint (D-64)

D-64 states the context request *"shares cookies, UA and TLS fingerprint with the context"*. Cookies and UA: true. TLS/HTTP fingerprint: **false**. Raw bytes captured by a local socket server:

```
=== (a) context.request.get ===
GET /4/find?venue_id=1 HTTP/1.1
user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) … Chrome/140.0.0.0 Safari/537.36
accept: application/json
accept-encoding: gzip,deflate,br
Authorization: ResyAPI api_key="k"
X-Origin: https://resy.com
Host: 127.0.0.1:55026
Connection: keep-alive

=== (c) page.goto (real Chromium network stack) ===
GET /nav HTTP/1.1
Host: 127.0.0.1:55026
Connection: keep-alive
sec-ch-ua: "Not:A-Brand";v="99", "HeadlessChrome";v="145", "Chromium";v="145"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "macOS"
Upgrade-Insecure-Requests: 1
User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) … Chrome/140.0.0.0 Safari/537.36
Accept-Language: en-US
Accept: text/html,application/xhtml+xml,…
Sec-Fetch-Site: none
…
Accept-Encoding: gzip, deflate, br, zstd
```
[VERIFIED: raw request bytes captured with `asyncio.start_server`, executed 2026-09-05]

The differences are systematic: lowercase header names, header **order**, `accept-encoding: gzip,deflate,br` without spaces and without `zstd`, no `sec-ch-*`, no `Sec-Fetch-*`, no `Accept-Language`. This is a Node.js client, not Chrome — so the JA3/JA4 will be Node's.

**Correction.** (a) Delete the "TLS fingerprint" claim from the code comments and the README. (b) POLL-04's *"realistic request headers"* must be met **explicitly**: set the full realistic set per context via `extra_http_headers`, verified to flow into `context.request` calls:

```
=== (d) context.request.get WITH context extra_http_headers ===
…
Accept-Language: en-US,en;q=0.9
sec-ch-ua: "Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"
sec-ch-ua-mobile: ?0
sec-ch-ua-platform: "macOS"
Sec-Fetch-Dest: empty
Sec-Fetch-Mode: cors
Sec-Fetch-Site: same-site
Origin: https://resy.com
Referer: https://resy.com/
Authorization: ResyAPI api_key="k"
```
[VERIFIED: executed 2026-09-05]

Each fingerprint row must therefore carry a matching `sec-ch-ua` / `sec-ch-ua-platform` / `Accept-Language` triple, not just a UA string — an inconsistent triple is worse than none. **Keep D-64's no-page-loads design** regardless: §Pattern 8 shows pages cost ~178 MB each, which would forfeit PERF-05. The residual TLS risk is recorded as Open Question Q1.

---

## Standard Stack

### Core — all already pinned and installed, zero new packages

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `playwright` | 1.58.0 | Chromium fleet, `BrowserContext` isolation, `APIRequestContext` | Ships `py.typed` — `mypy --strict` passes with no stubs and no ignores (verified). Only realistic option for a JS-capable, cookie-sharing HTTP client |
| `tf-playwright-stealth` | 1.2.0 (import `playwright_stealth`) | Source of the `navigator.*` patch scripts | Use the **`SCRIPTS` dict**, not `stealth_async` (§B-2, §B-3) |
| `redis` (asyncio) | 7.4.0 | Rate budget, canary window, backoff, pause flag | Already the project's only Redis client; server is `redis:7.2-alpine` → **7.2.16** verified live |
| `prometheus-client` | 0.25.0 | `scrape_ban_total` + fleet metrics | `start_http_server` returns `(WSGIServer, Thread)` in 0.25 → cleanly shutdownable (verified) |
| `fastapi` / `uvicorn[standard]` | 0.136.0 / 0.44.0 | The `resy_stub.py` fake in tests | Already dependencies; `uvicorn.Server` runs in-process on an ephemeral port |
| `pydantic` | 2.13.3 | `RESY_ACCOUNTS_JSON` validation, event schemas | `extra="forbid"` already catches the `context_id` addition (verified) |
| `aiokafka` | 0.13.0 | Unchanged publish path | No change needed for Resy |
| Python | 3.12.13 | — | `requires-python = ">=3.12,<3.13"` |

[VERIFIED: `importlib.metadata.version` for all of the above against `/Users/aryanahuja/projects/mise/.venv`, executed 2026-09-05]

### Supporting (test tier)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` / `pytest-asyncio` | 9.0.3 / 1.3.0 | `asyncio_mode = "auto"` | Module-scoped async fixtures need `pytest_asyncio.fixture(..., loop_scope=)` — see §Pitfall 8 |
| `testcontainers` | 4.14.2 | Redis 7.2 / Kafka / Timescale | Only for the tests that genuinely need a container |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `context.request.get` (D-64) | In-page `fetch()` from a page navigated to `https://resy.com` | Gets Chromium's real TLS + native header order + client hints + `Sec-Fetch-*` for free (verified). Costs ~178 MB per open page and one extra OS process each (verified) — forfeits PERF-05. **Rejected**; recorded as Q1 |
| `headless=True` (headless shell) | `headless=True, channel="chromium"` | The headless shell leaks `"HeadlessChrome";v="145"` in `sec-ch-ua` and `userAgentData.brands`; `channel="chromium"` reports `"Chromium";v="145"` instead (verified). **Recommend `channel="chromium"`** — the full browser, ~equal launch time (0.25 s warm) |
| `stealth_async(page)` | Hand-composed `context.add_init_script` | The library form is per-page and randomises the fingerprint (§B-3). **Rejected** |
| One Lua budget script (D-65) | `SET NX EX 0` + `INCRBY` | Two round trips, and `INCRBY` can land on a key that expired between them, leaving a counter with no TTL. Verified `INCR` alone leaves `ttl == -1` — a permanent key. **Rejected** |
| `psutil` for RSS/PID | `ps` / `pgrep` via `asyncio.create_subprocess_exec` | `psutil` is not a dependency and would need adding; PITFALLS.md §Pitfall 1 suggests it, but subprocess works and adds nothing to the lockfile. **Keep subprocess**, with the `/proc` fallback from §B-8 |

**Installation:** none.

```bash
# Required Wave 0 step — this is NOT a no-op on this machine (see B-1)
uv run playwright install chromium
```

**Version verification:**
```
playwright==1.58.0        tf-playwright-stealth==1.2.0   redis==7.4.0
aiokafka==0.13.0          prometheus-client==0.25.0      fastapi==0.136.0
uvicorn==0.44.0           pydantic==2.13.3               pytest==9.0.3
pytest-asyncio==1.3.0     testcontainers==4.14.2         python 3.12.13
```
[VERIFIED: `importlib.metadata`, executed 2026-09-05] — `uv run playwright --version` → `Version 1.58.0`.

---

## Package Legitimacy Audit

**This phase installs no new packages.** Every library named above is already present in `pyproject.toml` and resolved in `uv.lock`, and was audited at Phase 1 planning time.

| Package | Registry | Installed | Source Repo | Verdict | Disposition |
|---------|----------|-----------|-------------|---------|-------------|
| `playwright` | PyPI | 1.58.0 (pinned, in lockfile) | github.com/microsoft/playwright-python | OK | Pre-existing — no install task |
| `tf-playwright-stealth` | PyPI | 1.2.0 (pinned, in lockfile) | fork of AtuboDad/playwright_stealth | OK | Pre-existing — no install task |
| `redis`, `aiokafka`, `prometheus-client`, `fastapi`, `uvicorn`, `pydantic` | PyPI | pinned, in lockfile | — | OK | Pre-existing |

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS]:** none.

**Non-package supply-chain item that DOES need a gate:** `uv run playwright install chromium` downloads ~253 MB of browser binaries from `cdn.playwright.dev` at Wave 0. This is a network fetch of executable content and should be an explicit, reviewable task rather than a side effect of a test run. Recorded as the `make browsers` target.

---

## Architecture Patterns

### System Architecture Diagram

```
                     ┌──────────────────────────── poller process ───────────────────────────────┐
                     │                                                                            │
 Redis ZSET          │   ┌─────────────┐   job "resy:800000001"    ┌──────────────────────────┐   │
 sched:polls  ──────────►│  poll_loop  │──────────────────────────►│  SOURCE REGISTRY         │   │
   (claim Lua)       │   │  (N worker  │                           │  {"opentable": …,        │   │
                     │   │   tasks)    │                           │   "resy": ResyAdapter}   │   │
                     │   └──────┬──────┘                           └────────────┬─────────────┘   │
                     │          │                                               │                 │
                     │   ┌──────▼──────────────── PRE-DISPATCH GATES ───────────▼──────────────┐  │
                     │   │  1. resy:paused EXISTS?     ── yes ─► release now+60s, no dispatch  │  │
                     │   │  2. backoff:{src}:{rid}?    ── yes ─► release now+backoff           │  │
                     │   │  3. budget Lua: INCRBY rate:resy:{minute} by cost, cap 80           │  │
                     │   │        └─ refused ─────────────────► release now+5000ms             │  │
                     │   │  4. ContextPool.acquire(venue_id)  (Semaphore(N) + idle Queue)      │  │
                     │   │        └─ SET rate:resy:ctx:{ctx}:{venue} 1 NX EX 45                │  │
                     │   │             └─ exists on every idle ctx ─► release now+5000ms       │  │
                     │   └───────────────────────────────┬─────────────────────────────────────┘  │
                     │                                   │ granted                                │
                     │   ┌───────────────────────────────▼─────────────────────────────────────┐  │
                     │   │  ContextPool: 1 Browser (channel="chromium", headless)              │  │
                     │   │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                    │  │
                     │   │  │ ctx 0   │ │ ctx 1   │ │ ctx 2   │ │ ctx 3   │  fingerprint i%6   │  │
                     │   │  │ UA/vp/  │ │         │ │         │ │         │  cookies acct j%K  │  │
                     │   │  │ tz/hdrs │ │         │ │         │ │         │  add_init_script   │  │
                     │   │  │ .request│ │         │ │         │ │         │  (stealth, once)   │  │
                     │   │  └────┬────┘ └─────────┘ └─────────┘ └─────────┘                    │  │
                     │   └───────┼─────────────────────────────────────────────────────────────┘  │
                     │           │ GET /4/find × (dates × parties)                                 │
                     │           │  (Playwright NODE driver HTTP — not Chromium's stack, B-9)      │
                     │           ▼                                                                 │
                     │   ┌───────────────┐  APIResponse(.status,.headers,.text())                  │
                     │   │  ResyAdapter  │──────┬────────────────────────────────────┐             │
                     │   └───────────────┘      │                                    │             │
                     │                          ▼                                    ▼             │
                     │              ┌────────────────────────┐        ┌──────────────────────────┐ │
                     │              │ ResponseSignature      │        │  envelope                │ │
                     │              │ (status, len_bucket,   │        │  {"requests":[{date,     │ │
                     │              │  has_results, venues,  │        │    party_size, status,   │ │
                     │              │  has_slots)            │        │    body}, …]}            │ │
                     │              └──────────┬─────────────┘        └────────────┬─────────────┘ │
                     │        LPUSH/LTRIM 20   │                                   │               │
                     │   canary:resy:{venue} ◄─┤                                   │               │
                     │                         ▼ verdict = BAN                     │               │
                     │        ┌────────────────────────────────┐                   │               │
                     │        │ scrape_ban_total{reason} +1    │                   │               │
                     │        │ recycle ctx (close+create ~5ms)│                   │               │
                     │        │ SET backoff:… ; status=banned  │                   │               │
                     │        │ all poisoned in 5m ─► resy:paused EX 900           │               │
                     │        └────────────────┬───────────────┘                   │               │
                     │                         │                                   │               │
                     │                         ▼                                   ▼               │
                     │                    ┌────────────────────────────────────────────┐           │
                     │                    │  Publisher (UNCHANGED from Phase 1)        │           │
                     │                    └───────────┬──────────────────┬─────────────┘           │
                     │  ┌──────────────────┐          │                  │                         │
                     │  │ /metrics :9101   │          │                  │                         │
                     │  │ (daemon thread)  │          │                  │                         │
                     │  └──────────────────┘          │                  │                         │
                     └────────────────────────────────┼──────────────────┼─────────────────────────┘
                                                      ▼                  ▼
                                          Kafka availability.raw   Kafka polls.completed
                                                      │                  │  status ∈ {success,
                                                      │                  │   error,timeout,BANNED}
                                                      ▼                  ▼
                          ┌──────────────────────────────────────────────────────────┐
                          │  state_machine consumer (Phase 2)                        │
                          │   parse_raw ─► PARSER_REGISTRY["resy"] = parse_resy  ◄── ONE new entry
                          │   DiffEngine ─── UNCHANGED, no source branching          │
                          │   _handle_completed: non-success ─► mark_unknown         │
                          └──────────────────────────────────────────────────────────┘
```

### Recommended Project Structure

```
services/poller/
├── config.py                   # + Resy env READ THROUGH FUNCTIONS (never module constants)
├── main.py                     # + optional ContextPool start/stop, start_http_server
├── scheduler.py                # + source registry, pre-dispatch gates, backoff release
└── sources/
    ├── registry.py             # {source: AvailabilitySource} — replaces the if/else
    └── resy/
        ├── README.md           # cites the enforcing functions for the README legal claims
        ├── accounts.py         # pydantic models for RESY_ACCOUNTS_JSON (both cookie shapes)
        ├── adapter.py          # ResyAdapter(AvailabilitySource) — envelope builder
        ├── canary.py           # ResponseSignature + pure verdict function
        ├── fingerprints.py     # >=6 coherent rows: UA + vp + locale + tz + dsf
        │                       #   + sec-ch-ua / sec-ch-ua-platform / Accept-Language (B-9)
        │                       #   + platform / hardwareConcurrency / deviceMemory / webgl (B-3)
        ├── fixtures.py         # [ASSUMED] /4/find bodies, TODO(spike) markers
        ├── pool.py             # ContextPool: Browser + Semaphore + idle Queue + recycle
        └── stealth.py          # build_init_script(fingerprint) from SCRIPTS (B-2, B-3)
shared/
├── metrics.py                  # NEW — every metric defined exactly once
├── redis_keys.py               # + tier/backoff/rate/canary/pause keys + budget Lua
├── events.py                   # + "banned", + context_id
└── telemetry.py                # + cookie/auth/proxy redaction (B-6)
services/state_machine/
├── parsers/resy.py             # NEW — registered in PARSER_REGISTRY
├── parsers/__init__.py         # + one dict entry
└── consumer.py                 # invert the status check (B-7)
scripts/
├── seed_restaurants.py         # + numeric Resy ids, "-resy" slug, RESY_ENABLED
├── soak_playwright.py          # NEW — ps/pgrep sampling, JSONL, exit 0/1/2
└── seed/restaurants.yml        # + resy_venue_id_numeric, rename to resy_slug (B-4)
tests/fakes/resy_stub.py        # NEW — FastAPI app + __ctl endpoints + hit log
docs/runbooks/perf05-soak.md    # NEW — STATUS: pending-human-run
```

### Pattern 1: Source registry replaces the `if source ==` branch (D-63)

Today `poll_loop` branches inline, and an unknown source is dropped **without release** — the job leaks into `sched:polls:inflight`:

```python
            if source == "opentable":
                raw_response = await opentable.poll(…)
                status = "success"
                http_status = 200
            else:
                log.warning("unknown_source", source=source)
```
[VERIFIED: services/poller/scheduler.py:90-99]

Replace with `ADAPTERS: dict[str, AvailabilitySource]`, constructed in `main.py` and passed in; Resy is present only when `RESY_ENABLED=true`. **Also fix the leak**: an unknown source must still be released (or explicitly `ZREM`'d from inflight), otherwise every stray descriptor becomes a permanent reaper cycle.

### Pattern 2: Cadence, backoff and rate refusal are all ZSET scores, never sleeps

The release path already computes a score and honours the expedite flag:

```python
        release_now_ms = int(time.time() * 1000)
        expedited = await scheduler.consume_expedite(job)
        next_score = (
            release_now_ms + CONFIRM_DELAY_MS if expedited else _next_poll_score(release_now_ms)
        )
```
[VERIFIED: services/poller/scheduler.py:142-146]

Extend it, in this precedence order (D-59 says expedite is honoured *only* when no backoff is active):

1. `backoff:{source}:{rid}` present → `now + backoff_seconds*1000` (ignore the expedite flag, but still `GETDEL` it so it does not fire later)
2. else expedite flag → `now + CONFIRM_DELAY_MS`
3. else → `now + jitter(effective_interval_seconds(source, watches, override))`

`_next_poll_score` currently hard-codes the module-level OpenTable constants:

```python
_INTERVAL_MS: int = POLL_INTERVAL_SECONDS * 1000  # 90_000 ms
_JITTER_MS: int = int(_INTERVAL_MS * POLL_JITTER_FRACTION)  # +/- 13_500 ms
```
[VERIFIED: services/poller/scheduler.py:30-31] — it must take the interval as a parameter so Resy's 180 s baseline and the tier result flow through. Keep the ±15 % jitter fraction (`POLL_JITTER_FRACTION: float = 0.15` [VERIFIED: shared/redis_keys.py:25]).

### Pattern 3: `ContextPool` — one browser, N contexts, semaphore + idle queue (D-60)

Measured costs make the shape obvious. Contexts are essentially free; only pages are expensive:

```
[after launch]                    pgrep(ms-playwright)=6
[after 4 contexts (no pages)]     pgrep(ms-playwright)=6     total chromium RSS  455 120 KiB
[after 4 request calls]           pgrep(ms-playwright)=6     total chromium RSS  457 648 KiB
[after 4 pages]                   pgrep(ms-playwright)=11    total chromium RSS 1 167 648 KiB
[after closing pages+contexts]    pgrep(ms-playwright)=6     total chromium RSS  618 432 KiB
[after browser.close()]           pgrep(ms-playwright)=0
```
[VERIFIED: executed 2026-09-05, `channel="chromium"`]

Timings (warm): `launch` 0.25 s, `new_context` 2–7 ms, `context.close` 3 ms, **full recycle ~5 ms**, `browser.close` 25 ms. [VERIFIED: executed 2026-09-05] SC3's "observable context recycle within one poll cycle" is therefore never at risk.

**The pool must never open a page in the production path.** Pages are for tests only.

`browser.close()` in a shielded `finally` is mandatory — see §Pitfall 1.

### Pattern 4: Coherent per-context stealth (corrects D-60 per B-2/B-3)

Build the `opts` object from the *chosen fingerprint*, compose the script list yourself, and install it once on the context. Verified output on a real HTTP origin, with a second page created after the fact:

```
navigator.webdriver              = None
navigator.userAgent              = Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) … Chrome/140.0.0.0 Safari/537.36
navigator.platform               = MacIntel
navigator.languages              = ['en-US', 'en']
navigator.vendor                 = Google Inc.
navigator.hardwareConcurrency    = 10
navigator.deviceMemory           = 8
navigator.plugins.length         = 3
typeof window.chrome             = object
typeof window.chrome.runtime     = object
typeof chrome.loadTimes          = function
webgl vendor                     = Apple Inc.
webgl renderer                   = Apple M3 Pro
permissions.query                = denied
tz                               = America/New_York
2nd page navigator.webdriver     = None
2nd page navigator.userAgent     = Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Appl
```
[VERIFIED: executed 2026-09-05 against a local uvicorn origin]

Contrast the same script on `about:blank` — see §Pitfall 3; this is the difference between a real assertion and a test that locks in a broken stealth.

### Pattern 5: The `/4/find` call through `context.request` (D-64)

Verified end to end against the stub. Key semantics:

| Property | Verified behaviour |
|----------|--------------------|
| Signature | `get(url, *, params, headers, data, form, multipart, timeout, fail_on_status_code, ignore_https_errors, max_redirects, max_retries)` [VERIFIED: `inspect.signature(APIRequestContext.get)`] |
| 4xx/5xx | **Returned, not raised** — `fail_on_status_code` defaults to off. `status=429 ok=False retry-after=30`; `status=403 ok=False ct=text/html` [VERIFIED] |
| `.json()` on non-JSON | raises `json.JSONDecodeError: Expecting value: line 1 column 1 (char 0)` — the adapter must guard [VERIFIED] |
| Errors | `playwright.async_api.Error` for `connect ECONNREFUSED` / `getaddrinfo ENOTFOUND`; `TimeoutError` (a **subclass** of `Error`) for `Timeout 1500ms exceeded` [VERIFIED] |
| Response API | `.status: int`, `.ok: bool`, `.status_text`, `.url`, `.headers: dict[str,str]` (lowercased), `.headers_array` (a **property**, not a method), `await .json()`, `await .text()`, `await .body()`, `await .dispose()` [VERIFIED] |
| Cookies | Sent from the context jar, host-matched. A cookie added with `url="https://resy.com/"` is stored **host-only** (`domain: "resy.com"`) and will *not* reach `api.resy.com`; `domain=".resy.com"` does [VERIFIED: `[('auth_token', '.resy.com', '/', True, 'Lax', -1), ('u', 'resy.com', '/', True, 'Lax', -1)]`] |

`add_cookies` validation, reproduced:

```
B1 name+value only:        REJECTED -> Error BrowserContext.add_cookies: Cookie should have a url or a domain/path pair
B2 domain+path+secure:     ACCEPTED
B3 url form:               ACCEPTED
B4 domain WITHOUT path:    REJECTED -> BrowserContext.add_cookies: Cookie should have a url or a domain/path pair
B5 sameSite None (no secure): ACCEPTED   # Playwright does not enforce the browser rule here
```
[VERIFIED: executed 2026-09-05] — the `SetCookieParam` TypedDict is `total=False` with **zero required keys**, so mypy will not catch a missing `domain`; only the runtime will. D-61's expansion shape (`domain=".resy.com", path="/", secure=True`) is correct and is the one to use.

### Pattern 6: Minute budget as a single Lua script (D-65)

```
budget: cost=3 cap=80 -> granted 26/30 calls; last=[0, 78, 2]; TTL=90
first-call TTL set?   90
naive INCR alone TTL: -1   (no expiry -> a permanent key if the process dies before EXPIRE)
SET NX EX 45 first: True  ttl: 45
SET NX EX 45 again: None  (falsy = the floor is still active)
ttl unchanged (no sliding window): 45
```
[VERIFIED: executed against live `redis:7.2-alpine` → server 7.2.16, 2026-09-05]

Note `r.set(..., nx=True)` returns **`None`**, not `False`, when the key exists — matching the existing helper's `return result is True`:

```python
    result = await r.set(key, value, nx=True, ex=ttl_seconds)
    return result is True
```
[VERIFIED: shared/redis_keys.py:40-41]

### Pattern 7: The canary window (D-67)

```
canary LIST after 25 LPUSH+LTRIM(0,19): llen= 20 head= b'200|24|1|1|1' tail= b'200|5|1|1|1'
pipeline(transaction=True) results: 21 True 20 True   ttl: 3600
```
[VERIFIED: executed 2026-09-05]

Do the `LPUSH` + `LTRIM` + `LRANGE` + `EXPIRE` in one `r.pipeline(transaction=True)` (a MULTI/EXEC) so a concurrent poll cannot read a half-updated window. The **verdict function must be pure** — `(new_signature, baseline_list) -> BanReason | None` — so every rule in D-67 is a unit test with no Redis.

### Pattern 8: Process accounting for the soak (PERF-05)

The tree, verified:

```
45130 45129 116784 …/site-packages/playwright/driver/node …            # node driver, child of python
45133 45130 160752 …/ms-playwright/chromium-1208/…/Google Chrome for Testing   # browser, child of node
45135     1   9776 …/Google Chrome …Framework…                          # crashpad, PPID 1 (re-parented!)
45137     1   9664 …/Google Chrome …Framework…                          # crashpad, PPID 1
45144 45133 102352 …                                                    # gpu / network / utility
45145 45133  88080 …
45146 45133  77504 …
--- pgrep -f ms-playwright count: 6
--- pgrep -f 'chrome-headless-shell' count: 0
--- pgrep -f 'chromium-1208' count: 6
```
[VERIFIED: executed 2026-09-05]

Two consequences: **(1)** two crashpad handlers are re-parented to PID 1, so walking the process tree from the Python pid misses them — but they *do* exit on `browser.close()` (`pgrep` returned 0). **(2)** `pgrep -f ms-playwright` is the correct discriminator (§B-8).

### Anti-Patterns to Avoid

- **Calling `stealth_async(page)`** — per-page, randomises the fingerprint, contradicts D-60 (§B-3).
- **Opening a page to make the availability request** — ~178 MB and one process per page; forfeits PERF-05 (§Pattern 3).
- **`asyncio.sleep` to enforce the 45 s floor or the 80 rpm cap** — burns a pool slot and a worker task; the whole scheduler design exists to avoid it (D-59, D-65).
- **Asserting stealth on `about:blank`** — the init script throws there and every patch after the throw is silently skipped (§Pitfall 3).
- **Trusting `resource.getrusage` for the leak verdict** — monotone high-water mark (§B-8).
- **Reading Resy env vars into module-level constants** — `services/poller/config.py` already freezes env at import (`KAFKA_BOOTSTRAP_SERVERS: str = os.getenv(…)` [VERIFIED: services/poller/config.py:44]), which broke a full-suite run in 02-02. Every new Resy setting must be read through a function, as `services/state_machine/config.py` does.
- **A `fail_on_status_code=True` request** — it would raise on the very 429/403 the canary and the backoff exist to observe.
- **Logging `raw_response`, a `booking_token`, or any header dict at INFO** — the redactor is key-name based and will not save you (§B-6).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Browser context pooling | A custom pool class with health checks, warm spares, eviction | `asyncio.Semaphore(N)` + `asyncio.Queue` of idle contexts (D-60) | Contexts cost 2–7 ms to create and 3 ms to close (verified). A pool that "keeps contexts warm" optimises something already free while adding the exact lifecycle bugs PITFALLS §Pitfall 1 warns about |
| Anti-detection JS | Your own `navigator.webdriver` deleter, plugin faker, `window.chrome` shim | `playwright_stealth.core._stealth_config.SCRIPTS` (the JS files only) | 17 battle-tested scripts ship with the pinned package. Take the JS, reject the Python wrapper (§B-3) |
| Atomic minute budget | `GET` → compare → `INCR` → `EXPIRE` in Python | One Lua script (§Pattern 6) | Verified `INCR` alone leaves `ttl == -1` forever. Three round trips is also three race windows |
| Per-context cooldown | A dict of `{(ctx, venue): last_ts}` in memory | `SET key 1 NX EX 45` | In-memory state dies with the process and does not survive a context recycle; Redis makes the floor a system property. Also satisfies `test_no_setnx_expire_pairs.py` |
| Free-port allocation in tests | Hard-coded ports / retry loops | `socket.bind(("127.0.0.1", 0))` then read `getsockname()[1]` | Verified working under pytest |
| Waiting for uvicorn readiness | `asyncio.sleep(1)` after `create_task` | `await asyncio.wait_for(<poll server.started>, timeout=10)` | `uvicorn.Server.started` is the documented flag; verified in a passing test |
| Metric scraping in tests | Spin up the HTTP server and fetch `/metrics` | `registry.get_sample_value(name, labels)` | No socket, no thread, no port; verified (§Pitfall 6 has the naming gotcha) |
| Sub-process RSS | Parsing `top`, or adding `psutil` | `ps -o rss= -p <pid>` via `asyncio.create_subprocess_exec` | KiB on both macOS and Linux (verified); no new dependency |
| Cookie string parsing | Splitting `document.cookie` by hand | `context.add_cookies([...])` + `context.cookies(url)` | The runtime enforces the `url` XOR `domain`+`path` rule for you (§Pattern 5) |

**Key insight:** every "hard" primitive in this phase (atomic budget, cooldown, rolling window, pause flag) is a one-line Redis command or a five-line Lua script that was executed successfully this session. The genuinely hard parts are *process lifecycle* and *fingerprint coherence* — spend the engineering budget there.

---

## Common Pitfalls

### Pitfall 1: A cancelled task without a shielded `finally` leaves zombie Chromium processes

This is PERF-05's headline failure mode, reproduced deliberately:

```
--- cancellation with NO finally cleanup (leak check) ---
procs while running: 6
procs after cancel WITHOUT cleanup: 6 <-- LEAKED if > 0
post-loop procs check done
final pgrep: ['45332', '45334', '45336', '45339', '45340', '45341']
```
[VERIFIED: executed 2026-09-05 — six processes survived `asyncio.run()` returning]

The mitigation, also verified:

```
--- cancellation: task cancelled while awaiting a slow request ---
procs before: 0
  worker saw CancelledError
  finally: closing browser (shielded)
  browser closed in finally
  task cancelled OK
procs after cancel+cleanup: 0
```
[VERIFIED: executed 2026-09-05]

**How to avoid:** `finally: await asyncio.shield(browser.close())` then `await playwright.stop()`. A bare `await browser.close()` inside a `finally` reached via cancellation will itself raise `CancelledError` at the first `await` — `shield` is what makes it complete. Expect a `Future exception was never retrieved / Error: Request context disposed.` warning for the in-flight request; that is benign and should be swallowed, not "fixed" by removing the shield.

### Pitfall 2: The default UA leaks `HeadlessChrome` in every headless mode

```
HEADLESS_SHELL:   APIRequestContext default UA -> …HeadlessChrome/145.0.7632.6 Safari/537.36
CHANNEL_CHROMIUM: APIRequestContext default UA -> …HeadlessChrome/145.0.0.0 Safari/537.36
HEADED_CHROMIUM:  APIRequestContext default UA -> …Chrome/145.0.0.0 Safari/537.36
```
[VERIFIED: executed 2026-09-05]

**How to avoid:** `user_agent=` is **mandatory** on every `new_context()` — never rely on the default, and never create an un-fingerprinted context "just for a health check". Add a regression test asserting no context in the pool reports a UA containing `Headless`.

Related: the headless shell also leaks it in client hints (`sec-ch-ua: "Not:A-Brand";v="99", "HeadlessChrome";v="145", "Chromium";v="145"`), while `channel="chromium"` reports `"Chromium";v="145", "Not:A-Brand";v="99"` [VERIFIED]. Neither matches real Chrome's `"Google Chrome";v="140", …`, which is why §B-9 requires an explicit `sec-ch-ua` per fingerprint.

### Pitfall 3: The stealth init script fails **silently** on `about:blank`, disabling every later patch

```
shell    | about:blank      | OUR opts  err=["Cannot read properties of undefined (reading 'get')"] webdriver=True  deviceMemory=None userAgentData=undefined
shell    | http://127.0.0.1 | OUR opts  err=[]                                                      webdriver=None  deviceMemory=8    userAgentData=object
chromium | about:blank      | LIB opts  err=["Cannot read properties of undefined (reading 'get')"] webdriver=True
chromium | http://127.0.0.1 | LIB opts  err=[]                                                      webdriver=None
```
[VERIFIED: executed 2026-09-05 across both headless modes and both opts sources]

**Root cause:** `navigator.userAgent.js` calls `utils.replaceGetterWithProxy(Object.getPrototypeOf(navigator), "deviceMemory"/"userAgentData", …)`, and those properties are exposed only in a secure/trustworthy context. On `about:blank` the descriptor is `undefined` and `.get` throws. Bisected one script at a time, `navigator_user_agent` is the only offender:

```
navigator_user_agent             THROWS: Cannot read properties of undefined (reading 'get')
chrome_app / chrome_csi / chrome_load_times / chrome_runtime / iframe_content_window /
media_codecs / navigator_languages / navigator_permissions / navigator_plugins /
navigator_vendor / webdriver / outerdimensions / webgl_vendor      OK
```
[VERIFIED: executed 2026-09-05]

Because Playwright combines all init scripts into one, a throw in an early script kills every later one — and `add_init_script` reports nothing. `webdriver` comes **after** `navigator_user_agent` in the library's own order, so the throw disables exactly the patch you care about.

**How to avoid:** (1) every stealth assertion in the test suite must navigate to the **stub origin**, never `about:blank`; (2) attach a `page.on("pageerror", …)` collector in the stealth test and assert it stayed empty — that is what turns a silent failure into a red test.

### Pitfall 4: `poll_loop` is strictly serial — four contexts buy nothing without a concurrency change

```python
    while True:
        now_ms = int(time.time() * 1000)
        job = await scheduler.claim(now_ms)
        if job is None:
            await asyncio.sleep(1)
            continue
```
[VERIFIED: services/poller/scheduler.py:55-60] — one job is claimed, awaited to completion, and released before the next claim. `main.py` runs exactly one `poll_loop` [VERIFIED: services/poller/main.py:96-99].

D-60's `asyncio.Semaphore(4)` can never contend under this loop, so the pool would be a four-context decoration around a one-at-a-time pipeline, and the 80 rpm cap would never be approached.

**How to avoid:** run `RESY_CONTEXTS` (or a small fixed count) `poll_loop` worker tasks over the same `LuaScheduler` — the claim Lua is already atomic (`ZRANGEBYSCORE … LIMIT 0 1` then `ZREM` + `ZADD` inflight [VERIFIED: shared/redis_keys.py:117-124]), so N workers is safe with no further change. Do **not** fire-and-forget polls as detached tasks: the release path must still run for each job, and detached tasks make cancellation cleanup (Pitfall 1) much harder.

### Pitfall 5: A cookie added by `url=` is host-only and never reaches `api.resy.com`

```
B6 cookies stored for resy.com: [('auth_token', '.resy.com', '/', True, 'Lax', -1),
                                 ('u',          'resy.com', '/', True, 'Lax', -1)]
```
[VERIFIED: executed 2026-09-05]

The `url` form yields `domain: "resy.com"` (host-only), which does **not** match the `api.resy.com` subdomain; only the explicit `domain=".resy.com"` form does. Since `expires` is `-1` (session cookie) in both cases, nothing on disk will remind you.

**How to avoid:** `accounts.py` must normalise *both* accepted D-61 shapes to `domain=".resy.com"`. If an operator supplies an explicit Playwright cookie list containing a host-only `resy.com` domain, log a warning — silently accepting it produces an anonymous fleet that still returns `200 OK`, which is indistinguishable from a soft ban.

### Pitfall 6: `Duplicated timeseries in CollectorRegistry` when a metrics module is re-imported

```
DUPLICATE registration -> ValueError : Duplicated timeseries in CollectorRegistry: {'scrape_ban_total', 'scrape_ban', 'scrape_ban_created'}
default REGISTRY duplicate -> ValueError : Duplicated timeseries in CollectorRegistry: {'x_total', 'x_created', 'x'}
```
[VERIFIED: executed 2026-09-05]

This project already evicts modules from `sys.modules` in integration teardown (recorded in STATE.md for 02-02), so a module-level metric definition in `shared/metrics.py` is one `importlib.reload` away from an exception.

**How to avoid:** define metrics exactly once in `shared/metrics.py` against the default `REGISTRY`; never reload that module; and make sure no test fixture evicts `shared.metrics` from `sys.modules`. Add a `tests/unit/test_metrics_registry.py` that imports the module twice and asserts no exception.

**Naming gotcha, verified:** `Counter("scrape_ban_total", …)` is stored under internal name `scrape_ban` and emits samples `scrape_ban_total` + `scrape_ban_created`. Tests must call `get_sample_value("scrape_ban_total", labels)` — `"scrape_ban_total_total"` returns `None`, which is an assertion that silently passes if written as `assert x is None`.

**Bucket gotcha:** the default histogram buckets end at `10.0` (`[0.005, …, 7.5, 10.0, inf]` [VERIFIED]). A Playwright poll of three requests can exceed that; D-69's `poll_latency_seconds` needs explicit buckets (e.g. `(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)`).

### Pitfall 7: `playwright_stealth` is untyped; `playwright` is not

`playwright` ships `py.typed`; `playwright_stealth` does **not** [VERIFIED: `ls .venv/.../playwright/py.typed` → present; `.../playwright_stealth/py.typed` → `No such file or directory`]. A probe module using `Browser`, `BrowserContext`, `APIResponse`, `ProxySettings`, `SetCookieParam`, `add_init_script`, `add_cookies`, `request.get`, `PlaywrightError`/`PlaywrightTimeout`, and the repo's `cast(Awaitable[T], …)` Redis pattern passed cleanly:

```
uv run mypy --strict --python-version 3.12 .mypyprobe/probe.py
Success: no issues found in 1 source file
```
[VERIFIED: executed 2026-09-05 with the project's `ignore_missing_imports = true`]

**How to avoid trouble:** no `# type: ignore` is needed anywhere for Playwright. `playwright_stealth` resolves to `Any` via `ignore_missing_imports`, which means **mypy will not catch a typo in a `SCRIPTS` key** — guard that with a unit test asserting every name in your script-order tuple exists in `SCRIPTS`.

### Pitfall 8: Module-scoped async fixtures need `pytest_asyncio.fixture`, not `pytest.fixture`

```
TypeError: fixture() got an unexpected keyword argument 'loop_scope'
```
[VERIFIED: executed 2026-09-05 under pytest 9.0.3 + pytest-asyncio 1.3.0]

Under `asyncio_mode = "auto"` a plain `@pytest.fixture` async fixture works but is pinned to a function-scoped loop, so it cannot be `scope="module"`. The working form (verified green) is `@pytest_asyncio.fixture(scope="module", loop_scope="module")` plus `@pytest.mark.asyncio(loop_scope="module")` on every consuming test.

**Recommendation:** with `launch` at 0.25 s warm, a **function-scoped** browser fixture is simpler and fast enough (three tests, uvicorn stub and real Chromium, ran in 2.94 s total). Only reach for module scope if the Resy suite grows past ~15 browser tests.

### Pitfall 9: uvicorn's signal handling in tests (and the stale workaround that no longer works)

`uvicorn.Server.serve()` replaces the SIGINT/SIGTERM handlers and restores them, including after cancellation:

```
override=False: during-serve handler is uvicorn's? True   restored to the pre-serve handler? True
override=True:  during-serve handler is uvicorn's? True   restored to the pre-serve handler? True
after task.cancel(): restored? True
```
[VERIFIED: executed 2026-09-05]

Note `override=True` — assigning `server.install_signal_handlers = lambda: None`, the workaround in every pre-0.30 blog post — **has no effect in 0.44**, because `serve()` now uses a context manager:

```python
    async def serve(self, sockets: list[socket.socket] | None = None) -> None:
        with self.capture_signals():
```
[VERIFIED: uvicorn/server.py:77-78] and `capture_signals` saves `original_handlers` and restores them in a `finally` [VERIFIED: uvicorn/server.py:322-334].

**How to avoid:** do nothing — it is already safe. Just do not add the dead workaround, and always drive shutdown with `server.should_exit = True` + `await asyncio.wait_for(task, timeout=10)` rather than cancelling the serve task.

### Pitfall 10: `venues: []` with `200 OK` is indistinguishable from "no availability"

This is POLL-06's entire reason to exist, and the stub reproduces it (`mode=banned_empty status=200 ok=True len=27 ct=application/json`, `json ok, keys: ['results']` [VERIFIED]). A canary that only compares against *this venue's* history will also fire on a genuinely fully-booked Saturday.

**How to avoid:** D-67's rule already requires **three consecutive** empty 200s *while the baseline majority had venues*. Add a fleet-level cross-check before declaring a ban: if every venue polled in the same minute went empty simultaneously, that is a ban; if one venue went empty while others still return slots, that is far more likely to be real. Record `venues_count` per signature so this is computable from the existing window.

---

## Code Examples

### Chromium availability guard (corrects D-71 per B-1) — verified green in pytest

```python
def _chromium_available() -> bool:
    """True only if the revision THIS playwright pins is installed (B-1)."""
    import json
    from pathlib import Path
    import playwright

    manifest = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
    rev = next(
        b["revision"] for b in json.loads(manifest.read_text())["browsers"]
        if b["name"] == "chromium"
    )
    root = Path.home() / ("Library/Caches/ms-playwright" if sys.platform == "darwin"
                          else ".cache/ms-playwright")
    return (root / f"chromium-{rev}").exists()


pytestmark = pytest.mark.skipif(
    not _chromium_available(),
    reason="Playwright Chromium for the pinned playwright version is not installed — run `make browsers`",
)
```
[VERIFIED: this exact guard ran in a passing 3-test file, 2026-09-05]

### `ContextPool` browser lifecycle — verified zero leaked processes

```python
@pytest_asyncio.fixture  # or the pool's own start()/stop()
async def browser() -> AsyncIterator[Browser]:
    pw = await async_playwright().start()
    b = await pw.chromium.launch(headless=True, channel="chromium")   # channel= avoids the shell UA leak
    try:
        yield b
    finally:
        await asyncio.shield(b.close())   # shield: a bare await re-raises CancelledError immediately
        await pw.stop()
```
[VERIFIED: `procs after cancel+cleanup: 0`, executed 2026-09-05]

### Coherent per-context stealth (corrects D-60 per B-2/B-3)

```python
from playwright_stealth.core._stealth_config import SCRIPTS

SCRIPT_ORDER = (
    "utils", "generate_magic_arrays", "chrome_app", "chrome_csi", "chrome_load_times",
    "chrome_runtime", "iframe_content_window", "media_codecs", "navigator_languages",
    "navigator_permissions", "navigator_plugins", "navigator_user_agent",
    "navigator_vendor", "webdriver", "outerdimensions", "webgl_vendor",
)

def stealth_opts(fp: Fingerprint) -> dict[str, Any]:
    """Everything the shipped JS reads lives under `opts` — build it from OUR fingerprint."""
    return {
        "navigator": {
            "userAgent": fp.user_agent,
            "brands": fp.brands,                   # must agree with fp.sec_ch_ua
            "doNotTrack": "1",
            "platform": fp.platform,               # "MacIntel" / "Win32" / "Linux x86_64"
            "language": fp.languages[0],
            "languages": fp.languages,
            "appVersion": fp.user_agent.removeprefix("Mozilla/"),
            "vendor": "Google Inc.",
            "deviceMemory": fp.device_memory,
            "hardwareConcurrency": fp.hardware_concurrency,
            "maxTouchPoints": 0,
            "mobile": False,
            "productSub": "20030107",
        },
        "webgl": {"vendor": fp.webgl_vendor, "renderer": fp.webgl_renderer},
        "viewport": {
            "width": fp.viewport["width"], "height": fp.viewport["height"],
            "outerWidth": fp.viewport["width"], "outerHeight": fp.viewport["height"] + 85,
            "innerWidth": fp.viewport["width"], "innerHeight": fp.viewport["height"],
        },
        "runOnInsecureOrigins": None,
    }

def build_init_script(fp: Fingerprint) -> str:
    return "\n".join([f"const opts = {json.dumps(stealth_opts(fp))}",
                      *(SCRIPTS[name] for name in SCRIPT_ORDER)])

# once per context, never per page
await ctx.add_init_script(build_init_script(fp))
```
[VERIFIED: produced `navigator.webdriver = None` with UA/platform/languages/hardwareConcurrency/deviceMemory/WebGL all matching `fp`, on a real HTTP origin, and applying to a page created afterwards — executed 2026-09-05]

### Context creation with a coherent fingerprint + realistic headers (corrects D-64 per B-9)

```python
ctx = await browser.new_context(
    user_agent=fp.user_agent,               # MANDATORY — the default leaks "HeadlessChrome"
    viewport=fp.viewport,
    locale=fp.locale,
    timezone_id=fp.timezone_id,
    device_scale_factor=fp.device_scale_factor,
    proxy=proxy_settings,                   # per-context proxy DOES work in 1.58 (verified)
    extra_http_headers={                    # B-9: APIRequestContext sends none of these by itself
        "Accept-Language": fp.accept_language,          # e.g. "en-US,en;q=0.9"
        "sec-ch-ua": fp.sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": fp.sec_ch_ua_platform,    # e.g. '"macOS"'
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Origin": "https://resy.com",
        "Referer": "https://resy.com/",
    },
)
await ctx.add_cookies([
    {"name": name, "value": value, "domain": ".resy.com", "path": "/", "secure": True}
    for name, value in account.cookies.items()          # ".resy.com", NOT url= (Pitfall 5)
])
await ctx.add_init_script(build_init_script(fp))
```
[VERIFIED: every keyword above exists on `Browser.new_context` in 1.58.0 (`inspect.signature`), the cookie form was accepted at runtime, and the `extra_http_headers` were observed on the wire in a `context.request.get` call — executed 2026-09-05]

`proxy` is available on **both** `chromium.launch` and `new_context` in 1.58 [VERIFIED: `inspect.signature`, and the doc line `proxy : Union[{server: str, bypass: …}] — Network proxy settings to use with this context.`], and a per-context proxy is genuinely enforced:

```
per-context proxy w/ dead proxy -> Error | APIRequestContext.get: connect ECONNREFUSED 127.0.0.1:9
per-context proxy page.goto     -> Error | Page.goto: net::ERR_PROXY_CONNECTION_FAILED
```
[VERIFIED: executed 2026-09-05] — D-62's launch-level placement is fine for this phase; note in `pool.py` that moving it to `new_context` is a one-line change when proxy rotation lands.

### The `/4/find` call and its error taxonomy (D-64, D-59)

```python
resp = await ctx.request.get(
    f"{base}/4/find",
    params={"lat": 0, "long": 0, "day": day, "party_size": party, "venue_id": venue_id},
    headers={
        "Authorization": f'ResyAPI api_key="{api_key}"',
        "X-Resy-Auth-Token": auth_token,
        "X-Origin": "https://resy.com",
        "Accept": "application/json",
    },
    timeout=10_000,          # ms; TimeoutError is a subclass of playwright Error
)
status = resp.status         # 429/403/500 are RETURNED, never raised
if resp.headers.get("content-type", "").startswith("application/json"):
    body = await resp.json()          # raises json.JSONDecodeError on a challenge page
else:
    body = None
text = await resp.text()              # for body_len in the canary signature
await resp.dispose()
```

Observed against the stub:

```
mode=rate_limited    status=429 ok=False retry-after=30 len=24 ct=application/json
mode=error_500       status=500 ok=False retry-after=None len=13 ct=text/plain; charset=utf-8
mode=banned_empty    status=200 ok=True  retry-after=None len=27 ct=application/json
mode=challenge_403   status=403 ok=False retry-after=None len=39 ct=text/html; charset=utf-8
mode=normal          status=200 ok=True  retry-after=None len=242 ct=application/json
```
[VERIFIED: executed 2026-09-05]

### Minute-budget Lua (D-65) — executed against Redis 7.2.16

```lua
-- KEYS[1] = rate:resy:{epoch_minute}
-- ARGV[1] = cost (requests this poll will make)   ARGV[2] = cap (RESY_GLOBAL_RPM)
-- ARGV[3] = ttl seconds                            Returns {granted(0|1), count_after, remaining}
local cur  = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost = tonumber(ARGV[1])
local cap  = tonumber(ARGV[2])
if cur + cost > cap then
  return {0, cur, cap - cur}
end
local new = redis.call('INCRBY', KEYS[1], cost)
if new == cost then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
end
return {1, new, cap - new}
```
[VERIFIED: `granted 26/30 calls; last=[0, 78, 2]; TTL=90` — executed 2026-09-05]

Note the refusal is *conservative*: with cost 3 and cap 80 it stops at 78, leaving 2 unused. That is correct — never overshoot the cap the public README promises.

### Per-context floor and the canary window (D-65, D-67)

```python
granted = await set_nx_ex(r, f"rate:resy:ctx:{ctx_id}:{venue_id}", "1", 45)   # SET .. NX EX 45
# verified: True first, None (falsy) second, TTL stays 45 — no sliding window

async with r.pipeline(transaction=True) as pipe:
    pipe.lpush(key, sig); pipe.ltrim(key, 0, 19); pipe.lrange(key, 0, -1); pipe.expire(key, 3600)
    _, _, window, _ = await pipe.execute()
# verified: llen stays 20 after 25 pushes; pipeline returns [21, True, 20, True]
```
[VERIFIED: executed 2026-09-05]

### mypy-strict Redis helpers for the new commands (repo `cast(Awaitable[T], …)` convention)

```python
async def incrby(r: Redis, key: str, amount: int) -> int:
    return await cast(Awaitable[int], r.incrby(key, amount))

async def lpush_sig(r: Redis, key: str, sig: str) -> int:
    return await cast(Awaitable[int], r.lpush(key, sig))

async def ltrim_window(r: Redis, key: str, stop: int) -> bool:
    return await cast(Awaitable[bool], r.ltrim(key, 0, stop))

async def lrange_window(r: Redis, key: str) -> list[bytes]:
    return await cast(Awaitable[list[bytes]], r.lrange(key, 0, -1))

async def hget_field(r: Redis, key: str, field: str) -> bytes | None:
    return await cast(Awaitable[bytes | None], r.hget(key, field))
```
[VERIFIED: `mypy --strict` clean on a probe containing all five, executed 2026-09-05] — every cast belongs in `shared/redis_keys.py`, exactly as the module's own docstring demands (*"Every cast lives here, exactly once"* [VERIFIED: shared/redis_keys.py:68-74]).

### In-process uvicorn stub (D-71) — this exact fixture ran green

```python
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
async def stub_base() -> AsyncIterator[str]:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())

    async def _wait() -> None:
        while not server.started:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait(), timeout=10)      # bounded; no unbounded sleep loop
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=10)
```
[VERIFIED: 3 tests using this fixture plus real headless Chromium passed in 2.94 s, 2026-09-05]

### Prometheus in an asyncio process (D-69)

```python
server, thread = start_http_server(metrics_port, registry=REGISTRY)   # daemon thread
try:
    await asyncio.gather(*worker_tasks)
finally:
    server.shutdown(); thread.join(timeout=5)
```
[VERIFIED: `start_http_server(port, addr, registry, …) -> Tuple[wsgiref.simple_server.WSGIServer, threading.Thread]`, `daemon=True`, and `thread alive after shutdown: False` — executed 2026-09-05]

In tests, use `port=0` for an ephemeral port and read the registry directly:

```
scrape_ban_total:  get_sample_value("scrape_ban_total", {"source":"resy","reason":"empty_results"}) -> 1.0
poll_total:        get_sample_value("poll_total",       {"source":"resy","status":"success"})       -> 2.0
hist count/sum:    poll_latency_seconds_count -> 1.0 ; poll_latency_seconds_sum -> 0.052
bucket:            poll_latency_seconds_bucket{le="0.1"} -> 1.0
```
[VERIFIED: executed 2026-09-05]

The daemon thread is compatible with the project's async-only rules: it introduces no `time.sleep(`, no `requests`, and no sync `redis` import, so all three CI ban-greps stay green. Document it in `shared/metrics.py` so a future reader does not "fix" it.

### RSS / PID sampling for the soak (corrects D-70 per B-8)

```python
async def _ps_rss_kib(pid: int) -> int | None:
    """CURRENT RSS in KiB on both macOS and Linux (verified)."""
    p = await asyncio.create_subprocess_exec(
        "ps", "-o", "rss=", "-p", str(pid),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await p.communicate()
    s = out.decode().strip()
    return int(s) if s else None


async def _playwright_pids() -> list[int]:
    """`ms-playwright` — NOT `chrom`, which matches the developer's own Chrome (B-8)."""
    p = await asyncio.create_subprocess_exec(
        "pgrep", "-f", "ms-playwright",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await p.communicate()
    return [int(x) for x in out.decode().split()]
```
Sample `sum(_ps_rss_kib(pid) for pid in [self, *playwright_pids])` every `--sample-every`; the verdict compares the **last** sample against the **first stable** sample, not `ru_maxrss`. Exit codes mirror `scripts/check_poll_success.py` (`return 2` on setup failure, `return 1` on a failed gate, `return 0` on pass [VERIFIED: scripts/check_poll_success.py:74,108,117,123]).

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact on this phase |
|--------------|------------------|--------------|----------------------|
| `chromium.launch(headless=True)` runs full Chromium | `headless=True` launches the separate **chrome-headless-shell** binary | Playwright 1.49 (2024) | The shell leaks `HeadlessChrome` in `sec-ch-ua` and `userAgentData`. Use `channel="chromium"` (§Pitfall 2) |
| Per-context proxy needed a dummy launch-level proxy | `new_context(proxy=…)` works standalone | modern Playwright | D-62 can stay at launch level; per-context is available for free when rotation lands |
| `prometheus_client.start_http_server` returned `None` | returns `(WSGIServer, Thread)` | prometheus-client 0.20+ | Clean shutdown and ephemeral test ports are now possible |
| `uvicorn` needed `install_signal_handlers = lambda: None` in tests | `serve()` wraps in `capture_signals()` which saves/restores | uvicorn 0.30+ | The old workaround is a no-op in 0.44 — do not add it (§Pitfall 9) |
| `playwright-stealth@2.0.3` | `tf-playwright-stealth==1.2.0` | 2025 fork | Already pinned. But its *Python wrapper* is the wrong abstraction here (§B-2/B-3) — take the JS |
| `pytest.fixture(scope="module")` for async fixtures | `pytest_asyncio.fixture(scope=…, loop_scope=…)` | pytest-asyncio 0.24 → 1.x | `pytest.fixture(loop_scope=…)` raises `TypeError` (§Pitfall 8) |

**Deprecated / outdated:**
- `StealthConfig`'s `vendor` / `renderer` / `nav_user_agent` / `nav_platform` / `languages` / `nav_vendor` / `run_on_insecure_origins` — dead fields in 1.2.0, read by nothing (§B-3). Any guide that tells you to set them is describing a version that does not exist here.
- `navigator.doNotTrack` patching — still present in the shipped JS, but Chrome removed the DNT API in ~135; harmless here because the property still exists on `Navigator.prototype` (verified `dnt_in_proto=True` on Chromium 145).

---

## Runtime State Inventory

> This phase is additive rather than a rename, but it does mutate seed data and introduce new Redis keys, so the categories are answered explicitly.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `restaurants` rows already seeded from `restaurants.yml` with `source='opentable'` only (the Resy branch is unreachable — §B-5). Adding Resy rows is an **insert**, not a rename; the existing rows are untouched. `sched:polls` already holds `opentable:{rid}` members. | Data migration: re-run `make seed` after the YAML change (the script is `ON CONFLICT DO UPDATE` idempotent [VERIFIED: scripts/seed_restaurants.py:76-88]). No `UPDATE` of existing rows is needed |
| Live service config | None — no external service holds state for this phase. Kafka topics already exist (all five created by `scripts/create_topics.py`); no new topic is introduced | None |
| OS-registered state | None — nothing is registered with launchd/systemd/Task Scheduler. **New OS-level state is introduced at runtime**: 6 Chromium/node processes per poller process, two of which re-parent to PID 1 (§Pattern 8) | Ensure `browser.close()` runs on every exit path (§Pitfall 1) |
| Secrets / env vars | New: `RESY_ENABLED`, `RESY_API_BASE`, `RESY_API_KEY`, `RESY_PROXY_URL`, `RESY_CONTEXTS`, `RESY_GLOBAL_RPM`, `RESY_BASELINE_INTERVAL_SECONDS`, `RESY_DATE_RANGE_DAYS`, `METRICS_PORT`. Existing `RESY_ACCOUNTS_JSON` is already in `.env.example:48` and already redacted. `RESY_ACCOUNT_{1,2,3}_{EMAIL,PASSWORD}` exist at `.env.example:42-47` for the bootstrap phase only | Add the new block to `.env.example`; extend the redactor for `RESY_API_KEY` and `RESY_PROXY_URL` (§B-6) |
| Build artifacts | `~/Library/Caches/ms-playwright/` now contains **both** `chromium-1208` (correct) and `chromium-1223` (orphaned, from a newer Playwright). Total ~1 GB across four directories | `chromium-1223` / `chromium_headless_shell-1223` are stale and can be removed with `playwright uninstall --all` on a machine that only runs this project — **do not** do it automatically; another tool on this machine installed them |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.12.13 | — |
| Playwright driver (Node) | `ContextPool` | ✓ | bundled with `playwright==1.58.0` | — |
| Chromium (rev **1208**) | POLL-04, POLL-05, PERF-05 | ✓ **after `playwright install chromium` was run this session** | Chrome for Testing 145.0.7632.6 | none — tests skip with the `make browsers` message (§B-1) |
| chrome-headless-shell (rev 1208) | not used (we pass `channel="chromium"`) | ✓ | 145.0.7632.6 | — |
| Docker | Redis / Kafka / Timescale testcontainers | ✓ | daemon reachable | Container-dependent tests already skip via `_docker_available()` [VERIFIED: tests/conftest.py:8-17] |
| Redis 7.2 | rate budget, canary, backoff | ✓ | 7.2.16 (verified live via `redis:7.2-alpine`) | — |
| PostgreSQL / TimescaleDB | `poll_log` success rate for the soak verdict | ✓ | `postgres:16-alpine` pulled and used this session; project image is `timescale/timescaledb:2.17.2-pg16` | soak can compute success from its own counters if the DB is down — but PERF-05's ≥99 % should come from `poll_log` |
| `ps`, `pgrep` | soak sampling | ✓ on macOS; ✗ in `python:3.12-slim` | — | `/proc/<pid>/statm` + `/proc/*/cmdline`, or install `procps` in the CI image (§B-8) |
| `curl` / network to `cdn.playwright.dev` | `playwright install chromium` | ✓ | — | pre-baked browser layer in the CI image |
| Real Resy accounts / API key / proxy | live polling only | ✗ (human-gated, FOUND-06) | — | **anonymous mode** (D-61) + the fixture-backed stub; every code path is exercised without secrets |

**Missing dependencies with no fallback:** none for the automated scope. The 12-hour production soak and the live `/4/find` DevTools capture remain human-gated, exactly as CONTEXT.md states.

**Missing dependencies with fallback:** `ps`/`pgrep` on slim Linux images (use `/proc`); real Resy credentials (anonymous mode + stub).

---

## Validation Architecture

*(`workflow.nyquist_validation` is `true` in `.planning/config.json` [VERIFIED: read this session] — this section is required.)*

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` — `testpaths = ["tests"]`, `pythonpath = ["."]`, marker `integration` |
| Quick run command | `uv run pytest tests/unit -x -q` (`make test`) |
| Full suite command | `uv run pytest tests/unit tests/integration -v` (`make test-integration`) |
| Browser guard | `_chromium_available()` comparing the installed revision to `driver/package/browsers.json` (§Code Examples) — **not** a glob |
| Container guard | existing `_docker_available()` in `tests/conftest.py` |
| Measured cost | uvicorn stub + real headless Chromium, 3 tests: **2.94 s** end to end [VERIFIED: executed 2026-09-05] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| POLL-02 | `tier_interval_seconds`: 12→60, 9→180, 3→180, 2→600, 0→600; boundaries at 2/3 and 9/10 | unit | `pytest tests/unit/test_tier_cadence.py -x` | ❌ Wave 0 |
| POLL-02 | `effective_interval_seconds`: watches only *speed up* (OpenTable never exceeds 90 s), Resy floored at 45 s, `tier:override` beats the computed tier | unit | `pytest tests/unit/test_effective_interval.py -x` | ❌ Wave 0 |
| POLL-02 | Jitter stays within ±15 % over 1 000 draws and is never negative | unit | `pytest tests/unit/test_jitter_bounds.py -x` | ❌ Wave 0 |
| POLL-02 | Backoff math: `min(interval * 2^n, 1800)`; TTL = 2× value; DEL on success | unit | `pytest tests/unit/test_backoff_math.py -x` | ❌ Wave 0 |
| POLL-02 | Release path precedence — backoff beats expedite; expedite flag is still `GETDEL`'d while backed off | integration | `pytest tests/integration/test_release_precedence.py -x` | ❌ Wave 0 |
| POLL-02 | **SC3:** stub returns 429 → job released at `now+backoff` **and** the serving context is recycled, both observed within one poll cycle | integration | `pytest tests/integration/test_429_backoff_and_recycle.py -x` | ❌ Wave 0 |
| POLL-04 | `_chromium_available()` returns False for a mismatched revision (B-1 regression guard) | unit | `pytest tests/unit/test_browser_guard.py -x` | ❌ Wave 0 |
| POLL-04 | Fingerprint table: ≥6 rows, all unique, every row internally coherent (UA platform ↔ `sec-ch-ua-platform` ↔ `navigator.platform` ↔ webgl vendor), no row contains `Headless` | unit | `pytest tests/unit/test_fingerprints.py -x` | ❌ Wave 0 |
| POLL-04 | Every name in `SCRIPT_ORDER` exists in `playwright_stealth…SCRIPTS` (mypy can't catch this — Pitfall 7) | unit | `pytest tests/unit/test_stealth_script_names.py -x` | ❌ Wave 0 |
| POLL-04 | Pool creates N contexts on 1 browser; `acquire`/`release` round-trips; recycle on `pages_served >= 500`, age ≥ 2 h, and poisoned | integration | `pytest tests/integration/test_context_pool.py -x` | ❌ Wave 0 |
| POLL-04 | Fingerprint rotation is per context: two contexts report **different** `navigator.userAgent`, each equal to its own table row | integration | `pytest tests/integration/test_fingerprint_rotation.py -x` | ❌ Wave 0 |
| POLL-04 | **Stealth (B-2/B-3/Pitfall 3):** on the **stub origin** (never `about:blank`) `navigator.webdriver` ∈ (None, False), `navigator.userAgent` **equals the fingerprint UA**, `pageerror` collector is empty, and a page created *after* the first still has the patch | integration | `pytest tests/integration/test_stealth_applied.py -x` | ❌ Wave 0 |
| POLL-04 | Cookies: `{name: value}` and explicit-list shapes both normalise to `domain=".resy.com"`; a host-only `resy.com` input warns (Pitfall 5) | unit | `pytest tests/unit/test_resy_accounts.py -x` | ❌ Wave 0 |
| POLL-04 | Anonymous mode: empty `RESY_ACCOUNTS_JSON` still starts the pool and logs `resy_anonymous_mode` exactly once | integration | `pytest tests/integration/test_anonymous_mode.py -x` | ❌ Wave 0 |
| POLL-05 | **Realistic headers (B-9):** the stub's hit log shows `Accept-Language`, `sec-ch-ua`, `sec-ch-ua-platform`, `Sec-Fetch-*`, `Origin`, `Referer`, `Authorization`, `X-Origin` on the `/4/find` request | integration | `pytest tests/integration/test_resy_request_headers.py -x` | ❌ Wave 0 |
| POLL-05 | Adapter builds the D-64 envelope: one entry per (date, party), `status` recorded per entry, `request_params["party_sizes"]` matches what was actually requested (B-4-of-Phase-2 guard) | unit | `pytest tests/unit/test_resy_envelope.py -x` | ❌ Wave 0 |
| POLL-05 | Budget Lua: cost 3 / cap 80 grants 26 then refuses; TTL set on first INCR only; a refusal does not consume budget | integration | `pytest tests/integration/test_rate_budget_lua.py -x` | ❌ Wave 0 |
| POLL-05 | 45 s floor: second `SET NX EX` on the same (ctx, venue) is falsy and the TTL does not slide; the pool picks another idle context; all-blocked → release at `now+5000` | integration | `pytest tests/integration/test_per_context_floor.py -x` | ❌ Wave 0 |
| POLL-05 | Zero `asyncio.sleep(` / `time.sleep(` anywhere under `services/poller/sources/resy/` (extends the Phase 2 gate) | unit | `pytest tests/unit/test_no_inline_sleep_resy.py -x` | ❌ Wave 0 |
| POLL-06 | Signature bucketing is deterministic and stable across equal bodies; `body_len_bucket` boundaries | unit | `pytest tests/unit/test_response_signature.py -x` | ❌ Wave 0 |
| POLL-06 | Pure verdict matrix: 403-with-challenge → BAN; 429 → BAN; 3 consecutive empty-200s against a non-empty baseline → BAN; **2** consecutive → no ban; body_len < 20 % of median → BAN; a genuinely fully-booked venue with an empty baseline → **no** ban (Pitfall 10) | unit | `pytest tests/unit/test_canary_verdict.py -x` | ❌ Wave 0 |
| POLL-06 | Rolling window: 25 pushes leave `llen == 20`; the pipeline is a single MULTI/EXEC | integration | `pytest tests/integration/test_canary_window.py -x` | ❌ Wave 0 |
| POLL-06 | A ban increments `scrape_ban_total{source="resy",reason=…}` read via `get_sample_value` (correct sample name — Pitfall 6), publishes `status="banned"`, and recycles the context | integration | `pytest tests/integration/test_ban_reaction.py -x` | ❌ Wave 0 |
| POLL-06 | Fleet pause: all contexts poisoned within 5 min → `resy:paused` with TTL 900; the scheduler releases Resy jobs at `now+60000` and dispatches none | integration | `pytest tests/integration/test_fleet_pause.py -x` | ❌ Wave 0 |
| POLL-06 | `shared/metrics.py` imports twice without `Duplicated timeseries` (Pitfall 6) | unit | `pytest tests/unit/test_metrics_registry.py -x` | ❌ Wave 0 |
| POLL-06 | Redaction covers `cookie`, `auth_token`, `x-resy-auth-token`, `authorization`, `set-cookie`, `RESY_API_KEY`, `RESY_PROXY_URL` (B-6) | unit | `pytest tests/unit/test_telemetry_redaction.py -x` | ✅ extend existing |
| PERF-05 | `_ps_rss_kib` returns KiB; `_playwright_pids()` returns 0 with no browser and >0 with one; `pgrep -f chrom` is **not** used anywhere in the script (B-8 regression guard) | unit | `pytest tests/unit/test_soak_sampling.py -x` | ❌ Wave 0 |
| PERF-05 | **Zombie guard (Pitfall 1):** a subprocess that cancels mid-poll **with** the shielded `finally` leaves zero `ms-playwright` processes; the same without it leaves >0 (both asserted) | integration | `pytest tests/integration/test_no_zombie_browsers.py -x` | ❌ Wave 0 |
| PERF-05 | **CI soak:** `scripts/soak_playwright.py --duration 90s --stub` exits 0, writes JSONL, and reports a stable PID count | integration | `pytest tests/integration/test_soak_ci.py -x` | ❌ Wave 0 |
| PERF-05 | Soak verdict logic: synthetic samples with +25 % RSS → exit 1; +10 % → exit 0; PID spread of 3 → exit 1 | unit | `pytest tests/unit/test_soak_verdict.py -x` | ❌ Wave 0 |
| POLL-05/06 | Resy parser matrix: success / empty `venues` / missing `results` / non-dict / partial-envelope → `ParsedPoll` or `ParseError`; coverage derived only from status-200 envelope entries | unit | `pytest tests/unit/test_parsers_resy.py -x` | ❌ Wave 0 |
| all | **SC5:** a Resy `availability.raw` message produces an `availability.events` message through the **unchanged `DiffEngine`**; asserts `PARSER_REGISTRY` gained exactly one key and `engine.py` contains no `"resy"` literal (B-7 restates the criterion) | integration | `pytest tests/integration/test_resy_e2e_state_machine.py -x` | ❌ Wave 0 |
| all | `PollCompleted` accepts `"banned"` and `context_id`; the three committed golden `.events.jsonl` files remain byte-identical (B-7 regression guard) | unit | `pytest tests/unit/test_events_schema.py tests/unit/test_replay_determinism.py -x` | ✅ extend existing |
| all | Both non-success consumers mark UNKNOWN for `banned` (`consumer.py` **and** `scripts/replay_raw.py`) | unit | `pytest tests/unit/test_banned_marks_unknown.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit -x -q` — every arithmetic, verdict, fingerprint-coherence and grep-guard property is at the unit tier and needs neither a browser nor a container. Keep it under ~5 s.
- **Per wave merge:** `uv run pytest tests/unit tests/integration -v` plus `make lint` (`ruff check .` + `mypy shared/ services/`) and the three CI ban-greps. Budget ~3 s of browser time per browser test (measured 2.94 s for three).
- **Phase gate:** full suite green + SC1–SC5 demonstrated. SC1's *12-hour* run is human-gated; the automated gate is the 90 s CI soak plus the zombie guard, and `docs/runbooks/perf05-soak.md` carries `STATUS: pending-human-run`.

### Wave 0 Gaps

- [ ] `make browsers` → `uv run playwright install chromium` — **blocking**, nothing browser-related runs without it (§B-1)
- [ ] `tests/conftest.py`: `_chromium_available()` revision-aware guard + a shared `browser` fixture with the shielded `finally`
- [ ] `tests/fakes/resy_stub.py` — FastAPI app, `__ctl/mode`, `__ctl/hits`, and the `stub_base` fixture (the exact fixture in §Code Examples is verified working)
- [ ] `services/poller/sources/resy/fixtures.py` — `[ASSUMED]` `/4/find` bodies with `TODO(spike)` markers for: normal, empty-`venues`, missing-`results`, 429 body, 403 challenge HTML
- [ ] `shared/telemetry.py` redaction extension **before any cookie code exists** (§B-6)
- [ ] `scripts/seed/restaurants.yml` — `resy_venue_id_numeric` placeholders + `resy_slug` rename (§B-4); `scripts/seed_restaurants.py` — `-resy` slug suffix (§B-5)
- [ ] `shared/metrics.py` with explicit histogram buckets (§Pitfall 6)
- [ ] `tests/unit/factories.py` — extend with `make_resy_envelope(...)` so no Resy fixture reads a wall clock
- [ ] All 30 test files above (only `test_events_schema.py`, `test_replay_determinism.py` and `test_telemetry_redaction.py` exist and are extended)
- [ ] Framework install: **none** — pytest, pytest-asyncio, testcontainers, FastAPI, uvicorn, playwright, prometheus-client all present

**Nyquist note:** the riskiest properties are sampled at the *unit* tier and therefore on every commit — fingerprint coherence, canary verdicts, tier/backoff arithmetic, soak-verdict logic, the stealth script-name check, and the `no-sleep` grep. Only nine tests genuinely need a browser and only six need a container; keep everything else out of `tests/integration/`.

---

## Security Domain

`security_enforcement` is not set to `false` in `.planning/config.json`, so this section applies.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | partial | Not *our* authentication — we replay third-party session cookies. Never store them, never log them, never persist to DB (PROJECT.md constraint + PITFALLS §Pitfall 8) |
| V3 Session Management | **yes** | Cookies live only in `BrowserContext` memory (D-61); a context recycle discards them. `expires: -1` (session) is the correct and verified default |
| V4 Access Control | no | No multi-tenant surface in this phase |
| V5 Input Validation | **yes** | `/4/find` bodies are untrusted third-party JSON. `parse_resy` must never index-assume; `.json()` raises `JSONDecodeError` on a challenge page (verified) and must be caught. `RESY_ACCOUNTS_JSON` is validated by pydantic before any cookie is injected |
| V6 Cryptography | no | No keys, no encryption in this phase |
| V7 Error Handling & Logging | **yes** | §B-6 — the redactor is currently blind to `cookie`, `authorization`, `x-resy-auth-token`, `RESY_API_KEY` and `RESY_PROXY_URL`. Fix in Wave 0. Never log `raw_response` at INFO |
| V8 Data Protection | **yes** | `booking_token` is a third-party reservation handle; never log it at INFO. `RESY_PROXY_URL` embeds `user:pass` |
| V12 Files & Resources | **yes** | `scripts/soak_playwright.py` writes `logs/soak-<ts>.jsonl` from a `--duration`-driven loop; resolve the path and refuse to write outside the repo |
| V14 Configuration | **yes** | `playwright install` downloads 253 MB of executables from a CDN — make it an explicit, reviewable Wave 0 task, not an implicit side effect |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Session cookie leaked into a structlog line, a stack trace, or a Sentry event | Information Disclosure | §B-6 redaction extension + a unit test per key; never pass a raw header dict to a log call |
| Residential proxy credentials leaked via `RESY_PROXY_URL` in a log or an error string | Information Disclosure | Redact the exact key; when constructing `ProxySettings`, split `user`/`pass` into `username`/`password` so the URL string is never carried around whole |
| Malformed / hostile `/4/find` body crashes the poller or the state machine | Denial of Service | `ParseError` → UNKNOWN (D-39). Reproduced: `.json()` on a 403 challenge page raises `JSONDecodeError` |
| Zombie Chromium processes exhaust memory and the OOM killer reaps the poller | Denial of Service | Reproduced in §Pitfall 1; shielded `finally` + the PERF-05 PID gate |
| Unbounded Redis growth from ever-new canary/rate keys | Denial of Service | Every new key has a TTL: `rate:resy:{minute}` 90 s, `rate:resy:ctx:*` 45 s, `canary:resy:*` 3600 s, `backoff:*` 2× value, `resy:paused` 900 s. Redis runs `maxmemory-policy noeviction` [VERIFIED: ops/docker-compose.yml:43] so an untagged key is permanent |
| Self-inflicted ToS violation: exceeding the publicly promised 80 rpm / 45 s limits | Repudiation / legal | The budget Lua and the `SET NX EX 45` floor are the enforcement; `services/poller/sources/resy/README.md` must cite the enforcing functions by name so the public README's claim is auditable |
| Stealth applied with the library's random fingerprint, making the fleet *more* identifiable | Spoofing (failed) | §B-3 — coherent per-context opts, plus a unit test that no fingerprint row is internally inconsistent |
| `RESY_ENABLED=true` in an environment with no credentials silently polls anonymously and looks "healthy" | Repudiation | Anonymous mode logs a warning once (D-61) **and** must set a distinct Prometheus label so Grafana can tell anonymous traffic from authenticated |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The `/4/find` response is `results.venues[].slots[]` with `slot.date.start`, `slot.date.end`, `slot.config.type`, `slot.config.token`, `slot.size.{min,max}` | §D-66, `fixtures.py`, `parsers/resy.py` | Parser rewrite. Corroborated by two independent public sources — `jsonData["results"]["venues"][0]["slots"]`, `i["date"]["start"]`, `i["config"]["id"]` [CITED: https://github.com/leavenstee/hot-date/blob/master/resy.py] and a description of each slot carrying start/end, a seating `type` ("Dining Room", "Table", "Patio") and a booking token [CITED: https://apify.com/clearpath/resy-availability-api]. **Not verified live** — no calls to resy.com are permitted in this phase. Confined to one fixtures module and one parser by design |
| A2 | `config.token` (not `config.id`) is the field to store as `booking_token` | §D-66 | Public sources show **both** `config.id` and a "config token"; if only `id` is present, `booking_token` is null and Phase 4's deep link degrades to the venue page. Make the parser accept `token` and fall back to `id`, recording which it used |
| A3 | The `rgs://resy/...` token format | fixtures | Cosmetic — the token is opaque data, never parsed |
| A4 | `venue_id` is numeric and the numeric ids for the 31 Resy restaurants are unknown | §B-4 | Placeholder ids (`800000001+`) mean live polling returns nothing until the human DevTools capture lands. Identical in shape and risk to Phase 1's `opentable_rid: 900000001` placeholders, and gated the same way |
| A5 | `X-Resy-Auth-Token` is the correct header name for the per-account token | §D-64 | Corroborated: the header is written as `"x-resy-auth-token" -> [authToken]` [CITED: https://github.com/Alkaar/resy-booking-bot/blob/master/src/main/scala/com/resy/ResyApi.scala]; a sibling `X-Resy-Universal-Auth` also exists. Keep the header name in `config.py`, not hard-coded in the adapter |
| A6 | Resy's soft-ban presents as `200 OK` with sanitized/empty availability | §Pattern 7, POLL-06 | Single-source in the project's own research [CITED: .planning/research/PITFALLS.md §Pitfall 2, which itself flags LOW confidence]. If the real ban is a 403 challenge instead, the 403 rule already covers it — the design is deliberately belt-and-braces |
| A7 | `~/Library/Caches/ms-playwright` (macOS) / `~/.cache/ms-playwright` (Linux) is the browser root | §Code Examples guard | If `PLAYWRIGHT_BROWSERS_PATH` is set, the guard misreports. Prefer asking Playwright itself, or honour the env var in the guard |
| A8 | 4 contexts × 3 requests/poll stays under 80 rpm at ~50 restaurants on a 180 s baseline | §Pattern 6 | 50 venues ÷ 180 s × 3 req ≈ 50 rpm steady state, leaving headroom for confirmation re-polls. Arithmetic only — not measured against a live fleet. The budget Lua enforces the cap regardless |
| A9 | Two crashpad handlers re-parented to PID 1 always exit on `browser.close()` | §Pattern 8 | Observed once (`pgrep` → 0). If they ever linger, the PERF-05 PID gate (`max - min <= 2`) already tolerates exactly two |

---

## Open Questions

1. **Q1 — Is the Node-driver TLS fingerprint an acceptable risk for `/4/find`, given that the alternative costs ~178 MB per open page?**
   - What we know: `context.request` emits Node-shaped bytes, not Chrome-shaped ones (§B-9, captured verbatim). In-page `fetch()` from a `resy.com`-origin page produces the full native Chrome header set and Chromium's TLS stack (verified). Pages cost ~178 MB each and one extra OS process each (verified: 455 MB → 1 168 MB for four).
   - What's unclear: whether Resy's protection actually fingerprints TLS on `api.resy.com` XHR traffic. Cannot be determined without live calls, which this phase forbids.
   - **Recommendation:** ship D-64 as locked — `context.request` plus the explicit realistic header set from §B-9 — because it is the only option compatible with PERF-05. Structure `ResyAdapter` so the transport is one private method (`_fetch(ctx, url, headers) -> APIResponse`), so a future switch to a page-hosted `fetch()` is a single-method change rather than a rewrite. Record the tradeoff in `services/poller/sources/resy/README.md` and revisit only if the live canary shows bans that the header fix does not resolve.

2. **Q2 — How many `poll_loop` workers should run, and are they per-source or shared?**
   - What we know: the loop is strictly serial today and `main.py` runs exactly one (§Pitfall 4). The claim Lua is atomic, so N workers over one scheduler is safe with no change.
   - What's unclear: a shared worker pool means a slow Resy poll can starve OpenTable's 90 s cadence (POLL-03, already a Phase 1 gate).
   - **Recommendation:** run **two separate worker groups** filtered by source — one OpenTable worker (preserving today's exact behaviour and POLL-03) and `RESY_CONTEXTS` Resy workers. That needs a source filter in the claim, which the current Lua does not have; the cheapest correct version is one worker group of `1 + RESY_CONTEXTS` tasks plus an explicit note that a slow Resy poll can delay an OpenTable one by at most one poll duration. Raise with the user if OpenTable cadence isolation is considered load-bearing.

3. **Q3 — Should the Resy `restaurants` row reuse the OpenTable row's identity, or stand alone?**
   - What we know: `UNIQUE(slug)` blocks a second row with the same slug (§B-5, reproduced). `(source, platform_id)` is the documented join key (D-52).
   - What's unclear: whether Phase 6's heatmap wants one logical restaurant with two sources, or two independent rows.
   - **Recommendation:** two rows with `slug = f"{slug}-resy"` in this phase — it is the minimal change and keeps `(source, platform_id)` intact. Note explicitly in `services/poller/sources/resy/README.md` that Phase 6 will need a `restaurant_group` concept (or a `canonical_slug` column) to merge them for display, and log it in `.planning/deferred-items.md`. Do **not** invent that column here.

4. **Q4 — What is the `body_len_bucket` granularity in `ResponseSignature`?**
   - What we know: D-67 names the field but not its bucketing. Verified body lengths from the stub span 13–242 bytes; a real venue-day response will be kilobytes.
   - What's unclear: too-fine bucketing makes every response a new signature (the baseline becomes noise); too-coarse hides the "< 20 % of median" rule.
   - **Recommendation:** use a log2 bucket (`0 if n == 0 else int(math.log2(n))`), which is scale-free and stable, and keep the exact `body_len` as a *separate* field in the stored signature so the median rule is computed on raw bytes rather than on buckets. Both are one line and both are unit-testable.

5. **Q5 — Should the stale `chromium-1223` / `chromium_headless_shell-1223` directories be removed?**
   - What we know: they are ~500 MB of orphaned browsers installed by a newer Playwright (possibly the MCP chrome tooling also present in the cache).
   - What's unclear: whether another tool on this machine depends on them.
   - **Recommendation:** leave them. Mention the disk cost in `docs/runbooks/perf05-soak.md` (a soak run should not start with a nearly-full disk) but do not delete another tool's assets from a project task.

---

## Sources

### Primary (HIGH confidence — executed against the pinned artifacts this session, 2026-09-05)
- `.venv` introspection: `inspect.signature` / `getdoc` on `BrowserType.launch`, `Browser.new_context`, `BrowserContext.add_cookies`, `APIRequestContext.get`, `APIRequestContext.dispose`, `prometheus_client.start_http_server`, `playwright_stealth.stealth_async`, `StealthConfig.__init__`, `Properties.__init__`
- `playwright/driver/package/browsers.json` (pinned browser revisions) and `playwright_stealth/{stealth.py,core/_stealth_config.py,properties/_properties.py,js/*}` — read verbatim
- Live headless Chromium (Chrome for Testing 145.0.7632.6, revision 1208, `channel="chromium"` and headless shell): launch/context/page timings, process tree, RSS at 0/4-contexts/4-pages, cancellation leak and its mitigation, default-UA leak, `sec-ch-ua` leak, cookie validation matrix, stealth application matrix, `about:blank` vs HTTP-origin init-script failure, per-script bisect
- Raw HTTP wire capture via `asyncio.start_server` — byte-exact request lines for `context.request.get`, `page.goto`, in-page `fetch()`, and `extra_http_headers` merge behaviour
- Live `redis:7.2-alpine` → **7.2.16**: budget Lua (30 evals), `SET NX EX` floor semantics, `INCR`-without-`EXPIRE` TTL `-1`, `LPUSH`/`LTRIM`/`LRANGE`/`LLEN`, `pipeline(transaction=True)`, `HGET` miss → `None`, pause key TTL
- Live `postgres:16-alpine` — reproduced the `restaurants_slug_key` unique violation against migration 0003's schema
- `python:3.12-slim` via Docker — `getrusage` units on Linux vs `/proc/self/status`, and the absence of `ps`/`pgrep`
- `mypy --strict --python-version 3.12` against a probe module using the full Playwright + redis-py surface → `Success: no issues found`
- `pytest` 9.0.3 + `pytest-asyncio` 1.3.0 — in-process `uvicorn.Server` + real headless Chromium, 3 tests green in 2.94 s; `pytest.fixture(loop_scope=…)` `TypeError`; uvicorn signal save/restore
- `uvicorn/server.py:77-78, 322-334` — `capture_signals` source, read verbatim
- Repository source read this session: `services/poller/{main,config,scheduler,publisher}.py`, `services/poller/sources/base.py`, `services/state_machine/{consumer,engine,models}.py`, `services/state_machine/parsers/{__init__,errors}.py`, `shared/{events,redis_keys,telemetry,db}.py`, `scripts/{seed_restaurants,replay_raw,check_poll_success}.py`, `scripts/seed/restaurants.yml`, `migrations/versions/{0003,0007}_*.py`, `tests/conftest.py`, `tests/integration/conftest.py`, `tests/unit/{test_no_inline_sleep,test_no_setnx_expire_pairs}.py`, `tests/fixtures/raw_streams/*`, `pyproject.toml`, `.ruff.toml`, `Makefile`, `.env.example`, `.github/workflows/lint.yml`, `ops/docker-compose.yml`, `.planning/config.json`

### Secondary (MEDIUM confidence — project research, authored 2026-04-20)
- `.planning/research/PITFALLS.md` §Pitfall 1 (Playwright context leak / zombie PIDs / soak gate), §Pitfall 2 (Resy bot detection, soft-ban canary), §Concurrency table (semaphore per external dependency; ~20 polls per context), §Threats (cookie scrubbing)
- `.planning/research/ARCHITECTURE.md` §3 (4 contexts × 1 browser), §5 (rate limits at the scheduler, not the worker)
- `.planning/research/STACK.md` §Browser Automation (Playwright 1.58.0, `tf-playwright-stealth` 1.2.0 over `playwright-stealth@2.0.3`, `fake-http-header` as a transitive dep)
- `.planning/phases/02-state-machine-event-pipeline/02-RESEARCH.md` (Pitfall 3 `cast(Awaitable[T], …)`; B-4 coverage over-declaration, the pattern D-64's envelope prevents), `02-CONTEXT.md` D-36..D-56, `.planning/STATE.md` (the `services/poller/config.py` import-time env freeze)

### Tertiary (LOW confidence — flagged in §Assumptions Log)
- Resy `/4/find` request shape — [CITED: https://github.com/Alkaar/resy-booking-bot/blob/master/src/main/scala/com/resy/ResyApi.scala] `"lat" -> "0", "long" -> "0", "day" -> date, "party_size" -> partySize.toString, "venue_id" -> venueId.toString`; headers `"Authorization" -> "ResyAPI api_key=\"[apiKey]\""`, `"x-resy-auth-token" -> [authToken]`
- Resy `/4/find` response shape — [CITED: https://github.com/leavenstee/hot-date/blob/master/resy.py] `jsonData["results"]["venues"][0]["slots"]`, `i["date"]["start"]`, `i["config"]["id"]`
- Resy slot `config.type` values ("Dining Room", "Table", "Patio") and per-slot booking token — [CITED: https://apify.com/clearpath/resy-availability-api]
- Resy protection level — [CITED: https://scraperly.com/scrape/resy], single-source, already flagged LOW in the project's own PITFALLS.md

**No calls were made to resy.com or api.resy.com in this session**, per the phase constraint.

---

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — zero new packages; every version confirmed via `importlib.metadata` against the project `.venv`
- Playwright 1.58 API semantics (launch, context, cookies, `APIRequestContext`, proxy, errors, lifecycle): **HIGH** — every claim executed, with transcripts quoted inline
- `tf-playwright-stealth` 1.2.0 behaviour: **HIGH** — public surface, source, and runtime effects all reproduced, including the silent-throw failure mode
- Redis / Prometheus / uvicorn / pytest-asyncio semantics: **HIGH** — executed against the pinned versions and the pinned server image
- Blocking corrections B-1..B-9: **HIGH** — each reproduced as a concrete runtime error or a verbatim source contradiction
- Memory / process measurements: **HIGH** on macOS arm64 (measured); **MEDIUM** for Linux CI extrapolation (units verified in Docker, absolute figures not)
- Resy `/4/find` payload shape: **LOW** — `[ASSUMED]`, two independent public sources, isolated to `fixtures.py` + `parsers/resy.py` by design
- Soft-ban presentation: **LOW** — single-source, unverifiable without live traffic; the design covers both the 403 and the empty-200 presentations

**Research date:** 2026-09-05
**Valid until:** 2026-10-05 (30 days — every Python dependency is exact-pinned; the drift risks are the Chromium binary CDN and any change to Resy's protection stack, neither of which this repo controls)
