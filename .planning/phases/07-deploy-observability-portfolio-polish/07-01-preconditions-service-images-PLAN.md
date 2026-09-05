---
phase: 07-deploy-observability-portfolio-polish
plan: 01
type: execute
wave: 1
depends_on: []
autonomous: true
requirements: [DEPLOY-01]
files_modified:
  - .dockerignore
  - .env.example
  - Makefile
  - ops/docker/state_machine.Dockerfile
  - ops/docker/poller.Dockerfile
  - ops/docker/notifier.Dockerfile
  - ops/docker/api.Dockerfile
  - tests/unit/test_phase7_preconditions.py
  - tests/unit/test_dockerfiles_hardened.py

estimate:
  tokens: 62000
  raw_tokens: 62000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Wave 0 (A1): `uv run pytest tests/unit/test_phase7_preconditions.py -q` fails with a message naming the owning phase when any of `services/notifier/main.py`, `services/api/`, `web/package.json`, `shared/metrics.py` or migrations through `0011` are absent — Phase 7 cannot execute out of order."
    - "D-119: `docker build -f ops/docker/state_machine.Dockerfile -t mise-state-machine:dev .` exits 0 and the resulting container runs as uid 1001, not root."
    - "D-119: all four Python service images exist as `ops/docker/{poller,state_machine,notifier,api}.Dockerfile`, each pinning its base by tag (never `:latest`), declaring a `USER` that is not root, and declaring a `HEALTHCHECK`."
    - "D-119a: the three plain Python images take their uv binary from `ghcr.io/astral-sh/uv:0.11.7` via `COPY --from` (the `-python3.12-bookworm-slim` tag family no longer exists), and the poller image is based on `mcr.microsoft.com/playwright/python:v1.58.0-noble` whose system Python 3.12.3 already satisfies `requires-python >=3.12,<3.13`."
    - "D-119a: the poller image launches Chromium as `pwuser` under default Docker seccomp with no sandbox-disabling launch flag (research verified `NO-SANDBOX-FREE OK: 145.0.7632.0`)."
    - "D-126: `make images` builds all four Python images with explicit `ghcr.io/$(GHCR_OWNER)/mise-<service>:$(MISE_TAG)` tags and is idempotent across repeated runs."
    - "V14/D-119: `.dockerignore` excludes `.env`, `.venv`, `web/node_modules`, `web/.next`, `.git`, `.planning` and every cache dir, so no secret and no 400 MB host venv can enter a build context."
    - "D-126: `.env.example` declares every environment key Phase 7 introduces (`SENTRY_DSN`, `GHCR_OWNER`, `MISE_TAG`, `METRICS_PORT`, `PROMETHEUS_PORT`, `GRAFANA_PORT`, `PROMETHEUS_URL`, `BETTERUPTIME_API_TOKEN`, `SMOKE_WEB_URL`, `GIT_SHA`), each with a comment naming what reads it."
    - "D-127: image builds are gated in CI rather than on every commit, but `make images` must succeed at least once during this phase before it can be verified — that run is this plan's Task 3 acceptance criterion."
  artifacts:
    - .dockerignore
    - ops/docker/state_machine.Dockerfile
    - ops/docker/poller.Dockerfile
    - ops/docker/notifier.Dockerfile
    - ops/docker/api.Dockerfile
    - tests/unit/test_phase7_preconditions.py
    - tests/unit/test_dockerfiles_hardened.py
  key_links:
    - "`.dockerignore` → every `docker build`: without it the Python build context carries `.venv` and `.env`; this is the single control that keeps secrets out of image layers."
    - "`ops/docker/*.Dockerfile` `METRICS_PORT` defaults (9101/9102/9103) → `ops/prometheus/prometheus.yml` scrape targets (07-04) → Grafana panels (07-04). A port changed here silently empties five dashboard panels."
    - "`pyproject.toml` + `uv.lock` → the `uv sync --frozen --no-install-project` dependency layer. A lockfile drift makes every image build re-resolve and the `--frozen` flag fail loudly instead."
  prohibitions:
    - "Must never bake a secret into an image layer: no `COPY .env`, no `ENV` carrying a credential, no `ARG` defaulted to a real token. Secrets reach containers only through compose `env_file`."
    - "Must never run a service container as root. Every image declares a non-root `USER` before its `ENTRYPOINT`."
    - "Must never weaken the browser sandbox to make the poller image start. If Chromium fails to launch, fix the cause rather than disabling the sandbox — this service renders attacker-influenced pages."
  flagged_assumptions:
    - "A1 (07-RESEARCH Assumptions Log): Phases 3–6 have not executed. Every file this plan packages (`services/notifier/`, `services/api/`, `web/`) is assumed present at execution time. Task 1 is the halt gate for that assumption; it is an assertion, not a hope."
    - "Pitfall 8: `python:3.12-slim` is a moving tag (bookworm → trixie under the same name). This plan pins by tag and records the observed OS/Python in a comment rather than pinning by digest; a base-OS change under the tag can therefore still surprise a future build. Digest pinning is deferred, not denied."
---

<objective>
Establish the Phase 7 execution precondition gate and package the four Python services as production-grade, non-root container images.

Purpose: DEPLOY-01 is delivered from this repository as real images rather than as a cloud deployment (D-119). Nothing else in Phase 7 — compose profiles, Prometheus scrape targets, CI smoke, CD image push — has anything to run until these images exist and build reproducibly from a clean context. Task 1 exists because Phase 7 executes last and every artifact it wraps belongs to a phase that has not run yet (A1); a plan that silently packaged a missing service would fail four waves later with an unreadable error.

Output: `.dockerignore`, four `ops/docker/*.Dockerfile`, `make images`, the Phase-7 precondition gate, and a Dockerfile hardening gate.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-CONTEXT.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-RESEARCH.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-PATTERNS.md
@CLAUDE.md
@pyproject.toml
</context>

<artifacts_this_phase_produces>
Phase 7 inventory. **Bold** entries are produced by this plan; the rest are named so this plan's
choices stay consistent with them and are never re-created elsewhere.

- **Images:** `mise-state_machine`, `mise-poller`, `mise-notifier`, `mise-api` — plus `mise-web` (07-02).
- Compose services/profiles: `prod` / `smoke` / `monitoring` profiles, `migrate` + `topics` one-shots (07-02), `prometheus`, `grafana`, `kafka-exporter`, `redis-exporter` (07-04).
- Workflows: `ci.yml`, `cd.yml` (07-07).
- **Scripts/targets:** `make images`; plus `up-prod` (07-02), `up-monitoring` (07-04), `smoke` (07-07), `docs`/`status` (07-08).
- **Docs:** `.env.example` Phase-7 key block; plus `docs/deploy/gcp.md`, `docs/runbooks/uptime.md`, `docs/HUMAN-ACTIONS.md` (07-05), `README.md`/`docs/status.json`/`docs/architecture.{mmd,svg}` (07-08).
- Metrics: `shared/metrics.py` additions (07-03) exposed on the `METRICS_PORT` values this plan bakes into the images.
</artifacts_this_phase_produces>

<tasks>

<task type="auto">
  <name>Task 1 (Wave 0): Phase-7 precondition gate and build-context hygiene</name>
  <files>tests/unit/test_phase7_preconditions.py, .dockerignore, .env.example</files>
  <read_first>
    - `.planning/phases/07-deploy-observability-portfolio-polish/07-RESEARCH.md` §Runtime State Inventory (the `.dockerignore` entry list) and §Assumptions Log A1
    - `tests/unit/test_no_inline_sleep.py:18-59` — the repo's canonical grep-gate shape: `REPO_ROOT = Path(__file__).resolve().parents[2]`, comment stripping, and the non-vacuity test at `:40-46`
    - `.env.example` (all 59 lines) — comment voice and section ordering
    - `migrations/versions/` — current revisions stop at `0009_restaurant_slug_source_unique.py`
  </read_first>
  <action>
Create `tests/unit/test_phase7_preconditions.py`. It asserts, with one test per upstream phase and a
failure message that names the owning phase and its plan, that every artifact Phase 7 wraps exists:

- Phase 3: `shared/metrics.py` exists and imports, and exposes `poll_total` and `poll_latency_seconds`.
- Phase 4: `services/notifier/main.py` exists; `migrations/versions/` contains a revision whose numeric
  prefix is at least `0010`.
- Phase 5: `services/api/` exists and contains a `main.py` or `app.py`; `migrations/versions/` reaches at
  least `0011`; `uv run alembic heads` reports exactly one head (a fork would make the `migrate` one-shot
  container in 07-02 non-deterministic).
- Phase 6: `web/package.json` exists and `web/` contains a `next.config.*`.

Each assertion message reads like `services/notifier/main.py is missing — Phase 4 (Notification Pipeline)
owns it; Phase 7 must not execute before Phase 4 completes (A1).` Include a non-vacuity test asserting the
set of checked paths has at least 6 members, so a refactor that empties the list cannot make the gate pass
by scanning nothing.

Create `.dockerignore` at the repository root excluding: `.git`, `.venv`, `**/__pycache__`, `.pytest_cache`,
`.mypy_cache`, `.ruff_cache`, `.planning`, `web/node_modules`, `web/.next`, `docs/admin-evidence`,
`*.docx`, and `.env` plus `.env.*` with an exception for `.env.example`. Put a comment above the `.env`
entry naming what it prevents: a credential entering an image layer, where `docker history` can read it
back forever.

Extend `.env.example` with a `# Phase 7 — deploy & observability` section declaring, each with a one-line
comment naming its reader: `SENTRY_DSN` (blank = Sentry disabled, `shared/observability.py`),
`GHCR_OWNER` (compose `image:` tags and `make images`), `MISE_TAG` (default `dev`), `METRICS_PORT`
(per-service; 9101 poller / 9102 state machine / 9103 notifier), `PROMETHEUS_PORT` (9090),
`GRAFANA_PORT` (3001, bound to loopback), `PROMETHEUS_URL` (`scripts/uptime_report.py` compose mode),
`BETTERUPTIME_API_TOKEN` (pending-human, `scripts/uptime_report.py` hosted mode), `SMOKE_WEB_URL`
(`tests/e2e/test_smoke.py`), and `GIT_SHA` (Sentry release tag). Every value is a placeholder or a
default; no real credential is ever committed here.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_phase7_preconditions.py -q` exits 0 (all upstream artifacts present) or exits non-zero with a message naming the missing artifact's owning phase.
    - `grep -c '^\.env$' .dockerignore` returns 1 and `grep -c '!\.env\.example' .dockerignore` returns 1.
    - `grep -v '^#' .env.example | grep -c 'SENTRY_DSN'` returns 1, and the same filtered grep returns 1 for each of `GHCR_OWNER`, `MISE_TAG`, `PROMETHEUS_URL`, `BETTERUPTIME_API_TOKEN`.
    - `uv run ruff check tests/unit/test_phase7_preconditions.py` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_phase7_preconditions.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>The phase halts loudly and legibly if Phase 4–6 artifacts are absent, and no build context can carry a secret or the host venv.</done>
</task>

<task type="tracer">
  <name>Task 2 (tracer): one service, source to runnable image</name>
  <files>ops/docker/state_machine.Dockerfile, Makefile</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 1 (lines 278-327) — the verified two-stage uv Dockerfile, built and run on this machine (661 MB, `uid=1001(mise)`, `import OK 6`)
    - `07-RESEARCH.md` §Standard Stack — why `COPY --from=ghcr.io/astral-sh/uv:0.11.7 /uv /uvx /bin/` replaces the deleted `-python3.12-bookworm-slim` tag
    - `services/state_machine/__main__.py` and `services/state_machine/main.py:81-145` — the module entrypoint the image runs
    - `Makefile:1-73` — `.PHONY` line and the `## description` convention consumed by `help`
  </read_first>
  <action>
Write `ops/docker/state_machine.Dockerfile` as a two-stage build following §Pattern 1 exactly:
`FROM python:3.12-slim AS builder`, the uv binary copied in from the pinned `ghcr.io/astral-sh/uv:0.11.7`
image, `UV_COMPILE_BYTECODE=1`, `UV_LINK_MODE=copy`, `UV_PYTHON_DOWNLOADS=never`,
`UV_PROJECT_ENVIRONMENT=/app/.venv`; a first `uv sync --frozen --no-dev --no-install-project` under
`--mount=type=cache,target=/root/.cache/uv` with `uv.lock` and `pyproject.toml` bind-mounted, so the
dependency layer is cached independently of source edits; then `COPY` of `shared/ services/ scripts/
migrations/` plus `alembic.ini pyproject.toml uv.lock`, and a second `uv sync --frozen --no-dev`.
Runtime stage `FROM python:3.12-slim`, a system group+user `mise` at gid/uid 1001, `COPY --from=builder
--chown=mise:mise /app /app`, `ENV PATH="/app/.venv/bin:$PATH"`, `PYTHONUNBUFFERED=1`,
`METRICS_PORT=9102`, `USER mise`, `EXPOSE 9102`, a `HEALTHCHECK` that probes
`http://127.0.0.1:${METRICS_PORT}/metrics` with `urllib.request` from the venv Python (this base has
neither curl nor wget), and `ENTRYPOINT ["python", "-m", "services.state_machine"]`.

Add a header comment recording the base image's observed identity on this date (Debian 13 trixie,
Python 3.12.14) and why the tag is not pinned by digest, per §Pitfall 8.

Add a `make images` target (and its `.PHONY` entry and `## description`) that builds this image as
`ghcr.io/$(GHCR_OWNER)/mise-state_machine:$(MISE_TAG)` with `GHCR_OWNER ?= local` and `MISE_TAG ?= dev`
defaults declared at the top of the Makefile. Task 3 extends the target to the other three services;
write it as a loop over a `PY_IMAGES` variable so extending it is a one-word edit.

The healthcheck will report unhealthy until 07-03 starts the metrics server — that is intended and must
be stated in a comment on the `HEALTHCHECK` line, because a healthcheck that passes while `/metrics` is
dark would be a healthcheck that proves nothing.
  </action>
  <acceptance_criteria>
    - `docker build -f ops/docker/state_machine.Dockerfile -t mise-state-machine:tracer .` exits 0.
    - `docker run --rm --entrypoint sh mise-state-machine:tracer -c 'id -u'` prints `1001`.
    - `docker run --rm --entrypoint sh mise-state-machine:tracer -c 'python -c "import services.state_machine, shared.metrics; print(\"import ok\")"'` prints `import ok` and exits 0.
    - `docker run --rm --entrypoint sh mise-state-machine:tracer -c 'ls /app/.env 2>/dev/null; echo rc=$?'` prints `rc=1` (no `.env` in the image).
    - `make images` exits 0 and `docker image inspect ghcr.io/local/mise-state_machine:dev` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>docker build -f ops/docker/state_machine.Dockerfile -t mise-state-machine:tracer . && docker run --rm --entrypoint sh mise-state-machine:tracer -c 'test "$(id -u)" = 1001 && python -c "import services.state_machine, shared.metrics"'</automated>
  </verify>
  <done>One service goes from repository source to a running, non-root container whose packaged venv imports the service module — the packaging path is proven end to end before it is replicated.</done>
</task>

<task type="auto">
  <name>Task 3: the remaining three Python images and the hardening gate</name>
  <files>ops/docker/poller.Dockerfile, ops/docker/notifier.Dockerfile, ops/docker/api.Dockerfile, Makefile, tests/unit/test_dockerfiles_hardened.py</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 2 (lines 329-397) — the verified Playwright poller image, including the measured facts about `mcr.microsoft.com/playwright/python:v1.58.0-noble` (Ubuntu 24.04.3, Python 3.12.3, `pwuser` uid 1001, `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`, the PyPI `playwright` package absent from the base)
    - `07-RESEARCH.md` §Anti-Patterns to Avoid — why no sandbox-disabling flag is added and why a later `rm -rf` cannot shrink a base layer
    - `services/poller/config.py:145,297` — `DEFAULT_METRICS_PORT = 9101`
    - `tests/unit/test_no_inline_sleep.py:18-59` — grep-gate shape with comment stripping and the non-vacuity assertion
    - The Dockerfile written in Task 2 — notifier and api are that file with three lines changed
  </read_first>
  <action>
Write three more Dockerfiles under `ops/docker/`:

`notifier.Dockerfile` — byte-identical to `state_machine.Dockerfile` except `METRICS_PORT=9103`,
`EXPOSE 9103`, and `ENTRYPOINT ["python", "-m", "services.notifier"]`.

`api.Dockerfile` — the same two-stage build, `EXPOSE 8000`, `HEALTHCHECK` probing
`http://127.0.0.1:8000/healthz`, and an entrypoint running uvicorn against the Phase-5 ASGI app bound
to `0.0.0.0:8000` with `--no-access-log` (the API's own structlog request middleware, Phase 5 D-97, is
the access log; a second one would double every line). Read the Phase-5 app's import path from
`services/api/` rather than guessing it; if the app factory is `create_app`, use the factory form.

`poller.Dockerfile` — single-stage on `mcr.microsoft.com/playwright/python:v1.58.0-noble` with the uv
binary copied in as before, `UV_PYTHON=/usr/bin/python3.12`, the same two-phase `uv sync`, `chown -R
pwuser:pwuser /app`, `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`, `METRICS_PORT=9101`, `USER pwuser`,
`EXPOSE 9101`, a `HEALTHCHECK` with `--start-period=45s`, and `ENTRYPOINT ["python", "-m",
"services.poller"]`. Chromium must launch under the default seccomp profile with the sandbox intact; a
header comment records that this was measured, so nobody re-adds the flag as a guess.

Extend `make images` to build all four via the `PY_IMAGES` list.

Create `tests/unit/test_dockerfiles_hardened.py` following the repo grep-gate shape. Strip comment lines
before every assertion, so an explanatory comment can neither satisfy nor break a gate. For every file
matching `ops/docker/*.Dockerfile` assert: at least one `FROM` line and no `FROM` line ending in
`:latest` or lacking a tag; exactly one `USER` instruction whose argument is neither `root` nor `0`, and
it appears after the last `COPY`; a `HEALTHCHECK` instruction is present; no `COPY` or `ADD` whose source
is `.env`; and no occurrence of a Chromium sandbox-disabling launch flag. Add the mandatory non-vacuity
test: the scanned set has at least 4 members and its stems include `poller`, `state_machine`, `notifier`
and `api` (07-02 adds `web` and updates this expectation).
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_dockerfiles_hardened.py -q` exits 0 with at least 5 tests collected.
    - `docker build -f ops/docker/notifier.Dockerfile -t mise-notifier:dev .` and the same for `api` exit 0.
    - `docker build -f ops/docker/poller.Dockerfile -t mise-poller:dev .` exits 0, and `docker run --rm --entrypoint sh mise-poller:dev -c 'id -un && python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(args=[\"--disable-dev-shm-usage\"]); print(b.version); b.close(); p.stop()"'` prints `pwuser` and a Chromium version.
    - `make images` exits 0 and `docker images --format '{{.Repository}}:{{.Tag}}' | grep -c '^ghcr.io/local/mise-'` returns 4.
    - `grep -v '^#' ops/docker/poller.Dockerfile | grep -c 'no-sandbox'` returns 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_dockerfiles_hardened.py -q -W error::RuntimeWarning && make images</automated>
  </verify>
  <done>All four Python services build as pinned, non-root, health-checked images from one `make images` invocation, and a permanent unit gate prevents the next contributor from regressing any of those four properties.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| host filesystem → docker build context | Everything not excluded by `.dockerignore` is uploaded to the daemon and can end up in a layer. |
| upstream registry → local image | Base images (`python:3.12-slim`, the MCR Playwright image, the uv donor image) are third-party content executed with our code. |
| container process → host kernel | The poller renders remote, attacker-influenced pages inside Chromium. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-07-01 | Information disclosure | build context | high | mitigate | `.dockerignore` excludes `.env`/`.env.*`; `test_dockerfiles_hardened.py` forbids `COPY .env`; Task 2 acceptance greps the built image for `/app/.env`. |
| T-07-02 | Elevation of privilege | all four images | high | mitigate | Every image declares a non-root `USER` before `ENTRYPOINT`; the hardening gate asserts it on every `ops/docker/*.Dockerfile` forever. |
| T-07-03 | Elevation of privilege | poller Chromium | high | mitigate | Chromium runs as `pwuser` with the sandbox intact under default seccomp (measured); the hardening gate greps for a sandbox-disabling flag and fails if one appears. |
| T-07-04 | Tampering | base images | medium | mitigate | Every `FROM` carries an explicit version tag, gated by the hardening test; the observed OS/Python of each base is recorded in a header comment so a silent tag move is diagnosable. |
| T-07-SC | Tampering | uv/pip installs inside the image | high | mitigate | Images install only from the committed `uv.lock` via `uv sync --frozen`; no new package is added in this plan, so the Package Legitimacy Gate has nothing to clear here (`sentry-sdk` is cleared in 07-03, `@mermaid-js/mermaid-cli` in 07-08). Record this in the SUMMARY. |
</threat_model>

<verification>
1. `uv run pytest tests/unit/test_phase7_preconditions.py tests/unit/test_dockerfiles_hardened.py -q -W error::RuntimeWarning` — exit 0.
2. `make images` — exit 0, four `ghcr.io/local/mise-*:dev` tags present.
3. `uv run ruff check . && uv run mypy shared/ services/ scripts/` — exit 0 (no source module changed, but the new test files are linted).
4. `uv run pytest tests/unit -q -W error::RuntimeWarning` — the full unit tier stays green.
</verification>

<success_criteria>
- Four Dockerfiles exist, build, and produce non-root containers whose packaged venv imports their service module.
- The precondition gate fails loudly and legibly when an upstream phase's artifact is missing.
- No image can carry `.env`, and no Dockerfile can regress non-root/pinned-base/healthcheck without a red unit test.
- `make images` is the single command that produces every Python service image.
</success_criteria>

<output>
Create `.planning/phases/07-deploy-observability-portfolio-polish/07-01-SUMMARY.md` when done.
Record in it: the observed base-image identities (`docker run --rm python:3.12-slim python -V` and the
MCR image's `PRETTY_NAME`), the four image sizes, and the package-legitimacy note that this plan added
no new package.
</output>
