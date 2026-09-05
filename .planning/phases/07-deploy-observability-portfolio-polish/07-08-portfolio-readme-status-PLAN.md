---
phase: 07-deploy-observability-portfolio-polish
plan: 08
type: execute
wave: 6
depends_on: ["07-04", "07-05", "07-07"]
autonomous: true
requirements: [DEPLOY-07]
files_modified:
  - scripts/status_report.py
  - scripts/render_diagram.py
  - docs/status.json
  - docs/architecture.mmd
  - docs/architecture.svg
  - README.md
  - CONTRIBUTING.md
  - Makefile
  - tests/unit/test_status_report.py
  - tests/unit/test_readme_status_guard.py
  - tests/unit/test_architecture_diagram.py

estimate:
  tokens: 80000
  raw_tokens: 80000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "D-125: `scripts/status_report.py` writes `docs/status.json` from live sources only — pytest collection counts per tier, the `web/` test count when Node is available, phase completion parsed from `.planning/ROADMAP.md`, and every human-gated item found by scanning the runbooks for their `pending-human` banners. No number in that file is typed by hand."
    - "D-125: the README Status section is generated from `docs/status.json` between explicit begin/end markers, and `make status` regenerates it byte-identically on an unchanged tree — a drift test proves it."
    - "D-125: `tests/unit/test_readme_status_guard.py` asserts every integer test count rendered in the README Status section equals the corresponding value in `docs/status.json`, so a stale hand-typed count cannot survive a commit."
    - "D-125: the README carries an architecture diagram (an ASCII overview plus `docs/architecture.svg` rendered from the committed `docs/architecture.mmd`), the live-demo link, the local Grafana dashboard URL with the hosted public link marked pending-human, refreshed Legal & Ethical Scraping and Why-Kafka sections, the `scripts/replay_raw.py` walkthrough with real fixture commands, and an Interview talking points section."
    - "D-125: the live-demo link is the literal placeholder token the orchestrator replaces after deploying `web/`; the README never asserts a URL that has not been deployed."
    - "D-124a: `docs/architecture.svg` is rendered by `scripts/render_diagram.py`, which writes a puppeteer config pointing at the Playwright Chromium already on this machine and runs the mermaid CLI with the puppeteer download suppressed — no 170 MB browser download, and no hand-drawn SVG that the `.mmd` source can drift from."
    - "DEPLOY-07 probe (boundary — *what happens exactly at each min/max/threshold, and one step either side?*): the status generator handles a tier that collects zero tests (reported as 0, never omitted), a phase with zero plans complete, and a phase at exactly 100 %. The README guard fails when a rendered count is one above or one below the value in `docs/status.json` — equality is the whole contract."
    - "DEPLOY-07 probe (precision — *where can precision loss, overflow, or rounding occur, and what is the exact contract?*): phase completion is stored in `docs/status.json` as the two integers `completed` and `total`, never as a pre-rounded float. The README renders the fraction and, where a percentage is shown, floors it to a whole number with the rule stated in `status_report.py`'s docstring — so 5/6 renders 83 %, never 84 %, and a rounding change is a code change with a failing test rather than a silent restatement."
    - "D-126: `CONTRIBUTING.md` documents the compose profiles, the six CI jobs, the Make targets this phase added, and the one-time Kafka volume reset."
    - "DEPLOY-07: the README claims nothing the code does not do. Every human-gated item is listed explicitly with its runbook path — Twilio 10DLC, Resend domain, Resy cookies plus numeric venue ids and API key, the OpenTable DevTools spike, the 24 h PERF-02 and PERF-01 windows, the 12 h PERF-05 soak, the iPhone push test, GCP provisioning and `terraform apply`, the domain and DNS, Grafana Cloud, Better Uptime, and the Sentry DSN."
    - "D-127: the unit tier covers the README status guard and the `docs/status.json` regenerate-and-diff drift check, so a claim in the README can never outlive the code behind it."
  artifacts:
    - scripts/status_report.py
    - scripts/render_diagram.py
    - docs/status.json
    - docs/architecture.mmd
    - docs/architecture.svg
    - tests/unit/test_status_report.py
    - tests/unit/test_readme_status_guard.py
    - tests/unit/test_architecture_diagram.py
  key_links:
    - "`docs/status.json` → the README Status section. One generator, one source; the guard test is what makes that a fact rather than an intention."
    - "runbook `pending-human` banners (07-05) → `status_report.py`'s human-gated list → the README. A runbook that gets completed and loses its banner drops out of the README on the next `make status`."
    - "`.planning/ROADMAP.md` phase checkboxes → phase completion counts. The ROADMAP is the source of truth for what is done; the README quotes it rather than restating it."
  prohibitions:
    - "Must never claim a deployed or hosted capability the project does not have. The hosted Grafana dashboard, the live domain, the uptime monitor and the production deployment are pending-human, and the README says so next to each one."
    - "Must never hand-type a test count, a phase count or a percentage into the README. If a number is not in `docs/status.json`, it does not go in the Status section."
    - "Must never present an aspirational feature as shipped. The existing honest voice — implemented / scaffolded / planned-only / known rough edges — is the format, and it stays."
  flagged_assumptions:
    - "The live-demo URL is a placeholder token at commit time. The orchestrator replaces it after deploying `web/` to Vercel; until then the README's demo line reads as pending. If the deploy does not happen this run, the placeholder must be replaced with an explicit pending-human line rather than left as a raw token."
    - "`docs/status.json` is a point-in-time snapshot committed alongside the README. It goes stale the moment a test is added, which is why `make status` exists and why the drift test fails a commit that changed the suite without regenerating."
    - "Mermaid rendering needs a Chromium. `scripts/render_diagram.py` reuses the Playwright browser; on a machine without it, `make docs` fails loudly and the committed SVG stays as it was — the `.mmd` source is the reviewable artifact either way."
---

<objective>
Turn the repository into the portfolio artifact DEPLOY-07 describes: an architecture diagram, an honest generated status report, refreshed design-rationale sections, and interview talking points — with every number produced by a script rather than by a person.

Purpose: this README is the thing a reader judges the project by, and the fastest way to lose that reader is a claim the code does not support. The existing README already has the right voice (implemented / scaffolded / planned-only / known rough edges) and the wrong numbers, because the numbers were typed by hand and the suite has grown since. Generating them closes that gap permanently.

Output: `scripts/status_report.py` and `docs/status.json`, the architecture diagram and its renderer, the rewritten README, `CONTRIBUTING.md`, and three guards.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/deferred-items.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-CONTEXT.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-RESEARCH.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-PATTERNS.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-04-SUMMARY.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-05-SUMMARY.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-07-SUMMARY.md
@README.md
@CONTRIBUTING.md
</context>

<package_legitimacy>
`@mermaid-js/mermaid-cli@11.17.0` is invoked through `npx` at documentation-build time only; it is never
a runtime dependency of `web/` and is never added to any lockfile that ships. The Package Legitimacy Gate
returned **SUS** on the `too-new` heuristic, which fires on the latest release date rather than on package
age. The package was created 2020-03-01, lives in the official `mermaid-js` org at
`github.com/mermaid-js/mermaid-cli`, has roughly 598,000 weekly downloads, and declares **no**
`postinstall` script. Its transitive `puppeteer` dependency **does** declare a postinstall that downloads
a Chrome build — which is why `scripts/render_diagram.py` sets the puppeteer download suppression flag
and points `executablePath` at the Playwright Chromium already present. No human is available to clear a
checkpoint this run, so D-124a's recorded disposition applies: **approved; no checkpoint task.** The
executor must restate this verdict in the SUMMARY.
</package_legitimacy>

<artifacts_this_phase_produces>
- **Scripts:** `scripts/status_report.py` (writes `docs/status.json` and the README Status block), `scripts/render_diagram.py` (Mermaid to SVG via the local Chromium).
- **Docs:** `docs/status.json`, `docs/architecture.mmd`, `docs/architecture.svg`, the rewritten `README.md`, the updated `CONTRIBUTING.md`.
- **Targets:** `make docs`, `make status`.
- **Tests:** `tests/unit/test_status_report.py`, `tests/unit/test_readme_status_guard.py`, `tests/unit/test_architecture_diagram.py`.
</artifacts_this_phase_produces>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1 (tracer): a test count travels from the suite to the README without a human touching it</name>
  <files>scripts/status_report.py, docs/status.json, README.md, Makefile, tests/unit/test_status_report.py</files>
  <read_first>
    - `README.md:283-297` — the current hand-typed `### Test coverage state` block, which is the drift this task exists to eliminate
    - `README.md:16-29,234-322` — the `## Status` and `## Detailed status` spine and the four honest subsections that stay
    - `.planning/ROADMAP.md` `## Progress` table and the per-phase `Plans:` checkbox lists — the phase-completion source
    - `scripts/replay_raw.py:425-483` — the `build_parser()` + `main(argv) -> int` argparse idiom for scripts taking real arguments
    - `scripts/check_poll_success.py:1-13` — the docstring-plus-exit-table convention
    - `docs/runbooks/*.md` and `docs/HUMAN-ACTIONS.md` from 07-05 — the `pending-human` banners the generator scans
  </read_first>
  <behavior>
    - `status_report.py --write` produces `docs/status.json` containing, for each test tier, an integer collected count obtained from `pytest --collect-only -q`; a tier that collects zero is present with the value 0, never omitted.
    - Phase completion is stored as the integers `completed` and `total` per phase, plus a repository-wide pair — never as a pre-rounded float.
    - The human-gated list is derived by scanning `docs/` for `pending-human` banners; a runbook whose banner is removed disappears from the list on the next run.
    - Running the generator twice on an unchanged tree produces byte-identical `docs/status.json`, and rewriting the README Status block twice produces a byte-identical README.
    - `--check` exits 1 when the on-disk `docs/status.json` or the README block differs from what a fresh run would produce, and 0 when they match.
    - The percentage rendering rule is floor-to-integer: 5 of 6 renders 83, and the test asserts it is not 84.
  </behavior>
  <action>
Create `scripts/status_report.py` with the repository's script conventions: a docstring naming the
requirement, a `Usage:` line naming both make targets, an explicit exit-code table, `build_parser()` and
`main(argv) -> int`.

The generator collects, from live sources only: per-tier test counts by running
`pytest --collect-only -q` for `tests/unit`, `tests/integration` and `tests/e2e` and parsing the
collected-count line; the `web/` test count from `npm test` when Node and `web/package.json` are present,
recorded as `null` with a reason when they are not; per-phase plan completion parsed from
`.planning/ROADMAP.md`'s checkbox lists; and the human-gated inventory built by scanning `docs/` for
files carrying a `pending-human` banner, capturing each file's path and its first heading.

It writes `docs/status.json` with a stable key order and a trailing newline so regeneration is
byte-comparable, and it rewrites the README's Status block in place between two explicit HTML-comment
markers. Everything outside those markers is left untouched — this generator owns one region of the
README and nothing else.

State the rounding contract in the module docstring and implement it once: percentages are floored to a
whole number, computed from the two stored integers, so 5 of 6 is 83 %. A reader who sees 83 % should be
able to recompute it exactly.

Add `--check` (no writes; exit 1 on any difference) and `--write` modes, and the `make status` target.

Insert the marker pair into `README.md` around a first generated Status block, and run the generator so
`docs/status.json` and the block exist.

Create `tests/unit/test_status_report.py` covering every behaviour above — including the zero-collected
tier, the floor-rounding boundary, and the idempotence of two consecutive runs — plus a drift test
asserting `status_report.py --check` exits 0 on the committed tree.
  </action>
  <acceptance_criteria>
    - `uv run python scripts/status_report.py --write && uv run python scripts/status_report.py --check; echo $?` prints `0`.
    - Running `--write` twice leaves `git diff --exit-code docs/status.json README.md` exiting 0.
    - `python3 -c "import json; d=json.load(open('docs/status.json')); assert isinstance(d['tests']['unit']['collected'], int); assert all(isinstance(p['completed'], int) and isinstance(p['total'], int) for p in d['phases'])"` exits 0.
    - `uv run pytest tests/unit/test_status_report.py -q -W error::RuntimeWarning` exits 0 with at least 8 tests collected.
    - `grep -c 'status_report' Makefile` returns at least 2.
    - `uv run mypy scripts/ && uv run ruff check .` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run python scripts/status_report.py --write && uv run python scripts/status_report.py --check && uv run pytest tests/unit/test_status_report.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>An integer produced by the test suite reaches the README through a script and a JSON file, and regenerating it changes nothing — the drift between the code and the claim is now structurally impossible rather than merely discouraged.</done>
</task>

<task type="auto">
  <name>Task 2: the architecture diagram and its renderer</name>
  <files>docs/architecture.mmd, docs/architecture.svg, scripts/render_diagram.py, Makefile, tests/unit/test_architecture_diagram.py</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 11 (lines 828-851) — the verified mermaid render (71,118-byte SVG in 1.36 s), the puppeteer-config generation, and the platform-specific executable path that must not be hard-coded
    - `07-RESEARCH.md` §Architecture Patterns "System Architecture Diagram" (lines 193-243) — the ASCII overview this diagram mirrors, including the prod and monitoring profile boundaries
    - `07-RESEARCH.md` §Package Legitimacy Audit — the puppeteer postinstall finding behind the download-suppression flag
    - `Makefile:1-73` — target conventions
  </read_first>
  <action>
Write `docs/architecture.mmd` as the reviewable source of the system diagram: the two external sources
(OpenTable over httpx, Resy through the Playwright pool) into the poller; Kafka as the spine with the
five topics; the state machine's tri-state diff and confirmation re-poll; Redis carrying the ZSET
scheduler, the state hashes and both idempotency layers; TimescaleDB with its two hypertables; the
notifier's three channels; the API with SSE; the web PWA; and, as a separate subgraph, the monitoring
profile with Prometheus, the two exporters and Grafana. Label the boundary between what runs in the
`prod` profile and what runs in `monitoring`. Keep node labels short enough to render legibly at README
width.

Create `scripts/render_diagram.py`: use the Playwright sync API to read `chromium.executable_path`, write
a puppeteer config JSON naming that executable and the shared-memory workaround flag, then invoke the
mermaid CLI through `npx` at the pinned version with the puppeteer download suppressed, rendering
`docs/architecture.mmd` to `docs/architecture.svg` with a transparent background. Fail loudly with an
actionable message when Chromium is absent — a silently skipped render leaves a stale SVG next to a
changed source, which is exactly the drift a committed diagram is supposed to avoid.

Commit both the `.mmd` and the rendered `.svg`. Add `make docs` invoking the renderer.

Create `tests/unit/test_architecture_diagram.py`: assert `docs/architecture.mmd` exists, parses as a
mermaid graph declaration, and names every service and datastore the compose `prod` and `monitoring`
profiles define (read the service list from `ops/docker-compose.yml` rather than hard-coding it, so a new
service fails this test until it appears in the diagram); assert `docs/architecture.svg` exists, is
non-empty, and its root element is an `svg`. Add the non-vacuity assertion: at least 8 node labels
extracted from the `.mmd` source.
  </action>
  <acceptance_criteria>
    - `make docs` exits 0 and `docs/architecture.svg` is larger than 10,000 bytes.
    - `python3 -c "import xml.etree.ElementTree as ET; r=ET.parse('docs/architecture.svg').getroot(); assert r.tag.endswith('svg')"` exits 0.
    - `uv run pytest tests/unit/test_architecture_diagram.py -q -W error::RuntimeWarning` exits 0.
    - Re-running `make docs` and then `git diff --stat docs/architecture.svg` shows no semantic change beyond any embedded id salt (record in the SUMMARY if the renderer is not byte-stable).
    - `uv run mypy scripts/` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>make docs && uv run pytest tests/unit/test_architecture_diagram.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>The architecture is a reviewable text file that renders to a committed SVG, and a service that exists in compose but not in the diagram fails a test.</done>
</task>

<task type="auto">
  <name>Task 3: the portfolio README, the talking points, and the honesty guard</name>
  <files>README.md, CONTRIBUTING.md, tests/unit/test_readme_status_guard.py</files>
  <read_first>
    - `README.md` (whole file) — its heading spine and voice: `## Status`, `## Architecture`, `## Key design decisions (as implemented)`, `## Tech stack`, `## Quickstart`, `## Repository layout`, `## Detailed status` with its four subsections, `## Legal & Ethical Scraping`, `## Why Kafka for ~400 Events/Day?`, `## Operations Runbook`
    - `README.md:306` — the line naming the old Kafka image, which the 07-02 migration invalidated
    - `README.md:298-322` — the known-rough-edges list, several entries of which later phases have fixed (the testcontainers Kafka fixture now uses the Confluent image; verify each entry against the tree before repeating it)
    - `docs/HUMAN-ACTIONS.md` from 07-05 — the consolidated gate list the Status section cites
    - `.planning/deferred-items.md` — the tooling quirks and deferred fixes the rough-edges section must mention honestly, including the `slot_key` injectivity item and the poller `gather` sibling-task leak
    - `.planning/PROJECT.md` and `.planning/ROADMAP.md` — the core value statement and the phase goals the talking points draw on
    - `07-04-SUMMARY.md` — the exact local Grafana dashboard URL to link
    - `scripts/replay_raw.py` and `tests/fixtures/raw_streams/` — the real fixture paths the replay walkthrough must use
  </read_first>
  <action>
Rewrite `README.md` keeping its heading spine and its voice. Changes, section by section:

`## Status` — the generated block from Task 1 between its markers, with the live-demo line carrying the
literal placeholder token the orchestrator replaces after the Vercel deploy, and a one-line pointer to
`docs/HUMAN-ACTIONS.md`.

`## Architecture` — embed `docs/architecture.svg` and keep a compact ASCII overview beneath it for
readers viewing the file as plain text. Describe the two compose profiles and what each contains.

`## Quickstart` — the current infra commands plus the new ones: `make images`, `make up-prod`,
`make up-monitoring`, `make smoke`, `make status`, `make docs`. State the one-time Kafka volume reset.

`## Observability` (new) — the five DEPLOY-05 panels, the local dashboard URL from 07-04, and an explicit
line stating that the hosted public dashboard (Grafana Cloud) and the uptime monitor are pending-human
with their runbook paths.

`## Legal & Ethical Scraping` — refresh in place: keep the NY Restaurant Reservation Anti-Piracy Act
(Feb 2025) citation and the public-data-only, no-booking-automation posture, and update the rate-limit
numbers to the values the code actually enforces (the Resy 80 requests-per-minute cap and the
per-restaurant interval floor from Phase 3).

`## Why Kafka for ~400 Events/Day?` — keep the honest tradeoff argument; add what the phase now proves,
namely the replay determinism goldens and the consumer-lag gate.

`## Replay walkthrough` — real commands against the committed fixtures, showing the byte-identity claim
being checked rather than asserted.

`## Interview talking points` (new) — exactly-once versus at-least-once and why deterministic event ids
plus two idempotency layers were chosen over transactions; the Redis ZSET scheduler with atomic Lua and
what the expedite handshake buys; stream-based confirmation instead of an inline sleep; Playwright pool
economics and the soft-ban canary; the two-layer idempotency boundary; and the honest tradeoffs —
single-broker RF=1, no tracing, a poller image that is 4.59 GB, and the fact that the hardest remaining
problems are human-gated rather than technical.

`## Detailed status` — keep the four subsections, and verify every claim in them against the tree rather
than carrying it forward. Correct the Kafka image line, drop rough edges that later phases fixed, and add
the ones `.planning/deferred-items.md` records.

Update `CONTRIBUTING.md` with the compose profiles, the six CI jobs, the Make targets this phase added,
and the one-time volume reset.

Create `tests/unit/test_readme_status_guard.py`. Strip HTML comments and fenced code blocks before
scanning, so an explanatory comment can neither satisfy nor break a gate. Assert: every integer that
appears immediately before the word `passed` or `collected` inside the generated Status block also
appears as a value in `docs/status.json`; the placeholder token appears at most once and only on the
live-demo line; every `docs/` path referenced by the README resolves on disk; the README contains no
sentence asserting a live hosted deployment without an adjacent pending-human qualifier, checked against
a small list of hosted-capability phrases each of which must occur within two lines of the word
`pending`; and the phrase reserved for the legal footer appears only inside the
`## Legal & Ethical Scraping` section. Add the non-vacuity assertion: at least 10 headings parsed and at
least 3 integers extracted from the Status block.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_readme_status_guard.py -q -W error::RuntimeWarning` exits 0 with at least 6 tests collected.
    - `uv run python scripts/status_report.py --check` exits 0 against the rewritten README.
    - `python3 -c "import re,pathlib; t=pathlib.Path('README.md').read_text(); p=set(re.findall(r'docs/[\w./-]+\.(?:md|svg|json|mmd)', t)); missing=[x for x in p if not pathlib.Path(x).exists()]; print(missing); assert not missing"` exits 0.
    - `grep -c 'bitnami' README.md` returns 0.
    - `grep -c 'Interview talking points' README.md` returns 1 and `grep -c 'HUMAN-ACTIONS.md' README.md` returns at least 1.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0 and `uv run ruff check .` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_readme_status_guard.py tests/unit/test_status_report.py -q -W error::RuntimeWarning && uv run python scripts/status_report.py --check</automated>
  </verify>
  <done>The README describes exactly what this repository does, every number in it came from a script, every hosted capability it mentions is marked pending-human, and a guard test keeps all three true.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| repository → public reader | The README is the project's public claim surface; an overstatement is a reputational defect, not a cosmetic one. |
| generator → committed docs | `status_report.py` writes into `README.md` and `docs/status.json`; a bug there silently rewrites the public claim. |
| npx → build machine | The mermaid CLI pulls a transitive dependency whose postinstall downloads a browser binary. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-07-30 | Repudiation | README claims | high | mitigate | Every count is generated; the guard test asserts equality with `docs/status.json`, that hosted-capability phrases sit next to a pending qualifier, and that every referenced doc path resolves. |
| T-07-31 | Tampering | generated README region | medium | mitigate | The generator owns exactly one marker-delimited block and touches nothing else; `--check` fails a commit whose block drifted from the sources. |
| T-07-32 | Information disclosure | committed docs | medium | mitigate | The README cites `docs/HUMAN-ACTIONS.md`, which is already gated against personal data (07-05); no credential, account id or personal address is introduced here. |
| T-07-SC | Tampering | `@mermaid-js/mermaid-cli` via `npx` and its `puppeteer` transitive | high | mitigate | Pinned version invoked at documentation-build time only, never a shipped dependency; the puppeteer install-time browser download is suppressed and the existing Playwright Chromium is used instead; legitimacy verdict recorded in `<package_legitimacy>` and restated in the SUMMARY. |
</threat_model>

<verification>
1. `uv run pytest tests/unit -q -W error::RuntimeWarning` — exit 0, including all three new guards.
2. `uv run python scripts/status_report.py --check` — exit 0 on the committed tree.
3. `make docs` — exit 0; `docs/architecture.svg` parses as SVG.
4. Every `docs/` path referenced by the README and by `docs/HUMAN-ACTIONS.md` resolves on disk.
5. `uv run ruff check . && uv run mypy shared/ services/ scripts/` — exit 0.
6. Full phase gate: `uv run pytest tests/unit tests/integration -q -p no:cacheprovider`, `make smoke`, `make images`, and `terraform -chdir=terraform validate` all exit 0.
</verification>

<success_criteria>
- The README carries a diagram, a demo link placeholder, the local dashboard URL, refreshed legal and Kafka sections, a replay walkthrough with real commands, and interview talking points.
- Every number in the Status section came from `docs/status.json`, and regeneration is a no-op.
- Every human-gated item is listed with its runbook path, and no hosted capability is claimed without a pending-human qualifier.
- `CONTRIBUTING.md` reflects the profiles, jobs and targets this phase introduced.
</success_criteria>

<output>
Create `.planning/phases/07-deploy-observability-portfolio-polish/07-08-SUMMARY.md` when done.
Record: the `@mermaid-js/mermaid-cli` legitimacy verdict, the final per-tier test counts from
`docs/status.json`, whether the SVG render is byte-stable across runs, the exact placeholder token left
for the orchestrator to replace, and the complete human-gated list as rendered in the README.
</output>
