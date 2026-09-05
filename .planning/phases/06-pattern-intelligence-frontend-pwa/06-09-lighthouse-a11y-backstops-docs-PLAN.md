---
phase: 06-pattern-intelligence-frontend-pwa
plan: 09
type: execute
wave: 9
depends_on: ["06-08"]
files_modified:
  - web/scripts/lighthouse.mjs
  - web/src/lib/sw-artifact.test.ts
  - web/src/app/a11y.test.tsx
  - web/src/app/backstops.test.tsx
  - web/src/components/tap-targets.test.tsx
  - web/README.md
  - README.md
  - .env.example
  - docs/runbooks/ios-pwa-push.md
  - docs/runbooks/lighthouse-p75.md
  - docs/api.md
  - Makefile
autonomous: true
requirements: [FE-07, FE-01]

estimate:
  tokens: 86000
  raw_tokens: 86000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "FE-07 boundary probe: the Lighthouse gate runs the mobile preset five times against a production build served by the start command, prints all five largest-contentful-paint values, and exits 1 when the MEDIAN exceeds the budget and 0 when it does not — a budget forced below the observed value must produce a non-zero exit (D-111a, RESEARCH OQ-7)."
    - "FE-07 precision probe: the gate throws on a Lighthouse runtime error instead of comparing a null value, because a null comparison silently passes and reports a perfect score for a page that never painted (RESEARCH Pitfall 5)."
    - "The gate launches the Playwright headless shell binary specifically; the full Chrome for Testing build returns no-first-contentful-paint under this Lighthouse version and every score comes back zero. The path is overridable by an environment variable (D-111a)."
    - "FE-01 probe: a test asserts the generated service worker file exists after a build and that its source contains a push listener and a notification-click listener — a build that silently emitted no worker fails the suite (BC-1, RESEARCH Pitfall 1)."
    - "FE-07 tap targets: a held-out test renders every route shell and asserts every interactive element carries the 44 px minimum classes, with the single documented exception of heatmap cells (UI-SPEC A-5, WCAG 2.5.8 Essential)."
    - "FE-07 accessibility: axe runs over all six route shells — home, restaurant detail, watch setup, manage, alert landing and offline — and the violation list is empty on each. The contrast rule is disabled in this environment and contrast is instead evidenced by the Lighthouse accessibility category, which is stated explicitly so 'we check contrast with axe' never becomes a false claim (D-111, D-118, RESEARCH axe note)."
    - "Backstop — zero, one, many: every count string is correct at 0, 1, 2 and 50 across the feed, the watch list, the notification history and the search results, including the singular and plural forms of the social-proof counter, the party label that never pluralises its noun, the openings count and the paused-updates pending count (UI-SPEC UI Considerations)."
    - "Backstop — long text: a 900-character pattern summary wraps at the prose measure, never truncates and never overflows its card (UI-SPEC UI Considerations)."
    - "Backstop — overflow and zoom: no horizontal scroll and no content loss at a 320 px viewport width and at 200 percent zoom on all five routes; the heatmap's scaling is the main risk surface and is asserted explicitly (UI-SPEC UI Considerations)."
    - "`web/README.md` documents the environment variables, the one-time legacy-peer-resolution install need, the reason no bundler flag is ever passed, and that the public environment values are inlined at build time so a change on the host requires a redeploy, not a restart (D-109a, D-110, BC-9, BC-10)."
    - "`web/` is deployable as a project rooted at `web/` with no additional deployment config file; the README records the deploy command, that the first deployment of a new project is a production deployment, and that the public environment variables must exist on the host BEFORE the first build (RESEARCH Vercel section, BC-10)."
    - "`.env.example` gains a frontend section naming the three public variables with the build-time-inlining caveat, and amends the public base URL entry to state that it is now the WEB origin because notification links point at the frontend landing page (D-116, D-110)."
    - "The iOS push runbook is updated with the exact steps for five consecutive pushes and retains its pending-human status; a new Lighthouse runbook records the production p75 procedure and is also pending-human (D-117, D-111)."
    - "Every remaining human-gated item is a line in a runbook with a pending-human status, not a silent omission: the real-iPhone five-push validation, the production Lighthouse p75, and the host environment variables for a deployed API."
  artifacts:
    - web/scripts/lighthouse.mjs
    - web/src/lib/sw-artifact.test.ts
    - web/src/app/a11y.test.tsx
    - web/src/app/backstops.test.tsx
    - web/src/components/tap-targets.test.tsx
    - web/README.md
    - docs/runbooks/lighthouse-p75.md
    - docs/runbooks/ios-pwa-push.md
    - .env.example
  key_links:
    - "`make lighthouse` builds, starts the production server, runs the gate against it and tears the server down — it is the only place the production server is exercised in this phase."
    - "The backstop suite is held out: it renders the finished route shells from 06-05 through 06-08 rather than component fixtures, so a regression in any of them fails here."
    - "`web/README.md` and `.env.example` are what the orchestrator's post-phase deploy step reads; the deploy itself is not a task in any plan."
  prohibitions:
    - "The Lighthouse gate never compares a null value against the budget — a runtime error throws."
    - "The gate never launches the full browser build; only the headless shell binary is used."
    - "No test in this phase is skipped, marked to-do, or guarded by anything other than a genuine environment check (the Lighthouse gate may skip only when the headless shell binary is genuinely absent, and must say so loudly)."
    - "The accessibility claim never states that contrast was verified by axe in this environment."
    - "No runbook records a human-gated step as complete; each keeps a pending-human status until a person performs it."
  flagged_assumptions:
    - "RESEARCH A8: a five-run local median under the mobile preset is a lab number, not the field p75 the requirement names. The honest claim in the summary is 'lab median LCP under the mobile preset'; the production p75 stays pending-human in the new runbook."
    - "RESEARCH A1/A2: no deployment config file is assumed necessary because the framework is auto-detected and the project root can be set to `web/`. A failed first deploy is visible immediately and fixed by setting the root directory."
    - "UI-SPEC unresolved items carried into the visual audit: long restaurant names beyond the seed's 20-character maximum may truncate awkwardly in feed rows and search results, and the heatmap viewBox has no max-width so cells become airy above the content width and axis labels approach illegibility below 320 px."
---

<objective>
Close the phase: prove the performance and accessibility budgets mechanically, pin the four held-out backstops the
UI-SPEC named, and write down every environment variable, install quirk and human-gated step so the deploy that
follows this phase is a matter of running one command.

Purpose: FE-07 is the only requirement in this phase with a number attached, and the only honest way to claim it
locally is a repeatable, median-of-five lab measurement that fails loudly rather than passing on a null. Everything
else here is the difference between a phase that works on this machine and a phase someone else can run.

Output: the Lighthouse gate and its make target, the service-worker artifact test, the held-out accessibility and
backstop suites, and the documentation and runbooks.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-08-SUMMARY.md
@CLAUDE.md
</context>

## Artifacts this phase produces (this plan's share)

| Kind | Artifact | Notes |
|------|----------|-------|
| script | `web/scripts/lighthouse.mjs` | mobile preset, five runs, median gate, throws on a runtime error |
| make target | `lighthouse` | build, start, measure, tear down |
| test | `src/lib/sw-artifact.test.ts` | the generated worker exists and has both handlers |
| test | `src/app/a11y.test.tsx` | axe over all six route shells |
| test | `src/app/backstops.test.tsx` | zero-one-many, long text, viewport and zoom |
| test | `src/components/tap-targets.test.tsx` | 44 px sweep with the documented heatmap exception |
| docs | `web/README.md` | env vars, install quirk, no-bundler-flag rule, deploy notes |
| docs | `.env.example` frontend section | three public names plus the build-time-inlining caveat |
| runbook | `docs/runbooks/lighthouse-p75.md` | pending-human production p75 procedure |
| runbook | `docs/runbooks/ios-pwa-push.md` | updated five-consecutive-push steps, still pending-human |

<tasks>

<task type="auto">
  <name>Task 1: The Lighthouse budget gate and the service-worker artifact proof</name>
  <files>web/scripts/lighthouse.mjs, web/src/lib/sw-artifact.test.ts, Makefile</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Code Examples → "Lighthouse gate" (the executed script with both exit paths proven, the headless-shell path, and the runtime-error throw) and §Common Pitfalls → Pitfall 5 (the four launch variants measured and why only one works) and Pitfall 1 (the silent missing worker)
    - `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-06/web/scripts/lighthouse.mjs` — the executed script to copy
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-111 (the budget and that the production run is human-gated), D-111a (headless shell, mobile preset, median of five, exit 1 above the budget)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md` → "`web/scripts/lighthouse.mjs`" and "`Makefile` (modified)" — the copy instruction, the median delta, and the `.PHONY` plus doc-comment convention
    - `Makefile` — the existing target style and the web targets added in 06-04
  </read_first>
  <action>
Copy the executed research script into `web/scripts/lighthouse.mjs`, then apply the median delta. The script reads
its target URL and its budget from environment variables with the documented defaults, resolves the browser binary
from an environment variable falling back to the Playwright headless-shell path, and launches with the no-sandbox and
disable-gpu flags. Run Lighthouse five times with the performance and accessibility categories only. After each run,
throw immediately if the result carries a runtime error — never compare a possibly-null largest-contentful-paint
value against the budget, because a null comparison is false and the gate would report a pass for a page that never
painted. Collect the five rounded values, print all five plus the median, the form factor, the performance score and
the accessibility score as JSON on standard output, and set a non-zero exit code when the MEDIAN exceeds the budget.
Print the pass or fail line on standard error so the JSON on standard output stays machine-readable.

If the headless-shell binary is genuinely absent, exit with a distinct non-zero code and a message naming the
environment variable to set. Do not silently skip and do not fall back to the full browser build, which returns
no-first-contentful-paint under this Lighthouse version.

Add a `lighthouse` target to the Makefile that builds the production bundle, starts the production server on a fixed
port in the background, waits for it to answer, runs the script against it, and tears the server down in a trap so a
failing run never leaves a process behind. Add it to the `.PHONY` list with a doc comment, and write the multi-line
rationale comment above it recording that the number this produces is a LAB MEDIAN under the mobile preset, not the
field p75 the requirement names, and that the p75 claim stays human-gated.

`web/src/lib/sw-artifact.test.ts`: read the generated service worker from disk and assert it exists and that its
source contains a push listener and a notification-click listener. If the file is absent the test must fail with a
message naming the build step and the bundler-flag correction, because that is the failure mode this test exists to
catch. Skip only when a build has genuinely not been run in this working tree, and make that condition explicit and
loud rather than a silent pass.
  </action>
  <acceptance_criteria>
    - `make lighthouse` exits 0 and prints five largest-contentful-paint values plus a median.
    - `cd web && LH_LCP_BUDGET_MS=1 node scripts/lighthouse.mjs` exits non-zero (the gate fails when the budget is impossible).
    - `cd web && npm run build && npm test -- src/lib/sw-artifact.test.ts` exits 0.
    - `grep -c 'runtimeError' web/scripts/lighthouse.mjs` is at least 1.
    - `grep -c 'chrome-headless-shell' web/scripts/lighthouse.mjs` is at least 1 and `grep -c 'Google Chrome for Testing' web/scripts/lighthouse.mjs` equals 0.
    - `make help` lists `lighthouse`.
  </acceptance_criteria>
  <verify>
    <automated>make lighthouse</automated>
  </verify>
  <done>The performance budget is a command that fails loudly, and a build that emits no service worker is a red test.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Held-out accessibility sweep, tap-target sweep and the four UI-SPEC backstops</name>
  <files>web/src/app/a11y.test.tsx, web/src/app/backstops.test.tsx, web/src/components/tap-targets.test.tsx</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §UI Considerations — the four backstop rows verbatim (zero-one-many, feed burst overflow, viewport and zoom overflow, long-text summary) and the two unresolved rows to flag rather than fix
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Accessibility Contract (all sections), §Copywriting Contract → the count strings, §Component Inventory item 6 (the heatmap tap-target exemption and its rationale)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Code Examples → "axe in a component test" — the direct axe call and why the contrast rule is disabled in this environment
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-111 (axe on each page shell), D-118 (the unit test list)
    - The six route shells built in 06-04 through 06-08 and their fixture modules under `web/src/test/fixtures/`
  </read_first>
  <behavior>
    - axe over each of the six route shells — home, restaurant detail, watch setup, manage, alert landing and offline — returns an empty violation list, with the contrast rule disabled.
    - Rendering every route shell and querying every interactive element yields zero elements missing the 44 px minimum classes, with heatmap gridcells excluded by an explicit, commented exception.
    - Zero, one, many: the social-proof counter reads correctly at 1 and at 2; the party label reads Table for 1 and Table for 2 with the noun never pluralised; an openings count reads correctly at 1 and at many; the paused-updates label reads correctly at 1 pending and at several; the feed, watch list, notification history and search results each render correctly at 0, 1, 2 and 50 items.
    - Long text: a 900-character pattern summary renders fully, is not truncated, and its container carries the prose measure rather than a fixed height.
    - Overflow and zoom: at a 320 px viewport width every route renders without a horizontally scrolling container, and the heatmap's SVG scales rather than overflowing; the same holds with a 200 percent root font size.
    - Every assertion names the UI-SPEC row it is discharging in its test name.
  </behavior>
  <action>
`src/app/a11y.test.tsx`: render each of the six route shells with a stubbed global fetch over the typed fixtures and
run axe directly over each container, asserting the violation id list is empty. Disable the contrast rule and write
the comment recording precisely why: this environment computes no layout and resolves no custom properties, so an axe
contrast result here would be meaningless, and contrast is evidenced instead by the Lighthouse accessibility category
in Task 1. Do not claim contrast coverage anywhere in this file's names or messages.

`src/components/tap-targets.test.tsx`: render each route shell, collect every interactive element, and assert each
carries both 44 px minimum classes. Exclude elements with the gridcell role and add the comment recording the WCAG
2.5.8 Essential exemption and the equivalent-information path — the per-cell accessible names and the pattern card
prose. Add a guard-the-guard assertion that the collected element count is greater than a realistic floor so a broken
query cannot make the sweep vacuous.

`src/app/backstops.test.tsx`: the four held-out backstops, each named after its UI-SPEC row.
For zero-one-many, render each list surface at 0, 1, 2 and 50 items and assert the exact count strings, including the
counter's singular and plural forms and the party label's non-pluralising noun.
For long text, render the pattern card with a 900-character summary and assert the full string is present in the
rendered text and that no truncation class is applied to its container.
For overflow and zoom, render each route inside a 320 px-wide container and assert no element reports a scroll width
exceeding its client width, then repeat with a doubled root font size. Where this environment cannot measure layout,
assert the structural property instead — that the heatmap SVG declares a percentage width and an automatic height and
carries no fixed pixel width — and say so in the test name so the claim is not overstated.
The feed-burst overflow backstop already lives in the reducer test from 06-06; reference it by name in a comment here
rather than duplicating it.

Record the two UI-SPEC unresolved rows as comments at the top of the backstop file, naming them as carried
assumptions for the visual audit rather than as covered behaviour.
  </action>
  <acceptance_criteria>
    - `cd web && npm test -- src/app/a11y.test.tsx src/app/backstops.test.tsx src/components/tap-targets.test.tsx` exits 0.
    - The a11y test covers exactly six route shells, asserted by a count in the test itself.
    - `grep -c 'gridcell' web/src/components/tap-targets.test.tsx` is at least 1 (the documented exception is explicit).
    - `grep -ci 'contrast' web/src/app/a11y.test.tsx` is at least 1 and the file states contrast is covered by the Lighthouse category, not by axe here.
    - `grep -cE '\b(it|test)\.(skip|todo)\b|describe\.skip' web/src/app/backstops.test.tsx web/src/app/a11y.test.tsx web/src/components/tap-targets.test.tsx` equals 0.
    - `cd web && npm test` exits 0 (the whole frontend suite).
  </acceptance_criteria>
  <verify>
    <automated>cd web && npm test -- src/app/a11y.test.tsx src/app/backstops.test.tsx src/components/tap-targets.test.tsx</automated>
  </verify>
  <done>Six route shells pass axe, every interactive element clears 44 px with one documented exception, and the four UI-SPEC backstops are held-out tests rather than intentions.</done>
</task>

<task type="auto">
  <name>Task 3: Environment documentation, deploy readiness and the two pending-human runbooks</name>
  <files>web/README.md, README.md, .env.example, docs/runbooks/ios-pwa-push.md, docs/runbooks/lighthouse-p75.md, docs/api.md</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-110 (the three public environment variables and their roles), D-110a (build-time inlining and the offline-build gate), D-109a (the one-time legacy-peer-resolution install and the no-bundler-flag rule), D-117 (the push flow the runbook validates)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Code Examples → "Vercel deploy" (the deploy command, that the first deployment is production, the root-directory option, that no deployment config file is required, and that the public variables must exist before the first build) and §Environment Availability (what is present on this machine and what is not)
    - `docs/runbooks/resy-cookie-capture.md` and `docs/runbooks/perf02-24h-log.md` — the repo's runbook shape and the pending-human status banner style to copy
    - `docs/runbooks/ios-pwa-push.md` as Phase 4 shipped it — the existing steps this task extends
    - `.env.example` — the section-header style and the long why-this-is-not-configurable comment style
    - `README.md` — where the frontend belongs in the existing structure
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-04-SUMMARY.md` — the recorded package audit and the image hostnames, to reference rather than restate
  </read_first>
  <action>
`web/README.md`: the project's frontend entry point. Document the three public environment variables, what each is
for, and their defaults. Add a prominent note that these values are INLINED into the client bundle at build time —
changing one on a hosting platform requires a redeploy, not a restart, and a secret must never be given one of these
names. Document the one-time legacy-peer-resolution flag needed for the initial dev-dependency install on this npm
version, and that the routine install target uses a clean install without it. State plainly that no script passes a
bundler flag and why: with it the build exits 0 and emits no service worker at all, which is a working-looking build
with no push notifications. List the commands: install, dev, build, test, typecheck, lint, and the two make targets
that matter (the offline build gate and the Lighthouse gate). Add a deploy section: the project deploys as a project
rooted at `web/` with no additional deployment config file, the first deployment of a new project is a production
deployment, and the public environment variables must exist on the host BEFORE the first build. State that the deploy
itself is a step taken after this phase, not part of it.

`README.md` at the repo root: add a short frontend section pointing at `web/README.md`, naming the routes the PWA
serves and the two make targets, so a reader of the portfolio README can find the frontend.

`.env.example`: add a `# Frontend (web/)` section with the three public names, their defaults, and the build-time
inlining caveat written in the file's existing explanatory style. Amend the public base URL entry from Phase 4 to
record that it is now the WEB origin, because notification deep links point at the frontend landing page which then
calls the API — reference the decision id.

`docs/runbooks/ios-pwa-push.md`: keep the pending-human status banner and extend it with the exact procedure for the
five-consecutive-push validation — install to the Home Screen, open from the Home Screen, complete the watch flow and
enable notifications, then trigger five sends and record each arrival with a timestamp, plus what to check if a push
stops arriving (the revocation counter and the subscription's revoked timestamp). Name the two implementation facts
that make or break it: the handler wraps its entire chain and the notification body is never empty.

`docs/runbooks/lighthouse-p75.md`: a new runbook with the pending-human status banner covering the production p75
measurement — the deployed URL, the field-data source, why the local number is a lab median and not a p75, and the
threshold that must be met. Record the local median measured in Task 1 as the current evidence.

`docs/api.md`: add a short note that the frontend is typed against this document and the OpenAPI snapshot, so a route
or field change here must be mirrored in the frontend api client module.

Every human-gated item in this phase must end up as a pending-human line in one of these runbooks: the real-iPhone
five-push validation, the production p75, and the host environment variables for a deployed API. None of them may be
recorded as complete.
  </action>
  <acceptance_criteria>
    - `grep -c 'NEXT_PUBLIC_API_BASE_URL' web/README.md .env.example` is at least 1 in each file.
    - `grep -ci 'inlined at build' web/README.md` is at least 1 and `grep -ci 'inlined' .env.example` is at least 1.
    - `grep -c 'STATUS: pending-human' docs/runbooks/ios-pwa-push.md docs/runbooks/lighthouse-p75.md` is at least 1 in each file.
    - `grep -ci 'web/README.md' README.md` is at least 1.
    - `grep -ci 'legacy-peer-deps' web/README.md` is at least 1.
    - `uv run pytest tests/unit -x -q -W error::RuntimeWarning` and `cd web && npm test` both exit 0.
    - `make web-build-offline && make lighthouse` both exit 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit -x -q -W error::RuntimeWarning && cd web && npm test && npm run build && npm run lint && npm run typecheck</automated>
  </verify>
  <done>Someone who has never seen this repository can install, run, test and deploy the frontend from the documentation, and every step no machine can take is a pending-human line in a runbook.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| documentation → operator action | the README and runbooks tell a person which values to set on a hosting platform |
| local measurement → published claim | a lab number is the evidence behind a stated performance budget |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-06-46 | Information disclosure | a secret documented under a public environment prefix | critical | mitigate | The README states explicitly that these three values are inlined into the client bundle and that a secret must never carry the prefix; the 06-04 gate enforces the three-name allowlist mechanically |
| T-06-47 | Repudiation | a performance claim resting on a null measurement | high | mitigate | The gate throws on a Lighthouse runtime error rather than comparing a null value, and prints all five runs so the median is auditable |
| T-06-48 | Repudiation | a lab median presented as a field p75 | medium | mitigate | The make target's comment, the runbook and the phase summary all state that the local number is a lab median under the mobile preset and that the p75 claim is human-gated |
| T-06-49 | Spoofing | a build shipping without a service worker | high | mitigate | The artifact test asserts the generated worker exists and carries both handlers, and fails loudly rather than skipping |
| T-06-50 | Tampering | an accessibility claim that was never checked | medium | mitigate | The axe suite covers six route shells with an explicit statement of what it does NOT cover in this environment, and the Lighthouse accessibility category supplies the contrast evidence |
| T-06-SC | Tampering | npm installs | high | mitigate | This plan installs nothing; the Lighthouse and browser-launcher packages were pinned and audited in 06-04. Recorded in the SUMMARY |
</threat_model>

<verification>
- `make lighthouse` — five runs, median under budget
- `make web-build-offline`
- `cd web && npm test && npm run typecheck && npm run lint && npm run build`
- `uv run pytest tests/unit -x -q -W error::RuntimeWarning`
- `uv run pytest tests/integration -q -p no:cacheprovider`
- `uv run ruff check . && uv run mypy shared/ services/ scripts/`
</verification>

<success_criteria>
- The Lighthouse gate passes on the median of five runs and provably fails when the budget is impossible.
- The generated service worker is asserted present with both handlers after a build.
- axe is clean on six route shells, every interactive element clears 44 px except heatmap cells, and the four UI-SPEC backstops are green.
- The frontend is documented well enough to deploy from a clean clone, and every human-gated step is a pending-human runbook line.
</success_criteria>

<output>
Create `.planning/phases/06-pattern-intelligence-frontend-pwa/06-09-SUMMARY.md` when done.
Record the five measured largest-contentful-paint values and their median, state the claim as a lab median under the
mobile preset rather than a field p75, and list the three remaining human-gated items with the runbook that carries
each one.
</output>
