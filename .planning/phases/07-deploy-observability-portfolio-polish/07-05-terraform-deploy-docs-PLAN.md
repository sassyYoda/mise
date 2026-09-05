---
phase: 07-deploy-observability-portfolio-polish
plan: 05
type: execute
wave: 3
depends_on: ["07-02"]
autonomous: true
requirements: [DEPLOY-02, DEPLOY-06]
files_modified:
  - terraform/versions.tf
  - terraform/variables.tf
  - terraform/main.tf
  - terraform/outputs.tf
  - terraform/.terraform.lock.hcl
  - terraform/modules/cloud_run_api/main.tf
  - terraform/modules/cloud_run_worker_pool/main.tf
  - terraform/modules/network/main.tf
  - terraform/modules/memorystore/main.tf
  - terraform/modules/artifact_registry/main.tf
  - terraform/modules/secrets/main.tf
  - terraform/modules/kafka_vm/main.tf
  - terraform/modules/timescale_vm/main.tf
  - .gitignore
  - docs/deploy/gcp.md
  - docs/runbooks/uptime.md
  - docs/HUMAN-ACTIONS.md
  - docs/PHASE-01-HUMAN-ACTIONS.md
  - tests/unit/test_pending_human_banners.py

estimate:
  tokens: 70000
  raw_tokens: 70000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "D-119: `terraform -chdir=terraform init -backend=false -input=false` and `terraform -chdir=terraform validate` both exit 0 with zero GCP credentials present, and `terraform -chdir=terraform fmt -check -recursive` exits 0."
    - "D-119: every file under `terraform/` carries the banner `STATUS: pending-human — not applied` and at least one `TODO(human)` marker, enforced by `tests/unit/test_pending_human_banners.py`. The skeleton declares the topology; it never provisions it."
    - "DEPLOY-02: the module set covers every infrastructure element the requirement names — `network` (VPC), `memorystore` (Redis), `artifact_registry`, `secrets` (Secret Manager), `kafka_vm` and `timescale_vm` (GCE), `cloud_run_api`, and `cloud_run_worker_pool` (polling / state / dispatcher / notification workers)."
    - "DEPLOY-02 probe (empty — *what is the result for empty, single-element, or null input?*): module stubs contain declarations only and no `resource` blocks, which is precisely what lets `validate` — and even `plan` — succeed with no credentials and no state. A skeleton that validates only because a provider was reachable would be a skeleton that stops validating the day the network is down."
    - "DEPLOY-02 probe (adjacency — *when two things are exactly equal or just touch, do they merge, collide, or separate?*): the root/module boundary is checked, not assumed. Every variable passed in `terraform/main.tf` must be declared in the receiving module and every referenced `output` must exist there; `validate` fails on either. A module variable declared but unused is legal and deliberate — it is the shape the future implementation must fill."
    - "DEPLOY-02 probe (ordering — *when elements compare equal, is output order specified and stable?*): `terraform fmt` owns canonical formatting and re-aligns single-line blocks, so hand-aligned HCL fails `fmt -check`. The repository commits `fmt`-canonical files and CI gates on `fmt -check -recursive`, making formatting deterministic rather than a matter of taste."
    - "D-119: `docs/deploy/gcp.md` describes the ROADMAP topology — Cloud Run for the API, Cloud Run Worker Pools or a GCE MIG for the always-on pollers, GCE VMs for Kafka KRaft and TimescaleDB, Memorystore Redis, Artifact Registry, Secret Manager — with the exact `gcloud` commands, and states plainly that nothing here has been applied."
    - "D-124 / PERF-04: `docs/runbooks/uptime.md` documents the Better Uptime monitors (`https://mise.place` and `GET /readyz`, every 60 s) as pending-human, and names `scripts/uptime_report.py` (07-06) as the tool that computes the monthly figure once data exists."
    - "D-126: `docs/HUMAN-ACTIONS.md` consolidates every phase's pending-human gate into one checklist ordered by wait time, contains no personal data (no real email address, phone number, account id or credential), and `docs/PHASE-01-HUMAN-ACTIONS.md` is superseded by it with a pointer rather than being silently deleted."
  artifacts:
    - terraform/versions.tf
    - terraform/main.tf
    - terraform/modules/cloud_run_api/main.tf
    - docs/deploy/gcp.md
    - docs/runbooks/uptime.md
    - docs/HUMAN-ACTIONS.md
    - tests/unit/test_pending_human_banners.py
  key_links:
    - "`terraform/` → the `ops-config` CI job in 07-07, which runs `fmt -check`, `init -backend=false` and `validate`. The skeleton is only a real artifact because CI proves it still validates."
    - "`docs/HUMAN-ACTIONS.md` → the README Status section (07-08), which lists every human-gated item with its runbook path. One file is the source; the README cites it."
    - "`docs/runbooks/uptime.md` → `scripts/uptime_report.py` (07-06). The runbook explains the pending-human hosted arm; the script implements the local Prometheus arm."
  prohibitions:
    - "Must never run `terraform apply`, and never add a `backend` block. Applying would create billable cloud resources that no one asked for and that nobody is watching; a backend would make even `init` require credentials."
    - "Must never place a real credential, account id, phone number or personal email address in any committed doc. Runbooks name where a value comes from, never the value."
    - "Must never describe a pending-human step as done. Every runbook and every Terraform file states its status in a banner at the top, where a reader sees it before they read anything else."
  flagged_assumptions:
    - "Terraform 1.13.0 with provider `hashicorp/google ~> 7.9` (resolved to 7.46.1) was verified on this machine. `.terraform.lock.hcl` is committed so `init` is reproducible; the 117 MB provider download is cached in CI."
    - "The module stubs describe an intended topology that has never been applied. Their `TODO(human)` comments carry the design constraints found in research (for example: the Cloud Run API service needs `min_instances = 1` and a 3600 s timeout for the SSE endpoint) so the future implementer inherits the reasoning rather than rediscovering it."
---

<objective>
Declare the GCP topology as a Terraform skeleton that validates offline, and consolidate every human-gated step in the project into one honest checklist.

Purpose: D-119 splits DEPLOY-02 into what can be truthfully delivered from here (a formatted, initialising, validating IaC skeleton whose every file says it was never applied) and what cannot (provisioning a real project). The same split governs DEPLOY-06's uptime monitoring. A portfolio repository earns credibility by being exact about that line, and by putting the line where a reader finds it first.

Output: `terraform/**` (root + eight module stubs), `docs/deploy/gcp.md`, `docs/runbooks/uptime.md`, `docs/HUMAN-ACTIONS.md`, and a banner gate that keeps every one of those files honest.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/deferred-items.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-CONTEXT.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-RESEARCH.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-PATTERNS.md
@docs/PHASE-01-HUMAN-ACTIONS.md
@docs/runbooks/perf02-24h-log.md
@docs/runbooks/twilio-10dlc-setup.md
</context>

<artifacts_this_phase_produces>
- **IaC:** `terraform/{versions,variables,main,outputs}.tf` plus eight module stubs under `terraform/modules/`, and the committed `.terraform.lock.hcl`.
- **Docs:** `docs/deploy/gcp.md`, `docs/runbooks/uptime.md`, `docs/HUMAN-ACTIONS.md` (superseding `docs/PHASE-01-HUMAN-ACTIONS.md`).
- **Tests:** `tests/unit/test_pending_human_banners.py`.
- Images/compose/workflows/metrics: none — this plan produces declarations and prose, never running infrastructure.
</artifacts_this_phase_produces>

<tasks>

<task type="tracer">
  <name>Task 1 (tracer): a root module and one service module that initialise and validate with no credentials</name>
  <files>terraform/versions.tf, terraform/variables.tf, terraform/main.tf, terraform/outputs.tf, terraform/modules/cloud_run_api/main.tf, terraform/.terraform.lock.hcl, .gitignore</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 8 (lines 701-751) — the verified `versions.tf`, the module-stub shape, the measured exit codes for `fmt`/`init -backend=false`/`validate`/`plan`, and the three gotchas
    - `.planning/ROADMAP.md` Phase 7 Success Criterion 4 — the exact infrastructure list DEPLOY-02 must cover
    - `.gitignore` — where a `terraform/` section belongs
  </read_first>
  <action>
Create `terraform/versions.tf` with `required_version = ">= 1.9.0"`, `required_providers.google` at
`source = "hashicorp/google"`, `version = "~> 7.9"`, a `provider "google"` block reading `var.project_id`,
`var.region`, `var.zone`, and an explicit comment stating that there is deliberately no `backend` block:
this skeleton is never applied, and a backend would make `terraform init` demand credentials.

Create `terraform/variables.tf` declaring `project_id`, `region` (default `us-east1`, matching the
Artifact Registry region in the Phase-1 GCP runbook), `zone`, `image_tag`, and `ghcr_owner`, each with a
`description`.

Create `terraform/modules/cloud_run_api/main.tf` as a declaration-only stub: `variable` blocks for
`project_id`, `region`, `image`, an `output "url"` with an empty-string value, the
`STATUS: pending-human — not applied` banner as the first line, and a `TODO(human)` comment naming the
resource that belongs here (`google_cloud_run_v2_service`) together with the two constraints research
recorded: `min_instances = 1` and a 3600 s request timeout so the SSE endpoint is not cut off mid-stream.
No `resource` block — that absence is what keeps `validate` credential-free.

Create `terraform/main.tf` calling that one module with values from the root variables, and
`terraform/outputs.tf` re-exporting its `url`. Both carry the status banner.

Run `terraform -chdir=terraform fmt -recursive` before committing — `fmt` re-aligns single-line blocks,
so hand-aligned HCL will otherwise fail the CI `fmt -check`. Run `terraform -chdir=terraform init
-backend=false` and commit the generated `.terraform.lock.hcl` so `init` is reproducible. Add
`terraform/.terraform/`, `*.tfstate`, `*.tfstate.*` and `.terraform.tfstate.lock.info` to `.gitignore`
(the lock file `.terraform.lock.hcl` is committed and must not be ignored).
  </action>
  <acceptance_criteria>
    - `terraform -chdir=terraform fmt -check -recursive` exits 0.
    - `terraform -chdir=terraform init -backend=false -input=false` exits 0 and prints a successful-initialisation line.
    - `terraform -chdir=terraform validate` exits 0 and prints that the configuration is valid.
    - `git status --porcelain terraform/.terraform` produces no output (the provider cache is ignored) while `git ls-files terraform/.terraform.lock.hcl` lists the lock file.
    - `grep -rL 'STATUS: pending-human' terraform --include='*.tf'` produces no output.
    - `grep -rn 'resource "' terraform/modules | wc -l` returns 0.
  </acceptance_criteria>
  <verify>
    <automated>terraform -chdir=terraform fmt -check -recursive && terraform -chdir=terraform init -backend=false -input=false && terraform -chdir=terraform validate</automated>
  </verify>
  <done>The IaC path exists end to end — root module, provider constraint, one wired module, a reproducible lock — and it proves itself with three commands that need no cloud account.</done>
</task>

<task type="auto">
  <name>Task 2: the remaining seven module stubs and the banner gate</name>
  <files>terraform/modules/cloud_run_worker_pool/main.tf, terraform/modules/network/main.tf, terraform/modules/memorystore/main.tf, terraform/modules/artifact_registry/main.tf, terraform/modules/secrets/main.tf, terraform/modules/kafka_vm/main.tf, terraform/modules/timescale_vm/main.tf, terraform/main.tf, terraform/outputs.tf, tests/unit/test_pending_human_banners.py</files>
  <read_first>
    - `terraform/modules/cloud_run_api/main.tf` from Task 1 — the stub shape every other module copies
    - `.planning/REQUIREMENTS.md` DEPLOY-01 and DEPLOY-02 (lines 81-82) — the verbatim infrastructure list
    - `07-RESEARCH.md` §Pattern 8 gotchas — every variable passed by the caller must be declared in the module and every referenced output must exist; `validate` catches both
    - `tests/unit/test_no_inline_sleep.py:18-59` — grep-gate shape with comment stripping and the non-vacuity assertion
  </read_first>
  <action>
Create seven more declaration-only module stubs under `terraform/modules/`, each with the status banner,
`variable` blocks for what its caller passes, at least one `output`, and a `TODO(human)` comment naming
the concrete Google resource type and any constraint worth inheriting:

- `network` — VPC plus the Serverless VPC Access connector Cloud Run needs to reach Memorystore and the GCE VMs.
- `memorystore` — the managed Redis instance; note that it must sit in the same region and VPC as the connector.
- `artifact_registry` — the Docker repository; note the region must match the Cloud Run region to avoid cross-region pull latency.
- `secrets` — Secret Manager entries for the runtime secrets `.env.example` already names; note that values are never declared in HCL, only referenced.
- `kafka_vm` — a GCE VM running Kafka in KRaft mode; note the single-broker RF=1 MVP tradeoff carried over from compose.
- `timescale_vm` — a GCE VM running TimescaleDB; note that Cloud SQL is not an option because it does not support the TimescaleDB extension (this is why the requirement says self-hosted).
- `cloud_run_worker_pool` — the always-on poller / state machine / notifier workers; note that these are not request-driven and therefore must not scale to zero.

Extend `terraform/main.tf` to call all eight modules with root variables, and `terraform/outputs.tf` to
re-export the handful of outputs a deploy would actually need. Every call site must pass only variables
the module declares — `validate` is what proves that, so run it after every module is added rather than
once at the end.

Create `tests/unit/test_pending_human_banners.py`. Over every file matching `terraform/**/*.tf`, assert
the status banner appears within the first three lines and at least one `TODO(human)` marker exists, and
assert no file contains a `resource "` block. Add a second scan (used again in Task 3) over the
pending-human docs. Include the mandatory non-vacuity test: at least 12 `.tf` files scanned, and the
scanned module directory names include all eight expected modules.

Re-run `terraform fmt -recursive` before committing.
  </action>
  <acceptance_criteria>
    - `terraform -chdir=terraform fmt -check -recursive && terraform -chdir=terraform init -backend=false -input=false && terraform -chdir=terraform validate` all exit 0.
    - `ls -d terraform/modules/*/ | wc -l` returns 8.
    - `uv run pytest tests/unit/test_pending_human_banners.py -q -W error::RuntimeWarning` exits 0.
    - `grep -rn 'TODO(human)' terraform --include='*.tf' | wc -l` returns at least 8.
    - `terraform -chdir=terraform plan -input=false` exits 0 without any credential being present (there are no resources to plan).
  </acceptance_criteria>
  <verify>
    <automated>terraform -chdir=terraform fmt -check -recursive && terraform -chdir=terraform validate && uv run pytest tests/unit/test_pending_human_banners.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>Every infrastructure element DEPLOY-02 names has a declared, validated home in the repository, and no file can lose its "not applied" banner without a red test.</done>
</task>

<task type="auto">
  <name>Task 3: the GCP deploy guide, the uptime runbook, and one consolidated human-actions checklist</name>
  <files>docs/deploy/gcp.md, docs/runbooks/uptime.md, docs/HUMAN-ACTIONS.md, docs/PHASE-01-HUMAN-ACTIONS.md, tests/unit/test_pending_human_banners.py</files>
  <read_first>
    - `docs/runbooks/twilio-10dlc-setup.md:1-19` — the runbook shape `docs/deploy/gcp.md` follows (Why this matters / Owner / TL;DR blockquote / numbered steps)
    - `docs/runbooks/perf02-24h-log.md:1-16` — the `**Status:** BLOCKED ON HUMAN ACTION` banner position and the "each item is a hard gate" prerequisites section
    - `docs/PHASE-01-HUMAN-ACTIONS.md` (whole file) — the plain-English voice, the "big picture (30 seconds)" opener, and the wait-time-ordered priority table `docs/HUMAN-ACTIONS.md` inherits
    - `.planning/phases/0{1,3,4,5,6}-*/0*-CONTEXT.md` "Human-gated" paragraphs — the complete inventory of gates this checklist must consolidate
    - `.planning/deferred-items.md` — items the checklist should honestly acknowledge rather than hide
    - `07-RESEARCH.md` §Pattern 12 and §Pitfall 9 — the PERF-04 measurement arms and why the public dashboard is Grafana Cloud rather than the local container
  </read_first>
  <action>
Write `docs/deploy/gcp.md` in the runbook voice, opening with a `STATUS: pending-human — not applied`
banner. Describe the ROADMAP topology component by component with the exact `gcloud` command for each:
project and API enablement, Artifact Registry repository, Secret Manager entries, the VPC and Serverless
VPC Access connector, Memorystore Redis, the two GCE VMs (Kafka KRaft, TimescaleDB) including why Cloud
SQL cannot host TimescaleDB, the Cloud Run API service (with `min_instances` and the 3600 s timeout for
SSE), and the Cloud Run Worker Pools for the always-on services. Add a section mapping each component to
its `terraform/modules/<name>` stub, and a closing section stating that Grafana is exposed publicly via a
Grafana Cloud public dashboard rather than by publishing this container's port, because an anonymous
Grafana viewer can read the datasource list including internal URLs.

Write `docs/runbooks/uptime.md` with the same banner. Document the two Better Uptime monitors PERF-04
requires (`https://mise.place` and the API `GET /readyz`, 60-second interval), the alerting contact
setup, where the API token goes (`BETTERUPTIME_API_TOKEN` in `.env`, never committed), and how the
monthly figure is computed once data exists — `scripts/uptime_report.py` (07-06) with its
0-pass / 1-fail / 2-insufficient-data exit contract, in both its hosted-export and its local Prometheus
modes. State plainly that no monitor exists yet and that the 99.5 % monthly figure therefore has no
measurement behind it.

Write `docs/HUMAN-ACTIONS.md` consolidating every phase's pending-human gate into one checklist, ordered
by wait time the way the Phase-1 document is: Twilio 10DLC (weeks), Resend domain verification, the
domain and DNS, the GCP project and `terraform apply`, Resy accounts plus numeric venue ids and API key,
the OpenTable DevTools spike, the real-iPhone PWA push test, the 24 h PERF-02 and PERF-01 observation
windows, the 12 h PERF-05 soak, the Sentry DSN, the Grafana Cloud public dashboard, the Better Uptime
monitors, the production secrets, and the Vercel environment variables. Each entry names the requirement
it gates, the runbook that explains it, and what unblocks when it completes. Carry no personal data at
all: no real email address, phone number, account id, project id or credential — name the field, never
the value.

Replace the body of `docs/PHASE-01-HUMAN-ACTIONS.md` with a short superseded notice pointing at
`docs/HUMAN-ACTIONS.md`, keeping the file present so existing links and the Phase-1 SUMMARY references do
not rot.

Extend `tests/unit/test_pending_human_banners.py` with a docs scan: `docs/deploy/gcp.md` and
`docs/runbooks/uptime.md` each carry a status banner in their first ten lines; `docs/HUMAN-ACTIONS.md`
exists, references at least twelve distinct runbook or evidence paths that all resolve on disk, and
matches no personal-data pattern (an email-address regex, an E.164 phone regex, and the literal
placeholder-token shapes used in `.env.example`). Add the non-vacuity assertion for this scan too.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_pending_human_banners.py -q -W error::RuntimeWarning` exits 0 with at least 6 tests collected.
    - `head -10 docs/deploy/gcp.md | grep -c 'pending-human'` returns at least 1; the same holds for `docs/runbooks/uptime.md`.
    - `grep -cE '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}' docs/HUMAN-ACTIONS.md` returns 0.
    - `python3 -c "import re,pathlib; t=pathlib.Path('docs/HUMAN-ACTIONS.md').read_text(); p=set(re.findall(r'docs/[\w./-]+\.md', t)); missing=[x for x in p if not pathlib.Path(x).exists()]; print(len(p), missing); assert not missing and len(p) >= 12"` exits 0.
    - `grep -c 'HUMAN-ACTIONS.md' docs/PHASE-01-HUMAN-ACTIONS.md` returns at least 1 and `wc -l < docs/PHASE-01-HUMAN-ACTIONS.md` returns fewer than 30.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_pending_human_banners.py -q -W error::RuntimeWarning</automated>
  </verify>
  <done>A reader can find every real-world step this project still needs, in one file, ordered by how long it takes, with no claim that any of it is done and no secret anywhere in it.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| committed repository → public reader | This is a portfolio repository; every doc and every `.tf` file is world-readable. |
| runbook instructions → operator's cloud account | The `gcloud` commands in the deploy guide, if run, create billable, internet-reachable infrastructure. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-07-17 | Information disclosure | `docs/HUMAN-ACTIONS.md` and the runbooks | high | mitigate | The banner gate greps every consolidated doc for email, phone and token patterns; runbooks name the field and its source, never the value. |
| T-07-18 | Elevation of privilege | `terraform apply` | high | mitigate | No `backend` block and no `resource` blocks; every file banners `not applied`; the banner gate asserts the absence of `resource "` in modules; the CD promotion job (07-07) is `workflow_dispatch` + secret-gated. |
| T-07-19 | Information disclosure | Terraform state | medium | mitigate | `.gitignore` excludes `*.tfstate*` and `terraform/.terraform/` so a future `apply` cannot accidentally commit state containing resource attributes. |
| T-07-20 | Spoofing | published Grafana | medium | transfer | Public read access is transferred to Grafana Cloud public dashboards (pending-human), documented in `docs/deploy/gcp.md`; the local container stays loopback-bound (07-04). |
| T-07-SC | Tampering | Terraform provider download | medium | mitigate | `.terraform.lock.hcl` is committed, pinning provider `hashicorp/google` 7.46.1 by hash, so `init` is reproducible and a substituted provider fails verification. No package-manager install occurs in this plan. Record in SUMMARY. |
</threat_model>

<verification>
1. `terraform -chdir=terraform fmt -check -recursive` — exit 0.
2. `terraform -chdir=terraform init -backend=false -input=false && terraform -chdir=terraform validate` — exit 0 with no GCP credentials configured.
3. `uv run pytest tests/unit -q -W error::RuntimeWarning` — exit 0, including the banner gate.
4. `grep -rL 'STATUS: pending-human' terraform --include='*.tf'` — no output.
5. Every `docs/` path referenced by `docs/HUMAN-ACTIONS.md` resolves on disk.
</verification>

<success_criteria>
- The Terraform skeleton formats, initialises and validates offline, and covers every element DEPLOY-02 names.
- No file in `terraform/` can lose its "not applied" banner, and none contains a resource that could be created.
- `docs/deploy/gcp.md` gives an operator the exact commands without pretending any of them were run.
- One checklist holds every pending-human gate in the project, ordered by wait time, carrying no personal data.
</success_criteria>

<output>
Create `.planning/phases/07-deploy-observability-portfolio-polish/07-05-SUMMARY.md` when done.
Record: the Terraform and provider versions actually resolved, the exit codes of `fmt`/`init`/`validate`,
the count of consolidated human-gated items, and the list of runbook paths `docs/HUMAN-ACTIONS.md` cites.
</output>
