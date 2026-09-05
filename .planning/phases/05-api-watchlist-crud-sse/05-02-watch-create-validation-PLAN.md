---
phase: 05-api-watchlist-crud-sse
plan: 02
type: execute
wave: 2
depends_on: [05-01]
files_modified:
  - services/api/schemas.py
  - services/api/watch_service.py
  - services/api/routers/watches.py
  - services/api/config.py
  - services/api/app.py
  - shared/watch_counts.py
  - migrations/versions/00NN_watch_dedupe_partial_unique.py
  - tests/unit/factories.py
  - tests/unit/test_watch_models.py
  - tests/unit/test_watch_count_fields.py
  - tests/integration/test_watch_crud.py
  - tests/integration/test_restaurant_merge.py
  - tests/integration/test_watch_dedupe.py
  - tests/integration/test_watch_counts.py
autonomous: true
requirements: [WATCH-01, WATCH-02]

estimate:
  tokens: 74000
  raw_tokens: 74000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`POST /watches` upserts `users` on the lower-cased, whitespace-stripped email with `on_conflict_do_update(index_elements=['email'])` and `RETURNING id`, so a second submission from the same address reuses the same `user_id`; `on_conflict_do_nothing` is forbidden here because it returns NO row on conflict and the watch would be inserted with a null user (D-90, research §User upsert trap)."
    - "PROBE WATCH-01/unclassified — flagged assumption: identity is the email address alone and nothing verifies that the submitter owns it. Anyone may create a watch for any address; the only consequence is that the management link is emailed to the real owner, who can delete it. The management token — never the email — is the credential for every later mutation, which is why the create response is the only place a token is minted without one being presented (D-90, D-91)."
    - "A slug resolves to the FULL set of `restaurants` rows sharing it (one per source after `uq_restaurants_slug_source`); the watch row is bound to the OpenTable row when one exists and to the Resy row otherwise, and the response echoes a `sources` list naming every source row of that slug (D-93)."
    - "The `201` body is `{watch, management_url, token}` where `management_url` is `{PUBLIC_BASE_URL}/manage/t/{token}` built from `shared/links.py`, and the token is a `shared/tokens.py` token with `purpose='manage'` carrying `user_id` and a 30-day expiry; `watchlist_entries.management_token` is left NULL because verification is purely HMAC and a stored token would be a stored credential (D-91)."
    - "The management-link email is sent through the Phase-4 `EmailProvider` (dry-run aware) as a best-effort side effect: a provider failure is logged with `safe_error` and the request still returns its success status. It is never retried inline and never fails the request (D-93, research §Best-effort side effect)."
    - "`shared/watch_counts.py :: recount(slug)` writes a `watch:count` HASH field for EVERY source row of the slug, including one with zero active watches, by counting through an OUTER join whose `status='active'` predicate sits in the JOIN condition — moving that predicate into the WHERE clause converts the outer join back to an inner one and a restaurant that drops to zero keeps a stale count and stays in the fastest polling tier forever (D-95, D-95a, research §watch:count recount)."
    - "`recount` builds every field through `shared/redis_keys.py :: watch_count_field(...)` and passes the source row's PLATFORM id, never `restaurants.id` — the poller's job descriptor is `{source}:{platform_id}` and the two integers differ for Resy; a unit test pins the produced field for one Resy and one OpenTable row (D-95b, D-52)."
    - "`recount` is best effort and non-fatal: a Redis failure is logged with `safe_error`, increments `watch_count_recount_failures_total`, and the committed watch is still returned — a 500 after a successful commit would make the client retry and create a duplicate (D-95a, research Pitfall 11)."
    - "Every `WatchCreate` rule from D-93 is enforced and unit-tested: `party_size` 1..10 inclusive, `date_to >= date_from`, window at most 60 days, `date_from` not in the past, `HH:MM` 24-hour time strings, `time_window_from` strictly before `time_window_to`, both time bounds set together or neither, `days_of_week` a subset of the seven lower-case abbreviations, a non-empty `channels` subset of email/sms/push, `sms` requiring an E.164 phone, `push` requiring a subscription with an endpoint and both keys, a slug matching the lower-case pattern, a syntactically valid email, and `extra='forbid'` on every model (D-93, WATCH-02)."
    - "PROBE WATCH-02/adjacency: the boundaries are exact and each side is asserted — `date_to == date_from` is a valid one-day window; a window of exactly 60 days is accepted and 61 is rejected; `party_size` 1 and 10 are accepted while 0 and 11 are rejected; `time_window_from == time_window_to` is REJECTED because the rule is strictly-before, while `18:00`/`18:01` is accepted."
    - "PROBE WATCH-02/empty: an empty `channels` list is rejected by a minimum-length rule, an empty `days_of_week` list is rejected with a message telling the caller to omit the field rather than being silently reinterpreted as every day, and an omitted `days_of_week` means no day filter at all; `time_window_from` and `time_window_to` are rejected when only one is supplied."
    - "PROBE WATCH-02/ordering: `days_of_week` is deduplicated, lower-cased and sorted into calendar order mon..sun BEFORE the comma join, so two logically identical watches always produce one stored string and the D-93b dedupe index can see them as equal; `channels` is canonicalised the same way (research §Request Models)."
    - "PROBE WATCH-02/idempotency: a second identical `POST /watches` from the same email returns `200` with the SAME watch id and a freshly minted token, and `watchlist_entries` holds exactly one matching row — enforced by a partial unique index over the nine identity columns restricted to `status IN ('active','paused')`, so a deleted watch never blocks a re-create (D-93b)."
    - "PROBE WATCH-02/concurrency: two identical `POST /watches` issued concurrently produce exactly one row; the loser's `UniqueViolation` is caught by name and converted into the same `200`-with-the-existing-watch path, never into a `500` and never into a second row (D-93b)."
    - "`date_from >= today` is evaluated in `shared/servicetime.py :: SERVICE_TZ`, not UTC; a `freeze_time` test pinned at 01:30 UTC proves a watch for the New York calendar date is accepted, because between 20:00 and midnight Eastern the UTC rule tells a New Yorker that tonight is in the past (D-93a, research Pitfall 1)."
    - "The migration is hand-written, never autogenerated, carries a pre-flight guard that refuses to run and names the offending rows when duplicate active watches already exist, and resolves its own revision id and `down_revision` from the live head at execution time (D-93b, D-33)."
  artifacts:
    - services/api/schemas.py
    - services/api/watch_service.py
    - services/api/routers/watches.py
    - shared/watch_counts.py
    - migrations/versions/00NN_watch_dedupe_partial_unique.py
    - tests/unit/test_watch_models.py
    - tests/unit/test_watch_count_fields.py
    - tests/integration/test_watch_crud.py
    - tests/integration/test_restaurant_merge.py
    - tests/integration/test_watch_dedupe.py
    - tests/integration/test_watch_counts.py
  key_links:
    - "`WatchCreate.days_of_week` -> the canonical comma join -> `watchlist_entries.days_of_week` -> the D-93b dedupe index AND Phase 4's `match_watches`. Three readers of one string; if the ordering is not canonicalised at the boundary, two identical watches are stored as two different strings and the dedupe index cannot see them (research §Request Models)."
    - "`recount(slug)` -> `watch:count` HASH -> the Phase 3 poller's tier arithmetic. The API is the only writer of a contract whose reader already ships; a wrong field key is invisible here and shows up as a restaurant that never leaves the slowest tier (D-58, D-95b)."
    - "`sign_token('manage', {'user_id': …})` -> `management_url` -> the emailed link -> `GET /api/manage/{token}` (05-04). The token is the ONLY credential; nothing is stored, so a bug that mints the wrong `user_id` hands one user another's watches."
    - "slug -> the set of source rows -> `watchlist_entries.restaurant_id`. Phase 4's fan-out joins by `restaurants.id`, so a watch bound to the OpenTable row must still match Resy events for the same slug; the notifier's join is extended to slug equality and that amendment is recorded in its README (D-93)."
  prohibitions:
    - "MUST NOT write a management token into `watchlist_entries.management_token`, any other column, a log line or a file — verification is purely HMAC and a stored token is a stored credential."
    - "MUST NOT log, echo or return a raw phone number, a token, or a management URL from any code path in this plan."
    - "MUST NOT use `on_conflict_do_nothing`, and MUST NOT omit `index_elements` from any upsert — an unnamed conflict target swallows every unique violation, including ones this code never meant to tolerate."
    - "MUST NOT let a `recount` failure, an email-provider failure, or any other best-effort side effect fail a request whose database transaction already committed."
    - "MUST NOT compute `today` from `datetime.now(UTC)` anywhere in the validators."
    - "MUST NOT use `alembic revision --autogenerate`, and MUST NOT drop or rewrite an existing index or constraint in this migration."
    - "MUST NOT pass `restaurants.id` as the `restaurant_id` argument to `watch_count_field` or `tier_override_field`."
---

<objective>
Ship `POST /watches` complete: email-only identity, one slug resolving to its full set of source rows,
the whole D-93 validation matrix, an HMAC management token and URL, the management-link email, the
`watch:count` write the Phase 3 poller already reads, and a partial unique index that makes the
endpoint idempotent per user instead of duplicating a watch on every double-click.

Purpose: this is the only write endpoint an unauthenticated caller can reach, and three of its
failure modes are silent rather than loud — an unnamed upsert conflict target that makes a row
vanish, an inner join that leaves a zero-watch restaurant pinned to the fastest polling tier, and a
UTC `today` that tells a New Yorker at 21:30 that tonight has already passed. All three were
reproduced during research; all three are pinned here as executable tests.
Output: the request/response models, the watch service, the create route, the shared recount helper,
one hand-written migration, and six test modules across both tiers.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md
@.planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md
@.planning/phases/05-api-watchlist-crud-sse/05-01-SUMMARY.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — one POST /watches produces a user row, a watch row, a watch:count field and a management URL</name>
  <files>services/api/schemas.py, services/api/watch_service.py, services/api/routers/watches.py, services/api/config.py, services/api/app.py, shared/watch_counts.py, tests/unit/test_watch_count_fields.py, tests/integration/test_watch_crud.py, tests/integration/test_restaurant_merge.py, tests/integration/test_watch_counts.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"SQLAlchemy 2.0 Async (executed against TimescaleDB 2.17.2-pg16)" — the user upsert transcript, the `DO NOTHING` empty-return trap, the one-slug-many-source-rows result, the `ARRAY.contains` `NotImplementedError` and its three alternatives, and the outer-join recount
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-90, §D-91, §D-93, §D-95, §D-95a, §D-95b
    - .planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md §"`services/api/watch_service.py`", §"`shared/watch_counts.py`", §"Best-effort side effect", §"Module docstring contract"
    - services/state_machine/persistence.py lines 1-40 and 90-120 (the import block, the session idiom, the `pg_insert` dialect import, and the best-effort `except` arm with its `noqa` rationale)
    - shared/db.py lines 41-90 (`User`, `Restaurant`, `WatchlistEntry` column types — note `days_of_week`, `channels`, `seat_type_filter` are Text and the time bounds are `Time`)
    - shared/redis_keys.py lines 315-340 (`WATCH_COUNT_HASH`, `watch_count_field` and the `{source}:{restaurant_id}` field contract) and the typed redis helper block
    - shared/tokens.py and shared/links.py as shipped by 04-01 (`sign_token`, `verify_token`, `public_base_url`) — the exact call signatures and the token wire claim names
    - services/notifier/providers/email.py as shipped by 04-05 (`EmailProvider` and its dry-run behaviour)
    - tests/integration/conftest.py (`api_app`, `live_api`, `db_urls`, `redis_url`, `apply_migrations`, `reset_shared_db_singletons`)
  </read_first>
  <behavior>
    - A `POST /watches` with an email, a slug, a party size, a date range and the email channel returns 201; the body carries a watch object, a management URL and a token.
    - Exactly one `users` row exists for that address afterwards; posting again with the same address in different case and with surrounding whitespace reuses the same user id.
    - The management URL starts with the configured public base URL and contains the token; the token verifies with the manage purpose and carries that user id.
    - `watchlist_entries.management_token` is NULL for the created row.
    - For a slug with an OpenTable row and a Resy row, the created watch's `restaurant_id` is the OpenTable row's id, and the response's source list names both.
    - For a slug with only a Resy row, the watch binds to the Resy row.
    - An unknown slug returns 404.
    - After the create, the `watch:count` hash holds a field for BOTH source rows of the slug; the bound row's count is 1 and the sibling's is 0.
    - `watch_count_field` is called with the source row's platform id: for a Resy row whose surrogate id and platform id differ, the produced field contains the platform id.
    - With Redis unreachable, the same create still returns its success status and the failure counter increments.
    - The management email is attempted exactly once; with the provider in dry-run the send is recorded and the response is unchanged; with the provider raising, the response is still the success status.
  </behavior>
  <action>
Write `services/api/schemas.py` with the request and response models this task needs, leaving the full
validator matrix to Task 2 — the field set, the types and the `extra='forbid'` posture are complete
now, the cross-field rules arrive next. Define an annotated email string type carrying lower-casing
and whitespace stripping as declarative constraints, so the value reaching the upsert is already
canonical and the validation and the conflict key can never drift (D-90). Define `WatchCreate` with
the D-93 field set and `WatchOut`, `WatchCreateResponse` and a `RestaurantSource` DTO. `WatchOut`
exposes a masked phone (last two digits only) and never a raw phone; state that in the field
docstring. Do not depend on an email-validation package — none is pinned, and the address's only use
is to receive a link, so a syntactic check is the right depth.

Write `shared/watch_counts.py` with `recount(slug)` (D-95, D-95a, D-95b). One statement: select the
source, the platform id and a count of watch rows, selecting FROM `restaurants`, OUTER joining
`watchlist_entries` with BOTH the foreign-key equality AND the active-status predicate inside the
join condition, filtering on the slug, grouped by source and platform id. Put a comment on the join
stating that moving the status predicate into the WHERE clause silently converts this to an inner
join and drops the zero-watch sibling, which then keeps a stale count forever. Write every field
through `watch_count_field(...)`, passing the row's platform id coerced to the type that helper
expects, with a comment recording D-52's rule that the surrogate `restaurants.id` must never appear
in a Redis field. Write all fields in one hash-set call. Wrap the whole Redis interaction in the
best-effort `except` arm the repo already uses — a blind except whose `noqa` comment states the
reason — logging through `safe_error` and incrementing the recount failure counter. Give the module
the standard docstring: what it is, the decision ids, the constraint a future reader will otherwise
"fix" (the outer join), and a `Named symbols:` list.

Write `services/api/watch_service.py` in the register of `services/state_machine/persistence.py` —
same import block, same session idiom, same dialect import — but without its best-effort swallow: a
failed watch insert must fail the request. Provide `upsert_user(session, email) -> int` using
`pg_insert(...).on_conflict_do_update(index_elements=["email"], set_={"updated_at": now})` with
`RETURNING id` and `scalar_one()`; put the reproduced trap in a comment, namely that the do-nothing
variant returns no rows on conflict so the call would raise or, worse, yield a null user id. Provide
`resolve_restaurant(session, slug) -> list[Restaurant]` returning every source row for the slug
ordered so the OpenTable row sorts first, and `bind_target(rows)` selecting the OpenTable row when
present and the Resy row otherwise (D-93). Provide `create_watch(...)` performing the insert, and a
`canonical_days`/`canonical_channels` pair that dedupes, lower-cases and sorts into calendar order
before the comma join — the persistence layer owns the string shape and the model owns the list.

Write `services/api/routers/watches.py` with `POST /watches`. Order of operations, each a commented
step: validate the body through the model; resolve the slug and 404 when it is unknown; upsert the
user; insert the watch and commit; mint a manage-purpose token carrying the user id through
`shared/tokens.py` and build the management URL through `shared/links.py`; call `recount(slug)`;
attempt the management-link email through the Phase-4 `EmailProvider`; return the created body with a
`201`. State in a comment that the token is minted AFTER the commit and is never persisted, and that
both the recount and the email are best-effort and appear after the commit for exactly that reason.
Increment `watch_create_total` with a result label on each outcome. Register the router in
`services/api/app.py` beside the health and metrics routers, and add any config accessor the route
needs to `services/api/config.py`.

Write `tests/unit/test_watch_count_fields.py` pinning the D-95b contract: build one OpenTable row and
one Resy row whose surrogate id and platform id differ, and assert the field the recount would write
for each is the one `watch_count_field` produces from the PLATFORM id. This test is cheap and it is
the only place the two-integers-under-one-name bug is visible.

Write `tests/integration/test_watch_crud.py` (the create half only; the lifecycle arrives in 05-04),
`tests/integration/test_restaurant_merge.py` (two source rows for one slug, the OpenTable binding,
the Resy-only fallback, and the 404) and `tests/integration/test_watch_counts.py` (both fields
present including the zero sibling, and the Redis-down path still returning success). Every module
docstring names which BC-1 tier it uses and why; these are plain request/response tests, so they use
the buffering transport against the `api_app` fixture with the containers behind it.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_watch_count_fields.py -q -W error::RuntimeWarning &amp;&amp; uv run pytest tests/integration/test_watch_crud.py tests/integration/test_restaurant_merge.py tests/integration/test_watch_counts.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_watch_crud.py tests/integration/test_restaurant_merge.py tests/integration/test_watch_counts.py -q -p no:cacheprovider` exits 0.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run python -c "from services.api.app import create_app; print(sorted((r.path, tuple(sorted(r.methods))) for r in create_app().routes if getattr(r,'path','')=='/watches'))"` prints a single entry whose methods tuple contains `POST`.
    - `uv run python -c "import shared.watch_counts as w; print(callable(w.recount))"` prints `True`.
    - `grep -c 'on_conflict_do_update' services/api/watch_service.py` prints at least `1`.
    - `grep -c 'outerjoin' shared/watch_counts.py` prints at least `1`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>One anonymous POST travels the entire stack — pydantic, Postgres user upsert, slug resolution across source rows, watch insert, HMAC token mint, Redis watch:count write and a best-effort email — and returns a management URL that verifies back to the user it names.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The complete WATCH-02 validation matrix, the E.164 boundary table, and a New-York "today"</name>
  <files>services/api/schemas.py, services/api/watch_service.py, tests/unit/factories.py, tests/unit/test_watch_models.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Request Models (executed)" — the full 18-rule accept/reject transcript, the 8-row E.164 boundary table, and the four "details that will otherwise be discovered the hard way"
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Common Pitfalls" Pitfall 1 (the UTC `today` reproduction with its exact frozen instant) and Pitfall 12 (the `days_of_week` round-trip)
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-93 and §D-93a
    - shared/servicetime.py as written in 05-01 (`SERVICE_TZ`)
    - services/api/schemas.py as written in Task 1
    - tests/unit/factories.py (the existing builder style this file extends)
    - shared/events.py lines 1-70 (the pydantic v2 wire-model conventions this repo already uses)
  </read_first>
  <behavior>
    - Accepted: a baseline payload; a mixed-case, whitespace-padded email normalised to lower case; a mixed-case duplicate day list deduplicated and ordered; a time window with the earlier bound first; the sms channel with a phone in any punctuated form normalised to E.164; the push channel with a complete subscription.
    - Rejected with a message naming the rule: `date_to` before `date_from`; a window longer than 60 days; a `date_from` in the past; a malformed clock string on either time field; a time window whose bounds are equal or inverted; only one of the two time bounds; an unknown day abbreviation, with the message listing the allowed set; an empty channel list; an unknown channel; the sms channel with no phone; the push channel with no subscription; a phone that is not E.164; a party size of 0 or 11; any extra field; a malformed email; a slug that does not match the lower-case pattern.
    - Accepted at the edges: `date_to` equal to `date_from`; a window of exactly 60 days; party sizes 1 and 10; a time window of `18:00` to `18:01`.
    - An empty `days_of_week` list is rejected with a message telling the caller to omit the field; an omitted `days_of_week` yields no filter.
    - E.164: the 8-digit minimum and the 15-digit maximum are accepted; 7 digits, 16 digits, a leading zero after the plus, and a number with no plus are all rejected.
    - Cross-field failures report an empty location that renders as the body, while field-level failures keep their field name; both shapes are asserted so the documented error contract is true.
    - With the clock frozen at 01:30 UTC on a given day, a payload whose `date_from` is the previous UTC day but the current New York day is ACCEPTED.
    - `days_of_week` and `channels` canonicalise to a stable calendar-ordered comma string regardless of input order or case.
  </behavior>
  <action>
Complete `services/api/schemas.py` with every D-93 rule. Use pydantic v2 spellings only — the v1
decorator names error at class-definition time. Field-level constraints carry the bounded values
declaratively (party size range, slug pattern, minimum channel-list length). Cross-field rules go in
an after-model validator: the date ordering, the 60-day window, the not-in-the-past check, the
paired-and-ordered time bounds, and the channel-to-credential requirements. Each raises a message
that names the rule in the caller's vocabulary rather than in the validator's.

Implement the clock rule against `shared/servicetime.py :: SERVICE_TZ` (D-93a). Put the reproduction
in the validator's comment: computing `today` in UTC rejects a watch for tonight for the four hours
each evening when New York is on the previous UTC date — which are precisely the hours someone is
hunting for a table tonight.

Implement the phone normaliser and the E.164 check as one strict pattern applied AFTER stripping
spaces, parentheses, hyphens and dots, with the boundary table from research reproduced as the
docstring's contract. Do not widen the pattern; do not reach for a phone-parsing package, which is
not pinned and is far more machinery than storing what the user typed requires.

Implement `days_of_week` and `channels` as lists in the model and canonical comma strings in the
persistence layer: deduplicate, lower-case, and sort into calendar order before the join. Put the
reason in the comment — Phase 4's matcher, the D-93b dedupe index and any future grouping all read
that one string, and an input-order-dependent representation makes two identical watches look
different to all three. Reject an empty list explicitly rather than treating it as "every day"; the
message tells the caller to omit the field.

Extend `tests/unit/factories.py` with a `watch_create_payload(**overrides)` builder returning a valid
baseline payload, so every rejection test differs from the accepted baseline by exactly one field and
a reader can see which rule is under test.

Write `tests/unit/test_watch_models.py` covering every bullet in `<behavior>`. Drive the accept and
reject matrices from parametrised tables so the count of asserted rules is visible at a glance, and
assert on the message content, not merely on the fact that a validation error was raised. Include the
E.164 boundary table as its own parametrised case, both error-location shapes, and the frozen-clock
case pinned at the exact instant research reproduced — name that test for the behaviour it protects,
because a test that only ever runs in the morning would pass forever without it.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_watch_models.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_watch_models.py -q -W error::RuntimeWarning` exits 0.
    - `uv run pytest tests/unit/test_watch_models.py -q --collect-only 2>/dev/null | tail -1` reports at least `30` collected tests.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run python -c "from services.api.schemas import WatchCreate; import json; print(WatchCreate.model_config.get('extra'))"` prints `forbid`.
    - `grep -c 'SERVICE_TZ' services/api/schemas.py` prints at least `1`.
    - `uv run python -c "from services.api.watch_service import canonical_days as c; print(c(['Sat','fri','FRI','mon']))"` prints `mon,fri,sat`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Every WATCH-02 rule is enforced and named in a failing message, both sides of every boundary are asserted, a New Yorker can create a watch for tonight at 21:30, and two logically identical watches always produce one stored string.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Per-user idempotency — the partial unique index migration, the duplicate 200, and the concurrent-duplicate path</name>
  <files>migrations/versions/00NN_watch_dedupe_partial_unique.py, services/api/watch_service.py, services/api/routers/watches.py, tests/integration/test_watch_dedupe.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-93b (the nine identity columns, the status restriction, and the "resolve the number at execution time" allowance)
    - .planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md §"`migrations/versions/00XX_*.py`" (the header, the revision chain and the refuse-rather-than-destroy pre-flight guard)
    - migrations/versions/0008_add_event_id_to_availability_events.py (the exact guard idiom, the docstring convention and the no-autogenerate rule)
    - migrations/versions/0004_create_watchlist_entries.py (the column types the index expression must coalesce — the time bounds are `Time`, the day and seat filters are `Text`)
    - services/api/watch_service.py and services/api/routers/watches.py as written in Tasks 1-2
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Anti-Patterns to Avoid" (naming `index_elements`, and why a `SELECT` before an `INSERT` is the wrong shape)
  </read_first>
  <behavior>
    - `alembic upgrade head` on a fresh database reaches the new revision and creates a partial unique index over the nine identity columns restricted to the active and paused statuses.
    - The migration refuses to run, naming the offending rows, when the table already holds duplicate active watches.
    - `alembic downgrade` of one step removes the index and leaves every other object untouched.
    - A second identical create for the same email returns 200, the same watch id, and a newly minted token; the table holds one matching row.
    - A create that differs in exactly one identity column returns 201 and a new row.
    - Two identical creates for a watch whose stored `days_of_week` differ only by input ORDER collapse to one row, because the string was canonicalised before insert.
    - Deleting a watch and re-creating the same one returns 201 and a new row, because the index does not cover the deleted status.
    - Two concurrent identical creates yield exactly one row; both callers receive a success status and the same watch id, and neither receives a 500.
  </behavior>
  <action>
Write the migration. Resolve its identity at execution time rather than hard-coding D-93b's literal
numbers: run the alembic head query, set `down_revision` to the current head, and take the next free
zero-padded number as this revision's id — D-93b's "0012 on 0011" was written against a chain that
assumed Phase 6 had already landed, and D-93b itself defers the numbering. Follow the 0008 header and
docstring convention: a title line naming the revision and the owning decision id, then a numbered
list of what this migration corrects.

The index covers `user_id`, `restaurant_id`, `party_size`, `date_from`, `date_to`, the two time
bounds coalesced to a start-of-day and an end-of-day time literal cast to the column's type, and the
day and seat filters coalesced to the empty string, restricted to rows whose status is active or
paused. Write it as a raw index expression rather than through the autogenerator, which the repo bans
for this schema. Add the pre-flight guard in the 0008 shape: count the groups that would violate the
new index before creating it and, if any exist, raise a message naming the count, one example group
and the remediation, refusing to run rather than failing halfway. The downgrade drops only the index.

Change the create path to be idempotent (D-93b). Insert with a conflict target naming the new index
by name — never an unnamed conflict target, which would swallow the email uniqueness violation as
well. On conflict, look the existing row up by the same nine identity values and return it with a
`200` and a freshly minted token, so the client always leaves holding a current-version credential.
Add a comment stating why the status is not part of the returned decision: a paused duplicate is
still the same watch, and returning it lets the manage page resume it rather than accumulating a
second row.

Handle the concurrent case explicitly. Catch the integrity error by its constraint name, re-read the
existing row, and return the same `200` path; a bare catch would also absorb the foreign-key and
email violations this code must not hide. Put the race in the comment: two identical requests can
both pass any pre-check and only the index can decide, which is why there is no `SELECT` before the
`INSERT`.

Write `tests/integration/test_watch_dedupe.py` covering every `<behavior>` bullet. For the concurrent
case, issue the two requests with `asyncio.gather` against the `api_app` fixture and assert on the
row count and on both responses. For the ordering case, submit the same day set in two different
input orders. For the delete-then-recreate case, use a direct status update to the deleted state so
this module does not depend on the delete route 05-04 introduces, and note that in a comment.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_watch_dedupe.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_watch_dedupe.py -q -p no:cacheprovider` exits 0.
    - `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
    - `ls migrations/versions/ | grep -c 'watch_dedupe'` prints `1`.
    - `uv run python -c "import glob; s=open(glob.glob('migrations/versions/*watch_dedupe*.py')[0]).read(); print('status' in s and 'user_id' in s and 'party_size' in s)"` prints `True`.
    - `uv run python -c "import re,glob; p=glob.glob('migrations/versions/*watch_dedupe*.py')[0]; s=open(p).read(); print(bool(re.search(r'down_revision\s*=\s*\"0\d+\"', s)))"` prints `True`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A double-clicked create returns the watch that already exists instead of a second row, a concurrent pair collapses to one row without a 500, and a deleted watch can be re-created — all decided by one partial unique index the database enforces rather than by a check the application could race.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (05-02 slice)

**New modules:** `services/api/schemas.py`, `services/api/watch_service.py`,
`services/api/routers/watches.py`, `shared/watch_counts.py`.

**Modified modules:** `services/api/app.py`, `services/api/config.py`, `tests/unit/factories.py`.

**HTTP routes:** `POST /watches` — `201` on create, `200` on an idempotent duplicate, `404` for an
unknown slug, `422` for any validation failure.

**Response shape:** `{watch: WatchOut, management_url: str, token: str, sources: [RestaurantSource]}`.

**New symbols — `services/api/schemas.py`:** `WatchCreate`, `WatchOut`, `WatchCreateResponse`,
`RestaurantSource`, `PushSubscriptionIn`, `NormalizedEmail`, `DAYS_OF_WEEK`, `CHANNELS`,
`E164_PATTERN`, `MAX_WATCH_WINDOW_DAYS`.

**New symbols — `services/api/watch_service.py`:** `upsert_user`, `resolve_restaurant`, `bind_target`,
`create_watch`, `canonical_days`, `canonical_channels`.

**New symbols — `shared/watch_counts.py`:** `recount`.

**Migration:** `migrations/versions/00NN_watch_dedupe_partial_unique.py` — a partial unique index over
nine identity columns of `watchlist_entries`, restricted to the active and paused statuses. Revision
id and `down_revision` resolved from the live head at execution time (D-93b).

**Redis keys written for the first time by the API:** the `watch:count` HASH, one field per source row
of a slug, via `watch_count_field(source, platform_id)`.

**Metrics incremented:** `watch_create_total{result}`, `watch_count_recount_failures_total`.

**Cross-phase amendment recorded:** Phase 4's `match_watches` fan-out joins by `restaurants.id`; a
watch bound to the OpenTable row must also match events from the Resy sibling, so the join is extended
to slug equality and the change is documented in the notifier README (D-93).
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| anonymous internet -> `POST /watches` | The only unauthenticated write in the system; every field is attacker-controlled |
| API -> `users.email` | An address the submitter has not proven they own |
| API -> Redis `watch:count` | A contract whose reader (the Phase 3 poller) trusts whatever is written |
| API -> the email provider | An outbound side effect triggered by an anonymous request |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-05-09 | Spoofing | a watch created for an address the submitter does not own | medium | accept | Deliberate per D-90: no account, no password. The management link goes to the real owner, who can delete the watch; the token, not the address, authorises every later mutation |
| T-05-10 | Tampering | a forged or mis-minted management token granting another user's watches | critical | mitigate | The token is minted server-side from the id the upsert returned, signed with the full HMAC, purpose-scoped, and never stored or echoed into a log |
| T-05-11 | Information Disclosure | a phone number or a management token in a log line or a response body | high | mitigate | Responses expose a masked phone only; the token appears once, in the create response; `redact_path` and the extended secret-key set cover the log side |
| T-05-12 | Denial of Service | unbounded watch creation filling `watchlist_entries` | high | mitigate | The D-93b partial unique index makes repeated identical creates a no-op, and 05-03 adds the per-IP 60/min cap that is WATCH-06 |
| T-05-13 | Denial of Service | the poller pinned to the fastest tier for a restaurant with no watches | medium | mitigate | The outer-join recount emits a field for every source row including the zero one; the zero-sibling case is an integration assertion |
| T-05-14 | Tampering | an unnamed upsert conflict target swallowing a violation this code must not tolerate | high | mitigate | Every upsert and every conflict target is named; the reproduced vanishing-row case is cited in the code comment |
| T-05-15 | Denial of Service | an anonymous request driving an outbound email send | medium | mitigate | Best-effort, one attempt, never retried inline; the rate limit added in 05-03 bounds the send rate; the provider's dry-run mode is the default outside production |
| T-05-16 | Information Disclosure | a database error message echoing bound parameters (the encrypted phone, the email) into the log | high | mitigate | `ErrorBoundary` plus `safe_error` from 05-01 strip the SQL detail and the parameter list before any field is written |
| T-05-SC | Tampering | package-manager installs | high | mitigate | Zero packages added; no phone-parsing or email-validation dependency is introduced, and the async-only gate from 05-01 covers the new modules |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run alembic upgrade head` reaches the new revision on a fresh container and `uv run alembic downgrade -1` reverses it.
</verification>

<success_criteria>
- An anonymous caller can create a watch and receives a management URL whose token verifies back to the user the upsert created.
- One slug resolves to every source row that shares it, the watch binds to the OpenTable row when there is one, and the response says which sources exist.
- Every WATCH-02 rule is enforced, both sides of every boundary are asserted, and "today" is a New York date.
- A repeated identical create returns the existing watch rather than a second row, including under a concurrent pair.
- The `watch:count` hash carries a field for every source row of the slug, zero-watch siblings included, and a Redis outage cannot fail a committed create.
</success_criteria>

<output>
Create `.planning/phases/05-api-watchlist-crud-sse/05-02-SUMMARY.md` when done
</output>
