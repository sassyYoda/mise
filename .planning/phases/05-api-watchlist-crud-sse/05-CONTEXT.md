# Phase 5: API, Watchlist CRUD & SSE - Context

**Gathered:** 2026-09-05
**Status:** Ready for planning
**Mode:** Autonomous smart discuss — recommended answers accepted for every grey area (no human available; defaults chosen for consistency with PROJECT.md, REQUIREMENTS.md and Phases 1–4 decisions D-01..D-89)

<domain>
## Phase Boundary

Grow the FastAPI application skeleton created in Phase 4 (`services/api/app.py`, `/go`, `/unsubscribe`, provider webhooks) into the stateless API the Phase 6 PWA consumes: watchlist CRUD with HMAC-SHA256 management tokens (monthly rotation, 7-day dual-version grace), email-only user identity, AES-256-GCM phone storage, a per-IP 60 req/min limit on watch creation, CORS, structured JSON request logging, an SSE live feed multicast from a single background Kafka consumer per process (15 s heartbeats, `Last-Event-ID` replay), public restaurant/stats endpoints, HTTP-Basic admin routes (restaurant CRUD, polling-tier override, per-restaurant event volume, system health), and a public Prometheus `/api/metrics` — all curl-testable before the frontend exists. Requirements: WATCH-01..06, API-01..03.

**Human-gated (build around):** the "SSE through the actual Cloud Run URL" and Cloud Run proxy behaviour (Phase 7 deploy); measured locally with the same headers. Everything else in this phase runs locally against testcontainers.

Out of scope: pattern/heatmap endpoints (Phase 6 adds `/api/restaurants/{slug}/heatmap` and `/pattern` on top of this router), Dockerfiles/deploy (Phase 7), the management *page* (Phase 6 — this phase ships `GET /api/manage/{token}`).

</domain>

<decisions>
## Implementation Decisions

### Identity, tokens, rotation (WATCH-01, WATCH-03)
- **D-90:** Users are identified by email only; `POST /watches` upserts `users` by lower-cased, stripped email (`ON CONFLICT (email) DO UPDATE SET updated_at = now()` returning id). No passwords, no sessions, no cookies.
- **D-91:** Management tokens are `shared/tokens.py` tokens (Phase 4 D-82) with `purpose="manage"` and claims `{user_id, purpose, token_version, issued_at, expires_at}` (`expires_at` = issued + 30 days). The management URL is path-based: `{PUBLIC_BASE_URL}/manage/t/{token}` (Phase 6 page) and the API accepts the token as the path segment on `GET /api/manage/{token}` or as `Authorization: Bearer {token}` on `/watches/*`. Tokens are never stored — `watchlist_entries.management_token` (Phase 1 column) stays NULL; verification is purely HMAC.
- **D-92:** Rotation: `HMAC_TOKEN_VERSION` names the signing version, `HMAC_MGMT_SECRET_V{n}` holds each secret, `HMAC_GRACE_UNTIL` (ISO date) is the cutover: a token signed with version N−1 verifies until that date and fails after it (ROADMAP SC2 dry-run). `scripts/rotate_hmac_secret.py --dry-run` prints the env changes for a rotation and `tests/unit/test_token_rotation.py` proves the grace window with `freezegun`. On every successful `POST /watches` and on `GET /api/manage/{token}` responses the API returns a freshly signed current-version token so clients migrate naturally.

### Watch creation and editing (WATCH-02, WATCH-04, WATCH-05, WATCH-06)
- **D-93:** `POST /watches` (pydantic `WatchCreate`): `email`, `restaurant_slug`, `party_size` (1–10), `date_from`/`date_to` (`date_to >= date_from`, window ≤ 60 days, `date_from >= today`), optional `time_window_from`/`time_window_to` (`HH:MM`, from < to), optional `days_of_week` (subset of `mon..sun`), optional `seat_type_filter`, `channels` (non-empty subset of `email,sms,push`; `sms` requires `phone` E.164; `push` requires `push_subscription` `{endpoint, keys{p256dh, auth}}`), optional `phone`, optional `push_subscription`. Restaurant resolution by slug → the row set from `restaurants` (one per source after Phase 3's `UNIQUE(slug, source)`); the watch is stored against the **OpenTable row when present, else the Resy row** and a `sources` list is echoed back (a watch matches events from every source row sharing the slug — Phase 4 `match_watches` joins by `restaurants.id`, so the fan-out query is extended to `restaurants.slug` equality; document in the notifier README). Response `201 {watch: {...}, management_url, token}`; also sends the management-link transactional email through the Phase 4 `EmailProvider` (dry-run aware) — best effort, failures logged, never fail the request.
- **D-94:** Phones are stored only as `users.phone = encrypt_phone(e164)` (AES-256-GCM, Phase 4 `shared/crypto.py`) plus `users.phone_hash`; the API never returns a phone (responses show `phone_masked` = last 2 digits). A DB-level integration test asserts the stored bytes are not the plaintext and that `decrypt_phone` round-trips. Push subscriptions upsert into `push_subscriptions` by `endpoint` (`revoked_at = NULL` on re-subscribe).
- **D-95:** Management endpoints (Bearer token, user-scoped — a watch belonging to another user is a 404, never a 403): `GET /watches` (list active + paused with per-watch notification history: last 20 `notification_log` rows incl. `slot_still_available`), `PATCH /watches/{id}` (`status: paused|active` for pause/resume; editable `party_size`, `date_from`, `date_to`, `time_window_*`, `days_of_week`, `seat_type_filter`, `channels`, `phone`), `DELETE /watches/{id}` (soft delete: `status='deleted'`, Phase 4 D-89). `GET /api/manage/{token}` returns the same list plus a fresh token (Phase 6 page hydration). Every mutation updates the Redis `watch:count` HASH field `{source}:{platform_id}` for each source row of the restaurant (count of `status='active'` watches — Phase 3 D-58) inside the same request via a small `shared/watch_counts.py :: recount(restaurant_slug)` helper.
- **D-96:** Rate limit: `POST /watches` is limited to 60 req/min per client IP (`X-Forwarded-For` first hop when `TRUST_PROXY_HEADERS=true`, else the socket peer) with a Redis fixed-window counter `rate:api:watch_create:{ip}:{epoch_minute}` via the Phase 4 Lua `INCR` + conditional `EXPIRE 120`; the 61st request returns `429` with `Retry-After`. Implemented as a FastAPI dependency (`services/api/ratelimit.py`), no third-party limiter.

### Application plumbing (API-01)
- **D-97:** `create_app()` adds `CORSMiddleware` (`CORS_ALLOWED_ORIGINS` comma list, default `http://localhost:3000`), a structlog request-logging middleware (`request_id` from `X-Request-ID` or uuid4, method, path template, status, `duration_ms`, client ip — no bodies, no tokens: paths containing tokens are logged with the token replaced by `{token}`), and global exception handlers that return JSON `{error, request_id}` without stack traces. Health: `GET /healthz` (liveness) and `GET /readyz` (checks DB `SELECT 1`, Redis `PING`, Kafka consumer running). Config through functions in `services/api/config.py` (lazy env — Phase 2 lesson). Lifespan (`AsyncExitStack`): DB engine, Redis client, shared httpx client, the SSE hub's Kafka consumer, signal handling via `shared/shutdown.py` (Phase 2 WR-02).

### SSE live feed (API-02)
- **D-98:** `services/api/sse.py :: FeedHub` — exactly one background task per process consuming `availability.events` with `AIOKafkaConsumer("availability.events", group_id=None, auto_offset_reset="latest", enable_auto_commit=False)` (no group → no offset commits, every process sees every event), enriching each `AvailabilityEvent` with `restaurant_name`/`slug`/`neighborhood` via an LRU-cached `(source, platform_id)` lookup, appending to an in-memory ring buffer (last 100 events, keyed by `event_id`) and putting the message on every connection's `asyncio.Queue(maxsize=100)` (if full, drop the oldest for that connection and increment `sse_dropped_total`). `GET /api/feed/live` returns `StreamingResponse` (`text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`) writing `id: {event_id}\nevent: slot_opened\ndata: {json}\n\n` per event and a `: ping` comment every 15 s (`asyncio.wait_for(queue.get(), timeout=15)` — no sleep loop). `Last-Event-ID` (header or `?last_event_id=`) replays the ring-buffer events after that id before streaming live. `GET /api/feed/recent?limit=5` (max 50) hydrates from the same ring buffer, falling back to the last N rows of `availability_events` when the buffer is empty (fresh process).
- **D-99:** The ≤ 500 ms first-event latency (SC3) is asserted locally by an integration test that opens the stream, publishes an event to Kafka, and measures receipt; the Cloud Run proxy measurement is pending-human (Phase 7 runbook).

### Public read endpoints and metrics (API-03, FE-02 support)
- **D-100:** `GET /api/restaurants` (query `q` name/neighborhood/cuisine substring, `neighborhood`, `cuisine`, `price_tier`, paginated `limit`/`offset`, default 50) and `GET /api/restaurants/{slug}` return the merged logical restaurant: one object with `sources: [{source, platform_id}]`, `active_watch_count` (from `watch:count`), `recent_events` (last 10 `availability_events` rows across its source rows), `cover_photo_url`, etc. Phase 6 adds `/heatmap` and `/pattern` sub-routes. `GET /api/stats` → `{active_watches, events_24h, notifications_sent_24h, restaurants}` (social-proof counter, cached 30 s in Redis).
- **D-101:** `GET /api/metrics` exposes the process-wide `prometheus_client` registry (Phase 3 `shared/metrics.py` + `prometheus-fastapi-instrumentator` request metrics) in text format, unauthenticated, excluded from request logging. API-specific metrics: `sse_connections_active`, `sse_events_sent_total`, `sse_dropped_total`, `watch_create_total{result}`, `api_rate_limited_total`.
- **D-102:** Push helpers: `GET /api/push/vapid-public-key` (from `VAPID_PUBLIC_KEY`), `POST /api/push/subscribe` (Bearer management token + subscription JSON) and `DELETE /api/push/subscribe` (by endpoint) — Phase 6's service worker uses these.

### Admin (API-03)
- **D-103:** `/admin/*` behind HTTP Basic (`ADMIN_BASIC_USER`/`ADMIN_BASIC_PASSWORD`, `hmac.compare_digest`, `WWW-Authenticate: Basic realm="mise-admin"`, 401 on missing/incorrect, routes disabled with 404 when the env vars are unset): `GET/POST/PATCH/DELETE /admin/restaurants[/{id}]` (all `restaurants` columns; create seeds `sched:polls` for the new `(source, platform_id)` like `seed_restaurants.py`; delete only when no active watches, else 409), `PUT /admin/restaurants/{slug}/tier {tier: 1|2|3|null}` → writes/clears `tier:override` (Phase 3 D-58), `GET /admin/restaurants/{slug}/events?window=24h|7d` (event counts + latest 50), `GET /admin/health` (Kafka topic/lag summary via `AIOKafkaAdminClient` + `end_offsets` vs committed offsets for groups `state-machine`/`notifier`, last successful poll per source from `poll_log`, Redis/DB ping, poll success rate last hour). All admin mutations are logged with `admin_user`.

### Test strategy
- **D-104:** Unit: request models/validators (every WATCH-02 rule), token rotation with `freezegun`, rate-limit window math, SSE framing (`id:/event:/data:` bytes, ping), ring-buffer replay after `Last-Event-ID`, basic-auth compare, request-log redaction of tokens. Integration (testcontainers, `httpx.ASGITransport`): `POST /watches` → user + watch rows, ciphertext phone bytes, `watch:count` updated, management email dry-run recorded; CRUD lifecycle incl. soft delete and cross-user 404; 61st POST → 429; SSE first-event ≤ 500 ms after a Kafka publish and `Last-Event-ID` reconnect replay; `/api/metrics` contains `sse_connections_active`; admin CRUD + tier override + 401; `/readyz`. An OpenAPI snapshot test (`tests/unit/test_openapi_snapshot.py`) pins the public route list so Phase 6 can rely on it. `docs/api.md` documents every route with curl examples (portfolio artifact; Phase 7 README links it).

### Claude's Discretion
- Router/module layout under `services/api/routers/` (`watches.py`, `manage.py`, `restaurants.py`, `feed.py`, `admin.py`, `push.py`, `metrics.py`, `health.py` suggested); pydantic response model names; LRU cache sizes; pagination defaults.
- Whether the management-link email is sent inline or via a background task (`BackgroundTasks`) — either is fine as long as it never fails the request.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase 4: `services/api/app.py :: create_app()` and routers `links.py`/`webhooks.py` (extend, don't rewrite); `shared/tokens.py` (sign/verify with versions + grace), `shared/crypto.py` (`encrypt_phone`/`decrypt_phone`, `phone_hash`), `services/notifier/providers/email.py` (`EmailProvider`, dry-run), `services/notifier/matching.py` + fan-out SQL (extend the join to slug-siblings), `shared/redis_keys.py` daily-cap Lua (reuse for the per-IP window).
- Phase 3: `shared/metrics.py` (single registry), `watch:count` / `tier:override` HASH helpers (D-58), `shared/telemetry.py` redaction.
- Phase 2: `shared/kafka.py :: make_consumer`, `services/state_machine/main.py` lifespan + `shared/shutdown.py`, `services/state_machine/config.py` lazy-env pattern, `RedisStateStore` read path.
- Phase 1: `shared/db.py` ORM (`User`, `Restaurant`, `WatchlistEntry`, `NotificationLog`, `PollLog`), `scripts/seed_restaurants.py` (seeding `sched:polls` for a new restaurant), `scripts/verify_seed.py`.
- Tests: `tests/integration/conftest.py` (containers, env-freeze workaround), Phase 4 `ASGITransport` tests.

### Established Patterns
- Async-only; lazy env; every Redis key in `shared/redis_keys.py`; every Kafka schema in `shared/events.py`; never `str(exc)` in logs (`safe_error`); grep gates with non-vacuity checks; small atomic commits.

### Integration Points
- Consumes `availability.events` (SSE) and reads `availability_events`, `poll_log`, `notification_log`, `restaurants`, `watchlist_entries`, `users`, `push_subscriptions`; writes users/watches/push_subscriptions/restaurants (admin) and Redis `watch:count`, `tier:override`, `rate:api:*`, `sched:polls` (admin create).
- Phase 6 consumes: `/api/restaurants*`, `/api/feed/live|recent`, `/api/stats`, `/watches*`, `/api/manage/{token}`, `/api/push/*`, `/go/{token}` (Phase 4), plus OpenAPI at `/openapi.json`.
- Makefile: `make api` (uvicorn, reload in dev), `make api-smoke` (curl script); `.env.example` API block (`PUBLIC_BASE_URL`, `CORS_ALLOWED_ORIGINS`, `ADMIN_BASIC_*`, `TRUST_PROXY_HEADERS`, `HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL`, `API_PORT`).

</code_context>

<specifics>
## Specific Ideas

- `docs/api.md` with curl walkthroughs for the full watch lifecycle is a portfolio artifact — write it as the SC "testable end-to-end via curl" evidence.
- Keep `/api/feed/live` boring and correct: one consumer, queues, ping every 15 s, `X-Accel-Buffering: no`.

</specifics>

<deferred>
## Deferred Ideas

- OAuth2 admin (V2-08); multi-party-size watches (V2-09); WebSocket feed; per-user API keys.
- Cloud Run proxy SSE verification (Phase 7 runbook).

</deferred>
