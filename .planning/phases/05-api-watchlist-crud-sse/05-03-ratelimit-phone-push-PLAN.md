---
phase: 05-api-watchlist-crud-sse
plan: 03
type: execute
wave: 3
depends_on: [05-02]
files_modified:
  - shared/redis_keys.py
  - services/api/ratelimit.py
  - services/api/deps.py
  - services/api/config.py
  - services/api/schemas.py
  - services/api/watch_service.py
  - services/api/routers/watches.py
  - services/api/routers/push.py
  - services/api/app.py
  - tests/unit/test_redis_keys_phase5.py
  - tests/unit/test_rate_limit_window.py
  - tests/unit/test_no_setnx_expire_pairs.py
  - tests/unit/test_push_endpoint_validation.py
  - tests/integration/test_rate_limit.py
  - tests/integration/test_phone_ciphertext.py
  - tests/integration/test_push_subscribe.py
autonomous: true
requirements: [WATCH-05, WATCH-06, API-01]

estimate:
  tokens: 72000
  raw_tokens: 72000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`POST /watches` is capped at 60 requests per minute per client, keyed on `rate:api:watch_create:{ip}:{epoch_minute}`, enforced by a FastAPI dependency over a single Redis Lua script that performs the increment and a CONDITIONAL expire in one round trip — never an increment followed by a separate expire, which leaves a permanent key when the process dies between the two (D-96, WATCH-06)."
    - "PROBE WATCH-06/boundary: the 60th request in a window is allowed and the 61st is refused with `429`; the refusal carries `Retry-After` equal to the key's remaining TTL clamped to at least one second — never a constant 60, which tells a client refused at second 59 to wait a whole minute — plus `X-RateLimit-Limit` and `X-RateLimit-Remaining` (D-96, research Pitfall 10)."
    - "PROBE WATCH-06/precision: the bucket is `now_epoch_seconds // 60` — integer division, never a float and never a formatted timestamp — so two callers a millisecond apart inside the same wall minute always land on the same key; the TTL is 120 seconds so a counter always outlives the minute it describes across clock skew between replicas; and the fixed window admits up to twice the cap across a boundary, which is documented rather than claimed away (D-96, research §Rate Limiting)."
    - "PROBE WATCH-06/idempotency: the script is deliberately NOT idempotent — a replayed call increments again, which is the whole point of a counter — but the expire fires only on the FIRST increment of a bucket, so replaying can never slide the window forward and turn a fixed window into a sliding one (research §Rate Limiting, the Phase 4 D-74a reproduction)."
    - "PROBE WATCH-06/concurrency: N concurrent requests against one bucket produce exactly N increments and exactly one TTL, because the increment and the conditional expire are one script and Redis executes it atomically; a concurrency test asserts the final count equals the request count and the TTL is the configured value, not -1."
    - "The client address the limiter keys on comes from `services/api/middleware.py :: client_ip_from_scope` — the SAME function the request logger uses — so three requests carrying three different spoofed leading `X-Forwarded-For` entries and the same trailing pair land in ONE bucket, and the 61st is still refused (D-96a / BC-2)."
    - "Every new Redis key, TTL constant and Lua script for this phase lives in `shared/redis_keys.py` beside the existing families, with a named function and an entry in that module's `Named symbols:` docstring — the D-18 rule the module docstring already states (D-96)."
    - "Phone numbers reach the database only as `users.phone` AES-256-GCM ciphertext from Phase 4's `shared/crypto.py :: encrypt_phone`, plus a deterministic `users.phone_hash`; an integration test reads the raw column bytes, asserts they are not the plaintext, and asserts `decrypt_phone` round-trips them (D-94, WATCH-05)."
    - "No API response, log field or error message ever contains a phone number: `WatchOut.phone_masked` exposes the last two digits only, and a request that supplies a phone produces no log record containing it (D-94)."
    - "PROBE WATCH-05/unclassified — flagged assumption: this phase is a pure WRITER of the encryption contract. Decryption happens only at notification send time in Phase 4's SMS provider, so the round-trip is verified here against `decrypt_phone` directly rather than through a send; that the notifier decrypts the same bytes correctly is Phase 4's assertion, not this phase's (D-94, research §Sequencing)."
    - "Push subscriptions upsert into `push_subscriptions` keyed on the endpoint, clearing any revocation timestamp on re-subscribe, so a browser that re-registers the same endpoint updates one row instead of accumulating rows (D-94, D-102)."
    - "A subscription endpoint is accepted only when its scheme is `https` and its host matches the configured push-service suffix allowlist; anything else is rejected with `422` naming the environment variable that extends the list. Research raised this as an open SSRF pivot — the stored URL is one Phase 4 later POSTs to — and this is the planner's resolution of it (D-102, research §Security Domain)."
    - "`GET /api/push/vapid-public-key` is unauthenticated and returns the configured public key; `POST /api/push/subscribe` and `DELETE /api/push/subscribe` require a valid manage-purpose Bearer token and act only on the authenticated user's rows (D-102, D-91)."
    - "`services/api/deps.py :: bearer_user` verifies an `Authorization: Bearer` token through `shared/tokens.py` with the manage purpose expected, returns the user id, and answers `401` for a missing, malformed, wrong-purpose, expired or badly signed token — the purpose check is what stops a click or unsubscribe token from opening a management route (D-91, research §Tokens rule 4)."
  artifacts:
    - services/api/ratelimit.py
    - services/api/routers/push.py
    - tests/unit/test_redis_keys_phase5.py
    - tests/unit/test_rate_limit_window.py
    - tests/unit/test_push_endpoint_validation.py
    - tests/integration/test_rate_limit.py
    - tests/integration/test_phone_ciphertext.py
    - tests/integration/test_push_subscribe.py
  key_links:
    - "`client_ip_from_scope` (05-01) -> `services/api/ratelimit.py` -> the `rate:api:*` bucket key. One resolution function serves the log and the limiter; a second copy is how the two come to disagree about who the caller is, and the limiter's copy is the one an attacker cares about (BC-2)."
    - "`encrypt_phone` / `phone_hash` (Phase 4 D-85) -> `users.phone` / `users.phone_hash` -> the inbound STOP lookup and the SMS send in Phase 4. One canonicalisation on write and on lookup; a mismatch is a silent compliance failure, not a visible error."
    - "`push_subscriptions.endpoint` -> Phase 4's Web Push sender. Whatever URL this route accepts is a URL the notifier will POST to with our VAPID credentials, which is why the scheme and host are constrained at the boundary rather than at send time."
    - "`bearer_user` -> every management route in 05-04 and both mutating push routes here. It is the only authorisation primitive in this phase; a purpose check omitted here would let a `go` token from an SMS open a management endpoint."
  prohibitions:
    - "MUST NOT issue an increment and an expire as two separate Redis commands anywhere in `services/api/` — the pair is one script or it is a bug."
    - "MUST NOT key the rate limiter on the first `X-Forwarded-For` entry, on the socket peer when proxy headers are trusted, or on anything other than the shared client-IP resolver."
    - "MUST NOT return a constant `Retry-After`; the value is the key's remaining TTL."
    - "MUST NOT write a phone number to the database in any form other than the ciphertext and hash Phase 4's crypto module produces, and MUST NOT place a phone number, a token, or a push endpoint's authentication keys in a log field, an error message or a response body."
    - "MUST NOT re-implement, wrap or copy `encrypt_phone`, `decrypt_phone` or `phone_hash`; this phase is a caller."
    - "MUST NOT store a push endpoint whose scheme is not `https` or whose host is outside the configured allowlist."
    - "MUST NOT accept a Bearer token without checking its purpose claim, and MUST NOT report a token failure with a message that distinguishes 'expired' from 'bad signature' to the caller."
    - "MUST NOT add a third-party rate-limiting package; the limiter is the Lua script plus a dependency."
---

<objective>
Close the three gaps between a working create endpoint and a safe one: the 60-per-minute per-IP cap
that IS WATCH-06, phone numbers that exist in the database only as ciphertext, and push subscriptions
stored behind a Bearer credential and a constrained endpoint URL.

Purpose: BC-2 established that the locked client-IP rule makes the cap unenforceable — Google's
balancer appends to whatever the client sent and verifies nothing before the last two entries, so
keying on the first hop lets any caller mint a fresh bucket per request — and the alternative default
collapses every caller onto the balancer's own address and rate-limits the service as one client.
Both failure modes were reproduced; the fix is one resolver shared with the request logger, and this
plan is where it becomes load-bearing. The phone and push work is the other half of the same
boundary: the only two pieces of user data in this system that are not public.
Output: the fixed-window script and its keys in the shared registry, a rate-limit dependency, the
Bearer authorisation primitive, phone and push persistence, the three push routes, and seven test
modules.
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
@.planning/phases/05-api-watchlist-crud-sse/05-02-SUMMARY.md
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: End-to-end tracer — the 61st POST /watches in a minute is refused, and a spoofed forwarded hop cannot escape the bucket</name>
  <files>shared/redis_keys.py, services/api/ratelimit.py, services/api/deps.py, services/api/config.py, services/api/routers/watches.py, tests/unit/test_redis_keys_phase5.py, tests/unit/test_rate_limit_window.py, tests/unit/test_no_setnx_expire_pairs.py, tests/integration/test_rate_limit.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Rate Limiting (executed against Redis 7.2.16)" — the executed cap transcript, the script, the key transcript, the `Retry-After` rule and the fixed-window burst note
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Code Examples" — "Rate-limit dependency"
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Blocking Corrections" BC-2 (both reproduced client-IP failure modes and the Google load-balancer header shape)
    - .planning/phases/05-api-watchlist-crud-sse/05-PATTERNS.md §"`services/api/ratelimit.py`" — the `rate_minute_key` docstring to copy, the budget-script structure, the TTL-constant comment, and the mypy cast discipline
    - shared/redis_keys.py lines 250-300 (`rate_minute_key`, `RESY_RATE_TTL_SECONDS`) and lines 440-545 (`RESY_BUDGET_LUA` and the typed `cast(Awaitable[...])` helper block)
    - services/api/middleware.py as written in 05-01 (`client_ip_from_scope`)
    - tests/unit/test_no_setnx_expire_pairs.py (the comment-stripping scan, the scanned directory tuple, and the behavioural-claim test that pins a single atomic call)
    - tests/unit/test_client_ip.py as written in 05-01 (do not duplicate its cases; this task asserts the BUCKET, not the resolver)
  </read_first>
  <behavior>
    - Calling the script 60 times against one key returns allowed each time; the 61st returns refused, and the key's TTL is the configured value on every call rather than being refreshed.
    - The key produced for two timestamps a millisecond apart within one wall minute is identical; the key for the first second of the next minute differs.
    - Sixty concurrent calls against one fresh key leave the counter at exactly sixty and the TTL at the configured value.
    - The 61st `POST /watches` within a minute returns 429 with a `Retry-After` between 1 and the TTL, and with the limit and remaining headers present.
    - A refused request creates no `users` and no `watchlist_entries` row.
    - Three requests carrying three different spoofed leading forwarded entries and the same trailing pair share one bucket; the counter after them is three, not one each.
    - With proxy trust disabled, the header is ignored entirely and the socket peer is the bucket.
    - The refusal increments the rate-limited counter metric with the bucket label.
    - A source scan of `services/api/**` and `shared/redis_keys.py` finds no increment-then-expire command pair outside a script.
  </behavior>
  <action>
Extend `shared/redis_keys.py` — the single registry the module docstring already declares for every
Redis key in `services/` — with `api_rate_key(bucket, ip, epoch_second)` returning
`rate:api:{bucket}:{ip}:{epoch_minute}`, computing the minute by integer division and carrying the
same docstring rationale `rate_minute_key` already has: two callers a millisecond apart inside one
wall minute must land on the same key, so the input is never a float and never a formatted timestamp.
Add `RATE_WINDOW_SECONDS` and `RATE_KEY_TTL_SECONDS`, keeping the existing "why the TTL exceeds the
window" comment — a counter must outlive the minute it describes so clock skew between replicas
cannot orphan it. Add `FIXED_WINDOW_LUA` beside the existing budget script: an increment, an expire
applied ONLY when the counter is at one, and a return of the count, the allow flag and the TTL. Carry
the existing script's comment block explaining why the two commands are one script and why the expire
is conditional; the unconditional form refreshes the TTL on every increment and converts a fixed
window into a sliding one. Add the typed helper the caller needs so no `cast` ever appears in
`services/api/**`, and add every new name to the module's `Named symbols:` list. Add the bucket-name
constant for watch creation rather than passing a bare string from the route.

Write `services/api/ratelimit.py` holding only the FastAPI dependency. It resolves the client through
`client_ip_from_scope` with the configured trust and hop settings — importing the resolver, never
re-deriving it — registers the script, calls it with the TTL and the cap, and on refusal raises a 429
whose `Retry-After` is the returned TTL clamped to at least one, alongside the limit and remaining
headers. Increment the rate-limited counter with the bucket label. The docstring states the two
things a future reader must not "simplify": the dependency runs BEFORE the request body is parsed so
a flood costs one Redis round trip rather than a validation pass, and the resolver is shared with the
request logger so the log and the limiter can never disagree about the caller.

Add the cap and window accessors to `services/api/config.py` as functions, defaulting to the D-96
values, and attach the dependency to `POST /watches` in `services/api/routers/watches.py` as a route
dependency so it runs ahead of the handler.

Write `tests/unit/test_redis_keys_phase5.py` pinning the key shape and the two-timestamps-one-key
property, and `tests/unit/test_rate_limit_window.py` pinning the window arithmetic and the
`Retry-After` clamping as pure functions. Extend `tests/unit/test_no_setnx_expire_pairs.py` with the
non-vacuity assertion its scanned set now needs — the scanned directory tuple already covers the new
package, so add the assertion that a module from this phase is actually present in the scanned set,
which is what makes the existing gate non-vacuous for `services/api`.

Write `tests/integration/test_rate_limit.py` against the Redis container and the `api_app` fixture:
the sixty-then-one boundary, the header values, the no-row-created assertion, the concurrency case
under `asyncio.gather`, the three-spoofed-hops-one-bucket case, and the proxy-trust-disabled case.
Its docstring names the tier it uses and why.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_redis_keys_phase5.py tests/unit/test_rate_limit_window.py tests/unit/test_no_setnx_expire_pairs.py -q -W error::RuntimeWarning &amp;&amp; uv run pytest tests/integration/test_rate_limit.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_rate_limit.py -q -p no:cacheprovider` exits 0.
    - `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
    - `uv run python -c "from shared.redis_keys import api_rate_key as k; print(k('watch_create','203.0.113.55',1788000059)==k('watch_create','203.0.113.55',1788000060-1), k('watch_create','203.0.113.55',1788000060)!=k('watch_create','203.0.113.55',1788000059))"` prints `True True`.
    - `uv run python -c "from shared.redis_keys import FIXED_WINDOW_LUA as s; print(s.count('INCR'), s.count('EXPIRE'))"` prints `1 1`.
    - `grep -c 'client_ip_from_scope' services/api/ratelimit.py` prints at least `1`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A caller who exceeds sixty creates in a minute is refused with an honest wait time, a caller who forges the leading forwarded hop shares a bucket with themselves, and the increment and its expiry are one atomic script in the one module that owns Redis keys.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Phone numbers exist only as ciphertext — encryption on write, a masked response, and a byte-level proof</name>
  <files>services/api/schemas.py, services/api/watch_service.py, services/api/routers/watches.py, tests/integration/test_phone_ciphertext.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-94 and the WATCH-05 row of §Phase Requirements
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Sequencing Dependencies" (the ciphertext-bytes assertion recipe and the note that Phase 5 is a pure consumer of the crypto module)
    - shared/crypto.py as shipped by 04-01 — the exact signatures of `encrypt_phone`, `decrypt_phone`, `phone_hash`, the canonicalisation they apply, and the key-validation error they raise
    - .planning/phases/04-notification-pipeline/04-01-shared-token-crypto-kernel-PLAN.md §"New symbols — `shared/crypto.py`" and its phone-hash stability truth
    - shared/db.py lines 41-50 (`User.phone` is a binary column; `phone_hash` arrives with Phase 4's migration)
    - services/api/watch_service.py and services/api/schemas.py as written in 05-02
    - shared/telemetry.py lines 97-135 (the value-shaped redaction keys, which already include the phone key name)
  </read_first>
  <behavior>
    - A create with the sms channel and a phone stores a non-null binary phone value whose bytes are not the plaintext in any encoding, and a non-null phone hash.
    - `decrypt_phone` applied to the stored bytes returns the E.164 form the validator normalised to.
    - Two creates with the same phone written in different punctuation produce the same hash and different ciphertexts.
    - The create response carries a masked phone showing the last two digits and no other digits; no response field anywhere contains the full number.
    - No log record produced during a create carries the phone number in any form.
    - A create without the sms channel leaves the stored phone and hash untouched for an existing user rather than nulling them.
    - A create whose phone fails to encrypt because the key is malformed fails the request loudly at that point with no partial row committed.
  </behavior>
  <action>
Extend `services/api/watch_service.py` with the phone half of the user upsert (D-94). The upsert
writes the encrypted phone and the hash only when the incoming payload carries a phone; when it does
not, the update set must leave both columns alone rather than assigning null, because a user who adds
an email-only watch has not asked to stop receiving SMS for their other watches. Put that in the
comment — an update set that always writes every column is how a second watch silently disables the
first watch's SMS.

Call `encrypt_phone` and `phone_hash` from `shared/crypto.py`; do not wrap them, do not re-canonicalise
the number, and do not add a second normalisation step — the model already normalised to E.164 and
the crypto module canonicalises again on both write and lookup, which is what makes an inbound STOP
match. State in a comment that this module is a caller, not an owner, of the encryption contract.

Add `phone_masked` to the response model as the ONLY phone-shaped field the API ever emits: the last
two digits with the rest replaced by a fixed mask, computed from the validated input rather than by
decrypting. Add a field docstring saying the full number is never returned by any route in this
system and is decrypted only at send time in the notifier.

Write `tests/integration/test_phone_ciphertext.py`. Create a watch with the sms channel through the
route, then read `users.phone` as raw bytes with a direct query and assert those bytes do not contain
the plaintext under UTF-8 or ASCII; assert `decrypt_phone` returns the normalised number; assert the
hash is stable across two punctuation variants while the ciphertexts differ; assert the response's
masked field shows two digits; capture logs during the request and assert none carries the number.
Add the leave-alone case: a second, email-only create for the same address leaves the stored phone
and hash unchanged. Add the malformed-key case by pointing the key environment variable at an invalid
value and asserting the request fails and no watch row was committed.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_phone_ciphertext.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_phone_ciphertext.py -q -p no:cacheprovider` exits 0.
    - `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
    - `uv run python -c "from services.api.schemas import WatchOut; print('phone_masked' in WatchOut.model_fields, 'phone' in WatchOut.model_fields)"` prints `True False`.
    - `grep -c 'encrypt_phone' services/api/watch_service.py` prints at least `1`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A phone number entered through the public API exists in the database only as AES-256-GCM ciphertext plus a lookup hash, is proven so by reading the raw column bytes, and can leave the system through no response field and no log line.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: The Bearer authorisation primitive, push-subscription storage, and the three push routes</name>
  <files>services/api/deps.py, services/api/schemas.py, services/api/watch_service.py, services/api/routers/push.py, services/api/config.py, services/api/app.py, tests/unit/test_push_endpoint_validation.py, tests/integration/test_push_subscribe.py</files>
  <read_first>
    - .planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md §D-91, §D-94 (the push-subscription upsert rule) and §D-102
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Tokens and Rotation (executed)" — the five verification rules, especially the purpose check and the narrow-through-`object` idiom mypy strict requires
    - .planning/phases/05-api-watchlist-crud-sse/05-RESEARCH.md §"Security Domain" — the "Push endpoint used as an SSRF pivot" row that raised this control with the planner
    - shared/tokens.py as shipped by 04-01 — `verify_token`'s signature, its expected-purpose parameter, and its exception hierarchy
    - migrations/versions/ — the Phase 4 revision creating `push_subscriptions`, for the exact column names and the endpoint uniqueness
    - services/api/deps.py as written in 05-01 (`get_session`, `get_redis`, `get_request_id`)
    - .planning/phases/04-notification-pipeline/04-02-events-redis-schema-kernel-PLAN.md — the `push_subscriptions` shape and the revocation column semantics
  </read_first>
  <behavior>
    - A request with a valid manage-purpose Bearer token resolves to the user id in its claims.
    - A request with no header, a malformed header, a token signed with the wrong secret, an expired token, or a token whose purpose is a click or unsubscribe purpose all return 401, and the response body distinguishes none of these cases from each other.
    - `GET /api/push/vapid-public-key` returns the configured key with no credential required.
    - `POST /api/push/subscribe` with a valid token stores one row for the endpoint; posting the same endpoint again updates that row and clears its revocation timestamp rather than inserting a second.
    - `DELETE /api/push/subscribe` with a valid token marks that endpoint revoked and returns success; deleting an endpoint belonging to another user returns 404, never 403.
    - An endpoint whose scheme is not https is rejected with 422; an endpoint whose host is outside the configured suffix allowlist is rejected with 422 and a message naming the environment variable that extends it; an endpoint on an allowed host is accepted.
    - A subscription missing either key of its key pair is rejected with 422.
  </behavior>
  <action>
Add `bearer_user` to `services/api/deps.py` (D-91). It reads the authorization header, refuses
anything that is not a bearer scheme, and calls `shared/tokens.py :: verify_token` with the manage
purpose expected. Every token failure — missing, malformed, wrong signature, unknown version, expired,
wrong purpose — becomes one indistinguishable 401; the log line records the failure SHAPE by
exception class name, never the token and never a message that would let a caller distinguish an
expired token from a forged one. Put the purpose rule in the comment: this is the check that stops a
click token minted for an SMS from opening a management route, and it is why the purpose claim exists
at all. Return the user id as an int, narrowing the verified payload through the strict-mode idiom
the token module's own research established.

Add the push subscription models to `services/api/schemas.py`: an input model carrying the endpoint
and the key pair with both keys required, and an output model that echoes the endpoint back but never
the keys. Implement the endpoint constraint as a field validator — scheme must be https, and the host
must end with one of the configured allowed suffixes. Add the suffix list to
`services/api/config.py` as a function reading a comma-separated variable whose default is the known
push-service domains, and state the reason in its docstring: whatever URL this route accepts is a URL
the Phase 4 notifier will later POST to carrying our VAPID credentials, so an unconstrained endpoint
is a server-side request-forgery pivot. The rejection message names the variable so an operator can
extend the list without reading code.

Extend `services/api/watch_service.py` with `upsert_push_subscription(session, user_id, sub)` and
`revoke_push_subscription(session, user_id, endpoint)`. The upsert names the endpoint uniqueness as
its conflict target explicitly — never an unnamed target — and clears the revocation timestamp on
conflict so a browser re-registering the same endpoint updates one row. The revoke is a single
user-scoped update returning the affected id, so an endpoint that is not this user's produces an
empty result and therefore a 404, in one round trip and with no separate existence query.

Write `services/api/routers/push.py` with the three D-102 routes and register it in
`services/api/app.py`. The key route reads the public key from config and is deliberately
unauthenticated; both mutating routes depend on `bearer_user`. Wire the subscription written during
`POST /watches` through the same `upsert_push_subscription` function so the create path and the push
route cannot diverge — one writer for one table.

Write `tests/unit/test_push_endpoint_validation.py` covering the scheme rule, the allowlist rule with
its message, an allowed host, and the missing-key cases. Write `tests/integration/test_push_subscribe.py`
covering the token matrix against the routes, the re-subscribe collapsing to one row with the
revocation cleared, the revoke, and the cross-user 404.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_push_endpoint_validation.py -q -W error::RuntimeWarning &amp;&amp; uv run pytest tests/integration/test_push_subscribe.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_push_endpoint_validation.py -q -W error::RuntimeWarning` exits 0.
    - `uv run pytest tests/integration/test_push_subscribe.py -q -p no:cacheprovider` exits 0.
    - `uv run python -c "from services.api.app import create_app; print(sorted((r.path, tuple(sorted(r.methods))) for r in create_app().routes if getattr(r,'path','').startswith('/api/push')))"` prints three entries covering the key route and both subscribe methods.
    - `uv run python -c "import services.api.deps as d; print(callable(d.bearer_user))"` prints `True`.
    - `grep -c 'expected_purpose' services/api/deps.py` prints at least `1`.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>One Bearer verification function guards every management surface in this phase, a push endpoint cannot be stored unless it is an https URL on an allowed host, and re-subscribing a browser updates one row instead of growing a table.</done>
</task>

</tasks>

<artifacts_produced>
## Artifacts this phase produces (05-03 slice)

**New modules:** `services/api/ratelimit.py`, `services/api/routers/push.py`.

**Modified modules:** `shared/redis_keys.py`, `services/api/deps.py`, `services/api/config.py`,
`services/api/schemas.py`, `services/api/watch_service.py`, `services/api/routers/watches.py`,
`services/api/app.py`.

**HTTP routes:** `GET /api/push/vapid-public-key` (200, unauthenticated),
`POST /api/push/subscribe` (201/200, Bearer), `DELETE /api/push/subscribe` (200 / 404, Bearer).
`POST /watches` gains a `429` response with `Retry-After`, `X-RateLimit-Limit` and
`X-RateLimit-Remaining`.

**New symbols — `shared/redis_keys.py`:** `api_rate_key`, `RATE_WINDOW_SECONDS`,
`RATE_KEY_TTL_SECONDS`, `FIXED_WINDOW_LUA`, `RATE_BUCKET_WATCH_CREATE`, plus the typed helper the
dependency calls.

**New symbols — `services/api/ratelimit.py`:** `enforce_rate_limit`, `rate_limit_watch_create`.

**New symbols — `services/api/deps.py`:** `bearer_user`.

**New symbols — `services/api/schemas.py`:** `PushSubscriptionOut`, the endpoint validator, and
`WatchOut.phone_masked`.

**New symbols — `services/api/watch_service.py`:** `upsert_push_subscription`,
`revoke_push_subscription`, and the phone half of the user upsert.

**Redis keys written:** `rate:api:{bucket}:{ip}:{epoch_minute}`, TTL 120 s.

**Env vars introduced:** `WATCH_CREATE_RATE_LIMIT`, `PUSH_ENDPOINT_ALLOWED_SUFFIXES`. Consumes
`VAPID_PUBLIC_KEY`, `PHONE_ENCRYPTION_KEY`, `PHONE_HASH_SECRET`, `TRUST_PROXY_HEADERS`, `PROXY_HOPS`.
Documented in `.env.example` by 05-06.

**Metrics incremented:** `api_rate_limited_total{bucket}`.

**Database columns written for the first time by the API:** `users.phone` (ciphertext),
`users.phone_hash`, and every column of `push_subscriptions`.
</artifacts_produced>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| load balancer -> rate limiter | The forwarded header is attacker-influenced up to the last two entries |
| anonymous internet -> `POST /watches` | The only unauthenticated write; the cap is its sole abuse control |
| API -> `users.phone` at rest | The only regulated personal data in the system |
| API -> `push_subscriptions.endpoint` | A URL the notifier will later POST to with our VAPID credentials |
| bearer token -> management surface | A capability token is the entire authorisation model |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-05-17 | Denial of Service | rate-limit bypass by forging the leading forwarded hop | critical | mitigate | The bucket is keyed on the shared second-to-last-hop resolver; three spoofed leading entries collapsing to one bucket is an integration assertion (BC-2) |
| T-05-18 | Denial of Service | a counter left with no expiry after a crash between increment and expire | high | mitigate | One Lua script performs both; the conditional expire fires only on the first increment; the existing repo-wide gate scans the new package |
| T-05-19 | Information Disclosure | a phone number in a response, a log line or an exception message | critical | mitigate | Only a two-digit masked form is ever emitted; the column holds ciphertext; the redaction set already covers the phone key name; a log-capture assertion is part of the ciphertext test |
| T-05-20 | Information Disclosure | phone plaintext at rest | critical | mitigate | AES-256-GCM via Phase 4's crypto module, proven by reading the raw column bytes |
| T-05-21 | Tampering | a push endpoint pointing at an internal address, turning the notifier into an SSRF pivot | high | mitigate | Scheme constrained to https and host constrained to a configured suffix allowlist at the boundary, with the rejection naming the variable that extends it |
| T-05-22 | Elevation of Privilege | a click or unsubscribe token replayed against a management route | critical | mitigate | `bearer_user` passes the expected purpose to the verifier; the wrong-purpose case is asserted alongside the forged and expired cases |
| T-05-23 | Information Disclosure | a 401 body that distinguishes an expired token from a forged one | medium | mitigate | One indistinguishable response for every token failure; the shape is logged by exception class only |
| T-05-24 | Information Disclosure | another user's push endpoint revoked or enumerated | high | mitigate | The revoke is a single user-scoped update returning the affected id; an empty result is a 404, never a 403 |
| T-05-25 | Denial of Service | a fixed window admitting up to twice the cap across a boundary | low | accept | At 60/min in front of one indexed insert this is immaterial; a sliding window is not worth the complexity and the behaviour is documented rather than claimed away |
| T-05-SC | Tampering | package-manager installs | high | mitigate | Zero packages added; no third-party rate limiter and no phone-parsing dependency is introduced |
</threat_model>

<verification>
- `uv run pytest tests/unit -q -W error::RuntimeWarning` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- `uv run pytest tests/unit/test_no_setnx_expire_pairs.py -q` exits 0 with its non-vacuity companion covering `services/api`.
</verification>

<success_criteria>
- The 60-per-minute cap is enforced per real client and survives a forged forwarded hop.
- `Retry-After` tells a refused caller the truth, and the increment and its expiry are one atomic script.
- A phone number reaches the database only as ciphertext and can leave the system through no field and no log line.
- One Bearer function, purpose-checked, guards every management surface this phase exposes.
- A push endpoint is stored only when it is an https URL on an allowed host, and re-subscribing updates one row.
</success_criteria>

<output>
Create `.planning/phases/05-api-watchlist-crud-sse/05-03-SUMMARY.md` when done
</output>
