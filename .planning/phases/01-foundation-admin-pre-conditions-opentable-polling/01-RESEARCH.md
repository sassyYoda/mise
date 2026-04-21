# Phase 1 Research: Foundation, Admin Pre-conditions & OpenTable Polling

**Researched:** 2026-04-21
**For:** gsd-planner
**Confidence:** HIGH for stack/patterns (verified in STACK.md / ARCHITECTURE.md / PITFALLS.md on 2026-04-20); MEDIUM for OpenTable GraphQL endpoint internals (partially-public, may require empirical validation); HIGH for admin runbook (Twilio 10DLC runbook already exists at `docs/runbooks/twilio-10dlc-setup.md`).

---

## User Constraints (from CONTEXT.md)

### Locked Decisions

D-01..D-35 from `.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md` are all locked. Copied verbatim:

- **D-01:** Python 3.12.x + `uv` + single `pyproject.toml` (no Poetry, no requirements.txt)
- **D-02:** Kafka 3.8.x KRaft single broker; `aiokafka==0.13.0`; `acks=all`; persistent volume for log dir
- **D-03:** Redis 7.2+, `redis==7.4.0` via `import redis.asyncio as redis`; `maxmemory-policy = noeviction`
- **D-04:** Postgres 16 + TimescaleDB 2.17 self-hosted; SQLA 2.0 async + asyncpg hot path; `psycopg==3.3.3` sync for Alembic
- **D-05:** `httpx==0.28.1`, one shared `AsyncClient` per worker, `Limits(max_connections=100, max_keepalive_connections=20)`, `tenacity==9.1.4`
- **D-06:** Pydantic v2 in `shared/events.py`; `.model_dump_json()` on wire; no Schema Registry
- **D-07:** Monorepo `services/{poller,state_machine,notifier,api}/`, `shared/`, `web/`, `migrations/`, `ops/`, `scripts/`, `tests/{unit,integration,e2e}/`
- **D-08:** `ops/docker-compose.yml` = infra only; Python services run via `uv run python -m services.poller` on host
- **D-09:** `.env` (gitignored) + `.env.example`; `pydantic-settings` `env_file=".env"`; no direnv/Doppler
- **D-10:** Top-level `Makefile` as the command facade (`make up|down|migrate|seed|test|test-integration|lint|fmt|poll|help`)
- **D-11:** PERF-02 verified via SQL on `poll_log` hypertable, not Prometheus at P1
- **D-12:** `structlog==25.5.0` wired day 1 in `shared/telemetry.py` (JSON prod, ConsoleRenderer dev, ENV-switched)
- **D-13:** OpenTelemetry deferred post-MVP
- **D-14:** Hand-curated ≥50 NYC restaurants from Eater NYC 38 / Infatuation Hit List / Resy "Top Reserved" / OpenTable "Best of NY"
- **D-15:** Seed YAML at `scripts/seed/restaurants.yml`; `scripts/seed_restaurants.py` idempotent upsert on `(source, platform_id)`
- **D-16:** Hard ≥50 restaurant count is P1 exit gate; all five fields populated (name/slug/neighborhood/cuisine/price_tier/cover_photo/opentable_rid/resy_venue_id captured now)
- **D-17:** Phase 1 polls every restaurant at 90s ± 15% jitter
- **D-18:** Redis ZSET visibility-timeout pattern: main `sched:polls`, in-flight `sched:polls:inflight`, atomic Lua ZRANGEBYSCORE→ZREM→ZADD-inflight, 60s visibility timeout, reaper loop, all keys in `shared/redis_keys.py`
- **D-19:** Scheduler enqueues `(source, restaurant_id)` pairs; poller fans out to `next 7 days × [2, 4]` party sizes internally; one poll = one GraphQL call = one `availability.raw` Kafka message
- **D-20:** P1 does NOT implement confirmation poll (Phase 2)
- **D-21:** Twilio 10DLC submitted Day 1 Week 1; runbook at `docs/runbooks/twilio-10dlc-setup.md`; toll-free registered in parallel
- **D-22:** `mise.place` domain registered (user's registrar choice)
- **D-23:** GCP project + Artifact Registry + Secret Manager APIs enabled (no Terraform yet)
- **D-24:** Resy accounts manually created, cookies in Playwright context memory only (never DB-persisted)
- **D-25:** VAPID keypair generated once via `pywebpush.generate_vapid_keys()` or `openssl ecparam -genkey -name prime256v1`; private → Secret Manager / `.env`, public → frontend env (P6)
- **D-26:** HMAC management-token secret = `secrets.token_bytes(32)`; stored in Secret Manager / `.env`
- **D-27:** Five topics via `scripts/create_topics.py` (idempotent, `AIOKafkaAdminClient`): `availability.raw` (1p/24h), `availability.events` (1p/7d), `notifications.queued` (1p/30d), `notifications.sent` (1p/30d), `polls.completed` (1p/7d)
- **D-28:** Replication factor 1 at MVP; broker on persistent disk in dev; documented in README
- **D-29:** Message key = `{source}:{restaurant_id}` for `availability.raw` and `polls.completed`
- **D-30:** Alembic runs on psycopg3 sync; hypertables via `op.execute("SELECT create_hypertable(...)")`, NOT autogenerate
- **D-31:** P1 tables: `users`, `restaurants`, `watchlist_entries` (columns), `notification_log` (columns), `availability_events` (hypertable, empty), `poll_log` (hypertable, actively written)
- **D-32:** `pgcrypto` enabled early migration; phone columns as `BYTEA` (ciphertext) even though writes are P5
- **D-33:** `chunk_time_interval => INTERVAL '1 day'` explicitly set on both hypertables
- **D-34:** `pytest` + `pytest-asyncio==1.1.0` `asyncio_mode="auto"`; unit tests in `tests/unit/`, integration in `tests/integration/` (testcontainers per-file), E2E deferred to P7
- **D-35:** CI runs unit + integration on every PR; `ruff check` + `ruff format --check` + `mypy`

### Claude's Discretion

- File naming within services (e.g. `scheduler.py` vs `claimer.py`)
- Specific structlog processor chain
- Pydantic field names and docstrings
- `AsyncClient` timeout values (5s connect, 10s read is a safe default)
- Log level defaults (INFO prod, DEBUG dev)
- Makefile target wording and `make help` order
- Which Kafka UI to include in compose (redpanda-console / kafka-ui / kafdrop — all fine)
- `.env.example` formatting and grouping
- Visibility-timeout reaper loop frequency (5–15s range; pick ~10s)
- Exact Lua script error handling beyond the core atomic primitive
- Docstrings, type hints, internal helper organization

### Deferred Ideas (OUT OF SCOPE — do not plan)

- Watchlist tiered cadence (60s/3min/10min) → Phase 3 (POLL-02)
- Resy polling + Playwright + fingerprint rotation + soft-ban canary → Phase 3
- State machine + diff engine + confirmation poll + idempotency + replay script → Phase 2
- Prometheus exporters + Grafana dashboards → Phase 7
- Terraform + Cloud Run Worker Pools + Memorystore + GCE VMs → Phase 7
- Full docker-compose CI integration smoke → Phase 7
- HMAC rotation mechanism (dual-version verification) → Phase 5 (P1 only generates v1)
- OpenTelemetry tracing → post-MVP
- E2E tests directory → Phase 7
- Per-service production Dockerfiles → Phase 7

---

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FOUND-01 | Monorepo scaffolded with `docker compose up` stack | D-07 layout, D-08 compose scope, Focus Area 1 Kafka compose |
| FOUND-02 | Alembic migrations for users / restaurants / watchlist_entries / notification_log / availability_events / poll_log hypertables | D-30, D-31, D-32, D-33, Focus Area 2 |
| FOUND-03 | ≥50 NYC restaurants seeded with platform_id / neighborhood / cuisine / price_tier / cover_photo | D-14, D-15, D-16 |
| FOUND-04 | 5 Kafka topics created with retention | D-27, D-28, D-29, Focus Area 1 |
| FOUND-05 | Twilio 10DLC submitted, domain registered, GCP project provisioned | D-21, D-22, D-23, Focus Area 9, existing runbook |
| FOUND-06 | Resy accounts, VAPID keypair, HMAC secret | D-24, D-25, D-26, Focus Area 9 |
| POLL-01 | Redis ZSET distributed scheduler, atomic pop, no-op on empty | D-18, Focus Area 3 |
| POLL-03 | OpenTable httpx polling against widget GraphQL, 90s minimum, parses slots with availability/seat area/booking token | D-17, D-19, Focus Area 4 |
| POLL-07 | `availability.raw` emitted with latency; `polls.completed` to `poll_log` | D-27, D-29, Focus Area 5 |
| PERF-02 | ≥99% poll success hourly via `poll_log.success/total` SQL | D-11, Validation Architecture table |

---

## Executive Summary

**Biggest decisions:**
1. Infra-only `docker-compose.yml` + Python services on host is the right P1 velocity choice (D-08) — no per-service Dockerfiles, no compose-bake loops; `make up && uv run python -m services.poller` is the inner loop.
2. Hypertables are created inside Alembic migration bodies via `op.execute("SELECT create_hypertable(...)")` — autogenerate is off-limits here because it will try to drop/recreate the time-index and corrupt the hypertable (confirmed pattern in Alembic discussion #1465 and PITFALLS.md Pitfall 12). The migration creates the regular table first, then converts in the same revision.
3. OpenTable's widget GraphQL endpoint is **semi-public**: reachable with just a realistic `User-Agent` and an `Origin: https://www.opentable.com` header. Community scrapers (`nfmcclure/opentable_availability_check`, `jonluca/OpenTable-Reservation-Maker`, sosedoff/opentable issue #6) confirm the shape, but OpenTable has periodically changed query names and param structures. We MUST implement the adapter behind a `selectors.py` / `graphql.py` version-mapped module (same hygiene as Resy DOM selectors), AND log raw responses to `availability.raw` (D-19, `scripts/replay_raw.py` readiness) so a format change is debuggable without re-polling.
4. Twilio 10DLC is a **blocking admin task, not a code task** — the runbook at `docs/runbooks/twilio-10dlc-setup.md` is already complete. The plan must schedule a user-executed wave for the ~45-minute Twilio console submission on day 1 and verify "Campaign Status: Pending/Registered" as a phase exit gate before any subsequent plan can mark the phase complete. Do not let code waves block on this; the two run in parallel.
5. PERF-02 verification is **a SQL query** (D-11), not a dashboard, not a Prometheus alert. The verification artifact is `scripts/check_poll_success.py` (or a Makefile target that runs a psycopg query) that prints per-hour success rate over the last 24h. This is cheap, deterministic, and P1-exit-auditable.

**Biggest risks:**
- OpenTable GraphQL query structure drift (MEDIUM) — mitigated by logging raw response bodies to Kafka and writing the query in one isolated module with a `selectors.py`-style "schema version" comment header.
- Developer starts the poller before topics exist (HIGH) — mitigated by D-27 `scripts/create_topics.py` being a `make migrate` dependency (or a no-op-if-exists op), and by the poller's Kafka producer having `allow_auto_create_topics=False`.
- Alembic migration for hypertables being re-run with autogenerate and corrupting the time index (MEDIUM) — mitigated by CI lint rule (`rg "create_hypertable" migrations/versions/` must match inside `op.execute` contexts) and a dev `README.md` in `migrations/` telling future contributors never to autogenerate against TimescaleDB.
- 50-restaurant curation taking longer than the engineer's estimate (MEDIUM) — mitigated by making curation a **dedicated wave** (Wave 0.5, user-executed, ~4–6h) rather than a sub-task of the seed script; the seed script must be idempotent so curation can happen in parallel with code waves.

---

## Validation Architecture

Mandatory Nyquist Dimension 8 section. Each of the 5 ROADMAP success criteria maps to a validation surface, an observability hook, and a named artifact the planner will schedule.

| SC | Statement (ROADMAP) | Validation Surface | Observability Hook | Named Verification Artifact |
|----|---------------------|--------------------|--------------------|-----------------------------|
| SC1 | `docker compose up` boots Kafka+Redis+Postgres+TimescaleDB; poller emits `availability.raw` within 60s | **Integration smoke** (testcontainers in CI) + **manual human smoke** (docker-compose from clean clone) | Kafka console consumer on `availability.raw`; `docker compose ps` all healthy; `make poll` stdout JSON log line `event="availability.raw.published"` | `tests/integration/test_poller_smoke.py::test_end_to_end_emit_within_60s` + Makefile target `make smoke` running `docker compose up -d && sleep 30 && kafka-console-consumer --topic availability.raw --max-messages 1` |
| SC2 | Twilio A2P 10DLC "Pending"/"Registered"; toll-free backup registered | **Manual / admin verification** (no code) | Twilio Console screenshot; campaign SID + status captured in `docs/runbooks/twilio-10dlc-setup.md` as a filled-in checklist | User-executed checkbox in `docs/runbooks/twilio-10dlc-setup.md` §"Track approval status" with date + SID recorded; planner adds a dedicated non-code Wave with a User gate |
| SC3 | ≥50 NYC restaurants with all 5 fields populated; scheduled in `sched:polls` ZSET | **Integration test** (testcontainers Redis + Postgres) + **manual SQL + Redis check** | `SELECT COUNT(*) FROM restaurants WHERE opentable_rid IS NOT NULL AND neighborhood IS NOT NULL AND cuisine IS NOT NULL AND price_tier IS NOT NULL AND cover_photo_url IS NOT NULL;` must return ≥ 50; `ZCARD sched:polls` must return ≥ 50 | `tests/integration/test_seed_idempotency.py::test_seed_populates_all_fields_and_zset` + Makefile target `make verify-seed` running both queries and asserting counts |
| SC4 | `availability_events` and `poll_log` hypertables with `chunk_time_interval = INTERVAL '1 day'`; `polls.completed` events written to `poll_log` with latency | **Integration test** (testcontainers Timescale) + **SQL introspection** | `SELECT chunk_time_interval FROM timescaledb_information.dimensions WHERE hypertable_name IN ('availability_events','poll_log');` returns `86400000000` µs (1 day); `SELECT COUNT(*) FROM poll_log WHERE time >= NOW() - INTERVAL '5 minutes' AND latency_ms IS NOT NULL;` > 0 after a test poll | `tests/integration/test_hypertable_config.py::test_chunk_interval_is_one_day` + `tests/integration/test_poll_log_writes.py::test_poll_writes_row_with_latency` |
| SC5 | Poll success rate ≥ 99% hourly across 24h; shared `AsyncClient` FD count stable | **SQL verification** (authoritative) + **manual FD audit during extended run** | `SELECT time_bucket('1 hour', time) AS hour, SUM(CASE WHEN status='success' THEN 1 ELSE 0 END)::float / COUNT(*) AS rate FROM poll_log WHERE time >= NOW() - INTERVAL '24 hours' GROUP BY hour ORDER BY hour;` must show every hour ≥ 0.99; `ls /proc/$(pgrep -f services.poller)/fd \| wc -l` stable over 24h | `scripts/check_poll_success.py` (or `make verify-perf02`) running the SQL and asserting all buckets ≥ 0.99; FD-count snapshot captured in `docs/runbooks/perf02-24h-log.md` by the engineer operating the long run |

Additional validation gates (not 1:1 to a ROADMAP SC but required for phase correctness):

| Gate | Surface | Hook | Artifact |
|------|---------|------|----------|
| Atomic `SET NX EX` convention set at P1 (Pitfall 7) | **CI lint rule** | `rg "redis.*\.setnx\|SETNX\\b" services/ shared/` returns zero matches (exceptions: a comment explaining the ban) | CI step `ripgrep-bans` in `.github/workflows/lint.yml` or `pre-commit` hook |
| No blocking calls in async workers (Pitfall 16) | **CI lint rule** | `rg "\bimport requests\b\|\btime\.sleep\(\|from urllib\b" services/poller/ services/state_machine/ services/notifier/ services/api/` returns zero | Same CI step |
| Redis `maxmemory-policy = noeviction` asserted in docker-compose (Pitfall 18) | **Integration test** | `redis-cli CONFIG GET maxmemory-policy` returns `noeviction` | `tests/integration/test_redis_config.py::test_eviction_policy_is_noeviction` |
| Kafka topics exist with correct retention before poller starts (D-27) | **Integration test** + **startup guard** | `AIOKafkaAdminClient.describe_topics()` shows all 5 topics with expected `retention.ms` | `tests/integration/test_topics_created.py::test_all_five_topics_have_retention` + poller startup sanity-check that refuses to start if topics missing |
| Pitfall 11: Kafka on persistent volume | **Compose file review** | `ops/docker-compose.yml` `kafka` service has `volumes: - kafka-data:/var/lib/kafka/data` named volume | Static review + `tests/integration/test_compose_lint.py` parsing the yaml |
| Pitfall 12: hypertable `chunk_time_interval` is explicitly 1 day | Covered by SC4 artifact above | — | — |
| httpx shared AsyncClient FD stability (Pitfall 9) | **Integration test** + **long-run observation** | Unit test asserts poller exposes a singleton `AsyncClient` bound to the asyncio lifespan; integration run asserts FD count stable for 1h | `tests/unit/test_http_client_singleton.py` + 1h soak run captured in SC5 artifact |

---

## Implementation Guidance

### 1. aiokafka KRaft single-broker bootstrap

**Confidence:** HIGH (verified 2026-04-21 via multiple 2024–2026 community Docker Compose references for Kafka 3.8 KRaft; cross-referenced with `aiokafka==0.13.0` PyPI docs and STACK.md version pin).

**docker-compose excerpt** (Claude's discretion on image tag — `bitnami/kafka:3.8` or `apache/kafka:3.8.1` are both valid; Bitnami is more widely referenced for single-broker KRaft setups):

```yaml
services:
  kafka:
    image: bitnami/kafka:3.8
    container_name: mise-kafka
    ports:
      - "9092:9092"
      - "9094:9094"  # external plaintext listener (for host Python)
    environment:
      # KRaft mode
      KAFKA_CFG_NODE_ID: 1
      KAFKA_CFG_PROCESS_ROLES: broker,controller
      KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093,EXTERNAL://:9094
      KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092,EXTERNAL://localhost:9094
      KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,EXTERNAL:PLAINTEXT
      KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CFG_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      # Single-broker durability tuning (Pitfall 11)
      KAFKA_CFG_DEFAULT_REPLICATION_FACTOR: 1
      KAFKA_CFG_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_CFG_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_CFG_MIN_INSYNC_REPLICAS: 1
      # Generate a stable cluster ID (alternative: unset, let Bitnami generate + persist in the volume)
      KAFKA_KRAFT_CLUSTER_ID: MkU3OEVBNTcwNTJENDM2Qg
    volumes:
      - kafka-data:/bitnami/kafka  # persistent volume — Pitfall 11
    healthcheck:
      test: ["CMD-SHELL", "kafka-topics.sh --bootstrap-server localhost:9092 --list"]
      interval: 10s
      timeout: 5s
      retries: 6

volumes:
  kafka-data:
```

**Producer config (in `shared/kafka.py` factory function):**

```python
# shared/kafka.py
from aiokafka import AIOKafkaProducer

async def make_producer(bootstrap: str = "localhost:9094") -> AIOKafkaProducer:
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap,
        acks="all",                    # D-02, Pitfall 11
        enable_idempotence=True,       # prevents duplicates on retries
        max_in_flight_requests_per_connection=5,  # required with idempotence=True
        compression_type="gzip",       # cheap at ~10KB messages; Kafka default=None
        linger_ms=20,                  # small batching window for co-arriving polls
        request_timeout_ms=30_000,
        value_serializer=lambda v: v.encode("utf-8"),  # Pydantic `.model_dump_json()` → str → bytes
        key_serializer=lambda k: k.encode("utf-8"),    # `{source}:{restaurant_id}` (D-29)
    )
    await producer.start()
    return producer
```

**Topic creation** (`scripts/create_topics.py`, idempotent):

```python
# scripts/create_topics.py
import asyncio
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

TOPICS = [
    NewTopic("availability.raw",     num_partitions=1, replication_factor=1,
             topic_configs={"retention.ms": str(86_400_000)}),      # 24h
    NewTopic("availability.events",  num_partitions=1, replication_factor=1,
             topic_configs={"retention.ms": str(604_800_000)}),     # 7d
    NewTopic("polls.completed",      num_partitions=1, replication_factor=1,
             topic_configs={"retention.ms": str(604_800_000)}),     # 7d
    NewTopic("notifications.queued", num_partitions=1, replication_factor=1,
             topic_configs={"retention.ms": str(2_592_000_000)}),   # 30d
    NewTopic("notifications.sent",   num_partitions=1, replication_factor=1,
             topic_configs={"retention.ms": str(2_592_000_000)}),   # 30d
]

async def main() -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers="localhost:9094")
    await admin.start()
    try:
        existing = set(await admin.list_topics())
        to_create = [t for t in TOPICS if t.name not in existing]
        if to_create:
            await admin.create_topics(to_create)
    finally:
        await admin.close()

if __name__ == "__main__":
    asyncio.run(main())
```

Wire as a Makefile target: `make topics` → `uv run python scripts/create_topics.py`. Add as a `make up` dependency chain: `up → wait-for-kafka → topics → migrate → seed`.

### 2. TimescaleDB Alembic migration pattern

**Confidence:** HIGH (canonical pattern; sources: TimescaleDB docs, Alembic discussion #1465 which explicitly discusses the autogenerate-fights-hypertable trap, PITFALLS.md Pitfall 12 and Integration Gotchas table).

**`migrations/env.py`** — configure with `psycopg==3.3.3` sync driver (D-30):

```python
# migrations/env.py (Alembic generated, modified for psycopg3 sync)
from sqlalchemy import engine_from_config, pool
from alembic import context
from shared.db import Base  # SQLAlchemy declarative base

config = context.config
target_metadata = Base.metadata

# DATABASE_URL for migrations uses psycopg3 sync driver:
# postgresql+psycopg://mise:mise@localhost:5432/mise
# (vs. the app hot path which uses postgresql+asyncpg://...)

def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # CRITICAL: do NOT set `include_schemas=True` in a way that lets
            # autogenerate scan Timescale internal schemas. See discussion #1465.
        )
        with context.begin_transaction():
            context.run_migrations()
```

**First migration — extensions:**

```python
# migrations/versions/0001_extensions.py
from alembic import op

revision = "0001_extensions"
down_revision = None

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # D-32

def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS timescaledb")
```

**Hypertable migration pattern:**

```python
# migrations/versions/0005_poll_log_hypertable.py
from alembic import op
import sqlalchemy as sa

revision = "0005_poll_log_hypertable"
down_revision = "0004_notification_log"

def upgrade() -> None:
    # Step 1: create a plain Postgres table
    op.create_table(
        "poll_log",
        sa.Column("time",          sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("restaurant_id", sa.Integer,                  nullable=False),
        sa.Column("source",        sa.Text,                     nullable=False),
        sa.Column("status",        sa.Text,                     nullable=False),  # 'success' | 'error' | 'timeout'
        sa.Column("latency_ms",    sa.Integer,                  nullable=True),
        sa.Column("http_status",   sa.Integer,                  nullable=True),
        sa.Column("error",         sa.Text,                     nullable=True),
        sa.Column("poll_id",       sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
    )
    # Step 2: convert to hypertable with explicit chunk_time_interval (D-33, Pitfall 12)
    op.execute(
        "SELECT create_hypertable('poll_log', 'time', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )
    # Step 3: useful indexes (Timescale auto-creates on `time`; add supporting)
    op.create_index("ix_poll_log_restaurant_time", "poll_log", ["restaurant_id", "time"])

def downgrade() -> None:
    op.drop_index("ix_poll_log_restaurant_time", table_name="poll_log")
    # Drop hypertable via normal DROP TABLE — Timescale handles it.
    op.drop_table("poll_log")
```

**Connection URL scheme summary (include in `.env.example`):**

- Alembic (sync, psycopg3): `DATABASE_URL_SYNC=postgresql+psycopg://mise:mise@localhost:5432/mise`
- App hot path (async, asyncpg): `DATABASE_URL_ASYNC=postgresql+asyncpg://mise:mise@localhost:5432/mise`

**Ban `alembic revision --autogenerate` for hypertables**: add a `migrations/README.md` stating: *"Never run `alembic revision --autogenerate` after a hypertable exists; it will try to drop/recreate the time index. Always hand-write hypertable migrations."*

### 3. Redis ZSET visibility-timeout Lua script

**Confidence:** HIGH (ARCHITECTURE.md Pattern 1 is the authoritative design; Lua EVAL pattern is standard Redis usage documented in redis-py docs).

**Keys and TTLs in `shared/redis_keys.py`:**

```python
# shared/redis_keys.py
# Single source of truth for ALL Redis key patterns and TTLs.
# D-18. Any Redis access in services/ MUST import from here.

# Scheduler ZSETs
SCHED_POLLS           = "sched:polls"            # score = next_poll_epoch_ms
SCHED_POLLS_INFLIGHT  = "sched:polls:inflight"   # score = now + visibility_ms

# Visibility / reaper
POLL_VISIBILITY_TIMEOUT_MS = 60_000   # 60s (D-18)
POLL_INTERVAL_SECONDS      = 90       # D-17
POLL_JITTER_FRACTION       = 0.15     # D-17 (±15%)
REAPER_INTERVAL_SECONDS    = 10       # Claude discretion (5–15s range)

# Future Phase 2 placeholders — declared in P1 only if referenced (do NOT preemptively populate)
# SCHED_CONFIRMATIONS = "sched:confirmations"   # Phase 2

# Lua script for atomic claim
CLAIM_POLL_LUA = """
-- KEYS[1] = sched:polls
-- KEYS[2] = sched:polls:inflight
-- ARGV[1] = now_ms (current time in milliseconds)
-- ARGV[2] = visibility_timeout_ms
local ready = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 1)
if #ready == 0 then
  return nil
end
local job = ready[1]
redis.call('ZREM', KEYS[1], job)
redis.call('ZADD', KEYS[2], tonumber(ARGV[1]) + tonumber(ARGV[2]), job)
return job
"""

RELEASE_POLL_LUA = """
-- KEYS[1] = sched:polls:inflight
-- KEYS[2] = sched:polls
-- ARGV[1] = job descriptor
-- ARGV[2] = next_poll_epoch_ms
redis.call('ZREM', KEYS[1], ARGV[1])
redis.call('ZADD', KEYS[2], tonumber(ARGV[2]), ARGV[1])
"""

REAP_INFLIGHT_LUA = """
-- KEYS[1] = sched:polls:inflight
-- KEYS[2] = sched:polls
-- ARGV[1] = now_ms
-- Returns the list of jobs that were re-enqueued (for logging).
local expired = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1])
for _, job in ipairs(expired) do
  redis.call('ZREM', KEYS[1], job)
  -- re-enqueue immediately (score = now) so a live worker picks it up
  redis.call('ZADD', KEYS[2], ARGV[1], job)
end
return expired
"""
```

**EVALSHA caching pattern:**

```python
# services/poller/scheduler.py
import redis.asyncio as redis
from shared.redis_keys import (
    SCHED_POLLS, SCHED_POLLS_INFLIGHT,
    CLAIM_POLL_LUA, RELEASE_POLL_LUA, REAP_INFLIGHT_LUA,
    POLL_VISIBILITY_TIMEOUT_MS,
)

class Scheduler:
    def __init__(self, client: redis.Redis) -> None:
        self.r = client
        self._claim_sha: str | None = None
        self._release_sha: str | None = None
        self._reap_sha: str | None = None

    async def start(self) -> None:
        self._claim_sha   = await self.r.script_load(CLAIM_POLL_LUA)
        self._release_sha = await self.r.script_load(RELEASE_POLL_LUA)
        self._reap_sha    = await self.r.script_load(REAP_INFLIGHT_LUA)

    async def claim(self, now_ms: int) -> str | None:
        """Returns job descriptor '{source}:{restaurant_id}' or None if empty."""
        job = await self.r.evalsha(
            self._claim_sha, 2,
            SCHED_POLLS, SCHED_POLLS_INFLIGHT,
            str(now_ms), str(POLL_VISIBILITY_TIMEOUT_MS),
        )
        return job.decode() if job else None

    async def release(self, job: str, next_poll_ms: int) -> None:
        await self.r.evalsha(
            self._release_sha, 2,
            SCHED_POLLS_INFLIGHT, SCHED_POLLS,
            job, str(next_poll_ms),
        )

    async def reap(self, now_ms: int) -> list[str]:
        """Re-enqueue jobs past their visibility deadline; returns re-enqueued IDs."""
        jobs = await self.r.evalsha(
            self._reap_sha, 2,
            SCHED_POLLS_INFLIGHT, SCHED_POLLS,
            str(now_ms),
        )
        return [j.decode() for j in jobs]
```

**Edge cases:**

- **Empty pop:** Lua returns `nil` → Python gets `None` → worker sleeps ~1s and retries. Do not busy-loop.
- **Simultaneous expiry:** reaper and worker race — Lua's atomic `ZREM`+`ZADD` means exactly one wins; the other sees the job already removed from inflight and no-ops.
- **Worker crash mid-Lua:** impossible — Lua scripts are atomic in Redis; the script either completes entirely or doesn't run.
- **Worker crash after Lua, before poll completes:** job sits in inflight with expiry; reaper picks it up after `POLL_VISIBILITY_TIMEOUT_MS`.
- **`evalsha` NOSCRIPT error (Redis restart / FLUSHSCRIPTS):** catch `redis.exceptions.NoScriptError` and fall back to `eval()` which re-caches. Document this pattern in `scheduler.py`.

### 4. OpenTable widget GraphQL endpoint

**Confidence:** MEDIUM — the endpoint is publicly reachable (the same endpoint that powers the in-page restaurant availability widget) but (a) OpenTable has periodically renamed the GraphQL operations across 2022–2025, (b) official docs (`dev.opentable.com`) are partner-only and do NOT cover the widget endpoint, (c) community scrapers confirm the shape but are snapshot-in-time.

**Known-good shape (as of April 2026, pending empirical validation during the first implementation task — mark as `[ASSUMED]` until the engineer confirms against a live restaurant):**

- **Endpoint:** `https://www.opentable.com/dapi/fe/gql/prod` (the front-end gql proxy that the widget uses) OR `https://www.opentable.com/restref/api/availability` (REST-shaped availability search used by the widget in some contexts). Empirically: the adapter should try the GraphQL endpoint first; if the implementer finds the current widget is hitting a REST path, fall back to that. **Plan a 30-minute spike at the start of the poller implementation task to confirm the current endpoint via browser DevTools on an OpenTable NYC restaurant page.**
- **Required request headers:**
  ```
  User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36
  Accept: application/json
  Content-Type: application/json
  Origin: https://www.opentable.com
  Referer: https://www.opentable.com/r/{restaurant-slug}
  ```
- **Query variables shape (typical):**
  ```json
  {
    "restaurantIds": [12345],
    "partySize": 2,
    "dateTime": "2026-04-28T19:00:00",
    "databaseRegion": "NA"
  }
  ```
- **Response shape (typical — the response carries an `availability` array with `{timeslot, seatingTypes, offers, reservationToken}`):** subject to OpenTable's schema; this is why we log the **full raw response** into the `availability.raw` Kafka payload (D-19 + ARCHITECTURE.md Pattern 2 + the `replay_raw.py` requirement).

**Rate limit posture:** OpenTable does not publish rate limits for the widget endpoint. Community scrapers (nfmcclure/opentable_availability_check, jonluca/OpenTable bot) report that ~1 req/sec per restaurant is tolerated; at 50 restaurants × 1 poll per 90s = 0.55 req/sec global, we are well under any reasonable cap. **Still cap at 1 req/sec per restaurant via scheduler-side jitter, and respect `Retry-After` headers in `tenacity` retry logic.**

**Error shapes:**

- HTTP 429 — rate limited. Tenacity exponential backoff with jitter.
- HTTP 5xx — transient; retry up to 2 times with backoff, then fail the poll (write `status='error'` to `poll_log`, do NOT publish to `availability.raw`).
- HTTP 200 with empty or malformed payload — write `status='success'` but with `availability=[]` in the raw message so the Phase 2 differ can decide. Do not flag as error at P1 (that's Pitfall 6 for Phase 3 soft-ban detection).
- Timeout (httpx `ReadTimeout`/`ConnectTimeout`) — treat as 5xx-equivalent retry path.

**Fallback if GraphQL is gated:** If on-the-ground investigation finds the GraphQL path requires auth cookies, fall back to fetching the public widget HTML (`https://www.opentable.com/widget/reservation/canvas?rid={rid}&datetime=...&partysize=...`) and parsing the embedded `__NEXT_DATA__` JSON. Document in `services/poller/sources/opentable/adapter.py` which path is in use and why. (Mark this as `[ASSUMED]` — the first plan should include a "confirm endpoint" task.)

**Query builder lives at `services/poller/sources/opentable/graphql.py`** — isolated module so future OpenTable schema changes are a one-file update.

### 5. httpx shared AsyncClient pattern

**Confidence:** HIGH (PITFALLS.md Pitfall 9 + D-05 + ARCHITECTURE.md + httpx official docs).

**Pattern:**

```python
# services/poller/__main__.py
import asyncio
import httpx
from contextlib import asynccontextmanager

HTTP_LIMITS = httpx.Limits(max_connections=100, max_keepalive_connections=20)
HTTP_TIMEOUT = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

@asynccontextmanager
async def http_lifespan():
    async with httpx.AsyncClient(
        limits=HTTP_LIMITS,
        timeout=HTTP_TIMEOUT,
        http2=True,
        headers={"User-Agent": "Mozilla/5.0 ..."},  # see Focus Area 4
    ) as client:
        yield client

async def main() -> None:
    async with http_lifespan() as http_client:
        # pass http_client into the adapter constructor — NEVER create per-poll
        opentable = OpenTableAdapter(client=http_client)
        scheduler = Scheduler(redis_client)
        await scheduler.start()
        await poll_loop(scheduler, opentable, kafka_producer)

if __name__ == "__main__":
    asyncio.run(main())
```

**Tenacity retry decorator on the adapter's fetch method:**

```python
# services/poller/sources/opentable/adapter.py
from tenacity import (
    retry, stop_after_attempt, wait_exponential_jitter,
    retry_if_exception_type, before_sleep_log,
)
import httpx, structlog

log = structlog.get_logger(__name__)

TRANSIENT = (
    httpx.ConnectError, httpx.ReadError, httpx.WriteError,
    httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout,
    httpx.PoolTimeout,
)

class OpenTableAdapter:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client  # shared, NEVER per-poll (D-05, Pitfall 9)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=1, max=10, jitter=2),
        retry=retry_if_exception_type(TRANSIENT),
        before_sleep=before_sleep_log(log, "WARNING"),
        reraise=True,
    )
    async def fetch_availability(self, rid: int, dates: list[str], party_sizes: list[int]) -> dict:
        resp = await self.client.post(
            OPENTABLE_GQL_URL,
            json=build_query(rid, dates, party_sizes),
            headers=OPENTABLE_HEADERS,
        )
        # Handle 429 explicitly — respect Retry-After and re-raise as transient
        if resp.status_code == 429:
            raise httpx.ReadTimeout("429 rate limited", request=resp.request)
        resp.raise_for_status()
        return resp.json()
```

**FD-leak prevention (Pitfall 9 verification):**

- Unit test asserting a single `AsyncClient` instance is held for the lifetime of the process.
- Integration test running 100 sequential polls and asserting `len(os.listdir("/proc/self/fd"))` does not grow.
- 24h observation loop (SC5 artifact) capturing `ls /proc/$(pgrep -f services.poller)/fd | wc -l` in 5-minute samples; the resulting CSV goes into `docs/runbooks/perf02-24h-log.md`.

### 6. testcontainers-python fixtures for Kafka/Redis/Postgres

**Confidence:** HIGH (testcontainers 4.x docs; D-34 is explicit about per-file scoping and per-test isolation; respx / pytest-httpx are the official httpx mock tools per STACK.md).

**Per-file scoping (D-34) — `tests/integration/conftest.py`:**

```python
# tests/integration/conftest.py
import pytest
from testcontainers.kafka import KafkaContainer
from testcontainers.redis import RedisContainer
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="module")
def kafka_container():
    with KafkaContainer(image="confluentinc/cp-kafka:7.7.0").with_kraft() as kc:
        yield kc

@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer(image="redis:7.2-alpine") as rc:
        # Apply P1 config: maxmemory-policy=noeviction (D-03, Pitfall 18)
        client = rc.get_client()
        client.config_set("maxmemory-policy", "noeviction")
        yield rc

@pytest.fixture(scope="module")
def timescale_container():
    # Use the Timescale-official image (D-04: TimescaleDB 2.17 on PG 16)
    container = PostgresContainer(
        image="timescale/timescaledb:2.17.2-pg16",
        username="mise", password="mise", dbname="mise",
    )
    with container as tc:
        yield tc
```

**Kafka KRaft variant:** testcontainers 4.x supports KRaft via `KafkaContainer(...).with_kraft()` or a newer `KafkaContainer(image="apache/kafka:3.8.1")` which defaults to KRaft. Prefer the apache image for alignment with D-02's Kafka 3.8; verify version pin in `pyproject.toml` dev group.

**TimescaleDB image:** `timescale/timescaledb:2.17.2-pg16` (confirmed as a public tag on Docker Hub; align with D-04's 2.17 + PG16 spec).

**Waiting-for-ready:** testcontainers handles this automatically via its `wait_for()` defaults. For Kafka, `KafkaContainer` uses `kafka-topics.sh --list`. For Postgres, it waits for `pg_isready`. Redis is "ready when TCP is up."

**Mocking OpenTable in integration tests — use `respx`** (cleaner than `pytest-httpx` for route-based matching):

```python
# tests/integration/test_poller_end_to_end.py
import respx
from httpx import Response

@pytest.mark.asyncio
async def test_poller_publishes_availability_raw(kafka_container, redis_container, timescale_container):
    async with respx.mock(assert_all_called=True) as router:
        router.post("https://www.opentable.com/dapi/fe/gql/prod").mock(
            return_value=Response(200, json={"availability": [...]})
        )
        # boot poller against containers, run one poll cycle, assert:
        # - one message on availability.raw with correct key {source}:{rid}
        # - one row in poll_log with status='success' and latency_ms > 0
        # - scheduler moved the job back to sched:polls with score ≈ now+90000±15%
```

### 7. structlog JSON config

**Confidence:** HIGH (structlog 25.5 docs + D-12 + widely-used 2025/2026 pattern).

**`shared/telemetry.py`:**

```python
# shared/telemetry.py
import logging
import os
import sys
import structlog
from structlog.types import EventDict

ENV = os.getenv("ENV", "dev")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO" if ENV == "prod" else "DEBUG").upper()

def configure_logging() -> None:
    # stdlib root logger bridge (so libraries like aiokafka, sqlalchemy go through structlog)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=LOG_LEVEL,
    )

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if ENV == "prod":
        renderer: list = [structlog.processors.JSONRenderer()]
    else:
        renderer = [structlog.dev.ConsoleRenderer(colors=True)]

    structlog.configure(
        processors=shared_processors + renderer,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(LOG_LEVEL)
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

# Usage everywhere:
#   from shared.telemetry import configure_logging
#   configure_logging()
#   import structlog; log = structlog.get_logger(__name__)
#   log.info("poll.started", restaurant_id=42, source="opentable")
```

**Per-poll bound context:**

```python
# services/poller/__main__.py (inside the poll loop)
import structlog
base_log = structlog.get_logger(__name__)

async def poll_once(job: str) -> None:
    source, rid = job.split(":", 1)
    log = base_log.bind(source=source, restaurant_id=int(rid), poll_id=str(uuid.uuid4()))
    log.info("poll.started")
    # ... do work
    log.info("poll.completed", latency_ms=latency, status="success")
```

### 8. Validation Architecture (see top section)

Covered in `## Validation Architecture` above.

### 9. Twilio 10DLC / domain / GCP / VAPID / HMAC admin flow

**Confidence:** HIGH — runbook already exists at `docs/runbooks/twilio-10dlc-setup.md`; STACK.md + PITFALLS.md confirm timing/importance.

**Twilio 10DLC:** Follow `docs/runbooks/twilio-10dlc-setup.md` verbatim. Key console paths:

1. `Messaging → Regulatory Compliance → A2P 10DLC → Register a Brand` (Standard Brand, Technology industry, `https://mise.place`)
2. `Messaging → Services → Create Messaging Service → Register a Campaign` (Use Case: Low Volume Mixed)
3. `Phone Numbers → Manage → Buy a number` (NYC area code, SMS-capable)
4. `Phone Numbers → Buy a number → filter=Toll-Free` + `Messaging → Regulatory Compliance → Toll-Free Verification → Submit` (parallel backup)

**Expected secrets stored** (stub placeholders in `.env.example`, real values in `.env` and eventually Secret Manager):
```
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxx
TWILIO_FROM_NUMBER=+1917xxxxxxx
TWILIO_TOLLFREE_FROM_NUMBER=+1833xxxxxxx
```

**Domain:** `mise.place` — registrar is the user's choice (Cloudflare Registrar recommended for zero-margin pricing + free DNS). Point to a "Coming soon" page initially (Twilio 10DLC audit may check the domain is live). Store the nameservers in `docs/runbooks/domain-registration.md` (create this alongside).

**GCP project:**

```bash
# Run once, captured in docs/runbooks/gcp-provisioning.md
gcloud projects create mise-en-place-prod --name="Mise en Place Prod"
gcloud config set project mise-en-place-prod

# Enable APIs
gcloud services enable \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  compute.googleapis.com \
  sqladmin.googleapis.com \
  run.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com
```

(No Terraform at P1, per D-23. Terraform is P7.)

**VAPID keypair** (generate once; D-25):

```bash
# Option A (recommended): pywebpush
python -c "from pywebpush import generate_vapid_keys; k=generate_vapid_keys(); print('PRIVATE:', k['private_key']); print('PUBLIC:', k['public_key'])"

# Option B: openssl
openssl ecparam -genkey -name prime256v1 -noout -out vapid_private.pem
openssl ec -in vapid_private.pem -pubout -out vapid_public.pem
```

Store in `.env`:
```
VAPID_PRIVATE_KEY=...
VAPID_PUBLIC_KEY=...
VAPID_SUBJECT=mailto:admin@mise.place
```
(Public key is also exposed to frontend in P6; private key NEVER exposed.)

**HMAC secret** (D-26):

```bash
python -c "import secrets; print('HMAC_MGMT_SECRET=' + secrets.token_bytes(32).hex())"
```

Store as `HMAC_MGMT_SECRET_V1` in `.env` (the `_V1` suffix establishes the dual-version rotation contract from day 1; rotation is implemented in P5).

**Secrets summary in `.env.example`:**

```
# Runtime
ENV=dev
LOG_LEVEL=DEBUG

# Database
DATABASE_URL_SYNC=postgresql+psycopg://mise:mise@localhost:5432/mise
DATABASE_URL_ASYNC=postgresql+asyncpg://mise:mise@localhost:5432/mise
POSTGRES_USER=mise
POSTGRES_PASSWORD=mise
POSTGRES_DB=mise

# Redis
REDIS_URL=redis://localhost:6379/0

# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9094

# Twilio (runbook output)
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_MESSAGING_SERVICE_SID=
TWILIO_FROM_NUMBER=
TWILIO_TOLLFREE_FROM_NUMBER=

# VAPID (P4/P6)
VAPID_PRIVATE_KEY=
VAPID_PUBLIC_KEY=
VAPID_SUBJECT=mailto:admin@mise.place

# Security (P5)
HMAC_MGMT_SECRET_V1=

# Resy (P3) — placeholders captured in P1
RESY_ACCOUNT_1_EMAIL=
RESY_ACCOUNT_1_PASSWORD=
RESY_ACCOUNT_2_EMAIL=
RESY_ACCOUNT_2_PASSWORD=
```

### 10. Pitfall mitigations (P1 scope)

| # | Pitfall | P1 Concrete Mitigation | Planner Enforcement |
|---|---------|------------------------|----------------------|
| 5 | Twilio 10DLC lead time | User-executed Wave 1 admin task (runbook); phase exit gate checks Twilio console status | Dedicated wave; `docs/runbooks/twilio-10dlc-setup.md` §"Track approval status" checkbox filled |
| 7 | Atomic `SET NX EX` convention (even though idempotency is P2) | CI lint rule banning `SETNX` / `redis.setnx(` across `services/` and `shared/` | `.github/workflows/lint.yml` ripgrep step + pre-commit hook |
| 8 | README legal section stub drafted | P1 creates `README.md` with "Legal & Ethical Scraping" placeholder section (rate-limit cap, monitor-only, no resale, no booking) | Plan includes a README-skeleton task |
| 9 | httpx shared AsyncClient + `Limits` | Implementation enforced in `services/poller/__main__.py` lifespan; unit test + 1h FD observation | Unit test: `tests/unit/test_http_client_singleton.py`; long-run FD log in `docs/runbooks/perf02-24h-log.md` |
| 11 | Kafka persistent disk + `acks=all` + KRaft + single-broker documented | Named volume `kafka-data` in compose; producer config; README note | Compose-file integration test asserts volume presence |
| 12 | TimescaleDB `chunk_time_interval = INTERVAL '1 day'` | Migration body uses `op.execute("SELECT create_hypertable(..., chunk_time_interval => INTERVAL '1 day')")`; `migrations/README.md` bans autogenerate | Integration test `test_chunk_interval_is_one_day` |
| 16 | Ban `requests` / `time.sleep` / sync redis in async workers | CI lint rule via ripgrep; `flake8-async` as optional extra | `.github/workflows/lint.yml` ripgrep step |
| 18 | Redis `maxmemory-policy = noeviction` | Assert in `ops/docker-compose.yml` via `command: ["redis-server", "--maxmemory-policy", "noeviction"]`; integration test asserts `CONFIG GET` value | `tests/integration/test_redis_config.py::test_eviction_policy_is_noeviction` |

---

## Build Order (within Phase 1)

Respects D-07 (layout), D-10 (Makefile facade), D-30 (Alembic), D-27 (topics before poller), D-14..D-16 (50-restaurant curation = blocking user work, parallelizable).

### Wave 0 — Scaffolding (no dependencies; ~1 day)

Runs entirely in parallel.

- **0a.** Repo skeleton: directory structure per D-07, `pyproject.toml` with all dependencies per STACK.md, `uv.lock`, `.gitignore`, `.env.example`, `Makefile` stub with `help` target (D-10).
- **0b.** `shared/telemetry.py` (structlog config per Focus Area 7) + `shared/redis_keys.py` (Focus Area 3 constants) + empty `shared/events.py` header + empty `shared/kafka.py` header + empty `shared/db.py` header.
- **0c.** `ops/docker-compose.yml` for Kafka KRaft + Redis + Postgres/TimescaleDB + Kafka UI (Focus Area 1). `make up` / `make down` targets work.
- **0d.** CI: `.github/workflows/lint.yml` with `ruff check`, `ruff format --check`, `mypy`, ripgrep bans (Pitfall 7, 16).
- **0e.** `README.md` with stub "Legal & Ethical Scraping" section (Pitfall 8) and a "Why Kafka for 400 events/day?" honest-tradeoff paragraph (Pitfall 11).

### Wave 0.5 — Admin kickoff (USER-EXECUTED, PARALLEL TO EVERYTHING; ~4–6h + multi-week waiting clock)

- **0.5a.** [USER] Twilio 10DLC Brand + Campaign submission (runbook). Captures SIDs into `.env` / Secret Manager. **This wave unblocks the phase exit gate but not other code waves.**
- **0.5b.** [USER] `mise.place` domain registration + "Coming soon" page live.
- **0.5c.** [USER] GCP project + API enablement (Artifact Registry, Secret Manager, Compute, Cloud SQL, Cloud Run, Logging, Monitoring).
- **0.5d.** [USER] Generate VAPID keypair (`pywebpush.generate_vapid_keys()`) + HMAC secret (`secrets.token_bytes(32).hex()`); store in `.env`.
- **0.5e.** [USER] Manually create 2–3 Resy accounts + capture email/password in `.env` under `RESY_ACCOUNT_{1,2,3}_*` keys. (Cookies are NOT captured here; Playwright captures them live in P3 per D-24.)
- **0.5f.** [USER] Hand-curate 50 NYC restaurants into `scripts/seed/restaurants.yml` (D-14, D-16). **All 5 fields required per row.**

### Wave 1 — Schema & contracts (depends on Wave 0; ~1–2 days)

- **1a.** `shared/events.py` — Pydantic models for all 5 Kafka message shapes: `AvailabilityRaw`, `AvailabilityEvent`, `NotificationQueued`, `NotificationSent`, `PollCompleted`. Even though P1 only populates `AvailabilityRaw` and `PollCompleted`, define all 5 now (D-06, contract-first).
- **1b.** `shared/db.py` — SQLAlchemy 2.0 models for `users`, `restaurants`, `watchlist_entries`, `notification_log`, `availability_events`, `poll_log`. Phone columns as `BYTEA` (D-32).
- **1c.** Alembic init (`migrations/env.py` with psycopg3 sync driver per D-30) + migrations:
  - `0001_extensions.py` — enable `timescaledb` + `pgcrypto`
  - `0002_users.py`
  - `0003_restaurants.py`
  - `0004_watchlist_entries.py` (columns only, no CRUD)
  - `0005_notification_log.py` (columns only)
  - `0006_availability_events_hypertable.py` — create table + `op.execute(create_hypertable ... INTERVAL '1 day')`
  - `0007_poll_log_hypertable.py` — same pattern
  - `migrations/README.md` with the autogenerate ban (Pitfall 12)
- **1d.** `make migrate` target.

### Wave 2 — Kafka + Redis plumbing (depends on Wave 0 and Wave 1a; ~1 day, can start parallel with Wave 1bc)

- **2a.** `shared/kafka.py` — producer factory with `acks=all`, `enable_idempotence=True`, Pydantic-model-aware `value_serializer`. Consumer factory stub for future phases.
- **2b.** `scripts/create_topics.py` — idempotent topic creation via `AIOKafkaAdminClient` (D-27). `make topics` target.
- **2c.** Redis ZSET scheduler class `services/poller/scheduler.py` with Lua EVALSHA pattern (Focus Area 3).
- **2d.** Unit tests: `tests/unit/test_scheduler_lua.py` (argument construction) + `tests/unit/test_redis_keys.py` (constants are strings, TTL constants are ints).

### Wave 3 — Seed script + OpenTable adapter (depends on Waves 1 + 2 + 0.5f; ~1–2 days)

- **3a.** `scripts/seed_restaurants.py` — idempotent upsert keyed on `(source, platform_id)` (D-15). Reads `scripts/seed/restaurants.yml`. On first seed, also `ZADD`s one job per restaurant into `sched:polls` with randomized initial score in [now, now + 90s] (staggered boot).
- **3b.** `services/poller/sources/base.py` — `AvailabilitySource` ABC with single `fetch(restaurant_id, dates, party_sizes)` method returning raw JSON.
- **3c.** `services/poller/sources/opentable/graphql.py` — query builder. Include a `SCHEMA_VERSION = "2026-04"` constant comment at the top.
- **3d.** `services/poller/sources/opentable/adapter.py` — httpx impl with tenacity retry (Focus Area 5). **Includes a 30-minute live-endpoint spike at the start of this task to confirm URL + headers against OpenTable.com DevTools.**
- **3e.** Unit tests: mocked GraphQL response shapes via respx; `tests/unit/test_opentable_graphql.py` + `tests/unit/test_opentable_adapter.py` (retry-on-transient).

### Wave 4 — Poller main loop (depends on Wave 3; ~1 day)

- **4a.** `services/poller/__main__.py` — wires scheduler, OpenTable adapter, Kafka producer. Lifespan-managed `AsyncClient` (D-05, Pitfall 9). Reaper loop running every 10s (Claude discretion).
- **4b.** `services/poller/publisher.py` — produces `availability.raw` and `polls.completed` with key `{source}:{restaurant_id}` (D-29); writes `poll_log` row synchronously (or async-awaited) before releasing the scheduler job.
- **4c.** `make poll` target.
- **4d.** Integration tests (testcontainers): `tests/integration/test_poller_end_to_end.py` (one poll cycle → `availability.raw` + `poll_log` + scheduler re-queued), `tests/integration/test_topics_created.py`, `tests/integration/test_hypertable_config.py`, `tests/integration/test_redis_config.py`, `tests/integration/test_seed_idempotency.py`.
- **4e.** Startup guard: poller refuses to start if any of the 5 topics don't exist (clear error: "run `make topics` first").

### Wave 5 — Verification artifacts (depends on Wave 4; ~0.5 day)

- **5a.** `scripts/check_poll_success.py` — SQL query for PERF-02 (SC5). `make verify-perf02` target.
- **5b.** `make verify-seed` target (counts in `restaurants` and `sched:polls`).
- **5c.** `make smoke` target (docker compose up → wait → kafka-console-consumer).
- **5d.** `docs/runbooks/perf02-24h-log.md` template for the 24h FD observation.

### Wave 6 — Phase exit (depends on Waves 4 + 5 + 0.5a Twilio gate; ~0.5 day + waiting)

- **6a.** Manual verification: run `docker compose up` from clean clone, start poller, wait 60s, observe `availability.raw` in console consumer (SC1).
- **6b.** Confirm Twilio 10DLC status "Pending" or "Registered" + toll-free registered (SC2).
- **6c.** `make verify-seed` returns ≥50 on both counts (SC3).
- **6d.** Hypertable config assertion + `poll_log` rows present (SC4).
- **6e.** 24h run with `check_poll_success.py` showing ≥99% every hour; FD count snapshot stable (SC5).

**Parallelism notes:**
- Wave 0.5 (admin) runs fully parallel with Waves 0–5.
- Wave 2 can start as soon as Wave 0 (scaffolding) is complete; it does not block on Wave 1's schema work.
- Wave 3a depends on Wave 0.5f (curation) but Waves 3b–e do not — the adapter can be built against a fixture restaurant before the seed file exists.
- Wave 6e (24h run) is the only wall-clock blocker at the end; start it as soon as Wave 5 is green.

---

## Named Symbols (do not invent variants)

The planner MUST use these exact identifiers so later phases can reference them without renames.

### Environment variables (`.env.example`)
```
ENV
LOG_LEVEL
DATABASE_URL_SYNC
DATABASE_URL_ASYNC
POSTGRES_USER
POSTGRES_PASSWORD
POSTGRES_DB
REDIS_URL
KAFKA_BOOTSTRAP_SERVERS
TWILIO_ACCOUNT_SID
TWILIO_AUTH_TOKEN
TWILIO_MESSAGING_SERVICE_SID
TWILIO_FROM_NUMBER
TWILIO_TOLLFREE_FROM_NUMBER
VAPID_PRIVATE_KEY
VAPID_PUBLIC_KEY
VAPID_SUBJECT
HMAC_MGMT_SECRET_V1
RESY_ACCOUNT_1_EMAIL
RESY_ACCOUNT_1_PASSWORD
RESY_ACCOUNT_2_EMAIL
RESY_ACCOUNT_2_PASSWORD
```

### Redis keys (`shared/redis_keys.py`)
- `sched:polls` (ZSET, score = next_poll_epoch_ms)
- `sched:polls:inflight` (ZSET, score = now + visibility_timeout_ms)

### Redis constants
- `POLL_VISIBILITY_TIMEOUT_MS = 60_000`
- `POLL_INTERVAL_SECONDS = 90`
- `POLL_JITTER_FRACTION = 0.15`
- `REAPER_INTERVAL_SECONDS = 10`

### Kafka topics (D-27)
- `availability.raw` (1 partition, retention 86_400_000 ms / 24h)
- `availability.events` (1 partition, retention 604_800_000 ms / 7d)
- `notifications.queued` (1 partition, retention 2_592_000_000 ms / 30d)
- `notifications.sent` (1 partition, retention 2_592_000_000 ms / 30d)
- `polls.completed` (1 partition, retention 604_800_000 ms / 7d)

### Kafka message keys
- `availability.raw`: `{source}:{restaurant_id}` (e.g. `opentable:42`) — D-29
- `polls.completed`: `{source}:{restaurant_id}` — D-29

### Pydantic models (`shared/events.py`)
- `AvailabilityRaw` (fields: `poll_id: UUID`, `source: Literal["opentable","resy"]`, `restaurant_id: int`, `polled_at_epoch_ms: int`, `raw_response: dict`, `request_params: dict`)
- `AvailabilityEvent` (P2; stubbed at P1)
- `NotificationQueued` (P4; stubbed at P1)
- `NotificationSent` (P4; stubbed at P1)
- `PollCompleted` (fields: `poll_id: UUID`, `source: str`, `restaurant_id: int`, `status: Literal["success","error","timeout"]`, `latency_ms: int | None`, `http_status: int | None`, `error: str | None`, `polled_at_epoch_ms: int`)

### Database tables (`shared/db.py`)
- `users` (columns only at P1 — schema: `id`, `email`, `phone_encrypted BYTEA`, `created_at`)
- `restaurants` (columns: `id`, `source`, `platform_id` (str for opentable rid / resy venue_id), `name`, `slug`, `neighborhood`, `cuisine`, `price_tier` (int 1–4), `cover_photo_url`, `date_range_days int default 7`, `party_sizes int[] default '{2,4}'`, `created_at`, unique on `(source, platform_id)`)
- `watchlist_entries` (columns only at P1; populated P5)
- `notification_log` (columns only at P1; populated P4)
- `availability_events` (hypertable, columns only at P1; populated P2)
- `poll_log` (hypertable, columns: `time TIMESTAMPTZ NOT NULL`, `restaurant_id int`, `source text`, `status text`, `latency_ms int`, `http_status int`, `error text`, `poll_id UUID`; `chunk_time_interval => INTERVAL '1 day'`)

### Python packages / modules (D-07)
- `services.poller`, `services.poller.scheduler`, `services.poller.publisher`, `services.poller.sources.base`, `services.poller.sources.opentable.adapter`, `services.poller.sources.opentable.graphql`
- `services.state_machine` (P2 stub — do NOT create empty; create in P2)
- `services.notifier` (P4 stub — do NOT create empty)
- `services.api` (P5 stub — do NOT create empty)
- `shared.events`, `shared.kafka`, `shared.redis_keys`, `shared.db`, `shared.telemetry`

### Scripts
- `scripts/create_topics.py`
- `scripts/seed_restaurants.py`
- `scripts/seed/restaurants.yml`
- `scripts/check_poll_success.py`
- `scripts/replay_raw.py` (P2 — do NOT create at P1, but design `AvailabilityRaw` payload to make it possible)

### Makefile targets (D-10)
- `help`, `up`, `down`, `topics`, `migrate`, `seed`, `poll`, `test`, `test-integration`, `lint`, `fmt`, `smoke`, `verify-seed`, `verify-perf02`

### Config identifiers
- `restaurants.source` values: `"opentable"`, `"resy"` (only `"opentable"` populated at P1)
- `poll_log.status` values: `"success"`, `"error"`, `"timeout"`

### Runbooks (user-executed reference docs)
- `docs/runbooks/twilio-10dlc-setup.md` (exists)
- `docs/runbooks/domain-registration.md` (new at P1)
- `docs/runbooks/gcp-provisioning.md` (new at P1)
- `docs/runbooks/perf02-24h-log.md` (new at P1, template for long-run observation)

---

## External Docs / URLs (cite in code comments)

- **aiokafka 0.13.0:** https://aiokafka.readthedocs.io/en/v0.13.0/
- **aiokafka producer config (acks, idempotence):** https://aiokafka.readthedocs.io/en/v0.13.0/api.html#producer-class
- **Apache Kafka KRaft mode (3.8):** https://kafka.apache.org/documentation/#kraft
- **Bitnami Kafka Docker (KRaft-mode env vars):** https://hub.docker.com/r/bitnami/kafka
- **redis-py async docs (7.4):** https://redis.readthedocs.io/en/latest/examples/asyncio_examples.html
- **Redis `EVAL`/`EVALSHA`:** https://redis.io/docs/latest/commands/evalsha/
- **Redis `SET NX EX` atomic (Pitfall 7):** https://redis.io/docs/latest/commands/set/
- **Redis `maxmemory-policy` (Pitfall 18):** https://redis.io/docs/latest/develop/reference/eviction/
- **TimescaleDB `create_hypertable`:** https://docs.tigerdata.com/api/latest/hypertable/create_hypertable/
- **TimescaleDB chunk intervals:** https://docs.tigerdata.com/api/latest/hypertable/set_chunk_time_interval/
- **Alembic + TimescaleDB discussion (autogenerate trap):** https://github.com/sqlalchemy/alembic/discussions/1465
- **SQLAlchemy 2.0 async ORM:** https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- **asyncpg:** https://magicstack.github.io/asyncpg/current/
- **psycopg 3:** https://www.psycopg.org/psycopg3/docs/
- **httpx 0.28 AsyncClient + Limits:** https://www.python-httpx.org/async/
- **tenacity 9.1:** https://tenacity.readthedocs.io/en/latest/
- **pydantic 2.13:** https://docs.pydantic.dev/latest/
- **pydantic-settings:** https://docs.pydantic.dev/latest/concepts/pydantic_settings/
- **structlog 25.5:** https://www.structlog.org/en/stable/
- **testcontainers-python 4.x:** https://testcontainers-python.readthedocs.io/en/latest/
- **respx (httpx mocks):** https://lundberg.github.io/respx/
- **pytest-asyncio 1.1:** https://pytest-asyncio.readthedocs.io/en/v1.1.0/
- **Twilio A2P 10DLC (FOUND-05):** https://www.twilio.com/docs/messaging/compliance/a2p-10dlc
- **Twilio Toll-Free Verification backup:** https://www.twilio.com/docs/messaging/compliance/toll-free-message-verification
- **GCP enable APIs:** https://cloud.google.com/endpoints/docs/openapi/enable-api
- **pywebpush VAPID key generation (D-25):** https://github.com/web-push-libs/pywebpush
- **OpenTable widget / community adapters (Focus Area 4 — reference, not canonical):**
  - https://jonluca.substack.com/p/opentable
  - https://github.com/nfmcclure/opentable_availability_check
  - https://github.com/sosedoff/opentable/issues/6
- **NY Restaurant Reservation Anti-Piracy Act (README legal section, Pitfall 8):** https://www.hklaw.com/en/insights/publications/2025/02/new-york-curbs-scalping-of-restaurant-reservations
- **OpenTable Terms of Use (README legal section):** https://www.opentable.com/c/legal/terms-and-conditions/

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | OpenTable widget GraphQL endpoint is at `https://www.opentable.com/dapi/fe/gql/prod` (or a very similar path) and accepts `restaurantIds` + `partySize` + `dateTime` variables without cookies | Focus Area 4 | If gated, fall back to widget HTML + `__NEXT_DATA__` JSON parse; schedule a 30-minute spike in Wave 3d to confirm before implementation proceeds. If endpoint is fundamentally different, the adapter module isolates the blast radius. |
| A2 | `aiokafka 0.13.0` successfully produces to `bitnami/kafka:3.8` in KRaft mode with `acks=all` and `enable_idempotence=True` on a single broker | Focus Area 1 | Combination is well-documented but not formally regression-tested for us; integration smoke test in Wave 4 catches mismatches before phase exit. |
| A3 | `timescale/timescaledb:2.17.2-pg16` Docker image tag exists on Docker Hub | Focus Area 6 | If tag missing, use `timescale/timescaledb-ha:pg16` (HA image, same extension). Trivial swap. |
| A4 | `testcontainers-python 4.x` supports KRaft-mode Kafka (`with_kraft()` or apache-image auto-KRaft) | Focus Area 6 | If not, fall back to `confluentinc/cp-kafka:7.7` with manual KRaft env vars in the container, or run against the host docker-compose for integration tests. |
| A5 | OpenTable tolerates ~1 req/sec per restaurant for the widget endpoint without rate-limit action | Focus Area 4 | Community sources suggest this; at 50 restaurants × 90s cadence we're at 0.55 req/s globally, well under. If OpenTable pushes back (429s appear in `poll_log`), reduce cadence to 120s (still within POLL-03's "≥90s minimum") and document. |
| A6 | Kafka UI choice (redpanda-console vs kafka-ui vs kafdrop) is purely aesthetic at MVP scale | Focus Area 1 | All three work; plan picks one and moves on. |

**Resolution strategy:** A1 and A5 are the only assumptions with real execution risk. A1 is resolved by a bounded 30-minute spike at the start of Wave 3d (`services/poller/sources/opentable/adapter.py`). A5 is resolved passively by `poll_log` observations during the 24h SC5 run — if any hour shows <99% due to 429s, cadence is the first knob to turn.

---

## Risks & Open Questions

1. **OpenTable schema drift risk:** The widget GraphQL endpoint has no published contract. Mitigation: log full raw response into `availability.raw` (D-19); versioned `SCHEMA_VERSION` comment at the top of `graphql.py`; single-module blast radius. Flag for Phase 2 to add a weekly "OpenTable canary" smoke test once State Machine is live.

2. **Twilio 10DLC approval latency outside our control:** Standard Campaigns can take 1–3 weeks. P1 exit requires only "Submitted/Pending/Registered" per SC2, not "Registered." But Phase 4 (SMS worker) will block on actual "Registered" status. Planner should flag this as a known cross-phase dependency and recommend the team start P2 code work immediately after P1 exits — the waiting clock overlaps cleanly with P2's 1-week State Machine work.

3. **50-restaurant hand-curation is high-variance user work:** Could be 4h or 8h depending on research depth. Mitigation: Wave 0.5f runs parallel to Waves 1–4 code work; seed script is idempotent so incremental curation (10-at-a-time) is safe; phase exit gate checks the count.

4. **PERF-02 24h observation run is a wall-clock blocker at phase exit:** There's no way to compress 24 hours. Mitigation: start the run as soon as Wave 4 is green, even before all verification artifacts (Wave 5) exist, so the 24h timer overlaps with Wave 5 work.

5. **Cloud SQL + TimescaleDB incompatibility surfaces here, not in P7:** D-04 already flags this (TimescaleDB must be self-hosted on GCE, not Cloud SQL). P1 uses local docker-compose so doesn't hit it; but when P7 provisions production infra, the plan must include a GCE VM for Timescale co-located with Kafka. Documented in STACK.md; planner flags for P7 prep at the end of P1.

6. **Pydantic v2 breaking-change surface area:** v2 is Rust-backed and well-maintained, but the `model_dump_json()` API and field validators differ from v1. Since this is greenfield, no migration — but the planner must ensure all code examples use v2 patterns (`field_validator` not `validator`, `model_config` not `Config` class).

7. **structlog + aiokafka interaction:** aiokafka uses Python stdlib logging; structlog's stdlib bridge (`LoggerFactory`) handles this. No action needed beyond what's already specified.

8. **ZSET jitter accuracy:** Python's `random.uniform` is sufficient for ±15% jitter; no need for a cryptographic RNG. Documented in Focus Area 3 for clarity.

---

## RESEARCH COMPLETE

All 10 focus areas addressed with HIGH or MEDIUM-with-mitigation confidence. All 10 phase requirement IDs (FOUND-01..06, POLL-01, POLL-03, POLL-07, PERF-02) traced to research sections and named verification artifacts. Validation Architecture populated per Nyquist Dimension 8 with one named artifact per success criterion. Build Order proposes 7 waves respecting D-07, D-10, D-27, D-30, and the D-14..D-16 curation-as-admin-work constraint. Named Symbols section exhaustively enumerates every identifier plans must use verbatim. Two MEDIUM-confidence items (A1 OpenTable endpoint, A5 rate-limit tolerance) are flagged in the Assumptions Log with bounded resolution strategies.

**Ready for planning.**
