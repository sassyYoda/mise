# Project Research Summary

**Project:** Mise en Place
**Domain:** Real-time restaurant reservation intelligence — scraping + event pipeline + multi-channel notifications
**Researched:** 2026-04-20
**Confidence:** HIGH

## Executive Summary

Mise en Place is a distributed event-detection and notification system that happens to have a restaurant reservation use case. The core product is a polling fleet that continuously monitors Resy (via Playwright) and OpenTable (via httpx GraphQL), a stateful diff engine that turns noisy scrape output into confirmed availability events, a Kafka-backed notification pipeline that fans out to email/SMS/push in under 60 seconds, and a Next.js PWA with a live activity feed and per-restaurant availability heatmap. Research confirms the proposed architecture is sound and defensible for the portfolio narrative. The PRD stack is ~90% correct with five specific corrections that must be applied before implementation begins: Next.js 14 is two majors behind and must move to 15.x (or 16.x); `aioredis` is archived and must be replaced with `redis.asyncio` from redis-py; `playwright-stealth@2.0.3` is unmaintained and must be replaced with `tf-playwright-stealth==1.2.0`; TimescaleDB is not installable on Cloud SQL and must be self-hosted on the same GCE VM as Kafka; and Confluent Schema Registry adds zero value at MVP scale and should be deferred entirely. The sixth correction is a capability upgrade: Cloud Run Worker Pools (GA 2026) replace GCE VMs for the scraper and consumer fleet.

The primary technical risk is Resy bot detection, which can produce a catastrophic silent failure mode — polls return 200 OK with sanitized data, the diff engine sees no events, and the product looks dead during the demo. This is mitigated by `tf-playwright-stealth`, per-context fingerprint rotation, residential proxy traffic, and a soft-ban canary metric that alerts on response-signature drift rather than raw poll success rate. The secondary risk is false-positive notifications from diff-engine transient errors, mitigated by the confirmation poll at t+8s with a tri-state `AVAILABLE / UNAVAILABLE / UNKNOWN` representation. The third existential risk is non-technical: Twilio 10DLC registration takes 1-4 weeks and must be submitted on Day 1 of the project, not when SMS code is written. The legal context is favorable — the NY Restaurant Reservation Anti-Piracy Act (effective Feb 17, 2025) makes scalper marketplaces illegal in NY, and Mise en Place's monitor-only, no-auto-book, public-data-only posture is a strong positive differentiator that must be documented prominently in the README.

The recommended build order is Foundation and OpenTable polling first (proves the pipeline spine), then the State Machine and confirmation logic (the product's core intellectual work), then Resy and Playwright (highest-risk external dependency, isolated so a Playwright disaster cannot block the rest), then Notifications, then API and SSE, then Frontend, then Deploy and observability. The hard MVP cut line is: OpenTable polling + State Machine + Email notifications + Watchlist CRUD + basic Frontend. This is the minimum combination that validates the core thesis. Resy, SMS, Web Push, and the heatmap are all shippable additions on top of a working core.

---

## Key Findings

### Recommended Stack

The PRD stack is directionally correct but needs five concrete corrections applied before a line of code is written. Python 3.12 + FastAPI + asyncio + aiokafka + redis-py (async) + SQLAlchemy 2.0 + asyncpg is the canonical 2026 Python async backend stack. The browser automation layer (Playwright 1.58 + tf-playwright-stealth 1.2.0) is the only realistic path to Resy data. httpx 0.28 with `AsyncClient` pooling is the correct choice for OpenTable GraphQL. TimescaleDB must be self-hosted on GCE (co-located with the Kafka broker) because Cloud SQL does not support the Timescale extension — the PRD's "Cloud SQL/TimescaleDB" phrasing is not a real configuration. Cloud Run Worker Pools (GA January 2026) replace GCE for the scraper and consumer fleet, cutting cost ~40% vs request-driven Cloud Run Services for always-on workers and representing a strong portfolio signal given their recency. Next.js 15.x LTS on Vercel is the correct frontend host — Next.js 14 will be noticed by senior reviewers. All versions were verified against PyPI on 2026-04-20.

**Core technologies:**

- **Python 3.12** — backend language; stable PEP 695 types, production-proven asyncio
- **FastAPI 0.136 + Uvicorn 0.44[standard]** — async API with SSE; native Pydantic v2; uvloop gives ~30% throughput boost
- **Playwright 1.58 + tf-playwright-stealth 1.2.0** — Resy polling; only viable approach to JS-heavy SPA; stealth fork actively maintained vs unmaintained `playwright-stealth@2.0.3`
- **httpx 0.28** — OpenTable GraphQL; community consensus for new async Python code; superior mock support vs aiohttp
- **aiokafka 0.13** — Kafka producer/consumer; pure-asyncio API; correct choice over confluent-kafka at MVP throughput (400 events/day)
- **redis-py 7.4 (`redis.asyncio`)** — replaces archived `aioredis`; ZSET scheduler + SETNX idempotency + availability state
- **SQLAlchemy 2.0.49 + asyncpg 0.31** — ORM hot path; asyncpg is ~5x faster than psycopg3 async for read-heavy workloads
- **PostgreSQL 16 (Cloud SQL) + TimescaleDB 2.17 (self-hosted GCE)** — OLTP for watchlists/users; TimescaleDB hypertables for availability_events and poll_log time-series
- **Apache Kafka 3.8 KRaft mode (single GCE e2-small)** — durable 7-day replay + consumer group semantics; essential for audit trail and pattern model retraining
- **Pydantic 2.13 as schema contract** — replaces Confluent Schema Registry; `shared/events.py` is the single source of truth for all Kafka message shapes
- **Next.js 15.5 LTS + React 19 on Vercel** — PWA frontend; App Router stable; Vercel zero-config for Next; keep API on GCP
- **Resend 2.29 (email) + Twilio 9.10 (SMS) + pywebpush 2.3 (VAPID)** — multi-channel notification delivery
- **prometheus-client 0.25 + structlog 25.5 + Grafana Cloud free tier** — observability; public read-only Grafana link is a portfolio-launch requirement
- **Terraform 1.9 + hashicorp/google provider 7.28** — IaC; do not use OpenTofu at MVP
- **uv + ruff** — Python toolchain; uv is 10-100x faster than Poetry for Docker layer caching
- **Cloud Run Worker Pools (GA 2026)** — scraper/consumer fleet; long-running containers, CPU-based scaling, ~40% cheaper than request-driven Services for background work

**Explicit DO-NOT-USE list:**
- `aioredis` — archived; use `redis.asyncio`
- `playwright-stealth@2.0.3` — unmaintained; use `tf-playwright-stealth==1.2.0`
- `kafka-python` — sync, single-thread; use `aiokafka`
- Confluent Schema Registry — zero benefit at MVP; Pydantic models serve this role
- ZooKeeper-mode Kafka — deprecated and removed in Kafka 4.x; start on KRaft
- Next.js 14 / Pages Router — two majors behind; reviewers will notice
- `next-pwa` (shadowwalker) — struggles with App Router; use Serwist or a hand-rolled service worker
- OpenTelemetry at MVP — instrumentation package still beta `0.62b0`; skip

### Expected Features

Research confirmed that the market splits between first-party waitlists (free but batched/delayed), third-party monitors ($10-$18/mo, no pattern intelligence), and scalper marketplaces (illegal in NY since Feb 2025). Mise en Place's unique wedge is the combination of sub-60s verified latency, zero-friction no-account UX, free pricing, and pattern-intelligence (heatmap + pre-alerts) that no competitor offers. The NY Anti-Piracy Act is a tailwind — it eliminated Appointment Trader's core model and created reputational pressure on Dorsia, making a transparent, monitor-only, restaurant-respecting product positively differentiated in a way that would not have been true in 2023.

**Must have (table stakes) — missing any of these = product feels incomplete at first use:**
- Continuous polling for ~50 curated NYC restaurants (Resy + OpenTable)
- Watch CRUD with restaurant + date range + party size + time window + channel preference
- Sub-60s p95 detection-to-notification pipeline with confirmation poll and idempotency guard
- Email + SMS + Web Push delivery with deep-links to the specific Resy/OpenTable booking slot
- HMAC-token no-account management UI (create / view / pause / delete watches)
- Acknowledgement notification on watch creation
- Unsubscribe / STOP compliance (email CAN-SPAM + SMS TCPA) — non-negotiable legal requirement
- Restaurant catalogue with coverage transparency ("not monitored — request it" for uncovered restaurants)
- Mobile-first UI tested on iOS Safari specifically — the Resy demographic
- Public read-only Grafana metrics link — portfolio differentiator, also a user trust signal

**Should have (competitive differentiators — all unique vs competitors):**
- Availability pattern heatmap per restaurant (needs >= 2 weeks of polling data; ship "collecting data" placeholder at launch or begin pre-launch polling)
- Live SSE activity feed on homepage ("Just opened: 4-top at Don Angie, 2 min ago") — social proof + portfolio signal
- Flexible date range per watch ("any Fri/Sat in the next 3 weeks") — TableOne's filtering is widely criticized
- Alert delivery latency telemetry shown to user in management UI
- Multiple party sizes in one watch (2 or 4 people, whichever opens first)
- Admin page for restaurant onboarding and poll health monitoring

**Defer to v1.x (add after >= 4 weeks of data):**
- Pattern-detection v1 (rules-based: 48h rule, inventory-load-day, cancellation-peak) — requires >= 4-6 weeks data per restaurant
- Pre-alerts ("T-48h window opening in 6 hours for your watch")
- Restaurant coverage expansion to ~150 NYC restaurants
- Monthly pattern summary digest email

**Defer to v2+ (after PMF):**
- User accounts + freemium paid tier
- Shared / group watchlists
- Coverage expansion beyond NYC
- Tock / SevenRooms integration
- Native iOS / Android apps
- ML-based availability prediction

**Anti-features — never build:**
- Automated booking on user's behalf — ToS violation, legal liability, indistinguishable from scalping
- Paid reservation marketplace — illegal in New York under the Restaurant Reservation Anti-Piracy Act (up to $1,000/day per violation)
- Automated Resy account creation — explicit ToS violation, CAPTCHA / fingerprint detection cascade
- Browser extension that auto-clicks "book" — same problems as auto-booking plus account ban cascade

### Architecture Approach

The architecture is a 4-service event-driven pipeline intentionally over-engineered for the raw load (~400 events/day) to serve the portfolio narrative. The correct framing: architecture is the product for the tertiary persona (senior engineer reading the repo). The Polling Fleet (Playwright context pool + httpx adapter) emits to `availability.raw` Kafka topic; the State Machine Service is the only consumer of raw and the only producer of `availability.events` — this isolation enables replay-based debugging and decouples poller restarts from in-flight confirmation timers; the Notification Consumer fans out to watchlists and dispatches via Resend/Twilio/VAPID; the FastAPI API Server is stateless and handles watchlist CRUD, HMAC tokens, SSE live feed, and public metrics. The PRD proposes splitting Dispatcher + Workers — merge these into one Notification Consumer for MVP. State is split cleanly: ephemeral fast state in Redis (ZSET scheduler, availability state, idempotency keys), authoritative durable state in Postgres (watchlists, notification history), time-series analytics in TimescaleDB (availability_events, poll_log hypertables). The README must include an explicit "Why Kafka for 400 events/day?" section acknowledging the intentional over-engineering and explaining the 10x/100x scaling narrative.

**Major components:**
1. **Polling Fleet** — Playwright context pool (4 contexts, 1 browser) for Resy + httpx AsyncClient pool for OpenTable; reads Redis ZSET scheduler; produces `availability.raw`
2. **State Machine Service** — diffs raw against Redis SET; writes confirmation-pending to ZSET; re-polls via priority scheduler at t+8s; emits `availability.events` with Layer-1 SETNX idempotency guard; owns the replay script
3. **Notification Consumer** — consumes `availability.events`; queries Postgres for matching watchlists; dispatches email/SMS/push with Layer-2 SETNX idempotency; manual Kafka offset commit after provider ack
4. **API Server (FastAPI)** — stateless; watchlist CRUD with HMAC-SHA256 tokens; SSE `/api/feed` with single background Kafka consumer multicasting to connected clients (not one consumer per connection); public `/api/metrics`
5. **Next.js 15 PWA** — App Router; home + SSE live feed; watch setup; restaurant detail + heatmap; manage (HMAC-token URL); alert landing; PWA install flow with iOS standalone detection gate for Web Push opt-in

**Key patterns:**
- Distributed poll scheduler via Redis ZSET with Lua atomic pop (`BZPOPMIN` pattern)
- Raw/Refined topic split with 24h raw retention and 7d events retention enabling state machine replay
- Confirmation poll at t+8s routed through the scheduler (not inline `asyncio.sleep`) to respect rate limits
- Two-layer idempotency: Layer 1 at event emission (`event:{r}:{d}:{p}:{slot}:{txn}`, 20-min TTL); Layer 2 at notification dispatch (`notif:{user}:{event_id}:{chan}`, 24h TTL)
- Playwright context pool (not browser pool) for 3-4x memory savings; context recycled at 500 pages or on ban detection
- SSE with single background Kafka consumer per API process + in-memory asyncio queue per connected client; never one Kafka consumer per SSE connection
- `shared/events.py` as the Pydantic-based implicit schema registry; `shared/redis_keys.py` as the single source of Redis key namespaces and TTLs

### Critical Pitfalls

1. **Playwright browser-context memory leak killing the scraper overnight** — wrap every context in `async with browser.new_context()` or `try/finally context.close()`; detach event handlers before close; recycle the browser process every 500 polls; run with `--disable-dev-shm-usage` in Docker or mount `/dev/shm` >= 512 MB; gate Phase 3 exit on a 12-hour soak test with stable RSS. This is the most likely way the demo dies silently during overnight review.

2. **Resy silent soft-ban — polls return 200 OK with sanitized data** — use `tf-playwright-stealth` (not the abandoned `playwright-stealth@2.0.3`); jitter intervals (`45 + random.uniform(0, 15)` seconds per context); rotate fingerprints per account; use residential proxy for Resy traffic (not datacenter GCE egress); implement soft-ban canary metric that alerts on response-signature drift, not just poll success rate. Without the canary, silent soft-bans are indistinguishable from "no cancellations today."

3. **False-positive notifications from diff-engine transient errors** — implement tri-state `AVAILABLE / UNAVAILABLE / UNKNOWN` (errors/timeouts go to UNKNOWN, never flip to UNAVAILABLE); implement confirmation poll at t+8s as ZSET + side-loop, not inline `asyncio.sleep`; implement per-slot 15-minute flap-damping window. Ship these from day one; retrofitting after false positives in production is a credibility disaster.

4. **Kafka at-least-once delivery causing duplicate SMS/push notifications** — set `enable.auto.commit=false` on all consumers; manually commit offset only after provider 2xx ack; SETNX idempotency key must be set before provider call (not after); use `SET key value NX EX ttl` as a single atomic command (never `SETNX` + `EXPIRE` as two commands — a crash between them creates a permanent key with no TTL, permanently blocking that slot's notifications).

5. **Twilio 10DLC registration blocks SMS at launch** — Standard Campaigns can take "several weeks" per Twilio docs; submit on Day 1 (Phase 0 admin task); register a toll-free number as backup in parallel; plan the SMS-degraded demo path (email + Web Push as primary, SMS shown as "provisioning" in admin panel). This is a non-technical blocker that kills a technical launch.

6. **iOS PWA Web Push subscriptions silently terminated after ~3 pushes** — iOS Safari revokes a push subscription if the service worker `push` handler does not call `event.waitUntil(self.registration.showNotification(...))` wrapping the entire async chain; validate `title` + `body` + `data.url` server-side before sending; gate Web Push opt-in behind `window.matchMedia('(display-mode: standalone)')` check; test on a real iPhone in PWA mode (not simulator, not Safari tab) as a Phase 4 exit criterion.

---

## Implications for Roadmap

### Phase 0: Admin and Pre-conditions (Day 1, before code)

**Rationale:** Multiple non-technical blockers have multi-week lead times that cannot be compressed. Every one of these must start before or on Day 1 of Week 1 or they will gate the demo launch regardless of engineering velocity.

**Delivers:** Unblocked environment for all subsequent phases.

**Critical tasks — all must start Day 1:**
- Submit Twilio 10DLC Standard Campaign registration (1-4 week lead time; also register toll-free as backup)
- Register `mise.place` domain; configure DNS
- Set up GCP project; provision Artifact Registry, Cloud SQL, Memorystore, GCE VM for Kafka
- Generate HMAC secret (`secrets.token_bytes(32)`), VAPID keypair, store in Secret Manager — never in `.env` files
- Manually create Resy polling accounts (must be manual per PROJECT.md constraints — never automated)
- Draft README Legal & Ethical Scraping section (finalize at launch; draft exists from day one)

**Avoids:** Pitfall 5 (10DLC lead time), Pitfall 8 (legal/ToS exposure), Pitfall 14 (HMAC secret hardcoded)

**Research flag:** None — these are admin tasks, not engineering tasks.

---

### Phase 1: Foundation, Repo Scaffold, and OpenTable Polling (Weeks 1-2)

**Rationale:** No interesting logic yet — just the spine. Proves the Kafka plumbing, Redis ZSET scheduler, and OpenTable httpx path before introducing Playwright risk. OpenTable's semi-public GraphQL endpoint requires no authentication and is the safest first polling source. Every subsequent phase assumes raw events are flowing.

**Delivers:** `availability.raw` messages flowing in Kafka at configured cadence. `docker compose logs poller` is boring (that is correct). 10 seed restaurants polled via OpenTable. Basic Prometheus metrics exposed.

**Implements:**
- Repo skeleton with `services/`, `shared/`, `web/`, `ops/`, `scripts/` structure
- `shared/events.py` Pydantic schemas (the contract for all Kafka messages)
- `shared/redis_keys.py` (all key namespaces + TTL constants — single source of truth)
- `docker-compose.yml` with Kafka (KRaft, single broker) + Redis + Postgres + TimescaleDB
- Polling Fleet: OpenTable httpx adapter only; Redis ZSET scheduler with Lua atomic pop; rate limiter (token bucket, Redis-backed)
- TimescaleDB hypertables created via Alembic `op.execute` migrations; `chunk_time_interval = INTERVAL '1 day'`
- Redis `maxmemory-policy = noeviction` or `volatile-ttl` — not `allkeys-lru`
- CI: ruff + mypy + gitleaks/trufflehog secret scan on every commit

**Stack elements used:** Python 3.12, aiokafka 0.13, redis-py 7.4 (async), httpx 0.28, SQLAlchemy 2.0 + asyncpg 0.31, TimescaleDB 2.17, Alembic 1.18, Kafka 3.8 KRaft, prometheus-client 0.25, structlog 25.5

**Avoids:** Pitfall 9 (httpx pool exhaustion — shared AsyncClient in lifespan), Pitfall 11 (Kafka on persistent disk from day one), Pitfall 12 (TimescaleDB chunk interval set explicitly), Pitfall 18 (Redis eviction policy)

**Phase exit criterion:** 10 OpenTable restaurants polling successfully with stable file-descriptor count over 24h.

**Research flag:** Standard patterns — no deeper research needed.

---

### Phase 2: State Machine and Confirmation Logic (Week 3)

**Rationale:** This is the product's core intellectual contribution. Must come after raw events exist. Separating the State Machine from the poller is the single most important architectural decision — it enables replay, isolates the diff logic for testing, and keeps in-flight confirmation timers alive across poller restarts.

**Delivers:** `availability.events` emitted from `availability.raw` with false-positive suppression. Replay script at `scripts/replay_raw.py` as a first-class tool. Demo: inject fake raw events; show confirmed events emitted; show a chaos test where consumer is killed mid-process with zero duplicates.

**Implements:**
- State Machine Service: diff against Redis SET; tri-state `AVAILABLE / UNAVAILABLE / UNKNOWN`
- Confirmation ZSET + side-loop (NOT inline `asyncio.sleep`); confirmation poll issued through normal scheduler path to respect rate limits
- Layer-1 idempotency: `SET event:{r}:{d}:{p}:{slot}:{txn} 1 NX EX 1200` (single atomic command — zero occurrences of `SETNX` + `EXPIRE` as two separate calls)
- Per-slot 15-minute flap-damping window
- Emit to `availability.events` with 7-day Kafka retention
- `scripts/replay_raw.py` — feeds `availability.raw` from fixtures through state machine without re-polling
- Unit tests: simulated transient-error stream produces zero false events; kill-9 mid-process produces zero duplicates

**Avoids:** Pitfall 3 (false positives / flapping), Pitfall 7 (SETNX atomicity), Anti-Pattern 3 (inline confirmation sleep), Anti-Pattern 1 (emitting from poller)

**Phase exit criterion:** Simulated transient-error stream produces 0 false events; replay script runs end-to-end in CI.

**Research flag:** Standard patterns — idempotency and confirmation-poll logic are well-documented.

---

### Phase 3: Resy and Playwright Fleet (Week 4)

**Rationale:** Playwright is the highest-risk component (external DOM changes, bot detection, memory leaks). Build it after the foundation is solid so a Playwright disaster cannot block State Machine or Notification progress. This phase is isolatable — the pipeline already works on OpenTable; Resy adds a second source.

**Delivers:** ~50 restaurants polled across Resy + OpenTable. Grafana panel showing per-context scrape latency. 12-hour soak test passed. Soft-ban canary metric green. Demo: simulate 429 response and show context recycle.

**Implements:**
- Playwright context pool: 4 contexts, 1 browser; `asyncio.Semaphore(4)` for acquisition; warm-spare browser for crash recovery
- Resy adapter: login flow using `playwright_stealth(context)` from `tf-playwright-stealth`; availability scrape with versioned selectors in `selectors.py`
- Per-context fingerprint rotation (viewport, UA, Accept-Language, timezone — stable per account, rotated between accounts)
- Ban detection: response-signature drift alert (page size, header set, presence of known selectors vs rolling baseline); soft-ban canary Prometheus metric
- Context recycling: on ban detection, cookie expiry, or every 2h; recycle entire browser at 500 pages served; `--disable-dev-shm-usage` Docker flag
- Priority re-poll path for confirmation requests via Redis ZSET (not Kafka, to stay within 60s latency budget)
- Global 80 req/min rate cap enforced at the scheduler, not the worker
- Residential proxy routing for Resy traffic (datacenter IPs are first-class ban signals)
- 12-hour soak test in CI: RSS < baseline + 20%, Chromium PID count stable, poll success rate >= 99%
- Weekly `test_selectors.py` smoke test (Resy DOM changes are HIGH likelihood)

**Stack elements used:** Playwright 1.58, tf-playwright-stealth 1.2.0

**Avoids:** Pitfall 1 (memory leak), Pitfall 2 (bot detection / silent soft-ban), Anti-Pattern 5 (per-restaurant polling process)

**Phase exit criterion:** 12-hour soak test passes; soft-ban canary green for 7 consecutive days of polling.

**Research flag:** Needs deeper research during Phase 3. Resy-specific bot-detection details are LOW confidence (single source). Validate empirically: log `raw_open_count_before_emit` to calibrate confirmation delay. `tf-playwright-stealth` effectiveness against Resy's current protection must be tested live.

---

### Phase 4: Notification Pipeline (Week 5)

**Rationale:** Depends only on `availability.events` (Phase 2). Independent of Resy/Playwright — can start immediately after Phase 2 even if Phase 3 is still in progress. Twilio 10DLC must already be submitted (Phase 0) or SMS will not be available at this phase's exit.

**Delivers:** End-to-end notification flow. Demo: inject synthetic `availability.events`; matching watchlists receive notifications within latency budget; deduplication survives consumer restart.

**Implements:**
- Notification Consumer: consumes `availability.events`; Postgres query for matching watchlists; `enable.auto.commit=false`; manual commit after provider 2xx ack
- Layer-2 idempotency: `SET notif:{user}:{event_id}:{chan} 1 NX EX 86400` before provider call
- Per-user + per-channel rate limiting (Redis INCR + EXPIRE)
- Email channel: Resend 2.29; domain verified with SPF + DKIM + DMARC before Week 7
- SMS channel: Twilio 9.10 wrapped in `asyncio.to_thread()`; 10DLC campaign must be in "Registered" status; STOP keyword inbound webhook wired on Day 1 of SMS code
- Web Push channel: pywebpush 2.3 + VAPID keypair from Secret Manager; handle 410 Gone; `max.poll.records=1` on notifier consumer
- iOS-specific test: real iPhone in PWA standalone mode, 5 consecutive pushes, verify `event.waitUntil` wraps entire async chain
- Deep-link construction: `resy.com/cities/ny/venues/{slug}?date=...&seats=...` in every notification channel

**Avoids:** Pitfall 4 (Kafka duplicate notifications), Pitfall 5 (Twilio 10DLC), Pitfall 6 (iOS Web Push subscription death), Pitfall 7 (SETNX atomicity), Pitfall 10 (Kafka consumer poll timeout)

**MVP cut line:** Email + Web Push are sufficient for launch if 10DLC is delayed. SMS added as a post-launch update with transparent admin-page "provisioning" status.

**Phase exit criterion:** Kill-9 notifier between send and commit; verify no duplicate at Twilio SID level. Real iPhone PWA test: 5 consecutive pushes deliver. Opt-out flow (STOP / unsubscribe link) verified end-to-end.

**Research flag:** Standard patterns for email/SMS. iOS Web Push specific behavior is MEDIUM confidence — validate on real device.

---

### Phase 5: API Server, Watchlist CRUD, and SSE (Week 6)

**Rationale:** Decoupled from the pipeline — pipeline emits events regardless of whether the API exists. Can start in parallel with Phase 4 once Phase 2 is stable. Must come before the frontend.

**Delivers:** Complete API surface. Demo: curl to create watchlist, trigger synthetic event, see notification sent, see SSE event on connected curl.

**Implements:**
- FastAPI 0.136 with Pydantic v2 settings via `pydantic-settings`
- HMAC-SHA256 token mint/verify: payload includes `{user_id, purpose, token_version, issued_at, expires_at}`; path-based token (`/manage/t/{token}`) not query string; dual-version verification for rotation overlap; 32-byte secret from `secrets.token_bytes(32)`
- Watchlist CRUD: create / view / pause / delete with HMAC token auth
- PostgreSQL schema + Alembic migrations (watchlists, restaurants, users/tokens, notifications)
- SSE endpoint `/api/feed`: single background Kafka consumer per process; `asyncio.Queue` per connected client for multicast; heartbeat every 15s; `Cache-Control: no-cache` + `X-Accel-Buffering: no` headers; Cloud Run request timeout set to 3600s
- Public `/api/metrics` read-only endpoint
- Sentry configured with `before_send` scrubber for `cookie` / `authorization` / `x-auth` headers

**Avoids:** Pitfall 13 (SSE proxy buffering), Pitfall 14 (HMAC token design leaks), Anti-Pattern 4 (SSE consumer per Kafka subscription)

**Phase exit criterion:** HMAC rotation dry run (swap secret, verify v_N and v_N-1 both verify during overlap). SSE stream tested through Cloud Run URL (not localhost) with first event arriving < 500ms.

**Research flag:** Standard patterns — HMAC token design and SSE patterns are well-documented.

---

### Phase 6: Frontend PWA (Week 7)

**Rationale:** Requires the API. All pipeline pieces are live and tested; the frontend is a client of a stable backend.

**Delivers:** Full user journey from landing to receiving an alert. Demo: land on mise.place, create watch for Carbone Friday night, receive email/SMS/push when slot opens, click deep-link to Resy booking.

**Implements:**
- Next.js 15.5 LTS with App Router; `pnpm create next-app@15 --ts --app --tailwind`
- Home page with live SSE feed (last 50 events hydrated via REST at load; SSE appends); manual "Add to Home Screen" instructions when `isIOS && !isStandalone`
- Watch setup flow: email/phone input, restaurant picker, date range, party size(s), time window, channel preference
- Restaurant detail page with heatmap (TimescaleDB CAGG query; cells with < 10 observations shown gray); "Collecting data" placeholder for restaurants with < 14 days of history
- Manage page at `/manage/t/{token}`: view / pause / delete watches; alert latency telemetry per watch
- Alert landing page
- Service worker: hand-rolled or Serwist (`@serwist/next`) — NOT `next-pwa` (shadowwalker), which struggles with App Router
- PWA manifest; push subscription flow gated behind `(display-mode: standalone)` check
- All PWA behavior tested in production build (`next build && next start`) not dev mode

**Avoids:** Pitfall 6 (iOS Web Push), Pitfall 15 (pattern model overfitting in heatmap), Pitfall 19 (service worker update loop)

**Phase exit criterion:** Full user flow demo-able end-to-end on iOS Safari in PWA mode. Heatmap shows gray cells below minimum observations. Opt-out link in SMS verified with STOP webhook.

**Research flag:** Heatmap rendering with TimescaleDB CAGG is MEDIUM confidence — validate query performance at week 6 once data has accumulated.

---

### Phase 7: Deploy, Observability, and Portfolio Polish (Week 8)

**Rationale:** Deploy infrastructure can be provisioned early (Phase 0/1 started Cloud SQL, Memorystore, GCE), but final service deployment and public Grafana link are launch-blocking for portfolio reasons. The public read-only Grafana link is not optional — it is a portfolio artifact.

**Delivers:** Live at mise.place. Public Grafana dashboard at mise.place/metrics. README is the hiring artifact. Portfolio demo ready.

**Implements:**
- Cloud Run Services for FastAPI API (min-instances=1 during demo)
- Cloud Run Worker Pools for Polling Fleet, State Machine, Notification Consumer
- GCE e2-small for Kafka broker: KRaft mode, `acks=all`, persistent disk (pd-standard), documented single-broker tradeoff in README
- Cloud SQL PG 16; TimescaleDB on GCE co-located with Kafka
- Memorystore Redis 7.2 standard tier
- Terraform 1.9 + google provider 7.28 IaC for all resources
- Grafana Cloud free tier with public read-only dashboard link; dashboards as code in `ops/grafana/`
- Prometheus `scrape_ban_total` alert; `notification_idempotency_hits` counter; poll success rate >= 99% SLO alert
- Better Uptime monitors
- README: architecture section, Legal & Ethical Scraping section (rate-limit caps, no booking automation, no resale, robots.txt respect, monitor-only framing), "Why Kafka for 400 events/day?" honest tradeoff section, replay walkthrough
- `docs/ARCHITECTURE.md` in repo

**Avoids:** Pitfall 8 (legal/ToS), Pitfall 11 (Kafka persistence), Pitfall 17 (Prometheus cardinality), Pitfall 20 (Cloud Run cold start on SSE)

**Fallback:** If GCP proves expensive or slow, the architecture is portable to fly.io / Railway / Render.

**Phase exit criterion:** All items in the "Looks Done But Isn't" checklist from PITFALLS.md verified. Public Grafana read-only link accessible without login. README legal section reviewed.

**Research flag:** Cloud Run Worker Pools are new (GA 2026) — validate deployment pattern against GCP docs. Fallback to GCE managed instance group if deployment proves difficult.

---

### Phase Ordering Rationale

- **OpenTable before Resy** (Phase 1 before Phase 3): OpenTable requires no auth and has no bot detection, making it safe to build the scheduler and Kafka plumbing against a stable source. Playwright is the highest-risk component; isolating it to Phase 3 means a Playwright disaster cannot block State Machine or Notification work.
- **State Machine before Notifications** (Phase 2 before Phase 4): The Notification Consumer depends on `availability.events`. The State Machine is the only producer. No notifications can be built without it.
- **Phases 3 and 4 can run in parallel** if two engineers are available — the Notification Consumer depends on `availability.events` (Phase 2), not on Resy (Phase 3).
- **API before Frontend** (Phase 5 before Phase 6): The frontend is a client of the API. Frontend work is speculative without a stable API contract.
- **Infrastructure provisioned in Phase 0/1, finalized in Phase 7**: Cloud SQL, Memorystore, and GCE are provisioned early so DNS, secrets, and database migrations are ready throughout. Final service deployment happens in Week 8.
- **MVP cut line**: OpenTable polling + State Machine + Email notifications + Watchlist CRUD + basic Frontend. This validates the core thesis. Resy, SMS, Web Push, and the heatmap are all additive on top.

### Research Flags

**Phases needing deeper research or empirical validation during execution:**

- **Phase 3 (Resy / Playwright):** Resy-specific bot-detection details are LOW confidence (single source). Soft-ban behavior and effective fingerprint parameters must be validated empirically. Run a live test against Resy before committing to the full context pool architecture. `tf-playwright-stealth` effectiveness against Resy's current protection is unverified — validate in first week of Phase 3.
- **Phase 7 (Cloud Run Worker Pools):** Worker Pools are GA but new (January 2026). Community documentation is sparse. Validate deployment configuration against GCP docs before committing to this target. Fallback is GCE managed instance group.

**Phases with well-established patterns (no deeper research needed):**

- **Phase 1 (Foundation):** Redis ZSET scheduler, Kafka KRaft setup, httpx pooling, SQLAlchemy 2.0 async — extremely well-documented.
- **Phase 2 (State Machine):** Diff engine, confirmation-poll-via-ZSET, and SETNX atomicity patterns are all standard event-driven architecture.
- **Phase 4 (Notifications):** Resend, Twilio, pywebpush — all have good official docs. 10DLC registration is procedural, not technical.
- **Phase 5 (API):** FastAPI HMAC tokens, SSE multicast pattern, Postgres schema — all standard.
- **Phase 6 (Frontend):** Next.js 15 App Router, TimescaleDB CAGG heatmap query, Serwist service worker — standard patterns with good documentation.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All library versions verified against PyPI on 2026-04-20 and cross-checked with Context7. The five PRD corrections (Next.js version, aioredis, playwright-stealth, TimescaleDB hosting, Schema Registry) are unambiguous. Cloud Run Worker Pools are new but GCP-documented. |
| Features | HIGH | Competitor products verified via App Store listings, product pages, and news coverage. NY Anti-Piracy Act confirmed via primary legal source (Holland & Knight, Feb 2025). User pain points triangulated across multiple independent sources. |
| Architecture | HIGH | Patterns (ZSET scheduler, raw/refined topic split, confirmation-poll-via-ZSET, two-layer idempotency, context pool) are all well-established. Kafka vs Redis Streams analysis is honest and well-sourced. The portfolio-narrative framing is opinionated but grounded. |
| Pitfalls | HIGH for core-infra pitfalls (Playwright memory, Kafka at-least-once, SETNX atomicity, 10DLC lead time, iOS Web Push); LOW for Resy-specific bot detection details (single source; must be validated empirically in Phase 3). |

**Overall confidence:** HIGH

### Gaps to Address

- **Resy soft-ban empirical calibration (Phase 3):** The confirmation-poll delay (currently 8s) should be validated by logging `raw_open_count_before_emit`. If transient errors typically resolve in < 5s, lower to 5s; if they persist past 12s, raise it.
- **tf-playwright-stealth effectiveness against Resy (Phase 3):** Actively maintained but its specific effectiveness against Resy's current anti-bot stack is LOW confidence. First week of Phase 3 should include a controlled live test before committing to the full context pool architecture.
- **TimescaleDB CAGG query performance for heatmap (Phase 6):** Create the continuous aggregate in Week 5-6 (not earlier) and test against real data. Expected to be fast, but should be verified before the frontend consumes it.
- **Cloud Run Worker Pools deployment configuration (Phase 7):** New enough (GA January 2026) that community-sourced deployment patterns are sparse. Validate against official GCP docs before Phase 7; fall back to GCE managed instance group if needed.
- **Heatmap warm-up period UX (Phase 6):** Decide early whether to begin polling before public launch (recommended) or ship with a clearly designed "collecting data" placeholder. The heatmap needs >= 2 weeks of data to be useful.

---

## Sources

### Primary (HIGH confidence)
- PyPI verified package versions (2026-04-20): playwright 1.58, fastapi 0.136, sqlalchemy 2.0.49, redis 7.4, aiokafka 0.13, httpx 0.28.1, pydantic 2.13.3, asyncpg 0.31, psycopg 3.3.3, alembic 1.18.4, twilio 9.10.5, resend 2.29.0, pywebpush 2.3.0, prometheus-client 0.25, structlog 25.5, pytest 9.0.3, tf-playwright-stealth 1.2.0, uvicorn 0.44.0
- Context7: `/fastapi/fastapi`, `/redis/redis-py`, `/aio-libs/aiokafka`, `/encode/httpx`, `/vercel/next.js`, `/pydantic/pydantic`, `/magicstack/asyncpg`, `/sqlalchemy/alembic`, `/web-push-libs/pywebpush`, `/microsoft/playwright-python`
- [Next.js blog — Next.js 16.2 stable 2026-03-25](https://nextjs.org/blog)
- [Redis aioredis merge FAQ](https://redis.io/faq/doc/26366kjrif/what-is-the-difference-between-aioredis-v2-0-and-redis-py-asyncio)
- [GCP blog: Cloud Run Worker Pools + Kafka Autoscaler](https://cloud.google.com/blog/products/serverless/exploring-cloud-run-worker-pools-and-kafka-autoscaler)
- [Twilio A2P 10DLC Official Docs](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc)
- [Holland & Knight — NY curbs scalping of restaurant reservations (Feb 2025)](https://www.hklaw.com/en/insights/publications/2025/02/new-york-curbs-scalping-of-restaurant-reservations)
- [Microsoft Playwright-Python memory leak issues #286, #1754, #2511](https://github.com/microsoft/playwright-python/issues/286)
- [Kafka Consumer Offsets — Confluent](https://www.confluent.io/blog/guide-to-consumer-offsets/)
- [Redis SETNX + SET NX EX Official Docs](https://redis.io/docs/latest/commands/setnx/)
- [Progressier — iOS push subscriptions terminated after 3 notifications](https://dev.to/progressier/how-to-fix-ios-push-subscriptions-being-terminated-after-3-notifications-39a7)
- [OpenTable Terms of Use](https://www.opentable.com/c/legal/terms-and-conditions/)

### Secondary (MEDIUM confidence)
- [TableOne App Store listing](https://apps.apple.com/us/app/tableone-reservations/id6448799631) — pricing, feature set, review sentiment
- [ReservationFinder.io guides](https://www.reservationfinder.io/guides/resy-notify-alternatives) — competitor latency claims
- [Confluent blog: kafka-clients 2.13.0 Python Async GA (Nov 2025)](https://www.confluent.io/blog/confluent-kafka-clients-2-13-0-release-python-async/)
- [Leapcell — 10 Hidden Pitfalls of Redis Distributed Locks](https://dev.to/leapcell/10-hidden-pitfalls-of-using-redis-distributed-locks-39m5)
- [Gothamist — NY law aims to kill black market reservations](https://gothamist.com/news/new-york-law-aims-to-kill-black-market-for-restaurant-reservations)
- [Terraform Google Provider releases](https://github.com/hashicorp/terraform-provider-google/releases) — 7.28.0 current
- TimescaleDB chunk sizing and CAGG docs — TigerData, DEV

### Tertiary (LOW confidence — needs empirical validation)
- [Scraperly — How to Scrape Resy 2026](https://scraperly.com/scrape/resy) — Resy-specific protection level; single source; validate in Phase 3
- [Markaicode — Playwright memory leak fixes 2025](https://markaicode.com/playwright-mcp-memory-leak-fixes-2025/) — benchmarks not independently verified; direction matches GitHub issues

---
*Research completed: 2026-04-20*
*Ready for roadmap: yes*
