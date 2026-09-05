---
phase: 03-resy-playwright-fleet
plan: 05
type: execute
wave: 3
depends_on: [03-01, 03-02, 03-03, 03-04]
files_modified:
  - services/poller/sources/resy/accounts.py
  - services/poller/sources/resy/pool.py
  - services/poller/sources/resy/adapter.py
  - services/poller/sources/resy/canary.py
  - services/poller/sources/resy/README.md
  - services/poller/sources/registry.py
  - tests/unit/test_resy_accounts.py
  - tests/unit/test_resy_envelope.py
  - tests/unit/test_response_signature.py
  - tests/unit/test_canary_verdict.py
  - tests/unit/test_no_inline_sleep_resy.py
  - tests/integration/test_context_pool.py
  - tests/integration/test_fingerprint_rotation.py
  - tests/integration/test_anonymous_mode.py
  - tests/integration/test_resy_request_headers.py
  - tests/integration/test_canary_window.py
autonomous: true
requirements: [POLL-04, POLL-05, POLL-06]

estimate:
  tokens: 70000
  raw_tokens: 70000
  tasks: 4
  confidence: low

must_haves:
  truths:
    - "`ContextPool.start()` launches exactly ONE Chromium browser and creates `RESY_CONTEXTS` contexts, each with its own fingerprint row, its own account's cookies, the realistic header set and the stealth init script; `acquire()` / `release()` round-trips through an `asyncio.Semaphore(N)` plus an idle queue with no third-party pool framework (D-60)."
    - "`ResyAdapter.poll(rid, dates, party_sizes)` issues one `GET {RESY_API_BASE}/4/find` per `(date, party_size)` pair through `context.request` — never a page load — and returns the D-64 envelope `{\"requests\": [{date, party_size, status, body}, ...]}` whose entries record the ACTUAL status of each request (D-64)."
    - "PROBE POLL-04/concurrency: `RESY_CONTEXTS` concurrent `acquire()` calls all succeed and the `N+1`-th blocks until a release; a task cancelled mid-poll runs its shielded teardown and leaves ZERO `ms-playwright` processes; no context is ever handed to two callers at once (research §Pitfall 1, §Pattern 3)."
    - "The stub's hit log for a `/4/find` request shows `Accept-Language`, `sec-ch-ua`, `sec-ch-ua-platform`, `Sec-Fetch-Dest`, `Sec-Fetch-Mode`, `Sec-Fetch-Site`, `Origin`, `Referer`, `Authorization`, `X-Origin` and the configured auth-token header — `APIRequestContext` sends none of these by itself, so POLL-04's 'realistic request headers' is satisfied explicitly (D-64a, research B-9)."
    - "Both `RESY_ACCOUNTS_JSON` cookie shapes — a `{name: value}` object and an explicit Playwright cookie list — normalise to `domain=\".resy.com\", path=\"/\", secure=True`, and a host-only `resy.com` domain in operator input logs a warning; a `url=`-form cookie would never reach `api.resy.com` (D-61, research §Pitfall 5)."
    - "With `RESY_ACCOUNTS_JSON` unset or empty the pool still starts, logs `resy_anonymous_mode` exactly once, and sets the `resy_auth_mode` metric to the anonymous label — the fleet is never silently unauthenticated."
    - "`response_signature(status, headers, text)` is deterministic for equal inputs and stores `body_len_bucket = 0 if n == 0 else int(log2(n))` alongside the raw `body_len`, so the '< 20 % of the baseline median' rule is computed on raw bytes (D-67b)."
    - "`ban_verdict(new_signature, window)` is a PURE function replayable with no Redis, returning a ban reason for: a 403 carrying a challenge body, a 429, three consecutive empty-200s against a baseline whose majority had venues, and a body length under 20 % of the baseline median — and returning None for TWO consecutive empty-200s and for a venue whose baseline was already empty (D-67, research §Pitfall 10)."
    - "The canary window keeps exactly `CANARY_WINDOW_SIZE` entries after 25 pushes and is written in a single MULTI/EXEC so a concurrent poll cannot read a half-updated window (D-67)."
    - "No file under `services/poller/sources/resy/` contains an `asyncio.sleep(` or `time.sleep(` call — the 45 s floor, the 80 rpm cap and the 429 backoff are all ZSET scores, never waits."
  artifacts:
    - services/poller/sources/resy/accounts.py
    - services/poller/sources/resy/pool.py
    - services/poller/sources/resy/adapter.py
    - services/poller/sources/resy/canary.py
    - services/poller/sources/resy/README.md
    - services/poller/sources/registry.py
    - tests/integration/test_context_pool.py
    - tests/unit/test_canary_verdict.py
    - tests/unit/test_no_inline_sleep_resy.py
  key_links:
    - "`ContextPool` -> `ResyAdapter._fetch(ctx, url, headers)` — the single transport method; Q1 records that `context.request` is the Node driver, not Chromium, so a future switch to a page-hosted `fetch()` must remain a one-method change."
    - "`AvailabilitySource` ABC -> `ResyAdapter` -> `ADAPTERS` registry (`services/poller/sources/registry.py`) — the dispatch table that replaces `poll_loop`'s `if source ==` branch in 03-06."
    - "`ResponseSignature` -> `canary_window_push` (`shared/redis_keys.py`) -> `ban_verdict` -> the ban reaction in 03-06 — verdict is pure, Redis only stores the window."
  prohibitions:
    - "MUST NOT automate Resy account creation, login, credential entry, password reset, or booking; the fleet may only replay cookies a human captured under supervision and may never take an action that reserves a table."
    - "MUST NOT load an HTML page to obtain availability, and MUST NOT issue a request to any `resy.com` host from a test, a fixture or a CI run — every automated check targets the in-process stub on 127.0.0.1."
    - "MUST NOT run the fleet unauthenticated without a visible signal: anonymous mode must log once at WARNING and carry a distinct metric label, so a deployment with no credentials can never look healthy in Grafana."
---

<objective>
Build the fleet: a one-browser context pool with per-context identity and cookies, an adapter that
calls `/4/find` directly through the context's request client, and a pure soft-ban canary.

Purpose: POLL-04 and POLL-05 in one vertical slice. Contexts cost 2-7 ms and no OS process; pages
cost ~178 MB each — the no-page-loads design is what makes PERF-05 achievable, so the adapter's
transport must be isolated in one method and never grow a page.
Output: `pool.py`, `accounts.py`, `adapter.py`, `canary.py`, the source registry, the package README
that cites the enforcing functions the public README promises, and the browser + Redis tests.
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
  <name>Task 1: End-to-end tracer — the pool acquires a stealthed context and the adapter polls the stub through it</name>
  <precondition>`make browsers` (03-04) has been run: `_chromium_available()` in `tests/conftest.py` returns True for the pinned revision.</precondition>
  <files>services/poller/sources/resy/accounts.py, services/poller/sources/resy/pool.py, services/poller/sources/resy/adapter.py, services/poller/sources/registry.py, tests/integration/test_context_pool.py, tests/integration/test_resy_request_headers.py</files>
  <read_first>
    - services/poller/sources/base.py (the `AvailabilitySource` ABC — the signature is fixed; the envelope goes in the return value)
    - services/poller/sources/opentable/adapter.py (the constructor-injection rule and the `_fetch` / `poll` split to copy — but NOT its `asyncio.sleep` 429 handling and NOT its tenacity decorator, both of which are wrong for Resy)
    - shared/scheduler/lua.py lines 29-47 (the `__init__` stores handles / `async def start()` does async setup / `assert ... "Call start() first"` lifecycle class shape)
    - shared/http_client.py (the one-shared-resource-per-process idiom)
    - services/poller/config.py (the lazy Resy readers from 03-03)
    - services/poller/sources/resy/fingerprints.py, stealth.py (03-04)
    - shared/redis_keys.py (`rate_ctx_venue_key`, `RESY_CTX_FLOOR_SECONDS`, `set_nx_ex` — the floor primitive the pool consults when choosing a context)
    - shared/metrics.py (`playwright_contexts_active`, `resy_context_recycles_total`, `resy_auth_mode`, `poll_latency_seconds`)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pattern 3 (measured context/page costs and recycle timing), §Pattern 5 (the verified `APIRequestContext` semantics: 4xx/5xx returned not raised, `.json()` raising on a challenge page, the `Error`/`TimeoutError` hierarchy, cookie host-matching), §B-9 + §Code Examples "Context creation with a coherent fingerprint + realistic headers" and "The `/4/find` call and its error taxonomy", §Pitfall 1 (the reproduced zombie leak and the shielded `finally`), §Pitfall 5 (host-only cookies)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-60, §D-61, §D-62, §D-64, §D-64a, §D-65
  </read_first>
  <action>
Write `services/poller/sources/resy/accounts.py`: pydantic models validating `RESY_ACCOUNTS_JSON`
before a single cookie is injected. Accept BOTH D-61 shapes — a `{"email": ..., "cookies": {name:
value}}` object and a `{"email": ..., "cookies": [{"name","value","domain","path",...}]}` explicit
Playwright list — and normalise both to `domain=".resy.com", path="/", secure=True`. A cookie added
by the `url=` form is stored host-only and never reaches `api.resy.com`, which yields an anonymous
fleet that still returns 200 OK and is indistinguishable from a soft ban; so an operator-supplied
host-only `resy.com` domain must be rewritten to the dot form and logged at WARNING. Provide
`load_accounts(raw_json: str | None) -> list[ResyAccount]` returning an empty list for unset/empty
input, never raising for absence. This module must never log a cookie value — the redaction extended
in 03-02 is key-name based and cannot rescue a value logged under a benign key.

Write `services/poller/sources/resy/pool.py`: `ContextPool` following the `LuaScheduler` lifecycle
shape — the constructor stores configuration only, `async def start()` launches
`async_playwright()` and `chromium.launch(headless=True, channel="chromium", proxy=...)` (one
browser per process; `channel=` avoids the headless-shell UA leak; `proxy` comes from
`resy_proxy_url()` and is absent when unset), then creates `N = resy_contexts()` contexts. Each
context is built with `user_agent=`, `viewport=`, `locale=`, `timezone_id=`,
`device_scale_factor=` and the `extra_http_headers` realistic set from its fingerprint row, receives
its round-robin account's normalised cookies via `add_cookies`, and gets `build_init_script(fp)`
through `add_init_script`. Track per context: an id, its fingerprint index, its account index, a
`pages_served` counter (incremented per REQUEST — the pool opens no pages in production), a creation
timestamp, and a poisoned flag. `acquire(venue_id)` takes the semaphore and pops an idle context,
skipping any context whose `rate_ctx_venue_key(ctx_id, venue_id)` floor is still held, and returns
None when every idle context is floored so the caller can release the job rather than wait.
`release(ctx)` returns it to the idle queue, recycling first when it is poisoned, when
`pages_served >= 500`, when its age is at least 2 hours, or after an unrecoverable Playwright error;
a recycle closes the context and creates a fresh one with the NEXT fingerprint and the NEXT account,
and increments `resy_context_recycles_total` with the reason. `stop()` closes every context, then
`await asyncio.shield(browser.close())` and `await playwright.stop()` in a `finally` — a bare
`await` in a `finally` reached through cancellation re-raises at once and leaks six OS processes.
Swallow the benign `Request context disposed` warning for an in-flight request rather than removing
the shield. Keep `playwright_contexts_active` in step with reality. State in the module docstring
that nothing outside this class may construct a `Browser` (the Resy analogue of D-05), and that the
production path opens no pages.

Write `services/poller/sources/resy/adapter.py`: `ResyAdapter(AvailabilitySource)` taking the pool by
constructor injection. `_fetch(ctx, url, params, headers) -> APIResponse` is the ONLY place the
transport lives — Q1 records that `context.request` is the Node driver rather than Chromium, and this
isolation is what keeps a future page-hosted `fetch()` a one-method change. `poll()` acquires a
context, issues one request per `(date, party_size)` pair against
`{resy_api_base()}/4/find` with `lat=0&long=0&day={YYYY-MM-DD}&party_size={n}&venue_id={rid}` and the
per-request auth headers (`Authorization: ResyAPI api_key="..."`, the configured auth-token header,
`X-Origin`, `Accept`), and assembles the D-64 envelope with one entry per pair carrying the ACTUAL
status. Never pass `fail_on_status_code=True` — it would raise on the very 429/403 the canary and
the backoff exist to observe. Guard `.json()` behind a `content-type` check because a challenge page
raises `JSONDecodeError`, and record `body_len` and the response text for the canary. Catch
`playwright.async_api.TimeoutError` BEFORE `playwright.async_api.Error` (the former is a subclass).
Do not add a tenacity retry: `APIRequestContext` returns 429 rather than raising, so there is nothing
for `retry_if_exception_type` to catch, and a retry would spend budget the scheduler already
accounted for.

Write `services/poller/sources/registry.py`: `ADAPTERS: dict[str, AvailabilitySource]` plus a
`build_adapters(...)` factory constructing OpenTable always and Resy only when `resy_enabled()`, so
an unconfigured deployment never launches Chromium.

Write the tracer `tests/integration/test_context_pool.py`: start a pool of 2 contexts against the
stub, acquire, poll a venue through `ResyAdapter`, assert the envelope has one entry per (date,
party) pair with status 200 and a parsed body, release, and stop — asserting zero `ms-playwright`
processes afterwards. Add `tests/integration/test_resy_request_headers.py` asserting the stub's hit
log carries every header named in `must_haves.truths` for that same request.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_context_pool.py tests/integration/test_resy_request_headers.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_context_pool.py tests/integration/test_resy_request_headers.py -q -p no:cacheprovider` exits 0 (or skips with the Chromium-guard message).
    - `pgrep -f ms-playwright | wc -l` reports 0 after the test run completes.
    - `uv run pytest tests/unit -q` exits 0.
    - `grep -c "page.goto\|new_page(" services/poller/sources/resy/pool.py services/poller/sources/resy/adapter.py` reports 0 for both files.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0 with no `type: ignore` added for `playwright`.
  </acceptance_criteria>
  <done>A real browser context, carrying a coherent identity and a real cookie jar, fetches `/4/find` from the stub and returns a truthful envelope — and the process tree is clean afterwards.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Cookie normalisation, anonymous mode, and per-context fingerprint rotation</name>
  <files>tests/unit/test_resy_accounts.py, tests/integration/test_anonymous_mode.py, tests/integration/test_fingerprint_rotation.py, services/poller/sources/resy/accounts.py</files>
  <read_first>
    - services/poller/sources/resy/accounts.py and pool.py (as written in Task 1)
    - shared/events.py (the `ConfigDict(frozen=True, extra="forbid")` pydantic idiom this repo uses)
    - shared/metrics.py (`resy_auth_mode`)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pattern 5 (`add_cookies` validation: name+value alone is REJECTED, `domain` without `path` is REJECTED, the `url` form yields a host-only domain) and §Pitfall 5
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Security Domain (anonymous mode must carry a distinct metric label so Grafana can separate it)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-61
    - .env.example lines 35-49 (the operator-facing shape the parser must accept)
  </read_first>
  <behavior>
    - `{name: value}` object shape -> one normalised cookie per entry, each with `domain=".resy.com"`, `path="/"`, `secure=True`.
    - Explicit Playwright list shape with a correct dot-domain -> passed through unchanged.
    - Explicit list entry with `domain: "resy.com"` (host-only) -> rewritten to `.resy.com` AND a warning logged naming the account index, never the cookie value.
    - An entry missing `name` or `value`, or a `cookies` value that is neither an object nor a list -> `ValidationError` at load time, before any browser exists.
    - `load_accounts(None)`, `load_accounts("")` and `load_accounts("[]")` all return `[]` without raising.
    - Malformed JSON -> a raised error whose message names `RESY_ACCOUNTS_JSON` and contains no fragment of the input.
    - With zero accounts the pool starts, `resy_anonymous_mode` is logged exactly once regardless of context count, `resy_auth_mode` carries the anonymous label, and every context has an empty cookie jar.
    - With 2 accounts and 4 contexts the accounts repeat round-robin (0,1,0,1) and each context reports the `navigator.userAgent` of ITS OWN fingerprint row; two contexts report different UAs.
  </behavior>
  <action>
Write `tests/unit/test_resy_accounts.py` covering every non-browser row in `<behavior>`, asserting on
the normalised cookie dicts rather than on internal state, and asserting the warning is emitted via a
structlog capture rather than by reading stdout. Include an explicit assertion that no test-visible
log record contains a cookie value.

Write `tests/integration/test_anonymous_mode.py`: start a pool with `RESY_ACCOUNTS_JSON` unset,
assert the pool is usable, assert the log record count for the anonymous event is exactly one, and
assert the metric label via `get_sample_value` (using the correct sample name — a Counter named
`x_total` is stored internally as `x`).

Write `tests/integration/test_fingerprint_rotation.py`: start a pool of at least 2 contexts, open a
page per context against the STUB ORIGIN (never `about:blank`, where the init script throws and
silently disables every later patch), evaluate `navigator.userAgent`, and assert each equals its own
row's UA and that the two differ. Pages here are a test affordance only; assert in a comment and in
the pool's own counters that the production path opened none.

Fix `accounts.py` for whatever the matrix exposes rather than relaxing an assertion.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_resy_accounts.py tests/integration/test_anonymous_mode.py tests/integration/test_fingerprint_rotation.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_resy_accounts.py tests/integration/test_anonymous_mode.py tests/integration/test_fingerprint_rotation.py -q -p no:cacheprovider` exits 0 (or skips with the Chromium-guard message).
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run python -c "from services.poller.sources.resy.accounts import load_accounts; print(load_accounts(None), load_accounts(''), load_accounts('[]'))"` prints three empty lists.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>Both operator cookie shapes reach `api.resy.com`, a credential-free deployment is visibly anonymous rather than quietly broken, and each context wears its own identity.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The soft-ban canary — pure signature, pure verdict, Redis-only window</name>
  <files>services/poller/sources/resy/canary.py, tests/unit/test_response_signature.py, tests/unit/test_canary_verdict.py, tests/integration/test_canary_window.py</files>
  <read_first>
    - shared/redis_keys.py (`canary_key`, `CANARY_WINDOW_SIZE`, `CANARY_TTL_SECONDS`, `canary_window_push` — the single MULTI/EXEC helper from 03-02)
    - services/state_machine/parsers/opentable.py :: effective_coverage (the pure-function-with-no-clock precedent, D-49)
    - tests/unit/test_engine_transitions.py (the matrix-style table test this verdict matrix should mirror)
    - shared/metrics.py (`scrape_ban_total`)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pattern 7 (the verified LIST semantics and the demand that the verdict be pure), §Pitfall 10 (an empty 200 is indistinguishable from a fully booked venue; the fleet-level cross-check), §Code Examples "Per-context floor and the canary window"
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-67, §D-67b
  </read_first>
  <behavior>
    - `response_signature(200, {"content-type": "application/json"}, body)` produces a stable record `(http_status, body_len_bucket, has_results_key, venues_count, has_slots_key)` plus the raw `body_len`; two calls on equal inputs are equal, and the record serialises to a single compact string and parses back exactly.
    - `body_len_bucket`: 0 bytes -> 0; 1 byte -> 0; 2 -> 1; 1023 -> 9; 1024 -> 10. The raw `body_len` is preserved separately.
    - `ban_verdict` returns a reason for: status 403 with a challenge body; status 429; three consecutive empty-200 signatures where the majority of the remaining baseline had a non-zero `venues_count`; and a signature whose raw `body_len` is under 20 % of the baseline median.
    - `ban_verdict` returns None for: TWO consecutive empty-200s; three empty-200s when the baseline was already mostly empty (a genuinely fully booked venue); a short body when the baseline median is itself short; and an empty window (a cold start can never be a ban).
    - The function is pure — the same `(signature, window)` gives the same answer with no Redis, no clock and no metric side effect; the counter increment happens at the call site.
    - The Redis window keeps exactly `CANARY_WINDOW_SIZE` entries after 25 pushes, carries the TTL, and the four commands execute as one transaction.
  </behavior>
  <action>
Write `services/poller/sources/resy/canary.py`: a frozen `ResponseSignature` dataclass with the five
D-67 fields plus the raw `body_len`, a `response_signature(status, headers, text) -> ResponseSignature`
builder that parses defensively (a challenge page is not JSON), compact `to_wire()` / `from_wire()`
so the window stores short strings, `BanReason` as a `StrEnum` (the repo uses `StrEnum`, not the
`(str, Enum)` mixin, which ruff rejects on py312), and `ban_verdict(new: ResponseSignature, window:
Sequence[ResponseSignature]) -> BanReason | None` implementing the four rules above. The verdict
reads no clock, touches no Redis and increments no metric, so every rule is a unit test; the caller
in 03-06 owns the counter and the reaction. Add a `record_signature(r, venue_id, sig) ->
list[ResponseSignature]` thin wrapper over the shared `canary_window_push` helper, so this module
contains no inline `cast`. Document in the docstring why three consecutive empties are required and
why the baseline majority matters: a venue that is genuinely fully booked on a Saturday would
otherwise be reported as a ban.

Write `tests/unit/test_response_signature.py` and `tests/unit/test_canary_verdict.py` as literal
matrices covering every row in `<behavior>`, constructing windows by hand so no test needs Redis.
Write `tests/integration/test_canary_window.py` driving `record_signature` against the Redis
container for the 25-push / 20-entry / TTL / single-transaction properties.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_response_signature.py tests/unit/test_canary_verdict.py tests/integration/test_canary_window.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_response_signature.py tests/unit/test_canary_verdict.py tests/integration/test_canary_window.py -q -p no:cacheprovider` exits 0 (the integration file may skip with the Docker-guard message).
    - `grep -c "def test_" tests/unit/test_canary_verdict.py` returns at least 8.
    - `uv run python -c "from services.poller.sources.resy.canary import response_signature as s; print(s(200,{'content-type':'application/json'},'').body_len_bucket, s(200,{'content-type':'application/json'},'x'*1024).body_len_bucket)"` prints `0 10`.
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>A soft ban is decidable from a signature list alone, a fully booked Saturday is not mistaken for one, and the rolling window is transactionally correct.</done>
</task>

<task type="auto">
  <name>Task 4: The package README that makes the public promise auditable, and the no-sleep gate</name>
  <files>services/poller/sources/resy/README.md, tests/unit/test_no_inline_sleep_resy.py</files>
  <read_first>
    - services/poller/sources/opentable/README.md (the `<!-- SPIKE STATUS: PLACEHOLDER -->` marker, the explicit "only these files need editing after the spike" list, the closing rerun command)
    - README.md lines 323-340 (the Legal &amp; Ethical Scraping section that already promises 80 req/min and no booking automation — this README must cite the functions that now enforce it)
    - tests/unit/test_no_inline_sleep.py in full (the scanned-file tuple, the comment-stripping helper, and the non-vacuity guard — all three must be copied)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §B-9 (the TLS-fingerprint claim to delete), §Open Questions Q1 and Q3, §Anti-Patterns to Avoid
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-64a, §specifics
    - .planning/deferred-items.md (the table format for the Q3 follow-up)
  </read_first>
  <action>
Write `services/poller/sources/resy/README.md` following the OpenTable sibling's structure. It must:
carry a `<!-- SPIKE STATUS: PLACEHOLDER — needs live browser confirmation -->` marker and list
exactly which files a human edits after the DevTools capture (`fixtures.py`, the numeric ids in
`scripts/seed/restaurants.yml`, `RESY_API_KEY`, `RESY_ACCOUNTS_JSON`); name, by fully-qualified
symbol, the functions that enforce the two limits the root README publicly commits to — the minute
budget Lua and the per-context floor helper in `shared/redis_keys.py`, and the pre-dispatch gate in
`services/poller/scheduler.py` (landing in 03-06) — so the public claim is auditable from code;
record the D-64a tradeoff plainly, stating that `context.request` is the Playwright Node driver and
does NOT carry Chromium's TLS or native header fingerprint, that the realistic header set is
therefore supplied explicitly per context, that pages were rejected because they cost roughly 178 MB
each and would forfeit PERF-05, and that `_fetch` is the single method to change if that tradeoff is
ever revisited; and record the Q3 consequence that `(source, platform_id)` — not the slug — is the
join key Phases 4/5/6 must use, because one restaurant now has two rows sharing one slug. Add that
last point as a row in `.planning/deferred-items.md` naming the future `restaurant_group` /
`canonical_slug` decision as belonging to Phase 6, not here.

Write `tests/unit/test_no_inline_sleep_resy.py` by copying all three pieces of
`tests/unit/test_no_inline_sleep.py`: the explicit scanned-file tuple built by globbing
`services/poller/sources/resy/*.py`, the full-line-comment stripper so an explanatory comment can
neither satisfy nor break the gate, and the non-vacuity guard asserting the glob matched the expected
module names. Assert both the asynchronous and the synchronous form. The module docstring explains
what the gate protects: the 45 s floor, the 80 rpm cap and the 429 backoff are ZSET scores by design,
and a wait inside the adapter would burn a pool slot and a worker task while looking like it worked.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_no_inline_sleep_resy.py tests/unit/test_no_inline_sleep.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_no_inline_sleep_resy.py tests/unit/test_no_inline_sleep.py -q` exits 0.
    - `grep -c "shared/redis_keys.py\|scheduler.py" services/poller/sources/resy/README.md` returns at least 2 (the enforcing functions are cited by path).
    - `grep -c "SPIKE STATUS" services/poller/sources/resy/README.md` returns 1.
    - `grep -c "resy" .planning/deferred-items.md` returns at least 1.
    - `uv run pytest tests/unit -q` exits 0 and `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>The public rate-limit promise names the code that enforces it, the TLS tradeoff is recorded rather than mis-stated, and a wait can no longer be smuggled into the Resy package.</done>
</task>

</tasks>

## Artifacts this phase produces (plan 05)

| Kind | Symbol / path | Notes |
|------|---------------|-------|
| module | `services/poller/sources/resy/accounts.py` | |
| model | `ResyAccount` | pydantic, `extra="forbid"` |
| function | `load_accounts(raw_json) -> list[ResyAccount]` | both cookie shapes; `[]` for absent |
| module | `services/poller/sources/resy/pool.py` | |
| class | `ContextPool` | `start()` / `acquire(venue_id)` / `release(ctx)` / `recycle(ctx, reason)` / `stop()` |
| dataclass | `PooledContext` | id, fingerprint index, account index, `pages_served`, created-at, poisoned |
| constant | `CONTEXT_MAX_REQUESTS = 500`, `CONTEXT_MAX_AGE_SECONDS = 7200` | recycle triggers |
| module | `services/poller/sources/resy/adapter.py` | |
| class | `ResyAdapter(AvailabilitySource)` | constructor takes the pool |
| method | `ResyAdapter._fetch(ctx, url, params, headers) -> APIResponse` | the SINGLE transport site (Q1) |
| method | `ResyAdapter.poll(rid, dates, party_sizes) -> dict` | returns the D-64 envelope |
| module | `services/poller/sources/registry.py` | |
| symbol | `ADAPTERS: dict[str, AvailabilitySource]`, `build_adapters(...)` | replaces the `if source ==` branch |
| module | `services/poller/sources/resy/canary.py` | |
| dataclass | `ResponseSignature` | 5 fields + raw `body_len`; `to_wire()` / `from_wire()` |
| enum | `BanReason` (StrEnum) | `challenge_403`, `rate_limited_429`, `empty_results`, `short_body` |
| function | `response_signature(status, headers, text) -> ResponseSignature` | pure |
| function | `ban_verdict(new, window) -> BanReason \| None` | pure |
| function | `record_signature(r, venue_id, sig) -> list[ResponseSignature]` | one MULTI/EXEC |
| doc | `services/poller/sources/resy/README.md` | cites the enforcing functions; records the Q1 tradeoff |
| test | `tests/unit/test_no_inline_sleep_resy.py` | grep gate over the Resy package |

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| `RESY_ACCOUNTS_JSON` -> `BrowserContext` cookie jar | A human's captured third-party session crosses into process memory |
| `/4/find` response -> adapter -> Kafka | Untrusted third-party bytes, including a possible HTML challenge page |
| poller process -> OS process tree | Every context and browser is real OS state that outlives a careless `await` |
| residential proxy URL -> `ProxySettings` | Credentials embedded in a URL string |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-03-20 | Information Disclosure | `accounts.py`, `pool.py` | critical | mitigate | Cookies live only in context memory, are never written to Postgres, Kafka or disk, and no module logs a cookie value; `shared/telemetry.py` (03-02) redacts the key names as a second line of defence |
| T-03-21 | Information Disclosure | proxy credentials | high | mitigate | Split the URL into `username` / `password` when constructing `ProxySettings` so the credential-bearing string is never carried around whole or interpolated into an error |
| T-03-22 | Denial of Service | `ContextPool.stop()` | critical | mitigate | `await asyncio.shield(browser.close())` in `finally`, then `playwright.stop()`; research reproduced six surviving processes without the shield. The tracer asserts a clean process tree |
| T-03-23 | Denial of Service | `/4/find` body handling | high | mitigate | `.json()` is guarded by a content-type check because a 403 challenge page raises `JSONDecodeError`; a malformed body becomes a recorded non-200 envelope entry, never an escaping exception |
| T-03-24 | Spoofing (failed) | host-only cookies | high | mitigate | Both operator shapes normalise to `.resy.com`; a host-only domain would silently produce an anonymous fleet returning 200 OK that is indistinguishable from a soft ban (research §Pitfall 5) |
| T-03-25 | Repudiation | anonymous mode | medium | mitigate | Logged once at WARNING plus a distinct `resy_auth_mode` metric label, so unauthenticated traffic is visible in Grafana rather than looking healthy |
| T-03-26 | Repudiation | rate discipline | high | mitigate | No `asyncio.sleep`/`time.sleep` may exist under the Resy package (grep-gate unit test); every wait is a scheduler score, so a slot is never burned pretending to be polite |
| T-03-SC | Tampering | npm/pip/cargo installs | low | accept | No new packages; `playwright==1.58.0` and `tf-playwright-stealth==1.2.0` are pinned in `uv.lock` and audited (research §Package Legitimacy Audit) |
</threat_model>

## Flagged assumptions (probe, unresolved — review manually)

- **POLL-06 / unclassified** — the edge probe could not classify POLL-06 (`response-signature canary
  metric catches 200 OK responses with sanitized / empty availability data; alerts on anomaly`).
  Carried forward explicitly rather than auto-resolved: the requirement does not define what
  "anomaly" means numerically, nor how a genuinely fully booked venue is distinguished from a
  sanitized one. This plan implements D-67's three-consecutive-empties-against-a-non-empty-baseline
  rule plus the 20 %-of-median body rule, and research §Pitfall 10 additionally proposes a
  fleet-level cross-check (if every venue polled in the same minute went empty at once, that is a
  ban; if one did while others returned slots, it is probably real). The fleet-level cross-check is
  NOT implemented in this plan — the per-venue window is — and that gap is recorded here rather
  than silently dropped. Assumption A6 also records that the soft-ban-as-empty-200 premise is
  single-source and LOW confidence.

<verification>
- `uv run pytest tests/unit -q` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 or skips with the documented environment guards.
- `pgrep -f ms-playwright | wc -l` reports 0 after the suite.
- `uv run ruff check . && uv run mypy shared/ services/` exits 0.
</verification>

<success_criteria>
- One browser, N isolated contexts, each with its own coherent identity and cookie jar, acquired and released without contention bugs.
- `/4/find` is fetched directly with the full realistic header set and no page load.
- A soft ban is decidable from a pure function over a bounded rolling window.
- The Resy package contains no wait, and the README names the code that enforces the public promise.
</success_criteria>

<output>
Create `.planning/phases/03-resy-playwright-fleet/03-05-SUMMARY.md` when done.
</output>
</content>
