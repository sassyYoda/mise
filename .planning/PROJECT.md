# Mise en Place

## What This Is

Mise en Place is a restaurant reservation intelligence platform that continuously monitors Resy and OpenTable for cancellation availability at hard-to-book NYC restaurants, detects statistical patterns in when slots release, and delivers sub-minute push/SMS/email notifications to users watching for a specific table. It is built as a distributed real-time event detection system — a portfolio-grade systems engineering project as much as a consumer product.

## Core Value

When a coveted table opens, the watching user is notified fast enough to actually book it — p95 detection-to-notification latency ≤ 60 seconds. Everything else is secondary; if this fails, the product has no reason to exist.

## Requirements

### Validated

<!-- Shipped and confirmed valuable. -->

- ✓ Stateful availability diff engine with confirmation polls and idempotency guards — Phase 2 (tri-state diff, t+8s ZSET-expedited confirmation, `SET NX EX` Layer-1 claims, byte-identical `scripts/replay_raw.py`; 254 unit / 62 integration tests)

### Active

<!-- Current scope. Building toward these. See REQUIREMENTS.md for detail. -->

- [ ] Continuous polling of Resy (Playwright) and OpenTable (HTTP) across ≥ 50 NYC restaurants
- [ ] Kafka-based event pipeline (availability.raw → availability.events → notifications.queued → notifications.sent)
- [ ] Multi-channel notification delivery: email (Resend), SMS (Twilio), Web Push (VAPID)
- [ ] Watchlist CRUD with token-based, auth-free management links
- [ ] Statistical pattern detection model (48h rule, inventory-load day, cancellation-peak, duration)
- [ ] Next.js 15 PWA: home + live SSE activity feed, watch setup, restaurant detail with heatmap, manage, alert landing
- [ ] Admin page + Prometheus/Grafana dashboard + public read-only metrics link
- [ ] Deployed to mise.place on GCP (Cloud Run + Cloud SQL/TimescaleDB + Memorystore Redis + self-hosted Kafka on GCE)

### Out of Scope

<!-- Explicit boundaries. Reasoning included to prevent re-adding. -->

- **Automated booking on user's behalf** — requires storing payment credentials; legal complexity and ToS risk
- **Coverage outside New York City** — deferred to v2 after MVP validation
- **Native iOS / Android apps** — PWA covers mobile at MVP
- **Tock integration** — lower NYC coverage than Resy/OpenTable; deferred to v2
- **Group / team accounts with shared watchlists** — out of scope for v1
- **Monetization / paid tiers** — free at MVP; freemium planned for v2
- **Automated Resy account creation** — accounts for polling are created manually to avoid ToS violations on account automation

## Context

- **Domain:** Hospitality / consumer tech, with a strong systems-engineering portfolio angle. The tertiary persona is a senior engineer reviewing the repo — architecture, Grafana dashboard, and README legal/rate-limit reasoning matter as much as the consumer UX.
- **Market gap:** Existing tools either charge to resell reservations (Appointment Trader, Dorsia) or notify only for newly released future inventory (Resy Wishlist). None offer continuous monitoring + pattern-based predictive alerts for organic cancellations.
- **Scraping posture:** Resy has no public availability API — Playwright browser pool with pre-authenticated contexts, fingerprint rotation, and ≤ 80 req/min total cap. OpenTable uses the semi-public widget GraphQL endpoint with httpx async — no scraping required. All polled data is publicly visible to any anonymous browser user.
- **Release patterns the system exploits:** cancellation windows, 48h-before-service releases, inventory load days, party-size adjustments, no-show releases, failed credit-card-hold releases.
- **Scale at MVP:** ~50 restaurants, ~400 availability events/day, ~2,500 notifications/day — trivially within Resend/Twilio free-tier economics.

## Constraints

- **Timeline:** MVP in 8 weeks from kick-off — hard target for portfolio launch
- **Tech stack:** Python 3.12 + asyncio + Playwright for backend services; FastAPI + Next.js 14 App Router for API/frontend; Kafka for event pipeline; Redis for state + scheduler; PostgreSQL + TimescaleDB for persistent state and time-series data
- **Performance:** p95 detection-to-notification ≤ 60s; SMS ≤ 10s; Web Push ≤ 5s; poll success rate ≥ 99%; uptime ≥ 99.5%
- **Ethical scraping:** Max 80 Resy req/min total across all contexts; ≥ 45s per-restaurant per-context interval; robots.txt respected; only public data; no booking automation; no account creation automation
- **Security:** Phone numbers encrypted at rest (AES-256-GCM via pgcrypto); HMAC-SHA256 management tokens, rotated monthly; no payment data stored; Resy session cookies ephemeral, never DB-persisted
- **Budget:** Low-cost MVP — free tiers where possible (Resend, Sentry, Grafana Cloud, Better Uptime, Vercel); paid line items ~$30/mo Kafka GCE + ~$35/mo Redis + ~$20/mo Twilio estimated + ~$10/mo residential proxy if needed
- **Legal:** README must include a clear rate-limiting and legal-analysis section; no auth bypass, no PII access, public-data-only; Tock deferred partly for ToS-risk management

## Key Decisions

<!-- Decisions that constrain future work. Add throughout the project lifecycle. -->

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Kafka (self-hosted on GCE) over Redis pub/sub | Durable replay (7-day retention), consumer group semantics, audit trail for pattern model and debugging | — Pending |
| Playwright over raw HTTP for Resy | Resy has no public availability API; browser session w/ fingerprint rotation is the realistic path | — Pending |
| httpx async over Playwright for OpenTable | OpenTable widget GraphQL endpoint is semi-public and does not need auth for availability checks | — Pending |
| Redis ZSET distributed poll scheduler | Avoids central scheduler bottleneck; workers pop jobs when scheduled time arrives | — Pending |
| Confirmation poll at t+8s before emitting event | Eliminates transient API errors as false-positive notifications | — Pending |
| Redis SETNX idempotency guard with 20-min TTL | Prevents duplicate notifications across consecutive polls and consumer redelivery | — Pending |
| No user accounts at MVP; HMAC management tokens | Removes onboarding friction for the core "table opened" flow | — Pending |
| TimescaleDB for availability_events + poll_log | Hypertables optimize time-series queries for heatmap and pattern model | — Pending |
| GCP Cloud Run + Cloud SQL + Memorystore | Managed services minimize ops load; free/low tiers at MVP scale | — Pending |
| PWA at MVP, not native apps | Covers iOS/Android mobile with Web Push; ships faster | — Pending |
| Stream-based confirmation: the state machine never calls a source; it expedites the restaurant's next poll to t+8s via `ZADD LT` and confirms on the next `availability.raw` | Keeps the diff engine pure so replay of the raw log is byte-identical (STATE-06) | ✓ Phase 2 |
| Deterministic `event_id` (uuid5) and `produced_at` = confirming poll timestamp | Replay determinism; downstream Layer-2 dedupe by event_id absorbs at-least-once redelivery | ✓ Phase 2 |
| `restaurant_id` on the wire is the platform id; `(source, platform_id)` is the join key to `restaurants` | Matches `poll_log`; no DB lookups in the engine | ✓ Phase 2 |
| Layer-1 claim key `event:{rid}:{date}:{party}:{slot_key}:{token}` (percent-escaped) | Two seat types can share one booking token (found by code review) | ✓ Phase 2 |
| Autonomous run executes plans sequentially on the main tree (`use_worktrees=false`) | Docker-backed tests contend under parallel worktrees; no human to resolve merges | ✓ Phase 2 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-09-05 after Phase 2*
