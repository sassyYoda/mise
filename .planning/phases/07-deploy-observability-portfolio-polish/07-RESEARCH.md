# Phase 7: Deploy, Observability & Portfolio Polish — Research

**Researched:** 2026-09-05
**Domain:** Container packaging (uv + Playwright + Next.js standalone), Docker Compose profiles, Prometheus/Grafana provisioning, Sentry, GitHub Actions CI/CD to GHCR, Terraform skeleton, portfolio README generation
**Confidence:** HIGH — every load-bearing claim below was executed on this machine (Docker 29.4 / Compose v5.1.2, Node 22.14, uv 0.11.7, Terraform 1.13.0) and the commands + outputs are quoted. Two claims are `[ASSUMED]` and listed in the Assumptions Log.

**Scratch dir for every experiment:** `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-07/`. Nothing outside this file was written to the repo; `git status --porcelain` shows only Phase-3 executors' untracked test files.

---

<user_constraints>
## User Constraints (from 07-CONTEXT.md)

### Locked Decisions

- **D-119:** This run does not provision GCP and does not write Terraform that cannot be applied. DEPLOY-01/02 are delivered as: (a) production-grade container images for `poller`, `state_machine`, `notifier`, `api` (multi-stage `uv`-based Dockerfiles under `ops/docker/<service>.Dockerfile`, non-root user, `HEALTHCHECK`, pinned base `python:3.12-slim`, Playwright deps only in the poller image via `mcr.microsoft.com/playwright/python:v1.58.0-noble` base); (b) `ops/docker-compose.yml` gains a `prod` profile that runs those images with env from `.env` (`docker compose --profile prod up -d`), plus `prometheus` and `grafana` services in a `monitoring` profile; (c) `docs/deploy/gcp.md` describes the ROADMAP topology (Cloud Run for the API, Cloud Run Worker Pools / a GCE MIG for the always-on pollers, GCE VMs for Kafka KRaft + TimescaleDB, Memorystore Redis, Artifact Registry, Secret Manager) with the exact `gcloud` commands and a `terraform/` skeleton (`main.tf`, `variables.tf`, per-module stubs with `TODO(human)` markers) that `terraform validate` passes but that carries a `STATUS: pending-human — not applied` banner. The README states this plainly.
- **D-120:** CD (`.github/workflows/cd.yml`): on push to `main`, build all four images with `docker/build-push-action`, tag `ghcr.io/<owner>/mise-<service>:sha-<short>` and `:main`, push to GHCR using `GITHUB_TOKEN` (no external secrets required), and write an image manifest artifact. A manual `workflow_dispatch` job `deploy-prod` is documented as the promotion step and runs only when `GCP_PROJECT_ID`/`GCP_WORKLOAD_IDENTITY_PROVIDER` secrets exist (guarded by `if:`), otherwise it prints the pending-human notice. Post-deploy health checks are implemented as `scripts/post_deploy_check.py` (consumer lag → 0 within 2 min via `AIOKafkaAdminClient` offsets, successful polls within 3 min via `poll_log`) and run by both the compose smoke job and the (gated) prod job.
- **D-121:** `.github/workflows/ci.yml` replaces `lint.yml`: jobs `lint` (ruff, mypy `shared/ services/ scripts/`, the three ban greps), `unit` (`uv run pytest tests/unit -q`), `integration` (testcontainers on `ubuntu-latest` with Docker; `uv run playwright install --with-deps chromium`; `uv run pytest tests/integration -q -p no:cacheprovider`), `web` (`npm ci`, `npm run lint`, `npm test`, `npm run build` in `web/`), and `smoke` (`docker compose --profile prod --profile monitoring up -d --wait`, `make topics migrate seed`, run `scripts/post_deploy_check.py --mode compose`, then a Playwright smoke test `tests/e2e/test_smoke.py` that opens the web app served by `next start` inside the compose stack (a `web` service in the `prod` profile) and drives poll → state → event → dispatcher → mock provider (`NOTIFY_DRY_RUN=true`) through the UI: create a watch, inject a raw poll via `scripts/replay_raw.py --input` into Kafka, assert the feed shows the event and `notification_log` has a `sent` row). `concurrency` cancels superseded runs; caches for `uv` and `npm`.
- **D-122:** Prometheus: every service exposes `/metrics` on `METRICS_PORT` (Phase 3 D-69 for the poller; state machine `9102`, notifier `9103`; API via `/api/metrics`). `ops/prometheus/prometheus.yml` scrapes all four plus `kafka-exporter` (`danielqsj/kafka-exporter`) for `kafka_consumergroup_lag` and `redis-exporter`. Metric names the dashboard depends on are fixed in `shared/metrics.py`: `poll_total{source,status}`, `poll_latency_seconds{source}`, `events_emitted_total{source}`, `notifications_total{channel,status}`, `notification_latency_seconds{channel}`, `scrape_ban_total`, `sse_connections_active`. Derived panels: `poll_success_rate` = `sum(rate(poll_total{status="success"}[5m])) / sum(rate(poll_total[5m]))`, `poll_latency_p95` = `histogram_quantile(0.95, …)`, `kafka_consumer_lag` = `sum by (consumergroup) (kafka_consumergroup_lag)`, `events_per_minute` = `sum(rate(events_emitted_total[1m])) * 60`, `notification_delivery_rate` = sent+delivered / total.
- **D-123:** Grafana is provisioned from files (`ops/grafana/provisioning/{datasources,dashboards}` + `ops/grafana/dashboards/mise.json`) with anonymous **Viewer** access enabled (`GF_AUTH_ANONYMOUS_ENABLED=true`, org role Viewer) so the compose stack itself serves a public read-only dashboard at `http://localhost:3001/d/mise`; the README links that local URL and states that the hosted public link (Grafana Cloud public dashboard at `mise.place/metrics`) is pending-human. A unit test parses `mise.json` and asserts the five required panel titles and their PromQL reference only metric names that exist in `shared/metrics.py` (drift guard).
- **D-124:** Sentry: `sentry-sdk[fastapi]` added (pinned) with `shared/observability.py :: init_sentry()` called in every service `main` — a no-op when `SENTRY_DSN` is unset; structlog events at ERROR are captured; PII disabled (`send_default_pii=False`, `before_send` strips `cookie`/`authorization` via the telemetry redactor). Uptime: `docs/runbooks/uptime.md` documents the Better Uptime monitors (`https://mise.place`, `GET /readyz` every 60 s) as pending-human; `scripts/uptime_report.py` computes monthly uptime from a Better Uptime API export **or** from Prometheus `up` samples when run against the compose stack, exiting 0 iff ≥ 99.5 % (PERF-04 tooling).
- **D-125:** README rewrite (keep the existing honest voice): architecture diagram (ASCII + `docs/architecture.svg` rendered from a Mermaid source `docs/architecture.mmd` via `npx @mermaid-js/mermaid-cli` in `make docs`), live-demo link (the Vercel URL captured by the orchestrator after Phase 6 — placeholder token `<VERCEL_URL>` replaced at the end of the run), public Grafana link (local compose URL + pending-human note), refreshed Legal & Ethical Scraping and Why-Kafka sections, `scripts/replay_raw.py` walkthrough with real fixture commands, an "Interview talking points" section (exactly-once vs at-least-once + deterministic ids; Redis ZSET scheduler with Lua; stream-based confirmation; Playwright pool economics; two-layer idempotency; honest tradeoffs), and a **Status** section listing per phase what is implemented, which test suites cover it (with counts from the final run), and every human-gated item with its runbook path. No claim without code behind it — a unit test greps the README for the phrase "Coming Soon" outside the legal footer and for stale counts (`27 unit`), and `docs/status.json` (machine-readable status generated by `scripts/status_report.py` from pytest collection counts + git) is the source the README table is regenerated from.
- **D-126:** Repo hygiene: `CONTRIBUTING.md` updated with the compose profiles and CI jobs; `.env.example` complete for every service; `Makefile` targets `up-prod`, `up-monitoring`, `images`, `smoke`, `docs`, `status`; `LICENSE` unchanged; `docs/PHASE-01-HUMAN-ACTIONS.md` superseded by `docs/HUMAN-ACTIONS.md` (all phases' pending-human items in one checklist, no personal data).
- **D-127:** Unit: dashboard JSON drift guard, prometheus config parse, `post_deploy_check` decision logic with fake lag/poll samples, `uptime_report` math, README status guard, `init_sentry` no-op without DSN. Integration/e2e: compose `prod`+`monitoring` profiles come up healthy (`docker compose … up --wait` in CI smoke), Prometheus targets `up == 1` for all services, Grafana dashboard loads anonymously (HTTP 200 on the dashboard JSON API), the Playwright smoke test (D-121). Image builds are tested in CI only (too slow locally to gate every commit) but `make images` must succeed at least once in this run before the phase is verified.

### Claude's Discretion

- Exact Dockerfile layering / uv cache mounts; Prometheus scrape intervals; Grafana panel layout; Mermaid diagram styling; talking-point wording.

### Deferred Ideas (OUT OF SCOPE)

- Applying Terraform to a real GCP project; Grafana Cloud sync; multi-broker Kafka; OTel tracing.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description (verbatim, `.planning/REQUIREMENTS.md:81-94`) | Research Support |
|----|-------------|------------------|
| DEPLOY-01 | "Services deployed to GCP Cloud Run Worker Pools (polling fleet, state machine, dispatcher, notification workers) + Cloud Run (API) + Vercel (Next.js) + self-hosted Kafka on GCE + Memorystore Redis + self-hosted TimescaleDB on GCE (Cloud SQL does not support the TimescaleDB extension)" | §Standard Stack (base images), §Pattern 1 (uv multi-stage), §Pattern 2 (Playwright base), §Pattern 3 (Next.js standalone) — all four images built and run here. Cloud provisioning is D-119 pending-human → `docs/deploy/gcp.md`. |
| DEPLOY-02 | "Terraform configs for all GCP infrastructure (Cloud Run services, VPC, Memorystore, Artifact Registry, secrets, GCE Kafka + TimescaleDB VMs)" | §Pattern 8 — `terraform init -backend=false && terraform validate` **and** `terraform plan` all exit 0 with zero credentials on Terraform 1.13.0 / google 7.46.1. |
| DEPLOY-03 | "GitHub Actions CI: lint (ruff + mypy) + per-service pytest + docker-compose integration test (poll → state → event → dispatcher → mock worker) + Playwright smoke test against staging" | §GitHub Actions (pinned action versions), §Pattern 5 (compose profiles + `--wait` exit codes), §Pattern 6 (async Playwright e2e, two working fixture shapes). |
| DEPLOY-04 | "GitHub Actions CD: build-and-push on merge to main (Artifact Registry with SHA tag + deploy to Cloud Run staging); manual deploy-prod with post-deploy health checks (consumer lag → 0 in < 2min; successful polls in < 3min)" | §GitHub Actions (GHCR + `GITHUB_TOKEN`, `metadata-action` `type=sha`), §Pattern 7 (verified aiokafka lag recipe, LAG=15 matching `kafka-consumer-groups.sh`). |
| DEPLOY-05 | "Prometheus metrics exported from all services + Grafana Cloud dashboard with poll_success_rate, poll_latency_p95, kafka_consumer_lag, events_per_minute, notification_delivery_rate; **public read-only dashboard link** (launch-blocking for portfolio)" | §Pattern 4 (full stack stood up: Prometheus 3.14.0 targets `up==1`, Grafana 13.2.1 anonymous Viewer serving all five panels), §Pattern 9 (`promtool` offline gates). |
| DEPLOY-06 | "Sentry error tracking on all services; Better Uptime pinging `mise.place` and API health endpoint every 60 seconds" | §Pattern 10 + §Pitfall 1 & 2 (two reproduced Sentry/structlog defects with a verified fix). Better Uptime is pending-human. |
| DEPLOY-07 | "README includes architecture diagram, live-demo link, public Grafana link, rate-limiting & ethical-scraping section, legal analysis citing NY Restaurant Reservation Anti-Piracy Act (Feb 2025), interview-question talking points" | §Pattern 11 (mermaid-cli renders headlessly here in 1.4 s using the existing Playwright Chromium), §README guard notes. |
| PERF-04 | "System uptime ≥ 99.5% (Better Uptime, monthly)" | §Pattern 12 (`avg_over_time(up[...])` against the live Prometheus API — the compose-mode path of `scripts/uptime_report.py`). |
</phase_requirements>

---

## Summary

Every locked decision in 07-CONTEXT.md is buildable as written, and I proved the risky parts by executing them rather than reasoning about them. The four container shapes were built and run: a two-stage `uv` image for the plain Python services (661 MB, non-root, imports `services.state_machine` cleanly), a Playwright-based poller image on `mcr.microsoft.com/playwright/python:v1.58.0-noble` (4.59 GB; Chromium 145 launches as `pwuser` **without** `--no-sandbox`), and a Next.js 15 `output: 'standalone'` image on `node:22-alpine` (340 MB, ready in 31 ms). The single biggest unknown flagged in the brief — whether the Playwright base ships a Python that satisfies `requires-python >=3.12,<3.13` — resolves cleanly: it is Ubuntu 24.04.3 with system **Python 3.12.3**, so no `uv python install` gymnastics are needed. A full monitoring stack (apache/kafka 3.8.1 + redis + kafka-exporter + redis-exporter + Prometheus 3.14.0 + Grafana 13.2.1) came up healthy with `docker compose up -d --wait` in **11.5 seconds**, Prometheus reported `up == 1` on every target, `kafka_consumergroup_lag` read exactly the 15 that `kafka-consumer-groups.sh` reported, and Grafana served the five-panel provisioned dashboard to a fully anonymous client (`/d/mise` → 200, `/api/dashboards/uid/mise` → 200 with `meta.provisioned: true`, `POST /api/ds/query` → 200).

Three findings change how the plan should be written. First, **D-124's "structlog events at ERROR are captured" is technically true but produces unusable Sentry data by default**: because `shared/telemetry.py` uses `structlog.stdlib.LoggerFactory()` with a `JSONRenderer`, Sentry's `LoggingIntegration` receives the whole rendered JSON line — including a unique ISO timestamp — as the issue message, so every single error becomes its own Sentry issue; and `log.exception()` produces an event with **no exception attached at all**, because structlog's `format_exc_info` processor consumes `exc_info` into a string before stdlib logging ever sees it. Both defects were reproduced and a fix (a structlog processor placed *before* `format_exc_info`, with `LoggingIntegration(event_level=None)`) was prototyped and verified to give stable fingerprints, a real `ValueError: boom` exception object, and structured extras. Second, **the D-120 consumer-lag recipe has two silent-zero traps in aiokafka 0.13.0**: `consumer.partitions_for_topic(t)` returns `None` on an unsubscribed consumer even after a metadata fetch, and `list_consumer_group_offsets(group, partitions=[])` returns `{}` — so the obvious implementation reports lag 0 while the real lag is 15. The correct recipe (derive the partition set from the committed-offset map, never pass `partitions=`) was verified against a live broker. Third, **`bitnamilegacy/kafka:3.8` is explicitly "no longer updated"** (Docker Hub description; last image push 2025-07-18), which is a poor thing for a portfolio repo to be running; `apache/kafka:3.8.1` works, is non-root, and was verified — but switching it is a four-part change (env prefix `KAFKA_CFG_*` → `KAFKA_*` plus `CLUSTER_ID`, healthcheck must use the absolute path `/opt/kafka/bin/kafka-topics.sh` because the scripts are **not on `PATH`**, volume path `/bitnami/kafka` → `/var/lib/kafka/data`, and `make down -v` is required because the old volume is incompatible).

There are **no blocking corrections** — nothing in D-119..D-127 failed to run as written. The dominant *schedule* risk is not technical: Phase 7 wraps artifacts (`shared/metrics.py`, `services/notifier/`, `services/api/`, `web/`) that none of Phases 3–6 have produced yet (`STATE.md` says `current_phase: 3, status: executing`). Every Phase 7 plan must therefore treat those as hard upstream dependencies rather than assuming files exist.

**Primary recommendation:** Build the phase bottom-up in this order — (1) `shared/metrics.py` + `shared/observability.py` as the single source of truth for metric names and Sentry init; (2) the four Dockerfiles + the `prod`/`monitoring` compose profiles using the exact env blocks in §Code Examples; (3) `ops/prometheus/{prometheus.yml,rules/mise.rules.yml}` and `ops/grafana/**` with `promtool check config` + `promtool check rules` as the offline gates; (4) `ci.yml`/`cd.yml` with the pinned action versions in §GitHub Actions; (5) the `terraform/` skeleton (validated here); (6) the README/status generation last, once the test counts are final.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Service packaging (Python) | Build/CI (Dockerfile) | — | Runtime image contents are a build-time concern; nothing in `services/` should know it is containerised. |
| Browser runtime (Chromium) | Build/CI (poller image base) | — | Browser binaries are 900 MB of base layer; keeping them out of the other three images is the whole reason for a per-service Dockerfile. |
| Frontend serving | Frontend Server (Next.js standalone `node server.js`) | CDN/Static (Vercel, pending-human) | `output: 'standalone'` produces a self-contained Node server; Vercel is the public demo, compose is the CI smoke target. |
| Metric *production* | API/Backend (each service process) | — | `prometheus_client` registries are per-process; a sidecar cannot see them. |
| Metric *collection* | Ops (Prometheus container) | — | Pull model over the compose network by service name. |
| Kafka/Redis metrics | Ops (exporters) | — | Brokers expose JMX, not Prometheus; `kafka-exporter`/`redis-exporter` translate. Never hand-roll. |
| Dashboarding + public read access | Ops (Grafana, anonymous Viewer) | — | Auth is a Grafana concern; the app must not proxy dashboards. |
| Error capture | API/Backend (in-process Sentry SDK) | — | Needs the exception object and request scope; a log scraper cannot reconstruct either. |
| Uptime measurement | External (Better Uptime, pending-human) | Ops (Prometheus `up` fallback) | A liveness prober must be outside the failure domain it measures; the Prometheus path is the local-proof fallback only. |
| Image distribution | CI (GHCR via `GITHUB_TOKEN`) | Cloud (Artifact Registry, pending-human) | GHCR needs no external secret, which is exactly why D-120 chose it. |
| Infra declaration | IaC (`terraform/`, unapplied) | Docs (`docs/deploy/gcp.md`) | D-119 splits "describes the topology" (docs) from "declares it" (Terraform stubs). |
| Consumer-lag health gate | Ops script (`scripts/post_deploy_check.py`) | — | Reads broker state via the admin client; belongs to neither the poller nor the state machine. |

---

## Standard Stack

### Core — container images (all pulled and run on this machine, 2026-09-05)

| Image | Version | Purpose | Why standard |
|-------|---------|---------|--------------|
| `python:3.12-slim` | digest-worthy; today resolves to **Debian 13 trixie, Python 3.12.14** `[VERIFIED: docker run --rm python:3.12-slim → "Python 3.12.14" / PRETTY_NAME="Debian GNU/Linux 13 (trixie)"]` | base for `state_machine`, `notifier`, `api` | Locked by D-119. Smallest official image that still has glibc (asyncpg/psycopg/cryptography wheels are manylinux). |
| `mcr.microsoft.com/playwright/python:v1.58.0-noble` | tag **exists** `[VERIFIED: MCR /v2/playwright/python/tags/list — 973 tags, includes v1.58.0-noble, -amd64, -arm64]` | base for `poller` | Locked by D-119; matches `playwright==1.58.0` in `pyproject.toml:11`. Ships the exact browser build the pinned client expects. |
| `node:22-alpine` | resolves to **v22.23.2** `[VERIFIED: docker run --rm node:22-alpine node --version]` | base for `web` | Locked by D-119. Standalone Next output only needs a Node runtime. |
| `apache/kafka` | **3.8.1** `[VERIFIED: docker pull + full KRaft boot; tag present on Docker Hub]` | broker (recommended for BOTH profiles — see Pitfall 5) | Official ASF image, runs as `appuser` uid 1000, actively maintained. |
| `bitnamilegacy/kafka` | 3.8 — **"Legacy Bitnami images (no longer updated)"**, last image push `2025-07-18` `[VERIFIED: hub.docker.com/v2/repositories/bitnamilegacy/kafka/ description + tag last_updated]` | current dev broker (`ops/docker-compose.yml:8`) | Status quo only. Not recommended to carry into a `prod` profile. |
| `redis` | 7.2-alpine (already pinned, `ops/docker-compose.yml:34`) | state + scheduler | Unchanged. |
| `timescale/timescaledb` | 2.17.2-pg16 (already pinned, `ops/docker-compose.yml:52`) | hypertables | Unchanged. |
| `prom/prometheus` | **v3.14.0** `[VERIFIED: docker pull; /api/v1/targets returned health "up" for 3 jobs]` | scraper | Latest stable (`latest` → v3.14.0 on Docker Hub tag list). |
| `grafana/grafana` | **13.2.1** `[VERIFIED: docker pull; /api/health returned {"version":"13.2.1"}]` | dashboard | Newest semver on Docker Hub (13.2.1, 2026-09-01). |
| `danielqsj/kafka-exporter` | **v1.9.0** (published 2025-02-17; `latest` moved 2026-04-13) `[VERIFIED: docker pull + metric scrape]` | `kafka_consumergroup_lag` | The de-facto Kafka→Prometheus exporter; named in D-122. |
| `oliver006/redis_exporter` | **v1.90.0** (2026-08-27) `[VERIFIED: docker pull; Prometheus target up==1]` | Redis metrics | The de-facto Redis exporter. |
| `ghcr.io/astral-sh/uv` | **0.11.7** (matches the host uv that wrote `uv.lock`) `[VERIFIED: ghcr manifest HTTP 200 for tag 0.11.7; used successfully as a COPY --from stage]` | uv binary donor stage | Official; `COPY --from=… /uv /uvx /bin/` works against any base. |

**Do not use `0.11.7-python3.12-bookworm-slim`** — it 404s. uv dropped `bookworm` variants; 0.11.x publishes `trixie`, `alpine`, and `dhi` flavours only `[VERIFIED: paginated GHCR tag list, 7597 tags; `grep '^0\.11\.7'` shows `-python3.12-trixie-slim` but no `bookworm`]`. The `COPY --from` pattern sidesteps the whole question.

### Core — Python packages

| Package | Version | Purpose | Why standard |
|---------|---------|---------|--------------|
| `sentry-sdk[fastapi]` | **2.68.1** (uploaded 2026-08-24) `[VERIFIED: pypi.org/pypi/sentry-sdk/json → info.version]` | DEPLOY-06 | Official SDK. First release 2018-07-26, 346 releases, repo `github.com/getsentry/sentry-python`. |
| `prometheus-client` | **0.25.0 — already pinned** (`pyproject.toml:28`). Latest is 0.26.0 (2026-07-24). | metric registry | No reason to bump inside this phase; `pyproject.toml` + `uv.lock` are frozen elsewhere. |
| `prometheus-fastapi-instrumentator` | **7.1.0 — already pinned** (`pyproject.toml:29`). Latest is 8.1.0. | `/api/metrics` | 7.1.0 verified working with the `/api/metrics` endpoint below; a major bump is out of scope. |
| `aiokafka` | **0.13.0 — already pinned** (`pyproject.toml:22`) | admin/lag queries | `AIOKafkaAdminClient.list_consumer_group_offsets` present and verified. |
| `playwright` | **1.58.0 — already pinned** (`pyproject.toml:11`) | e2e smoke | Must equal the base-image tag; it does. |

### Supporting — Node / CLI

| Tool | Version | Purpose | When to use |
|------|---------|---------|-------------|
| `@mermaid-js/mermaid-cli` | **11.17.0** `[VERIFIED: npm view @mermaid-js/mermaid-cli version]` | `docs/architecture.mmd` → `docs/architecture.svg` | `make docs` only; never on the CI critical path. |
| `terraform` | **1.13.0 installed here** `[VERIFIED: terraform version]`; provider `hashicorp/google` **7.46.1** resolved from `~> 7.9` `[VERIFIED: .terraform.lock.hcl]` | `terraform validate` gate | Local + CI. Provider download is 117 MB — cache it. |
| `promtool` | ships inside `prom/prometheus:v3.14.0` | offline config + PromQL syntax gate | No separate install needed: `docker run --rm --entrypoint promtool …`. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `apache/kafka:3.8.1` | keep `bitnamilegacy/kafka:3.8` | Zero migration work, but ships an image the vendor says is no longer updated — a bad line in a portfolio README, and no security patches. |
| Playwright base image (4.59 GB) | `python:3.12-slim` + `playwright install --with-deps chromium` | ~1.5 GB image instead of 4.59 GB, but you own the apt dependency list and lose the vendor-tested browser/OS pairing. D-119 locks the MCR base; keep it. |
| `docker/build-push-action` GHA cache | `actions/cache` on `/tmp/.buildx-cache` | The old manual-cache dance is obsolete; `type=gha` is one line. |
| PromQL inline in the dashboard JSON | Prometheus **recording rules** (`ops/prometheus/rules/mise.rules.yml`) | Recording rules are syntax-checkable offline by `promtool check rules` (verified) and make panels cheap. Strongly recommended *in addition to* the D-122 panel expressions. |
| `pytest-playwright` plugin | raw `playwright.async_api` + `pytest-asyncio` | The plugin's fixtures are sync-first and the codebase is async-only (CLAUDE.md). Raw async API verified working (§Pattern 6); do not add the plugin. |

**Installation:**

```bash
# Python — one new runtime dependency (pyproject.toml [project.dependencies])
uv add "sentry-sdk[fastapi]==2.68.1"

# Node — dev-time only, never a runtime dep of web/
npx -y @mermaid-js/mermaid-cli@11.17.0 --version
```

**Version verification performed (2026-09-05):**

```
pypi sentry-sdk                     -> 2.68.1   (uploaded 2026-08-24)
pypi prometheus-client              -> 0.26.0   (repo pins 0.25.0 — keep)
pypi prometheus-fastapi-instrumentator -> 8.1.0 (repo pins 7.1.0 — keep)
pypi uv                             -> 0.12.10  (host has 0.11.7 — pin 0.11.7 everywhere)
npm  @mermaid-js/mermaid-cli        -> 11.17.0
npm  next                           -> 16.3.4 latest; 15.x line at 15.5.25 (Phase 6 D-109 says Next 15)
```

---

## Package Legitimacy Audit

Run via `gsd-tools query package-legitimacy check` on 2026-09-05.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| `sentry-sdk` | PyPI | first release **2018-07-26**, 346 releases; latest 2026-08-24 | not reported by PyPI API | `github.com/getsentry/sentry-python` | **SUS** (`too-new`, `unknown-downloads`) | **Approved with checkpoint** |
| `@mermaid-js/mermaid-cli` | npm | package created **2020-03-01**; latest 2026-09-02 | **598,298 / wk** | `github.com/mermaid-js/mermaid-cli` | **SUS** (`too-new`) | **Approved with checkpoint** |

**Packages removed due to `SLOP` verdict:** none.
**Packages flagged as suspicious `SUS`:** `sentry-sdk`, `@mermaid-js/mermaid-cli` — the planner must insert a `checkpoint:human-verify` before each install per the phase protocol.

**Honest reading of both verdicts:** the `too-new` signal fires on the *latest release date*, not on package age. `sentry-sdk` is an eight-year-old package in the official `getsentry` org with 346 releases; `@mermaid-js/mermaid-cli` is a six-year-old package in the official `mermaid-js` org with ~600k weekly downloads. Both signals are heuristic false positives. The checkpoints are cheap; keep them, but the recommended human answer is "approve".

**Postinstall audit** `[VERIFIED: npm view <pkg> scripts --json]`:
- `@mermaid-js/mermaid-cli` — **no `postinstall`** (only `prepare`/`prepack`/`test`/`lint`).
- `puppeteer` (pulled transitively by the mermaid CLI toolchain) — **has `"postinstall": "node install.mjs"`, which downloads a Chrome build.** Always run the mermaid CLI with `PUPPETEER_SKIP_DOWNLOAD=1` and an explicit `executablePath` (see Pattern 11). This is both a supply-chain hygiene win and a ~170 MB saving.
- `sentry-sdk` — PyPI wheel, no install scripts; imports `urllib3`, **not** `requests` `[VERIFIED: fresh venv, `'requests' in sys.modules` → False after `import sentry_sdk`]`.

---

## Project Constraints (from CLAUDE.md and existing CI)

| Directive | Source | Phase-7 consequence |
|-----------|--------|---------------------|
| Backend is **async-only**; `requests`, `time.sleep`, sync `redis` are banned in `services/`, `shared/` | `CLAUDE.md`, `.github/workflows/lint.yml:19-27` | `ci.yml` **must keep all three ban greps verbatim**. `sentry-sdk` does not import `requests`, so the grep stays green; but the greps only scan `services/ shared/` source, never site-packages — do not use them as a dependency audit. |
| ruff line length 120 | `.ruff.toml` | New files (`shared/metrics.py`, `shared/observability.py`, `scripts/post_deploy_check.py`, `scripts/uptime_report.py`, `scripts/status_report.py`) must conform. |
| mypy **strict** over `shared/ services/ scripts/` | `pyproject.toml:56-59`, `Makefile:41` | Every new script is type-checked. `sentry_sdk` ships `py.typed`; `prometheus_client` does too. `ignore_missing_imports = true` is already set. |
| `uv run pytest tests/unit -x -q -W error::RuntimeWarning` | `Makefile:29-36` | New unit tests must not leave un-awaited coroutines. |
| Every compose image pinned, no `:latest`, no `version:` key | `tests/unit/test_compose_images_are_pinned.py` | The new `prometheus`/`grafana`/`kafka-exporter`/`redis-exporter` and the four service `image:` lines must all carry explicit tags — the existing test will fail the build otherwise. Service definitions that only have `build:` and no `image:` are invisible to that regex; give each built service an `image: ghcr.io/<owner>/mise-<svc>:${MISE_TAG:-dev}` so compose can also *pull* CD-built images. |
| Small commits, `STATUS: pending-human` runbook banners, grep-gate unit tests | 07-CONTEXT `<code_context>` | Keep the convention. |

---

## Architecture Patterns

### System Architecture Diagram

```
                       ┌──────────────────────────── prod profile ────────────────────────────┐
  OpenTable GraphQL ──▶│                                                                       │
    (httpx)            │  ┌────────┐  claim/release   ┌───────────────────────┐                │
                       │  │ poller │◀────────────────▶│ redis  (ZSET sched,   │                │
  Resy /4/find    ────▶│  │ :9101  │                  │  state, idempotency)  │                │
   (Playwright pool)   │  └───┬────┘                  └───────────┬───────────┘                │
                       │      │ availability.raw                  │                            │
                       │      │ polls.completed                   │                            │
                       │      ▼                                   │                            │
                       │  ┌──────────────────┐                    │                            │
                       │  │ kafka (KRaft, 1  │                    │                            │
                       │  │ broker, RF=1)    │                    │                            │
                       │  └──┬────────────┬──┘                    │                            │
                       │     │ raw        │ events                │                            │
                       │     ▼            ▼                       ▼                            │
                       │ ┌──────────────┐  ┌───────────┐   ┌──────────────┐                    │
                       │ │state_machine │  │ notifier  │   │ timescaledb  │                    │
                       │ │ :9102        │─▶│  :9103    │──▶│  hypertables │                    │
                       │ │ tri-state    │  │ NX EX     │   │  + poll_log  │                    │
                       │ │ diff, t+8s   │  │ claim     │   └──────┬───────┘                    │
                       │ └──────┬───────┘  └─────┬─────┘          │                            │
                       │        │ events         │ email/SMS/push │                            │
                       │        ▼                ▼                ▼                            │
                       │   ┌─────────────────────────────────────────────┐                     │
                       │   │ api (FastAPI)  /api/metrics /readyz /healthz │                     │
                       │   └──────────────────────┬──────────────────────┘                     │
                       │                          │ SSE + REST                                 │
                       │                     ┌────▼─────┐                                      │
                       │                     │   web    │  next start (standalone)             │
                       │                     │  :3000   │  /healthz                            │
                       │                     └──────────┘                                      │
                       └───────────────────────────────────────────────────────────────────────┘
                              ▲            ▲            ▲            ▲          ▲
              scrape /metrics │            │            │            │          │ /api/metrics
                       ┌──────┴────────────┴────────────┴────────────┴──────────┴──────┐
  monitoring profile   │ prometheus :9090  ◀── kafka-exporter :9308, redis-exporter :9121│
                       └───────────────────────────────┬───────────────────────────────┘
                                                       │ datasource (provisioned)
                                              ┌────────▼─────────┐
                                              │ grafana :3000    │  anonymous Viewer
                                              │ /d/mise (5 panels)│  → localhost:3001
                                              └──────────────────┘

  CI/CD:  push ──▶ ci.yml {lint, unit, integration, web, smoke} ──▶ cd.yml build+push GHCR
                                                                    └─▶ deploy-prod (gated, pending-human)
  Terraform skeleton: validated, never applied.
```

### Recommended new/changed files

```
ops/
├── docker-compose.yml                  # + prod & monitoring profiles; kafka image swap
├── docker/
│   ├── poller.Dockerfile               # MCR playwright base
│   ├── state_machine.Dockerfile        # python:3.12-slim
│   ├── notifier.Dockerfile             # python:3.12-slim
│   ├── api.Dockerfile                  # python:3.12-slim + uvicorn
│   └── web.Dockerfile                  # node:22-alpine, standalone   (or web/Dockerfile)
├── prometheus/
│   ├── prometheus.yml
│   └── rules/mise.rules.yml            # derived series, promtool-checkable
└── grafana/
    ├── provisioning/datasources/prometheus.yml
    ├── provisioning/dashboards/mise.yml
    └── dashboards/mise.json
shared/
├── metrics.py                          # SINGLE definition site (D-69, D-122)
└── observability.py                    # init_sentry(), sentry structlog processor
scripts/
├── post_deploy_check.py                # lag + poll_log gates
├── uptime_report.py                    # Better Uptime export OR Prometheus `up`
├── status_report.py                    # docs/status.json
└── render_diagram.py                   # writes puppeteer config from playwright path
terraform/{versions,variables,main,outputs}.tf + modules/*/main.tf
docs/{deploy/gcp.md, runbooks/uptime.md, HUMAN-ACTIONS.md, architecture.mmd, architecture.svg, status.json}
tests/e2e/{__init__.py,conftest.py,test_smoke.py}
.github/workflows/{ci.yml,cd.yml}       # lint.yml deleted
```

---

### Pattern 1: Two-stage `uv` image for a plain Python service

**What:** dependency layer (`--no-install-project`) cached separately from the source layer; runtime stage copies `/app` wholesale and runs non-root.
**When:** `state_machine`, `notifier`, `api`.
**Verified:** built and ran on this machine. `docker build` took 19.3 s warm; image **661 MB**; `docker run --entrypoint sh` printed `uid=1001(mise)`, `import OK 6` (the six `REQUIRED_TOPICS`), `deps ok`, `Python 3.12.14`.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Layer 1 — dependencies only. Cached until pyproject.toml/uv.lock change.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
# Layer 2 — project source.
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
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    METRICS_PORT=9102
USER mise
EXPOSE 9102
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('METRICS_PORT','9102')+'/metrics', timeout=2).status==200 else 1)"
ENTRYPOINT ["python", "-m", "services.state_machine"]
```

Notes that matter:
- `--no-install-project` on the first sync is what makes the dependency layer cacheable — without it every source edit re-resolves everything.
- `UV_PYTHON_DOWNLOADS=never` keeps uv from silently pulling a managed interpreter that differs from the base image.
- The `HEALTHCHECK` uses `urllib.request` from the venv Python; `python:3.12-slim` has **no `curl` and no `wget`**, so a shell-based probe would need an extra apt layer.
- The healthcheck depends on the metrics server being up — that is the point (a service that stopped serving `/metrics` is a service Prometheus has lost).
- `playwright` is an unconditional entry in `[project.dependencies]` (`pyproject.toml:11`), so **all four Python images carry the ~50 MB Python package** (not the browsers). Acceptable; moving it to an extra would churn `uv.lock` and every other phase's env.

### Pattern 2: The Playwright poller image

**Verified facts about `mcr.microsoft.com/playwright/python:v1.58.0-noble`** `[VERIFIED: docker run --rm … sh -c '…']`:

```
PRETTY_NAME="Ubuntu 24.04.3 LTS"
Python 3.12.3            # /usr/bin/python3 and /usr/bin/python   → satisfies requires-python >=3.12,<3.13
pip 25.3
PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
/ms-playwright: chromium-1208  chromium_headless_shell-1208  ffmpeg-1011  firefox-1509  webkit-2248
pwuser:x:1001:1001  (non-root user already present)
node: absent
`python3 -m pip show playwright` → EMPTY  # the PyPI package is NOT preinstalled; uv installs it from uv.lock
```

**So: no `uv python install 3.12` is required, and no fallback approach is needed.** D-119 is correct as written.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM mcr.microsoft.com/playwright/python:v1.58.0-noble AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/bin/python3.12 \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project
COPY shared/ /app/shared/
COPY services/ /app/services/
COPY scripts/ /app/scripts/
COPY pyproject.toml uv.lock /app/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev \
 && chown -R pwuser:pwuser /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    METRICS_PORT=9101
USER pwuser
EXPOSE 9101
HEALTHCHECK --interval=15s --timeout=3s --start-period=45s --retries=3 \
  CMD python -c "import urllib.request,os,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('METRICS_PORT','9101')+'/metrics', timeout=2).status==200 else 1)"
ENTRYPOINT ["python", "-m", "services.poller"]
```

Verified inside the built image, running as `pwuser`:

```
uid=1001(pwuser) gid=1001(pwuser) groups=1001(pwuser),100(users)
CHROMIUM OK: 145.0.7632.0                      # with args ["--disable-dev-shm-usage","--no-sandbox"]
NO-SANDBOX-FREE OK: 145.0.7632.0               # ALSO works WITHOUT --no-sandbox under default Docker seccomp
```

**Do not add `--no-sandbox`.** It was not required; dropping it keeps the Chromium sandbox enabled, which matters for a service that renders attacker-influenced pages.

**`--disable-dev-shm-usage` is still required** (PITFALLS.md:25 — the default 64 MB `/dev/shm` crashes Chromium), or set `shm_size: 512mb` on the compose service. Prefer the compose `shm_size` for prod and keep the flag as belt-and-braces.

**Size reality** `[VERIFIED: docker images]`:
```
mcr.microsoft.com/playwright/python:v1.58.0-noble   3.62GB (uncompressed)   0.96GB compressed, 4 layers (amd64)
mise-poller-test:scratch                            4.59GB
mise-sm-test:scratch                                 661MB
mise-web-test:scratch                                340MB
  /ms-playwright breakdown: chromium 602M, headless_shell 323M, firefox 253M, webkit 265M, ffmpeg 3.3M
```
`rm -rf /ms-playwright/{firefox-*,webkit-*}` in a later `RUN` **does not shrink the image** (the files persist in the base layer). Live with 4.59 GB, or accept the alternative in §Alternatives Considered. The GHCR push cost is front-loaded: the ~1 GB of base layers upload once, then only the `.venv`+source layers (~120 MB compressed) change per commit.

### Pattern 3: Next.js 15 `output: 'standalone'` on `node:22-alpine`

**Verified:** built (21.8 s) and run from a scaffolded Next **15.5.25** app; image **340 MB**; container reached `healthy`; `GET /` → 200; `GET /healthz` → `ok`; server log `✓ Ready in 31ms`.

```dockerfile
# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# NEXT_PUBLIC_* are INLINED into the bundle at BUILD time — they must be build args.
# Setting them as runtime env on the container has no effect. (Phase 6 D-110.)
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_SITE_URL=http://localhost:3000
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL \
    NEXT_PUBLIC_SITE_URL=$NEXT_PUBLIC_SITE_URL
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -g 1001 -S nodejs && adduser -S nextjs -u 1001
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
USER nextjs
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD wget --spider -q http://127.0.0.1:3000/healthz || exit 1
CMD ["node", "server.js"]
```

Three things the plan must carry:
1. `HOSTNAME=0.0.0.0` — the standalone `server.js` binds `localhost` otherwise and is unreachable from the compose network.
2. The three-`COPY` dance (`standalone`, `public`, `.next/static`) is mandatory; `standalone` deliberately omits static assets.
3. `web/` needs a tiny **`src/app/healthz/route.ts`** returning `ok` with `export const dynamic = "force-dynamic"` — otherwise the healthcheck has nothing cheap to hit and `up --wait` has no readiness signal. This is a **new file Phase 7 must add to `web/`** (Phase 6 does not specify one). `node:22-alpine` has `wget`; it has no `curl`.

### Pattern 4: Compose `monitoring` profile — provisioned Prometheus + anonymous Grafana

The whole stack below was stood up and torn down in the scratch dir. `docker compose up -d --wait` completed in **11.45 s** with every service healthy.

```yaml
  prometheus:
    image: prom/prometheus:v3.14.0
    profiles: [monitoring]
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.retention.time=15d
      - --web.enable-lifecycle
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus/rules:/etc/prometheus/rules:ro
      - prometheus-data:/prometheus
    ports: ["9090:9090"]
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:9090/-/healthy"]
      interval: 5s
      timeout: 3s
      retries: 10

  grafana:
    image: grafana/grafana:13.2.1
    profiles: [monitoring]
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer
      GF_AUTH_ANONYMOUS_ORG_NAME: "Main Org."
      GF_AUTH_BASIC_ENABLED: "false"
      GF_SECURITY_ALLOW_EMBEDDING: "true"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_ANALYTICS_CHECK_FOR_UPDATES: "false"
      GF_USERS_DEFAULT_THEME: dark
      GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH: /var/lib/grafana/dashboards/mise.json
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
    ports: ["3001:3000"]
    depends_on:
      prometheus: {condition: service_healthy}
    healthcheck:
      test: ["CMD-SHELL", "wget --spider -q http://localhost:3000/api/health || exit 1"]
      interval: 5s
      timeout: 3s
      retries: 20
```

**Anonymous access — measured, not assumed** (all requests sent with no credentials whatsoever):

```
GET  /api/health                                        -> 200 {"database":"ok","version":"13.2.1"}
GET  /d/mise                                            -> 200
GET  /api/dashboards/uid/mise                           -> 200, meta.provisioned = True,
                                                            url = /d/mise/mise-en-place-e28094-system-overview
GET  /api/search?query=                                 -> 200, one dash-db with uid "mise"
GET  /api/datasources                                   -> 200  (leaks the internal URL http://prometheus:9090)
GET  /api/datasources/proxy/uid/mise-prom/api/v1/query  -> 200
POST /api/ds/query                                      -> 200
panel titles read back: ['poll_success_rate','poll_latency_p95','kafka_consumer_lag',
                         'events_per_minute','notification_delivery_rate']
Grafana log: "starting to provision dashboards" / "finished to provision dashboards" — no errors.
```

`schemaVersion: 39` is accepted by Grafana 13.2.1 and the `uid: "mise"` is preserved, so `/d/mise` is a stable URL and the D-123 README link is safe.

Provisioning file shapes (both verified working):

```yaml
# ops/grafana/provisioning/datasources/prometheus.yml
apiVersion: 1
datasources:
  - name: Prometheus
    uid: mise-prom            # panels reference this uid; keep it stable
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
    jsonData:
      timeInterval: 15s
```

```yaml
# ops/grafana/provisioning/dashboards/mise.yml
apiVersion: 1
providers:
  - name: mise
    orgId: 1
    folder: ""
    type: file
    disableDeletion: true
    allowUiUpdates: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

`ops/prometheus/prometheus.yml` (targets are compose **service names**; the ones below were live and `up == 1`):

```yaml
global:
  scrape_interval: 15s
  scrape_timeout: 10s
  external_labels: {stack: mise-compose}
rule_files:
  - /etc/prometheus/rules/*.yml
scrape_configs:
  - job_name: prometheus
    static_configs: [{targets: ["localhost:9090"]}]
  - job_name: poller
    static_configs: [{targets: ["poller:9101"]}]
  - job_name: state_machine
    static_configs: [{targets: ["state_machine:9102"]}]
  - job_name: notifier
    static_configs: [{targets: ["notifier:9103"]}]
  - job_name: api
    metrics_path: /api/metrics
    static_configs: [{targets: ["api:8000"]}]
  - job_name: kafka
    static_configs: [{targets: ["kafka-exporter:9308"]}]
  - job_name: redis
    static_configs: [{targets: ["redis-exporter:9121"]}]
```

Exporters (both verified against the live broker/Redis):

```yaml
  kafka-exporter:
    image: danielqsj/kafka-exporter:v1.9.0
    profiles: [monitoring]
    command: ["--kafka.server=kafka:9092", "--kafka.version=3.8.1"]
    depends_on: {kafka: {condition: service_healthy}}
  redis-exporter:
    image: oliver006/redis_exporter:v1.90.0
    profiles: [monitoring]
    environment: {REDIS_ADDR: "redis://redis:6379"}
    depends_on: {redis: {condition: service_healthy}}
```

**`kafka_consumergroup_lag` is real and correct.** After producing 20 messages and consuming 5 with group `state-machine`, `kafka-consumer-groups.sh --describe` reported LAG 15 on partition 0; the exporter simultaneously served:

```
kafka_consumergroup_lag{consumergroup="state-machine",partition="0",topic="availability.raw"} 15
kafka_consumergroup_lag_sum{consumergroup="state-machine",topic="availability.raw"} 15
kafka_consumergroup_members{consumergroup="state-machine"} 0
```
and Prometheus answered `sum by (consumergroup) (kafka_consumergroup_lag)` → `{consumergroup="state-machine"} 15`. Other families exposed: `kafka_brokers`, `kafka_topic_partitions`, `kafka_topic_partition_{current,oldest}_offset`, `kafka_topic_partition_under_replicated_partition`, `kafka_consumergroup_current_offset[_sum]`.

### Pattern 5: Compose profile semantics (measured)

```
docker compose config --services                                  -> redis                     (profile-less only)
docker compose --profile prod config --services                   -> redis, migrate, app
docker compose --profile prod --profile monitoring config --services -> prom, redis, migrate, app
```

- **Profile-less services always start**, even when `--profile x` is given. So the existing `kafka`/`redis`/`postgres` need no profile; only the four services + `web` + `prometheus`/`grafana`/exporters do.
- `depends_on: {migrate: {condition: service_completed_successfully}}` works and is the right shape for a one-shot `make migrate`/`create_topics` container in the prod profile. Observed: `migrate Exited (0)` then `app Started`.
- `docker compose up -d --wait` **exits 1** when any waited-for container ends unhealthy, and it does so as soon as the retries are exhausted (8.6 s with `--wait-timeout 30`), not at the timeout.
- **Pipe trap:** `docker compose up -d --wait 2>&1 | tail -25; echo $?` printed `EXIT=0` — that is `tail`'s status. Without the pipe the same command returned `REAL EXIT=1`. Every CI shell step that pipes compose output **must** set `set -o pipefail` (add `shell: bash` + `set -euo pipefail`).
- Services with **no** healthcheck are treated as ready by `--wait` as soon as they are running (observed for `kafka-exporter`/`redis-exporter`). Add healthchecks to anything whose readiness the smoke job depends on.

### Pattern 6: Async Playwright e2e under pytest-asyncio

**Two working shapes, one broken one — all measured.**

```
scope="module" plain @pytest.fixture async generator, asyncio_mode=auto  -> HANGS (killed at >420 s)
function-scoped @pytest.fixture async generator                          -> 2 passed in 0.73 s
@pytest_asyncio.fixture(scope="module", loop_scope="module")
  + pytestmark = pytest.mark.asyncio(loop_scope="module")                -> 2 passed in 0.71 s
```

Use the third shape so Chromium launches once per module:

```python
# tests/e2e/test_smoke.py
from __future__ import annotations
import os
import pytest, pytest_asyncio
from playwright.async_api import async_playwright

WEB = os.getenv("SMOKE_WEB_URL", "http://localhost:3000")
pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]

@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def browser():
    async with async_playwright() as p:
        b = await p.chromium.launch(args=["--disable-dev-shm-usage"])
        yield b
        await b.close()

@pytest_asyncio.fixture(loop_scope="module")
async def page(browser):
    ctx = await browser.new_context(viewport={"width": 390, "height": 844})  # mobile-first, D-111
    pg = await ctx.new_page()
    yield pg
    await ctx.close()

async def test_home_renders(page):
    resp = await page.goto(WEB, wait_until="domcontentloaded")
    assert resp is not None and resp.status == 200
    await page.wait_for_selector("[data-testid=hero]")
```

`pyproject.toml` needs an **`e2e` marker** registered — `[tool.pytest.ini_options].markers` currently declares only `integration` (`pyproject.toml:50-52`). Without it, `-m e2e` under `filterwarnings`-strict CI is a warning, and `-W error::RuntimeWarning` in `make test` is unforgiving.

`page.request.get(...)` is available on the page and is the cheapest way to assert an API response from the same browser context (used to verify `/healthz` → `"ok"`).

### Pattern 7: Consumer lag with `aiokafka` — the correct recipe

**Two traps, both reproduced against a live broker with a known lag of 15:**

```
consumer.partitions_for_topic("availability.raw")            -> None   # unsubscribed consumer
after await consumer._client.fetch_all_metadata()            -> None   # STILL None
admin.list_consumer_group_offsets(g, partitions=[])          -> {}     # silently zero lag
admin.list_consumer_group_offsets(g)                         -> {TP(...,0): OffsetAndMetadata(5,''), TP(...,1): (0,''), TP(...,2): (0,'')}
```

The naive implementation returned `{'state-machine': 0}`. The correct one returned `{'state-machine': 15, 'notifier': -1, 'does-not-exist': -1}` — matching the exporter exactly, and distinguishing "no lag" from "group has never committed".

```python
# scripts/post_deploy_check.py (verified core)
async def consumer_lag(bootstrap: str, groups: list[str]) -> dict[str, int]:
    """Total lag per consumer group, derived from COMMITTED partitions only.

    Do NOT pass `partitions=` to list_consumer_group_offsets: an empty list yields {}
    and therefore a silent lag of 0. And do NOT use consumer.partitions_for_topic()
    on an unsubscribed consumer — it returns None (verified, aiokafka 0.13.0).
    -1 means "group unknown / never committed", which is NOT the same as lag 0.
    """
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
    consumer = AIOKafkaConsumer(bootstrap_servers=bootstrap, enable_auto_commit=False)
    await admin.start()
    await consumer.start()
    out: dict[str, int] = {}
    try:
        for g in groups:
            committed = await admin.list_consumer_group_offsets(g)
            if not committed:
                out[g] = -1
                continue
            tps = list(committed)
            ends = await consumer.end_offsets(tps)
            out[g] = sum(max(0, ends[tp] - max(committed[tp].offset, 0)) for tp in tps)
    finally:
        await consumer.stop()
        await admin.close()
    return out
```

`AIOKafkaAdminClient` methods available in 0.13.0 `[VERIFIED: dir()]`: `alter_configs, close, create_partitions, create_topics, delete_records, delete_topics, describe_cluster, describe_configs, describe_consumer_groups, describe_topics, find_coordinator, list_consumer_group_offsets, list_consumer_groups, list_topics, start`.

Exit-code convention to match `scripts/check_poll_success.py` (`main() -> None` then `sys.exit(exit_code)`, `scripts/check_poll_success.py:126-128`): 0 = pass, 1 = fail, 2 = insufficient data.

### Pattern 8: A `terraform/` skeleton that validates with no credentials

**Verified on Terraform 1.13.0:**

```
terraform fmt -recursive -check   -> exit 3 before formatting; exit 0 after `terraform fmt -recursive`
terraform init -backend=false     -> "Terraform has been successfully initialized!"  (google 7.46.1, .terraform = 117 MB)
terraform validate                -> "Success! The configuration is valid."   exit 0
terraform plan -input=false       -> exit 0   (no resources ⇒ no credentials needed even for plan)
```

`versions.tf`:

```hcl
terraform {
  required_version = ">= 1.9.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.9"
    }
  }
  # No backend block on purpose: STATUS pending-human — this skeleton is never applied,
  # and a backend would require credentials for `terraform init`.
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone
}
```

Module stubs carry `variable` + `output` + a `TODO(human)` comment and **no `resource` blocks**, which is what keeps `validate` credential-free:

```hcl
# terraform/modules/cloud_run_api/main.tf
# STATUS: pending-human — not applied. TODO(human): google_cloud_run_v2_service with
# min_instances = 1 and timeout = 3600s for the SSE endpoint (PITFALLS 13, 20).
variable "project_id" { type = string }
variable "region"     { type = string }
variable "image"      { type = string }

output "url" { value = "" }
```

Gotchas:
- **`terraform fmt` re-aligns single-line blocks**, so hand-aligned `variable "region"     { … }` fails `fmt -check`. Run `terraform fmt -recursive` before committing and gate CI on `terraform fmt -check -recursive`.
- Commit `.terraform.lock.hcl` so `init` is reproducible; cache `.terraform/` in CI (117 MB provider download otherwise).
- Module stubs must satisfy the caller: every variable passed in `main.tf` must be declared in the module, and every `output` referenced must exist. `validate` catches both.

### Pattern 9: Offline validation gates for Prometheus config **and** PromQL

Both verified in the `prom/prometheus:v3.14.0` container — no server needed:

```bash
docker run --rm --entrypoint promtool -v "$PWD/ops/prometheus:/cfg:ro" prom/prometheus:v3.14.0 \
  check config /cfg/prometheus.yml
#   SUCCESS: /cfg/prometheus.yml is valid prometheus config file syntax     (exit 0)
#   negative control -> FAILED: ... cannot unmarshal !!str `notalist` into []string   (exit 1)

docker run --rm --entrypoint promtool -v "$PWD/ops/prometheus:/cfg:ro" prom/prometheus:v3.14.0 \
  check rules /cfg/rules/mise.rules.yml
#   SUCCESS: 5 rules found                                                   (exit 0)
#   negative control -> FAILED: ... could not parse expression: 1:25: parse error: unexpected <aggr:sum>
```

There is **no `promtool check promql`** subcommand — putting the five derived expressions in a recording-rule file is the only way to get an offline PromQL syntax gate. Recommended file (validated verbatim):

```yaml
# ops/prometheus/rules/mise.rules.yml
groups:
  - name: mise-derived
    interval: 30s
    rules:
      - record: mise:poll_success_rate:5m
        expr: sum(rate(poll_total{status="success"}[5m])) / clamp_min(sum(rate(poll_total[5m])), 1e-9)
      - record: mise:poll_latency_p95:5m
        expr: histogram_quantile(0.95, sum by (le, source) (rate(poll_latency_seconds_bucket[5m])))
      - record: mise:kafka_consumer_lag:sum
        expr: sum by (consumergroup) (kafka_consumergroup_lag)
      - record: mise:events_per_minute:1m
        expr: sum(rate(events_emitted_total[1m])) * 60
      - record: mise:notification_delivery_rate:5m
        expr: sum(rate(notifications_total{status=~"sent|delivered"}[5m])) / clamp_min(sum(rate(notifications_total[5m])), 1e-9)
```

`clamp_min(…, 1e-9)` instead of a bare denominator: a plain division by `sum(rate(poll_total[5m]))` yields `NaN` when no polls happened in the window, which renders as a gap in Grafana and makes a healthy idle system look broken.

### Pattern 10: `shared/observability.py :: init_sentry()`

**No-op behaviour verified exactly as D-124 requires** (`sentry-sdk 2.68.1`):

```
init_sentry(None)                        -> False
sentry_sdk.get_client().is_active()      -> False
sentry_sdk.capture_message("hi")         -> None
threads created                          -> 0          # truly zero cost when DSN is unset
init_sentry("https://…@…/1")             -> True
get_client().is_active()                 -> True
transport                                -> HttpTransport   (background worker, spawned lazily)
capture_message() inside a running loop  -> 7.19 ms          (queued, not a network round-trip)
'requests' in sys.modules after import   -> False;  urllib3 -> True
```

The unit test D-127 asks for is therefore `assert sentry_sdk.get_client().is_active() is False` after `init_sentry(None)`.

```python
def init_sentry(dsn: str | None = None, *, env: str | None = None) -> bool:
    dsn = dsn if dsn is not None else os.getenv("SENTRY_DSN", "")
    if not dsn:
        return False                     # zero threads, zero network, zero cost
    sentry_sdk.init(
        dsn=dsn,
        environment=env or os.getenv("ENV", "dev"),
        release=os.getenv("GIT_SHA", "mise@0.1.0"),
        send_default_pii=False,
        traces_sample_rate=0.0,          # errors only; no tracing budget in scope
        shutdown_timeout=2.0,            # bounded: SIGTERM must not hang on a flush
        integrations=[LoggingIntegration(level=logging.INFO, event_level=None)],
        before_send=_scrub,
    )
    return True
```

`shutdown_timeout` matters: with a DSN set, process exit blocks flushing ("Sentry is attempting to send 2 pending events / Waiting up to 2 seconds" was printed on exit in the experiment). That is 2 s added to every `docker stop`; keep it explicit so nobody wonders where it came from. `_scrub` should drop `cookie`/`authorization` and also `extra["sys.argv"]`, which the SDK adds automatically (observed) and which can carry CLI secrets for the `scripts/` entry points.

### Pattern 11: Mermaid → SVG using the Playwright Chromium already on this machine

**Verified: 71,118-byte SVG produced in 1.36 s.**

```bash
export PUPPETEER_SKIP_DOWNLOAD=1
npx -y @mermaid-js/mermaid-cli@11.17.0 \
  -i docs/architecture.mmd -o docs/architecture.svg \
  -p .mermaid-puppeteer.json -b transparent
```

The puppeteer config must name the real binary. Its path is platform-specific — **`.../chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`**, not `Chromium.app/…` (my first guess failed with `Browser was not found at the configured executablePath`). Generate it instead of hard-coding:

```python
# scripts/render_diagram.py
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    exe = p.chromium.executable_path          # verified to return the exact path above
json.dump({"executablePath": exe, "args": ["--disable-dev-shm-usage"]},
          open(".mermaid-puppeteer.json", "w"))
```

**Recommendation:** commit both `docs/architecture.mmd` **and** the rendered `docs/architecture.svg`, make `make docs` regenerate the SVG via `scripts/render_diagram.py`, and add a CI job step that re-renders and `git diff --exit-code docs/architecture.svg` **only on a `docs` label or nightly** — not on every PR (it needs Chromium + a 170 MB puppeteer download unless the Playwright browser is already installed in that job).

### Pattern 12: PERF-04 uptime from Prometheus `up` (compose mode)

The live Prometheus answered `/api/v1/query?query=up` with per-job values (`kafka 1, redis 1, prometheus 1`), so the compose-mode arm of `scripts/uptime_report.py` is a plain HTTP call:

```
GET {PROM}/api/v1/query?query=avg_over_time(up{job=~"api|poller|state_machine|notifier"}[30d])
```

Exit 0 iff the min across jobs ≥ 0.995, exit 2 when the series has fewer samples than the window demands (a 15-day-retention Prometheus cannot answer a 30-day question — `--storage.tsdb.retention.time=15d` above; either raise retention to `35d` or make the window a CLI flag and report the actual coverage). **The Better Uptime arm is pending-human** and reads a JSON export; do not invent the API shape.

### Anti-Patterns to Avoid

- **Hand-rolling Kafka lag from `poll_log` or a consumer offset table.** The broker already knows; `list_consumer_group_offsets` + `end_offsets` is 12 lines and matches the exporter exactly.
- **A `HEALTHCHECK` that shells out to `curl`/`wget` on `python:3.12-slim`.** Neither binary exists; you would add an apt layer to run a probe.
- **Runtime `NEXT_PUBLIC_*` env on the web container.** They are inlined at build time; setting them at runtime silently does nothing.
- **`--no-sandbox` in the poller image.** Not needed (proved), and it disables a real defence for a service that renders remote pages.
- **`rm -rf` in a later layer to shrink an image.** Base-layer bytes are immutable.
- **Piping compose output to `tail`/`head` in a CI step without `pipefail`.** Turns a red build green.
- **Cardinality by `restaurant_id`/`date` on the new metrics** (PITFALLS.md:351-353). Keep `poll_total` labelled `{source,status}` exactly as D-122 says.
- **Adding `pytest-playwright`.** Its fixtures are sync; the repo is async-only.

---

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Kafka consumer lag as a metric | a poller that writes lag to a gauge | `danielqsj/kafka-exporter:v1.9.0` | Handles group coordinator discovery, partition enumeration, and `-1` sentinel offsets. Verified to match `kafka-consumer-groups.sh`. |
| Redis metrics | `INFO` parsing | `oliver006/redis_exporter:v1.90.0` | Hundreds of fields, versioned field renames. |
| HTTP request metrics on FastAPI | middleware counting requests | `prometheus-fastapi-instrumentator==7.1.0` | Route-template grouping (`/watches/{wid}`, not one series per id), `excluded_handlers`, gzip, status-class handling. |
| Metrics HTTP server in an asyncio service | an aiohttp/FastAPI sidecar app | `prometheus_client.start_http_server` | Verified daemon-thread WSGI server; does not touch the event loop (50/50 loop ticks completed during 20 concurrent scrapes). |
| Error grouping / release tracking | log scraping + alerts | `sentry-sdk` | Fingerprinting, breadcrumbs, release health, PII scrubbing. |
| Docker image tagging in CI | `shell` string building from `github.sha` | `docker/metadata-action@v6` | Auto-lowercases the image name (GHCR rejects uppercase) and emits `sha-<7>` from `type=sha`. |
| Buildx layer cache in Actions | `actions/cache` on `/tmp/.buildx-cache` | `cache-from/cache-to: type=gha,mode=max` | The manual dance is obsolete and unbounded. |
| PromQL correctness checking | a regex over the dashboard JSON | `promtool check rules` on a recording-rule file | Real parser; verified to reject a malformed `histogram_quantile`. |
| Mermaid rendering | hand-drawn SVG | `@mermaid-js/mermaid-cli` | Text source stays reviewable and diffable. |

**Key insight:** every observability primitive in this phase already exists as a small, boring, well-tested binary. The only code Phase 7 should write is the *glue* that is specific to this system — the metric name registry (`shared/metrics.py`), the Sentry↔structlog bridge (which genuinely does not exist off the shelf for this logging config), the two health-gate scripts, and the status generator.

---

## Common Pitfalls

### Pitfall 1: Sentry turns every structlog ERROR into its own issue

**What goes wrong:** With `LoggingIntegration`'s default `event_level=logging.ERROR` and `shared/telemetry.py`'s `structlog.stdlib.LoggerFactory()` + `JSONRenderer`, the Sentry issue *message* is the entire rendered JSON line — including a per-call ISO timestamp. Sentry groups by message, so grouping collapses to one issue per occurrence.

**Reproduced** (`sentry-sdk 2.68.1`, repo's exact structlog config, in-memory transport):

```
=== captured sentry events: 2
  level: error
  logger: services.state_machine.consumer
  message: {"topic": "availability.raw", "partition": 0, "attempts": 5, "event":
            "message_retries_exhausted", "level": "error", "logger":
            "services.state_machine.consumer", "timestamp": "2026-…
```

**Why it happens:** structlog renders *before* handing the string to stdlib logging; Sentry only sees the rendered string.

**How to avoid:** own the capture in a structlog processor and set `LoggingIntegration(level=logging.INFO, event_level=None)` so the integration contributes breadcrumbs only (no double reporting — verified: exactly 2 events, not 4).

### Pitfall 2: `log.exception()` reaches Sentry with **no exception attached**

**What goes wrong:** the stack trace is lost; the Sentry issue has a message and nothing else.

**Reproduced:** with the default integration, the `log.exception("kafka_send_failed")` case produced `exception?: False`.

**Why it happens:** `structlog.processors.format_exc_info` pops `exc_info` and replaces it with a rendered `"Traceback (most recent call last): …"` **string** before the stdlib record is created.

**How to avoid — verified fix.** The processor must sit **before** `format_exc_info` in the chain:

```python
_SENTRY_SKIP = {"event", "level", "logger", "timestamp"}

def sentry_processor(logger, method, event_dict):
    """Capture ERROR/CRITICAL structlog events as grouped Sentry issues.

    MUST run BEFORE structlog.processors.format_exc_info: that processor replaces
    ``exc_info`` with a rendered string, after which the traceback is unrecoverable.
    """
    if method in ("error", "exception", "critical") and sentry_sdk.get_client().is_active():
        name = event_dict.get("event", "log")
        level = "fatal" if method == "critical" else "error"
        with sentry_sdk.new_scope() as scope:
            scope.set_level(level)
            scope.fingerprint = [event_dict.get("logger", "?"), name]   # stable grouping
            for k, v in event_dict.items():
                if k not in _SENTRY_SKIP and k != "exc_info":
                    scope.set_extra(k, v)
            exc_info = event_dict.get("exc_info")
            if exc_info:
                sentry_sdk.capture_exception(sys.exc_info() if exc_info is True else exc_info)
            else:
                sentry_sdk.capture_message(name, level=level)
    return event_dict
```

Verified output after the fix:

```
=== events: 2
 level: error | fingerprint: ['services.state_machine.consumer', 'message_retries_exhausted']
 message: message_retries_exhausted
 exception: None
 extra: {'topic': 'availability.raw', 'attempts': 5, 'sys.argv': [...]}
 ---
 level: error | fingerprint: ['services.state_machine.consumer', 'kafka_send_failed']
 exception: ValueError: boom
 extra: {'topic': 'availability.events', 'sys.argv': [...]}
```

`shared/telemetry.py::configure_logging` must insert this processor into `shared_processors` immediately before `structlog.processors.format_exc_info` (currently `shared/telemetry.py:118-124`). Do **not** use `scope._level` (private); pass the literal level string as above.

### Pitfall 3: `prometheus_client` suffix rules make a metric name a contract

**Measured** with `generate_latest` on a fresh registry:

```
Counter("poll_total")              -> poll_total{...}                 AND poll_created{...}
Counter("scrape_ban_total")        -> scrape_ban_total{...}           AND scrape_ban_created{...}
Counter("events_emitted")          -> events_emitted_total            AND events_emitted_created
Gauge("sse_connections_active")    -> sse_connections_active          (no suffix)
Histogram("notification_latency_seconds") -> _bucket{le=…}, _count, _sum, _created
```

Two consequences for D-122 and the D-123 drift guard:
- **`sse_connections_active` must be a `Gauge`.** A `Counter` of that name would be exposed as `sse_connections_active_total` and the dashboard query would return nothing.
- The drift-guard test must normalise **`_total`, `_created`, `_bucket`, `_sum`, `_count`** off PromQL metric names before comparing against the identifiers in `shared/metrics.py`. Note the asymmetry: `Counter("poll_total")` produces a `_created` series named `poll_created` (the `_total` is stripped, not appended to).

### Pitfall 4: The API `/api/metrics` route and the OpenAPI snapshot

**Verified** with `prometheus-fastapi-instrumentator==7.1.0`:

```python
Instrumentator(
    should_group_status_codes=False,
    should_ignore_untemplated=True,
    excluded_handlers=["/api/metrics", "/healthz"],
).instrument(app).expose(app, endpoint="/api/metrics", include_in_schema=False, should_gzip=False)
```
```
GET /api/metrics -> 200, content-type: text/plain; version=1.0.0; charset=utf-8
http_requests_total{handler="/watches/{wid}",method="GET",status="200"} 2.0
http_request_duration_highr_seconds_bucket{le="0.01"} 2.0
sse_connections_active_total 0.0
openapi has /api/metrics: False
```

`should_ignore_untemplated=True` is what keeps `/watches/abc` and `/watches/def` on one series (`handler="/watches/{wid}"`) instead of two — the cardinality guard PITFALLS.md:351 warns about. `include_in_schema=False` keeps the route out of `/openapi.json`; **decide deliberately**, because Phase 5 D-104 pins the public route list in `tests/unit/test_openapi_snapshot.py` and D-101 calls `/api/metrics` a public route. Recommendation: `include_in_schema=False` plus an explicit assertion in the drift guard that the route responds — a metrics endpoint in a client-facing OpenAPI schema is noise.

### Pitfall 5: Switching the Kafka image is a four-part change

`apache/kafka:3.8.1` came up healthy and served everything, but it is **not** a drop-in for `bitnamilegacy/kafka:3.8`:

| Concern | bitnamilegacy 3.8 (current, `ops/docker-compose.yml`) | apache/kafka 3.8.1 (verified) |
|---|---|---|
| env prefix | `KAFKA_CFG_NODE_ID`, `KAFKA_CFG_LISTENERS`, … | `KAFKA_NODE_ID`, `KAFKA_LISTENERS`, … (plain `KAFKA_` → `server.properties`) |
| cluster id | `KAFKA_KRAFT_CLUSTER_ID` | **`CLUSTER_ID`** — `ensure CLUSTER_ID` in `/etc/kafka/docker/configure`; the container refuses to start without it |
| CLI on `PATH` | yes (`kafka-topics.sh …`) | **no** — `command -v kafka-topics.sh` fails; use `/opt/kafka/bin/kafka-topics.sh` |
| data volume | `/bitnami/kafka` | `/var/lib/kafka/data` (`KAFKA_LOG_DIRS`) |
| user | root-ish | `appuser` uid 1000 |
| tools present | curl/wget | `wget` only |
| maintenance | **"Legacy Bitnami images (no longer updated)"**, last push 2025-07-18 | actively released (4.3.1 is current) |

Blast radius of the swap inside this repo: `ops/docker-compose.yml:8,29,31`, `Makefile:51` (`kafka-console-consumer.sh` → absolute path), `README.md:306` (says "the compose stack … uses `bitnami/kafka`"), and `tests/unit/test_compose_images_are_pinned.py`'s docstring. `tests/conftest.py:24` uses `confluentinc/cp-kafka:7.6.0` via testcontainers and is **unaffected**. Existing local volumes must be dropped (`make down` then `docker volume rm mise_kafka-data`, or `docker compose down -v`) — the two images' log-dir layouts are not interchangeable.

**Recommendation:** swap **both** the default and the `prod` profile to `apache/kafka:3.8.1` in one dedicated task with a `docker compose down -v` note in the plan and the README. Running one image in dev and a different one in "prod" would recreate exactly the dev/prod skew this phase exists to remove.

### Pitfall 6: `docker compose up --wait` exit status is easy to swallow

Covered in Pattern 5. The one-line rule for every CI step: `shell: bash` + `set -euo pipefail`.

### Pitfall 7: The poller image dominates smoke-job time

4.59 GB uncompressed / ~0.96 GB of base layers compressed. The D-121 smoke path is `replay_raw.py --input → Kafka → state_machine → notifier → api → web` — **it never polls anything**, so the poller container is not required to prove it. Building and starting it costs the smoke job several minutes for no assertion.

**Recommendation:** give the poller its own profile (`profiles: [prod, poller]`) so the smoke job can run `--profile smoke --profile monitoring` with the three light images, and let `cd.yml` build all four with `cache-to: type=gha,mode=max`. If the plan prefers to keep one `prod` profile verbatim per D-119, then the smoke job must at minimum use buildx GHA cache and set a generous `timeout-minutes`.

### Pitfall 8: `python:3.12-slim` is a moving tag

Today it is Debian 13 (trixie) with Python 3.12.14; three months ago it was bookworm. A base-OS change under a stable-looking tag can break a wheel or a `HEALTHCHECK`. Pin by digest (`python:3.12-slim@sha256:…`) in `ops/docker/*.Dockerfile`, or accept the churn knowingly and say so in a comment. The existing `test_compose_images_are_pinned.py` only guards `image:` lines in compose — it does **not** see `FROM` lines. Consider extending it to grep `ops/docker/*.Dockerfile` for `FROM …:latest`.

### Pitfall 9: Grafana's anonymous Viewer exposes the datasource URL

`GET /api/datasources` returned 200 to an unauthenticated client, including `"url":"http://prometheus:9090"`. On localhost this is nothing; if the Grafana port is ever exposed publicly it is internal-topology disclosure. Bind the Grafana port to `127.0.0.1:3001:3000` in the compose file and say in `docs/deploy/gcp.md` that public exposure goes through Grafana Cloud public dashboards (pending-human), never through this container.

### Pitfall 10: pytest-asyncio module-scoped async fixtures hang

Covered in Pattern 6 — the plain `@pytest.fixture(scope="module")` async generator never returned (killed after 420 s). Anyone writing `tests/e2e/conftest.py` will reach for exactly that shape.

---

## Code Examples

### The `prod` profile service block (all four Python services follow this shape)

```yaml
  state_machine:
    image: ghcr.io/${GHCR_OWNER:-local}/mise-state_machine:${MISE_TAG:-dev}
    build:
      context: ..
      dockerfile: ops/docker/state_machine.Dockerfile
    profiles: [prod]
    env_file: [../.env]
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      REDIS_URL: redis://redis:6379/0
      DATABASE_URL_ASYNC: postgresql+asyncpg://mise:mise@postgres:5432/mise
      DATABASE_URL_SYNC: postgresql+psycopg://mise:mise@postgres:5432/mise
      METRICS_PORT: "9102"
      ENV: prod
    depends_on:
      kafka:    {condition: service_healthy}
      redis:    {condition: service_healthy}
      postgres: {condition: service_healthy}
      migrate:  {condition: service_completed_successfully}
      topics:   {condition: service_completed_successfully}
    restart: unless-stopped
```

`image:` **and** `build:` together is deliberate: `docker compose --profile prod build` produces the tag CD pushes, and `MISE_TAG=sha-abc1234 docker compose --profile prod pull` can fetch a CD-built image without rebuilding. It also keeps `test_compose_images_are_pinned.py` green.

The poller additionally needs `shm_size: 512mb` (PITFALLS.md:25) and `METRICS_PORT: "9101"`.

### The `apache/kafka:3.8.1` env block (verified booting to healthy)

```yaml
  kafka:
    image: apache/kafka:3.8.1
    container_name: mise-kafka
    ports: ["9092:9092", "9094:9094"]
    environment:
      CLUSTER_ID: MkU3OEVBNTcwNTJENDM2Qg          # required by /etc/kafka/docker/configure
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: broker,controller
      KAFKA_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093,EXTERNAL://:9094
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092,EXTERNAL://localhost:9094
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,EXTERNAL:PLAINTEXT
      KAFKA_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_DEFAULT_REPLICATION_FACTOR: 1          # MVP: single broker, RF=1 — documented tradeoff
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_TRANSACTION_STATE_LOG_MIN_ISR: 1
      KAFKA_MIN_INSYNC_REPLICAS: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "false"     # D-27 startup guards depend on this
      KAFKA_LOG_DIRS: /var/lib/kafka/data
    volumes: ["kafka-data:/var/lib/kafka/data"]
    healthcheck:
      test: ["CMD-SHELL", "/opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list || exit 1"]
      interval: 5s
      timeout: 10s
      retries: 20
      start_period: 20s
```

### `shared/metrics.py` — the single definition site (D-69 + D-122)

```python
"""The ONE place a Prometheus metric is defined. ops/grafana/dashboards/mise.json and
ops/prometheus/rules/mise.rules.yml may only reference names declared here; a unit test
enforces that (drift guard, D-123)."""
from prometheus_client import Counter, Gauge, Histogram

POLL_TOTAL            = Counter("poll_total", "Polls by source and outcome", ["source", "status"])
POLL_LATENCY          = Histogram("poll_latency_seconds", "Poll wall time", ["source"])
EVENTS_EMITTED_TOTAL  = Counter("events_emitted", "Confirmed availability events", ["source"])   # -> events_emitted_total
NOTIFICATIONS_TOTAL   = Counter("notifications_total", "Notification sends", ["channel", "status"])
NOTIFICATION_LATENCY  = Histogram("notification_latency_seconds", "Detection→send", ["channel"])
SCRAPE_BAN_TOTAL      = Counter("scrape_ban_total", "Soft-ban verdicts", ["source", "reason"])
SSE_CONNECTIONS       = Gauge("sse_connections_active", "Open SSE connections")   # GAUGE, not Counter
```

### Starting the metrics server inside an existing `AsyncExitStack`

`start_http_server` returns `(WSGIServer, Thread)` in `prometheus-client 0.25.0`; the thread is a daemon and `server.shutdown()` + `thread.join()` is clean `[VERIFIED: "threads added: 1 thread: Thread-1 (serve_forever) daemon: True" … "server shutdown clean: True"]`. During 20 concurrent scrapes the event loop completed all 50 of its scheduled ticks — it does not block.

```python
# inside services/state_machine/main.py::run(), alongside the existing AsyncExitStack
server, thread = start_http_server(int(os.getenv("METRICS_PORT", "9102")), addr="0.0.0.0")
stack.callback(lambda: (server.shutdown(), thread.join(timeout=2)))
```

Note `addr="0.0.0.0"` (not the `127.0.0.1` used in the experiment) so Prometheus can reach it across the compose network — while the container `HEALTHCHECK` still probes `127.0.0.1`.

### `.github/workflows/ci.yml` skeleton (pinned versions verified 2026-09-05)

```yaml
name: ci
on:
  push: {branches: [main]}
  pull_request:
concurrency:
  group: ci-${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
defaults:
  run: {shell: bash}
env:
  UV_VERSION: "0.11.7"        # must match ops/docker/*.Dockerfile and the uv.lock writer

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with: {version: "${{ env.UV_VERSION }}", enable-cache: true}
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run mypy shared/ services/ scripts/
      - name: ban_requests_import
        run: '! grep -rn "^import requests\|^from requests " services/ shared/'
      - name: ban_time_sleep_in_async
        run: '! grep -rn "time\.sleep(" services/ shared/'
      - name: ban_sync_redis_import
        run: '! grep -rEn "^import redis$|^from redis import " services/ shared/'

  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with: {version: "${{ env.UV_VERSION }}", enable-cache: true}
      - run: uv sync --frozen
      - run: uv run pytest tests/unit -q -W error::RuntimeWarning

  integration:
    runs-on: ubuntu-latest          # Docker is preinstalled on the GitHub-hosted image
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10
        with: {version: "${{ env.UV_VERSION }}", enable-cache: true}
      - run: uv sync --frozen
      - run: uv run playwright install --with-deps chromium
      - run: uv run pytest tests/integration -q -p no:cacheprovider

  web:
    runs-on: ubuntu-latest
    defaults: {run: {working-directory: web}}
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-node@v7
        with: {node-version: "22", cache: npm, cache-dependency-path: web/package-lock.json}
      - run: npm ci
      - run: npm run lint
      - run: npm test
      - run: npm run build

  ops-config:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - run: docker compose -f ops/docker-compose.yml --profile prod --profile monitoring config -q
      - run: |
          docker run --rm --entrypoint promtool -v "$PWD/ops/prometheus:/cfg:ro" \
            prom/prometheus:v3.14.0 check config /cfg/prometheus.yml
      - run: |
          docker run --rm --entrypoint promtool -v "$PWD/ops/prometheus:/cfg:ro" \
            prom/prometheus:v3.14.0 check rules /cfg/rules/mise.rules.yml
      - uses: hashicorp/setup-terraform@v4
        with: {terraform_version: "1.13.0", terraform_wrapper: false}
      - run: terraform -chdir=terraform fmt -check -recursive
      - run: terraform -chdir=terraform init -backend=false -input=false
      - run: terraform -chdir=terraform validate

  smoke:
    runs-on: ubuntu-latest
    needs: [lint, unit]
    timeout-minutes: 30
    steps:
      - uses: actions/checkout@v7
      - uses: docker/setup-buildx-action@v4
      - uses: astral-sh/setup-uv@v10
        with: {version: "${{ env.UV_VERSION }}", enable-cache: true}
      - run: uv sync --frozen
      - run: uv run playwright install --with-deps chromium
      - name: bring up the stack
        run: |
          set -euo pipefail                       # compose's exit code must not be swallowed
          cp .env.example .env
          docker compose -f ops/docker-compose.yml --profile prod --profile monitoring \
            up -d --build --wait --wait-timeout 600
      - run: uv run python scripts/post_deploy_check.py --mode compose
      - run: uv run pytest tests/e2e -q -m e2e -p no:cacheprovider
      - if: always()
        run: docker compose -f ops/docker-compose.yml --profile prod --profile monitoring logs --no-color > compose.log
      - if: always()
        uses: actions/upload-artifact@v7
        with: {name: compose-logs, path: compose.log}
```

### `.github/workflows/cd.yml` — GHCR with `GITHUB_TOKEN`

```yaml
name: cd
on:
  push: {branches: [main]}
  workflow_dispatch:
    inputs:
      image_tag: {description: "sha-<short> tag to promote", required: true, type: string}
concurrency: {group: cd-${{ github.ref }}, cancel-in-progress: false}

jobs:
  build-push:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write            # required for ghcr.io pushes with GITHUB_TOKEN
    strategy:
      matrix:
        service: [poller, state_machine, notifier, api, web]
    steps:
      - uses: actions/checkout@v7
      - uses: docker/setup-buildx-action@v4
      - uses: docker/login-action@v4
        with:
          registry: ghcr.io
          username: ${{ github.repository_owner }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v6
        with:
          images: ghcr.io/${{ github.repository_owner }}/mise-${{ matrix.service }}
          tags: |
            type=sha
            type=ref,event=branch
      - uses: docker/build-push-action@v7
        with:
          context: .
          file: ops/docker/${{ matrix.service }}.Dockerfile
          push: true
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha,scope=${{ matrix.service }}
          cache-to: type=gha,mode=max,scope=${{ matrix.service }}
          provenance: false

  deploy-prod:
    needs: [build-push]
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: pending-human notice
        if: ${{ secrets.GCP_PROJECT_ID == '' || secrets.GCP_WORKLOAD_IDENTITY_PROVIDER == '' }}
        run: |
          echo "::notice title=pending-human::GCP promotion is not configured."
          echo "See docs/deploy/gcp.md and docs/HUMAN-ACTIONS.md."
      - if: ${{ secrets.GCP_PROJECT_ID != '' && secrets.GCP_WORKLOAD_IDENTITY_PROVIDER != '' }}
        uses: google-github-actions/auth@v3
        with:
          project_id: ${{ secrets.GCP_PROJECT_ID }}
          workload_identity_provider: ${{ secrets.GCP_WORKLOAD_IDENTITY_PROVIDER }}
      # …gcloud run deploy… then:
      # uv run python scripts/post_deploy_check.py --mode prod --api-url "$API_URL"
```

Facts behind this file:
- `docker/metadata-action` "will automatically … Lowercase the image name" `[CITED: github.com/docker/metadata-action README]` — this matters because `github.repository_owner` may contain capitals and GHCR rejects them.
- `type=sha` emits `sha-<7 chars>` by default `[CITED: same README]`, which is exactly D-120's `:sha-<short>`.
- `permissions: packages: write` is what lets `GITHUB_TOKEN` push to GHCR; `docker/login-action@v4` with `password: ${{ secrets.GITHUB_TOKEN }}` is the documented login `[CITED: docs.docker.com/build/ci/github-actions/push-multi-registries/]`.
- `cache-to: type=gha` requires Buildx ≥ 0.21 / BuildKit ≥ 0.20 because GitHub retired the v1 cache API on 2025-04-15; `docker/setup-buildx-action@v4` + `build-push-action@v7` are past that line `[CITED: github.com/moby/buildkit issue 5896; dash0.com/faq/cache-docker-images-github-actions]`.
- `if: ${{ secrets.X != '' }}` at **step** level works; `secrets` is **not** available in job-level `if:` — put the guard on steps (or promote to an `environment`). Getting this backwards is a common failure.

**Action versions confirmed on 2026-09-05** (latest release tag + date):

```
actions/checkout          v7.0.1  2026-07-20      docker/login-action        v4.6.0  2026-07-29
actions/setup-node        v7.0.0  2026-07-14      docker/build-push-action   v7.3.0  2026-07-01
actions/cache             v6.1.0  2026-06-26      docker/metadata-action     v6.2.0  2026-07-02
actions/upload-artifact   v7.0.1  2026-04-10      docker/setup-buildx-action v4.3.0  2026-08-19
astral-sh/setup-uv       v10.0.1  2026-08-14      hashicorp/setup-terraform  v4.0.1  2026-05-12
google-github-actions/auth   v3   2025-09-03
```

The current `.github/workflows/lint.yml` pins `actions/checkout@v4` and `astral-sh/setup-uv@v3` — both several majors stale. Bumping them is part of the `ci.yml` replacement.

---

## State of the Art

| Old approach | Current approach | When changed | Impact on this phase |
|---|---|---|---|
| `bitnami/kafka` for local Kafka | `apache/kafka` official image | Bitnami withdrew its free catalogue mid-2025; `bitnamilegacy` is frozen | Pitfall 5 — recommend the swap. |
| `actions/cache` + `/tmp/.buildx-cache` | `cache-from/to: type=gha,mode=max` | buildx 0.21 / GHA cache v2 (v1 shut down 2025-04-15) | One line in `cd.yml`. |
| `uv` `bookworm` image variants | `trixie` variants | uv ≥ ~0.10 | `0.11.7-python3.12-bookworm-slim` 404s; use `COPY --from=ghcr.io/astral-sh/uv:0.11.7`. |
| `python:3.12-slim` = Debian bookworm | Debian **13 trixie** | Debian 13 release, 2025 | Pin by digest or accept the churn (Pitfall 8). |
| Grafana 10/11 dashboard JSON | schemaVersion 39 accepted by Grafana 13.2.1 | ongoing | Verified compatible; no migration needed. |
| Prometheus 2.x | Prometheus **3.x** (3.14.0) | Prometheus 3.0, late 2024 | Config format unchanged for our use; `promtool` behaviour identical. |
| `pytest-asyncio` implicit event loops | explicit `loop_scope=` | pytest-asyncio 0.24 → 1.x | Pitfall 10; the old module-scope idiom hangs. |
| Next.js `next start` in a full node_modules image | `output: 'standalone'` | Next 12+, standard since 13 | 340 MB vs ~1 GB. |

**Deprecated/outdated in this repo today:**
- `.github/workflows/lint.yml` — superseded by `ci.yml` (D-121); `checkout@v4`, `setup-uv@v3`.
- `docs/PHASE-01-HUMAN-ACTIONS.md` — superseded by `docs/HUMAN-ACTIONS.md` (D-126).
- `README.md:306` claim that "the compose stack … uses `bitnami/kafka`" — already wrong (it uses `bitnamilegacy`), and will be wrong again after the swap.
- `.planning/research/ARCHITECTURE.md:494` says "Cloud SQL for Postgres+Timescale"; `REQUIREMENTS.md:81` (DEPLOY-01) says self-hosted TimescaleDB on GCE **because Cloud SQL does not support the extension**. REQUIREMENTS is authoritative — `docs/deploy/gcp.md` must follow REQUIREMENTS, not ARCHITECTURE.

---

## Runtime State Inventory

Phase 7 is additive, not a rename/refactor — but it **changes the Kafka image**, which is a data-shaped migration. Included for that reason.

| Category | Items found | Action required |
|----------|-------------|-----------------|
| Stored data | Docker volume `mise_kafka-data` currently mounted at `/bitnami/kafka` (`ops/docker-compose.yml:29`). `apache/kafka` expects `/var/lib/kafka/data`. The KRaft metadata log is not portable between the two layouts. | Data migration: `docker compose -f ops/docker-compose.yml down -v` (or `docker volume rm mise_kafka-data`) then `make up topics migrate seed`. Must be a documented step in the plan and in `CONTRIBUTING.md`; dev topics/offsets are throwaway. |
| Live service config | None. There is no external SaaS holding config for this phase yet: Sentry project, Better Uptime monitors, Grafana Cloud, Vercel env vars, and the GCP project are all **pending-human** and have no existing state to migrate. | None — record each in `docs/HUMAN-ACTIONS.md`. |
| OS-registered state | None — verified: no launchd/systemd/Task Scheduler artefacts in the repo, and `.planning` records no host-level registration for this project. | None. |
| Secrets / env vars | New keys only, all absent today: `SENTRY_DSN`, `GHCR_OWNER`, `MISE_TAG`, `GRAFANA_PORT`, `PROMETHEUS_PORT`, `BETTERUPTIME_API_TOKEN`. Existing `.env.example` already has `GCP_PROJECT_ID`. New CI secrets `GCP_PROJECT_ID` / `GCP_WORKLOAD_IDENTITY_PROVIDER` are referenced but optional by design (D-120). | Code + `.env.example` additions; no rename of an existing key. |
| Build artifacts | `.venv/` at the repo root (host dev env) is unrelated to the images. `web/node_modules` and `web/.next` must be in `.dockerignore` or the build context balloons and `npm ci` is defeated. Local scratch images `mise-{sm,poller,web}-test:scratch` exist on this machine from this research and are disposable. | Add/verify `.dockerignore` at the repo root (`.venv`, `__pycache__`, `.git`, `web/node_modules`, `web/.next`, `.planning`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`). Without it the Python build context includes the 400 MB+ `.venv`. |

---

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|------------|-------------|-----------|---------|----------|
| Docker + Compose v2 | image builds, compose profiles, smoke | ✓ | Engine 29.4.0, Compose v5.1.2 | — |
| Node + npm | `web` build, mermaid-cli | ✓ | Node v22.14.0, npm 10.9.2 | — |
| uv | all Python work | ✓ | 0.11.7 | — |
| Playwright Chromium (host) | e2e smoke, mermaid render | ✓ | `chromium-1208` + `chromium-1223` in `~/Library/Caches/ms-playwright` | `uv run playwright install chromium` |
| **Terraform** | `terraform validate` gate | ✓ | **1.13.0** (latest is 1.16.1 — fine; skeleton needs ≥ 1.9) | — |
| `gh` CLI | optional CI inspection | ✓ | 2.92.0 | — |
| `promtool` | Prometheus config/PromQL gates | ✓ (in-container) | via `prom/prometheus:v3.14.0` | — |
| `mmdc` on PATH | diagram render | ✗ | — | `npx -y @mermaid-js/mermaid-cli@11.17.0` (verified working) |
| GCP project / credentials | `terraform apply`, Cloud Run deploy | ✗ | — | **pending-human** — D-119 explicitly builds around this |
| Sentry DSN | live error capture | ✗ | — | env-driven no-op verified; unit test covers the unset path |
| Better Uptime account | PERF-04 monthly measurement | ✗ | — | Prometheus `up` arm of `uptime_report.py` |
| GHCR push credentials | `cd.yml` | ✗ locally (CI-only via `GITHUB_TOKEN`) | — | none needed locally; `make images` builds without pushing |

**Missing dependencies with no fallback:** none that block Phase 7 as scoped by D-119.
**Missing dependencies with fallback:** `mmdc` (use `npx`), Sentry DSN (no-op), Better Uptime (Prometheus arm), GCP (docs + unapplied skeleton).

---

## Blocking Corrections to Locked Decisions

**None.** Every decision D-119 through D-127 was executed or prototyped here and none failed to run as written. Specifically:

- D-119's Playwright base **does** ship a conforming Python (3.12.3) — no `uv python install 3.12` workaround needed.
- D-119's `terraform validate` **does** pass without credentials (so does `terraform plan`).
- D-121's `docker compose --profile prod --profile monitoring up -d --wait` shape works and returns a correct exit code.
- D-123's anonymous Grafana Viewer serving `/d/mise` works end-to-end, including the datasource query path panels need.
- D-124's `init_sentry()` no-op-without-DSN works exactly as described (zero threads).
- D-125's mermaid render works headlessly here in 1.4 s.

Four **non-blocking implementation constraints** the plan must absorb (each is a *how*, not a *whether*), fully documented above: the Sentry↔structlog processor ordering (Pitfalls 1–2), `sse_connections_active` must be a `Gauge` (Pitfall 3), the `aiokafka` lag recipe (Pattern 7), and the Kafka image swap's four-part blast radius (Pitfall 5).

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"`), `pyproject.toml:44-53` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `pythonpath = ["."]`) |
| Quick run command | `uv run pytest tests/unit -x -q -W error::RuntimeWarning` (`make test`) |
| Full suite command | `uv run pytest tests/unit tests/integration -q` then `uv run pytest tests/e2e -q -m e2e` |
| Frontend | Vitest in `web/` (Phase 6 D-109/D-118) — `npm test`; Phase 7 only adds the CI job |
| Markers | `integration` declared today; **`e2e` must be added** to `pyproject.toml:50-52` (Wave 0) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test type | Automated command | File exists? |
|--------|----------|-----------|-------------------|--------------|
| DEPLOY-01 | Four Dockerfiles exist, pin their bases, run non-root, declare a HEALTHCHECK | unit (static) | `uv run pytest tests/unit/test_dockerfiles_hardened.py -q` | ❌ Wave 0 |
| DEPLOY-01 | Every compose image pinned; `prod`+`monitoring` profiles parse | unit | `uv run pytest tests/unit/test_compose_images_are_pinned.py tests/unit/test_compose_profiles.py -q` | partial (`test_compose_images_are_pinned.py` ✅; profiles ❌) |
| DEPLOY-01 | `prod`+`monitoring` stack reaches healthy | e2e (CI smoke) | `docker compose -f ops/docker-compose.yml --profile prod --profile monitoring up -d --wait --wait-timeout 600` | ❌ Wave 0 (CI step, not a pytest file) |
| DEPLOY-02 | Terraform skeleton is formatted, initialises and validates offline | unit-ish (CI step) | `terraform -chdir=terraform fmt -check -recursive && terraform -chdir=terraform init -backend=false && terraform -chdir=terraform validate` | ❌ Wave 0 |
| DEPLOY-02 | Every `terraform/**/*.tf` carries the `STATUS: pending-human — not applied` banner | unit (grep gate) | `uv run pytest tests/unit/test_terraform_pending_human_banner.py -q` | ❌ Wave 0 |
| DEPLOY-03 | `ci.yml` retains all three ban greps and the mypy target set | unit (grep gate) | `uv run pytest tests/unit/test_ci_workflow_gates.py -q` | ❌ Wave 0 |
| DEPLOY-03 | Playwright smoke drives replay → event → notification through the UI | e2e | `uv run pytest tests/e2e -q -m e2e -p no:cacheprovider` | ❌ Wave 0 |
| DEPLOY-04 | `post_deploy_check` decision logic (lag → 0 in 2 min, polls in 3 min, unknown group ≠ 0) | unit | `uv run pytest tests/unit/test_post_deploy_check.py -q` | ❌ Wave 0 |
| DEPLOY-04 | `post_deploy_check` reads real broker lag | integration | `uv run pytest tests/integration/test_post_deploy_check_lag.py -q` | ❌ Wave 0 |
| DEPLOY-04 | `cd.yml` tags `sha-<short>` + `main`, declares `packages: write`, needs no external secret | unit (grep gate) | `uv run pytest tests/unit/test_cd_workflow.py -q` | ❌ Wave 0 |
| DEPLOY-05 | `shared/metrics.py` declares the seven names with the right types (`sse_connections_active` is a Gauge) | unit | `uv run pytest tests/unit/test_metrics_registry.py -q` | ❌ Wave 0 |
| DEPLOY-05 | Dashboard JSON has the five panel titles and every PromQL metric name exists in `shared/metrics.py` or is an exporter name | unit (drift guard) | `uv run pytest tests/unit/test_dashboard_drift.py -q` | ❌ Wave 0 |
| DEPLOY-05 | `prometheus.yml` parses and lists a job per service | unit | `uv run pytest tests/unit/test_prometheus_config.py -q` | ❌ Wave 0 |
| DEPLOY-05 | PromQL in `rules/mise.rules.yml` parses | CI step | `docker run --rm --entrypoint promtool -v "$PWD/ops/prometheus:/cfg:ro" prom/prometheus:v3.14.0 check rules /cfg/rules/mise.rules.yml` | ❌ Wave 0 |
| DEPLOY-05 | Prometheus reports `up == 1` for all service jobs; Grafana serves `/api/dashboards/uid/mise` anonymously | integration (against the compose stack) | `uv run pytest tests/integration/test_monitoring_stack.py -q` | ❌ Wave 0 |
| DEPLOY-06 | `init_sentry()` is a no-op without a DSN (client inactive, zero threads) | unit | `uv run pytest tests/unit/test_init_sentry_noop.py -q` | ❌ Wave 0 |
| DEPLOY-06 | The structlog processor produces one Sentry event per ERROR with a stable fingerprint, a real exception for `log.exception`, and scrubbed extras | unit (in-memory transport) | `uv run pytest tests/unit/test_sentry_structlog_bridge.py -q` | ❌ Wave 0 |
| DEPLOY-07 | README has no "Coming Soon" outside the legal footer and no stale test counts | unit (grep gate) | `uv run pytest tests/unit/test_readme_status_guard.py -q` | ❌ Wave 0 |
| DEPLOY-07 | `docs/status.json` regenerates identically from the current tree (no drift) | unit | `uv run pytest tests/unit/test_status_report.py -q` | ❌ Wave 0 |
| DEPLOY-07 | `docs/architecture.mmd` parses and the committed SVG is non-empty | unit (light) | `uv run pytest tests/unit/test_architecture_diagram.py -q` | ❌ Wave 0 |
| PERF-04 | `uptime_report` math: ≥ 99.5 % → 0, below → 1, insufficient samples → 2 | unit | `uv run pytest tests/unit/test_uptime_report.py -q` | ❌ Wave 0 |
| PERF-04 | `uptime_report --mode compose` reads Prometheus `up` samples | integration | `uv run pytest tests/integration/test_uptime_report_prometheus.py -q` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `uv run pytest tests/unit -x -q -W error::RuntimeWarning` (`make test`) — seconds.
- **Per wave merge:** `make lint && uv run pytest tests/unit tests/integration -q` plus `docker compose … config -q` and both `promtool` checks.
- **Phase gate:** the full CI matrix green (`lint`, `unit`, `integration`, `web`, `ops-config`, `smoke`), `make images` succeeding at least once locally (D-127), and `terraform validate` exit 0, before `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] Register the `e2e` marker in `pyproject.toml` `[tool.pytest.ini_options].markers`
- [ ] `tests/e2e/__init__.py` + `tests/e2e/conftest.py` (module-scoped browser using `loop_scope="module"` — Pattern 6) — covers DEPLOY-03
- [ ] `tests/e2e/test_smoke.py` — covers DEPLOY-03
- [ ] `tests/unit/test_dockerfiles_hardened.py` — DEPLOY-01
- [ ] `tests/unit/test_compose_profiles.py` — DEPLOY-01
- [ ] `tests/unit/test_metrics_registry.py` — DEPLOY-05
- [ ] `tests/unit/test_dashboard_drift.py` — DEPLOY-05
- [ ] `tests/unit/test_prometheus_config.py` — DEPLOY-05
- [ ] `tests/unit/test_init_sentry_noop.py`, `tests/unit/test_sentry_structlog_bridge.py` — DEPLOY-06
- [ ] `tests/unit/test_post_deploy_check.py`, `tests/unit/test_uptime_report.py` — DEPLOY-04, PERF-04
- [ ] `tests/unit/test_ci_workflow_gates.py`, `tests/unit/test_cd_workflow.py` — DEPLOY-03/04
- [ ] `tests/unit/test_readme_status_guard.py`, `tests/unit/test_status_report.py`, `tests/unit/test_architecture_diagram.py` — DEPLOY-07
- [ ] `tests/unit/test_terraform_pending_human_banner.py` — DEPLOY-02
- [ ] `tests/integration/test_monitoring_stack.py`, `test_post_deploy_check_lag.py`, `test_uptime_report_prometheus.py`
- [ ] Root `.dockerignore` (not a test, but every image build depends on it)
- [ ] `web/src/app/healthz/route.ts` (Phase 6 does not create it; the compose healthcheck needs it)
- [ ] Framework install: none — pytest/pytest-asyncio/testcontainers are already in `[dependency-groups].dev`

---

## Security Domain

`security_enforcement` is not set to `false` anywhere in `.planning/config.json`, so it is enabled.

### Applicable ASVS categories

| ASVS category | Applies | Standard control |
|---------------|---------|------------------|
| V2 Authentication | partly | Grafana anonymous **Viewer** is deliberate and read-only (D-123); `GF_AUTH_BASIC_ENABLED=false` was verified to still permit anonymous read. Bind the port to `127.0.0.1`. Admin API routes stay HTTP-Basic (Phase 5 D-102). |
| V3 Session Management | no | Phase 7 introduces no sessions. |
| V4 Access Control | yes | `packages: write` is the **only** elevated permission in `cd.yml`; the top-level default must be `permissions: {contents: read}`. `deploy-prod` is `workflow_dispatch`-only and secret-gated. |
| V5 Input Validation | yes | `post_deploy_check.py` / `uptime_report.py` parse broker and Prometheus responses — treat both as untrusted; never `eval` a PromQL response; bound the `--window` argument. |
| V6 Cryptography | no | No new crypto. Existing HMAC/AES paths untouched. |
| V7 Error Handling & Logging | **yes — the crux of this phase** | `send_default_pii=False`; `before_send` must strip `cookie`/`authorization` **and** `extra["sys.argv"]` (the SDK adds argv automatically — observed). The existing `_redact_secrets` structlog processor (`shared/telemetry.py:88-104`) already blanks `TWILIO_AUTH_TOKEN`, `HMAC_MGMT_SECRET_V1`, `VAPID_PRIVATE_KEY`, `RESY_ACCOUNTS_JSON`; the Sentry processor must run **after** it so scrubbed values never reach Sentry. |
| V14 Configuration | yes | Non-root users in all five images (verified `uid=1001` in three of them). No secrets in image layers — `.env` is mounted via `env_file`, never `COPY`ed. `.dockerignore` must exclude `.env`. |

### Known threat patterns for this stack

| Pattern | STRIDE | Standard mitigation |
|---|---|---|
| Secrets baked into an image layer | Information disclosure | `env_file` + `.dockerignore` for `.env`; never `COPY .env`; `docker history` spot-check in the hardening test. |
| Sentry exfiltrating booking tokens / phone numbers | Information disclosure | `send_default_pii=False` + `before_send` + processor ordering after `_redact_secrets`; `safe_error()` (`shared/telemetry.py:52-79`) already strips SQL params and Postgres `DETAIL:` lines. |
| Anonymous Grafana leaking internal topology | Information disclosure | Verified: `/api/datasources` returns `http://prometheus:9090` to anonymous clients. Bind `127.0.0.1:3001:3000`; public hosting is Grafana Cloud, pending-human. |
| Slopsquatted / trojaned build-time package | Tampering | `uv sync --frozen` against a committed `uv.lock`; `npm ci` against a committed lockfile; `PUPPETEER_SKIP_DOWNLOAD=1` to stop an install-time binary download. |
| Over-privileged `GITHUB_TOKEN` | Elevation of privilege | Job-scoped `permissions:`; `contents: read` by default, `packages: write` only on `build-push`. |
| Unsandboxed Chromium in the poller | Elevation of privilege | Verified that `--no-sandbox` is **not** required — do not add it. |
| Metric cardinality blow-up as a DoS on Prometheus | DoS | `should_ignore_untemplated=True` (verified) and the D-122 label sets; no `restaurant_id`/`date` labels (PITFALLS.md:351-353). |
| Compose smoke job leaking secrets into CI logs | Information disclosure | The smoke job copies `.env.example` (placeholders only), never a real `.env`; upload `compose.log` as an artifact rather than echoing it. |

---

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | Phases 3–6 will have produced `shared/metrics.py` (Phase 3 D-69), `services/notifier/` with `NOTIFY_DRY_RUN` (Phase 4 D-80), `services/api/` with `/api/metrics` + `/readyz` (Phase 5 D-101/D-97), and `web/` with `next build` clean (Phase 6 D-109) **before Phase 7 executes**. `STATE.md` currently reads `current_phase: 3, status: executing`, and none of those files exist in the tree today (`shared/` has no `metrics.py`; there is no `services/notifier/`, `services/api/`, or `web/`). | throughout | High. Every Dockerfile, Prometheus job, dashboard panel, and smoke assertion in this phase targets an artefact that does not exist yet. Phase 7 plans must declare these as hard upstream dependencies and must not be executed out of order. |
| A2 | GitHub-hosted `ubuntu-latest` runners can build the 4.59 GB poller image and push ~1 GB of new base layers to GHCR inside the job timeout. Not measured — no CI run was performed from this machine. Compressed base is 0.96 GB in 4 layers, which makes it plausible, and subsequent pushes only move the ~120 MB venv/source layers. | Pitfall 7, `cd.yml` | Medium. If the first CD run times out, split the poller into its own job with a raised `timeout-minutes`, or pre-warm with `cache-from: type=gha`. |

Everything else in this document is `[VERIFIED]` by an executed command whose output is quoted, or `[CITED]` to an official source named inline.

---

## Open Questions

1. **Does the smoke job need the poller image at all?**
   - What we know: the D-121 smoke path injects raw messages with `scripts/replay_raw.py --input` and asserts on the feed and `notification_log`. The poller is never exercised. The poller image is 4.59 GB and dominates the job.
   - What's unclear: whether D-119's single `prod` profile is meant to be indivisible.
   - **Recommendation:** give the poller `profiles: [prod, poller]` and let the smoke job run `--profile smoke --profile monitoring`, where `smoke` covers `state_machine`, `notifier`, `api`, `web`. Keep `make up-prod` on `--profile prod` so the human-facing command is unchanged. If the planner prefers strict D-119 fidelity, keep one profile and set `timeout-minutes: 45` with `cache-to: type=gha,mode=max`.

2. **Swap the Kafka image now, or keep `bitnamilegacy` in the `prod` profile?**
   - What we know: `bitnamilegacy` is vendor-declared "no longer updated" (last push 2025-07-18); `apache/kafka:3.8.1` boots healthy with the exact env block given above. 02-CONTEXT D-56 explicitly says "Phase 7 may move to an official image with its production profile."
   - What's unclear: whether the volume reset is acceptable mid-project (other agents are running Phase 3 against the current stack).
   - **Recommendation:** swap, as a **single late task** in the phase with `docker compose down -v` documented, sequenced after Phase 3's soak work is done. Running two different brokers across profiles would be worse than either choice alone.

3. **Should `/api/metrics` appear in the OpenAPI snapshot?**
   - What we know: `include_in_schema=False` keeps it out (verified); Phase 5 D-104 pins the public route list in `tests/unit/test_openapi_snapshot.py`; D-101 calls it a public route.
   - **Recommendation:** `include_in_schema=False`, and add an explicit live assertion (`/api/metrics` returns 200 and contains `sse_connections_active`) to the monitoring integration test. A scrape endpoint in a client-facing schema is noise, and flipping it would churn the Phase 5 snapshot.

4. **Prometheus retention vs the PERF-04 30-day window.**
   - What we know: `--storage.tsdb.retention.time=15d` cannot answer `avg_over_time(up[30d])`.
   - **Recommendation:** set `35d` retention in the compose `monitoring` profile (cheap at this cardinality) and make `uptime_report.py` report the actual sample coverage, exiting 2 when coverage is short of the requested window rather than reporting a falsely-high number.

5. **Where does the mermaid render run?**
   - What we know: it works locally in 1.4 s with the existing Playwright Chromium; in CI it needs either the Playwright browser installed in that job or a puppeteer Chrome download.
   - **Recommendation:** commit both `.mmd` and `.svg`; `make docs` regenerates via `scripts/render_diagram.py`; CI re-renders and `git diff --exit-code`s **only** in the `integration` job (which already runs `playwright install chromium`), not in `lint`.

6. **Pin `python:3.12-slim` by digest?**
   - What we know: the tag silently moved from bookworm to trixie.
   - **Recommendation:** pin by digest in `ops/docker/*.Dockerfile` with a comment recording the human-readable version, and extend `test_compose_images_are_pinned.py` to also assert no `FROM …:latest` in `ops/docker/*.Dockerfile`. Renovate/Dependabot can bump the digest later.

7. **`shared/metrics.py` ownership between Phase 3 and Phase 7.**
   - What we know: Phase 3 D-69 creates it with six poller metrics; Phase 7 D-122 fixes seven names including notifier and SSE metrics that Phases 4/5 add.
   - **Recommendation:** Phase 7 *extends* rather than rewrites, and the drift-guard test reads the module's public names by import (not by regex) so it stays correct however the file was assembled.

---

## Sources

### Primary (HIGH confidence — executed on this machine, 2026-09-05)

- `docker run` / `docker build` / `docker compose up --wait` against: `mcr.microsoft.com/playwright/python:v1.58.0-noble`, `python:3.12-slim`, `node:22-alpine`, `apache/kafka:3.8.1`, `prom/prometheus:v3.14.0`, `grafana/grafana:13.2.1`, `danielqsj/kafka-exporter:v1.9.0`, `oliver006/redis_exporter:v1.90.0`, `redis:7.2-alpine`.
- `uv run python` against the repo's own environment for: `prometheus_client` server + naming, `prometheus-fastapi-instrumentator` 7.1.0, `aiokafka` 0.13.0 admin API, `playwright.sync_api.executable_path`, pytest-asyncio fixture scoping.
- Isolated venv with `sentry-sdk[fastapi]==2.68.1` + `structlog` reproducing and then fixing both Sentry defects.
- `terraform fmt/init/validate/plan` 1.13.0 with `hashicorp/google` 7.46.1.
- `promtool check config` / `check rules` (positive and negative controls).
- `npx @mermaid-js/mermaid-cli@11.17.0` producing a 71 KB SVG.
- Registry APIs: `mcr.microsoft.com/v2/playwright/python/tags/list`, `ghcr.io/v2/astral-sh/uv/tags/list` (paginated, 7,597 tags), `hub.docker.com/v2/repositories/{prom/prometheus,grafana/grafana,danielqsj/kafka-exporter,oliver006/redis_exporter,apache/kafka,bitnamilegacy/kafka}`, `pypi.org/pypi/{sentry-sdk,prometheus-client,prometheus-fastapi-instrumentator,uv}/json`, `api.github.com/repos/*/releases/latest`, `npm view`.
- Repo files read this session: `ops/docker-compose.yml`, `Makefile`, `.github/workflows/lint.yml`, `pyproject.toml`, `uv.lock` (header), `CLAUDE.md`, `.env.example`, `shared/telemetry.py`, `services/poller/main.py`, `services/state_machine/main.py`, `tests/conftest.py`, `tests/integration/conftest.py`, `tests/unit/test_compose_images_are_pinned.py`, `scripts/check_poll_success.py`, `scripts/replay_raw.py` (CLI surface), `README.md`, `.planning/{REQUIREMENTS,ROADMAP,STATE,PROJECT,config.json}`, `.planning/research/{ARCHITECTURE,PITFALLS}.md`, `.planning/phases/0{3,4,5,6,7}-*/*-CONTEXT.md`.

### Secondary (MEDIUM confidence — official docs)

- `github.com/docker/metadata-action` README — automatic image-name lowercasing, `type=sha` → `sha-<7>`, `type=ref,event=branch`.
- `docs.docker.com/build/ci/github-actions/push-multi-registries/` — `docker/login-action@v4` to `ghcr.io` with `secrets.GITHUB_TOKEN`.

### Tertiary (LOW confidence — community, cross-checked but not executed)

- `github.com/moby/buildkit` issue 5896 and `dash0.com/faq/cache-docker-images-github-actions` — GHA cache service v2 minimums (Buildx 0.21 / BuildKit 0.20 / Compose 2.33.1) and the 2025-04-15 v1 shutdown. Used only to justify pinning `setup-buildx-action@v4`; not load-bearing.

---

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — every image pulled and run; every package version read from its registry today.
- Architecture / patterns: **HIGH** — all six container/compose/Terraform/e2e patterns were executed, not sketched.
- Pitfalls: **HIGH** — nine of ten were reproduced with quoted output; Pitfall 8 (moving base tag) is an observation about tag drift, cross-checked against the running image.
- CI/CD workflow YAML: **MEDIUM** — action versions and semantics are verified from release APIs and official docs, but the workflows themselves were not executed on GitHub (assumption A2).
- Cloud/GCP topology and Better Uptime: **LOW by design** — pending-human per D-119, documented rather than verified.

**Research date:** 2026-09-05
**Valid until:** 2026-10-05 for the pinned images/packages (Grafana, Prometheus, and the GitHub Actions all release monthly — re-check tags if planning slips past this). The behavioural findings (Sentry/structlog, aiokafka lag, compose `--wait` semantics, pytest-asyncio scoping, Next standalone layout) are version-pinned and stable.
