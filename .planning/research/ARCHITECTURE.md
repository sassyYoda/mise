# Architecture Research

**Domain:** Real-time event detection and multi-channel notification pipeline (restaurant reservation availability)
**Researched:** 2026-04-20
**Confidence:** HIGH — patterns are well-established; the load is small enough that multiple valid architectures exist, so recommendations are opinionated but grounded in the portfolio-narrative context.

---

## Executive Architectural Assessment

The proposed 5-service Kafka architecture is **defensible and correct for the portfolio narrative**, but **over-engineered for the raw load** (50 restaurants, ~400 events/day ≈ 16 events/hour, ~2,500 notifications/day ≈ 1.7/min average). At this volume a single process with asyncio tasks and a Postgres `NOTIFY` channel would functionally suffice.

The right framing: **architecture is the product**. The portfolio reader is a senior engineer evaluating systems thinking. Therefore we keep the Kafka pipeline, the State Machine Service, the confirmation-poll, and the idempotency guard — because they are the *demonstration artifacts*. What we simplify is the **operational footprint** (service count, deploy targets, dashboards) without collapsing the *logical* pipeline.

**Key architectural decisions recommended in this document:**

1. **Keep Kafka** — but run 4 logical services, not 5 (merge Dispatcher + Workers into one multi-channel consumer for MVP).
2. **Keep the confirmation-poll at t+8s** — but make the delay configurable per source and enforce it inside the State Machine, not inside the poller.
3. **Keep the Playwright context pool** — but size it as 4 contexts × 1 browser, not 4 browsers, and introduce a warm-spare for failure recovery.
4. **Idempotency at two boundaries** — at event emission (dedup transient flaps) and at notification dispatch (dedup consumer redelivery). Different keys, different TTLs.
5. **Rate limits enforced at the poll scheduler**, not at the Playwright worker — the worker is too late to be polite.
6. **Build order: Scheduler → Scraper → State Machine → Notification → Frontend** — each phase produces a demo-able artifact.

---

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         EXTERNAL INTERFACES                               │
│   ┌────────────┐  ┌────────────┐  ┌───────────┐  ┌──────────────────┐   │
│   │ Resy.com   │  │ OpenTable  │  │  Twilio / │  │   Next.js PWA    │   │
│   │ (Playwrt)  │  │  (httpx)   │  │  Resend / │  │   mise.place     │   │
│   │            │  │            │  │   VAPID   │  │                  │   │
│   └─────┬──────┘  └─────┬──────┘  └─────▲─────┘  └────────▲─────────┘   │
│         │ browser        │ GraphQL       │ HTTP            │ SSE/REST    │
├─────────┼────────────────┼───────────────┼─────────────────┼─────────────┤
│         │                │               │                 │             │
│   ┌─────▼────────────────▼─────┐   ┌─────┴────────┐   ┌────┴──────────┐ │
│   │   POLLING FLEET            │   │ NOTIFICATION │   │  API SERVER   │ │
│   │   ─ Playwright pool (4 ctx)│   │  CONSUMER    │   │  (FastAPI)    │ │
│   │   ─ httpx pool (N async)   │   │  (all chans) │   │  + SSE feed   │ │
│   │   Reads: Redis ZSET        │   │              │   │               │ │
│   │   Writes: availability.raw │   │              │   │               │ │
│   └──────────┬─────────────────┘   └──────▲───────┘   └──────▲────────┘ │
│              │ produces                   │ consumes          │         │
├──────────────┼────────────────────────────┼───────────────────┼─────────┤
│              │       KAFKA EVENT BUS      │                   │         │
│              ▼                            │                   │         │
│   ┌───────────────────┐   ┌──────────────────────┐   ┌─────────────┐   │
│   │ availability.raw  │──▶│  STATE MACHINE SVC   │──▶│ notif.queued│   │
│   │   (high volume)   │   │  ─ diff vs Redis SET │   │ notif.sent  │   │
│   │                   │   │  ─ schedule confirm  │   │ avail.events│   │
│   │ polls.completed   │   │  ─ emit on confirm   │   │ (for UI+DB) │   │
│   └───────────────────┘   └──────────┬───────────┘   └─────────────┘   │
│                                       │                                 │
├───────────────────────────────────────┼─────────────────────────────────┤
│                         STATE & PERSISTENCE                              │
│   ┌────────────────────────┐  ┌──────▼───────────┐  ┌───────────────┐   │
│   │  REDIS (Memorystore)   │  │  POSTGRES +       │  │  Object store │   │
│   │  ─ ZSET: poll schedule │  │  TIMESCALEDB      │  │  (optional)   │   │
│   │  ─ SET: curr avail     │  │  ─ restaurants    │  │  ─ poll HTML  │   │
│   │  ─ SETNX: idempotency  │  │  ─ watchlists     │  │    snapshots  │   │
│   │  ─ INCR: rate limits   │  │  ─ availability_  │  │    (debug)    │   │
│   │  ─ HASH: context state │  │    events (hyper) │  └───────────────┘   │
│   │                        │  │  ─ poll_log (hyp) │                      │
│   └────────────────────────┘  │  ─ notifications  │                      │
│                               └──────────────────┘                      │
└──────────────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Owns | Produces | Consumes | State it holds |
|-----------|------|----------|----------|----------------|
| **Polling Fleet** | HTTP/browser sessions, scrape logic, proxy rotation | `availability.raw`, `polls.completed` | Redis ZSET (next poll time) | Browser contexts (in-memory), poll metrics (Redis HASH) |
| **State Machine Service** | Availability diff, confirmation scheduling, event emission | `availability.events` | `availability.raw` | Redis SET per `(restaurant, date, party)`; Redis ZSET for confirmation-pending checks |
| **Notification Consumer** | Fanout to watchlists, channel dispatch, per-user rate limits | `notifications.queued` → sends to providers → `notifications.sent` | `availability.events`, `notifications.queued` (self-feed) | Redis SETNX idempotency keys; per-user rate-limit counters |
| **API Server (FastAPI)** | Watchlist CRUD, HMAC tokens, SSE live feed, public metrics | `watchlist.created` (optional) | `availability.events` (SSE passthrough), `notifications.sent` | None — stateless; reads Postgres directly |
| **Next.js Frontend** | UI, SSE consumer, heatmap rendering | (none) | SSE from API, REST from API | Browser local state only |

**Intentional merge for MVP:** The PRD proposes "Notification Dispatcher" + "Notification Workers" as separate services. At 2,500 notifications/day (~1.7/min) this split adds one Kafka topic and two deploy units with no observable benefit. Merge into a single **Notification Consumer** with per-channel async task groups. Split later only if a channel's latency budget is violated by head-of-line blocking — which at this volume, it won't be.

### Why this specific decomposition

- **Polling Fleet is one service, not one per source.** Resy (Playwright) and OpenTable (httpx) share the same scheduler, output topic, and observability surface. They differ only in the adapter implementation. One process with two adapter classes is simpler and lets you demonstrate the "adapter pattern for heterogeneous sources" story in the README.
- **State Machine Service is isolated.** This is the intellectually interesting component. Separating it from the poller means (a) you can replay `availability.raw` to regenerate `availability.events` during development — a killer demo capability, (b) poller restarts don't lose in-flight confirmation timers, (c) the diff logic is testable in isolation against fixture event streams.
- **API Server is stateless and frontend-adjacent.** It must *not* write to Kafka from user-triggered CRUD paths — watchlist creation goes straight to Postgres. Keep Kafka for system-internal events, HTTP for user-initiated.

---

## Recommended Project Structure

```
mise/
├── services/
│   ├── poller/                      # Polling Fleet
│   │   ├── __main__.py              # entrypoint, reads Redis ZSET
│   │   ├── scheduler.py             # ZSET pop + enqueue
│   │   ├── sources/
│   │   │   ├── base.py              # AvailabilitySource ABC
│   │   │   ├── resy/
│   │   │   │   ├── adapter.py       # Playwright impl
│   │   │   │   ├── context_pool.py  # 4-context asyncio pool
│   │   │   │   ├── fingerprint.py   # UA/viewport rotation
│   │   │   │   └── selectors.py     # DOM selectors (versioned)
│   │   │   └── opentable/
│   │   │       ├── adapter.py       # httpx impl
│   │   │       └── graphql.py       # query builder
│   │   ├── rate_limit.py            # token-bucket, Redis-backed
│   │   └── publisher.py             # → availability.raw
│   │
│   ├── state_machine/               # Diff + confirmation
│   │   ├── __main__.py              # Kafka consumer loop
│   │   ├── differ.py                # SET diff logic
│   │   ├── confirmation.py          # t+8s scheduler (Redis ZSET)
│   │   ├── emitter.py               # → availability.events
│   │   └── replay.py                # dev tool: replay raw → events
│   │
│   ├── notifier/                    # Merged dispatcher+workers
│   │   ├── __main__.py              # Kafka consumer, fans out
│   │   ├── fanout.py                # event → watchlist matches
│   │   ├── idempotency.py           # SETNX guard
│   │   ├── rate_limit.py            # per-user + per-channel caps
│   │   └── channels/
│   │       ├── base.py              # Channel ABC
│   │       ├── sms.py               # Twilio
│   │       ├── email.py             # Resend
│   │       └── push.py              # VAPID web push
│   │
│   └── api/                         # FastAPI + SSE
│       ├── main.py
│       ├── routers/
│       │   ├── watchlists.py        # CRUD with HMAC tokens
│       │   ├── restaurants.py       # heatmap data
│       │   ├── feed.py              # SSE /api/feed
│       │   └── admin.py             # metrics passthrough
│       ├── tokens.py                # HMAC-SHA256 mint/verify
│       └── sse.py                   # fanout from Kafka → browser
│
├── web/                             # Next.js 14 App Router
│   ├── app/
│   │   ├── page.tsx                 # home + live feed
│   │   ├── watch/[token]/page.tsx   # manage
│   │   ├── r/[slug]/page.tsx        # restaurant detail + heatmap
│   │   └── alert/[id]/page.tsx      # notification landing
│   └── components/
│
├── shared/                          # Cross-service Python lib
│   ├── events.py                    # Pydantic event schemas (single source of truth)
│   ├── kafka.py                     # producer/consumer factories
│   ├── redis_keys.py                # all key namespaces + TTL constants
│   ├── db.py                        # SQLAlchemy models
│   └── telemetry.py                 # OTel/Prometheus setup
│
├── migrations/                      # Alembic — includes Timescale hypertable DDL
├── ops/
│   ├── docker-compose.yml           # local: kafka+redis+postgres+all services
│   ├── grafana/                     # dashboards as code
│   └── terraform/                   # GCP infra (optional portfolio flex)
├── scripts/
│   ├── replay_raw.py                # feed availability.raw from fixtures
│   ├── seed_restaurants.py
│   └── bench_latency.py             # e2e latency harness
└── tests/
    ├── unit/                        # per-service
    ├── integration/                 # with testcontainers for kafka/redis
    └── e2e/                         # docker-compose driven
```

### Structure Rationale

- **`services/` is flat, not nested by layer.** Each service is deployable and testable independently. No "app/models" vs "app/routes" — services are the organizing unit.
- **`shared/events.py` is the contract.** Pydantic models for every Kafka event live in one file imported by every service. This is the single most valuable piece of shared code; everything else is local.
- **`shared/redis_keys.py` prevents drift.** Every Redis key pattern and its TTL is a constant. Reviewers can read one file to understand the entire Redis footprint.
- **`web/` is a separate top-level folder, not inside `services/`.** It's a different runtime (Node, not Python) and has its own dependency graph.
- **`scripts/replay_raw.py` is a portfolio signature.** The ability to replay raw events through the state machine is the clearest possible demonstration of the architecture's decoupled-ness. Make it a first-class script, not a test-only helper.

---

## Architectural Patterns

### Pattern 1: Distributed Poll Scheduler (Redis ZSET)

**What:** Each restaurant/source pair has a row in a Redis ZSET where `score = next_poll_epoch_ms`. Workers run `ZRANGEBYSCORE ... LIMIT 0 1` + `ZREM` atomically via a Lua script (or `BZPOPMIN` in Redis ≥5). On completion, the worker re-adds with `score = now + interval_ms + jitter`.

**When to use:** Any time you have N periodic jobs with independent cadences and want horizontal scale without a central scheduler process.

**Trade-offs:**
- + No scheduler process to fail; no single point of coordination
- + Trivially horizontally scalable — more workers = more throughput
- + Natural backpressure: if workers are slow, the ZSET grows and you see it
- − Must handle worker crashes with a visibility-timeout pattern (pop → process → mark done, or put back on timeout)
- − At MVP scale (50 jobs), this is architecturally overkill but *narratively essential*

**Example:**
```python
# Atomic pop-if-due via Lua
POP_IF_DUE = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local ready = redis.call('ZRANGEBYSCORE', key, '-inf', now, 'LIMIT', 0, 1)
if #ready == 0 then return nil end
redis.call('ZREM', key, ready[1])
-- move to 'in-flight' ZSET with visibility timeout
redis.call('ZADD', KEYS[2], now + tonumber(ARGV[2]), ready[1])
return ready[1]
"""
```

### Pattern 2: Raw/Refined Event Split with Replay

**What:** Two Kafka topics. `availability.raw` is noisy, high-volume, short-retention (24h). `availability.events` is validated, deduplicated, long-retention (7d). The State Machine is the only consumer of raw and the only producer of events. Raw retention is long enough that the state machine can be rewound and events regenerated without re-polling.

**When to use:** Any pipeline where (a) the raw signal is noisy, (b) refinement logic is likely to evolve, (c) you want to debug production incidents without replaying scrapes.

**Trade-offs:**
- + The pattern-detection model (48h rule etc.) can be retrained by replaying months of raw — you cannot do this if raw is thrown away
- + The state machine can be rewritten and back-filled
- + Decouples poll latency from event latency concerns
- − Two topics to monitor; consumer-lag across both is confusing without good dashboards
- − Retention costs roughly 2x

### Pattern 3: Confirmation Poll with State Machine Ownership

**What:** On a *transition* detected by diff (closed → open), the State Machine does **not** emit immediately. It writes a pending-confirmation record to Redis ZSET with score `now + 8s`, and a side-loop `ZRANGEBYSCORE` pops due confirmations and issues a priority re-poll through the same Polling Fleet (via `polls.requested` topic or direct Redis job). Only if the re-poll confirms the open slot does the state machine emit to `availability.events`.

**When to use:** Any scrape-driven change detection where the source has transient errors or race conditions during page loads (which for Resy is constant).

**Trade-offs:**
- + Cuts false-positive notifications dramatically — documented as the single biggest driver of user trust
- + Makes the 8s a tunable — per-source, per-restaurant if needed
- − Adds up to 8s to the detection→notification latency budget (p95 must account: poll_interval + 8s confirmation + emit + fanout + provider_latency ≤ 60s)
- − The confirmation poll is an additional load on Resy — must count against the 80 req/min budget

**Why t+8s specifically?** Short enough to stay within the 60s SLA, long enough that transient 5xx and rate-limited responses resolve. Consider making it configurable: t+5s for OpenTable (more stable API), t+10s for Resy (browser-based, flakier). **Recommendation: validate the 8s empirically by logging `raw_open_count_before_emit` — if it's usually ≥2, 8s is right; if it's often 1, raise it; if it's always ≥3, lower it.**

**Critical nuance:** the confirmation poll must be **issued by the state machine through the scheduler**, not directly through the worker. Otherwise it bypasses the global rate limiter and can contribute to bans during correlated event storms.

### Pattern 4: Two-Layer Idempotency

**What:** Idempotency guards at two distinct logical boundaries with distinct keys:

- **At event emission (Layer 1):** `SETNX event:{restaurant}:{date}:{party}:{slot_hash}:{state_transition}` with 20-min TTL. Prevents the state machine from emitting duplicate transitions during consumer redelivery or its own crash-restart within 20 minutes.
- **At notification dispatch (Layer 2):** `SETNX notif:{user_id}:{event_id}:{channel}` with 24h TTL. Prevents the Notification Consumer from sending duplicate notifications to the same user for the same event, even across consumer restarts or Kafka rebalance redelivery.

**When to use:** Every event-driven system. Two layers because duplicates originate from different sources (pipeline flapping vs consumer redelivery) and have different blast radii (duplicate event corrupts state; duplicate SMS costs money and annoys the user).

**Trade-offs:**
- + Defense in depth; either layer can fail open and the other catches it
- + TTLs are tuned to the specific duplicate window of that layer
- − Two places to reason about; must be unit-tested independently
- − Under Kafka rebalances that span 20 minutes (rare), Layer 1 can still produce a duplicate — Layer 2 must be the hard guarantee for user-visible actions

### Pattern 5: Playwright Context Pool (Not Browser Pool)

**What:** One Playwright `Browser` instance, N `BrowserContext`s (default N=4), each with its own cookie jar, storage, and fingerprint. An `asyncio.Semaphore(N)` gates acquisition. Contexts are long-lived (minutes to hours) and are recycled only on (a) detected ban, (b) cookie expiration, (c) periodic rotation (every 2h).

**When to use:** Scraping a single domain that needs session continuity (logged-in Resy) with concurrency ≥ 2.

**Trade-offs:**
- + One browser process (~200MB) vs N browsers (~N × 200MB) — 3-4x memory saving
- + Cookie jars are isolated per context — one ban doesn't taint the others
- + Recycling a context is O(ms), recycling a browser is O(seconds)
- − Browser crashes take down all contexts — mitigate with a warm-spare browser and a supervisor task
- − Playwright has occasional context leaks; add a `total_pages_served` counter per context and recycle at ~500

**Recommendation vs alternatives:**
- **Raw HTTP (httpx) for Resy** — attempted by many; fails because Resy's availability endpoints require a full browser fingerprint and session-level JS challenges. Not viable.
- **Single browser context, serial** — simple but can't meet the poll cadence (50 restaurants × 60s interval / 4s per poll = needs ≥4 parallel).
- **Browser-per-restaurant** — blows memory and provides no benefit over contexts.
- **Thread-per-context with sync Playwright** — viable but loses the asyncio cohesion of the rest of the codebase.

**The 4-context number is right for 50 restaurants at 60s interval.** Math: 50 polls × 2-4s per poll = 100-200s of work per minute; ÷ 60s = need 2-4 concurrent. 4 is a healthy ceiling. If you add a confirmation-poll queue, 4 still holds because confirmations are bursty, not sustained.

### Pattern 6: Server-Sent Events for Live Feed (not WebSocket)

**What:** API server subscribes to `availability.events` Kafka topic; each connected browser gets a long-lived HTTP response that pushes events as they arrive. Uses FastAPI's `StreamingResponse` with the `text/event-stream` content type.

**When to use:** One-directional server→client streaming of small events with reconnect semantics. Textbook use case.

**Trade-offs:**
- + HTTP-native — traverses proxies, CDNs, corporate firewalls
- + Auto-reconnect with `Last-Event-ID` is built into the browser
- + No frame protocol, no ping/pong — simpler than WebSocket
- − One-directional only (fine here; all client→server traffic is REST)
- − Each connection holds a Kafka consumer or a fanout queue — don't subscribe per-connection, use a single background consumer that multicasts

---

## Data Flow

### Happy-Path Event Flow (end-to-end)

```
 t=0s     Scheduler pops (restaurant=carbone, source=resy) from Redis ZSET
 t=0.1s   Polling Fleet worker acquires context, navigates, extracts slots
 t=2.5s   Worker produces availability.raw{ restaurant, date, party, slots: [7pm, 9pm] }
 t=2.6s   State Machine consumes raw; diffs against Redis SET
           → current state: {9pm}; new state: {7pm, 9pm}
           → transition detected: 7pm went OPEN
 t=2.7s   State Machine writes confirmation-pending ZSET entry (score=t+8s)
 t=10.7s  Confirmation worker pops; enqueues priority poll via Redis ZSET
 t=10.8s  Polling Fleet worker runs priority poll
 t=13.3s  availability.raw produced; State Machine consumes
           → diff confirms 7pm still open
           → SETNX event:carbone:2026-04-21:2:7pm:OPEN OK (no duplicate)
           → produces availability.events{ event_id, restaurant, date, party, slot, ts }
           → updates Redis SET with new state
 t=13.4s  Notification Consumer consumes event
           → Postgres query: watchlists matching (restaurant, date∈range, party≥n)
           → 12 matching watchlists fanned out
 t=13.5s  For each watchlist:
           → SETNX notif:{user}:{event_id}:{sms} OK
           → rate-limit check: user has sent 0/5 today, OK
           → produces notifications.queued{channel=sms, to=+1..., body=...}
 t=13.6s  Notification Consumer (same service, channel handler) picks queued
           → calls Twilio API
 t=15.2s  Twilio responds 201
           → produces notifications.sent{status=delivered}
           → Postgres insert into notifications table
 t=15.3s  API Server SSE stream pushes availability.events + notifications.sent
           → connected browsers render live-feed entry
```

**Total end-to-end: ~15s.** Budget is 60s. Confirmation adds 8s. Provider latency is 0.5-3s. Fanout is O(milliseconds) at 12 watchlists. Large safety margin.

### Failure-Path Flows

**1. Polling worker crashes mid-scrape.**
- Redis ZSET "in-flight" entry expires (visibility timeout 60s); job reappears on main ZSET; another worker picks it up.
- No `availability.raw` was emitted → state is unchanged → no event → no notification. Correct behavior.

**2. State Machine crashes between diff and emit.**
- Kafka consumer offset wasn't committed → on restart, reconsumes the `availability.raw` message.
- SETNX idempotency key was never set (crash was before emit) → re-diff, re-emit. No duplicate.
- Alternative crash point: emit succeeded but offset commit failed → SETNX key exists → emit skipped on redelivery. No duplicate.

**3. Notification Consumer crashes mid-fanout.**
- Kafka redelivers `availability.events` message.
- Re-fanout to the same 12 watchlists.
- Layer-2 SETNX `notif:{user}:{event_id}:{channel}` catches already-sent notifications; only the in-flight ones get retried.
- Failure window: if SETNX was set but Twilio call never completed, user misses the notification. Mitigation: only set SETNX after a confirmed 2xx from the provider. Trade-off accepted: prefer missed notification (user doesn't book; no harm) over duplicate notification (user acts twice; potential double booking attempt).

**4. Kafka is down.**
- Polling Fleet: producer retries with exponential backoff; after 30s, begins buffering to local disk (WAL-style). On Kafka recovery, drains buffer.
- State Machine & Notifier: consumers block; no data loss.
- API Server SSE: clients keep reconnecting but receive no events (show a "reconnecting..." banner).
- Recovery time: <1 min after Kafka returns.

**5. Resy bans our IP / session.**
- Playwright worker gets 403/429 → publishes `polls.completed{status=banned}` → marks context as poisoned → recycles context.
- Scheduler backs off that source (exponential, max 10 min) via Redis HASH state.
- Alert fires via Prometheus (`scrape_ban_total` > threshold).
- If all contexts poisoned → scheduler pauses Resy entirely, emits a system notification.

**6. Postgres read-replica lag during fanout.**
- Fanout queries watchlists. If a watchlist was *just* created, it may not be on the replica yet.
- Mitigation: fanout reads from primary, not replica. At 400 events/day × ~10 watchlist matches avg = 4000 reads/day, trivial for primary.

### State Management Summary

| State | Store | Key pattern | TTL | Owner |
|-------|-------|-------------|-----|-------|
| Current availability | Redis SET | `avail:{restaurant}:{date}:{party}` | None (overwritten) | State Machine |
| Poll schedule | Redis ZSET | `sched:polls` score=next_poll_ms | None | Scheduler |
| Confirmation pending | Redis ZSET | `confirm:pending` score=due_ms | 1h safety | State Machine |
| Idempotency (events) | Redis string | `event:{r}:{d}:{p}:{slot}:{txn}` | 20 min | State Machine |
| Idempotency (notifs) | Redis string | `notif:{user}:{event_id}:{chan}` | 24 h | Notifier |
| Rate limit (source) | Redis INCR+EXPIRE | `rate:resy:{min_bucket}` | 90 s | Scheduler/Worker |
| Rate limit (user notif) | Redis INCR+EXPIRE | `rate:notif:{user}:{day}` | 48 h | Notifier |
| Restaurant registry | Postgres | `restaurants` table | — | API |
| Watchlists | Postgres | `watchlists` table (HMAC token) | — | API |
| Event log (audit + pattern) | Postgres/Timescale | `availability_events` hypertable | 90 d | State Machine (via consumer) |
| Poll log | Postgres/Timescale | `poll_log` hypertable | 30 d | Polling Fleet |
| Notification history | Postgres | `notifications` table | — | Notifier |

**Critical principle: ephemeral state (fast, lossy) lives in Redis; authoritative state (slow, durable) lives in Postgres.** The rule is: if you restart Redis, the system must recover within 1 poll cycle. If you restart Postgres, user data must not be lost.

---

## Kafka vs Redis Streams at This Scale — Explicit Analysis

**The math:**
- 400 events/day → 0.005 events/sec average → negligible throughput requirement
- Peak burst: if a restaurant releases 20 slots at once × 50 restaurants all at NYE → 1000 events in a minute → 17/sec. Still trivial.
- Both Kafka and Redis Streams handle this with 6 orders of magnitude to spare.

**Decision criteria that actually matter at this volume:**

| Criterion | Kafka (self-hosted GCE) | Redis Streams (existing Memorystore) |
|-----------|-------------------------|--------------------------------------|
| Ops complexity | Broker + Zookeeper/KRaft; tune retention, segments, ISR | Already running for ZSET/SETNX; zero new infra |
| Cost | ~$30/mo GCE for n2-standard-2 | $0 incremental (same Redis instance) |
| 7-day retention | Native, cheap | Stream length caps; memory-bound |
| Consumer groups | First-class; rebalance built in | Supported via `XGROUP` |
| Replay | Seek by offset or timestamp | Seek by ID |
| Portfolio narrative | "Built an event pipeline on Kafka" reads strong | "Used Redis Streams" reads weaker |
| Debugging tools | kafkactl, Confluent UI, kafdrop | redis-cli, RedisInsight |
| Client ecosystem | aiokafka, confluent-kafka-python | redis-py (already used) |

**Recommendation: Keep Kafka. But be honest in the README.** Write a section called "Why Kafka for 400 events/day?" that explicitly says: "the load does not require Kafka; we chose it to build and demonstrate the consumer-group, replay, and retention patterns that matter at 10× and 100× scale. Redis Streams would have been the pragmatic choice at this volume." This earns more engineering respect than silently over-engineering.

**Concrete Kafka setup at this scale:**
- 1 broker, KRaft mode (no Zookeeper). Single GCE n2-standard-2 (~$30/mo).
- 3-5 topics total, each with 1 partition. Don't pre-shard; you don't have the volume.
- Replication factor 1 (it's a portfolio project; full durability isn't worth 3x cost). Document this decision.
- Retention: `availability.raw` 24h, `availability.events` 7d, `notifications.*` 30d (for audit/debug).
- Acknowledge: "at 1 partition per topic, we have no parallelism within a topic; consumers are serialized." At this volume that's fine. Add partitions only if consumer lag appears.

**One scenario where Kafka is wrong even for portfolio:** if deployment ops overhead threatens the 8-week timeline. If in week 4 Kafka is still causing deploy pain, cut to Redis Streams. Shipping beats narrative.

---

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| **MVP (50 restaurants, 400 events/day)** | As designed. Single Kafka broker, single Redis, single Postgres. One instance per service. |
| **10× (500 restaurants, 4k events/day)** | Add poller replicas (Playwright contexts per instance × instances). Partition `availability.raw` by restaurant_id. Add Redis read replica for poll scheduler. Postgres primary is still fine. |
| **100× (5k restaurants, 40k events/day, 250k notifs/day)** | Split Notification Consumer back into Dispatcher + per-channel Workers (channel-level backpressure matters now). Move to Kafka cluster (3 brokers, RF=3). Postgres read replica for API reads. Consider separating the SSE fanout into its own service. Introduce residential proxy pool for scraping. |
| **1000×+** | Regional sharding by restaurant geography; per-region Kafka clusters; CDC-based replication of watchlists to regional stores. At this point, this system is a business, not a portfolio. |

### Scaling Priorities (what breaks first)

1. **First bottleneck: Resy rate limiting.** At 80 req/min cap, you can poll ~50 restaurants × 60s = enough, but adding confirmation polls eats 10-20% of the budget. Adding restaurants past ~100 requires residential proxies.
2. **Second bottleneck: Playwright memory.** At 4 contexts you're at ~500MB. Doubling restaurants means doubling contexts (bigger VM or split pollers across machines).
3. **Third bottleneck: SSE connection count.** FastAPI + uvicorn can hold ~10k concurrent SSE connections per worker. At MVP you'll have <100 concurrent; this is not a concern until viral moment.
4. **Fourth: Postgres fanout query.** At 100k watchlists, `WHERE restaurant_id=? AND party<=?` needs indexes; at 1M it needs partitioning.

**Do not pre-optimize any of these.** Instrument them (Prometheus), set SLO alerts, fix when breached.

---

## Anti-Patterns

### Anti-Pattern 1: Emitting events from the poller directly

**What people do:** Polling worker compares to last-known state in local memory and emits `availability.events` when it sees a change.
**Why it's wrong:** State is lost on restart; horizontal scale breaks (two workers disagree about current state); diff logic is coupled to scrape logic and can't be replayed; confirmation polls can't be coordinated.
**Do this instead:** Poller emits only raw facts. A separate stateful service owns the "what changed" logic.

### Anti-Pattern 2: Using the same Redis key for state and idempotency

**What people do:** A single `restaurant:{id}:last_seen` key used for both "what's currently open" and "have I notified about this."
**Why it's wrong:** Conflates two lifecycles. Notification TTL (24h) is not the same as state TTL (none). Clearing state to debug breaks idempotency.
**Do this instead:** Distinct key namespaces with distinct TTLs, documented in `shared/redis_keys.py`.

### Anti-Pattern 3: Confirmation poll in the same consumer as the initial poll

**What people do:** State Machine notices a change, blocks for 8s with `await asyncio.sleep(8)`, re-polls inline, then emits.
**Why it's wrong:** (a) Blocks the consumer; (b) bypasses the global rate limiter; (c) loses the confirmation if the consumer crashes during sleep; (d) can't batch confirmations under burst.
**Do this instead:** Write confirmation-pending to Redis ZSET; a separate loop dequeues due confirmations and issues them through the normal scheduler path.

### Anti-Pattern 4: SSE consumer per Kafka subscription

**What people do:** Every connected browser opens a new Kafka consumer inside the API process.
**Why it's wrong:** Consumer-group rebalances every connect/disconnect; duplicate processing; memory per connection.
**Do this instead:** One background Kafka consumer per API process; in-memory multicast (asyncio Queue per connection or `anyio` broadcast) to connected SSE clients.

### Anti-Pattern 5: Watchlist fanout in the producer

**What people do:** State Machine queries watchlists when emitting the event, produces one Kafka message per (event, watchlist).
**Why it's wrong:** Couples the event pipeline to user-model changes; fanout fan-out is blocking; one slow Postgres query stalls all events.
**Do this instead:** `availability.events` is user-agnostic. The Notification Consumer owns fanout. Events are "what happened"; notifications are "who we tell."

### Anti-Pattern 6: Per-restaurant polling process

**What people do:** Spawn a worker process per restaurant so each has its own loop.
**Why it's wrong:** 50 processes for 50 restaurants is absurd resource use; doesn't generalize; loses the scheduler narrative.
**Do this instead:** Fixed worker pool, Redis ZSET as shared queue. Workers are interchangeable.

### Anti-Pattern 7: Storing Resy session cookies in Postgres

**What people do:** Persist browser session cookies to DB for reuse across restarts.
**Why it's wrong:** High-value secrets at rest; rotation nightmare; Resy ToS risk amplified.
**Do this instead:** Cookies live in Playwright context memory only. On restart, re-login via Playwright automation using credentials from env / secret manager. Accept the 30s startup cost.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| **Resy** | Playwright (Chromium), persistent contexts, manually-created accounts, fingerprint rotation | No API; browser is the only way. Treat selectors as versioned; build a weekly `test_selectors.py` smoke test. |
| **OpenTable** | httpx async to widget GraphQL endpoint | Semi-public. Requires `restaurantId` and `partySize`. Respect `Retry-After`. Rate limit to 1 req/sec per restaurant. |
| **Twilio (SMS)** | REST API with retries on 5xx, 429 | ~$0.008/msg; ~$20/mo at 2500 msg/day. Handle TOLL-FREE verification in advance (10DLC registration takes days). |
| **Resend (email)** | REST API, async | Free tier 3000/mo; fits MVP. Implement transactional template in Resend UI, reference by ID. |
| **VAPID Web Push** | `pywebpush` lib over HTTPS to browser push services | No provider account needed; generate VAPID keypair once, store public in frontend JS, private in secret manager. Handle 410 (subscription dead) by deleting from Postgres. |
| **GCP (deploy)** | Cloud Run for stateless services; GCE for Kafka; Cloud SQL for Postgres+Timescale; Memorystore for Redis | Cloud Run auto-scales stateless services to zero (API, Notifier). Polling Fleet must be always-on — deploy to GCE managed instance group, not Cloud Run. |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| **Polling Fleet → State Machine** | Kafka `availability.raw` | Fire-and-forget; at-least-once. Raw payload includes poll_id for traceability. |
| **State Machine → Notification Consumer** | Kafka `availability.events` | At-least-once; idempotency guard at consumer side. Event payload is user-agnostic. |
| **State Machine → Polling Fleet (confirmation)** | Redis ZSET `sched:polls` with priority flag | Do NOT use Kafka for this; latency budget is too tight and the scheduler already owns poll issuance. |
| **Notification Consumer → API Server (for live feed)** | Kafka `notifications.sent` | API subscribes read-only and broadcasts to SSE. |
| **API Server → Postgres** | SQLAlchemy async | Primary only for fanout reads; read-replica OK for read-heavy endpoints like heatmap at post-MVP scale. |
| **Frontend → API** | HTTPS REST for CRUD; SSE for live feed | No GraphQL (unnecessary complexity); no WebSocket (one-directional suffices). |
| **All services → Redis** | redis-py async | Single logical instance; all keys namespaced. Connection pool per service, ~10 connections. |
| **All services → Prometheus** | `/metrics` endpoint via `prometheus-client` | Scraped by Grafana Cloud agent. Each service exposes its own; global dashboard aggregates. |

---

## Build Order (Dependency-Ordered)

This feeds directly into roadmap phase structure. Each phase produces a demo-able artifact.

### Phase 1: Foundation + Single-Source Polling (Weeks 1–2)
**Build:**
1. Repo skeleton, shared event schemas, docker-compose with Kafka+Redis+Postgres
2. Polling Fleet with **OpenTable only** (httpx — simpler, no Playwright infra yet)
3. Redis ZSET scheduler with 10 seed restaurants
4. Raw event emission to Kafka
5. Basic Prometheus metrics

**Demo:** Kafka topic shows `availability.raw` messages flowing at configured cadence. `docker compose logs poller` is boring (good).

**Why first:** No interesting logic yet — just the spine. Proves the scheduler and Kafka plumbing. Lets later phases assume raw events exist.

**Cut line if behind schedule:** None — this is the floor.

### Phase 2: State Machine + Confirmation Logic (Week 3)
**Build:**
1. State Machine Service consuming `availability.raw`
2. Diff against Redis SET
3. Confirmation ZSET + side-loop
4. Idempotency Layer 1 (SETNX)
5. Emit `availability.events`
6. Replay script (`scripts/replay_raw.py`)

**Demo:** Inject fake raw events via replay script; show refined events emitted correctly, including deduplication of transient flaps. Show a chaos test where consumer is killed mid-process and no duplicates result.

**Why second:** Requires raw events; nothing else can be built before this.

**Cut line:** Can ship with confirmation-poll disabled (configurable); turn on once baseline works. Idempotency cannot be cut.

### Phase 3: Resy + Playwright Fleet (Week 4)
**Build:**
1. Playwright context pool (4 contexts, 1 browser)
2. Resy adapter: login flow, availability scrape, fingerprint rotation
3. Ban detection + backoff
4. Priority re-poll path for confirmations
5. Extend rate limiter to enforce 80 req/min Resy cap

**Demo:** Watch 10 Resy restaurants polled; show Grafana panel with per-context latency; simulate 429 response and show context recycle.

**Why third:** Playwright is the highest-risk component (external changes, bans). Build after foundation is solid so a Playwright disaster doesn't block other progress. Could run in parallel with Phase 4 if second engineer available.

**Cut line:** Can ship with 2 contexts instead of 4 if memory-constrained. Can ship without fingerprint rotation for week-1 launch; add post-launch.

### Phase 4: Notification Pipeline (Week 5)
**Build:**
1. Notification Consumer skeleton
2. Watchlist fanout (Postgres query)
3. Idempotency Layer 2 (SETNX per-user-per-event-per-channel)
4. Email channel (Resend)
5. SMS channel (Twilio) — after 10DLC registration submitted in Phase 1
6. Web Push (VAPID) — subscribe flow in frontend stubbed

**Demo:** Inject a synthetic `availability.events`; show matching watchlists receive notifications within latency budget; show deduplication under consumer restart.

**Why fourth:** Requires events (Phase 2). Independent of source (OpenTable vs Resy).

**Cut line:** MVP can ship with Email + Push only; defer SMS to post-launch if Twilio verification is slow. Single-channel MVP is defensible.

### Phase 5: API Server + Watchlist CRUD + SSE (Week 6)
**Build:**
1. FastAPI with HMAC token mint/verify
2. Watchlist CRUD endpoints
3. Postgres schema + migrations (watchlists, restaurants, events mirror)
4. SSE endpoint `/api/feed` with Kafka consumer multicast
5. Public `/api/metrics` read-only endpoint

**Demo:** curl the API to create a watchlist; trigger an event; see notification sent; see SSE event on a connected curl.

**Why fifth:** Decoupled from pipeline (pipeline emits regardless of whether API exists). Could move earlier if frontend work is starting in parallel.

**Cut line:** Can ship without SSE initially; frontend polls REST every 10s. SSE is a quality-of-life upgrade.

### Phase 6: Frontend PWA (Week 7)
**Build:**
1. Next.js 14 App Router scaffold
2. Home page with live feed (SSE consumer)
3. Watch setup flow (email/phone, restaurant picker, date range)
4. Restaurant detail + heatmap (from Timescale pattern query)
5. Manage page (HMAC-token URL)
6. Alert landing page

**Demo:** Full user flow — land on mise.place, watch Carbone for Friday night, receive email/SMS/push when slot opens, click through to booking.

**Why sixth:** Requires the API. All pipeline pieces are already live and tested; the frontend is a client of a stable backend.

**Cut line:** Heatmap can be static placeholder at launch; pattern model lives below. PWA install prompt can be added post-launch.

### Phase 7: Deploy + Observability + Legal README (Week 8)
**Build:**
1. GCP deploy: Cloud Run services, GCE for Kafka, Cloud SQL, Memorystore
2. Grafana Cloud dashboards (public read-only link)
3. Better Uptime monitors
4. README: architecture section, ethical-scraping + legal section, replay walkthrough
5. Public-metrics page linked from README

**Demo:** Live at mise.place. Public dashboard at mise.place/metrics. README is the hiring artifact.

**Cut line:** Deploy to GCP can degrade to fly.io / Railway / Render if GCP proves expensive or slow. The architecture is portable.

### Parallelization Opportunities

- **Phase 3 (Resy) and Phase 4 (Notifier)** can run in parallel if two people. Notifier consumes from Kafka topic that Phase 2 already emits; doesn't need Resy.
- **Phase 5 (API) and Phase 6 (Frontend)** can start in parallel once Phase 5 has stable CRUD endpoints, even before SSE is done.
- **Phase 7 (Deploy)** parts can begin in Week 5 — provision Cloud SQL, Memorystore, Kafka VM early so DNS and secrets are ready.

### MVP Cut Line (hard)

**Must ship:**
- OpenTable polling (1 source)
- State machine + confirmation + idempotency
- Email notifications
- Watchlist CRUD (HMAC tokens)
- Basic frontend with watch setup and confirmation

**Can defer:**
- Resy (if Playwright disaster → launch OpenTable-only, document clearly)
- SMS (if 10DLC slow)
- Web Push (nice-to-have; defer if browsers misbehave)
- Heatmap (placeholder OK)
- Pattern detection model (this is inherently post-launch; needs data)
- Admin page beyond Grafana
- PWA install prompt
- GCP deploy (can ship on fly.io/Railway for cheaper/faster)

**Truly post-MVP:**
- Pattern detection model (needs 2-4 weeks of data)
- Tock integration
- User accounts
- Group watchlists

---

## Portfolio-Narrative Callouts (Where to Over-Engineer)

The product is 30% for users, 70% for the senior engineer reading your GitHub. These are places where the "right" engineering choice diverges from the "right" portfolio choice, and the portfolio choice wins:

1. **Kafka over Redis Streams** — narrative value of Kafka + replay + consumer groups outweighs the ops cost. Already recommended; document the trade-off explicitly in README.
2. **Explicit State Machine service** — could be a function inside the poller; making it a service shows you understand stateful event processing. Worth the deploy unit.
3. **Two-layer idempotency** — one layer would be enough at this volume. Two layers demonstrates you understand that duplicates have multiple origins.
4. **Prometheus + Grafana with public dashboard** — most portfolio projects don't have observability. Having a live, linkable Grafana dashboard is a differentiator.
5. **Replay script as a first-class tool** — documents the architecture in code; reviewers skim `scripts/` and immediately understand the pipeline.
6. **README legal/ethical section** — explicit rate-limit reasoning, robots.txt stance, ToS analysis. This is where portfolio readers go from "interesting project" to "this person is senior."
7. **A `docs/ARCHITECTURE.md` in the repo** derived from this research — many portfolio projects lack architecture docs. Having one signals the habit.

## Where to Simplify (Avoid These Over-Engineering Traps)

1. **Do not split Dispatcher and Workers.** One Notification Consumer with per-channel async handlers is enough. Splitting is a pre-optimization.
2. **Do not add a dead-letter-queue topic at MVP.** Instead, log failures to Postgres `failed_events` table with retry counter. DLQ topic is ceremony without benefit at this volume.
3. **Do not build a schema registry.** Pydantic models in `shared/events.py` are the schema registry. Add Confluent Schema Registry only when you have a second language consuming events.
4. **Do not use Celery.** You have Redis for scheduling, Kafka for pipeline; Celery is redundant and hides the interesting parts behind a framework.
5. **Do not build a plugin system for sources.** Two sources is not enough sources to justify a plugin architecture. An abstract base class in `sources/base.py` is the right level.
6. **Do not implement WebSocket.** SSE is sufficient and simpler. WebSocket requires a pinger, frame protocol, and reconnect logic you'll write yourself.
7. **Do not build custom Playwright orchestration.** Use `asyncio.Semaphore` + a list of pre-created contexts. Don't write a "pool framework."
8. **Do not Dockerize each service for local dev.** A single docker-compose with mounted volumes and hot-reload is enough for dev. Full multi-stage Dockerfiles are for production only.

---

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Resy DOM selectors change weekly | HIGH | Outages | Weekly selector smoke test; fail loud via Sentry; maintain selector version map |
| Resy ban on all pooled accounts simultaneously | MEDIUM | All Resy polling down | Rotate accounts; stagger logins; have 2 backup accounts ready; pause on >50% ban rate |
| Playwright memory leak → OOM | MEDIUM | Polling stops | Per-context page counter; recycle at 500 pages; healthcheck on memory; restart on >1.5GB |
| Kafka GCE instance dies | LOW | Full pipeline stops | Document restore procedure; RF=1 accepts ~5min recovery; dashboard alerts |
| Twilio 10DLC registration delayed | MEDIUM | No SMS at launch | Submit Week 1; ship email+push without SMS; add SMS as update |
| Confirmation-poll logic has race condition | MEDIUM | Missed or duplicate events | Unit-test state machine exhaustively with fixture traces; use replay script for regression |
| Postgres fanout query slow as watchlists grow | LOW (at MVP) | Notification latency | Index `(restaurant_id, party_size, date_range)`; monitor p95 query time |
| SSE connection leak in browsers | LOW | Memory bloat in API server | Heartbeat every 15s; close on missed heartbeat; max connections cap |
| 8s confirmation delay + poll_interval breaks 60s SLA | LOW | SLA miss | Budget: 10s poll + 8s confirm + 5s scrape + 5s notify = 28s, well under 60s. Monitor in production. |

---

## Sources

- [Redis Streams vs Kafka: A Detailed Comparison](https://oneuptime.com/blog/post/2026-03-31-redis-streams-vs-kafka-detailed-comparison/view)
- [Real-Time Event Streaming: Kafka vs Redis Streams vs NATS in 2026](https://dev.to/young_gao/real-time-event-streaming-kafka-vs-redis-streams-vs-nats-in-2026-34o1)
- [Beyond the Hype: Why We Chose Redis Streams Over Kafka](https://dev.to/mtk3d/beyond-the-hype-why-we-chose-redis-streams-over-kafka-for-our-microservices-dmc)
- [Playwright Browser Contexts — Official Docs](https://playwright.dev/python/docs/api/class-playwright)
- [playwright-pool: Sophisticated Async Browser Pool](https://github.com/tgscan/playwright-pool)
- [Granitosaurus playwright-pool reference implementation](https://github.com/Granitosaurus/playwright-pool)
- [Idempotent message processing — Redis Streams docs](https://redis.io/docs/latest/develop/data-types/streams/idempotency/)
- [How to Handle Idempotency in Microservices](https://oneuptime.com/blog/post/2026-01-24-idempotency-in-microservices/view)
- [Notification Deduplication — Sohil Ladhani](https://sohilladhani.com/blog/post/2026-04-12-notification-deduplication/)
- [Build 5 Rate Limiters with Redis](https://redis.io/tutorials/howtos/ratelimiting/)
- [Web Scraping Architecture Patterns: From Prototype to Production (2026)](https://use-apify.com/blog/web-scraping-architecture-patterns)
- [Guide to Distributed Web Crawling](https://brightdata.com/blog/web-data/distributed-web-crawling)
- [Microservices Interservice Communication with Redis Streams](https://redis.io/tutorials/howtos/solutions/microservices/interservice-communication/)
- [How to Design Event-Driven Architecture for Microservices](https://oneuptime.com/blog/post/2026-02-20-event-driven-architecture-guide/view)

---
*Architecture research for: Real-time restaurant availability detection + notification pipeline*
*Researched: 2026-04-20*
