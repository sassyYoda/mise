# Phase 7: Deploy, Observability & Portfolio Polish — Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 47 new/modified files
**Analogs found:** 31 / 47 (16 have no in-repo analog — see §No Analog Found)

Two analog sources are used and they are **not** interchangeable:

| Source | Notation | Trust |
|--------|----------|-------|
| Files on disk in this repo | `path:line` | Real, committed, style-of-record. **Copy these.** |
| Research scratch dir (executed, verified, not committed) | `RESEARCH §Pattern N` / `SCRATCH/<path>` | Verified-to-run reference implementations. Copy the *mechanics*, then re-dress in repo style. |

`SCRATCH` = `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-07/`
`RESEARCH` = `.planning/phases/07-deploy-observability-portfolio-polish/07-RESEARCH.md`

**Hard precondition (A1, D-127 Wave 0):** `services/notifier/`, `services/api/`, `web/`, and the Phase-4/5/6 test suites **do not exist on disk today** (`ls services/` → `poller  state_machine` only). Every pattern below that names them is written against the defining decision, not against code. Wave 0 must halt if they are still absent.

---

## File Classification

### Container packaging (DEPLOY-01)

| New/Modified File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `ops/docker/state_machine.Dockerfile` | config (build) | batch | `SCRATCH/build/ops/docker/state_machine.Dockerfile` + RESEARCH §Pattern 1 (:278-327) | exact (verified build, 661 MB) |
| `ops/docker/notifier.Dockerfile` | config (build) | batch | same as above, `ENTRYPOINT`/`METRICS_PORT=9103` swapped | exact |
| `ops/docker/api.Dockerfile` | config (build) | request-response | same as above, `uvicorn` entrypoint, `EXPOSE 8000` | role-match |
| `ops/docker/poller.Dockerfile` | config (build) | streaming | `SCRATCH/build/ops/docker/poller.Dockerfile` + RESEARCH §Pattern 2 (:329-397) | exact (verified, Chromium 145 as `pwuser`) |
| `ops/docker/web.Dockerfile` | config (build) | request-response | RESEARCH §Pattern 3 (:399-440) | exact (verified, 340 MB) |
| `.dockerignore` (new, repo root) | config | — | none | **no analog** — RESEARCH :1364 lists the required entries |

### Compose + ops config (DEPLOY-01, DEPLOY-05)

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `ops/docker-compose.yml` (modified) | config | — | itself, `ops/docker-compose.yml:4-96` | exact (in-place extension) |
| `ops/prometheus/prometheus.yml` | config | pub-sub (scrape) | `SCRATCH/obs/prometheus/prometheus.yml`, RESEARCH :542-567 | exact (targets verified `up==1`) |
| `ops/prometheus/rules/mise.rules.yml` | config | transform | `SCRATCH/obs/prometheus/rules/mise.rules.yml`, RESEARCH :770-789 | exact (`promtool check rules` → 5 rules) |
| `ops/grafana/provisioning/datasources/prometheus.yml` | config | — | `SCRATCH/obs/grafana/provisioning/datasources/prometheus.yml`, RESEARCH :512-524 | exact |
| `ops/grafana/provisioning/dashboards/mise.yml` | config | — | `SCRATCH/obs/grafana/provisioning/dashboards/mise.yml`, RESEARCH :527-540 | exact |
| `ops/grafana/dashboards/mise.json` | config | — | `SCRATCH/obs/grafana/dashboards/mise.json` | exact (5 panels read back anonymously) |

### Application glue (DEPLOY-05, DEPLOY-06)

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `shared/metrics.py` (modified — **append only**) | model (registry) | — | `shared/metrics.py:1-60` (exists, Phase 3) | exact |
| `shared/observability.py` (new) | utility | event-driven | `shared/telemetry.py:87-183` (redactor + processor idiom) + RESEARCH §Pattern 10/Pitfall 2 | role-match |
| `shared/telemetry.py` (modified) | utility | event-driven | itself, `shared/telemetry.py:196-204` | exact |
| `services/state_machine/main.py` (modified) | service entrypoint | streaming | itself, `services/state_machine/main.py:81-145` | exact |
| `services/poller/main.py`, `services/notifier/main.py`, `services/api/main.py` (modified) | service entrypoint | streaming / request-response | `services/state_machine/main.py:81-145` | role-match (notifier/api do not exist yet — A1) |
| `web/src/app/healthz/route.ts` (new) | route | request-response | none in repo (`web/` absent) | **no analog** — RESEARCH :440 |

### Scripts (DEPLOY-04, DEPLOY-07, PERF-04)

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `scripts/post_deploy_check.py` | utility (CLI gate) | request-response | `scripts/check_poll_success.py:1-132` (exit-code + shape) + RESEARCH §Pattern 7 (lag recipe) | exact + mechanics |
| `scripts/uptime_report.py` | utility (CLI gate) | request-response | `scripts/check_poll_success.py:1-132` + RESEARCH §Pattern 12 | role-match |
| `scripts/status_report.py` | utility (generator) | file-I/O | `scripts/replay_raw.py:425-483` (argparse + `main(argv) -> int`) | role-match |
| `scripts/render_diagram.py` | utility | file-I/O | RESEARCH §Pattern 11 (:828-851) | mechanics only |

### CI/CD + IaC (DEPLOY-02, DEPLOY-03, DEPLOY-04)

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `.github/workflows/ci.yml` (replaces `lint.yml`) | config | batch | `.github/workflows/lint.yml:1-27` (ban greps verbatim) + RESEARCH :1160-1242 | role-match |
| `.github/workflows/cd.yml` | config | batch | RESEARCH :1244-1312 | **no in-repo analog** |
| `.github/workflows/lint.yml` (deleted) | — | — | — | — |
| `terraform/{versions,variables,main,outputs}.tf` | config (IaC) | — | `SCRATCH/tf/*.tf`, RESEARCH §Pattern 8 | exact (`validate` exit 0) |
| `terraform/modules/{network,memorystore,kafka_vm,timescale_vm,cloud_run_api}/main.tf` | config (IaC) | — | `SCRATCH/tf/modules/*/main.tf` | exact |

### Tests (D-127)

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `tests/unit/test_dashboard_drift.py` | test | transform | `tests/unit/test_metrics_registry.py:1-30` + `tests/unit/test_no_inline_sleep.py:40-46` (non-vacuity) | role-match |
| `tests/unit/test_prometheus_config.py` | test | file-I/O | `tests/unit/test_compose_images_are_pinned.py:1-26` | exact |
| `tests/unit/test_compose_profiles.py` | test | file-I/O | `tests/unit/test_compose_images_are_pinned.py:1-26` | exact |
| `tests/unit/test_dockerfiles_hardened.py` | test | file-I/O | `tests/unit/test_no_inline_sleep.py:18-59` (grep gate) | exact |
| `tests/unit/test_ci_workflow_gates.py`, `test_cd_workflow.py`, `test_terraform_pending_human_banner.py`, `test_readme_status_guard.py` | test | file-I/O | `tests/unit/test_no_inline_sleep.py:18-59` | exact |
| `tests/unit/test_post_deploy_check.py`, `test_uptime_report.py`, `test_status_report.py` | test | transform | `tests/unit/test_metrics_registry.py` (pure-function tier) | role-match |
| `tests/unit/test_init_sentry_noop.py`, `test_sentry_structlog_bridge.py` | test | event-driven | `SCRATCH/sentry/noop_test.py`, `SCRATCH/sentry/structlog_sentry_test.py`; repo style from `tests/unit/test_telemetry_redaction.py` | mechanics + style |
| `tests/integration/test_monitoring_stack.py`, `test_post_deploy_check_lag.py`, `test_uptime_report_prometheus.py` | test | request-response | `tests/integration/test_topics_created.py`, `tests/integration/conftest.py` | role-match |
| `tests/e2e/{__init__,conftest,test_smoke}.py` | test | request-response | `SCRATCH/e2e/test_smoke3.py` + RESEARCH §Pattern 6 (:607-653) | mechanics (fixture scoping is load-bearing) |

### Docs + hygiene (DEPLOY-07, D-126)

| File | Role | Data Flow | Closest Analog | Match |
|---|---|---|---|---|
| `README.md` (rewrite) | doc | — | `README.md:1-427` (its own headings + voice) | exact |
| `CONTRIBUTING.md` (modified) | doc | — | `CONTRIBUTING.md:1-21` | exact |
| `docs/HUMAN-ACTIONS.md` (supersedes `docs/PHASE-01-HUMAN-ACTIONS.md`) | doc | — | `docs/PHASE-01-HUMAN-ACTIONS.md:1-27` | exact |
| `docs/runbooks/uptime.md` | doc | — | `docs/runbooks/perf02-24h-log.md:1-16` (STATUS banner) | exact |
| `docs/deploy/gcp.md` | doc | — | `docs/runbooks/twilio-10dlc-setup.md:1-19` (owner/TL;DR runbook shape) | role-match |
| `docs/architecture.mmd` / `.svg` | doc | — | `SCRATCH/mmd/architecture.mmd` | mechanics |
| `docs/status.json` | data (generated) | file-I/O | none | **no analog** |
| `Makefile` (modified) | config | — | `Makefile:1-73` | exact |
| `.env.example` (modified) | config | — | `.env.example:1-59` | exact |
| `pyproject.toml` (modified) | config | — | `pyproject.toml:45-52` | exact |

---

## Pattern Assignments

### `ops/docker/*.Dockerfile` (config/build, batch)

**Analog:** `SCRATCH/build/ops/docker/state_machine.Dockerfile` (built + run on this machine); transcript at `RESEARCH:278-327` (plain) and `:329-397` (Playwright).

Copy verbatim, changing only `ENTRYPOINT`, `METRICS_PORT`, `EXPOSE`:

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project     # <- cacheable dependency layer
COPY shared/ /app/shared/
COPY services/ /app/services/
COPY scripts/ /app/scripts/
COPY migrations/ /app/migrations/
COPY alembic.ini pyproject.toml uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime
RUN groupadd --system --gid 1001 mise \
 && useradd  --system --uid 1001 --gid mise --create-home mise
WORKDIR /app
COPY --from=builder --chown=mise:mise /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 METRICS_PORT=9102
USER mise
EXPOSE 9102
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('METRICS_PORT','9102')+'/metrics', timeout=2).status==200 else 1)"
ENTRYPOINT ["python", "-m", "services.state_machine"]
```

Non-negotiable deltas the analog encodes (each has a verified failure behind it):
- `COPY --from=ghcr.io/astral-sh/uv:0.11.7` — **not** `uv:0.11.7-python3.12-bookworm-slim` (404, RESEARCH:104).
- `HEALTHCHECK` uses `python -c urllib.request`; `python:3.12-slim` has no `curl`/`wget` (RESEARCH:325).
- Poller image: base `mcr.microsoft.com/playwright/python:v1.58.0-noble`, `UV_PYTHON=/usr/bin/python3.12`, `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`, `chown -R pwuser:pwuser /app`, `USER pwuser`, **no `--no-sandbox`** (RESEARCH:385).
- Web image: three-`COPY` standalone dance + `HOSTNAME=0.0.0.0` (RESEARCH:437-440).

**Repo-style comment convention to carry over** (from `ops/docker-compose.yml:5-7` and `shared/metrics.py:9-40`): every pin and every non-obvious line gets a comment naming the failure it prevents. This repo does not ship bare config.

---

### `ops/docker-compose.yml` (config) — extend, do not rewrite

**Analog:** itself. Existing service-block shape at `ops/docker-compose.yml:38-52` (redis) — key order `image, container_name, ports, environment, volumes, healthcheck, networks`, and a comment above any pin that has history.

**Existing constraint the file already enforces** (`tests/unit/test_compose_images_are_pinned.py:13-26`):

```python
IMAGE_LINE = re.compile(r"^\s*image:\s*(\S+)\s*$", re.MULTILINE)
...
assert ":" in image, f"{image} has no tag at all"
assert not image.endswith(":latest"), f"{image} is not reproducible"
```

⇒ every new service must declare an explicit `image:` tag. Use `image:` **and** `build:` together so the test sees a tag and CD-built images can be pulled (RESEARCH:1047-1075):

```yaml
  state_machine:
    image: ghcr.io/${GHCR_OWNER:-local}/mise-state_machine:${MISE_TAG:-dev}
    build: {context: .., dockerfile: ops/docker/state_machine.Dockerfile}
    profiles: [prod]
    env_file: [../.env]
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      REDIS_URL: redis://redis:6379/0
      METRICS_PORT: "9102"
      ENV: prod
    depends_on:
      kafka:    {condition: service_healthy}
      migrate:  {condition: service_completed_successfully}
      topics:   {condition: service_completed_successfully}
    restart: unless-stopped
```

**Kafka image swap (D-119a).** The block being replaced is `ops/docker-compose.yml:4-36`. Replacement env block verified booting to healthy at `RESEARCH:1077-1108`. Four coupled edits, all in the blast radius the research measured:

| Change | Current | New |
|---|---|---|
| image | `bitnamilegacy/kafka:3.8` (`:8`) | `apache/kafka:3.8.1` |
| env prefix | `KAFKA_CFG_*` + `KAFKA_KRAFT_CLUSTER_ID` (`:14-27`) | `KAFKA_*` + `CLUSTER_ID` |
| volume | `kafka-data:/bitnami/kafka` (`:29`) | `kafka-data:/var/lib/kafka/data` |
| healthcheck | `kafka-topics.sh …` (`:31`) | `/opt/kafka/bin/kafka-topics.sh …` (scripts are **not** on PATH) |

Also update `Makefile:51` (`smoke` target's `kafka-console-consumer.sh` → absolute path), `README.md:306`, and add the `docker compose down -v` note to `CONTRIBUTING.md` (the two log-dir layouts are not interchangeable).

**Monitoring profile:** copy `RESEARCH:446-489` verbatim (prometheus + grafana blocks, both healthchecked). Bind Grafana as `127.0.0.1:3001:3000` — anonymous `GET /api/datasources` leaks `http://prometheus:9090` (RESEARCH Pitfall 9).

**Profile semantics to rely on** (measured, RESEARCH:593-606): profile-less services always start, so `kafka`/`redis`/`postgres` keep no profile; only the five app services + monitoring get one.

---

### `shared/metrics.py` (model/registry) — append only

**Analog:** the file itself. It already defines `poll_total`, `poll_latency_seconds`, `scrape_ban_total` at module scope with the mandated header (`shared/metrics.py:1-40`: "**Every metric is defined ONCE, at module scope**"). Phase 7 appends `events_emitted`, `notifications_total`, `notification_latency_seconds`, `sse_connections_active` in the same shape:

```python
# -- Event emission (D-122) --
events_emitted = Counter(
    "events_emitted", "Confirmed availability events emitted.", ["source"],
)  # exposes events_emitted_total
sse_connections_active = Gauge(   # GAUGE, not Counter: a Counter would expose
    "sse_connections_active",     # sse_connections_active_total and every panel would be empty
    "Open SSE connections.",
)
```

Two traps already documented in the file's own docstring (`:31-38`) and re-verified in RESEARCH Pitfall 3: `Counter("poll_total")` emits `poll_total` + `poll_created` (the `_total` is stripped, not appended), and `sse_connections_active` must be a `Gauge`. The drift guard must normalise `_total|_created|_bucket|_sum|_count` before comparing.

---

### `shared/observability.py` (utility, event-driven)

**Analog for structure:** `shared/telemetry.py:153-183` — a module-level processor function `(logger, method, event_dict) -> event_dict` with a docstring that explains the failure it prevents, plus frozenset constants at module scope.
**Analog for behaviour:** `SCRATCH/sentry/structlog_sentry_fix.py`, transcript `RESEARCH:790-827` (init) and `:955-1000` (processor).

```python
def init_sentry(dsn: str | None = None, *, env: str | None = None) -> bool:
    dsn = dsn if dsn is not None else os.getenv("SENTRY_DSN", "")
    if not dsn:
        return False                      # verified: zero threads, zero network
    sentry_sdk.init(
        dsn=dsn,
        environment=env or os.getenv("ENV", "dev"),
        release=os.getenv("GIT_SHA", "mise@0.1.0"),
        send_default_pii=False,
        traces_sample_rate=0.0,
        shutdown_timeout=2.0,             # bounded: SIGTERM must not hang on a flush
        integrations=[LoggingIntegration(level=logging.INFO, event_level=None)],
        before_send=_scrub,
    )
    return True
```

`event_level=None` is load-bearing: with the default the whole rendered JSON line (unique ISO timestamp included) becomes the Sentry issue title, so every error is its own issue (RESEARCH Pitfall 1, reproduced).

**Wiring into `shared/telemetry.py`.** The processor chain is `shared/telemetry.py:196-204`; insert **immediately before** `structlog.processors.format_exc_info` (currently `:201`) — that processor replaces `exc_info` with a rendered string, after which `log.exception()` reaches Sentry with no exception attached (RESEARCH Pitfall 2, reproduced: `exception?: False`):

```python
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        sentry_processor,                       # <- NEW, MUST precede format_exc_info
        structlog.processors.format_exc_info,
        _redact_secrets,
    ]
```

`_scrub` reuses the existing key-name policy in `shared/telemetry.py:100-121` (`_SECRET_KEYS`, `_SECRET_KEYS_CI` already contain `cookie`/`authorization`) and must additionally drop `extra["sys.argv"]`, which the SDK adds automatically and which carries CLI arguments for the `scripts/` entry points.

---

### `services/*/main.py` (service entrypoint) — add `init_sentry` + metrics server

**Analog:** `services/state_machine/main.py:81-145`. `run()` calls `configure_logging()` first (`:82`), then acquires every resource inside a single `AsyncExitStack` with `stack.push_async_callback(...)` per resource, LIFO teardown — the file's own comment at `:99-104` explains why a late `try/finally` was wrong. Follow it exactly:

```python
async def run() -> None:
    configure_logging()
    init_sentry()                     # no-op when SENTRY_DSN is unset
    ...
    async with AsyncExitStack() as stack:
        server, thread = start_http_server(int(os.getenv("METRICS_PORT", "9102")), addr="0.0.0.0")
        stack.callback(lambda: (server.shutdown(), thread.join()))
        stack.push_async_callback(dispose_engine)
        ...
```

`start_http_server` returns `(WSGIServer, Thread)` with `daemon=True`; verified not to block the loop (50/50 ticks during 20 concurrent scrapes) and `server.shutdown() + thread.join()` is clean (RESEARCH:1127+). The daemon thread keeps all three CI ban-greps green — it introduces no `time.sleep(`, no `requests`, no sync `redis`.

---

### `scripts/post_deploy_check.py` (utility, request-response)

**Analog (style, exit codes, structure):** `scripts/check_poll_success.py:1-132`.

Copy the docstring shape (`:2-13`) — purpose, `Usage:` + `make` target, then an explicit exit-code table:

```python
"""
DEPLOY-04: post-deploy health gate. Consumer lag -> 0 within 2 min; successful polls within 3 min.

Usage: uv run python scripts/post_deploy_check.py --mode compose

Exit codes:
  0 — both gates passed
  1 — a gate failed
  2 — insufficient data (no committed offsets / empty poll_log window)
"""
```

Copy the entrypoint split verbatim (`scripts/check_poll_success.py:47,126-132`): an `async def check() -> int` doing the work, and

```python
def main() -> None:
    exit_code = asyncio.run(check())
    sys.exit(exit_code)
```

Copy the SQL/threshold-constant idiom (`:29-33`) — named module constants, not literals inline.

**Lag mechanics (D-120a, verified against a live broker with real lag 15):** derive partitions from the committed-offsets map; never pass `partitions=`, never call `consumer.partitions_for_topic()` on an unsubscribed consumer — both silently report 0 (RESEARCH:654-700).

```python
committed = await admin.list_consumer_group_offsets(g)   # NO partitions= argument
if not committed:
    out[g] = -1            # "never committed" is NOT lag 0
    continue
tps = list(committed)
ends = await consumer.end_offsets(tps)
out[g] = sum(max(0, ends[tp] - max(committed[tp].offset, 0)) for tp in tps)
```

Unit test the decision logic against a fake admin returning `{'state-machine': 15, 'notifier': -1}`.

`scripts/uptime_report.py` uses the same skeleton with the PERF-04 threshold (`>= 0.995`) and `GET {PROM}/api/v1/query?query=avg_over_time(up{...}[30d])` (RESEARCH §Pattern 12); exit 2 when the series has fewer samples than the window demands — note Prometheus is configured `--storage.tsdb.retention.time=15d`, so either raise it to `35d` or make the window a flag.

`scripts/status_report.py` follows `scripts/replay_raw.py:425-483` instead: `build_parser() -> argparse.ArgumentParser` + `def main(argv: Sequence[str] | None = None) -> int`.

---

### `tests/unit/test_*` grep gates (test, file-I/O)

**Analog:** `tests/unit/test_no_inline_sleep.py:18-59` — the canonical repo grep gate. Three features to copy for every new gate (`test_dockerfiles_hardened`, `test_ci_workflow_gates`, `test_cd_workflow`, `test_terraform_pending_human_banner`, `test_readme_status_guard`):

1. Path resolution from the test file: `REPO_ROOT = Path(__file__).resolve().parents[2]` (`:18`).
2. **A non-vacuity test** — the single most important convention here (`:40-46`):
   ```python
   def test_scanned_file_set_is_not_empty():
       """A glob that silently matched nothing would make both assertions below vacuous."""
       assert len(SCANNED_FILES) >= 8
       names = {path.name for path in SCANNED_FILES}
       assert {"consumer.py", "main.py", "engine.py", "store.py"} <= names
   ```
   Every Phase-7 gate must assert its scan set is non-empty and contains named members (`{"poller","state_machine","notifier","api","web"}` for the Dockerfile gate).
3. Comment stripping so an explanatory comment can neither satisfy nor break the gate (`:26,31-37`).

`tests/unit/test_compose_images_are_pinned.py:1-26` is the analog for the simpler regex-over-one-file gates (`test_prometheus_config.py`, `test_compose_profiles.py`). Note its docstring names the incident that caused it — keep that habit.

For `test_dashboard_drift.py`, combine the grep gate with `tests/unit/test_metrics_registry.py:19-30` (imports `shared.metrics`, reads the real registry). Assert the five panel titles from `SCRATCH/obs/grafana/dashboards/mise.json` (`poll_success_rate`, `poll_latency_p95`, `kafka_consumer_lag`, `events_per_minute`, `notification_delivery_rate`) and that every metric name in every `targets[].expr` — after stripping `_total|_created|_bucket|_sum|_count` — is either declared in `shared/metrics.py` or on an explicit exporter allowlist (`kafka_consumergroup_lag`, `up`, `http_request*`).

---

### `tests/e2e/test_smoke.py` (test, request-response)

**Analog:** `SCRATCH/e2e/test_smoke3.py`, transcript `RESEARCH:607-653`. The fixture scoping is not cosmetic — the obvious shape **hangs** (killed at >420 s):

```
scope="module" plain @pytest.fixture async generator, asyncio_mode=auto  -> HANGS
@pytest_asyncio.fixture(scope="module", loop_scope="module")
  + pytestmark = pytest.mark.asyncio(loop_scope="module")                -> 2 passed in 0.71 s
```

```python
pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def browser():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--disable-dev-shm-usage"])
        yield b
        await b.close()
```

Requires the `e2e` marker registered in `pyproject.toml:49-52` (only `integration` is declared today) — otherwise `-W error::RuntimeWarning` in `make test` is unforgiving. Do **not** add `pytest-playwright`: its fixtures are sync and this codebase is async-only (CLAUDE.md).

---

### `.github/workflows/ci.yml` (config, batch)

**Analog:** `.github/workflows/lint.yml:1-27` for the gates, `RESEARCH:1160-1242` for the job graph.

**Copy these three steps character-for-character** (`lint.yml:19-27`) — a `test_ci_workflow_gates.py` grep gate will assert they survived:

```yaml
      - name: ban_requests_import
        run: |
          ! grep -rn "^import requests\|^from requests " services/ shared/
      - name: ban_time_sleep_in_async
        run: |
          ! grep -rn "time\.sleep(" services/ shared/
      - name: ban_sync_redis_import
        run: |
          ! grep -rEn "^import redis$|^from redis import " services/ shared/
```

Deltas from `lint.yml`: mypy target widens to `shared/ services/ scripts/` (matching `Makefile:41`); `actions/checkout@v4` → `@v7` and `astral-sh/setup-uv@v3` → `@v10` (both several majors stale).

**Every shell step that pipes compose output needs `set -euo pipefail`** — measured: `docker compose up -d --wait 2>&1 | tail -25; echo $?` printed `EXIT=0` while the real exit was 1 (RESEARCH:604, D-120a).

`cd.yml` has no in-repo analog; copy `RESEARCH:1244-1312` including `permissions: packages: write`, `docker/metadata-action@v6` with `type=sha`, `cache-{from,to}: type=gha,scope=${{ matrix.service }}`, and the step-level (never job-level) `if: ${{ secrets.GCP_PROJECT_ID != '' }}` guard.

---

### `Makefile` (config)

**Analog:** `Makefile:1-73`. Every target carries a `## description` consumed by the `help` target (`:70-72`), and the target name is added to the `.PHONY` line (`:3`). Targets that encode a hard-won decision carry a multi-line comment above the recipe (`test:`, `:29-36` — nine lines explaining `-W error::RuntimeWarning`). New targets `up-prod`, `up-monitoring`, `images`, `smoke`, `docs`, `status` follow that form; `smoke:` replaces the existing `sleep 30` recipe (`:50-52`) with `up -d --wait`.

---

### Docs

**`docs/runbooks/uptime.md`** — analog `docs/runbooks/perf02-24h-log.md:1-16`:

```markdown
# PERF-02 24-Hour Observation Log

**Purpose:** ...

**Status:** BLOCKED ON HUMAN ACTION — see [Prerequisites](#prerequisites) below.
```

Use `**Status:** pending-human` in the same position, then a Prerequisites section where "Each item is a hard gate." `docs/deploy/gcp.md` follows `docs/runbooks/twilio-10dlc-setup.md:1-19` instead (Why this matters / Owner / TL;DR blockquote / numbered steps).

**`docs/HUMAN-ACTIONS.md`** — analog `docs/PHASE-01-HUMAN-ACTIONS.md:1-27`: plain-English framing, "The big picture (30 seconds)" numbered list, ordered by wait time. Consolidates every phase's gates; carries no personal data (D-126).

**`README.md`** — analog is its own heading spine: `## Status` (`:16`), `## Architecture` (`:30`), `## Key design decisions (as implemented)` (`:72`), `## Detailed status` (`:234`) with the four honest subsections `### Implemented and exercised by tests` / `### Scaffolded but incomplete` / `### Planned only (no code in tree)` / `### Known rough edges` (`:238-298`), `## Legal & Ethical Scraping` (`:323`), `## Why Kafka for ~400 Events/Day?` (`:349`), `## Operations Runbook` (`:377`). Keep this spine and this voice; regenerate the counts in `### Test coverage state` (`:283`) from `docs/status.json`. Line `:306` currently says the stack uses `bitnami/kafka` and must change with the image swap.

---

## Shared Patterns

### 1. Env-driven, no-op-when-unset integration
**Source:** `shared/telemetry.py:185-192` (`configure_logging` reads `ENV`/`LOG_LEVEL` with defaults, idempotent via a `_CONFIGURED` global).
**Apply to:** `shared/observability.py::init_sentry`, `scripts/uptime_report.py` (Better Uptime arm), `cd.yml deploy-prod`, all `terraform/` stubs.
The unit test is always "assert the unset path is inert": `assert sentry_sdk.get_client().is_active() is False` after `init_sentry(None)`.

### 2. Fail-closed allowlist guards at startup
**Source:** `services/state_machine/main.py:85-93`:
```python
    if crash_after() is not None and not crash_hook_allowed():
        raise RuntimeError(
            f"MISE_CRASH_AFTER is set but ENV={os.getenv('ENV')!r} is not one of "
            f"{sorted(CRASH_HOOK_ENVS)}. ..."
        )
```
**Apply to:** any new env-gated behaviour in the prod profile. The error message names the variable, the observed value, the allowed set, and what to do.

### 3. Exit-code contract for CLI gates: 0 pass / 1 fail / 2 insufficient data
**Source:** `scripts/check_poll_success.py:9-12, 74, 108, 117, 123`.
**Apply to:** `post_deploy_check.py`, `uptime_report.py`, `status_report.py`. "Insufficient data" is never conflated with "pass" — that distinction is the whole reason the third code exists, and it maps directly onto the lag `-1` sentinel.

### 4. Grep-gate unit tests with a non-vacuity assertion
**Source:** `tests/unit/test_no_inline_sleep.py:40-46`; simpler variant `tests/unit/test_compose_images_are_pinned.py:16-21`.
**Apply to:** all six new static gates. See §`tests/unit/test_*` above.

### 5. Comment-the-incident config
**Source:** `ops/docker-compose.yml:5-7` and `:74-75`; `shared/metrics.py:9-40`; `Makefile:29-36`.
Every pin, every non-obvious flag, and every default gets a comment naming the failure it prevents and the decision id. **Apply to:** all `ops/**` files, both workflows, all Dockerfiles, `terraform/**`.

### 6. `STATUS: pending-human` banner
**Source:** `docs/runbooks/perf02-24h-log.md:6-7`.
**Apply to:** `docs/deploy/gcp.md`, `docs/runbooks/uptime.md`, every `terraform/**/*.tf` (grep-gated by `test_terraform_pending_human_banner.py`), and the README Status section.

### 7. Secret redaction reuse
**Source:** `shared/telemetry.py:110-121` (`_SECRET_KEYS_CI` already contains `cookie`, `set-cookie`, `authorization`, `x-resy-auth-token`) and `:128-150` (`_mask_proxy_credentials`, fails closed).
**Apply to:** Sentry `before_send`. Do not write a second key list — import this one, and add only `sys.argv`.

---

## No Analog Found

Planner should use RESEARCH transcripts / scratch files as the source of truth for these.

| File | Role | Data Flow | Reason | Use instead |
|---|---|---|---|---|
| `.github/workflows/cd.yml` | config | batch | Repo has never pushed an image | RESEARCH:1244-1312 |
| `terraform/**` | config (IaC) | — | No HCL in the repo | `SCRATCH/tf/**`, RESEARCH §Pattern 8 |
| `ops/prometheus/**`, `ops/grafana/**` | config | pub-sub | No monitoring config exists | `SCRATCH/obs/**` (verified live) |
| `ops/docker/*.Dockerfile`, `.dockerignore` | config (build) | batch | Repo has never built an image | `SCRATCH/build/ops/docker/**`, RESEARCH §Patterns 1-3 |
| `tests/e2e/*` | test | request-response | `tests/e2e/` is an empty Phase-1 scaffold dir (absent on disk today) | `SCRATCH/e2e/test_smoke3.py`, RESEARCH §Pattern 6 |
| `docs/status.json`, `scripts/status_report.py` output | data | file-I/O | No generated-doc precedent | D-125; regenerate-and-diff test |
| `docs/architecture.mmd` / `.svg`, `scripts/render_diagram.py` | doc / utility | file-I/O | No diagram tooling | `SCRATCH/mmd/*`, RESEARCH §Pattern 11 |
| `web/src/app/healthz/route.ts` | route | request-response | `web/` does not exist yet (Phase 6) | RESEARCH:440 — `export const dynamic = "force-dynamic"`, returns `ok` |
| `services/notifier/main.py`, `services/api/main.py` | service entrypoint | streaming / request-response | **Not on disk** — Phase 4 (`04-CONTEXT.md`) and Phase 5 (`05-CONTEXT.md`) artifacts | Pattern from `services/state_machine/main.py:81-145`; halt per **A1** if absent at Wave 0 |
| `web/**` (Dockerfile context, `npm test`, `next.config` standalone) | component | request-response | **Not on disk** — Phase 6 (`06-CONTEXT.md` D-109/D-110/D-111) | Needs `output: 'standalone'` (Phase 6) + build-time `NEXT_PUBLIC_*` args (D-110) |
| `/api/metrics` route on the API | route | request-response | `services/api/` absent — Phase 5 D-101/D-104 pin the public route list | RESEARCH Pitfall 4 (`Instrumentator(...).expose(app, endpoint="/api/metrics", include_in_schema=False)`); coordinate with `tests/unit/test_openapi_snapshot.py` (Phase 5 D-104) |

---

## Metadata

**Analog search scope:** `ops/`, `scripts/`, `shared/`, `services/`, `tests/unit/`, `tests/integration/`, `docs/`, `.github/workflows/`, repo-root config; plus `SCRATCH/research-07/{build,obs,profiles,tf,sentry,e2e,mmd,web}`.
**Files scanned:** 38 read in full or in targeted ranges; 5 analogs selected as primary (`scripts/check_poll_success.py`, `tests/unit/test_no_inline_sleep.py`, `ops/docker-compose.yml`, `services/state_machine/main.py`, `shared/telemetry.py`).
**Pattern extraction date:** 2026-09-05
