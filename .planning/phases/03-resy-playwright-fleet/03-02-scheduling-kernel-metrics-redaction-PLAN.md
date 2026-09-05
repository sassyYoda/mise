---
phase: 03-resy-playwright-fleet
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - shared/redis_keys.py
  - shared/telemetry.py
  - shared/metrics.py
  - tests/unit/test_tier_cadence.py
  - tests/unit/test_effective_interval.py
  - tests/unit/test_jitter_bounds.py
  - tests/unit/test_backoff_math.py
  - tests/unit/test_telemetry_redaction.py
  - tests/unit/test_metrics_registry.py
  - tests/integration/test_rate_budget_lua.py
autonomous: true
requirements: [POLL-02, POLL-05, POLL-06]

estimate:
  tokens: 60000
  raw_tokens: 60000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`tier_interval_seconds(active_watches)` returns 60 for >= 10 watches, 180 for 3-9, and 600 for 0-2, and `effective_interval_seconds(source, active_watches, override)` returns `min(tier, baseline[source])` clamped up to the per-source minimum — OpenTable never exceeds its 90 s baseline, Resy never drops below 45 s (D-57)."
    - "PROBE POLL-05/boundary: the minute budget grants when `current + cost == cap` and refuses when `current + cost == cap + 1`, and refusing consumes none of the budget; the per-context floor grants once at 45 s TTL and returns falsy on the immediately following attempt without sliding the TTL (D-65, research §Pattern 6)."
    - "PROBE POLL-05/adjacency: two acquisitions that touch exactly — the same `(context_id, venue_id)` at the same instant, and a budget request that lands exactly on the cap — resolve to exactly one winner; they neither both succeed nor both fail (`SET NX EX` returns `None`, not `False`, for the loser)."
    - "PROBE POLL-05/precision: every arithmetic boundary is integer-exact — the rate key's `epoch_minute` is `now_ms // 60_000`, jitter is `int(random.uniform(-j, j))` bounded by `+/- 15 %` and never negative-net, and backoff is `min(interval * 2 ** n, 1800)` with an integer TTL of `2 * value` (D-57, D-59, D-65)."
    - "PROBE POLL-05/concurrency: 30 concurrent budget calls at cost 3 against cap 80 grant exactly 26 and refuse 4, and the counter carries a TTL after the FIRST increment — a bare `INCR` without the Lua would leave a permanent key (`ttl == -1`), verified against a live Redis 7.2 container."
    - "`shared/telemetry.py` redacts, case-insensitively, every one of `cookie`, `cookies`, `set-cookie`, `auth_token`, `x-resy-auth-token`, `authorization`, `api_key`, plus exact `RESY_API_KEY` and `RESY_PROXY_URL` (credentials masked), in addition to the four keys it already covered (D-61a, research B-6)."
    - "`shared/metrics.py` imports twice in one process without raising `Duplicated timeseries in CollectorRegistry`, and `poll_latency_seconds` declares explicit buckets extending past 10 s (D-69, research §Pitfall 6)."
  artifacts:
    - shared/metrics.py
    - tests/unit/test_tier_cadence.py
    - tests/unit/test_effective_interval.py
    - tests/unit/test_jitter_bounds.py
    - tests/unit/test_backoff_math.py
    - tests/unit/test_metrics_registry.py
    - tests/integration/test_rate_budget_lua.py
  key_links:
    - "`RESY_BUDGET_LUA` -> `shared/redis_keys.py` -> the poller's pre-dispatch gate (03-06) — the ONLY place the 80 rpm cap is enforced; bypassing it breaks the promise the public README makes."
    - "`effective_interval_seconds` -> `_next_poll_score(now_ms, interval_seconds)` (03-06) — the tier result only reaches production through the release path's ZSET score, never through a sleep."
    - "`shared/metrics.py` module-level definitions -> every importer — a second definition site anywhere raises at import and takes the poller down."
  prohibitions:
    - "MUST NOT write a Resy session cookie, `X-Resy-Auth-Token` value, `booking_token`, `RESY_API_KEY`, or the credential half of `RESY_PROXY_URL` into Postgres, a Kafka payload, `poll_log`, a structlog line, or any file on disk — these are a third party's credentials, replayed under a human's supervision, not the project's own secrets."
---

<objective>
Build the arithmetic and Redis primitives every later plan depends on — tier cadence, backoff,
the atomic minute budget, the per-context floor — plus the metric registry and the secret redaction
that must exist BEFORE a single cookie is handled.

Purpose: POLL-02 and POLL-05 are enforcement promises the public README already makes. Enforcement
must live in Redis (atomic) and in pure functions (unit-testable with no clock), not in the browser
worker, which is too late to be polite.
Output: new keys, helpers and one Lua script in `shared/redis_keys.py`; a new `shared/metrics.py`;
an extended redactor; and the unit + integration tests that pin every boundary.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/03-resy-playwright-fleet/03-CONTEXT.md
@.planning/phases/03-resy-playwright-fleet/03-PATTERNS.md
</context>

<tasks>

<task type="tracer">
  <name>Task 1: End-to-end tracer — one Resy job's full scheduling decision, computed against a live Redis</name>
  <files>shared/redis_keys.py, tests/integration/test_rate_budget_lua.py</files>
  <read_first>
    - shared/redis_keys.py in full (the key-function convention, `set_nx_ex` and its `result is True` return, the `cast(Awaitable[T], ...)` block and its docstring rule, `CLAIM_POLL_LUA` / `EXPEDITE_POLL_LUA` commentary density, `POLL_INTERVAL_SECONDS` / `POLL_JITTER_FRACTION`)
    - shared/scheduler/lua.py (the `script_load` + `_evalsha_with_fallback` NOSCRIPT pattern)
    - tests/integration/test_expedite_lua.py and tests/integration/test_scheduler_claim_release.py (the container fixture wiring and Lua assertion style)
    - tests/integration/conftest.py lines 1-70 (`redis_url` fixture)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pattern 6 and §Code Examples "Minute-budget Lua" (the exact script, executed against Redis 7.2.16) and "Per-context floor and the canary window"
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-57, §D-58, §D-59, §D-65
  </read_first>
  <action>
Extend `shared/redis_keys.py` with the Phase-3 key registry and the arithmetic. Every key gets a
`def *_key(...) -> str` with a decision-ID docstring, exactly as `avail_state_key` and
`sched_expedite_key` do, and every new redis-py command gets its `cast(Awaitable[T], ...)` helper
HERE and nowhere else — the module docstring states that rule and downstream service modules must
contain zero inline casts.

Keys and constants to add:
`rate_minute_key(epoch_minute: int) -> "rate:resy:{minute}"` with `RESY_RATE_TTL_SECONDS = 90`;
`rate_ctx_venue_key(context_id: str, venue_id: int) -> "rate:resy:ctx:{ctx}:{venue}"` with
`RESY_CTX_FLOOR_SECONDS = 45`; `canary_key(venue_id: int) -> "canary:resy:{venue}"` with
`CANARY_WINDOW_SIZE = 20` and `CANARY_TTL_SECONDS = 3600`; `backoff_key(source, restaurant_id) ->
"backoff:{source}:{rid}"`; `RESY_PAUSED_KEY = "resy:paused"` with `RESY_PAUSE_TTL_SECONDS = 900`;
`WATCH_COUNT_HASH = "watch:count"` and `TIER_OVERRIDE_HASH = "tier:override"` with
`watch_count_field(source, restaurant_id)` / `tier_override_field(source, restaurant_id)` producing
`"{source}:{restaurant_id}"`. Also add `RESY_BASELINE_INTERVAL_SECONDS_DEFAULT = 180`,
`RESY_MIN_INTERVAL_SECONDS = 45`, `RESY_GLOBAL_RPM_DEFAULT = 80`, `BACKOFF_MAX_SECONDS = 1800`,
`RATE_REFUSAL_RETRY_MS = 5_000` and `FLEET_PAUSE_RETRY_MS = 60_000`. Every TTL is mandatory: the
pinned Redis runs `maxmemory-policy noeviction`, so an untagged key is permanent.

Pure functions (no clock, no IO, no entropy except the explicitly-seeded jitter draw):
`tier_interval_seconds(active_watches: int) -> int` -> 60 / 180 / 600 per the POLL-02 tiers;
`effective_interval_seconds(source: str, active_watches: int, override: int | None = None) -> int`
-> when `override` is 1/2/3 it selects the tier directly, otherwise the computed tier; the result is
`min(tier, baseline_for(source))` and is then raised to the per-source minimum. OpenTable's baseline
is `POLL_INTERVAL_SECONDS` (90) and its minimum is also 90 — watches may only speed polling up,
never slow the heatmap collection down (POLL-03 floor). Resy's baseline is a caller-supplied
argument defaulting to 180 and its minimum is 45.
`jittered_score_ms(now_ms: int, interval_seconds: int) -> int` -> `now_ms + interval_ms +
int(random.uniform(-jitter_ms, +jitter_ms))` using the existing `POLL_JITTER_FRACTION` as the single
source of the +/- 15 %.
`next_backoff_seconds(interval_seconds: int, consecutive_failures: int) -> int` ->
`min(interval_seconds * 2 ** consecutive_failures, BACKOFF_MAX_SECONDS)`, and
`backoff_ttl_seconds(backoff_seconds: int) -> int` -> `2 * backoff_seconds`.

Add `RESY_BUDGET_LUA` verbatim in shape from research §Code Examples: `KEYS[1]` the minute key,
`ARGV[1]` cost, `ARGV[2]` cap, `ARGV[3]` ttl; it GETs the current value, refuses with
`{0, cur, cap - cur}` when `cur + cost > cap`, otherwise `INCRBY`s and sets the EXPIRE only when the
new value equals the cost (first increment of this minute). Carry the `EXPEDITE_POLL_LUA` commentary
density: state that the refusal is deliberately conservative (cost 3 against cap 80 stops at 78),
that a bare `INCR` followed by a separate `EXPIRE` would leave a permanent counter if the process
died between the two commands, and that this is the only place the publicly promised cap is enforced.

Add the typed async helpers the later plans need — `incrby`, `getdel_str`, `hget_field`, `lpush_sig`,
`ltrim_window`, `lrange_window`, `set_str_ex`, `delete_key` — each a one-line
`await cast(Awaitable[T], r.<command>(...))` with a docstring, and add a
`canary_window_push(r, key, sig, size, ttl) -> list[bytes]` that issues LPUSH + LTRIM + LRANGE +
EXPIRE in a single `r.pipeline(transaction=True)` so a concurrent poll cannot read a half-updated
window. Update the module's `Named symbols:` docstring list with every new name.

Write `tests/integration/test_rate_budget_lua.py` as the tracer: against the module-scoped Redis
container, load `RESY_BUDGET_LUA` with `script_load` and drive one Resy job's complete scheduling
decision end to end — seed `watch:count` and `tier:override` via HSET, read them back through the
new helpers, compute `effective_interval_seconds`, take a `jittered_score_ms`, then call the budget
script and the `set_nx_ex` floor. Assert the boundary, adjacency, precision and concurrency
properties named in `must_haves.truths`: the exact-cap grant, the cap-plus-one refusal, that a
refusal leaves the counter unchanged, the 90 s TTL after the first increment only, 30 concurrent
`asyncio.gather` calls granting exactly 26 at cost 3 / cap 80, the falsy second `SET NX EX` on the
same `(ctx, venue)`, and that the floor's TTL does not slide.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_rate_budget_lua.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_rate_budget_lua.py -q -p no:cacheprovider` exits 0 (or skips with the existing Docker-guard message when no Docker runtime is reachable).
    - `uv run pytest tests/unit -q` exits 0 — the existing `tests/unit/test_redis_keys.py`, `test_redis_keys_phase2.py` and `test_no_setnx_expire_pairs.py` all stay green.
    - `uv run python -c "from shared import redis_keys as k; print(k.tier_interval_seconds(12), k.tier_interval_seconds(9), k.tier_interval_seconds(2), k.effective_interval_seconds('opentable', 12), k.effective_interval_seconds('resy', 12))"` prints `60 180 600 90 60`.
    - `grep -c "cast(Awaitable" shared/redis_keys.py` returns a value strictly greater than its pre-plan count.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>One Resy job's watch-count -> tier -> interval -> jitter -> budget -> floor decision runs end to end against a live Redis, with every boundary pinned.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Secret redaction and the single metric definition site</name>
  <files>shared/telemetry.py, shared/metrics.py, tests/unit/test_telemetry_redaction.py, tests/unit/test_metrics_registry.py</files>
  <read_first>
    - shared/telemetry.py lines 17-32 (`_redact_secrets` and its four-key set) and lines 34-75 (the processor chain)
    - tests/unit/test_telemetry_redaction.py (the existing assertions to extend, not replace)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §B-6 (the reproduced leak of six of eight secret-bearing keys, including the proxy URL with embedded credentials)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pitfall 6 (the `Duplicated timeseries` reproduction, the `scrape_ban_total` vs `scrape_ban_total_total` sample-name trap, the default buckets stopping at 10.0)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Code Examples "Prometheus in an asyncio process"
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-61a, §D-69
    - shared/redis_keys.py lines 1-10 (the `Named symbols:` docstring convention every shared module follows)
  </read_first>
  <behavior>
    - Given an event dict carrying `cookie`, `Cookie`, `cookies`, `set-cookie`, `auth_token`, `x-resy-auth-token`, `X-Resy-Auth-Token`, `authorization`, `Authorization`, `api_key`, `RESY_API_KEY`, the redactor replaces every value with the existing `[REDACTED]` sentinel.
    - Given `RESY_PROXY_URL` = a URL with embedded `user:pass`, the emitted value retains scheme/host/port but the credential segment is masked.
    - The four pre-existing keys (`TWILIO_AUTH_TOKEN`, `HMAC_MGMT_SECRET_V1`, `VAPID_PRIVATE_KEY`, `RESY_ACCOUNTS_JSON`) and the `RESY_ACCOUNT_*_PASSWORD` prefix rule still redact.
    - A benign key such as `restaurant_id` or `latency_ms` passes through untouched (the redactor is not over-broad).
    - `importlib.import_module("shared.metrics")` twice in one interpreter raises nothing.
    - `get_sample_value("scrape_ban_total", {"source": "resy", "reason": "empty_results"})` returns a float after one `.inc()`; `get_sample_value("scrape_ban_total_total", ...)` returns `None`, and the test asserts the FIRST is a number rather than asserting the second is `None`.
    - `poll_latency_seconds` has a bucket boundary above 10 seconds.
  </behavior>
  <action>
Extend `shared/telemetry.py::_redact_secrets`: keep the existing exact-match set and the
`RESY_ACCOUNT_*_PASSWORD` rule, and add a case-insensitive match set covering `cookie`, `cookies`,
`set-cookie`, `auth_token`, `x-resy-auth-token`, `authorization`, `api_key`, plus exact
`RESY_API_KEY`. Handle `RESY_PROXY_URL` (and `proxy_url`, case-insensitively) specially: mask the
credential segment rather than the whole value, so an operator can still see which proxy host was in
play while the password never reaches a log. Keep the function pure and allocation-cheap — it runs on
every log call. Note in the docstring that the redactor is key-name based and therefore cannot save a
caller who logs a whole header dict under a benign key, which is why the adapter is forbidden from
logging `raw_response` or a header mapping at INFO.

Create `shared/metrics.py` defining every Phase-3 metric EXACTLY ONCE against the default
`prometheus_client.REGISTRY`: `scrape_ban_total` (Counter, labels `source`, `reason`),
`poll_latency_seconds` (Histogram, label `source`, explicit buckets
`(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)` — the library default stops at 10.0 and a
three-request Playwright poll can exceed it), `poll_total` (Counter, labels `source`, `status`),
`resy_context_recycles_total` (Counter, label `reason`), `resy_rate_budget_remaining` (Gauge),
`playwright_contexts_active` (Gauge), and `resy_auth_mode` (Gauge, label `mode`) so Grafana can tell
anonymous traffic from authenticated (research §Security Domain). Give the module the standard
`Named symbols:` docstring and a prominent comment stating: this module is defined once and must
never be `importlib.reload`ed or evicted from `sys.modules` by a test fixture, because a second
definition against the default registry raises `Duplicated timeseries`; and that `Counter("x_total")`
is stored internally as `x` and emits samples `x_total` + `x_created`, so tests must read
`get_sample_value("scrape_ban_total", labels)`.

Extend `tests/unit/test_telemetry_redaction.py` with one assertion per key in `<behavior>` plus the
pass-through case, and write `tests/unit/test_metrics_registry.py` covering the double-import, the
sample-name trap (asserting a numeric value from the correct name), and the histogram bucket bound.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_telemetry_redaction.py tests/unit/test_metrics_registry.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_telemetry_redaction.py tests/unit/test_metrics_registry.py -q` exits 0.
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run python -c "import importlib, shared.metrics as m; importlib.import_module('shared.metrics'); print('ok')"` prints `ok`.
    - `grep -c "def test_" tests/unit/test_telemetry_redaction.py` returns a value strictly greater than its pre-plan count.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>Every secret-bearing key name this phase introduces is redacted, and every Phase-3 metric has exactly one definition site that survives a double import.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Unit matrix for tier, interval, jitter and backoff arithmetic</name>
  <files>tests/unit/test_tier_cadence.py, tests/unit/test_effective_interval.py, tests/unit/test_jitter_bounds.py, tests/unit/test_backoff_math.py</files>
  <read_first>
    - shared/redis_keys.py (the functions written in Task 1)
    - tests/unit/test_service_time_math.py and tests/unit/test_redis_keys_phase2.py (the pure-math table-test style this repo uses)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Validation Architecture, the four POLL-02 unit rows (the exact boundary values named there)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-57, §D-58, §D-59
    - .planning/REQUIREMENTS.md line 22 (the literal POLL-02 tier wording)
  </read_first>
  <behavior>
    - `tier_interval_seconds`: 100 -> 60, 10 -> 60, 9 -> 180, 3 -> 180, 2 -> 600, 1 -> 600, 0 -> 600. Boundaries asserted on BOTH sides of 2/3 and 9/10.
    - A negative watch count is treated as 0 rather than raising (`watch:count` is written by a future phase and must never crash the poller).
    - `effective_interval_seconds("opentable", 100)` == 90 and `effective_interval_seconds("opentable", 0)` == 90 — watches only speed polling up.
    - `effective_interval_seconds("resy", 100)` == 60, `("resy", 5)` == 180, `("resy", 0)` == 180 with the default baseline; with a baseline argument of 30 the result is clamped up to 45.
    - `override=1|2|3` selects 60/180/600 regardless of the watch count, and still passes through the per-source clamp; `override=None` and an out-of-range override fall back to the computed tier.
    - `jittered_score_ms`: over 1000 draws every result lies in `[now + 0.85 * interval_ms, now + 1.15 * interval_ms]`, no result is <= `now`, and at least two distinct values are produced (a constant would satisfy a bounds-only assertion).
    - `next_backoff_seconds(180, 0..5)` == 180, 360, 720, 1440, 1800, 1800 (the cap engages between n=3 and n=4); `backoff_ttl_seconds(v) == 2 * v` for each.
  </behavior>
  <action>
Write the four unit files, one property family each, as parametrised table tests. Every expected
value is a literal, never re-derived from the function under test. Include the boundary pairs on
both sides of every threshold — a test that only checks the midpoints cannot catch an off-by-one in
a `>=` comparison. The jitter test must seed `random` explicitly (or pass a seeded `Random`) so it is
reproducible, and must include the distinct-values assertion so a stubbed-out jitter cannot pass.
The backoff test asserts the exact sequence including the value at which the 1800 s cap engages.
Add a short module docstring to each file naming the requirement (POLL-02) and the decision it pins.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_tier_cadence.py tests/unit/test_effective_interval.py tests/unit/test_jitter_bounds.py tests/unit/test_backoff_math.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_tier_cadence.py tests/unit/test_effective_interval.py tests/unit/test_jitter_bounds.py tests/unit/test_backoff_math.py -q` exits 0.
    - `uv run pytest tests/unit -q` exits 0 and completes in under 15 seconds.
    - `grep -c "def test_" tests/unit/test_tier_cadence.py tests/unit/test_effective_interval.py tests/unit/test_jitter_bounds.py tests/unit/test_backoff_math.py` reports a non-zero count for each of the four files.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>Every POLL-02 tier boundary, clamp, override, jitter bound and backoff step is pinned by a literal-valued unit test that runs on every commit.</done>
</task>

</tasks>

## Artifacts this phase produces (plan 02)

| Kind | Symbol / path | Notes |
|------|---------------|-------|
| redis key helper | `rate_minute_key(epoch_minute) -> "rate:resy:{minute}"` | TTL `RESY_RATE_TTL_SECONDS` = 90 |
| redis key helper | `rate_ctx_venue_key(context_id, venue_id) -> "rate:resy:ctx:{ctx}:{venue}"` | TTL `RESY_CTX_FLOOR_SECONDS` = 45 |
| redis key helper | `canary_key(venue_id) -> "canary:resy:{venue}"` | TTL `CANARY_TTL_SECONDS` = 3600 |
| redis key helper | `backoff_key(source, restaurant_id) -> "backoff:{source}:{rid}"` | TTL = 2x value |
| redis key | `RESY_PAUSED_KEY = "resy:paused"` | TTL `RESY_PAUSE_TTL_SECONDS` = 900 |
| redis key | `WATCH_COUNT_HASH = "watch:count"` | field `watch_count_field(source, rid)` |
| redis key | `TIER_OVERRIDE_HASH = "tier:override"` | field `tier_override_field(source, rid)` |
| constant | `RESY_BASELINE_INTERVAL_SECONDS_DEFAULT = 180` | |
| constant | `RESY_MIN_INTERVAL_SECONDS = 45` | POLL-05 floor |
| constant | `RESY_GLOBAL_RPM_DEFAULT = 80` | POLL-05 cap |
| constant | `BACKOFF_MAX_SECONDS = 1800` | |
| constant | `CANARY_WINDOW_SIZE = 20` | |
| constant | `RATE_REFUSAL_RETRY_MS = 5_000` | |
| constant | `FLEET_PAUSE_RETRY_MS = 60_000` | |
| function | `tier_interval_seconds(active_watches) -> int` | pure |
| function | `effective_interval_seconds(source, active_watches, override=None, baseline_seconds=None) -> int` | pure |
| function | `jittered_score_ms(now_ms, interval_seconds) -> int` | pure + seeded entropy |
| function | `next_backoff_seconds(interval_seconds, consecutive_failures) -> int` | pure |
| function | `backoff_ttl_seconds(backoff_seconds) -> int` | pure |
| lua script | `RESY_BUDGET_LUA` | KEYS[1]=minute key; ARGV=cost, cap, ttl; returns `{granted, count_after, remaining}` |
| redis helper | `incrby`, `getdel_str`, `hget_field`, `lpush_sig`, `ltrim_window`, `lrange_window`, `set_str_ex`, `delete_key` | typed `cast(Awaitable[T], ...)` wrappers |
| redis helper | `canary_window_push(r, key, sig, size, ttl) -> list[bytes]` | single MULTI/EXEC |
| module | `shared/metrics.py` | single definition site |
| metric | `scrape_ban_total{source,reason}` | Counter |
| metric | `poll_latency_seconds{source}` | Histogram, explicit buckets to 60 s |
| metric | `poll_total{source,status}` | Counter |
| metric | `resy_context_recycles_total{reason}` | Counter |
| metric | `resy_rate_budget_remaining` | Gauge |
| metric | `playwright_contexts_active` | Gauge |
| metric | `resy_auth_mode{mode}` | Gauge (`authenticated` \| `anonymous`) |

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| poller -> Resy | Outbound request volume crosses a publicly promised limit; the only enforcement point is Redis |
| any code -> structlog | Secret-bearing values cross into log sinks, stack traces and (from Phase 7) Sentry |
| `watch:count` / `tier:override` writer (Phase 5) -> this phase | Values written by a future phase are read here with no schema guarantee |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-03-05 | Information Disclosure | `shared/telemetry.py::_redact_secrets` | critical | mitigate | Case-insensitive redaction of the eight leaking keys reproduced in research B-6, plus credential masking of `RESY_PROXY_URL`; one unit assertion per key. Landed BEFORE any cookie-handling code exists |
| T-03-06 | Repudiation | `RESY_BUDGET_LUA` | high | mitigate | Cap enforced server-side in one atomic script with a conservative refusal, so the 80 rpm figure the public README commits to cannot be exceeded by a race between workers |
| T-03-07 | Denial of Service | new Redis keys | medium | mitigate | Every new key carries an explicit TTL constant (90 / 45 / 3600 / 2x / 900 s); the pinned server runs `maxmemory-policy noeviction`, so an untagged key would be permanent |
| T-03-08 | Denial of Service | `shared/metrics.py` | medium | mitigate | Single module-level definition site plus a double-import regression test — a duplicate registration raises at import and would take the poller down at start |
| T-03-09 | Tampering | `watch:count` / `tier:override` reads | medium | mitigate | Both are parsed defensively with a default of 0 / `None`; a negative, absent or non-integer value degrades to the slowest tier rather than raising inside `poll_loop` |
| T-03-SC | Tampering | npm/pip/cargo installs | low | accept | No new packages; `prometheus-client==0.25.0` and `redis==7.4.0` are already pinned in `uv.lock` and were audited at Phase 1 (research §Package Legitimacy Audit) |
</threat_model>

## Flagged assumptions (probe, unresolved — review manually)

- **POLL-02 / unclassified** — the edge probe could not classify POLL-02 (`three tiers with +/-15 %
  jitter and exponential backoff on 429/503`). Carried forward as an explicit assumption rather than
  auto-resolved: the requirement text does not state what the tier is when the watch count is
  *unavailable* (Phase 5 has not shipped `watch:count`), nor whether backoff resets on the first
  success or after a sustained clean window. This plan implements the D-58 default of 0 watches
  (slowest tier) and the D-59 reset-on-next-success rule; both are recorded here so a reviewer can
  contradict them without archaeology.

<verification>
- `uv run pytest tests/unit -q` exits 0.
- `uv run pytest tests/integration/test_rate_budget_lua.py -q -p no:cacheprovider` exits 0 or skips with the Docker-guard message.
- `uv run ruff check . && uv run mypy shared/ services/` exits 0.
- `uv run pytest tests/unit/test_no_setnx_expire_pairs.py -q` exits 0 — the minute budget is one Lua script and the floor is a single `SET NX EX`.
</verification>

<success_criteria>
- Tier, interval, jitter and backoff arithmetic is pure, unit-tested and boundary-exact.
- The 80 rpm cap and the 45 s floor are enforceable atomically in Redis, verified against a live 7.2 container.
- Every secret-bearing key name introduced by this phase is redacted before any cookie code exists.
- Every Phase-3 metric has exactly one definition site.
</success_criteria>

<output>
Create `.planning/phases/03-resy-playwright-fleet/03-02-SUMMARY.md` when done.
</output>
</content>
