---
phase: 04-notification-pipeline
plan: 02
type: execute
wave: 1
depends_on: []
files_modified:
  - shared/redis_keys.py
  - shared/events.py
  - shared/db.py
  - services/state_machine/persistence.py
  - migrations/versions/0010_notification_pipeline.py
  - scripts/create_topics.py
  - tests/integration/conftest.py
  - tests/unit/factories.py
  - tests/unit/test_notification_events_schema.py
  - tests/unit/test_notif_idempotency_key.py
  - tests/integration/test_migration_0010.py
  - tests/integration/test_notif_claim_and_cap.py
autonomous: true
requirements: [NOTIF-01, NOTIF-02, NOTIF-06]

estimate:
  tokens: 64000
  raw_tokens: 64000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`notif_idempotency_key(watch_id, event_id, channel)` returns `notif:{watch}:{event}:{channel}` with every component percent-escaped, and `set_nx_ex` against a live Redis 7.2 returns `True` on the first claim, `False` on the second, and `True` again only after an explicit DELETE — the delete-on-definitive-failure path (D-76, NOTIF-02)."
    - "The channel suffix is load-bearing: `notif_idempotency_key(7, 'E', 'email')`, `(7, 'E', 'sms')` and `(7, 'E', 'push')` are three distinct keys, so one watch's three sends claim independently and a single un-suffixed key can never collapse them (D-76, Phase-2 WR/CR-01 precedent)."
    - "`NOTIF_DAILY_CAP_LUA` INCRs and sets the TTL only when the counter is 1, so `TTL rate:notif:{user}:{day}` counts DOWN across successive calls instead of being refreshed — the MULTI form is measurably a sliding 48 h window and is not used anywhere (D-74a, research §Per-user daily cap)."
    - "PROBE NOTIF-02/adjacency: at exactly the cap the Lua returns allowed, at cap + 1 it returns refused, and two concurrent claims on the identical `(watch, event, channel)` produce exactly one winner — `set_nx_ex` returns `True` for one caller and `False` for the other, never both."
    - "PROBE NOTIF-02/empty: an empty `event_id`, an empty `channel` and a zero `watch_id` each still render a well-formed, distinct key rather than colliding on `notif:::`; `service_day()` on the first instant of a New York calendar day and on its last produce two different keys."
    - "PROBE NOTIF-02/ordering: the claim is order-independent — whichever of two racing workers wins, exactly one `notification_log` row survives for the tuple, because the Layer-3 partial unique index uses the SAME `(watch_id, event_id, channel)` triple as the Layer-2 Redis key and the two can never disagree (D-76a)."
    - "`alembic upgrade head` on a fresh database reaches revision 0010, after which `users` has `phone_hash` (uniquely indexed) and `sms_opt_out NOT NULL DEFAULT false`, `notification_log` has `latency_ms` and `error` plus a column comment recording the status vocabulary `queued|sent|delivered|clicked|failed|suppressed|duplicate_suppressed`, and `push_subscriptions` exists with a UNIQUE `endpoint` and an active-only index (D-85)."
    - "Migration 0010 carries a pre-flight guard that REFUSES to run — raising a `RuntimeError` naming the duplicate count and the remedy — rather than letting `CREATE UNIQUE INDEX` fail cryptically when `notification_log` already holds a duplicate `(watch_id, event_id, channel)`; `downgrade()` drops `push_subscriptions` before the columns and indexes it depends on (0008 guard idiom)."
    - "`NotificationQueued` and `NotificationSent` are `frozen=True, extra=\"forbid\"` pydantic models in `shared/events.py` whose field declaration order is the wire order, and `make_job_id(watch_id, event_id, channel)` is a deterministic `uuid5` over `notif:{watch_id}:{event_id}:{channel}` that reproduces the same UUID across processes (D-75, D-86)."
    - "`scripts/create_topics.py` creates `notifications.dlq` with 30-day retention idempotently, and re-running it is a no-op (D-75)."
    - "`SERVICE_TZ` has exactly ONE definition site, in `shared/redis_keys.py`; `services/state_machine/persistence.py` imports it instead of declaring its own `ZoneInfo`, and every Phase-2 service-time test stays green."
  artifacts:
    - migrations/versions/0010_notification_pipeline.py
    - tests/integration/test_notif_claim_and_cap.py
    - tests/integration/test_migration_0010.py
    - tests/unit/test_notification_events_schema.py
    - tests/unit/test_notif_idempotency_key.py
  key_links:
    - "`notif_idempotency_key()` -> `set_nx_ex()` (Layer 2, Redis) -> the partial UNIQUE index on `notification_log` (Layer 3, Postgres). The two layers key on the identical triple ON PURPOSE, so they cannot disagree about what a duplicate is; SC2's proof is then a database constraint rather than a count."
    - "`NOTIF_DAILY_CAP_LUA` -> `services/notifier/consumer.py` (04-03) — the only place the per-user cap is enforced; a cap evaluated after a provider call would be a bill, not a cap."
    - "`make_job_id()` -> `NotificationQueued.job_id` -> the Resend `Idempotency-Key` header (04-05) and downstream dedupe of a duplicated `notifications.sent` (04-06). Determinism is what makes all three the same identity."
    - "migration 0010 `users.phone_hash` -> `POST /webhooks/twilio/inbound` (04-04). The unique index is what lets a STOP resolve a sender to exactly one user."
  prohibitions:
    - "MUST NOT issue a two-command `SETNX` followed by a separate `EXPIRE` anywhere; every claim goes through `shared.redis_keys.set_nx_ex`, and the daily cap sets its TTL inside the Lua."
    - "MUST NOT create a Redis key without a TTL. The pinned server runs `maxmemory-policy noeviction`, so an untagged key is permanent and a permanent claim silently suppresses a real alert forever."
    - "MUST NOT generate migration 0010 with `alembic revision --autogenerate` — the same session proposes destructive changes to the hypertables."
    - "MUST NOT alter, drop or re-point the existing `notification_log.watch_id` foreign key. Per D-89 it stays exactly as it is and Phase 5's WATCH-04 delete is a soft delete, which preserves the audit trail (research OQ-4 recommended `ON DELETE SET NULL`; the locked decision supersedes it)."
    - "MUST NOT redefine, rename or reorder any existing field of `AvailabilityEvent`, `AvailabilityRaw` or `PollCompleted` — the committed replay goldens are byte-identical only while that wire order holds."
---

<objective>
Land the wire schemas, the Redis claim and rate-limit primitives, and the storage schema that every
later Phase-4 plan writes through: `NotificationQueued` / `NotificationSent`, the Layer-2
`SET NX EX` key family, the per-user daily-cap Lua, migration 0010, and the `notifications.dlq` topic.

Purpose: NOTIF-02 and ROADMAP SC2 are an ATOMICITY promise, and atomicity has to be built into the
primitives rather than remembered at each call site. This plan proves, against a live Redis and a
live TimescaleDB, that the Redis claim and the database constraint agree on exactly one send per
`(watch, event, channel)` before any code exists that could send one.
Output: extended `shared/redis_keys.py` and `shared/events.py`, updated ORM, hand-written migration
0010, the dead-letter topic, integration seed helpers, and the tests that pin every boundary.
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
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — one claim, one capped user, one durable row, proven across Redis and Postgres</name>
  <files>shared/redis_keys.py, shared/db.py, migrations/versions/0010_notification_pipeline.py, tests/integration/conftest.py, tests/integration/test_notif_claim_and_cap.py</files>
  <precondition>`migrations/versions/0009_restaurant_slug_source_unique.py` exists on disk (created by Phase 3 plan 03-03). Migration 0010 sets `down_revision = "0009"` and `alembic upgrade head` fails on a missing revision, so if 0009 is absent, STOP and report the phase-ordering violation instead of rebasing onto 0008.</precondition>
  <reversibility rating="costly">Migration 0010 adds a unique index and a table to a shared schema; reversing it after Phase 5 has written phone hashes and push subscriptions is a data migration, not a `downgrade()`.</reversibility>
  <read_first>
    - shared/redis_keys.py in full (the `Named symbols:` docstring list to extend, `set_nx_ex` and its single-`r.set` shape, `event_idempotency_key` and its injectivity/escaping argument, `AVAIL_STATE_TTL_SECONDS` / `EVENT_IDEMPOTENCY_TTL_SECONDS` comment density, and the `CLAIM_POLL_LUA` / `EXPEDITE_POLL_LUA` commentary style)
    - shared/db.py lines 36-105 (`User`, `WatchlistEntry`, `NotificationLog` — the exact columns, the absent `server_default` on `created_at`/`updated_at`, and the `LargeBinary` phone column comment)
    - migrations/versions/0008_add_event_id_to_availability_events.py in full (the hand-written header comment, the pre-flight duplicate guard, the `COMMENT ON COLUMN` idiom and its doubled `%%`, and the reverse-order `downgrade`)
    - tests/integration/conftest.py in full (`reset_shared_db_singletons`, `apply_migrations`, `redis_url`, `db_urls`)
    - tests/integration/test_migration_0008.py (the migration-test shape) and tests/integration/test_scheduler_claim_release.py (the Redis container assertion style)
    - shared/scheduler/lua.py (the `script_load` + NOSCRIPT-fallback pattern for registering a script)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Layer-2 Idempotency, Rate Limit and Commit" (the verified claim transcript, the exact daily-cap Lua, the MULTI counter-example, and the backstops section) and §"Migration 0010" (the full change table and the guard rules)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-74, §D-74a, §D-76, §D-76a, §D-85, §D-89
  </read_first>
  <behavior>
    - Against a live Redis 7.2 container: the first `set_nx_ex(notif_idempotency_key(7, e, "sms"), "1", 86400)` returns `True` with `TTL` near 86400; the second returns `False`; after `DELETE`, a third returns `True`.
    - The three channel keys for one `(watch, event)` are pairwise distinct and claiming one leaves the other two claimable.
    - The daily-cap script with cap 3 returns allowed for calls 1-3 and refused for calls 4-5, and `TTL` is set on call 1 and then strictly decreases rather than resetting.
    - `service_day()` renders `YYYY-MM-DD` in `America/New_York`, so an instant at 23:00 New York time and one at 00:30 the next New York day produce different keys.
    - Against a live TimescaleDB container: `alembic upgrade head` reaches `0010`; a seeded user and watch insert; an `ON CONFLICT DO UPDATE` insert of `notification_log` for `(watch, event, "sms")` returns an id, and a second identical insert returns the SAME id rather than creating a row.
    - Attempting to leave two rows for one triple in a non-suppressed status raises a Postgres unique violation.
  </behavior>
  <action>
Extend `shared/redis_keys.py` with the Phase-4 registry, in the module's existing register — every
key a `def *_key(...) -> str` with a decision-ID docstring, every constant a `Final`, and the
`Named symbols:` line updated with every new name.

Add `NOTIF_IDEMPOTENCY_TTL_SECONDS = 86_400` and `notif_idempotency_key(watch_id: int, event_id: str,
channel: str) -> str` returning `"notif:"` joined from the three percent-escaped components exactly as
`event_idempotency_key` does. The docstring carries two loads: the ROADMAP SC2 key is
`notif:{watch_id}:{event_id}` and this is that key family EXTENDED by a channel suffix, because one
watch has up to three independent sends and a shared key collapses them — structurally the same
defect as Phase 2's token-only claim key that collapsed two seat types (D-76); and the escaping is
cheap insurance for a component set that is injective today only because `channel` is a `Literal` and
`event_id` a UUID.

Add `SERVICE_TZ: Final[ZoneInfo] = ZoneInfo("America/New_York")` with `service_day(now=None) -> str`
returning `YYYY-MM-DD` in that zone, `NOTIF_RATE_TTL_SECONDS = 172_800`,
`NOTIFY_DAILY_CAP_DEFAULT = 50`, `rate_notif_key(user_id: int, day: str) -> str` producing
`rate:notif:{user_id}:{day}`, and `NOTIF_DAILY_CAP_LUA` verbatim in shape from research: INCR, then
`if n == 1 then EXPIRE end`, then a refusal branch returning `{n, 0}` above the cap and `{n, 1}`
otherwise. Carry the counter-example in the comment above it: a MULTI cannot branch on the INCR
reply, so its EXPIRE is unconditional and refreshes the window on every call, silently converting a
calendar-day cap into a sliding 48-hour one — a user receiving one alert a day would then never
reset. State that the day component comes from `SERVICE_TZ` and not from `date.today()`, because a
"50 per day" that rolls over at 19:00 local is a bug users notice.

Then collapse the duplicate timezone: change `services/state_machine/persistence.py` to import
`SERVICE_TZ` from `shared.redis_keys` under its existing private alias instead of constructing its own
`ZoneInfo`. One-line change, zero behaviour change, and it keeps a single definition site for the
service zone the way `CONFIRM_DELAY_MS` already has one.

Update `shared/db.py` in lockstep with the migration: add `phone_hash: Mapped[str | None]` and
`sms_opt_out: Mapped[bool]` to `User`; add `latency_ms: Mapped[int | None]` and
`error: Mapped[str | None]` to `NotificationLog`; add a `PushSubscription` class over
`push_subscriptions` with `id`, `user_id` FK, `endpoint` (unique), `p256dh`, `auth`, `user_agent`,
`created_at`, `revoked_at`. Leave `NotificationLog.watch_id`'s foreign key exactly as it is (D-89).

Hand-write `migrations/versions/0010_notification_pipeline.py` with `revision = "0010"` and
`down_revision = "0009"`, following 0008's header comment stating that it is hand-written and why
autogenerate is banned. Changes: the two `users` columns plus a unique index on `phone_hash` (a unique
index over a nullable column is fine in Postgres — NULLs do not collide, and email-only users have no
phone); the two `notification_log` columns; a `COMMENT ON COLUMN notification_log.status` recording
the vocabulary; the Layer-3 backstop `CREATE UNIQUE INDEX uq_notification_log_watch_event_channel ON
notification_log (watch_id, event_id, channel) WHERE status NOT IN ('suppressed',
'duplicate_suppressed')`; and `CREATE TABLE push_subscriptions` with a partial index on `user_id`
where `revoked_at IS NULL`. Write a comment above the partial index explaining the predicate: D-76a
asks for a plain UNIQUE so SC2 is a database constraint, but D-76 also requires a
`duplicate_suppressed` row to be written for a tuple that already has a `sent` row and D-74 requires a
`suppressed` row for a capped one — excluding exactly those two statuses is what lets both decisions
hold at once, while `queued`, `sent`, `delivered`, `clicked` and `failed` remain one row per triple.
Add the 0008-style pre-flight guard that counts existing duplicate triples in a non-suppressed status
and raises a `RuntimeError` naming the count and the remedy; note that `notification_log` has never
been written to (0005: columns only, writes in Phase 4), so it is a no-op in every environment today —
which is precisely the situation 0008's guard was written for. `downgrade()` reverses in order,
dropping the table before the columns and indexes.

Add to `tests/integration/conftest.py` a `seed_user_and_watch(session, *, email, restaurant, ...)`
helper that sets `created_at`/`updated_at` EXPLICITLY on both `User` and `WatchlistEntry` — the ORM
declares them `nullable=False` with no `server_default`, so an omission fails on a NOT NULL violation
— flushes to populate `user.id`, and returns the created rows. Also add `fake_push_subscription()`
generating a real P-256 keypair and returning an endpoint/`p256dh`/`auth` triple whose private half
the caller keeps, so 04-05's push assertions can actually decrypt.

Write `tests/integration/test_notif_claim_and_cap.py` as the tracer, driving one notification's
complete duplicate-suppression decision across BOTH layers against live containers: apply migrations
to head, monkeypatch `DATABASE_URL_ASYNC` and call `reset_shared_db_singletons()` (or the cached
engine still points at localhost), seed a user and an active watch, claim the Redis key, run the cap
Lua, insert the `notification_log` row through a `pg_insert(...).on_conflict_do_update(...)` naming
the same triple and RETURNING the id, then replay the whole sequence and assert the claim is refused,
the row id is unchanged, and no second row exists. Assert every bullet in `<behavior>`, including the
TTL countdown, the concurrent single-winner property via `asyncio.gather`, and the New York day
rollover.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_notif_claim_and_cap.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_notif_claim_and_cap.py -q -p no:cacheprovider` exits 0, or skips with the existing Docker-guard message on a host with no Docker runtime.
    - `uv run pytest tests/unit -q` exits 0 — `test_redis_keys.py`, `test_redis_keys_phase2.py`, `test_no_setnx_expire_pairs.py` and `test_service_time_math.py` all stay green.
    - `uv run python -c "from shared.redis_keys import notif_idempotency_key as k; print(k(7,'E','email'), k(7,'E','sms'), k(7,'E','push'), len({k(7,'E',c) for c in ('email','sms','push')}))"` prints three distinct keys and a trailing `3`.
    - `uv run python -c "from shared.redis_keys import NOTIF_DAILY_CAP_LUA as s; print('INCR' in s, 'EXPIRE' in s, 'if n == 1' in s)"` prints `True True True`.
    - `uv run python -c "import shared.redis_keys as k, services.state_machine.persistence as p; print(p._SERVICE_TZ is k.SERVICE_TZ)"` prints `True`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>One notification's duplicate decision runs end to end across a live Redis claim, a live per-user cap and a live Postgres unique constraint, and the second attempt is refused by both layers.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: `NotificationQueued` / `NotificationSent` wire schemas, deterministic job ids, and the dead-letter topic</name>
  <files>shared/events.py, scripts/create_topics.py, tests/unit/factories.py, tests/unit/test_notification_events_schema.py</files>
  <read_first>
    - shared/events.py in full (the `frozen=True, extra="forbid"` config, the `to_bytes` convention, `NAMESPACE_MISE`'s permanence comment, `make_event_id`'s non-injectivity warning, and `AvailabilityEvent`'s "declaration order IS the wire order" note)
    - tests/unit/test_events_schema.py (the schema-assertion style to mirror)
    - tests/unit/factories.py in full (the existing builders to extend)
    - scripts/create_topics.py in full (the `NewTopic` list, the retention comments and the idempotent create)
    - services/state_machine/consumer.py lines 50-66 (`DLQ_TOPIC` and the retention reasoning for a dead-letter topic)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-75, §D-86
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Latency Budget and Measurement" (why `produced_at_epoch_ms` is the confirming poll's timestamp and what a negative `latency_ms` means)
  </read_first>
  <behavior>
    - `make_job_id(7, "5f5e…", "sms")` returns the same UUID on every call and in a fresh interpreter; the three channels for one `(watch, event)` give three distinct UUIDs.
    - `NotificationQueued` round-trips through `to_bytes()` and `model_validate_json` unchanged, with the embedded `AvailabilityEvent` intact.
    - An extra field in the JSON raises a `ValidationError` (`extra="forbid"`), and assigning to a field raises (`frozen=True`).
    - A `channel` outside `email|sms|push` is rejected.
    - The JSON key order emitted by `to_bytes()` matches the field declaration order for both models.
    - `NotificationSent.latency_ms` equals `sent_at_epoch_ms - event_produced_at_epoch_ms` in the builder used by the factories, and the model accepts `0` but the factory clamps a negative computation to `0`.
    - Re-running `scripts/create_topics.py` after a first run prints the idempotent no-op line and creates nothing.
  </behavior>
  <action>
Extend `shared/events.py` with the Phase-4 contracts (D-75, D-86), appended after `AvailabilityEvent`
and never reordering anything above them.

`NOTIFICATION_CHANNELS: Final[tuple[str, ...]] = ("email", "sms", "push")` and
`make_job_id(watch_id: int, event_id: str, channel: str) -> UUID` as `uuid5(NAMESPACE_MISE,
f"notif:{watch_id}:{event_id}:{channel}")`. The docstring must state that determinism is the point —
the same job id is what makes the Resend `Idempotency-Key` header, the Layer-2 Redis claim and any
downstream dedupe of a duplicated `notifications.sent` all name one identity — and, unlike
`make_event_id`, the components here are injective by construction (`watch_id` is an int, `event_id`
a UUID string, `channel` a `Literal`), so the joined form is unambiguous; say that explicitly so the
next reader does not have to re-derive it from `make_event_id`'s warning.

`NotificationQueued` with fields in this exact wire order: `job_id: UUID`, `watch_id: int`,
`user_id: int`, `event_id: UUID`, `channel: Literal["email", "sms", "push"]`, `event:
AvailabilityEvent`, `queued_at_epoch_ms: int`, plus `to_bytes()`. The docstring records D-75's reason
for embedding the whole event: the delivery worker then needs no second lookup to render a message.

`NotificationSent` with fields in this exact wire order: `job_id`, `watch_id`, `user_id`, `event_id`,
`channel`, `status: Literal["sent", "failed", "suppressed", "duplicate_suppressed"]`,
`provider_id: str | None`, `sent_at_epoch_ms: int`, `event_produced_at_epoch_ms: int`,
`latency_ms: int`, plus `to_bytes()`. The docstring records that `latency_ms` is
`sent_at - event.produced_at_epoch_ms` (D-45/D-86), that `produced_at_epoch_ms` is the confirming
poll's timestamp rather than a wall clock, and that the value is clamped at zero by the producer
because a notifier clock behind the poller's would otherwise store a negative row that silently drags
the PERF-01 p95 down and makes the gate lie.

Add a `notifications.dlq` `NewTopic` to `scripts/create_topics.py` with 30-day retention, listed in
the module docstring's topic table and in its Named Symbols block alongside the other topics. Comment
the retention choice: 30 days matches `notifications.queued`/`notifications.sent` rather than the
7-day diagnostic topics, because a notification that dead-lettered is a user who did not get an alert
and the record has to outlive a billing cycle's worth of questions.

Extend `tests/unit/factories.py` with `make_availability_event(**overrides)`,
`make_notification_queued(**overrides)` and `make_watch_row(**overrides)` in the file's existing
builder style, each with sane deterministic defaults so a test names only the field it is exercising.

Write `tests/unit/test_notification_events_schema.py` covering every schema bullet in `<behavior>`,
including an explicit assertion that the JSON key order produced by `to_bytes()` equals the declared
field order for both models, and a same-value/different-process determinism check for `make_job_id`
run through `uv run python -c` in a subprocess.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_notification_events_schema.py tests/unit/test_events_schema.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_notification_events_schema.py -q` exits 0.
    - `uv run pytest tests/unit/test_replay_determinism.py tests/unit/test_event_id_determinism.py -q` exits 0 — appending to `shared/events.py` did not perturb any committed golden.
    - `uv run python -c "from shared.events import make_job_id as j; print(j(7,'e','email')==j(7,'e','email'), len({str(j(7,'e',c)) for c in ('email','sms','push')}))"` prints `True 3`.
    - `uv run python -c "import json; from shared.events import NotificationSent; print(list(NotificationSent.model_fields))"` prints the ten field names in the declared wire order ending with `latency_ms`.
    - `grep -c "notifications.dlq" scripts/create_topics.py` returns a value of at least `2`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Both notification wire contracts exist with frozen, extra-forbidding schemas and a deterministic job id, and the dead-letter topic is created idempotently alongside the other six.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Key injectivity and the migration's up/down/guard behaviour, pinned as tests</name>
  <files>tests/unit/test_notif_idempotency_key.py, tests/integration/test_migration_0010.py</files>
  <read_first>
    - tests/unit/test_redis_keys_phase2.py (the injectivity-assertion style for `event_idempotency_key`, including the deleted-helpers-stay-gone test)
    - tests/unit/test_slot_key_collisions.py (how a known non-injectivity is pinned as an executable constraint rather than prose)
    - tests/integration/test_migration_0008.py in full (the upgrade/downgrade shape and, per the 02-REVIEW-FIX WR-07 lesson, the rule that a shared schema must not be downgraded and restored outside the failure path)
    - tests/integration/test_migrations_apply.py (the fresh-database upgrade-to-head assertion)
    - migrations/versions/0010_notification_pipeline.py as written in Task 1
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Migration 0010" (the guard rules and the column list)
  </read_first>
  <behavior>
    - Two different `(watch_id, event_id, channel)` triples never render the same key, including triples whose components contain `:` or `%`.
    - A key built from a component containing `:` percent-escapes it, so the rendered key can be split back unambiguously.
    - `rate_notif_key` renders `rate:notif:{user}:{day}` and two different users on the same day, and one user on two days, give four distinct keys.
    - On a fresh container, `alembic upgrade head` leaves `information_schema` showing `users.phone_hash`, `users.sms_opt_out`, `notification_log.latency_ms`, `notification_log.error` and the `push_subscriptions` table with a UNIQUE constraint on `endpoint`.
    - The `notification_log.status` column comment contains all seven status words.
    - Inserting two `notification_log` rows with the same `(watch_id, event_id, channel)` and status `sent` raises a unique violation; inserting one `sent` row and one `duplicate_suppressed` row for the same triple succeeds.
    - `alembic downgrade -1` from 0010 succeeds and removes the table and all four columns; a subsequent `upgrade head` restores them.
  </behavior>
  <action>
Write `tests/unit/test_notif_idempotency_key.py` in the style of `tests/unit/test_redis_keys_phase2.py`:
a parametrised injectivity matrix over triples chosen to be adjacent under an unescaped join (a
`watch_id` whose digits run into an `event_id`, an `event_id` containing `:`, a `channel` containing
`%`), asserting distinctness; a round-trip test proving the escaped components can be recovered; the
`rate_notif_key` distinctness matrix; and a `service_day` test that pins the New York rollover by
constructing two aware datetimes either side of local midnight rather than by reading the clock.

Write `tests/integration/test_migration_0010.py` against the module-scoped TimescaleDB container.
Follow `test_migration_0008.py` exactly, INCLUDING the WR-07 lesson recorded in `02-REVIEW-FIX.md`:
do not downgrade the shared schema and then restore it outside a failure path — take the container
through `upgrade head`, make every structural assertion by querying `information_schema.columns`,
`information_schema.table_constraints` and `pg_indexes`, read the status column comment through
`col_description`, and confine the downgrade/upgrade round trip to its own test that leaves the schema
at head on every exit path.

Add the constraint-behaviour assertions: two `sent` rows on one triple raise
`asyncpg.exceptions.UniqueViolationError`, while a `sent` row plus a `duplicate_suppressed` row on the
same triple both persist — the partial predicate is what makes D-76 and D-76a compatible, so the test
has to prove BOTH halves, not just the refusal. Add a test that exercises the pre-flight guard by
seeding two conflicting non-suppressed rows before the index is created and asserting the migration
raises a `RuntimeError` whose message names the duplicate count.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_notif_idempotency_key.py tests/integration/test_migration_0010.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_notif_idempotency_key.py -q` exits 0.
    - `uv run pytest tests/integration/test_migration_0010.py tests/integration/test_migrations_apply.py -q -p no:cacheprovider` exits 0, or skips on a Docker-less host.
    - `uv run pytest tests/unit tests/integration -q -p no:cacheprovider` exits 0 (or skips the integration tier without failures).
    - `grep -c "0009" migrations/versions/0010_notification_pipeline.py` returns at least `1`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>The claim and rate keys are provably injective, and migration 0010's upgrade, downgrade, column comment, partial unique index and pre-flight guard each have an executable assertion.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (04-02 slice)

**New symbols — `shared/redis_keys.py`:** `NOTIF_IDEMPOTENCY_TTL_SECONDS` (86400),
`notif_idempotency_key()`, `SERVICE_TZ`, `service_day()`, `NOTIF_RATE_TTL_SECONDS` (172800),
`NOTIFY_DAILY_CAP_DEFAULT` (50), `rate_notif_key()`, `NOTIF_DAILY_CAP_LUA`.

**Redis key patterns:** `notif:{watch_id}:{event_id}:{channel}` (SET NX EX, 24 h),
`rate:notif:{user_id}:{YYYY-MM-DD}` (INCR + conditional EXPIRE, 48 h).

**Lua scripts:** `NOTIF_DAILY_CAP_LUA` — `KEYS[1]` rate key, `ARGV[1]` ttl, `ARGV[2]` cap; returns
`{count, allowed}`.

**New symbols — `shared/events.py`:** `NOTIFICATION_CHANNELS`, `make_job_id()`, `NotificationQueued`,
`NotificationSent`.

**Kafka topics:** `notifications.dlq` (1 partition, 30-day retention) added to
`scripts/create_topics.py`.

**Database — migration `0010_notification_pipeline`** (`down_revision = "0009"`):
`users.phone_hash TEXT NULL` + `uq_users_phone_hash`; `users.sms_opt_out BOOLEAN NOT NULL DEFAULT
false`; `notification_log.latency_ms INTEGER NULL`; `notification_log.error TEXT NULL`; column comment
recording the status vocabulary `queued|sent|delivered|clicked|failed|suppressed|duplicate_suppressed`;
partial unique index `uq_notification_log_watch_event_channel` on `(watch_id, event_id, channel)`
`WHERE status NOT IN ('suppressed','duplicate_suppressed')`; table `push_subscriptions(id, user_id,
endpoint UNIQUE, p256dh, auth, user_agent, created_at, revoked_at)` with a `revoked_at IS NULL`
partial index.

**ORM additions — `shared/db.py`:** `User.phone_hash`, `User.sms_opt_out`,
`NotificationLog.latency_ms`, `NotificationLog.error`, class `PushSubscription`.

**Test helpers:** `tests/integration/conftest.py::seed_user_and_watch`,
`tests/integration/conftest.py::fake_push_subscription`; `tests/unit/factories.py::make_availability_event`,
`make_notification_queued`, `make_watch_row`.

**Env vars consumed:** `NOTIFY_DAILY_CAP_PER_USER` (read by 04-03; the default constant lives here).
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Kafka `availability.events` -> notifier | Producer-supplied JSON deserialised into pydantic models |
| notifier -> Redis | The only store touched BEFORE a provider call; its correctness is the whole duplicate-suppression guarantee |
| notifier -> Postgres | The durable audit trail two success criteria read |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-04-09 | Tampering | Redis eviction discarding a live claim | high | mitigate | `maxmemory-policy=noeviction` on the pinned server and in `tests/conftest.py`; every key carries a TTL set in the same command or the same script |
| T-04-10 | Tampering | Non-atomic claim (`SETNX` + `EXPIRE`) | high | mitigate | Single `SET … NX EX` through `shared.redis_keys.set_nx_ex`; the existing `tests/unit/test_no_setnx_expire_pairs.py` already scans `services/`, `shared/` and `scripts/` recursively |
| T-04-11 | Denial of Service | Notification bombing one user | medium | mitigate | `rate:notif:{user}:{day}` cap via `NOTIF_DAILY_CAP_LUA`, atomic and expiring, enforced before any provider call (D-74) |
| T-04-12 | Tampering | Duplicate `notification_log` rows defeating the SC2 proof | high | mitigate | Layer-3 partial unique index on the SAME triple as the Layer-2 key, with a pre-flight guard that refuses to create it over existing duplicates |
| T-04-13 | Tampering | SQL injection through event fields | medium | mitigate | SQLAlchemy Core with bound parameters throughout; no string-built SQL anywhere in this plan |
| T-04-14 | Information Disclosure | Migration failure text quoting row values | low | mitigate | The pre-flight guard reports a COUNT and a remedy, never the offending rows; `safe_error` strips Postgres `DETAIL:` lines from any exception that reaches a log |
| T-04-SC | Tampering | package-manager installs | high | mitigate | This phase adds ZERO packages (research §Package Legitimacy Audit). `python-multipart` must not be added; the gate lands in 04-04 |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 or skips cleanly without Docker.
- `uv run alembic upgrade head` reaches `0010` on a fresh database, and `uv run alembic downgrade -1` followed by `upgrade head` round-trips.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
</verification>

<success_criteria>
- The Layer-2 Redis key and the Layer-3 database constraint key on the identical triple and are proven to agree.
- The per-user cap is a fixed calendar day in New York, not a sliding window, with the TTL countdown asserted.
- Migration 0010 is hand-written, guarded, reversible, and chained to 0009.
- Both notification wire schemas are frozen, extra-forbidding, and order-stable; job ids are deterministic.
- Every pre-existing test, including the replay goldens, stays green.
</success_criteria>

<output>
Create `.planning/phases/04-notification-pipeline/04-02-SUMMARY.md` when done
</output>
