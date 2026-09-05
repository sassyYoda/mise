---
phase: 05-api-watchlist-crud-sse
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - shared/servicetime.py
  - shared/telemetry.py
  - shared/metrics.py
  - services/state_machine/persistence.py
  - services/api/config.py
  - services/api/middleware.py
  - services/api/deps.py
  - services/api/app.py
  - services/api/routers/health.py
  - services/api/routers/metrics.py
  - tests/unit/test_phase5_preconditions.py
  - tests/unit/test_request_log.py
  - tests/unit/test_api_logs_never_carry_payload.py
  - tests/unit/test_client_ip.py
  - tests/unit/test_api_async_only.py
  - tests/unit/test_metrics_registry.py
  - tests/integration/conftest.py
  - tests/integration/test_api_plumbing.py
  - tests/integration/test_metrics.py
autonomous: true
requirements: [API-01, API-03]

estimate:
  tokens: 68000
  raw_tokens: 68000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Wave 0 gate: `tests/unit/test_phase5_preconditions.py` fails with a message naming the OWNING decision id and plan for every missing upstream artifact — `shared/tokens.py` (D-82 / 04-01), `shared/crypto.py` (D-85 / 04-01), `shared/metrics.py` (D-69 / 03-02), the `watch:count` / `tier:override` helpers in `shared/redis_keys.py` (D-58 / 03-02), `services/api/app.py :: create_app` (D-84 / 04-04), `EmailProvider` (D-78 / 04-05), a migration establishing `uq_restaurants_slug_source` (D-63b / 03-03) and a migration establishing `push_subscriptions` + `users.phone_hash` (D-85 / 04-02) — rather than surfacing as an `ImportError` inside a route (D-93a)."
    - "`shared/db.py :: Restaurant.slug` no longer declares `unique=True`; the precondition test asserts this by source scan because a `Base.metadata.create_all` that rebuilds `UNIQUE(slug)` silently destroys the one-slug-many-source-rows model every later plan depends on (D-63b / 03-03, research §Sequencing trap 1)."
    - "`shared/servicetime.py :: SERVICE_TZ` is the ONE definition of `ZoneInfo('America/New_York')`; `services/state_machine/persistence.py` re-exports it as `_SERVICE_TZ` through `__all__` with `# noqa: F401`, and the whole pre-existing `tests/unit/test_service_time_math.py` suite stays green with zero behaviour change (D-93a)."
    - "`services/api/middleware.py :: ErrorBoundary` is a pure-ASGI callable that catches every unhandled exception, logs `safe_error(exc)` plus `request_id`, emits a JSON `{error, request_id}` body, and NEVER re-raises — so Starlette's `ServerErrorMiddleware` is never reached and no traceback carrying bound SQL parameters or a pydantic input echo enters the log stream (D-97a / BC-3)."
    - "`services/api/middleware.py :: RequestLog` is a pure-ASGI callable, not a `dispatch`-style middleware: it captures `status` at `http.response.start`, records `ttfb_ms` at the FIRST `http.response.body` and `duration_ms` in its `finally` after the LAST one, and reads `scope['route']` in that same `finally` because the router has not matched before the app is called (D-97, research Pattern 1)."
    - "PROBE API-01/boundary: for a streaming response the logged `duration_ms` is the full connection lifetime measured at the final body message, not ~0 measured when the response object was returned — the measured 0 ms vs 103 ms split in research Pattern 1. A request that raises before the router matches logs `route=None` and the status the `ErrorBoundary` produced, never status `0`."
    - "PROBE API-01/precision: `duration_ms` and `ttfb_ms` derive from `time.perf_counter()` (monotonic — a wall-clock NTP step can never produce a negative duration), are rounded to 2 decimal places, and `ttfb_ms` is `None` (never `0.0`) when no body message was ever sent."
    - "`redact_path` maps `/manage/t/{tok}`, `/api/manage/{tok}`, `/go/{tok}` and `/unsubscribe/{tok}` to the literal prefix plus a `{token}` placeholder by PREFIX match, falls back to a token-shaped-segment regex for any other path, and leaves `/api/restaurants/lilia` and `/watches/17` untouched; the request logger renders the redacted path and the route template only, and drops the query string entirely (D-97, D-95a)."
    - "`client_ip_from_scope` returns the socket peer when `TRUST_PROXY_HEADERS` is false and the SECOND-TO-LAST `X-Forwarded-For` entry (governed by `PROXY_HOPS`, default 1) when it is true — never the first entry, which Google's load balancer forwards unverified, and never uvicorn's `ProxyHeadersMiddleware` resolution, which collapses every caller onto the balancer's own address (D-96a / BC-2)."
    - "`GET /healthz` returns `200 {\"status\":\"ok\"}` unconditionally and touches no dependency; `GET /readyz` returns one entry per live process dependency (`db` via `SELECT 1`, `redis` via `PING`, each under its own timeout) and answers `503` when any entry is unhealthy (D-97). The `feed` entry joins the same response in 05-05, when the SSE pump joins the lifespan."
    - "`GET /api/metrics` is unauthenticated, returns `prometheus_client.CONTENT_TYPE_LATEST` verbatim rather than a hand-written `text/plain`, serves `generate_latest` over the SAME registry object `shared/metrics.py` writes into, is `include_in_schema=False`, and carries no `http_requests_total` series about itself (D-101, research §Metrics two-registry hazard)."
    - "`Instrumentator(should_exclude_streaming_duration=True, excluded_handlers=['/api/metrics','/healthz','/readyz'], registry=<the shared registry>)` is configured at app construction, BEFORE any streaming route exists, so a long-lived SSE connection can never write its whole lifetime into `http_request_duration_seconds` (D-101a)."
    - "Middleware order is fixed and asserted: CORS is outermost so a rejected preflight is still logged, `RequestLog` sits inside CORS and outside the instrumentator so it measures the true duration, and `ErrorBoundary` is the last `add_middleware` call — innermost to Starlette's own error middleware, outermost to everything of ours (D-97a, research Pitfall 8)."
    - "uvicorn runs with `log_config=None` and its `uvicorn.error` / `uvicorn.access` loggers are routed through structlog, so no API log line escapes the redaction processors (D-97a, research OQ-6)."
    - "`tests/integration/conftest.py` gains BOTH test tiers BC-1 requires: an `api_app` fixture building `create_app()` against the container URLs after `reset_shared_db_singletons()`, and a `live_api` fixture that binds an ephemeral port, serves `create_app()` with `lifespan='on'` in-process, yields its base URL and shuts down with `should_exit` plus a bounded `wait_for` — never by cancelling the serve task (D-104a / BC-1, Phase 3 D-71 recipe)."
    - "PROBE API-01/unclassified — flagged assumption: `X-Request-ID` is echoed back on every response and accepted from the caller when present. An attacker-supplied value therefore appears in our logs verbatim; it is treated as a correlation hint only, never as an identity, and is length-bounded before it is logged."
  artifacts:
    - shared/servicetime.py
    - services/api/middleware.py
    - services/api/deps.py
    - services/api/routers/health.py
    - services/api/routers/metrics.py
    - tests/unit/test_phase5_preconditions.py
    - tests/unit/test_request_log.py
    - tests/unit/test_api_logs_never_carry_payload.py
    - tests/unit/test_client_ip.py
    - tests/unit/test_api_async_only.py
    - tests/integration/test_api_plumbing.py
    - tests/integration/test_metrics.py
  key_links:
    - "`shared/metrics.py` -> `GET /api/metrics` -> Phase 7's Grafana scrape. The registry object handed to `Instrumentator(registry=…)` and the one handed to `generate_latest(…)` must be the SAME object: two registries holding one metric name is silent, and the endpoint would serve a gauge frozen at 0 while the real one climbs (research §Metrics)."
    - "`ErrorBoundary` -> `shared/telemetry.py :: safe_error` -> the log sink. This is the only egress an unhandled exception has; if `ErrorBoundary` re-raises, Starlette logs the raw traceback and the repo's absolute no-`str(exc)` rule is broken for every 500 in the API (BC-3, T-02-03)."
    - "`client_ip_from_scope` -> `services/api/ratelimit.py` (05-03) -> the `rate:api:*` bucket key. One resolution function, two readers; a second copy is how the log and the limiter come to disagree about who the caller is (BC-2)."
    - "`shared/servicetime.py :: SERVICE_TZ` -> `WatchCreate.date_from` validation (05-02) AND `hours_before_service` (Phase 2 persistence). One timezone constant; two definitions is how a watch for tonight becomes a 422 after 20:00 Eastern (D-93a, Pitfall 1)."
    - "`live_api` fixture -> every SSE assertion in 05-05. `ASGITransport` buffers the whole response and never runs lifespan, so without this fixture the SC3 latency test cannot be written at all — it hangs forever on an infinite generator (BC-1)."
  prohibitions:
    - "MUST NOT re-raise from `ErrorBoundary`, and MUST NOT put a raw exception message, a traceback, an SQL string, a bound parameter or a pydantic `input_value` into any log field — every error egress goes through `safe_error`."
    - "MUST NOT log a request body, a query string, an `Authorization` header value, a cookie, or any path segment that has not passed through `redact_path`."
    - "MUST NOT resolve the client address from the first `X-Forwarded-For` entry, from `request.client.host` when proxy headers are trusted, or through uvicorn's `ProxyHeadersMiddleware`."
    - "MUST NOT define any Prometheus metric outside `shared/metrics.py`, and MUST NOT construct a second `CollectorRegistry` anywhere in `services/api/`."
    - "MUST NOT redefine, re-implement or shadow any Phase 3 or Phase 4 artifact the precondition gate asserts — `shared/tokens.py`, `shared/crypto.py`, `shared/metrics.py`, the `watch:count` / `tier:override` helpers, `create_app`, `EmailProvider` and migrations 0009/0010 are consumed as they are shipped."
    - "MUST NOT read any environment variable at module import time in `services/api/**` — every read is inside a function (02-02 deviation 1)."
    - "MUST NOT call `prometheus_client.start_http_server` in the API process; the API already has an HTTP surface."
---

<objective>
Build the API's load-bearing plumbing before a single business route exists: a Wave-0 gate that fails
loudly and by decision id when an upstream Phase 3/4 artifact is missing, the one service-timezone
constant, the two pure-ASGI middlewares that are the entire error- and log-safety story for this
phase, lazy config, health and readiness, and the Prometheus endpoint wired to the one registry.

Purpose: BC-3 showed the locked exception-handler design returns a clean body and still leaks the
traceback — with bound SQL parameters and pydantic input echoes — into the log stream, and research
Pattern 1 measured a `dispatch`-style logger recording 0 ms for a 103 ms stream. Both defects are
invisible in a passing test suite and become permanent the moment routes are layered on top. They are
therefore fixed first, on the plan's best context, and every later plan inherits them.
Output: `shared/servicetime.py`, `services/api/{config,middleware,deps}.py`, the health and metrics
routers, the Phase-5 metric definitions in `shared/metrics.py`, both integration test tiers BC-1
requires, and five unit test files that pin the gate.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md
@.planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Wave 0 — the precondition gate, and the one service-timezone constant</name>
  <files>tests/unit/test_phase5_preconditions.py, shared/servicetime.py, services/state_machine/persistence.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Sequencing Dependencies (not corrections — hard preconditions)" — the artifact/owner table and both live traps
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-93a (the Wave-0 assertion list and the `_SERVICE_TZ` move)
    - .planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md §"No Analog Found" (the owning decision id for every absent artifact) and §"One live trap to re-verify at execution time"
    - services/state_machine/persistence.py lines 1-60 (`_SERVICE_TZ`, `hours_before_service`, the module docstring register)
    - services/state_machine/config.py lines 16-40 (the sanctioned re-export idiom: `__all__` entry plus `# noqa: F401 (re-exported for consumers)`)
    - shared/db.py lines 51-71 (`Restaurant`, the `slug` column declaration, and the existing `__table_args__` shape)
    - tests/unit/test_no_inline_sleep.py lines 30-55 (the non-vacuity companion idiom)
  </read_first>
  <behavior>
    - Importing `shared.tokens`, `shared.crypto`, `shared.metrics`, `shared.watch_counts`-adjacent helpers and `services.api.app` succeeds; each failure raises an assertion naming the owning decision id and the owning plan file.
    - `shared.redis_keys` exposes `WATCH_COUNT_HASH`, `TIER_OVERRIDE_HASH`, `watch_count_field` and `tier_override_field`.
    - The `migrations/versions/` directory contains a revision whose source names `uq_restaurants_slug_source`, and a revision whose source names both `push_subscriptions` and `phone_hash`.
    - A source scan of `shared/db.py` finds no `unique=True` on the `Restaurant.slug` column declaration.
    - `services.notifier.providers.email` exposes `EmailProvider`.
    - `shared.servicetime.SERVICE_TZ` is a `ZoneInfo` whose key is `America/New_York`, and `services.state_machine.persistence._SERVICE_TZ` is the very same object.
    - The whole pre-existing unit suite, including `tests/unit/test_service_time_math.py`, stays green.
  </behavior>
  <action>
Write `tests/unit/test_phase5_preconditions.py` as the Wave-0 gate D-93a asks for. Structure it as one
test per upstream artifact rather than one test with many assertions, so a failing run names exactly
which upstream plan has not landed. Every assertion message follows one shape: the missing symbol or
file, the owning decision id, and the owning plan filename — for example a missing `sign_token` cites
D-82 and `04-01-shared-token-crypto-kernel-PLAN.md`. Cover, each with its own test:
`shared.tokens` exposing `sign_token` and `verify_token` (D-82 / 04-01); `shared.crypto` exposing
`encrypt_phone`, `decrypt_phone` and `phone_hash` (D-85 / 04-01); `shared.metrics` importing without
raising a duplicate-timeseries error (D-69 / 03-02); `shared.redis_keys` exposing `WATCH_COUNT_HASH`,
`TIER_OVERRIDE_HASH`, `watch_count_field` and `tier_override_field` (D-58 / 03-02);
`services.api.app` exposing `create_app` (D-84 / 04-04); `services.notifier.providers.email` exposing
`EmailProvider` (D-78 / 04-05). Use `importlib.import_module` inside a `try/except ImportError` and
convert the failure into `pytest.fail(...)` with that message, so a missing module reads as a gate
failure rather than a collection error that takes the whole unit tier down.

Add two file-level assertions that need no import. First, scan every file in `migrations/versions/`
and assert one of them names `uq_restaurants_slug_source` (D-63b / 03-03) and one names both
`push_subscriptions` and `phone_hash` (D-85 / 04-02); do not hard-code revision numbers, because the
chain is resolved at execution time. Second, reproduce research §Sequencing trap 1: read
`shared/db.py`, isolate the `Restaurant.slug` mapped-column declaration, and assert it does not carry
a uniqueness flag — a comment in the test states why, namely that any `Base.metadata.create_all`
against the stale declaration silently rebuilds the single-column constraint and makes the
one-slug-two-source-rows model of D-93 and D-100 fail with no error at all. Give the migration scan a
non-vacuity companion asserting the scanned file set is non-empty and every entry is a real file,
following `tests/unit/test_no_inline_sleep.py`.

Create `shared/servicetime.py` (D-93a). It holds `SERVICE_TZ = ZoneInfo("America/New_York")` and the
`hours_before_service` helper currently living in `services/state_machine/persistence.py`, moved
verbatim — this is a MOVE, not a rewrite, so the arithmetic and its docstring travel unchanged. Give
the module the standard `Named symbols:` docstring and state the reason the constant is shared: every
mise restaurant is in NYC, the state machine computes service-local hours with it, and the Phase-5
`date_from` validator must use the same zone or a watch created at 21:30 Eastern is rejected as being
in the past (research Pitfall 1). Edit `services/state_machine/persistence.py` to import `SERVICE_TZ`
and `hours_before_service` from `shared.servicetime`, bind `_SERVICE_TZ = SERVICE_TZ` for the existing
private name, and add both to `__all__` with the `# noqa: F401 (re-exported for consumers)` comment
`services/state_machine/config.py` already uses. Nothing else in the state machine changes; its unit
tests are the proof.

Add to `tests/unit/test_phase5_preconditions.py` a final test asserting `shared.servicetime.SERVICE_TZ`
and `services.state_machine.persistence._SERVICE_TZ` are the same object — identity, not equality, so
a future re-declaration rather than a re-export fails here.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_phase5_preconditions.py tests/unit/test_service_time_math.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_phase5_preconditions.py -q` exits 0. A non-zero exit HALTS this phase: the failure message names the upstream plan that must execute first.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0 — the entire pre-existing unit tier is unaffected by the timezone move.
    - `uv run python -c "import shared.servicetime as s, services.state_machine.persistence as p; print(s.SERVICE_TZ.key, s.SERVICE_TZ is p._SERVICE_TZ)"` prints `America/New_York True`.
    - `grep -c 'ZoneInfo("America/New_York")' shared/servicetime.py` prints `1`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Every upstream Phase 3/4 artifact this phase consumes is asserted present by name and by owning decision id, the two live traps from research §Sequencing are pinned as executable tests, and one timezone constant serves both the state machine and the API.</done>
</task>

<task type="tracer" tdd="true">
  <name>Task 2: End-to-end tracer — one request through ErrorBoundary and RequestLog to a live health route</name>
  <files>services/api/config.py, services/api/middleware.py, services/api/deps.py, services/api/routers/health.py, services/api/app.py, tests/unit/test_request_log.py, tests/unit/test_client_ip.py, tests/unit/test_api_logs_never_carry_payload.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Blocking Corrections" BC-3 (the `ServerErrorMiddleware` re-raise and the reproduced traceback leak) and BC-2 (both client-IP failure modes)
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Code Examples" — "Pure-ASGI request logging middleware", "Token redaction", "Lifespan with `AsyncExitStack` and lifespan state"
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Architecture Patterns" Pattern 1 and §"Common Pitfalls" Pitfall 8 (middleware order) and Pitfall 9 (lifespan under ASGITransport)
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"`/readyz`" (the three checks and the timeout-per-check rule)
    - services/api/app.py and services/api/config.py as shipped by 04-04 (the `create_app()` factory, the `AsyncExitStack` lifespan, the existing accessors, and the comment naming the routers this phase adds)
    - services/state_machine/config.py lines 1-15 and 96-129 (the lazy-env docstring and the fail-closed validated-env pattern)
    - shared/telemetry.py lines 52-144 (`safe_error`, `_redact_secrets`, `get_logger`, `configure_logging`)
    - tests/unit/test_logs_never_carry_payload.py (the marker-string model for the BC-3 gate)
  </read_first>
  <behavior>
    - A request to `/healthz` returns `200 {"status":"ok"}` and an `X-Request-ID` response header; when the caller sent `X-Request-ID`, that value is echoed, otherwise a uuid4 is generated.
    - A route that raises returns `500 {"error": ..., "request_id": ...}` with no traceback in the body, and exactly one log record whose `error` field is the `safe_error` rendering; the exception does not propagate past `ErrorBoundary`.
    - A route that raises a `ValueError` carrying a unique marker string produces no log record and no response byte containing that marker.
    - The log record for a request to `/api/manage/<64-char token>` carries a path ending in a `{token}` placeholder and never the token characters.
    - The log record for a streamed response has `duration_ms` at least as large as the stream's real duration and `ttfb_ms` strictly smaller than it.
    - A request that never reaches the router logs `route=None` and a non-zero status.
    - `client_ip_from_scope` with `trust_proxy=False` returns the socket peer even when `X-Forwarded-For` is present.
    - `client_ip_from_scope` with `trust_proxy=True`, `hops=1` and header `1.2.3.4, 203.0.113.9, 35.191.0.1` returns `203.0.113.9`; three different spoofed leading entries with the same trailing pair all return `203.0.113.9`.
    - `client_ip_from_scope` with `trust_proxy=True` and a single-entry header returns that entry; with no header at all it falls back to the socket peer.
    - `GET /readyz` returns `200` with a per-dependency map when DB and Redis answer, and `503` when either does not.
  </behavior>
  <action>
Extend `services/api/config.py` (the file 04-04 shipped — extend it, never rewrite it) with the
Phase-5 accessors, every one a FUNCTION for the reason its module docstring already records:
`kafka_bootstrap_servers()` defaulting to the same broker string `services/state_machine/config.py`
uses; `cors_allowed_origins()` parsing `CORS_ALLOWED_ORIGINS` as a comma list with the local Next.js
dev origin as the default; `trust_proxy_headers()` and `proxy_hops()` implementing the fail-closed
validated-env pattern — an unparseable value raises a `RuntimeError` naming the variable and the
accepted values rather than coercing to a default, because a typo that silently disables proxy trust
is BC-2's failure mode wearing a different hat; `admin_basic_user()` and `admin_basic_password()`
returning `None` when unset; `api_port()`; `readiness_timeout_seconds()`. Add each to the module's
`Named symbols:` docstring list.

Write `services/api/middleware.py` with four public symbols: `redact_path`, `client_ip_from_scope`,
`RequestLog` and `ErrorBoundary`. Take the executed sketches in 05-RESEARCH.md §Code Examples as the
source; they are already `mypy --strict` and ruff clean, including the
`cast("list[tuple[bytes, bytes]]", scope.get("headers", []))` idiom the ASGI scope read needs.

`redact_path` matches a fixed tuple of sensitive prefixes covering the management, click and
unsubscribe paths and returns the prefix plus a placeholder segment; anything else falls through to a
regex matching a token-shaped segment (two long base64url runs joined by a dot). The docstring states
why the prefix match comes first: the regex alone would miss a truncated or malformed token, and a
malformed token is exactly the value most likely to be logged during an incident.

`client_ip_from_scope(scope, *, trust_proxy, hops)` implements BC-2. When `trust_proxy` is false it
returns the socket peer from `scope["client"]`. When true it splits the forwarded-for header, strips
whitespace, and indexes `hops + 1` from the END — with `hops=1` that is the second-to-last entry.
The docstring carries both reproduced failure modes as prose: taking the leading entry lets any
caller mint a fresh rate-limit bucket per request because Google's balancer appends to whatever the
client sent and verifies nothing before the last two entries, and taking the socket peer behind the
balancer collapses every caller onto one address and rate-limits the whole service as a single
client. A header with fewer entries than `hops + 1` falls back to the last entry, and a missing or
empty header falls back to the socket peer.

`RequestLog` is a pure ASGI callable. Non-`http` scopes pass straight through. It starts a
`time.perf_counter()`, reads or generates the request id (bounding an incoming `X-Request-ID` to a
sane length before it is ever logged), wraps `send` to capture the status from the response-start
message, to append the request-id response header there, and to stamp `ttfb_ms` at the first body
message; the log call itself lives in the `finally` so it runs after the LAST body message. Read
`scope.get("route")` in that same `finally` and log its `path` attribute as the route template — the
docstring states that the router has not matched before the inner app is called and that logging the
raw path instead would be both unbounded log cardinality and a token leak. Log exactly these fields:
event name, request id, method, redacted path, route template, status, `duration_ms`, `ttfb_ms`,
client ip. No body, no headers, no query string. State in the docstring that this is deliberately not
a `dispatch`-style middleware, because `call_next` returns the response object before any body byte
is written and a streaming connection would be recorded with a duration of roughly zero and no final
status — research measured the two side by side.

`ErrorBoundary` is a pure ASGI callable implementing BC-3. It calls the inner app inside a `try`. On
any exception it logs `safe_error(exc)` with the request id, and — only if the response has not
started — sends a 500 response-start plus a JSON body of the error shape and the request id. It never
re-raises. The docstring states the reason precisely: Starlette's own server-error middleware
re-raises after a custom handler builds its clean body, specifically so the server can log the
traceback, which in this repository would put a raw exception message carrying bound SQL parameters
and pydantic input echoes into the log stream in violation of the absolute `safe_error` rule. If the
response has already started, it logs and closes the stream rather than attempting a second
response-start.

Write `services/api/deps.py` with the request-scoped providers the routers share: `get_session`
yielding an `AsyncSession` from the shared factory, `get_redis` returning the lifespan Redis client
from `request.state`, and `get_request_id` reading the header the middleware set. Keep it free of
business logic; later plans add the bearer and admin guards here.

Write `services/api/routers/health.py` with `GET /healthz` returning a fixed ok body and touching
nothing — Cloud Run's liveness probe must not fail because Redis blipped — and `GET /readyz` running
each dependency check under its own `asyncio.wait_for` so one hung dependency cannot hang the probe:
a `SELECT 1` for the database and a `PING` for Redis. Build the response as a map of dependency name
to status and return 503 when any is unhealthy. Add a comment naming the `feed` entry 05-05 adds when
the SSE pump joins the lifespan, so the extension point is documented rather than discovered.

Edit `services/api/app.py` (04-04's file) to register the health router and install the middleware in
the exact order Pitfall 8 requires. Starlette applies middleware in reverse registration order, so
add CORS first (outermost — a rejected preflight is still logged), then `RequestLog`, then
`ErrorBoundary` last so it is outermost among ours and innermost to Starlette's. Put a comment above
the three calls stating the ordering rule and what each inversion would cost. Call
`configure_logging()` at the top of the lifespan, and route uvicorn's own error and access loggers
through structlog there as well, so no API log line escapes the redaction processors; note in the
comment that the process must therefore be started with uvicorn's logging config disabled, which the
Make target in 05-06 does.

Write `tests/unit/test_request_log.py` covering every `<behavior>` bullet about logging: build a
minimal ASGI app wrapped in `RequestLog`, drive it with hand-written scope/receive/send callables,
and capture records with structlog's testing capture. Include the streaming case by making the inner
app emit two body messages with a real delay between them and asserting `duration_ms` exceeds that
delay while `ttfb_ms` does not. Include the redaction case with a realistic token-shaped path.

Write `tests/unit/test_client_ip.py` (BC-2). It is the executable statement of the rate limit's
correctness: assert the trusted three-hop case, the three-different-spoofed-leading-entries case
collapsing to one answer, the single-entry case, the no-header case, and the untrusted case that
ignores the header entirely.

Write `tests/unit/test_api_logs_never_carry_payload.py` modelled on the existing
`tests/unit/test_logs_never_carry_payload.py` (BC-3). Raise an exception whose message embeds a
unique marker string, drive it through `ErrorBoundary`, and assert the marker appears in neither any
captured log record nor the response body, and that the exception did not propagate out of the
middleware. Add a second case whose marker sits in a token-shaped path segment.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_request_log.py tests/unit/test_client_ip.py tests/unit/test_api_logs_never_carry_payload.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_request_log.py tests/unit/test_client_ip.py tests/unit/test_api_logs_never_carry_payload.py -q` exits 0.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run python -c "from services.api.app import create_app; app=create_app(); print(sorted(r.path for r in app.routes if getattr(r,'path','') in ('/healthz','/readyz')))"` prints `['/healthz', '/readyz']`.
    - `uv run python -c "from services.api.app import create_app; print([m.cls.__name__ for m in create_app().user_middleware])"` prints a list whose FIRST element is `ErrorBoundary` and whose LAST element is `CORSMiddleware`.
    - `uv run python -c "from services.api.middleware import client_ip_from_scope as f; s={'client':('10.0.0.1',1),'headers':[(b'x-forwarded-for',b'1.2.3.4, 203.0.113.9, 35.191.0.1')]}; print(f(s,trust_proxy=True,hops=1), f(s,trust_proxy=False,hops=1))"` prints `203.0.113.9 10.0.0.1`.
    - `uv run python -c "from services.api.middleware import redact_path as r; print(r('/api/manage/'+'a'*40+'.'+'b'*43), r('/api/restaurants/lilia'))"` prints a first field ending in `{token}` and a second field equal to `/api/restaurants/lilia`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>One request travels the whole stack — CORS, request log, error boundary, router — and produces a redacted, correctly-timed structured log line plus an echoed request id; an exception on that same path produces a clean JSON 500 and a scrubbed log field, and nothing re-raises.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Prometheus exposition on the shared registry, the Phase-5 metric definitions, both test tiers, and the async-only gate</name>
  <files>shared/metrics.py, shared/telemetry.py, services/api/routers/metrics.py, services/api/app.py, tests/unit/test_metrics_registry.py, tests/unit/test_api_async_only.py, tests/integration/conftest.py, tests/integration/test_api_plumbing.py, tests/integration/test_metrics.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"`/api/metrics` (D-101)" — the exposition transcript, `excluded_handlers` proof, the duplicate-registration error and the silent two-registry hazard
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"The uvicorn integration harness (BC-1)" and §"Blocking Corrections" BC-1
    - shared/metrics.py as shipped by 03-02 (the single-definition-site rule, the explicit-buckets comment, and the `Counter("x_total")` sample-name trap note)
    - tests/unit/test_metrics_registry.py (the double-import test and the `get_sample_value` idiom)
    - tests/integration/conftest.py lines 1-80 (`reset_shared_db_singletons`, `apply_migrations`, `create_topics`, `redis_url`, `db_urls`)
    - .planning/phases/03-resy-playwright-fleet/03-04-browser-harness-fingerprints-stealth-PLAN.md — the `stub_base` uvicorn-on-an-ephemeral-port fixture recipe (D-71); if it has landed on disk by execution time, share its helper rather than re-deriving it
    - tests/unit/test_no_inline_sleep.py and tests/unit/test_no_setnx_expire_pairs.py (the comment-stripping scan and the non-vacuity companion)
    - shared/telemetry.py lines 97-135 (`_SECRET_KEYS` and the redaction processor)
  </read_first>
  <behavior>
    - `GET /api/metrics` returns 200 with the content type constant the client library exports, and its body contains a `sse_connections_active` sample line.
    - Incrementing `watch_create_total` in-process changes the value that `/api/metrics` reports for it.
    - After several requests to other routes, `/api/metrics` carries no `http_requests_total` series whose handler label is `/api/metrics`, `/healthz` or `/readyz`.
    - `shared.metrics` imported twice in one process does not raise a duplicate-timeseries error.
    - A CORS preflight from an allowed origin returns the allow-origin header; one from an unlisted origin does not.
    - The `live_api` fixture yields a base URL that answers `GET /healthz` with 200 over a real socket, and the process exits cleanly at teardown.
    - The `api_app` fixture yields an app whose `GET /readyz` reports both dependencies healthy against the containers.
    - A source scan of `services/api/**` finds no synchronous HTTP client import, no blocking sleep call, and no synchronous Redis import.
  </behavior>
  <action>
Extend `shared/metrics.py` — the single definition site 03-02 established — with the Phase-5 metrics
D-101 names, defined exactly once against the same registry every other metric in that module uses:
`sse_connections_active` as a Gauge, `sse_events_sent_total` and `sse_dropped_total` as Counters,
`sse_pump_errors_total` as a Counter (research Pitfall 7: a dead pump serves 200s with a silent
feed), `watch_create_total` as a Counter labelled by result, `api_rate_limited_total` as a Counter
labelled by bucket, and `watch_count_recount_failures_total` as a Counter (Pitfall 11). Also export
the registry object itself under a named symbol so `Instrumentator(registry=…)` and `generate_latest`
can be handed the SAME object; the module comment states the hazard in full — registering one metric
name in two registries is silent, and the endpoint would then serve a gauge frozen at zero while the
real one climbs elsewhere. Add every new name to the `Named symbols:` docstring list.

Write `services/api/routers/metrics.py` with `GET /api/metrics`, `include_in_schema=False`, no
authentication (D-101 makes this deliberate and DEPLOY-05 depends on it), returning
`generate_latest` over the shared registry with the library's own content-type constant rather than a
hand-written media type — the escaping and the help/type preamble are versioned and not worth
reproducing. Put a comment on the route stating the privacy rule that goes with a public endpoint: no
metric may carry a label holding a user id, an email, a phone or a token, which is also the
cardinality rule.

In `services/api/app.py`, construct the instrumentator with streaming duration excluded and the
metrics, liveness and readiness handlers excluded, handing it the shared registry object, and
instrument the app at construction time — before any streaming route exists, so the configuration can
never be retrofitted after a 30-minute connection has already poisoned the latency histogram. Add the
comment explaining that the instrumentator's own duration is measured to request completion, which
for a live feed is the whole connection lifetime. Register the metrics router.

Extend `shared/telemetry.py`'s redaction set: the secret-key membership check becomes a prefix check
so every versioned management secret is covered rather than only the first, and `ADMIN_BASIC_PASSWORD`
joins the set alongside the value-shaped keys `token` and `management_url`.
Assert the three new redaction rules in `tests/unit/test_api_logs_never_carry_payload.py` — this
plan's own module, written in Task 2 — rather than in `tests/unit/test_telemetry_redaction.py`,
whose existing Phase-3 and Phase-4 assertions must stay untouched: one test module, one owning plan.

Extend `tests/unit/test_metrics_registry.py` with the Phase-5 additions: the double-import case still
passes, each new metric is readable through `get_sample_value` under its correct sample name (the
counter suffix trap the module already documents), and the registry object the module exports is the
one the metrics router serves.

Write `tests/unit/test_api_async_only.py` as a grep gate scoped to `services/api/**`, copying both
halves of the established idiom: strip full-line comments before scanning so a comment can neither
satisfy nor break the gate, and add the mandatory non-vacuity companion asserting the scanned set is
non-empty and contains the modules this phase creates. Assert the absence of a synchronous HTTP
client import, a blocking sleep call, and a synchronous Redis import, matching the rules
`.ruff.toml` and CLAUDE.md already state for `services/` and `shared/`.

Extend `tests/integration/conftest.py` with the two fixtures BC-1 requires, sharing one helper. The
`api_app` fixture sets the container URLs into the environment, calls `reset_shared_db_singletons()`,
imports `create_app` INSIDE the fixture body so collection never needs the app, and yields the
constructed app for `ASGITransport`-based request/response tests. The `live_api` fixture binds an
ephemeral port by opening and closing a socket, runs a `uvicorn.Server` with lifespan enabled as a
task, waits for the server's own started flag under a bounded wait, yields the base URL, and shuts
down by setting the exit flag and awaiting the task under a bounded wait — never by cancelling the
serve task. Do not add the signal-handler workaround; it has no effect in the pinned uvicorn. Put a
module comment stating the BC-1 rule every later test module must restate in its own docstring: plain
request/response routes may use the buffering transport, and anything that streams or reads lifespan
state must use the live server.

Write `tests/integration/test_api_plumbing.py` covering the CORS preflight pair, `/readyz` healthy
against the containers, and a `live_api` smoke request to `/healthz` proving the harness itself works.
Write `tests/integration/test_metrics.py` covering the content type, the presence of a Phase-5 sample
line, the in-process increment being visible through the endpoint, and the absence of any request
series about the excluded handlers. Each module's docstring names which tier it uses and why.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_metrics_registry.py tests/unit/test_api_async_only.py -q -W error::RuntimeWarning &amp;&amp; uv run pytest tests/integration/test_api_plumbing.py tests/integration/test_metrics.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run pytest tests/integration/test_api_plumbing.py tests/integration/test_metrics.py -q -p no:cacheprovider` exits 0.
    - `uv run python -c "from services.api.app import create_app; print('/api/metrics' in {getattr(r,'path','') for r in create_app().routes})"` prints `True`.
    - `uv run python -c "import shared.metrics as m; print(all(hasattr(m,n) for n in ('sse_connections_active','sse_events_sent_total','sse_dropped_total','sse_pump_errors_total','watch_create_total','api_rate_limited_total','watch_count_recount_failures_total')))"` prints `True`.
    - `uv run python -c "import importlib, shared.metrics as a; b=importlib.import_module('shared.metrics'); print(a is b)"` prints `True` and exits 0 (no duplicate-timeseries error).
    - `uv run python -c "import inspect, tests.integration.conftest as c; print(sorted(n for n in dir(c) if n in ('api_app','live_api')))"` prints `['api_app', 'live_api']`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>`/api/metrics` serves the same registry the code writes into, streaming durations can never poison the latency histogram, both BC-1 test tiers exist and are proven by a real request, and an async-only gate guards `services/api/**` from its first file.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (05-01 slice)

**New modules:** `shared/servicetime.py`, `services/api/middleware.py`, `services/api/deps.py`,
`services/api/routers/health.py`, `services/api/routers/metrics.py`.

**Modified modules:** `services/api/config.py` (extend 04-04's), `services/api/app.py` (extend
04-04's), `shared/metrics.py` (extend 03-02's), `shared/telemetry.py`,
`services/state_machine/persistence.py` (re-export only).

**HTTP routes:** `GET /healthz` (200, no dependency touched), `GET /readyz` (200 / 503 with a
per-dependency map), `GET /api/metrics` (200, unauthenticated, `include_in_schema=False`).

**New symbols — `shared/servicetime.py`:** `SERVICE_TZ`, `hours_before_service`.

**New symbols — `services/api/middleware.py`:** `redact_path`, `client_ip_from_scope`, `RequestLog`,
`ErrorBoundary`.

**New symbols — `services/api/deps.py`:** `get_session`, `get_redis`, `get_request_id`.

**New config accessors — `services/api/config.py`:** `kafka_bootstrap_servers()`,
`cors_allowed_origins()`, `trust_proxy_headers()`, `proxy_hops()`, `admin_basic_user()`,
`admin_basic_password()`, `api_port()`, `readiness_timeout_seconds()`.

**New metrics — `shared/metrics.py`:** `sse_connections_active` (Gauge), `sse_events_sent_total`,
`sse_dropped_total`, `sse_pump_errors_total`, `watch_create_total{result}`,
`api_rate_limited_total{bucket}`, `watch_count_recount_failures_total`, plus the exported registry
object.

**Env vars introduced:** `CORS_ALLOWED_ORIGINS`, `TRUST_PROXY_HEADERS`, `PROXY_HOPS`,
`ADMIN_BASIC_USER`, `ADMIN_BASIC_PASSWORD`, `API_PORT`. Documented in `.env.example` by 05-06.

**Test helpers:** `tests/integration/conftest.py :: api_app` (buffering transport tier) and
`:: live_api` (in-process uvicorn tier, BC-1).

**Response headers introduced:** `X-Request-ID` on every response.
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| public internet -> every API route | Unauthenticated, attacker-controlled method, path, headers and body |
| load balancer -> API process | `X-Forwarded-For` is appended-to, not verified, before the last two entries |
| API process -> log sink | Every exception message, path and header is a potential exfiltration channel |
| public internet -> `/api/metrics` | Deliberately unauthenticated; every label is public |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-05-01 | Information Disclosure | unhandled exception -> log sink | high | mitigate | `ErrorBoundary` catches, renders via `safe_error` and never re-raises, so Starlette's traceback logger is unreachable (BC-3); a marker-string test is the gate |
| T-05-02 | Information Disclosure | management/click token in a logged path | high | mitigate | `redact_path` prefix match plus a token-shaped-segment regex; query strings dropped; unit-tested on all four sensitive prefixes |
| T-05-03 | Denial of Service | forged `X-Forwarded-For` minting a fresh rate bucket per request | high | mitigate | `client_ip_from_scope` takes the second-to-last hop; three spoofed leading entries collapse to one answer in `tests/unit/test_client_ip.py` (BC-2) |
| T-05-04 | Denial of Service | trusting the socket peer behind the balancer, rate-limiting all callers as one | high | mitigate | Same function, the `trust_proxy` branch; the untrusted-mode case is separately asserted |
| T-05-05 | Information Disclosure | a metric label carrying a user id, email, phone or token on a public endpoint | medium | mitigate | Label sets are fixed at definition time in `shared/metrics.py` (`result`, `bucket`, `source`, `reason`, `status`, `mode` only); the rule is stated on the route |
| T-05-06 | Denial of Service | `/readyz` hanging on a stalled dependency and failing the whole revision | medium | mitigate | Each check runs under its own bounded wait; `/healthz` touches no dependency at all |
| T-05-07 | Spoofing | attacker-supplied `X-Request-ID` poisoning log correlation | low | accept | Treated as a correlation hint only, never as identity; length-bounded before it is logged |
| T-05-08 | Information Disclosure | unauthenticated `/api/metrics` exposing operational volume | low | accept | Deliberate per D-101; DEPLOY-05 requires a public dashboard and the data is aggregate only |
| T-05-SC | Tampering | package-manager installs | high | mitigate | Zero packages added — this phase installs nothing (research §Package Legitimacy Audit); every library used is already pinned and already imported by shipped code |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run pytest tests/unit/test_phase5_preconditions.py -q` exits 0 — the Wave-0 gate.
</verification>

<success_criteria>
- Every upstream Phase 3/4 artifact is asserted present by name and owning decision id before any API route is written.
- An unhandled exception produces a clean JSON body and a scrubbed log field, and nothing re-raises.
- A streaming response is logged with its real duration; a token-bearing path is logged redacted.
- The client address is resolved from the second-to-last forwarded hop and proven immune to a spoofed leading entry.
- `/api/metrics` serves the one registry the code writes into, with liveness, readiness and itself excluded from request series.
- Both BC-1 test tiers exist in `tests/integration/conftest.py` and are exercised by a real request.
</success_criteria>

<output>
Create `.planning/phases/05-api-watchlist-crud-sse/05-01-SUMMARY.md` when done
</output>
