---
phase: 07-deploy-observability-portfolio-polish
plan: 07
type: execute
wave: 5
depends_on: ["07-02", "07-03", "07-04", "07-05", "07-06"]
autonomous: true
requirements: [DEPLOY-03, DEPLOY-04]
files_modified:
  - .github/workflows/ci.yml
  - .github/workflows/cd.yml
  - .github/workflows/lint.yml
  - pyproject.toml
  - Makefile
  - tests/e2e/__init__.py
  - tests/e2e/conftest.py
  - tests/e2e/test_smoke.py
  - tests/unit/test_ci_workflow_gates.py
  - tests/unit/test_cd_workflow.py

estimate:
  tokens: 78000
  raw_tokens: 78000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "D-121: `.github/workflows/ci.yml` replaces `lint.yml` and runs the jobs `lint`, `unit`, `integration`, `web`, `ops-config` and `smoke`, with `concurrency` cancelling superseded runs and caching for both `uv` and `npm`."
    - "D-121: the `lint` job keeps all three ban greps verbatim from `lint.yml:19-27` and widens the mypy target set to `shared/ services/ scripts/`, matching `Makefile`'s `lint` target — `tests/unit/test_ci_workflow_gates.py` asserts every one of those four facts."
    - "D-121: the `smoke` job brings up `--profile smoke --profile monitoring` with `up -d --build --wait`, runs `scripts/post_deploy_check.py --mode compose`, then runs the Playwright smoke test, and uploads compose logs as an artifact on failure."
    - "D-120a / Pitfall 6: every CI shell step that pipes command output sets `pipefail`. Measured: `docker compose up -d --wait 2>&1 | tail -25; echo $?` printed 0 while the real exit status was 1 — without this the smoke job goes green on a stack that never came up."
    - "D-121a: the smoke job excludes the poller. The smoke path injects raw messages with `scripts/replay_raw.py` and never scrapes anything, so building and starting a 4.59 GB Playwright image would cost minutes to prove nothing; CD builds and pushes that image instead."
    - "D-121: `tests/e2e/test_smoke.py` drives the full pipeline through the running stack — create a watch, inject a raw poll into Kafka, assert the event appears in the UI feed and that `notification_log` holds a `sent` row with `NOTIFY_DRY_RUN=true`."
    - "Pitfall 10: the e2e browser fixture uses `@pytest_asyncio.fixture(scope=\"module\", loop_scope=\"module\")` with a module-level `pytest.mark.asyncio(loop_scope=\"module\")`. The obvious plain `@pytest.fixture(scope=\"module\")` async generator hangs indefinitely under `asyncio_mode=auto` (measured: killed at over 420 seconds), and the `e2e` marker must be registered in `pyproject.toml` alongside `integration`."
    - "D-120: `.github/workflows/cd.yml` builds all five images on push to `main` with `docker/metadata-action` `type=sha` plus the branch tag, pushes to `ghcr.io/<owner>/mise-<service>` using only `GITHUB_TOKEN` with job-scoped `packages: write`, and uses `cache-from`/`cache-to: type=gha` scoped per service."
    - "D-120 / V4: the top-level workflow permission is `contents: read`; `packages: write` appears only on the build-push job. The `deploy-prod` job is `workflow_dispatch`-only, and its GCP steps are guarded by **step-level** `if:` on the two optional secrets — job-level `if:` cannot read `secrets` — so with no secrets configured it prints a pending-human notice and exits successfully."
    - "DEPLOY-04: the same `scripts/post_deploy_check.py` runs in both the compose smoke job and the gated production job, which is what makes the local run a real rehearsal rather than a different check with the same name."
    - "D-127: the integration/e2e tier proves the `prod` and `monitoring` compose profiles come up healthy under `up -d --wait` in the CI smoke job, and that the Playwright smoke test drives poll to state to event to dispatcher to mock provider with `NOTIFY_DRY_RUN=true`."
  artifacts:
    - .github/workflows/ci.yml
    - .github/workflows/cd.yml
    - tests/e2e/conftest.py
    - tests/e2e/test_smoke.py
    - tests/unit/test_ci_workflow_gates.py
    - tests/unit/test_cd_workflow.py
  key_links:
    - "`ci.yml` `ops-config` job → `ops/prometheus/**` (07-04) and `terraform/` (07-05). Those artifacts are only real because a job proves they still parse and validate."
    - "`cd.yml` image names `ghcr.io/<owner>/mise-<service>` → the compose `image:` tags (07-02). The same string in both places is what lets `MISE_TAG=sha-abc1234 docker compose pull` fetch a CD-built image."
    - "`tests/e2e/test_smoke.py` → `scripts/replay_raw.py` fixtures and the `NOTIFY_DRY_RUN` path (Phase 4 D-80). The smoke test asserts the pipeline, not the providers."
  prohibitions:
    - "Must never let a piped shell step hide a non-zero exit status. A CI step that turns a red build green is worse than no CI step."
    - "Must never require an external secret for the default CD path. Image publishing uses `GITHUB_TOKEN` only, so a fork or a fresh clone still gets a working pipeline."
    - "Must never weaken, delete or narrow one of the three ban greps to make a build pass. They encode the async-only contract in `CLAUDE.md`; if one fires, the code is wrong, not the gate."
    - "Must never disable or skip a test to get CI green. Environment guards that skip cleanly when a runtime is absent are permitted; a skip that hides a real failure is not."
  flagged_assumptions:
    - "DEPLOY-03's probe row is `unclassified` in the edge report and is carried forward unresolved rather than auto-resolved. The open question it stands for: no CI run has ever executed from this machine, so the job graph's real wall-clock behaviour on a GitHub-hosted runner is unmeasured. Every job's commands are individually proven locally by this plan's acceptance criteria; the first push is the first real observation, and the SUMMARY must record what it showed."
    - "A2 (07-RESEARCH Assumptions Log): whether a GitHub-hosted runner can build and push the 4.59 GB poller image inside the job timeout is unmeasured. The compressed base is 0.96 GB in four layers and subsequent pushes move only the ~120 MB venv/source layers, which makes it plausible. Mitigation if the first CD run times out: split the poller into its own job with a raised `timeout-minutes` and rely on the per-service GHA cache scope already configured."
    - "`ci.yml` pins action versions confirmed on 2026-09-05 (`actions/checkout@v7`, `astral-sh/setup-uv@v10`, `actions/setup-node@v7`, `docker/*@v4/v6/v7`, `hashicorp/setup-terraform@v4`, `google-github-actions/auth@v3`). The current `lint.yml` pins `checkout@v4` and `setup-uv@v3`, both several majors stale; bumping them is part of the replacement."
---

<objective>
Replace the single lint workflow with a full CI job graph that actually exercises this system, add the end-to-end smoke test it runs, and publish SHA-tagged images from a CD workflow that needs no external secret.

Purpose: DEPLOY-03 and DEPLOY-04 are the difference between "the code is there" and "the code is proven on every commit." The measured trap that governs this plan is small and decisive: piping compose output to `tail` without `pipefail` turns a failed stack into a green build. A CI system that reports success for a broken stack is not a weaker CI system — it is a false one.

Output: `ci.yml`, `cd.yml`, the deletion of `lint.yml`, `tests/e2e/**`, the `e2e` marker, `make smoke`, and two workflow gates.
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
@.planning/phases/07-deploy-observability-portfolio-polish/07-06-SUMMARY.md
@.github/workflows/lint.yml
@Makefile
@CLAUDE.md
</context>

<artifacts_this_phase_produces>
- **Workflows:** `.github/workflows/ci.yml` (jobs `lint`, `unit`, `integration`, `web`, `ops-config`, `smoke`) and `.github/workflows/cd.yml` (jobs `build-push`, `deploy-prod`); `lint.yml` is removed.
- **Tests:** `tests/e2e/{__init__,conftest,test_smoke}.py`; `tests/unit/test_ci_workflow_gates.py`; `tests/unit/test_cd_workflow.py`.
- **Config/targets:** the `e2e` pytest marker in `pyproject.toml`; `make smoke` rewritten to `up -d --wait` plus the e2e suite.
- **Images (published):** `ghcr.io/<owner>/mise-{poller,state_machine,notifier,api,web}` tagged `sha-<short>` and `main`.
</artifacts_this_phase_produces>

<tasks>

<task type="tracer">
  <name>Task 1 (tracer): one workflow whose lint job runs green, command for command, locally</name>
  <files>.github/workflows/ci.yml, .github/workflows/lint.yml, tests/unit/test_ci_workflow_gates.py</files>
  <read_first>
    - `.github/workflows/lint.yml` (all 27 lines) — the three ban-grep steps to carry over character for character, and the two stale action pins to bump
    - `07-RESEARCH.md` §Code Examples `ci.yml` skeleton (lines 1139-1242) — the verified job graph and the action versions confirmed on 2026-09-05
    - `Makefile:38-41` — the `lint` target whose mypy scope CI must match
    - `tests/unit/test_no_inline_sleep.py:18-59` — grep-gate shape with comment stripping and the non-vacuity assertion
  </read_first>
  <action>
Create `.github/workflows/ci.yml` with `name: ci`, triggers on push to `main` and on pull requests, a
`concurrency` group keyed on workflow and ref with `cancel-in-progress: true`, `defaults.run.shell: bash`,
and an `env.UV_VERSION` pinned to the same uv version the Dockerfiles and `uv.lock` use.

Add two jobs for this tracer. `lint`: checkout, `astral-sh/setup-uv` with caching enabled, `uv sync
--frozen`, `uv run ruff check .`, `uv run mypy shared/ services/ scripts/`, and the three ban-grep steps
copied from `lint.yml:19-27` character for character with their existing step names. `unit`: the same
setup plus `uv run pytest tests/unit -q -W error::RuntimeWarning`.

Delete `.github/workflows/lint.yml` in the same commit — two workflows running the same gates would
double every PR's queue time and let them drift apart.

Create `tests/unit/test_ci_workflow_gates.py`: parse `ci.yml` with `yaml.safe_load` and assert that the
three ban-grep steps are present with their exact `run` bodies (compare against the strings this test
holds, so a weakened grep fails here rather than in production), that the mypy step targets all three
directories, that `lint.yml` no longer exists, and that `defaults.run.shell` is `bash`. Add the
non-vacuity assertion: at least two jobs parsed and the job names include `lint` and `unit`.
  </action>
  <acceptance_criteria>
    - `python3 -c "import yaml,sys; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(sorted(d['jobs']))"` lists at least `lint` and `unit`.
    - Every command in the `lint` job runs green locally: `uv run ruff check .`, `uv run mypy shared/ services/ scripts/`, and each of the three ban greps exits 0.
    - `test ! -f .github/workflows/lint.yml` exits 0.
    - `uv run pytest tests/unit/test_ci_workflow_gates.py -q -W error::RuntimeWarning` exits 0.
    - `python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); assert d['defaults']['run']['shell']=='bash'"` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run ruff check . && uv run mypy shared/ services/ scripts/ && ! grep -rn "^import requests\|^from requests " services/ shared/ && ! grep -rn "time\.sleep(" services/ shared/ && ! grep -rEn "^import redis$|^from redis import " services/ shared/ && uv run pytest tests/unit/test_ci_workflow_gates.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>A single workflow file exists, the old one is gone, and every command its first two jobs will run has been executed locally and passed — the CI path is proven before it is widened.</done>
</task>

<task type="auto">
  <name>Task 2: the end-to-end smoke test and `make smoke`</name>
  <files>pyproject.toml, tests/e2e/__init__.py, tests/e2e/conftest.py, tests/e2e/test_smoke.py, Makefile</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 6 (lines 607-653) — the three measured fixture shapes (one of which hangs) and the working `test_smoke.py` skeleton
    - `07-RESEARCH.md` §Pitfall 10 — the module-scoped async fixture that never returns
    - `pyproject.toml:49-52` — the `markers` list where `e2e` must be registered next to `integration`
    - `scripts/replay_raw.py` `--input` handling and `tests/fixtures/raw_streams/` — the injection path the smoke test uses
    - `.planning/phases/04-notification-pipeline/04-CONTEXT.md` D-80 — `NOTIFY_DRY_RUN=true` records a `sent` row with a `dry-run-` provider id
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` D-113 and D-116 — the watch-setup flow and the homepage live feed the test drives
    - `Makefile:50-52` — the `smoke` recipe being replaced, including its fixed `sleep 30`
  </read_first>
  <action>
Register the `e2e` marker in `pyproject.toml`'s `[tool.pytest.ini_options].markers` with a one-line
description. Without it, `-m e2e` emits an unknown-marker warning, and `make test` runs with
`-W error::RuntimeWarning`.

Create `tests/e2e/__init__.py` and `tests/e2e/conftest.py`. The browser fixture must use
`@pytest_asyncio.fixture(scope="module", loop_scope="module")` with a module-level
`pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="module")]`, launching Chromium once per
module with `--disable-dev-shm-usage`; the page fixture is function-scoped with `loop_scope="module"` and
a 390x844 mobile viewport matching the Phase-6 mobile-first contract. Put a comment on the fixture
decorator naming the measured failure it avoids: the plain `@pytest.fixture(scope="module")` async
generator never returns. Do not add `pytest-playwright` — its fixtures are synchronous and this codebase
is async-only.

Create `tests/e2e/test_smoke.py` driving the pipeline end to end against the running stack, reading base
URLs from `SMOKE_WEB_URL` and the API base with localhost defaults:

1. The homepage loads with status 200 and renders its hero.
2. Create a watch through the two-step `/watch/[slug]` flow for a seeded restaurant, and assert the
   success screen shows a management link.
3. Inject a matching raw poll into Kafka with `scripts/replay_raw.py --input <fixture>` as a subprocess,
   asserting a zero exit.
4. Poll the live feed until the corresponding event appears, with a bounded timeout and an explicit
   failure message naming which stage did not complete.
5. Assert `notification_log` holds a row for that watch with `status = 'sent'` and a dry-run provider id.

Rewrite `make smoke` to bring up `--profile smoke --profile monitoring` with `up -d --build --wait`, run
`make topics migrate seed`, run `scripts/post_deploy_check.py --mode compose`, then
`uv run pytest tests/e2e -q -m e2e -p no:cacheprovider`. The recipe must not pipe any of those commands
through another program without `pipefail`, and it replaces the fixed `sleep 30` entirely — a sleep is a
guess, and `--wait` is an answer.
  </action>
  <acceptance_criteria>
    - `python3 -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); assert any(m.startswith('e2e') for m in d['tool']['pytest']['ini_options']['markers'])"` exits 0.
    - `uv run pytest tests/e2e --collect-only -q -m e2e` exits 0 and collects at least 3 tests.
    - `make smoke` exits 0 end to end on a clean machine and completes in under 15 minutes.
    - `uv run pytest tests/e2e -q -m e2e -p no:cacheprovider` exits 0 against a running stack, with no test taking longer than 120 seconds.
    - `grep -v '^\s*#' Makefile | grep -c 'sleep 30'` returns 0.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` still exits 0 (no unknown-marker warning escalates).
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/e2e --collect-only -q -m e2e && make smoke</automated>
  </verify>
  <done>One command proves the whole pipeline — poll injection, state machine, event, notifier, API and UI — against real containers, using the fixture scoping that actually terminates.</done>
</task>

<task type="auto">
  <name>Task 3: the remaining CI jobs and the CD pipeline</name>
  <files>.github/workflows/ci.yml, .github/workflows/cd.yml, tests/unit/test_ci_workflow_gates.py, tests/unit/test_cd_workflow.py</files>
  <read_first>
    - `07-RESEARCH.md` §Code Examples `ci.yml` skeleton (lines 1160-1242) and `cd.yml` (lines 1244-1312) — both verified shapes with pinned action versions
    - `07-RESEARCH.md` §Pattern 5 (line 604) — the measured pipe trap: a piped `up -d --wait` reported exit 0 while the real status was 1
    - `07-RESEARCH.md` `cd.yml` facts list — `metadata-action` lowercases the image name and emits `sha-<7>` from `type=sha`; `permissions: packages: write` is what lets `GITHUB_TOKEN` push to GHCR; `secrets` is unavailable in job-level `if:`
    - `07-RESEARCH.md` §Pattern 9 — the two `promtool` invocations the `ops-config` job runs
    - `terraform/` from 07-05 and `ops/prometheus/` from 07-04 — the artifacts `ops-config` validates
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` D-109 — `npm run lint`, `npm test`, `npm run build` in `web/`
  </read_first>
  <action>
Add four jobs to `ci.yml`.

`integration`: uv setup, `uv run playwright install --with-deps chromium`, then `uv run pytest
tests/integration -q -p no:cacheprovider` on `ubuntu-latest` (Docker is preinstalled there).

`web`: `actions/setup-node` at Node 22 with npm caching keyed on `web/package-lock.json`, working
directory `web`, running `npm ci`, `npm run lint`, `npm test`, `npm run build`.

`ops-config`: `docker compose -f ops/docker-compose.yml --profile prod --profile monitoring config -q`;
the two `promtool` invocations against `ops/prometheus/` via `docker run --entrypoint promtool`;
`hashicorp/setup-terraform` at 1.13.0 with `terraform_wrapper: false`, then `terraform -chdir=terraform
fmt -check -recursive`, `init -backend=false -input=false` and `validate`. This job is the reason the
07-04 and 07-05 artifacts stay real.

`smoke`: `needs: [lint, unit]`, `timeout-minutes: 30`, buildx and uv setup, `playwright install
--with-deps chromium`, then a step that sets `set -euo pipefail` before copying `.env.example` to `.env`
(placeholders only — never a real secret in CI) and running `docker compose --profile smoke --profile
monitoring up -d --build --wait --wait-timeout 600`; then `uv run python scripts/post_deploy_check.py
--mode compose`; then `uv run pytest tests/e2e -q -m e2e -p no:cacheprovider`; then two `if: always()`
steps writing compose logs to a file and uploading it as an artifact.

Create `.github/workflows/cd.yml`: `name: cd`, triggers on push to `main` and on `workflow_dispatch` with
an `image_tag` input, `concurrency` keyed on ref with `cancel-in-progress: false`, and a top-level
`permissions: {contents: read}`. Job `build-push` runs a matrix over the five services with job-level
`permissions: {contents: read, packages: write}`, buildx setup, `docker/login-action` against `ghcr.io`
using `github.repository_owner` and `secrets.GITHUB_TOKEN`, `docker/metadata-action` producing
`type=sha` and `type=ref,event=branch` tags for `ghcr.io/${{ github.repository_owner }}/mise-${{
matrix.service }}`, and `docker/build-push-action` with the per-service Dockerfile, `push: true`,
`cache-from`/`cache-to: type=gha,mode=max,scope=<service>` and `provenance: false`. The `web` service
builds from the `web/` context; the other four from the repository root. Write the resolved tag list to a
job summary or an uploaded manifest artifact so a human can see exactly what was published.

Job `deploy-prod`: `needs: [build-push]`, `if: github.event_name == 'workflow_dispatch'`. Its GCP steps
carry **step-level** `if:` guards on `secrets.GCP_PROJECT_ID` and `secrets.GCP_WORKLOAD_IDENTITY_PROVIDER`
being non-empty — job-level `if:` cannot read `secrets`, and getting that backwards is a common failure.
With neither secret set the job prints a notice pointing at `docs/deploy/gcp.md` and
`docs/HUMAN-ACTIONS.md` and succeeds. With both set it authenticates via
`google-github-actions/auth`, deploys, and runs `scripts/post_deploy_check.py --mode prod --api-url
"$API_URL"` — the same script the smoke job runs.

Create `tests/unit/test_cd_workflow.py`: parse `cd.yml` and assert the top-level permission is
`contents: read`; that `packages: write` appears only on `build-push`; that the image name template is
`ghcr.io/<owner>/mise-<service>`; that the tag list contains `type=sha`; that the matrix covers all five
services; that `deploy-prod` is `workflow_dispatch`-gated; that every `secrets.` reference in the file is
drawn from the allowlist `{GITHUB_TOKEN, GCP_PROJECT_ID, GCP_WORKLOAD_IDENTITY_PROVIDER}`; and that no
`if:` at job level references `secrets`. Extend `tests/unit/test_ci_workflow_gates.py` with the pipefail
rule: every multi-line `run:` block in either workflow whose body contains a pipe character must also
contain `pipefail`. Add non-vacuity assertions to both: at least six CI jobs and at least two CD jobs
parsed, with their expected names present.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_ci_workflow_gates.py tests/unit/test_cd_workflow.py -q -W error::RuntimeWarning` exits 0.
    - `python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/ci.yml')); print(sorted(d['jobs']))"` prints exactly `['integration', 'lint', 'ops-config', 'smoke', 'unit', 'web']`.
    - Every `ops-config` command runs green locally: the two-profile `config -q`, both `promtool` checks, and `terraform fmt -check -recursive`/`init -backend=false`/`validate`.
    - Every `web` job command runs green locally from `web/`: `npm ci`, `npm run lint`, `npm test`, `npm run build`.
    - `python3 -c "import yaml; d=yaml.safe_load(open('.github/workflows/cd.yml')); assert d['permissions']=={'contents':'read'}; assert set(d['jobs']['build-push']['strategy']['matrix']['service'])=={'poller','state_machine','notifier','api','web'}"` exits 0.
    - `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` exits 0 — the full non-e2e suite that CI will run.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_ci_workflow_gates.py tests/unit/test_cd_workflow.py -q -W error::RuntimeWarning && docker compose -f ops/docker-compose.yml --profile prod --profile monitoring config -q && terraform -chdir=terraform fmt -check -recursive && terraform -chdir=terraform validate</automated>
  </verify>
  <done>Every artifact this phase produced is verified by a job on every commit, images publish to GHCR with no external secret, and the production promotion path is documented, gated, and honest about being unconfigured.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| pull request → CI runner | A PR from a fork runs workflow code against a runner holding a `GITHUB_TOKEN`. |
| CI runner → GHCR | The build-push job publishes artifacts consumers will pull. |
| repository secrets → workflow steps | `GCP_*` secrets, when present, grant deployment authority. |
| CI logs → public | This is a portfolio repository; workflow logs and artifacts are readable. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-07-25 | Elevation of privilege | `GITHUB_TOKEN` scope | high | mitigate | Top-level `permissions: {contents: read}`; `packages: write` only on `build-push`; `test_cd_workflow.py` asserts both facts and that every `secrets.` reference is on the three-name allowlist. |
| T-07-26 | Repudiation | a green build over a broken stack | high | mitigate | `defaults.run.shell: bash`, `set -euo pipefail` in every compose step, and a unit rule that any piped multi-line `run:` block must contain `pipefail`. |
| T-07-27 | Information disclosure | CI logs and artifacts | medium | mitigate | The smoke job copies `.env.example` (placeholders only) and never a real `.env`; compose output is uploaded as an artifact rather than echoed; no secret is ever printed. |
| T-07-28 | Tampering | published image tags | medium | mitigate | `docker/metadata-action` generates immutable `sha-<short>` tags from the commit; `provenance: false` keeps the manifest simple and predictable; the promotion job takes an explicit tag input rather than a floating one. |
| T-07-29 | Elevation of privilege | `deploy-prod` | high | mitigate | `workflow_dispatch`-only, and every GCP step guarded by step-level `if:` on both secrets; with neither configured the job prints a pending-human notice and touches nothing. |
| T-07-SC | Tampering | CI action supply chain | high | mitigate | Every action is pinned to a major version tag confirmed on 2026-09-05; `uv sync --frozen` and `npm ci` install only from committed lockfiles; no package-manager install is added by this plan. Record in SUMMARY. |
</threat_model>

<verification>
1. `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` — exit 0.
2. `make smoke` — exit 0 end to end, including `post_deploy_check` and the e2e suite.
3. Every `ops-config` command run locally — `config -q`, both `promtool` checks, `terraform fmt -check`/`init`/`validate` — exit 0.
4. Every `web` job command run locally from `web/` — exit 0.
5. `uv run pytest tests/unit/test_ci_workflow_gates.py tests/unit/test_cd_workflow.py -q` — exit 0, and `.github/workflows/lint.yml` no longer exists.
</verification>

<success_criteria>
- One workflow runs six jobs covering lint, unit, integration, frontend, ops config and a full compose smoke.
- No shell step can hide a failure behind a pipe.
- CD publishes five SHA-tagged images to GHCR using only `GITHUB_TOKEN`, and the production promotion is gated and honestly reports itself unconfigured.
- The three ban greps survive verbatim, enforced by a unit test rather than by review.
</success_criteria>

<output>
Create `.planning/phases/07-deploy-observability-portfolio-polish/07-07-SUMMARY.md` when done.
Record: the local wall-clock time for `make smoke`, the collected e2e test count, the exact job name list
from `ci.yml`, and — if a push happens during this run — the first CI run's per-job durations and the
first CD run's published tags, since A2 (the poller image build time on a hosted runner) is otherwise
unmeasured.
</output>
