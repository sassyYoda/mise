---
phase: 07-deploy-observability-portfolio-polish
plan: 04
type: execute
wave: 3
depends_on: ["07-02", "07-03"]
autonomous: true
requirements: [DEPLOY-05]
files_modified:
  - ops/docker-compose.yml
  - ops/prometheus/prometheus.yml
  - ops/prometheus/rules/mise.rules.yml
  - ops/grafana/provisioning/datasources/prometheus.yml
  - ops/grafana/provisioning/dashboards/mise.yml
  - ops/grafana/dashboards/mise.json
  - Makefile
  - tests/unit/test_prometheus_config.py
  - tests/unit/test_promtool_gates.py
  - tests/unit/test_dashboard_drift.py
  - tests/integration/test_monitoring_stack.py

estimate:
  tokens: 76000
  raw_tokens: 76000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "D-122: `ops/prometheus/prometheus.yml` declares one scrape job per running component — `prometheus`, `poller:9101`, `state_machine:9102`, `notifier:9103`, `api:8000` at metrics path `/api/metrics`, `kafka-exporter:9308`, `redis-exporter:9121` — and `/api/v1/targets` reports `health: up` for every one against the live stack."
    - "D-122: Kafka and Redis metrics come from `danielqsj/kafka-exporter:v1.9.0` and `oliver006/redis_exporter:v1.90.0`, never from hand-rolled application code; `sum by (consumergroup) (kafka_consumergroup_lag)` answers with a real number (research measured it agreeing exactly with `kafka-consumer-groups.sh`)."
    - "D-123: `docker compose --profile monitoring up -d` serves a public read-only dashboard with no login: anonymous `GET /d/mise` returns 200, anonymous `GET /api/dashboards/uid/mise` returns 200 with `meta.provisioned: true`, and the five DEPLOY-05 panels are titled exactly `poll_success_rate`, `poll_latency_p95`, `kafka_consumer_lag`, `events_per_minute`, `notification_delivery_rate`."
    - "D-122a: `promtool check config` and `promtool check rules` both exit 0 offline against `ops/prometheus/**` — the only way to get a real PromQL parser to validate the five derived expressions without a running server."
    - "D-123: the drift guard imports `shared.metrics` and proves that every metric identifier appearing in the dashboard JSON and in the recording rules is either declared there, defined as a recording rule, or on an explicit exporter allowlist — a metric rename fails a unit test instead of silently emptying a panel."
    - "DEPLOY-05 probe (empty — *what is the result for empty, single-element, or null input?*): every ratio expression divides by `clamp_min(sum(rate(...)), 1e-9)`, so a window with zero polls or zero notifications renders 0 rather than `NaN`. A healthy idle system must not look broken, and a gap in a portfolio dashboard reads as an outage."
    - "DEPLOY-05 probe (adjacency — *when two things are exactly equal or just touch, do they merge, collide, or separate?*): the drift guard normalises the `_total`, `_created`, `_bucket`, `_sum` and `_count` suffixes before comparing, because `Counter(\"poll_total\")` emits `poll_total` **and** `poll_created` (the suffix is stripped, not appended). `sse_connections_active` and `sse_connections_active_total` are treated as distinct and only the former may appear — conflating them is exactly the failure that empties a panel."
    - "DEPLOY-05 probe (ordering — *when elements compare equal, is output order specified and stable?*): panel identity is carried by explicit `id` and `gridPos` fields so the rendered layout is deterministic across reloads; the drift guard compares panel titles as a set, so a layout change cannot fail the test and a title change cannot pass it. Scrape-job order in `prometheus.yml` is irrelevant to target equality and the config test compares sets."
    - "Pitfall 9: the Grafana port is published on `127.0.0.1` only. Anonymous `GET /api/datasources` returns the internal `http://prometheus:9090` URL, which is internal-topology disclosure the moment that port is reachable from outside the host; public hosting is Grafana Cloud, pending-human."
    - "D-127: the unit tier covers the dashboard JSON drift guard and the Prometheus config parse; the integration tier covers Prometheus targets reporting up and the Grafana dashboard JSON API answering an anonymous client against the live compose stack."
  artifacts:
    - ops/prometheus/prometheus.yml
    - ops/prometheus/rules/mise.rules.yml
    - ops/grafana/provisioning/datasources/prometheus.yml
    - ops/grafana/provisioning/dashboards/mise.yml
    - ops/grafana/dashboards/mise.json
    - tests/unit/test_dashboard_drift.py
    - tests/integration/test_monitoring_stack.py
  key_links:
    - "compose service name + `METRICS_PORT` (07-02) → `prometheus.yml` `static_configs.targets`. The config test asserts this cross-file agreement directly, because a mismatch produces a target that is simply down rather than an error."
    - "`shared/metrics.py` identifiers (07-03) → recording rules → dashboard panel expressions. Three files, one vocabulary; the drift guard is the only thing that keeps them one vocabulary."
    - "datasource `uid: mise-prom` → every panel's `datasource.uid`. A provisioned datasource whose uid changes leaves five panels pointing at nothing, with no error anywhere."
  prohibitions:
    - "Must never publish the Grafana container port on a public interface. The public read-only dashboard is a Grafana Cloud concern (pending-human); this container binds loopback."
    - "Must never hand-roll Kafka or Redis metrics in application code when an exporter exists — the broker already knows the lag, and a hand-rolled gauge is a second source of truth that will disagree."
    - "Must never write a dashboard panel against a metric name that no code emits. A green dashboard built on absent series is worse than no dashboard: it is a claim with nothing behind it."
  flagged_assumptions:
    - "Grafana's anonymous Viewer role is deliberate (D-123) and was verified to serve `/d/mise`, `/api/dashboards/uid/mise` and `/api/ds/query` to a fully unauthenticated client. It also serves `/api/datasources`. This is accepted for a loopback-bound container and must not be accepted for any publicly reachable one."
    - "Prometheus retention is set to 35d rather than the researched 15d so `scripts/uptime_report.py` (07-06) can answer a 30-day PERF-04 question at all. This is a storage-for-answerability trade at negligible cardinality; if disk pressure appears, the window becomes a CLI flag rather than a silently short answer."
---

<objective>
Stand up the monitoring half of the compose stack: a Prometheus that scrapes every component, five recording rules that survive an offline PromQL parser, and a file-provisioned Grafana serving the five DEPLOY-05 panels to an anonymous reader.

Purpose: DEPLOY-05's public read-only dashboard is called launch-blocking for portfolio credibility in the ROADMAP and in STATE.md's risk list. This plan makes it real locally and provably anonymous, and it wires a drift guard so the panels cannot quietly decay into queries against metrics nothing emits.

Output: `ops/prometheus/**`, `ops/grafana/**`, the compose `monitoring` profile, `make up-monitoring`, and three gates (config, promtool, drift) plus one integration proof.
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
@.planning/phases/07-deploy-observability-portfolio-polish/07-02-SUMMARY.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-03-SUMMARY.md
@shared/metrics.py
@ops/docker-compose.yml
</context>

<artifacts_this_phase_produces>
- **Compose services/profiles:** the `monitoring` profile — `prometheus` (v3.14.0), `grafana` (13.2.1), `kafka-exporter` (v1.9.0), `redis-exporter` (v1.90.0).
- **Ops config:** `ops/prometheus/prometheus.yml`, `ops/prometheus/rules/mise.rules.yml`, `ops/grafana/provisioning/{datasources,dashboards}/*.yml`, `ops/grafana/dashboards/mise.json`.
- **Metrics (derived):** recording rules `mise:poll_success_rate:5m`, `mise:poll_latency_p95:5m`, `mise:kafka_consumer_lag:sum`, `mise:events_per_minute:1m`, `mise:notification_delivery_rate:5m`.
- **Scripts/targets:** `make up-monitoring`.
- Images/workflows/docs: none — consumed from 07-01/07-02, referenced by 07-07 and 07-08.
</artifacts_this_phase_produces>

<tasks>

<task type="tracer">
  <name>Task 1 (tracer): a running service's metric reaches Grafana through an anonymous datasource</name>
  <files>ops/docker-compose.yml, ops/prometheus/prometheus.yml, ops/grafana/provisioning/datasources/prometheus.yml, Makefile</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 4 (lines 442-592) — the full verified monitoring stack: the prometheus and grafana compose blocks, both provisioning file shapes, and the measured anonymous-access transcript
    - `07-RESEARCH.md` §Pitfall 9 — anonymous `GET /api/datasources` leaks the internal Prometheus URL, hence the loopback bind
    - `ops/docker-compose.yml` as 07-02 left it — service names, the `default` network, and the healthcheck idiom
    - `Makefile` `up-prod` target added in 07-02
  </read_first>
  <action>
Add a `prometheus` service to `ops/docker-compose.yml` with `profiles: [monitoring]`, image
`prom/prometheus:v3.14.0`, command flags `--config.file=/etc/prometheus/prometheus.yml`,
`--storage.tsdb.retention.time=35d` (with a comment recording that 15d cannot answer the PERF-04 30-day
question in 07-06) and `--web.enable-lifecycle`; read-only bind mounts for `./prometheus/prometheus.yml`
and `./prometheus/rules`; a named `prometheus-data` volume; port `${PROMETHEUS_PORT:-9090}:9090`; and a
`wget --spider` healthcheck against `/-/healthy`.

Add a `grafana` service with `profiles: [monitoring]`, image `grafana/grafana:13.2.1`, the D-123
environment block (`GF_AUTH_ANONYMOUS_ENABLED=true`, `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer`,
`GF_AUTH_ANONYMOUS_ORG_NAME="Main Org."`, `GF_AUTH_BASIC_ENABLED=false`,
`GF_SECURITY_ALLOW_EMBEDDING=true`, analytics and update checks off, and the default home dashboard path),
read-only mounts of `./grafana/provisioning` and `./grafana/dashboards`, a healthcheck against
`/api/health`, `depends_on: {prometheus: {condition: service_healthy}}`, and the port published as
`127.0.0.1:${GRAFANA_PORT:-3001}:3000` with a comment naming Pitfall 9 as the reason for the loopback bind.

Create `ops/prometheus/prometheus.yml` with `global.scrape_interval: 15s`, `scrape_timeout: 10s`,
`external_labels: {stack: mise-compose}`, `rule_files: [/etc/prometheus/rules/*.yml]`, and — for this
tracer — two jobs only: `prometheus` against `localhost:9090` and `state_machine` against
`state_machine:9102`. Task 2 adds the rest.

Create `ops/grafana/provisioning/datasources/prometheus.yml` declaring one datasource named `Prometheus`
with `uid: mise-prom`, `type: prometheus`, `access: proxy`, `url: http://prometheus:9090`,
`isDefault: true`, `editable: false`, `jsonData.timeInterval: 15s`. The uid is a stable contract every
panel will reference; a comment says so.

Add `make up-monitoring` bringing up `--profile smoke --profile monitoring` with `-d --build --wait`,
plus its `.PHONY` entry and `## description`.
  </action>
  <acceptance_criteria>
    - `docker compose -f ops/docker-compose.yml --profile monitoring config -q` exits 0 and `--profile monitoring config --services` includes `prometheus` and `grafana`.
    - `make up-monitoring` exits 0 within its wait timeout.
    - `curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22state_machine%22%7D' | grep -q '"value"'` exits 0 and the sampled value is `1`.
    - `curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:3001/api/health` prints `200` with no credentials supplied.
    - `curl -fsS 'http://127.0.0.1:3001/api/datasources/proxy/uid/mise-prom/api/v1/query?query=up' | grep -q '"status":"success"'` exits 0 with no credentials supplied.
    - `docker compose -f ops/docker-compose.yml --profile monitoring config | grep -c '127.0.0.1:'` returns at least 1 for the grafana published port.
  </acceptance_criteria>
  <verify>
    <automated>make up-monitoring && curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22state_machine%22%7D' | grep -q '"value"' && curl -fsS 'http://127.0.0.1:3001/api/datasources/proxy/uid/mise-prom/api/v1/query?query=up' | grep -q '"status":"success"'</automated>
  </verify>
  <done>A counter incremented inside a Python process is queryable through Grafana's provisioned datasource by a client holding no credentials — the entire observability path exists end to end before any panel or exporter is added to it.</done>
</task>

<task type="auto">
  <name>Task 2: complete the scrape config, add the exporters, and gate both offline</name>
  <files>ops/prometheus/prometheus.yml, ops/prometheus/rules/mise.rules.yml, ops/docker-compose.yml, tests/unit/test_prometheus_config.py, tests/unit/test_promtool_gates.py</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 4 (lines 542-592) — the verified seven-job scrape config and the two exporter compose blocks, plus the measured `kafka_consumergroup_lag` output
    - `07-RESEARCH.md` §Pattern 9 (lines 752-789) — the verified `promtool check config` / `check rules` invocations with their positive and negative controls, and the recording-rule file validated verbatim
    - `07-RESEARCH.md` §Pattern 5 — services without a healthcheck are treated as ready by `--wait` the moment they are running (observed for both exporters)
    - `tests/unit/test_compose_images_are_pinned.py:1-26` — the single-file regex gate this file's tests should resemble
    - `tests/conftest.py:7-17` — `_docker_available()`, the repo's environment guard for Docker-dependent tests
  </read_first>
  <action>
Extend `ops/prometheus/prometheus.yml` to the full seven jobs: `prometheus`, `poller` (`poller:9101`),
`state_machine` (`state_machine:9102`), `notifier` (`notifier:9103`), `api` (`api:8000` with
`metrics_path: /api/metrics`), `kafka` (`kafka-exporter:9308`) and `redis` (`redis-exporter:9121`). Add a
comment above the `api` job recording that its metrics path differs because Phase 5 owns that route.

Add `kafka-exporter` (`danielqsj/kafka-exporter:v1.9.0`, command `--kafka.server=kafka:9092` and
`--kafka.version=3.8.1`, `depends_on: kafka service_healthy`) and `redis-exporter`
(`oliver006/redis_exporter:v1.90.0`, `REDIS_ADDR: redis://redis:6379`, `depends_on: redis
service_healthy`) to the `monitoring` profile. Give each a healthcheck against its own metrics port —
without one, `up --wait` treats a merely-running exporter as ready and the smoke job in 07-07 can race it.

Create `ops/prometheus/rules/mise.rules.yml` with one group `mise-derived` at `interval: 30s` holding the
five recording rules from §Pattern 9 verbatim: `mise:poll_success_rate:5m`, `mise:poll_latency_p95:5m`,
`mise:kafka_consumer_lag:sum`, `mise:events_per_minute:1m`, `mise:notification_delivery_rate:5m`. Every
ratio divides by `clamp_min(<denominator>, 1e-9)`; add a comment on the first one explaining that a bare
division yields `NaN` on an idle window, which renders as a gap and makes a healthy system look broken.

Create `tests/unit/test_prometheus_config.py`: parse both YAML files and the compose file, then assert
(a) the set of scrape job names equals the expected seven; (b) for every job whose target host matches a
compose service name, the target port equals that service's declared `METRICS_PORT` (or 8000 for the
api) — this is the cross-file agreement that a mismatch would otherwise turn into a silently-down target;
(c) the rule file contains exactly five `record:` entries and every one of their names starts with
`mise:`; (d) every ratio expression contains `clamp_min`. Add the non-vacuity assertion: at least seven
jobs and at least five rules parsed.

Create `tests/unit/test_promtool_gates.py`: run `promtool check config` and `promtool check rules` via
`docker run --rm --entrypoint promtool -v <ops/prometheus>:/cfg:ro prom/prometheus:v3.14.0`, asserting
exit 0 and that stdout reports 5 rules found. Guard the whole module with the repo's `_docker_available()`
environment check so it skips cleanly on a machine without Docker — an environment guard, never a
disabled test. 07-07 runs the same two commands as a mandatory CI step so the guard can never hide a
failure in CI.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_prometheus_config.py tests/unit/test_promtool_gates.py -q -W error::RuntimeWarning` exits 0.
    - `docker run --rm --entrypoint promtool -v "$PWD/ops/prometheus:/cfg:ro" prom/prometheus:v3.14.0 check config /cfg/prometheus.yml` exits 0.
    - `docker run --rm --entrypoint promtool -v "$PWD/ops/prometheus:/cfg:ro" prom/prometheus:v3.14.0 check rules /cfg/rules/mise.rules.yml` exits 0 and prints `SUCCESS: 5 rules found`.
    - After `make up-monitoring`, `curl -fsS http://127.0.0.1:9090/api/v1/targets | python3 -c "import json,sys; d=json.load(sys.stdin)['data']['activeTargets']; print(len(d), all(t['health']=='up' for t in d))"` prints a count of at least 7 and `True`.
    - `curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=kafka_consumergroup_lag' | grep -q '"resultType"'` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_prometheus_config.py tests/unit/test_promtool_gates.py -q -W error::RuntimeWarning && docker run --rm --entrypoint promtool -v "$PWD/ops/prometheus:/cfg:ro" prom/prometheus:v3.14.0 check rules /cfg/rules/mise.rules.yml</automated>
  </verify>
  <done>Every component in the stack is scraped, the five derived series are computed by Prometheus rather than by a dashboard, and both the config and the PromQL are validated by a real parser offline — before anyone opens a browser.</done>
</task>

<task type="auto">
  <name>Task 3: the provisioned dashboard, the drift guard, and the anonymous-access proof</name>
  <files>ops/grafana/provisioning/dashboards/mise.yml, ops/grafana/dashboards/mise.json, ops/docker-compose.yml, tests/unit/test_dashboard_drift.py, tests/integration/test_monitoring_stack.py</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 4 (lines 490-541) — the verified dashboard-provider file and the measured anonymous responses, including `meta.provisioned: true` and the five panel titles read back
    - `07-RESEARCH.md` §Pitfall 3 — the `prometheus_client` suffix rules the drift guard must normalise
    - `shared/metrics.py` after 07-03 — the seven declared identifiers the guard compares against
    - `tests/unit/test_metrics_registry.py:19-30` — reading the real registry by import rather than by regex
    - `tests/unit/test_no_inline_sleep.py:40-46` — the non-vacuity idiom
    - `tests/integration/test_topics_created.py` and `tests/integration/conftest.py` — the integration-tier style and skip guards
  </read_first>
  <action>
Create `ops/grafana/provisioning/dashboards/mise.yml`: one file provider named `mise`, `orgId: 1`, empty
folder, `disableDeletion: true`, `allowUiUpdates: false`, `updateIntervalSeconds: 30`, options path
`/var/lib/grafana/dashboards`.

Create `ops/grafana/dashboards/mise.json` with `uid: "mise"` (a stable URL the README links),
`schemaVersion: 39` (accepted by Grafana 13.2.1 — verified), a title, and exactly five panels titled
`poll_success_rate`, `poll_latency_p95`, `kafka_consumer_lag`, `events_per_minute` and
`notification_delivery_rate`. Each panel carries an explicit `id` and `gridPos` so the layout is
deterministic, `datasource: {type: prometheus, uid: mise-prom}`, and a single target querying the
matching recording rule (`mise:poll_success_rate:5m` and so on). Panel units should match the series:
percent-unit for the two ratios, seconds for the latency quantile, plain numbers for lag and rate.

Create `tests/unit/test_dashboard_drift.py`. Import `shared.metrics` and collect the declared metric
names from the module's public collector objects — read the collectors, not the source text, so the guard
stays correct however the file was assembled. Parse `ops/grafana/dashboards/mise.json` and
`ops/prometheus/rules/mise.rules.yml`, extract every metric identifier appearing in every panel target
expression and every rule expression, strip the `_total`/`_created`/`_bucket`/`_sum`/`_count` suffixes,
and assert each remaining identifier is either declared in `shared/metrics.py`, defined as a `record:`
name in the rules file, or a member of an explicit exporter allowlist (`kafka_consumergroup_lag`, `up`,
`http_requests`, `http_request_duration_seconds`, `http_request_duration_highr_seconds`, `redis_up`).
Assert the five panel titles as a **set** so a layout change cannot fail the test while a title change
still does. Assert `sse_connections_active` is treated as distinct from `sse_connections_active_total`
and that only the bare name may appear. Add the non-vacuity assertions: at least 5 panels and at least 8
extracted identifiers.

Create `tests/integration/test_monitoring_stack.py`, run against an already-running
`--profile smoke --profile monitoring` stack and skipped cleanly when the stack is not reachable (an
environment guard, not a disabled test). Using an `httpx.AsyncClient` that sends no credentials at all,
assert: `GET {PROM}/api/v1/targets` reports `health == "up"` for every active target; `GET
{GRAFANA}/d/mise` returns 200; `GET {GRAFANA}/api/dashboards/uid/mise` returns 200 with
`meta.provisioned` true and the five expected panel titles; `POST {GRAFANA}/api/ds/query` against the
`mise-prom` datasource returns 200; and `GET {API}/api/metrics` returns 200 containing
`sse_connections_active`.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_dashboard_drift.py -q -W error::RuntimeWarning` exits 0 with at least 5 tests collected.
    - After `make up-monitoring`: `curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:3001/d/mise` prints `200` with no credentials.
    - `curl -fsS http://127.0.0.1:3001/api/dashboards/uid/mise | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['meta']['provisioned'], sorted(p['title'] for p in d['dashboard']['panels']))"` prints `True` and the five expected titles.
    - `uv run pytest tests/integration/test_monitoring_stack.py -q -p no:cacheprovider` exits 0 against the running stack.
    - `python3 -c "import json;d=json.load(open('ops/grafana/dashboards/mise.json'));assert d['uid']=='mise';assert len(d['panels'])==5"` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_dashboard_drift.py -q -W error::RuntimeWarning && uv run pytest tests/integration/test_monitoring_stack.py -q -p no:cacheprovider</automated>
  </verify>
  <done>The five launch-blocking panels render for a reader holding no credentials, and no panel can survive a metric rename without a red unit test.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| anonymous reader → Grafana | Anonymous Viewer is deliberately enabled; every Grafana API a Viewer can reach is effectively public to anyone who can reach the port. |
| Prometheus → service `/metrics` | Prometheus pulls from every service over the compose network with no authentication. |
| exporter → broker / Redis | The exporters hold read access to broker and Redis internals. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-07-13 | Information disclosure | anonymous `GET /api/datasources` | medium | mitigate | Grafana publishes on `127.0.0.1` only; `docs/deploy/gcp.md` (07-05) states that public exposure goes through a Grafana Cloud public dashboard, never through this container; the README (07-08) links the local URL and marks the hosted link pending-human. |
| T-07-14 | Information disclosure | dashboard panels | low | accept | Panels show aggregate rates and lag with no per-restaurant or per-user labels; that is the whole point of the D-122 label sets. |
| T-07-15 | Tampering | dashboard drift | medium | mitigate | `allowUiUpdates: false` and `disableDeletion: true` make the file the source of truth; the drift guard fails a unit test when the JSON references a metric nothing emits. |
| T-07-16 | Denial of service | Prometheus TSDB growth | low | accept | 35d retention at this cardinality is a few hundred MB; the volume is named and disposable, and the trade is documented in the flagged assumptions. |
| T-07-SC | Tampering | monitoring images | high | mitigate | All four monitoring images are pinned to explicit released tags that were pulled and run during research (`prom/prometheus:v3.14.0`, `grafana/grafana:13.2.1`, `danielqsj/kafka-exporter:v1.9.0`, `oliver006/redis_exporter:v1.90.0`); `test_compose_images_are_pinned.py` enforces the pinning forever. No package-manager install occurs in this plan. Record in SUMMARY. |
</threat_model>

<verification>
1. `uv run pytest tests/unit -q -W error::RuntimeWarning` — exit 0, including the three new gates.
2. `docker run --rm --entrypoint promtool -v "$PWD/ops/prometheus:/cfg:ro" prom/prometheus:v3.14.0 check config /cfg/prometheus.yml` and the matching `check rules` — both exit 0.
3. `make up-monitoring` — exit 0; `/api/v1/targets` reports every target `up`.
4. `uv run pytest tests/integration/test_monitoring_stack.py -q -p no:cacheprovider` — exit 0.
5. `docker compose -f ops/docker-compose.yml --profile prod --profile monitoring config -q` — exit 0 (the two profiles compose cleanly).
</verification>

<success_criteria>
- Prometheus scrapes every component and reports all targets up.
- The five DEPLOY-05 panels exist, are provisioned from files, and render for an anonymous client at `/d/mise`.
- PromQL and Prometheus config are validated offline by a real parser.
- A metric rename anywhere fails a unit test rather than emptying a panel.
</success_criteria>

<output>
Create `.planning/phases/07-deploy-observability-portfolio-polish/07-04-SUMMARY.md` when done.
Record: the measured `up -d --wait` time for `--profile smoke --profile monitoring`, the target count and
health from `/api/v1/targets`, the anonymous response codes for `/d/mise` and `/api/dashboards/uid/mise`,
and the exact local dashboard URL the README (07-08) must link.
</output>
