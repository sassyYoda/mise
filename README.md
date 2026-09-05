# Mise en Place

Real-time restaurant availability notifications for NYC. When a coveted table opens up
because someone cancelled, the person watching that restaurant is told fast enough to
actually book it.

Target: p95 detection-to-notification latency of 60 seconds or less.

Mise en Place is a personal, non-commercial portfolio project. It polls publicly visible
availability on OpenTable (and, later, Resy), pushes every raw poll onto a Kafka log,
diffs consecutive polls to detect newly opened slots, and fans out email, SMS, and web
push alerts. It is built as a small distributed system on purpose: Kafka as the durable
event spine, a Redis ZSET as a distributed scheduler with Lua-atomic job claiming,
TimescaleDB hypertables for time-series storage, and asyncio Python services.

## Status

**Phase 1 of 7 is code-complete. Nothing is deployed, and no end user can be notified yet.**

What runs today: a single OpenTable poller process that claims restaurants from a Redis
ZSET, polls availability over httpx, publishes `availability.raw` and `polls.completed`
to Kafka, and writes a `poll_log` row to TimescaleDB for every attempt. The full local
stack (Kafka KRaft, Redis, TimescaleDB, Kafka UI) comes up with `make up`.

What does not exist yet: the diff engine, the Resy/Playwright poller, the notification
pipeline, the FastAPI API, the Next.js PWA, and any cloud deployment. See
[Detailed status](#detailed-status) at the bottom for the file-level breakdown, known
gaps, and test coverage.

## Architecture

```
                    +--------------------+
                    |  restaurants.yml   |  55 curated NYC restaurants
                    |  (make seed)       |
                    +---------+----------+
                              | upsert rows + ZADD sched:polls
                              v
+-------------+     +--------------------+     +---------------------------+
| TimescaleDB |<----|   Redis (ZSET)     |<--->|  services/poller          |
| restaurants |     |  sched:polls       |     |  poll_loop: CLAIM (Lua)   |
|             |     |  sched:polls:      |     |    -> OpenTableAdapter    |
|             |     |    inflight        |     |    -> Publisher           |
|             |     |                    |     |    -> RELEASE (Lua)       |
|             |     |  reaper_loop:      |     |  reaper_loop: REAP (Lua)  |
|             |     |  re-enqueue stuck  |     |  every 10s                |
|             |     |  jobs after 60s    |     +------+-------------+------+
|             |     +--------------------+            |             |
|  poll_log   |<-----------------------------------------------------+
|  (hypertable, 1 row per poll, synchronous write)   |
+-------------+                                       v
                                       +-----------------------------+
                                       |  Kafka (single broker,      |
                                       |  KRaft, acks=all,           |
                                       |  idempotent producer)       |
                                       |                             |
                                       |  availability.raw    24h    |  <- BUILT
                                       |  polls.completed      7d    |  <- BUILT
                                       |  availability.events  7d    |  <- topic only
                                       |  notifications.queued 30d   |  <- topic only
                                       |  notifications.sent   30d   |  <- topic only
                                       +-----------------------------+
                                                      |
                     (planned, Phases 2-6)            v
                     diff engine -> availability.events -> notification consumer
                     -> Resend / Twilio / Web Push -> FastAPI API -> Next.js PWA
```

Kafka message key is always `{source}:{restaurant_id}`, so all events for one restaurant
stay ordered on one partition.

## Key design decisions (as implemented)

Each item below points at the file that implements it. Nothing here is aspirational.

**Distributed scheduler on a Redis ZSET with Lua-atomic claim, release, and reap.**
`sched:polls` is scored by next-poll epoch ms. A worker claims the single lowest-scored
due job by running a Lua script that does `ZRANGEBYSCORE` + `ZREM` + `ZADD` into
`sched:polls:inflight` in one atomic step, so two workers cannot claim the same
restaurant. After the poll, a second script moves it back with a new score. A reaper
loop re-enqueues any inflight job older than the 60 second visibility timeout, so a
crashed worker cannot strand a restaurant.
Scripts: `shared/redis_keys.py` (`CLAIM_POLL_LUA`, `RELEASE_POLL_LUA`, `REAP_INFLIGHT_LUA`).
Client wrapper with EVALSHA and script reload: `shared/scheduler/lua.py`.
Loops: `services/poller/scheduler.py`, `services/poller/reaper.py`.

**Kafka producer configured for durability, not speed.** `acks="all"`,
`enable_idempotence=True`, gzip compression, `linger_ms=20`. One factory, no inline
producers anywhere. `shared/kafka.py`. Topics are created idempotently with explicit
retention (`scripts/create_topics.py`), broker auto-create is disabled
(`ops/docker-compose.yml`), and the poller refuses to start if any of the five topics
is missing (`services/poller/main.py:_assert_topics_exist`).

**Strict, frozen event schemas.** Every Kafka payload is a Pydantic v2 model with
`frozen=True, extra="forbid"`. `shared/events.py` is the single source of truth for
`AvailabilityRaw` and `PollCompleted`.

**Raw responses are stored verbatim.** `availability.raw` carries the complete OpenTable
response plus the request parameters, so a future diff engine can be re-run over the
Kafka log without re-polling. `services/poller/sources/base.py`,
`services/poller/publisher.py`.

**Poll interval jitter.** Next poll is scheduled at `now + 90s +/- 15%` to avoid
constant-interval fingerprinting. `services/poller/scheduler.py:_next_poll_score`,
constants in `shared/redis_keys.py`.

**One `httpx.AsyncClient` per process.** Per-poll clients leak file descriptors over a
24 hour run; the process-wide singleton in `shared/http_client.py` is the only place the
client is constructed. The adapter receives it by injection.

**Retry with backoff and `Retry-After` support.** The OpenTable adapter uses tenacity
(3 attempts, exponential jitter) and sleeps for the server-supplied `Retry-After` on
HTTP 429 before retrying. User-Agent is rotated per request from a fixed list.
`services/poller/sources/opentable/adapter.py`, `services/poller/config.py`.

**Every poll attempt is recorded, success or not.** `Publisher.publish` writes a
`poll_log` row synchronously before returning, so the PERF-02 gate can trust the table.
`services/poller/publisher.py`.

**TimescaleDB hypertables via hand-written Alembic.** `availability_events` and
`poll_log` are hypertables with 1 day chunks. Autogenerate is banned once a hypertable
exists because it tries to drop the time index. `migrations/versions/0006_*.py`,
`migrations/versions/0007_*.py`, rules in `migrations/README.md`.

**Secrets never reach logs.** A structlog processor redacts Twilio, HMAC, VAPID, and
Resy cookie keys from every event dict. `shared/telemetry.py:_redact_secrets`.

**Async hygiene enforced in CI.** `import requests`, `time.sleep(`, and sync `redis`
imports are banned in `services/` and `shared/` by grep steps in
`.github/workflows/lint.yml`. Two-command `SETNX` + `EXPIRE` is banned in favor of the
atomic `SET NX EX` helper in `shared/redis_keys.py:set_nx_ex`. See `CONTRIBUTING.md`.

**Measurable SLA gates.**
- Product SLA: p95 detection-to-notification latency of 60 seconds or less. Not yet
  measurable, since no notification path exists.
- PERF-02: at least 99% of OpenTable polls succeed in every hourly bucket over 24 hours,
  with stable FD count. Checked by `scripts/check_poll_success.py` (`make verify-perf02`)
  using `time_bucket()` over `poll_log`. Not yet run against live traffic.

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.12, asyncio | `uv` for env and lockfile |
| Event log | Apache Kafka 3.8 (KRaft, single broker) | `aiokafka` client |
| Scheduler | Redis 7.2 ZSET + Lua | `redis-py` 7.x asyncio, `noeviction` policy |
| Storage | PostgreSQL 16 + TimescaleDB 2.17 | SQLAlchemy 2.0 async, asyncpg at runtime, psycopg3 for Alembic |
| HTTP | httpx + tenacity | shared client singleton |
| Schemas | Pydantic v2 | frozen, extra forbidden |
| Logging | structlog | JSON in prod, console in dev, secret redaction |
| Tests | pytest, pytest-asyncio, respx, testcontainers | integration tier spins up real Kafka/Redis/TimescaleDB |
| Lint | ruff, mypy strict | GitHub Actions `lint` workflow |
| Local infra | Docker Compose | Kafka, Redis, TimescaleDB, Kafka UI on :8080 |

Declared in `pyproject.toml` but not yet used by any code: FastAPI, uvicorn, Playwright,
tf-playwright-stealth, resend, twilio, pywebpush, prometheus-client. They are pinned for
later phases.

## Quickstart

Prerequisites: Python 3.12, [uv](https://docs.astral.sh/uv/), Docker with Compose.

```bash
git clone https://github.com/sassyYoda/mise.git && cd mise
cp .env.example .env          # defaults point at the local compose stack
uv sync

make up                       # Kafka (9094 on host), Redis (6379), TimescaleDB (5432), Kafka UI (8080)
make topics                   # create the 5 Kafka topics idempotently
make migrate                  # alembic upgrade head (7 migrations, 2 hypertables)
make seed                     # upsert 55 restaurants, ZADD them into sched:polls
make verify-seed              # asserts >=50 rows in DB and >=50 members in sched:polls

make poll                     # run the OpenTable poller in the foreground
```

Watch `availability.raw` arrive in Kafka UI at http://localhost:8080, or query
`poll_log` in Postgres (`mise`/`mise`).

Note: the OpenTable GraphQL endpoint in
`services/poller/sources/opentable/graphql.py` is an assumed placeholder and the seed
file uses placeholder restaurant IDs. Until both are replaced with values captured from a
real browser session (see `services/poller/sources/opentable/README.md`), live polls
will return errors and `poll_log` will fill with `status='error'` rows. The pipeline
itself still exercises end to end.

Tests and lint:

```bash
make test               # unit tests, no Docker needed
make test-integration   # unit + integration; testcontainers pulls Kafka, Redis, TimescaleDB images
make lint               # ruff + mypy
make fmt                # ruff format
make help               # list all targets
```

## Repository layout

```
shared/                      Cross-service kernel
  events.py                  Pydantic Kafka message schemas
  redis_keys.py              All Redis keys, TTLs, Lua scripts, SET NX EX helper
  scheduler/lua.py           LuaScheduler: claim / release / reap via EVALSHA
  kafka.py                   AIOKafkaProducer factory (acks=all, idempotent)
  db.py                      SQLAlchemy async models + session factory
  http_client.py             Process-wide httpx.AsyncClient singleton
  telemetry.py               structlog config + secret redaction
services/
  poller/                    OpenTable poller service (python -m services.poller)
    main.py                  Wiring, topic guard, graceful shutdown
    scheduler.py             poll_loop: claim -> poll -> publish -> release
    reaper.py                reaper_loop: re-enqueue expired inflight jobs
    publisher.py             Kafka emit + synchronous poll_log write
    config.py                UA rotation list, env-derived settings
    sources/base.py          AvailabilitySource ABC
    sources/opentable/       adapter.py, graphql.py (placeholder endpoint), fixtures.py
migrations/                  Alembic, 7 hand-written revisions (no autogenerate)
scripts/
  create_topics.py           Idempotent Kafka topic creation with retention
  seed_restaurants.py        YAML -> restaurants table + sched:polls ZSET (idempotent UPSERT)
  verify_seed.py             SC3 gate: >=50 restaurants seeded
  check_poll_success.py      PERF-02 gate: 99% hourly success over 24h
  seed/restaurants.yml       55 curated NYC restaurants (placeholder RIDs and photo URLs)
ops/docker-compose.yml       Kafka KRaft, Redis, TimescaleDB, Kafka UI
tests/
  unit/                      27 tests, no external services
  integration/               testcontainers-backed; skip automatically without Docker
docs/
  admin-evidence/            Templates for domain, GCP, Resy, Twilio setup evidence
  runbooks/                  PERF-02 24h log, Twilio 10DLC setup
.planning/                   Roadmap, requirements, per-phase plans and verification
```

## Detailed status

Verified against the code on 2026-09-05. Commits span 2026-04-20 to 2026-04-22.

### Implemented and exercised by tests

- Redis ZSET scheduler with Lua claim/release/reap and visibility-timeout reaper.
  Integration-tested in `tests/integration/test_scheduler_claim_release.py`.
- Kafka producer factory with durability config; five topics with retention; startup
  topic guard. `tests/unit/test_kafka_config.py`, `tests/integration/test_topics_created.py`.
- Seven Alembic migrations including two TimescaleDB hypertables with 1 day chunks.
  `tests/integration/test_migrations_apply.py`, `tests/integration/test_hypertable_config.py`.
- OpenTable poller: adapter with retry and `Retry-After`, publisher writing Kafka + `poll_log`,
  poll loop with jitter, reaper loop. End-to-end smoke with respx-mocked OpenTable in
  `tests/integration/test_poller_smoke.py`; `poll_log` write in
  `tests/integration/test_poll_log_writes.py`.
- Idempotent seed script and verify gate. `tests/integration/test_seed_idempotency.py`.
- Shared httpx singleton, UA rotation, structlog redaction, frozen event schemas.
  Unit-tested in `tests/unit/`.
- PERF-02 gate script `scripts/check_poll_success.py` (exit 0/1/2), plus runbook.

### Scaffolded but incomplete

- **OpenTable endpoint and query shape are assumed, not confirmed.**
  `services/poller/sources/opentable/graphql.py` and `fixtures.py` carry `[ASSUMED]`
  markers. A DevTools capture on a live OpenTable page is required before any real poll
  succeeds. The adapter README documents GraphQL, REST, and HTML fallbacks.
- **Seed data is placeholder.** All 55 entries in `scripts/seed/restaurants.yml` have
  `opentable_rid` values in the 900,000,000+ range and `cover_photo_url` under
  `placeholder.mise.place`. Names, slugs, neighborhoods, cuisines, and price tiers are real.
- **Database tables exist for features that have no code yet.** `users`,
  `watchlist_entries`, `notification_log`, and `availability_events` are migrated and
  have ORM models in `shared/db.py`, but nothing reads or writes them.
- **`set_nx_ex` helper exists but is unused.** It is the intended building block for
  notification dedup in a later phase.
- **Admin evidence files are unfilled templates** (`docs/admin-evidence/*.md`): domain,
  GCP project, Twilio 10DLC, Resy accounts all pending human action.
- **PERF-02 24 hour run has not been executed.** `docs/runbooks/perf02-24h-log.md` still
  has `_fill in_` placeholders.

### Planned only (no code in tree)

Phases 2 through 7 of `.planning/ROADMAP.md`: tri-state diff engine and t+8s
confirmation poll, two-layer idempotency, replay script, Resy Playwright poller,
notification consumer (Resend, Twilio, VAPID push), FastAPI API with HMAC management
tokens and SSE, Next.js PWA with heatmap, pattern intelligence, Cloud Run / GCE
deployment, Terraform, Grafana dashboard. None of these have any implementation.
Prometheus instrumentation is also not yet wired despite the dependency being pinned.

### Test coverage state

- `uv run pytest tests/unit -q`: 27 passed.
- `uv run pytest tests/integration -q` with Docker running: 10 passed, 2 errors. The 12
  tests across 8 files skip cleanly without Docker. The 10 that pass cover Redis
  (scheduler claim/release/reap, eviction policy) and TimescaleDB (migrations, hypertable
  chunking, `poll_log` writes, seed idempotency).
- The 2 errors are `test_topics_created.py` and `test_poller_smoke.py`, the only tests
  that need Kafka. See the fixture bug under Known rough edges. Until it is fixed, the
  end-to-end smoke path (claim, poll, publish to Kafka, release) is only exercised with
  the Kafka producer mocked.
- No coverage tooling configured. Untested paths include the EVALSHA `NOSCRIPT` fallback,
  the 429 `Retry-After` branch, the reaper loop's error handling, and
  `scripts/check_poll_success.py` (no fixture data).

### Known rough edges

- **Kafka integration tests cannot start their container.** `tests/conftest.py` builds
  `KafkaContainer(image="apache/kafka:3.8.1")`, but testcontainers' `KafkaContainer`
  (4.14.x) launches via `/etc/confluent/docker/configure` and `/launch`, which only exist
  in `confluentinc/cp-kafka` images. The apache image exits with code 2 before the
  broker starts, so both Kafka-backed integration tests error. Fix is to use the
  testcontainers default `confluentinc/cp-kafka:7.6.0` (or a KRaft-capable Confluent
  tag) in the fixture; the compose stack is unaffected because it uses `bitnami/kafka`.
- **Latent bug in the EVALSHA fallback.** `shared/scheduler/lua.py` catches
  `redis.exceptions.NoScriptError`, but the module is imported as
  `import redis.asyncio as redis`, and `redis.asyncio` has no `exceptions` attribute.
  If Redis restarts or scripts are flushed, the fallback path raises `AttributeError`
  instead of reloading the script. Fix is to `from redis.exceptions import NoScriptError`.
  Not hit in tests because scripts are loaded fresh per container.
- **CI lint job would fail on `main`.** `uv run ruff check .` reports 119 errors (88 are
  E501 line-too-long; the rest are import ordering, unused imports, and a few ASYNC
  rules). `uv run mypy shared/ services/` reports 10 errors in 5 files under strict mode.
  The workflow at `.github/workflows/lint.yml` runs both and would go red.
- **`pyyaml` is used by `scripts/seed_restaurants.py` but is not declared in
  `pyproject.toml`.** It is present only as a transitive dependency of `pre-commit`.
- `.env.example` documents Twilio, Resy, VAPID, HMAC, and GCP variables that no code
  reads yet.
- Single Kafka broker, replication factor 1, no consumer groups exist yet.

## Legal & Ethical Scraping

This project is a personal portfolio demo that monitors publicly visible restaurant availability
data. The following policies govern its operation:

- **Public data only**: All polled data is visible to any anonymous browser user on OpenTable.com
  and Resy.com. No private APIs, no auth bypass, no credential theft.
- **Rate limiting**: Polling is capped at a 90 second minimum interval per restaurant for httpx
  (OpenTable), enforced today by `POLL_INTERVAL_SECONDS` in `shared/redis_keys.py`. The planned
  Playwright poller for Resy will be capped at 80 req/min total; that cap will be enforced in
  code when the Resy poller lands (Phase 3). Both are documented here as a public commitment.
- **No booking automation**: The system detects availability and notifies users. It does not
  automate the booking step. Per the
  [NY Restaurant Reservation Anti-Piracy Act (Feb 2025)](https://columbianewsservice.com/2025/07/28/new-york-banned-reservation-resales-now-appointment-trader-is-testing-the-law-with-ai/),
  automated reservation resale and booking automation are explicitly prohibited, and we agree
  with that posture.
- **No account creation automation**: Resy polling accounts are created manually by the developer.
  Automated account creation violates Resy's ToS.
- **Compliance response**: If OpenTable or Resy requests takedown, the scraper stops within 24 hours.
  Historical heatmap data may remain as a static portfolio artifact.
- **robots.txt**: We respect robots.txt directives for all polled domains.
- **Portfolio scope**: This is a non-commercial portfolio project. No paid tier, no resale,
  no monetization.

*Privacy Policy and Terms of Service for mise.place: Coming Soon.*

## Why Kafka for ~400 Events/Day?

This project uses Apache Kafka as its event pipeline backbone even though the MVP volume
is roughly 400 `availability.raw` events per day (50 restaurants x ~8 polls/hour).

**Honest tradeoff:**
- At MVP volume, a simple Postgres table with a background worker would work fine.
- Kafka is chosen here as a portfolio-grade architectural decision:
  - **Durable replay**: The `availability.raw` stream is an immutable log. A planned
    Phase 2 `scripts/replay_raw.py` would re-run the diff engine over any offset range
    without re-polling OpenTable.
  - **Decoupled consumers**: The planned state machine (Phase 2) and notification
    consumer (Phase 4) would read from `availability.events` independently, with their
    own offsets and consumer groups. Adding a new consumer (e.g., analytics) requires
    zero changes to producers.
  - **Future scaling**: If the restaurant catalog grows to 5,000 entries or the system goes
    multi-city, Kafka handles the throughput increase with partition addition only.

**Single-broker tradeoff (MVP):**
- Replication factor 1 (single broker, KRaft mode, persistent volume).
- If the broker host is lost, in-flight messages in the retention window may be replayed from
  Kafka's log; older poll history is in TimescaleDB (`poll_log`).
- `acks=all` on all producers ensures the broker has fsynced before ack.
- **Upgrade path (Phase 7)**: Add a second broker, increase `default.replication.factor=2`,
  and update `min.insync.replicas=2`. No application code changes required.

## Operations Runbook

### PERF-02 24-Hour Verification (SC5)

PERF-02 requires that >=99% of OpenTable polls succeed in every hourly bucket over a 24-hour
observation window, with a stable FD count (no socket leaks).

**Prerequisites before starting the 24h run:**
1. OpenTable DevTools spike complete (see `services/poller/sources/opentable/README.md`). The
   placeholder `OPENTABLE_GQL_ENDPOINT` must be replaced with the live endpoint captured from
   a real browser session, or the poller will hit HTTP 404/400 and fail the 99% threshold.
2. Infrastructure up: `make up && make topics && make migrate && make seed && make verify-seed`.
3. `scripts/seed/restaurants.yml` has >=50 entries (verified by `make verify-seed`).

**Start the 24h run:**
```bash
# In a detached tmux/screen session (must survive shell close):
tmux new-session -d -s mise-poll 'make poll 2>&1 | tee logs/poll-$(date +%Y%m%dT%H%M%SZ).log'
POLLER_PID=$(pgrep -f "services.poller" | head -1)
echo "Poller PID: $POLLER_PID"

# Record the t0 baseline in docs/runbooks/perf02-24h-log.md:
T0=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Linux:
FD_COUNT=$(ls /proc/$POLLER_PID/fd 2>/dev/null | wc -l)
# macOS:
FD_COUNT=$(lsof -p $POLLER_PID 2>/dev/null | wc -l)
echo "t0=$T0 PID=$POLLER_PID FD=$FD_COUNT"
```

**Snapshot FD count at t+1h, t+6h, t+12h, t+24h** and fill the table in
`docs/runbooks/perf02-24h-log.md`.

**After 24 hours, run the PERF-02 gate:**
```bash
make verify-perf02
```

Expected: exits 0 and prints "PERF-02 PASSED: All 24 hourly buckets >= 99% success rate."

**Exit codes:**
- `0`: all 24 hourly buckets >=99% success (PERF-02 satisfied)
- `1`: at least one bucket below 99% (failing hours printed to stdout; investigate via
  `docker logs mise-postgres` or the `poll_log` table)
- `2`: fewer than 24 hourly buckets of data (run has not yet completed 24h)

**Passing criteria for phase closure:**
- `make verify-perf02` exits 0.
- FD count at t+24h is within 5% of the t0 baseline (confirms the shared
  `httpx.AsyncClient` singleton is not leaking connections).
- `docs/runbooks/perf02-24h-log.md` is fully filled in (no `_fill in_` placeholders).

## License

GNU General Public License v3.0. See `LICENSE`.
