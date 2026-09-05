---
phase: 07-deploy-observability-portfolio-polish
plan: 06
type: execute
wave: 4
depends_on: ["07-02", "07-03", "07-04", "07-05"]
autonomous: true
requirements: [DEPLOY-04, PERF-04]
files_modified:
  - scripts/post_deploy_check.py
  - scripts/uptime_report.py
  - Makefile
  - tests/unit/test_post_deploy_check.py
  - tests/unit/test_uptime_report.py
  - tests/integration/test_post_deploy_check_lag.py
  - tests/integration/test_uptime_report_prometheus.py

estimate:
  tokens: 72000
  raw_tokens: 72000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "D-120: `scripts/post_deploy_check.py` implements both DEPLOY-04 gates — consumer lag reaches 0 within 2 minutes, and successful polls appear in `poll_log` within 3 minutes — and follows the repository's exit contract: 0 pass, 1 fail, 2 insufficient data."
    - "D-120a: lag is derived from the committed-offsets map returned by `list_consumer_group_offsets(group)` with **no** `partitions=` argument. Passing an empty partition list returns `{}` and reports a silent lag of 0, and `consumer.partitions_for_topic()` returns `None` on an unsubscribed consumer even after a metadata fetch — both traps were reproduced against a live broker whose real lag was 15."
    - "DEPLOY-04 probe (empty — *what is the result for empty, single-element, or null input?*): a group that has never committed yields the sentinel `-1`, which is NOT lag 0 and NOT a pass; an empty `poll_log` window exits 2 (insufficient data) rather than 0. Conflating 'no data' with 'healthy' is precisely what the third exit code exists to prevent."
    - "DEPLOY-04 probe (adjacency — *when two things are exactly equal or just touch, do they merge, collide, or separate?*): a committed offset exactly equal to the end offset is lag 0 and passes; the broker's `-1` sentinel offset is floored to 0 by `max(0, end - max(committed, 0))` so it can never produce a negative lag that reads as healthy; the 2-minute and 3-minute deadlines are inclusive, and a sample landing exactly on the boundary counts as inside the window."
    - "DEPLOY-04 probe (ordering — *when elements compare equal, is output order specified and stable?*): the per-group report is emitted in sorted group order so two runs against the same broker produce byte-comparable output, and the process exit code is the worst outcome across all groups regardless of the order they were checked — a failing group can never be masked by a later passing one."
    - "PERF-04 / D-124: `scripts/uptime_report.py` computes monthly uptime and exits 0 only when the minimum across monitored jobs is at least 0.995. Its `--mode compose` arm queries Prometheus `avg_over_time(up{...}[window])`; its hosted arm reads a Better Uptime export and is pending-human."
    - "PERF-04: when the Prometheus series covers less of the window than requested, the script exits 2 and reports the actual coverage. A 15-day retention answering a 30-day question with a confident number would be a fabricated availability figure — the exact dishonesty this repository's Status section exists to avoid."
    - "D-126: `make post-deploy-check` and `make uptime-report` exist, carry `## descriptions`, and are the documented entry points used by CI (07-07) and by `docs/runbooks/uptime.md` (07-05)."
    - "V5: both scripts treat broker and Prometheus responses as untrusted input — no `eval`, bounded `--window` parsing, and a malformed response produces exit 2 with a diagnostic rather than a traceback or a false pass."
    - "D-127: the unit tier covers `post_deploy_check` decision logic against fake lag and poll samples and `uptime_report` threshold math; the integration tier covers both against a live broker and a live Prometheus."
  artifacts:
    - scripts/post_deploy_check.py
    - scripts/uptime_report.py
    - tests/unit/test_post_deploy_check.py
    - tests/unit/test_uptime_report.py
    - tests/integration/test_post_deploy_check_lag.py
    - tests/integration/test_uptime_report_prometheus.py
  key_links:
    - "`post_deploy_check.py` → the `smoke` CI job and the gated `deploy-prod` CD job (07-07). It is the same script in both places, which is what makes the compose run a real rehearsal of the production check."
    - "consumer group names (`state-machine`, `notifier`) → the lag query. These strings come from the services' `group_id` constants; the script must import or assert them rather than duplicating literals that can drift."
    - "`PROMETHEUS_URL` + the 35d retention set in 07-04 → whether `uptime_report.py --mode compose` can answer a 30-day question at all."
  prohibitions:
    - "Must never report a health gate as passed when the underlying data is absent. Insufficient data is exit 2, and exit 2 is not success."
    - "Must never derive Kafka lag from application tables or a hand-maintained offset store. The broker is the source of truth; a second one will disagree at the worst moment."
    - "Must never publish an uptime percentage that the retained samples cannot support. Report the coverage alongside the number, or exit 2."
  flagged_assumptions:
    - "PERF-04 probe row is `unclassified` in the edge report and is therefore carried forward unresolved rather than auto-resolved. The open question it stands for: the requirement says 'Better Uptime, monthly', but no Better Uptime account exists this run. This plan builds the measurement tool and its local Prometheus arm; the authoritative hosted measurement remains pending-human and is recorded as such in `docs/runbooks/uptime.md` and in the README Status section (07-08). No 99.5 % claim is made anywhere from local data alone."
    - "DEPLOY-03's probe row is likewise `unclassified` and is carried into 07-07, where the CI workflow lives."
    - "The lag gate assumes the consumer groups exist. On a freshly-migrated stack they may not have committed yet, which is exactly the `-1` sentinel path — reported as insufficient data, never as healthy."
---

<objective>
Build the two measurement gates DEPLOY-04 and PERF-04 name: a post-deploy health check that proves a deploy actually recovered, and an uptime report that refuses to invent a number it cannot measure.

Purpose: a deploy pipeline without a post-deploy check is a pipeline that reports success for a broken release. Research reproduced two silent-zero traps in the obvious `aiokafka` lag implementation — both of which would have made this gate report perfect health against a broker with real lag of 15. That is worse than having no gate, because it is a gate that lies.

Output: `scripts/post_deploy_check.py`, `scripts/uptime_report.py`, their Make targets, and four test files covering the decision logic in isolation and against a live broker and a live Prometheus.
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
@.planning/phases/07-deploy-observability-portfolio-polish/07-04-SUMMARY.md
@.planning/phases/07-deploy-observability-portfolio-polish/07-05-SUMMARY.md
@scripts/check_poll_success.py
</context>

<artifacts_this_phase_produces>
- **Scripts:** `scripts/post_deploy_check.py` (DEPLOY-04 lag + poll gates), `scripts/uptime_report.py` (PERF-04 measurement, both arms).
- **Targets:** `make post-deploy-check`, `make uptime-report`.
- **Tests:** two unit modules for the decision logic, two integration modules against the live broker and the live Prometheus.
- Images/compose/workflows/docs: none — 07-07 calls these scripts from CI, 07-05 documents them.
</artifacts_this_phase_produces>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1 (tracer): real broker lag becomes a process exit code</name>
  <files>scripts/post_deploy_check.py, tests/unit/test_post_deploy_check.py, tests/integration/test_post_deploy_check_lag.py</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 7 (lines 654-700) — the two reproduced traps, the verified `consumer_lag` recipe, and the `AIOKafkaAdminClient` method inventory for 0.13.0
    - `scripts/check_poll_success.py:1-132` — the docstring shape (purpose, `Usage:`, explicit exit-code table), the named module constants at `:29-33`, and the `async def check() -> int` / `def main() -> None` entrypoint split at `:47,126-132`
    - `shared/kafka.py` and the state machine's `CONSUMER_GROUP_ID` — the real group-id constants, so the script imports them instead of duplicating string literals
    - `tests/integration/test_topics_created.py` and `tests/integration/conftest.py` — the integration-tier fixtures and skip guards
  </read_first>
  <behavior>
    - `consumer_lag(bootstrap, ["state-machine"])` against a broker with 20 produced and 5 consumed messages returns `{"state-machine": 15}` — matching what `kafka-consumer-groups.sh --describe` reports.
    - `consumer_lag(bootstrap, ["never-committed"])` returns `{"never-committed": -1}`, distinct from a lag of 0.
    - A committed offset exactly equal to the end offset yields 0.
    - A broker-sentinel committed offset of `-1` on a partition yields the full end offset as lag, never a negative number.
    - The CLI exits 0 when every group reaches lag 0 inside the deadline, 1 when a group is still lagging at the deadline, and 2 when every group reports the never-committed sentinel.
  </behavior>
  <action>
Create `scripts/post_deploy_check.py` following `check_poll_success.py`'s structure exactly: a module
docstring that states the requirement, a `Usage:` line naming the `make` target, and an explicit exit-code
table (0 pass, 1 fail, 2 insufficient data); named module constants for the two deadlines
(`LAG_DEADLINE_SECONDS = 120`, `POLL_DEADLINE_SECONDS = 180`) and the poll interval; an `async def
check(...) -> int` doing the work; and `def main() -> None` calling `sys.exit(asyncio.run(check()))`.

Implement `consumer_lag(bootstrap: str, groups: list[str]) -> dict[str, int]` per the verified recipe: an
`AIOKafkaAdminClient` and a non-auto-committing `AIOKafkaConsumer`, `await
admin.list_consumer_group_offsets(g)` with **no** `partitions=` argument, `-1` when the returned map is
empty, otherwise partitions derived from that map and lag summed as `max(0, end - max(committed, 0))`.
The docstring must name both traps and say what each one silently produces, because the correct code
looks arbitrary without that context.

Add the lag gate: poll `consumer_lag` on a fixed interval until every group reaches 0 or
`LAG_DEADLINE_SECONDS` elapses, emitting one structured line per round in sorted group order. Return 0
when all groups reach 0, 1 when any group is still lagging at the deadline, 2 when every group reports
the sentinel.

Add `--mode {compose,prod}` and `--bootstrap`/`--groups` arguments with defaults read from the
environment the compose stack already sets; the group list defaults to the real `group_id` constants
imported from the services rather than to string literals.

Create `tests/unit/test_post_deploy_check.py` driving the decision logic through a fake admin/consumer
pair returning the research's measured shapes, covering every behaviour above. Create
`tests/integration/test_post_deploy_check_lag.py` producing a known number of messages, consuming a
subset with a real group, and asserting `consumer_lag` returns the exact expected number — guarded by
the repo's Docker-availability check so it skips cleanly without a container runtime.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_post_deploy_check.py -q -W error::RuntimeWarning` exits 0 with at least 6 tests collected.
    - `uv run pytest tests/integration/test_post_deploy_check_lag.py -q -p no:cacheprovider` exits 0.
    - `grep -c 'partitions=' scripts/post_deploy_check.py` returns 0 outside comments — verify with `grep -v '^\s*#' scripts/post_deploy_check.py | grep -c 'list_consumer_group_offsets(.*partitions='` returning 0.
    - Against a running `--profile smoke` stack: `uv run python scripts/post_deploy_check.py --mode compose; echo $?` prints an exit code of 0, 1 or 2 and never raises a traceback.
    - `uv run mypy scripts/` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_post_deploy_check.py -q -W error::RuntimeWarning && uv run mypy scripts/</automated>
  </verify>
  <done>Broker state travels through the admin client, the lag arithmetic and the deadline loop to a process exit code that a CI job can act on — with the two silent-zero traps proven closed by a test against a real broker.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: the poll-recovery gate and the CLI contract</name>
  <files>scripts/post_deploy_check.py, Makefile, tests/unit/test_post_deploy_check.py</files>
  <read_first>
    - `scripts/check_poll_success.py:29-33,74,108,117,123` — the SQL/threshold constant idiom and every place the exit code is decided
    - `shared/db.py` — the `poll_log` model and the async session helper the query uses
    - `07-RESEARCH.md` §Pattern 7 closing note — the exit-code convention this script must match
    - `Makefile:38-46` — the `lint` and `verify-perf02` target shapes
  </read_first>
  <behavior>
    - With at least one `poll_log` row whose `status = 'success'` and whose timestamp is inside the deadline window, the poll gate passes.
    - With rows present but none successful inside the window, the poll gate fails (exit 1).
    - With no rows at all inside the window, the poll gate reports insufficient data (exit 2).
    - A row landing exactly on the window boundary is counted as inside.
    - The overall exit code is the worst of the lag gate and the poll gate: any 1 wins over any 2, and any 2 wins over 0.
  </behavior>
  <action>
Add the second DEPLOY-04 gate to `scripts/post_deploy_check.py`: poll `poll_log` on the same interval
until a successful poll appears inside `POLL_DEADLINE_SECONDS` or the deadline elapses. Use a named SQL
constant with an inclusive lower bound on the timestamp, and parameterise it — never format a value into
the statement.

Combine the two gate results into one process exit code with an explicit precedence documented in the
docstring: 1 beats 2 beats 0. Print a short human-readable summary naming each gate, its outcome, the
observed value and the deadline, so a CI log tells an operator what actually happened without them
re-running anything.

Add `--mode prod` handling that takes an `--api-url` and checks the deployed API's `/readyz` alongside
the two gates, so the same script serves the gated promotion job in 07-07. In `--mode prod` the script
must still refuse to invent data: an unreachable API is exit 1, not a skipped check.

Add `make post-deploy-check` with its `.PHONY` entry and `## description`.

Extend `tests/unit/test_post_deploy_check.py` with the poll-gate and precedence behaviours above, using
an in-memory or fixture-backed row set rather than a live database.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_post_deploy_check.py -q -W error::RuntimeWarning` exits 0 with at least 12 tests collected.
    - `make post-deploy-check` runs the script and exits with 0, 1 or 2 (never a traceback) against a running `--profile smoke` stack.
    - `grep -v '^\s*#' scripts/post_deploy_check.py | grep -c 'f"SELECT\|% (' ` returns 0 (no string-formatted SQL).
    - `uv run mypy scripts/ && uv run ruff check .` exits 0.
    - `grep -c 'post-deploy-check' Makefile` returns at least 2 (the `.PHONY` entry and the target).
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_post_deploy_check.py -q -W error::RuntimeWarning && uv run mypy scripts/</automated>
  </verify>
  <done>Both DEPLOY-04 gates run from one command with one honest exit code, and the precedence between "failed" and "could not tell" is a tested rule rather than an accident of evaluation order.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: the PERF-04 uptime report</name>
  <files>scripts/uptime_report.py, Makefile, tests/unit/test_uptime_report.py, tests/integration/test_uptime_report_prometheus.py</files>
  <read_first>
    - `07-RESEARCH.md` §Pattern 12 (lines 852-861) — the verified Prometheus query, the retention constraint, and why coverage must be reported
    - `07-RESEARCH.md` §Open Questions 4 — the retention-versus-window trade resolved in 07-04 by setting 35d
    - `docs/runbooks/uptime.md` from 07-05 — the pending-human hosted arm this script must match, and the exit contract the runbook already promises
    - `scripts/check_poll_success.py:1-132` — the same skeleton this script reuses
    - `scripts/replay_raw.py:425-483` — the `build_parser()` + `main(argv) -> int` argparse idiom for scripts that take real arguments
  </read_first>
  <behavior>
    - Minimum availability across jobs of exactly 0.995 exits 0 (the threshold is inclusive); 0.9949 exits 1.
    - A response whose series covers fewer samples than the requested window exits 2 and prints the actual coverage as a fraction of the window.
    - An empty Prometheus result set exits 2, never 0.
    - A malformed or non-JSON Prometheus response exits 2 with a diagnostic and no traceback.
    - `--window` accepts only a bounded set of duration forms and rejects anything else with exit 2 rather than passing it through to the query.
    - The hosted arm, invoked without `BETTERUPTIME_API_TOKEN`, exits 2 with a message pointing at `docs/runbooks/uptime.md`.
  </behavior>
  <action>
Create `scripts/uptime_report.py` with the same docstring-plus-exit-table shape and the
`build_parser()` / `main(argv) -> int` argparse structure. Arguments: `--mode {compose,hosted}`,
`--prometheus-url` (default from `PROMETHEUS_URL`), `--window` (default `30d`), `--jobs` (default the
four service jobs), and `--threshold` (default 0.995).

The compose arm issues one `GET {prom}/api/v1/query` for
`avg_over_time(up{job=~"..."}[<window>])`, plus a second query establishing how much of the window the
series actually covers, and prints a per-job table followed by the minimum. It exits 0 only when the
minimum is at least the threshold **and** coverage is complete; short coverage is exit 2 with the
coverage fraction printed, because a 35-day retention answering a 30-day question is only trustworthy
when the samples are actually there.

The hosted arm reads a Better Uptime JSON export from `--input` and computes the same figure. Do not
invent the API's response shape: parse the export defensively, and when the token or the file is absent
exit 2 pointing at the runbook. This arm is pending-human by design.

Treat every response as untrusted: no `eval`, explicit JSON parsing with a typed extraction step, and a
`--window` validated against a small allowed pattern before it is interpolated into PromQL.

Add `make uptime-report` with its `.PHONY` entry and `## description`.

Create `tests/unit/test_uptime_report.py` covering every behaviour above with canned response payloads,
and `tests/integration/test_uptime_report_prometheus.py` running the compose arm against the live
Prometheus from 07-04 with a short window, asserting a 0 or 2 exit and a parseable table — guarded so it
skips cleanly when the stack is not up.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_uptime_report.py -q -W error::RuntimeWarning` exits 0 with at least 8 tests collected.
    - `uv run python scripts/uptime_report.py --mode compose --window 5m; echo $?` prints 0 or 2 against the running stack and never raises.
    - `uv run python scripts/uptime_report.py --mode compose --window "5m); drop"; echo $?` prints 2 (the window argument is validated, not interpolated blindly).
    - `uv run python scripts/uptime_report.py --mode hosted; echo $?` prints 2 and the message names `docs/runbooks/uptime.md`.
    - `uv run pytest tests/integration/test_uptime_report_prometheus.py -q -p no:cacheprovider` exits 0.
    - `uv run mypy scripts/ && uv run ruff check .` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_uptime_report.py -q -W error::RuntimeWarning && uv run mypy scripts/</automated>
  </verify>
  <done>PERF-04 has a real measurement tool with an inclusive threshold, a validated window, and an explicit refusal to report a figure the retained samples cannot support.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Kafka broker → `post_deploy_check.py` | Admin and consumer responses are external input parsed into a pass/fail decision. |
| Prometheus HTTP API → `uptime_report.py` | A JSON response drives a published availability number. |
| CLI argv → PromQL | `--window` and `--jobs` reach a query string. |
| deployed API → `--mode prod` | `/readyz` on a remote host gates a promotion. |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-07-21 | Tampering | PromQL construction | medium | mitigate | `--window` is validated against a bounded duration pattern and `--jobs` against a name pattern before interpolation; no `eval`; a rejected argument exits 2 rather than reaching the query. |
| T-07-22 | Repudiation | false-healthy gate | high | mitigate | The `-1` sentinel and the empty-window path map to exit 2, never 0; the unit suite pins the empty, boundary and never-committed cases so a refactor cannot restore the silent zero. |
| T-07-23 | Information disclosure | CLI arguments in logs and Sentry | medium | mitigate | `shared/observability.py`'s `before_send` drops the `sys.argv` extra (07-03); `BETTERUPTIME_API_TOKEN` is read from the environment and never echoed. |
| T-07-24 | Denial of service | unbounded polling loops | low | mitigate | Both gates are bounded by named deadline constants and a fixed interval; every HTTP call carries an explicit timeout. |
| T-07-SC | Tampering | dependencies | low | accept | No new package: both scripts use `aiokafka`, `httpx` and `sqlalchemy`, all already pinned in `pyproject.toml`. Record in SUMMARY. |
</threat_model>

<verification>
1. `uv run pytest tests/unit/test_post_deploy_check.py tests/unit/test_uptime_report.py -q -W error::RuntimeWarning` — exit 0.
2. `uv run pytest tests/integration/test_post_deploy_check_lag.py tests/integration/test_uptime_report_prometheus.py -q -p no:cacheprovider` — exit 0.
3. `uv run mypy shared/ services/ scripts/ && uv run ruff check .` — exit 0.
4. Against a running `--profile smoke --profile monitoring` stack: `make post-deploy-check` and `make uptime-report` both terminate with a documented exit code and a readable summary.
5. `uv run pytest tests/unit -q -W error::RuntimeWarning` — the whole unit tier stays green.
</verification>

<success_criteria>
- The lag gate reports the same number the broker's own CLI reports, and reports "never committed" as insufficient data rather than as health.
- Both DEPLOY-04 gates run from one command with a documented exit-code precedence.
- The uptime report refuses to publish a figure its samples cannot support.
- Every boundary, empty and ordering case above is pinned by a unit test.
</success_criteria>

<output>
Create `.planning/phases/07-deploy-observability-portfolio-polish/07-06-SUMMARY.md` when done.
Record: the lag figure observed against the live broker and the value `kafka-consumer-groups.sh` reported
for the same group, the exit codes produced by both scripts against the compose stack, and the actual
Prometheus coverage fraction for the default 30-day window on this machine.
</output>
