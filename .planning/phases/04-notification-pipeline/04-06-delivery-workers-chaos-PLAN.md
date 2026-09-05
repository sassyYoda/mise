---
phase: 04-notification-pipeline
plan: 06
type: execute
wave: 4
depends_on: [04-02, 04-03, 04-05]
files_modified:
  - services/notifier/workers.py
  - services/notifier/persistence.py
  - services/notifier/main.py
  - services/notifier/__main__.py
  - services/notifier/README.md
  - tests/fakes/provider_stub.py
  - tests/integration/test_notifier_e2e.py
  - tests/integration/test_notifier_chaos.py
  - tests/unit/test_idempotency_ordering.py
  - tests/unit/test_no_inline_sleep.py
  - tests/unit/test_no_setnx_expire_pairs.py
  - tests/unit/test_kafka_consumer_config.py
  - tests/unit/test_logs_never_carry_payload.py
autonomous: true
requirements: [NOTIF-02, NOTIF-03, NOTIF-04, NOTIF-05, NOTIF-06, PERF-01]

estimate:
  tokens: 74000
  raw_tokens: 74000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "The delivery worker executes one job in exactly this order, with nothing reordered: Layer-2 `SET NX EX` claim -> `queued` row upsert -> render -> provider call (with retries) -> `notification_log` UPDATE to `sent`/`failed` -> `notifications.sent` publish -> offset commit. A unit test with a fake provider that records call ordering proves the claim strictly PRECEDES the provider call, which is the property NOTIF-02 and ROADMAP SC2 actually require (D-76)."
    - "SC2, proven end to end: a subprocess notifier launched with `MISE_CRASH_AFTER=provider_ack` SIGKILLs itself after a stub provider returns 2xx and before the offset commit; on restart the redelivered job finds its claim held, writes `duplicate_suppressed`, and the stub's hit log shows EXACTLY ONE call and the database EXACTLY ONE non-suppressed row per `(watch, channel)`. The subprocess exit code is asserted as `-9` OR `137`, because `uv run` is the direct child and relays a killed grandchild as 128 + signal (Phase-2 02-03 deviation) — without that assertion a run where the hook never fired would pass vacuously."
    - "A Layer-2 claim that already exists writes a `duplicate_suppressed` row, makes NO provider call, and still commits the offset; the claim is DELETED only on a DEFINITIVE provider failure so a later redelivery can re-attempt, and is NEVER deleted on success — deleting on success would re-open the duplicate window for a rebalancing consumer (D-76, research §Anti-Patterns)."
    - "PROBE NOTIF-06/unclassified — flagged assumption: 'commits only after provider acknowledgement' is interpreted as commit-after-DURABILITY, not commit-after-HTTP-response. The offset is committed only after the `notification_log` row is durable AND `notifications.sent` has been acknowledged by the broker, because the row is the audit trail the SC2 proof and the PERF-01 measurement both read. Unlike the Phase-2 state machine's deliberately best-effort persistence, a failed row write here takes the TRANSIENT arm and does not commit (research §Pitfall 3)."
    - "PROBE PERF-01/unclassified — flagged assumption: the PERF-01 clock starts at `event.produced_at_epoch_ms`, which is the CONFIRMING POLL's timestamp rather than a wall clock, and stops at the moment the row is marked sent. `latency_ms = sent_at - produced_at`, CLAMPED AT ZERO with a `clock_skew_suspected` warning on a negative computation — a negative row silently drags the p95 down and makes the gate lie (D-45, D-86)."
    - "The end-to-end integration test publishes one `availability.events` message and observes, on a real broker with real containers, one `notifications.queued` job per channel, one stub provider call per channel, one `notifications.sent` message per channel carrying a populated non-negative `latency_ms`, and one `notification_log` row per channel with `status='sent'`, `provider_id` and `sent_at` set (PERF-01, NOTIF-06)."
    - "Per-channel failure handling is exactly D-79: an email that exhausts 3 attempts records `failed`, deletes its claim and is dead-lettered to `notifications.dlq`; an SMS that exhausts 2 attempts records `failed`, deletes its claim and enqueues an `sms_failed_fallback` email when `email` is one of the watch's channels; a push 404/410 sets `push_subscriptions.revoked_at`, records `error='subscription_revoked'`, falls back to email, and is NOT dead-lettered."
    - "A job for a channel whose credentials are absent records `status='failed'`, `error='provider_unconfigured'` and deletes its claim so it can be retried once configured, rather than raising or silently dropping (D-80)."
    - "A job whose user has `sms_opt_out = true` never reaches the SMS provider even if the message was queued before the opt-out — the check is repeated at the worker, because the queue can outlive the opt-out."
    - "`services/notifier/main.py` refuses to start when `MISE_CRASH_AFTER` is set and `ENV` is not EXPLICITLY one of the shared allowlist, guards that all seven required topics exist including `notifications.dlq`, runs BOTH consumer loops concurrently under one `asyncio.TaskGroup` passed to a single `run_until_signal`, shares ONE `AIOKafkaProducer`, and unwinds an `AsyncExitStack` with `dispose_engine` registered first so it tears down last (D-75, Pattern 4)."
    - "`services/notifier/README.md` reproduces the six-row crash-point table with BOTH honest caveats stated rather than papered over: an alert crashed between claim and provider is LOST for 24 hours by deliberate choice, and a duplicate `notifications.sent` is possible after the last crash window — the pipeline is not described as exactly-once, and `job_id` determinism is named as the downstream dedupe key."
    - "`tests/unit/test_no_inline_sleep.py` scans `services/notifier/*.py`, `services/notifier/providers/*.py` and `services/api/**/*.py` in addition to the state machine, with its non-vacuity floor raised and the new module names asserted in the scanned set; its docstring records that `tenacity`'s own sleep lives inside its package and is therefore out of scope for this file-scoped gate, so nobody 'fixes' the gate with an allowlist."
  artifacts:
    - services/notifier/workers.py
    - services/notifier/main.py
    - services/notifier/README.md
    - tests/fakes/provider_stub.py
    - tests/integration/test_notifier_e2e.py
    - tests/integration/test_notifier_chaos.py
    - tests/unit/test_idempotency_ordering.py
  key_links:
    - "`set_nx_ex(notif_idempotency_key(...))` -> the provider call. Everything about SC2 is that this edge is directed and never reversed; the chaos test's stub hit log is the provider-side oracle that proves it."
    - "`upsert_queued_row()` -> `notification_log.id` -> `sign_token('go', {'n': id})` -> `render_sms`/`render_email`. The row must exist before the render, which is why the phase creates it as `queued` right after the claim rather than after the provider replies."
    - "`event.produced_at_epoch_ms` -> `latency_ms` -> `notifications.sent` AND `notification_log.latency_ms` -> `scripts/check_notification_latency.py` (04-07). One number, written twice, read by the PERF-01 gate."
    - "`tests/fakes/provider_stub.py` -> the chaos subprocess. `respx` patches httpx IN-PROCESS and cannot survive a SIGKILLed child, so the SID-level duplicate oracle has to be a real listener whose hit log the parent reads over a control endpoint (the Phase-3 `resy_stub` shape)."
    - "`shared.crash_hook.maybe_crash` -> the five Phase-4 stages. `provider_ack` is the SC2 stage; the others exist so the crash table in the README is executable rather than asserted."
  prohibitions:
    - "MUST NOT call a provider before the Layer-2 claim has succeeded, under any code path, including the fallback and dry-run paths."
    - "MUST NOT delete the Layer-2 claim on SUCCESS. It is deleted only on a definitive provider failure, and never as cleanup."
    - "MUST NOT commit an offset before the `notification_log` row is durable and `notifications.sent` has been acknowledged."
    - "MUST NOT enable auto-commit on either consumer, and MUST NOT commit past a message whose handler failed transiently."
    - "MUST NOT send an SMS to a user whose `sms_opt_out` is true, including as the SMS-failure fallback path."
    - "MUST NOT store a negative `latency_ms`."
    - "MUST NOT describe the pipeline as exactly-once in the README, in a docstring, or in a log line."
    - "MUST NOT wait with a bare `asyncio.sleep` or `time.sleep` anywhere under `services/notifier/` or `services/api/`."
    - "MUST NOT log a rendered body, a recipient, a provider credential, or a `provider_id` alongside a recipient."
---

<objective>
Ship the delivery half of the notifier — the second consumer loop that claims, renders, sends,
records, publishes and commits in that order — plus the service entrypoint that runs both loops under
one lifespan, and the chaos test that proves ROADMAP SC2 with a real SIGKILL and a provider-side
duplicate oracle.

Purpose: SC2 is the phase's hardest guarantee and the one most easily faked. A unit test with a mock
proves an intention; a subprocess killed by an uncatchable signal between a real 2xx and a real offset
commit, restarted, showing exactly one call in a listener's hit log, proves the property. This plan
also produces the `latency_ms` number PERF-01 is measured from.
Output: `services/notifier/{workers,main,__main__}.py`, an honest crash-table README, a provider stub
that survives a killed child, and the e2e and chaos integration tests.
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
@.planning/phases/04-notification-pipeline/04-02-SUMMARY.md
@.planning/phases/04-notification-pipeline/04-03-SUMMARY.md
@.planning/phases/04-notification-pipeline/04-05-SUMMARY.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — one queued job claimed, sent, recorded, published and committed</name>
  <files>services/notifier/workers.py, services/notifier/persistence.py, services/notifier/main.py, services/notifier/__main__.py, tests/integration/test_notifier_e2e.py</files>
  <read_first>
    - services/state_machine/consumer.py lines 330-400 (`_apply_emit`'s claim/send/persist ordering and its `_maybe_crash` placement) and lines 200-260 (the transient rewind)
    - services/state_machine/main.py in full (the `AsyncExitStack` lifespan, the `REQUIRED_TOPICS` guard, the fail-closed crash-hook interlock, and `run_until_signal`)
    - services/state_machine/__main__.py (the two-line entrypoint shape)
    - shared/shutdown.py (`run_until_signal`'s signature — it takes ONE awaitable, so the two loops fan out inside it)
    - services/notifier/{config,consumer,persistence}.py as written in 04-03 and `providers/*` + `templates.py` as written in 04-05
    - shared/redis_keys.py (`notif_idempotency_key`, `NOTIF_IDEMPOTENCY_TTL_SECONDS`, `set_nx_ex`) and shared/crash_hook.py (`maybe_crash` and its stage list)
    - tests/integration/test_state_machine_e2e.py in full (the container plumbing, the topic creation, the drain helper and the assertion style)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Ordering and crash windows" (the six-row crash table and the two honest caveats), §"Latency Budget and Measurement" (the budget walk-through and the clamp rule), §"Architecture Patterns" Pattern 1 and Pattern 4
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-75, §D-76, §D-77, §D-79, §D-80, §D-86
  </read_first>
  <behavior>
    - One `availability.events` message with a matching three-channel watch produces three `notifications.queued` jobs, three stub provider calls, three `notifications.sent` messages and three `notification_log` rows with `status='sent'`.
    - Each `NotificationSent` carries a `latency_ms` equal to its row's `latency_ms`, is non-negative, and equals `sent_at - event.produced_at_epoch_ms`.
    - A job whose computed latency would be negative stores `0` and emits a `clock_skew_suspected` warning.
    - Replaying the same queued job finds the claim held, writes `duplicate_suppressed`, makes no provider call, and commits.
    - A job for a channel with no configured credentials records `failed` / `provider_unconfigured`, deletes its claim, and commits.
    - With `NOTIFY_DRY_RUN=true` the whole path runs, records `sent` with a `dry-run-` provider id, and makes zero outbound requests.
    - Both consumer loops run concurrently under one `run_until_signal`; a SIGTERM unwinds the exit stack rather than killing the process, and the producer is shared.
    - Starting with `MISE_CRASH_AFTER` set and `ENV=staging` raises at startup naming the allowlist.
  </behavior>
  <action>
Write `services/notifier/workers.py` — loop B, consuming `notifications.queued` in the
`notifier-workers` group. Class `NotifierDeliveryWorker(consumer, producer, redis_client, providers,
...)` with `run()` and `handle_job(msg)`. `handle_job` executes D-76's order with a `maybe_crash`
call immediately after each named stage, and the ordering is the module's whole point, so write each
step's reason as a comment:

1. Parse `NotificationQueued`; a `ValidationError` is poison — dead-letter and commit past.
2. `set_nx_ex(notif_idempotency_key(watch_id, event_id, channel), "1",
   NOTIF_IDEMPOTENCY_TTL_SECONDS)`. On failure: `mark_duplicate_suppressed`, publish nothing, commit.
   `maybe_crash("nx_claim")`.
3. `upsert_queued_row(...)` to obtain the `notification_log.id` the `go` token names.
4. Load the watch/user/restaurant context; re-check `sms_opt_out` for an `sms` job and record
   `failed` / `sms_opt_out` if it is now set — the queue can outlive the opt-out.
5. Mint the `go` token with `n = row_id`, build the `go` and unsubscribe URLs, and render the channel's
   message.
6. Call the provider through the shared retry wrapper. `maybe_crash("provider_ack")` immediately
   after a successful call — this is the SC2 stage.
7. `mark_sent(row_id, provider_id, sent_at, latency_ms)` where `latency_ms = max(0, sent_at_ms -
   event.produced_at_epoch_ms)`, logging `clock_skew_suspected` when the raw value is negative. This
   write is NOT best-effort: a failure takes the transient arm and does not commit.
   `maybe_crash("log_insert")`.
8. `send_and_wait` a `NotificationSent` to `notifications.sent` keyed by the watch id.
   `maybe_crash("sent_publish")`.
9. Commit the offset. `maybe_crash("commit")`.

Failure arms, exactly per D-79: a definitive provider failure records `failed`, DELETES the claim so a
later redelivery can re-attempt, and then — email only — dead-letters to `notifications.dlq`; an SMS
exhaustion additionally enqueues an `sms_failed_fallback` email job when `email` is one of the watch's
channels; a `PushSubscriptionRevoked` sets `push_subscriptions.revoked_at`, records
`error='subscription_revoked'`, falls back to email and is NOT dead-lettered. An unconfigured channel
records `provider_unconfigured` and deletes its claim. Write, as a comment on the delete, that the
claim is NEVER deleted on success — that would re-open the duplicate window for a rebalancing
consumer.

Write `services/notifier/main.py` mirroring `services/state_machine/main.py`: `configure_logging()`;
the fail-closed crash-hook interlock using the shared `crash_hook_allowed()` and `CRASH_HOOK_ENVS`;
`assert_crypto_env()`; `_assert_topics_exist` over the seven required topics INCLUDING
`notifications.dlq`; an `AsyncExitStack` with `dispose_engine` pushed first, then the Redis client,
then ONE shared `AIOKafkaProducer`, then both consumers; construction of only those providers whose
credentials are present (D-80); an optional Prometheus HTTP server on `METRICS_PORT` when set; and
`await run_until_signal(...)` over a single awaitable that fans both loops out through an
`asyncio.TaskGroup`, so a failing loop cancels its sibling instead of leaving it running against a
closing Redis (the Phase-2 WR-05 lesson). Write `services/notifier/__main__.py` as the two-line
entrypoint.

Write `tests/integration/test_notifier_e2e.py` driving the whole pipeline in-process against live
Kafka, Redis and TimescaleDB containers with the providers pointed at `respx`-mocked base URLs: seed
the restaurant/user/watch, publish one `availability.events` message, run both loops until the
expected messages arrive, and assert every bullet in `<behavior>`. Assert the `latency_ms` identity
rather than merely that the field is present.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_notifier_e2e.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_notifier_e2e.py -q -p no:cacheprovider` exits 0, or skips with the existing Docker-guard message on a Docker-less host.
    - `ENV=staging MISE_CRASH_AFTER=provider_ack uv run python -m services.notifier` exits non-zero and its stderr names the allowlisted environments.
    - `uv run python -c "import inspect, services.notifier.main as m; s=inspect.getsource(m); print('notifications.dlq' in s, 'TaskGroup' in s, 'run_until_signal' in s, 'dispose_engine' in s)"` prints `True True True True`.
    - `uv run python -c "import inspect, services.notifier.workers as w; s=inspect.getsource(w); print(s.index('set_nx_ex') &lt; s.index('send_with_retry'))"` prints `True`.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>One availability event travels the entire pipeline on real infrastructure — fan-out, claim, render, mocked provider, durable row, published `NotificationSent` with a real measured latency, committed offset — and the service runs both loops under one signal-aware lifespan.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The SC2 chaos proof — SIGKILL between provider ack and commit, with a provider-side duplicate oracle</name>
  <files>tests/fakes/provider_stub.py, tests/integration/test_notifier_chaos.py, services/notifier/workers.py</files>
  <precondition>A Docker-compatible runtime is reachable; the test module skips through the existing `tests/conftest.py` guard when it is not. `tests/fakes/__init__.py` already exists (created by Phase 3 plan 03-04) — add to that package, do not recreate it.</precondition>
  <read_first>
    - tests/integration/test_state_machine_chaos.py in full (the subprocess launch, the SIGKILL expectation, the `-SIGKILL` OR `137` returncode reasoning recorded in STATE.md as the 02-03 deviation, the drain helper and the exactly-once assertions)
    - tests/fakes/resy_stub.py as created by Phase 3 plan 03-04 (the in-test HTTP stub with a mode-control endpoint and a readable hit log — the shape to copy)
    - services/notifier/workers.py as written in Task 1 (the `maybe_crash` stage placement)
    - shared/crash_hook.py (`maybe_crash`, `crash_hook_allowed`, the stage list)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Ordering and crash windows" (the crash table row for `provider_ack` and what must be true after restart) and §"Code Examples" — "respx as the SID-level duplicate oracle" (and why a tuple, not a list)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-87 and §specifics (the chaos test should read like the ROADMAP SC2 sentence)
  </read_first>
  <behavior>
    - The stub serves the Resend and Twilio endpoints, records every request in a hit log keyed by path plus a caller-supplied correlation value, and exposes the log over a control endpoint the parent process reads.
    - The stub can be switched to return a chosen status so the definitive-failure and retry arms are exercisable from a subprocess too.
    - A notifier subprocess launched with `MISE_CRASH_AFTER=provider_ack`, `ENV=test` and the provider base URLs pointed at the stub dies with returncode `-9` or `137`.
    - Before the kill, the stub's hit log holds exactly one call for the job's channel.
    - After a clean restart with the hook unset, the job is redelivered, the claim is found held, a `duplicate_suppressed` row is written, and the stub's hit log STILL holds exactly one call for that channel.
    - The database holds exactly one non-suppressed `notification_log` row per `(watch, channel)`.
    - The offset advances past the job after the restart, so the pipeline is not wedged.
  </behavior>
  <action>
Write `tests/fakes/provider_stub.py` in the shape of Phase 3's `tests/fakes/resy_stub.py`: a small
ASGI app served on an ephemeral port for the duration of a test, exposing
`POST /emails` (Resend-shaped 200 with a generated id) and
`POST /2010-04-01/Accounts/{sid}/Messages.json` (Twilio-shaped 201 with a generated sid), plus
`POST /__ctl/mode` to switch the returned status and `GET /__ctl/hits` returning the recorded request
log. State in the module docstring WHY this exists rather than `respx`: `respx` patches httpx inside
the running interpreter, and the SC2 proof requires a subprocess that is SIGKILLed, so the duplicate
oracle has to be a real listener whose hit log survives the child's death and is readable from the
parent. The generated ids are the SID-level oracle the ROADMAP sentence names.

Write `tests/integration/test_notifier_chaos.py` so it reads like the ROADMAP SC2 sentence. Start the
containers and the stub; create topics; apply migrations; seed a restaurant, user and an active watch;
publish one `availability.events` message; launch `uv run python -m services.notifier` as a subprocess
with `ENV=test`, `MISE_CRASH_AFTER=provider_ack`, and `RESEND_API_BASE`/`TWILIO_API_BASE` pointed at
the stub. Wait for the process to die and assert its returncode is `-9` OR `137` — that assertion is
load-bearing, because a run where the hook never fired would otherwise pass vacuously, and `uv run` is
the direct child which relays a killed grandchild as 128 + signal (the Phase-2 02-03 deviation). Read
`GET /__ctl/hits` and assert exactly one call. Relaunch without the hook, wait for the job to be
processed, and assert: the hit log STILL shows exactly one call, the database has exactly one
non-suppressed row for the `(watch, channel)` pair, a `duplicate_suppressed` row exists recording the
second attempt, and the consumer group's committed offset has advanced.

Adjust `services/notifier/workers.py` only as the test exposes gaps — most likely the exact placement
of `maybe_crash("provider_ack")` relative to the `notification_log` update, and the
`duplicate_suppressed` row's write on the redelivery path.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_notifier_chaos.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_notifier_chaos.py -q -p no:cacheprovider` exits 0, or skips with the existing Docker-guard message on a Docker-less host.
    - `uv run pytest tests/integration/test_state_machine_chaos.py -q -p no:cacheprovider` exits 0 or skips — the Phase-2 chaos proof is unaffected by the crash-hook move.
    - `uv run python -c "import inspect, tests.fakes.provider_stub as s; src=inspect.getsource(s); print('__ctl/hits' in src, '__ctl/mode' in src)"` prints `True True`.
    - `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` exits 0 (or skips the integration tier without failures).
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A real `kill -9` between a real provider acknowledgement and the offset commit produces exactly one provider-side send after restart, proven by a listener's hit log rather than by a mock's memory.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The honest crash-table README, the ordering assertion, and the extended source gates</name>
  <files>services/notifier/README.md, tests/unit/test_idempotency_ordering.py, tests/unit/test_no_inline_sleep.py, tests/unit/test_no_setnx_expire_pairs.py, tests/unit/test_kafka_consumer_config.py, tests/unit/test_logs_never_carry_payload.py</files>
  <read_first>
    - services/state_machine/consumer.py lines 1-20 (the module docstring that carries the Phase-2 crash contract) and services/state_machine/README.md if present (the crash table the Phase-2 review corrected for an over-claim)
    - tests/unit/test_no_inline_sleep.py in full (`SCANNED_FILES`, the comment-stripping helper, the non-vacuity assertion and the named-file set)
    - tests/unit/test_no_setnx_expire_pairs.py in full (it already walks `services/`, `shared/` and `scripts/` recursively, so the new trees are inside it the moment they land — the gap is that nothing PROVES they are)
    - tests/unit/test_logs_never_carry_payload.py in full (the existing payload-in-log assertions to extend to the notifier and API modules)
    - tests/unit/test_kafka_consumer_config.py in full (the factory-config assertions to extend for both notifier groups)
    - tests/unit/test_emission_idempotency.py and tests/unit/test_emit_flush_ordering.py (the fake-collaborator ordering-assertion style)
    - services/notifier/workers.py as written in Tasks 1-2
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Ordering and crash windows" (the six-row table verbatim and BOTH caveats) and §"The no-sleep gate wording" (the exact docstring sentence to adopt so nobody adds an allowlist)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §specifics ("Keep the notifier's README crash table honest — the Phase 2 review caught an over-claim there")
  </read_first>
  <behavior>
    - A fake provider that appends to a shared call log proves the Redis claim is recorded before the provider call, for every one of the three channels.
    - When the claim fails, the provider's call log stays empty and a `duplicate_suppressed` row is recorded.
    - On a definitive provider failure the claim is deleted; on success the claim is still present afterwards.
    - The offset is committed only after both the row update and the `notifications.sent` acknowledgement are recorded in the fake collaborators' logs.
    - `tests/unit/test_no_inline_sleep.py` scans the notifier, its providers package and the API tree in addition to the state machine, its scanned set is asserted non-empty with the new module names present, and both sleep forms are still banned.
    - `tests/unit/test_kafka_consumer_config.py` asserts `enable_auto_commit=False` and `max_poll_records=1` for both the `notifier` and `notifier-workers` group ids.
    - The README's crash table has one row per crash point and states both caveats explicitly.
  </behavior>
  <action>
Write `services/notifier/README.md`. Lead with the pipeline in one paragraph, then reproduce the
six-row crash-point table — crash point, claim state, provider state, `notification_log` state,
`notifications.sent` state, offset state, and what happens on restart — verbatim from the research
section. Then state BOTH caveats in plain words, because the Phase-2 review caught an over-claim in
exactly such a table and the specifics note asks for this one to stay honest: an alert crashed between
the claim and the provider call is LOST for 24 hours, and that is a deliberate trade — a missed alert
beats a double send; and a duplicate `notifications.sent` is possible after the last crash window, so
the pipeline is NOT exactly-once and downstream consumers should dedupe on the deterministic `job_id`.
Add the operational sections a reader needs: the two consumer groups and what renaming one costs, the
five crash-hook stages and the fail-closed `ENV` allowlist, the per-channel retry and fallback policy,
and the env-var table.

Write `tests/unit/test_idempotency_ordering.py` with fake collaborators — a fake Redis recording claim
calls, a fake provider recording sends, a fake persistence recording row writes, a fake producer
recording publishes, and a fake consumer recording commits — all appending to ONE shared ordered log,
so the assertion is about the sequence rather than about each call in isolation. Assert the ordering
for all three channels, the claim-failure path, the delete-on-definitive-failure and
no-delete-on-success behaviour, and that the commit is last.

Extend `tests/unit/test_no_inline_sleep.py`: add `services/notifier/*.py`,
`services/notifier/providers/*.py` and `services/api/**/*.py` to `SCANNED_FILES`, raise the
non-vacuity floor, and extend the named-file assertion with the new module names so a glob that
matched nothing cannot make the gate vacuous. Add the research-supplied docstring sentence recording
that backoff in the notifier is delegated to `tenacity`, whose own sleep lives inside its own package
and is therefore out of scope for this file-scoped gate, and that any sleep appearing in OUR modules
is a hand-rolled wait — so a future reader does not "fix" the gate by adding an allowlist. Extend
`tests/unit/test_kafka_consumer_config.py` with the two notifier group ids.

Extend `tests/unit/test_no_setnx_expire_pairs.py` with a single assertion that the collected file
list actually CONTAINS the new trees — `services/notifier`, `services/notifier/providers` and
`services/api` — naming specific files. The gate's directory walk already covers them, so no scanning
change is needed; what is missing is proof, because a recursive glob that silently stops matching is
exactly the vacuous-green failure the existing non-vacuity companion exists to prevent. Extend
`tests/unit/test_logs_never_carry_payload.py` to the notifier and API modules with the same
source-scan shape it already uses, so a log call carrying a rendered body, a recipient or a token
fails at the unit tier rather than in production.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_idempotency_ordering.py tests/unit/test_no_inline_sleep.py tests/unit/test_no_setnx_expire_pairs.py tests/unit/test_kafka_consumer_config.py tests/unit/test_logs_never_carry_payload.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_idempotency_ordering.py tests/unit/test_no_inline_sleep.py tests/unit/test_no_setnx_expire_pairs.py tests/unit/test_kafka_consumer_config.py tests/unit/test_logs_never_carry_payload.py -q` exits 0.
    - `uv run python -c "from tests.unit.test_no_inline_sleep import SCANNED_FILES as f; ns={p.name for p in f}; print(len(f) >= 16, {'workers.py','main.py','push.py','links.py'} &lt;= ns)"` prints `True True`.
    - `grep -c "^|" services/notifier/README.md` returns at least `8` — the crash table plus the env table are present as tables, not as prose.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>The claim-before-provider ordering is asserted as a sequence rather than assumed, the README states both crash-window trade-offs honestly, and the no-sleep and consumer-config gates cover the two new service trees without an allowlist.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (04-06 slice)

**New modules:** `services/notifier/workers.py`, `services/notifier/main.py`,
`services/notifier/__main__.py`, `services/notifier/README.md`, `tests/fakes/provider_stub.py`.

**New symbols — `workers.py`:** `QUEUED_TOPIC`, `SENT_TOPIC` (`notifications.sent`), `DLQ_TOPIC`,
`NotifierDeliveryWorker`, `handle_job()`, `SMS_FALLBACK_TEMPLATE_NAME` (`sms_failed_fallback`).

**New symbols — `main.py`:** `REQUIRED_TOPICS` (seven topics, including `notifications.dlq`),
`_assert_topics_exist()`, `run()`.

**New symbols — `tests/fakes/provider_stub.py`:** `ProviderStub`, control routes `POST /__ctl/mode`
and `GET /__ctl/hits`, stub endpoints `POST /emails` and
`POST /2010-04-01/Accounts/{sid}/Messages.json`.

**Crash-hook stages exercised:** `nx_claim`, `provider_ack` (the SC2 stage), `log_insert`,
`sent_publish`, `commit`.

**Kafka topics published to:** `notifications.sent` (key `{watch_id}`), `notifications.dlq`.

**Notification log statuses written here:** `sent`, `failed`, `duplicate_suppressed`; columns
written: `provider_id`, `sent_at`, `latency_ms`, `error`.

**Error codes recorded:** `provider_unconfigured`, `subscription_revoked`, `phone_decrypt_failed`,
`sms_opt_out`.

**Env vars consumed:** `METRICS_PORT` (optional Prometheus exporter), plus every variable declared by
04-03 and 04-05. Added to `.env.example` by 04-07.

**Make target referenced (added in 04-07):** `make notifier` -> `uv run python -m services.notifier`.

**Extended gates:** `tests/unit/test_no_inline_sleep.py` (now covers `services/notifier`,
`services/notifier/providers` and `services/api`), `tests/unit/test_no_setnx_expire_pairs.py` (now
proves the new trees are inside its recursive walk), `tests/unit/test_kafka_consumer_config.py` (now
covers both notifier consumer groups), `tests/unit/test_logs_never_carry_payload.py` (now covers the
notifier and API modules).
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Kafka `notifications.queued` -> worker | Producer-supplied job bytes; the embedded event is re-read here |
| worker -> Redis claim | The single gate standing between a redelivery and a duplicate send |
| worker -> provider | The only irreversible action in the pipeline: an SMS cannot be un-sent |
| worker -> Postgres / `notifications.sent` | The durable audit trail two success criteria read |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-04-36 | Tampering | duplicate provider send after a crash or rebalance | critical | mitigate | Layer-2 `SET NX EX` strictly before the provider call, never deleted on success; Layer-3 partial unique index; provider-side `Idempotency-Key`; proven by a SIGKILL subprocess test with a listener-side hit-log oracle |
| T-04-37 | Repudiation | a send with no durable record | high | mitigate | The `sent`/`failed` row write is NOT best-effort (unlike the Phase-2 state machine's); a failure takes the transient arm and refuses to commit |
| T-04-38 | Denial of Service | one stuck job stalling a `max_poll_records=1` pipeline | high | mitigate | Bounded attempts per channel, a clamped `Retry-After`, per-call timeouts, and a dead-letter arm that commits past rather than retrying forever |
| T-04-39 | Repudiation | an SMS sent to a user who already opted out | critical | mitigate | `sms_opt_out` re-checked at the worker as well as at fan-out, because a queued job can outlive the opt-out; the fallback path honours it too |
| T-04-40 | Information Disclosure | a rendered body, recipient or provider id paired with a recipient in a log | high | mitigate | Log by shape only; the extended `_redact_secrets` covers every value-shaped field; the README states the rule |
| T-04-41 | Denial of Service | the test-only SIGKILL hook armed in a deployed environment | critical | mitigate | Startup interlock refuses unless `ENV` is EXPLICITLY allowlisted, using the single shared definition from `shared/crash_hook.py` |
| T-04-42 | Tampering | a duplicated `notifications.sent` misread downstream as a second send | low | accept | Possible by construction in the last crash window; `job_id` is deterministic so consumers can dedupe, and the README says so rather than claiming exactly-once |
| T-04-SC | Tampering | package-manager installs | high | mitigate | Zero packages added; the stub is a test fixture built from already-pinned libraries |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 or skips cleanly without Docker.
- `uv run pytest tests/integration/test_notifier_chaos.py -q -p no:cacheprovider` exits 0 — ROADMAP SC2.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run python -m services.notifier` starts and shuts down cleanly on SIGTERM against a running local stack.
</verification>

<success_criteria>
- The claim strictly precedes every provider call, on every path, asserted as a sequence.
- A real SIGKILL between a real 2xx and the offset commit yields exactly one provider-side send after restart.
- Every send produces a durable row and a `notifications.sent` message carrying a non-negative measured latency.
- Both loops run under one lifespan, one producer, one signal handler, and the crash hook cannot arm outside the allowlist.
- The README's crash table states both trade-offs and never claims exactly-once.
</success_criteria>

<output>
Create `.planning/phases/04-notification-pipeline/04-06-SUMMARY.md` when done
</output>
