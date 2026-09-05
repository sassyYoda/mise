# Phase 4: Notification Pipeline - Research

**Researched:** 2026-09-05
**Domain:** Multi-channel transactional notification delivery (Resend email / Twilio SMS / VAPID Web Push) over a manual-commit Kafka consumer with Redis Layer-2 idempotency
**Confidence:** HIGH for everything executed in this repo's `.venv` (provider crypto, signature schemes, token sizing, respx/ASGI test harness, tenacity, Redis Lua, SQL shape); MEDIUM for provider REST contracts (official docs, not exercised against live accounts); LOW for the platform deep-link URL schemes (D-83, unchanged `[ASSUMED]` from Phase 1).

Every claim below tagged `[VERIFIED: transcript]` was produced by running code in `/Users/aryanahuja/projects/mise/.venv` during this session. Transcripts are reproduced inline — they are the evidence, not a summary of it.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

Copied verbatim from `04-CONTEXT.md § Implementation Decisions`. D-73..D-87 are LOCKED. Three of them cannot run exactly as written; those are named in `## Blocking Corrections to Locked Decisions` with a reproduced error, and everything else stands.

**Fan-out and matching (NOTIF-01)**

- **D-73:** `services/notifier/consumer.py` consumes `availability.events` with `AIOKafkaConsumer("availability.events", group_id="notifier", enable_auto_commit=False, max_poll_records=1)` (varargs, constructed inside `run()` — Phase 2 B-1). For each `AvailabilityEvent` it resolves the restaurant via `restaurants(source, platform_id)` → `restaurants.id` (D-52 join key) and selects `watchlist_entries` where `status='active'`, `restaurant_id` matches, `party_size == event.party_size` (exact; multi-size watches are V2-09), `date_from <= event.date <= date_to`, `time_window_from/to` (if set) contains `time_slot`, `days_of_week` (if set, comma list of `mon..sun`) contains the service weekday, `seat_type_filter` (if set) equals `seat_type`. Matching lives in a pure function `match_watches(event, rows) -> list[Match]` in `services/notifier/matching.py` (unit-tested with a parametrised matrix); the SQL only pre-filters by restaurant/status/party/date.
- **D-74:** Per-user daily cap `rate:notif:{user_id}:{YYYY-MM-DD}` (INCR + EXPIRE 172800 in one Lua/MULTI, cap `NOTIFY_DAILY_CAP_PER_USER` default 50); over-cap matches are logged `notification_rate_limited` and recorded in `notification_log` with `status='suppressed'` (no provider call).
- **D-75:** Each match yields one `NotificationQueued` message per channel in `watch.channels` (`email,sms,push`) published to `notifications.queued` with key `{watch_id}` — schema in `shared/events.py`: `job_id: UUID` (uuid5 over `notif:{watch_id}:{event_id}:{channel}` — deterministic), `watch_id`, `user_id`, `event_id`, `channel: Literal["email","sms","push"]`, `event: AvailabilityEvent` (embedded so workers need no second lookup), `queued_at_epoch_ms`. The same process consumes `notifications.queued` with a second consumer (group `notifier-workers`) and dispatches to channel workers — one service, two consumer loops (ARCHITECTURE "merged dispatcher + workers"). Kafka topic `notifications.dlq` (retention 30 d) is added to `scripts/create_topics.py` for dead letters.

**Layer-2 idempotency and offset commit (NOTIF-02, NOTIF-06)**

- **D-76:** Before any provider call the worker runs `set_nx_ex(r, notif_idempotency_key(watch_id, event_id, channel), "1", 86400)` where the key is `notif:{watch_id}:{event_id}:{channel}` — the ROADMAP SC2 key `notif:{watch_id}:{event_id}` extended by the channel suffix because one watch has up to three independent sends; the un-suffixed prefix is documented as the SC2 key family. NX failure → `notification_log` row `status='duplicate_suppressed'`, no send. Ordering per job: claim NX → provider call (with retries) → `notification_log` insert (`status='sent'|'failed'`, `provider_id`, `sent_at`, `latency_ms`) → publish `notifications.sent` → commit offset. On a *definitive* provider failure the claim is **deleted** so a later redelivery/retry can re-attempt; on crash between claim and provider ack the notification is lost for 24 h (documented trade-off — prefer a missed alert over a double send, ARCHITECTURE §Failure 3). Zero two-command `SETNX`+`EXPIRE` anywhere (extend the Phase 2 grep test to `services/notifier`).
- **D-77:** Both consumers commit manually after the message's work is durable; on handler exceptions the consumer seeks back to the failed offset (the Phase 2 CR-01 fix pattern) instead of skipping. `enable.auto.commit=false` is asserted by a unit test on the consumer factory config.

**Providers (NOTIF-03, NOTIF-04, NOTIF-05)**

- **D-78:** The `resend`, `twilio` and `pywebpush` SDKs are synchronous `requests`-based clients and are **not** imported by services. Providers are thin async clients over their REST APIs using the shared `httpx.AsyncClient` (D-05): `services/notifier/providers/{email,sms,push}.py` with `EmailProvider.send(to, subject, html, text, headers) -> ProviderResult(provider_id, status_code)`, `SmsProvider.send(to_e164, body) -> ProviderResult`, `PushProvider.send(subscription, payload) -> ProviderResult`. Resend: `POST https://api.resend.com/emails` (Bearer `RESEND_API_KEY`, from `NOTIFY_FROM_EMAIL`). Twilio: `POST https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json` (basic auth `TWILIO_ACCOUNT_SID`/`TWILIO_AUTH_TOKEN`, `MessagingServiceSid=TWILIO_MESSAGING_SERVICE_SID`, `StatusCallback` to the API webhook). Web Push: payload encryption (aes128gcm) via `pywebpush.WebPusher(...).encode(...)` (pure crypto, no network — verify in research) or `http_ece` directly, VAPID `Authorization` header via `py_vapid`/`cryptography` from `VAPID_PRIVATE_KEY`/`VAPID_SUBJECT`, delivered with httpx `POST {endpoint}` and `TTL: 60`, `Urgency: high`. Every provider base URL is env-overridable (`RESEND_API_BASE`, `TWILIO_API_BASE`) so tests point `respx` at them.
- **D-79:** Retries with `tenacity`: email 3 attempts (exp backoff 1–8 s) then dead-letter to `notifications.dlq` + `notification_log.status='failed'`; SMS 2 attempts then `failed` + a fallback email to the user (`sms_failed_fallback` template) when email is one of the watch's channels; push: on 404/410 mark `push_subscriptions.revoked_at` and fall back to email; on other failures 2 attempts then `failed`. Provider 429 honours `Retry-After` via tenacity wait (no bare `asyncio.sleep` loops outside tenacity's wait — the no-sleep gate is scoped to explicit `asyncio.sleep(` calls in `services/notifier`, tenacity's internal sleep is allowed and documented).
- **D-80:** Channel enablement is env-driven: a provider is constructed only when its credentials are present; a job for a disabled channel is recorded `status='failed'`, `error='provider_unconfigured'` (and still counts toward the idempotency claim being deleted so it can be retried once configured). `NOTIFY_DRY_RUN=true` short-circuits every provider with a fake `provider_id='dry-run-<job_id>'`, records `sent`, and logs the rendered message — the local demo path.
- **D-81:** Templates in `services/notifier/templates.py` using `string.Template` (no new deps): email HTML + text (restaurant, date/time, party size, seat type, "Book now" CTA = `/go/{token}`, estimated-window line when the pattern hook returns text, unsubscribe footer = `/unsubscribe/{token}` + `List-Unsubscribe` / `List-Unsubscribe-Post: List-Unsubscribe=One-Click` headers); SMS ≤ 160 chars (`"{restaurant} {date} {time} party of {n} — book: {short /go link}  Reply STOP to opt out"`, asserted ≤ 160 with the longest seeded name); push JSON `{title, body, url, tag=event_id}`. The estimated-window text comes from `services/notifier/pattern_hook.py :: estimate_window_text(source, restaurant_id) -> str | None` which returns `None` in this phase (Phase 6 PATTERN-03 implements it) — templates omit the line when `None`.

**Signed links, `/go/[token]`, unsubscribe, STOP webhook (NOTIF-04, NOTIF-07, PERF-03)**

- **D-82:** `shared/tokens.py`: versioned HMAC-SHA256 tokens `base64url(json payload) + "." + base64url(hmac)` with payload `{v: token_version, p: purpose, ...claims, iat, exp}`; secrets from `HMAC_MGMT_SECRET_V{n}` env (current version `HMAC_TOKEN_VERSION`, default 1); verification accepts the current and previous version during a grace window (`HMAC_GRACE_UNTIL` ISO date) — this is the Phase 5 WATCH-03 rotation contract, defined here because deep links and unsubscribe links need it now. Purposes used in this phase: `go`, `unsubscribe`, `sms_stop` (Phase 5 adds `manage`).
- **D-83:** Deep links: `shared/links.py :: platform_booking_url(source, platform_id, slug, date, party_size, time_slot) -> str` — OpenTable `https://www.opentable.com/restref/client/?rid={rid}&datetime={date}T{HH:MM}&covers={party}` and Resy `https://resy.com/cities/ny/{slug}?date={date}&seats={party}` (both `[ASSUMED]` URL schemes, documented with `TODO(spike)` markers; unit-tested for shape). Every channel links to `{PUBLIC_BASE_URL}/go/{token}` where the `go` token carries `{notification_log_id, event_id, watch_id}`.
- **D-84:** Phase 4 creates the FastAPI application skeleton that Phase 5 extends: `services/api/app.py :: create_app()` with routers `services/api/routers/links.py` (`GET /go/{token}` → verify token, set `notification_log.clicked_at`, compute `slot_still_available` by reading the Phase 2 Redis slot record (`AVAILABLE` → true, else false), persist it, then `302` to the platform URL when available or `200` with a minimal "sorry, that table is gone" HTML (Phase 6 restyles it); `GET|POST /unsubscribe/{token}` → set the watch `status='paused'` (and `users.sms_opt_out=true` when purpose is `sms_stop`), idempotent) and `services/api/routers/webhooks.py` (`POST /webhooks/twilio/inbound` — validates `X-Twilio-Signature` per Twilio's HMAC-SHA1 scheme in `shared/twilio_signature.py` (no SDK), matches the sender by `users.phone_hash`, flips every active watch of that user to `status='paused'` and sets `sms_opt_out`, replies TwiML `<Response/>`; `POST /webhooks/twilio/status` — records `delivered_at`/`status='delivered'|'failed'` on `notification_log` by `provider_id`; `POST /webhooks/resend` — `email.delivered`/`email.bounced` → same columns, signature verified with `RESEND_WEBHOOK_SECRET` (Svix HMAC) when set). Served by `uvicorn services.api.app:app`; `make api`. Phase 5 adds `/watches`, `/api/feed/live`, `/admin`, `/api/metrics`. The SC4 "within 5 seconds" is met by doing the DB write synchronously in the request.
- **D-85:** Migration 0010: `users.phone_hash TEXT` (HMAC-SHA256 of E.164 with `PHONE_HASH_SECRET`, unique index, nullable) + `users.sms_opt_out BOOLEAN NOT NULL DEFAULT false`; new table `push_subscriptions(id, user_id FK, endpoint TEXT UNIQUE, p256dh TEXT, auth TEXT, user_agent TEXT, created_at, revoked_at NULL)`; `notification_log.latency_ms INTEGER NULL`, `notification_log.error TEXT NULL`; `notification_log.status` values documented: `queued|sent|delivered|clicked|failed|suppressed|duplicate_suppressed`. `shared/crypto.py :: encrypt_phone(e164) -> bytes / decrypt_phone(bytes) -> str` implements **AES-256-GCM via `cryptography`** with key `PHONE_ENCRYPTION_KEY` (32-byte base64) — pgcrypto has no GCM mode, so WATCH-05's "AES-256-GCM via pgcrypto" is satisfied at the application layer with the ciphertext in the existing BYTEA column (documented deviation; Phase 5 writes with `encrypt_phone`, this phase decrypts only inside `SmsProvider` at send time).

**Latency and false-positive measurement (PERF-01, PERF-03)**

- **D-86:** `NotificationSent` (`shared/events.py`): `job_id, watch_id, user_id, event_id, channel, status, provider_id, sent_at_epoch_ms, event_produced_at_epoch_ms, latency_ms` published to `notifications.sent` (key `{watch_id}`); `latency_ms = sent_at - event.produced_at_epoch_ms` (D-45: detection timestamp). Prometheus (`shared/metrics.py`): `notification_latency_seconds{channel}` histogram, `notifications_total{channel,status}` counter, `notification_delivery_rate` derived in Grafana. `scripts/check_notification_latency.py` prints p50/p95 per channel over a window from `notification_log.latency_ms` and exits 0 iff overall p95 <= 60 s, SMS p95 <= 10 s, push p95 <= 5 s (exit 2 when < 100 samples); `scripts/check_false_positive_rate.py` computes daily `slot_still_available=false / clicked` and exits 0 iff < 2 %. The 24 h production measurement is pending-human (`docs/runbooks/perf01-latency.md`).

**Test strategy**

- **D-87:** Unit: matching matrix, templates (SMS ≤ 160), token sign/verify/rotation/expiry, link builders, Twilio signature, phone crypto round-trip, provider request shapes via `respx` (Resend/Twilio/push endpoint incl. 404/410 revocation), idempotency ordering with a fake provider, no-sleep and no-SETNX grep gates. Integration (testcontainers + respx): `availability.events` → matched watch (seeded users/watches through the ORM) → `notifications.queued` → `notifications.sent` + `notification_log` row with `latency_ms`; chaos: subprocess notifier with `MISE_CRASH_AFTER=provider_ack` (SIGKILL after the mocked provider returns 2xx, before commit) → restart → exactly one provider call and one `sent` row per (watch, channel); API routes via `httpx.AsyncClient(transport=ASGITransport(app))` for `/go`, `/unsubscribe`, `/webhooks/twilio/inbound` (STOP flips the watch within one request). `docs/runbooks/ios-pwa-push.md` and `docs/runbooks/perf01-latency.md` carry `STATUS: pending-human`.

### Claude's Discretion

- Exact template wording, subject lines, `string.Template` layout; provider timeout values (5 s connect / 10 s read default); histogram buckets.
- Whether the two consumer loops share one `AIOKafkaProducer` (they should — one producer per process, D-02).
- Internal module split of `services/notifier/` (`consumer.py`, `dispatcher.py`, `workers.py`, `providers/`, `templates.py`, `matching.py`, `persistence.py`, `main.py`, `config.py` is the suggested shape).

### Deferred Ideas (OUT OF SCOPE)

- Multi-party-size watches (V2-09); per-channel quiet hours; SMS link shortener (use the `/go` token as-is; keep it short by using a compact token payload).
- Push subscription registration endpoint + service worker — Phase 5 API / Phase 6 PWA.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| NOTIF-01 | Dispatcher consumes `availability.events`, queries watchlist for matching watches, enqueues per-channel jobs to `notifications.queued` | `## Fan-out SQL and Matching` — compiled pre-filter SQL `[VERIFIED: transcript]`, the `int` vs `TEXT` platform-id join hazard (Pitfall 6), pure-function matching split, `NotificationQueued` schema alignment with `shared/events.py` field-order convention |
| NOTIF-02 | `SET NX EX` on `notif:{watch_id}:{event_id}` (24 h TTL) prevents duplicates on redelivery | `## Layer-2 Idempotency, Rate Limit and Commit` — `set_nx_ex` claim/reclaim proven against real Redis 7.2.16 `[VERIFIED: transcript]`; Layer-3 DB + provider-side backstops recommended |
| NOTIF-03 | Email via Resend, HTML template, retries 3× then dead-letter | `## Provider Contracts § Resend`, `## Retries` — `POST /emails` body/headers/response/error codes `[CITED]`, `Idempotency-Key` header found, tenacity 3-attempt loop `[VERIFIED: transcript]` |
| NOTIF-04 | SMS via Twilio ≤ 160 chars, ≤ 10 s SLA, STOP webhook, retries 2× then failure + email | `## Provider Contracts § Twilio`, `## SMS Length Budget (measured)`, `## Twilio Inbound Signature` — signature reproduces Twilio's published vector `[VERIFIED: transcript]`; BC-2 corrects the 160-char template |
| NOTIF-05 | Web Push via VAPID, ≤ 5 s SLA, invalid-subscription → email fallback | `## Provider Contracts § Web Push` — aes128gcm payload built and round-trip decrypted without network I/O `[VERIFIED: transcript]`; 404/410 revocation semantics `[CITED: RFC 8030]`; Apple VAPID constraints |
| NOTIF-06 | Manual offset commit only after provider ack; `notification_log` status transitions | `## Consumer Shell` — the Phase 2 seek-back/commit pattern reproduced verbatim from `services/state_machine/consumer.py`; `MISE_CRASH_AFTER` ENV allowlist; migration 0010 status vocabulary |
| NOTIF-07 | Deep-link generator + `mise.place/go/[token]` redirect with click tracking and "too slow" fallback | `## Signed Tokens (measured)`, `## Deep Links` — token sizing measured, `/go` route + 302 verified in-process `[VERIFIED: transcript]`; platform URL schemes remain `[ASSUMED]` |
| PERF-01 | p95 detection→notification latency ≤ 60 s | `## Latency Budget and Measurement` — `latency_ms` source-of-truth, Prometheus naming gotcha, `check_notification_latency.py` exit-code contract mirrored from `scripts/check_poll_success.py` |
| PERF-03 | False-positive rate < 2 % daily | `## `/go` and slot_still_available` — Redis slot read via `RedisStateStore.get_slots`, `check_false_positive_rate.py` denominator definition |
</phase_requirements>

---

## Summary

Phase 4 is a **provider-integration and crash-ordering** phase, not an algorithms phase. The hard parts are all boundaries: three third-party HTTP contracts, two inbound webhook signature schemes, one payload-encryption standard, and a claim-then-send ordering that must survive `kill -9`. Everything the phase needs is already installed in `.venv` — the phase adds no runtime dependency, and it must not add one (see BC-3, which is precisely the temptation to add `python-multipart`).

The single largest risk is the one D-78 already half-anticipated: `import pywebpush` drags `requests`, `aiohttp` and `urllib3` into the process. The clean route — `http_ece.encrypt(...)` for the aes128gcm body and `py_vapid.Vapid.from_string(...).sign(...)` for the `Authorization` header — was executed end to end this session and produces a payload that round-trip decrypts with the subscriber's private key, importing neither `requests` nor `aiohttp`. That makes the async-only CI gate honest rather than nominally satisfied.

The second largest risk is measurement dishonesty. Two success criteria (PERF-01's 24 h window, the real-iPhone push test) are human-gated, and one (SC2, zero duplicate sends at provider-SID level) is provable today with `respx`'s per-route `call_count` as the SID oracle. The phase should ship the SC2 proof as a real subprocess SIGKILL chaos test — exactly the Phase 2 shape — and ship the PERF-01/PERF-03 scripts with the same three-way exit-code contract `scripts/check_poll_success.py` already uses, so "not enough data" (exit 2) is never confusable with "passed" (exit 0).

**Primary recommendation:** Build `services/notifier/` as a copy of the Phase 2 consumer's *shape* — lazy env accessors, `AsyncExitStack` lifespan, `run_until_signal`, seek-back-on-transient-failure, `_maybe_crash` behind the `CRASH_HOOK_ENVS` allowlist — with three thin `httpx` provider clients that never import a vendor SDK, and prove SC2 with a `respx` call-count oracle inside a real SIGKILL subprocess test.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Event → watchlist fan-out | Backend consumer (`services/notifier/consumer.py`) | Database (pre-filter SQL) | The SQL narrows by restaurant/status/party/date; the residual predicates (time window, days-of-week, seat type) are pure Python so they are unit-testable as a matrix without a database (D-73) |
| Duplicate suppression | Redis (Layer-2 `SET NX EX`) | Database (recommended UNIQUE), Provider (`Idempotency-Key`) | Redis is the only store the worker touches *before* the provider call; DB and provider keys are backstops for the window Redis cannot cover |
| Per-user rate limiting | Redis (Lua INCR+EXPIRE) | — | Must be atomic and expiring; a DB counter adds a write to the hot path for no gain |
| Payload encryption (push) | Backend worker (`http_ece` + `cryptography`) | — | Pure CPU, no network; belongs beside the sender, never in a browser tier |
| Provider delivery | Backend worker (`httpx.AsyncClient` singleton) | — | The shared client owns pooling (Pitfall 9); providers are stateless functions over it |
| Webhook signature verification | API tier (`services/api/routers/webhooks.py`) | `shared/` (pure verifier functions) | The verifier must be a pure function over `(secret, url/body, headers)` so it is testable against published vectors without an HTTP server |
| Click tracking + `slot_still_available` | API tier (`GET /go/{token}`) | Redis (Phase 2 slot store), Database (`notification_log`) | SC4/SC5 require the write to be synchronous in the request; reading Phase 2's Redis record is the only live availability source in-process |
| Unsubscribe / STOP | API tier | Database (`watchlist_entries.status`, `users.sms_opt_out`) | Compliance-critical and must complete inside the request (SC4 "within 5 seconds") |
| Latency / false-positive measurement | Scripts tier (`scripts/check_*.py`) | Database (`notification_log`) | Batch analysis over durable rows; never on the hot path |

---

## Blocking Corrections to Locked Decisions

Three locked decisions cannot be executed exactly as written. Each is reproduced as a real error below, with the smallest correction that preserves the decision's intent.

### BC-1 — D-78: `pywebpush.WebPusher(...).encode(...)` cannot be used from `services/`

**The decision says two incompatible things.** D-78's first sentence: "The `resend`, `twilio` and `pywebpush` SDKs are synchronous `requests`-based clients and are **not** imported by services." Its Web Push clause then offers `pywebpush.WebPusher(...).encode(...)` as the encryption route. Importing `pywebpush` at all violates the first sentence and the CLAUDE.md async-only gate.

**Reproduced** `[VERIFIED: transcript]` — one fresh interpreter per module, checking `sys.modules` after import:

```
py_vapid                                           -> clean
http_ece                                           -> clean
cryptography.hazmat.primitives.ciphers.aead        -> clean
resend                                             -> ['requests', 'urllib3']
twilio.rest                                        -> ['requests', 'urllib3']
pywebpush                                          -> ['requests', 'aiohttp', 'urllib3']
```

`pywebpush/__init__.py` lines 18–24, read this session:

```python
import aiohttp
import http_ece
import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from functools import partial
from py_vapid import Vapid, Vapid01
from requests import Response
```

**Correction:** take the `or http_ece directly` branch D-78 already permits, and make it the only branch. `services/notifier/providers/push.py` imports `http_ece`, `py_vapid` and `cryptography` — never `pywebpush`. `WebPusher.encode` for `content_encoding="aes128gcm"` is a nine-line wrapper around `http_ece.encrypt(data, salt=None, private_key=<ephemeral P-256>, dh=<p256dh>, auth_secret=<auth>, version="aes128gcm")` returning `{"body": <bytes>}` (source read this session), so the direct call is not a reimplementation — it is the same call without the import cost.

Proven equivalent and network-free `[VERIFIED: transcript]`:

```
ciphertext len: 217
requests in sys.modules? False
aiohttp  in sys.modules? False
round-trip OK: True
```

(The same 217-byte length as `WebPusher(sub).encode(payload, content_encoding="aes128gcm")` produced for the identical payload; the `pywebpush` route was additionally decrypted back to the original bytes with `http_ece.decrypt` to confirm both paths are the same RFC 8188 record.)

`pywebpush==2.3.0` stays pinned in `pyproject.toml` — it is a legitimate reference implementation and its `encode` may be used from `tests/` as a cross-check oracle. It just may not be imported from `services/` or `shared/`. Recommend a new grep gate (`tests/unit/test_no_sync_sdk_imports.py`) asserting `pywebpush|resend|twilio` appear in no `services/**` or `shared/**` module.

### BC-2 — D-81: the SMS template cannot be ≤ 160 characters, and its em dash silently halves the segment size

Two independent defects in the literal template
`"{restaurant} {date} {time} party of {n} — book: {short /go link}  Reply STOP to opt out"`.

**Defect A — the em dash forces UCS-2.** `—` (U+2014) is not in the GSM 03.38 basic or extension table, so a message containing it is encoded UCS-2 and the single-segment limit drops from 160 to **70** characters. Measured against the GSM 03.38 tables `[VERIFIED: transcript]`:

```
  em dash U+2014             gsm7=NO -> UCS-2
  en dash U+2013             gsm7=NO -> UCS-2
  middot U+00B7              gsm7=NO -> UCS-2
  curly apostrophe U+2019    gsm7=NO -> UCS-2
  hyphen                     gsm7=yes
  apostrophe                 gsm7=yes
```

**Defect B — it does not fit even after the dash is fixed.** The longest name in `scripts/seed/restaurants.yml` is `Mission Chinese Food` (20 chars; all 55 seeded names are GSM-7 representable). With the smallest D-82-shaped `go` token that still carries a full 32-byte HMAC:

```
A (D-81 literal, hyphen, https)    chars=163 gsm7=yes septets=163 fits160=no
     Mission Chinese Food 2026-05-01 7:30 PM party of 2 - book: https://mise.place/go/eyJuIjoxMjM0NTYsInAiOiJnbyIsInYiOjF9.iLhWhxPUQNEfFMUDoLIuTQ  Reply STOP to opt out
```

163 septets with a *16-byte truncated* signature. With the full 32-byte signature it is 184.

**Correction** — three edits, each preserving the decision's content requirements (restaurant, date, time, party size, `/go` link, STOP instruction):

1. Replace `—` with ` - ` (ASCII hyphen). Non-negotiable: it is the difference between 160 and 70.
2. Drop the URL scheme. `mise.place/go/{token}` instead of `https://mise.place/go/{token}` saves 8 characters; every mobile SMS client autolinks a bare host.
3. Drop `exp` (and `iat`) from the **`go`** token payload only. The `/go` link's lifetime is already bounded by the `notification_log` row it names — the route can reject a click older than N hours from `notification_log.created_at`. Purposes `unsubscribe` and `sms_stop` keep `exp` per D-82.

Measured result, longest seeded name, **full 32-byte HMAC, no truncation** `[VERIFIED: transcript]`:

```
C (no scheme, 32B sig)             chars=153 gsm7=yes septets=153 fits160=YES
     Mission Chinese Food 5/1 7:30PM x2 - mise.place/go/eyJuIjoxMjM0NTYsInAiOiJnbyIsInYiOjF9.iLhWhxPUQNEfFMUDoLIuTZF-J2WkPDIFlSkCi11KB7s Reply STOP to opt out
```

Headroom is 7 septets, which is thin. Two guards the planner must include:

- `render_sms()` hard-truncates the restaurant name so the rendered body is bounded by construction, and the unit test asserts `≤ 160 septets` across **all 55 seeded names** *and* a 10-digit `notification_log.id` (an 8-digit id costs +3 chars → 156; a 10-digit id costs +5 → 158).
- The test computes the link from the configured `PUBLIC_BASE_URL` host, not from the literal `mise.place` — a longer host is the most likely way this regresses.

An alternative that buys ~20 more septets, if the planner wants margin: give the `go` token an opaque form (`base64url(16 random bytes)` stored on the `notification_log` row) rather than the signed-payload form. That breaks the D-82 uniform token shape, so it is **not** recommended — recorded here only so the trade-off is on the record.

### BC-3 — D-84: `await request.form()` raises under the pinned Starlette, and `python-multipart` is not a dependency

D-84 requires `POST /webhooks/twilio/inbound` to read the form fields `From`, `Body`. Both the FastAPI `Form(...)` parameter style and Starlette's `Request.form()` fail on the pinned stack, **even for `application/x-www-form-urlencoded`** (Twilio's actual content type — no multipart involved).

`Form(...)` fails at route-registration time `[VERIFIED: transcript]`:

```
RuntimeError: Form data requires "python-multipart" to be installed.
  File ".../fastapi/dependencies/utils.py", line 120, in ensure_multipart_is_installed
```

`await request.form()` fails at request time `[VERIFIED: transcript]`:

```
  File ".../starlette/requests.py", line 270, in _get_form
    assert parse_options_header is not None, (
AssertionError: The `python-multipart` library must be installed to use form parsing.
```

`python-multipart` is absent from `pyproject.toml` and from `.venv`:

```
importlib.metadata.PackageNotFoundError: No package metadata was found for python-multipart
```

**Correction:** parse the urlencoded body directly and add no dependency.

```python
from urllib.parse import parse_qsl

raw = await request.body()
params: dict[str, str] = dict(parse_qsl(raw.decode(), keep_blank_values=True))
```

This is strictly better than adding the dependency, because Twilio's signature scheme is computed over *exactly* the POST parameters as sent — `parse_qsl` over the raw body is the same dict the verifier needs, with no framework coercion in between. Verified in-process against a FastAPI app over `httpx.ASGITransport` `[VERIFIED: transcript]`:

```
POST twilio inbound -> 200 <Response/>
   sig: abc123= params: {'From': '+15551234567', 'Body': 'STOP', 'MessageSid': 'SM1'}
```

Add `tests/unit/test_no_new_runtime_deps.py` asserting `python-multipart` stays out of `pyproject.toml` `[project].dependencies`, so a later executor cannot "fix" this by installing it.

---

## Standard Stack

Nothing new is installed. Every version below was read from `.venv` this session via `importlib.metadata.version` `[VERIFIED: transcript]`.

### Core (already pinned — use these)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `httpx` | 0.28.1 | All three provider calls, through `shared.http_client.get_async_client()` | D-05/D-78; one pooled client per process (Pitfall 9). Per-call `timeout=` override is supported and is how the push 5 s SLA is enforced |
| `tenacity` | 9.1.4 | Async retry with exponential backoff and `Retry-After` | D-79. `AsyncRetrying` and the `@retry` decorator both verified over an `httpx` call |
| `http_ece` | 1.2.1 | RFC 8188 `aes128gcm` payload encryption for Web Push | Imports nothing but `cryptography`; `pywebpush.encode` is a wrapper over it (BC-1) |
| `py_vapid` | 1.9.4 | VAPID `Authorization: vapid t=…,k=…` header | Works with `cryptography` 46.0.7 — the Phase 1 incompatibility note applies to *keypair generation*, not to `from_string`/`sign` (see Pitfall 1) |
| `cryptography` | 46.0.7 | `AESGCM` phone encryption, P-256 ephemeral keys | D-85. `AESGCM` is the only GCM primitive in play; pgcrypto has none |
| `redis` (asyncio) | 7.4.0 | Layer-2 claim, per-user rate-limit Lua, `/go` slot read | Server pinned at `redis:7.2-alpine`; Lua and `SET NX EX` verified against 7.2.16 |
| `aiokafka` | 0.13.0 | Two manual-commit consumer loops + one shared producer | `shared.kafka.make_consumer/make_producer` already set `enable_auto_commit=False`, `max_poll_records=1` |
| `sqlalchemy[asyncio]` | 2.0.49 | Fan-out pre-filter, `notification_log` writes | Core `select()` only — no relationship loading needed (see Fan-out SQL) |
| `fastapi` / `starlette` / `uvicorn` | 0.136.0 / 0.52.1 / 0.44.0 | `services/api/` skeleton | D-84. Note BC-3 |
| `pydantic` | 2.13.3 | `NotificationQueued`, `NotificationSent` | `shared/events.py` convention: `frozen=True, extra="forbid"`, declaration order is wire order |
| `prometheus-client` | 0.25.0 | `notification_latency_seconds`, `notifications_total` | Extends Phase 3's `shared/metrics.py` — must not redefine (Pitfall 8) |

### Test-only

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `respx` | 0.23.1 | Mock all three provider endpoints; `route.call_count` is the SC2 duplicate oracle | Every provider unit test and the integration/chaos tests |
| `pytest-asyncio` | 1.3.0 | `asyncio_mode = "auto"` is set in `pyproject.toml` — no `@pytest.mark.asyncio` needed | All async tests |
| `testcontainers` | ≥4.8 | Kafka / Redis 7.2 / TimescaleDB, module-scoped fixtures in `tests/conftest.py` | Integration tier |
| `twilio` | 9.10.5 | **Test-only** cross-check of `shared/twilio_signature.py` against `RequestValidator` | Allowed in `tests/`; forbidden in `services/`/`shared/` |
| `pywebpush` | 2.3.0 | **Test-only** cross-check of the `http_ece` encryption path | Same |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `http_ece` direct | `pywebpush.WebPusher.encode` | Identical output, but drags `requests`+`aiohttp`+`urllib3` into the service (BC-1). Rejected |
| `parse_qsl` on the raw body | `python-multipart` + `Request.form()` | One new runtime dependency, and it hands you a coerced `FormData` that then has to be flattened back for signature verification. Rejected (BC-3) |
| `svix` library for Resend webhooks | 12-line manual verifier | New dependency for an algorithm that fits in a function and is validated against two published vectors. Rejected |
| Lua for the daily cap | `MULTI`/`EXEC` pipeline | The pipeline form must issue an unconditional `EXPIRE`, which refreshes the window on *every* increment and silently turns a calendar-day cap into a sliding 48 h cap. Lua with `if n == 1 then EXPIRE` is correct — see Pitfall 4 |
| Signed-payload `/go` token | Opaque random token + DB lookup | ~20 more SMS septets of headroom, at the cost of breaking D-82's uniform token shape and adding a DB read to the redirect. Not recommended |

**Installation:** none. `uv sync` is unchanged; the phase adds zero packages.

**Version verification transcript** `[VERIFIED: transcript]`:

```
fastapi              0.136.0      pywebpush            2.3.0
uvicorn              0.44.0       py_vapid             1.9.4
httpx                0.28.1       http_ece             1.2.1
tenacity             9.1.4        resend               2.29.0
cryptography         46.0.7       twilio               9.10.5
sqlalchemy           2.0.49       redis                7.4.0
aiokafka             0.13.0       pydantic             2.13.3
respx                0.23.1       pytest-asyncio       1.3.0
starlette            0.52.1       requests             2.33.1 (transitive; must not reach services/)
python-multipart     NOT INSTALLED
Python 3.12.13
```

---

## Package Legitimacy Audit

This phase installs **no** external packages. Every library it uses is already pinned in `pyproject.toml` and present in `.venv`, verified by `importlib.metadata.version` above. There is therefore no new-package attack surface and no `package-legitimacy check` to run.

| Package | Registry | Status | Verdict | Disposition |
|---------|----------|--------|---------|-------------|
| *(none added)* | — | — | — | — |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none
**Package the phase must NOT add:** `python-multipart` — see BC-3. The correct fix adds no dependency.

---

## Architecture Patterns

### System Architecture Diagram

```
                  Kafka: availability.events  (Phase 2 producer, key {source}:{rid})
                                 │
                                 ▼
        ┌────────────────────────────────────────────────────────────────┐
        │  services/notifier  (ONE process, TWO consumer loops,          │
        │                      ONE shared AIOKafkaProducer — D-02)       │
        │                                                                │
        │  loop A: consumer.py   group_id="notifier"                     │
        │    getone() ──▶ AvailabilityEvent.model_validate_json          │
        │            │                                                   │
        │            ├──▶ Postgres: pre-filter SELECT ─────────────┐     │
        │            │      restaurants(source, platform_id)        │     │
        │            │      ⋈ watchlist_entries(active,party,date)  │     │
        │            │      ⋈ users                                 │     │
        │            │                                              ▼     │
        │            ├──▶ matching.match_watches(event, rows)  [PURE]    │
        │            │      time-window / days-of-week / seat-type       │
        │            │                                                   │
        │            ├──▶ Redis: rate:notif:{uid}:{YYYY-MM-DD} Lua       │
        │            │      over cap ──▶ notification_log status=        │
        │            │                   'suppressed'  (no send)         │
        │            │                                                   │
        │            ├──▶ producer.send_and_wait("notifications.queued") │
        │            │      one NotificationQueued per channel, key=wid  │
        │            └──▶ consumer.commit({tp: offset+1})                │
        │                                                                │
        │  loop B: workers.py    group_id="notifier-workers"             │
        │    getone() ──▶ NotificationQueued                             │
        │            │                                                   │
        │            ├─(1)▶ Redis SET NX EX notif:{wid}:{eid}:{chan} 24h │
        │            │        NX fail ──▶ log 'duplicate_suppressed',    │
        │            │                    commit, done                   │
        │            │                                                   │
        │            ├─(2)▶ templates.render_{email,sms,push}            │
        │            │        └─ tokens.sign(purpose='go' | 'unsub')     │
        │            │        └─ links.platform_booking_url(...)         │
        │            │                                                   │
        │            ├─(3)▶ providers/*.send()  via shared httpx client  │
        │            │        ┌──────────┬──────────────┬─────────────┐  │
        │            │        │ Resend   │ Twilio       │ Web Push    │  │
        │            │        │ POST     │ POST         │ POST        │  │
        │            │        │ /emails  │ Messages.json│ {endpoint}  │  │
        │            │        │ →  id    │ → sid        │ → 201       │  │
        │            │        └──────────┴──────────────┴─────────────┘  │
        │            │        tenacity: 3 / 2 / 2 attempts, Retry-After  │
        │            │        404|410 ──▶ push_subscriptions.revoked_at  │
        │            │                    ──▶ email fallback             │
        │            │        definitive failure ──▶ DEL claim           │
        │            │                          ──▶ notifications.dlq    │
        │            │        ◀── MISE_CRASH_AFTER=provider_ack SIGKILL  │
        │            │                                                   │
        │            ├─(4)▶ Postgres notification_log INSERT             │
        │            │        status, provider_id, sent_at, latency_ms   │
        │            ├─(5)▶ producer.send_and_wait("notifications.sent") │
        │            └─(6)▶ consumer.commit({tp: offset+1})   ◀── LAST   │
        └────────────────────────────────────────────────────────────────┘
                    │                                    │
                    ▼                                    ▼
        Kafka: notifications.sent            Kafka: notifications.dlq (30 d)
        (Phase 5 SSE, Phase 7 Grafana)

        ┌────────────────────────────────────────────────────────────────┐
        │  services/api  (uvicorn, separate process — `make api`)        │
        │                                                                │
        │  GET  /go/{token} ──▶ tokens.verify ──▶ notification_log       │
        │        │                                  .clicked_at = now    │
        │        ├──▶ Redis avail:{rid}:{date}:{party} HGETALL           │
        │        │      state == AVAILABLE ? true : false                │
        │        │      ──▶ notification_log.slot_still_available        │
        │        ├── available ──▶ 302 platform_booking_url(...)         │
        │        └── gone      ──▶ 200 "sorry, that table is gone"       │
        │                                                                │
        │  GET  /unsubscribe/{token} ──▶ confirm page (see OQ-2)         │
        │  POST /unsubscribe/{token} ──▶ watch.status='paused'           │
        │                                users.sms_opt_out=true          │
        │                                (RFC 8058 one-click body)       │
        │                                                                │
        │  POST /webhooks/twilio/inbound                                 │
        │        raw body ──▶ parse_qsl ──▶ X-Twilio-Signature verify    │
        │        Body=="STOP" ──▶ users by phone_hash ──▶ pause all      │
        │        ──▶ 200 "<Response/>"  (TwiML)                          │
        │  POST /webhooks/twilio/status ──▶ by provider_id (sid)         │
        │  POST /webhooks/resend ──▶ svix-id/timestamp/signature verify  │
        │        email.delivered|email.bounced ──▶ by provider_id        │
        └────────────────────────────────────────────────────────────────┘

        scripts/check_notification_latency.py  ──reads──▶ notification_log.latency_ms
        scripts/check_false_positive_rate.py   ──reads──▶ notification_log.slot_still_available
```

### Component Responsibilities

| File | Responsibility | Must not |
|------|----------------|----------|
| `services/notifier/config.py` | Lazy env accessors (functions, never module constants), `CONSUMER_GROUP_ID`, `WORKER_GROUP_ID`, `CRASH_HOOK_ENVS` re-use, `crash_after()` | Read env at import (the `services/poller/config.py` freeze defect, 02-02 deviation 1) |
| `services/notifier/matching.py` | Pure `match_watches(event, rows) -> list[Match]` | Touch Redis, Postgres, the clock, or `random` |
| `services/notifier/persistence.py` | `notification_log` insert/update, watch pre-filter SELECT | Block the Kafka commit on a Postgres stall (mirror D-48 best-effort where the row is analytics; the `sent` row is **not** best-effort — see Pitfall 3) |
| `services/notifier/providers/{email,sms,push}.py` | One `send()` each, `ProviderResult(provider_id, status_code)` | Import `resend`, `twilio`, `pywebpush` (BC-1); construct their own `httpx.AsyncClient` |
| `services/notifier/templates.py` | `string.Template` render for three channels | Emit non-GSM-7 characters into the SMS body (BC-2) |
| `shared/tokens.py` | Versioned HMAC sign/verify, constant-time compare | Use `==` on a signature |
| `shared/twilio_signature.py` | Pure `twilio_signature(auth_token, url, params) -> str` | Import the Twilio SDK |
| `shared/svix_signature.py` | Pure Svix v1 verifier | Import `svix` |
| `shared/crypto.py` | `encrypt_phone` / `decrypt_phone` (AES-256-GCM), `phone_hash` (HMAC-SHA256) | Reuse a nonce; log a plaintext number |
| `shared/links.py` | `platform_booking_url(...)` | Pretend the URL schemes are verified (they are `[ASSUMED]`) |

### Pattern 1: claim → send → record → publish → commit

The Phase 2 consumer already encodes this ordering for events; Phase 4 repeats it for sends. Reproduced verbatim from `services/state_machine/consumer.py:343-398` (read this session):

```python
    async def _apply_emit(self, decision: Emit) -> None:
        """One confirmed emission, in the D-46 order: claim, send, persist, record."""
        ...
        claimed = await set_nx_ex(self.r, claim_key, "1", EVENT_IDEMPOTENCY_TTL_SECONDS)
        _maybe_crash("nx_claim")
        if not claimed and not await self._crashed_mid_emit(decision):
            ...
            return
        await self.producer.send_and_wait(...)
        _maybe_crash("kafka_send")
```

**When to use:** every notification job. **Why `send_and_wait` and not `send`:** `shared/kafka.py:33` sets `linger_ms=20`, so a bare `send` can return before the broker acks and the offset commit would overtake the record.

### Pattern 2: seek-back on transient failure, commit on poison

Reproduced from `services/state_machine/consumer.py:215-250`:

```python
        topic_partition = TopicPartition(msg.topic, msg.partition)
        try:
            self.consumer.seek(topic_partition, msg.offset)
            self.consumer.pause(topic_partition)
        except (KafkaError, ValueError) as exc:
            ...
        self._resume_handles[topic_partition] = asyncio.get_running_loop().call_later(
            TRANSIENT_RETRY_BACKOFF_SECONDS, self._resume_partition, topic_partition
        )
```

**Why it matters here more than in Phase 2:** merely *not committing* is insufficient — the consumer position has already advanced, so the next message's `commit(offset + 1)` moves the watermark past the failed offset and the notification is lost silently. The `pause`/`call_later(resume)` pair is also how the notifier avoids `asyncio.sleep` while still backing off (STATE.md records this as the reason the primitive was chosen).

**Poison tuple:** Phase 2's blocker note warns "any exception escaping `process()` that is not in the poison tuple loops forever by design; keep the poison tuple complete when adding parsers." Phase 4's poison set is `(ValidationError,)` for an undecodable `NotificationQueued`, plus a `TemplateRenderError` if templates can raise. A 4xx from a provider is **not** poison at the Kafka layer — it is a definitive failure that dead-letters and then commits.

### Pattern 3: `MISE_CRASH_AFTER` behind a fail-closed ENV allowlist

The hook is already built. `services/state_machine/config.py:68-85`:

```python
CRASH_HOOK_ENVS: frozenset[str] = frozenset({"dev", "test", "ci", "local"})


def crash_hook_allowed() -> bool:
    raw = os.getenv("ENV")
    return raw is not None and raw.strip().lower() in CRASH_HOOK_ENVS


def crash_after() -> str | None:
    """TEST ONLY (D-51): stage after which the consumer SIGKILLs itself. Unset everywhere else."""
    return os.getenv("MISE_CRASH_AFTER")
```

and `services/state_machine/main.py:82-88` refuses to start when the hook is set and `ENV` is not explicitly allowlisted. **Phase 4 must import `CRASH_HOOK_ENVS` and `crash_hook_allowed` from a shared location rather than copying them** — Phase 2's CR fix notes that "two readers of a single safety-critical variable is one too many." Recommendation: move both into `shared/` (e.g. `shared/crash_hook.py`) and have `services/state_machine/config.py` re-export, or have `services/notifier/config.py` import from `services.state_machine.config`. The former is cleaner; the latter creates a service→service import the repo has otherwise avoided.

Phase 4's stage names, each fired immediately after the named step: `nx_claim`, `provider_ack`, `log_insert`, `sent_publish`, `commit`. D-87 names `provider_ack` — that is the SC2 stage.

### Pattern 4: two consumer loops, one producer, one lifespan

`services/notifier/main.py` mirrors `services/state_machine/main.py:100-157` — `AsyncExitStack`, resources registered the moment they exist, `dispose_engine` pushed **first** so it unwinds **last**, and `run_until_signal(...)` so SIGTERM cancels rather than kills.

Both loops run concurrently under one `asyncio.TaskGroup` (or `asyncio.gather`) wrapped by the single `run_until_signal`. `shared/shutdown.py:33` exposes `async def run_until_signal(main: Awaitable[object]) -> None`, so pass it a single awaitable that fans out internally.

`_assert_topics_exist` must be extended: `REQUIRED_TOPICS` in `services/state_machine/main.py:49-55` currently lists five topics; the notifier's own guard adds `notifications.dlq`.

### Anti-Patterns to Avoid

- **Deleting the Layer-2 claim on success.** PITFALLS Pitfall 7: "Never `DEL` on success — that re-opens the window for duplicate fires from a rebalancing consumer." D-76 deletes only on *definitive failure*, which is correct; the executor must not generalise it.
- **A single `notif:{watch}:{event}` key shared by three channels.** D-76's channel suffix is load-bearing — this is structurally the same defect as Phase 2's WR/CR-01 token-only claim key that collapsed two seat types onto one claim.
- **Building a second `httpx.AsyncClient`.** `shared/http_client.py:9` — "Do NOT construct `httpx.AsyncClient` anywhere else in the codebase."
- **Logging a rendered SMS/email body, a phone number, an API key, or a `provider_id` alongside a recipient.** Phase 2 CR-02 was exactly this defect (`str(exc)` leaking a booking token). Follow `_failure_shape()` in `services/state_machine/consumer.py:64-86`: log the exception's dotted type name, never `str(exc)`.
- **`notification_log` writes as best-effort.** `services/state_machine/persistence.py` swallows insert failures by design (D-48) because a *delivered notification beats a durable analytics row*. That reasoning inverts here: the `sent` row is the audit trail the SC2 duplicate proof and the PERF-01 measurement both read. See Pitfall 3.

---

## Provider Contracts

### Resend — `POST https://api.resend.com/emails` `[CITED: resend.com/docs/api-reference/emails/send-email]`

| Item | Value |
|------|-------|
| Method / path | `POST https://api.resend.com/emails` |
| Auth header | `Authorization: Bearer re_xxxxxxxxx` |
| Content type | `application/json` |
| Required body | `from` (`Name <email@example.com>` accepted), `to` (string or array, max 50), `subject` |
| Optional body | `html`, `text`, `reply_to`, `cc`, `bcc`, `headers` (object), `tags`, `scheduled_at`, `attachments` |
| Success | **200**, body `{"id": "49a3999c-0ce1-4ea6-ab68-afcd6dc2e794"}` |
| **Idempotency** | Optional `Idempotency-Key` request header — "Unique per API request; expires after 24 hours; max 256 characters" |

`headers` is the field that carries D-81's `List-Unsubscribe` and `List-Unsubscribe-Post`.

**Recommendation (not in CONTEXT.md, high value):** send `Idempotency-Key: {job_id}`. `job_id` is already deterministic (`uuid5` over `notif:{watch_id}:{event_id}:{channel}`, D-75) and its 24 h expiry matches the Layer-2 TTL exactly. This closes the one window Layer-2 cannot: a crash *after* the HTTP request left the process but *before* the response was read leaves the claim held, but if the claim were ever released (D-76 deletes it on definitive failure) a retry would otherwise re-send. Resend's `409 invalid_idempotent_request` / `409 concurrent_idempotent_requests` then become the third line of defence.

Documented error codes `[CITED: resend.com/docs/api-reference/errors]`:

| Status | Codes | Retry? |
|--------|-------|--------|
| 400 | `invalid_idempotency_key`, `validation_error` | No — definitive |
| 401 | `missing_api_key`, `restricted_api_key` | No — `provider_unconfigured`-class |
| 403 | `email_above_quota`, `invalid_permission`, `restricted_api_key`, `suspended_api_key` | No |
| 404 | `not_found` | No |
| 405 | `method_not_allowed` | No |
| 409 | `concurrent_idempotent_requests`, `invalid_idempotent_request`, `resource_locked` | Treat as **already sent** — do not retry, do not dead-letter |
| 422 | `invalid_attachment`, `invalid_parameter`, `missing_required_field`, `missing_required_parameter` | No |
| 429 | `rate_limit_exceeded`, `daily_quota_exceeded`, `monthly_quota_exceeded` | Yes for `rate_limit_exceeded`; quota codes are definitive for the day |
| 500 | `application_error` | Yes |
| 503 | `service_unavailable` | Yes |

The exact JSON error body schema is not published; treat the body as `{"statusCode": int, "name": str, "message": str}` defensively and key retry decisions off the HTTP status, not the body. `[ASSUMED]` for the body shape.

### Resend webhooks — Svix `[VERIFIED: transcript]` + `[CITED: docs.svix.com/receiving/verifying-payloads/how-manual]`

Headers: `svix-id`, `svix-timestamp` (seconds since epoch), `svix-signature` (space-delimited `v1,<base64>` list).

Signed content: `f"{svix_id}.{svix_timestamp}.{raw_body}"`. HMAC-SHA256, key = `base64decode(secret_without_"whsec_"_prefix)`. Compare constant-time. Reject if the timestamp is outside tolerance (5 minutes is the conventional window).

Our 12-line verifier reproduces **both** published Svix vectors exactly:

```
vector A: v1,rAvfW3dJ/X/qxhsaXPOyyCGmRKsaKWcsNccKXlIktD0=
documented: v1,rAvfW3dJ/X/qxhsaXPOyyCGmRKsaKWcsNccKXlIktD0=

vector B: v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=
documented: v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE=
```

(vector A: `whsec_plJ3nmyCDGBKInavdOK15jsl` / `msg_loFOjxBNrRLzqYUf` / `1731705121` / `{"event_type":"ping","data":{"success":true}}`; vector B: `whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw` / `msg_p5jXN8AQM9LWM0D4loKWxJek` / `1614265330` / `{"test": 2432232314}`.)

Both vectors go into `tests/unit/test_svix_signature.py` as parametrised cases. Tamper and multi-signature-header cases also verified (`tamper: False`, `multi-sig header ok: True`).

**Critical:** verify against the **raw** body bytes. Resend's docs state "Make sure that you're using the raw request body when verifying webhooks. The cryptographic signature is sensitive to even the slightest change." In FastAPI that means `await request.body()`, never a Pydantic-parsed model re-serialised.

Event types and payload shape are **not** enumerated in the pages fetched. D-84 names `email.delivered` and `email.bounced`; treat the envelope as `{"type": str, "created_at": str, "data": {"email_id": str, ...}}` and match `notification_log` by `provider_id == data.email_id`. `[ASSUMED]` — the planner should add a `TODO(spike)` to confirm the field name against a real webhook delivery during the human-gated Resend setup.

### Twilio — `POST https://api.twilio.com/2010-04-01/Accounts/{AccountSid}/Messages.json` `[CITED: twilio.com/docs/messaging/api/message-resource]`

| Item | Value |
|------|-------|
| Auth | HTTP Basic, `AccountSid` : `AuthToken` |
| Content type | `application/x-www-form-urlencoded` (httpx `data=` produces this — verified) |
| Required | `To` (E.164) |
| Sender (one of) | `From` **or** `MessagingServiceSid` |
| Content (one of) | `Body` (≤ 1600 chars) **or** `MediaUrl` **or** `ContentSid` |
| Optional | `StatusCallback` (delivery-status webhook URL), `ScheduleType`, `SendAt` |
| Success | **201 Created** |
| Response fields | `sid`, `status`, `error_code`, `error_message`, `body`, `from`, `to`, `date_created`, `date_sent` |
| `status` values | `queued`, `sending`, `sent`, `failed`, `delivered`, `undelivered`, `receiving`, `received`, `accepted`, `scheduled`, `read`, `partially_delivered`, `canceled` |

`sid` is the `provider_id` and is the SC2 oracle. Note `Body` supports 1600 chars — the ≤ 160 constraint in NOTIF-04/D-81 is a *cost and deliverability* constraint (one GSM-7 segment), not an API limit. That is exactly why BC-2's septet measurement, not `len()`, is the right assertion.

Request shape verified through `respx` `[VERIFIED: transcript]`:

```
twilio request content-type: application/x-www-form-urlencoded
twilio body: b'To=%2B15551234567&MessagingServiceSid=MG1&Body=hi'
twilio auth header present: True
```

**Delivery-status mapping for `POST /webhooks/twilio/status`:** `delivered` → `notification_log.status='delivered'`, `delivered_at=now`; `failed`/`undelivered` → `status='failed'`, `error=MessageStatus + ErrorCode`. Everything else is a no-op (the row stays `sent`).

**429 / `Retry-After`:** Twilio returns 429 with a `Retry-After` header under queue-overflow conditions. Honour it through the tenacity wait (verified below), clamped — see Pitfall 5.

### Twilio inbound signature — `X-Twilio-Signature` `[VERIFIED: transcript]`

Algorithm `[CITED: twilio.com/docs/usage/webhooks/webhooks-security]`: HMAC-SHA1 with the account auth token as key, over `full_webhook_URL (including query) + concat(k + v for k in sorted(POST params))`, base64-encoded.

The implementation is twelve lines and needs no SDK:

```python
def twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """X-Twilio-Signature: base64(HMAC-SHA1(auth_token, url + concat(sorted k+v)))."""
    s = url
    for k in sorted(params):
        s += k + params[k]
    return base64.b64encode(
        hmac.new(auth_token.encode("utf-8"), s.encode("utf-8"), hashlib.sha1).digest()
    ).decode()
```

It reproduces Twilio's published worked example and matches the SDK's own `RequestValidator.compute_signature` on four independent inputs `[VERIFIED: transcript]`:

```
our impl        : RSOYDt4T1cUTdK1PDd93/VVr8B8=
twilio SDK      : RSOYDt4T1cUTdK1PDd93/VVr8B8=
SDK validate(mine): True
tampered validates?: False | ours: False

https://mycompany.com/myapp                  token=12345             -> 3M0LHWqn3EfNbG6V2+syyg40dpM=   sdk=3M0LHWqn3EfNbG6V2+syyg40dpM=
https://mycompany.com/myapp                  token=TWILIO_AUTH_TOKEN -> 8ZSBAKUKpILHFH9XYNMOG4Yfb7Y=   sdk=8ZSBAKUKpILHFH9XYNMOG4Yfb7Y=
https://mycompany.com/myapp.php?foo=1&bar=2  token=12345             -> RSOYDt4T1cUTdK1PDd93/VVr8B8=   sdk=RSOYDt4T1cUTdK1PDd93/VVr8B8=
https://mycompany.com/myapp.php?foo=1&bar=2  token=TWILIO_AUTH_TOKEN -> dhSrMKmxFyvx3Tr1aZX+O8U64O4=   sdk=dhSrMKmxFyvx3Tr1aZX+O8U64O4=
```

Params for the documented vector: `CallSid=CA1234567890ABCDE, Caller=+14158675309, Digits=1234, From=+14158675309, To=+18005551212`. `RSOYDt4T1cUTdK1PDd93/VVr8B8=` is the vector Twilio publishes for the query-string URL form.

**JSON-body variant** (Twilio uses this when a webhook is configured to POST JSON): Twilio appends a `bodySHA256` query parameter — the SHA-256 hex of the raw JSON body — to the URL, and the signature is computed over that URL with an empty parameter set. Also verified against the SDK `[VERIFIED: transcript]`:

```
bodySHA256: 7a38bf81f383f69433ad6e900d35b3e2385593f76a7b7ab5d4355b8ba41ee24b
sdk compute (empty params): m5ij+9mPJiX/KSczbtotqDaCTzM=
ours       (empty params): m5ij+9mPJiX/KSczbtotqDaCTzM=
```

Our routes should register as form-encoded, so the form path is the live one; the JSON branch is a two-line guard worth including because a console misconfiguration otherwise fails signature verification with no clue.

**The URL used for verification must be the URL Twilio was configured with**, not what the request looks like after a proxy. Behind a load balancer, `request.url` reports the internal scheme/host. Read the verification URL from a config function (`TWILIO_WEBHOOK_BASE_URL` + the route path), never from `request.url`. This is a very common production failure.

### Web Push — VAPID + aes128gcm `[VERIFIED: transcript]`

**Encryption.** `http_ece.encrypt(payload, salt=None, private_key=<ephemeral P-256>, dh=<p256dh raw bytes>, auth_secret=<auth raw bytes>, version="aes128gcm")` returns the complete RFC 8188 single-record body. Structure of the 217-byte body produced for a realistic push payload:

```
body[:16] hex (salt): 0a1f33a21bbf3d0ad8b2de5aaeceb397
rs (bytes 16..20): 4096
idlen (byte 20): 65          # the ephemeral P-256 uncompressed public point
```

`WebPusher(sub).encode(payload, content_encoding="aes128gcm")` returns a `CaseInsensitiveDict` with the single key `body` (bytes) — for `aes128gcm` there is no `crypto_key` and no `salt` key; those exist only on the deprecated `aesgcm` branch. Both routes decrypt back to the original payload with `http_ece.decrypt(body, private_key=<subscriber key>, auth_secret=<auth>, version="aes128gcm")`.

**VAPID header.** `py_vapid.Vapid.from_string(private_key=<b64url 32-byte scalar>)` works with `cryptography` 46.0.7 and returns a `Vapid02`. `sign(claims)` returns `{"Authorization": "vapid t=<JWT>,k=<b64url 65-byte public point>"}`:

```
Authorization: vapid t=eyJ0eXAiOiJKV1QiLCJhbGciOiJFUzI1NiJ9.eyJhdWQiOiJodHRwczovL3VwZGF0ZXMucHVzaC5zZXJ2aWNlcy5tb3ppbGxhLmNvbSIsImV4cCI6MTc4ODYzODAyOCwic3ViIjoibWFpbHRvOmFkbWluQG1pc2UucGxhY2UifQ._F94uJrfKj6vAZhZ3Y4LPZ8ZAwy-CiHb17v-84nu15FVwYGUIglD2odDsr5zYx3KjNvKj7F1Z954v9X5rCMSWA,k=BMa9swTGJOlxWviqj_L6T5EFuRbfxSebZWLSH6hhnuW2Mqj37vBWrvSdhynzX2ErCC4fom0T8Y0XBzsZZt-FCSQ
```

The `k=` value equals `b64url(public_key.public_bytes(X962, UncompressedPoint))` — i.e. `VAPID_PUBLIC_KEY` from `.env`, so a test can assert they match and catch a mismatched keypair at unit-test time rather than as a 403 in production.

The private key format `py_vapid` accepts is exactly what Phase 1 generated (STATE.md: "65-byte uncompressed P-256 public point + 32-byte big-endian private scalar, both b64url-no-pad") — 43 characters for the private scalar, 87 for the public point.

**Claim rules** `[VERIFIED: transcript]` + `[CITED: Apple/Mozilla push service behaviour]`:

- `sub` is **required**; omitting it raises `VapidException: Missing 'sub' from claims.`
- `sub` must be `mailto:you@example.com` (no space after the colon, no angle brackets) or an `https://` URL. Apple's push service returns `403 {"reason":"BadJwtToken"}` for anything else. `.env.example:56` already has `VAPID_SUBJECT=mailto:admin@mise.place` — correct.
- `aud` must be the push service **origin** (`scheme://host`, no path), derived per-subscription from the endpoint. `py_vapid` does not compute it: `urlsplit(endpoint)` → `f"{scheme}://{netloc}"`.
- `exp` must be **≤ 24 h** in the future. `py_vapid` defaults it to exactly `now + 86400` when omitted (verified: `now=1788595205`, default `exp=1788681605`). Exactly 24 h plus clock skew is a documented rejection cause. **Always pass `exp` explicitly** — 12 h is the safe value.

**Request headers:** `Authorization` (from `sign`), `Content-Encoding: aes128gcm`, `Content-Type: application/octet-stream`, `TTL: 60` (D-78), `Urgency: high` (D-78).

**Status codes** `[CITED: RFC 8030]`:

| Status | Meaning | Action |
|--------|---------|--------|
| 201 Created | Accepted for delivery | `notification_log.status='sent'`; `provider_id` from the `Location` header when present |
| 400 | Malformed request / bad JWT | Definitive; log the shape, dead-letter |
| 403 | Bad VAPID JWT (Apple `BadJwtToken`) | Definitive; alarm — this means a config error, not a per-subscription problem |
| 404 Not Found | Subscription removed | `push_subscriptions.revoked_at = now`, fall back to email (D-79) |
| 410 Gone | Subscription expired | Same as 404 |
| 413 | Payload too large | Definitive. Push services must accept ≤ 4096 bytes, so our JSON payload must stay well under it |
| 429 | Rate limited | Retry honouring `Retry-After` |

**Caching:** cache the signed VAPID header **per push-service origin**, keyed `(origin, exp_bucket)`, and re-sign when within an hour of expiry. Signing per message is an ECDSA operation per send — measurable at scale and pointless, since one header is valid for every subscription on that origin.

---

## Signed Tokens (measured)

D-82's shape: `base64url(json payload) + "." + base64url(hmac_sha256)`.

Measured sizes with a canonical JSON encoding (`separators=(",",":")`, `sort_keys=True`) `[VERIFIED: transcript]`:

| Payload | sig bytes | token chars | `mise.place/go/<token>` |
|---------|-----------|-------------|-------------------------|
| `{v,p,notification_log_id,event_id(uuid),watch_id,iat,exp}` verbose names | 32 | 238 | 260 |
| `{v,p,n,e(uuid),w,i,x}` compact names | 32 | 190 | 212 |
| `{"v":1,"p":"go","n":123456,"x":<exp>}` | 32 | 100 | 114 |
| `{"v":1,"p":"go","n":123456,"x":<exp>}` | 16 | 79 | 93 |
| **`{"v":1,"p":"go","n":123456}`** (BC-2 recommendation) | **32** | **80** | **94** |
| `{"v":1,"p":"go","n":123456}` | 16 | 59 | 73 |
| `{"v":1,"p":"go","n":12345678}` (8-digit id) | 32 | 83 | 97 |

Sample of the 59-char form: `eyJuIjoxMjM0NTYsInAiOiJnbyIsInYiOjF9.iLhWhxPUQNEfFMUDoLIuTQ`

**Recommendation:** keep the full 32-byte signature everywhere. Truncating the HMAC buys 21 characters and costs a security property for no benefit once BC-2's other two savings (no scheme, compact date) are applied.

**Embedding `event_id` and `watch_id` in the `go` token is unnecessary.** The `notification_log` row named by `n` already carries `watch_id`, `event_id` and `channel`; carrying them in the token more than doubles it (94 → 212 chars) and creates two sources of truth that can disagree. Carry only `{v, p, n}` for `go`; `unsubscribe` and `sms_stop` carry `{v, p, w or u, iat, exp}` per D-82 (they are email/URL-borne, not SMS-borne, so length is free).

**Verification rules:**

- `hmac.compare_digest` for the signature — never `==`. Available and verified.
- Reject before parsing if the token has no `.` separator.
- Read `v` from the payload, look up `HMAC_MGMT_SECRET_V{v}`, and accept the *previous* version only while `now < HMAC_GRACE_UNTIL` (D-82).
- Reject an unknown `p` (purpose). A token minted for `unsubscribe` must not be accepted by `/go` — this is the classic token-confusion bug and the reason `p` is in the payload at all.
- The payload is attacker-supplied JSON until the MAC verifies. Verify the MAC over the **base64url string**, not over re-serialised JSON — otherwise a canonicalisation difference breaks verification. The sketch below does this correctly.

The whole module typechecks under `mypy --strict` `[VERIFIED: transcript]` — the sketch at `/private/tmp/.../research-04/mypysketch/sketch.py` covering tokens, Twilio signature, Svix, phone crypto, VAPID and the push send reports `Success: no issues found in 1 source file`. Two typing details that the executor will otherwise hit:

- `json.loads` returns `Any`; assign through `payload_obj: object` and narrow with `isinstance(payload_obj, dict)` before use, or mypy strict rejects the return.
- `http_ece.encrypt(...)` is untyped; bind it to an annotated local (`encrypted: bytes = http_ece.encrypt(...)`) rather than returning it directly, or `--strict` reports `Returning Any from function declared to return "bytes"`.

---

## SMS Length Budget (measured)

The full measurement is in BC-2. Summary for the planner:

- **Constraint is septets, not characters.** GSM-7 single segment = 160 septets; a single non-GSM-7 character drops the whole message to UCS-2 and 70 characters.
- Characters in the GSM extension table (`^ { } \ [ ~ ] | €`) cost **2** septets each. Avoid them in templates.
- All 55 seeded restaurant names are GSM-7 representable; the longest is `Mission Chinese Food` (20 chars).
- The recommended template renders **153 septets** worst case at a 6-digit `notification_log.id`, 156 at 8 digits, 158 at 10 digits.

The unit test must implement the GSM 03.38 table and assert septets, not `len()`. Reference implementation (from the transcript, reusable verbatim):

```python
GSM_BASIC = ("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞ\x1bÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
             "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM_EXT = "^{}\\[~]|€"


def gsm7_septets(s: str) -> int | None:
    """Septet count, or None when the text is not GSM-7 (i.e. UCS-2, 70-char segments)."""
    n = 0
    for ch in s:
        if ch in GSM_EXT:
            n += 2
        elif ch in GSM_BASIC:
            n += 1
        else:
            return None
    return n
```

---

## Fan-out SQL and Matching

The pre-filter compiles cleanly against the existing ORM `[VERIFIED: transcript]` (SQLAlchemy 2.0.49, PostgreSQL dialect, literal binds):

```sql
SELECT watchlist_entries.id, watchlist_entries.user_id, watchlist_entries.party_size,
       watchlist_entries.date_from, watchlist_entries.date_to,
       watchlist_entries.time_window_from, watchlist_entries.time_window_to,
       watchlist_entries.days_of_week, watchlist_entries.seat_type_filter,
       watchlist_entries.channels, watchlist_entries.status,
       users.email, users.phone,
       restaurants.id AS restaurant_pk, restaurants.name, restaurants.slug
FROM watchlist_entries
  JOIN restaurants ON restaurants.id = watchlist_entries.restaurant_id
  JOIN users       ON users.id       = watchlist_entries.user_id
WHERE restaurants.source = 'opentable'
  AND restaurants.platform_id = '42'
  AND watchlist_entries.status = 'active'
  AND watchlist_entries.party_size = 2
  AND watchlist_entries.date_from <= '2026-05-01'
  AND watchlist_entries.date_to   >= '2026-05-01'
```

**No `selectinload` and no relationship loading is needed** — the `select()` names scalar columns, so `session.execute(stmt)` returns `Row` tuples and there is no lazy-load-on-a-detached-instance hazard (the classic async-SQLAlchemy `MissingGreenlet`). The ORM classes in `shared/db.py` declare no `relationship()` at all, so this is the only shape available anyway.

**The join key hazard (Pitfall 6 below):** `AvailabilityEvent.restaurant_id` is typed `int` and holds the *source platform id* (`shared/events.py:108` and its docstring at lines 91–93: "restaurant_id is the PLATFORM id (OpenTable rid / Resy venue id) … the complete join key against `restaurants` is `(source, platform_id)`"). `Restaurant.platform_id` is `Text` (`shared/db.py:55`). The bind therefore needs `str(event.restaurant_id)`. An `int` bind against a `text` column errors in asyncpg rather than silently returning zero rows — but only at runtime, in the integration tier.

**Residual predicates in Python** (`matching.py`, pure):

- `time_window_from <= time_slot <= time_window_to` when both set. `time_slot` is a `str` (`"HH:MM"`) on the wire; `services/state_machine/persistence.py:58-63` shows the tolerant parse convention (`dt_time.fromisoformat`, `None` on failure) — reuse it. A watch whose window cannot be compared because `time_slot` is unparseable should **not** match (fail closed).
- `days_of_week` is a comma list of `mon..sun` (D-73). The weekday is of the **service date**, not the detection date. `services/state_machine/persistence.py:53-55` establishes the project's convention `day_of_week(d) = d.isoweekday() % 7` (0=Sun..6=Sat) and migration 0008 records it as a column comment; map `mon..sun` to that numbering, and unit-test the mapping explicitly — an off-by-one here silently drops every Sunday alert.
- `seat_type_filter == event.seat_type` when set. `seat_type` is `str | None`; a watch with a filter must not match an event whose `seat_type` is `None`.
- `party_size` is already filtered in SQL (exact match, D-73).

**Seeding users/watches in integration tests through the ORM:** the ORM models have no `server_default` for `created_at`/`updated_at` on `users` and `watchlist_entries` (`shared/db.py:47-48, 87-88` declare them `nullable=False` with no default), so a test that omits them fails on a NOT NULL violation. Set them explicitly:

```python
async with get_async_session()() as session:
    now = datetime.now(UTC)
    user = User(email="u@example.com", phone=encrypt_phone("+15551234567", key),
                created_at=now, updated_at=now)
    session.add(user)
    await session.flush()                       # populates user.id
    session.add(WatchlistEntry(user_id=user.id, restaurant_id=restaurant.id,
                               party_size=2, date_from=d, date_to=d,
                               channels="email,sms,push", status="active",
                               created_at=now, updated_at=now))
    await session.commit()
```

`tests/integration/conftest.py:20` provides `reset_shared_db_singletons()` — call it after monkeypatching `DATABASE_URL_ASYNC` to the container, or the cached engine points at localhost.

---

## Layer-2 Idempotency, Rate Limit and Commit

### The claim, against real Redis 7.2.16 `[VERIFIED: transcript]`

```
--- set_nx_ex claim ---
first : True ttl: 86400
second: False
delete-on-definitive-failure then reclaim: 1 True
```

`shared.redis_keys.set_nx_ex` already exists (`shared/redis_keys.py:35-42`) and issues a single `SET key value NX EX ttl`. Add `notif_idempotency_key(watch_id, event_id, channel)` beside it:

```python
NOTIF_IDEMPOTENCY_TTL_SECONDS: int = 86_400   # 24 h — NOTIF-02


def notif_idempotency_key(watch_id: int, event_id: str, channel: str) -> str:
    """SET NX EX claim for one (watch, event, channel) send (D-76, NOTIF-02)."""
    return "notif:" + ":".join(quote(p, safe="") for p in (str(watch_id), event_id, channel))
```

Percent-escape the components exactly as `event_idempotency_key` does (`shared/redis_keys.py:93-94`). `channel` is a `Literal`, `watch_id` an int and `event_id` a UUID string, so injectivity is not currently at risk — but the escaping costs nothing and Phase 2's WR-04 is the precedent for why the un-escaped form is a trap waiting for a schema change.

### Per-user daily cap — Lua, not a pipeline `[VERIFIED: transcript]`

```lua
-- KEYS[1] = rate:notif:{user_id}:{YYYY-MM-DD}
-- ARGV[1] = ttl seconds (172800)
-- ARGV[2] = cap
-- Returns {count, allowed}
local n = redis.call('INCR', KEYS[1])
if n == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
if n > tonumber(ARGV[2]) then
  return {n, 0}
end
return {n, 1}
```

Behaviour with cap = 3:

```
  call 1: count=1 allowed=True ttl=172800
  call 2: count=2 allowed=True ttl=172800
  call 3: count=3 allowed=True ttl=172800
  call 4: count=4 allowed=False ttl=172800
  call 5: count=5 allowed=False ttl=172800
```

D-74 permits "one Lua/MULTI". **The MULTI form is wrong** and the transcript shows why:

```
--- MULTI/EXEC alternative (also atomic, no scripting) ---
  pipeline result: [1, True] ttl: 172800
  NOTE: unconditional EXPIRE refreshes the window on every call -> a sliding
        48h window, NOT a fixed calendar day. Lua with `if n == 1` is correct.
```

A `MULTI` can only issue `EXPIRE` unconditionally (it cannot branch on the `INCR` reply), which refreshes the TTL on every increment and turns the calendar-day counter into a sliding 48 h counter — so a user who receives one alert a day forever never resets. Use the Lua. Load it through `r.register_script(...)` as `shared/scheduler/lua.py` already does for the poll scripts.

The `YYYY-MM-DD` in the key must come from a **named timezone**, not `date.today()`. The product is NYC-local (`services/state_machine/persistence.py:31` — `_SERVICE_TZ = ZoneInfo("America/New_York")`); "50 alerts per day" that rolls over at 19:00 local is a bug users will notice. Reuse `_SERVICE_TZ`.

### Ordering and crash windows

D-76's per-job order, with the crash consequence at each boundary (this table belongs verbatim in `services/notifier/README.md`, and Phase 2's specifics note warns to keep it honest — the Phase 2 review caught an over-claim in exactly such a table):

| Crash point | Redis claim | Provider | `notification_log` | `notifications.sent` | Offset | On restart |
|-------------|-------------|----------|--------------------|----------------------|--------|------------|
| before claim | absent | not called | none | none | uncommitted | Redelivered; claimed and sent once |
| after claim, before provider | held 24 h | not called | none | none | uncommitted | Redelivered; **claim blocks the send — alert lost for 24 h.** Accepted trade-off (D-76, ARCHITECTURE §Failure 3) |
| **after provider ack, before log** (`MISE_CRASH_AFTER=provider_ack`) | held | **sent once** | none | none | uncommitted | Redelivered; claim blocks a second send → **exactly one provider SID.** This is SC2 |
| after log, before publish | held | sent | `sent` row | none | uncommitted | Redelivered; claim blocks → no duplicate send, `notifications.sent` lost (Phase 5 SSE misses one item) |
| after publish, before commit | held | sent | `sent` row | published | uncommitted | Redelivered; claim blocks → duplicate `notifications.sent` possible. Consumers must be idempotent on `job_id` |
| after commit | held | sent | `sent` row | published | committed | Nothing to do |

Two honest caveats the README must state rather than paper over:

1. The "alert lost for 24 h" window is real and is chosen deliberately.
2. A duplicate `notifications.sent` message is possible on the last-but-one row. `job_id` is deterministic (D-75), so downstream dedup is available — say so, do not claim exactly-once.

### Recommended backstops (beyond CONTEXT.md)

- **`notification_log` UNIQUE `(watch_id, event_id, channel)`** in migration 0010, with the insert written as `ON CONFLICT DO NOTHING` (the `pg_insert(...).on_conflict_do_nothing(index_elements=[...])` idiom `services/state_machine/persistence.py:97-101` already uses). This makes the database itself refuse a second `sent` row for the same tuple — a Layer-3 check whose key is identical to the Layer-2 Redis key, so the two can never disagree. It also makes the duplicate assertion in the chaos test a *database constraint* rather than a count.
  Note: this constrains `status='suppressed'` and `status='duplicate_suppressed'` rows too. If the planner wants those recorded alongside a `sent` row for the same tuple, make the unique index **partial**: `WHERE status IN ('sent','delivered','clicked')`.
- **Resend `Idempotency-Key: {job_id}`** (see § Resend). Free, provider-side, 24 h expiry matching Layer-2.

---

## Retries (tenacity 9.1.4)

Verified end to end `[VERIFIED: transcript]`:

```
tenacity 9.1.4
result: ok attempts: 3 elapsed=0.024s (Retry-After 0.01 honoured)
exhausted -> reraised: provider 500 | attempts: 2
decorator form -> abc | provider calls: 2
```

Both the `AsyncRetrying` async-iterator form and the `@tenacity.retry` decorator work over an `httpx` call under `respx`. `retry_if_exception_type` is the correct predicate for a typed provider exception (D-79 says `retry_if_exception`; both exist in 9.1, and `retry_if_exception_type` is the one that reads correctly here).

**Retry-After.** tenacity's `wait` callables take a `RetryCallState`; read the pending exception and prefer its `retry_after`:

```python
def wait_retry_after(fallback: WaitBaseT) -> WaitBaseT:
    """Honour Retry-After from the raised exception; else exponential backoff."""
    def _wait(rcs: RetryCallState) -> float:
        exc = rcs.outcome.exception() if rcs.outcome else None
        ra = getattr(exc, "retry_after", None)
        if ra is not None:
            return min(float(ra), MAX_RETRY_AFTER_SECONDS)   # clamp — see Pitfall 5
        return fallback(rcs)
    return _wait
```

**The `Retry-After` value is provider-controlled and must be clamped.** An unclamped `Retry-After: 3600` parks the notifier's single-message consumer loop for an hour, blowing the PERF-01 budget and eventually tripping Kafka's `max.poll.interval.ms` rebalance (PITFALLS Pitfall 10). Clamp to 30 s; if the provider wants longer, the right answer is to dead-letter and move on. `Retry-After` may also be an HTTP-date rather than seconds — parse both, and treat an unparseable value as absent.

### The no-sleep gate wording

`tests/unit/test_no_inline_sleep.py:27` bans `asyncio\.sleep\(` and `time\.sleep\(` across `services/state_machine/*.py`. tenacity sleeps internally, but it does so **inside its own package** — `tenacity/asyncio/__init__.py:64: return asyncio.sleep(seconds)` `[VERIFIED: transcript]` — never in our source. Therefore:

> **The gate needs no allowlist.** Extend `SCANNED_FILES` to `services/notifier/*.py`, `services/notifier/providers/*.py` and `services/api/**/*.py`, keep the identical two regexes, and add the non-vacuity assertion (the existing `test_scanned_file_set_is_not_empty` shape, raising the file-count floor to cover the new tree).

Proposed docstring sentence for the extended gate, so a future reader does not "fix" it by adding an allowlist:

> Backoff in `services/notifier` is delegated to `tenacity`, whose own `asyncio.sleep` lives in `tenacity/asyncio/__init__.py` and is therefore out of scope for this file-scoped grep. Any `asyncio.sleep(` appearing in *our* modules is a hand-rolled wait and is banned — use a tenacity `wait`, or the Kafka `pause`/`resume` + `loop.call_later` pattern in `services/state_machine/consumer.py::_retry_later`.

### Per-channel policy (D-79) with the retryable set made explicit

| Channel | Attempts | Retry on | Definitive (no retry) | On exhaustion |
|---------|----------|----------|-----------------------|---------------|
| email | 3, exp 1–8 s | 429 `rate_limit_exceeded`, 5xx, `httpx.TransportError`, `ReadTimeout` | 4xx (except 429), 409 idempotency codes = already sent | `status='failed'`, DEL claim, → `notifications.dlq` |
| sms | 2 | 429 (+`Retry-After`), 5xx, transport | 4xx | `status='failed'`, DEL claim, + `sms_failed_fallback` email when `email ∈ watch.channels` |
| push | 2 | 429 (+`Retry-After`), 5xx, transport | 400, 403, 413 | `status='failed'`, DEL claim |
| push | — | — | **404 / 410** | `push_subscriptions.revoked_at = now`; fall back to email; `status='failed'`, `error='subscription_revoked'` — **not** a dead letter |

**Timeouts.** `shared/http_client.py:24` sets the process default `httpx.Timeout(10.0, connect=5.0)`, which matches Claude's-discretion note in CONTEXT.md. Push has a 5 s SLA, so pass a tighter per-call `timeout=httpx.Timeout(4.0, connect=2.0)` on the push send. Per-call override verified working (see the ASGI/respx transcripts).

---

## `/go`, `slot_still_available`, and unsubscribe

### Route behaviour verified in-process `[VERIFIED: transcript]`

```
GET /go/abc  -> 302 | location: https://www.opentable.com/restref/client/?rid=1
   client.follow_redirects default: False
GET /go/gone -> 200 <p>sorry, that table is gone</p>
POST twilio inbound -> 200 <Response/>
   sig: abc123= params: {'From': '+15551234567', 'Body': 'STOP', 'MessageSid': 'SM1'}
POST resend -> {'x-svix-id': 'msg_1', 'x-svix-ts': '1700000000', 'x-svix-sig': 'v1,...'}
```

Harness (fastapi 0.136.0 / starlette 0.52.1 / httpx 0.28.1):

```python
transport = httpx.ASGITransport(app=app)
async with httpx.AsyncClient(transport=transport, base_url="https://api.mise.place") as c:
    r = await c.get("/go/abc")
```

`httpx.ASGITransport.__init__(self, app, raise_app_exceptions=True, root_path='', client=('127.0.0.1', 123))` — the `app=` keyword is correct for httpx 0.28 (the old `httpx.AsyncClient(app=...)` shortcut was removed in 0.28 and is a common stale-recipe failure). `follow_redirects` defaults to `False`, which is what the `/go` test needs — it asserts the 302 and the `location` header rather than chasing it to OpenTable.

**Use `base_url="https://..."`**, not `http://test`. `/go` writes the click and then redirects; if any code path derives the token-verification URL or an absolute link from `request.url`, an `http://test` base silently exercises a different string than production.

### `slot_still_available`

Read the Phase 2 record through `RedisStateStore.get_slots(rid, date, party)` (`services/state_machine/store.py:108`), which returns `dict[slot_key, SlotRecord]`. The slot key is `f"{time_slot}|{seat_type or '-'}"` (`shared/redis_keys.py:78`). `available = record is not None and record.state is SlotState.AVAILABLE`.

Two consequences the planner must handle:

1. `services/api/` will import `services/state_machine/store.py`, which is a service→service import. `MemoryStateStore` lives in the same module and drags `redis.asyncio` along (already logged in `deferred-items.md` as a known wart). Acceptable — but prefer importing only the read path, and do not construct the state machine's engine.
2. The Redis state has a 25 h TTL (`AVAIL_STATE_TTL_SECONDS = 90_000`). A click after the TTL reads *absent*, which the rule above scores as `slot_still_available=false` — inflating the PERF-03 false-positive rate with stale clicks rather than real ones. **`scripts/check_false_positive_rate.py` must bound its denominator to clicks within the state TTL** (or `/go` must record a third state, `unknown`, for an absent record and exclude it). Recommend: store `NULL` for an absent record and count only `TRUE`/`FALSE` rows, so `false / (true + false)` is the honest ratio. This is a genuine correctness point for PERF-03 and is not covered by CONTEXT.md.

### One-click unsubscribe (RFC 8058) `[CITED: RFC 8058 / Mailgun / Customer.io]`

- `List-Unsubscribe: <https://mise.place/unsubscribe/{token}>` — must contain an **HTTPS** URI.
- `List-Unsubscribe-Post: List-Unsubscribe=One-Click`
- The mailbox provider issues `POST` with body `List-Unsubscribe=One-Click` (form-encoded) and **no cookies or auth**. Parse it with `parse_qsl` (BC-3), not `Request.form()`.
- Both headers must be covered by DKIM. Resend signs with the verified domain's DKIM key, and passing them through the `headers` field puts them in the signed set — but this is worth a line in the human-gated Resend runbook.
- The unsubscribe must take effect within 48 h; ours is synchronous.

See OQ-2 for the `GET` half of D-84.

---

## Deep Links

`shared/links.py :: platform_booking_url(...)` per D-83. Both URL schemes remain `[ASSUMED]` — a targeted search this session surfaced only third-party reconstructions, plus a note that OpenTable's public RestRef API has been shut down (booking-URL construction reportedly still works for manual use). A second candidate form appeared:

```
https://www.opentable.com/booking/experiences-availability?rid={rid}&datetime={date}T{time}&covers={covers}
```

Keep D-83's `restref/client` form as the shipped default with a `TODO(spike)` marker, and unit-test only the **shape** (parameters present, date/time formatting, URL-encoding of the slug) — never the live behaviour. Phase 1 set exactly this precedent for the OpenTable endpoint (STATE.md: "placeholder endpoint/headers/fixtures seeded … with `[ASSUMED]`/`TODO(spike)` markers so adapter code + respx-mocked tests work today").

**Two inputs worth preferring over a constructed URL**, both already available and neither mentioned in D-83:

1. `AvailabilityEvent.booking_token` (`shared/events.py:113`). For OpenTable this is the slot's own booking handle. If its shape turns out to be a URL or a slot hash usable in a `restref` link, a token-derived deep link lands the user on the exact slot rather than on a date/party search. Recommend `platform_booking_url(..., booking_token: str | None = None)` with a documented fallback chain.
2. `Restaurant.slug` for Resy. **Note the Phase 3 dependency:** migration 0009 replaces `UNIQUE(slug)` with `UNIQUE(slug, source)` (D-63b), so after Phase 3 a slug lookup must be qualified by source. The fan-out SELECT already joins `restaurants` and selects `slug`, so the notifier reads the right row for free — but a *separate* slug lookup anywhere else would return the wrong source's row.

---

## Latency Budget and Measurement

### Where the 60 s goes (ARCHITECTURE §Failure walk-through, times are the documented budget)

```
t+0.0 s   slot appears at the source
t+≤90 s   poll detects it                        (POLL-03 90 s minimum interval — outside PERF-01)
t+8 s     confirmation poll (D-43)               ┐
t+~0.2 s  availability.events produced            │ produced_at_epoch_ms  ← PERF-01 CLOCK STARTS
t+~0.1 s  notifier loop A: SELECT + match         │
t+~0.05 s Redis rate-limit Lua                    │  PERF-01 measures only
t+~0.05 s notifications.queued send_and_wait      │  this bracket
t+~0.05 s loop B getone                           │
t+~0.02 s Redis SET NX EX claim                   │
t+0.3–3 s provider call (Twilio p50 ~1 s)         │
t+~0.05 s notification_log insert                 ┘ sent_at              ← PERF-01 CLOCK STOPS
```

`latency_ms = sent_at_epoch_ms - event.produced_at_epoch_ms` (D-86, D-45). **`produced_at_epoch_ms` is the confirming poll's `polled_at_epoch_ms`, not a wall clock** — `shared/events.py:95-97` states this explicitly, and it is what makes replay byte-identical. Two consequences:

- The measured latency includes any Kafka consumer lag, which is what PERF-01 wants.
- If the notifier's clock is ahead of the poller's, `latency_ms` is inflated; if behind, it can go **negative**. Clamp at 0 and log a `clock_skew_suspected` warning on a negative value rather than storing it — a negative row silently drags the p95 down and makes the gate lie.

Headroom against the 60 s budget is roughly 50 s, so the realistic failure mode is not per-message cost but **head-of-line blocking**: `max_poll_records=1` plus a slow provider means one stuck message stalls everything behind it. That is why the `Retry-After` clamp and the hard per-call timeouts matter (PITFALLS Pitfall 10 documents the same failure as the cause of `CommitFailedException` storms).

### Prometheus naming gotcha `[VERIFIED: transcript]`

```
sample: [('notifications_total', {'channel':'sms','status':'sent'}, 1.0),
         ('notifications_created', {'channel':'sms','status':'sent'}, 1788595272.13)]
collected metric names: ['notification_latency_seconds', 'notifications']
duplicate registration raises: ValueError Duplicated timeseries in CollectorRegistry: {'notifications', 'notifications_cre…
```

`Counter("notifications_total", ...)` produces the **exposed sample** `notifications_total` (what Grafana queries — D-86 is satisfiable) but the **metric family name** is `notifications`, and a companion `notifications_created` gauge is emitted. That matters twice: (a) the family-name collision check is against `notifications`, not `notifications_total`; (b) any test that asserts on `REGISTRY.collect()` metric names must expect `notifications`.

`shared/metrics.py` is created by **Phase 3 plan 03-02** with a single-definition-site rule and a double-import regression test (`tests/unit/test_metrics_registry.py`). Phase 4 **extends** that module — a second definition of any existing metric raises at import and takes the process down. Add:

```python
notification_latency_seconds = Histogram(
    "notification_latency_seconds", "detection->send latency", ["channel"],
    buckets=(0.5, 1, 2, 5, 10, 20, 30, 45, 60, 90, 120, float("inf")),
)
notifications_total = Counter("notifications_total", "notification outcomes", ["channel", "status"])
```

Buckets must straddle all three SLOs (5 s push, 10 s SMS, 60 s overall) so Grafana can read each off the histogram without a second metric.

### `scripts/check_notification_latency.py` / `check_false_positive_rate.py`

Mirror `scripts/check_poll_success.py` exactly — it is the established contract (read this session):

- Module docstring stating usage, the `make` target, and the three exit codes.
- `DATABASE_URL_ASYNC` env with the same default, and the same `postgresql+asyncpg://` → `postgresql://` strip for raw `asyncpg`.
- Threshold constants at module scope (`P95_OVERALL_SECONDS = 60`, `P95_SMS_SECONDS = 10`, `P95_PUSH_SECONDS = 5`, `MIN_SAMPLES = 100`, `FALSE_POSITIVE_THRESHOLD = 0.02`).
- Print a per-bucket table, then a `PASSED` / `FAILED` / `INSUFFICIENT DATA` line; insufficient data goes to `stderr` and returns **2**.
- `def main() -> None: sys.exit(asyncio.run(check()))`.

p95 in SQL: `percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)`, grouped by `channel`, over `WHERE status IN ('sent','delivered','clicked') AND latency_ms IS NOT NULL AND created_at >= NOW() - INTERVAL '24 hours'`. Compute the overall p95 across all channels in the same query with `GROUPING SETS` or a second aggregate — do not average per-channel p95s.

False-positive denominator, per the § `/go` note: `COUNT(*) FILTER (WHERE slot_still_available IS FALSE)::float / NULLIF(COUNT(*) FILTER (WHERE slot_still_available IS NOT NULL), 0)`.

Both get `make verify-perf01` / `make verify-perf03` targets with `##` help comments, matching the existing Makefile style.

---

## Migration 0010

**Sequencing dependency:** `migrations/versions/` currently ends at `0008`. Phase 3 plan 03-03 creates `0009_restaurant_slug_source_unique.py` with `down_revision = "0008"`. Phase 4's `0010` must set `down_revision = "0009"` and therefore **cannot be applied until Phase 3's migration lands**. If Phase 4 executes before Phase 3 completes, either rebase 0010 onto 0008 or block the plan. Flag this to the executor explicitly.

Shape, following the 0008 guard convention (`migrations/versions/0008_add_event_id_to_availability_events.py`, read this session):

```python
revision = "0010"
down_revision = "0009"
```

| Change | Notes |
|--------|-------|
| `users.phone_hash TEXT NULL` + `UNIQUE` index | HMAC-SHA256 hex, 64 chars (measured). Nullable because email-only users have no phone. A **unique** index over a nullable column is fine in Postgres (NULLs do not collide) |
| `users.sms_opt_out BOOLEAN NOT NULL DEFAULT false` | `server_default=sa.text("false")` |
| `notification_log.latency_ms INTEGER NULL` | |
| `notification_log.error TEXT NULL` | |
| `COMMENT ON COLUMN notification_log.status` | Record the vocabulary `queued|sent|delivered|clicked|failed|suppressed|duplicate_suppressed` in the database, as 0008 does for `day_of_week` and `restaurant_id`. Remember alembic's doubled `%%` if the text contains a percent sign |
| **`UNIQUE (watch_id, event_id, channel)` on `notification_log`** | Recommended Layer-3 backstop — see § Recommended backstops. Consider a partial index `WHERE status IN ('sent','delivered','clicked')` |
| `CREATE TABLE push_subscriptions` | `id` PK, `user_id` FK → `users.id`, `endpoint TEXT NOT NULL UNIQUE`, `p256dh TEXT NOT NULL`, `auth TEXT NOT NULL`, `user_agent TEXT NULL`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `revoked_at TIMESTAMPTZ NULL`. Index on `(user_id) WHERE revoked_at IS NULL` for the send-path lookup |

**Guards, following 0008:**

- If the new `UNIQUE (watch_id, event_id, channel)` is added, refuse to run when duplicates already exist rather than letting `CREATE UNIQUE INDEX` fail cryptically:
  `SELECT count(*) FROM (SELECT 1 FROM notification_log GROUP BY watch_id, event_id, channel HAVING count(*) > 1) d` → raise a `RuntimeError` naming the count and the remedy. `notification_log` has never been written to (Phase 1's migration 0005 docstring: "columns only; writes in Phase 4"), so this is a no-op in every environment today — exactly the situation 0008's guard was written for.
- Never `alembic revision --autogenerate` — `notification_log` is a plain table, but the same session would propose destructive changes to the hypertables (Pitfall 12, D-33). Hand-write it.
- `downgrade()` drops in reverse order, and drops the table before the columns it references.

**ORM must be updated in lockstep** (`shared/db.py`): add `phone_hash`, `sms_opt_out` to `User`; `latency_ms`, `error` to `NotificationLog`; and a new `PushSubscription` class. The integration test `tests/integration/test_migration_0008.py` is the template for `test_migration_0010.py` — note WR-07's lesson recorded in `02-REVIEW-FIX.md`: **do not downgrade a shared schema and restore it outside the failure path.**

---

## Phone Encryption and Hashing

`[VERIFIED: transcript]`:

```
=== AES-256-GCM phone encryption ===
PHONE_ENCRYPTION_KEY (b64, 32B key): qQ3o51GlzTEGfoOCvvlBhJuLeWBLSWlzfMUDhO4o5DA= len 44
ciphertext len for +15551234567: 40 (12 nonce + 12 pt + 16 tag)
round trip: +15551234567
nondeterministic (nonce): True
tamper detected: cryptography.exceptions.InvalidTag

=== phone_hash (HMAC-SHA256, deterministic, unique-indexable) ===
phone_hash: cd486d0819f6e43427dcb664d0b33a546ce584812b1f95b208e69acf253fb621 len 64
stable: True
```

**Layout:** `nonce (12 bytes) || ciphertext || GCM tag (16 bytes)`, stored whole in the existing `users.phone` BYTEA (`shared/db.py:46`, already commented "BYTEA, AES-256-GCM (D-32, T-04)"). 12 bytes is the GCM standard nonce length — do not use 16.

```python
NONCE_BYTES: Final[int] = 12


def encrypt_phone(e164: str, key_b64: str) -> bytes:
    key = base64.b64decode(key_b64)
    if len(key) != 32:
        raise ValueError("PHONE_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256)")
    nonce = os.urandom(NONCE_BYTES)
    return nonce + AESGCM(key).encrypt(nonce, e164.encode(), None)


def decrypt_phone(blob: bytes, key_b64: str) -> str:
    key = base64.b64decode(key_b64)
    return AESGCM(key).decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:], None).decode()
```

- The key-length check must be **explicit**. Without it a short key produces a `cryptography` error whose message is unhelpful and whose failure point is a send, not startup. Validate at service startup, not at first send.
- Every encryption uses a fresh nonce, so ciphertexts are non-deterministic — which is why `phone_hash` (HMAC-SHA256, deterministic) exists as the lookup key for the STOP webhook. That is D-85's design and it is correct.
- Tampering raises `cryptography.exceptions.InvalidTag`. Catch it specifically in `SmsProvider` and record `error='phone_decrypt_failed'` — never let the exception's `str()` near a log line.
- Consider AAD (`AESGCM(...).encrypt(nonce, pt, aad=str(user_id).encode())`) to bind a ciphertext to its row. Phase 5 writes these values, so **this must be decided now or not at all** — a later change is a data migration. See OQ-3.

**`phone_hash` and the STOP webhook.** The webhook receives `From` in E.164; hash it with `PHONE_HASH_SECRET` and look up `users.phone_hash`. Normalise first: Twilio sends `+1XXXXXXXXXX`, but a Phase 5 signup form may store a differently formatted number. Define **one** canonicalisation (`+` + digits only, no spaces/dashes/parens) in `shared/crypto.py`, use it on both write and lookup, and unit-test the pair. A mismatch means STOP silently does nothing — a TCPA exposure, not a cosmetic bug.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Web Push payload encryption | An ECDH+HKDF+AES-GCM implementation from RFC 8188 | `http_ece.encrypt(..., version="aes128gcm")` | The key derivation has four HKDF steps and a record-padding scheme; a subtle error yields a payload the browser silently drops with no error anywhere |
| VAPID JWT | `jwt.encode` with a hand-built ES256 signature | `py_vapid.Vapid.from_string(...).sign(claims)` | Emits the exact `vapid t=…,k=…` header form and the DER→raw signature conversion ES256 requires |
| Twilio signature | — | The 12-line function above **is** the sanctioned hand-roll (verified against the SDK on 4 inputs) | The SDK pulls `requests`; the algorithm is twelve lines and vector-tested. This is the one place hand-rolling is right |
| Svix signature | The `svix` package | The 12-line verifier above (two published vectors pass) | Same reasoning; one fewer dependency |
| Retry/backoff loops | `while attempts < n: await asyncio.sleep(...)` | `tenacity` | Trips the no-sleep gate, and gets jitter, `Retry-After` and exhaustion semantics wrong |
| Atomic claim | `SETNX` then `EXPIRE` | `shared.redis_keys.set_nx_ex` | PITFALLS Pitfall 7; already gated by `tests/unit/test_no_setnx_expire_pairs.py` |
| Daily counter with TTL | `INCR` + unconditional `EXPIRE` in a pipeline | The Lua above | The pipeline form silently becomes a sliding window (measured) |
| Form parsing for webhooks | `python-multipart` + `Request.form()` | `parse_qsl(await request.body())` | BC-3; also gives the exact param dict the signature needs |
| SMS length check | `len(body) <= 160` | `gsm7_septets(body) <= 160` | One em dash makes `len()` off by 2.3× (BC-2) |
| Provider HTTP client | `resend` / `twilio` / `pywebpush` SDKs | `shared.http_client.get_async_client()` + `httpx` | All three are sync `requests` clients (BC-1) |
| E.164 parsing | A regex zoo | One canonicalisation function, `+` + digits | Full E.164 validation is `phonenumbers`-sized; we only need a stable key |

**Key insight:** every "don't hand-roll" here is about *cryptographic* or *atomicity* correctness, where a wrong implementation produces a silent no-op (a dropped push, a permanent Redis key, a STOP that does nothing) rather than an exception. The two places hand-rolling *is* correct — the Twilio and Svix verifiers — are correct precisely because published test vectors exist, so the implementation is falsifiable in CI.

---

## Common Pitfalls

### Pitfall 1: `py_vapid` looks broken because Phase 1 said it was

**What goes wrong:** an executor reads STATE.md — "Used `cryptography.ec` SECP256R1 directly rather than `py_vapid` for VAPID generation (py_vapid 1.9.x API incompatible with cryptography >=43 EC keys)" — and reimplements JWT signing by hand.
**Why it happens:** the Phase 1 note is about **key generation**. `Vapid.from_string(...)` + `sign(...)` work fine on `cryptography` 46.0.7 `[VERIFIED: transcript]`.
**How to avoid:** use `py_vapid` for signing; keep `cryptography.ec` for generation. Record the distinction in the module docstring.
**Warning signs:** a hand-rolled ES256 signer appearing in `providers/push.py`.

### Pitfall 2: the VAPID `aud` is per-endpoint, and `exp` defaults to exactly the maximum

**What goes wrong:** one cached `Authorization` header is reused across Chrome (`fcm.googleapis.com`), Firefox (`updates.push.services.mozilla.com`) and Safari (`web.push.apple.com`); the non-matching services return 401/403.
**Why it happens:** `py_vapid` neither derives nor validates `aud`.
**How to avoid:** `aud = f"{scheme}://{netloc}"` from `urlsplit(endpoint)`; cache per origin. Always pass `exp = now + 12*3600` — the library's default is exactly `now + 86400` (verified), and "more than one day into the future" is a documented Apple rejection.
**Warning signs:** push works on one browser only; Apple `403 BadJwtToken`.

### Pitfall 3: copying Phase 2's best-effort persistence into the notifier

**What goes wrong:** `services/state_machine/persistence.py:106` swallows insert failures (`except Exception: log.error(...)`). Copied into the notifier's `sent` insert, a Postgres blip produces a sent SMS with no `notification_log` row — invisible to PERF-01, invisible to the SC2 duplicate check, and un-clickable (`/go` resolves a token to a `notification_log` row).
**Why it happens:** the pattern is right there, well-commented, and D-48's reasoning ("a delivered notification beats a durable analytics row") sounds like it generalises.
**How to avoid:** the `sent`/`failed` insert is **not** best-effort. On failure, do **not** commit the offset — take the transient/seek-back branch. The row is the audit trail two success criteria read.
**Warning signs:** `notifications_total{status="sent"}` exceeding `SELECT count(*) FROM notification_log WHERE status='sent'`.

### Pitfall 4: the daily cap becomes a sliding window

Covered under § Per-user daily cap. **Warning sign:** `TTL rate:notif:*` never counting down toward zero.

### Pitfall 5: an unclamped `Retry-After` stalls the pipeline

**What goes wrong:** `Retry-After: 3600` parks the single-message consumer loop for an hour; PERF-01 is blown, and Kafka eventually rebalances the partition (PITFALLS Pitfall 10 — the documented cause of `CommitFailedException` storms and duplicate sends).
**How to avoid:** clamp to 30 s and dead-letter beyond it. Parse both the delta-seconds and HTTP-date forms; treat unparseable as absent.
**Warning signs:** consumer lag climbing while the provider dashboard is green.

### Pitfall 6: the `int` platform id versus the `TEXT` platform_id column

**What goes wrong:** `AvailabilityEvent.restaurant_id` is `int` (`shared/events.py:108`); `Restaurant.platform_id` is `Text` (`shared/db.py:55`). Binding the int errors in asyncpg — and only in the integration tier, because unit tests use stubs.
**Why it happens:** the field name is identical to `restaurants.id`, which *is* an integer. `shared/events.py:91-93` warns about exactly this: "It is NOT the `restaurants` table primary key; the complete join key against `restaurants` is `(source, platform_id)`."
**How to avoid:** `str(event.restaurant_id)` at the bind site, with a comment naming D-52. Add an integration assertion that a seeded restaurant is actually found — a fan-out returning zero matches otherwise looks like "no watches," which is a valid state.
**Warning signs:** the e2e test produces zero `notifications.queued` messages and passes nothing but the "no crash" assertion.

### Pitfall 7: `respx` list-valued lookups are unhashable

**What goes wrong:**

```
respx/patterns.py:129, in __hash__
    return hash((self.__class__, self.lookup, self.value))
TypeError: unhashable type: 'list'
```

raised at route-registration time from `mock.post(host__in=["fcm.googleapis.com", ...])` `[VERIFIED: transcript]`.
**How to avoid:** pass a **tuple**: `host__in=("fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com")`. Works.
**Warning signs:** a `TypeError` from inside `respx` during fixture setup, with no reference to your test.

### Pitfall 8: redefining a `shared/metrics.py` metric

**What goes wrong:** `ValueError: Duplicated timeseries in CollectorRegistry` at import, which takes the whole service down at start `[VERIFIED: transcript]`.
**How to avoid:** one definition site (Phase 3's rule, plan 03-02); Phase 4 **appends** to that module. Also remember the `_total`-suffix family-name behaviour described under § Prometheus naming gotcha.

### Pitfall 9: the webhook verification URL is not `request.url`

**What goes wrong:** behind a proxy or in a test, `request.url` is `http://internal:8000/...` while Twilio signed `https://api.mise.place/...`. Every inbound STOP fails verification and is rejected — users cannot opt out, which is the TCPA exposure PITFALLS calls out.
**How to avoid:** build the verification URL from `TWILIO_WEBHOOK_BASE_URL` + the route path. Unit-test both the match and the mismatch.
**Warning signs:** `twilio_signature_invalid` in the logs with a nonzero rate.

### Pitfall 10: iOS revokes the subscription after ~3 "silent" pushes

**What goes wrong:** an iOS PWA stops receiving pushes after two or three sends, with nothing in the logs (PITFALLS Pitfall 6; flagged in STATE.md as a Phase 4 existential risk).
**Why it happens:** the service worker's `push` handler must call `event.waitUntil(self.registration.showNotification(...))` wrapping the *entire* async chain, and the payload must carry a non-empty `title` **and** `body`.
**Sender-side obligations for this phase** (the SW is Phase 6): the push payload JSON must always include non-empty `title` and `body` — assert it in a unit test, and never let a template render an empty body. Handle 404/410 by setting `revoked_at`. Keep the payload well under 4096 bytes.
**Warning signs:** `push_subscriptions.revoked_at` filling up for iOS user agents.

### Pitfall 11: a duplicate `notifications.sent` after the last crash window

Covered in the crash table. Do not describe the pipeline as exactly-once; `job_id` is deterministic so downstream consumers can dedupe.

### Pitfall 12: leaking a rendered message body, phone number or API key into logs

**What goes wrong:** Phase 2 CR-02 was exactly this — `str(exc)` on a `ValidationError` embedded a live booking token. Here the equivalents are the rendered SMS body (contains a signed capability URL), the E.164 number, `Authorization` headers, and `RESEND_API_KEY`.
**How to avoid:** reuse `_failure_shape()` (`services/state_machine/consumer.py:64-86`) — never `str(exc)`. Extend `shared/telemetry.py::_redact_secrets` with `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `PHONE_ENCRYPTION_KEY`, `PHONE_HASH_SECRET`, `HMAC_MGMT_SECRET_V*`, `authorization`, `api_key`, plus the value-shaped keys `phone`, `to`, `to_e164`, `body`, `sms_body`, `html`, `endpoint`, `p256dh`, `auth`, `token`.
**Note the collision with Phase 3:** plan 03-02 rewrites `_redact_secrets` to be case-insensitive and adds eight keys (D-61a). Phase 4 must **extend** the post-03-02 function, not the current four-key version in `shared/telemetry.py:23-28`, and must add its assertions to `tests/unit/test_telemetry_redaction.py` rather than replacing them. `HMAC_MGMT_SECRET_V1` is already covered.
**Warning signs:** a `/go` token in a log line — anyone reading the log can click through as the user.

---

## Code Examples

All verified in `.venv` this session.

### Web Push send (no `pywebpush`, no `requests`)

```python
# Source: executed transcript, this session. See BC-1.
import base64, time
from urllib.parse import urlsplit

import http_ece
import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid


def _b64u_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def vapid_headers(endpoint: str, private_key_b64u: str, subject: str) -> dict[str, str]:
    origin = urlsplit(endpoint)
    claims = {
        "sub": subject,                                   # mailto:… — no space, no <>
        "aud": f"{origin.scheme}://{origin.netloc}",      # ORIGIN only, per endpoint
        "exp": int(time.time()) + 12 * 3600,              # NOT the 24 h default
    }
    return dict(Vapid.from_string(private_key=private_key_b64u).sign(claims))


def encrypt_push(p256dh: str, auth: str, payload: bytes) -> bytes:
    server_key = ec.generate_private_key(ec.SECP256R1())
    encrypted: bytes = http_ece.encrypt(
        payload, salt=None, private_key=server_key,
        dh=_b64u_decode(p256dh), auth_secret=_b64u_decode(auth), version="aes128gcm",
    )
    return encrypted


async def push_send(client: httpx.AsyncClient, endpoint: str, body: bytes,
                    headers: dict[str, str]) -> int:
    response = await client.post(
        endpoint, content=body,
        headers={**headers, "TTL": "60", "Content-Encoding": "aes128gcm",
                 "Content-Type": "application/octet-stream", "Urgency": "high"},
        timeout=httpx.Timeout(4.0, connect=2.0),          # push SLA is 5 s
    )
    return response.status_code
```

### Twilio inbound webhook with signature verification, no `python-multipart`

```python
# Source: executed transcript, this session. See BC-3 and Pitfall 9.
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request, Response

router = APIRouter()


@router.post("/webhooks/twilio/inbound")
async def twilio_inbound(request: Request) -> Response:
    raw = await request.body()
    params: dict[str, str] = dict(parse_qsl(raw.decode(), keep_blank_values=True))
    url = twilio_webhook_url("/webhooks/twilio/inbound")   # config, NOT request.url
    expected = twilio_signature(twilio_auth_token(), url, params)
    if not hmac.compare_digest(request.headers.get("X-Twilio-Signature", ""), expected):
        log.warning("twilio_signature_invalid")            # no params, no body
        return Response(status_code=403)
    if params.get("Body", "").strip().upper() in STOP_KEYWORDS:
        await pause_all_watches_for_phone(params["From"])
    return Response(content="<Response/>", media_type="application/xml")
```

`STOP_KEYWORDS` should be `{"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT"}` — Twilio's Advanced Opt-Out set. Twilio's own filter already intercepts these on a Messaging Service, so our handler is a belt-and-braces DB update; treat a missing inbound webhook as a compliance gap, not a delivery gap.

### respx as the SID-level duplicate oracle

```python
# Source: executed transcript, this session. Note Pitfall 7 — tuple, not list.
with respx.mock(assert_all_called=False) as mock:
    sms = mock.post(f"{TWILIO_BASE}/2010-04-01/Accounts/{SID}/Messages.json").mock(
        return_value=httpx.Response(201, json={"sid": "SM1234", "status": "queued"}))
    push = mock.post(host__in=("fcm.googleapis.com",
                               "updates.push.services.mozilla.com",
                               "web.push.apple.com")).mock(
        return_value=httpx.Response(201, headers={"location": "https://fcm.googleapis.com/0:xyz"}))
    ...
    assert sms.call_count == 1, "SC2: exactly one Twilio SID across the crash and the restart"
    assert {c.request.headers["TTL"] for c in push.calls} == {"60"}
```

`route.calls[i].request` exposes `.content`, `.headers` and `.url`, so the assertion can check the form body, the basic-auth header, and the push `TTL`/`Content-Encoding` without a live provider. `assert_all_called=True` is available on the context-manager form and is worth using where every route is expected to fire.

### FastAPI in-process test harness

```python
# Source: executed transcript, this session (fastapi 0.136.0 / httpx 0.28.1).
transport = httpx.ASGITransport(app=create_app())
async with httpx.AsyncClient(transport=transport, base_url="https://api.mise.place") as client:
    r = await client.get(f"/go/{token}")
    assert r.status_code == 302
    assert r.headers["location"].startswith("https://www.opentable.com/")
```

`follow_redirects` defaults to `False`; `pyproject.toml` sets `asyncio_mode = "auto"` so no `@pytest.mark.asyncio` is needed (both forms verified passing).

---

## Project Constraints (from CLAUDE.md)

`CLAUDE.md` embeds STACK.md rather than listing bare directives; the operative rules come from the pinned stack plus `.ruff.toml`, `pyproject.toml` and `CONTRIBUTING.md`.

| Constraint | Source | How Phase 4 complies |
|------------|--------|----------------------|
| Async-only in `services/` and `shared/`; no `import requests` | CLAUDE.md stack + CI grep, `.ruff.toml` comment | BC-1 — `http_ece`/`py_vapid`/`cryptography` only; new grep gate for `pywebpush|resend|twilio` |
| No `time.sleep(` in `services/`/`shared/` | Same + `tests/unit/test_no_inline_sleep.py` | Extend the existing gate to `services/notifier` and `services/api`; tenacity's sleep is in its own package |
| No `import redis` / `from redis import` (sync client) | Same | `redis.asyncio` only, as Phase 2 |
| ruff `line-length = 120`, `select = ["E","F","W","I","UP","ASYNC"]` | `.ruff.toml` | Verified on the sketch — only an import-ordering nit, auto-fixable |
| `mypy --strict` on `shared/ services/ scripts/` | `Makefile` `lint` target, `[tool.mypy] strict = true` | The full sketch passes `--strict` `[VERIFIED: transcript]`; two `Any`-narrowing idioms documented |
| Every Redis key in `shared/redis_keys.py` | Established pattern (D-18) | `notif_idempotency_key`, `rate_notif_key`, `NOTIF_IDEMPOTENCY_TTL_SECONDS`, the rate-limit Lua all land there |
| Every Kafka schema in `shared/events.py` | D-06 | `NotificationQueued`, `NotificationSent` — `frozen=True, extra="forbid"`, declaration order is wire order |
| Env read lazily, never as a module constant | `services/state_machine/config.py:7-11` (02-02 deviation 1) | `services/notifier/config.py` and `services/api/config.py` use functions |
| Grep gates carry a non-vacuity check | `tests/unit/test_no_setnx_expire_pairs.py:35`, `test_no_inline_sleep.py:40` | Every new gate gets a `test_scanned_*_is_not_empty` companion |
| Small atomic commits | Established pattern | Planner's concern |
| No `alembic revision --autogenerate` | Pitfall 12 / D-33, 0008 header comment | 0010 is hand-written |

---

## Runtime State Inventory

Not applicable — Phase 4 is greenfield (a new service, a new API skeleton, new columns and one new table). No rename, refactor or string migration is involved. The one adjacent concern, **live-service configuration not stored in git**, is real and belongs in the human-gated runbooks:

| Category | Items | Action |
|----------|-------|--------|
| Live service config | Twilio Messaging Service inbound + status-callback webhook URLs; Resend webhook endpoint + signing secret; Resend domain SPF/DKIM/DMARC records | Configured in vendor consoles, not in git. `docs/runbooks/` must record the exact URLs and the console path, or a redeploy to a new hostname silently breaks STOP handling |
| Secrets/env | `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `PHONE_ENCRYPTION_KEY`, `PHONE_HASH_SECRET`, `NOTIFY_FROM_EMAIL`, `PUBLIC_BASE_URL`, `TWILIO_WEBHOOK_BASE_URL`, `NOTIFY_DRY_RUN`, `NOTIFY_DAILY_CAP_PER_USER`, `RESEND_API_BASE`, `TWILIO_API_BASE`, `HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL` | All new; add to `.env.example` (which today has no `RESEND_*` block at all). `TWILIO_*`, `VAPID_*` and `HMAC_MGMT_SECRET_V1` already exist |
| Stored data | None to migrate — `notification_log` has never been written (0005 docstring: "columns only; writes in Phase 4"); `users.phone` is populated by Phase 5 | None |
| OS-registered state | None | None |
| Build artifacts | None | None |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.12.13 | — |
| Docker | integration tier (testcontainers) | ✓ | daemon reachable this session | `tests/conftest.py:8` skips the tier when absent |
| Redis 7.2 | Layer-2 claim, rate limit, `/go` | ✓ | server 7.2.16 verified via a throwaway container | — |
| Kafka | both consumer loops | ✓ (image `confluentinc/cp-kafka:7.6.0` per `tests/conftest.py:24`) | — | — |
| TimescaleDB | `notification_log`, migration 0010 | ✓ (image `timescale/timescaledb:2.17.2-pg16`) | — | — |
| `http_ece`, `py_vapid`, `cryptography` | Web Push | ✓ | 1.2.1 / 1.9.4 / 46.0.7 | — |
| `respx` | provider mocking | ✓ | 0.23.1 | — |
| `python-multipart` | *(not required — BC-3)* | ✗ | — | `parse_qsl` on the raw body |
| Twilio live 10DLC number | real SMS send | ✗ | — | `respx` + `NOTIFY_DRY_RUN`; STATUS: pending-human |
| Resend verified domain + API key | real email send | ✗ | — | same |
| Real iPhone with the PWA installed | NOTIF-05 iOS proof | ✗ | — | none — human-gated runbook (SC3) |
| 24 h production traffic | PERF-01 window | ✗ | — | none — human-gated runbook |

**Missing with no fallback (human-gated, do not block the phase):** Twilio A2P 10DLC approval and a live US number; Resend domain verification; a real iPhone; the 24 h PERF-01 window. Each gets a `docs/runbooks/*.md` with a `STATUS: pending-human` banner, matching the Phase 1 convention (`01-03` evidence-file shells).

**Missing with fallback:** `python-multipart` — the fallback is strictly better (BC-3).

**Sequencing dependency, not an environment gap:** migration `0009` does not exist yet; Phase 3 plan 03-03 creates it. `shared/metrics.py` and `shared.events.FAILED_POLL_STATUSES` likewise arrive with Phase 3. Phase 4 must extend them, not create them.

---

## State of the Art

| Old approach | Current approach | When changed | Impact on this phase |
|--------------|------------------|--------------|----------------------|
| `aesgcm` (draft-01) push encryption | `aes128gcm` (RFC 8188) | RFC 8291, 2017 | Use `content_encoding="aes128gcm"`; the `aesgcm` branch of `pywebpush.encode` (which returns extra `crypto_key`/`salt` keys) is deprecated and must not be copied |
| `httpx.AsyncClient(app=...)` | `httpx.AsyncClient(transport=httpx.ASGITransport(app=...))` | httpx 0.27 deprecation → removed in 0.28 | Any tutorial using `app=` fails on the pinned 0.28.1 |
| Unauthenticated `mailto:` unsubscribe | RFC 8058 one-click `List-Unsubscribe-Post` | Gmail/Yahoo bulk-sender enforcement, Feb 2024 | Both headers are required for deliverability at any volume; the `POST` body is `List-Unsubscribe=One-Click` |
| Ad-hoc webhook HMAC schemes | Standard Webhooks / Svix (`svix-id`/`svix-timestamp`/`svix-signature`) | Svix standardisation, ~2022 | Resend uses it; the verifier is portable to any Svix-backed provider |
| Twilio long codes without registration | A2P 10DLC registration required | 2021 → enforced | STATE.md tracks this as a Phase-1 Day-1 admin task; the SMS-degraded demo path (PITFALLS Pitfall 5) stays the plan |
| `pywebpush.webpush()` one-shot helper | Explicit `encode` + your own async HTTP | ongoing | The helper is sync and `requests`-based; it is the wrong shape for an async service (BC-1) |

**Deprecated / do not use:**

- `pywebpush.webpush(...)` and `WebPusher.send(...)` — sync, `requests`-based.
- `aesgcm` content encoding.
- `responses` / `aioresponses` for mocking — wrong client library (STACK.md line 113).
- `SETNX` + `EXPIRE` as two commands — already gated.

---

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | OpenTable `https://www.opentable.com/restref/client/?rid=…&datetime=…&covers=…` is a working booking deep link | Deep Links | NOTIF-07 CTAs land on an error page; SC5 fails. Mitigated by `TODO(spike)` + shape-only tests. A second candidate (`/booking/experiences-availability`) is recorded |
| A2 | Resy `https://resy.com/cities/ny/{slug}?date=…&seats=…` pre-selects date and party | Deep Links | Same as A1 |
| A3 | Resend webhook payload is `{"type", "created_at", "data": {"email_id", …}}` and `data.email_id` matches the send-response `id` | Provider Contracts § Resend webhooks | `/webhooks/resend` matches zero `notification_log` rows; `delivered_at` never populates. Non-blocking (status stays `sent`) |
| A4 | Resend error bodies are `{"statusCode", "name", "message"}` | Provider Contracts § Resend | Only affects log detail; retry decisions key off HTTP status |
| A5 | Twilio returns `Retry-After` on 429 for the Messages resource | Retries | The exponential fallback covers it; the code path is `getattr(..., None)`-guarded |
| A6 | `AvailabilityEvent.booking_token` for OpenTable is usable in a deep link | Deep Links | Only affects the optional preferred branch; the constructed URL remains the fallback |
| A7 | A 5-minute Svix timestamp tolerance is appropriate | Provider Contracts § Svix | Too tight → legitimate retries rejected; too loose → replay window. 5 min is the conventional value |
| A8 | `notification_log.id` stays below 10 digits for the life of v1 | SMS Length Budget | The SMS overflows 160 septets at ~11 digits. The recommended test pins a 10-digit id |
| A9 | Every seeded restaurant name stays GSM-7 representable | SMS Length Budget | A future name with `é`/`—` forces UCS-2. The recommended test iterates all seeded names, so it fails loudly in CI |
| A10 | Phase 3 lands `migrations/versions/0009_*`, `shared/metrics.py` and `FAILED_POLL_STATUSES` before Phase 4 executes | Migration 0010 | `alembic upgrade head` fails on a missing `down_revision`; `shared/metrics.py` gets created twice |

---

## Open Questions

### OQ-1 — Where do `CRASH_HOOK_ENVS` / `crash_hook_allowed()` live once two services need them?

- **What we know:** they are in `services/state_machine/config.py:68-80`. Phase 2's CR fix explicitly warns that "two readers of a single safety-critical variable is one too many," so copying them into `services/notifier/config.py` is the wrong move.
- **What's unclear:** whether the planner prefers a new `shared/crash_hook.py` (a refactor touching a Phase 2 file, which Phase 3 may also be touching) or a `services.notifier.config` → `services.state_machine.config` import (a service→service dependency the repo has otherwise avoided).
- **Recommendation:** create `shared/crash_hook.py` exporting `CRASH_HOOK_ENVS`, `crash_hook_allowed()`, `crash_after()` and `maybe_crash(stage)`, and have `services/state_machine/config.py` re-export from it with `__all__` (the same idiom it already uses for `CONFIRM_DELAY_MS` at lines 20–34). One definition site, no service→service import, and `tests/unit/test_state_machine_startup.py` keeps passing unchanged. Sequence it as its own small task so it does not collide with Phase 3 edits.

### OQ-2 — Should `GET /unsubscribe/{token}` mutate state?

- **What we know:** D-84 says `GET|POST /unsubscribe/{token}` sets the watch to `paused`, idempotently. RFC 8058 one-click uses `POST`. Email footers are clicked with `GET`.
- **What's unclear:** corporate link scanners (Outlook SafeLinks, Proofpoint, Barracuda) and some mail clients prefetch every URL in a message with `GET`. A state-mutating `GET` therefore pauses watches nobody asked to pause — a silent, hard-to-diagnose loss of the product's core function, arriving as "the alerts just stopped."
- **Recommendation:** `POST` mutates (satisfying RFC 8058 one-click, and this is the path SC4's "within 5 seconds" is measured on). `GET` renders a one-button confirmation page whose form `POST`s to the same URL — plus accept `GET …?confirm=1` so a plain-text-only client still has a working path. This preserves D-84's endpoint, method set and idempotency; it only moves *which* method mutates. If the planner would rather keep D-84 literal, the mitigation is `Cache-Control: no-store` plus a scanner-User-Agent denylist, which is strictly weaker. Flag for human confirmation.

### OQ-3 — Should `encrypt_phone` bind the ciphertext to its row with AAD?

- **What we know:** AES-GCM supports associated data. Binding `user_id` as AAD means a ciphertext copied to another row fails to decrypt.
- **What's unclear:** Phase 5 is the writer; Phase 4 only decrypts. Adding AAD later is a data migration.
- **Recommendation:** **do not** use AAD in v1. The threat it defends against (an attacker with write access to `users.phone` but not to the key) is not in the v1 model, and the coupling would force `decrypt_phone` to take a `user_id` that `SmsProvider` would have to thread through. Record the decision in the `shared/crypto.py` docstring so it is a choice rather than an oversight, and note it as a v2 hardening item.

### OQ-4 — Does `notification_log` need `user_id` and `job_id` columns?

- **What we know:** the table has `watch_id`, `event_id`, `channel`, `status`, `provider_id` and the four timestamps. `job_id` is deterministic from `(watch_id, event_id, channel)`, and `user_id` is reachable through `watch_id`.
- **What's unclear:** every PERF-01/PERF-03 query and every webhook lookup would be simpler with them, and a `watch` deleted in Phase 5 (WATCH-04 offers delete) orphans the FK.
- **Recommendation:** add neither. `job_id` is derivable, and `user_id` is one join away. **Do** decide the delete semantics now: make `notification_log.watch_id` `ON DELETE SET NULL` (and the column nullable) in migration 0010, or Phase 5's delete either fails on the FK or cascades away the audit trail. This is cheap in 0010 and expensive later. Flag for human confirmation.

### OQ-5 — Which `notification_log` row does the `/go` token name for a multi-channel alert?

- **What we know:** BC-2's compact `go` token carries only `notification_log.id`. One event on a three-channel watch produces three rows, so three different `/go` tokens point at three rows.
- **What's unclear:** whether PERF-03's click-through and false-positive rates should be per-channel (three rows, three click records — good for "which channel converts") or per-notification (one row).
- **Recommendation:** keep it per-channel. It is what the current schema produces naturally, it makes `slot_still_available` attributable to the channel whose latency caused the miss, and PERF-03's ratio is unaffected because both numerator and denominator scale together. Document it in the script docstring so nobody later reads the denominator as "unique alerts."

---

## Validation Architecture

`workflow.nyquist_validation` is `true` in `.planning/config.json`.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `pythonpath = ["."]`, marker `integration` |
| Quick run command | `make test` → `uv run pytest tests/unit -x -q` |
| Full suite command | `make test-integration` → `uv run pytest tests/unit tests/integration -v` |
| Lint gate | `make lint` → `uv run ruff check . && uv run mypy shared/ services/ scripts/` |
| Container fixtures | `tests/conftest.py` — module-scoped `kafka_container`, `redis_container` (7.2-alpine, `maxmemory-policy=noeviction`), `timescale_container` (2.17.2-pg16); all skip when Docker is unreachable |
| Helpers | `tests/integration/conftest.py` — `apply_migrations`, `create_topics`, `reset_shared_db_singletons`, `redis_url`, `db_urls` |

### Phase Requirements → Test Map

| Req | Behaviour | Type | Automated command | File exists? |
|-----|-----------|------|-------------------|--------------|
| NOTIF-01 | `match_watches` matrix: party, date range, time window, days-of-week, seat type, status; boundary inclusivity | unit | `uv run pytest tests/unit/test_matching_matrix.py -x -q` | ❌ Wave 0 |
| NOTIF-01 | Pre-filter SELECT finds a seeded watch through `(source, platform_id)` with the `str()` bind | integration | `uv run pytest tests/integration/test_notifier_fanout.py -x -q` | ❌ Wave 0 |
| NOTIF-01 | One `NotificationQueued` per channel; `job_id` deterministic across two renders | unit | `uv run pytest tests/unit/test_notification_events_schema.py -x -q` | ❌ Wave 0 |
| NOTIF-01/D-74 | Rate-limit Lua: fixed calendar-day TTL, cap boundary, `suppressed` row, no provider call | integration | `uv run pytest tests/integration/test_notifier_rate_limit.py -x -q` | ❌ Wave 0 |
| NOTIF-02 | `notif_idempotency_key` shape + escaping; `set_nx_ex` claim / re-claim / DEL-and-reclaim | unit | `uv run pytest tests/unit/test_notif_idempotency_key.py -x -q` | ❌ Wave 0 |
| NOTIF-02 | Claim precedes the provider call; NX failure writes `duplicate_suppressed` and calls no provider (fake provider records call order) | unit | `uv run pytest tests/unit/test_idempotency_ordering.py -x -q` | ❌ Wave 0 |
| NOTIF-02 | No two-command `SETNX`+`EXPIRE` anywhere (extend scanned dirs; keep the non-vacuity guard) | unit | `uv run pytest tests/unit/test_no_setnx_expire_pairs.py -x -q` | ✅ extend |
| NOTIF-03 | Resend request shape: URL, `Authorization: Bearer`, JSON body, `List-Unsubscribe*` headers, `Idempotency-Key`; 200 → `id` | unit (respx) | `uv run pytest tests/unit/test_provider_email.py -x -q` | ❌ Wave 0 |
| NOTIF-03 | 3 attempts then dead-letter; 409 treated as already-sent; 4xx not retried | unit (respx) | `uv run pytest tests/unit/test_retry_policy.py -x -q` | ❌ Wave 0 |
| NOTIF-04 | Twilio request shape: form encoding, basic auth, `MessagingServiceSid`, `StatusCallback`; 201 → `sid` | unit (respx) | `uv run pytest tests/unit/test_provider_sms.py -x -q` | ❌ Wave 0 |
| NOTIF-04 | SMS body ≤ 160 **septets** across all 55 seeded names, GSM-7 only, with a 10-digit log id | unit | `uv run pytest tests/unit/test_sms_length.py -x -q` | ❌ Wave 0 |
| NOTIF-04 | `X-Twilio-Signature` reproduces both published Twilio vectors and rejects tampering; verification URL comes from config | unit | `uv run pytest tests/unit/test_twilio_signature.py -x -q` | ❌ Wave 0 |
| NOTIF-04 | Inbound STOP flips every active watch and sets `sms_opt_out`, inside one request; bad signature → 403 and no writes | integration (ASGI) | `uv run pytest tests/integration/test_api_webhooks.py -x -q` | ❌ Wave 0 |
| NOTIF-04 | 2 attempts then `failed` + `sms_failed_fallback` email when email is a channel | unit (respx) | `uv run pytest tests/unit/test_retry_policy.py -x -q` | ❌ Wave 0 |
| NOTIF-05 | aes128gcm body decrypts with the subscriber key; headers `TTL`/`Content-Encoding`/`Urgency`; `aud` is per-endpoint origin; `exp` ≤ 12 h; `k=` equals `VAPID_PUBLIC_KEY`; payload always has non-empty `title` and `body` | unit (respx) | `uv run pytest tests/unit/test_provider_push.py -x -q` | ❌ Wave 0 |
| NOTIF-05 | 404 and 410 both set `revoked_at` and trigger the email fallback | unit (respx) | `uv run pytest tests/unit/test_push_revocation.py -x -q` | ❌ Wave 0 |
| NOTIF-05 | No `services/**` or `shared/**` module imports `pywebpush`, `resend`, `twilio`, or `requests` (BC-1) | unit (grep) | `uv run pytest tests/unit/test_no_sync_sdk_imports.py -x -q` | ❌ Wave 0 |
| NOTIF-06 | Both consumer factories carry `enable_auto_commit=False`; `max_poll_records=1` | unit | `uv run pytest tests/unit/test_kafka_consumer_config.py -x -q` | ✅ extend |
| NOTIF-06 | No committed offset ever passes a failed one; transient failure seeks back and pauses | unit | `uv run pytest tests/unit/test_notifier_offset_policy.py -x -q` | ❌ Wave 0 (model on `test_offset_commit_policy.py`) |
| NOTIF-06 | `notification_log` status transitions `sent → delivered` (Twilio status webhook) and `sent → clicked` (`/go`) | integration | `uv run pytest tests/integration/test_notification_log_transitions.py -x -q` | ❌ Wave 0 |
| **SC2** | `MISE_CRASH_AFTER=provider_ack` SIGKILL between provider ack and commit → **exactly one** mocked-provider call (`route.call_count == 1`) and one `sent` row per `(watch, channel)` after restart | integration (chaos) | `uv run pytest tests/integration/test_notifier_chaos.py -x -q` | ❌ Wave 0 (model on `test_state_machine_chaos.py`) |
| NOTIF-07 | Token sign/verify; wrong purpose rejected; expired rejected; v1→v2 rotation inside and outside the grace window; tampered signature rejected | unit | `uv run pytest tests/unit/test_tokens.py -x -q` | ❌ Wave 0 |
| NOTIF-07 | `platform_booking_url` shape for both sources; slug/date/time encoding | unit | `uv run pytest tests/unit/test_links.py -x -q` | ❌ Wave 0 |
| NOTIF-07 | `GET /go/{token}` → 302 to the platform URL when available, 200 "gone" page otherwise; `clicked_at` and `slot_still_available` both written | integration (ASGI) | `uv run pytest tests/integration/test_api_go.py -x -q` | ❌ Wave 0 |
| PERF-01 | `latency_ms = sent_at − produced_at`; negative values clamped and warned; end-to-end `availability.events` → `notifications.sent` with a populated `latency_ms` | integration | `uv run pytest tests/integration/test_notifier_e2e.py -x -q` | ❌ Wave 0 |
| PERF-01 | `check_notification_latency.py` exits 0 / 1 / 2 on synthetic pass / fail / <100-sample fixtures | integration | `uv run pytest tests/integration/test_check_notification_latency.py -x -q` | ❌ Wave 0 |
| PERF-01 | 24 h production p95 window | **manual** | `make verify-perf01` — `docs/runbooks/perf01-latency.md`, `STATUS: pending-human` | n/a |
| PERF-03 | `check_false_positive_rate.py` exit codes; denominator excludes `slot_still_available IS NULL` | integration | `uv run pytest tests/integration/test_check_false_positive_rate.py -x -q` | ❌ Wave 0 |
| D-85 | Phone AES-256-GCM round trip, nonce uniqueness, `InvalidTag` on tamper, key-length guard; `phone_hash` stability and canonicalisation | unit | `uv run pytest tests/unit/test_crypto.py -x -q` | ❌ Wave 0 |
| D-85 | Migration 0010 applies on a fresh DB and downgrades cleanly; duplicate guard raises on pre-existing duplicates | integration | `uv run pytest tests/integration/test_migration_0010.py -x -q` | ❌ Wave 0 |
| D-84 | Resend webhook Svix verification against both published vectors; tampered body rejected | unit | `uv run pytest tests/unit/test_svix_signature.py -x -q` | ❌ Wave 0 |
| D-79 | No `asyncio.sleep(` / `time.sleep(` in `services/notifier`, `services/notifier/providers`, `services/api` | unit (grep) | `uv run pytest tests/unit/test_no_inline_sleep.py -x -q` | ✅ extend |
| BC-3 | `python-multipart` stays out of `[project].dependencies` | unit | `uv run pytest tests/unit/test_no_new_runtime_deps.py -x -q` | ❌ Wave 0 |
| Pitfall 12 | Redaction covers the new secret and value-shaped keys; no rendered body / phone / token in any log call | unit | `uv run pytest tests/unit/test_telemetry_redaction.py tests/unit/test_logs_never_carry_payload.py -x -q` | ✅ extend |
| NOTIF-05 | Real-iPhone PWA push (3+ consecutive sends, subscription survives) | **manual** | `docs/runbooks/ios-pwa-push.md`, `STATUS: pending-human` | n/a |

### Sampling Rate

- **Per task commit:** `make test` (unit tier, `-x -q`) plus `make lint`. Both are seconds-scale and catch every grep gate, every signature vector, the SMS budget and the `mypy --strict` regressions.
- **Per wave merge:** `make test-integration` (unit + integration, Docker required).
- **Phase gate:** full suite green, plus `make verify-perf01` / `make verify-perf03` exercised against the synthetic fixtures (exit-code contract proven) before `/gsd-verify-work`. The live 24 h window and the iPhone test remain `pending-human` and must be reported as such — not as passes.

### Wave 0 Gaps

- [ ] `tests/unit/gsm7.py` — shared GSM 03.38 septet helper used by `test_sms_length.py` (covers NOTIF-04)
- [ ] `tests/unit/fixtures/vectors.py` — the two Svix vectors and the four Twilio vectors as parametrisable constants (covers NOTIF-04, D-84)
- [ ] `tests/unit/factories.py` — extend with `make_availability_event`, `make_watch_row`, `make_notification_queued` (file exists; add builders)
- [ ] `tests/integration/conftest.py` — add `seed_user_and_watch(session, …)` (must set `created_at`/`updated_at` explicitly — no server defaults) and a `fake_push_subscription()` generating a real P-256 keypair so push assertions can decrypt
- [ ] `tests/integration/conftest.py` — add an `api_client` fixture wrapping `httpx.AsyncClient(transport=ASGITransport(app=create_app()), base_url="https://api.mise.place")`
- [ ] Extend `tests/unit/test_no_inline_sleep.py` `SCANNED_FILES` and raise the non-vacuity floor
- [ ] Extend `tests/unit/test_no_setnx_expire_pairs.py` (no change needed — it already scans `services/` recursively; add an assertion that `services/notifier` is in the scanned set so it cannot silently miss the new tree)
- [ ] No framework install needed — pytest, pytest-asyncio, respx and testcontainers are all present

---

## Security Domain

`security_enforcement` is not set in `.planning/config.json`, so it is enabled by default.

### Applicable ASVS Categories

| ASVS category | Applies | Standard control |
|---------------|---------|------------------|
| V2 Authentication | partial | No user accounts by design (WATCH-01). Auth to *providers* is a Bearer token (Resend) and HTTP Basic (Twilio); both from env, never logged |
| V3 Session Management | no | Stateless; no sessions, no cookies. RFC 8058 explicitly forbids cookies on the unsubscribe POST |
| V4 Access Control | **yes** | Capability tokens are the entire access-control model. Every token carries `p` (purpose) and `v` (version); a purpose mismatch is rejected. `/go` grants only a redirect + a click record; `unsubscribe` grants only a pause |
| V5 Input Validation | **yes** | Pydantic v2 with `extra="forbid"` on every Kafka schema; `parse_qsl` on webhook bodies with signature verification *before* any use; a rejected signature performs no DB write |
| V6 Cryptography | **yes** | `cryptography` AES-256-GCM (12-byte nonce, never reused), HMAC-SHA256 tokens and `phone_hash`, HMAC-SHA1 only where Twilio's protocol mandates it, `hmac.compare_digest` everywhere. Zero hand-rolled primitives |
| V7 Error Handling & Logging | **yes** | `_failure_shape()` instead of `str(exc)`; `shared/telemetry.py` redaction extended (Pitfall 12) |
| V8 Data Protection | **yes** | Phone numbers encrypted at rest, decrypted only inside `SmsProvider` at send time (WATCH-05, D-85). VAPID private key and HMAC secrets from env only — never in git |
| V9 Communications | **yes** | HTTPS to every provider; `List-Unsubscribe` must be an HTTPS URI (RFC 8058) |
| V13 API & Web Service | **yes** | Every inbound webhook signature-verified before any side effect; a 403 short-circuits before the DB |

### Known Threat Patterns

| Pattern | STRIDE | Standard mitigation |
|---------|--------|---------------------|
| Forged Twilio inbound STOP (attacker pauses a stranger's watches) | Spoofing | `X-Twilio-Signature` verified against the config-derived URL with `compare_digest`; verify **before** the phone lookup |
| Forged Resend webhook (marks a failed send delivered) | Spoofing | Svix HMAC-SHA256 over the raw body + timestamp tolerance |
| Token forgery / truncation on `/go` and `/unsubscribe` | Spoofing, Elevation | Full 32-byte HMAC (no truncation), versioned secrets, purpose claim, constant-time compare |
| Token-confusion (an `unsubscribe` token replayed at `/go`, or vice versa) | Elevation | The `p` claim is checked against the route's expected purpose |
| Signature timing oracle | Information Disclosure | `hmac.compare_digest` on every comparison — never `==` |
| Replay of a captured webhook | Tampering | Svix timestamp tolerance; Twilio status callbacks are idempotent by `provider_id` |
| Provider-controlled `Retry-After` used as a DoS | Denial of Service | Clamp to 30 s (Pitfall 5) |
| Notification bombing a single user | Denial of Service | `rate:notif:{user}:{day}` cap (D-74) |
| Log-based disclosure of a `/go` token, a phone number, a rendered body, or an API key | Information Disclosure | `_failure_shape()`, extended `_redact_secrets`, and `tests/unit/test_logs_never_carry_payload.py` |
| Redis eviction discarding a live idempotency key | Tampering | `maxmemory-policy=noeviction` (already set in `tests/conftest.py:34` and PITFALLS §Redis) |
| VAPID private key exposure (permanent push capability over every subscriber) | Elevation | Env/secret manager only, one keypair per environment, `VAPID_PRIVATE_KEY` already in the redaction set |
| Ciphertext-swap between user rows | Tampering | Out of scope for v1 — see OQ-3 |
| SQL injection through event fields | Tampering | SQLAlchemy Core with bound parameters throughout; no string-built SQL |

---

## Sources

### Primary (HIGH confidence — executed in this repo's `.venv`, 2026-09-05)

- Package versions via `importlib.metadata.version` — fastapi 0.136.0, starlette 0.52.1, httpx 0.28.1, tenacity 9.1.4, pywebpush 2.3.0, py_vapid 1.9.4, http_ece 1.2.1, resend 2.29.0, twilio 9.10.5, cryptography 46.0.7, sqlalchemy 2.0.49, aiokafka 0.13.0, redis 7.4.0, pydantic 2.13.3, respx 0.23.1, pytest-asyncio 1.3.0, prometheus-client 0.25.0, Python 3.12.13; `python-multipart` absent
- Transitive-import probe (one fresh interpreter per module) — `pywebpush → requests, aiohttp, urllib3`; `py_vapid`, `http_ece`, `cryptography...aead` clean
- `inspect.getsource(pywebpush.WebPusher.encode)` and `pywebpush/__init__.py` module header
- VAPID keypair generation + `Vapid.from_string` + `sign` under cryptography 46.0.7; default-`exp` probe; missing-`sub` probe
- `http_ece.encrypt`/`decrypt` round trip (217-byte aes128gcm record) both via `pywebpush.encode` and directly
- `AESGCM` phone encrypt/decrypt/tamper; HMAC-SHA256 `phone_hash`; token size matrix; GSM 03.38 septet measurement over all 55 seeded restaurant names
- `twilio_signature` vs `twilio.request_validator.RequestValidator` on four inputs plus the `bodySHA256` JSON variant
- Svix verifier against both published vectors, plus tamper and multi-signature cases
- `respx` route-count oracle, `host__in` list/tuple hashability, `assert_all_called`
- FastAPI + `httpx.ASGITransport` in-process routes; `Form(...)` and `Request.form()` failures without `python-multipart`
- `tenacity` `AsyncRetrying` + decorator with a `Retry-After`-aware wait; `tenacity/asyncio/__init__.py:64` sleep site
- Redis 7.2.16 (throwaway container): rate-limit Lua, `set_nx_ex` claim/reclaim, MULTI/EXEC sliding-window demonstration
- `prometheus_client` duplicate-registration error and `_total` family-name behaviour
- SQLAlchemy pre-filter compiled to PostgreSQL SQL with literal binds
- `mypy --strict` and `ruff check` over a 130-line sketch covering tokens, Twilio, Svix, phone crypto, VAPID and push

### Primary (HIGH confidence — repository files read this session)

`CLAUDE.md`, `pyproject.toml`, `.ruff.toml`, `Makefile`, `.env.example`; `shared/{events,kafka,http_client,telemetry,redis_keys,db,shutdown}.py`; `services/state_machine/{consumer,main,config,store,persistence}.py`; `scripts/{create_topics,check_poll_success}.py`; `migrations/versions/{0005,0008}_*.py`; `tests/conftest.py`, `tests/integration/{conftest,test_state_machine_chaos}.py`, `tests/unit/{test_no_inline_sleep,test_no_setnx_expire_pairs}.py`; `.planning/{REQUIREMENTS,STATE,deferred-items,config.json}`; `.planning/research/{ARCHITECTURE,PITFALLS,STACK}.md`; `.planning/phases/02-*/02-{CONTEXT,REVIEW-FIX}.md`; `.planning/phases/03-*/03-CONTEXT.md` and plans 03-01/03-02/03-03; `.planning/phases/04-*/04-CONTEXT.md`

### Secondary (MEDIUM confidence — official vendor documentation)

- resend.com/docs/api-reference/emails/send-email — method, body fields, headers, `Idempotency-Key`, 200 response
- resend.com/docs/api-reference/errors — the full error-code table
- resend.com/docs/dashboard/webhooks/verify-webhooks-requests — Svix headers, raw-body requirement
- docs.svix.com/receiving/verifying-payloads/how-manual — signed-content construction, secret decoding, header format, tolerance, worked example
- twilio.com/docs/messaging/api/message-resource — URL, auth, parameters, 201, status vocabulary
- twilio.com/docs/usage/webhooks/webhooks-security — HMAC-SHA1 scheme, worked example, `bodySHA256` JSON variant
- rfc-editor.org/rfc/rfc8030 — Web Push status-code semantics (201/400/404/410/413/429)

### Tertiary (LOW confidence — community sources, marked `[ASSUMED]` in the text)

- OpenTable / Resy deep-link URL shapes (A1, A2) — third-party reconstructions only; the public RestRef API is reported shut down
- Apple `web.push.apple.com` VAPID `sub`/`aud`/`exp` constraints — consistent across multiple `web-push-libs` issue threads and Apple Developer Forums, but the primary Apple documentation page could not be retrieved this session
- RFC 8058 operational guidance (DKIM coverage of the two headers, 48 h processing) — vendor blogs (Mailgun, Customer.io), consistent with the RFC abstract

---

## Metadata

**Confidence breakdown:**

- Standard stack — **HIGH**: nothing new is added; every version read from `.venv`, every critical API exercised
- Provider crypto and signature schemes — **HIGH**: reproduces published vectors and the vendor SDK's own output
- Provider REST contracts — **MEDIUM**: official docs, not exercised against live accounts (human-gated)
- Architecture and crash ordering — **HIGH**: the pattern is already shipped and chaos-proven in Phase 2; this phase repeats its shape
- SMS budget, token sizes, SQL shape, test harness — **HIGH**: measured
- Pitfalls — **HIGH** for the eight reproduced as errors; **MEDIUM** for the iOS revocation pattern (documented behaviour, device-gated)
- Deep-link URLs — **LOW**: unchanged `[ASSUMED]`, matching D-83's own disclaimer

**Research date:** 2026-09-05
**Valid until:** 2026-10-05 for provider REST contracts (Resend and Twilio ship API changes on a monthly cadence); indefinite for the pinned-library findings, which are version-locked by `pyproject.toml`.
