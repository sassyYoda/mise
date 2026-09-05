---
phase: 04-notification-pipeline
plan: 04
type: execute
wave: 2
depends_on: [04-01, 04-02]
files_modified:
  - services/api/__init__.py
  - services/api/config.py
  - services/api/app.py
  - services/api/routers/__init__.py
  - services/api/routers/links.py
  - services/api/routers/webhooks.py
  - tests/integration/conftest.py
  - tests/integration/test_api_go.py
  - tests/integration/test_api_unsubscribe.py
  - tests/integration/test_api_webhooks.py
  - tests/integration/test_notification_log_transitions.py
  - tests/unit/test_no_new_runtime_deps.py
autonomous: true
requirements: [NOTIF-04, NOTIF-06, NOTIF-07, PERF-03]

estimate:
  tokens: 70000
  raw_tokens: 70000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`GET /go/{token}` verifies the token with `expected_purpose='go'`, resolves the `notification_log` row the token names, writes `clicked_at` and `status='clicked'` and the computed `slot_still_available` SYNCHRONOUSLY in the request, and returns `302` with a `Location` header equal to `platform_booking_url(...)` for the event's source (D-84, NOTIF-07, SC5)."
    - "`slot_still_available` is TRUE when the Phase-2 Redis slot record exists and its state is AVAILABLE, FALSE when the record exists in any other state, and NULL when the record is ABSENT — an absent record means the 25 h state TTL expired, not that the table is gone, and counting it as FALSE would inflate the PERF-03 rate with stale clicks (D-86a, research §slot_still_available)."
    - "PROBE PERF-03/boundary: the three-way outcome is exact at each edge — AVAILABLE gives TRUE and a 302; a present non-AVAILABLE record gives FALSE and a 200 'that table is gone' page; an absent record gives NULL and still redirects, because an unknown state is not a negative one; and a click whose `notification_log.created_at` is older than `GO_TOKEN_MAX_AGE_HOURS` is refused with the gone page, which is the lifetime bound BC-2 traded the `exp` claim for."
    - "PROBE NOTIF-07/unclassified — flagged assumption: the redirect TARGET is only shape-verified. `platform_booking_url` emits `[ASSUMED]` URL forms (research A1/A2), so `test_api_go.py` asserts the `Location` header's parameters, encoding and status code and never follows the redirect; `follow_redirects` stays at its httpx default of False for exactly this reason."
    - "`POST /unsubscribe/{token}` sets the named watch to `status='paused'` (and `users.sms_opt_out=true` when the token's purpose is `sms_stop`), is idempotent on repeat, and completes inside the request — SC4's five-second budget is measured on the POST (D-84, D-84a/BC-3)."
    - "`GET /unsubscribe/{token}` does NOT mutate: it renders a one-button confirmation form that POSTs to the same URL, with `Cache-Control: no-store`. A corporate link scanner that prefetches every URL in an email therefore cannot silently pause a watch nobody asked to pause. `GET …?confirm=1` is accepted as the explicit plain-text-client path (D-84a, research OQ-2)."
    - "Every webhook body is read as RAW bytes and parsed with `urllib.parse.parse_qsl`; `python-multipart` is neither installed nor added, and `tests/unit/test_no_new_runtime_deps.py` fails if it ever appears in `[project].dependencies` (D-84a/BC-3)."
    - "`POST /webhooks/twilio/inbound` verifies `X-Twilio-Signature` against a URL built from `TWILIO_WEBHOOK_BASE_URL` plus the route path — never `request.url` — BEFORE the phone lookup; an invalid signature returns 403 and performs ZERO database writes (D-84, research §Pitfall 9)."
    - "A verified inbound STOP resolves the sender through `phone_hash(From)` against the unique `users.phone_hash` index, sets `sms_opt_out=true`, flips EVERY `active` watch of that user to `paused`, and replies `<Response/>` — all inside one request (NOTIF-04, SC4)."
    - "`POST /webhooks/twilio/status` maps `delivered` to `status='delivered'` + `delivered_at`, maps `failed`/`undelivered` to `status='failed'` + an `error` naming the status and error code, and is a no-op for every other `MessageStatus`, matching the row by `provider_id = MessageSid` (NOTIF-06)."
    - "`POST /webhooks/resend` verifies the Svix signature over the raw body when `RESEND_WEBHOOK_SECRET` is set and rejects a tampered body with 403; the `notification_log` row is matched by `provider_id` against the event payload's email id (NOTIF-06)."
    - "`create_app()` is importable and testable in-process through `httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url='https://api.mise.place')` — the `app=` shortcut was removed in httpx 0.28 and an `http://test` base URL would exercise a different string than production (research §Route behaviour verified in-process)."
    - statement: "The Resend webhook envelope is `{\"type\", \"created_at\", \"data\": {\"email_id\", …}}` and `data.email_id` equals the id returned by the send call. The shape is [ASSUMED] (research A3) — only a real webhook delivery during the human-gated Resend domain setup can confirm the field name, so the handler carries a `TODO(spike)` and a delivery that matches zero rows is logged rather than treated as an error."
      verification: backstop
  artifacts:
    - services/api/app.py
    - services/api/config.py
    - services/api/routers/links.py
    - services/api/routers/webhooks.py
    - tests/integration/test_api_go.py
    - tests/integration/test_api_unsubscribe.py
    - tests/integration/test_api_webhooks.py
    - tests/integration/test_notification_log_transitions.py
    - tests/unit/test_no_new_runtime_deps.py
  key_links:
    - "`verify_token(..., expected_purpose=...)` (04-01) -> every route in `links.py`. The purpose claim is the entire access-control model: `/go` grants a redirect and a click record, `unsubscribe` grants a pause, and neither token is accepted by the other route."
    - "`RedisStateStore.get_slots` (Phase 2) -> `/go`'s `slot_still_available` -> `scripts/check_false_positive_rate.py` (04-07). The route's three-way answer is what makes PERF-03's denominator honest; a two-way answer would inflate it with expired state."
    - "`TWILIO_WEBHOOK_BASE_URL` + route path -> `verify_twilio_signature` (04-01). Behind a proxy `request.url` reports the internal scheme and host, and every inbound STOP then fails verification silently — a TCPA exposure, not a cosmetic bug."
    - "`phone_hash()` (04-01) -> `users.phone_hash` unique index (04-02) -> the STOP handler. One canonicalisation on both sides or the opt-out matches nothing."
    - "`services/api/app.py` -> `services/state_machine/store.py::RedisStateStore`. A deliberate service-to-service import of the READ path only; the state machine's engine is never constructed here."
  prohibitions:
    - "MUST NOT perform any database write, phone lookup or state mutation before a webhook's signature has verified; a rejected signature short-circuits with 403 and touches nothing."
    - "MUST NOT derive the signature-verification URL from `request.url`, `request.headers['host']`, or any other request-supplied value."
    - "MUST NOT mutate state in a bare `GET` handler that a link scanner can prefetch."
    - "MUST NOT add `python-multipart`, or any other runtime dependency, to satisfy form parsing."
    - "MUST NOT accept a token whose `p` claim differs from the route's expected purpose, even when its MAC is valid."
    - "MUST NOT log a token, a phone number, a `MessageSid` paired with a recipient, or a webhook body; failures are logged by shape."
    - "MUST NOT construct a second `httpx.AsyncClient` or a second SQLAlchemy engine inside the API process."
---

<objective>
Ship the FastAPI application skeleton Phase 5 will extend, carrying the three inbound surfaces this
phase owns: the click-tracked deep-link redirect, one-click unsubscribe, and the Twilio and Resend
webhooks.

Purpose: NOTIF-07's deep links and NOTIF-04's STOP handling are only real if something answers the
URL, and PERF-03's false-positive rate is only honest if `/go` can say "I do not know" as well as
"yes" and "no". This is also the phase's only HTTP server, so it establishes the ASGI test harness,
the raw-body webhook convention and the config-derived verification URL that Phase 5 inherits.
Output: `services/api/` with two routers, the `api_client` fixture, and four test files driving every
route in-process over `ASGITransport`.
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
  <name>Task 1: End-to-end tracer — a real `/go` click writes the row, computes availability, and redirects</name>
  <files>services/api/__init__.py, services/api/config.py, services/api/app.py, services/api/routers/__init__.py, services/api/routers/links.py, tests/integration/conftest.py, tests/integration/test_api_go.py</files>
  <read_first>
    - services/state_machine/main.py lines 95-160 (the `AsyncExitStack` lifespan shape, `dispose_engine` pushed first so it unwinds last, and the resource-registration ordering the app factory mirrors)
    - services/state_machine/store.py lines 90-140 (`RedisStateStore.get_slots` and its return shape) and services/state_machine/models.py (`SlotState`, `SlotRecord`)
    - shared/redis_keys.py `avail_state_key` and the slot-key comment (`f"{time_slot}|{seat_type or '-'}"`) plus `AVAIL_STATE_TTL_SECONDS`
    - shared/db.py (`NotificationLog`, `WatchlistEntry`, `Restaurant`, and the `AvailabilityEvent` hypertable ORM class) and migration 0008's `uq_availability_events_event_id_time` index (leading column `event_id`)
    - shared/tokens.py and shared/links.py as written in 04-01
    - tests/integration/conftest.py in full (the 04-02 `seed_user_and_watch`, `reset_shared_db_singletons` ordering rule, `redis_url`, `db_urls`)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"`/go`, `slot_still_available`, and unsubscribe" (the verified in-process transcript, the `ASGITransport(app=...)` signature, the `base_url` warning, and the three-way availability rule)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Code Examples" — "FastAPI in-process test harness"
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-84, §D-86a
  </read_first>
  <behavior>
    - A `go` token for a seeded `notification_log` row whose event's slot record is AVAILABLE returns 302, with `Location` containing the platform id, the date and the party size.
    - After that request, the row has a non-null `clicked_at`, `status='clicked'` and `slot_still_available IS TRUE`.
    - The same token replayed is idempotent: still a 302, `clicked_at` unchanged or refreshed without error, and still exactly one row.
    - With the slot record present but in a non-AVAILABLE state, the response is 200, the body contains the "gone" wording, and `slot_still_available IS FALSE`.
    - With no slot record at all, the response is 302 and `slot_still_available IS NULL`.
    - A tampered token returns 400 and writes nothing; a token minted for `unsubscribe` returns 400 and writes nothing.
    - A token naming a `notification_log` id that does not exist returns 404 and writes nothing.
    - A row whose `created_at` is older than `GO_TOKEN_MAX_AGE_HOURS` returns the 200 gone page rather than redirecting.
    - `httpx.AsyncClient(transport=ASGITransport(app=create_app()), base_url="https://api.mise.place")` reaches every route without a network listener.
  </behavior>
  <action>
Create `services/api/__init__.py` and `services/api/routers/__init__.py` as package markers, and
`services/api/config.py` in the `services/notifier/config.py` register — every environment read a
FUNCTION, a `Named symbols:` docstring line, `__all__` for the re-exports. Accessors:
`redis_url()`, `database_url_async()`, `env_name()`, `twilio_webhook_base_url()`,
`twilio_auth_token()`, `resend_webhook_secret()`, and `go_token_max_age_hours()` reading
`GO_TOKEN_MAX_AGE_HOURS` with a default of 72. The docstring for the last one records why it exists:
BC-2 removed the `exp` claim from the `go` token to buy SMS septets, and the stated substitute was
that the link's lifetime is bounded by the `notification_log` row it names — this accessor is that
bound, made explicit rather than implied.

Write `services/api/app.py` with `create_app() -> FastAPI`. Use a `lifespan` async context manager
built on `AsyncExitStack`, mirroring `services/state_machine/main.py`: push `dispose_engine` FIRST so
LIFO unwinding closes the asyncpg pool LAST against a live loop, then create the `redis.asyncio`
client and register `aclose`, then `close_async_client` for the shared httpx singleton. Store the
Redis client on `app.state`. Call `assert_crypto_env()` at startup so a malformed
`PHONE_ENCRYPTION_KEY` fails at boot rather than at the first SMS. Include the `links` router now and
leave a comment naming the routers Phase 5 adds (`/watches`, `/api/feed/live`, `/admin`,
`/api/metrics`) so the extension point is documented rather than discovered. Expose
`app = create_app()` at module scope for `uvicorn services.api.app:app`.

Write `services/api/routers/links.py` with `GET /go/{token}`. Order of operations, each a commented
step: verify the token with `expected_purpose="go"` and translate `TokenError` into a 400 with no
body detail; read the integer `n` claim; load the `notification_log` row joined to
`watchlist_entries` and `restaurants` in ONE statement (404 when absent); refuse a row older than
`go_token_max_age_hours()` with the gone page; load the event's `date`, `time_slot`, `party_size`,
`seat_type` and platform `restaurant_id` from `availability_events` by `event_id` — the leading
column of `uq_availability_events_event_id_time`, so this is an index lookup; compute
`slot_still_available` by reading the Phase-2 record through `RedisStateStore(...).get_slots(rid,
date, party)` and indexing the slot key `f"{time_slot}|{seat_type or '-'}"`, yielding TRUE for
`SlotState.AVAILABLE`, FALSE for any other present state, and NULL for an absent record; UPDATE
`clicked_at`, `status='clicked'` and `slot_still_available` synchronously — SC4's timing budget is met
by doing the write in the request, not by deferring it; then return a `RedirectResponse` with status
302 for TRUE or NULL and an `HTMLResponse` 200 carrying a minimal "sorry, that table is gone" page
for FALSE. Comment the NULL branch with its reason: an absent record after the 25 h state TTL means
UNKNOWN, and scoring it FALSE would both mislead the user and inflate PERF-03 with stale clicks
(D-86a). Set `Cache-Control: no-store` on every response so an intermediary cannot serve one user's
redirect to another.

Extend `tests/integration/conftest.py` with an `api_client` fixture yielding
`httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="https://api.mise.place")`,
importing `create_app` INSIDE the fixture body so collection does not require the app before its
dependencies are configured. Comment the `base_url` choice: `/go` writes a click and then redirects,
and any code path deriving an absolute link from the request would silently exercise a different
string under `http://test`.

Write `tests/integration/test_api_go.py` as the tracer: seed a restaurant, user, active watch and a
`notification_log` row against live containers; write a matching Phase-2 slot record into live Redis
through `RedisStateStore`; mint a real `go` token; and drive every bullet in `<behavior>` through
`api_client`. Leave `follow_redirects` at its default of False and assert the `Location` header's
shape rather than chasing it to a third-party site.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_api_go.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_api_go.py -q -p no:cacheprovider` exits 0, or skips with the existing Docker-guard message on a Docker-less host.
    - `uv run python -c "from services.api.app import create_app; app=create_app(); print(sorted({r.path for r in app.routes if getattr(r,'path','').startswith('/go')}))"` prints `['/go/{token}']`.
    - `uv run python -c "from services.api.app import app; print(type(app).__name__)"` prints `FastAPI`.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A real signed click reaches a live app over ASGITransport, resolves its notification row, reads the live Phase-2 slot state, records the click and the three-way availability answer, and redirects — the whole NOTIF-07 / PERF-03 request path, end to end.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: One-click unsubscribe that a link scanner cannot trigger</name>
  <files>services/api/routers/links.py, tests/integration/test_api_unsubscribe.py, tests/unit/test_no_new_runtime_deps.py</files>
  <read_first>
    - services/api/routers/links.py as written in Task 1
    - shared/tokens.py (`TOKEN_PURPOSES`, `UNSUBSCRIBE_TOKEN_TTL_SECONDS`, `TokenExpired`) as written in 04-01
    - shared/db.py (`WatchlistEntry.status`, `User.sms_opt_out`)
    - pyproject.toml `[project].dependencies` in full (the exact list the gate pins)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"One-click unsubscribe (RFC 8058)" (the HTTPS-URI requirement, the `List-Unsubscribe=One-Click` POST body, the no-cookies rule, the 48-hour deadline) and §"Blocking Corrections" BC-3
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Open Questions" OQ-2 (the link-scanner failure mode and the accepted resolution)
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-84, §D-84a
  </read_first>
  <behavior>
    - `POST /unsubscribe/{token}` with body `List-Unsubscribe=One-Click` and no cookies returns 200 and sets the named watch to `paused`.
    - The same POST repeated returns 200 and leaves exactly one paused watch — idempotent.
    - A token whose purpose is `sms_stop` additionally sets `users.sms_opt_out = true`; a plain `unsubscribe` token does not touch that column.
    - `GET /unsubscribe/{token}` returns 200 with an HTML form whose method is POST and whose action is the same path, sets `Cache-Control: no-store`, and leaves the watch `active`.
    - `GET /unsubscribe/{token}?confirm=1` mutates exactly as the POST does.
    - An expired `unsubscribe` token returns 400 and leaves the watch `active`.
    - A `go` token presented to either method returns 400 and leaves the watch `active`.
    - `python-multipart` is absent from `[project].dependencies`, and the gate names the reason in its failure message.
  </behavior>
  <action>
Add `GET /unsubscribe/{token}` and `POST /unsubscribe/{token}` to `services/api/routers/links.py`.

The POST is the mutating path (D-84a, research OQ-2). Read the body as RAW bytes and parse it with
`urllib.parse.parse_qsl(raw.decode(), keep_blank_values=True)` — no framework form parsing, so the
route works with the pinned Starlette and adds no dependency (BC-3). Accept the token for either
`unsubscribe` or `sms_stop` by verifying twice against the two expected purposes and taking the first
that succeeds, so the route need not trust the payload before its MAC verifies. Set the named watch's
`status` to `paused`; when the purpose is `sms_stop`, additionally set `users.sms_opt_out = true` for
the token's user. Both writes are idempotent by construction (an UPDATE to a value it already holds),
and both happen INSIDE the request — SC4's five-second budget is measured here. Return a small HTML
confirmation with `Cache-Control: no-store` and no cookies, because RFC 8058 forbids the mailbox
provider's POST from carrying any.

The GET is deliberately non-mutating. Corporate link scanners prefetch every URL in a message, so a
state-mutating GET pauses watches nobody asked to pause — a silent loss of the product's core
function that arrives as "the alerts just stopped". Render a one-button form whose `method` is `post`
and whose `action` is the same path, and accept `?confirm=1` as an explicit opt-in that performs the
same mutation as the POST for a plain-text client with no form support. Write the reasoning into the
handler docstring so a later reader does not "simplify" the GET into a mutation.

Write `tests/integration/test_api_unsubscribe.py` covering every bullet in `<behavior>` through the
`api_client` fixture against live containers, including a timing assertion that the POST completes
well inside SC4's budget, and an explicit assertion that the GET left the watch `active`.

Write `tests/unit/test_no_new_runtime_deps.py`: parse `pyproject.toml`, read `[project].dependencies`,
and assert the forbidden distribution name is not among them. The failure message must name BC-3 and
point at `urllib.parse.parse_qsl` as the correct fix, so a future executor who hits the Starlette
error does not "fix" it by installing the package. Add a non-vacuity companion asserting the parsed
dependency list is non-empty and contains a package known to be there, so a path or key typo cannot
make the gate pass over an empty list.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_no_new_runtime_deps.py tests/integration/test_api_unsubscribe.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_no_new_runtime_deps.py -q` exits 0.
    - `uv run pytest tests/integration/test_api_unsubscribe.py -q -p no:cacheprovider` exits 0, or skips on a Docker-less host.
    - `uv run python -c "from services.api.app import create_app; app=create_app(); print(sorted({(r.path, tuple(sorted(r.methods))) for r in app.routes if 'unsubscribe' in getattr(r,'path','')}))"` prints one path with both `GET` and `POST`.
    - `uv run python -c "import inspect, services.api.routers.links as l; print('parse_qsl' in inspect.getsource(l))"` prints `True`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A mailbox provider's one-click POST pauses a watch inside the request while a scanner's GET provably does not, and the dependency the correct fix avoids is pinned out of the project by a non-vacuous gate.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Twilio inbound STOP, Twilio status callbacks, and Resend delivery webhooks</name>
  <files>services/api/routers/webhooks.py, services/api/config.py, tests/integration/test_api_webhooks.py, tests/integration/test_notification_log_transitions.py</files>
  <read_first>
    - services/api/app.py and services/api/config.py as written in Task 1
    - shared/twilio_signature.py, shared/svix_signature.py and shared/crypto.py (`phone_hash`, `canonical_e164`) as written in 04-01
    - shared/db.py (`User.phone_hash`, `User.sms_opt_out`, `NotificationLog.provider_id`, `.delivered_at`, `.status`, `.error`)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Twilio inbound signature" (the algorithm, the JSON `bodySHA256` variant, and the configured-URL rule), §"Twilio" (the delivery-status mapping table and the full `status` vocabulary), §"Resend webhooks — Svix" (headers, signed content, raw-body rule, the [ASSUMED] envelope)
    - .planning/phases/04-notification-pipeline/04-RESEARCH.md §"Code Examples" — "Twilio inbound webhook with signature verification, no python-multipart" and §"Pitfall 9"
    - .planning/phases/04-notification-pipeline/04-CONTEXT.md §D-84, §D-84a
  </read_first>
  <behavior>
    - A correctly signed inbound POST whose `Body` is `STOP` (also `stop`, ` Stop `, `STOPALL`, `UNSUBSCRIBE`, `CANCEL`, `END`, `QUIT`) returns 200 with `<Response/>`, sets `sms_opt_out=true`, and flips every `active` watch of that user to `paused` while leaving other users untouched.
    - A correctly signed inbound POST whose `Body` is ordinary text returns 200 `<Response/>` and changes nothing.
    - An inbound POST with a wrong or absent signature returns 403, and the user's watches and `sms_opt_out` are unchanged.
    - The signature is computed over the configured base URL plus the route path; a request arriving with a different `Host` header still verifies.
    - A sender whose `phone_hash` matches no user returns 200 `<Response/>` and writes nothing.
    - A signed status callback with `MessageStatus=delivered` sets `status='delivered'` and `delivered_at` on the row whose `provider_id` equals `MessageSid`; `failed` and `undelivered` set `status='failed'` with an `error` naming the status and `ErrorCode`; `sent`, `queued` and `read` are no-ops.
    - A Resend webhook with a valid Svix signature and `type='email.delivered'` sets `status='delivered'`; `email.bounced` sets `status='failed'`; a tampered body returns 403; a delivery matching no row returns 200 and logs a miss.
    - With `RESEND_WEBHOOK_SECRET` unset the route returns 202 without writing, so a local run is not blocked by a secret nobody has yet.
  </behavior>
  <action>
Write `services/api/routers/webhooks.py` with three routes, all reading `await request.body()` and
parsing with `parse_qsl` or `json.loads` as appropriate — never a framework form parser (BC-3).

`POST /webhooks/twilio/inbound`: build the verification URL as `twilio_webhook_base_url()` plus this
route's literal path and verify `X-Twilio-Signature` with `verify_twilio_signature` BEFORE anything
else; a failure returns 403 immediately with no database access. State in a comment that the URL comes
from config because behind a load balancer `request.url` reports the internal scheme and host, and
every inbound STOP would then fail verification with no clue — the failure mode is users who cannot
opt out. Add the two-line JSON-body guard: when the request's content type is JSON, append
`bodySHA256={hex}` to the URL and verify with an EMPTY parameter set, so a console misconfiguration
produces a diagnosable path rather than a silent rejection. On a verified request, uppercase and strip
`Body`, compare against the STOP keyword set, and on a match resolve the sender by
`phone_hash(From)` against the unique index, set `sms_opt_out`, and UPDATE every `active` watch of
that user to `paused` in one statement. Always reply `200` with the TwiML `<Response/>` body and an
XML content type — Twilio treats a non-2xx as a delivery failure and retries.

`POST /webhooks/twilio/status`: same signature verification against this route's own path, then map
`MessageStatus` per the research table onto `notification_log` matched by `provider_id = MessageSid`.
Everything outside the mapped set is an explicit no-op, not an error; the callback is idempotent by
construction because it sets absolute values.

`POST /webhooks/resend`: when `resend_webhook_secret()` is set, verify the Svix signature over the RAW
body bytes with the `svix-id` / `svix-timestamp` / `svix-signature` headers and return 403 on failure
— never re-serialise a parsed model, because the signature is sensitive to the slightest change. When
the secret is unset, return 202 and log once, so a local run is not blocked. Parse the envelope
defensively as `{"type": str, "created_at": str, "data": {"email_id": str}}` and mark the row matched
by `provider_id`; `email.delivered` maps to `delivered`, `email.bounced` and `email.complained` map to
`failed`. Put a `TODO(spike)` above the envelope parse recording that the field name is `[ASSUMED]`
(research A3) and must be confirmed against a real delivery during the human-gated Resend setup, and
log a zero-row match rather than raising.

Register the router in `services/api/app.py` and add any missing accessor to
`services/api/config.py`.

Write `tests/integration/test_api_webhooks.py` covering every webhook bullet in `<behavior>`, signing
each request with the real `shared/twilio_signature.py` and `shared/svix_signature.py` helpers so the
test exercises the same algorithm the route does, and including the differing-`Host` case that proves
the configured URL is what is used. Write `tests/integration/test_notification_log_transitions.py`
driving the full NOTIF-06 status chain against live containers: a seeded `sent` row moves to
`delivered` through the Twilio status callback and then to `clicked` through `/go`, with `sent_at`,
`delivered_at` and `clicked_at` all populated and none of them overwritten by a later step.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_api_webhooks.py tests/integration/test_notification_log_transitions.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_api_webhooks.py tests/integration/test_notification_log_transitions.py -q -p no:cacheprovider` exits 0, or skips on a Docker-less host.
    - `uv run python -c "from services.api.app import create_app; app=create_app(); print(sorted(r.path for r in app.routes if '/webhooks/' in getattr(r,'path','')))"` prints the three webhook paths.
    - `uv run python -c "import inspect, services.api.routers.webhooks as w; s=inspect.getsource(w); print('twilio_webhook_base_url' in s, 'verify_svix_signature' in s, 'TODO(spike)' in s)"` prints `True True True`.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A forged webhook is rejected before it can touch the database, a genuine STOP pauses every watch of the sender inside one request, and the `sent -> delivered -> clicked` status chain is proven end to end.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (04-04 slice)

**New modules:** `services/api/__init__.py`, `services/api/config.py`, `services/api/app.py`,
`services/api/routers/__init__.py`, `services/api/routers/links.py`,
`services/api/routers/webhooks.py`.

**New symbols — `services/api/app.py`:** `create_app()`, module-level `app` (served by
`uvicorn services.api.app:app`).

**New symbols — `services/api/config.py`:** `redis_url()`, `database_url_async()`, `env_name()`,
`twilio_webhook_base_url()`, `twilio_auth_token()`, `resend_webhook_secret()`,
`go_token_max_age_hours()`, `DEFAULT_GO_TOKEN_MAX_AGE_HOURS`.

**New symbols — routers:** `links.py` — `go_redirect`, `unsubscribe_form`, `unsubscribe_submit`,
`GONE_PAGE_HTML`, `CONFIRM_FORM_HTML`; `webhooks.py` — `twilio_inbound`, `twilio_status`,
`resend_events`, `STOP_KEYWORDS`, `TWILIO_STATUS_MAP`.

**HTTP routes:** `GET /go/{token}` (302 or 200), `GET /unsubscribe/{token}` (confirm form; `?confirm=1`
mutates), `POST /unsubscribe/{token}` (RFC 8058 one-click), `POST /webhooks/twilio/inbound`,
`POST /webhooks/twilio/status`, `POST /webhooks/resend`.

**Env vars introduced:** `TWILIO_WEBHOOK_BASE_URL`, `RESEND_WEBHOOK_SECRET`,
`GO_TOKEN_MAX_AGE_HOURS`. Added to `.env.example` by 04-07.

**Notification log statuses written here:** `clicked`, `delivered`, `failed`; columns written:
`clicked_at`, `slot_still_available`, `delivered_at`, `error`.

**Test helpers:** `tests/integration/conftest.py::api_client` (ASGITransport, base URL
`https://api.mise.place`).

**Make target referenced (added in 04-07):** `make api` -> `uv run uvicorn services.api.app:app`.
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| public internet -> `/go`, `/unsubscribe` | Unauthenticated capability tokens are the entire access-control model |
| Twilio / Resend -> `/webhooks/*` | Attacker-forgeable bodies and headers; only the signature distinguishes them |
| mailbox provider / link scanner -> `/unsubscribe` | Automated prefetch of every URL in an email, with no user intent behind it |
| API process -> Phase-2 Redis state | A read-only cross-service import of the slot store |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-04-21 | Spoofing | forged Twilio inbound STOP pausing a stranger's watches | critical | mitigate | `X-Twilio-Signature` verified against the CONFIG-derived URL with `compare_digest`, before the phone lookup and before any write; 403 short-circuits |
| T-04-22 | Spoofing | forged Resend webhook marking a failed send delivered | medium | mitigate | Svix HMAC-SHA256 over the raw body plus a 300 s timestamp tolerance; secret-unset path returns 202 and writes nothing |
| T-04-23 | Elevation of Privilege | token confusion — an `unsubscribe` token replayed at `/go` or the reverse | high | mitigate | `p` claim checked against each route's expected purpose; both directions asserted in the route tests |
| T-04-24 | Tampering | link-scanner prefetch silently pausing watches | high | mitigate | `GET` renders a confirmation form and never mutates; `POST` (or an explicit `?confirm=1`) is the only mutating path (OQ-2) |
| T-04-25 | Information Disclosure | a `/go` token in a log line grants click-through as the user | high | mitigate | Tokens are never logged; `_redact_secrets` covers the `token` key; route failures are logged by shape |
| T-04-26 | Information Disclosure | a shared cache serving one user's redirect to another | medium | mitigate | `Cache-Control: no-store` on every `/go` and `/unsubscribe` response |
| T-04-27 | Tampering | replay of a captured status callback | low | accept | Twilio status callbacks set absolute values keyed by `provider_id`, so replay is idempotent; no additional nonce store is warranted at v1 volume |
| T-04-28 | Denial of Service | unauthenticated route abuse | medium | transfer | Rate limiting is Phase 5's API-02; this phase's routes perform one indexed lookup and one UPDATE each, and Cloud Run's per-instance concurrency bounds the blast radius until then |
| T-04-SC | Tampering | package-manager installs | high | mitigate | Zero packages added. `python-multipart` is the one package that must NOT be added; `tests/unit/test_no_new_runtime_deps.py` (this plan) is the gate, with a non-vacuity companion |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 or skips cleanly without Docker.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run python -c "from services.api.app import create_app; print(len([r for r in create_app().routes if getattr(r,'path','').startswith(('/go','/unsubscribe','/webhooks'))]))"` prints at least `5`.
</verification>

<success_criteria>
- Six routes exist, all reachable in-process over `ASGITransport` with no network listener.
- Every webhook verifies its signature against a config-derived URL or the raw body before any write.
- `/go` answers TRUE, FALSE and NULL for availability, and only FALSE renders the gone page.
- The unsubscribe GET provably does not mutate; the POST provably does, inside the request.
- No runtime dependency is added, and a gate keeps it that way.
</success_criteria>

<output>
Create `.planning/phases/04-notification-pipeline/04-04-SUMMARY.md` when done
</output>
