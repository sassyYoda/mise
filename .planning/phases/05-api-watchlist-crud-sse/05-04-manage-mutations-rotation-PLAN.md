---
phase: 05-api-watchlist-crud-sse
plan: 04
type: execute
wave: 4
depends_on: [05-03]
files_modified:
  - services/api/routers/manage.py
  - services/api/routers/watches.py
  - services/api/schemas.py
  - services/api/watch_service.py
  - services/api/config.py
  - services/api/app.py
  - scripts/rotate_hmac_secret.py
  - tests/unit/test_watch_update_model.py
  - tests/unit/test_token_rotation.py
  - tests/unit/test_rotate_script.py
  - tests/integration/test_manage_route.py
  - tests/integration/test_watch_lifecycle.py
autonomous: true
requirements: [WATCH-03, WATCH-04, WATCH-06]

estimate:
  tokens: 70000
  raw_tokens: 70000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`GET /api/manage/{token}` accepts the management token as a PATH segment, verifies it with the manage purpose expected, returns the user's active and paused watches with each watch's last 20 `notification_log` rows including `slot_still_available`, and includes a FRESHLY minted current-version token so a client holding an older-version credential migrates naturally on every visit (D-91, D-92, D-95)."
    - "`GET /watches` returns the same list for an `Authorization: Bearer` caller; `PATCH /watches/{id}` edits party size, both date bounds, both time bounds, the day filter, the seat filter, the channels and the phone, and flips status between paused and active; `DELETE /watches/{id}` is a SOFT delete setting the status to deleted and retaining the row for the notification-log foreign key (D-95, Phase 4 D-89, WATCH-04)."
    - "Every management mutation is user-scoped inside the SQL predicate — an update or delete matches on the id AND the owning user AND a non-deleted status, returning the affected id — so another user's watch is a `404`, never a `403`, and the answer costs one round trip with no separate existence query and no timing oracle (D-95, research Pattern 5)."
    - "PROBE WATCH-04/idempotency: a repeated `DELETE` of the same watch returns `404` on the second call because the predicate excludes the deleted status; pausing an already-paused watch returns `200` and changes nothing but the updated timestamp; an empty `PATCH` body is rejected rather than silently succeeding."
    - "PROBE WATCH-04/concurrency: a `PATCH` and a `DELETE` issued concurrently for one watch leave the row in exactly one of the two terminal states and the loser receives a `404`; because each mutation is one conditional statement, no partially applied edit can survive and no lost update can occur."
    - "`WatchUpdate` distinguishes an OMITTED field (leave unchanged) from an explicit null (clear the filter) using the set-fields introspection pydantic provides, so a `PATCH` that omits the day filter cannot silently erase it — the collapse of absent and null is research Pitfall 12 and it is the difference between editing a watch and quietly widening it (D-95)."
    - "Every management mutation recounts the `watch:count` HASH for the affected slug through `shared/watch_counts.py :: recount`, inline and best-effort, so pausing the last active watch on a restaurant drops it out of the fastest polling tier within the request (D-95, D-95a)."
    - "PROBE WATCH-03/unclassified — flagged assumption: the management token IS the credential, so a leaked management URL grants full control of that user's watches until the token expires. Three mitigations are in place and their residual risk is documented rather than denied: the Bearer form is preferred for every mutation so the path form appears once per session, every successful call re-mints a current-version token so a captured one decays, and the 30-day expiry bounds the worst case. Cloud Run's own request log records the raw path regardless of our redaction, which is why `docs/api.md` states this rather than implying the token is secret from the infrastructure (D-91, D-92, research Pitfall 5)."
    - "Rotation is proven end to end with `freezegun` as a context manager inside async tests: a token signed under version N−1 verifies at the cutover instant, still verifies at the last second of the grace window, and is REJECTED at the first instant of the cutoff — while the current version verifies throughout. This is ROADMAP SC2's dry-run, made executable (D-92, WATCH-03)."
    - "`scripts/rotate_hmac_secret.py --dry-run` prints the env delta and nothing else: the new token version, the NAME of the new secret variable, the computed grace date seven days out, and the date after which the previous secret may be deleted. It prints no key material, writes no file, and typechecks under the repo's strict settings because `scripts/` is in the lint target (D-92)."
    - "A token whose purpose is not the manage purpose is rejected by both the path form and the Bearer form before any database work happens; a token whose version is neither the current nor the previous one is rejected outright rather than being tried against every configured secret (D-91, D-92, research §Tokens rules 2 and 4)."
    - "Tokens never appear in a log line: the request logger renders the route template for the path form and drops the query string entirely, and no handler in this plan logs the token, the management URL or the authorization header (D-95a, D-97)."
  artifacts:
    - services/api/routers/manage.py
    - scripts/rotate_hmac_secret.py
    - tests/unit/test_watch_update_model.py
    - tests/unit/test_token_rotation.py
    - tests/unit/test_rotate_script.py
    - tests/integration/test_manage_route.py
    - tests/integration/test_watch_lifecycle.py
  key_links:
    - "`GET /api/manage/{token}` -> the fresh token in its response -> the client's next request. This is the whole rotation migration path: a user whose emailed link was signed under the previous version silently upgrades on their first visit, which is what makes a seven-day grace window sufficient (D-92)."
    - "the user-scoped predicate -> the 404 semantics -> the absence of an enumeration oracle. Splitting it into a `SELECT` then an `UPDATE` would reintroduce both a second round trip and a time-of-check window (research Pattern 5)."
    - "`recount(slug)` on every mutation -> `watch:count` -> the poller's cadence. Pause is the mutation that matters most here: a paused watch must stop counting, or a restaurant nobody is watching keeps its 60-second cadence and its share of the Resy rate budget (D-58, D-95)."
    - "`WatchUpdate`'s set-fields introspection -> the persisted comma strings -> Phase 4's matcher. An omitted day filter that becomes a cleared one widens the watch and produces notifications the user did not ask for (Pitfall 12)."
  prohibitions:
    - "MUST NOT return `403` for a watch belonging to another user; the answer is `404` and it comes from the SQL predicate, not from a comparison after a read."
    - "MUST NOT perform a `SELECT` to check ownership before an `UPDATE` or `DELETE`."
    - "MUST NOT hard-delete a `watchlist_entries` row; the notification log's foreign key depends on it and the delete is a status change."
    - "MUST NOT store, log or echo a management token anywhere other than the response body that mints it; `watchlist_entries.management_token` stays NULL."
    - "MUST NOT accept a token without checking its purpose and its version, and MUST NOT try a token against every configured secret to see which one fits."
    - "MUST NOT treat an omitted `PATCH` field as an instruction to clear the stored value."
    - "MUST NOT print, log or write key material from the rotation script, and MUST NOT have the script mutate the environment, a file, or a secret store."
---

<objective>
Give a user who never created an account full control of their watches: a path-token hydration route
for the Phase 6 manage page, Bearer-authorised list, edit, pause, resume and soft delete, the
`watch:count` recount that makes a pause actually slow the poller down, and the monthly HMAC rotation
with its seven-day grace window proven as an executable dry-run.

Purpose: this is the only place in the system where one user could be handed another's data, and the
mechanism that prevents it is a single SQL predicate rather than a check the code could forget. The
same is true of rotation: SC2 is not "rotation is possible" but "a token signed under the previous
version verifies through the grace window and fails after it", which is a claim only a frozen clock
can settle.
Output: the manage router, the three management methods on the watches router, a `PATCH` model that
can tell absent from null, the rotation script, and five test modules across both tiers.
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
@.planning/phases/05-api-watchlist-crud-sse/05-03-SUMMARY.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — GET /api/manage/{token} hydrates a user's watches and hands back a fresh token</name>
  <files>services/api/routers/manage.py, services/api/schemas.py, services/api/watch_service.py, services/api/app.py, tests/integration/test_manage_route.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-91, §D-92, §D-95
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Tokens and Rotation (executed)" — the five verification rules and the claim-name reconciliation the planner must honour (the wire names are Phase 4's; D-91's names are the documentation of what they mean)
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Common Pitfalls" Pitfall 5 (the token in the infrastructure's own request log and its three mitigations)
    - shared/db.py lines 91-110 (`NotificationLog` columns, especially `slot_still_available`, `status`, `channel` and the timestamps)
    - services/api/deps.py as written in 05-03 (`bearer_user` and the one-401-for-every-failure rule this route mirrors for the path form)
    - services/api/schemas.py and services/api/watch_service.py as written in 05-02 and 05-03
    - services/api/middleware.py as written in 05-01 (`redact_path` — the manage prefix is already in its sensitive set)
  </read_first>
  <behavior>
    - A valid manage token in the path returns 200 with the user's active and paused watches and a token field.
    - The returned token differs from the presented one, verifies with the manage purpose, carries the same user id, and is signed under the current version.
    - Deleted watches are absent from the list.
    - Each watch carries its most recent notification entries, capped at twenty, newest first, each exposing the channel, the status, the send timestamp and the still-available flag.
    - A watch with no notifications carries an empty history rather than being omitted.
    - A token with a click or unsubscribe purpose returns 401; so do a malformed token, a token signed with a different secret, and an expired token — with identical bodies.
    - The route performs no database work at all when the token fails.
    - No log record emitted during the request contains the token characters; the logged path ends in the redaction placeholder.
    - A user with no watches returns 200 with an empty list and a fresh token.
  </behavior>
  <action>
Extend `services/api/schemas.py` with the response models this route returns: a watch list wrapper
carrying the watches and the freshly minted token, a notification-history item exposing only the
channel, the status, the send timestamp and the still-available flag, and the watch list item reusing
the existing watch output model plus its history. The history item deliberately omits the provider id
and the error text — those are operator data, and this endpoint is reachable with nothing but a
token.

Extend `services/api/watch_service.py` with `list_watches(session, user_id)`. One statement returns
the user's non-deleted watches ordered deterministically, and a second returns their notification
history in one query rather than one per watch — select the history rows for the whole watch set and
group them in Python, with a comment stating that a per-watch query here is an N+1 that grows with
the user's watch count on a page the Phase 6 UI loads on every visit. Cap each watch's history at
twenty using a window function or by slicing after a bounded fetch; whichever is used, the cap is
applied in SQL or immediately after, never by fetching the whole log.

Write `services/api/routers/manage.py` with `GET /api/manage/{token}`. It verifies the path token
through the same token module and expected purpose `bearer_user` uses, converting every failure into
one indistinguishable 401 whose log line records the exception class only; it then loads the list and
mints a fresh current-version token for the response. Put the rotation intent in a comment: this
response is the migration path, because a user whose emailed link was signed under the previous
version silently upgrades on their first visit, which is what makes a bounded grace window sufficient
rather than a permanent dual-verification. Add a second comment recording Pitfall 5's residual risk —
our own logs redact the token, and the platform's request log does not — and note that `docs/api.md`
must state it rather than implying otherwise. Register the router in `services/api/app.py`.

Write `tests/integration/test_manage_route.py` covering every `<behavior>` bullet. Build the fixture
data through the existing create route so the test exercises the same shapes production writes, then
assert the list, the history cap and ordering, the empty-history and empty-list cases, the four token
failure cases with identical bodies, and the no-database-work claim by asserting a failure response
when the database is unreachable but the token is invalid. Capture logs during a successful request
and assert the token characters appear in none of them. The module docstring names the BC-1 tier it
uses and why.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_manage_route.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_manage_route.py -q -p no:cacheprovider` exits 0.
    - `uv run python -c "from services.api.app import create_app; print('/api/manage/{token}' in {getattr(r,'path','') for r in create_app().routes})"` prints `True`.
    - `uv run python -c "import services.api.watch_service as w; print(callable(w.list_watches))"` prints `True`.
    - `cat services/api/routers/manage.py services/api/watch_service.py | grep -v '^\s*#' | grep -c management_token` prints `0` — with full-line comments stripped, so a comment explaining the rule cannot break its own gate; the column is never read or written by this phase.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A user with nothing but a link sees every watch they own, with its notification history, and leaves holding a current-version credential — while a token of the wrong purpose, version or signature gets one indistinguishable refusal and touches no data.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: List, edit, pause, resume and soft delete — user-scoped in the predicate, with a PATCH model that can tell absent from null</name>
  <files>services/api/routers/watches.py, services/api/schemas.py, services/api/watch_service.py, tests/unit/test_watch_update_model.py, tests/integration/test_watch_lifecycle.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-95 (the editable field list and the soft-delete rule) and §D-95a
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Architecture Patterns" Pattern 5 (the executed user-scoped update returning an empty list for the wrong user) and §"Soft delete + user-scoped 404"
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Common Pitfalls" Pitfall 12 (absent vs null vs empty on the day filter) and Pitfall 11 (recount is best effort)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-89 (why the delete is soft: the notification-log foreign key)
    - services/api/schemas.py as written in 05-02 and 05-03 (the create model's validators, which the update model must reuse rather than restate)
    - services/api/watch_service.py as written in 05-02 and 05-03 (`canonical_days`, `canonical_channels`, the phone half of the upsert)
    - shared/watch_counts.py as written in 05-02 (`recount`)
  </read_first>
  <behavior>
    - A Bearer list request returns the caller's active and paused watches and omits deleted ones.
    - A patch changing the party size to a valid value returns 200 and the updated watch; a patch to an invalid value returns 422 with the same message the create model produces.
    - A patch that omits the day filter leaves the stored value unchanged; a patch that sets it to null clears it; a patch that sets it to an empty list is rejected.
    - The same three-way behaviour holds for the time window pair, the seat filter and the phone.
    - A patch setting the status to paused, then a patch setting it to active, both return 200 and the intermediate row is paused.
    - A patch with no fields at all is rejected.
    - A patch or delete for a watch id belonging to another user returns 404; the response is byte-identical to the response for an id that does not exist at all.
    - A delete returns 200 and the row survives with the deleted status; a second delete of the same id returns 404.
    - Concurrent patch and delete for one watch leave the row in exactly one terminal state and one caller receives 404.
    - Pausing the only active watch on a restaurant drops that restaurant's `watch:count` field to zero for every source row of the slug.
    - A patch whose date range or time window violates a create-time rule is rejected by the same rule, evaluated against the merged result rather than against the submitted fragment.
  </behavior>
  <action>
Add `WatchUpdate` to `services/api/schemas.py`. Every field is optional in the wire sense but the
model must distinguish three states — omitted, explicitly null, and a value — which pydantic's
default handling collapses. Use the model's set-fields introspection to detect presence, and document
the contract in the class docstring: omission means unchanged, an explicit null clears an optional
filter, and an empty list is rejected the same way the create model rejects it. Reject a body with no
fields set. Reuse the create model's validators for the shared rules rather than restating them;
where a rule is cross-field (the date ordering, the window length, the paired time bounds, the
channel-to-credential requirement) it must be evaluated against the MERGED result of the stored row
and the patch, not against the fragment, so a patch that moves only the end date cannot produce an
inverted range. Put that in the comment — validating the fragment alone is the shape that lets an
invalid watch exist.

Add `update_watch` and `soft_delete_watch` to `services/api/watch_service.py`. Both are a single
conditional statement matching on the id, the owning user and a non-deleted status, returning the
affected id; an empty result is the 404. Put the reproduced rationale in the comment: an empty result
means "does not exist or is not yours", which is exactly the semantics required, and it is produced
without a separate read that would cost a round trip and open a time-of-check window. The soft delete
sets the status rather than removing the row, because the notification log's foreign key points at it
and the audit trail is the reason the row is retained.

Add `GET /watches`, `PATCH /watches/{id}` and `DELETE /watches/{id}` to
`services/api/routers/watches.py`, all three depending on `bearer_user`. After every successful
mutation, call `recount` for the affected slug inline and best-effort, exactly as the create path
does. State in a comment why pause is the mutation that matters most: a paused watch that keeps
counting leaves a restaurant nobody is watching on the fastest cadence, consuming its share of the
Resy request budget for nothing.

Write `tests/unit/test_watch_update_model.py` covering the three-way field semantics for each optional
field, the empty-body rejection, the empty-list rejection, and the merged-validation cases. Write
`tests/integration/test_watch_lifecycle.py` covering the full sequence — create, list, patch, pause,
resume, delete, re-delete — plus the cross-user 404 with a byte-identical comparison against the
not-found response, the concurrent patch-and-delete case under `asyncio.gather`, and the
pause-drops-the-count assertion read back from the `watch:count` hash for both source rows.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_watch_update_model.py -q -W error::RuntimeWarning &amp;&amp; uv run pytest tests/integration/test_watch_lifecycle.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_watch_update_model.py -q -W error::RuntimeWarning` exits 0.
    - `uv run pytest tests/integration/test_watch_lifecycle.py -q -p no:cacheprovider` exits 0.
    - `uv run python -c "from services.api.app import create_app; print(sorted({(r.path, m) for r in create_app().routes for m in getattr(r,'methods',set()) if getattr(r,'path','').startswith('/watches')}))"` prints entries covering `POST /watches`, `GET /watches`, `PATCH /watches/{watch_id}` and `DELETE /watches/{watch_id}`.
    - `uv run python -c "import services.api.watch_service as w; print(callable(w.update_watch), callable(w.soft_delete_watch))"` prints `True True`.
    - `grep -c 'model_fields_set' services/api/schemas.py` prints at least `1`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A user can list, edit, pause, resume and delete their own watches and no one else's, the boundary is one SQL predicate rather than a check that could be forgotten, an omitted field never erases a filter, and pausing the last watch on a restaurant slows the poller down inside the same request.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The rotation dry-run — a previous-version token through the grace window, and a script that prints an env delta and nothing else</name>
  <files>scripts/rotate_hmac_secret.py, services/api/config.py, tests/unit/test_token_rotation.py, tests/unit/test_rotate_script.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-92 (the variable names, the cutover semantics and the re-mint rule)
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Tokens and Rotation (executed)" — the full dry-run transcript with its four instants, the freezegun-inside-async finding, and the suggested script output
    - .planning/ROADMAP.md Phase 5 Success Criterion 2 (the claim this task makes executable)
    - shared/tokens.py as shipped by 04-01 — `token_version()`, `grace_until()`, the per-version secret lookup and the exception raised for an unknown version
    - .planning/phases/04-notification-pipeline/04-01-shared-token-crypto-kernel-PLAN.md — its grace-window truth and `tests/unit/test_tokens.py`, whose assertions this module must EXTEND rather than duplicate
    - scripts/verify_seed.py (the script register: argument parsing, exit codes, and the fact that `scripts/` is inside the strict typecheck target)
  </read_first>
  <behavior>
    - With the current version at 2 and a grace date seven days out, a token minted under version 1 verifies at the instant of cutover, verifies at the last second of the grace day, and is rejected at the first instant of the day after.
    - The version-2 token verifies at all four instants.
    - A token whose version is neither the current nor the previous one is rejected without any secret lookup for that version.
    - A manage-purpose token presented where a click purpose is expected is rejected, and the reverse also holds.
    - The frozen clock holds across an await inside the async test, so the assertions after a suspension point are still at the frozen instant.
    - The script with the dry-run flag exits 0 and prints exactly four lines: the new version number, the NAME of the new secret variable, the computed grace date, and the date after which the previous secret may be deleted.
    - The script's output contains no value of any secret variable, even when those variables are set in the environment it runs under.
    - The script writes no file and mutates no environment variable; running it twice produces identical output for the same inputs.
    - The script without the dry-run flag refuses to run and explains that applying a rotation is a deployment action, exiting non-zero.
  </behavior>
  <action>
Write `tests/unit/test_token_rotation.py` as the executable form of ROADMAP SC2 (D-92). Use
`freeze_time` as a CONTEXT MANAGER inside the async tests rather than as a decorator, so one test can
walk the four instants research measured and a reader can see the window rather than infer it. Set
the version and both secrets through the environment inside each case, since the token module reads
them lazily by design. Assert the four instants for the previous-version token and the current-version
token, the unknown-version rejection, both directions of the purpose mismatch, and the
frozen-across-await property. Add a module docstring stating that Phase 4's `tests/unit/test_tokens.py`
already pins the token FORMAT and its exception hierarchy; this module pins the ROTATION OPERATION
for the manage purpose, and the two must not duplicate each other's assertions.

Write `scripts/rotate_hmac_secret.py`. It parses a dry-run flag and refuses to do anything without it,
because applying a rotation means changing a secret store and that is a deployment action, not a
script's business. In dry-run it reads the current version from the environment, computes the next
version, and prints four lines: the new version number, the NAME of the variable the new secret must
be placed in, the grace date computed as today plus seven days in the service timezone, and the date
after which the previous version's variable may be deleted. It prints no value from any secret
variable and touches no file. Give it the argument-parsing and exit-code shape `scripts/verify_seed.py`
uses, and remember that this directory is inside the strict typecheck target, so it must typecheck as
strictly as the services do. Add any accessor it needs to `services/api/config.py` only if the token
module does not already expose it — prefer reading through `shared/tokens.py`'s existing accessors so
there is one reader of these variables.

Write `tests/unit/test_rotate_script.py` invoking the script as a subprocess with a populated
environment: assert the exit code, the exact line count, the presence of the variable NAME, the
computed dates, the absence of every secret VALUE in the output, that no file was created, and that a
second invocation produces identical bytes. Assert the non-dry-run refusal separately.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_token_rotation.py tests/unit/test_rotate_script.py -q -W error::RuntimeWarning</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_token_rotation.py tests/unit/test_rotate_script.py -q -W error::RuntimeWarning` exits 0.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `HMAC_TOKEN_VERSION=1 HMAC_MGMT_SECRET_V1=0123456789abcdef0123456789abcdef uv run python scripts/rotate_hmac_secret.py --dry-run | wc -l` prints `4`.
    - `HMAC_TOKEN_VERSION=1 HMAC_MGMT_SECRET_V1=0123456789abcdef0123456789abcdef uv run python scripts/rotate_hmac_secret.py --dry-run | grep -c '0123456789abcdef'` prints `0`.
    - `HMAC_TOKEN_VERSION=1 uv run python scripts/rotate_hmac_secret.py; echo $?` prints a non-zero exit status.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>ROADMAP SC2 is an executable assertion rather than a claim: a previous-version token verifies through the grace window and fails at the cutoff, and the operator's rotation procedure is a four-line env delta that never prints a secret.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (05-04 slice)

**New modules:** `services/api/routers/manage.py`, `scripts/rotate_hmac_secret.py`.

**Modified modules:** `services/api/routers/watches.py`, `services/api/schemas.py`,
`services/api/watch_service.py`, `services/api/config.py`, `services/api/app.py`.

**HTTP routes:** `GET /api/manage/{token}` (200 / 401), `GET /watches` (200, Bearer),
`PATCH /watches/{watch_id}` (200 / 404 / 422, Bearer), `DELETE /watches/{watch_id}` (200 / 404,
Bearer — soft delete).

**Response shapes:** `WatchListResponse {watches: [WatchWithHistory], token: str}`,
`NotificationHistoryItem {channel, status, sent_at, slot_still_available}`.

**New symbols — `services/api/schemas.py`:** `WatchUpdate`, `WatchWithHistory`,
`NotificationHistoryItem`, `WatchListResponse`, `NOTIFICATION_HISTORY_LIMIT`.

**New symbols — `services/api/watch_service.py`:** `list_watches`, `update_watch`,
`soft_delete_watch`.

**New script:** `scripts/rotate_hmac_secret.py --dry-run` — prints the env delta for a rotation.

**Env vars consumed:** `HMAC_TOKEN_VERSION`, `HMAC_MGMT_SECRET_V{n}`, `HMAC_GRACE_UNTIL`,
`PUBLIC_BASE_URL`. Documented in `.env.example` by 05-06.

**Status values written to `watchlist_entries.status`:** `paused`, `active`, `deleted`.

**Redis contract written:** the `watch:count` HASH is recounted after every management mutation.
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| anonymous internet -> `/api/manage/{token}` | A URL in an email is the entire credential; it traverses mailboxes, browser history and platform logs |
| bearer token -> every management mutation | One capability grants full control of one user's watches |
| one user -> another user's watch id | Sequential integer ids make enumeration trivial to attempt |
| operator -> the rotation script | A script that prints secrets is a secret leak with an audit trail |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-05-26 | Information Disclosure | enumerating another user's watches by id | critical | mitigate | Every read and mutation is user-scoped inside the SQL predicate and returns 404; the cross-user response is asserted byte-identical to the not-found response |
| T-05-27 | Elevation of Privilege | a click or unsubscribe token opening a management route | critical | mitigate | Purpose is checked before any database work on both the path form and the Bearer form; both directions of the mismatch are asserted |
| T-05-28 | Spoofing | a forged or replayed management token | critical | mitigate | Full HMAC over the encoded payload with constant-time comparison, version-scoped secret lookup, 30-day expiry, and a fresh token minted on every successful call so a captured one decays |
| T-05-29 | Information Disclosure | the management token recorded by the platform's own request log | high | accept | Unavoidable for a path-form token; mitigated by preferring the Bearer form for every mutation, by re-minting, and by the bounded expiry. Recorded as residual risk in `docs/api.md` rather than denied (Pitfall 5) |
| T-05-30 | Information Disclosure | a 401 that tells the caller whether a token was expired or forged | medium | mitigate | One indistinguishable response and body for every token failure; the shape is logged by exception class only |
| T-05-31 | Tampering | a lost update or a partially applied edit under concurrency | medium | mitigate | Each mutation is one conditional statement; the concurrent patch-and-delete case is asserted to leave exactly one terminal state |
| T-05-32 | Tampering | a `PATCH` that silently widens a watch by clearing an omitted filter | high | mitigate | The update model distinguishes omitted from null through set-fields introspection; all three states are unit-asserted per field |
| T-05-33 | Information Disclosure | the rotation script printing key material | high | mitigate | The script prints variable NAMES and dates only; a test asserts no secret value appears in its output and that it writes nothing |
| T-05-34 | Denial of Service | unbounded notification history on a user with many watches | low | mitigate | The history is capped at twenty rows per watch and fetched in one query for the whole set, not per watch |
| T-05-SC | Tampering | package-manager installs | high | mitigate | Zero packages added; `freezegun` is already pinned as a dev dependency and already used by the repo |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run pytest tests/unit/test_token_rotation.py -q` exits 0 — ROADMAP SC2's dry-run.
</verification>

<success_criteria>
- A user holding only a link can list, edit, pause, resume and delete their own watches, and always leaves with a current-version token.
- Another user's watch is a 404 whose response cannot be distinguished from a non-existent id, decided by the SQL predicate.
- An omitted `PATCH` field never clears a stored filter, and a patch is validated against the merged result.
- Every management mutation recounts `watch:count`, so a pause slows the poller inside the same request.
- A previous-version token verifies through the grace window and fails at the cutoff, proven with a frozen clock.
</success_criteria>

<output>
Create `.planning/phases/05-api-watchlist-crud-sse/05-04-SUMMARY.md` when done
</output>
