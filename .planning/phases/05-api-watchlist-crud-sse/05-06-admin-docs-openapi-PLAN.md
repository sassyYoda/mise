---
phase: 05-api-watchlist-crud-sse
plan: 06
type: execute
wave: 6
depends_on: [05-05]
files_modified:
  - services/api/routers/admin.py
  - services/api/deps.py
  - services/api/schemas.py
  - services/api/config.py
  - services/api/app.py
  - scripts/api_smoke.sh
  - docs/api.md
  - docs/runbooks/sse-cloudrun.md
  - Makefile
  - .env.example
  - README.md
  - tests/unit/test_admin_guard.py
  - tests/unit/test_openapi_snapshot.py
  - tests/unit/fixtures/openapi_routes.txt
  - tests/integration/test_admin.py
  - tests/integration/test_api_smoke_script.py
autonomous: true
requirements: [API-03, API-01]

estimate:
  tokens: 72000
  raw_tokens: 72000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Every `/admin/*` route is guarded by one dependency that returns `404` when the admin credentials are unset — the routes are not merely unusable, they are indistinguishable from routes that do not exist — and `401` with a `WWW-Authenticate: Basic` challenge naming the realm when they are set and the presented credentials are missing or wrong (D-103)."
    - "The credential comparison uses constant-time equality on BOTH the username and the password and combines the two results with a NON-short-circuiting operator, because a short-circuiting combine leaks whether the username matched; the basic-auth extractor is configured not to raise on a missing header, so a missing credential reaches the dependency and is answered with the challenge rather than with the framework's default refusal (D-103, research §HTTP Basic)."
    - "PROBE API-03/unclassified — flagged assumption: `/admin/*` carries no rate limit in this phase. Brute force is bounded only by constant-time comparison, platform per-instance concurrency and credential strength; research raised a per-IP limit on the admin surface and this plan records it as an accepted residual risk to be closed in Phase 7 alongside the deploy hardening, not silently omitted (D-103, research §Security Domain)."
    - "`/admin/restaurants` supports create, read, update and delete over every `restaurants` column; a create seeds the polling schedule entry for the new source-and-platform pair exactly as the seed script does, reusing the shared job-descriptor helper rather than formatting its own string (D-103)."
    - "A delete is refused with `409` while the restaurant still has active watches, and the message names the count; only a restaurant nobody is watching can be removed (D-103)."
    - "`PUT /admin/restaurants/{slug}/tier` writes the tier override hash field for every source row of the slug, and clears it when the tier is null — using the same field helper the count writer uses, with the platform id, never the surrogate row id (D-103, D-95b, Phase 3 D-58)."
    - "`GET /admin/restaurants/{slug}/events` returns the event count for the requested window and the most recent fifty rows across every source row of the slug (D-103)."
    - "`GET /admin/health` reports, in one response: per-topic Kafka lag as the end offsets minus the committed offsets for the state-machine and notifier groups, the last successful poll per source, a database and Redis ping, and the poll success rate for the last hour. The admin client is constructed per request and closed in a `finally` with its start inside the `try` — the placement this repository already fixed once for a connection leak (D-103, research §admin health)."
    - "Every admin mutation is logged with the authenticated admin username, so the audit trail names who changed a restaurant, a tier or a schedule entry (D-103)."
    - "`tests/unit/test_openapi_snapshot.py` pins the SORTED list of `METHOD path` pairs plus the response model names — not the whole document, whose descriptions and schema details would make the snapshot a diff-noise generator — so Phase 6 can generate a client against a contract that cannot change silently (D-104, D-104b)."
    - "`docs/api.md` documents every route in this phase with a runnable curl example, both validation-error shapes (a field-level error keeps its field name; a cross-field error reports the body), the rate-limit headers and the fixed-window burst caveat, the soft-delete semantics, the SSE reconnect and whole-buffer-replay behaviour, the per-process ring's cross-replica caveat, and the residual risk that a management token in a path is recorded by the platform's own request log (D-104, research Pitfalls 3, 5 and §Rate Limiting)."
    - "`scripts/api_smoke.sh` walks the full watch lifecycle against a base URL with curl — create, list through the management token, patch, pause, delete, plus the public reads and a bounded read of the live feed — exits non-zero on the first unexpected status, and is itself exercised by an integration test against the in-process server, so the portfolio artifact is a tested artifact rather than a hopeful one (D-104, CONTEXT §Specifics)."
    - "`make api` runs the server with its own logging configuration disabled so the structlog routing installed in 05-01 is the only log path, and `make api-smoke` runs the smoke script; both appear in the phony target list and carry the help comment the help target greps for (D-97a)."
    - "`.env.example` gains the full Phase-5 block, with the proxy-trust variable carrying the second-to-last-hop assumption and its local default beside it, and the admin password using the existing placeholder style; the admin password is also in the log redaction set (D-96a, D-103)."
    - "`docs/runbooks/sse-cloudrun.md` exists with a pending-human status banner and the exact procedure for the one measurement this phase cannot make locally: the SSE first-event latency through the deployed URL, with the request-timeout setting the stream depends on and the reconnect behaviour to expect (D-99)."
  artifacts:
    - services/api/routers/admin.py
    - scripts/api_smoke.sh
    - docs/api.md
    - docs/runbooks/sse-cloudrun.md
    - tests/unit/test_admin_guard.py
    - tests/unit/test_openapi_snapshot.py
    - tests/unit/fixtures/openapi_routes.txt
    - tests/integration/test_admin.py
    - tests/integration/test_api_smoke_script.py
  key_links:
    - "the admin guard -> every `/admin` route. It is the only thing between an anonymous caller and restaurant CRUD plus the polling schedule; the unset-credentials case returning 404 is what keeps an unconfigured deployment from advertising an admin surface at all."
    - "`PUT /admin/restaurants/{slug}/tier` -> the `tier:override` hash -> the Phase 3 poller's cadence. Same contract, same field helper and same platform id as the watch-count writer; a wrong field here is an override that silently does nothing (D-58, D-95b)."
    - "admin create -> the polling schedule entry -> the poller's next cycle. A restaurant created without its schedule entry is a row that is never polled, which looks like a scraping failure rather than a missing key."
    - "the OpenAPI route snapshot -> Phase 6's generated client. The snapshot is the contract; a route renamed without updating it is caught here rather than in the frontend (D-104b)."
    - "`docs/api.md` -> the phase's 'testable end-to-end via curl' criterion -> the Phase 7 README link. The smoke script is the executable half of the same claim."
  prohibitions:
    - "MUST NOT compare admin credentials with a plain equality operator, and MUST NOT combine the two comparison results with a short-circuiting operator."
    - "MUST NOT expose an admin route when the admin credentials are unset; the answer is 404, not an open route and not a 401."
    - "MUST NOT hard-delete a restaurant that still has active watches; the answer is 409 with the count."
    - "MUST NOT format the polling job descriptor or either hash field by hand; both come from the shared helpers, with the platform id."
    - "MUST NOT leave an admin client open on an error path; it is started inside the try and closed in the finally."
    - "MUST NOT log an admin password, a management token, a phone number or a secret value in an admin route, an example in the documentation, or the smoke script's output."
    - "MUST NOT pin the whole OpenAPI document in the snapshot; the snapshot is the sorted method-and-path list plus the response model names."
    - "MUST NOT place real credentials in `.env.example`; every value is a placeholder in the existing style."
---

<objective>
Close the phase with the operator surface and the evidence: HTTP-Basic admin routes for restaurant
CRUD, polling-tier override, per-restaurant event volume and a system-health summary; a route-list
snapshot Phase 6 can build a client against; a curl walkthrough that is executed in CI rather than
merely written; the Make targets and environment block; and the one pending-human runbook for the
measurement that needs a deployed URL.

Purpose: ROADMAP SC5 is "admin routes expose restaurant CRUD, polling-tier override and per-restaurant
event volume, and public metrics are accessible without authentication", and the phase's own framing
is "testable end-to-end via curl before the frontend exists". Both are claims about evidence, so the
documentation ships with a script that proves it and a snapshot that keeps the contract from drifting
under Phase 6's feet.
Output: the admin router and its guard, the smoke script, the API reference, the route snapshot, the
Make and environment additions, the README section, and the Cloud Run SSE runbook.
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
@.planning/phases/05-api-watchlist-crud-sse/05-05-SUMMARY.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — restaurant CRUD behind HTTP Basic, seeding the polling schedule and refusing a delete that would orphan watches</name>
  <files>services/api/deps.py, services/api/routers/admin.py, services/api/schemas.py, services/api/config.py, services/api/app.py, tests/unit/test_admin_guard.py, tests/integration/test_admin.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-103
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"HTTP Basic (D-103)" — the executed 401/404/200 transcript, the non-short-circuiting combine, and the reason the extractor must not raise on a missing header
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Security Domain" (the admin brute-force row this plan accepts and records)
    - .planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md §"`services/api/routers/admin.py`" — the seed script's imports, the shared job-descriptor helper, and the optional-argument typing note
    - scripts/seed_restaurants.py lines 1-60 (the create-and-seed shape this route reuses, including the schedule key and the descriptor helper)
    - shared/redis_keys.py (the schedule key, the job descriptor helper, and the tier-override field helper)
    - services/api/deps.py as written in 05-01 and 05-03 (the provider style and the one-indistinguishable-401 rule)
    - services/api/schemas.py as written in the earlier plans (the merged restaurant models the admin views reuse)
  </read_first>
  <behavior>
    - With the admin credentials unset, every admin route returns 404 with no authentication challenge.
    - With them set and no credentials presented, an admin route returns 401 and a basic challenge naming the realm.
    - A wrong password returns 401; a wrong username returns 401; the two responses are identical.
    - Correct credentials return 200 and the handler runs.
    - A create inserts the restaurant and adds a polling schedule entry for its source and platform pair; the entry's member string equals what the shared descriptor helper produces.
    - A create with a source and platform pair that already exists is refused rather than duplicating.
    - A read returns the restaurant's full column set; an unknown id returns 404.
    - An update changes only the submitted columns and returns the updated row.
    - A delete of a restaurant with an active watch returns 409 and a message naming the count; the row survives.
    - A delete of a restaurant with no active watches succeeds and removes its schedule entry.
    - Every mutation emits a log record carrying the authenticated admin username.
  </behavior>
  <action>
Add the admin guard to `services/api/deps.py`. Read both credentials through the config accessors so a
test can set them per case, and when either is unset raise a not-found immediately — the routes must
be indistinguishable from routes that do not exist, which is what keeps an unconfigured deployment
from advertising an admin surface. Configure the basic-auth extractor so a MISSING header reaches the
dependency rather than being refused by the framework, which lets the response carry the
authenticate challenge and the realm. Compare both fields with constant-time equality and combine the
two booleans with a non-short-circuiting operator; the comment states why, namely that a
short-circuiting combine returns early when the username differs and leaks whether the username
matched. Return the authenticated username so handlers can put it in their audit log lines.

Write `services/api/routers/admin.py` with the restaurant CRUD half of D-103, every route depending on
the guard. The create accepts the full column set, inserts with a named conflict target on the
existing source-and-platform uniqueness, and seeds the polling schedule entry through the shared
descriptor helper and the shared schedule key — never a hand-formatted string, which is how the
poller and the API come to disagree about a job's name. Take the Redis client from the lifespan
provider rather than constructing one, unlike the standalone seed script. The delete first counts
active watches for that restaurant and refuses with a conflict status naming the count when there are
any, and otherwise deletes the row and removes its schedule entry. The read and update cover the
remaining verbs. Every mutating handler logs one record naming the admin username, the action and the
affected identifier. Follow the optional-argument typing note from the patterns map — explicit
none-checks rather than truthiness fallbacks, because the strict checker types the latter as optional
and the same rule bites on every default in this router. Register the router in
`services/api/app.py`.

Add the admin request and response models to `services/api/schemas.py`, keeping the admin views
separate from the public restaurant models: the admin view exposes every column, the public one does
not, and merging them is how an internal field ends up on a public route.

Write `tests/unit/test_admin_guard.py` covering the unset-credentials 404, the missing-credential 401
with its challenge header, the wrong-username and wrong-password cases and their identical responses,
and the success case. Write the CRUD half of `tests/integration/test_admin.py` covering every
remaining `<behavior>` bullet, reading the schedule entry back from Redis to prove the seed, and
capturing logs to prove the audit line carries the username.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_admin_guard.py -q -W error::RuntimeWarning &amp;&amp; uv run pytest tests/integration/test_admin.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_admin_guard.py -q -W error::RuntimeWarning` exits 0.
    - `uv run pytest tests/integration/test_admin.py -q -p no:cacheprovider` exits 0.
    - `uv run python -c "from services.api.app import create_app; print(sorted({(r.path, m) for r in create_app().routes for m in getattr(r,'methods',set()) if getattr(r,'path','').startswith('/admin/restaurants')}))"` prints entries covering `GET`, `POST`, `PATCH` and `DELETE`.
    - `cat services/api/routers/admin.py services/api/deps.py | grep -c compare_digest` prints at least `2`.
    - `uv run python -c "import inspect, services.api.deps as d; src=inspect.getsource(d); print('404' in src or 'HTTP_404' in src)"` prints `True`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>An operator with credentials can create, read, update and delete restaurants and the poller picks the new one up on its next cycle; an operator without credentials cannot tell the admin surface exists; and a restaurant somebody is watching cannot be deleted out from under them.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Polling-tier override, per-restaurant event volume, and the system-health summary</name>
  <files>services/api/routers/admin.py, services/api/schemas.py, services/api/config.py, tests/integration/test_admin.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-103 (the tier, events and health routes) and §D-95b (the platform-id field rule)
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"`/admin/health` Kafka lag (D-103)" — the admin-client construction rule and the lag arithmetic
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Redis side of the same contract" (the tier-override hash read shape)
    - services/state_machine/main.py lines 60-90 (the admin-client usage this route follows exactly, including the start-inside-try and close-in-finally placement)
    - shared/redis_keys.py (`tier_override_field`, the tier arithmetic constants, and the count hash)
    - shared/db.py lines 110-155 (`AvailabilityEvent` and `PollLog`, for the window counts and the last-successful-poll query)
    - services/api/routers/admin.py as written in Task 1
  </read_first>
  <behavior>
    - Setting a tier writes the override field for every source row of the slug; the stored value is the requested tier.
    - Setting the tier to null clears the field for every source row and leaves other slugs untouched.
    - An out-of-range tier is rejected with 422; an unknown slug returns 404.
    - The written field is built from the source and the platform id, and for a source row whose surrogate id differs from its platform id the field contains the platform id.
    - The events route returns the count for the requested window and at most fifty recent rows, aggregated across every source row of the slug.
    - An unsupported window value is rejected with 422 rather than silently defaulting.
    - The health route returns per-group consumer lag, the last successful poll per source, a database and Redis status, and the last hour's poll success rate.
    - The health route closes its admin client even when the broker is unreachable, and reports the broker section as unavailable rather than failing the whole response.
    - Every tier mutation emits a log record carrying the admin username, the slug and the new value.
  </behavior>
  <action>
Add the tier route to `services/api/routers/admin.py`. It resolves the slug to its source rows, and
for each row writes or clears the override hash field built through the shared field helper with the
row's platform id — the same rule the count writer follows, and the comment says so, because a field
built from the surrogate row id is an override that silently does nothing. A null tier clears; a tier
outside the valid set is a validation failure at the model boundary, not a runtime check. Log the
mutation with the admin username, the slug and the value.

Add the events route: the count over the requested window and the most recent rows capped at fifty,
aggregated across every source row of the slug. Accept only the two documented window values as an
enumerated query parameter so an unsupported value is a validation failure rather than a silent
default — a health view that silently answers a different question than the one asked is worse than
one that refuses.

Add the health route. Build the Kafka admin client per request and close it in a `finally` with its
start INSIDE the try, which is the placement this repository already corrected once for a connection
leak; a long-lived admin client would be one more thing to tear down in the lifespan for a route with
no latency budget. Lag is the end offsets minus the committed offsets for the two consumer groups.
Add the last successful poll per source and the last hour's success rate from the poll log, and reuse
the readiness checks for the database and Redis rather than writing second versions of them. Each
section is independently fallible: a broker that cannot be reached reports that section as
unavailable with the scrubbed reason and the rest of the response still renders, because a health
view that returns nothing when one dependency is down is a health view that tells you nothing when
you need it most.

Add the admin response models to `services/api/schemas.py`. Extend `tests/integration/test_admin.py`
with the tier, events and health cases from `<behavior>`, including reading both hash fields back for
a two-source slug, the clear case, the enumerated-window rejection, and the broker-unavailable case
driven by pointing the broker setting at an unroutable address.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_admin.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_admin.py -q -p no:cacheprovider` exits 0.
    - `uv run python -c "from services.api.app import create_app; print(sorted(p for p in {getattr(r,'path','') for r in create_app().routes} if p.startswith('/admin')))"` prints a list containing `/admin/health`, `/admin/restaurants`, `/admin/restaurants/{slug}/events` and `/admin/restaurants/{slug}/tier`.
    - `cat services/api/routers/admin.py | grep -v '^\s*#' | grep -c tier_override_field` prints at least `1`.
    - `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>An operator can force a restaurant's polling cadence, see what it has produced, and read consumer lag, poll health and dependency status in one response that still renders when one dependency is down.</done>
</task>

<task type="auto">
  <name>Task 3: The evidence — a tested curl walkthrough, the OpenAPI route snapshot, the Make and environment blocks, and the pending-human SSE runbook</name>
  <files>scripts/api_smoke.sh, docs/api.md, docs/runbooks/sse-cloudrun.md, Makefile, .env.example, README.md, tests/unit/test_openapi_snapshot.py, tests/unit/fixtures/openapi_routes.txt, tests/integration/test_api_smoke_script.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-104, §D-104b and §Specific Ideas (the curl walkthrough as the success-criterion artifact)
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Common Pitfalls" Pitfall 3 (the per-process ring's cross-replica caveat) and Pitfall 5 (the token in the platform's request log)
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Rate Limiting" (the fixed-window burst caveat to state rather than imply) and §"Request Models" (the two validation-error shapes)
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Cloud Run (human-gated, Phase 7 — build for it now)" — the request-timeout setting, the streaming support note, and the reconnect expectation
    - .planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md §"`Makefile` and `.env.example`" — the help-comment convention, the phony list, and the safety-property comment style
    - Makefile lines 1-45 (the target shape, the phony list and the in-recipe rationale style)
    - .env.example (the section headers and the placeholder-value style)
    - docs/runbooks/perf02-24h-log.md (the pending-human status banner and runbook structure this repo already uses)
    - README.md (the section ordering the API section joins)
  </read_first>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_openapi_snapshot.py -q -W error::RuntimeWarning` exits 0.
    - `uv run pytest tests/integration/test_api_smoke_script.py -q -p no:cacheprovider` exits 0.
    - `bash -n scripts/api_smoke.sh` exits 0 and `test -x scripts/api_smoke.sh` exits 0.
    - `grep -c '^api:' Makefile` prints `1` and `grep -c '^api-smoke:' Makefile` prints `1`.
    - `grep -c 'api api-smoke\|api-smoke' Makefile` prints at least `2` (the target and its entry in the phony list).
    - `grep -c 'TRUST_PROXY_HEADERS\|PROXY_HOPS\|ADMIN_BASIC_USER\|ADMIN_BASIC_PASSWORD\|CORS_ALLOWED_ORIGINS\|PUBLIC_BASE_URL\|HMAC_TOKEN_VERSION\|HMAC_GRACE_UNTIL\|API_PORT' .env.example` prints at least `9`.
    - `grep -c 'STATUS: pending-human' docs/runbooks/sse-cloudrun.md` prints `1`.
    - `grep -c 'curl' docs/api.md` prints at least `15`.
    - `uv run python -c "from services.api.app import create_app; app=create_app(); rows=sorted(f'{m} {r.path}' for r in app.routes for m in getattr(r,'methods',set()) if m!='HEAD'); snap=[l for l in open('tests/unit/fixtures/openapi_routes.txt').read().splitlines() if l.strip()]; print(rows==snap)"` prints `True`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <action>
Write `scripts/api_smoke.sh` as the executable half of the phase's "testable end-to-end via curl"
claim. It takes a base URL argument with a local default, runs with an unset-variable and
pipefail-style strictness so an unexpected status stops it, and walks the lifecycle: create a watch
and capture the returned token, list through the management path route, list through the bearer
header, patch the party size, pause, resume, delete, confirm the second delete answers not-found,
then the public reads — restaurant search, restaurant detail, stats, recent feed — a bounded read of
the live feed proving frames arrive, and the metrics endpoint. Each step prints the step name and the
observed status and compares it against the expected one, exiting non-zero with the mismatch on the
first failure. It prints no token, no phone and no secret; where a token must be passed it is held in
a shell variable and never echoed. Make the file executable.

Write `docs/api.md` as the portfolio artifact and the Phase 6 contract. One section per route with a
runnable curl example and the response shape, plus the caveats research says must be stated rather
than implied: both validation-error shapes, since a cross-field failure reports the body while a
field failure keeps its field name; the rate-limit headers and the fact that a fixed window can admit
up to twice the cap across a boundary; that a delete is a soft delete and the row is retained for the
notification audit trail; that the live feed replays the whole retained buffer when a last-event id
has rotated out, and why a browser should deduplicate on event id; that the recent endpoint is served
from a per-process buffer and falls back to the database, so two replicas can answer differently;
and the residual risk that a management token in a path is recorded by the platform's own request log,
which is why the bearer form is preferred and why every successful call re-mints. Add a short section
naming the environment variables an operator must set. Link the smoke script as the executable form
of the walkthrough.

Write `tests/unit/test_openapi_snapshot.py` and its fixture. The snapshot is the sorted list of
method-and-path pairs plus the response model names — never the whole document, whose descriptions
and schema details would turn every prose edit into a snapshot diff. Generate the fixture from the
built app, commit it, and have the test compare the current app against it with a failure message
that shows the added and removed lines and tells the reader to update the fixture deliberately when
the change is intended. State in the module docstring that this file is Phase 6's contract.

Add the two Make targets with the help comment the help target greps for and their entries in the
phony list. The server target runs the app with its own logging configuration disabled, and the
recipe carries the reason in a comment: the structlog routing installed in 05-01 is the only log path,
and leaving the default configuration in place would produce a second, unredacted one. The smoke
target invokes the script.

Add the Phase-5 block to `.env.example` under its own section header, in the existing placeholder
style. The proxy-trust variable carries a multi-line comment stating the second-to-last-hop
assumption, the one-appending-proxy expectation and that the local default is untrusted; the admin
password uses a placeholder value and is already covered by the log redaction set. Add the public
base URL, the allowed origins, the token version and grace date, the port, the rate cap, the push
suffix allowlist, the heartbeat and ring settings and the stats cache window.

Write `docs/runbooks/sse-cloudrun.md` with the pending-human status banner this repo already uses.
It records the one measurement this phase cannot make locally: the first-event latency through the
deployed URL rather than a local socket. Include the request-timeout setting an SSE stream depends on
and its default and maximum, the note that the platform does not buffer server streaming and that the
no-buffering header is kept for any proxy that appears later, the expectation that even at the maximum
the stream is eventually cut so the client must reconnect, and the exact commands and the acceptance
threshold. Reference the locally measured figure so the human knows what a healthy result looks like.

Add a short API section to `README.md` linking the reference document, naming the base paths, and
stating the public-metrics posture and the admin-credential requirement.

Write `tests/integration/test_api_smoke_script.py`: run the smoke script as a subprocess against the
in-process live server fixture and assert it exits 0 and that its output contains none of the token,
phone or secret values used during the run. This is what makes the documentation a tested artifact
rather than a hopeful one.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_openapi_snapshot.py -q -W error::RuntimeWarning &amp;&amp; uv run pytest tests/integration/test_api_smoke_script.py -q -p no:cacheprovider &amp;&amp; bash -n scripts/api_smoke.sh</automated>
  </verify>
  <done>The phase's "testable end-to-end via curl" claim is a script that runs in CI, the route list Phase 6 builds against cannot change without a deliberate snapshot update, an operator has a complete environment block and two Make targets, and the one measurement that needs a deployed URL is a written procedure rather than an open question.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (05-06 slice)

**New modules:** `services/api/routers/admin.py`.

**Modified modules:** `services/api/deps.py`, `services/api/schemas.py`, `services/api/config.py`,
`services/api/app.py`.

**HTTP routes:** `GET /admin/restaurants`, `POST /admin/restaurants`,
`GET /admin/restaurants/{restaurant_id}`, `PATCH /admin/restaurants/{restaurant_id}`,
`DELETE /admin/restaurants/{restaurant_id}` (200 / 409),
`PUT /admin/restaurants/{slug}/tier`, `GET /admin/restaurants/{slug}/events?window=24h|7d`,
`GET /admin/health` — all behind HTTP Basic, all `404` when the admin credentials are unset.

**New symbols — `services/api/deps.py`:** `admin_guard`.

**New symbols — `services/api/routers/admin.py`:** `ADMIN_REALM`, the seven handlers, and the
window enumeration.

**New symbols — `services/api/schemas.py`:** `AdminRestaurantIn`, `AdminRestaurantOut`,
`TierOverrideIn`, `AdminEventsOut`, `AdminHealthOut`.

**New scripts:** `scripts/api_smoke.sh` — the full watch lifecycle plus the public reads over curl.

**New docs:** `docs/api.md` (every route, curl examples, both error shapes, the rate-limit and
soft-delete and SSE-replay caveats, and the token-in-path residual risk),
`docs/runbooks/sse-cloudrun.md` (`STATUS: pending-human` — SSE first-event latency through the
deployed URL).

**New test fixture:** `tests/unit/fixtures/openapi_routes.txt` — the sorted `METHOD path` snapshot
Phase 6 generates its client against (D-104b).

**Make targets:** `make api`, `make api-smoke`.

**Env vars documented in `.env.example`:** `PUBLIC_BASE_URL`, `CORS_ALLOWED_ORIGINS`,
`TRUST_PROXY_HEADERS`, `PROXY_HOPS`, `ADMIN_BASIC_USER`, `ADMIN_BASIC_PASSWORD`,
`HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL`, `API_PORT`, `WATCH_CREATE_RATE_LIMIT`,
`PUSH_ENDPOINT_ALLOWED_SUFFIXES`, `SSE_HEARTBEAT_SECONDS`, `FEED_RING_SIZE`,
`STATS_CACHE_SECONDS`.

**Redis contract written:** the `tier:override` HASH, one field per source row of a slug, via
`tier_override_field(source, platform_id)`; the `sched:polls` ZSET entry for an admin-created
restaurant, via the shared job-descriptor helper.

**README:** an API section linking `docs/api.md`.
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| public internet -> `/admin/*` | A single shared credential guards restaurant CRUD and the polling schedule |
| admin -> the polling schedule | An admin write changes what the fleet does on its next cycle |
| API process -> Kafka admin client | A per-request client that must not leak on an error path |
| repository -> `.env.example`, `docs/api.md` | Committed files that must never carry a real credential or a real token |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-05-44 | Spoofing | admin credential brute force | high | mitigate | Constant-time comparison on both fields with a non-short-circuiting combine, so neither a timing difference nor an early return reveals whether the username matched |
| T-05-45 | Information Disclosure | an unconfigured deployment advertising an admin surface | high | mitigate | The guard answers not-found when either credential is unset, so the routes are indistinguishable from routes that do not exist |
| T-05-46 | Denial of Service | unlimited admin authentication attempts | medium | accept | Recorded as residual risk: no per-IP limit on `/admin/*` in this phase. Bounded by constant-time comparison, credential strength and per-instance concurrency; closing it belongs with the Phase 7 deploy hardening |
| T-05-47 | Tampering | an admin deleting a restaurant users are actively watching | high | mitigate | The delete counts active watches first and refuses with a conflict naming the count |
| T-05-48 | Tampering | a restaurant created without its polling schedule entry, silently never polled | medium | mitigate | The create seeds the schedule entry through the shared descriptor helper, and the integration test reads the entry back |
| T-05-49 | Tampering | a tier override written against the surrogate row id, silently doing nothing | medium | mitigate | The field is built by the shared helper from the platform id; the two-source read-back is an integration assertion |
| T-05-50 | Repudiation | an unattributable admin change | medium | mitigate | Every admin mutation logs the authenticated username with the action and the affected identifier |
| T-05-51 | Denial of Service | a leaked Kafka admin client per failed health request | medium | mitigate | Started inside the try and closed in the finally — the placement this repository already fixed once for a connection leak |
| T-05-52 | Information Disclosure | a real credential or token committed in the example env file, the docs or the smoke script's output | high | mitigate | Placeholder values only in the example file; the smoke script holds its token in a variable and never echoes it, and its integration test asserts no secret appears in the output |
| T-05-53 | Information Disclosure | the health route leaking infrastructure detail to an unauthenticated caller | medium | mitigate | It sits behind the same admin guard as every other admin route; the public metrics endpoint carries aggregate series only |
| T-05-SC | Tampering | package-manager installs | high | mitigate | Zero packages added; the admin client, the basic-auth extractor and the constant-time comparison all come from libraries already pinned |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `make api-smoke` exits 0 against a locally running server, and the same script is run against the in-process server by `tests/integration/test_api_smoke_script.py`.
- `docs/runbooks/sse-cloudrun.md` carries `STATUS: pending-human` — the deployed-URL SSE measurement is the phase's one human-gated item and does not block phase completion.
</verification>

<success_criteria>
- Restaurant CRUD, polling-tier override, per-restaurant event volume and a system-health summary are all reachable with credentials and all invisible without them.
- A delete cannot orphan an active watch, and a created restaurant is polled on the next cycle.
- The route list Phase 6 builds against is pinned by a snapshot that fails on an accidental change.
- The curl walkthrough in `docs/api.md` is backed by a script that runs in CI and prints no secret.
- An operator has a complete environment block, two Make targets, and a written procedure for the one measurement that needs a deployed URL.
</success_criteria>

<output>
Create `.planning/phases/05-api-watchlist-crud-sse/05-06-SUMMARY.md` when done
</output>