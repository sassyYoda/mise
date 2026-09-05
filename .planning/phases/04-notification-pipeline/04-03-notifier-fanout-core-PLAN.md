---
phase: 04-notification-pipeline
plan: 03
type: execute
wave: 2
depends_on: [04-01, 04-02]
files_modified:
  - services/notifier/__init__.py
  - services/notifier/config.py
  - services/notifier/matching.py
  - services/notifier/persistence.py
  - services/notifier/consumer.py
  - tests/unit/test_matching_matrix.py
  - tests/unit/test_notifier_config_lazy.py
  - tests/unit/test_notifier_offset_policy.py
  - tests/integration/test_notifier_fanout.py
  - tests/integration/test_notifier_rate_limit.py
autonomous: true
requirements: [NOTIF-01, NOTIF-02, NOTIF-06]

estimate:
  tokens: 68000
  raw_tokens: 68000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "One `AvailabilityEvent` on `availability.events` produces exactly one `NotificationQueued` message on `notifications.queued` per channel in the matching watch's `channels` list, keyed by `{watch_id}`, with the whole event embedded so the delivery worker needs no second lookup (D-73, D-75, NOTIF-01)."
    - "The pre-filter SELECT joins `restaurants` on `(source, platform_id)` with the platform id bound as a STRING — `AvailabilityEvent.restaurant_id` is an `int` holding the source platform id while `restaurants.platform_id` is `TEXT`, and an int bind errors in asyncpg only at the integration tier (D-52, research §Pitfall 6). The integration test asserts a seeded restaurant is actually FOUND, because a zero-match fan-out otherwise looks exactly like 'no watches'."
    - "`match_watches(event, rows)` is a PURE function — no Redis, no Postgres, no clock read, no entropy — and a source-scan test in `tests/unit/test_matching_matrix.py` proves `services/notifier/matching.py` performs no I/O import (D-73, the `engine.py` purity precedent)."
    - "PROBE NOTIF-01/adjacency: inclusivity is exact at every boundary — a watch whose `date_from == date_to == event.date` matches; one whose `date_to` is the day before does not; `time_window_from == time_slot` and `time_window_to == time_slot` both match; a slot one minute outside either edge does not; `party_size` is exact equality, so a party-4 watch never matches a party-2 event (multi-size watches are deferred V2-09)."
    - "PROBE NOTIF-01/empty: an event with zero matching watches emits zero messages, logs a zero-match event and STILL commits its offset; a watch with an empty `channels` string emits zero jobs rather than a default email; `time_window_from/to`, `days_of_week` and `seat_type_filter` all treat NULL as NO CONSTRAINT, while a SET `seat_type_filter` against an event whose `seat_type` is `None` does NOT match; an unparseable `time_slot` fails CLOSED and matches no windowed watch."
    - "PROBE NOTIF-01/ordering: `match_watches` output is deterministic and stable — two calls over the same rows in the same order produce an identical list, and the per-channel jobs for one watch are emitted in the fixed `email, sms, push` order of `NOTIFICATION_CHANNELS`, so the `job_id` sequence for one event is reproducible across processes."
    - "`days_of_week` is a comma list of `mon..sun` evaluated against the SERVICE date's weekday under the project's `day_of_week(d) = d.isoweekday() % 7` convention (0=Sun..6=Sat), unit-tested for all seven days — an off-by-one here silently drops every Sunday alert (D-73, migration 0008's column comment)."
    - "A user at or above `NOTIFY_DAILY_CAP_PER_USER` for the current New York calendar day gets NO `NotificationQueued` message, a `notification_rate_limited` log line and a `notification_log` row with `status='suppressed'` — the cap is evaluated BEFORE anything is published, because a cap evaluated later is a bill rather than a cap (D-74)."
    - "A watch whose user has `sms_opt_out = true` never produces an `sms` job, and its other channels are unaffected — the opt-out is applied at fan-out and again at the worker (NOTIF-04, D-84)."
    - "`AIOKafkaConsumer` is constructed inside `run()` through `shared.kafka.make_consumer` with `enable_auto_commit=False`, `max_poll_records=1` and `group_id='notifier'`; a transient handler failure SEEKS BACK to the failed offset and PAUSES the partition with a `loop.call_later` resume rather than skipping it, and a poison message is dead-lettered to `notifications.dlq` and only then committed past (D-77, NOTIF-06, Phase-2 CR-01 pattern)."
    - "Every environment read in `services/notifier/config.py` is a FUNCTION, never a module constant — a source-scan test proves no module-level `os.getenv` exists — so importing the notifier during test collection cannot pin a later test to the localhost defaults (the 02-02 poller freeze defect)."
  artifacts:
    - services/notifier/config.py
    - services/notifier/matching.py
    - services/notifier/persistence.py
    - services/notifier/consumer.py
    - tests/unit/test_matching_matrix.py
    - tests/unit/test_notifier_offset_policy.py
    - tests/integration/test_notifier_fanout.py
    - tests/integration/test_notifier_rate_limit.py
  key_links:
    - "`availability.events` -> `NotifierFanoutConsumer.handle_message` -> `select_matching_watches` -> `match_watches` -> `notifications.queued`. This is the whole NOTIF-01 path; a break anywhere in it is indistinguishable from 'nobody was watching'."
    - "`str(event.restaurant_id)` at the bind site -> `restaurants.platform_id` (TEXT). The single most likely silent-zero-match defect in the phase (D-52, Pitfall 6)."
    - "`NOTIF_DAILY_CAP_LUA` (04-02) -> the fan-out's pre-publish gate. The cap must sit upstream of the queue, or a capped user's jobs still cost a provider call."
    - "`services/notifier/persistence.py` -> the delivery worker (04-06). The `queued` row it inserts is what the `go` token names, so it must exist BEFORE the message is rendered, not after the provider replies."
  prohibitions:
    - "MUST NOT publish a `NotificationQueued` message for a watch whose `status` is anything other than `active`, or for a user who is at or above the daily cap."
    - "MUST NOT publish an `sms` job for a user whose `sms_opt_out` is true — not once, not as a fallback, not in dry-run mode."
    - "MUST NOT let the consumer auto-commit, and MUST NOT commit an offset that is at or past a message whose handler failed transiently — the position has already advanced, so a later commit silently moves the watermark past a lost notification."
    - "MUST NOT read the clock, Redis, Postgres or `random` inside `services/notifier/matching.py`; every residual predicate is a pure comparison over values already in hand."
    - "MUST NOT log a rendered message, an email address, a phone number or a booking token from the fan-out path; failures are logged by SHAPE through the Phase-2 `_failure_shape` / `safe_error` split."
    - "MUST NOT read an environment variable at module import time in `services/notifier/`."
---

<objective>
Build the fan-out half of the notifier: the lazy config module, the pure watch matcher, the
persistence layer both consumer loops share, and the manual-commit consumer that turns one
`availability.events` message into one `notifications.queued` job per channel per matching watch.

Purpose: NOTIF-01 is the requirement whose failure mode is invisible — a fan-out that matches nothing
looks exactly like a quiet night. So the matching logic is a pure function with a parametrised
boundary matrix, and the SQL half is proven against a real database with a real seeded restaurant, so
"found zero watches" can never be mistaken for "worked".
Output: `services/notifier/{config,matching,persistence,consumer}.py`, the boundary matrix, the
offset-policy assertions, and two integration tests that drive a real broker and a real database.
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
@.planning/phases/04-notification-pipeline/04-01-SUMMARY.md
@.planning/phases/04-notification-pipeline/04-02-SUMMARY.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — one availability event through the real SELECT and the pure matcher to one queued job per channel</name>
  <files>services/notifier/__init__.py, services/notifier/config.py, services/notifier/matching.py, services/notifier/persistence.py, services/notifier/consumer.py, tests/integration/test_notifier_fanout.py</files>
  <read_first>
    - services/state_machine/config.py in full (the lazy-accessor docstring, `__all__`, `CONSUMER_GROUP_ID`'s "renaming it replays the whole topic" warning)
    - services/state_machine/consumer.py lines 1-60 (module docstring, topic constants, `DLQ_TOPIC` reasoning) and lines 200-260 (the seek/pause/`call_later` transient rewind) and lines 330-400 (`_apply_emit`'s claim-send-record ordering and `send_and_wait`)
    - services/state_machine/persistence.py lines 25-110 (`_SERVICE_TZ` import, `day_of_week`, `_parse_time_slot`, the `pg_insert(...).on_conflict_do_nothing` idiom, and the best-effort `except` this file must NOT copy)
    - shared/db.py lines 36-105 (the exact `User`, `Restaurant`, `WatchlistEntry`, `NotificationLog` columns, plus the 04-02 additions)
    - shared/kafka.py in full (`make_consumer` varargs, `make_producer` `linger_ms`)
    - shared/events.py (`AvailabilityEvent` field meanings, the 04-02 `NotificationQueued` / `make_job_id`)
    - tests/integration/test_state_machine_e2e.py and tests/integration/conftest.py (the container plumbing, `reset_shared_db_singletons` ordering rule, and the 04-02 `seed_user_and_watch` helper)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Fan-out SQL and Matching" (the compiled SELECT, the residual-predicate list, the ORM seeding note about absent `created_at` defaults) and §"Pitfall 6"
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Architecture Patterns" Pattern 2 and Pattern 4
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-73, §D-75, §D-77
  </read_first>
  <behavior>
    - A seeded `opentable` restaurant with `platform_id = '42'`, a user, and an active watch for party 2 on the event's date with `channels = "email,sms,push"` produces exactly three `notifications.queued` messages for one event.
    - Each message parses as `NotificationQueued`, carries the embedded `AvailabilityEvent` unchanged, and has a `job_id` equal to `make_job_id(watch_id, event_id, channel)`.
    - The Kafka message key is the watch id as a string.
    - A second, non-matching watch (wrong party size) seeded alongside produces no additional message.
    - After the message is handled, the consumer's committed offset has advanced by exactly one.
    - The SELECT returns the seeded watch — asserted directly, not inferred from the message count.
  </behavior>
  <action>
Create `services/notifier/__init__.py` (empty package marker) and `services/notifier/config.py` in the
exact register of `services/state_machine/config.py`: a module docstring that names every symbol and
states, in prose, that every environment read below is a FUNCTION and why — the
`services/poller/config.py` import-time freeze pinned a whole test run to localhost defaults, and this
module structurally cannot repeat it. Define `CONSUMER_GROUP_ID = "notifier"` and
`WORKER_GROUP_ID = "notifier-workers"` as module constants with the "renaming this replays the topic"
warning; lazy accessors `kafka_bootstrap_servers()`, `redis_url()`, `database_url_async()`,
`env_name()`, `daily_cap_per_user()` (reads `NOTIFY_DAILY_CAP_PER_USER`, defaults to
`NOTIFY_DAILY_CAP_DEFAULT` from `shared.redis_keys`, refuses a non-integer or a value below 1 with a
`RuntimeError` naming the variable, mirroring `max_message_attempts`), and `dry_run()` reading
`NOTIFY_DRY_RUN`. Re-export `CRASH_HOOK_ENVS`, `crash_hook_allowed`, `crash_after` and `maybe_crash`
from `shared.crash_hook` through `__all__` with the `# noqa: F401` comment the state machine already
uses — import them, never redeclare them (D-88).

Write `services/notifier/matching.py` as a PURE module (D-73). It imports only from `datetime`,
`dataclasses`, `typing` and `shared.events` — no Redis, no SQLAlchemy, no `random`, no clock. Define a
frozen `Match` dataclass carrying `watch_id`, `user_id`, `channels: tuple[str, ...]`, `email`,
`phone_ciphertext`, `sms_opt_out`, `restaurant_name`, `restaurant_slug`, `restaurant_platform_id` and
`restaurant_source`, and a frozen `WatchRow` describing the SELECT's row shape so the pure half has a
typed input independent of SQLAlchemy. `match_watches(event, rows) -> list[Match]` applies the
residual predicates the SQL cannot: the time window (inclusive at BOTH edges when both bounds are
set), `days_of_week` (a comma list of `mon..sun` mapped onto `isoweekday() % 7`, 0=Sun..6=Sat, taken
from the SERVICE date and not the detection date), and `seat_type_filter` (exact equality when set; a
watch with a filter must NOT match an event whose `seat_type` is `None`). Parse `time_slot` with the
tolerant `dt_time.fromisoformat` convention `services/state_machine/persistence.py` established, and
FAIL CLOSED — an unparseable slot matches no windowed watch. Split `channels` on commas, strip, drop
empties, and preserve `NOTIFICATION_CHANNELS` order rather than the string's order so the emitted job
sequence is stable. Drop `sms` when `sms_opt_out` is true. Return the list sorted by `watch_id`, and
say in the docstring that the ordering is part of the contract because `job_id` reproducibility across
processes depends on it.

Write `services/notifier/persistence.py` owning every Postgres statement BOTH loops issue.
`select_matching_watches(source, platform_id, date, party_size) -> list[WatchRow]` builds the
research-verified Core `select()` naming scalar columns only (no `relationship()` exists on these
models, and naming scalars is what keeps the async session free of a lazy-load-on-detached-instance
hazard), joining `restaurants` on `source` and `platform_id` and `users` on `user_id`, filtering
`status = 'active'`, exact `party_size`, and `date_from <= date <= date_to`. Bind the platform id as
`str(...)` with a comment naming D-52 and Pitfall 6.
`upsert_queued_row(watch_id, event_id, channel) -> int` issues
`pg_insert(NotificationLog).values(...).on_conflict_do_update(...)` against the
`(watch_id, event_id, channel)` partial index, setting `status='queued'` and clearing `error`, and
RETURNING the id. Its docstring must record the ordering decision this phase makes explicitly: D-76
lists the `notification_log` insert AFTER the provider call, but the `go` token names
`notification_log.id` (D-86a, BC-2), so the row has to exist before the message can be rendered — the
row is therefore created as `queued` immediately after the Layer-2 claim and UPDATEd to `sent` or
`failed` afterwards. The claim still strictly precedes the provider call, which is the property
NOTIF-02 and SC2 actually require, and `queued` is already in the D-85 status vocabulary.
Add `record_suppressed(watch_id, event_id, channel, reason)` writing a `status='suppressed'` row, and
the helpers the delivery worker needs so it consumes this module rather than growing its own SQL —
`mark_sent(row_id, provider_id, sent_at, latency_ms)`, `mark_failed(row_id, error)`,
`mark_duplicate_suppressed(watch_id, event_id, channel)`, `revoke_push_subscription(endpoint)` setting
`revoked_at`, and `load_job_context(watch_id)` returning the user's email, encrypted phone,
`sms_opt_out`, active push subscriptions and the restaurant's name, slug, source and platform id —
each a small statement with the same bound-parameter discipline. State at the top of the module, loudly, that
unlike `services/state_machine/persistence.py` these writes are NOT best-effort: the `sent` row is the
audit trail that both the SC2 duplicate proof and the PERF-01 measurement read, so a failure
PROPAGATES to the caller's transient arm instead of being swallowed (research §Pitfall 3).

Write `services/notifier/consumer.py` — loop A. `EVENTS_TOPIC = "availability.events"`,
`QUEUED_TOPIC = "notifications.queued"`, `DLQ_TOPIC = "notifications.dlq"`. Class
`NotifierFanoutConsumer(consumer, producer, redis_client, cap_script)` with `run()` and
`handle_message(msg)`. Per message: parse `AvailabilityEvent` (a `ValidationError` is POISON — publish
the original bytes plus diagnostic headers to `notifications.dlq`, then commit past it); resolve the
restaurant and select candidate rows; call `match_watches`; for each match, evaluate the daily cap;
for each surviving channel build a `NotificationQueued` and `send_and_wait` it to
`notifications.queued` keyed by the watch id — `send_and_wait`, never a bare `send`, because
`shared/kafka.py` sets `linger_ms=20` and a bare send can return before the broker acks; then commit
the offset ONCE for the whole message. On a transient failure use the Phase-2 rewind verbatim: seek
back to `msg.offset`, pause the partition, and re-arm with `loop.call_later` — never an inline sleep.
Log by shape only, reusing the `_failure_shape` / `safe_error` split.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_notifier_fanout.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_notifier_fanout.py -q -p no:cacheprovider` exits 0, or skips with the existing Docker-guard message on a Docker-less host.
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run python -c "import sys; import services.notifier.matching; print(len([m for m in ('redis','sqlalchemy','asyncpg','aiokafka') if m in sys.modules]))"` prints `0` in a fresh interpreter — the pure matcher pulls in no I/O stack.
    - `grep -c "str(" services/notifier/persistence.py` returns at least `1`, and `grep -n "D-52" services/notifier/persistence.py` prints at least one line.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>One real `availability.events` message, against a live broker and a live database with a seeded restaurant/user/watch, produces exactly three keyed `notifications.queued` jobs and advances the committed offset by one.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The matching boundary matrix and the lazy-config source scan</name>
  <files>services/notifier/matching.py, tests/unit/test_matching_matrix.py, tests/unit/test_notifier_config_lazy.py</files>
  <read_first>
    - services/notifier/matching.py as written in Task 1
    - tests/unit/test_engine_transitions.py (the parametrised matrix style this file mirrors)
    - tests/unit/test_engine_purity.py (the source-scan purity assertion to copy)
    - tests/unit/test_service_time_math.py (the existing `day_of_week` convention assertions)
    - .planning/phases/03-resy-playwright-fleet/03-03-resy-config-schema-seed-PLAN.md (its lazy-config source-scan test is the model for `test_notifier_config_lazy.py`)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Fan-out SQL and Matching" residual-predicate bullets
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-73
  </read_first>
  <behavior>
    - Date range: `date_from == date_to == event.date` matches; `date_to == event.date - 1 day` does not; `date_from == event.date + 1 day` does not.
    - Time window: `time_window_from == time_slot` matches; `time_window_to == time_slot` matches; one minute before `from` or after `to` does not; both bounds NULL matches every slot.
    - Days of week: for each of the seven weekday spellings, an event whose service date falls on that day matches a watch naming it and does not match one naming only the adjacent day; a NULL `days_of_week` matches every day; whitespace and mixed case in the list are tolerated.
    - Seat type: NULL filter matches any `seat_type` including `None`; a filter of `"bar"` matches `seat_type="bar"`, does not match `"standard"`, and does not match `None`.
    - Channels: `"email,sms,push"` yields the three channels in `NOTIFICATION_CHANNELS` order regardless of the string's order; `""` and `" , "` yield none; an unknown channel name is dropped rather than passed through.
    - Opt-out: `sms_opt_out=True` removes `sms` and leaves `email` and `push`.
    - Unparseable `time_slot` matches a watch with NULL bounds but not one with a window.
    - Two calls over the same row list return equal results, and the result is sorted by `watch_id`.
    - `services/notifier/config.py` contains no module-level environment read, and `daily_cap_per_user()` refuses `0` and a non-numeric value with a `RuntimeError` naming the variable.
  </behavior>
  <action>
Write `tests/unit/test_matching_matrix.py` as a parametrised matrix covering every bullet in
`<behavior>`, one `pytest.mark.parametrize` block per predicate so a failure names the predicate
rather than a row number. Build inputs through the 04-02 factories (`make_availability_event`,
`make_watch_row`) so each case names only the field it exercises. Include the seven-day weekday table
as an explicit mapping in the test — writing the expected `mon..sun` -> `0..6` correspondence out by
hand is the point, because an off-by-one against `isoweekday() % 7` silently drops every Sunday alert
and cannot be caught by a test that recomputes it the same way the source does.

Add the purity assertion in the style of `tests/unit/test_engine_purity.py`: read
`services/notifier/matching.py`, strip full-line comments, and assert the import block names none of
the I/O or entropy modules, and that the module body contains no call to a now/today constructor.

Fix whatever the matrix exposes in `services/notifier/matching.py` — inclusivity, the weekday map,
the fail-closed slot parse and the channel ordering are the four places a first draft is most likely
to be one step off.

Write `tests/unit/test_notifier_config_lazy.py`: a source scan proving every environment read in
`services/notifier/config.py` sits inside a function body, a monkeypatched round trip showing a value
set AFTER import is picked up by the accessor, and the two `daily_cap_per_user()` refusal cases.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_matching_matrix.py tests/unit/test_notifier_config_lazy.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_matching_matrix.py tests/unit/test_notifier_config_lazy.py -q` exits 0.
    - `uv run pytest tests/unit/test_matching_matrix.py --collect-only -q` reports at least 30 collected cases — a matrix that collapsed to a handful of cases is not a matrix.
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Every inclusivity boundary, every NULL-means-no-constraint case, the seven-day weekday map and the channel ordering are pinned by an executable matrix, and the config module is provably lazy.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The per-user daily cap on the hot path, and the offset-commit policy</name>
  <files>services/notifier/consumer.py, tests/integration/test_notifier_rate_limit.py, tests/unit/test_notifier_offset_policy.py</files>
  <read_first>
    - services/notifier/consumer.py as written in Task 1
    - tests/unit/test_offset_commit_policy.py in full (the existing Phase-2 assertions this file models)
    - tests/unit/test_partition_resume.py and tests/unit/test_retry_cap_and_dlq.py (the pause/resume and dead-letter assertion styles)
    - tests/unit/test_kafka_consumer_config.py (the `enable_auto_commit=False` factory assertion to mirror for the notifier's two group ids)
    - shared/redis_keys.py `NOTIF_DAILY_CAP_LUA`, `rate_notif_key`, `service_day` as written in 04-02
    - shared/scheduler/lua.py (the `register_script` / NOSCRIPT-fallback loading pattern)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Per-user daily cap" (the cap-3 behaviour table) and §"Architecture Patterns" Pattern 2 (why not committing is INSUFFICIENT — the position has already advanced)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-74, §D-74a, §D-77
  </read_first>
  <behavior>
    - With `NOTIFY_DAILY_CAP_PER_USER=2` and a user who already has two alerts today, a matching event emits zero `notifications.queued` messages, writes one `notification_log` row per channel with `status='suppressed'`, and still commits.
    - The same user under the cap emits the full per-channel set and the counter increments once per notification, not once per channel — the cap counts NOTIFICATIONS per user per day.
    - The rate key's TTL is set once and then counts down across the run.
    - Two users share no counter; one user's cap does not suppress the other.
    - A handler raising a transient error leaves the offset uncommitted, seeks the partition back to that offset, and pauses it; the resume is scheduled with `call_later` and the same message is redelivered.
    - A message that fails to parse is published to `notifications.dlq` with the original bytes and then committed past, so a poison message never stalls the partition.
    - The notifier's consumer factory call carries `enable_auto_commit=False` and `max_poll_records=1` for both `notifier` and `notifier-workers`.
  </behavior>
  <action>
Wire the daily cap into `services/notifier/consumer.py` between matching and publishing (D-74). Load
`NOTIF_DAILY_CAP_LUA` once through `register_script` at consumer construction, following
`shared/scheduler/lua.py`'s NOSCRIPT-fallback pattern. For each `Match`, call the script with
`rate_notif_key(match.user_id, service_day())`, `NOTIF_RATE_TTL_SECONDS` and
`daily_cap_per_user()`; the counter is incremented ONCE per matched notification, not once per
channel, and the docstring must state that choice because "50 alerts a day" is a promise about alerts
and not about SMS segments. On refusal, log `notification_rate_limited` with the user id and the
count and nothing else, write one `status='suppressed'` row per channel through
`record_suppressed`, and publish nothing.

Write `tests/integration/test_notifier_rate_limit.py` against live Redis and TimescaleDB containers,
driving the cap behaviour end to end: seed a user and an active watch, set the cap to 2, feed three
matching events through `handle_message`, and assert two produce jobs while the third produces zero
jobs, three `suppressed` rows and a decreasing TTL on the rate key. Add the two-user isolation case.

Write `tests/unit/test_notifier_offset_policy.py` modelled on
`tests/unit/test_offset_commit_policy.py`: a fake consumer recording `commit`, `seek`, `pause` and
`resume` calls, exercised through `handle_message` for the success, transient-failure and poison
paths. Assert the transient path issues the seek and the pause BEFORE any commit and never commits at
all — the Phase-2 note is the reason to test this rather than assume it: merely not committing is
insufficient, because the consumer position has already advanced and the NEXT message's commit would
move the watermark past the failed offset and lose the notification silently. Assert the poison path
publishes to `notifications.dlq` and then commits, and add the factory-config assertion for both
notifier group ids.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_notifier_offset_policy.py tests/integration/test_notifier_rate_limit.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_notifier_offset_policy.py -q` exits 0.
    - `uv run pytest tests/integration/test_notifier_rate_limit.py -q -p no:cacheprovider` exits 0, or skips on a Docker-less host.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run python -c "import inspect, services.notifier.consumer as c; src=inspect.getsource(c); print('call_later' in src, 'send_and_wait' in src, 'NOTIF_DAILY_CAP_LUA' in src)"` prints `True True True`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A capped user is suppressed before anything is queued, with a durable `suppressed` row and no provider cost, and the offset policy — seek back on transient, dead-letter then commit on poison, never auto-commit — has an executable assertion for each of its three arms.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (04-03 slice)

**New modules:** `services/notifier/__init__.py`, `services/notifier/config.py`,
`services/notifier/matching.py`, `services/notifier/persistence.py`, `services/notifier/consumer.py`.

**New symbols — `services/notifier/config.py`:** `CONSUMER_GROUP_ID` (`"notifier"`),
`WORKER_GROUP_ID` (`"notifier-workers"`), `kafka_bootstrap_servers()`, `redis_url()`,
`database_url_async()`, `env_name()`, `daily_cap_per_user()`, `dry_run()`; re-exports of
`CRASH_HOOK_ENVS`, `crash_hook_allowed()`, `crash_after()`, `maybe_crash()` from `shared.crash_hook`.

**New symbols — `services/notifier/matching.py`:** `WatchRow`, `Match`, `match_watches()`,
`weekday_token()` (the `mon..sun` -> `0..6` map).

**New symbols — `services/notifier/persistence.py`:** `select_matching_watches()`,
`upsert_queued_row()`, `record_suppressed()`, `mark_sent()`, `mark_failed()`,
`mark_duplicate_suppressed()`, `revoke_push_subscription()`, `load_job_context()`.

**New symbols — `services/notifier/consumer.py`:** `EVENTS_TOPIC` (`availability.events`),
`QUEUED_TOPIC` (`notifications.queued`), `DLQ_TOPIC` (`notifications.dlq`),
`NotifierFanoutConsumer`, `TRANSIENT_RETRY_BACKOFF_SECONDS`.

**Kafka consumer groups:** `notifier` (loop A, `availability.events`), `notifier-workers` (loop B,
declared here, consumed in 04-06).

**Env vars consumed:** `KAFKA_BOOTSTRAP_SERVERS`, `REDIS_URL`, `DATABASE_URL_ASYNC`, `ENV`,
`NOTIFY_DAILY_CAP_PER_USER`, `NOTIFY_DRY_RUN`, `MISE_CRASH_AFTER` (test-only).

**Notification log statuses written here:** `queued`, `suppressed`.
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Kafka `availability.events` -> `handle_message` | Producer-supplied bytes; every field is attacker-influenced until pydantic validates it |
| notifier -> Postgres | Event fields reach bound parameters of the pre-filter SELECT |
| notifier -> Redis | The daily-cap counter, keyed by a user id |
| notifier -> `notifications.queued` | The embedded event is re-published to a topic other services read |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-04-15 | Denial of Service | one user flooded with alerts | medium | mitigate | `NOTIF_DAILY_CAP_LUA` evaluated before any publish; over-cap matches recorded `suppressed` with no provider cost (D-74) |
| T-04-16 | Denial of Service | a poison message stalling the partition forever | high | mitigate | Bounded transient retries plus a poison arm that dead-letters to `notifications.dlq` and commits past — the Phase-2 CR-01 fix, repeated here rather than reinvented |
| T-04-17 | Tampering | a committed offset overtaking a failed one | high | mitigate | Explicit `seek(msg.offset)` + `pause` + `call_later(resume)`; a unit test asserts no commit occurs on the transient arm |
| T-04-18 | Tampering | SQL injection through event fields | medium | mitigate | SQLAlchemy Core with bound parameters only; the platform id is bound as a string, never interpolated |
| T-04-19 | Information Disclosure | booking token or email address in a fan-out log line | high | mitigate | `_failure_shape` for producer-supplied data and `safe_error` for our own infrastructure; the extended `_redact_secrets` from 04-01 covers the value-shaped keys |
| T-04-20 | Repudiation | an alert suppressed with no record of why | low | mitigate | Every suppression writes a `notification_log` row with `status='suppressed'` and a reason, so a "why did I not get an alert" question has an answer |
| T-04-SC | Tampering | package-manager installs | high | mitigate | This phase adds ZERO packages (research §Package Legitimacy Audit); the gate lands in 04-04 |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 or skips cleanly without Docker.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run pytest tests/unit/test_no_setnx_expire_pairs.py tests/unit/test_no_inline_sleep.py -q` exits 0 — the new service tree does not reintroduce either banned shape.
</verification>

<success_criteria>
- One event fans out to exactly one job per channel per matching active watch, on a real broker.
- The matcher is pure, its boundaries are exhaustively parametrised, and the weekday map is written out by hand in the test.
- The daily cap sits upstream of the queue and leaves a durable record of every suppression.
- The offset policy has an executable assertion for each of its three arms and never auto-commits.
</success_criteria>

<output>
Create `.planning/phases/04-notification-pipeline/04-03-SUMMARY.md` when done
</output>
