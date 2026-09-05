---
phase: 03-resy-playwright-fleet
plan: 07
type: execute
wave: 5
depends_on: [03-03, 03-04, 03-05, 03-06]
files_modified:
  - scripts/soak_playwright.py
  - Makefile
  - README.md
  - docs/runbooks/perf05-soak.md
  - docs/runbooks/resy-cookie-capture.md
  - .planning/deferred-items.md
  - tests/unit/test_soak_sampling.py
  - tests/unit/test_soak_verdict.py
  - tests/integration/test_soak_ci.py
  - tests/integration/test_no_zombie_browsers.py
autonomous: true
requirements: [PERF-05]

estimate:
  tokens: 60000
  raw_tokens: 60000
  tasks: 4
  confidence: low

must_haves:
  truths:
    - "`uv run python scripts/soak_playwright.py --duration 90s --sample-every 5s --stub` exits 0, writes a `logs/soak-<ts>.jsonl` file with one JSON object per sample, and reports a PASS verdict with a stable Playwright process count (PERF-05, CI-sized variant of D-70)."
    - "RSS is sampled as CURRENT usage via `ps -o rss= -p <pid>` (KiB on both macOS and Linux) for the poller pid and every Playwright pid; `resource.getrusage` appears only as a diagnostic annotation in the JSONL and never in the verdict, because `ru_maxrss` is a monotone high-water mark that makes the growth gate unfalsifiable (D-70a, research B-8)."
    - "Playwright processes are discovered by the path token `ms-playwright`, never by a name pattern matching `chrom` — research measured four false positives from the developer's own Chrome at baseline, and the launched binary is literally named `Google Chrome for Testing` (D-70a, research B-8)."
    - "On a Linux image without `ps`/`pgrep` the sampler falls back to `/proc/<pid>/statm` and `/proc/*/cmdline` and still produces samples, rather than silently reporting zero processes (research B-8)."
    - "`soak_verdict(samples)` is a PURE function: synthetic samples with +25 % RSS growth yield a FAIL, +10 % yields a PASS, a PID spread of 3 yields a FAIL, a spread of 2 passes, and a poll success rate below 0.99 yields a FAIL; the growth baseline is the first post-warm-up sample (t + 2 min), never the very first (D-70a)."
    - "PROBE PERF-05: a run that collected zero Playwright processes, or fewer samples than the duration and interval imply, exits 2 (preconditions not met) rather than 0 — an unfalsifiable green is not a pass. Exit codes mirror `scripts/check_poll_success.py`: 0 pass, 1 gate failed, 2 setup/insufficient data."
    - "A poller task cancelled mid-poll leaves ZERO `ms-playwright` processes when the shielded teardown runs, and the test asserts the leak is real by also exercising a subject WITHOUT the shield and observing a non-zero count (research §Pitfall 1)."
    - "`docs/runbooks/perf05-soak.md` and `docs/runbooks/resy-cookie-capture.md` both exist and both carry an explicit pending-human status banner naming the exact actions no agent may perform: the 12-hour production soak run, the Resy cookie capture, the `RESY_API_KEY` DevTools capture, the numeric venue-id resolution, and the residential proxy subscription."
    - "`README.md`'s Legal &amp; Ethical Scraping section states that the Resy caps are now enforced in code and names the enforcing symbols, replacing the present 'will be capped ... when the Resy poller lands (Phase 3)' future tense."
  artifacts:
    - scripts/soak_playwright.py
    - docs/runbooks/perf05-soak.md
    - docs/runbooks/resy-cookie-capture.md
    - tests/unit/test_soak_verdict.py
    - tests/unit/test_soak_sampling.py
    - tests/integration/test_soak_ci.py
    - tests/integration/test_no_zombie_browsers.py
  key_links:
    - "`_playwright_pids()` -> `soak_verdict` -> the PERF-05 gate — the discriminator token is the whole test; matching `chrom` would count the operator's browser and make the PID-stability gate meaningless."
    - "`scripts/soak_playwright.py --stub` -> `tests/fakes/resy_stub.py` (03-04) -> `ContextPool` (03-05) — the soak exercises the real fleet with no live traffic, so PERF-05's automated half needs no credentials."
    - "`docs/runbooks/perf05-soak.md` -> the 12-hour run -> the ROADMAP's hard gate before Resy runs in production — the one item in this phase that genuinely cannot be automated."
  prohibitions:
    - "MUST NOT emit a soak PASS verdict from a run whose sampler found zero Playwright processes, or that collected fewer samples than its duration and interval imply — a green that could not have gone red is worse than a red, because it retires a gate that was never actually exercised."
---

<objective>
Deliver PERF-05's automated half — a soak harness that can actually detect a leak — and write the
human-facing documentation for the five things in this phase that a human, and only a human, can do.

Purpose: the 12-hour soak is a hard ROADMAP gate before Resy runs in production. It cannot be run
here, so the deliverable is a correct, tested, CI-exercised harness plus a runbook a human can follow,
not a claim that the gate passed.
Output: `scripts/soak_playwright.py`, `make soak`, two runbooks with pending-human banners, a README
that stops promising the caps in the future tense, and the zombie-process regression test.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/03-resy-playwright-fleet/03-CONTEXT.md
@.planning/phases/03-resy-playwright-fleet/03-PATTERNS.md
</context>

<tasks>

<task type="tracer">
  <name>Task 1: End-to-end tracer — a 90-second soak against the stub exits 0 with a real verdict</name>
  <precondition>`make browsers` (03-04) has been run; `ps` and `pgrep` are available on the host, or the `/proc` fallback path is exercised instead.</precondition>
  <files>scripts/soak_playwright.py, Makefile, tests/integration/test_soak_ci.py</files>
  <read_first>
    - scripts/check_poll_success.py in full (the docstring exit-code contract, the threshold constants, the verdict dataclass, the `main()` / `asyncio.run` / `sys.exit` shape, and the `postgresql+asyncpg://` -> `postgresql://` strip for the raw asyncpg query)
    - services/poller/sources/resy/pool.py and adapter.py (03-05 — the fleet the soak drives)
    - tests/fakes/resy_stub.py (03-04)
    - services/poller/config.py (the lazy readers)
    - Makefile (the `## description` convention and the exhaustive `.PHONY` line — `browsers` was added in 03-04, `soak` is added here)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §B-8 in full (why `getrusage` cannot detect a leak, the per-platform unit differences, the four false positives from `pgrep -f chrom` at baseline, and the missing `ps`/`pgrep` in slim images), §Pattern 8 (the measured process tree, the two crashpad handlers re-parented to PID 1 that still exit on close), §Code Examples "RSS / PID sampling for the soak"
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-70, §D-70a
  </read_first>
  <action>
Write `scripts/soak_playwright.py` with the docstring exit-code contract this repo uses
(`0` pass, `1` a gate failed, `2` preconditions not met / insufficient data) and the CLI
`--duration`, `--sample-every`, `--venues`, `--stub`, `--out`. Duration and interval accept a
human suffix (`12h`, `90s`) and are parsed by a small pure helper.

Sampling, per D-70a: `_ps_rss_kib(pid)` shells `ps -o rss= -p <pid>` through
`asyncio.create_subprocess_exec` and returns CURRENT RSS in KiB, which is the same unit on macOS and
Linux; `_playwright_pids()` shells `pgrep -f ms-playwright` — the path token, never a `chrom` name
pattern, which research measured returning four processes with no browser running at all because the
launched binary is named `Google Chrome for Testing`. Provide a `/proc`-based fallback for both
(`/proc/<pid>/statm` and a scan of `/proc/*/cmdline`) because `ps` and `pgrep` are absent from slim
Python images; the fallback must be exercised by a code path the unit test can force, not left as
dead code. Record `resource.getrusage` in the JSONL as a diagnostic annotation with a comment saying
plainly that it is a monotone high-water mark and must never enter the verdict.

Each sample is one JSON object with the timestamp, the poller RSS, the summed Playwright RSS, the
Playwright PID count, the active-context gauge value, and the poll success rate; append it to
`logs/soak-<ts>.jsonl`. Resolve the output path and refuse to write outside the repository root
(ASVS V12). Keep the sample loop's cadence with `asyncio.sleep` — this is a script, not service code,
and it is the one legitimate wait in this phase; say so in a comment so it is not mistaken for a
scheduling wait.

Split IO from judgement: `soak_verdict(samples: Sequence[SoakSample]) -> SoakVerdict` is PURE, with
module constants `RSS_GROWTH_THRESHOLD = 0.20`, `PID_SPREAD_MAX = 2`,
`SUCCESS_RATE_THRESHOLD = 0.99` and `WARMUP_SECONDS = 120`. The growth comparison is the LAST sample
against the first sample at or after the warm-up point, never against the very first — a cold start
inflates the baseline and hides a real leak. `main()` refuses with exit 2 when the run collected no
Playwright processes or fewer samples than `duration / interval` implies.

`--stub` starts the in-process Resy stub, points `RESY_API_BASE` at it, and drives a real
`ContextPool` plus `ResyAdapter` over `--venues` synthetic venue ids, so the harness exercises the
actual fleet with no live traffic and no credentials. Without `--stub` it reads the live environment
and additionally samples the poll success rate from `poll_log` using the `check_poll_success.py`
query shape.

Add a `soak:` target to the `Makefile` with a `##` description and add `soak` to `.PHONY`; default it
to the CI-sized variant and document the 12-hour invocation in the target's comment.

Write the tracer `tests/integration/test_soak_ci.py`: run `scripts/soak_playwright.py --duration 90s
--sample-every 5s --venues 2 --stub` as a subprocess, assert exit code 0, assert the JSONL file exists
with at least 15 lines each parsing as JSON with the expected keys, and assert the reported PID
spread is within `PID_SPREAD_MAX`.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_soak_ci.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_soak_ci.py -q -p no:cacheprovider` exits 0 (or skips with the Chromium-guard message).
    - `uv run python scripts/soak_playwright.py --duration 90s --sample-every 5s --venues 2 --stub` exits 0 and prints a PASS verdict naming the RSS growth fraction, the PID spread and the success rate.
    - `ls logs/soak-*.jsonl | wc -l` is at least 1 after the run, and `pgrep -f ms-playwright | wc -l` reports 0 afterwards.
    - `make help` lists a `soak` target and `grep -c "^\.PHONY.*soak" Makefile` returns 1.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A 90-second soak drives the real fleet against the stub, writes real samples, and produces a verdict that could have gone red.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The verdict and the sampler are provable without a 12-hour wait</name>
  <files>tests/unit/test_soak_verdict.py, tests/unit/test_soak_sampling.py, scripts/soak_playwright.py</files>
  <read_first>
    - scripts/soak_playwright.py (as written in Task 1)
    - scripts/check_poll_success.py lines 29-44 (the threshold-constant + verdict-property style)
    - tests/unit/test_service_time_math.py (the pure-arithmetic table-test style)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §B-8 (the measured baselines the assertions encode) and §Pattern 8 (the two crashpad handlers re-parented to PID 1, which is why `PID_SPREAD_MAX` is 2)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-70, §D-70a
  </read_first>
  <behavior>
    - `soak_verdict`: synthetic samples rising 10 % from the post-warm-up baseline -> PASS; rising 25 % -> FAIL naming the RSS gate; PID values spanning 3 distinct counts -> FAIL naming the PID gate; spanning 2 -> PASS; a success rate of 0.985 -> FAIL naming the success gate; all three failing at once -> FAIL naming all three.
    - The growth baseline is the first sample at or after `WARMUP_SECONDS`; a run whose first two minutes spike and then settle PASSES, and a run that is flat for two minutes and then climbs 25 % FAILS. Both are asserted, because using the very first sample would invert exactly these two cases.
    - Zero Playwright pids in every sample -> the run is not a pass; `main()` returns 2.
    - Fewer collected samples than `duration / interval` implies -> `main()` returns 2.
    - An empty or single-sample list -> `main()` returns 2, never a division error.
    - `_ps_rss_kib` returns a positive integer for the current process and `None` for a pid that does not exist, without raising.
    - `_playwright_pids()` returns a list of ints, and its command uses the `ms-playwright` path token; a source-scan assertion in the test proves the script contains no name-pattern process match that would collide with the operator's own browser.
    - The duration parser accepts `90s`, `5m`, `12h` and rejects `12`, `12x` and a negative value with a clear error.
  </behavior>
  <action>
Write `tests/unit/test_soak_verdict.py` as a literal table over synthetic `SoakSample` lists —
constructed by hand, never sampled — covering every verdict row in `<behavior>`, including the two
warm-up cases that a first-sample baseline would invert. Assert on the failing gate NAMES, not just
the boolean, so a verdict that fails for the wrong reason cannot pass the test.

Write `tests/unit/test_soak_sampling.py` for the sampler primitives and the duration parser, plus the
source-scan assertion that the script contains no name-pattern process match. Strip full-line
comments before scanning (the `tests/unit/test_no_inline_sleep.py` helper is the template) so an
explanatory comment can neither satisfy nor break the gate, and include a non-vacuity assertion that
the scanned file is non-empty. Force the `/proc` fallback through a monkeypatched command-missing
path so it is covered rather than dead.

Fix `scripts/soak_playwright.py` for whatever the matrix exposes rather than relaxing an assertion —
in particular any off-by-one in the warm-up baseline selection or any path where an empty sample list
raises instead of returning exit 2.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_soak_verdict.py tests/unit/test_soak_sampling.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_soak_verdict.py tests/unit/test_soak_sampling.py -q` exits 0 in under 5 seconds (no browser, no container).
    - `grep -c "def test_" tests/unit/test_soak_verdict.py` returns at least 8.
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Every PERF-05 gate boundary, including the warm-up baseline that decides whether a leak is visible at all, is pinned by a unit test that runs in seconds.</done>
</task>

<task type="auto">
  <name>Task 3: The zombie-browser regression test</name>
  <files>tests/integration/test_no_zombie_browsers.py</files>
  <read_first>
    - services/poller/sources/resy/pool.py (the shielded `stop()` from 03-05)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pitfall 1 in full (both the leaking run — six processes surviving `asyncio.run` — and the clean run were reproduced; the benign `Request context disposed` warning is expected and must be swallowed, not "fixed" by removing the shield)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pattern 8 (the two crashpad handlers re-parent to PID 1 and are therefore invisible to a process-tree walk, but do exit on `browser.close()`)
    - tests/conftest.py (`_chromium_available()` and the `browser` fixture from 03-04)
  </read_first>
  <action>
Write `tests/integration/test_no_zombie_browsers.py` proving PERF-05's headline failure mode is
actually caught. Run TWO subjects as subprocesses so a leak cannot contaminate the pytest process:
one that cancels a task mid-poll WITH the shielded teardown, and one deliberately written without it.
Assert the shielded subject leaves zero processes matching the `ms-playwright` path token and that
the unshielded subject leaves a non-zero count — a test that only asserted the clean case would pass
just as happily against a teardown that never ran. Reap the leaked processes at the end of the
unshielded case so the test does not poison the machine or the following tests, and guard the whole
file with the Chromium availability skip.

Discover processes by the `ms-playwright` path token rather than a name pattern, for the same reason
the soak script does: the operator's own Chrome answers a name match. Note in the module docstring
that two crashpad handlers re-parent to PID 1 and so are invisible to a tree walk from the subprocess
pid, which is why the assertion counts by token rather than by descendant.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_no_zombie_browsers.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_no_zombie_browsers.py -q -p no:cacheprovider` exits 0 (or skips with the Chromium-guard message).
    - `pgrep -f ms-playwright | wc -l` reports 0 after the test run — the deliberately-leaking subject was reaped.
    - The file contains both a clean-teardown assertion and a leaking-subject assertion; `grep -c "def test_" tests/integration/test_no_zombie_browsers.py` returns at least 2.
    - `uv run ruff check .` exits 0.
  </acceptance_criteria>
  <done>The leak the PERF-05 gate exists to catch is reproduced and asserted, so the clean-teardown assertion cannot be vacuous.</done>
</task>

<task type="auto">
  <name>Task 4: Runbooks for the five human-gated steps, and a README that stops using the future tense</name>
  <files>docs/runbooks/perf05-soak.md, docs/runbooks/resy-cookie-capture.md, README.md, .planning/deferred-items.md</files>
  <read_first>
    - docs/runbooks/perf02-24h-log.md lines 1-40 (the title / `**Purpose:**` / status banner / `## Prerequisites` with `- **Action:**` and `- **Verification:**` bullets structure to copy)
    - docs/runbooks/twilio-10dlc-setup.md (the second runbook precedent for a multi-step human gate)
    - README.md lines 320-345 (the Legal &amp; Ethical Scraping section whose Resy sentence is currently future tense)
    - .env.example lines 35-49 (the two-phase secret-handling comment `resy-cookie-capture.md` must actually document — the file is referenced there and in D-63a but does not yet exist)
    - services/poller/sources/resy/README.md (03-05 — the enforcing-function citations this README links to)
    - scripts/resolve_resy_venue_ids.py (03-03 — the resolver this runbook drives)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Open Questions Q5 (the ~500 MB of stale browser directories: mention the disk cost, do not delete another tool's assets) and §Assumptions Log A4, A5
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §domain "Human-gated" list, §D-70
    - .planning/deferred-items.md (the existing table format)
  </read_first>
  <action>
Write `docs/runbooks/perf05-soak.md` following `perf02-24h-log.md`: a title, a `**Purpose:**` line, a
prominent `STATUS: pending-human-run` banner stating that the 12-hour run is a hard ROADMAP gate
before Resy runs in production and that no agent can perform it, then `## Prerequisites` where each
gate carries `- **Action:**` and `- **Verification:**` bullets — infrastructure up, `make browsers`
run, `RESY_ENABLED=true` with real accounts and a resolved venue set, and enough free disk (note the
roughly 500 MB of stale sibling browser revisions in the shared cache; report the number, do not
delete another tool's assets). Then the invocation (`make soak` and the explicit 12-hour form), the
three pass gates with their exact thresholds, how to read the JSONL, what a failure of each gate
means and what to do about it, and a results table for the human to fill in.

Write `docs/runbooks/resy-cookie-capture.md` — referenced by `.env.example` and by D-63a but never
created. Carry a `STATUS: pending-human` banner and cover, each as an `- **Action:** / -
**Verification:**` pair: capturing the post-login session cookies in a supervised browser and
serialising them into `RESY_ACCOUNTS_JSON` in either accepted shape (stating that the `domain` must be
the dot form or the cookies never reach `api.resy.com`); capturing `RESY_API_KEY` and the auth-token
header name from DevTools, flagging that the header name is corroborated but unverified; resolving the
numeric venue ids with `uv run python scripts/resolve_resy_venue_ids.py`, flagging the endpoint as
`[ASSUMED]`; and subscribing to a residential proxy and setting `RESY_PROXY_URL`. State plainly that
the project never automates account creation, login or booking, that cookies live only in browser
context memory, and that nothing here may be committed.

Update `README.md`'s Legal &amp; Ethical Scraping section: the Resy sentence currently promises the cap
in the future tense. Replace it with a statement that both limits are now enforced in code and name
the enforcing symbols and their file, linking to `services/poller/sources/resy/README.md` for the
detail — so a reader can audit the public claim against the implementation in two hops. Leave the
no-booking-automation and public-data-only clauses intact.

Add rows to `.planning/deferred-items.md` for the follow-ups this phase deliberately did not take:
the fleet-level canary cross-check proposed in research §Pitfall 10 (only the per-venue window
shipped), source-filtered claims per D-72's accepted caveat, and the stale sibling browser revisions
from Q5.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; test -f docs/runbooks/perf05-soak.md &amp;&amp; test -f docs/runbooks/resy-cookie-capture.md &amp;&amp; grep -q "pending-human" docs/runbooks/perf05-soak.md &amp;&amp; grep -q "pending-human" docs/runbooks/resy-cookie-capture.md</automated>
  </verify>
  <acceptance_criteria>
    - `test -f docs/runbooks/perf05-soak.md && test -f docs/runbooks/resy-cookie-capture.md` succeeds.
    - Each runbook contains a pending-human status banner and at least four `- **Action:**` / `- **Verification:**` prerequisite pairs; `grep -c '\*\*Action:\*\*' docs/runbooks/resy-cookie-capture.md` returns at least 4.
    - `grep -c "redis_keys" README.md` returns at least 1 — the public rate-limit claim now names the enforcing module.
    - `grep -c "will be capped" README.md` returns 0 — the future-tense promise is gone.
    - `grep -c "canary\|source-filtered\|chromium-1223" .planning/deferred-items.md` returns at least 3.
    - `uv run pytest tests/unit -q` exits 0 and `uv run ruff check .` exits 0.
  </acceptance_criteria>
  <done>Every human-gated step in this phase has a runnable, self-describing procedure with an explicit pending-human banner, and the public README's rate-limit promise is auditable against code.</done>
</task>

</tasks>

## Artifacts this phase produces (plan 07)

| Kind | Symbol / path | Notes |
|------|---------------|-------|
| script | `scripts/soak_playwright.py` | exit 0/1/2 like `check_poll_success.py` |
| cli flag | `--duration`, `--sample-every`, `--venues`, `--stub`, `--out` | duration accepts `90s` / `5m` / `12h` |
| function | `_ps_rss_kib(pid) -> int \| None` | CURRENT RSS in KiB, both platforms |
| function | `_playwright_pids() -> list[int]` | `ms-playwright` path token only |
| function | `_proc_rss_kib` / `_proc_playwright_pids` | `/proc` fallback for slim images |
| function | `parse_duration(text) -> int` | pure |
| dataclass | `SoakSample` | ts, poller RSS, playwright RSS, pid count, contexts active, success rate |
| dataclass | `SoakVerdict` | pass flag + per-gate reasons |
| function | `soak_verdict(samples) -> SoakVerdict` | pure; warm-up baseline |
| constant | `RSS_GROWTH_THRESHOLD = 0.20`, `PID_SPREAD_MAX = 2`, `SUCCESS_RATE_THRESHOLD = 0.99`, `WARMUP_SECONDS = 120` | |
| artifact | `logs/soak-<ts>.jsonl` | one JSON object per sample |
| make target | `make soak` | CI-sized default; 12-hour form documented in the target comment |
| doc | `docs/runbooks/perf05-soak.md` | `STATUS: pending-human-run` |
| doc | `docs/runbooks/resy-cookie-capture.md` | `STATUS: pending-human`; referenced by `.env.example` and D-63a |
| doc | `README.md` Legal &amp; Ethical Scraping | present tense, names the enforcing symbols |
| test | `tests/unit/test_soak_verdict.py`, `test_soak_sampling.py` | pure, seconds |
| test | `tests/integration/test_soak_ci.py` | 90 s soak against the stub |
| test | `tests/integration/test_no_zombie_browsers.py` | asserts BOTH the clean and the leaking case |

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| `--out` / `--yaml` style path arguments -> filesystem | Operator-supplied paths, written to |
| soak subprocesses -> the host process table | The harness both reads and (in the leak test) creates OS processes |
| runbooks -> a human handling live credentials | The documentation is the only control on how a third party's session is captured |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-03-33 | Repudiation | soak verdict | high | mitigate | `soak_verdict` is pure and unit-tested at every gate boundary including the warm-up baseline; a run with zero Playwright processes or too few samples exits 2 rather than 0, so a green always means the gate was genuinely exercised |
| T-03-34 | Denial of Service | zombie browsers | critical | mitigate | The leak is reproduced deliberately in `test_no_zombie_browsers.py` and then reaped, so the clean-teardown assertion cannot be vacuous; the PERF-05 PID gate tolerates exactly the two crashpad handlers research observed |
| T-03-35 | Tampering | `--out` path write | medium | mitigate | The output path is resolved and refused outside the repository root before any write (ASVS V12) |
| T-03-36 | Information Disclosure | soak JSONL and runbooks | high | mitigate | Samples contain only process ids, byte counts and rates — never a cookie, a token or a venue identity; the runbooks state explicitly that captured credentials are never committed and live only in the environment and in browser context memory |
| T-03-37 | Repudiation | public README claim | medium | mitigate | The Legal &amp; Ethical Scraping section moves from future to present tense and names the enforcing symbols, so the public commitment is auditable against the code in two hops |
| T-03-38 | Denial of Service | operator disk | low | accept | Roughly 500 MB of stale sibling browser revisions sit in the shared cache; the runbook reports the disk cost as a soak prerequisite but the project does not delete artifacts another tool installed (research Q5) |
| T-03-SC | Tampering | npm/pip/cargo installs | low | accept | No new packages; `psutil` was explicitly rejected in favour of `ps`/`pgrep` subprocesses so nothing is added to the lockfile (research §Alternatives Considered, §Package Legitimacy Audit) |
</threat_model>

## Flagged assumptions (probe, unresolved — review manually)

- **PERF-05 / unclassified** — the edge probe could not classify PERF-05 (`Playwright fleet passes
  12-hour soak test without memory leak or zombie browser processes before Resy goes live`). Carried
  forward explicitly rather than auto-resolved: the requirement fixes neither the sampling interval,
  nor the load profile the fleet must be under during the twelve hours, nor whether the run must be
  against live Resy or may be stub-backed. This plan implements the D-70 thresholds (RSS <= baseline
  + 20 %, PID spread <= 2, success rate >= 0.99) with a 2-minute warm-up baseline and a CI-sized
  90 s stub-backed variant, and records that the twelve-hour run itself is pending-human. A reviewer
  who believes the gate must run against live Resy under production load changes the runbook, not
  the harness — and that distinction is recorded here rather than assumed away.

<verification>
- `uv run pytest tests/unit -q` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 (environment-guarded skips acceptable, failures not).
- `uv run python scripts/soak_playwright.py --duration 90s --sample-every 5s --venues 2 --stub` exits 0.
- `pgrep -f ms-playwright | wc -l` reports 0 after the full suite.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
</verification>

<success_criteria>
- PERF-05's automated half exists, is exercised in CI at 90 seconds, and can genuinely fail.
- The zombie-process failure mode is reproduced and asserted, not merely assumed absent.
- Every human-gated step in the phase has a runbook with an explicit pending-human banner.
- The public README's rate-limit promise is present tense and traceable to the code that enforces it.
</success_criteria>

<output>
Create `.planning/phases/03-resy-playwright-fleet/03-07-SUMMARY.md` when done.
</output>