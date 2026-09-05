---
phase: 07
slug: deploy-observability-portfolio-polish
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-09-05
---

# Phase 07 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"`); Vitest in `web/` (Phase 6) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `pythonpath = ["."]`; the `e2e` marker is registered by 07-07 Task 2 |
| **Quick run command** | `uv run pytest tests/unit -x -q -W error::RuntimeWarning` (`make test`) |
| **Full suite command** | `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` then `make smoke` (compose `--profile smoke --profile monitoring` + `scripts/post_deploy_check.py` + `uv run pytest tests/e2e -q -m e2e`) |
| **Static/offline gates** | `uv run ruff check .`; `uv run mypy shared/ services/ scripts/`; the three ban greps; `docker compose --profile prod --profile monitoring config -q`; `promtool check config` + `check rules`; `terraform fmt -check -recursive` + `init -backend=false` + `validate` |
| **Estimated runtime** | quick ~20 s · integration ~4 min · full smoke ~10-15 min |

---

## Sampling Rate

- **After every task commit:** `uv run pytest tests/unit -x -q -W error::RuntimeWarning`
- **After every plan wave:** `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` plus the wave's static gates (compose `config -q` after waves 2-3, `promtool` after wave 3, `terraform validate` after wave 3, `make smoke` after wave 5)
- **Before `/gsd-verify-work`:** the full suite green, `make images` succeeding at least once (D-127), `make smoke` green, and `terraform validate` exit 0
- **Max feedback latency:** 20 seconds at the unit tier

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 07-01-01 | 01 | 1 | DEPLOY-01 | T-07-01 | `.env` and the host venv cannot enter a build context | unit | `uv run pytest tests/unit/test_phase7_preconditions.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-01-02 | 01 | 1 | DEPLOY-01 | T-07-02 | image runs as uid 1001, not root | build | `docker build -f ops/docker/state_machine.Dockerfile -t mise-state-machine:tracer . && docker run --rm --entrypoint sh mise-state-machine:tracer -c 'test "$(id -u)" = 1001'` | ❌ W0 | ⬜ pending |
| 07-01-03 | 01 | 1 | DEPLOY-01 | T-07-03 / T-07-04 | Chromium sandbox intact; every base pinned | unit + build | `uv run pytest tests/unit/test_dockerfiles_hardened.py -q -W error::RuntimeWarning && make images` | ❌ W0 | ⬜ pending |
| 07-02-01 | 02 | 2 | DEPLOY-01 | — | web container non-root, health-probeable | build | `docker build -f ops/docker/web.Dockerfile -t mise-web:tracer web/ && curl -fsS http://127.0.0.1:3010/healthz` | ❌ W0 | ⬜ pending |
| 07-02-02 | 02 | 2 | DEPLOY-01 | T-07-05 / T-07-06 | secrets only via `env_file`; poller `/dev/shm` sized | unit | `uv run pytest tests/unit/test_compose_profiles.py tests/unit/test_compose_images_are_pinned.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-02-03 | 02 | 2 | DEPLOY-01 | T-07-07 / T-07-08 | maintained broker image; no auto-topic creation | integration | `docker compose -f ops/docker-compose.yml up -d kafka --wait --wait-timeout 120 && docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092 --list` | ✅ | ⬜ pending |
| 07-03-01 | 03 | 2 | DEPLOY-05 | T-07-11 | bounded metric label sets; gauge/counter contract | unit | `uv run pytest tests/unit/test_metrics_exposition.py tests/unit/test_metrics_registry.py -q -W error::RuntimeWarning` | partial | ⬜ pending |
| 07-03-02 | 03 | 2 | DEPLOY-06 | T-07-09 / T-07-12 / T-07-SC | no secret reaches Sentry; bounded shutdown flush | unit | `uv run pytest tests/unit/test_init_sentry_noop.py tests/unit/test_sentry_structlog_bridge.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-03-03 | 03 | 2 | DEPLOY-05, DEPLOY-06 | T-07-10 | `/api/metrics` public by design, absent from OpenAPI | unit | `uv run pytest tests/unit/test_services_observability_wiring.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-04-01 | 04 | 3 | DEPLOY-05 | T-07-13 | Grafana bound to loopback; anonymous read only | integration | `make up-monitoring && curl -fsS 'http://127.0.0.1:9090/api/v1/query?query=up%7Bjob%3D%22state_machine%22%7D' \| grep -q '"value"'` | ❌ W0 | ⬜ pending |
| 07-04-02 | 04 | 3 | DEPLOY-05 | T-07-16 | offline config + PromQL validation | unit | `uv run pytest tests/unit/test_prometheus_config.py tests/unit/test_promtool_gates.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-04-03 | 04 | 3 | DEPLOY-05 | T-07-14 / T-07-15 | dashboard file is source of truth; no drift | unit + integration | `uv run pytest tests/unit/test_dashboard_drift.py -q && uv run pytest tests/integration/test_monitoring_stack.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 07-05-01 | 05 | 3 | DEPLOY-02 | T-07-18 / T-07-19 | never applied; state never committed | static | `terraform -chdir=terraform fmt -check -recursive && terraform -chdir=terraform init -backend=false -input=false && terraform -chdir=terraform validate` | ❌ W0 | ⬜ pending |
| 07-05-02 | 05 | 3 | DEPLOY-02 | T-07-18 / T-07-SC | no `resource` blocks; provider pinned by lock | unit | `uv run pytest tests/unit/test_pending_human_banners.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-05-03 | 05 | 3 | DEPLOY-02, DEPLOY-06 | T-07-17 / T-07-20 | no personal data in consolidated docs | unit | `uv run pytest tests/unit/test_pending_human_banners.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-06-01 | 06 | 4 | DEPLOY-04 | T-07-22 | never-committed ≠ lag 0; no silent zero | unit + integration | `uv run pytest tests/unit/test_post_deploy_check.py -q && uv run pytest tests/integration/test_post_deploy_check_lag.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 07-06-02 | 06 | 4 | DEPLOY-04 | T-07-22 / T-07-24 | insufficient data is never success; bounded loops | unit | `uv run pytest tests/unit/test_post_deploy_check.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-06-03 | 06 | 4 | PERF-04 | T-07-21 / T-07-23 | `--window` validated before it reaches PromQL | unit + integration | `uv run pytest tests/unit/test_uptime_report.py -q && uv run pytest tests/integration/test_uptime_report_prometheus.py -q -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 07-07-01 | 07 | 5 | DEPLOY-03 | T-07-SC | the three ban greps survive verbatim | unit | `uv run pytest tests/unit/test_ci_workflow_gates.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-07-02 | 07 | 5 | DEPLOY-03 | T-07-27 | CI uses `.env.example` placeholders only | e2e | `uv run pytest tests/e2e -q -m e2e -p no:cacheprovider` | ❌ W0 | ⬜ pending |
| 07-07-03 | 07 | 5 | DEPLOY-03, DEPLOY-04 | T-07-25 / T-07-26 / T-07-28 / T-07-29 | least-privilege token; no swallowed failures | unit | `uv run pytest tests/unit/test_ci_workflow_gates.py tests/unit/test_cd_workflow.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-08-01 | 08 | 6 | DEPLOY-07 | T-07-31 | generated block is idempotent and owned | unit | `uv run python scripts/status_report.py --check && uv run pytest tests/unit/test_status_report.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-08-02 | 08 | 6 | DEPLOY-07 | T-07-SC | no install-time browser download | unit | `uv run pytest tests/unit/test_architecture_diagram.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |
| 07-08-03 | 08 | 6 | DEPLOY-07 | T-07-30 / T-07-32 | no unqualified hosted-capability claim | unit | `uv run pytest tests/unit/test_readme_status_guard.py -q -W error::RuntimeWarning` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 is Task 1 of plan 07-01 plus the per-plan test scaffolds each task creates before its
implementation. The precondition gate is the halt mechanism for assumption A1.

- [ ] `tests/unit/test_phase7_preconditions.py` — the A1 halt gate (Phase 3/4/5/6 artifacts, single alembic head)
- [ ] `.dockerignore` (repo root) — every image build depends on it
- [ ] `pyproject.toml` — register the `e2e` marker beside `integration` (07-07 Task 2)
- [ ] `tests/e2e/{__init__.py,conftest.py,test_smoke.py}` — module-scoped browser using `loop_scope="module"`; the plain `@pytest.fixture(scope="module")` async generator hangs
- [ ] `tests/unit/test_dockerfiles_hardened.py` — DEPLOY-01
- [ ] `tests/unit/test_compose_profiles.py` — DEPLOY-01
- [ ] `tests/unit/test_metrics_exposition.py` — DEPLOY-05
- [ ] `tests/unit/test_init_sentry_noop.py`, `tests/unit/test_sentry_structlog_bridge.py` — DEPLOY-06
- [ ] `tests/unit/test_services_observability_wiring.py` — DEPLOY-05/06
- [ ] `tests/unit/test_prometheus_config.py`, `tests/unit/test_promtool_gates.py`, `tests/unit/test_dashboard_drift.py` — DEPLOY-05
- [ ] `tests/unit/test_pending_human_banners.py` — DEPLOY-02/06
- [ ] `tests/unit/test_post_deploy_check.py`, `tests/unit/test_uptime_report.py` — DEPLOY-04, PERF-04
- [ ] `tests/unit/test_ci_workflow_gates.py`, `tests/unit/test_cd_workflow.py` — DEPLOY-03/04
- [ ] `tests/unit/test_status_report.py`, `tests/unit/test_readme_status_guard.py`, `tests/unit/test_architecture_diagram.py` — DEPLOY-07
- [ ] `tests/integration/test_monitoring_stack.py`, `tests/integration/test_post_deploy_check_lag.py`, `tests/integration/test_uptime_report_prometheus.py`
- [ ] `web/src/app/healthz/route.ts` — Phase 6 defines no health route; the compose healthcheck needs one
- [ ] Framework install: none — pytest, pytest-asyncio and testcontainers are already in `[dependency-groups].dev`

---

## Manual-Only Verifications

Every item below is human-gated and consolidated in `docs/HUMAN-ACTIONS.md` (07-05). None of them may be
claimed as done in the README (07-08) while its runbook still carries a `pending-human` banner.

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| GCP project provisioning and `terraform apply` | DEPLOY-01, DEPLOY-02 | Creates billable cloud resources; needs an account and billing | `docs/deploy/gcp.md` — follow the `gcloud` sequence, then `terraform -chdir=terraform apply` once the module stubs are implemented |
| `mise.place` domain + DNS | DEPLOY-01, NOTIF-* | Domain purchase and DNS delegation | `docs/HUMAN-ACTIONS.md` §domain; `docs/admin-evidence/domain.md` |
| Grafana Cloud public dashboard link | DEPLOY-05 | Requires a hosted Grafana account; the local container stays loopback-bound | `docs/deploy/gcp.md` closing section; README Observability line stays pending until the link exists |
| Better Uptime monitors + the 99.5 % monthly measurement | PERF-04 | A liveness prober must live outside the failure domain it measures | `docs/runbooks/uptime.md`; then `make uptime-report` in hosted mode with `BETTERUPTIME_API_TOKEN` |
| Sentry project DSN | DEPLOY-06 | Requires a Sentry account; the integration is a verified no-op until then | Set `SENTRY_DSN` in `.env`; confirm one grouped issue with a traceback appears after a deliberate error |
| Production secrets in Secret Manager | DEPLOY-01 | Real credentials, never committed | `docs/deploy/gcp.md` §Secret Manager |
| Vercel env vars pointing at a deployed API | DEPLOY-01, FE-* | `NEXT_PUBLIC_*` are inlined at build time and need a deployed API URL | `docs/HUMAN-ACTIONS.md` §Vercel; the README demo link placeholder is replaced by the orchestrator |
| Twilio A2P 10DLC approval + live US number | NOTIF-02 (Phase 4) | Carrier review, 1-3 weeks | `docs/runbooks/twilio-10dlc-setup.md` |
| Resend domain verification | NOTIF-01 (Phase 4) | DNS records + provider verification | `docs/HUMAN-ACTIONS.md` §Resend |
| Resy cookies, numeric venue ids, API key | POLL-02 (Phase 3) | Supervised browser login; third-party credentials | `docs/admin-evidence/resy.md` |
| OpenTable DevTools endpoint spike | POLL-01 (Phase 1) | Live browser capture of a request shape | `docs/PHASE-01-HUMAN-ACTIONS.md` → `docs/HUMAN-ACTIONS.md` §OpenTable |
| 24 h PERF-02 poll-success window | PERF-02 (Phase 1) | 24 hours of wall clock against live sources | `docs/runbooks/perf02-24h-log.md`; gate: `make verify-perf02` |
| 24 h PERF-01 latency window | PERF-01 (Phase 4) | 24 hours of production traffic | `docs/runbooks/perf01-latency.md` (Phase 4) |
| 12 h PERF-05 Playwright soak | PERF-05 (Phase 3) | 12 hours of wall clock with a real browser fleet | Phase 3 soak runbook |
| Real-iPhone PWA push (5 consecutive) | NOTIF-03 (Phase 4) | Simulators do not reproduce iOS push revocation | `docs/runbooks/ios-pwa-push.md` (Phase 4/6) |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 20 s at the unit tier
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
