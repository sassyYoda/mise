# Pitfalls Research

**Domain:** Real-time restaurant reservation scraping + event pipeline + multi-channel notifications (portfolio MVP)
**Researched:** 2026-04-20
**Confidence:** HIGH (core-infra pitfalls verified against official docs + multiple primary sources; LOW on Resy-specific bot-detection specifics — single-source)

---

## Critical Pitfalls

These are the genuinely risky ones. If the roadmap does not address these, the MVP either fails the ≤ 60s latency target, gets IP-banned within hours, floods users with false-positive alerts, or ships a demo that deadlocks on the reviewer's laptop.

### Pitfall 1: Playwright Browser-Context Leak Killing the Scraper

**What goes wrong:**
Long-running Playwright services accumulate orphaned `BrowserContext` and `Page` objects. RSS climbs steadily over hours/days. Eventually the OOM killer reaps the worker mid-poll, and `/dev/shm` exhaustion (default 64 MB in Docker) crashes Chromium while leaving zombie processes attached to the Python parent. Polls start silently failing; the 99% success-rate SLO breaches; the heatmap/pattern model trains on gap-ridden data.

**Why it happens:**
The textbook pattern is `context = await browser.new_context(); page = await context.new_page(); ...` in a loop — and missing `await context.close()` in `finally`. `page.on(...)` and `page.route(...)` handlers hold strong references that the GC cannot collect even if you close the page. Issues [#286](https://github.com/microsoft/playwright-python/issues/286), [#1754](https://github.com/microsoft/playwright-python/issues/1754), [#1602](https://github.com/microsoft/playwright-python/issues/1602), and [#2511](https://github.com/microsoft/playwright-python/issues/2511) in `playwright-python` are all variants of this. In a polling service running 24/7 the leak surface is enormous.

**How to avoid:**
- One context per poll, wrapped in `async with browser.new_context(...)` or `try/finally` with `await context.close()` — never reuse a context across polls for long-lived sessions (use auth state file + fresh context instead).
- Detach event handlers before closing (`page.remove_listener(...)`).
- Recycle the entire browser process every N polls (e.g., 500) — the cheapest reliable defense.
- Run Chromium with `--disable-dev-shm-usage` in Docker, or mount a larger `/dev/shm` (≥ 512 MB).
- Wrap Playwright workers with a supervisor that reaps zombie Chromium PIDs (`process.children(recursive=True)` on the worker PID).

**Warning signs:**
RSS of the scraper worker climbing monotonically in Grafana. Chromium PID count > N_contexts + 1. `/dev/shm` usage at >80%. Increasing poll latency over 6-12h uptime.

**Phase to address:** Scraping Foundations phase (Phase 2 or 3). Memory-leak soak test (12h continuous run) is a gating criterion before entering the event-pipeline phase.

**Severity:** **Critical** — a leaking scraper invalidates every downstream claim (latency SLO, pattern model data, uptime).

---

### Pitfall 2: Resy Bot Detection & IP Ban Mid-Demo

**What goes wrong:**
Resy's anti-bot stack (TLS fingerprint, canvas/WebGL fingerprint, timing signatures, request-shape anomaly detection) flags the Playwright fleet. Polling accounts get softbanned (CAPTCHAs, silent empty responses) or the source IP gets blocked. The worst failure mode is a silent soft-ban: polls succeed with `200 OK` but return sanitized or stale availability — so the diff engine generates zero events and the portfolio demo looks dead.

**Why it happens:**
Common mistakes:
- Using `playwright` defaults (detectable by `navigator.webdriver`, missing plugins, unusual timings).
- Single datacenter IP (GCE egress) with no residential backing — datacenter IPs are first-class block signals.
- Polling at exactly constant intervals (e.g., every 45.0s) — humans have jitter.
- Reusing the same browser context indefinitely — cookies age, timing profile becomes non-human.
- Ignoring soft-ban (diff still empty, but you assume "no cancellations today").

**How to avoid:**
- `playwright-stealth` or `rebrowser-patches` to patch the obvious `navigator.webdriver` and CDP detection vectors.
- Jitter poll intervals: `45 + random.uniform(0, 15)` seconds per context.
- Rotate fingerprints per account (viewport, UA, Accept-Language, timezone) — keep them stable *per account* across polls; rotate *between accounts*.
- One residential proxy ($10/mo per PROJECT.md budget) for Resy traffic — not datacenter IPs. Document this in the README legal section.
- Soft-ban detection: compare raw-response signature (page size, response-header set, presence of known selectors) against a rolling baseline. Alert if an account's response signature drifts even though status = 200.
- Hard cap at 80 req/min total (already in PROJECT.md constraints) and publish it in the README as a pre-emptive good-faith gesture.

**Warning signs:**
Sudden drop to zero events/day without corresponding drop in poll success. Response sizes for a specific account diverging from peers. CAPTCHAs rendering in headless screenshots (run a nightly sentinel screenshot job).

**Phase to address:** Scraping Foundations phase. A "soft-ban canary" metric must exist before the Event Pipeline phase.

**Severity:** **Critical** — defines whether the product works at all, and defines the legal/ToS risk surface.

---

### Pitfall 3: Stateful Diff Engine Generating False Positives (Flapping)

**What goes wrong:**
A transient Resy error, a TCP reset, or a retry storm temporarily "disappears" a table that is still available. The diff engine fires a `table_opened` event on the *next* successful poll, a user gets woken at 3 AM about a reservation that was never actually new, and the product credibility is destroyed. Or the opposite: a table flaps available/unavailable across consecutive polls (party-size recount, load-balancer cache), producing duplicate notifications.

**Why it happens:**
Naive diff: `if prev_state != curr_state: emit_event`. No distinction between "restaurant responded with availability=[]" and "restaurant responded with error/timeout". No cooldown between state changes for the same slot.

**How to avoid:**
- **Confirmation poll at t+8s** (already in PROJECT.md Key Decisions) — before emitting, re-poll once; only emit if the new state is confirmed. This is the single most important correctness mechanism in the pipeline.
- **Tri-state representation**: `AVAILABLE / UNAVAILABLE / UNKNOWN` — errors/timeouts go to `UNKNOWN`, never flip to `UNAVAILABLE`.
- **Per-slot debounce / flap-damping window** (e.g., 15 min): after firing for `restaurant_X:2025-05-01:19:00:party2`, suppress re-fires for that exact slot-tuple during the window regardless of state transitions.
- **Redis SETNX idempotency key** scoped to `(restaurant, date, time, party_size)` with 20-min TTL (already in PROJECT.md) — but see Pitfall 7 for the atomicity gotcha.
- Log every suppressed flap with reason; this data is the diff-engine's own test suite.

**Warning signs:**
Notification-to-unique-slot ratio > 1.05. User-reported "I clicked and the table was never there." Error-rate spikes correlating with notification spikes.

**Phase to address:** Event Pipeline phase — the diff engine MUST ship with confirmation-poll + tri-state from day one. Adding this retroactively after false-positives in production is a credibility disaster.

**Severity:** **Critical** — the product is a notification system; false positives are *the* product-killing failure mode.

---

### Pitfall 4: Kafka At-Least-Once Delivery Causing Duplicate Notifications

**What goes wrong:**
The notifier consumer reads an event, sends an SMS via Twilio, then crashes before committing its offset. On restart it re-reads the same event and sends the SMS again. User gets two identical 3 AM texts. Alternatively: consumer takes >`max.poll.interval.ms` to process a batch (Twilio slow day); Kafka rebalances, another consumer picks up the same partition, both send the notification. Result: duplicate notifications and `CommitFailedException` spam in logs.

**Why it happens:**
Default Kafka delivery is at-least-once. `enable.auto.commit=true` (Kafka default) commits offsets on a timer — which may fire *before* the SMS actually sent, leading to at-most-once (worse). Most teams discover this only after the first production duplicate. Per New Relic and Confluent docs, the defaults favor convenience over safety — which is wrong for notification workloads.

**How to avoid:**
- `enable.auto.commit=false`. Manual commit **after** the notification provider ack'd (Twilio 2xx, Resend `id`, Web Push endpoint 201).
- **Redis SETNX idempotency key** (already in PROJECT.md) scoped to `(user_token, slot_tuple)` checked *inside the notifier consumer* before calling the provider. The SETNX does the dedup work; Kafka only needs at-least-once.
- Set `max.poll.interval.ms` generously (default 5 min is fine for this use case).
- Use a single consumer group with stable membership; avoid rapid restarts.
- Wrap the handler in try/except such that `commitSync` is only reached after idempotent provider success or deliberate drop.

**Warning signs:**
`CommitFailedException` appearing in logs. Twilio dashboard shows duplicate SIDs for the same destination in the same minute. User complaints of double-texts.

**Phase to address:** Event Pipeline phase. Duplicate-prevention test (force-crash notifier between send and commit, verify no second send) is a phase-exit criterion.

**Severity:** **Critical** — same product-credibility surface as Pitfall 3.

---

### Pitfall 5: Twilio A2P 10DLC / Toll-Free Verification Blocks Demo Launch

**What goes wrong:**
Week 7: SMS integration is "working" — Twilio test messages deliver. Week 8: point to real US user phone numbers. Twilio silently filters all sends. Reason: unregistered 10DLC campaign, or unverified toll-free number. Resolution takes 1-4 weeks (Standard Campaigns can take "several weeks" per Twilio docs). Portfolio demo ships with SMS non-functional. During the "Heightened Awareness Period" (a Twilio term for high-traffic seasons), throughput can be throttled further.

**Why it happens:**
Test-mode Twilio numbers work without 10DLC registration. The filtering only kicks in for real traffic to real US carriers. Developers discover the registration requirement after writing "send SMS" code.

**How to avoid:**
- **Start 10DLC registration in Week 1** of the project (Phase 0/1 admin checklist), not when SMS code is written. Sole-Proprietor registration is fastest if applicable.
- As backup, register a toll-free number in parallel with Toll-Free Verification.
- Document use case, opt-in flow, and opt-out (STOP) handling in the registration form *exactly* matching what the PWA actually does (mismatches cause rejection per Twilio docs).
- Plan an **SMS-degraded demo path**: if 10DLC approval is delayed, the demo uses email (Resend) + Web Push as primary channels and shows SMS as "provisioning" in the admin panel. This is honest and defensible to a senior-engineer reviewer.

**Warning signs:**
Twilio console "Campaign status: Pending" after 5+ business days. "MESSAGE_FILTERED" in delivery logs when sending to non-test numbers.

**Phase to address:** **Phase 0 / project kickoff admin task** — register before writing a line of notification code.

**Severity:** **Critical** — non-technical blocker that kills a technical launch.

---

### Pitfall 6: iOS PWA Web Push Subscriptions Silently Canceled

**What goes wrong:**
Web Push on iOS (Safari, PWA only — not browser tab) works for the first 2 sends. The third send silently terminates the subscription. User stops receiving alerts, nothing in the logs indicates why. The PWA demo fails for iPhone reviewers — a non-trivial portion of the target audience.

**Why it happens:**
iOS Safari treats a push event as "silent" (and penalizes the subscription) if the service worker's `push` handler does not call `event.waitUntil(self.registration.showNotification(...))` — or calls it with a malformed payload (missing `title`, no `body`). After ~3 silent pushes iOS revokes the subscription. This is [documented by Progressier](https://dev.to/progressier/how-to-fix-ios-push-subscriptions-being-terminated-after-3-notifications-39a7) and confirmed in Apple Developer Forums.

**How to avoid:**
- Every `self.addEventListener('push', ev => { ev.waitUntil(showNotification(...)) })` — `waitUntil` must wrap the entire async chain, not just the final promise.
- Validate payload server-side before sending: `title` and `body` required, `icon` recommended, `data.url` for click target.
- iOS PWA installation is a prerequisite — gate Web Push opt-in UI behind "is standalone" check (`window.matchMedia('(display-mode: standalone)')`).
- Handle `pushsubscriptionchange` and endpoint 410 Gone responses — purge stale subscriptions from DB.
- Test on a real iPhone in PWA mode (not simulator, not Safari tab) for the demo video.

**Warning signs:**
Subscription count on iOS decaying without matching user action. Endpoint `410 Gone` rate rising. Users report "stopped getting alerts."

**Phase to address:** Notification Channels phase — iOS-specific test is an exit criterion.

**Severity:** **High** — demo-breaking on iPhone. Downgrade to Medium if SMS + email are acceptable fallbacks for the reviewer persona.

---

### Pitfall 7: Redis SETNX Used Non-Atomically (Deadlock or Dedup Miss)

**What goes wrong:**
Code does `SETNX key 1` then `EXPIRE key 1200` as two commands. Process crashes between them. Key has no TTL. That slot's idempotency key is permanent — the restaurant will never emit a notification again until manual cleanup. Alternative failure: the idempotency check and the provider call are not atomic, so two consumers both SETNX=success (one wins, the other fails *after* the SMS is already queued).

**Why it happens:**
Legacy Redis tutorials still show the two-command pattern because `SETNX` + `EXPIRE` predates the atomic `SET key value NX EX ttl` form (Redis 2.6.12+). [Leapcell's "10 Hidden Pitfalls"](https://dev.to/leapcell/10-hidden-pitfalls-of-using-redis-distributed-locks-39m5) lists this as #1.

**How to avoid:**
- Always `SET key value NX EX 1200` as a single atomic command. Never `SETNX` + `EXPIRE` separately.
- For the notifier's check-then-send, the SETNX claim must happen *before* the provider call, and the release must be absent (let TTL expire). Never `DEL` on success — that re-opens the window for duplicate fires from a rebalancing consumer.
- TTL must exceed worst-case provider retry window (20 min is reasonable for SMS; longer would block legitimate re-notifications for a re-opened slot).
- Design the critical section to be idempotent anyway — if Pitfall 4's commit-after-send fails, the next attempt should short-circuit on SETNX.

**Warning signs:**
Grafana: `notification_idempotency_hits` counter zero or weirdly low. User reports of missed notifications for restaurants that clearly had cancellations. Orphan Redis keys with no TTL (`redis-cli --scan --pattern 'notif:*' | xargs -I{} redis-cli TTL {} | grep -c '^-1$'`).

**Phase to address:** Event Pipeline phase, alongside Pitfall 4.

**Severity:** **High** — a subset of Pitfall 4's blast radius, but easy to avoid if mentioned explicitly.

---

### Pitfall 8: Legal/ToS Exposure (Scraping Public Data But Still Receiving a C&D)

**What goes wrong:**
The portfolio repo goes semi-viral on Hacker News. Resy/OpenTable legal sends a cease-and-desist pointing to their ToS which explicitly prohibits scraping. The project is taken down and the portfolio narrative becomes a cautionary tale rather than a showcase. OpenTable's ToS [explicitly prohibits](https://www.opentable.com/c/legal/terms-and-conditions/) "scraper, generative AI or other AI technology" access. New York's [Restaurant Reservation Anti-Piracy Act](https://columbianewsservice.com/2025/07/28/new-york-banned-reservation-resales-now-appointment-trader-is-testing-the-law-with-ai/) and proposed New Jersey legislation raise the stakes.

**Why it happens:**
"Public data" is a defense, not an immunity. Courts have been inconsistent. A visible public project is a bigger legal target than a quiet one — Appointment Trader has been the lightning rod precisely because of its visibility.

**How to avoid:**
- **README must** include an explicit "Legal & Ethical Scraping" section covering: public-data-only, rate-limit caps (80 req/min), no booking automation, no account creation automation, no reservation reselling, robots.txt respect, manual takedown compliance. This is already in PROJECT.md constraints — enforce it in the README.
- Frame the project publicly as a **personal portfolio/demo**, not a service with users. The demo link shows live data; there is no paid tier, no resale, no payment collection.
- Do **not** scrape Tock (already out of scope per PROJECT.md — good call, enforce it).
- Pre-draft a takedown-compliance plan: if C&D arrives, scraper stops within 24h; read-only public pages (heatmap) stay up on historical data.
- Do not publish Resy account credentials or cookies in the repo. Use `.env` + GitHub secrets. A leaked cookie is both a security and ToS disaster.

**Warning signs:**
Sudden spike in HN/Twitter traffic to the repo. Email from an `@resy.com` or `@opentable.com` legal domain. Unusual 403s on previously-working endpoints.

**Phase to address:** Phase 0 (README legal section drafted week 1) and Phase 8/Launch (final legal review before going public).

**Severity:** **High** for portfolio reputation; **Critical** if paired with monetization (out of scope). Downgrade from Critical-as-a-whole because the project is explicitly portfolio + free + no booking.

---

## Moderate Pitfalls

Real risks, but well-trodden territory — addressing them is routine if you know they exist.

### Pitfall 9: httpx Connection-Pool Exhaustion in the OpenTable Poller

**What goes wrong:**
OpenTable polling uses `httpx` async. Per-poll `httpx.AsyncClient()` creation is used instead of a reusable client. File descriptors leak; TCP TIME_WAIT accumulates; eventually the worker cannot open new sockets and all polls fail.

**How to avoid:**
One shared `httpx.AsyncClient` per worker with explicit `limits=httpx.Limits(max_connections=100, max_keepalive_connections=20)`. Use `async with AsyncClient(...)` in the worker's `lifespan`/startup, not per request. Add a semaphore to cap concurrent in-flight requests *within* the pool (backpressure).

**Severity:** **Medium** — standard asyncio hygiene; easy to get right if on the checklist.

**Phase to address:** Scraping Foundations.

---

### Pitfall 10: Kafka Consumer Lag Due to `max.poll.interval.ms` Timeout

**What goes wrong:**
Notifier consumer's Twilio call takes 12 seconds (bad network day). Processing 10 messages in a batch takes >120 seconds. Kafka thinks the consumer is dead, rebalances, `CommitFailedException` fires, messages are reprocessed, duplicates emitted.

**How to avoid:**
- Reduce `max.poll.records` to 1 for the notifier (one message per poll cycle — low-throughput workload).
- Send notifications with a hard per-call timeout (e.g., 10 s for SMS, 5 s for Web Push matching PROJECT.md SLOs); on timeout, emit to a dead-letter topic rather than blocking the consumer.
- Use async heartbeat via the `kafka-python` / `aiokafka` background thread — but still keep `max.poll.records=1`.

**Severity:** **Medium**.

**Phase to address:** Event Pipeline phase.

---

### Pitfall 11: Single-Node Kafka Data Loss on Host Failure

**What goes wrong:**
GCE host crashes or is preempted. Single-broker Kafka loses all un-flushed messages. Pipeline's audit trail (touted as a portfolio feature) is invalidated.

**How to avoid:**
- Accept the risk at MVP — document it explicitly in the README ("single-node Kafka; not HA; acceptable at MVP scale and portfolio scope"). A senior-engineer reviewer respects honest tradeoffs more than silent gaps.
- Use a **persistent disk** (pd-standard) for Kafka log directory; do not use ephemeral local SSD.
- Set `acks=all` and `flush.messages=1` for the producer — forces fsync before ack (trading throughput for durability; fine at 2500 notifs/day).
- **Do not** run ZooKeeper in embedded mode; use KRaft (Kafka ≥ 3.3) — simpler single-node.
- Alert on broker unavailability; have a documented manual-recovery runbook.

**Severity:** **Medium** — low-probability, but a portfolio-visible architecture choice that must be defended in the README.

**Phase to address:** Event Pipeline phase + Launch/Observability phase.

---

### Pitfall 12: TimescaleDB Chunk Interval Misconfiguration

**What goes wrong:**
`chunk_time_interval` defaults to 7 days. At 400 events/day + poll_log at ~100K rows/day, that's a manageable chunk. But if pattern-model training runs a 90-day window query, the planner touches 13 chunks. Worse: if dev sets chunk interval to 1 hour "because it seems granular," you get 2,160 chunks/day — planning overhead dominates every query and crosses the 500-chunk-warning threshold within hours.

**How to avoid:**
- Start with `chunk_time_interval => INTERVAL '1 day'` for `availability_events` and `INTERVAL '1 day'` for `poll_log`. Monitor chunk count weekly; tune if needed.
- Do **not** change it mid-project without understanding that `set_chunk_time_interval()` only affects *new* chunks ([bug #9105](https://github.com/timescale/timescaledb/issues/9105) shows edge-case corruption at the boundary).
- Add the continuous aggregate for the heatmap at Week 5-6, not earlier — premature CAGG creation couples chunk-size decisions prematurely.

**Severity:** **Medium** — cheap to get right, expensive to retrofit.

**Phase to address:** Data Persistence / Pattern Model phase.

---

### Pitfall 13: SSE Feed Buffered by Nginx/Cloud Run Proxy

**What goes wrong:**
Live activity feed on the PWA home page shows events 30 seconds late (or in 30-second batches), not instantly. Undermines the "sub-60s end-to-end" portfolio story because the visible feed looks laggy even when the pipeline isn't.

**How to avoid:**
- Response headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Content-Type: text/event-stream`. Starlette/FastAPI's `EventSourceResponse` sets these.
- Send a `: keepalive\n\n` comment every 15 s to prevent proxy idle-timeout closes.
- On Cloud Run, set request timeout to 3600 s (max) for the SSE endpoint; this is non-default (default 5 min).
- Test through the actual Cloud Run URL, not `localhost` — Cloud Run's front-end proxy has its own buffering behavior.

**Severity:** **Medium** — purely a demo-credibility issue.

**Phase to address:** PWA/Frontend phase.

---

### Pitfall 14: HMAC Management Token Design Leaks

**What goes wrong:**
The "no-account HMAC token" flow is novel — points to a senior reviewer. Common mistakes: token includes only `user_id` (easy to enumerate and forge if secret leaks); no expiry or version; single static secret with no rotation plan; token sent as URL query param (logged by every proxy and browser history).

**How to avoid:**
- Token payload: `{user_id, purpose, token_version, issued_at, expires_at}` signed with HMAC-SHA256. Include `token_version` so monthly rotation works (accept v_N and v_N-1 concurrently during the overlap window — the dual-phase rotation pattern).
- Use URL path or fragment for the token, not query string (`/manage/#tok=...`) — fragments are not sent to the server and not logged. For server-side verification (which you need), use path: `/manage/t/{token}` — and document that email-preview tools will pre-fetch it (mitigate with one-time-use or signed nonce).
- Minimum 32-byte secret from `secrets.token_bytes(32)`, not from an env var with a human-chosen string.
- Rotate via env var swap + dual-key verification for 24h after cutover. Document rotation in README.
- Do not sign the whole URL; sign an *intent* payload and embed it. An HMAC over the URL leaks structure and is brittle under URL-encoding changes.

**Severity:** **Medium** — specific to this project's unusual auth design; reviewers will scrutinize this.

**Phase to address:** Watchlist CRUD / Auth phase.

---

### Pitfall 15: Pattern Detection Model Overfits on Sparse Data

**What goes wrong:**
~400 events/day × 50 days = 20K events at launch. The "48h rule" / "cancellation-peak" / "inventory-load-day" heuristics are fit on this data and look great in notebooks. Deployed, they produce wildly confident predictions for dimensions that have 5 data points. The heatmap shows "8:13 PM Wednesday is a hot cancellation window" because one Carbone canceled at 8:13 PM three times.

**How to avoid:**
- Explicitly **heuristic / rule-based** at MVP, not ML. The project's pattern-model features (48h rule, load days) are *rules discovered from literature*, not model-learned. Frame the ML as "descriptive statistics over historical data" not "predictions."
- When displaying the heatmap, require a minimum-cell-count threshold (e.g., ≥ 10 observations) before coloring a cell; otherwise show gray.
- Compute confidence intervals on release-rate estimates (Wilson score for Bernoulli-ish events, not raw proportion). Display them.
- Hold out a validation window (last 2 weeks) and report false-positive/false-negative rate honestly in the README.
- Do NOT auto-notify based on predictions alone (e.g., "we predict a slot will open at 7pm") — only notify on *observed* events. Predictions are for the heatmap only.

**Severity:** **Medium** — affects the "pattern intelligence" portfolio narrative, not the core notification loop.

**Phase to address:** Pattern Model phase (late — Week 6 or 7). Explicitly *after* event-pipeline works, so you have real data to fit on.

---

### Pitfall 16: asyncio / GIL Confusion Causing Accidental Serialization

**What goes wrong:**
Scraper uses `asyncio` but calls a blocking library (e.g., `requests` instead of `httpx`, or `time.sleep` instead of `asyncio.sleep`, or CPU-bound parsing in the event loop). All 20 concurrent polls serialize on the single thread and latency balloons.

**How to avoid:**
- Ban `requests`, `time.sleep`, `urllib`, synchronous Redis client (`redis` without `redis.asyncio`) from the async workers via CI lint rule (grep-based or `flake8-async`).
- CPU-bound work (JSON parsing of large payloads, pattern-model scoring) → `asyncio.to_thread(...)` or a process pool.
- Use `uvloop` — drop-in and 2-4x faster for this workload.
- Add a `asyncio.get_event_loop().set_debug(True)` in local dev to catch slow callbacks (>100 ms).

**Severity:** **Medium** — easy to avoid with discipline; painful to debug after the fact.

**Phase to address:** Scraping Foundations phase.

---

## Minor Pitfalls

Worth mentioning but unlikely to hurt at MVP scale.

### Pitfall 17: Prometheus Metric Cardinality Explosion

Labels like `restaurant_id`, `party_size`, `date` on a single counter generates a label cross-product of potentially millions of series. Grafana Cloud free tier caps active series (default ~10K). Use `restaurant_id` sparingly; never label by `date` or raw `time` — aggregate first. Severity: **Low** at 50 restaurants. Phase: Observability.

### Pitfall 18: Redis Memory Eviction of Active Keys

Default `maxmemory-policy` is `noeviction` on Memorystore — so OOM causes writes to fail (which is actually correct for idempotency keys). But many tutorials suggest `allkeys-lru`, which would silently evict an idempotency key mid-TTL and re-open the dedup window. Keep it at `noeviction` or `volatile-ttl`. Severity: **Low** at the data volumes in PROJECT.md. Phase: Infrastructure.

### Pitfall 19: Service Worker Update Loop on PWA

Next.js 14 + `next-pwa` with a bad `skipWaiting` configuration causes the SW to update on every navigation, losing push-subscription state on iOS. Use a stable SW filename and test the update flow explicitly. Severity: **Low**. Phase: PWA/Frontend.

### Pitfall 20: Cloud Run Cold-Start on SSE Endpoint

Cloud Run's min-instances default is 0. Each new SSE client pays a 2-3 s cold start. Set min-instances=1 for the API service during demo periods ($~$3/mo) or accept the first-click delay. Severity: **Low**. Phase: Deployment.

---

## Portfolio-MVP Specific Tradeoffs (Over-Engineering vs Under-Engineering)

This is the biggest "pitfall category" that generic guides miss. The project has a senior-engineer reviewer as tertiary persona — under-engineering hurts that story; over-engineering burns 8 weeks.

### Over-Engineering Traps (do NOT do these at MVP)

| Temptation | Why Appealing | Why Wrong at MVP |
|---|---|---|
| Multi-broker HA Kafka cluster | "Looks enterprise" | Single-node + documented tradeoff is more impressive; HA Kafka is a full week of ops on GCE |
| Kubernetes / GKE deployment | "Production-grade" | Cloud Run is the correct choice; GKE is 2 weeks of yak-shaving for zero MVP benefit |
| ML model for pattern prediction | "AI buzzword" | Rule-based heuristics + honest CIs are more defensible; an ML model on 20K events overfits and loses credibility |
| Microservices beyond the 4-5 defined | "Proper architecture" | Every extra service is a deploy target and a failure mode; keep it at scraper / diff / notifier / api / web |
| Custom auth system with JWTs, refresh tokens, etc. | "Complete product" | HMAC token design is a *feature* of this project — implementing real auth would dilute the "no friction" story |
| 100% test coverage | "Professional" | 60-70% with high-value integration tests (diff-engine correctness, idempotency, SSE end-to-end) is more impressive than 100% unit-test-coverage of DTOs |
| Service mesh / Istio / tracing infra beyond OpenTelemetry basics | "Observability" | Prometheus + Grafana + Sentry + structured logs is the right level |

### Under-Engineering Traps (DO spend time on these)

| Temptation to Skip | Why Skipped | Why You Cannot Skip |
|---|---|---|
| Confirmation poll (Pitfall 3) | "Polling is already expensive" | Without it, the notification product is unfaithful; this is the one feature that validates correctness |
| Soak test (Pitfall 1) | "It worked for an hour" | Memory leaks in Playwright manifest at 6-12h; a demo that dies overnight is demo-killing |
| README legal section (Pitfall 8) | "I'll add it later" | Senior reviewers read this first; it signals maturity |
| Twilio 10DLC registration (Pitfall 5) | "I'll do it when I need SMS" | Lead time is weeks; must be Phase 0 admin |
| Real iPhone PWA test (Pitfall 6) | "Works on Chrome" | iOS Web Push has unique failure modes; reviewers WILL test on iPhone |
| Prometheus + Grafana public read-only dashboard | "Internal tool" | This IS the portfolio artifact — it proves the system works |
| Soft-ban detection (Pitfall 2) | "Just count poll success rate" | Silent soft-bans look like "no cancellations today" — invisible without signature-drift detection |

### Scope-Creep Traps Specific to This Project

1. **"Let's add Tock"** — already out of scope per PROJECT.md; will come back as a tempting 1-week detour in Week 5. Reject.
2. **"Let's add a public API with rate limits"** — OpenTable-grade features the project doesn't need. Reject.
3. **"Let's do native mobile"** — PWA is the decision. Reject.
4. **"Let's add booking automation"** — legal disaster. Reject with prejudice.
5. **"Let's add user accounts"** — directly contradicts the HMAC-token design that is a portfolio feature.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `SETNX` + `EXPIRE` as two commands | Works in tutorials | Deadlock on process crash between commands (Pitfall 7) | **Never** — atomic `SET NX EX` is one character longer |
| `enable.auto.commit=true` on Kafka consumers | Less code | Duplicate or lost notifications (Pitfall 4) | **Never** for notification consumers |
| Playwright context reused across many polls | Faster polls (no context startup) | Memory leak + cookie aging increases bot-detection (Pitfall 1, 2) | Up to ~20 polls per context with explicit recycling |
| Single fat `.env` with all secrets committed to GitHub | "I'll fix it before launch" | Credential leak = ToS violation = C&D (Pitfall 8) | **Never** — use secrets manager from day one |
| No confirmation poll (just direct state diff) | Halves polling load | False-positive storm destroys credibility (Pitfall 3) | Never, for a notification product |
| Skipping iOS PWA test on real device | "Faster demo loop" | Pitfall 6 blindside at launch | Only if you document "SMS is primary on iOS" explicitly |
| Datacenter IPs for Resy | No proxy cost | Silent soft-ban (Pitfall 2) | Never at production; OK for local dev only |
| Fit pattern model on full dataset without holdout | Looks more confident | Overfitting claims that don't survive scrutiny (Pitfall 15) | Never for the public README/demo |
| Single Kafka broker on GCE ephemeral disk | Cheaper | All event history lost on preemption (Pitfall 11) | **Never** — use persistent disk |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **Twilio SMS** | Test-mode works; deploy; filtered for real US numbers | Register 10DLC in Phase 0; have toll-free fallback; plan SMS-degraded demo (Pitfall 5) |
| **Resend Email** | Domain not verified with SPF/DKIM/DMARC; mail goes to spam | Verify `mise.place` domain with SPF + DKIM + DMARC before Week 7; warm up sending from low volume |
| **Web Push (VAPID)** | Same VAPID keypair shared across environments, or regenerated per deploy | One VAPID keypair per environment, stored in secrets; never rotate without user re-subscription (Pitfall 6) |
| **Playwright + Resy** | Fresh context every poll (slow) or permanent context (detected) | Auth-state JSON file; fresh context per poll that loads the state; recycle state weekly (Pitfall 1, 2) |
| **httpx + OpenTable** | New `AsyncClient` per poll | Shared client in worker lifespan with explicit `Limits` (Pitfall 9) |
| **Kafka + Python** | `kafka-python` (sync) inside an async worker | `aiokafka` for producers/consumers in async services |
| **Redis + Python** | `redis` sync client in async worker | `redis.asyncio` / `redis-py` async API |
| **TimescaleDB + ORM** | SQLAlchemy migrations don't know about hypertables | Use raw `SELECT create_hypertable(...)` in Alembic migration with `op.execute`; don't let autogenerate recreate the table (Pitfall 12) |
| **Cloud Run + SSE** | Default 5-min timeout kills long-lived streams | Set request timeout to 3600 s; min-instances ≥ 1 during demo (Pitfall 13, 20) |
| **Next.js 14 PWA** | Service worker gets disabled in dev; code-path untested until deploy | Test SW behavior in production build locally before deploy (`next build && next start`) |

---

## Performance Traps

Patterns that work at small scale but fail as usage grows.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Per-poll Playwright context creation | CPU pinned, /dev/shm full | Pooled contexts with age-based recycling | Immediately at concurrency ≥ 5 |
| Unbounded asyncio concurrency (no semaphore) | Latency spikes under load | `asyncio.Semaphore` per external dependency (Resy, OpenTable, Twilio, Resend) | At 80 req/min cap if a dependency slows |
| SELECT without chunk-pruning predicates on hypertable | Query planning touches all chunks | Always include `time >= NOW() - INTERVAL '...'` in pattern-model queries (Pitfall 12) | At ~30 days of data / 30+ chunks |
| N+1 query in heatmap API | Page load 3+ s | Single CAGG query or explicit `JOIN` | At 50 restaurants × 7 days × 24 h |
| Prometheus histogram cardinality blowout | Grafana OOM / series limit | Use native `Histogram` with fixed buckets, never custom per-request labels (Pitfall 17) | At ~1K active series on free tier |
| SSE broadcasting to all clients in-process | Event loop stall with 20+ clients | Redis pub/sub fan-out; each API instance subscribes and relays to local SSE clients | At 30-50 concurrent SSE clients |
| Single-threaded pattern-model training on request | API timeout during retrain | Offline training job; load pickled model on startup | Immediately once dataset > 10K events |

---

## Security Mistakes

Beyond OWASP basics — issues specific to this project.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Resy session cookies persisted to DB | Credential theft = ToS violation + account-ban (Pitfall 8) | Ephemeral in Redis with short TTL, encrypted at rest; never DB-persisted (already in PROJECT.md constraints — enforce) |
| Phone numbers stored unencrypted | PII leak; legal exposure (CCPA, TCPA) | AES-256-GCM via pgcrypto (already in PROJECT.md); index on HMAC(phone) for lookup, never on plaintext |
| HMAC management token as query string | Leaks into server logs, referrer headers, browser history (Pitfall 14) | Path-based token (`/manage/t/{token}`) + short TTL (30 days) + rotation |
| HMAC secret in env var with human-chosen value ("supersecret") | Brute-force attack feasible | `secrets.token_bytes(32)` at project init; stored in secrets manager (Pitfall 14) |
| VAPID private key in git (even "expired" one) | Someone can send pushes to your users forever (subscription endpoints are per-VAPID) | Secrets manager only; one keypair per env |
| Open SSE endpoint broadcasts all events | Leaks restaurant-level availability to any viewer | Acceptable for this product (data is public) but document it explicitly; do NOT broadcast user-scoped notification events |
| Twilio webhook callback without signature validation | Attacker forges inbound SMS (STOP, opt-out) | Use Twilio's `validate_request` on inbound webhooks with the auth token |
| Leaked cookie from Resy scraper via stack trace in Sentry | Resy account ban + ToS violation | Sentry `before_send` scrubber for `cookie`, `authorization`, `x-auth` headers; test with fuzzed payloads |
| README leaks IP addresses of scraping infrastructure | Target for researchers/Resy IT | Don't include GCE public IPs or project IDs in the public README |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Notification says "Table opened at Carbone!" without party size / date / time in preview | User opens app and hunts | Push payload includes "Carbone · 7:30 PM · Fri May 2 · party of 2" in the visible body |
| "Book now" link goes to Resy restaurant page, not the specific slot | User has to re-search; slot gone by then | Deep-link with the booking intent parameters if Resy URL supports it; otherwise pre-fill search with date/time/party in query string |
| No way to mute for the current evening (too many alerts during a busy release) | User disables notifications entirely | 4-hour "snooze" on the management page |
| SSE feed shows stale events on refresh (no backfill) | User refreshes, feed looks empty | Last 50 events hydrated via REST at load; SSE appends from there |
| PWA install prompt never shown on iOS (iOS does not fire `beforeinstallprompt`) | iOS users never subscribe to Web Push | Manual "Add to Home Screen" instructions on the page when `isIOS && !isStandalone` |
| Opt-out link in SMS is "reply STOP" but webhook isn't wired | Users can't opt out; TCPA violation | Twilio inbound webhook on Day 1 of SMS; test with STOP and verify DB update |
| Heatmap shows "high confidence" colors for 2-observation cells | User trusts a false pattern | Grey out cells below minimum observations (Pitfall 15) |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces. Run this against each feature at phase exit.

- [ ] **Scraper:** Works for 1 hour in dev — verify 12h soak test with RSS/PID monitoring (Pitfall 1)
- [ ] **Scraper:** Poll success rate shown — verify soft-ban canary metric (response-signature drift) exists (Pitfall 2)
- [ ] **Diff engine:** Detects transitions — verify confirmation poll + tri-state (AVAILABLE/UNAVAILABLE/UNKNOWN) in code (Pitfall 3)
- [ ] **Diff engine:** Idempotency key exists — verify it uses atomic `SET NX EX` (not `SETNX` + `EXPIRE`) and is scoped to `(restaurant, date, time, party_size)` (Pitfall 7)
- [ ] **Notifier:** SMS sends in dev — verify 10DLC campaign registered and phone numbers associated (Pitfall 5)
- [ ] **Notifier:** Kafka consumer commits offsets — verify `enable.auto.commit=false` + manual commit after provider ack (Pitfall 4)
- [ ] **Web Push:** Works on desktop Chrome — verify iOS PWA real-device test with ≥ 5 consecutive pushes (Pitfall 6)
- [ ] **Web Push:** Service worker `push` handler has `event.waitUntil(...)` wrapping the *entire* async chain (Pitfall 6)
- [ ] **SSE feed:** Events stream locally — verify through Cloud Run URL (proxy buffering), not localhost (Pitfall 13)
- [ ] **HMAC tokens:** Working end-to-end — verify `token_version` is in payload and dual-version verification works (rotation readiness) (Pitfall 14)
- [ ] **Pattern heatmap:** Displays colors — verify minimum-observation threshold and confidence intervals shown (Pitfall 15)
- [ ] **Kafka:** Brokers up — verify persistent disk mounted (not ephemeral), KRaft mode, `acks=all` (Pitfall 11)
- [ ] **TimescaleDB:** Hypertable exists — verify `chunk_time_interval` set explicitly, chunk count monitored (Pitfall 12)
- [ ] **README:** Project described — verify Legal & Ethical Scraping section, rate-limit section, architecture-decision tradeoffs (Pitfall 8, 11)
- [ ] **Prometheus:** Metrics visible — verify cardinality budget, public read-only Grafana link works (Pitfall 17)
- [ ] **Secrets:** Nothing hardcoded — verify `gitleaks` or `trufflehog` scan of the repo, env-var audit (Pitfall 8)
- [ ] **Phone PII:** Encrypted — verify DB dump shows only `\x...` bytes, not plaintext, in `users.phone` (Security)
- [ ] **Sentry:** Configured — verify `before_send` scrubs cookies/auth headers via fuzzed test (Security)

---

## Recovery Strategies

When pitfalls occur despite prevention.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Playwright memory leak in prod | LOW | Systemd/Cloud Run auto-restart on OOM; ship a fix within 24h |
| Resy IP ban | MEDIUM | Switch proxy provider; reduce rate limit by 50%; disable that account; audit logs for the trigger |
| False-positive notification storm | HIGH (reputational) | Pause notifier consumer immediately; apologize publicly; add confirmation poll + flap-damping; add explicit "we confirmed this slot twice before alerting" to UI |
| Kafka duplicate notifications | MEDIUM | Add SETNX check in notifier if missing; force-redeliver deduped; post-mortem in README |
| Twilio 10DLC rejection | HIGH (delivers slowly) | Fallback to toll-free verified; escalate with Twilio support; if >2 weeks, ship demo with SMS in "pending" state |
| iOS Web Push subscription death | MEDIUM | Fix `event.waitUntil`; push users to re-subscribe via in-app banner; 3-send test nightly via sentinel |
| Redis key without TTL | LOW | `SCAN + TTL + DEL` cleanup script; fix the code; replay last 24h of events |
| C&D letter from Resy/OT | HIGH | Stop scraper within 24h; remove live-data pages; keep historical heatmap up; update README to reflect new state; consider if "archive" pivot is defensible |
| Kafka broker data loss (host preemption) | HIGH | 7-day retention buffer means some data is in-flight lost; heatmap accuracy drops for that window; document in demo; move to preemption-resistant instance |
| Pattern model discredited (false trends) | MEDIUM | Raise observation thresholds; add error bars; frame as "descriptive only" in README; never auto-notify on predictions |

---

## Pitfall-to-Phase Mapping

Rough phase alignment. Roadmap creation should refine.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| 1. Playwright memory leak | Scraping Foundations (P2) | 12h soak test with RSS < baseline + 20%, PID count stable |
| 2. Resy bot detection | Scraping Foundations (P2) | Soft-ban canary metric green for 7 days; `playwright-stealth` in place |
| 3. False-positive / flapping | Event Pipeline (P3) | Simulated transient-error test produces 0 false events |
| 4. Kafka at-least-once dupes | Event Pipeline (P3) | Kill-9 notifier between send and commit; verify no duplicate at Twilio |
| 5. Twilio 10DLC lead time | **Phase 0 / kickoff admin** | Campaign "Registered" status in Twilio console by Week 3 |
| 6. iOS Web Push | Notifications (P4) | Real iPhone PWA test: 5 consecutive pushes deliver |
| 7. Redis SETNX atomicity | Event Pipeline (P3) | Code review + grep for `SETNX` (should be zero occurrences) |
| 8. Legal/ToS | Kickoff + Launch (P0, P8) | README legal section at P0; final legal review at P8 |
| 9. httpx pool exhaustion | Scraping Foundations (P2) | 24h load test; file-descriptor count stable |
| 10. Kafka consumer poll timeout | Event Pipeline (P3) | Chaos test: Twilio responds in 30s; verify no rebalance |
| 11. Single-node Kafka durability | Infrastructure (P1) + Observability (P7) | Persistent disk mounted; README tradeoff section written |
| 12. TimescaleDB chunks | Data Persistence (P5) | Chunk count < 100 after 30 days ingestion |
| 13. SSE buffering | PWA/Frontend (P6) | Cloud Run URL test: first event arrives < 500ms |
| 14. HMAC token leak vectors | Watchlist/Auth (P4) | Code review + rotation dry run |
| 15. Pattern model overfitting | Pattern Model (P6 or P7) | Held-out validation window; CIs in UI |
| 16. asyncio / blocking calls | Scraping Foundations (P2) | `flake8-async` in CI; event-loop debug mode in dev |
| 17. Prometheus cardinality | Observability (P7) | Active series < 5K in Grafana Cloud |
| 18. Redis eviction policy | Infrastructure (P1) | `CONFIG GET maxmemory-policy` = `noeviction` or `volatile-ttl` |
| 19. PWA service worker update | PWA/Frontend (P6) | SW update does not revoke push subscription |
| 20. Cloud Run cold start | Deployment (P7/P8) | min-instances ≥ 1 for API during demo period |

---

## Summary: The Five Things That Will Actually Break the Demo

If roadmap time is triaged hard, these are the non-negotiables:

1. **Confirmation poll + tri-state diff engine** (Pitfall 3) — without this, the product is a false-positive generator.
2. **Playwright memory leak prevention + 12h soak test** (Pitfall 1) — without this, the scraper dies overnight during review.
3. **Twilio 10DLC registration in Week 1** (Pitfall 5) — without this, SMS is absent at demo time.
4. **iOS PWA real-device Web Push test** (Pitfall 6) — without this, iPhone reviewers see a dead product.
5. **Atomic `SET NX EX` idempotency + Kafka manual commit** (Pitfalls 4, 7) — without these, duplicates destroy trust.

Everything else is defense-in-depth or polish. These five are existential.

---

## Sources

### Primary (HIGH confidence)
- [Microsoft Playwright-Python Issue #286: Memory leak while reusing BrowserContext](https://github.com/microsoft/playwright-python/issues/286)
- [Microsoft Playwright-Python Issue #1754: page.on / page.route memory leak](https://github.com/microsoft/playwright-python/issues/1754)
- [Microsoft Playwright-Python Issue #2511: Memory leak with any browsers and contexts used once](https://github.com/microsoft/playwright-python/issues/2511)
- [Kafka Consumer Offsets Guide - Confluent](https://www.confluent.io/blog/guide-to-consumer-offsets/)
- [Kafka Consumer Auto Commit - New Relic](https://newrelic.com/blog/best-practices/kafka-consumer-config-auto-commit-data-loss)
- [Kafka Offset Management - Conduktor](https://www.conduktor.io/blog/kafka-offset-management-consumer-commit-guide)
- [Twilio A2P 10DLC Official Docs](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc)
- [Twilio 2025 Heightened Awareness Period](https://www.twilio.com/en-us/blog/products/twilio-s-2025-heightened-awareness-period--ensuring-reliable-mes)
- [Twilio A2P 10DLC Troubleshooting](https://www.twilio.com/docs/messaging/compliance/a2p-10dlc/troubleshooting-a2p-brands)
- [Progressier: iOS push subscriptions terminated after 3 notifications](https://dev.to/progressier/how-to-fix-ios-push-subscriptions-being-terminated-after-3-notifications-39a7)
- [Apple Developer Forums: PWA push notifications on iOS](https://developer.apple.com/forums/thread/732594)
- [Redis SETNX Official Docs](https://redis.io/docs/latest/commands/setnx/)
- [Redis Distributed Locks Official Patterns](https://redis.io/docs/latest/develop/clients/patterns/distributed-locks/)
- [OpenTable Terms of Use](https://www.opentable.com/c/legal/terms-and-conditions/)
- [FastAPI Server-Sent Events Docs](https://fastapi.tiangolo.com/tutorial/server-sent-events/)

### Secondary (MEDIUM confidence — verified against ≥ 2 sources)
- [10 Hidden Pitfalls of Redis Distributed Locks - Leapcell](https://dev.to/leapcell/10-hidden-pitfalls-of-using-redis-distributed-locks-39m5)
- [Configuring SSE Through Nginx - OneUptime](https://oneuptime.com/blog/post/2025-12-16-server-sent-events-nginx/view)
- [A2P 10DLC Registration Developer Guide - NotificationAPI](https://www.notificationapi.com/blog/a2p-10dlc-registration-the-complete-developer-s-guide-2025)
- [Using Push Notifications in PWAs - MagicBell](https://www.magicbell.com/blog/using-push-notifications-in-pwas)
- [PWA iOS Limitations - MagicBell 2026](https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide)
- [TimescaleDB Chunk Sizing - TigerData](https://www.tigerdata.com/blog/timescale-cloud-tips-testing-your-chunk-size)
- [Monitoring TimescaleDB in Production](https://dev.to/philip_mcclarence_2ef9475/monitoring-timescaledb-in-production-a-complete-checklist-22bn)
- [TimescaleDB Chunks and Size - DEV](https://dev.to/philip_mcclarence_2ef9475/how-timescaledb-chunks-actually-work-and-why-size-matters-3hl5)
- [TimescaleDB Issue #9105: Chunk compression hangs](https://github.com/timescale/timescaledb/issues/9105)
- [FastAPI Mistakes Killing Performance - DEV](https://dev.to/igorbenav/fastapi-mistakes-that-kill-your-performance-2b8k)
- [12 FastAPI Anti-Patterns - Medium](https://medium.com/@Modexa/12-fastapi-anti-patterns-quietly-killing-throughput-bddaa961634a)
- [HMAC API Security 2025 - Authgear](https://www.authgear.com/post/hmac-api-security)
- [HMAC Verification Tokens - Rotational Labs](https://rotational.io/blog/hmac-verification-tokens/)
- [Restaurant Reservation Ruckus / Appointment Trader - LRA](https://www.lra.org/2024/03/12/restaurant-reservation-ruckus-inside-the-controversial-world-of-appointment-trader/)
- [New York Banned Reservation Resales - Columbia News](https://columbianewsservice.com/2025/07/28/new-york-banned-reservation-resales-now-appointment-trader-is-testing-the-law-with-ai/)

### Tertiary (LOW confidence — single-source; flag for validation)
- [Web Scraping Without Getting Banned 2026 - DEV](https://dev.to/vhub_systems_ed5641f65d59/web-scraping-without-getting-banned-in-2026-the-complete-anti-bot-bypass-guide-297h) — general anti-bot advice, not Resy-specific
- [How to Scrape Resy 2026 - Scraperly](https://scraperly.com/scrape/resy) — single source on Resy's specific protection level; validate empirically in Phase 2
- [Playwright MCP Memory Leak Fixes 2025 - Markaicode](https://markaicode.com/playwright-mcp-memory-leak-fixes-2025/) — benchmarks not independently verified
- [8GB Was a Lie: Playwright in Production - Medium](https://medium.com/@onurmaciit/8gb-was-a-lie-playwright-in-production-c2bdbe4429d6) — blog; direction of advice matches GitHub issues

---

*Pitfalls research for: Mise en Place (real-time restaurant reservation scraping + event pipeline + multi-channel notifications, 8-week portfolio MVP)*
*Researched: 2026-04-20*
