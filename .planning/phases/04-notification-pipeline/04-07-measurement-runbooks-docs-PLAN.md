---
phase: 04-notification-pipeline
plan: 07
type: execute
wave: 5
depends_on: [04-02, 04-04, 04-06]
files_modified:
  - scripts/check_notification_latency.py
  - scripts/check_false_positive_rate.py
  - tests/integration/test_check_notification_latency.py
  - tests/integration/test_check_false_positive_rate.py
  - Makefile
  - .env.example
  - README.md
  - docs/runbooks/perf01-latency.md
  - docs/runbooks/ios-pwa-push.md
  - .planning/deferred-items.md
autonomous: true
requirements: [PERF-01, PERF-03]

user_setup:
  - service: twilio
    why: "A2P 10DLC approval and a live US number are required before a real SMS can be sent or a real STOP can arrive. Every SMS code path is exercised against a stub and under NOTIFY_DRY_RUN, so no task in this phase blocks on it."
    env_vars:
      - name: TWILIO_MESSAGING_SERVICE_SID
        source: "Twilio Console -> Messaging -> Services"
      - name: TWILIO_WEBHOOK_BASE_URL
        source: "The deployed API hostname; must match the URL configured on the Messaging Service"
    dashboard_config:
      - task: "Point the Messaging Service inbound webhook at POST {TWILIO_WEBHOOK_BASE_URL}/webhooks/twilio/inbound"
        location: "Twilio Console -> Messaging -> Services -> Integration"
      - task: "Point the status callback at POST {TWILIO_WEBHOOK_BASE_URL}/webhooks/twilio/status"
        location: "Twilio Console -> Messaging -> Services -> Integration"
  - service: resend
    why: "Domain verification and an API key are required before a real email can be delivered. All email code paths run against a stub."
    env_vars:
      - name: RESEND_API_KEY
        source: "Resend Dashboard -> API Keys"
      - name: RESEND_WEBHOOK_SECRET
        source: "Resend Dashboard -> Webhooks -> signing secret (whsec_...)"
    dashboard_config:
      - task: "Verify the sending domain (SPF/DKIM/DMARC) so the List-Unsubscribe headers are covered by DKIM"
        location: "Resend Dashboard -> Domains"
      - task: "Create a webhook endpoint at POST {PUBLIC_BASE_URL}/webhooks/resend for email.delivered and email.bounced"
        location: "Resend Dashboard -> Webhooks"

estimate:
  tokens: 58000
  raw_tokens: 58000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`scripts/check_notification_latency.py` computes p95 with `percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)` per channel AND an overall p95 in the same query — never an average of per-channel p95s — over rows with `status IN ('sent','delivered','clicked')`, a non-null `latency_ms` and `created_at` inside the window, and exits 0 only when overall p95 <= 60 s, SMS p95 <= 10 s and push p95 <= 5 s (PERF-01, D-86)."
    - "PROBE PERF-01/unclassified — flagged assumption: 'p95 detection-to-notification latency' is interpreted as the bracket from `availability.events.produced_at` (the CONFIRMING poll's timestamp, not a wall clock) to the moment the row is marked sent, which by construction includes Kafka consumer lag — that is what PERF-01 wants to measure. The polling interval itself is POLL-03's budget and is explicitly OUTSIDE this bracket; the script's docstring says so, so nobody later reads a passing gate as 'the user hears within 60 s of the table opening'."
    - "Both scripts use the three-way exit-code contract `scripts/check_poll_success.py` established — 0 passed, 1 gate failed, 2 not enough data — with the insufficient-data message on stderr, so 'no data yet' can never be mistaken for 'passed' (D-86)."
    - "PROBE PERF-03/boundary: the gate is `< 2 %`, so a computed rate of exactly `0.02` FAILS and `0.0199…` passes; the script has a test at the threshold and one sample either side of it. Fewer than the minimum sample count exits 2 rather than 0, and a day with zero classifiable clicks exits 2 rather than reporting a rate of zero."
    - "PROBE PERF-03/precision: the ratio is `COUNT(*) FILTER (WHERE slot_still_available IS FALSE)::float / NULLIF(COUNT(*) FILTER (WHERE slot_still_available IS NOT NULL), 0)` — rows where the column is NULL are excluded from BOTH numerator and denominator, the `NULLIF` makes a zero denominator a NULL rather than a division error, and the comparison is made on the float ratio without rounding, so a value that would round to 2 % but is below it still passes (D-86a)."
    - "`make verify-perf01` and `make verify-perf03` exist with `##` help strings and appear in `.PHONY`, alongside `make notifier` (`uv run python -m services.notifier`) and `make api` (`uv run uvicorn services.api.app:app`); `make help` lists all four."
    - "`.env.example` gains every environment variable this phase introduced, in the file's existing placeholder style, each with a comment naming what breaks when it is wrong: `RESEND_API_KEY`, `RESEND_API_BASE`, `RESEND_WEBHOOK_SECRET`, `NOTIFY_FROM_EMAIL`, `TWILIO_API_BASE`, `TWILIO_WEBHOOK_BASE_URL`, `TWILIO_STATUS_CALLBACK_URL`, `NOTIFY_DRY_RUN`, `NOTIFY_DAILY_CAP_PER_USER`, `PUBLIC_BASE_URL`, `PHONE_ENCRYPTION_KEY`, `PHONE_HASH_SECRET`, `HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL`, `GO_TOKEN_MAX_AGE_HOURS`, `METRICS_PORT`."
    - "`docs/runbooks/perf01-latency.md` and `docs/runbooks/ios-pwa-push.md` both exist and both carry an explicit `STATUS: pending-human` banner naming the exact actions no agent may perform: the 24-hour production observation window, the real-iPhone PWA push test with five consecutive sends, the Twilio 10DLC approval and live number, and the Resend domain verification. Each runbook states what IS already proven automatically so the human step is not confused with the whole requirement."
    - "`README.md` gains a notification-pipeline section that states, without overclaiming, which Phase-4 criteria are proven in CI (SC2's zero duplicate sends, the deep-link shape, the STOP flow against a signed webhook) and which are `pending-human` (SC1's 24-hour window, SC3's real-iPhone test, and the live-number half of SC4)."
    - "`.planning/deferred-items.md` records every `[ASSUMED]` and every deliberately-deferred item this phase produced, each naming what is wrong, why it was not fixed here, and who picks it up — the two booking-URL schemes, the Resend webhook envelope field, the absent AAD on `encrypt_phone`, the opaque-token SMS alternative, the possible duplicate `notifications.sent`, and the API's read-only import of the state machine's store."
    - statement: "PERF-01 passes over a sustained 24-hour production window and a real iPhone in PWA standalone mode receives five consecutive Web Push notifications without revocation. Neither can be established by any automated test in this repository — the first needs 24 hours of real traffic, the second needs physical hardware and the Phase-6 service worker. Both are runbook-gated and must be reported as pending, never as passes."
      verification: backstop
  artifacts:
    - scripts/check_notification_latency.py
    - scripts/check_false_positive_rate.py
    - tests/integration/test_check_notification_latency.py
    - tests/integration/test_check_false_positive_rate.py
    - docs/runbooks/perf01-latency.md
    - docs/runbooks/ios-pwa-push.md
  key_links:
    - "`notification_log.latency_ms` (written by 04-06) -> `check_notification_latency.py` -> `make verify-perf01`. The gate reads exactly the number the worker wrote; a clamped-at-zero negative and a missing row are both visible here."
    - "`notification_log.slot_still_available` (written by 04-04's `/go`) -> `check_false_positive_rate.py`. The three-way TRUE/FALSE/NULL answer is what makes the denominator honest; a two-way answer would count every expired-state click as a false positive."
    - "`docs/runbooks/*.md` -> the phase verification report. These files are the only place the human-gated half of SC1, SC3 and SC4 is recorded, so a phase that reports them as passes is reporting a fiction."
  prohibitions:
    - "MUST NOT report a pending-human measurement as a pass, in a runbook, in the README, or in a summary."
    - "MUST NOT let 'not enough data' share an exit code with 'passed'."
    - "MUST NOT average per-channel p95 values to produce an overall p95."
    - "MUST NOT count a click whose `slot_still_available` is NULL in either half of the PERF-03 ratio."
    - "MUST NOT print a recipient, a phone number, a token or a provider id in either script's output — the reports are aggregate counts and percentiles only."
    - "MUST NOT overwrite the existing `.env.example`, `Makefile` or `README.md` content; every change is an addition in the file's existing style."
---

<objective>
Ship the two measurement gates the phase is graded on, the Makefile and `.env.example` entries that
make the services runnable, an honest README section, and the two runbooks that carry the
human-gated half of the phase.

Purpose: PERF-01 and PERF-03 are numbers, and a number is only a gate if "not enough data yet" is
distinguishable from "passed". Both scripts therefore copy the three-way exit-code contract PERF-02
already established, and both runbooks state plainly what an agent cannot do — a 24-hour production
window and a physical iPhone — so the phase's report is accurate rather than flattering.
Output: two scripts with integration tests over synthetic fixtures, four Make targets, the provider
env block, a README section, two `pending-human` runbooks, and the deferred-items ledger.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/04-notification-pipeline/04-CONTEXT.md
@.planning/phases/04-notification-pipeline/04-PATTERNS.md
@.planning/phases/04-notification-pipeline/04-04-SUMMARY.md
@.planning/phases/04-notification-pipeline/04-06-SUMMARY.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — synthetic rows through the PERF-01 latency gate and its three exit codes</name>
  <files>scripts/check_notification_latency.py, tests/integration/test_check_notification_latency.py, Makefile</files>
  <read_first>
    - scripts/check_poll_success.py in full (the module docstring naming usage/`make` target/exit codes, the `DATABASE_URL_ASYNC` default and the `postgresql+asyncpg://` strip for raw asyncpg, the module-scope threshold constants, the per-bucket table print, the PASSED/FAILED/INSUFFICIENT lines, and `def main() -> None: sys.exit(asyncio.run(check()))`)
    - shared/db.py `NotificationLog` (the exact columns the query reads, including the 04-02 additions)
    - Makefile in full (the `.PHONY` line, the `##` help-string convention and the `help` target's grep)
    - tests/integration/conftest.py (`apply_migrations`, `db_urls`, `reset_shared_db_singletons`)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"`scripts/check_notification_latency.py` / `check_false_positive_rate.py`" (the mirror contract, the exact percentile SQL and the "do not average per-channel p95s" rule) and §"Latency Budget and Measurement" (what the bracket does and does not include, and the negative-latency clamp)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-86
  </read_first>
  <behavior>
    - Seeded rows whose per-channel p95s are all inside their SLOs, with at least the minimum sample count, exit 0 and print a per-channel table plus a PASSED line.
    - Rows whose SMS p95 exceeds 10 s exit 1 and name the failing channel and its measured value, even when the overall p95 is inside 60 s.
    - Rows whose overall p95 exceeds 60 s exit 1 even when every per-channel p95 passes.
    - Fewer than the minimum sample count exits 2 with the message on stderr and prints nothing that resembles a pass.
    - Zero rows in the window exits 2.
    - Rows with `status='failed'` or a NULL `latency_ms` are excluded from every percentile.
    - The overall p95 is computed across all rows in one query, and a fixture engineered so that the average of the per-channel p95s would pass while the true overall p95 fails still exits 1.
    - `make verify-perf01` invokes the script and propagates its exit code.
  </behavior>
  <action>
Write `scripts/check_notification_latency.py` mirroring `scripts/check_poll_success.py` structurally —
that file is the established contract and deviating from it is how a reader stops trusting the exit
codes. Module docstring: what it asserts, `Usage: uv run python scripts/check_notification_latency.py`,
`Or: make verify-perf01`, and the three exit codes spelled out. Add a paragraph stating exactly what
the measured bracket is and is not: it starts at `availability.events.produced_at`, which is the
CONFIRMING POLL's timestamp rather than a wall clock, and ends when the row is marked sent, so it
includes Kafka consumer lag by design and EXCLUDES the polling interval, which is POLL-03's budget.
Write that down, because a passing gate read as "the user hears within 60 s of the table opening" is
a false claim about the product.

Module-scope constants: `P95_OVERALL_SECONDS = 60`, `P95_SMS_SECONDS = 10`, `P95_PUSH_SECONDS = 5`,
`MIN_SAMPLES = 100`, `WINDOW_HOURS = 24`. Read `DATABASE_URL_ASYNC` with the same default and apply
the same `postgresql+asyncpg://` to `postgresql://` strip before handing it to raw `asyncpg`.

One query computes both the per-channel and the overall percentile — `percentile_cont(0.95) WITHIN
GROUP (ORDER BY latency_ms)` with `GROUPING SETS ((channel), ())` — filtered to
`status IN ('sent','delivered','clicked')`, `latency_ms IS NOT NULL` and
`created_at >= NOW() - INTERVAL '24 hours'`. Comment the grouping set with its reason: averaging
per-channel p95s is not a p95 of anything, and it is the obvious wrong shortcut.

Print a per-channel table (channel, samples, p50, p95, threshold, verdict), then exactly one of
`PASSED`, `FAILED` or the insufficient-data line, the last on stderr with a return of 2. End with
`def main() -> None: sys.exit(asyncio.run(check()))`.

Add to the `Makefile`, in its existing style and added to `.PHONY`: `notifier` (`uv run python -m
services.notifier`), `api` (`uv run uvicorn services.api.app:app`) and `verify-perf01`, each with a
`##` help string so `make help` picks it up.

Write `tests/integration/test_check_notification_latency.py` as the tracer: apply migrations against
the TimescaleDB container, seed synthetic `notification_log` rows shaped for each verdict, invoke the
script as a SUBPROCESS with the container's `DATABASE_URL_ASYNC`, and assert the exit code and the
presence of the verdict line for every bullet in `<behavior>` — including the engineered fixture where
the average of per-channel p95s would pass but the true overall p95 fails.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_check_notification_latency.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_check_notification_latency.py -q -p no:cacheprovider` exits 0, or skips with the existing Docker-guard message on a Docker-less host.
    - `uv run python scripts/check_notification_latency.py` against an empty database exits `2` and writes its reason to stderr.
    - `make help` output contains lines for `notifier`, `api` and `verify-perf01`.
    - `uv run python -c "import scripts.check_notification_latency as c; print(c.P95_OVERALL_SECONDS, c.P95_SMS_SECONDS, c.P95_PUSH_SECONDS, c.MIN_SAMPLES)"` prints `60 10 5 100`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Synthetic rows drive the PERF-01 gate through all three of its exit codes as a real subprocess, and `make verify-perf01` runs it.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The PERF-03 false-positive gate, exact at the threshold and honest about NULLs</name>
  <files>scripts/check_false_positive_rate.py, tests/integration/test_check_false_positive_rate.py, Makefile</files>
  <read_first>
    - scripts/check_notification_latency.py as written in Task 1 (the contract this file mirrors)
    - scripts/check_poll_success.py (the `HourlyBucket` dataclass and the per-bucket print shape)
    - services/api/routers/links.py as written in 04-04 (the three-way TRUE/FALSE/NULL write this script reads)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"`slot_still_available`" (why an absent Redis record must not be scored FALSE, and the exact denominator expression) and §"Open Questions" OQ-5 (per-channel rows, and why the ratio is unaffected)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-86, §D-86a
    - .planning/REQUIREMENTS.md PERF-03 (the literal `< 2%` wording the boundary test pins)
  </read_first>
  <behavior>
    - A day whose ratio is `0.0199` exits 0; a day whose ratio is exactly `0.02` exits 1; a day whose ratio is `0.0201` exits 1.
    - Clicks with `slot_still_available IS NULL` are excluded from both numerator and denominator: a fixture of 1 FALSE, 99 TRUE and 500 NULL rows yields `0.01`, not `0.00166…`.
    - A day with zero non-NULL rows exits 2 rather than printing a rate of zero.
    - Fewer than the minimum sample count exits 2.
    - The output reports the numerator, the denominator, the excluded NULL count and the ratio, and the excluded count is shown so a reader can see how much of the data was unclassifiable.
    - Rows are bucketed by day and the worst qualifying day drives the verdict.
    - `make verify-perf03` invokes the script and propagates its exit code.
  </behavior>
  <action>
Write `scripts/check_false_positive_rate.py` to the same contract: module docstring with usage, the
`make verify-perf03` target and the three exit codes; module-scope
`FALSE_POSITIVE_THRESHOLD = 0.02`, `MIN_SAMPLES`, `WINDOW_DAYS`; the same URL handling; and
`def main() -> None: sys.exit(asyncio.run(check()))`.

The ratio is
`COUNT(*) FILTER (WHERE slot_still_available IS FALSE)::float / NULLIF(COUNT(*) FILTER (WHERE
slot_still_available IS NOT NULL), 0)`, grouped by day. Comment BOTH halves with their reasons: NULL
means the Phase-2 slot record had already passed its 25-hour TTL when the click arrived, so the state
is UNKNOWN rather than negative — counting those as false positives would inflate the rate with stale
clicks instead of real ones (D-86a) — and the `NULLIF` turns a zero denominator into a NULL the code
reports as insufficient data rather than into a division error. Compare the float ratio directly
against the threshold with a strict `<`, because PERF-03's wording is `< 2%`, and note in a comment
that a rate of exactly `0.02` therefore FAILS. Do not round before comparing.

Print, per day: total clicks, classifiable clicks, false positives, excluded NULLs, and the rate;
then the single verdict line. Showing the excluded count is the point — a run where most clicks were
unclassifiable is a different situation from a clean pass, and the reader must be able to see it.

Note in the docstring, per OQ-5, that one alert on a three-channel watch produces three
`notification_log` rows and therefore up to three click records, so the counts are PER CHANNEL and
must not be read as "unique alerts"; the ratio is unaffected because numerator and denominator scale
together.

Add `verify-perf03` to the `Makefile` with its `##` help string and to `.PHONY`.

Write `tests/integration/test_check_false_positive_rate.py` seeding synthetic rows for each bullet —
in particular the three boundary fixtures at `0.0199`, exactly `0.02` and `0.0201`, and the
NULL-exclusion fixture whose two possible denominators give visibly different answers — invoking the
script as a subprocess and asserting the exit code and the reported numbers.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_check_false_positive_rate.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_check_false_positive_rate.py -q -p no:cacheprovider` exits 0, or skips on a Docker-less host.
    - `uv run python scripts/check_false_positive_rate.py` against an empty database exits `2`.
    - `uv run python -c "import scripts.check_false_positive_rate as c; print(c.FALSE_POSITIVE_THRESHOLD)"` prints `0.02`.
    - `make help` output contains a line for `verify-perf03`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>The PERF-03 gate is exact at its threshold, excludes unclassifiable clicks from both halves of the ratio, reports how many it excluded, and refuses to call an empty day a pass.</done>
</task>

<task type="auto">
  <name>Task 3: Environment block, README section, the two pending-human runbooks, and the deferred ledger</name>
  <files>.env.example, README.md, docs/runbooks/perf01-latency.md, docs/runbooks/ios-pwa-push.md, .planning/deferred-items.md</files>
  <read_first>
    - .env.example in full (the section headers, the `your_..._here` placeholder style, and the long explanatory comments on `MISE_CRASH_AFTER` and `STATE_MACHINE_MAX_ATTEMPTS` that set the tone)
    - docs/runbooks/perf02-24h-log.md in full (the structure `perf01-latency.md` mirrors: preconditions, procedure, evidence to capture, pass criteria)
    - docs/runbooks/twilio-10dlc-setup.md in full (the pending-status banner convention `ios-pwa-push.md` mirrors)
    - README.md (the existing sections, especially "Legal & Ethical Scraping" and the tradeoff sections, so the new section matches the voice)
    - .planning/deferred-items.md in full (the four-column table and the "what is wrong / why deferred" discipline)
    - .planning/ROADMAP.md Phase 4 success criteria 1-5 (the exact claims the README section must be honest about)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Assumptions Log" (A1-A10 — the source list for the deferred ledger) and §"Runtime State Inventory" (the live-service configuration that lives in vendor consoles rather than in git)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-87 (the `STATUS: pending-human` spelling to use in both files)
  </read_first>
  <acceptance_criteria>
    - `grep -c "STATUS: pending-human" docs/runbooks/perf01-latency.md docs/runbooks/ios-pwa-push.md` reports at least one match in each file.
    - `uv run python -c "import re,pathlib; t=pathlib.Path('.env.example').read_text(); names=['RESEND_API_KEY','RESEND_API_BASE','RESEND_WEBHOOK_SECRET','NOTIFY_FROM_EMAIL','TWILIO_API_BASE','TWILIO_WEBHOOK_BASE_URL','TWILIO_STATUS_CALLBACK_URL','NOTIFY_DRY_RUN','NOTIFY_DAILY_CAP_PER_USER','PUBLIC_BASE_URL','PHONE_ENCRYPTION_KEY','PHONE_HASH_SECRET','HMAC_TOKEN_VERSION','HMAC_GRACE_UNTIL','GO_TOKEN_MAX_AGE_HOURS','METRICS_PORT']; print(sorted(n for n in names if n+'=' not in t))"` prints `[]`.
    - `uv run python -c "import pathlib; t=pathlib.Path('.env.example').read_text(); print(all(k in t for k in ('KAFKA_BOOTSTRAP_SERVERS','MISE_CRASH_AFTER','RESY_ACCOUNTS_JSON','VAPID_SUBJECT','HMAC_MGMT_SECRET_V1')))"` prints `True` — every pre-existing entry survived.
    - `grep -c "^|" .planning/deferred-items.md` returns a value strictly greater than its pre-plan count.
    - `grep -n "pending-human" README.md` prints at least one line.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0 and `uv run ruff check .` exits 0.
  </acceptance_criteria>
  <action>
Append a provider/notification block to `.env.example` in the file's existing style, with the same
density of explanatory comment the `MISE_CRASH_AFTER` and `STATE_MACHINE_MAX_ATTEMPTS` entries carry.
Add: `RESEND_API_KEY`, `RESEND_API_BASE`, `RESEND_WEBHOOK_SECRET`, `NOTIFY_FROM_EMAIL`,
`TWILIO_API_BASE`, `TWILIO_WEBHOOK_BASE_URL`, `TWILIO_STATUS_CALLBACK_URL`, `NOTIFY_DRY_RUN`,
`NOTIFY_DAILY_CAP_PER_USER`, `PUBLIC_BASE_URL`, `PHONE_ENCRYPTION_KEY`, `PHONE_HASH_SECRET`,
`HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL`, `GO_TOKEN_MAX_AGE_HOURS`, `METRICS_PORT`. For the ones whose
failure mode is silent, say what breaks: a `TWILIO_WEBHOOK_BASE_URL` that does not match the URL
configured in the console makes every inbound STOP fail signature verification, which means users
cannot opt out; a `PHONE_ENCRYPTION_KEY` that does not decode to 32 bytes fails at startup by design;
a `PUBLIC_BASE_URL` with a longer host consumes the SMS body's septet headroom; `NOTIFY_DRY_RUN`
short-circuits every provider and is the local demo path. Change nothing that is already there.

Write `docs/runbooks/perf01-latency.md` in the shape of `docs/runbooks/perf02-24h-log.md`, opening
with a `STATUS: pending-human` banner. State plainly what IS already automated — the end-to-end
latency measurement exists, `notification_log.latency_ms` is written on every send, and
`make verify-perf01` enforces the thresholds with a three-way exit code — and what a human must do:
run the stack against real traffic for 24 hours with real provider credentials, then run the gate and
capture its output. List the preconditions (Twilio 10DLC approval and a live number, Resend domain
verification, the deployed API hostname configured in both consoles), the procedure, the evidence to
capture, and the pass criteria copied from ROADMAP SC1.

Write `docs/runbooks/ios-pwa-push.md` in the shape of `docs/runbooks/twilio-10dlc-setup.md`, also
opening with `STATUS: pending-human`. It covers ROADMAP SC3: a real iPhone in PWA standalone mode
receiving five consecutive pushes without the subscription being revoked. State the sender-side
obligations this phase already satisfies and tests — a non-empty `title` and `body` on every payload,
a payload well under 4096 bytes, a per-endpoint VAPID audience, a 12-hour expiry, and 404/410 marking
`revoked_at` — and state clearly that the service worker whose `push` handler must wrap the entire
async chain in `event.waitUntil(...)` is PHASE 6, so this runbook cannot be executed until then.
Record the failure signature to watch for: pushes stop after roughly three sends with nothing in the
logs, and `push_subscriptions.revoked_at` fills up for iOS user agents. Note the spelling choice —
this phase uses `STATUS: pending-human` per D-87, while Phase 3's runbooks use
`STATUS: pending-human-run` — so a future grep knows to look for both.

Add a notification-pipeline section to `README.md` matching the file's existing voice. Describe the
two consumer loops, the claim-before-send ordering, and the three channels. Then be explicit about
what is and is not proven: SC2's zero-duplicate-sends property is proven in CI by a SIGKILL subprocess
test with a provider-side hit-log oracle; the deep-link shape and the STOP flow are proven against
signed webhook fixtures; SC1's 24-hour window, SC3's real-iPhone test and the live-number half of SC4
are `pending-human` and named as such. Do not describe the pipeline as exactly-once.

Extend `.planning/deferred-items.md` with one row per item, each naming what is wrong, why it was not
fixed in the plan that found it, and who picks it up: the two `[ASSUMED]` booking-URL schemes and the
recorded alternate OpenTable form (A1/A2, needs a human click-through); the `[ASSUMED]` Resend webhook
envelope field name (A3, confirmable only against a real delivery); the deliberate absence of AAD on
`encrypt_phone` (D-89 — a v2 hardening item that would be a data migration later); the opaque-token
SMS alternative that buys ~20 septets at the cost of D-82's uniform token shape (recorded, not
recommended); the possible duplicate `notifications.sent` in the last crash window (deterministic
`job_id` makes downstream dedupe available); and the API tier's read-only import of
`services/state_machine/store.py`, which extends the existing 02-04 note about that module dragging
its Redis dependency along.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit -q -W error::RuntimeWarning &amp;&amp; uv run ruff check .</automated>
  </verify>
  <done>Every environment variable the phase introduced is documented with its failure mode, both human-gated criteria have a runbook that says what a human must do and what is already proven, the README claims only what CI proves, and every assumption this phase made is on the deferred ledger.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (04-07 slice)

**New scripts:** `scripts/check_notification_latency.py` (constants `P95_OVERALL_SECONDS=60`,
`P95_SMS_SECONDS=10`, `P95_PUSH_SECONDS=5`, `MIN_SAMPLES=100`, `WINDOW_HOURS=24`; exit codes 0/1/2),
`scripts/check_false_positive_rate.py` (constants `FALSE_POSITIVE_THRESHOLD=0.02`, `MIN_SAMPLES`,
`WINDOW_DAYS`; exit codes 0/1/2).

**New Make targets:** `notifier` -> `uv run python -m services.notifier`; `api` ->
`uv run uvicorn services.api.app:app`; `verify-perf01` -> `uv run python
scripts/check_notification_latency.py`; `verify-perf03` -> `uv run python
scripts/check_false_positive_rate.py`. All four added to `.PHONY` with `##` help strings.

**Env vars documented in `.env.example`:** `RESEND_API_KEY`, `RESEND_API_BASE`,
`RESEND_WEBHOOK_SECRET`, `NOTIFY_FROM_EMAIL`, `TWILIO_API_BASE`, `TWILIO_WEBHOOK_BASE_URL`,
`TWILIO_STATUS_CALLBACK_URL`, `NOTIFY_DRY_RUN`, `NOTIFY_DAILY_CAP_PER_USER`, `PUBLIC_BASE_URL`,
`PHONE_ENCRYPTION_KEY`, `PHONE_HASH_SECRET`, `HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL`,
`GO_TOKEN_MAX_AGE_HOURS`, `METRICS_PORT`.

**New runbooks:** `docs/runbooks/perf01-latency.md` (`STATUS: pending-human` — the 24-hour production
window, ROADMAP SC1), `docs/runbooks/ios-pwa-push.md` (`STATUS: pending-human` — the real-iPhone
five-push test, ROADMAP SC3; blocked on the Phase-6 service worker).

**Docs:** a notification-pipeline section in `README.md` distinguishing CI-proven criteria from
`pending-human` ones; new rows in `.planning/deferred-items.md` for A1/A2 (booking URLs), A3 (Resend
webhook envelope), the absent AAD (D-89), the opaque-token SMS alternative, the duplicate
`notifications.sent` window, and the API's read-only store import.
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| operator -> measurement scripts | Aggregate reads over `notification_log`; the output is read as evidence |
| repository -> vendor consoles | Webhook URLs and signing secrets live in Twilio and Resend, not in git |
| documentation -> reviewer | A runbook or README that overstates what is proven is itself a security-relevant failure of reporting |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-04-43 | Repudiation | "insufficient data" reported as a pass | high | mitigate | Three-way exit codes copied from the established PERF-02 contract; the insufficient-data message goes to stderr and returns 2; integration tests assert each code |
| T-04-44 | Information Disclosure | a measurement script printing a recipient, phone number or token | medium | mitigate | Both scripts emit only aggregate counts and percentiles; no row-level identifier is selected or printed |
| T-04-45 | Repudiation | a phase report claiming SC1 or SC3 passed | high | mitigate | Both are `STATUS: pending-human` runbooks; the README names them as pending; a prohibition in this plan forbids reporting them as passes |
| T-04-46 | Spoofing | webhook URLs and signing secrets drifting out of sync with a redeploy | medium | mitigate | The runbooks record the exact console paths and the exact URLs, so a new hostname is a documented step rather than a silent break in STOP handling |
| T-04-47 | Information Disclosure | a real secret pasted into `.env.example` | high | mitigate | The file keeps its placeholder style; the additions are `your_..._here` values with explanatory comments, and `.env` remains gitignored |
| T-04-SC | Tampering | package-manager installs | high | mitigate | Zero packages added across the whole phase (research §Package Legitimacy Audit); `tests/unit/test_no_new_runtime_deps.py` from 04-04 keeps `python-multipart` out |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 or skips cleanly without Docker.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `make help` lists `notifier`, `api`, `verify-perf01` and `verify-perf03`.
- `uv run python scripts/check_notification_latency.py; echo $?` and the same for `check_false_positive_rate.py` both report `2` against an empty database.
</verification>

<success_criteria>
- Both gates exist, mirror the PERF-02 exit-code contract, and are driven through all three codes by integration tests over synthetic fixtures.
- The PERF-03 ratio is exact at its threshold and excludes unclassifiable clicks from both halves.
- Every environment variable the phase introduced is in `.env.example` with its failure mode described.
- Both human-gated criteria have a `STATUS: pending-human` runbook, and nothing in the repo reports them as passes.
- Every `[ASSUMED]` this phase relied on is recorded in the deferred ledger with an owner.
</success_criteria>

<output>
Create `.planning/phases/04-notification-pipeline/04-07-SUMMARY.md` when done
</output>
