# Phase 1: Foundation, Admin Pre-conditions & OpenTable Polling - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-21
**Phase:** 01-foundation-admin-pre-conditions-opentable-polling
**Areas discussed:** Docker Compose scope & local dev UX, Prometheus & observability in P1, Restaurant seed source & count, Polling cadence & ZSET crash-safety

---

## Gray Area Selection

**Question:** Which gray areas do you want to discuss for Phase 1?

| Option | Description | Selected |
|--------|-------------|----------|
| Restaurant seed source & count | ≥50 NYC restaurants per FOUND-03 & SC3 — where does the list come from? What in-repo format? Is '50' a hard exit gate or a soft target? | ✓ |
| Polling cadence & ZSET crash-safety | Fixed interval vs Tier-3 default; ZSET visibility-timeout vs best-effort | ✓ |
| Docker Compose scope & local dev UX | Infra-only vs infra+services; secrets; task runner | ✓ |
| Prometheus & observability in P1 | PERF-02 via Prometheus vs SQL on poll_log; structlog timing; OTel | ✓ |

**User's choice:** All four selected.

---

## Docker Compose scope & local dev UX

### Q: What goes in `ops/docker-compose.yml` for local dev?

| Option | Description | Selected |
|--------|-------------|----------|
| Infra-only, services on host | Kafka + Redis + Postgres+Timescale + Kafka UI. Python services on host via `uv run`. Fastest iteration, clearest stack traces. | ✓ |
| Infra + services with hot-reload | Everything in compose with mounted volumes + `uvicorn --reload`. One-command up; more moving parts; slower reload. | |
| Infra + services, no hot-reload | Everything in compose, rebuild on change. Matches prod most closely; painful dev loop. | |

**User's choice:** Infra-only, services on host (Recommended)
**Notes:** Matches ARCHITECTURE.md guidance; Phase 7 adds per-service production Dockerfiles.

### Q: Secrets / env vars for local dev?

| Option | Description | Selected |
|--------|-------------|----------|
| .env + .env.example | Gitignored `.env` loaded by `pydantic-settings`; committed `.env.example` documents shape. | ✓ |
| direnv + .envrc | Auto-loads on `cd`; requires direnv install. | |
| Doppler / 1Password CLI | Cloud vault at runtime; overkill at MVP. | |

**User's choice:** .env + .env.example (Recommended)

### Q: Task runner / command facade?

| Option | Description | Selected |
|--------|-------------|----------|
| Makefile | `make up/down/migrate/seed/test/lint`. Ubiquitous, zero install, self-documenting via `make help`. | ✓ |
| `just` (justfile) | Modern Make replacement; nicer syntax; requires install. | |
| npm scripts + uv scripts only | No top-level runner; splits cheat-sheet across ecosystems. | |

**User's choice:** Makefile (Recommended)

---

## Prometheus & observability in P1

### Q: How do we verify PERF-02 (≥99% poll success hourly) at Phase 1 exit?

| Option | Description | Selected |
|--------|-------------|----------|
| SQL query on poll_log | SQL against `poll_log` hypertable. Zero extra infra in P1. Grafana in Phase 7 reads the same table. | ✓ |
| prometheus-client counters + local Grafana in compose | Full dashboard stack from day 1. Adds two containers + dashboard provisioning. | |
| Both — /metrics endpoint + no dashboards | Expose counters in P1, defer dashboards. Low incremental cost. | |

**User's choice:** SQL query on poll_log (Recommended)

### Q: Structured logging — wire structlog in P1 or later?

| Option | Description | Selected |
|--------|-------------|----------|
| Wire structlog from P1 | `shared/telemetry.py` with JSON renderer + stdlib bridge. Zero-effort P7 Cloud Logging/Loki ingestion. | ✓ |
| Defer to Phase 7 | Stdlib logging in P1, swap at deploy time. Creates churn across every service in P7. | |

**User's choice:** Wire structlog from P1 (Recommended)

### Q: Tracing / OpenTelemetry — anywhere in MVP?

| Option | Description | Selected |
|--------|-------------|----------|
| Defer entirely to post-MVP | Metrics + structured logs + Sentry cover MVP. OTel instrumentation still beta. | ✓ |
| Minimal OTel in P1 | SDK with noop exporter now. Low cost but unused ceremony. | |

**User's choice:** Defer entirely to post-MVP (Recommended)

---

## Restaurant seed source & count

### Q: Where does the ≥50-restaurant NYC catalog come from?

| Option | Description | Selected |
|--------|-------------|----------|
| Hand-curated from public lists | You pick ~50 from Eater/Infatuation/Resy/OpenTable top lists; manually capture platform IDs + metadata. Highest-quality list; tightest portfolio narrative. | ✓ |
| Scripted extraction from OpenTable search | One-shot script pulls from OpenTable public search. Fast; list ranked by OpenTable popularity, not "hard-to-book". | |
| Hybrid: scripted pull, hand-filtered | Scripted superset, hand-curated keep list. Best-of-both; ~2x tooling work. | |

**User's choice:** Hand-curated from public lists (Recommended)

### Q: Seed data format committed to the repo?

| Option | Description | Selected |
|--------|-------------|----------|
| YAML + idempotent seed script | `scripts/seed/restaurants.yml` + `scripts/seed_restaurants.py` upsert. Diff-friendly, comment-friendly. | ✓ |
| SQL fixture via Alembic data migration | Migration with inline INSERT...ON CONFLICT. Atomic but painful to edit. | |
| JSON + seed script | Machine-friendly, human-hostile (no comments, trailing commas). | |

**User's choice:** YAML file + idempotent seed script (Recommended)

### Q: Phase 1 exit gate — hard count vs soft target?

| Option | Description | Selected |
|--------|-------------|----------|
| Hard 50 for P1 exit | SC3 interpreted strictly. All metadata columns populated. ~4–6 hours of curation inside P1. | ✓ |
| Soft ≥10 for P1, reach 50 before Phase 3 | Faster P1 exit; SC3 technically not met at P1. | |
| Hard 50 but allow missing cover photos / price tier | 50 rows, all platform IDs, but other fields nullable. Satisfies SC3 loosely. | |

**User's choice:** Hard 50 for P1 exit (Recommended)

---

## Polling cadence & ZSET crash-safety (auto-selected during auto mode)

### Q: Poll cadence for Phase 1?

| Option | Description | Selected |
|--------|-------------|----------|
| 90s fixed + ±15% jitter | POLL-03 floor; jitter future-proofs Phase 3 tier math. | ✓ (auto, recommended default) |
| 3min fixed (Tier-2 default) | Gentler on OpenTable; less realistic demo feel. | |
| 10min fixed (Tier-3 default) | Very sparse; demos look dead. | |

**Selected:** 90s fixed + ±15% jitter — auto-selected as recommended default.

### Q: ZSET crash-safety level?

| Option | Description | Selected |
|--------|-------------|----------|
| Visibility-timeout + in-flight ZSET (full pattern) | Matches ARCHITECTURE.md Pattern 1; Lua script + reaper. Portfolio-narrative essential. | ✓ (auto, recommended default) |
| Best-effort pop + re-enqueue | Simpler; loses jobs on worker crash. | |
| BZPOPMIN single-worker | Simplest; no horizontal scale. | |

**Selected:** Visibility-timeout + in-flight ZSET — auto-selected as recommended default.

### Q: Poll unit — what does the scheduler enqueue?

| Option | Description | Selected |
|--------|-------------|----------|
| (source, restaurant_id) pairs; poller fans out date×party internally | Matches OpenTable batch-search behavior; one GraphQL call per poll. | ✓ (auto, recommended default) |
| (restaurant, date, party) triples | Scales with queue size; over-engineered for P1. | |

**Selected:** (source, restaurant_id) pairs — auto-selected as recommended default.

### Q: Date/party matrix for Phase 1?

| Option | Description | Selected |
|--------|-------------|----------|
| Next 7 days × party sizes [2, 4], per-restaurant overridable | Most common bookings; bounds data volume; Phase 2 diff engine gets realistic input. | ✓ (auto, recommended default) |

**Selected:** Next 7 days × party sizes [2, 4] — auto-selected as recommended default.

### Q: Confirmation poll in Phase 1?

| Option | Description | Selected |
|--------|-------------|----------|
| No — raw emit only; confirmation is Phase 2 | State machine owns confirmation (STATE-03). | ✓ (auto, recommended default) |

**Selected:** No — auto-selected as recommended default. Phase 1 is raw-emit only.

---

## Claude's Discretion

The following were left to Claude's discretion (captured in CONTEXT.md § Claude's Discretion):
- File naming within services
- Specific structlog processor chain
- Pydantic field names / docstrings
- `AsyncClient` timeout values
- Log level defaults
- Makefile target wording
- Which Kafka UI tool in compose (redpanda-console / kafka-ui / kafdrop)
- `.env.example` formatting
- Visibility-timeout reaper loop frequency
- Lua script error handling details

## Deferred Ideas

Captured in CONTEXT.md § Deferred:
- Watchlist-driven tiered cadence → Phase 3
- Resy + Playwright → Phase 3
- State machine + confirmation + replay → Phase 2
- Prometheus + Grafana dashboards → Phase 7
- Terraform + Cloud Run Worker Pools + Memorystore → Phase 7
- docker-compose E2E integration test → Phase 7
- HMAC token rotation mechanism → Phase 5
- OpenTelemetry → post-MVP
- E2E tests directory → Phase 7
- Per-service production Dockerfiles → Phase 7
