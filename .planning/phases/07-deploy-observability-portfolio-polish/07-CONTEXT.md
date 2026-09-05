# Phase 7: Deploy, Observability & Portfolio Polish - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning
**Mode:** Autonomous smart discuss — recommended answers accepted for every grey area (no human available; defaults chosen for consistency with PROJECT.md, REQUIREMENTS.md and Phases 1–6 decisions; the orchestrator's brief for this run explicitly narrows the ROADMAP's GCP/Terraform scope — see D-119)

<domain>
## Phase Boundary

Make the whole system runnable as a production-shaped stack from this repository and observable end-to-end, without provisioning cloud infrastructure that cannot be applied from here: per-service Dockerfiles and a `docker compose --profile prod` stack (all Python services + API + Prometheus + Grafana + the existing Kafka/Redis/TimescaleDB), real Prometheus instrumentation on every service with a provisioned Grafana dashboard carrying the five DEPLOY-05 panels, Sentry + uptime-check hooks that activate from env, GitHub Actions CI (lint + mypy + unit + Docker-backed integration + `web` build/test + a Playwright smoke test against the compose stack) and a CD workflow that builds and pushes SHA-tagged images to GHCR with a documented promotion step, deploy runbooks for the GCP topology the ROADMAP describes (as documentation + a `terraform/` skeleton that is explicitly not applied), and the final README: architecture diagram, legal/ethical scraping section (already present — refreshed), "Why Kafka" (present), replay walkthrough (present — refreshed), interview talking points, the Vercel demo link, and an honest Status section that says exactly what is implemented, tested, and human-gated. Requirements: DEPLOY-01..07, PERF-04.

**Human-gated (build around, document as pending-human):** GCP project + Cloud Run/GCE/Memorystore provisioning and Terraform `apply`, the `mise.place` domain/DNS, Grafana Cloud public dashboard link, Better Uptime monitor + 99.5 % monthly measurement, Sentry project DSN, production env secrets, and the Vercel env vars pointing at a deployed API.

</domain>

<decisions>
## Implementation Decisions

### Scope decision for this run (DEPLOY-01, DEPLOY-02, DEPLOY-04)
- **D-119:** This run does not provision GCP and does not write Terraform that cannot be applied. DEPLOY-01/02 are delivered as: (a) production-grade container images for `poller`, `state_machine`, `notifier`, `api` (multi-stage `uv`-based Dockerfiles under `ops/docker/<service>.Dockerfile`, non-root user, `HEALTHCHECK`, pinned base `python:3.12-slim`, Playwright deps only in the poller image via `mcr.microsoft.com/playwright/python:v1.58.0-noble` base); (b) `ops/docker-compose.yml` gains a `prod` profile that runs those images with env from `.env` (`docker compose --profile prod up -d`), plus `prometheus` and `grafana` services in a `monitoring` profile; (c) `docs/deploy/gcp.md` describes the ROADMAP topology (Cloud Run for the API, Cloud Run Worker Pools / a GCE MIG for the always-on pollers, GCE VMs for Kafka KRaft + TimescaleDB, Memorystore Redis, Artifact Registry, Secret Manager) with the exact `gcloud` commands and a `terraform/` skeleton (`main.tf`, `variables.tf`, per-module stubs with `TODO(human)` markers) that `terraform validate` passes but that carries a `STATUS: pending-human — not applied` banner. The README states this plainly.
- **D-120:** CD (`.github/workflows/cd.yml`): on push to `main`, build all four images with `docker/build-push-action`, tag `ghcr.io/<owner>/mise-<service>:sha-<short>` and `:main`, push to GHCR using `GITHUB_TOKEN` (no external secrets required), and write an image manifest artifact. A manual `workflow_dispatch` job `deploy-prod` is documented as the promotion step and runs only when `GCP_PROJECT_ID`/`GCP_WORKLOAD_IDENTITY_PROVIDER` secrets exist (guarded by `if:`), otherwise it prints the pending-human notice. Post-deploy health checks are implemented as `scripts/post_deploy_check.py` (consumer lag → 0 within 2 min via `AIOKafkaAdminClient` offsets, successful polls within 3 min via `poll_log`) and run by both the compose smoke job and the (gated) prod job.

### CI (DEPLOY-03)
- **D-121:** `.github/workflows/ci.yml` replaces `lint.yml`: jobs `lint` (ruff, mypy `shared/ services/ scripts/`, the three ban greps), `unit` (`uv run pytest tests/unit -q`), `integration` (testcontainers on `ubuntu-latest` with Docker; `uv run playwright install --with-deps chromium`; `uv run pytest tests/integration -q -p no:cacheprovider`), `web` (`npm ci`, `npm run lint`, `npm test`, `npm run build` in `web/`), and `smoke` (`docker compose --profile prod --profile monitoring up -d --wait`, `make topics migrate seed`, run `scripts/post_deploy_check.py --mode compose`, then a Playwright smoke test `tests/e2e/test_smoke.py` that opens the web app served by `next start` inside the compose stack (a `web` service in the `prod` profile) and drives poll → state → event → dispatcher → mock provider (`NOTIFY_DRY_RUN=true`) through the UI: create a watch, inject a raw poll via `scripts/replay_raw.py --input` into Kafka, assert the feed shows the event and `notification_log` has a `sent` row). `concurrency` cancels superseded runs; caches for `uv` and `npm`.

### Observability (DEPLOY-05, DEPLOY-06, PERF-04)
- **D-122:** Prometheus: every service exposes `/metrics` on `METRICS_PORT` (Phase 3 D-69 for the poller; state machine `9102`, notifier `9103`; API via `/api/metrics`). `ops/prometheus/prometheus.yml` scrapes all four plus `kafka-exporter` (`danielqsj/kafka-exporter`) for `kafka_consumergroup_lag` and `redis-exporter`. Metric names the dashboard depends on are fixed in `shared/metrics.py`: `poll_total{source,status}`, `poll_latency_seconds{source}`, `events_emitted_total{source}`, `notifications_total{channel,status}`, `notification_latency_seconds{channel}`, `scrape_ban_total`, `sse_connections_active`. Derived panels: `poll_success_rate` = `sum(rate(poll_total{status="success"}[5m])) / sum(rate(poll_total[5m]))`, `poll_latency_p95` = `histogram_quantile(0.95, …)`, `kafka_consumer_lag` = `sum by (consumergroup) (kafka_consumergroup_lag)`, `events_per_minute` = `sum(rate(events_emitted_total[1m])) * 60`, `notification_delivery_rate` = sent+delivered / total.
- **D-123:** Grafana is provisioned from files (`ops/grafana/provisioning/{datasources,dashboards}` + `ops/grafana/dashboards/mise.json`) with anonymous **Viewer** access enabled (`GF_AUTH_ANONYMOUS_ENABLED=true`, org role Viewer) so the compose stack itself serves a public read-only dashboard at `http://localhost:3001/d/mise`; the README links that local URL and states that the hosted public link (Grafana Cloud public dashboard at `mise.place/metrics`) is pending-human. A unit test parses `mise.json` and asserts the five required panel titles and their PromQL reference only metric names that exist in `shared/metrics.py` (drift guard).
- **D-124:** Sentry: `sentry-sdk[fastapi]` added (pinned) with `shared/observability.py :: init_sentry()` called in every service `main` — a no-op when `SENTRY_DSN` is unset; structlog events at ERROR are captured; PII disabled (`send_default_pii=False`, `before_send` strips `cookie`/`authorization` via the telemetry redactor). Uptime: `docs/runbooks/uptime.md` documents the Better Uptime monitors (`https://mise.place`, `GET /readyz` every 60 s) as pending-human; `scripts/uptime_report.py` computes monthly uptime from a Better Uptime API export **or** from Prometheus `up` samples when run against the compose stack, exiting 0 iff ≥ 99.5 % (PERF-04 tooling).

### Portfolio polish (DEPLOY-07)
- **D-125:** README rewrite (keep the existing honest voice): architecture diagram (ASCII + `docs/architecture.svg` rendered from a Mermaid source `docs/architecture.mmd` via `npx @mermaid-js/mermaid-cli` in `make docs`), live-demo link (the Vercel URL captured by the orchestrator after Phase 6 — placeholder token `<VERCEL_URL>` replaced at the end of the run), public Grafana link (local compose URL + pending-human note), refreshed Legal & Ethical Scraping and Why-Kafka sections, `scripts/replay_raw.py` walkthrough with real fixture commands, an "Interview talking points" section (exactly-once vs at-least-once + deterministic ids; Redis ZSET scheduler with Lua; stream-based confirmation; Playwright pool economics; two-layer idempotency; honest tradeoffs), and a **Status** section listing per phase what is implemented, which test suites cover it (with counts from the final run), and every human-gated item with its runbook path. No claim without code behind it — a unit test greps the README for the phrase "Coming Soon" outside the legal footer and for stale counts (`27 unit`), and `docs/status.json` (machine-readable status generated by `scripts/status_report.py` from pytest collection counts + git) is the source the README table is regenerated from.
- **D-126:** Repo hygiene: `CONTRIBUTING.md` updated with the compose profiles and CI jobs; `.env.example` complete for every service; `Makefile` targets `up-prod`, `up-monitoring`, `images`, `smoke`, `docs`, `status`; `LICENSE` unchanged; `docs/PHASE-01-HUMAN-ACTIONS.md` superseded by `docs/HUMAN-ACTIONS.md` (all phases' pending-human items in one checklist, no personal data).

### Test strategy
- **D-127:** Unit: dashboard JSON drift guard, prometheus config parse, `post_deploy_check` decision logic with fake lag/poll samples, `uptime_report` math, README status guard, `init_sentry` no-op without DSN. Integration/e2e: compose `prod`+`monitoring` profiles come up healthy (`docker compose … up --wait` in CI smoke), Prometheus targets `up == 1` for all services, Grafana dashboard loads anonymously (HTTP 200 on the dashboard JSON API), the Playwright smoke test (D-121). Image builds are tested in CI only (too slow locally to gate every commit) but `make images` must succeed at least once in this run before the phase is verified.

### Amendments after research (07-RESEARCH.md — no blocking corrections; recommendations accepted 2026-09-05)
- **D-119a:** Kafka image for both dev and prod profiles moves to `apache/kafka:3.8.1` (bitnamilegacy is vendor-declared unmaintained): env `KAFKA_CFG_*` → `KAFKA_*` + `CLUSTER_ID`, scripts live under `/opt/kafka/bin` (not on PATH — healthcheck and `make smoke` use the full path), data volume `/var/lib/kafka/data`, and the runbook says `docker compose down -v` is required once when switching. uv base: `COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/` (the `-python3.12-bookworm-slim` tag is gone); Playwright poller image `mcr.microsoft.com/playwright/python:v1.58.0-noble` (system Python 3.12.3, runs as `pwuser` without `--no-sandbox`). The `web` image uses Next standalone output on `node:22-alpine`.
- **D-120a:** Consumer-lag recipe: derive partitions from the committed-offsets map (`list_consumer_group_offsets(group)` with NO `partitions=` argument; `partitions_for_topic()` returns `None` on an unsubscribed consumer) — the naive form silently reports 0. Unit-test with a fake admin returning the research's `{'state-machine': 15, 'notifier': -1}` shape. CI shell steps use `set -o pipefail` so `docker compose up --wait` failures are not swallowed by `| tail`.
- **D-121a:** The compose smoke job excludes the poller image (the smoke path injects raw polls via `replay_raw.py`, so no scraping happens) — keeps the 4.6 GB Playwright image out of the CI critical path; the poller image is built/pushed by CD only.
- **D-122a:** `promtool check rules`/`check config` run offline in a unit-tier test against `ops/prometheus/*.yml` (validated positive and negative in research). Grafana anonymous Viewer verified: `/d/mise`, `/api/dashboards/uid/mise` (`meta.provisioned: true`) and `/api/ds/query` all answer an anonymous client — the drift-guard test hits the dashboard JSON API in the compose smoke.
- **D-124a:** Sentry with structlog: add a structlog processor placed *before* `format_exc_info` that captures the exception and a stable fingerprint (event name), and configure `LoggingIntegration(event_level=None)` so the JSON line (with its unique timestamp) is not used as the issue title; a unit test asserts exactly one Sentry event with a real exception per `log.exception()` via a fake transport. `sentry-sdk` and `@mermaid-js/mermaid-cli` legitimacy: accepted (long-lived official packages; the `too-new` heuristic fired on release date only) — recorded here in lieu of a human checkpoint. Mermaid renders with `PUPPETEER_SKIP_DOWNLOAD=1` + `executablePath` pointed at the Playwright Chromium; if rendering is flaky locally, commit the `.mmd` source and render in CI only.
- **A1:** Phases 4–6 artifacts (`services/notifier`, `services/api`, `web/`, `shared/metrics.py`) are hard upstream dependencies — Wave 0 is a precondition-verification task that halts clearly if any is missing.

### Claude's Discretion
- Exact Dockerfile layering / uv cache mounts; Prometheus scrape intervals; Grafana panel layout; Mermaid diagram styling; talking-point wording.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ops/docker-compose.yml` (infra + healthchecks), `Makefile`, `.github/workflows/lint.yml` (bans + lint job to fold into `ci.yml`), `.env.example`.
- `shared/metrics.py` (Phase 3), `services/*/main.py` lifespans (add `init_sentry`, metrics servers), `scripts/check_poll_success.py` / `check_notification_latency.py` (exit-code conventions), `scripts/replay_raw.py` (smoke injection), `tests/e2e/` (empty dir from Phase 1 scaffold).
- `web/` (Phase 6) — `next build`/`next start` in a `web` Dockerfile (`node:22-alpine`, standalone output).
- README sections written in Phase 1 (legal, Kafka tradeoff, runbook) and the Phase 2/4 service READMEs.

### Established Patterns
- Env-driven, no-op-when-unset integrations; pending-human runbooks with `STATUS:` banners; grep-gate unit tests; small commits.

### Integration Points
- GHCR image names; compose service names must match Prometheus targets; Vercel URL placeholder in README replaced by the orchestrator; `docs/HUMAN-ACTIONS.md` consolidates every phase's gates.

</code_context>

<specifics>
## Specific Ideas

- The README Status table is generated, not hand-typed, so it cannot drift from the test counts.
- Keep the compose `prod` profile honest: single-broker Kafka, RF=1, documented as the MVP tradeoff.

</specifics>

<deferred>
## Deferred Ideas

- Applying Terraform to a real GCP project; Grafana Cloud sync; multi-broker Kafka; OTel tracing.

</deferred>
