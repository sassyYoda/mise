# Feature Research

**Domain:** Restaurant reservation availability monitoring / cancellation-watch platform
**Researched:** 2026-04-20
**Confidence:** HIGH (competitor products verified via App Store listings, product pages, news coverage, and Trustpilot reviews; user pain points triangulated across multiple independent sources)

## Competitive Landscape Summary

The market splits into three categories:

1. **First-party waitlists** (Resy Notify, OpenTable Notify): free, broad coverage, but batched/delayed alerts, no queue transparency, no cross-platform coverage. Users report "I got the email and clicked within a minute — already gone" for top-tier restaurants.
2. **Third-party monitors** (TableOne at $18/mo, ReservationFinder.io at $10–20/mo, Tably, MouseDining-style): paid, claim sub-Notify latency, multi-platform (Resy + OpenTable + Tock + SevenRooms), party/time/date filters. Complaints: membership billing bugs, poor filter controls after UI changes, mixed login/auth reliability.
3. **Scalping marketplaces** (Appointment Trader, Dorsia, ResX): buy/sell reservations for cash. Appointment Trader is now **illegal in New York** under the Restaurant Reservation Anti-Piracy Act (effective Feb 17, 2025, up to $1,000/day per violation). Dorsia charges $175–$25,175/year for membership with a "death-only" refund policy. Industry-loathed; restaurants are actively fighting them.

**The gap Mise en Place exploits:** No existing product offers (a) continuous sub-minute monitoring + (b) pattern-based predictive intelligence (heatmaps, 48h-rule detection) + (c) zero-friction no-account UX + (d) free. TableOne and ReservationFinder are the closest competitors but charge monthly, have no pattern intelligence, and have reported UX regressions. Mise en Place's portfolio-systems-engineering posture (p95 ≤ 60s, public Grafana dashboard, open legal reasoning) is itself a differentiator vs. the scalper-adjacent reputation of the paid incumbents.

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete and churns users at first use.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Create a watch for restaurant + date(s) + party size | Core primitive of every competitor (Resy Notify, TableOne, ReservationFinder, Tably) | LOW | Already in PROJECT scope. Must accept date *ranges* not just single dates — single-date-only is a TableOne pain point. |
| Instant notification when matching slot opens | The entire value proposition | MEDIUM | Already the PROJECT's p95 ≤ 60s core requirement. |
| Multi-channel delivery: email + SMS + push | Users choose channel by urgency; SMS is the de facto standard for "fast enough to book" | MEDIUM | Already in PROJECT scope (Resend, Twilio, VAPID). |
| Time-window filter (e.g., only Fri/Sat 6–9 PM) | Resy Notify's biggest complaint is firing for *any* open slot; users won't take 5 PM solo tables for their anniversary | LOW | Stored on the watch record; evaluated server-side before emitting a notification event. |
| Party size filter (1–8+) | Table for 2 ≠ table for 6. Every competitor supports this. | LOW | Already implicit in PROJECT. Must be required at watch creation. |
| Ability to view / edit / pause / delete own watches | "Manage my watches" is universal | LOW | PROJECT has HMAC token-based no-auth management — good; must cover all four verbs, not just delete. |
| Deep-link from notification to Resy/OpenTable booking page | Users need to book in seconds; copy-paste kills conversion | LOW | Must construct the exact Resy `/cities/ny/venues/{slug}?date=...&seats=...` deeplink. Include in every notification channel. |
| Confirmation that a watch was created (and will fire) | Anxiety-reducing; without it users create the same watch 3 times | LOW | Acknowledgement email/SMS on watch creation. |
| Restaurant search / browse with coverage transparency | Users need to know if their restaurant is monitored before they bother | LOW | List of the ~50 monitored NYC restaurants; explicit "not yet covered — request it" for others. |
| No hidden fees / free to start | Resy Notify is free; TableOne/ReservationFinder trials convert poorly when there's a paywall before first alert fires | LOW | PROJECT is free at MVP — aligned. |
| Mobile-first UI | 80%+ of reservation traffic is mobile; Resy and OpenTable are mobile-dominant | MEDIUM | PWA in PROJECT scope; must be tested on iOS Safari specifically (the Resy demographic). |
| Unsubscribe / stop notifications without login | Required for SMS compliance (TCPA) and basic respect | LOW | STOP keyword for SMS; one-click unsubscribe with HMAC token for email. |
| Reliability / uptime signals | Users want to trust the monitor is actually running | LOW | Public read-only metrics page — already in PROJECT scope, and this is a *rare* differentiator in disguise. |

### Differentiators (Competitive Advantage)

Ranked by value-to-effort for portfolio impact and user acquisition.

| Rank | Feature | Value Proposition | Complexity | Notes |
|------|---------|-------------------|------------|-------|
| 1 | **Sub-60s detection-to-notification p95** | The entire reason the product wins. Resy Notify is batched ("minutes to hours"); TableOne is faster but still not sub-minute verified. Ship the number on the homepage. | HIGH | Already the PROJECT core value. Defended by Kafka + confirmation poll + Web Push pipeline. |
| 2 | **Availability pattern heatmap per restaurant** | No competitor has this. "Carbone releases tables Tue at 10 AM and at T-48h" is actionable even *without* a watch. Drives SEO and repeat visits. | MEDIUM | TimescaleDB hypertable makes the query cheap; frontend is a single heatmap component. Needs ≥ 2 weeks of polling data to be useful; ≥ 6 weeks to be confident. |
| 3 | **Pattern-aware pre-alerts** ("Carbone historically releases tables in ~14 min — get ready") | Turns passive alerts into active strategy. Competitors only fire on the event itself. | HIGH | Depends on pattern detection model (48h rule, inventory-load day, cancellation-peak). Ship rules-based v1; ML later. |
| 4 | **Zero-friction, no-account UX** | HMAC management tokens = signup-free. Resy requires account; TableOne requires payment + login. Removes the #1 conversion killer. | LOW | Already in PROJECT. Must be evangelized in marketing copy. |
| 5 | **Free, with a systems-engineering README** | Competitors charge $10–25K/year (Dorsia), $18/mo (TableOne). Free + transparent architecture + public Grafana dashboard earns engineer/foodie trust. | LOW | The Grafana dashboard + read-only metrics link *is* a differentiator with the recruiter persona. |
| 6 | **Cross-platform coverage (Resy + OpenTable)** | Resy Notify only watches Resy; OpenTable Notify only watches OpenTable. TableOne and ReservationFinder do cross-platform but charge. Free cross-platform = wedge. | MEDIUM | Already in PROJECT scope. |
| 7 | **Live SSE activity feed on homepage** | Social proof + entertainment. "Just opened: 4-top at Don Angie, 2 min ago." Competitors bury this; we make it the front door. | MEDIUM | Already in PROJECT. Low marginal cost given Kafka; high marginal value for landing-page conversion and portfolio impression. |
| 8 | **Flexible date range ("any Fri/Sat in the next 3 weeks")** | TableOne added multi-date but users report the filtering "incredibly poor." First-class date-range watches are a real gap. | LOW | Storage is trivial; predicate evaluator needs to iterate candidate dates. |
| 9 | **Alert delivery latency telemetry shown to user** | "Your last alert was sent 34s after the slot opened." Builds trust via transparency; no competitor does this. | LOW | PROJECT already tracks end-to-end timestamps; surface them in the management UI. |
| 10 | **Multiple party sizes in one watch** ("2 or 4 people, whichever opens first") | Real user behavior (anniversary planner: "2 for us, but 4 if friends join"). Currently nobody supports this well. | LOW | Store as array; OR-predicate. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem good but create legal, ethical, technical, or scope problems. Document here to prevent re-introduction.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Automated booking on user's behalf** | "Just book it for me when a table opens" — the obvious next step after the alert | (1) Requires storing Resy credentials or payment data — massive security/legal liability. (2) Violates Resy/OpenTable ToS (account automation). (3) NY Anti-Piracy Act and restaurant-industry enforcement are aggressively hostile to bot booking; no-show rate for bots is 4x normal. (4) Indistinguishable from the scalping apps we're explicitly *not*. | Deep-link + ~60s notification lead gives users a real chance to book themselves. Document in README why we won't cross this line. |
| **Paid marketplace / reservation resale** | "Let me sell my reservation if I can't make it" (ResX, Appointment Trader model) | (1) **Illegal in New York** under the Restaurant Reservation Anti-Piracy Act without a written agreement with each restaurant (civil penalties up to $1,000/day per violation). (2) Incompatible with the portfolio-grade ethical-scraping posture. (3) Destroys relationship with restaurants who might otherwise cooperate. | Stay a pure monitoring tool. Point out in the README that the product is designed *around* the scalping prohibition. |
| **Unverified / user-submitted restaurant data** | "Let me add any restaurant I want" | (1) No polling path for restaurants we haven't manually onboarded (Resy needs pre-authenticated browser context; OpenTable needs venue ID lookup). (2) Creates false negatives and support burden. (3) Encourages use on non-NYC restaurants outside MVP scope. | Curated coverage list + "request a restaurant" form → manual review → onboarding into the scheduler. |
| **Automated Resy account creation** | "Just spin up more accounts to poll harder" | Account automation is an explicit ToS violation and brings CAPTCHA / fingerprint detection hell. PROJECT already calls this out. | Manually-provisioned pool of polling accounts; rate caps at 80 req/min total. |
| **Group / shared watchlists at MVP** | "My partner and I want to share alerts" | Requires real accounts, permissions, fan-out messaging, conflict resolution — explodes scope for <5% of users. | Users share the SMS/email. Revisit as v2 with accounts. |
| **Tock and SevenRooms coverage at MVP** | "TableOne does four platforms" | Tock has lower NYC coverage than Resy/OpenTable and higher ToS risk; SevenRooms is venue-specific and fragmented. Both multiply scraper maintenance burden by 2x for <15% marginal coverage. | v2 after MVP validation, starting with Tock. PROJECT already defers Tock. |
| **Browser extension that auto-clicks "book" on Resy** | Same energy as auto-booking; "I'm faster than my phone" | Same problems as auto-booking plus: adversarial relationship with Resy's bot detection; guaranteed account ban cascade. | Keep the user in the loop; optimize notification latency and deep-link UX instead. |
| **Priority / paid-tier "fast lane" alerts** | Revenue model; mimics Resy Priority Notify (Amex link) | (1) Creates a two-tier fairness problem. (2) Incompatible with "free at MVP." (3) Adds billing complexity. | Freemium in v2: all alerts identical latency; paid tier unlocks more watches / SMS volume / pattern analytics. PROJECT already plans this. |
| **Predicting *which specific users* will cancel** | "Carbone's 8 PM table Tue is likely to cancel" targeted at an individual booking | Not knowable from public data; requires restaurant-side CRM access we'll never have. Also creepy. | Statistical patterns at the restaurant/party-size/day-of-week level only — exactly what PROJECT specifies. |
| **Notifications on every poll result** ("it's still booked, btw") | Users anxious the service is working | Creates notification fatigue; violates SMS cost discipline. | Surface poll-health via the activity feed and management page, not via per-user channels. |
| **Restaurant reviews / ratings / photos** | "While we're here, make it a yelp-alike" | Out of domain. Resy/OpenTable already do this and link is the destination anyway. | Link to Resy/OpenTable venue page from restaurant detail. |
| **Saved payment methods for users** | "Let me book faster through your site" | Would make us a merchant-of-record; out of scope and we don't handle the booking itself. | We never touch payment. Period. |
| **Coverage outside NYC at MVP** | "When are you coming to LA/SF/Miami?" | Each city multiplies scraper maintenance, restaurant onboarding, and legal surface area. PROJECT explicitly scopes NYC. | Waitlist signup for other cities; v2 expansion after MVP validation. |

## Feature Dependencies

```
Continuous polling engine (Resy Playwright + OpenTable httpx)
   └──required-by──> Stateful diff + confirmation poll
                         └──required-by──> availability.events emission
                                               ├──required-by──> Watch-matching service
                                               │                    └──required-by──> Notification delivery (email/SMS/push)
                                               │                                         └──required-by──> Deep-link to book
                                               └──required-by──> TimescaleDB time-series store
                                                                     ├──required-by──> Heatmap (needs ≥ 2 weeks data)
                                                                     ├──required-by──> Pattern detection model (needs ≥ 4–6 weeks data)
                                                                     │                    └──enhances──> Pre-alerts
                                                                     └──required-by──> Live SSE activity feed

Watchlist CRUD (HMAC management tokens)
   ├──required-by──> Watch creation (predicate: restaurant + dates + party sizes + time windows)
   ├──required-by──> Manage / pause / delete UI
   └──enhances──> Delivery-latency telemetry per watch

Restaurant coverage catalogue (curated list of ~50)
   ├──required-by──> Watch creation UI (search/browse)
   ├──required-by──> Poll scheduler (Redis ZSET)
   └──required-by──> Restaurant detail page (heatmap destination)

Public metrics + Grafana dashboard
   └──enhances──> Trust / portfolio signal (no hard runtime dependency)

[Automated booking] ──CONFLICTS-WITH──> [Ethical scraping posture] and [NY Anti-Piracy Act compliance]
[Paid marketplace] ──CONFLICTS-WITH──> [Free MVP] and [NY law]
[Shared watchlists] ──CONFLICTS-WITH──> [No-account UX]
```

### Dependency Notes

- **Heatmap requires ≥ 2 weeks of polling data:** Without a warm-up period, the heatmap shows empty cells and feels broken. Plan a "coming soon, collecting data" state for the first ~14 days post-launch. Ideally backfill from a pre-launch polling period before public launch.
- **Pattern detection (48h rule, inventory-load day, cancellation-peak) requires ≥ 4–6 weeks of data per restaurant:** Rules-based detection (e.g., "slots cluster at T-48h ± 3h") is feasible at 4 weeks; confidence grows to 6–8 weeks. ML approaches need more — defer.
- **Pre-alerts enhance (but don't require) pattern detection:** The system can ship rule-of-thumb alerts ("T-48h window approaching for your watched reservation") without a statistical model; upgrade later.
- **Delivery-latency telemetry depends on end-to-end timestamp tracking:** PROJECT already emits timestamps at each Kafka stage; just need to persist per-notification and surface in management UI.
- **Deep-link construction depends on stable Resy/OpenTable URL schemes:** Both are stable but watch for changes; integration tests should assert on deep-link format.
- **No-account UX conflicts with shared watchlists:** If we ever add shared watchlists (v2), we have to introduce accounts, which undoes the no-account differentiator. Keep them separate: shared watchlists is a *paid-tier v2 feature* that opts into an account.
- **SMS delivery conflicts with no-PII posture unless phone numbers are encrypted at rest:** PROJECT already specifies AES-256-GCM via pgcrypto; enforce that any code path touching phone numbers goes through the encrypted column.

## MVP Definition

### Launch With (v1 — the 8-week target)

Minimum viable product — what's needed to validate the "sub-60s notification for organic cancellations" thesis and differentiate from Resy Notify.

- [ ] **Continuous polling for ~50 curated NYC restaurants (Resy + OpenTable)** — without coverage, there's no product
- [ ] **Watch CRUD with restaurant + date-range + party-size(s) + time-window + channel preference** — the core user primitive, covering all the filter gaps Resy Notify has
- [ ] **Sub-60s p95 detection-to-notification pipeline with confirmation poll + idempotency guard** — the core value claim
- [ ] **Email + SMS + Web Push delivery with deep-links to Resy/OpenTable** — users need all three; SMS is the de facto "I'll actually see it" channel
- [ ] **HMAC-token-based no-account management UI (create / view / pause / delete)** — the zero-friction differentiator
- [ ] **Restaurant catalogue + detail page with basic heatmap (populated once ≥ 2 weeks data exists)** — SEO, trust, and the pattern-intelligence differentiator, even in skeleton form
- [ ] **Live SSE activity feed on homepage** — social proof, entertainment, conversion
- [ ] **Unsubscribe / STOP compliance (email + SMS)** — non-negotiable legal/ethical
- [ ] **Public read-only metrics link + Grafana dashboard** — portfolio differentiator and trust signal
- [ ] **Admin page for manual restaurant onboarding and poll health** — operational necessity

### Add After Validation (v1.x, weeks 9–16)

Features to add once the core is working and we have real user data.

- [ ] **Pattern-detection v1 (rules-based: 48h rule, inventory-load-day, cancellation-peak)** — trigger: ≥ 4 weeks of polling data across restaurants
- [ ] **Pre-alerts ("T-48h window opening in 6 hours for your watch")** — trigger: pattern detection shipped
- [ ] **Multiple party sizes per watch (OR-predicate)** — trigger: ≥ 10% of users creating two nearly-identical watches differing only by party size
- [ ] **Delivery-latency-per-watch telemetry in management UI** — trigger: support requests asking "did it fire?"
- [ ] **Restaurant coverage expansion to ~150 NYC restaurants** — trigger: MVP 50 are stable and the scheduler has headroom
- [ ] **"Request a restaurant" workflow with a notify-me-when-added list** — trigger: inbound requests exceed ~10/week
- [ ] **Monthly pattern summary digest email** — trigger: pattern detection shipped; retention data shows drop-off at 4 weeks

### Future Consideration (v2+, after PMF)

Features to defer until product-market fit is established.

- [ ] **User accounts + freemium paid tier (more watches, SMS volume, advanced patterns)** — when free-tier economics break
- [ ] **Shared watchlists (group/team)** — opt-in account feature in the paid tier
- [ ] **Coverage expansion to LA / SF / Miami / Chicago** — each city is a separate restaurant-onboarding and legal-review effort
- [ ] **Tock integration** — PROJECT already defers; revisit after Resy/OpenTable are rock-solid
- [ ] **SevenRooms integration for specific venue partnerships** — only if a restaurant group asks
- [ ] **Native iOS / Android apps** — only if PWA retention materially underperforms
- [ ] **Restaurant-side partner portal** (restaurants proactively publish cancellations to us) — the clean, ToS-compliant long-term play; requires sales motion
- [ ] **ML-based availability prediction** — after ≥ 6 months of time-series data; rules-based is likely sufficient for longer than expected
- [ ] **AI chat interface for natural-language watch creation** ("find me Carbone for 2 any Fri night in May") — trend-following but real

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Continuous Resy + OpenTable polling, ~50 restaurants | HIGH | HIGH | P1 |
| Sub-60s p95 notification pipeline (Kafka + confirmation poll) | HIGH | HIGH | P1 |
| Watch CRUD with time-window + party-size + date-range filters | HIGH | MEDIUM | P1 |
| Email + SMS + Web Push delivery + deep-links | HIGH | MEDIUM | P1 |
| HMAC-token no-account management UI | HIGH | LOW | P1 |
| Restaurant catalogue with coverage list | HIGH | LOW | P1 |
| Live SSE activity feed on homepage | MEDIUM | MEDIUM | P1 |
| Basic heatmap on restaurant detail page | MEDIUM | MEDIUM | P1 |
| Public Grafana / metrics page | MEDIUM | LOW | P1 (portfolio-critical) |
| STOP / unsubscribe compliance | HIGH | LOW | P1 (legal) |
| Admin page for restaurant onboarding + poll health | HIGH | MEDIUM | P1 (ops) |
| Pattern detection v1 (rules-based) | HIGH | HIGH | P2 |
| Pre-alerts (T-48h heads-up) | MEDIUM | MEDIUM | P2 |
| Multi-party-size watches | MEDIUM | LOW | P2 |
| Delivery-latency telemetry per watch | MEDIUM | LOW | P2 |
| Restaurant coverage to ~150 NYC | MEDIUM | MEDIUM | P2 |
| Monthly pattern digest email | LOW | LOW | P2 |
| User accounts + freemium | MEDIUM | HIGH | P3 |
| Group / shared watchlists | LOW | HIGH | P3 |
| Non-NYC city expansion | MEDIUM | HIGH | P3 |
| Tock / SevenRooms integration | LOW | HIGH | P3 |
| Native mobile apps | LOW | HIGH | P3 |
| ML-based prediction | MEDIUM | HIGH | P3 |
| AI chat interface for watch creation | LOW | MEDIUM | P3 |
| Automated booking | (anti-feature) | — | NEVER |
| Paid reservation marketplace | (anti-feature) | — | NEVER (illegal in NY) |
| Unverified user-submitted restaurants | (anti-feature) | — | NEVER |

**Priority key:**
- **P1:** Must have for launch — the 8-week MVP scope
- **P2:** Should have, add in v1.x once validation signals exist
- **P3:** Future consideration, deferred until PMF
- **NEVER:** Explicitly out of scope — see anti-features

## Competitor Feature Analysis

| Feature | Resy Notify | TableOne ($18/mo) | ReservationFinder.io ($10–20/mo) | Appointment Trader (illegal in NY) | Dorsia ($175–$25K/yr) | Mise en Place (our plan) |
|---------|-------------|-------------------|----------------------------------|------------------------------------|-----------------------|--------------------------|
| Price | Free | $18/mo | $10–20/mo | Per-reservation fees | $175–$25,175/yr membership + meal minimums | **Free at MVP; freemium v2** |
| Notification latency | Batched, minutes–hours | Near-real-time (unspecified) | "Instant" (unspecified) | N/A (marketplace) | N/A (concierge) | **p95 ≤ 60s, published and measured** |
| Resy coverage | Yes (native) | Yes | Yes | Yes (resells) | Yes (resells) | Yes (Playwright) |
| OpenTable coverage | No | Yes | Yes | Yes | Yes | Yes (httpx GraphQL) |
| Tock / SevenRooms | No | Yes | Yes | Partial | Partial | v2 |
| Time-window filter | No (fires on any slot) | Yes (but reports poor filtering post-UI-change) | Yes | N/A | N/A | Yes, first-class |
| Multi-date / date-range | Limited | Yes (reports mixed) | Yes | N/A | N/A | Yes, first-class |
| Multi-party-size per watch | No | No | No | N/A | N/A | v1.x |
| Account required | Yes (Resy account) | Yes + payment | Yes + payment | Yes | Yes (invite/paid) | **No — HMAC tokens** |
| Auto-booking | No | No | No | N/A | Concierge-booked | **Never (anti-feature)** |
| Reservation resale | No | No | No | Yes (core) | Yes (core) | **Never (anti-feature, NY illegal)** |
| Pattern heatmap / history | No | No | No | No | No | **Yes — unique differentiator** |
| Pre-alerts (pattern-based) | No | No | No | No | No | **v1.x — unique differentiator** |
| Live activity feed | No | No | No | No | No | **Yes — unique on homepage** |
| Public uptime / metrics | No | No | No | No | No | **Yes — portfolio signal** |
| SMS alerts | Yes | Yes | Yes (Pro) | N/A | N/A | Yes (Twilio) |
| Web Push | No (Resy has push in app only) | Push in native app | Email/SMS | N/A | N/A | Yes (VAPID in PWA) |
| Legal posture | First-party, no issues | Third-party monitor, scraping gray area | Third-party monitor, scraping gray area | **Illegal in NY** | Gray; pre-pay sidesteps resale law | Transparent README; monitor-only; no booking or resale |

## Key Gaps Mise en Place Exploits

1. **Speed ceiling on Resy Notify** is the canonical complaint; it's structurally slow because it's batched. A measured p95 ≤ 60s number on the homepage is a direct wedge.
2. **Filter precision on Resy Notify** — firing for any slot, any time — is the second canonical complaint. First-class time-window + date-range + party-size(s) solves it cheaply.
3. **Pricing on paid alternatives.** Free, with transparent rate-limiting and monitoring, undercuts TableOne ($216/yr) and Dorsia (up to $25K/yr) simultaneously while capturing different segments.
4. **No one publishes pattern intelligence.** A heatmap + 48h-rule analytics per restaurant is a genuine first, drives SEO, and makes the product useful *without* a watch ever firing.
5. **Signup friction.** No competitor offers a true no-account flow; HMAC tokens turn "try it" into a 30-second action.
6. **Post-scalping-ban positioning.** With Appointment Trader illegal in NY and Dorsia under "fun coupon trap" scrutiny, a monitor-only, ethically-scraped, restaurant-respecting product is positively differentiated in a way it wasn't two years ago.
7. **Portfolio / systems-engineering signal.** The public Grafana dashboard, the README's legal and rate-limit reasoning, and the open architecture are a differentiator specifically for the recruiter persona — no consumer-side competitor even tries.

## Sources

- [Resy Notify help doc](https://helpdesk.resy.com/what-is-notify-and-how-does-it-work-BJrJzPQLu) — official Notify behavior (HIGH confidence)
- [Resy blog — How to Snag Hard-to-Get Tables with Notify](https://blog.resy.com/2021/09/notify/) — first-party description of Notify (HIGH)
- [ReservationFinder.io — Resy Notify alternatives guide](https://www.reservationfinder.io/guides/resy-notify-alternatives) — competitive alternatives listing (MEDIUM)
- [ReservationFinder.io — Resy alerts, faster than Notify](https://www.reservationfinder.io/resy-alerts) — latency claims re: Resy Notify batching (MEDIUM)
- [ReservationFinder.io — Resy guide 2026](https://www.reservationfinder.io/guides/resy-guide) — Priority Notify via Amex, cancellation timing (MEDIUM)
- [TableOne Reservations — App Store listing](https://apps.apple.com/us/app/tableone-reservations/id6448799631) — coverage, pricing, review sentiment (HIGH)
- [TableOne homepage](https://tableone.app/) — 230+ restaurants, $18/mo / $99/yr pricing (HIGH)
- [W42ST — TableOne launch coverage](https://w42st.com/post/new-dinner-reservation-app-new-york-resy-opentable/) — founder background, positioning (MEDIUM)
- [Appointment Trader homepage](https://appointmenttrader.com/) — marketplace model (HIGH)
- [Holland & Knight — NY curbs scalping of restaurant reservations](https://www.hklaw.com/en/insights/publications/2025/02/new-york-curbs-scalping-of-restaurant-reservations) — Restaurant Reservation Anti-Piracy Act, Feb 17 2025, $1,000/day penalties (HIGH)
- [Gothamist — NY law aims to kill black market reservations](https://gothamist.com/news/new-york-law-aims-to-kill-black-market-for-restaurant-reservations) — legislative context (HIGH)
- [Columbia News Service — Appointment Trader testing NY law with AI](https://columbianewsservice.com/2025/07/28/new-york-banned-reservation-resales-now-appointment-trader-is-testing-the-law-with-ai/) — post-ban relaunch (MEDIUM)
- [Trustpilot — Appointment Trader reviews](https://www.trustpilot.com/review/appointmenttrader.com) — UX and support complaints (MEDIUM)
- [Dorsia FAQ](https://www.dorsia.com/faq) — membership tiers, pre-pay model (HIGH)
- [New York Hots — Dorsia $5,000 fun coupon trap](https://newyorkhots.com/dining/2026/01/dorsia-nyc-review-the-5000-fun-coupon-trap-and-the-death-only-refund-policy/) — refund policy criticism (MEDIUM)
- [Yahoo Finance — Dorsia $25K membership](https://finance.yahoo.com/news/membership-restaurant-reservation-app-dorsia-092901248.html) — pricing, member count, revenue (MEDIUM)
- [Bloomberg via BNN — Restaurant owners fed up with reservation-hoarding bots](https://www.bnnbloomberg.ca/restaurant-owners-are-fed-up-with-reservation-hoarding-bots-1.1989295) — industry hostility (MEDIUM)
- [Resy blog — What restaurant operators wish you knew about reservation fraud](https://blog.resy.com/for-restaurants/restaurant-reservation-fraud/) — bot no-show rate (4x normal) (HIGH)
- [NBC News — NYC reservations selling for hundreds](https://www.nbcnews.com/news/us-news/reservations-top-new-york-city-restaurants-are-selling-hundreds-dollar-rcna151702) — demand context for Carbone, Don Angie (MEDIUM)
- [CNN Business — Reservation wars 2026](https://us.cnn.com/2026/03/17/business/restaurant-reservations-apps-markets) — current market state (MEDIUM)
- [ResX — App Store listing](https://apps.apple.com/us/app/resx/id6444920738) — cancellation exchange model (MEDIUM)
- [MouseDining](https://mousedining.com/) — adjacent product (Disney dining alerts) for UX pattern reference (LOW)

---
*Feature research for: restaurant reservation availability monitoring platform*
*Researched: 2026-04-20*
