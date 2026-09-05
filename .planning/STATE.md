---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
current_phase: 2
current_phase_name: State Machine & Event Pipeline
status: executing
stopped_at: Completed 02-02-shared-kernel-expedite-schema-PLAN.md
last_updated: "2026-09-05T05:38:35.925Z"
last_activity: 2026-09-05
last_activity_desc: Phase 2 execution started
progress:
  total_phases: 2
  completed_phases: 0
  total_plans: 10
  completed_plans: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-20)

**Core value:** When a coveted table opens, the watching user is notified fast enough to actually book it — p95 detection-to-notification latency <= 60 seconds.
**Current focus:** Phase 2 — State Machine & Event Pipeline

## Current Position

Phase: 2 (State Machine & Event Pipeline) — EXECUTING
Plan: 3 of 4
Status: Ready to execute
Last activity: 2026-09-05 — Phase 2 execution started

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| — | — | — | — |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01 P03 | 349 | 4 tasks | 6 files |
| Phase 01 P05 | 407 | 4 tasks | 16 files created + 5 modified |
| Phase 01 P06 | 187 | 2 tasks | 3 files |
**Per-Plan Metrics:**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| Phase 2 P01 | 13 | 3 tasks | 17 files |
| Phase 2 P2 | 14 | 3 tasks | 14 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap: Phase ordering follows research build order — OpenTable before Resy so Playwright risk cannot block State Machine or Notifications.
- Roadmap: Twilio 10DLC registration is a Phase 1 Day-1 admin task (multi-week lead time gates Phase 4 SMS).
- Roadmap: 12-hour Playwright soak test (PERF-05) is a hard gate before Resy goes live in production.
- 01-03 delivered all autonomous pre-conditions: evidence-file shells for Twilio/Domain/GCP/Resy with STATUS: pending-admin-action banners, real HMAC_MGMT_SECRET_V1 + VAPID keypair generated locally into gitignored .env, and 55-entry scripts/seed/restaurants.yml (23 NYC neighborhoods, 30 cuisine types). Actual Twilio 10DLC submission, domain purchase, GCP project creation, and Resy cookie capture are BLOCKED ON HUMAN ACTION and listed verbatim in 01-03-SUMMARY.md.
- Used cryptography.ec SECP256R1 directly rather than py_vapid for VAPID generation (py_vapid 1.9.x API incompatible with cryptography >=43 EC keys). Output format matches VAPID RFC 8292: 65-byte uncompressed P-256 public point + 32-byte big-endian private scalar, both b64url-no-pad.
- 01-05 corrected a plan-text bug: REQUIRED_TOPICS in services/poller/main.py uses the 5 Named-Symbol topics (availability.raw, availability.events, polls.completed, notifications.queued, notifications.sent) rather than the plan-text's watchlist.commands/watchlist.events/notifications.delivered (which do not exist in scripts/create_topics.py).
- 01-05 OpenTable DevTools spike deferred to human action: placeholder endpoint/headers/fixtures seeded in services/poller/sources/opentable/ with [ASSUMED]/TODO(spike) markers so adapter code + respx-mocked tests work today. Live capture on opentable.com required before Plan 06 PERF-02 gate to confirm >= 99% success rate under the real endpoint.
- 01-06: PERF-02 tooling complete (check_poll_success.py with time_bucket SELECT + exit 0/1/2 gate, README legal + Kafka tradeoff + runbook, runbook procedure filled). 24h observation run (T3/T4) BLOCKED ON HUMAN ACTION; cannot declare PERF-02 pass or Phase 01 complete until DevTools spike + 24h run + FD evidence gathered.
- [Phase ?]: 02-01: DiffEngine is a pure functional core — StateStore Protocol, no clock read, no entropy, no IO; a source-grep unit test enforces it permanently (D-49, research Pitfall 8).
- [Phase ?]: 02-01: SlotState uses enum.StrEnum rather than (str, Enum) — ruff UP042 rejects the mixin form on py312; semantics are identical.
- [Phase ?]: 02-01: OPENTABLE_SUCCESS_RESPONSE carries seatingTypes [bar, standard], so one timeslot yields TWO slots and the confirming poll emits TWO events; Expedite is de-duplicated to one per restaurant per poll (ZSET score is per job, not per slot).
- [Phase ?]: 02-01: Requirements STATE-02/04/06 left Pending — this plan ships only the pure core; the SET NX EX claim, consumer shell and replay script land in 02-02/02-03/02-04.
- [Phase ?]: 02-02: The expedite handshake is server-side atomic — EXPEDITE_POLL_LUA does ZSCORE + conditional ZADD XX LT in one round trip; XX prevents resurrecting an in-flight job into a duplicate concurrent poll, LT prevents pushing an already-sooner poll later.
- [Phase ?]: 02-02: Every cast(Awaitable[T], ...) for redis-py HASH commands lives in shared/redis_keys.py helpers, so services/state_machine/store.py needs none and no type-suppression comment is used anywhere (research Pitfall 3).
- [Phase ?]: 02-02: availability_events PK is (time, event_id); restaurant_id left the PK because every slot confirmed by one poll shares that poll's time and collided on the second slot (research B-3).
- [Phase ?]: 02-02: availability_events.restaurant_id is the SOURCE PLATFORM id, recorded via COMMENT ON COLUMN and an ORM docstring; join key against restaurants is (source, platform_id) (D-52).
- [Phase ?]: 02-02: services/poller/config.py freezes env vars at import time — integration modules that import poller code must evict services.poller.* from sys.modules on teardown or they silently pin later tests to localhost defaults.
- [Phase ?]: 02-02: Requirements STATE-01/03/05 left Pending — this plan ships the primitives and schema; the state store, consumer shell and persistence land in 02-03.

### Pending Todos

None yet.

### Blockers/Concerns

**Existential risks flagged by research — track throughout execution:**

- [Phase 1] Twilio 10DLC registration must be submitted Day 1 of Week 1 or SMS will not be available at Phase 4 demo time.
- [Phase 3] Resy soft-ban canary and tf-playwright-stealth effectiveness are LOW-confidence empirically — validate in first week of Phase 3.
- [Phase 3] 12-hour Playwright soak test gates Resy production rollout; do not skip.
- [Phase 4] iOS PWA Web Push requires real-device test (not simulator) — subscription silently revokes after ~3 pushes if service worker `push` handler does not wrap entire async chain in `event.waitUntil(...)`.
- [Phase 4] Every idempotency key must use atomic `SET key value NX EX ttl` — zero occurrences of two-command `SETNX` + `EXPIRE` in source tree.
- [Phase 7] Public read-only Grafana dashboard link is launch-blocking for portfolio credibility, not optional polish.
- [Phase 1 CLOSE] PERF-02 24h observation run (01-06 T3/T4) requires OpenTable DevTools spike (01-05 T1) + infra up + 24h wall-clock wait. Full runbook at docs/runbooks/perf02-24h-log.md. Phase 01 cannot close until this run passes + admin gates from 01-03 complete.

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-09-05T05:38:35.919Z
Stopped at: Completed 02-02-shared-kernel-expedite-schema-PLAN.md
Resume file: None

**Planned Phase:** 01 (foundation-admin-pre-conditions-opentable-polling) — 6 plans — 2026-04-21T22:22:04.644Z
