# Phase 5: API, Watchlist CRUD & SSE - Research

**Researched:** 2026-09-05
**Domain:** Stateless async HTTP API (FastAPI/Starlette/uvicorn) + Server-Sent Events fan-out from Kafka + Postgres CRUD + Redis rate limiting
**Confidence:** HIGH — every version, API shape, framing byte, timing number and failure mode below was executed in this repository's own `.venv` (fastapi 0.136.0 / starlette 0.52.1 / uvicorn 0.44.0 / httpx 0.28.1 / pydantic 2.13.3 / SQLAlchemy 2.0.49 / aiokafka 0.13.0 / redis-py 7.4.0) against real Kafka 7.6.0, Redis 7.2.16 and TimescaleDB 2.17.2-pg16 containers on 2026-09-05.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Identity, tokens, rotation (WATCH-01, WATCH-03)**
- **D-90:** Users are identified by email only; `POST /watches` upserts `users` by lower-cased, stripped email (`ON CONFLICT (email) DO UPDATE SET updated_at = now()` returning id). No passwords, no sessions, no cookies.
- **D-91:** Management tokens are `shared/tokens.py` tokens (Phase 4 D-82) with `purpose="manage"` and claims `{user_id, purpose, token_version, issued_at, expires_at}` (`expires_at` = issued + 30 days). The management URL is path-based: `{PUBLIC_BASE_URL}/manage/t/{token}` (Phase 6 page) and the API accepts the token as the path segment on `GET /api/manage/{token}` or as `Authorization: Bearer {token}` on `/watches/*`. Tokens are never stored — `watchlist_entries.management_token` (Phase 1 column) stays NULL; verification is purely HMAC.
- **D-92:** Rotation: `HMAC_TOKEN_VERSION` names the signing version, `HMAC_MGMT_SECRET_V{n}` holds each secret, `HMAC_GRACE_UNTIL` (ISO date) is the cutover: a token signed with version N−1 verifies until that date and fails after it (ROADMAP SC2 dry-run). `scripts/rotate_hmac_secret.py --dry-run` prints the env changes for a rotation and `tests/unit/test_token_rotation.py` proves the grace window with `freezegun`. On every successful `POST /watches` and on `GET /api/manage/{token}` responses the API returns a freshly signed current-version token so clients migrate naturally.

**Watch creation and editing (WATCH-02, WATCH-04, WATCH-05, WATCH-06)**
- **D-93:** `POST /watches` (pydantic `WatchCreate`): `email`, `restaurant_slug`, `party_size` (1–10), `date_from`/`date_to` (`date_to >= date_from`, window ≤ 60 days, `date_from >= today`), optional `time_window_from`/`time_window_to` (`HH:MM`, from < to), optional `days_of_week` (subset of `mon..sun`), optional `seat_type_filter`, `channels` (non-empty subset of `email,sms,push`; `sms` requires `phone` E.164; `push` requires `push_subscription` `{endpoint, keys{p256dh, auth}}`), optional `phone`, optional `push_subscription`. Restaurant resolution by slug → the row set from `restaurants` (one per source after Phase 3's `UNIQUE(slug, source)`); the watch is stored against the **OpenTable row when present, else the Resy row** and a `sources` list is echoed back (a watch matches events from every source row sharing the slug — Phase 4 `match_watches` joins by `restaurants.id`, so the fan-out query is extended to `restaurants.slug` equality; document in the notifier README). Response `201 {watch: {...}, management_url, token}`; also sends the management-link transactional email through the Phase 4 `EmailProvider` (dry-run aware) — best effort, failures logged, never fail the request.
- **D-94:** Phones are stored only as `users.phone = encrypt_phone(e164)` (AES-256-GCM, Phase 4 `shared/crypto.py`) plus `users.phone_hash`; the API never returns a phone (responses show `phone_masked` = last 2 digits). A DB-level integration test asserts the stored bytes are not the plaintext and that `decrypt_phone` round-trips. Push subscriptions upsert into `push_subscriptions` by `endpoint` (`revoked_at = NULL` on re-subscribe).
- **D-95:** Management endpoints (Bearer token, user-scoped — a watch belonging to another user is a 404, never a 403): `GET /watches` (list active + paused with per-watch notification history: last 20 `notification_log` rows incl. `slot_still_available`), `PATCH /watches/{id}` (`status: paused|active` for pause/resume; editable `party_size`, `date_from`, `date_to`, `time_window_*`, `days_of_week`, `seat_type_filter`, `channels`, `phone`), `DELETE /watches/{id}` (soft delete: `status='deleted'`, Phase 4 D-89). `GET /api/manage/{token}` returns the same list plus a fresh token (Phase 6 page hydration). Every mutation updates the Redis `watch:count` HASH field `{source}:{platform_id}` for each source row of the restaurant (count of `status='active'` watches — Phase 3 D-58) inside the same request via a small `shared/watch_counts.py :: recount(restaurant_slug)` helper.
- **D-96:** Rate limit: `POST /watches` is limited to 60 req/min per client IP (`X-Forwarded-For` first hop when `TRUST_PROXY_HEADERS=true`, else the socket peer) with a Redis fixed-window counter `rate:api:watch_create:{ip}:{epoch_minute}` via the Phase 4 Lua `INCR` + conditional `EXPIRE 120`; the 61st request returns `429` with `Retry-After`. Implemented as a FastAPI dependency (`services/api/ratelimit.py`), no third-party limiter.

**Application plumbing (API-01)**
- **D-97:** `create_app()` adds `CORSMiddleware` (`CORS_ALLOWED_ORIGINS` comma list, default `http://localhost:3000`), a structlog request-logging middleware (`request_id` from `X-Request-ID` or uuid4, method, path template, status, `duration_ms`, client ip — no bodies, no tokens: paths containing tokens are logged with the token replaced by `{token}`), and global exception handlers that return JSON `{error, request_id}` without stack traces. Health: `GET /healthz` (liveness) and `GET /readyz` (checks DB `SELECT 1`, Redis `PING`, Kafka consumer running). Config through functions in `services/api/config.py` (lazy env — Phase 2 lesson). Lifespan (`AsyncExitStack`): DB engine, Redis client, shared httpx client, the SSE hub's Kafka consumer, signal handling via `shared/shutdown.py` (Phase 2 WR-02).

**SSE live feed (API-02)**
- **D-98:** `services/api/sse.py :: FeedHub` — exactly one background task per process consuming `availability.events` with `AIOKafkaConsumer("availability.events", group_id=None, auto_offset_reset="latest", enable_auto_commit=False)` (no group → no offset commits, every process sees every event), enriching each `AvailabilityEvent` with `restaurant_name`/`slug`/`neighborhood` via an LRU-cached `(source, platform_id)` lookup, appending to an in-memory ring buffer (last 100 events, keyed by `event_id`) and putting the message on every connection's `asyncio.Queue(maxsize=100)` (if full, drop the oldest for that connection and increment `sse_dropped_total`). `GET /api/feed/live` returns `StreamingResponse` (`text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`) writing `id: {event_id}\nevent: slot_opened\ndata: {json}\n\n` per event and a `: ping` comment every 15 s (`asyncio.wait_for(queue.get(), timeout=15)` — no sleep loop). `Last-Event-ID` (header or `?last_event_id=`) replays the ring-buffer events after that id before streaming live. `GET /api/feed/recent?limit=5` (max 50) hydrates from the same ring buffer, falling back to the last N rows of `availability_events` when the buffer is empty (fresh process).
- **D-99:** The ≤ 500 ms first-event latency (SC3) is asserted locally by an integration test that opens the stream, publishes an event to Kafka, and measures receipt; the Cloud Run proxy measurement is pending-human (Phase 7 runbook).

**Public read endpoints and metrics (API-03, FE-02 support)**
- **D-100:** `GET /api/restaurants` (query `q` name/neighborhood/cuisine substring, `neighborhood`, `cuisine`, `price_tier`, paginated `limit`/`offset`, default 50) and `GET /api/restaurants/{slug}` return the merged logical restaurant: one object with `sources: [{source, platform_id}]`, `active_watch_count` (from `watch:count`), `recent_events` (last 10 `availability_events` rows across its source rows), `cover_photo_url`, etc. Phase 6 adds `/heatmap` and `/pattern` sub-routes. `GET /api/stats` → `{active_watches, events_24h, notifications_sent_24h, restaurants}` (social-proof counter, cached 30 s in Redis).
- **D-101:** `GET /api/metrics` exposes the process-wide `prometheus_client` registry (Phase 3 `shared/metrics.py` + `prometheus-fastapi-instrumentator` request metrics) in text format, unauthenticated, excluded from request logging. API-specific metrics: `sse_connections_active`, `sse_events_sent_total`, `sse_dropped_total`, `watch_create_total{result}`, `api_rate_limited_total`.
- **D-102:** Push helpers: `GET /api/push/vapid-public-key` (from `VAPID_PUBLIC_KEY`), `POST /api/push/subscribe` (Bearer management token + subscription JSON) and `DELETE /api/push/subscribe` (by endpoint) — Phase 6's service worker uses these.

**Admin (API-03)**
- **D-103:** `/admin/*` behind HTTP Basic (`ADMIN_BASIC_USER`/`ADMIN_BASIC_PASSWORD`, `hmac.compare_digest`, `WWW-Authenticate: Basic realm="mise-admin"`, 401 on missing/incorrect, routes disabled with 404 when the env vars are unset): `GET/POST/PATCH/DELETE /admin/restaurants[/{id}]` (all `restaurants` columns; create seeds `sched:polls` for the new `(source, platform_id)` like `seed_restaurants.py`; delete only when no active watches, else 409), `PUT /admin/restaurants/{slug}/tier {tier: 1|2|3|null}` → writes/clears `tier:override` (Phase 3 D-58), `GET /admin/restaurants/{slug}/events?window=24h|7d` (event counts + latest 50), `GET /admin/health` (Kafka topic/lag summary via `AIOKafkaAdminClient` + `end_offsets` vs committed offsets for groups `state-machine`/`notifier`, last successful poll per source from `poll_log`, Redis/DB ping, poll success rate last hour). All admin mutations are logged with `admin_user`.

**Test strategy**
- **D-104:** Unit: request models/validators (every WATCH-02 rule), token rotation with `freezegun`, rate-limit window math, SSE framing (`id:/event:/data:` bytes, ping), ring-buffer replay after `Last-Event-ID`, basic-auth compare, request-log redaction of tokens. Integration (testcontainers, `httpx.ASGITransport`): `POST /watches` → user + watch rows, ciphertext phone bytes, `watch:count` updated, management email dry-run recorded; CRUD lifecycle incl. soft delete and cross-user 404; 61st POST → 429; SSE first-event ≤ 500 ms after a Kafka publish and `Last-Event-ID` reconnect replay; `/api/metrics` contains `sse_connections_active`; admin CRUD + tier override + 401; `/readyz`. An OpenAPI snapshot test (`tests/unit/test_openapi_snapshot.py`) pins the public route list so Phase 6 can rely on it. `docs/api.md` documents every route with curl examples (portfolio artifact; Phase 7 README links it).

### Claude's Discretion

- Router/module layout under `services/api/routers/` (`watches.py`, `manage.py`, `restaurants.py`, `feed.py`, `admin.py`, `push.py`, `metrics.py`, `health.py` suggested); pydantic response model names; LRU cache sizes; pagination defaults.
- Whether the management-link email is sent inline or via a background task (`BackgroundTasks`) — either is fine as long as it never fails the request.

### Deferred Ideas (OUT OF SCOPE)

- OAuth2 admin (V2-08); multi-party-size watches (V2-09); WebSocket feed; per-user API keys.
- Cloud Run proxy SSE verification (Phase 7 runbook).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| WATCH-01 | User identified by email only (no account, no password); record created on first watch creation | § SQLAlchemy — `pg_insert(...).on_conflict_do_update(index_elements=["email"]).returning(id)` proven to return the same `user_id` on re-submit; `on_conflict_do_nothing().returning()` proven to return **no row** (the trap) |
| WATCH-02 | Watchlist entry with restaurant, party size 1–10, date range, days-of-week, time window, seat-type, channels | § Request Models — full `WatchCreate` sketch, mypy-strict and ruff clean, with an executed accept/reject matrix for all 18 rules and an E.164 boundary table |
| WATCH-03 | Management token = HMAC-SHA256, sent on creation, rotates monthly with 7-day grace | § Tokens & Rotation — executed dry-run showing N−1 verifying at the last second of grace and rejected at the cutoff instant; freezegun proven to work inside `async def` across `await` |
| WATCH-04 | Manage via `/manage/[token]` — pause, resume, delete, edit; no login | § SQLAlchemy — `UPDATE … WHERE id AND user_id RETURNING id` gives user-scoped 404 in one round trip (executed, empty list for the wrong user) |
| WATCH-05 | Phone numbers encrypted at rest, decrypted only at notification send time | § Sequencing — `shared/crypto.py` + `users.phone_hash` are Phase 4 D-85/migration 0010 artifacts; Phase 5 is a pure consumer. Ciphertext-bytes assertion recipe given |
| WATCH-06 | Watchlist API endpoints; rate-limited to 60 req/min per IP | § Rate Limiting — Lua executed against Redis 7.2.16 (4th call refused at cap 3, TTL stable at 120 s). **BC-2**: the locked client-IP rule makes the limit unenforceable |
| API-01 | FastAPI server with CORS, 60 req/min rate limiting, structured JSON logging | § Middleware — pure-ASGI vs `BaseHTTPMiddleware` measured over a live stream (103 ms vs 0 ms duration); `scope["route"].path` proven available in the `finally`. **BC-3**: the locked exception-handler decision does not suppress the stack trace |
| API-02 | SSE `/api/feed/live` tails `availability.events`, `X-Accel-Buffering: no`, keepalive pings | § SSE — full `FeedHub` executed: 0.9–1.1 ms publish→receipt, drop-oldest verified, `Last-Event-ID` replay verified, heartbeat verified, generator `finally` verified to run on disconnect. **BC-1**: the locked test transport cannot stream |
| API-03 | Admin routes behind HTTP Basic; restaurant CRUD, tier overrides, health metrics, event volume | § Admin & Metrics — `HTTPBasic(auto_error=False)` + `hmac.compare_digest` executed (401 + `WWW-Authenticate`, 404 when unconfigured); `/api/metrics` served from the shared registry and proven excluded from its own instrumentation |
</phase_requirements>

## Summary

Phase 5 adds **zero new dependencies**. Every library it needs is already pinned in `pyproject.toml` and installed in `.venv` `[VERIFIED: .venv/importlib.metadata, this session]`. The work is entirely composition: a `create_app()` that grows six routers, one background Kafka consumer, one Redis Lua script and one pure-ASGI middleware.

Three locked decisions do not survive contact with the pinned versions, and each is reproduced below with an executed transcript. **BC-1**: `httpx.ASGITransport` accumulates the entire response body before returning a `Response` — it is structurally incapable of incremental streaming, so D-104's SSE integration tests (and D-99's ≤ 500 ms assertion) cannot be written against it; an infinite SSE generator simply hangs the test forever. The replacement — `uvicorn.Server` in-process on a random port, the same recipe Phase 3 D-71 adopted for the Resy stub — was executed end to end and measures **0.9 ms** publish→receipt against a 500 ms budget. **BC-2**: D-96's "`X-Forwarded-For` first hop" is the one value on Google's infrastructure that an attacker fully controls; Google's load balancer appends to whatever the client sent, producing `<supplied-value>,<client-ip>,<lb-ip>` and verifying nothing before `<client-ip>`. Taking hop[0] lets any caller mint a fresh rate-limit bucket per request, so the 60 req/min cap that *is* WATCH-06 becomes unenforceable; taking uvicorn's default instead collapses every user onto the load balancer's own address and rate-limits the whole service as one client. The second-to-last hop is the only correct choice, and both failure modes were reproduced. **BC-3**: Starlette's `ServerErrorMiddleware` re-raises after your handler builds its clean JSON body, specifically so the server can log the traceback — so D-97's "without stack traces" is true of the *response* and false of the *log stream*, which then carries `str(exc)` in violation of the repo's absolute rule (`shared/telemetry.py :: safe_error`, T-02-03).

Everything else in the phase is confirmed sound and, in several places, simpler than the decisions assume. `AIOKafkaConsumer(group_id=None)` needs **no manual `assign()`** — aiokafka installs a `NoGroupCoordinator` that assigns every partition of every subscribed topic at `start()` and reassigns on metadata change `[VERIFIED: aiokafka/consumer/consumer.py, AIOKafkaConsumer.start]`. `request.is_disconnected()` is unnecessary for SSE cleanup: uvicorn closes the async generator on client disconnect, so a `finally:` block runs promptly (measured 103 ms for a 103 ms stream). And `BaseHTTPMiddleware` does **not** buffer streaming responses under Starlette 0.52.1 — the real reason to avoid it is subtler and more damaging to this phase: `dispatch` resumes the instant `call_next` returns the response *object*, before a single body byte is written, so an SSE connection is logged with `duration_ms=0` and no final status.

**Primary recommendation:** Build `services/api/` on a pure-ASGI logging middleware, a synchronous (never-awaiting) `FeedHub.publish`, a second-to-last-hop client IP, and a `uvicorn.Server`-on-a-random-port integration harness. Fix BC-1/BC-2/BC-3 in the plan before writing any route; every other decision can be implemented as locked.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Watchlist CRUD, user upsert | API / Backend | Database | ARCHITECTURE.md:90 is explicit — "watchlist creation goes straight to Postgres… Keep Kafka for system-internal events, HTTP for user-initiated." No Kafka write on a user-triggered path |
| Management-token mint/verify | API / Backend | — | Stateless HMAC. `shared/tokens.py` (Phase 4 D-82) is the crypto tier; the API only calls it |
| Phone encryption | API (write) / Notifier (read) | Database (BYTEA) | WATCH-05: Phase 5 writes ciphertext via `encrypt_phone`; only `SmsProvider` decrypts, at send time |
| Rate limiting | API / Backend | Redis | Fixed-window counter is shared state; the process is stateless and horizontally scaled |
| SSE fan-out | API / Backend | Kafka (source), Browser (sink) | One background consumer per process, in-memory multicast (ARCHITECTURE.md:461, Anti-Pattern 4) |
| Live-feed rendering, reconnect | Browser / Client | API | `EventSource` handles reconnect and resends `Last-Event-ID`; the server only honours it |
| Active-watch counts | API (write) / Poller (read) | Redis `watch:count` HASH | Phase 3 D-58 contract; the poller must never query Postgres on its hot path |
| Polling-tier override | API admin (write) / Poller (read) | Redis `tier:override` HASH | Same contract, opposite direction |
| Metrics exposition | API / Backend | Prometheus (Phase 7 scrape) | `/api/metrics` is a read-only projection of the in-process registry |
| Restaurant search & detail | API / Backend | Database | Read-through; no cache beyond `/api/stats`' 30 s Redis entry |
| Admin auth | API / Backend | — | HTTP Basic at the edge of the router; OAuth2 is V2-08 |
| Cold-start feed hydration | API / Backend | Database (`availability_events`) | D-98's fallback when the ring buffer is empty on a fresh process |

## Blocking Corrections to Locked Decisions

### BC-1 — D-104 / D-99: `httpx.ASGITransport` cannot stream, so the SSE integration tests as specified cannot be written

D-104 locks "Integration (testcontainers, `httpx.ASGITransport`)" and lists among those tests "SSE first-event ≤ 500 ms after a Kafka publish and `Last-Event-ID` reconnect replay". `ASGITransport` cannot do this. Read from the installed source `[VERIFIED: .venv/lib/python3.12/site-packages/httpx/_transports/asgi.py:161-183]`:

```python
        try:
            await self.app(scope, receive, send)
        except Exception:  # noqa: PIE-786
            ...
        assert response_complete.is_set()
        assert status_code is not None
        assert response_headers is not None

        stream = ASGIResponseStream(body_parts)

        return Response(status_code, headers=response_headers, stream=stream)
```

and `[VERIFIED: httpx/_transports/asgi.py:54-60]`:

```python
class ASGIResponseStream(AsyncByteStream):
    def __init__(self, body: list[bytes]) -> None:
        self._body = body

    async def __aiter__(self) -> typing.AsyncIterator[bytes]:
        yield b"".join(self._body)
```

`handle_async_request` **awaits the whole application to completion**, accumulates every `http.response.body` message into `body_parts`, asserts the response finished, and only then constructs a `Response` whose stream yields one joined chunk. There is no path by which `client.stream(...)` + `aiter_lines()` observes a chunk before the handler returns.

Reproduced: an SSE endpoint with the ordinary `while True` generator, driven through `ASGITransport`, produced **no output at all** — not even the status line — and had to be killed after 120 s. `resp.status_code` is unreachable because `async with c.stream(...)` never yields a response object.

There is a second, independent blocker in the same file `[VERIFIED: httpx/_transports/asgi.py:132-136]`:

```python
        async def receive() -> dict[str, typing.Any]:
            nonlocal request_complete
            if request_complete:
                await response_complete.wait()
                return {"type": "http.disconnect"}
```

`receive()` waits on `response_complete` before ever returning `http.disconnect` — but `response_complete` is only set when the response ends. So `request.is_disconnected()` can never return `True` under `ASGITransport` either; calling it inside an SSE handler deadlocks.

**Correction.** Keep `ASGITransport` for every *non-streaming* route (it is fast, needs no port, and Phase 4 already uses it for `/go` and the webhooks). Add a `uvicorn.Server`-in-process harness for the streaming ones — the same recipe Phase 3 D-71 adopted for the Resy stub, so this is an established pattern in the project rather than a new one. Executed end to end `[VERIFIED: transcript, this session]`:

```
uvicorn started on 57411 | uvicorn 0.44.0
status: 200 | ct: text/event-stream; charset=utf-8
cache-control: no-cache | x-accel-buffering: no | transfer-encoding: chunked
first line (immediate?): ': connected'
publish->receipt: 0.99 ms  (subs at publish: 1)
frame: ['id: evt-1', 'event: slot_opened', 'data: {"id": "evt-1"}']
heartbeat comment at t+1002ms: ': ping'
heartbeat seen: True
  [server] generator finalized, subs = 0
after client close, subs = 0
```

The harness (put it in `tests/integration/conftest.py` as a fixture — see § Validation Architecture):

```python
# Source: executed transcript, this session (uvicorn 0.44.0 / httpx 0.28.1).
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])

port = free_port()
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                       log_level="warning", lifespan="on"))
task = asyncio.create_task(server.serve())
while not server.started:
    await asyncio.sleep(0.02)
...
server.should_exit = True
with contextlib.suppress(asyncio.TimeoutError):
    await asyncio.wait_for(task, 5)
```

Two consequences the planner must carry:

1. **`ASGITransport` does not run lifespan either.** Confirmed by inspection — its `scope` is `{"type": "http", ...}` and it never sends a `lifespan` scope. So every `ASGITransport` test of a route that reads `request.state.<lifespan-state>` will fail with `AttributeError`, and the SSE hub / DB engine / Redis client will never be constructed. Routes that depend on lifespan state need the uvicorn harness (`lifespan="on"`, verified: startup order `['db', 'redis', 'hub']`, shutdown order `['hub-stopped', 'redis-closed', 'db-closed']`) or FastAPI `dependency_overrides`.
2. **The ≤ 500 ms measurement.** Measure `t0` immediately before the Kafka `send_and_wait`, and stop the clock on the first `data:` line out of `aiter_lines()`. Real Kafka broker → consumer was **17.3 ms** and hub → client was **0.9–1.1 ms**, so the assertion has ~28× headroom and will not be flaky. Assert `< 0.5` seconds, and log the measured value so a regression is visible in CI output rather than only as a pass/fail.

### BC-2 — D-96: the "`X-Forwarded-For` first hop" rule makes the 60 req/min limit unenforceable

D-96 locks the rate-limit subject as "`X-Forwarded-For` first hop when `TRUST_PROXY_HEADERS=true`, else the socket peer". On Google's infrastructure — which DEPLOY-01 commits the API to — the first hop is the single value an attacker fully controls.

Google Cloud Load Balancing documents that when an incoming request already carries the header, the load balancer **appends** rather than replaces, producing `X-Forwarded-For: <supplied-value>,<client-ip>,<load-balancer-ip>`, and that it "does not verify any IP addresses that precede `<client-ip>,<load-balancer-ip>`" `[CITED: cloud.google.com/load-balancing/docs/https]`. Cloud Run's own header reference says only that "the first IP in this list is generally the IP of the client that created the request" `[CITED: docs.cloud.google.com/functions/docs/reference/headers]` — true for an honest client, false for a hostile one, and a rate limiter exists precisely for hostile ones.

Reproduced against a live uvicorn 0.44.0 with the exact header shape Cloud Run produces `[VERIFIED: transcript, this session]`:

```
=== uvicorn default forwarded_allow_ips='127.0.0.1' ===
  XFF='9.9.9.9, 203.0.113.55, 130.211.0.1'
     socket_peer='130.211.0.1'  D-96_first_hop='9.9.9.9'  recommended_2nd_to_last='203.0.113.55'
  XFF='8.8.8.8, 203.0.113.55, 130.211.0.1'
     socket_peer='130.211.0.1'  D-96_first_hop='8.8.8.8'  recommended_2nd_to_last='203.0.113.55'
  XFF='7.7.7.7, 203.0.113.55, 130.211.0.1'
     socket_peer='130.211.0.1'  D-96_first_hop='7.7.7.7'  recommended_2nd_to_last='203.0.113.55'
  honest client XFF='203.0.113.55, 130.211.0.1' -> first_hop='203.0.113.55' 2nd_to_last='203.0.113.55'

=== uvicorn forwarded_allow_ips='*' ===
  XFF='9.9.9.9, 203.0.113.55, 130.211.0.1'
     socket_peer='9.9.9.9'  D-96_first_hop='9.9.9.9'  recommended_2nd_to_last='203.0.113.55'
```

Both available knobs are wrong, in opposite directions:

- **D-96 as written (or `--forwarded-allow-ips='*'`, which does the same thing):** every request can carry a different first hop, so `rate:api:watch_create:{ip}:{minute}` never repeats and the 61st request is never reached. WATCH-06 is unenforceable — and the endpoint it protects is the one that writes rows and sends email.
- **uvicorn's default `forwarded_allow_ips="127.0.0.1"`:** the socket peer resolved to `130.211.0.1`, the *load balancer*. Read from the installed source `[VERIFIED: .venv/lib/python3.12/site-packages/uvicorn/middleware/proxy_headers.py:126-140]`, `get_trusted_client_host` walks the list in reverse and returns the first host not in the trusted set — with only `127.0.0.1` trusted, that is the LB. Every user in the world then shares one bucket and the whole service is capped at 60 requests per minute. That is a self-inflicted denial of service.

The same source shows why `"*"` is the spoofable branch:

```python
        if self.always_trust:
            return x_forwarded_for_hosts[0]
```

**Correction.** Resolve the client IP in application code, from the **second-to-last** hop, and do not rely on uvicorn's rewriting at all (leave `forwarded_allow_ips` at its default and read the raw header, so the two mechanisms cannot disagree). Verified helper, mypy `--strict` and ruff clean:

```python
# Source: sketch executed + typechecked this session.
def client_ip_from_scope(scope: Scope, *, trust_proxy: bool) -> str:
    if trust_proxy:
        raw_headers = cast("list[tuple[bytes, bytes]]", scope.get("headers", []))
        for key, value in raw_headers:
            if key == b"x-forwarded-for":
                hops = [h.strip() for h in value.decode("latin-1").split(",") if h.strip()]
                if len(hops) >= 2:
                    return hops[-2]      # <client-ip>, per Google's documented XFF shape
                if hops:
                    return hops[-1]
                break
    peer = scope.get("client")
    return str(peer[0]) if peer else "unknown"
```

Executed against both header shapes:

```
  trust=True : 203.0.113.55       # <supplied>, <client-ip>, <lb-ip>  -> stable across spoof attempts
  trust=False: 130.211.0.1        # socket peer
  no xff     : 198.51.100.7       # falls back to the peer
```

Add a unit test with the three-hop spoof vector asserting that three different supplied values yield **one** rate-limit key. That test is the executable statement of WATCH-06.

Two supporting notes for the plan: keep `TRUST_PROXY_HEADERS=false` as the local/dev default so the socket peer is used (the integration tests then get real per-connection isolation), and record in `docs/api.md` that the rule assumes exactly one appending proxy in front of the service — if Phase 7 adds an external HTTPS load balancer *in addition to* Cloud Run's front end, the index becomes `-3` and the constant must move to config.

### BC-3 — D-97: the global exception handler returns a clean body but the stack trace still reaches the log stream

D-97 locks "global exception handlers that return JSON `{error, request_id}` without stack traces". The handler works; the sentence's goal does not hold. Reproduced with a route raising `ValueError("secret-token-abc123 leaked in message")` and an `@app.exception_handler(Exception)` returning `{"error": "internal_error", "request_id": ...}` `[VERIFIED: transcript, this session]`:

```
--- exception handler (no stack trace / no exc message) ---
  /boom -> 500 {"error":"internal_error","request_id":"gen-123"}
```

The response is exactly as specified. But the same run emitted, to the process log:

```
ERROR:    Exception in ASGI application
Traceback (most recent call last):
  ...
  File ".../research-05/e6_fastapi.py", line 88, in boom
    raise ValueError("secret-token-abc123 leaked in message")
ValueError: secret-token-abc123 leaked in message
```

The cause is in Starlette's own source `[VERIFIED: .venv/lib/python3.12/site-packages/starlette/middleware/errors.py:180-186]`:

```python
            if not response_started:
                await response(scope, receive, send)

            # We always continue to raise the exception.
            # This allows servers to log the error, or allows test clients
            # to optionally raise the error within the test case.
            raise exc
```

`ServerErrorMiddleware` invokes the installed 500 handler, sends its response, and **then re-raises** so the ASGI server logs it. This directly violates the rule `shared/telemetry.py :: safe_error` exists to enforce — its docstring states that `error=str(exc)` "is never safe in this codebase" because SQLAlchemy's `StatementError.__str__` appends bound parameters, and `services/state_machine/consumer.py` carries the T-02-03 contract "Logs carry ids and counts only — never a booking token". In this phase the bound parameters of a failed `INSERT` into `users` are the **encrypted phone blob and the email**, and of `watchlist_entries` the whole watch. A single constraint violation puts them in Cloud Logging.

**Correction.** Two changes, both small:

1. Catch and log inside the **pure-ASGI logging middleware**, which sits outside the router, so the exception is rendered with `safe_error(exc)` and re-raised only after a redacted line is emitted — or, better, converted there so `ServerErrorMiddleware` never sees it.
2. Silence uvicorn's own traceback for handled 500s by configuring the `uvicorn.error` logger through `configure_logging()` (structlog already owns `logging.basicConfig` in `shared/telemetry.py :: configure_logging`), and add a unit test in the shape of the existing `tests/unit/test_logs_never_carry_payload.py` that raises an exception carrying a marker string through the app and asserts the marker appears in **no** emitted log record.

Amend the D-97 wording to "…that return JSON `{error, request_id}`, and that render every exception through `safe_error` before it reaches any log sink — the response body is not the only egress."

## Sequencing Dependencies (not corrections — hard preconditions)

Phase 5 is the most dependent phase in the roadmap and **none of its upstream artifacts exist on disk yet**. Verified this session against the working tree:

| Needed by | Artifact | Owner | Present? |
|-----------|----------|-------|----------|
| D-91, D-92 | `shared/tokens.py` (versioned HMAC sign/verify + grace) | Phase 4 D-82 | ✗ `ls shared/` → no `tokens.py` |
| D-94 | `shared/crypto.py :: encrypt_phone/decrypt_phone/phone_hash` | Phase 4 D-85 | ✗ |
| D-93 | `services/notifier/providers/email.py :: EmailProvider` (dry-run) | Phase 4 D-78 | ✗ `ls services/` → only `poller`, `state_machine` |
| D-97, all routers | `services/api/app.py :: create_app()` + `routers/links.py`, `routers/webhooks.py` | Phase 4 D-84 | ✗ |
| D-94, D-102 | `users.phone_hash`, `push_subscriptions` table | Phase 4 migration 0010 | ✗ `migrations/versions/` ends at `0008` |
| D-93, D-100 | `UNIQUE(slug, source)` on `restaurants` (one slug, many source rows) | Phase 3 migration 0009 (D-63b) | ✗ |
| D-95, D-100, D-103 | `watch:count` / `tier:override` HASH helpers | Phase 3 D-58 | ✗ (`shared/redis_keys.py` read this session: no such symbols) |
| D-101 | `shared/metrics.py` single-definition registry | Phase 3 D-69 | ✗ |
| D-93 | `match_watches` fan-out extended to slug-siblings | Phase 4 D-73 + this phase's amendment | ✗ |

Migration numbering is a chain: `0008` (on disk) → `0009` (Phase 3) → `0010` (Phase 4). Phase 5 needs both applied. If Phase 5 adds a migration of its own it is `0011` with `down_revision = "0010"`.

**Two live traps discovered while exercising this:**

1. **`shared/db.py` still declares `slug` unique.** `Restaurant.slug` is `mapped_column(Text, nullable=False, unique=True)` `[VERIFIED: shared/db.py:56]`, and migration 0003 creates both a `UNIQUE` constraint and `ix_restaurants_slug` `[VERIFIED: migrations/versions/0003_create_restaurants.py]`. Phase 3's migration 0009 drops that, but if the ORM class is not changed in the same commit, any test using `Base.metadata.create_all` rebuilds the old constraint and the whole "one slug, two source rows" model of D-93/D-100 silently fails. Reproduced: inserting the `resy` sibling with `on_conflict_do_nothing()` (no `index_elements`) swallowed the unique violation and the row simply vanished — `rows for slug=lilia: [(1, 'opentable', '12345', [2, 4])]`. Phase 5's first integration test must assert **two** rows for one slug.
2. **The constraint cannot be dropped as an index.** Reproduced: `DROP INDEX IF EXISTS restaurants_slug_key` → `asyncpg.exceptions.DependentObjectsStillExistError: cannot drop index restaurants_slug_key because constraint restaurants_slug_key on table restaurants requires it` / `HINT: You can drop constraint restaurants_slug_key on table restaurants instead.` The correct order is `ALTER TABLE restaurants DROP CONSTRAINT restaurants_slug_key` **then** `DROP INDEX ix_restaurants_slug`. Worth passing to the Phase 3 planner; worth a Phase 5 pre-flight check either way.

**Recommendation for the planner:** make Wave 0 of Phase 5 a *verification* wave that asserts each precondition and fails loudly with the owning decision id, rather than discovering them one `ImportError` at a time inside a route.

## Standard Stack

Phase 5 introduces **no new packages**. Everything below is already in `pyproject.toml` and installed.

### Core (already pinned — use these)

| Library | Version (verified in `.venv`) | Purpose in Phase 5 | Why standard |
|---------|-------------------------------|--------------------|--------------|
| fastapi | 0.136.0 | Routing, DI, OpenAPI, `HTTPBasic` | Already the project's API framework (STACK.md:38) |
| starlette | **0.52.1** | `StreamingResponse`, `CORSMiddleware`, ASGI types | Transitive; the version matters for every middleware claim here |
| uvicorn[standard] | 0.44.0 | ASGI server; also the in-process test harness (BC-1) | `uvloop` + `httptools`; `ProxyHeadersMiddleware` behaviour is load-bearing (BC-2) |
| pydantic | 2.13.3 | `WatchCreate` and every response model | `model_validator(mode="after")` covers all D-93 cross-field rules |
| pydantic-settings | 2.14.0 | *Not recommended here* — see Alternatives | |
| sqlalchemy[asyncio] | 2.0.49 | Async CRUD, `pg_insert(...).on_conflict_do_update` | `shared/db.py` already defines every ORM class |
| asyncpg | 0.31.0 | Async driver | App hot path (`shared/db.py` docstring) |
| aiokafka | 0.13.0 | `AIOKafkaConsumer(group_id=None)` for the feed; `AIOKafkaAdminClient` for `/admin/health` | `NoGroupCoordinator` gives groupless auto-assignment for free |
| redis | 7.4.0 (client) | Rate limit Lua, `watch:count`, `tier:override`, `/api/stats` cache | Server is redis 7.2.16 in tests |
| prometheus-client | 0.25.0 | `generate_latest`, `CONTENT_TYPE_LATEST`, metric types | Phase 3 `shared/metrics.py` owns the definitions |
| prometheus-fastapi-instrumentator | 7.1.0 | `http_requests_total` / `http_request_duration_seconds` | Route-template `handler` label; must be configured for SSE (see § Metrics) |
| structlog | 25.5.0 | Request logging via `shared/telemetry.py` | Redaction processor already exists |
| orjson | 3.11.8 | Optional fast SSE payload encoding | Already pinned; `json` is fine at this volume |
| httpx | 0.28.1 | Shared client (`shared/http_client.py`); test client | Singleton is mandatory (Pitfall 9) |

### Test-only (already pinned)

| Library | Version | Purpose |
|---------|---------|---------|
| pytest / pytest-asyncio | 9.0.3 / 1.3.0 | `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed |
| testcontainers[kafka,redis,postgres] | 4.14.2 | Kafka 7.6.0, redis:7.2-alpine, timescaledb 2.17.2-pg16 |
| freezegun | 1.5.5 | Token-rotation dry-run — verified to work inside `async def` |
| respx | 0.23.1 | Mock the Phase 4 `EmailProvider` HTTP call in `POST /watches` tests |

### Alternatives Considered

| Instead of | Could use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled SSE framing | `sse-starlette` (`EventSourceResponse`) | Adds a dependency for ~15 lines. PITFALLS.md:283 mentions it, but the framing was executed here byte-for-byte and the heartbeat/`Last-Event-ID`/drop-oldest logic is ours regardless. **Do not add it.** |
| `services/api/config.py` functions | `pydantic-settings` `BaseSettings` | `BaseSettings` reads env at instantiation; the project's Phase 2 lesson (`services/state_machine/config.py:7-11`, 02-02 deviation 1) is that *any* import-time env freeze pins integration tests to localhost defaults. Keep the lazy-function idiom. |
| Custom rate limiter | `slowapi` | D-96 already forbids a third-party limiter, and the Lua is 8 lines and executed below. |
| `BaseHTTPMiddleware` for logging | Pure ASGI class | See § Middleware — measured; pure ASGI is the only one that can log a stream's real duration and status. |
| `request.is_disconnected()` polling | Generator `finally:` | Measured: uvicorn closes the generator on disconnect, `finally` runs. `is_disconnected()` also deadlocks under `ASGITransport` (BC-1). |
| Manual `consumer.assign(...)` | `group_id=None` auto-assignment | aiokafka does it for you — see § Kafka. |

**Installation:** none. `pyproject.toml` is unchanged by this phase.

**Version verification** `[VERIFIED: .venv/bin/python -c "import importlib.metadata …", this session]`:

```
fastapi==0.136.0        starlette==0.52.1       uvicorn==0.44.0
httpx==0.28.1           pydantic==2.13.3        pydantic-settings==2.14.0
sqlalchemy==2.0.49      asyncpg==0.31.0         aiokafka==0.13.0
redis==7.4.0            prometheus-client==0.25.0
prometheus-fastapi-instrumentator==7.1.0
freezegun==1.5.5        respx==0.23.1           pytest-asyncio==1.3.0
pytest==9.0.3           structlog==25.5.0       orjson==3.11.8
anyio==4.13.0           testcontainers==4.14.2
python 3.12.13
```

## Package Legitimacy Audit

Phase 5 installs **nothing**. Every package below is already pinned in `pyproject.toml`, already resolved in `uv.lock`, and already imported by shipped Phase 1/2 code. The audit is included because `prometheus-fastapi-instrumentator` is *first used* in this phase.

| Package | Registry | Latest release (seam) | Downloads | Source repo | Verdict | Disposition |
|---------|----------|----------------------|-----------|-------------|---------|-------------|
| fastapi | PyPI | 2026-07-29 | n/a | github.com/fastapi/fastapi | SUS | Approved — already pinned |
| uvicorn | PyPI | 2026-08-19 | n/a | github.com/Kludex/uvicorn | SUS | Approved — already pinned |
| starlette | PyPI | 2026-08-08 | n/a | github.com/Kludex/starlette | SUS | Approved — transitive of fastapi |
| prometheus-fastapi-instrumentator | PyPI | 2026-07-26 | n/a | github.com/trallnag/prometheus-fastapi-instrumentator | SUS | Approved — already pinned (STACK.md:101) |
| prometheus-client | PyPI | 2026-07-24 | n/a | github.com/prometheus/client_python | SUS | Approved — already pinned |
| pydantic | PyPI | 2026-08-28 | n/a | github.com/pydantic/pydantic | SUS | Approved — already pinned |
| sqlalchemy | PyPI | 2026-08-11 | n/a | sqlalchemy.org | SUS | Approved — already pinned |
| aiokafka | PyPI | 2026-04-29 | n/a | github.com/aio-libs/aiokafka | SUS | Approved — already pinned |
| redis | PyPI | 2026-07-30 | n/a | github.com/redis/redis-py | SUS | Approved — already pinned |
| httpx | PyPI | 2024-12-06 | n/a | github.com/encode/httpx | SUS | Approved — already pinned |
| freezegun | PyPI | 2025-08-09 | n/a | github.com/spulec/freezegun | SUS | Approved — already pinned (dev) |

**Reading the verdicts honestly.** Every `SUS` is driven by two seam signals that carry no information for PyPI: `unknown-downloads` (PyPI's JSON API exposes no download counts, so *every* PyPI package is flagged) and `too-new` (the seam reads `publishedAt` as the **latest release date**, not the package's first publication — FastAPI's 2026-07-29 is a 2018-era project's newest release). Each package resolves to its canonical, well-known source repository, none is deprecated, and none declares a `postinstall`-equivalent hook. `[VERIFIED: gsd-tools query package-legitimacy check --ecosystem pypi …, this session]`

**Packages removed due to [SLOP] verdict:** none.
**Packages flagged as suspicious [SUS] requiring a human checkpoint:** none — no package is being *installed* by this phase, so there is no install to gate. If the planner adds any dependency not in the list above, it must go through a fresh `package-legitimacy check` and a `checkpoint:human-verify` task.

## Architecture Patterns

### System Architecture Diagram

```
                    ┌──────────────────── browser (Phase 6 PWA) ────────────────────┐
                    │  fetch /api/*        EventSource /api/feed/live               │
                    │        │                    │  (auto-reconnect + Last-Event-ID)│
                    └────────┼────────────────────┼─────────────────────────────────┘
                             │                    │
                    ═════════▼════════════════════▼═════════ Cloud Run front end ════
                      appends X-Forwarded-For: <supplied>,<client-ip>,<lb-ip>
                      request timeout 300 s default -> must be raised to 3600 s
                             │                    │
   ┌─────────────────────────▼────────────────────▼─────────────────────────────────┐
   │  services/api   (one stateless uvicorn process; N replicas)                     │
   │                                                                                 │
   │   ① CORSMiddleware ─ ② RequestLogMiddleware (PURE ASGI) ─ ③ Instrumentator      │
   │        │                    │ logs on the way OUT: real duration, route         │
   │        │                    │ template, {token}-redacted path                   │
   │        ▼                    ▼                                                   │
   │   ┌─────────────────── router dispatch ────────────────────────────────┐        │
   │   │                                                                     │        │
   │   │  POST /watches ──rate-limit dep──► Redis INCR+EXPIRE (fixed window) │        │
   │   │       │  (subject = 2nd-to-last XFF hop, BC-2)     │                │        │
   │   │       │                                            ├─429 + Retry-After       │
   │   │       ├─► pydantic WatchCreate  (18 rules)                          │        │
   │   │       ├─► upsert users ON CONFLICT(email) DO UPDATE RETURNING id    │        │
   │   │       ├─► encrypt_phone() ──────────────► users.phone BYTEA         │        │
   │   │       ├─► INSERT watchlist_entries (OpenTable row, else Resy row)   │        │
   │   │       ├─► recount(slug) ─────────────────► Redis watch:count HASH   │        │
   │   │       │                                    (read by the Phase 3 poller)      │
   │   │       ├─► sign(purpose="manage") ────────► {PUBLIC_BASE_URL}/manage/t/{tok}  │
   │   │       └─► BackgroundTasks: EmailProvider  (best effort, never fails req)     │
   │   │                                                                     │        │
   │   │  GET/PATCH/DELETE /watches[/{id}]  ──Bearer token──► verify(manage) │        │
   │   │       └─ UPDATE … WHERE id AND user_id RETURNING id  → [] means 404 │        │
   │   │                                                                     │        │
   │   │  GET /api/manage/{token}       (same list + a freshly minted token) │        │
   │   │  GET /api/restaurants[/{slug}] ─► merge source rows into one object │        │
   │   │  GET /api/stats                ─► 30 s Redis cache                  │        │
   │   │  GET /api/push/*               ─► push_subscriptions upsert         │        │
   │   │  /admin/*  ──HTTPBasic + compare_digest──► restaurants CRUD,        │        │
   │   │              tier:override HASH, sched:polls seed, AdminClient lag  │        │
   │   │  GET /api/metrics  (unauth, excluded from ② and ③)                  │        │
   │   │  GET /healthz (liveness)   GET /readyz (DB+Redis+hub.running)       │        │
   │   │                                                                     │        │
   │   │  GET /api/feed/live ──subscribe──┐          GET /api/feed/recent    │        │
   │   └──────────────────────────────────┼──────────────┬──────────────────┘        │
   │                                      ▼              ▼                            │
   │        ┌──────────────────────── FeedHub (one per process) ──────────────┐       │
   │        │  ring: deque(maxlen=100)  ◄── replay_after(Last-Event-ID)       │       │
   │        │  subs: {Queue(maxsize=100), …}                                  │       │
   │        │  publish() is SYNCHRONOUS: put_nowait, drop-oldest on full      │       │
   │        │     └─ never awaits ⇒ a slow browser cannot stall the pump      │       │
   │        └───────────────────────────▲────────────────────────────────────┘       │
   │                                     │ enrich (LRU (source,platform_id)→row)      │
   │        background task: while True: await consumer.getone()                      │
   │                                     ▲                                            │
   └─────────────────────────────────────┼────────────────────────────────────────────┘
                                         │  group_id=None, auto_offset_reset=latest
                                         │  NoGroupCoordinator assigns ALL partitions
   ┌─────────────┐   ┌──────────────┐   ┌┴──────────────────┐   ┌────────────────────┐
   │ Postgres /  │   │    Redis     │   │ Kafka             │   │ Phase 4 notifier    │
   │ TimescaleDB │   │ watch:count  │   │ availability.     │◄──│ (separate consumer  │
   │ users       │   │ tier:override│   │   events          │   │  group "notifier")  │
   │ restaurants │   │ rate:api:*   │   └───────────────────┘   └────────────────────┘
   │ watchlist_* │   │ sched:polls  │
   │ notif_log   │   │ stats cache  │            ▲ Phase 2 state machine produces
   │ avail_events│   └──────────────┘
   └─────────────┘
```

### Recommended Project Structure

```
services/api/
├── app.py                 # create_app(): middleware order, lifespan, routers  (extend Phase 4's)
├── config.py              # LAZY env functions only — never module constants
├── deps.py                # get_session / get_redis / get_hub / bearer_user / admin_guard
├── ratelimit.py           # fixed-window Lua dependency (D-96 + BC-2 client IP)
├── logging_mw.py          # pure-ASGI RequestLogMiddleware + redact_path
├── sse.py                 # FeedHub, sse_frame, sse_body, the Kafka pump task
├── schemas.py             # pydantic request/response models
├── watch_service.py       # upsert user, insert/edit/soft-delete watch, recount
└── routers/
    ├── links.py           # /go/{token}                      (Phase 4 — do not rewrite)
    ├── webhooks.py        # /webhooks/*                       (Phase 4 — do not rewrite)
    ├── watches.py         # POST/GET/PATCH/DELETE /watches
    ├── manage.py          # GET /api/manage/{token}
    ├── restaurants.py     # GET /api/restaurants[/{slug}], /api/stats
    ├── feed.py            # GET /api/feed/live, /api/feed/recent
    ├── push.py            # GET/POST/DELETE /api/push/*
    ├── admin.py           # /admin/*
    ├── metrics.py         # GET /api/metrics
    └── health.py          # GET /healthz, /readyz
shared/
└── watch_counts.py        # recount(slug) -> writes watch:count for every source row
```

### Pattern 1: pure-ASGI request logging (never `BaseHTTPMiddleware`)

**What:** wrap the app in a plain ASGI callable, capture status from `http.response.start`, emit the log line in `finally`.

**Why, measured.** Under Starlette 0.52.1 `BaseHTTPMiddleware` does **not** buffer a `StreamingResponse` — that widely-repeated pitfall is stale for this version. The real problem is timing. Both middlewares wrapped the same 103 ms stream `[VERIFIED: transcript, this session]`:

```
  [/sse] basehttp after call_next t+0ms          <-- logs status/duration BEFORE any body byte
  [base] GENERATOR FINALLY ran at n=2
  [base] pure-asgi finally at t+103ms            <-- the real connection duration
```

`call_next` returns a `_StreamingResponse` object immediately, so a `dispatch`-based logger records `duration_ms≈0` for every SSE connection and can never see the final status. A pure-ASGI wrapper's `finally` runs after the last `http.response.body`.

Two further facts the pattern depends on, both measured:

- **`scope["route"]` is only populated after the router matches**, so the template must be read in the `finally`, not before calling the app. Verified: `pure-asgi: done path=/api/restaurants/lilia template=/api/restaurants/{slug} status=200`. Logging `scope["path"]` alone would create unbounded log cardinality and would leak tokens.
- **Token redaction must be by prefix, not by regex alone.** The helper below was executed:

```
  /manage/t/eyJuIjoxMjM0NTYs…      -> /manage/t/{token}
  /api/manage/eyJuIjoxMjM0NTYs…    -> /api/manage/{token}
  /go/eyJuIjoxMjM0NTYs…            -> /go/{token}
  /unsubscribe/eyJuIjoxMjM0NTYs…   -> /unsubscribe/{token}
  /api/restaurants/lilia            -> /api/restaurants/lilia
  /watches/17                       -> /watches/17
  /some/other/eyJuIjoxMjM0…/x       -> /some/other/{token}/x
```

Full middleware (mypy `--strict` clean, ruff clean) is in § Code Examples.

### Pattern 2: one Kafka consumer, N queues, a synchronous publish

**What:** a single background task per process runs `await consumer.getone()` in a loop; each SSE connection owns an `asyncio.Queue(maxsize=100)`; `publish()` is a plain `def` that `put_nowait`s to every queue and drops the oldest item on a full one.

**Why `publish` must not be `async`.** If it awaited `q.put(...)`, the single pump would block on the slowest connected browser and every other client's feed would stall behind it. Being synchronous also removes the `set` mutation hazard for free: with no suspension point inside the loop, no other coroutine can subscribe or unsubscribe part-way through the iteration.

Executed `[VERIFIED: transcript]` — 7 events into a `maxsize=4` queue:

```
  published 7 into maxsize=4; queue holds ['d3', 'd4', 'd5', 'd6'] ; sse_dropped_total=3
  ring buffer retains all 7: ['d0','d1','d2','d3','d4','d5','d6']
```

The ring buffer is *not* affected by a slow connection — which is what makes `Last-Event-ID` replay work for a client that reconnects after being dropped.

### Pattern 3: SSE cleanup lives in the generator's `finally`, not behind `is_disconnected()`

Measured: after an abrupt client disconnect, uvicorn closes the async generator and the `finally` ran at `n=2` in both middleware configurations, and `hub.connections` returned to 0 within 200 ms. `request.is_disconnected()` returned `False` on every poll during a live stream and is unnecessary; it also deadlocks under `ASGITransport` (BC-1). Use:

```python
    try:
        yield b": connected\n\n"
        ...
    finally:
        hub.unsubscribe(q)
        SSE_CONNECTIONS.dec()
```

### Pattern 4: heartbeat via `wait_for`, never a sleep loop

`await asyncio.wait_for(q.get(), timeout=15.0)` → on `TimeoutError`, yield `b": ping\n\n"` and continue. This is both the keepalive and the queue read in one construct; a `while True: await asyncio.sleep(15)` loop would add up to 15 s of latency to every event. Verified: `got ': ping' after 402 ms` with `HEARTBEAT_S=0.4`, and events still arriving in ~1 ms.

### Pattern 5: user-scoped 404 in one round trip

`UPDATE … WHERE id = :id AND user_id = :uid AND status != 'deleted' RETURNING id`. An empty result means "does not exist *or* is not yours" — which is exactly D-95's requirement that another user's watch is a 404, never a 403, and it produces that answer without a separate `SELECT` that could leak existence through timing. Executed:

```
  soft delete UPDATE...RETURNING -> [1]      (empty list == 404 for wrong user)
  same UPDATE with wrong user_id -> []       (user-scoped 404 in one round trip)
```

### Anti-Patterns to Avoid

- **A Kafka consumer per SSE connection.** ARCHITECTURE.md:461 names this Anti-Pattern 4. One consumer per process, in-memory multicast.
- **`await q.put(...)` in the fan-out.** See Pattern 2 — one slow client stalls every client.
- **Writing to Kafka from `POST /watches`.** ARCHITECTURE.md:90: user-initiated CRUD goes straight to Postgres.
- **`BaseHTTPMiddleware` for request logging.** See Pattern 1 — measured.
- **Reading env at module import in `services/api/config.py`.** `services/poller/config.py` did this and pinned every integration test to localhost defaults (02-02 deviation 1, logged in `deferred-items.md`). Functions only.
- **`prometheus_client.start_http_server` in the API.** The poller does that (Phase 3 D-69) because it has no HTTP surface. The API has one; a second listener would be a second port to expose in Phase 7 for no benefit.
- **`on_conflict_do_nothing()` with no `index_elements`.** It swallows *every* unique violation, including ones you did not intend to tolerate. Reproduced: the `resy` sibling row vanished silently. Always name the index.
- **A `SELECT` then an `UPDATE` for ownership checks.** Two round trips and a TOCTOU window where Pattern 5 is one statement.

## Server-Sent Events (executed)

### Wire format

```
: connected

id: 4c3b…-…-…
event: slot_opened
data: {"event_id":"4c3b…","neighborhood":"Williamsburg","party_size":2,"restaurant_name":"Lilia","slug":"lilia","time_slot":"19:00"}

: ping

```

Each frame is terminated by a **blank line** (`\n\n`). A line starting with `:` is a comment and is what the heartbeat uses — `EventSource` ignores it but the bytes traverse every proxy, which is the point. Verified over the wire through uvicorn:

```
frame lines: ['id: live-0', 'event: slot_opened', 'data: {"event_id":"live-0",…}']
```

### Response headers (verified over the wire)

```
status: 200 | ct: text/event-stream; charset=utf-8
cache-control: no-cache | x-accel-buffering: no | transfer-encoding: chunked
```

`Transfer-Encoding: chunked` is what proves the response is genuinely streaming rather than buffered. `X-Accel-Buffering: no` is inert for uvicorn itself but is the documented instruction to nginx-class proxies (PITFALLS.md:283); keep it. `Connection: keep-alive` per D-98.

### Latency

| Hop | Measured | Notes |
|-----|----------|-------|
| Kafka `send_and_wait` → `consumer.getone()` returns | **17.3 ms** | real broker, cp-kafka 7.6.0, `group_id=None`, `auto_offset_reset="latest"` |
| `hub.publish()` → first byte at the HTTP client | **0.9 / 0.9 / 1.1 ms** | three consecutive publishes through uvicorn + httpx |
| Total, end to end | **≈ 18 ms** | against SC3's 500 ms budget — a 27× margin |

### `Last-Event-ID` replay (verified)

```
  Last-Event-ID: live-2       -> replayed ids ['after-0', 'after-1', 'after-2']
  ?last_event_id=after-0      -> replayed ids ['after-1', 'after-2']
  unknown Last-Event-ID       -> whole buffer replayed
```

Read the header *or* the query parameter — `EventSource` sends the header automatically on reconnect, but a hand-rolled client or a curl demo needs the query form:

```python
leid = request.headers.get("Last-Event-ID") or last_event_id
```

Design note the plan should carry: when the id is **not** in the ring (the client was offline longer than 100 events), replaying the whole buffer is the right call — a live-activity feed prefers a few duplicates over a silent gap, and the browser can dedupe on `event_id`. Document it in `docs/api.md`.

### `/api/feed/recent`

Verified clamping: `limit=999` returned 13 items from a 13-item ring (`min(limit, 50)` then last-N). D-98's DB fallback for a cold process reads the last N rows of `availability_events` — note that table's primary key is `(time, event_id)` `[VERIFIED: shared/db.py:118-131]`, so order by `"time" DESC LIMIT n`.

### Cloud Run (human-gated, Phase 7 — build for it now)

- **Request timeout is the binding constraint.** "The timeout is set by default to 5 minutes (300 seconds) and can be extended up to 60 minutes (3600 seconds)" `[CITED: docs.cloud.google.com/run/docs/configuring/request-timeout]`, set with `gcloud run services update SERVICE --timeout=TIMEOUT`. An SSE stream is one request, so at the default every client is disconnected after 5 minutes. Set `--timeout=3600`. PITFALLS.md:285 already says this; it is now confirmed against the current docs.
- **Cloud Run does not buffer responses.** Server streaming (including `text/event-stream` consumed by `EventSource`) has been supported since the 2021 streaming release; the *initial* release buffered both directions and that is the source of the stale advice `[CITED: cloud.google.com/blog/products/serverless/cloud-run-now-supports-http-grpc-server-streaming]`. `X-Accel-Buffering: no` costs nothing and covers any nginx that appears later.
- **Even at 3600 s the stream will be cut.** The client must reconnect, which is exactly why `Last-Event-ID` is in D-98 and why the ring buffer must outlive a single connection. `EventSource` reconnects on its own; document the expected behaviour in `docs/api.md` so Phase 6 does not reimplement it.
- **Cold start.** min-instances defaults to 0; each new SSE client pays 2–3 s (PITFALLS.md:365). Phase 7's concern, but it changes the *first* event's latency, not the steady-state number SC3 measures.

## Kafka Consumer Without a Group (executed)

D-98 specifies `AIOKafkaConsumer("availability.events", group_id=None, auto_offset_reset="latest", enable_auto_commit=False)`. Every question about that configuration is answered by the installed source and a live broker.

**No manual `assign()` is needed.** `[VERIFIED: .venv/lib/python3.12/site-packages/aiokafka/consumer/consumer.py, AIOKafkaConsumer.start]`:

```python
        else:
            # Using a simple assignment coordinator for reassignment on
            # metadata changes
            self._coordinator = NoGroupCoordinator(
                self._client, self._subscription,
                exclude_internal_topics=self._exclude_internal_topics,
            )
            if (self._subscription.subscription is not None
                    and self._subscription.partitions_auto_assigned()):
                await self._client.force_metadata_update()
                self._coordinator.assign_all_partitions(check_unknown=True)
```

Confirmed against a live broker:

```
constructed+started OK; assignment() after start = frozenset({TopicPartition(topic='availability.events', partition=0)})
  -> no manual .assign() was called; NoGroupCoordinator did it
position of tp = 0
```

`NoGroupCoordinator._on_metadata_change` re-runs `assign_all_partitions`, so a partition added later is picked up without a restart. Do **not** call `consumer.assign(...)` — doing so switches `partitions_auto_assigned()` to false and disables that reassignment.

**`commit()` is an error, as intended.** `await consumer.commit()` → `aiokafka.errors.IllegalOperation: Requires group_id`. With no group there are no committed offsets, which is exactly D-98's design: every API replica sees every event. Add a unit test asserting the consumer factory sets `group_id=None`, mirroring the existing `tests/unit/test_kafka_consumer_config.py`.

**Cancellation and shutdown are clean.** Executed:

```
  pump: CancelledError received -> clean exit
  consumer.stop() after cancel: OK
  getone() after stop raises ConsumerStoppedError
```

So the lifespan teardown is: cancel the pump task → `await` it suppressing `CancelledError` → `await consumer.stop()`. The `AsyncExitStack` unwinds LIFO, verified end to end (`shutdown order: ['hub-stopped', 'redis-closed', 'db-closed']`), so push the callbacks in the order DB → Redis → hub and they tear down hub → Redis → DB.

**Startup guard.** `assign_all_partitions(check_unknown=True)` raises `UnknownTopicOrPartitionError` when the topic is absent from metadata. The test broker auto-created it (`cp-kafka` defaults `auto.create.topics.enable=true`), so the failure did not surface locally — but `services/state_machine/main.py`'s docstring records that auto-creation is disabled in the real deployment, and `scripts/create_topics.py` is the sanctioned creator. Reuse the `_assert_topics_exist` guard from `services/state_machine/main.py:64-79` in the API lifespan, checking at minimum `availability.events`. Without it, `create_app()` starts, `/healthz` passes, and `/api/feed/live` is a permanently silent stream — the worst kind of failure for a portfolio demo.

**Note for D-98's `auto_offset_reset="latest"`.** There is a genuine race: the consumer must have finished its first fetch before a test publishes, or `latest` skips the message. The E5 transcript inserted `await asyncio.sleep(0.5)` after `start()` before publishing and received the event in 17.3 ms. In the integration test, wait on the hub's own readiness (e.g. `assignment()` non-empty *and* one successful `position()` call) rather than a bare sleep, so the test is not timing-dependent on a loaded CI box.

## Request Models (executed)

The full `WatchCreate` sketch passes `mypy --strict` and `ruff check` under the repo's own `.ruff.toml` `[VERIFIED: transcript]`:

```
=== mypy --strict ===  Success: no issues found in 1 source file
=== ruff ===           All checks passed!
```

Every D-93 rule was exercised `[VERIFIED: transcript]`:

```
--- happy / normalisation ---
  OK  baseline (email lowered+stripped): email='alice@example.com'
  OK  days subset: days=['fri','sat']            <-- 'Fri','sat','fri' deduped + lowered
  OK  time window: 18:00 / 21:30
  OK  sms + phone: phone='+12125551234'          <-- from '+1 (212) 555-1234'
  OK  push + sub

--- rejections ---
  date_to < date_from      -> 'date_to must be on or after date_from'
  window > 60d             -> 'date window must be at most 60 days'
  date_from in past        -> 'date_from must not be in the past'
  bad HH:MM                -> 'must be HH:MM in 24-hour form (00:00-23:59)'  (both fields)
  from >= to               -> 'time_window_from must be strictly before time_window_to'
  only one time bound      -> 'time_window_from and time_window_to must be set together'
  bad day                  -> "unknown days: ['funday']; allowed: [...]"
  empty channels           -> 'List should have at least 1 item after validation, not 0'
  bad channel              -> "Input should be 'email', 'sms' or 'push'"    (loc channels.0)
  sms without phone        -> "channel 'sms' requires a phone number"
  push without sub         -> "channel 'push' requires a push_subscription"
  bad phone                -> 'must be E.164, e.g. +12125551234'
  party_size 0 / 11        -> ge/le violations
  extra field              -> 'Extra inputs are not permitted'              (extra="forbid")
  bad email                -> 'must be a valid email address'
  bad slug                 -> "String should match pattern '^[a-z0-9][a-z0-9-]*$'"
```

E.164 boundary table `[VERIFIED: transcript]` (regex `^\+[1-9]\d{7,14}$`, applied after stripping spaces and `()-.`):

| Input | Result |
|-------|--------|
| `+12125551234` | accepted → `+12125551234` |
| `+1 212 555 1234` | accepted → `+12125551234` (normalised) |
| `+12345678` | accepted (8 digits, the minimum) |
| `+123456789012345` | accepted (15 digits, E.164's maximum) |
| `+1234567` | rejected (too short) |
| `+1234567890123456` | rejected (16 digits) |
| `+0123456789` | rejected (leading zero after `+`) |
| `12125551234` | rejected (no `+`) |

**Details that will otherwise be discovered the hard way:**

- **`model_validator(mode="after")` errors have an empty `loc`.** Every cross-field failure above reported `loc=('',)`, which FastAPI renders as `{"loc": ["body"], ...}` in the 422. Field-level errors keep their field name. If `docs/api.md` documents the error shape (it should), document both forms.
- **`StringConstraints(to_lower=True, strip_whitespace=True)`** on the `email` type does D-90's normalisation declaratively — the value reaching `on_conflict_do_update` is already canonical, so the upsert key and the validation can never drift.
- **No `email-validator` dependency.** FastAPI's `EmailStr` requires it and it is not pinned. The hand-rolled check (one `@`, non-empty local part, a dot in the domain not at either end) is sufficient for a system whose only use of the address is to send a link to it — an address that does not exist simply bounces, and Phase 4 already records that.
- **`days_of_week` is stored as a comma string.** `watchlist_entries.days_of_week` is `Text` with the documented shape `"mon,tue,fri"` `[VERIFIED: migrations/versions/0004_create_watchlist_entries.py]`. The model takes a list and the persistence layer joins it. Order must be canonicalised (the sketch preserves first-seen order after dedupe) or two logically identical watches will differ on the wire; recommend sorting into `mon..sun` order before the join so Phase 4's matcher and any future `GROUP BY` see one representation.
- **`channels` likewise** is `Text`, default `"email"`.

## SQLAlchemy 2.0 Async (executed against TimescaleDB 2.17.2-pg16)

### User upsert (WATCH-01 / D-90)

```python
# Source: executed transcript, this session (SQLAlchemy 2.0.49 + asyncpg 0.31.0).
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = (
    pg_insert(User.__table__)
    .values(email=email, created_at=now, updated_at=now)
    .on_conflict_do_update(index_elements=["email"], set_={"updated_at": now})
    .returning(User.__table__.c.id)
)
user_id = (await session.execute(stmt)).scalar_one()
```

```
  first insert  -> user_id=1
  second upsert -> user_id=1  same_id=True
```

**The trap:** `on_conflict_do_nothing(index_elements=["email"]).returning(id)` returns **no rows** on conflict — verified: `rows = []`. A `scalar_one()` there raises `NoResultFound`, and a `scalar_one_or_none()` silently yields `None` and the watch gets inserted with `user_id=None`. D-90 correctly specifies `DO UPDATE`; the reason is this, and it belongs in a code comment.

### One slug, many source rows (D-93 / D-100)

After simulating Phase 3's migration 0009:

```
  rows for slug=lilia: [(1, 'opentable', '12345', [2, 4]), (2, 'resy', '998', [2, 4])]
  indexes: restaurants_pkey | uq_restaurants_source_platform_id | uq_restaurants_slug_source
```

`party_sizes` deserialises to a plain Python `list[int]`.

### `ARRAY` on `restaurants.party_sizes` — the generic type has no `contains`

`shared/db.py:64-66` uses `sqlalchemy.ARRAY`, not `sqlalchemy.dialects.postgresql.ARRAY`. Reproduced:

```
  Restaurant.party_sizes.contains([2]) -> NotImplementedError: ARRAY.contains() not
      implemented for the base ARRAY type; please use the dialect-specific ARRAY type
```

Three working alternatives, all executed and all returning `['lilia', 'lilia']`:

```python
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY

# 1. cast to the dialect type at the call site (no schema change)
sa.cast(Restaurant.party_sizes, PG_ARRAY(sa.Integer)).contains([2])

# 2. scalar membership — reads best for "does this restaurant serve party size N?"
sa.literal(2) == sa.any_(Restaurant.party_sizes)

# 3. raw SQL with a typed bindparam
sa.text("select slug from restaurants where party_sizes @> :ps").bindparams(
    sa.bindparam("ps", value=[2], type_=PG_ARRAY(sa.Integer)))
```

Recommend **(2)** for readability in `GET /api/restaurants` filtering. Do not "fix" `shared/db.py` to the dialect ARRAY inside this phase — that column is shared with the poller and the seeder, and a type swap is a change with its own verification.

### Soft delete + user-scoped 404 (D-95)

```
  soft delete UPDATE...RETURNING -> [1]      (empty list == 404 for wrong user)
  same UPDATE with wrong user_id -> []       (user-scoped 404 in one round trip)
```

### `watch:count` recount (D-95 / Phase 3 D-58)

The recount must produce a row for **every** source sibling, including ones with zero watches — otherwise a restaurant that drops to zero keeps its stale count and the poller keeps it in Tier 1 forever. An inner join silently omits it. Executed:

```python
select(Restaurant.source, Restaurant.platform_id, func.count(WatchlistEntry.id))
  .select_from(Restaurant)
  .outerjoin(WatchlistEntry, and_(WatchlistEntry.restaurant_id == Restaurant.id,
                                  WatchlistEntry.status == "active"))
  .where(Restaurant.slug == slug)
  .group_by(Restaurant.source, Restaurant.platform_id)
```

```
  recount per source row: [('opentable', '12345', 2), ('resy', '998', 0)]
  -> outerjoin is required, or the resy row (0 watches) disappears from the result
```

Note the `status == "active"` predicate belongs in the **join condition**, not the `WHERE` — in a `WHERE` it converts the outer join back into an inner one.

### Redis side of the same contract (executed)

```
  HGETALL watch:count   = {b'opentable:12345': b'7', b'resy:998': b'7'}
  HGET missing field    = None       (read as 0)
  HGETALL tier:override = {b'opentable:12345': b'1'}
```

**Naming trap, read carefully.** Phase 3 D-58 writes the field as `{source}:{restaurant_id}`; D-95 and D-100 write it as `{source}:{platform_id}`. These are the same string: the poller's `shared/redis_keys.py :: job(source, restaurant_id)` builds `f"{source}:{restaurant_id}"` where `restaurant_id` is the **platform** id (`resy:{venue_id}`, `opentable:{rid}`), matching `availability_events.restaurant_id` which `shared/db.py:107-109` documents as "the SOURCE PLATFORM id … NOT restaurants.id". `restaurants.id` (the surrogate BIGSERIAL) must never appear in a Redis field. Put a one-line assertion in `shared/watch_counts.py` and a unit test, because two different integers under one name is precisely the bug that costs an afternoon.

### Pagination

`GET /api/restaurants` uses `limit`/`offset` (D-100). With ≤ 100 restaurants this is fine and keyset pagination would be premature. Two guards: clamp `limit` (`Query(50, ge=1, le=100)`) and always add a deterministic tiebreaker to `ORDER BY` (e.g. `name, id`) — `ORDER BY name` alone with duplicate names lets a row appear on two pages.

## Rate Limiting (executed against Redis 7.2.16)

The Lua is the Phase 4 D-74a script re-parameterised. Executed with `cap=3`, `ttl=120`:

```
  call 1: count=1 allowed=True  ttl=120
  call 2: count=2 allowed=True  ttl=120
  call 3: count=3 allowed=True  ttl=120
  call 4: count=4 allowed=False ttl=120
  server version: 7.2.16
```

```lua
-- KEYS[1] = rate:api:{bucket}:{ip}:{epoch_minute}
-- ARGV[1] = ttl seconds (120), ARGV[2] = cap (60)
-- Returns {count, allowed, ttl}
local n = redis.call('INCR', KEYS[1])
if n == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
if n > tonumber(ARGV[2]) then
  return {n, 0, redis.call('TTL', KEYS[1])}
end
return {n, 1, redis.call('TTL', KEYS[1])}
```

The conditional `EXPIRE` is not cosmetic: Phase 4's research reproduced that an unconditional `EXPIRE` in a `MULTI` refreshes the TTL on every increment and turns the window into a sliding one. Here the window is per-minute-bucket so the consequence is milder, but the 120 s TTL exists to survive clock skew across replicas and would drift for a client that keeps sending.

**Key and `Retry-After`.** Executed:

```
  rate_key('watch_create','203.0.113.55', 1788000059) -> rate:api:watch_create:203.0.113.55:29800000
  rate_key('watch_create','203.0.113.55', 1788000060) -> rate:api:watch_create:203.0.113.55:29800001
```

`Retry-After` should be the key's remaining TTL clamped to ≥ 1, not a constant 60 — a client refused at second 59 of a window should be told 1, not 60. Return `X-RateLimit-Limit` and `X-RateLimit-Remaining` alongside; they cost nothing and make the curl demo in `docs/api.md` self-explanatory.

**Fixed-window burst.** A fixed window admits up to 2× the cap across a boundary (60 at :59.9 and 60 at :00.1). At 60/min protecting a Postgres insert this is irrelevant and a sliding window is not worth the complexity — but say so in `docs/api.md` rather than implying a strict guarantee.

**Every key goes in `shared/redis_keys.py`.** That is the D-18 rule and `shared/redis_keys.py`'s module docstring states it: "Any Redis access in services/ MUST import from here." `rate_api_key`, `RATE_WINDOW_SECONDS`, `RATE_KEY_TTL_SECONDS` and the Lua all land there, beside the existing `CLAIM_POLL_LUA` family.

## Tokens and Rotation (executed)

The rotation dry-run required by D-92 / ROADMAP SC2, executed with `freezegun` inside `async def` `[VERIFIED: transcript]`:

```
--- freezegun inside an async function, datetime.now(UTC) ---
  datetime.now(UTC) after an await inside freeze_time: 2026-09-05T12:00:00+00:00

--- rotation dry-run: mint with V1, cut over to V2 with a 7-day grace ---
  minted v1 token, len = 158
  v1 during v1:       OK v=1 user_id=42
  cutover instant          2026-09-05T12:00:01Z: v1 -> OK v=1     v2 -> OK v=2
  last second of grace     2026-09-11T23:59:59Z: v1 -> OK v=1     v2 -> OK v=2
  grace expiry (>= cutoff) 2026-09-12T00:00:00Z: v1 -> REJECTED   v2 -> OK v=2
  well after cutover       2026-09-20T00:00:00Z: v1 -> REJECTED   v2 -> OK v=2

--- other rejections ---
  wrong purpose  : REJECTED (wrong purpose)
  tampered sig   : REJECTED (bad signature)
  no separator   : REJECTED (malformed token)
  expired (t+61d): REJECTED (expired)
```

**freezegun works with `datetime.now(UTC)` inside async functions, including across `await` boundaries** — the value was still frozen after `await asyncio.sleep(0, ...)`. With `asyncio_mode = "auto"` no decorator is needed on the test. Use `freeze_time` as a context manager rather than a decorator on the async test function, so the frozen window is explicit and a single test can walk several instants (as above).

**Verification rules that must be in the implementation** (carried forward from Phase 4's research, all exercised in the sketch):

1. Reject before parsing if the token has no `.` separator.
2. Read `v` from the payload, look up `HMAC_MGMT_SECRET_V{v}`, accept `v == current` always and `v == current - 1` only while `now.date() < HMAC_GRACE_UNTIL`. Any other `v` is rejected outright.
3. `hmac.compare_digest` over the **base64url body string**, never over re-serialised JSON.
4. Reject an unknown or mismatched `p` (purpose). A `go` token must not open `/api/manage` — this is the token-confusion bug and is why `p` exists.
5. `json.loads` returns `Any`; assign through `payload_obj: object` and narrow with `isinstance(..., dict)` or `mypy --strict` rejects the return (Phase 4 research; reconfirmed in this sketch, which passes `--strict`).

**Claim-name reconciliation the planner must settle.** D-91 names the claims `{user_id, purpose, token_version, issued_at, expires_at}`; Phase 4's D-82 wire format is `{...claims, v, p, iat, exp}`. `token_version` duplicates `v`, `issued_at` duplicates `iat`, `expires_at` duplicates `exp`. Two sources of truth for the same fact is the shape that produces a token which passes signature verification and fails a semantic check. Recommend: keep the D-82 wire names (`v`/`p`/`iat`/`exp`) as the only encoding, add `user_id`, and treat D-91's names as the *documentation* of what those fields mean. A measured `{user_id, v, p, iat, exp}` token is **158 chars**, so `https://mise.place/manage/t/{token}` is ~186 characters — comfortable in an email, irrelevant to SMS (management links are email-only).

**Rotation script.** `scripts/rotate_hmac_secret.py --dry-run` should print the exact env delta and nothing else — no key material to stdout, no writes. Suggested output: the new `HMAC_TOKEN_VERSION`, the name (not value) of the new secret var, the computed `HMAC_GRACE_UNTIL` (today + 7 days), and the date after which `HMAC_MGMT_SECRET_V{n-1}` may be deleted. `scripts/` is in the `mypy --strict` target list (`Makefile` `lint`), so it must typecheck.

## Admin, Health and Metrics (executed)

### HTTP Basic (D-103)

```
  no creds: 401 Basic realm="mise-admin" {'error': 'Unauthorized', 'request_id': 'gen-123'}
  bad pw  : 401 {'error': 'Unauthorized', 'request_id': 'gen-123'}
  good    : 200 {'admin_user': 'admin'}
```

Use `HTTPBasic(auto_error=False)` so a *missing* header reaches your dependency and can be answered with `WWW-Authenticate` rather than FastAPI's default 403. Compare both fields with `hmac.compare_digest` and combine with a **non-short-circuiting** operator:

```python
ok_u = hmac.compare_digest(creds.username.encode(), ADMIN_USER.encode())
ok_p = hmac.compare_digest(creds.password.encode(), ADMIN_PW.encode())
if not (ok_u & ok_p):      # `and` short-circuits and leaks whether the username matched
    raise unauthorized
```

D-103's "routes disabled with 404 when the env vars are unset" is a `raise HTTPException(404)` at the top of the same dependency — verified working. Read the env through `services/api/config.py` functions so a test can set it per-case.

### `/api/metrics` (D-101)

Executed with `Instrumentator(excluded_handlers=["/api/metrics","/healthz","/readyz"], registry=REG).instrument(app)` and a hand-written route serving `generate_latest(REG)`:

```
  content-type: text/plain; version=1.0.0; charset=utf-8
  sse_connections_active: 1 sample line(s) -> ['sse_connections_active 0.0']
  watch_create_total:     1 sample line(s) -> ['watch_create_total{result="created"} 1.0']
  http_requests_total:    4 sample line(s) -> ['http_requests_total{handler="/admin/health",method="GET",status="4xx"} 2.0']
  http_request_duration_seconds: 21 sample line(s)
  /api/metrics itself instrumented? False
```

Facts the plan needs:

- `CONTENT_TYPE_LATEST == "text/plain; version=1.0.0; charset=utf-8"` — return it, do not hand-write `text/plain`.
- The instrumentator's `handler` label is the **route template** (`/admin/health`, not `/admin/health?x=1`), and `should_group_status_codes=True` (default) buckets status to `4xx` — both are the right cardinality choices and match PITFALLS.md:353's warning.
- `excluded_handlers` works: `/api/metrics` produced no series about itself. Exclude `/healthz` and `/readyz` too (Phase 7 will poll them every 60 s and they would dominate the histogram).
- **`.expose()` is available** (`endpoint='/metrics'`, `include_in_schema=True`) but serving the route yourself is better here: D-101 wants `/api/metrics`, `include_in_schema=False`, and the *same* registry `shared/metrics.py` writes into.

**Two registry hazards, both reproduced:**

```
--- duplicate registration ---
  ValueError: Duplicated timeseries in CollectorRegistry: {'sse_connections_active'}

--- registering the SAME name in a *different* registry is silently allowed ---
  default REGISTRY value: [0.0]
  other  registry value:  [42.0]
```

The first is the single-definition rule (Phase 3 D-69) enforcing itself — good, and it means a metric defined in two modules fails loudly at import. The second is the dangerous one: two registries holding the same metric name is **silent**, and `/api/metrics` would serve a gauge that is permanently 0 while the real one climbs elsewhere. `Instrumentator(registry=...)` defaults to `None` (= the global `REGISTRY`). Whatever `shared/metrics.py` chooses, `Instrumentator(registry=…)` and `generate_latest(…)` must be handed the *same object*. Add a unit test that increments `sse_connections_active` and asserts the value appears in the `/api/metrics` body — a test that passes today and would catch a future registry split.

**SSE poisons the latency histogram unless configured.** `[VERIFIED: .venv/lib/python3.12/site-packages/prometheus_fastapi_instrumentator/middleware.py:186-192]`:

```python
                duration = max(default_timer() - start_time, 0.0)
                duration_without_streaming = 0.0
                if response_start_time:
                    duration_without_streaming = max(response_start_time - start_time, 0.0)
```

`duration` is measured to *request completion*, which for `/api/feed/live` is the whole connection lifetime — a single 30-minute SSE client writes a 1800 s observation into `http_request_duration_seconds` and every p95 panel Phase 7 builds becomes meaningless. `should_exclude_streaming_duration` (default `False`) switches the metric to `duration_without_streaming`. Set `should_exclude_streaming_duration=True`, **and** add `/api/feed/live` to `excluded_handlers` if you would rather have no data than time-to-first-byte data. Recommend the former: TTFB on the feed endpoint is genuinely useful.

### `/readyz` (D-97)

Three checks, each with its own timeout so a hung dependency cannot hang the probe:

| Check | How | Meaning |
|-------|-----|---------|
| DB | `await session.execute(text("SELECT 1"))` | asyncpg pool is live |
| Redis | `await r.ping()` | rate limiting and `watch:count` will work |
| Feed hub | `hub.task is not None and not hub.task.done()` | the SSE pump has not died silently |

The third is the one that matters and the one that is easy to get wrong: a background task that raised is `done()` with an exception nobody retrieved. Check `done()`, and if it is done, surface `safe_error(task.exception())`. `/healthz` stays trivial (`{"status":"ok"}`) so Cloud Run's liveness probe never fails because Redis blipped.

### `/admin/health` Kafka lag (D-103)

`AIOKafkaAdminClient` is already used by `services/state_machine/main.py:64-79`; follow its pattern exactly — `start()` **inside** the `try`, `close()` in `finally` (that placement is IN-02, a fix already made once in this repo for a connection leak). Lag = `consumer.end_offsets(partitions)` minus the committed offset for groups `state-machine` and `notifier`. Construct the client per request and close it; it is an admin route with no latency budget, and a long-lived admin client is one more thing to tear down in the lifespan.

## Don't Hand-Roll

| Problem | Don't build | Use instead | Why |
|---------|-------------|-------------|-----|
| Constant-time secret comparison | `a == b` on tokens/passwords | `hmac.compare_digest` | Timing oracle; already the repo's convention |
| Kafka partition assignment without a group | `consumer.assign(...)` loop + metadata watcher | `group_id=None` → `NoGroupCoordinator` | Verified: auto-assigns at `start()` **and** reassigns on metadata change. Calling `assign()` disables the reassignment |
| SSE reconnect / backoff on the client | Custom polling loop | `EventSource` + `Last-Event-ID` | The browser does it; the server only replays |
| Rate-limit atomicity | `INCR` then `EXPIRE` as two calls | The 8-line Lua above | Two commands leave a key with no TTL if the process dies between them — the exact shape `tests/unit/test_no_setnx_expire_pairs.py` already bans |
| Streaming test client | Threads + a real socket | `uvicorn.Server` on a random port | BC-1; already the Phase 3 D-71 pattern |
| Request-duration measurement for streams | `BaseHTTPMiddleware` timing | Pure-ASGI `finally` | Measured 0 ms vs 103 ms |
| Client IP behind a proxy | `request.client.host` or `xff.split(",")[0]` | Second-to-last hop (BC-2) | Both defaults are exploitable or self-DoSing |
| E.164 / phone parsing | A permissive regex you keep widening | One strict regex + one normaliser, unit-tested with the boundary table above | `phonenumbers` is not pinned and is overkill for storing what the user typed |
| Prometheus text exposition | String building | `generate_latest()` + `CONTENT_TYPE_LATEST` | Escaping and the `# HELP`/`# TYPE` preamble are fiddly and versioned |
| Config loading | `BaseSettings` at import | Lazy functions in `services/api/config.py` | 02-02 deviation 1 — an import-time freeze pins integration tests to localhost |
| Ownership checks | `SELECT` then `UPDATE` | `UPDATE … WHERE id AND user_id RETURNING id` | One round trip, no TOCTOU, gives the 404 semantics D-95 requires |

**Key insight:** almost every "custom" mechanism this phase might grow already exists either in the pinned libraries or in Phases 1–3's shared modules. The phase's real work is composition and the three corrections above — anything that looks like new infrastructure is probably a re-implementation of `shared/redis_keys.py`, `shared/telemetry.py` or `shared/shutdown.py`.

## Common Pitfalls

### Pitfall 1: `date_from >= today` computed in UTC locks out every NYC evening

D-93 says `date_from >= today` without naming a timezone, and the repo's async-only, UTC-everywhere habits make `datetime.now(UTC).date()` the obvious implementation. It is wrong for four hours every night. Reproduced `[VERIFIED: transcript]`:

```
  now UTC        : 2026-09-06T01:30:00+00:00 -> date 2026-09-06
  now America/NY : 2026-09-05T21:30:00-04:00 -> date 2026-09-05
  a watch for date_from=2026-09-05 (tonight, NYC) is rejected by the UTC rule: True
  ...and accepted by the NY rule: True
```

Between 20:00 and midnight Eastern — the hours when someone is most likely to be hunting for a table tonight — the API returns a 422 telling a New Yorker that today is in the past. The product is NYC-only and `services/state_machine/persistence.py:31` already establishes the constant `_SERVICE_TZ = ZoneInfo("America/New_York")` for exactly this reason. **How to avoid:** promote `_SERVICE_TZ` to `shared/` (or import it) and use `datetime.now(_SERVICE_TZ).date()` in the validator. **Warning sign:** a test that only ever runs in the morning passes forever; pin the reproduction above as a `freeze_time("2026-09-06T01:30:00Z")` unit test.

### Pitfall 2: the SSE handler awaits something slow and stalls every other client

Enrichment (`(source, platform_id)` → restaurant name/slug/neighborhood) is a DB read. If it happens inside the pump loop on every event, one slow query delays delivery for all connections; if it happens per-connection, it multiplies. **How to avoid:** enrich exactly once, in the pump, behind an LRU cache keyed on `(source, platform_id)` — D-98 already specifies this. Note the type mismatch: `AvailabilityEvent.restaurant_id` is `int` while `restaurants.platform_id` is `TEXT` `[VERIFIED: shared/db.py:52, shared/events.py AvailabilityEvent]`, so the cache key must be `(source, str(event.restaurant_id))`. Phase 4's research logged the same trap as its Pitfall 6. **Warning sign:** a cache with a 100% miss rate.

### Pitfall 3: the ring buffer is per-process, so `/api/feed/recent` is inconsistent across replicas

Two Cloud Run instances hold two different ring buffers. A user who refreshes and lands on a different instance sees a different "recent" list, and a reconnect with `Last-Event-ID` may replay from a buffer that never held that id. **How to avoid:** D-98's DB fallback is the answer — but make it the fallback for *any* miss, not only for an empty buffer: if `replay_after` returns the whole buffer because the id is unknown, that is also the case where the DB has the truth. At MVP scale one instance is the norm; document the behaviour in `docs/api.md` and keep `/api/feed/recent` authoritative from the DB if consistency ever matters more than latency.

### Pitfall 4: `on_conflict_do_nothing()` with no `index_elements` hides real errors

Reproduced in § Sequencing: the `resy` sibling row silently vanished because the statement tolerated a `slug` unique violation it was never meant to tolerate. **How to avoid:** always name `index_elements`. **Warning sign:** an insert whose `rowcount` you never check and a row that "sometimes" is not there.

### Pitfall 5: the `/api/manage/{token}` token ends up in Cloud Logging

PITFALLS.md:297 warns about tokens in URLs. D-97 redacts them in *our* structlog output, and the helper is verified — but Cloud Run's own request log records the raw path, and so does any browser history and any `Referer` header the page later sends. **How to avoid:** three cheap mitigations. (a) Prefer `Authorization: Bearer` for every `/watches/*` call — D-91 already allows it, so `/api/manage/{token}` is only the *first* hydration request. (b) Set `Referrer-Policy: no-referrer` on the manage page (Phase 6, but note it now). (c) Keep the 30-day expiry and re-mint on every successful call, as D-92 specifies, so a leaked path decays. Record the residual risk in `docs/api.md` rather than implying the token is secret from the infrastructure.

### Pitfall 6: `enable_auto_commit=False` with `group_id=None` looks like a contradiction and gets "fixed"

There is no group, so there are no offsets, so auto-commit is meaningless — a future reader may delete the argument or, worse, add a `group_id` to "fix" it. Adding a group would silently change the semantics: replicas would share partitions and each event would reach **one** instance's SSE clients instead of all of them. **How to avoid:** a comment on the constructor plus a unit test asserting `group_id is None` (mirroring `tests/unit/test_kafka_consumer_config.py`). **Warning sign:** users on one browser tab see events that users on another do not.

### Pitfall 7: the background pump dies and nothing notices

An unhandled exception in the pump task leaves the API serving 200s on `/healthz` with a permanently silent feed. **How to avoid:** `/readyz` checks `task.done()` (§ Health); the pump's own loop catches per-message exceptions, logs via `safe_error`, and continues — a single malformed message must not kill the stream. Set a `sse_pump_errors_total` counter. **Warning sign:** `sse_events_sent_total` flat while the state machine's event counter climbs.

### Pitfall 8: middleware order

Starlette applies middleware in reverse registration order (last added is outermost) — verified in the transcript, where the `BaseHTTPLogging` added second wrapped the `PureASGILogging` added first. The logging middleware must be **outside** the instrumentator (so it sees the true duration) and **inside** CORS (so a CORS preflight rejection is still logged). Get this wrong and `/api/metrics` picks up series for a route the log says never ran.

### Pitfall 9: `ASGITransport` tests silently skip lifespan

Every route that reads lifespan state (`request.state.hub`, the DB engine, the Redis client) will fail under `ASGITransport` with an `AttributeError` that looks like a bug in the route. **How to avoid:** `dependency_overrides` for unit-ish tests, the uvicorn harness for anything touching lifespan state. Verified: startup order `['db','redis','hub']` only appears under uvicorn.

### Pitfall 10: `Retry-After` as a constant

A client refused at second 59 that is told to wait 60 s wastes a minute. Use the key's TTL. Minor, but it is the difference between a rate limiter and an annoyance.

### Pitfall 11: recount runs inside the request and can fail

D-95 puts `recount(slug)` "inside the same request". If Redis is down, a `POST /watches` that already committed a row would 500 and the client would retry, creating a duplicate watch. **How to avoid:** the DB commit is the source of truth; the recount is best-effort. Wrap it, log the failure with `safe_error`, increment a counter, and return 201. Add a reconciliation path (the admin health route can report drift, or a Phase 7 cron can rebuild the whole HASH from Postgres). **Warning sign:** duplicate watches appearing in pairs in `watchlist_entries`.

### Pitfall 12: the `days_of_week` string round-trip

The column is a comma-joined `Text`. A `PATCH` that sets `days_of_week: []` must be distinguished from one that omits the field (leave unchanged) and one that sets `null` (clear the filter). Pydantic's default `None` collapses "absent" and "null". **How to avoid:** use a separate `WatchUpdate` model with every field defaulting to a sentinel, and `model_fields_set` to detect presence — or accept `null` as "clear" and document that omission means "unchanged".

## Code Examples

### Pure-ASGI request logging middleware (mypy `--strict` + ruff clean)

```python
# Source: sketch executed and typechecked this session (starlette 0.52.1).
class RequestLogMiddleware:
    """Pure-ASGI structured request log (API-01, D-97).

    NOT BaseHTTPMiddleware: its `dispatch` resumes as soon as `call_next` returns the
    response object, which for a StreamingResponse is BEFORE a single body byte has been
    written. Measured: BaseHTTPMiddleware 0 ms vs pure-ASGI 103 ms for the same 103 ms stream.
    """

    def __init__(self, app: ASGIApp, log: Any) -> None:
        self.app = app
        self.log = log

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        request_id = headers.get("x-request-id") or str(uuid4())
        status_code = 0
        first_byte_ms: float | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, first_byte_ms
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                raw = list(message.get("headers", []))
                raw.append((b"x-request-id", request_id.encode("latin-1")))
                message = {**message, "headers": raw}
            elif message["type"] == "http.response.body" and first_byte_ms is None:
                first_byte_ms = (time.perf_counter() - started) * 1000
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # scope["route"] is only populated AFTER the router has matched, which is why
            # this read lives in the `finally` and not before `self.app(...)`.
            route = scope.get("route")
            self.log.info(
                "http_request",
                request_id=request_id,
                method=scope["method"],
                path=redact_path(cast(str, scope["path"])),
                route=getattr(route, "path", None),
                status=status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
                ttfb_ms=None if first_byte_ms is None else round(first_byte_ms, 2),
                client_ip=client_ip_from_scope(scope, trust_proxy=False),
            )
```

### Token redaction

```python
# Source: sketch executed this session.
_TOKEN_SEG_RE: Final[re.Pattern[str]] = re.compile(r"/[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}")
_SENSITIVE_PREFIXES: Final[tuple[str, ...]] = ("/manage/t/", "/api/manage/", "/go/", "/unsubscribe/")


def redact_path(path: str) -> str:
    for prefix in _SENSITIVE_PREFIXES:
        if path.startswith(prefix):
            return prefix + "{token}"
    return _TOKEN_SEG_RE.sub("/{token}", path)
```

### FeedHub (the parts that matter)

```python
# Source: sketch executed and typechecked this session.
class FeedHub:
    def publish(self, item: dict[str, Any]) -> None:
        """SYNCHRONOUS on purpose: it must never await.

        `await q.put(...)` on a full queue would block the single Kafka pump on the slowest
        connected browser. Being sync also makes iterating `self._subs` safe: with no
        suspension point, no other coroutine can subscribe or unsubscribe mid-iteration.
        """
        self._ring.append(item)
        for q in self._subs:
            while True:
                try:
                    q.put_nowait(item)
                    break
                except asyncio.QueueFull:
                    with contextlib.suppress(asyncio.QueueEmpty):
                        q.get_nowait()      # drop the OLDEST for this connection only
                    self._on_drop()

    def replay_after(self, last_event_id: str | None) -> list[dict[str, Any]]:
        if last_event_id is None:
            return []
        snapshot = list(self._ring)
        for i, item in enumerate(snapshot):
            if item["event_id"] == last_event_id:
                return snapshot[i + 1:]
        return snapshot     # id already rotated out of the ring -> replay everything held


def sse_frame(item: dict[str, Any]) -> bytes:
    payload = json.dumps(item, separators=(",", ":"), sort_keys=True)
    return f"id: {item['event_id']}\nevent: slot_opened\ndata: {payload}\n\n".encode()


async def sse_body(hub, last_event_id, on_open, on_close) -> AsyncIterator[bytes]:
    q = hub.subscribe()
    backlog = hub.replay_after(last_event_id)
    on_open()
    try:
        yield b": connected\n\n"
        for item in backlog:
            yield sse_frame(item)
        while True:
            try:
                item = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                yield b": ping\n\n"
                continue
            yield sse_frame(item)
    finally:
        hub.unsubscribe(q)
        on_close()


SSE_HEADERS: Final[dict[str, str]] = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}
```

### Rate-limit dependency

```python
# Source: sketch executed and typechecked this session; Lua executed against Redis 7.2.16.
async def enforce_rate_limit(r: Redis, bucket: str, ip: str, cap: int, now_epoch_s: int) -> None:
    script = r.register_script(FIXED_WINDOW_LUA)
    key = rate_key(bucket, ip, now_epoch_s)
    raw = cast(list[int], await script(keys=[key], args=[RATE_KEY_TTL_SECONDS, cap]))
    count, allowed, ttl = int(raw[0]), int(raw[1]), int(raw[2])
    if not allowed:
        retry_after = max(ttl, 1) if ttl > 0 else RATE_WINDOW_SECONDS
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate_limited",
            headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": str(cap),
                     "X-RateLimit-Remaining": "0", "X-RateLimit-Count": str(count)},
        )
```

### Lifespan with `AsyncExitStack` and lifespan state

```python
# Source: executed transcript this session (startup ['db','redis','hub'];
# shutdown ['hub-stopped','redis-closed','db-closed']).
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[dict[str, Any]]:
    configure_logging()
    async with AsyncExitStack() as stack:
        stack.push_async_callback(dispose_engine)          # last to close (LIFO)
        r = redis.from_url(redis_url())
        stack.push_async_callback(r.aclose)
        stack.push_async_callback(close_async_client)
        await assert_topics_exist(kafka_bootstrap_servers())   # fail fast, not silently
        hub = FeedHub(on_drop=SSE_DROPPED.inc)
        await hub.start(kafka_bootstrap_servers())
        stack.push_async_callback(hub.stop)                # cancel pump, then consumer.stop()
        yield {"hub": hub, "redis": r}                     # -> request.state.hub / .redis
```

`yield`ing a dict populates Starlette's lifespan state, reachable as `request.state.hub` — verified. Note the API does **not** call `run_until_signal`: uvicorn installs its own SIGTERM handling and drives the lifespan shutdown, so `shared/shutdown.py` stays with the worker services where it belongs.

### The uvicorn integration harness (BC-1)

```python
# Source: executed transcript this session. Put this in tests/integration/conftest.py.
@pytest_asyncio.fixture
async def live_api(app: FastAPI) -> AsyncIterator[str]:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="on"))
    task = asyncio.create_task(server.serve())
    try:
        while not server.started:
            await asyncio.sleep(0.02)
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(task, 5)
```

## State of the Art

| Old approach | Current approach | When changed | Impact on this phase |
|--------------|------------------|--------------|----------------------|
| `httpx.AsyncClient(app=...)` shortcut | `httpx.AsyncClient(transport=ASGITransport(app=...))` | httpx 0.28 | Every stale recipe fails with a `TypeError`. Phase 4's research already flagged it |
| `BaseHTTPMiddleware` buffers streaming responses | It does not, under Starlette 0.52.1 | Fixed upstream | The widely-cited pitfall is stale; the *timing* problem (Pattern 1) is the live one |
| `@app.on_event("startup"/"shutdown")` | `lifespan=` async context manager | FastAPI 0.93+ (deprecated since) | Use `lifespan` — it is the only form that can carry `AsyncExitStack` and yield state |
| Cloud Run buffers responses | Server streaming supported | 2021 streaming release `[CITED: cloud.google.com/blog/…/cloud-run-now-supports-http-grpc-server-streaming]` | SSE works on Cloud Run; the 300 s default timeout is the remaining constraint |
| `aioredis` | `redis.asyncio` | redis-py 4.2 merge | Already the repo's convention; `import redis` (sync) is CI-banned |
| pydantic v1 `@validator` / `@root_validator` | `@field_validator` / `@model_validator(mode="after")` | pydantic 2.0 | The sketch uses the v2 forms; v1 spellings error at class-definition time |
| `Instrumentator().instrument(app).expose(app)` at `/metrics` | `.instrument(app)` only, serve the registry yourself | n/a (choice) | D-101 requires `/api/metrics` on the shared registry |

**Deprecated / do not use:**
- `sse-starlette` — unnecessary given the executed framing; adds a dependency for ~15 lines.
- `slowapi` — forbidden by D-96 and unnecessary given the executed Lua.
- `python-multipart` — Phase 4's D-84a already established it is not a dependency; nothing in Phase 5 accepts form data.
- `prometheus_client.start_http_server` in a service that already speaks HTTP.

## Assumptions Log

| # | Claim | Section | Risk if wrong |
|---|-------|---------|---------------|
| A1 | Phase 4's `shared/tokens.py` will land with the D-82 wire shape (`{v,p,…,iat,exp}`, base64url body `.` base64url sig) | Tokens | The rotation sketch and `tests/unit/test_token_rotation.py` need reshaping. Mitigated: Phase 4's research measured that exact shape, so the risk is low |
| A2 | Phase 4's `EmailProvider.send(to, subject, html, text, headers)` signature holds | D-93 email | The management-link send is a one-line call-site change |
| A3 | Phase 3's `shared/metrics.py` uses the **default** `prometheus_client.REGISTRY` (implied by D-69's `start_http_server`) | Metrics | If it uses a custom registry, `Instrumentator(registry=…)` and `generate_latest(…)` must both be pointed at it — the silent-two-truths hazard reproduced above |
| A4 | Cloud Run's front end appends exactly **two** hops (`<client-ip>,<lb-ip>`) with no additional external load balancer | BC-2 | The second-to-last index becomes wrong. Mitigated by making the index a named constant and asserting the hop count in the admin health output |
| A5 | `/api/feed/live` sees fewer than ~100 concurrent connections at MVP | SSE | ARCHITECTURE.md:430 estimates ~10k per worker, and PITFALLS.md:453 puts the Redis-pubsub threshold at 30–50 clients; below 100 the in-process fan-out is correct |
| A6 | `watchlist_entries.status` vocabulary is exactly `active|paused|deleted` | D-95 | Verified in migration 0004's comment `[VERIFIED: migrations/versions/0004_create_watchlist_entries.py]` — this one is not an assumption for the values, only for no Phase 4 addition |
| A7 | `EventSource` in the Phase 6 PWA sends `Last-Event-ID` on reconnect (WHATWG behaviour) | SSE | The `?last_event_id=` query fallback is implemented regardless, so a failure degrades to "replay nothing" rather than an error |
| A8 | The `notification_log` history join for `GET /watches` (last 20 rows per watch) stays cheap | D-95 | At MVP volumes trivially true; a lateral join or a per-watch `LIMIT 20` subquery is the fix if it is not |

## Open Questions

### OQ-1 — Which timezone defines "today" for `date_from`, and should the whole API adopt it?

- **What we know:** the product is NYC-only; `services/state_machine/persistence.py:31` already defines `_SERVICE_TZ = ZoneInfo("America/New_York")`; the UTC reading is reproducibly wrong for four hours every night (Pitfall 1).
- **What is unclear:** whether `_SERVICE_TZ` should move to `shared/` (it would then be imported by the API, the notifier's daily cap and the state machine) and whether `HMAC_GRACE_UNTIL`'s date comparison should use it too.
- **Recommendation:** move `_SERVICE_TZ` to `shared/time.py` in this phase, use it for `date_from >= today` and for `/api/stats`' "24h" windows, and leave `HMAC_GRACE_UNTIL` on UTC (a rotation cutover is an operational event, not a user-facing date, and a 4-hour ambiguity inside a 7-day grace is immaterial — but say so in a comment so the inconsistency is deliberate).

### OQ-2 — Does `POST /watches` return 200 or 201 when the same email re-submits an identical watch?

- **What we know:** D-90 upserts the *user*; D-93 says `201 {watch, management_url, token}`. Nothing says what happens when the identical (user, restaurant, party, dates) watch is submitted twice — and the management email means a user who does not receive it will click "create" again.
- **What is unclear:** duplicate watches produce duplicate notifications (Phase 4 fans out per watch, and the Layer-2 idempotency key is per `watch_id`, so two watches = two alerts).
- **Recommendation:** add a partial unique index on `watchlist_entries (user_id, restaurant_id, party_size, date_from, date_to) WHERE status <> 'deleted'` in a Phase 5 migration `0011`, and make `POST /watches` `ON CONFLICT DO UPDATE` the mutable fields, returning `200` with the existing watch and a fresh token. This makes "create it again" idempotent from the user's point of view and removes a duplicate-notification path that no other layer catches. Flag to the planner as a **decision to lock**, since it changes the documented status code.

### OQ-3 — Is `recount(slug)` inline in the request, or should it be a background task?

- **What we know:** D-95 says "inside the same request". Pitfall 11 shows a Redis outage would then fail a request whose DB write already committed.
- **What is unclear:** whether the poller's tier accuracy is worth request-path coupling.
- **Recommendation:** keep it inline (the read-your-writes property is genuinely nice for the admin view) but make it **non-fatal** — try/except, `safe_error` log, `watch_count_recount_failures_total` counter, still return 201. Add `GET /admin/health` reporting of drift between the HASH and a live `COUNT(*)` so the failure is visible rather than silent.

### OQ-4 — Should `GET /watches` accept the token as a path segment as well as a Bearer header?

- **What we know:** D-91 allows both `GET /api/manage/{token}` (path) and `Authorization: Bearer` on `/watches/*`. Pitfall 5 notes the path form is recorded by Cloud Run's request log.
- **What is unclear:** whether Phase 6's page will hold the token in memory after hydration (it can) and therefore never needs the path form again.
- **Recommendation:** keep exactly the split D-91 specifies — path only on `/api/manage/{token}`, Bearer everywhere else — and add a `Referrer-Policy: no-referrer` note to the Phase 6 hand-off. Do not add a path variant of `/watches`.

### OQ-5 — Does the OpenAPI snapshot pin the whole document or just the route list?

- **What we know:** D-104 says the snapshot "pins the public route list so Phase 6 can rely on it". `app.openapi()` returns OpenAPI 3.1.0; a small demo app's full document was 1206 bytes sorted-JSON, and a real one will be tens of kilobytes.
- **What is unclear:** a full-document snapshot fails on every docstring edit, which trains people to regenerate it without reading the diff — the classic golden-file failure mode this repo already worries about.
- **Recommendation:** snapshot the **sorted `(path, method)` list plus, for each, the required request-body field names and the response status codes**. That is the contract Phase 6 depends on and it is stable against prose changes. Executed shape: `[('/admin/health','GET'), ('/api/metrics','GET'), ('/watches','POST'), …]`. Keep the full `openapi.json` out of git; serve it live.

### OQ-6 — Where does `services/api` get its logger configuration so uvicorn's own loggers are captured?

- **What we know:** `shared/telemetry.py :: configure_logging` calls `logging.basicConfig(...)` and configures structlog; uvicorn installs its own `uvicorn.error` / `uvicorn.access` handlers via its logging config. BC-3 shows `uvicorn.error` emitting a raw traceback.
- **What is unclear:** whether to pass `log_config=None` to `uvicorn.Config` (letting structlog own everything) or to keep uvicorn's access log and disable only the error traceback.
- **Recommendation:** pass `log_config=None` and call `configure_logging()` in the lifespan, so there is exactly one log pipeline and the redaction processor sees every record. Disable uvicorn's access log (`access_log=False`) since `RequestLogMiddleware` supersedes it and produces a strictly better line. Verify with the BC-3 marker-string test.

## Environment Availability

| Dependency | Required by | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.12.13 | — |
| Docker | integration tier (testcontainers) | ✓ | daemon reachable | tests skip with a reason (`tests/conftest.py :: _docker_available`) |
| Kafka (testcontainers) | SSE integration, `/admin/health` | ✓ | confluentinc/cp-kafka:7.6.0, started and exercised | — |
| Redis (testcontainers) | rate limit, `watch:count` | ✓ | redis:7.2-alpine → server 7.2.16 | — |
| TimescaleDB (testcontainers) | CRUD integration | ✓ | timescale/timescaledb:2.17.2-pg16 | — |
| fastapi / starlette / uvicorn / httpx / pydantic / sqlalchemy / asyncpg / aiokafka / redis / prometheus-client / prometheus-fastapi-instrumentator / structlog / orjson | all | ✓ | see § Standard Stack | — |
| pytest / pytest-asyncio / testcontainers / freezegun / respx | tests | ✓ | 9.0.3 / 1.3.0 / 4.14.2 / 1.5.5 / 0.23.1 | — |
| `shared/tokens.py`, `shared/crypto.py`, `services/api/app.py`, migrations 0009 & 0010, `shared/metrics.py` | D-91..D-103 | ✗ | — | **No fallback** — see § Sequencing Dependencies |
| Cloud Run URL | SC3's proxy measurement, `--timeout=3600` | ✗ | — | Human-gated to Phase 7; measured locally with identical headers (D-99) |
| Resend API key / verified domain | management-link email | ✗ | — | Phase 4's `NOTIFY_DRY_RUN` records the render without sending |

**Missing dependencies with no fallback:** every Phase 3 and Phase 4 artifact in the § Sequencing Dependencies table. Phase 5 cannot execute before Phases 3 and 4 land their migrations and shared modules.

**Missing dependencies with fallback:** Cloud Run (local uvicorn with the same headers), Resend (dry-run), Twilio/VAPID (not exercised by Phase 5 beyond storing a subscription).

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"`) `[VERIFIED: pyproject.toml:44-46]` |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (`testpaths = ["tests"]`, `pythonpath = ["."]`, marker `integration`) |
| Quick run command | `make test` → `uv run pytest tests/unit -x -q -W error::RuntimeWarning` |
| Full suite command | `make test-integration` → `uv run pytest tests/unit tests/integration -v` |
| Lint gate | `make lint` → `uv run ruff check . && uv run mypy shared/ services/ scripts/` |

Note the `-W error::RuntimeWarning` on the unit tier: an un-awaited coroutine is a test failure in this repo, which matters here because a mis-mocked `AsyncMock` on a synchronous `put_nowait` would otherwise pass silently.

### Phase Requirements → Test Map

| Req | Behaviour | Type | Automated command | File exists? |
|-----|-----------|------|-------------------|--------------|
| WATCH-01 | Email-only identity; repeat submit reuses the same `user_id`; email normalised | integration | `pytest tests/integration/test_watch_crud.py::test_repeat_email_reuses_user -x` | ❌ Wave 0 |
| WATCH-02 | All 18 `WatchCreate` rules accept/reject correctly; E.164 boundary table | unit | `pytest tests/unit/test_watch_models.py -x` | ❌ Wave 0 |
| WATCH-02 | `date_from >= today` uses America/New_York (Pitfall 1 reproduction) | unit | `pytest tests/unit/test_watch_models.py::test_tonight_is_not_in_the_past -x` | ❌ Wave 0 |
| WATCH-03 | Token mint/verify; wrong purpose, tampered sig, no separator, expired all rejected | unit | `pytest tests/unit/test_token_rotation.py -x` | ❌ Wave 0 |
| WATCH-03 | **SC2 dry-run**: N−1 verifies through the grace window, fails at the cutoff | unit | `pytest tests/unit/test_token_rotation.py::test_previous_version_grace_window -x` | ❌ Wave 0 |
| WATCH-03 | `scripts/rotate_hmac_secret.py --dry-run` prints the env delta and no key material | unit | `pytest tests/unit/test_rotate_script.py -x` | ❌ Wave 0 |
| WATCH-04 | Pause / resume / edit / soft delete; another user's watch is 404 not 403 | integration | `pytest tests/integration/test_watch_crud.py -x -k lifecycle` | ❌ Wave 0 |
| WATCH-05 | `users.phone` bytes are not the plaintext; `decrypt_phone` round-trips; response shows `phone_masked` only | integration | `pytest tests/integration/test_phone_ciphertext.py -x` | ❌ Wave 0 |
| WATCH-06 | 61st `POST /watches` in a minute → 429 with `Retry-After` | integration | `pytest tests/integration/test_rate_limit.py -x` | ❌ Wave 0 |
| WATCH-06 | **Three different spoofed `X-Forwarded-For` first hops yield ONE bucket key** (BC-2) | unit | `pytest tests/unit/test_client_ip.py -x` | ❌ Wave 0 |
| API-01 | Request log carries route template, real duration, redacted token path; no body, no token | unit | `pytest tests/unit/test_request_log.py -x` | ❌ Wave 0 |
| API-01 | **No exception message reaches any log sink** (BC-3 marker-string test) | unit | `pytest tests/unit/test_api_logs_never_carry_payload.py -x` | ❌ Wave 0 |
| API-01 | CORS preflight from `CORS_ALLOWED_ORIGINS` succeeds; from another origin does not | integration | `pytest tests/integration/test_api_plumbing.py -x -k cors` | ❌ Wave 0 |
| API-01 | `/readyz` fails when the SSE pump task is dead | integration | `pytest tests/integration/test_api_plumbing.py -x -k readyz` | ❌ Wave 0 |
| API-02 | SSE framing bytes (`id:`/`event:`/`data:`/blank line), `: ping` comment | unit | `pytest tests/unit/test_sse_framing.py -x` | ❌ Wave 0 |
| API-02 | Drop-oldest on a full queue; ring buffer unaffected; `sse_dropped_total` increments | unit | `pytest tests/unit/test_feed_hub.py -x` | ❌ Wave 0 |
| API-02 | `Last-Event-ID` (header and query) replays only later events; unknown id replays the buffer | unit | `pytest tests/unit/test_feed_hub.py -x -k replay` | ❌ Wave 0 |
| API-02 | **SC3**: publish to Kafka → first SSE byte in < 500 ms, through a real uvicorn (BC-1 harness) | integration | `pytest tests/integration/test_sse_live.py::test_first_event_within_500ms -x` | ❌ Wave 0 |
| API-02 | Reconnect with `Last-Event-ID` after a real disconnect replays the gap | integration | `pytest tests/integration/test_sse_live.py -x -k reconnect` | ❌ Wave 0 |
| API-02 | Consumer factory asserts `group_id is None`, `enable_auto_commit is False`, `auto_offset_reset == "latest"` | unit | `pytest tests/unit/test_feed_consumer_config.py -x` | ❌ Wave 0 |
| API-03 | `/admin/*` → 401 + `WWW-Authenticate` without creds; 401 on bad password; 200 on good | integration | `pytest tests/integration/test_admin.py -x -k auth` | ❌ Wave 0 |
| API-03 | `/admin/*` → 404 when `ADMIN_BASIC_*` unset | unit | `pytest tests/unit/test_admin_guard.py -x` | ❌ Wave 0 |
| API-03 | Restaurant CRUD; delete refused with 409 while active watches exist; create seeds `sched:polls` | integration | `pytest tests/integration/test_admin.py -x -k restaurants` | ❌ Wave 0 |
| API-03 | `PUT /admin/restaurants/{slug}/tier` writes and clears `tier:override` | integration | `pytest tests/integration/test_admin.py -x -k tier` | ❌ Wave 0 |
| API-03 | `/api/metrics` is unauthenticated, returns `CONTENT_TYPE_LATEST`, contains `sse_connections_active`, and carries **no** series about itself | integration | `pytest tests/integration/test_metrics.py -x` | ❌ Wave 0 |
| D-95 | `watch:count` HASH updated for **every** source row of the slug, including one with 0 | integration | `pytest tests/integration/test_watch_counts.py -x` | ❌ Wave 0 |
| D-93 | One slug resolves to two source rows; the watch binds to the OpenTable row | integration | `pytest tests/integration/test_restaurant_merge.py -x` | ❌ Wave 0 |
| D-100 | `/api/restaurants` filters, clamps `limit`, and paginates deterministically | integration | `pytest tests/integration/test_restaurants_api.py -x` | ❌ Wave 0 |
| D-104 | OpenAPI route-list snapshot (OQ-5 shape) | unit | `pytest tests/unit/test_openapi_snapshot.py -x` | ❌ Wave 0 |
| CLAUDE.md | No `import requests`, no `time.sleep(`, no sync `import redis` in `services/api` | unit | `pytest tests/unit/test_api_async_only.py -x` | ❌ Wave 0 |
| API-02 | No `while True: await asyncio.sleep(` heartbeat loop in `services/api/sse.py` | unit | `pytest tests/unit/test_api_async_only.py -x -k heartbeat` | ❌ Wave 0 |
| D-96 | No two-command `INCR`+`EXPIRE` pair in `services/api` (extend the Phase 2 gate) | unit | `pytest tests/unit/test_no_setnx_expire_pairs.py -x` | ✅ exists — extend its scanned set |
| — | Manual, human-gated: SSE through the real Cloud Run URL with `--timeout=3600` | manual | `docs/runbooks/sse-cloudrun.md` (`STATUS: pending-human`) | ❌ Wave 0 |
| — | Manual, human-gated: the `docs/api.md` curl walkthrough executed end to end | manual | `make api-smoke` | ❌ Wave 0 |

Every grep gate above must carry a non-vacuity companion (`test_scanned_*_is_not_empty`), per the precedent in `tests/unit/test_no_inline_sleep.py:47-53` and `tests/unit/test_no_setnx_expire_pairs.py`.

### Sampling Rate

- **Per task commit:** `make test` (`pytest tests/unit -x -q -W error::RuntimeWarning`) — the whole unit tier runs in seconds and covers every validator, the token rotation, the SSE framing, the hub semantics and every grep gate.
- **Per wave merge:** `make test-integration` plus `make lint` (`ruff check .` and `mypy shared/ services/ scripts/`).
- **Phase gate:** full suite green, `make api-smoke` executed, `docs/api.md` curl walkthrough verified, then `/gsd-verify-work`.

### Wave 0 Gaps

- [ ] `tests/integration/conftest.py` — add the `live_api` uvicorn-on-a-random-port fixture (**BC-1; blocks every SSE integration test**) and an `api_app` fixture that builds `create_app()` against the container URLs using the existing `reset_shared_db_singletons()` env-freeze workaround.
- [ ] `tests/unit/factories.py` — extend with `WatchCreate` payload builders and a `make_availability_event()` helper for the hub tests.
- [ ] `tests/unit/test_client_ip.py` — new (BC-2); the spoof vector is the executable statement of WATCH-06.
- [ ] `tests/unit/test_api_logs_never_carry_payload.py` — new (BC-3); model it on the existing `tests/unit/test_logs_never_carry_payload.py`.
- [ ] `tests/unit/test_api_async_only.py` — new grep gate scoped to `services/api/**`, plus its non-vacuity companion.
- [ ] `tests/unit/test_no_setnx_expire_pairs.py` — extend the scanned set to `services/api` (file exists).
- [ ] Every other file in the map above — new.
- [ ] Framework install: **none needed** — pytest, pytest-asyncio, testcontainers, freezegun and respx are all pinned and installed.
- [ ] Precondition assertions (§ Sequencing Dependencies) — a Wave 0 test that imports `shared.tokens`, `shared.crypto`, `shared.metrics`, `shared.watch_counts` and asserts migration head ≥ `0010`, failing with the owning decision id.

## Security Domain

### Applicable ASVS Categories

| ASVS category | Applies | Standard control in this phase |
|---------------|---------|-------------------------------|
| V2 Authentication | yes | No passwords by design (WATCH-01). The management token *is* the credential: HMAC-SHA256, versioned, 30-day expiry, `hmac.compare_digest`, purpose-scoped. Admin uses HTTP Basic over TLS with `compare_digest` on both fields and a non-short-circuiting combine |
| V3 Session Management | yes | Stateless; no cookies, no server-side sessions. Token rotation with a bounded grace (D-92) is the revocation story. Re-minting on every successful call bounds a leaked token's useful life |
| V4 Access Control | yes | Every management route is user-scoped in the SQL predicate (`WHERE id AND user_id`), returning 404 rather than 403 so existence is not disclosed. `/admin/*` is a separate credential and returns 404 when unconfigured |
| V5 Input Validation | yes | pydantic v2 with `extra="forbid"` on every request model; bounded `party_size`, date window, `limit`; slug constrained by pattern; all SQL through SQLAlchemy bound parameters |
| V6 Cryptography | yes | AES-256-GCM for phones and HMAC-SHA256 for tokens, both from `cryptography`/`hmac` via Phase 4's `shared/crypto.py` and `shared/tokens.py` — nothing hand-rolled in this phase |
| V7 Error Handling & Logging | yes | **BC-3** — the locked design leaks the exception message to the log sink. Redaction of token-bearing paths is implemented and verified; `safe_error` must gate every error egress |
| V9 Communications | partial | TLS is terminated by Cloud Run (Phase 7). `PUBLIC_BASE_URL` must be `https://` so minted management URLs are never `http://` |
| V13 API & Web Service | yes | CORS restricted to `CORS_ALLOWED_ORIGINS`; rate limiting on the only write endpoint; OpenAPI is public by design (Phase 6 depends on it) |

### Known Threat Patterns

| Pattern | STRIDE | Standard mitigation |
|---------|--------|---------------------|
| Rate-limit bypass via forged `X-Forwarded-For` | Denial of Service | **BC-2** — resolve the client from the second-to-last hop; unit-test the spoof vector |
| Whole-service rate limiting via the LB's own IP | Denial of Service | Same fix; never take the socket peer behind a proxy |
| Token confusion (a `go` token opening `/api/manage`) | Elevation of Privilege | `p` (purpose) claim checked on every verify; a wrong purpose is rejected before anything else is read |
| Token forgery / truncated-MAC comparison | Spoofing | Full 32-byte HMAC, `hmac.compare_digest`, MAC computed over the base64url body string |
| Enumeration of other users' watches | Information Disclosure | User-scoped `UPDATE`/`SELECT` predicates; 404 for another user's id |
| Sensitive data in logs (phone ciphertext, email, booking token, management token) | Information Disclosure | `safe_error` + `_redact_secrets` + `redact_path`; BC-3's marker-string test as the gate |
| SQL injection | Tampering | SQLAlchemy Core/ORM with bound parameters throughout; the one `sa.text()` in this research uses a typed `bindparam` |
| Admin credential brute force | Spoofing | `compare_digest` removes the timing oracle; Phase 7 should add a per-IP limit on `/admin/*` (currently only `POST /watches` is limited — worth raising with the planner) |
| Unauthenticated `/api/metrics` disclosure | Information Disclosure | Accepted and deliberate (D-101, DEPLOY-05 wants a public dashboard). Confirm no metric carries a label with a user id, email or phone — PITFALLS.md:353's cardinality rule and this privacy rule point the same way |
| Open SSE feed leaking availability | Information Disclosure | Accepted: the data is public by definition (PITFALLS.md:469). Never broadcast user-scoped notification events on this channel |
| Push endpoint used as an SSRF pivot | Tampering | `POST /api/push/subscribe` stores an arbitrary URL that Phase 4 later POSTs to. Validate the endpoint is `https://` and, ideally, allowlist the known push-service hosts. Raise with the planner |

## Project Constraints (from CLAUDE.md)

`CLAUDE.md` embeds STACK.md rather than listing directives; the operative rules come from the pinned stack plus `.ruff.toml`, `pyproject.toml`, `Makefile` and the established Phase 1–2 patterns.

| Constraint | Source | How Phase 5 complies |
|------------|--------|----------------------|
| Async-only in `services/` and `shared/`; no `import requests` | CLAUDE.md stack + CI grep | Nothing in this phase is synchronous I/O. `FeedHub.publish` is a sync *function* but performs no I/O — document that distinction in a comment so a future gate is not tempted to "fix" it |
| No `time.sleep(` in `services/`/`shared/` | `.ruff.toml` comment + `tests/unit/test_no_inline_sleep.py` | New gate scoped to `services/api` |
| No `import redis` / `from redis import` (sync client) | Same | `redis.asyncio` only |
| ruff `line-length = 120`, `select = ["E","F","W","I","UP","ASYNC"]` | `.ruff.toml` | Both sketches pass `ruff check --config .ruff.toml` `[VERIFIED: transcript]` |
| `mypy --strict` on `shared/ services/ scripts/` | `Makefile` `lint`, `[tool.mypy] strict = true` | Both sketches pass `mypy --strict` `[VERIFIED: transcript]`. Two idioms needed: `cast("list[tuple[bytes, bytes]]", scope.get("headers", []))` for ASGI scope reads, and narrowing `json.loads` through `object` |
| Every Redis key in `shared/redis_keys.py` | Module docstring, D-18 | `rate_api_key`, `RATE_WINDOW_SECONDS`, `RATE_KEY_TTL_SECONDS`, `FIXED_WINDOW_LUA`, `watch:count`/`tier:override` helpers all land there |
| Every Kafka schema in `shared/events.py` | D-06 | Phase 5 adds none — it only *reads* `AvailabilityEvent` |
| Env read lazily, never as a module constant | `services/state_machine/config.py:7-11` (02-02 deviation 1) | `services/api/config.py` uses functions; no `BaseSettings` |
| Grep gates carry a non-vacuity check | `tests/unit/test_no_inline_sleep.py:47-53` | Every new gate gets a `test_scanned_*_is_not_empty` companion |
| Never `str(exc)` in a log field — use `safe_error` | `shared/telemetry.py :: safe_error` docstring, T-02-03 | **BC-3** — the locked exception-handler design violates this via Starlette's re-raise; corrected |
| No `alembic revision --autogenerate` | Pitfall 12 / D-33, migration 0008's header | Any Phase 5 migration (e.g. OQ-2's `0011`) is hand-written |
| Small atomic commits | Established pattern | Planner's concern |

## Runtime State Inventory

Phase 5 is additive, not a rename or migration, so a full inventory is not required. The two adjacent items that *are* runtime state and that this phase begins writing:

| Category | Items | Action |
|----------|-------|--------|
| Live service config | Redis `watch:count` and `tier:override` HASHes — read by the Phase 3 poller, written here for the first time. Neither is in git and neither has a TTL. | `shared/watch_counts.py` owns every write; `/admin/health` should report drift vs a live `COUNT(*)`; a rebuild path is Phase 7's concern |
| Stored data | `watchlist_entries.status = 'deleted'` soft-delete rows accumulate forever (D-89 keeps them for the `notification_log` FK) | None in v1 — note in `docs/api.md` that "delete" is a soft delete and the row is retained for the audit trail |
| Secrets / env vars | New names only, no renames: `PUBLIC_BASE_URL`, `CORS_ALLOWED_ORIGINS`, `ADMIN_BASIC_USER`, `ADMIN_BASIC_PASSWORD`, `TRUST_PROXY_HEADERS`, `HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL`, `API_PORT`. `HMAC_MGMT_SECRET_V1` already exists in `.env.example` | Add the block to `.env.example`; `HMAC_MGMT_SECRET_V*` is already in `shared/telemetry.py`'s `_SECRET_KEYS` redaction set — extend it with `ADMIN_BASIC_PASSWORD` |
| OS-registered state | None — verified: no launchd/systemd/Task Scheduler artifacts in this repo | None |
| Build artifacts | None — no package rename, no egg-info | None |

## Sources

### Primary (HIGH confidence — executed in this repository's `.venv`, 2026-09-05)

- `httpx.ASGITransport` full-buffering behaviour and the `receive()` disconnect deadlock — read from `.venv/lib/python3.12/site-packages/httpx/_transports/asgi.py:54-60, 132-136, 161-183`, plus a reproduced 120 s hang.
- `uvicorn.Server` in-process SSE harness — full transcript: headers, `transfer-encoding: chunked`, 0.99 ms publish→receipt, heartbeat, generator finalisation on disconnect.
- `BaseHTTPMiddleware` vs pure-ASGI over a live stream — 0 ms vs 103 ms duration; `scope["route"].path` availability.
- `uvicorn.middleware.proxy_headers` — read from `.venv/…/uvicorn/middleware/proxy_headers.py:126-140`; both failure modes reproduced against a live server with the Cloud Run header shape.
- `starlette.middleware.errors.ServerErrorMiddleware` re-raise — read from `.venv/…/starlette/middleware/errors.py:180-186`; traceback leak reproduced.
- `AIOKafkaConsumer.start` / `NoGroupCoordinator.assign_all_partitions` — read from `.venv/…/aiokafka/consumer/consumer.py` and `group_coordinator.py`; auto-assignment, `IllegalOperation` on `commit()`, `ConsumerStoppedError` after `stop()`, cancellation, and a 17.3 ms broker→consumer latency all confirmed against confluentinc/cp-kafka:7.6.0.
- Redis fixed-window Lua — executed against redis:7.2-alpine (server 7.2.16); `watch:count` / `tier:override` HASH round trip.
- SQLAlchemy 2.0.49 + asyncpg 0.31.0 against timescale/timescaledb:2.17.2-pg16 — user upsert `RETURNING`, the `DO NOTHING` empty-return trap, one-slug-two-sources, `ARRAY.contains` `NotImplementedError` plus three working alternatives, soft delete with user-scoped 404, outer-join recount, and the `DROP INDEX` vs `DROP CONSTRAINT` failure.
- pydantic 2.13.3 `WatchCreate` — 18-rule accept/reject matrix and an 8-row E.164 boundary table; `mypy --strict` and `ruff check` both clean.
- freezegun 1.5.5 inside `async def` — frozen `datetime.now(UTC)` across an `await`; the full N−1 grace-window rotation dry-run.
- FastAPI 0.136.0 plumbing — `HTTPBasic` 401/404/200, exception handlers, `BackgroundTasks`, lifespan state and LIFO teardown, `app.openapi()` 3.1.0 route list.
- `prometheus_client` 0.25.0 / `prometheus-fastapi-instrumentator` 7.1.0 — shared-registry exposition, `excluded_handlers` proof, duplicate-registration `ValueError`, the silent two-registry hazard, and `middleware.py:186-192`'s `duration` vs `duration_without_streaming`.
- `gsd-tools query package-legitimacy check --ecosystem pypi …` — 11 packages.

### Primary (HIGH confidence — repository files read this session)

- `CLAUDE.md`, `pyproject.toml`, `.ruff.toml`, `Makefile`, `.env.example`
- `shared/db.py`, `shared/redis_keys.py`, `shared/kafka.py`, `shared/telemetry.py`, `shared/shutdown.py`, `shared/http_client.py`, `shared/events.py`
- `services/state_machine/main.py`, `services/state_machine/config.py`
- `migrations/versions/0002_create_users.py` … `0005_create_notification_log.py`
- `tests/conftest.py`, `tests/integration/conftest.py`, `tests/unit/test_no_inline_sleep.py`, directory listing of `tests/unit/`
- `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `.planning/config.json`, `.planning/deferred-items.md`
- `.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md`, `04-CONTEXT.md`, `04-RESEARCH.md` (§§ Signed Tokens, Layer-2 Idempotency, `/go`, Migration 0010, Phone Encryption, FastAPI harness, Project Constraints), `03-CONTEXT.md`
- `.planning/research/ARCHITECTURE.md`, `PITFALLS.md`, `STACK.md`

### Secondary (MEDIUM confidence — official vendor documentation)

- Cloud Run request timeout — default 300 s, maximum 3600 s, `--timeout=` `[CITED: docs.cloud.google.com/run/docs/configuring/request-timeout]`
- Cloud Run container runtime contract — 504 on timeout, HTTP/2 h2c `[CITED: docs.cloud.google.com/run/docs/container-contract]`
- `X-Forwarded-For` shape — "the first IP in this list is generally the IP of the client that created the request" `[CITED: docs.cloud.google.com/functions/docs/reference/headers]`
- Google Cloud Load Balancing — appends `<supplied-value>,<client-ip>,<load-balancer-ip>` and "does not verify any IP addresses that precede `<client-ip>,<load-balancer-ip>`" `[CITED: cloud.google.com/load-balancing/docs/https]`
- Cloud Run server streaming (SSE consumable by `EventSource`; the initial release buffered, later releases do not) `[CITED: cloud.google.com/blog/products/serverless/cloud-run-now-supports-http-grpc-server-streaming]`

### Tertiary (LOW confidence — marked `[ASSUMED]` where used)

- The exact hop count Cloud Run's front end contributes when no external load balancer is present (A4). Everything downstream of it is guarded by making the index a named constant.

## Metadata

**Confidence breakdown:**

- Standard stack — HIGH. Nothing new is installed; every version was read from the live `.venv`.
- SSE design and timings — HIGH. Framing, headers, latency, heartbeat, drop-oldest, replay and disconnect cleanup were all executed end to end.
- Kafka groupless consumption — HIGH. Read from aiokafka's source and confirmed against a real broker.
- Rate limiting and client-IP resolution — HIGH for the mechanism (executed); MEDIUM for the exact Cloud Run hop count (A4), mitigated by a named constant.
- SQLAlchemy patterns — HIGH. Every statement was executed against TimescaleDB.
- Request models — HIGH. Full accept/reject matrix, mypy-strict, ruff clean.
- Token rotation — HIGH for the semantics (executed dry-run); MEDIUM for the exact claim names, which depend on Phase 4's unexecuted `shared/tokens.py` (A1).
- Metrics — HIGH for the exposition and instrumentator behaviour; MEDIUM for which registry `shared/metrics.py` will use (A3).
- Cloud Run behaviour — MEDIUM. Documented but not measured; D-99 already gates the real measurement on Phase 7.

**Research date:** 2026-09-05
**Valid until:** 2026-10-05 for the pinned-version findings (they are pinned, so they do not drift); 2026-09-19 for the Cloud Run claims, which are the only externally-sourced items here.
