---
phase: 07-deploy-observability-portfolio-polish
plan: 03
type: execute
wave: 2
depends_on: ["07-01"]
autonomous: true
requirements: [DEPLOY-05, DEPLOY-06]
files_modified:
  - shared/metrics.py
  - shared/observability.py
  - shared/telemetry.py
  - pyproject.toml
  - services/poller/main.py
  - services/state_machine/main.py
  - services/notifier/main.py
  - services/api/main.py
  - tests/unit/test_metrics_registry.py
  - tests/unit/test_metrics_exposition.py
  - tests/unit/test_init_sentry_noop.py
  - tests/unit/test_sentry_structlog_bridge.py
  - tests/unit/test_services_observability_wiring.py

estimate:
  tokens: 74000
  raw_tokens: 74000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "D-122: `shared/metrics.py` is the only definition site and declares all seven dashboard-facing metrics — `poll_total{source,status}`, `poll_latency_seconds{source}`, `events_emitted_total{source}`, `notifications_total{channel,status}`, `notification_latency_seconds{channel}`, `scrape_ban_total`, `sse_connections_active`."
    - "D-122 / Pitfall 3: `sse_connections_active` is a `Gauge`. A `Counter` of that name would be exposed as `sse_connections_active_total` and every panel querying it would render empty — the exposition test asserts the bare name is present and the `_total` variant is absent."
    - "D-122: every long-running service exposes Prometheus text on `METRICS_PORT` bound to `0.0.0.0` (poller 9101, state machine 9102, notifier 9103) via one shared `start_metrics_server` helper, and the API exposes `/api/metrics` on 8000."
    - "D-122 / Pitfall 4: `/api/metrics` responds 200 with `text/plain` content type and does **not** appear in `openapi.json` — Phase 5's `tests/unit/test_openapi_snapshot.py` (D-104) stays green and the client-facing schema stays free of scrape noise."
    - "D-124: `init_sentry()` with no `SENTRY_DSN` returns False, leaves `sentry_sdk.get_client().is_active()` False, and creates zero threads — the integration is genuinely free when unconfigured."
    - "D-124a / Pitfall 1 (DEPLOY-06 probe, adjacency — *when two things are exactly equal or just touch, do they merge, collide, or separate?*): two ERROR events from the same logger with the same event name MERGE into one Sentry issue because the fingerprint is `[logger_name, event_name]`; two with different event names SEPARATE. Without the custom processor the rendered JSON line — carrying a unique ISO timestamp — becomes the issue title and every single error separates into its own issue."
    - "D-124a / Pitfall 2 (DEPLOY-06 probe, ordering — *when elements compare equal, is output order specified and stable?*): the processor chain order is a specified contract, not a convention. `sentry_processor` runs immediately before `structlog.processors.format_exc_info`, because that processor replaces `exc_info` with a rendered string after which the traceback is unrecoverable; a unit test asserts the chain index relationship so the order cannot drift."
    - "D-124 (DEPLOY-06 probe, empty — *what is the result for empty, single-element, or null input?*): `SENTRY_DSN` unset, empty string, or whitespace all take the no-op path; `init_sentry(None)` and `init_sentry(\"\")` both return False. An ERROR event with no extra fields still produces exactly one event with a valid fingerprint."
    - "D-124 (DEPLOY-06 probe, concurrency — *if interrupted or run in parallel, what is guaranteed?*): every capture runs inside `sentry_sdk.new_scope()` so concurrent captures cannot cross-contaminate fingerprints or extras; the SDK's background transport means `capture_*` never blocks the event loop; `shutdown_timeout=2.0` bounds process exit so a SIGTERM cannot hang on a flush."
    - "V7 / D-124: no secret reaches Sentry. `sentry_processor` applies the existing `shared/telemetry.py` redactor to the event copy it sends, `send_default_pii=False`, and `before_send` drops `cookie`/`authorization` and the `sys.argv` extra the SDK adds automatically (which carries CLI arguments for the `scripts/` entry points)."
    - "D-127: the unit tier covers `init_sentry` no-op behaviour without a DSN and the structlog bridge's grouping, exception attachment and redaction, using an in-memory transport — never a network call."
  artifacts:
    - shared/observability.py
    - tests/unit/test_metrics_exposition.py
    - tests/unit/test_init_sentry_noop.py
    - tests/unit/test_sentry_structlog_bridge.py
    - tests/unit/test_services_observability_wiring.py
  key_links:
    - "`shared/metrics.py` metric identifiers → `ops/prometheus/rules/mise.rules.yml` and `ops/grafana/dashboards/mise.json` (07-04). The 07-04 drift guard imports this module and compares against the dashboard, so a rename here fails a test rather than emptying a panel."
    - "`start_metrics_server(port)` → the `HEALTHCHECK` baked into every image in 07-01, which probes `/metrics`. Until this plan lands, those containers are correctly unhealthy."
    - "`sentry_processor` position in `configure_logging`'s `shared_processors` → whether a `log.exception()` reaches Sentry with a traceback. This is a positional contract between two files."
  prohibitions:
    - "Must never define a Prometheus metric outside `shared/metrics.py`, and never inside a function — a duplicate registration raises at import time and takes the service down at startup (D-69)."
    - "Must never send an unredacted log field to Sentry. Redaction is applied to what is captured, not merely to what is printed."
    - "Must never redefine or relocate an artifact owned by Phases 3–6. If `/api/metrics` or the poller's metrics server already exists, assert its shape and adapt to it; do not re-create it."
  flagged_assumptions:
    - "Phase 5 D-101/D-101a is assumed to have created `/api/metrics` with `prometheus-fastapi-instrumentator`. Task 3 asserts its behaviour rather than re-adding it; if it is genuinely absent, Task 3 adds it with the D-101a knobs and the SUMMARY records that Phase 7 supplied a Phase-5 artifact."
    - "Phase 3 (03-06) is assumed to have started the poller's metrics server. Task 3 replaces a direct `start_http_server` call with the shared helper at the same port; if no server exists it adds one at 9101."
---

<objective>
Make every service observable: one metric registry, one metrics-exposition helper wired into all four services, and a Sentry integration that produces usable issues instead of noise.

Purpose: DEPLOY-05's launch-blocking public dashboard and DEPLOY-06's error tracking both depend on data that does not exist until the processes emit it. Two defects were reproduced in research that would have silently degraded this to decoration: Sentry grouping collapsing to one issue per occurrence, and `log.exception()` arriving with no exception attached. Both are fixed here, with tests, before any dashboard is drawn.

Output: the completed `shared/metrics.py` registry, `shared/observability.py`, the corrected structlog processor chain, and metrics + Sentry wired into all four service entrypoints.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-CONTEXT.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-RESEARCH.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-PATTERNS.md
@shared/metrics.py
@shared/telemetry.py
@CLAUDE.md
</context>

<package_legitimacy>
`sentry-sdk[fastapi]==2.68.1` is the one new runtime dependency. The Package Legitimacy Gate returned
**SUS** on the heuristics `too-new` and `unknown-downloads`. Both are false positives and the phase brief
supplies no human to clear a checkpoint, so D-124a records the disposition here instead: `sentry-sdk`
first released 2018-07-26, has 346 releases, lives at `github.com/getsentry/sentry-python` under the
official `getsentry` org, ships a PyPI wheel with no install scripts, and imports `urllib3` rather than
`requests` (verified — which is why the CI ban-grep stays green). The `too-new` signal fires on the
latest release date, not on package age. **Approved; no checkpoint task.** The executor must restate
this verdict, and the installed version, in the SUMMARY.
</package_legitimacy>

<artifacts_this_phase_produces>
- **Metrics:** `events_emitted_total{source}`, `notifications_total{channel,status}`, `notification_latency_seconds{channel}`, `sse_connections_active` appended to the existing `poll_total`, `poll_latency_seconds`, `scrape_ban_total` registry; `shared.metrics.start_metrics_server`.
- **Scripts/modules:** `shared/observability.py` (`init_sentry`, `sentry_processor`, `_scrub`).
- Compose services/profiles: consumed here, defined in 07-02 and 07-04.
- Workflows/docs: none — this plan is application glue only.
</artifacts_this_phase_produces>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1 (tracer): a metric declared once and scraped over HTTP</name>
  <files>shared/metrics.py, services/state_machine/main.py, tests/unit/test_metrics_exposition.py, tests/unit/test_metrics_registry.py</files>
  <read_first>
    - `shared/metrics.py` (whole file) — the mandated header, the existing three metrics, and the sample-name gotcha already documented at lines 31-38
    - `07-RESEARCH.md` §Code Examples "`shared/metrics.py` — the single definition site" (lines 1110-1126) and "Starting the metrics server inside an existing `AsyncExitStack`" (lines 1127-1138)
    - `07-RESEARCH.md` §Pitfall 3 — the measured `prometheus_client` suffix rules
    - `services/state_machine/main.py:81-145` — the `AsyncExitStack` acquisition order and the comment at `:99-104` explaining why a late `try/finally` was wrong
    - `tests/unit/test_metrics_registry.py` — the existing registry test's shape
  </read_first>
  <behavior>
    - `generate_latest(REGISTRY)` after importing `shared.metrics` contains the sample names `events_emitted_total`, `notifications_total`, `notification_latency_seconds_bucket`, `notification_latency_seconds_count`, and `sse_connections_active`.
    - The same output does **not** contain `sse_connections_active_total` — proving the Gauge choice, not merely asserting it.
    - Importing `shared.metrics` twice (the existing double-import test) still raises nothing.
    - `start_metrics_server(0)` returns a running server whose bound port serves HTTP 200 at `/metrics` with a body containing `poll_total`; calling the returned shutdown callable stops the thread within 2 seconds.
  </behavior>
  <action>
Append to `shared/metrics.py`, in the file's existing style (a section comment naming the decision id,
then the metric, then a comment on anything non-obvious): `events_emitted` as a `Counter` labelled
`["source"]` — declared without the `_total` suffix because `prometheus_client` appends it, and the
comment says so; `notifications_total` as a `Counter` labelled `["channel", "status"]`;
`notification_latency_seconds` as a `Histogram` labelled `["channel"]` covering detection-to-send, using
buckets that reach the PERF-01 60-second ceiling; and `sse_connections_active` as a `Gauge` with a
comment recording that a `Counter` here would expose `sse_connections_active_total` and silently empty
the dashboard panel.

Add `start_metrics_server(port: int, addr: str = "0.0.0.0") -> tuple[Any, Callable[[], None]]` to the
same module: it calls `prometheus_client.start_http_server(port, addr=addr, registry=REGISTRY)` and
returns the server object together with a shutdown callable that performs `server.shutdown()` and joins
the daemon thread with a bounded timeout. Bind `0.0.0.0` so Prometheus can reach it across the compose
network while the container healthcheck still probes `127.0.0.1`. Document in the docstring that the
returned thread is a daemon WSGI thread which introduces no `time.sleep(`, no `requests` and no sync
`redis` import, so all three CI ban-greps stay green, and that it must not be "fixed" into an async
server.

Wire it into `services/state_machine/main.py`: inside the existing `AsyncExitStack`, before the Redis
client is acquired, start the server on `int(os.getenv("METRICS_PORT", "9102"))` and register the
shutdown callable with `stack.callback(...)` so teardown stays LIFO and matches the file's own
docstring.

Create `tests/unit/test_metrics_exposition.py` implementing the behaviours above. Bind the server on
port 0 and read the actual port from the server object so the test cannot collide with a developer's
running stack. Extend `tests/unit/test_metrics_registry.py` with the four new names using
`REGISTRY.get_sample_value` (reading the emitted sample name, not the constructor argument — the file's
own docstring explains why those differ).
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_metrics_exposition.py tests/unit/test_metrics_registry.py -q -W error::RuntimeWarning` exits 0.
    - `uv run python -c "from prometheus_client import generate_latest, REGISTRY; import shared.metrics; b=generate_latest(REGISTRY).decode(); assert 'sse_connections_active ' in b; assert 'sse_connections_active_total' not in b; print('ok')"` prints `ok`.
    - `uv run mypy shared/ services/` exits 0.
    - `grep -rn "Counter(\|Gauge(\|Histogram(" services/ shared/ | grep -v '^shared/metrics.py' | wc -l` returns 0 (single definition site preserved).
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_metrics_exposition.py tests/unit/test_metrics_registry.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>One metric travels from its single declaration site through a running service's HTTP endpoint to a scrape-shaped response body — the whole exposition path is proven on one service before it is replicated to three more.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: `shared/observability.py` and the corrected structlog processor chain</name>
  <files>shared/observability.py, shared/telemetry.py, pyproject.toml, tests/unit/test_init_sentry_noop.py, tests/unit/test_sentry_structlog_bridge.py</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 10 (lines 790-827) — the verified `init_sentry` body and the measured no-op behaviour (zero threads, `is_active()` False)
    - `07-RESEARCH.md` §Pitfall 1 (lines 895-913) and §Pitfall 2 (lines 914-965) — both defects reproduced, with the verified processor fix and its required chain position
    - `shared/telemetry.py:88-183` — `_SECRET_KEYS`, `_SECRET_KEYS_CI`, `_PROXY_KEYS_CI`, `_mask_proxy_credentials`, `_redact_secrets`; the module-level processor idiom and the docstring voice
    - `shared/telemetry.py:196-204` — the `shared_processors` list this task edits
    - `tests/unit/test_telemetry_redaction.py` — the repo's style for asserting on a captured event dict
  </read_first>
  <behavior>
    - `init_sentry(None)` → returns `False`; `sentry_sdk.get_client().is_active()` is `False`; `threading.active_count()` is unchanged.
    - `init_sentry("")` and `init_sentry("   ")` behave identically to `init_sentry(None)`.
    - `init_sentry("https://k@example.invalid/1")` → returns `True` and `is_active()` is `True`.
    - With a fake in-memory transport: one `log.error("message_retries_exhausted", topic="availability.raw", attempts=5)` produces exactly ONE event whose message is `message_retries_exhausted` (not a JSON line) and whose fingerprint is `["<logger name>", "message_retries_exhausted"]`, with `topic` and `attempts` present as extras.
    - `log.exception("kafka_send_failed")` raised from inside an `except ValueError` block produces an event carrying a real `ValueError` exception object with a traceback — not a string, and not `None`.
    - An event logged with `authorization="Bearer secret"` and `cookie="s=1"` reaches the transport with both values replaced by the redaction sentinel, and no `sys.argv` extra is present.
    - Two `log.error("same_event")` calls from the same logger produce two events that share one fingerprint; a `log.error("other_event")` produces a different fingerprint.
    - `configure_logging()` places `sentry_processor` at a lower chain index than `structlog.processors.format_exc_info`.
  </behavior>
  <action>
Add `sentry-sdk[fastapi]==2.68.1` to `[project.dependencies]` in `pyproject.toml` and refresh `uv.lock`
with `uv lock` (never `uv add --frozen`; the lock must actually resolve). Record the legitimacy verdict
from this plan's `<package_legitimacy>` block in the SUMMARY.

Create `shared/observability.py` with three module-level symbols and the repo's docstring voice — every
docstring names the failure it prevents:

`init_sentry(dsn: str | None = None, *, env: str | None = None) -> bool` — resolves the DSN from the
argument or `SENTRY_DSN`, treats blank and whitespace-only as unset and returns `False` without touching
the SDK; otherwise calls `sentry_sdk.init` with `environment` from `ENV`, `release` from `GIT_SHA`,
`send_default_pii=False`, `traces_sample_rate=0.0`, `shutdown_timeout=2.0` (bounded so SIGTERM cannot
hang on a flush — a comment records that this adds up to two seconds to every container stop and where
that comes from), `integrations=[LoggingIntegration(level=logging.INFO, event_level=None)]`, and
`before_send=_scrub`. `event_level=None` is load-bearing and its comment says why: with the default the
whole rendered JSON line, unique timestamp included, becomes the issue title.

`sentry_processor(logger, method, event_dict)` — a structlog processor that, for `error`/`exception`/
`critical` methods and only when the client is active, opens a `sentry_sdk.new_scope()`, sets the level,
sets `scope.fingerprint` to `[event_dict["logger"], event_dict["event"]]`, copies every field except
`event`/`level`/`logger`/`timestamp`/`exc_info` into scope extras **after** passing that copy through
`shared.telemetry._redact_secrets`, and then captures either the exception (from `event_dict["exc_info"]`,
resolving `True` via `sys.exc_info()`) or the message. It returns `event_dict` unchanged. Do not use the
private `scope._level`; pass the level string. The docstring states that this function must run before
`format_exc_info` and why.

`_scrub(event, hint)` — the `before_send` hook: drop the `sys.argv` extra the SDK adds automatically
(it carries CLI arguments for the `scripts/` entry points), and apply the same key-name policy to
`extra`, `request.headers` and `contexts`. Import the key sets from `shared/telemetry.py`; do not write
a second key list.

Edit `shared/telemetry.py`'s `shared_processors` to insert `sentry_processor` immediately before
`structlog.processors.format_exc_info`, with an inline comment naming the defect the position prevents.
Import it lazily or guard the import so `shared/telemetry.py` keeps working if `sentry_sdk` is somehow
absent — a logging module that cannot import is a service that cannot start.

Create `tests/unit/test_init_sentry_noop.py` and `tests/unit/test_sentry_structlog_bridge.py`
implementing the behaviours above, using a fake transport that collects envelopes in memory (never a
network call). Add a test asserting the chain-index relationship between `sentry_processor` and
`format_exc_info`.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_init_sentry_noop.py tests/unit/test_sentry_structlog_bridge.py -q -W error::RuntimeWarning` exits 0 with at least 8 tests collected.
    - `uv run mypy shared/` exits 0.
    - `uv run ruff check .` exits 0.
    - `! grep -rn "^import requests\|^from requests " services/ shared/` exits 0 (the CI ban-grep stays green after adding the SDK).
    - `grep -c 'sentry-sdk\[fastapi\]==2.68.1' pyproject.toml` returns 1.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_init_sentry_noop.py tests/unit/test_sentry_structlog_bridge.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>Sentry is inert without a DSN, produces one stably-grouped issue per distinct error with a real traceback attached, and cannot exfiltrate a redacted field — each of those four properties pinned by a test rather than by a comment.</done>
</task>

<task type="auto">
  <name>Task 3: wire metrics and Sentry into all four service entrypoints</name>
  <files>services/poller/main.py, services/state_machine/main.py, services/notifier/main.py, services/api/main.py, tests/unit/test_services_observability_wiring.py</files>
  <read_first>
    - `services/state_machine/main.py:81-145` — the reference wiring completed in Task 1
    - `services/poller/main.py` and `services/poller/config.py:145,297` — `DEFAULT_METRICS_PORT = 9101` and the existing metrics-port accessor
    - `services/notifier/main.py` and `services/api/` as Phases 4 and 5 left them
    - `07-RESEARCH.md` §Pitfall 4 (lines 982-1002) — the verified `Instrumentator` configuration, the `/api/metrics` response shape, and the OpenAPI-snapshot interaction with Phase 5 D-104
    - `.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md` D-101 and D-101a — Phase 5 owns `/api/metrics`; Phase 7 adapts to it
    - `tests/unit/test_no_inline_sleep.py:18-59` — grep-gate shape with comment stripping and the non-vacuity assertion
  </read_first>
  <action>
Call `init_sentry()` immediately after `configure_logging()` in all four service entrypoints
(`services/poller/main.py`, `services/state_machine/main.py`, `services/notifier/main.py`, and the
Phase-5 API's lifespan or `create_app`). It is a no-op without a DSN, so this is safe in every
environment and needs no guard.

Start the metrics server via `shared.metrics.start_metrics_server` in the poller and the notifier,
registering the shutdown callable on each service's existing `AsyncExitStack`. For the poller: if Phase 3
already calls `prometheus_client.start_http_server` directly, replace that call with the shared helper at
the same port and keep `services/poller/config.py`'s `metrics_port()` accessor as the port source — do
not change the port or add a second server.

For the API: assert rather than re-create. If Phase 5 already exposes `/api/metrics`, leave the route
alone and only add `init_sentry()`. If it is genuinely absent, add it with the D-101a knobs —
`should_group_status_codes=False`, `should_ignore_untemplated=True` (this is what keeps `/watches/abc`
and `/watches/def` on one `handler="/watches/{wid}"` series instead of one series per id),
`should_exclude_streaming_duration=True`, `excluded_handlers` covering `/api/metrics`, `/healthz` and
`/readyz` — and expose it with `include_in_schema=False` and `should_gzip=False`.

Create `tests/unit/test_services_observability_wiring.py`: a grep gate over
`services/*/main.py` (plus the API's app module) that strips comments first and asserts every service
entrypoint references `init_sentry(`, that the three long-running services reference
`start_metrics_server(`, and that no service calls `prometheus_client.start_http_server` directly any
more. Add the non-vacuity assertion: at least four entrypoints scanned, and the scanned stems include
`poller`, `state_machine`, `notifier` and the API module. In the same file, add an ASGI-transport test
that `GET /api/metrics` on the Phase-5 app returns 200 with a `text/plain` content type and a body
containing `sse_connections_active`, and that `/api/metrics` is absent from the app's generated OpenAPI
paths.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_services_observability_wiring.py -q -W error::RuntimeWarning` exits 0.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0 — in particular Phase 5's `tests/unit/test_openapi_snapshot.py` is unchanged and still passes.
    - `uv run mypy shared/ services/ scripts/` exits 0 and `uv run ruff check .` exits 0.
    - `! grep -rn "time\.sleep(" services/ shared/` and `! grep -rEn "^import redis$|^from redis import " services/ shared/` both exit 0.
    - Against a running stack: `docker compose -f ops/docker-compose.yml --profile smoke up -d --wait --wait-timeout 300` exits 0 and `curl -fsS http://127.0.0.1:8000/api/metrics | grep -c sse_connections_active` returns at least 1.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_services_observability_wiring.py -q -W error::RuntimeWarning && uv run mypy shared/ services/ scripts/</automated>
  </verify>
  <done>Every service reports its own metrics and its own errors, the image healthchecks written in 07-01 now have something to succeed against, and a grep gate keeps the wiring from being dropped by a future refactor.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| service process → Sentry SaaS | Error payloads leave the trust domain entirely, carrying whatever the log call put in scope. |
| Prometheus scraper → service `/metrics` | An unauthenticated endpoint on the compose network exposes internal counters. |
| log call site → structlog processor chain | Every field a developer logs transits the redactor before it can leave the process. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-07-09 | Information disclosure | Sentry event payloads | critical | mitigate | `send_default_pii=False`; `sentry_processor` redacts the copy it captures using the existing `_redact_secrets` key policy; `before_send` drops the auto-added `sys.argv` extra; a unit test proves `authorization` and `cookie` arrive redacted. |
| T-07-10 | Information disclosure | `/metrics` and `/api/metrics` | low | accept | Endpoints are unauthenticated by design (D-101 calls `/api/metrics` a public route) and expose only aggregate counters with bounded label sets — no identifiers. Ports are published only where the compose file says so. |
| T-07-11 | Denial of service | metric cardinality | medium | mitigate | Label sets are fixed at `{source,status}` / `{channel,status}` and `should_ignore_untemplated=True` keeps route templates from exploding into per-id series; no `restaurant_id` or `date` label is ever added. |
| T-07-12 | Denial of service | Sentry flush on shutdown | low | mitigate | `shutdown_timeout=2.0` bounds the exit-time flush so `docker stop` cannot hang indefinitely. |
| T-07-SC | Tampering | `sentry-sdk[fastapi]==2.68.1` | high | mitigate | Legitimacy verdict recorded in `<package_legitimacy>` (SUS heuristics are false positives; official `getsentry` org, 8 years old, no install scripts, imports `urllib3` not `requests`). Installed from `uv.lock` with `--frozen` in every image. No human checkpoint is available this run; the verdict must be restated in the SUMMARY. |
</threat_model>

<verification>
1. `uv run pytest tests/unit -q -W error::RuntimeWarning` — exit 0, including all four new test files and the untouched Phase-5 OpenAPI snapshot.
2. `uv run ruff check . && uv run mypy shared/ services/ scripts/` — exit 0.
3. The three CI ban-greps all return no matches after adding `sentry-sdk`.
4. `docker compose --profile smoke up -d --wait` — the three service containers now reach `healthy`, because their image healthchecks finally have a `/metrics` to hit.
5. `curl -fsS http://127.0.0.1:9102/metrics | grep -c events_emitted_total` returns at least 1.
</verification>

<success_criteria>
- Seven dashboard-facing metrics are declared exactly once and exposed by the processes that own them.
- Sentry is free when unconfigured, correctly grouped when configured, carries real tracebacks, and leaks nothing.
- The processor-chain position and the wiring of all four services are enforced by tests, not by memory.
- No Phase 3–6 artifact is redefined; where one already exists, its shape is asserted instead.
</success_criteria>

<output>
Create `.planning/phases/07-deploy-observability-portfolio-polish/07-03-SUMMARY.md` when done.
Record: the `sentry-sdk` legitimacy verdict and installed version, whether `/api/metrics` and the poller's
metrics server already existed (and what was adapted versus added), and the final `shared_processors`
chain order.
</output>
