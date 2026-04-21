# Phase 1: Foundation, Admin Pre-conditions & OpenTable Polling - Context

**Gathered:** 2026-04-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up the monorepo + local Docker infra (Kafka KRaft, Redis, Postgres+TimescaleDB), start the Day-1 Twilio A2P 10DLC / domain / GCP / secrets admin clock, and get `availability.raw` Kafka messages flowing continuously from OpenTable httpx polling of ≥50 curated NYC restaurants via a Redis ZSET distributed scheduler.

**In scope:** monorepo scaffold, Docker Compose infra, Alembic schema + TimescaleDB hypertables, 50-restaurant seed catalog, 5 Kafka topics with retention, Twilio 10DLC submission, domain + GCP + Resy-account + VAPID + HMAC secrets provisioning, Redis ZSET scheduler, OpenTable httpx poller, `availability.raw` emission, `poll_log` persistence.

**Out of scope (deferred to later phases):**
- State machine / diff engine / confirmation poll → Phase 2
- Resy / Playwright fleet / fingerprint rotation / soft-ban canary → Phase 3
- Watchlist tiered cadence (60s/3min/10min) → Phase 3 (POLL-02)
- Notification pipeline → Phase 4
- Watchlist CRUD / FastAPI / SSE → Phase 5
- Pattern model / PWA / heatmap → Phase 6
- GCP deploy / Terraform / Grafana dashboard / README polish → Phase 7

</domain>

<decisions>
## Implementation Decisions

### Stack (carried forward from `.planning/research/STACK.md` — locked)
- **D-01:** Python 3.12.x with `uv` for dependency management and Docker layer caching; single `pyproject.toml` at repo root with dependency groups (`dev`, etc.). No Poetry, no requirements.txt.
- **D-02:** Kafka 3.8.x in **KRaft mode** (no ZooKeeper); single broker acceptable at MVP; `aiokafka==0.13.0` client; `acks=all` producer config; persistent volume for broker log dir.
- **D-03:** Redis 7.2+ with `redis-py==7.4.0` async (`import redis.asyncio as redis`); `maxmemory-policy = noeviction` (never `allkeys-lru` — would silently evict idempotency keys mid-TTL).
- **D-04:** Postgres 16 + TimescaleDB 2.17 self-hosted (Cloud SQL does not support the Timescale extension — Phase 7 will run Timescale on the same GCE VM as Kafka or a sibling); SQLAlchemy 2.0 async + `asyncpg` for the app hot path; `psycopg==3.3.3` sync for Alembic migrations.
- **D-05:** `httpx==0.28.1` with **one shared `AsyncClient` per worker** initialized in lifespan/startup, explicit `Limits(max_connections=100, max_keepalive_connections=20)`, `tenacity==9.1.4` for retry/backoff. Never create per-poll clients (FD leak — Pitfall 9).
- **D-06:** Pydantic v2 models in `shared/events.py` are the single source of truth for every Kafka message schema; `.model_dump_json()` on the wire; **no Confluent Schema Registry** at MVP.
- **D-07:** Monorepo layout per `ARCHITECTURE.md`: `services/{poller,state_machine,notifier,api}/`, `shared/` (events, kafka factories, `redis_keys.py`, db models, telemetry), `web/` (Next.js, later phase), `migrations/` (Alembic), `ops/` (docker-compose, grafana, terraform), `scripts/` (`replay_raw.py`, `seed_restaurants.py`, `bench_latency.py`), `tests/{unit,integration,e2e}/`.

### Local dev & ops layout (discussed)
- **D-08:** `ops/docker-compose.yml` runs **infra only** (Kafka KRaft, Redis, Postgres+TimescaleDB, plus a Kafka UI such as redpanda-console or kafka-ui for dev observability). Python services run on the host via `uv run python -m services.poller` (etc.) for instant reload and clean stack traces. Production Dockerfiles for each service are added later in Phase 7.
- **D-09:** Local secrets via **`.env` (gitignored) + committed `.env.example`** documenting the shape; loaded by `pydantic-settings` with `env_file=".env"`. Same file consumed by docker-compose `env_file:` for infra env (e.g. Postgres creds). No direnv, no Doppler, no vault at MVP — Phase 7 GCP Secret Manager replaces `.env` in prod.
- **D-10:** Top-level **`Makefile`** as the command facade: `make up` / `make down` (infra), `make migrate` (Alembic), `make seed` (restaurants), `make test` / `make test-integration`, `make lint`, `make fmt`, `make poll` (run poller on host), `make help` for self-documentation. Ubiquitous, zero install, Unix-portable.

### Observability baseline (discussed)
- **D-11:** **PERF-02 (≥99% poll success hourly) is verified by a SQL query against the `poll_log` TimescaleDB hypertable**, not via Prometheus at P1. Every poll writes `(time, restaurant_id, source, status, latency_ms, http_status, error)` to `poll_log`; the P1-exit check is `SELECT time_bucket('1 hour', time), success::float/total FROM poll_log ... WHERE time >= NOW() - INTERVAL '24 hours'`. Prometheus + Grafana dashboards are deferred to Phase 7 (they read from the same authoritative `poll_log` table via `pg_exporter` or a custom collector).
- **D-12:** **`structlog==25.5.0` wired from day 1** in `shared/telemetry.py` (JSON renderer in prod, ConsoleRenderer in dev based on `ENV`). All services import `log = structlog.get_logger(__name__)`. Phase 7 Cloud Logging / Loki ingestion is zero-effort because output is already JSON. Cheap to add now, painful to retrofit.
- **D-13:** **OpenTelemetry deferred entirely to post-MVP.** Metrics (via `poll_log` SQL at P1, Prometheus at P7) + structlog + Sentry (Phase 7) cover the MVP observability story. OTel instrumentation packages are still beta per STACK.md research.

### Restaurant seed catalog (discussed)
- **D-14:** **Hand-curated from public lists** — you pick ~50 NYC restaurants from Eater NYC Essential 38, Infatuation Hit List, Resy / OpenTable "Top Reserved" / "Best of" New York pages. For each restaurant manually capture: `name`, `slug`, `neighborhood`, `cuisine`, `price_tier` (1–4), `cover_photo_url`, `opentable_rid` (numeric), `resy_venue_id` (stored now for Phase 3, even though unused at P1). Narrative value of "the tables everyone wants" > scripted convenience; the manual ID lookup also surfaces platform URL/ID schemes you need in Phase 3.
- **D-15:** Seed data lives at `scripts/seed/restaurants.yml` (human-editable, diff-friendly, comment-friendly). `scripts/seed_restaurants.py` is an **idempotent upsert** keyed on `(source='opentable', platform_id=rid)` (and `(source='resy', platform_id=venue_id)` when Phase 3 uses it). Rerunning `make seed` is safe. A schema change + data change is a migration + YAML update; the script is stable.
- **D-16:** **Hard 50-restaurant count is a P1 exit gate.** SC3 says "≥50 seeded with platform IDs, neighborhood, cuisine, price tier, cover photo." All five columns must be populated (no NULL backfill shortcut) because Phase 2's diff engine and Phase 6's frontend both consume this metadata and we want realistic diff-engine input. Budget ~4–6 hours for the curation work inside Phase 1.

### Polling cadence, ZSET design, and poll unit (discussed)
- **D-17:** **Phase 1 polls every restaurant at 90s ± 15% jitter**, the POLL-03 floor. Watchlist-driven tiered cadence (60s/3min/10min based on active-watch count) is Phase 3 (POLL-02) — at P1 there are no watchlists. Jitter is trivial to add now (`next_poll = now + 90 + random.uniform(-13.5, 13.5)`) and avoids any rhythmic request pattern from day 1.
- **D-18:** **Redis ZSET scheduler uses the full visibility-timeout pattern** from ARCHITECTURE.md Pattern 1:
  - Main ZSET: `sched:polls` — `score = next_poll_epoch_ms`, member = compact job descriptor `{source}:{restaurant_id}` (e.g. `opentable:42`).
  - In-flight ZSET: `sched:polls:inflight` — entries moved here atomically at pop time with `score = now + visibility_timeout_ms`.
  - Pop + move is a single Lua script (`ZRANGEBYSCORE … LIMIT 0 1` → `ZREM` → `ZADD inflight`), never two commands.
  - A reaper loop periodically scans `sched:polls:inflight` for entries past their visibility deadline and re-enqueues them to `sched:polls` (worker crash recovery).
  - Visibility timeout: **60 seconds** (OpenTable polls should complete in <5s; 60s gives ample buffer for slow-network or long-GC tails before another worker steals the job).
  - On successful poll completion, worker `ZREM`s its in-flight entry and `ZADD`s the next poll to `sched:polls` with `score = now + interval + jitter`.
  - Redis key patterns and TTLs all live in `shared/redis_keys.py` as constants (enforces documentation-at-compile-time).
- **D-19:** **The scheduler enqueues `(source, restaurant_id)` pairs**, not `(restaurant, date, party)` triples. The poller internally fans out a single restaurant request to OpenTable's widget GraphQL over the configured **date × party matrix**: `next 7 days × party sizes [2, 4]` as P1 defaults. Per-restaurant overrides (`date_range_days`, `party_sizes` columns on `restaurants`) are populated by the seed but fall back to the global default. One poll = one GraphQL call = one `availability.raw` Kafka message carrying the slots for all date/party combos observed; this matches OpenTable's batch-search behavior and minimizes request count.
- **D-20:** **Phase 1 does NOT implement the confirmation poll.** State machine and confirmation-at-t+8s are Phase 2 concerns (STATE-03). Phase 1 is raw-emit only: poll → write `poll_log` row → publish `availability.raw` → update scheduler. No diff logic, no transition detection, no `availability.events` emission.

### Admin pre-conditions (not software decisions — admin tasks that must start Day 1)
- **D-21:** **Twilio A2P 10DLC Standard Campaign submission on Day 1 Week 1** per `docs/runbooks/twilio-10dlc-setup.md`. Toll-free number registered in parallel as fallback. Target status "Registered" by Phase 4 (SMS), but submission itself is the P1 gate — not approval. See Pitfall 5.
- **D-22:** `mise.place` domain registered (Namecheap / Cloudflare / Google Domains — user's preference).
- **D-23:** GCP project provisioned with Artifact Registry + Secret Manager APIs enabled. No Terraform yet — that's Phase 7. Just `gcloud projects create` + API enablement.
- **D-24:** **Manually created pre-authenticated Resy accounts** (FOUND-06). Stored as encrypted secrets (GCP Secret Manager in prod; `.env` + explicit gitignore in dev; never in source). **Cookies live in Playwright context memory only** — never DB-persisted (see Pitfall 8 / Anti-Pattern 7). Phase 3 will use these; P1 just captures and stores them.
- **D-25:** VAPID keypair generated **once** via `pywebpush.generate_vapid_keys()` or `openssl ecparam -genkey -name prime256v1`; private key → Secret Manager / `.env`; public key → frontend env (Phase 6). One keypair per environment, never rotated without forcing user re-subscription.
- **D-26:** HMAC management-token secret = `secrets.token_bytes(32)` (32 random bytes, NOT a human-chosen string); stored in Secret Manager / `.env`. Rotation mechanism (dual-version verification during 7-day overlap) is wired in Phase 5 — P1 just generates v1 of the secret.

### Kafka topic configuration
- **D-27:** Five topics created during P1 bootstrap via a `scripts/create_topics.py` script (idempotent; uses `aiokafka.admin.AIOKafkaAdminClient`):
  - `availability.raw` — 1 partition, retention 24h (`86400000 ms`)
  - `availability.events` — 1 partition, retention 7d (`604800000 ms`) (topic created in P1; emission starts P2)
  - `notifications.queued` — 1 partition, retention 30d (topic created in P1; emission starts P4)
  - `notifications.sent` — 1 partition, retention 30d (topic created in P1; emission starts P4)
  - `polls.completed` — 1 partition, retention 7d (P1 emission starts immediately alongside `poll_log` writes — useful for future real-time poll-success dashboards)
- **D-28:** Replication factor **1** at MVP (single-broker); documented in README as an explicit "honest tradeoff" per Pitfall 11. Broker on persistent disk (not ephemeral local SSD) even in dev.
- **D-29:** Message key = `{source}:{restaurant_id}` (e.g. `opentable:42`) for `availability.raw` and `polls.completed`. With 1 partition this has no effect now; future partition-by-restaurant scaling is free.

### Database schema (P1 subset of FOUND-02)
- **D-30:** All schema created via **Alembic migrations** run by psycopg3 sync driver. TimescaleDB hypertables created via `op.execute("SELECT create_hypertable('poll_log', 'time', chunk_time_interval => INTERVAL '1 day')")` inside the migration body — NOT via SQLAlchemy `autogenerate`, which will fight the hypertable semantics (Pitfall 12, Integration Gotchas table).
- **D-31:** P1 tables created: `users`, `restaurants`, `watchlist_entries` (columns only — CRUD is Phase 5), `notification_log` (columns only — writes are Phase 4), `availability_events` hypertable (empty at P1 — writes are Phase 2), `poll_log` hypertable (actively written by P1 poller).
- **D-32:** `pgcrypto` extension enabled via an early migration. Phone-number columns defined as `BYTEA` (ciphertext) even though they're only written in Phase 5 — establishes the encryption contract from day 1.
- **D-33:** TimescaleDB `chunk_time_interval = INTERVAL '1 day'` for both hypertables, explicitly set in the `create_hypertable` call (not relying on the 7-day default). Continuous aggregates are Phase 6.

### Testing strategy for Phase 1
- **D-34:** `pytest` + `pytest-asyncio==1.1.0` with `asyncio_mode = "auto"`. Three tiers:
  - **Unit tests** (`tests/unit/`) — pure-Python logic (GraphQL query builder, ZSET Lua argument construction, `shared/redis_keys.py` constants). Fast, no infra.
  - **Integration tests** (`tests/integration/`) — use `testcontainers-python==4.x` to spin ephemeral Redis + Postgres + Kafka per-test-file (not per-test; too slow). Exercises Alembic migration apply, poll-and-emit end-to-end against a mocked OpenTable (via `pytest-httpx` or `respx`), ZSET scheduler claim/release/reap.
  - **E2E** (`tests/e2e/`) — deferred to Phase 7 (full docker-compose driven).
- **D-35:** CI runs unit + integration tiers on every PR; integration tier uses testcontainers against the same Redis/Postgres/Kafka versions pinned in `docker-compose.yml`. Linting: `ruff check` + `ruff format --check` + `mypy`.

### Claude's Discretion
- File naming within services (e.g. `scheduler.py` vs `claimer.py` — follow ARCHITECTURE.md's proposed layout as default)
- Specific structlog processor chain (JSON in prod, ConsoleRenderer with colors in dev is the obvious default)
- Pydantic model field names and docstrings (match the PRD/requirements wording when ambiguous)
- `AsyncClient` timeout values (5s connect, 10s read is a safe default for OpenTable)
- Log level defaults (`INFO` in prod, `DEBUG` in dev)
- Makefile target wording and the order of `make help` output
- Which Kafka UI to include in compose (redpanda-console vs kafka-ui vs kafdrop) — any is fine
- `.env.example` formatting and grouping
- Exact visibility-timeout reaper loop frequency (5–15s range; pick a reasonable default like 10s)
- Exact Lua script error handling and return values beyond the core ZRANGEBYSCORE→ZREM→ZADD primitive
- Any docstrings, type hints, and internal helper organization

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project & Requirements
- `.planning/PROJECT.md` — Product vision, core value (p95 ≤ 60s), constraints, key decisions table
- `.planning/REQUIREMENTS.md` §§ "Foundation & Admin Pre-conditions", "Polling Engine" (FOUND-01..06, POLL-01, POLL-03, POLL-07, PERF-02) — the exact acceptance criteria for P1
- `.planning/ROADMAP.md` § "Phase 1" — goal statement + 5 success criteria + dependency graph

### Architecture & Stack Research
- `.planning/research/ARCHITECTURE.md` — Authoritative for monorepo layout, component decomposition, ZSET scheduler pattern (Pattern 1), raw/refined event split (Pattern 2), recommended project structure section
- `.planning/research/ARCHITECTURE.md` § "Build Order" → Phase 1 — the build order inside this phase and the cut line ("none — this is the floor")
- `.planning/research/STACK.md` — Authoritative for every version pin; `pyproject.toml` excerpt in the "Installation" section is the seed for the actual dependency declarations
- `.planning/research/STACK.md` § "What NOT to Use" — enforce this list (no aioredis, no playwright-stealth, no kafka-python, no psycopg2, no Poetry, no black+isort+flake8)

### Pitfalls (MUST apply to P1 code)
- `.planning/research/PITFALLS.md` § Pitfall 5 — Twilio 10DLC Day-1 registration (non-technical, P1 gate)
- `.planning/research/PITFALLS.md` § Pitfall 7 — atomic `SET NX EX` only; never two-command `SETNX`+`EXPIRE` (P1 sets the codebase convention even though idempotency keys start in P2)
- `.planning/research/PITFALLS.md` § Pitfall 8 — README legal section drafted at P0/P1 (even a stub)
- `.planning/research/PITFALLS.md` § Pitfall 9 — shared `httpx.AsyncClient` per worker, explicit `Limits`
- `.planning/research/PITFALLS.md` § Pitfall 11 — Kafka persistent disk, `acks=all`, KRaft mode, single-broker tradeoff documented
- `.planning/research/PITFALLS.md` § Pitfall 12 — TimescaleDB `chunk_time_interval = INTERVAL '1 day'` set explicitly in `create_hypertable` via Alembic `op.execute`
- `.planning/research/PITFALLS.md` § Pitfall 16 — ban `requests` / `time.sleep` / sync redis in async workers (CI lint rule)
- `.planning/research/PITFALLS.md` § Pitfall 18 — Redis `maxmemory-policy = noeviction`

### Features & Supporting Research
- `.planning/research/FEATURES.md` — Feature-level context for FOUND-* and POLL-* items
- `.planning/research/SUMMARY.md` — Overall research synthesis

### Operational Runbooks
- `docs/runbooks/twilio-10dlc-setup.md` — Step-by-step Twilio A2P 10DLC Standard Campaign submission (D-21 implementation guide; user-executed, not code)

### State
- `.planning/STATE.md` — Current position, blockers flagged for P1 (Twilio Day-1 clock)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **None.** Phase 1 is the greenfield foundation. Only existing artifacts are documentation (`CLAUDE.md`, `README.md`, `LICENSE`, `mise_en_place_prd.docx`) and planning docs.

### Established Patterns
- **None yet.** Phase 1 *establishes* the patterns (monorepo layout, `shared/events.py` schema ownership, `shared/redis_keys.py` key registry, structlog JSON logging, Makefile command facade, `.env`/`.env.example` secrets).

### Integration Points
- Phase 2 (State Machine) will consume `availability.raw` — contract is the Pydantic model in `shared/events.py`; keep it stable.
- Phase 3 (Resy) will add a second `AvailabilitySource` adapter behind the same base class; layout under `services/poller/sources/` must accommodate this (`base.py` + `opentable/` + eventual `resy/`).
- Phase 4 (Notifier) needs `notifications.queued` / `notifications.sent` topics to already exist — created in P1's `scripts/create_topics.py`.
- Phase 5 (API) will add FastAPI at `services/api/` alongside the poller — monorepo accommodates.
- Phase 7 (Deploy) maps each `services/{name}/` directory to a Cloud Run Service or Worker Pool with one Dockerfile per service; those Dockerfiles are added in P7, not P1.

</code_context>

<specifics>
## Specific Ideas

- **`scripts/replay_raw.py`** is called out as a P2 deliverable and portfolio signature in ARCHITECTURE.md — mentioned here so P1's `availability.raw` payload schema is designed with "replayable offline without re-polling" in mind. Concretely: include `poll_id`, `source`, `restaurant_id`, `polled_at_epoch_ms`, and the full raw GraphQL response in the message payload, not just extracted slots. This makes Phase 2's replay trivially possible.
- **Kafka message size:** OpenTable responses for a single (restaurant, 7 days × 2 party sizes) call are small (typically < 10 KB). No compression needed at P1; Kafka defaults are fine.
- **Visibility-timeout reaper loop** should log at INFO level every time it re-enqueues an abandoned job (rare event; worth a line). At DEBUG: empty-sweep messages.
- **Seed restaurant sources** user is considering: Eater NYC Essential 38, Infatuation NYC Hit List, Resy "Top Reserved in New York" list, OpenTable "Best of" NYC categories. Tastemaker curation > popularity ranking for the portfolio narrative ("the tables everyone wants").

</specifics>

<deferred>
## Deferred Ideas

Captured but not in P1 scope:

- **Watchlist-driven tiered cadence (60s/3min/10min based on active-watch count)** → Phase 3 (POLL-02). P1 uses flat 90s±15% because no watchlists exist yet.
- **Resy polling + Playwright context pool + fingerprint rotation + soft-ban canary** → Phase 3 (POLL-04/05/06).
- **State machine + confirmation poll + tri-state diff + idempotency Layer 1 + replay script** → Phase 2 (STATE-01..06).
- **Prometheus exporter endpoints + Grafana dashboards (public read-only link)** → Phase 7 (DEPLOY-05). P1 verifies PERF-02 via `poll_log` SQL.
- **Terraform + Cloud Run Worker Pools + Memorystore + GCE Kafka/Timescale VMs** → Phase 7 (DEPLOY-01/02).
- **CI integration test that spins full docker-compose + smokes the pipeline** → Phase 7 (DEPLOY-03). P1 ships with unit + testcontainers integration only.
- **HMAC token dual-version rotation mechanism** → Phase 5 (WATCH-03). P1 just generates v1 of the HMAC secret.
- **OpenTelemetry tracing** → post-MVP (or late Phase 7 if time permits).
- **E2E tests directory** → Phase 7.
- **Per-service production Dockerfiles** → Phase 7.

</deferred>

---

*Phase: 01-foundation-admin-pre-conditions-opentable-polling*
*Context gathered: 2026-04-21*
