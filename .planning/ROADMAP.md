# Roadmap: Mise en Place

**Defined:** 2026-04-20
**Granularity:** standard (8-week MVP)
**Core Value:** When a coveted table opens, the watching user is notified fast enough to actually book it — p95 detection-to-notification latency <= 60 seconds.

## Overview

Mise en Place is an 8-week portfolio MVP for a distributed restaurant-reservation availability detection and notification system. The roadmap follows the research-validated build order: admin/foundation and the lowest-risk polling source (OpenTable) first to prove the Kafka + Redis ZSET spine; then the stateful diff engine and confirmation logic that constitute the product's core intellectual work; then the highest-risk external dependency (Resy via Playwright) isolated so bot-detection disasters cannot block downstream work; then notifications once events are flowing; then the API and watchlist CRUD that backend the frontend; then the Next.js PWA with heatmap and pattern intelligence; finally GCP deployment with a public Grafana dashboard and a portfolio-grade README. Phase 1 submits Twilio 10DLC registration on Day 1 because its multi-week lead time gates SMS in Phase 4.

## Phases

**Phase Numbering:**
- Integer phases (1-7): Planned milestone work
- Decimal phases (e.g., 3.1): Urgent insertions (marked with INSERTED)

- [ ] **Phase 1: Foundation, Admin Pre-conditions & OpenTable Polling** - Monorepo, Docker Compose stack, Kafka spine, Redis ZSET scheduler, OpenTable httpx polling for 50 seeded restaurants; Twilio 10DLC submitted Day 1
- [ ] **Phase 2: State Machine & Event Pipeline** - Tri-state diff engine with t+8s confirmation poll, two-layer idempotency, replay script; emits confirmed `availability.events`
- [ ] **Phase 3: Resy & Playwright Fleet** - Playwright context pool, tf-playwright-stealth, soft-ban canary, 12-hour soak test before Resy goes live
- [ ] **Phase 4: Notification Pipeline** - Email (Resend), SMS (Twilio), Web Push (VAPID) with Layer-2 idempotency, iOS PWA push validated on real device
- [ ] **Phase 5: API, Watchlist CRUD & SSE** - FastAPI with HMAC management tokens, watchlist CRUD, SSE live feed, admin routes, public metrics endpoint
- [ ] **Phase 6: Pattern Intelligence & Frontend PWA** - Next.js 15 PWA with heatmap, live feed, watch setup, manage, alert landing; rules-based pattern model with confidence gating
- [ ] **Phase 7: Deploy, Observability & Portfolio Polish** - Cloud Run Worker Pools + Vercel + self-hosted Kafka/TimescaleDB on GCE; Terraform IaC; public Grafana dashboard; README legal section

## Phase Details

### Phase 1: Foundation, Admin Pre-conditions & OpenTable Polling
**Goal**: `availability.raw` messages flow continuously in Kafka for 50 seeded NYC restaurants via OpenTable httpx polling; Twilio 10DLC registration is submitted (multi-week clock started) and all Day-1 admin blockers (domain, GCP project, Resy accounts, HMAC/VAPID secrets) are resolved.
**Depends on**: Nothing (first phase)
**Requirements**: FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05, FOUND-06, POLL-01, POLL-03, POLL-07, PERF-02
**Success Criteria** (what must be TRUE):
  1. Running `docker compose up` from a clean clone boots Kafka (KRaft), Redis, and PostgreSQL+TimescaleDB, and the OpenTable poller begins emitting `availability.raw` messages visible via a Kafka console consumer within 60 seconds.
  2. Twilio A2P 10DLC Standard Campaign registration is in "Pending" or "Registered" status in the Twilio console (submitted on or before Week 1, Day 1), with a toll-free number registered in parallel as backup.
  3. At least 50 NYC restaurants with OpenTable platform IDs, neighborhood, cuisine, price tier, and cover photo are seeded in PostgreSQL and appear as scheduled entries in the Redis ZSET `sched:polls`.
  4. TimescaleDB `availability_events` and `poll_log` hypertables exist with `chunk_time_interval = INTERVAL '1 day'`, and `polls.completed` events are written to `poll_log` with measurable latency.
  5. Poll success rate is >= 99% hourly across a 24-hour window, measured from `poll_log.success / total` with the shared `httpx.AsyncClient` holding stable file-descriptor count.
**Plans**: TBD
**UI hint**: no

### Phase 2: State Machine & Event Pipeline
**Goal**: The State Machine consumes `availability.raw`, diffs against Redis state with tri-state `AVAILABLE / UNAVAILABLE / UNKNOWN`, schedules confirmation re-polls at t+8s via Redis ZSET (not inline sleep), and emits `availability.events` to Kafka with atomic `SET NX EX` idempotency — producing zero false events under simulated transient-error streams.
**Depends on**: Phase 1
**Requirements**: STATE-01, STATE-02, STATE-03, STATE-04, STATE-05, STATE-06
**Success Criteria** (what must be TRUE):
  1. Injecting a simulated transient-error stream (timeout, 5xx, empty payload) via `scripts/replay_raw.py` produces 0 false `availability.events` — transient errors flow to UNKNOWN and never flip a slot to UNAVAILABLE.
  2. Given a `availability.raw` Kafka offset range as a fixture, `scripts/replay_raw.py` regenerates a byte-identical `availability.events` stream without re-polling OpenTable (replay determinism proven in CI).
  3. A chaos test that kills the State Machine with `kill -9` between diff and emit produces zero duplicate events on restart — the Layer-1 `SET event:{r}:{d}:{p}:{token} 1 NX EX 1200` idempotency key blocks re-emission, and the source tree contains zero occurrences of two-command `SETNX` + `EXPIRE`.
  4. Confirmed `availability.events` persist to the TimescaleDB `availability_events` hypertable with populated `first_seen_at`, `last_seen_at`, `duration_seconds`, `hours_before_service`, and `day_of_week` columns.
**Plans**: TBD
**UI hint**: no

### Phase 3: Resy & Playwright Fleet
**Goal**: Resy polling is live across ~50 restaurants via a Playwright context pool (1 browser, 4 contexts) with `tf-playwright-stealth`, fingerprint rotation, residential proxy, soft-ban canary metric, and a passed 12-hour soak test — without triggering silent soft-bans and within the 80 req/min global cap.
**Depends on**: Phase 2 (state machine must diff Resy data the same way it diffs OpenTable)
**Requirements**: POLL-02, POLL-04, POLL-05, POLL-06, PERF-05
**Success Criteria** (what must be TRUE):
  1. A 12-hour soak test of the Playwright fleet completes with RSS growth <= baseline + 20%, stable Chromium PID count, and poll success rate >= 99% — this is a gating criterion before Resy runs in production (PERF-05).
  2. The soft-ban canary Prometheus metric `scrape_ban_total` alerts on response-signature drift (page size, header set, presence of known selectors) relative to a rolling baseline, distinct from raw poll success rate.
  3. The polling fleet enforces tier-based cadence (60s / 3min / 10min based on active watch count) with +/-15% jitter and exponential backoff on 429/503, and a simulated 429 response triggers observable context recycle within one poll cycle.
  4. The global rate limiter caps Resy traffic at <= 80 req/min across all contexts and enforces >= 45s per-restaurant per-context interval — verified by a sustained 30-minute production trace in Grafana.
  5. Resy `availability.raw` events flow into the same Kafka topic as OpenTable and are diff'd by the existing State Machine without source-specific branching in the diff logic.
**Plans**: TBD
**UI hint**: no

### Phase 4: Notification Pipeline
**Goal**: `availability.events` fan out to matching watchlists and deliver via Resend (email), Twilio (SMS, assuming 10DLC approved), and VAPID Web Push with Layer-2 SETNX idempotency and manual Kafka offset commit — achieving p95 detection-to-notification latency <= 60 seconds and surviving consumer kill-9 without duplicate sends, including on a real iPhone in PWA standalone mode.
**Depends on**: Phase 2 (consumes `availability.events`); Phase 1 Twilio 10DLC registration for SMS activation
**Requirements**: NOTIF-01, NOTIF-02, NOTIF-03, NOTIF-04, NOTIF-05, NOTIF-06, NOTIF-07, PERF-01, PERF-03
**Success Criteria** (what must be TRUE):
  1. p95 detection-to-notification latency (measured `availability.events.produced_at` -> `notifications.sent.sent_at`) is <= 60 seconds over a sustained 24-hour production window, with SMS p95 <= 10s and Web Push p95 <= 5s (PERF-01).
  2. A chaos test that kills the Notification Consumer with `kill -9` between provider ack and Kafka offset commit produces zero duplicate sends at the Twilio SID level on restart — Layer-2 `SET notif:{watch_id}:{event_id} 1 NX EX 86400` claim occurs before the provider call, and `enable.auto.commit=false` is verified in config.
  3. A real iPhone in PWA standalone mode (tested via `window.matchMedia('(display-mode: standalone)')`-gated opt-in) receives 5 consecutive Web Push notifications without the subscription being revoked — the service worker `push` handler wraps the entire async chain in `event.waitUntil(self.registration.showNotification(...))`.
  4. STOP keyword on inbound Twilio webhook and one-click email unsubscribe link (HMAC-signed) both flip the watch to inactive within 5 seconds end-to-end, verified against a live US phone number.
  5. Deep links in all three channels (email, SMS, Web Push) route through `mise.place/go/[token]` and land on the correct Resy/OpenTable booking slot with date, party size, and time pre-filled; false-positive rate (slot_still_available=false / total sent) is < 2% daily (PERF-03).
**Plans**: TBD
**UI hint**: no

### Phase 5: API, Watchlist CRUD & SSE
**Goal**: A stateless FastAPI server exposes watchlist CRUD with HMAC-SHA256 management tokens, rate limiting, structured JSON logging, an SSE live feed that multicasts `availability.events` from a single background Kafka consumer per process, admin routes behind HTTP Basic auth, and a public read-only metrics endpoint — all testable end-to-end via curl before the frontend exists.
**Depends on**: Phase 2 (SSE tails `availability.events`); Phase 4 can run in parallel after Phase 2
**Requirements**: WATCH-01, WATCH-02, WATCH-03, WATCH-04, WATCH-05, WATCH-06, API-01, API-02, API-03
**Success Criteria** (what must be TRUE):
  1. A user can `POST /watches` with email, restaurant, party size (1-10), date range, optional time window, optional days-of-week filter, and channel preferences; the response includes a path-based management URL `/manage/t/{token}` with an HMAC-SHA256 token containing `{user_id, purpose, token_version, issued_at, expires_at}`.
  2. An HMAC secret rotation dry-run (swap env var + dual-version verification during a 7-day grace window) succeeds — a token signed with `token_version=N-1` still verifies during the grace period and fails after cutover.
  3. An SSE client connected to `/api/feed/live` through the actual Cloud Run URL (not localhost) receives its first event within 500ms of the event being published to Kafka; a single background Kafka consumer per API process multicasts to per-connection `asyncio.Queue`s, and heartbeat pings every 15 seconds keep the connection alive across Cloud Run's proxy.
  4. Phone numbers stored via `POST /watches` appear in the database as `\x...` AES-256-GCM ciphertext via pgcrypto (not plaintext) and are decrypted only at notification send time; rate limiting caps watch creation at 60 req/min per IP.
  5. Admin routes under `/admin` (HTTP Basic Auth) expose restaurant CRUD, polling-tier override, and per-restaurant event volume; public `/api/metrics` returns Prometheus-format counters and is accessible without authentication.
**Plans**: TBD
**UI hint**: no

### Phase 6: Pattern Intelligence & Frontend PWA
**Goal**: A Next.js 15 App Router PWA deployed to Vercel with service worker (Serwist), Web Push opt-in, availability heatmap (TimescaleDB CAGG, observation-gated), live SSE activity feed on the homepage, 2-step watch setup, restaurant detail with plain-English pattern summary, manage-watches, and alert-landing pages — all mobile-first, Lighthouse LCP <= 2.5s, and tested in production build on iOS Safari in PWA mode.
**Depends on**: Phase 5 (frontend is an API client)
**Requirements**: PATTERN-01, PATTERN-02, PATTERN-03, FE-01, FE-02, FE-03, FE-04, FE-05, FE-06, FE-07
**Success Criteria** (what must be TRUE):
  1. A user on `mise.place` (production build) can create a watch for Carbone Friday night via the 2-step `/watch/[slug]` flow, receive an email + Web Push alert when a matching slot opens, click the deep link, and land on the correct Resy booking page — validated on iOS Safari in PWA standalone mode.
  2. The restaurant detail page renders an availability heatmap (x=hour, y=day-of-week, color=frequency) from a TimescaleDB continuous aggregate; cells with < 10 observations render gray, restaurants with < 14 days of history show a "collecting data" placeholder, and pattern summary cards cite confidence intervals per PATTERN-02.
  3. Notifications include an estimated availability window ("estimated window: ~8 minutes based on this restaurant's history") when PATTERN-03 data is available; restaurants below the threshold omit the text rather than showing a misleading estimate.
  4. The homepage live SSE feed shows the latest 5 events (hydrated via REST on load, appended via SSE thereafter), rate-capped at 1 event/sec, and reconnects via `Last-Event-ID` after network drop.
  5. Lighthouse LCP is <= 2.5s (p75 on homepage) on mobile, all tap targets are >= 44x44px, and the `/manage/t/{token}` page lets a user pause, resume, delete, or edit any watch without authentication.
**Plans**: TBD
**UI hint**: yes

### Phase 7: Deploy, Observability & Portfolio Polish
**Goal**: The system runs at `mise.place` on GCP (Cloud Run + Cloud Run Worker Pools + Vercel + self-hosted Kafka and TimescaleDB on GCE + Memorystore Redis) with Terraform IaC, GitHub Actions CI/CD (lint + tests + docker-compose integration + Playwright smoke), Sentry, Better Uptime, a public read-only Grafana dashboard at `mise.place/metrics`, and a README with architecture diagram, legal/ethical-scraping analysis citing the NY Restaurant Reservation Anti-Piracy Act, and interview talking points.
**Depends on**: Phases 1-6 all production-ready
**Requirements**: DEPLOY-01, DEPLOY-02, DEPLOY-03, DEPLOY-04, DEPLOY-05, DEPLOY-06, DEPLOY-07, PERF-04
**Success Criteria** (what must be TRUE):
  1. The public Grafana read-only dashboard link is accessible without login from the README and displays live `poll_success_rate`, `poll_latency_p95`, `kafka_consumer_lag`, `events_per_minute`, and `notification_delivery_rate` panels — this is launch-blocking for portfolio credibility (DEPLOY-05).
  2. System uptime is >= 99.5% monthly (Better Uptime-monitored) across `mise.place` and the API health endpoint, with ping every 60 seconds (PERF-04); post-deploy health checks show Kafka consumer lag falling to 0 within 2 minutes and successful polls resuming within 3 minutes of each production deploy.
  3. A full production deploy (merge to `main` -> Artifact Registry SHA tag -> Cloud Run staging -> manual prod promotion) completes via GitHub Actions with lint (ruff + mypy), per-service pytest, docker-compose integration test (poll -> state -> event -> dispatcher -> mock worker), and a Playwright smoke test against staging all green.
  4. Terraform `apply` from a clean state provisions all GCP infrastructure (Cloud Run services, Cloud Run Worker Pools for polling/state/dispatcher/notifier, VPC, Memorystore, Artifact Registry, Secret Manager, GCE VMs for Kafka KRaft + TimescaleDB) with zero manual console clicks.
  5. The README includes an architecture diagram, the public Grafana link, the live-demo link, an explicit "Legal & Ethical Scraping" section citing the NY Restaurant Reservation Anti-Piracy Act (Feb 2025) and our 80 req/min cap / no-booking-automation / public-data-only posture, an honest "Why Kafka for 400 events/day?" tradeoff section, and the `scripts/replay_raw.py` walkthrough.
**Plans**: TBD
**UI hint**: no

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7
(Phases 3 and 4 may run in parallel if capacity allows — Notifier depends only on Phase 2 events.)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation, Admin & OpenTable Polling | 0/TBD | Not started | - |
| 2. State Machine & Event Pipeline | 0/TBD | Not started | - |
| 3. Resy & Playwright Fleet | 0/TBD | Not started | - |
| 4. Notification Pipeline | 0/TBD | Not started | - |
| 5. API, Watchlist CRUD & SSE | 0/TBD | Not started | - |
| 6. Pattern Intelligence & Frontend PWA | 0/TBD | Not started | - |
| 7. Deploy, Observability & Portfolio Polish | 0/TBD | Not started | - |
