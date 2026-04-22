# Requirements: Mise en Place

**Defined:** 2026-04-20
**Core Value:** When a coveted table opens, the watching user is notified fast enough to actually book it — p95 detection-to-notification latency ≤ 60 seconds.

## v1 Requirements

Requirements for MVP (8-week target). Each maps to exactly one roadmap phase.

### Foundation & Admin Pre-conditions

- [ ] **FOUND-01**: Monorepo scaffolded (services/, frontend/, terraform/, scripts/, .github/workflows/) with Docker Compose stack (Kafka, ZooKeeper or KRaft, Redis, TimescaleDB/PostgreSQL) runnable via `docker compose up`
- [ ] **FOUND-02**: PostgreSQL + TimescaleDB schema created via Alembic migrations (users, restaurants, watchlist_entries, notification_log, availability_events hypertable, poll_log hypertable)
- [x] **FOUND-03
**: Initial NYC restaurant catalog (≥ 50 restaurants) seeded with platform IDs, neighborhood, cuisine, price tier, cover photo
- [x] **FOUND-04
**: Kafka topics created (`availability.raw`, `availability.events`, `notifications.queued`, `notifications.sent`, `polls.completed`) with retention policies; single-broker acceptable at MVP
- [x] **FOUND-05
**: Twilio A2P 10DLC / toll-free registration submitted on Day 1 of Week 1 (multi-week lead time); domain `mise.place` registered; GCP project + Artifact Registry + secrets manager provisioned
- [x] **FOUND-06
**: Manually created pre-authenticated Resy accounts stored as encrypted secrets; VAPID keypair generated; HMAC management-token secret generated

### Polling Engine

- [x] **POLL-01**: Redis ZSET distributed poll scheduler (keyed by `next_poll_at` Unix timestamp); workers pop due jobs atomically and no-op when empty
- [ ] **POLL-02**: Polling worker supports three tiers (Tier 1: 60s for ≥ 10 watches, Tier 2: 3min for 3–9 watches, Tier 3: 10min for 1–2 watches) with ±15% jitter and exponential backoff on 429/503
- [x] **POLL-03**: OpenTable polling via `httpx` async client against the widget GraphQL availability endpoint; 90s minimum interval; parses slots with availability, seat area, and booking token
- [ ] **POLL-04**: Resy polling via a Playwright browser pool (1 browser, 4 isolated BrowserContexts) with pre-authenticated sessions, `tf-playwright-stealth`, fingerprint rotation, and realistic request headers
- [ ] **POLL-05**: Resy scraper calls the internal availability API endpoint (`/api/4/find`) directly rather than loading full HTML pages; enforces ≤ 1 request / 45s per restaurant per context and ≤ 80 req/min total across all contexts
- [ ] **POLL-06**: Soft-ban detection — response-signature canary metric catches `200 OK` responses with sanitized / empty availability data; alerts on anomaly
- [x] **POLL-07**: Poll results emitted to Kafka topic `availability.raw` with poll latency and `polls.completed` events written to TimescaleDB `poll_log`

### State Machine & Event Pipeline

- [ ] **STATE-01**: Redis availability state set (`avail:{restaurant_id}:{date}:{party_size}`) tracks currently known slot tokens per (restaurant, date, party) with 25-hour TTL
- [ ] **STATE-02**: State machine consumes `availability.raw`; computes tri-state diff (appeared / disappeared / unchanged) against current Redis state
- [ ] **STATE-03**: For newly appeared slots, state machine schedules confirmation poll at t+8 seconds via Redis ZSET (not inline `asyncio.sleep`); confirmation poll re-verifies against source, and only confirmed slots emit `availability.events`
- [ ] **STATE-04**: Emission-layer idempotency — `SET NX EX` on key `event:{rid}:{date}:{party}:{token}` (20-minute TTL) prevents duplicate event emission across consecutive polls and consumer redelivery
- [ ] **STATE-05**: `availability.events` persist to TimescaleDB `availability_events` hypertable with `first_seen_at`, `last_seen_at`, `duration_seconds`, `hours_before_service`, `day_of_week`
- [ ] **STATE-06**: Replay script — given an `availability.raw` Kafka offset range, replays state machine and produces identical `availability.events` output (portfolio artifact)

### Watchlist & User Management

- [ ] **WATCH-01**: User identified by email only (no account, no password); record created on first watch creation
- [ ] **WATCH-02**: User can create a watchlist entry with: restaurant, party size (1–10), date range, optional days-of-week filter, optional time window, optional seat-type filter, notification channels (email, SMS, push)
- [ ] **WATCH-03**: Management token = HMAC-SHA256(email, server secret); sent via email on watch creation; rotates monthly with 7-day grace period
- [ ] **WATCH-04**: User can manage watches via `/manage/[token]` — pause, resume, delete, edit date/party/time, change notification channels; no login required
- [ ] **WATCH-05**: Phone numbers encrypted at rest (AES-256-GCM via pgcrypto) and decrypted only at notification send time
- [ ] **WATCH-06**: Watchlist API endpoints (FastAPI): POST /watches, GET /watches/[token], PATCH /watches/[id], DELETE /watches/[id]; rate-limited to 60 req/min per IP

### Notification Pipeline

- [ ] **NOTIF-01**: Notification dispatcher consumes `availability.events`, queries watchlist for matching watches (restaurant, party, date range, time window, status=active), enqueues per-channel notification jobs to `notifications.queued`
- [ ] **NOTIF-02**: Dispatch-layer idempotency — `SET NX EX` on key `notif:{watch_id}:{event_id}` (24-hour TTL) prevents duplicate notifications on Kafka consumer redelivery
- [ ] **NOTIF-03**: Email worker sends via Resend with HTML template (restaurant, date/time, party size, Book-now CTA, estimated availability window, unsubscribe footer); retries 3× on failure then dead-letters
- [ ] **NOTIF-04**: SMS worker sends via Twilio (≤ 160 chars) with delivery SLA ≤ 10 seconds; honors STOP / unsubscribe webhook; retries 2× then logs failure + emails user
- [ ] **NOTIF-05**: Web Push worker sends via VAPID with delivery SLA ≤ 5 seconds; on invalid-subscription fallback to email; service worker properly wraps push handler with `event.waitUntil(...)` for iOS PWA compatibility
- [ ] **NOTIF-06**: Kafka consumer commits offset only after provider acknowledgement (manual commit); notification send records persisted to `notification_log` with status transitions (sent → delivered → clicked / failed)
- [ ] **NOTIF-07**: Deep link generator produces platform-specific URLs (Resy: date+seats pre-selected; OpenTable: full pre-fill including time) wrapped in `mise.place/go/[token]` redirect for click-through tracking + "too slow" fallback messaging

### Pattern Intelligence

- [ ] **PATTERN-01**: Pattern model computes per-restaurant metrics from `availability_events`: 48h-rule detection, inventory-load-day detection (≥ 3× baseline, ≥ 3 observations), top 3 cancellation-peak hour-of-day bins, median/p25/p75 availability duration
- [ ] **PATTERN-02**: Pattern model gates display on observation threshold (≥ 2 weeks of data or ≥ N events per restaurant) and reports confidence intervals; restaurants below threshold show "collecting data" placeholder
- [ ] **PATTERN-03**: Notifications include an estimated availability window text ("estimated window: ~8 minutes based on this restaurant's history") sourced from the pattern model when available

### Frontend — PWA

- [ ] **FE-01**: Next.js 15 App Router PWA deployed to Vercel with service worker (Serwist or custom) supporting Web Push opt-in and offline watch-setup caching
- [ ] **FE-02**: Home page with search bar, "how it works," sample heatmap, social-proof counter, and real-time SSE live activity feed ("Just now: Table for 2 at …") capped at 1 event/sec with latest 5 shown
- [ ] **FE-03**: Watch-setup flow (`/watch/[slug]`) — 2-step form (preferences → contact info) with preview of the notification users will receive
- [ ] **FE-04**: Restaurant detail page (`/restaurant/[slug]`) — availability heatmap (x=hour, y=day-of-week, color=frequency), pattern summary card in plain English, current active-watch count, "Add to watchlist" CTA, recent-events log
- [ ] **FE-05**: Manage-watches page (`/manage/[token]`) — list / pause / delete / edit watches; notification history with slot_still_available outcomes
- [ ] **FE-06**: Alert-landing page (`/go/[token]`) — confirms slot still available (or shows sympathetic "sorry, gone" state), captures click event, redirects to platform deep link
- [ ] **FE-07**: Mobile-first responsive layout, 44×44px minimum tap targets, Lighthouse LCP ≤ 2.5s (p75 on homepage)

### API & Real-time

- [ ] **API-01**: FastAPI server with CORS, 60 req/min rate limiting on watch-creation, structured JSON logging
- [ ] **API-02**: SSE endpoint (`/api/feed/live`) tails `availability.events` Kafka topic and broadcasts to connected browsers with `X-Accel-Buffering: no` header and keepalive pings for Cloud Run compatibility
- [ ] **API-03**: Admin-only routes (`/admin`) behind HTTP Basic Auth (OAuth2 in v2) for restaurant CRUD, polling-tier overrides, system-health metrics, per-restaurant event volume

### Deploy, Observability & Portfolio

- [ ] **DEPLOY-01**: Services deployed to GCP Cloud Run Worker Pools (polling fleet, state machine, dispatcher, notification workers) + Cloud Run (API) + Vercel (Next.js) + self-hosted Kafka on GCE + Memorystore Redis + self-hosted TimescaleDB on GCE (Cloud SQL does not support the TimescaleDB extension)
- [ ] **DEPLOY-02**: Terraform configs for all GCP infrastructure (Cloud Run services, VPC, Memorystore, Artifact Registry, secrets, GCE Kafka + TimescaleDB VMs)
- [ ] **DEPLOY-03**: GitHub Actions CI: lint (ruff + mypy) + per-service pytest + docker-compose integration test (poll → state → event → dispatcher → mock worker) + Playwright smoke test against staging
- [ ] **DEPLOY-04**: GitHub Actions CD: build-and-push on merge to main (Artifact Registry with SHA tag + deploy to Cloud Run staging); manual deploy-prod with post-deploy health checks (consumer lag → 0 in < 2min; successful polls in < 3min)
- [ ] **DEPLOY-05**: Prometheus metrics exported from all services + Grafana Cloud dashboard with poll_success_rate, poll_latency_p95, kafka_consumer_lag, events_per_minute, notification_delivery_rate; **public read-only dashboard link** (launch-blocking for portfolio)
- [ ] **DEPLOY-06**: Sentry error tracking on all services; Better Uptime pinging `mise.place` and API health endpoint every 60 seconds
- [ ] **DEPLOY-07**: README includes architecture diagram, live-demo link, public Grafana link, rate-limiting & ethical-scraping section, legal analysis citing NY Restaurant Reservation Anti-Piracy Act (Feb 2025), interview-question talking points

### Performance & Reliability

- [ ] **PERF-01**: p95 detection-to-notification latency ≤ 60 seconds (measured from `availability.events.produced_at` to `notifications.sent.sent_at`)
- [ ] **PERF-02**: Poll success rate ≥ 99% (`poll_log` success / total, hourly)
- [ ] **PERF-03**: False-positive rate < 2% (`notification_log.slot_still_available=false` / total sent, daily)
- [ ] **PERF-04**: System uptime ≥ 99.5% (Better Uptime, monthly)
- [ ] **PERF-05**: Playwright fleet passes 12-hour soak test without memory leak or zombie browser processes before Resy goes live in production

## v2 Requirements

Tracked but not in current roadmap.

### Expansion

- **V2-01**: Tock integration as third booking platform
- **V2-02**: US city expansion (Los Angeles, San Francisco, Chicago, Miami)
- **V2-03**: Predictive pre-alerts ("Nobu likely to release Saturday tables in 90 min — set a reminder?")
- **V2-04**: Restaurant partner API for opt-in verified direct availability feeds

### Monetization

- **V2-05**: Freemium tier — free tier = email only + 3 active watches; Pro ($4.99/mo) = SMS + push + unlimited watches + predictions

### Platform

- **V2-06**: React Native mobile app sharing business logic with Next.js
- **V2-07**: Group / team accounts with shared watchlists
- **V2-08**: OAuth2 admin authentication (replaces MVP HTTP Basic)
- **V2-09**: Multi-party-size watches (e.g., "party of 2 OR party of 4")
- **V2-10**: "Speed score" gamification — show how long each slot was available

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Automated booking on the user's behalf | Requires storing payment credentials; legal complexity; ToS risk on booking automation |
| Paid reservation marketplace (resell tables) | NY Restaurant Reservation Anti-Piracy Act (Feb 2025) makes this illegal in NY; conflicts with ethical positioning |
| Automated Resy account creation | Violates Resy ToS around account automation; polling accounts are created manually |
| Auth-bypass or private-API access | All polled data must be publicly visible to any anonymous browser user |
| Native iOS / Android apps at MVP | PWA with Web Push is sufficient for mobile coverage in v1 |
| User-generated content (reviews, comments, photos) | Out of scope — product is availability intelligence, not social |
| Confluent Schema Registry | Overkill at 400 events/day; Pydantic models + JSON on wire is sufficient at MVP |
| Heavy ML pattern model | Dataset too small at launch; lightweight statistical model is correct choice |

## Traceability

Populated by roadmap creation 2026-04-20. All v1 REQ-IDs map to exactly one phase.

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-01 | Phase 1 | Pending |
| FOUND-02 | Phase 1 | Pending |
| FOUND-03 | Phase 1 | Pending |
| FOUND-04 | Phase 1 | Pending |
| FOUND-05 | Phase 1 | Pending |
| FOUND-06 | Phase 1 | Pending |
| POLL-01 | Phase 1 | Complete (01-05) |
| POLL-02 | Phase 3 | Pending |
| POLL-03 | Phase 1 | Complete (01-05 — pending DevTools spike) |
| POLL-04 | Phase 3 | Pending |
| POLL-05 | Phase 3 | Pending |
| POLL-06 | Phase 3 | Pending |
| POLL-07 | Phase 1 | Complete (01-05) |
| STATE-01 | Phase 2 | Pending |
| STATE-02 | Phase 2 | Pending |
| STATE-03 | Phase 2 | Pending |
| STATE-04 | Phase 2 | Pending |
| STATE-05 | Phase 2 | Pending |
| STATE-06 | Phase 2 | Pending |
| WATCH-01 | Phase 5 | Pending |
| WATCH-02 | Phase 5 | Pending |
| WATCH-03 | Phase 5 | Pending |
| WATCH-04 | Phase 5 | Pending |
| WATCH-05 | Phase 5 | Pending |
| WATCH-06 | Phase 5 | Pending |
| NOTIF-01 | Phase 4 | Pending |
| NOTIF-02 | Phase 4 | Pending |
| NOTIF-03 | Phase 4 | Pending |
| NOTIF-04 | Phase 4 | Pending |
| NOTIF-05 | Phase 4 | Pending |
| NOTIF-06 | Phase 4 | Pending |
| NOTIF-07 | Phase 4 | Pending |
| PATTERN-01 | Phase 6 | Pending |
| PATTERN-02 | Phase 6 | Pending |
| PATTERN-03 | Phase 6 | Pending |
| FE-01 | Phase 6 | Pending |
| FE-02 | Phase 6 | Pending |
| FE-03 | Phase 6 | Pending |
| FE-04 | Phase 6 | Pending |
| FE-05 | Phase 6 | Pending |
| FE-06 | Phase 6 | Pending |
| FE-07 | Phase 6 | Pending |
| API-01 | Phase 5 | Pending |
| API-02 | Phase 5 | Pending |
| API-03 | Phase 5 | Pending |
| DEPLOY-01 | Phase 7 | Pending |
| DEPLOY-02 | Phase 7 | Pending |
| DEPLOY-03 | Phase 7 | Pending |
| DEPLOY-04 | Phase 7 | Pending |
| DEPLOY-05 | Phase 7 | Pending |
| DEPLOY-06 | Phase 7 | Pending |
| DEPLOY-07 | Phase 7 | Pending |
| PERF-01 | Phase 4 | Pending |
| PERF-02 | Phase 1 | Pending |
| PERF-03 | Phase 4 | Pending |
| PERF-04 | Phase 7 | Pending |
| PERF-05 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 57 total (note: original REQUIREMENTS.md footer stated 46; actual ID count across all categories is 57 — FOUND:6, POLL:7, STATE:6, WATCH:6, NOTIF:7, PATTERN:3, FE:7, API:3, DEPLOY:7, PERF:5)
- Mapped to phases: 57 ✓
- Unmapped: 0 ✓

### Coverage by Phase

| Phase | Requirements | Count |
|-------|-------------|-------|
| Phase 1 — Foundation, Admin & OpenTable Polling | FOUND-01..06, POLL-01, POLL-03, POLL-07, PERF-02 | 10 |
| Phase 2 — State Machine & Event Pipeline | STATE-01..06 | 6 |
| Phase 3 — Resy & Playwright Fleet | POLL-02, POLL-04, POLL-05, POLL-06, PERF-05 | 5 |
| Phase 4 — Notification Pipeline | NOTIF-01..07, PERF-01, PERF-03 | 9 |
| Phase 5 — API, Watchlist CRUD & SSE | WATCH-01..06, API-01, API-02, API-03 | 9 |
| Phase 6 — Pattern Intelligence & Frontend PWA | PATTERN-01..03, FE-01..07 | 10 |
| Phase 7 — Deploy, Observability & Portfolio Polish | DEPLOY-01..07, PERF-04 | 8 |

---
*Requirements defined: 2026-04-20*
*Last updated: 2026-04-20 — traceability populated by gsd-roadmapper*
