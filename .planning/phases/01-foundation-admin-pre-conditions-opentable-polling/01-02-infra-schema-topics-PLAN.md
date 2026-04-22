---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 02
type: execute
wave: 2
depends_on: ["01"]
files_modified:
  - ops/docker-compose.yml
  - migrations/env.py
  - migrations/script.py.mako
  - migrations/README.md
  - migrations/versions/0001_extensions.py
  - migrations/versions/0002_create_users.py
  - migrations/versions/0003_create_restaurants.py
  - migrations/versions/0004_create_watchlist_entries.py
  - migrations/versions/0005_create_notification_log.py
  - migrations/versions/0006_create_availability_events_hypertable.py
  - migrations/versions/0007_create_poll_log_hypertable.py
  - alembic.ini
  - scripts/create_topics.py
autonomous: true
requirements_addressed:
  - FOUND-01
  - FOUND-02
  - FOUND-04

must_haves:
  truths:
    - "`docker compose -f ops/docker-compose.yml up -d` starts Kafka (KRaft), Redis 7.2+, TimescaleDB/Postgres 16, and Kafka UI with all services healthy"
    - "`make migrate` applies all 7 Alembic migrations against a running Postgres+TimescaleDB without error"
    - "Both `availability_events` and `poll_log` are hypertables with chunk_time_interval = 86400000000 microseconds (1 day)"
    - "`make topics` idempotently creates all 5 Kafka topics with correct retention.ms values"
    - "Redis `CONFIG GET maxmemory-policy` returns `noeviction`"
    - "Kafka broker has a named persistent volume for its log directory (Pitfall 11)"
  artifacts:
    - path: ops/docker-compose.yml
      provides: "Infra-only compose: Kafka KRaft, Redis, TimescaleDB, Kafka UI"
      contains: "kafka-data"
    - path: migrations/versions/0001_extensions.py
      provides: "Enables timescaledb and pgcrypto extensions (D-32)"
      contains: "pgcrypto"
    - path: migrations/versions/0006_create_availability_events_hypertable.py
      provides: "availability_events hypertable with chunk_time_interval=1 day"
      contains: "create_hypertable"
    - path: migrations/versions/0007_create_poll_log_hypertable.py
      provides: "poll_log hypertable with all Named Symbol columns"
      contains: "poll_log"
    - path: scripts/create_topics.py
      provides: "Idempotent Kafka topic creation for all 5 topics"
      contains: "availability.raw"
  key_links:
    - from: ops/docker-compose.yml
      to: "migrations/versions/0001_extensions.py"
      via: "Postgres+TimescaleDB container; migrate runs after `make up`"
      pattern: "timescale/timescaledb"
    - from: scripts/create_topics.py
      to: "availability.raw"
      via: "AIOKafkaAdminClient.create_topics()"
      pattern: "availability\\.raw"
---

<objective>
Stand up the full local infrastructure: Kafka KRaft single-broker, Redis 7.2+, TimescaleDB 2.17/Postgres 16, and a Kafka UI. Run Alembic migrations to create all P1 tables including the two TimescaleDB hypertables. Create all 5 Kafka topics with correct retention policies via an idempotent script.

Purpose: This plan delivers the persistent data layer and event bus that every subsequent plan depends on. SC4 (hypertables exist with correct chunk_time_interval) is validated here. SC1 (compose up starts infra) is delivered here.

Output: `ops/docker-compose.yml`, 7 Alembic migration files, `alembic.ini`, `scripts/create_topics.py`.
</objective>

<execution_context>
@/Users/aryanahuja/projects/mise/.claude/get-shit-done/workflows/execute-plan.md
@/Users/aryanahuja/projects/mise/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/ROADMAP.md
@.planning/REQUIREMENTS.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md
@.planning/research/STACK.md
@.planning/research/PITFALLS.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-01-SUMMARY.md
</context>

<tasks>

<task id="01-02-T1" type="auto">
  <name>Task 1: ops/docker-compose.yml — Kafka KRaft, Redis, TimescaleDB, Kafka UI</name>
  <files>ops/docker-compose.yml</files>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-02, D-03, D-04, D-08),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§1 aiokafka KRaft docker-compose excerpt),
    .planning/research/PITFALLS.md (§ Pitfall 11 persistent volume, § Pitfall 18 noeviction)
  </read_first>
  <action>
Create `ops/docker-compose.yml`. Use bitnami/kafka:3.8 image with KRaft mode (no ZooKeeper). The compose file runs infra only — Python services run on the host (D-08).

```yaml
version: "3.9"

services:
  kafka:
    image: bitnami/kafka:3.8
    container_name: mise-kafka
    ports:
      - "9092:9092"
      - "9094:9094"
    environment:
      KAFKA_CFG_NODE_ID: 1
      KAFKA_CFG_PROCESS_ROLES: broker,controller
      KAFKA_CFG_CONTROLLER_QUORUM_VOTERS: 1@kafka:9093
      KAFKA_CFG_LISTENERS: PLAINTEXT://:9092,CONTROLLER://:9093,EXTERNAL://:9094
      KAFKA_CFG_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092,EXTERNAL://localhost:9094
      KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP: CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT,EXTERNAL:PLAINTEXT
      KAFKA_CFG_CONTROLLER_LISTENER_NAMES: CONTROLLER
      KAFKA_CFG_INTER_BROKER_LISTENER_NAME: PLAINTEXT
      KAFKA_CFG_DEFAULT_REPLICATION_FACTOR: 1
      KAFKA_CFG_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_CFG_TRANSACTION_STATE_LOG_REPLICATION_FACTOR: 1
      KAFKA_CFG_MIN_INSYNC_REPLICAS: 1
      KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE: "false"
      KAFKA_KRAFT_CLUSTER_ID: MkU3OEVBNTcwNTJENDM2Qg
    volumes:
      - kafka-data:/bitnami/kafka
    healthcheck:
      test: ["CMD-SHELL", "kafka-topics.sh --bootstrap-server localhost:9092 --list"]
      interval: 10s
      timeout: 5s
      retries: 6
    networks:
      - default

  redis:
    image: redis:7.2-alpine
    container_name: mise-redis
    ports:
      - "6379:6379"
    command: redis-server --maxmemory-policy noeviction --appendonly yes
    volumes:
      - redis-data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
    networks:
      - default

  postgres:
    image: timescale/timescaledb:2.17.2-pg16
    container_name: mise-postgres
    ports:
      - "5432:5432"
    environment:
      POSTGRES_USER: mise
      POSTGRES_PASSWORD: mise
      POSTGRES_DB: mise
    volumes:
      - postgres-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U mise -d mise"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks:
      - default

  kafka-ui:
    image: provectuslabs/kafka-ui:latest
    container_name: mise-kafka-ui
    ports:
      - "8080:8080"
    environment:
      KAFKA_CLUSTERS_0_NAME: local
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka:9092
    depends_on:
      kafka:
        condition: service_healthy
    networks:
      - default

volumes:
  kafka-data:
  redis-data:
  postgres-data:

networks:
  default:
    name: mise-default
```

Key constraints verified:
- Kafka volume `kafka-data:/bitnami/kafka` — persistent, not ephemeral (Pitfall 11)
- Redis command includes `--maxmemory-policy noeviction` (Pitfall 18, D-03)
- KRaft mode: no ZooKeeper service (D-02)
- All services on named `default` network
- EXTERNAL listener on port 9094 allows host Python services to connect at `localhost:9094`
  </action>
  <verify>
    <automated>python3 -c "import yaml; d=yaml.safe_load(open('ops/docker-compose.yml')); assert 'kafka-data' in str(d['volumes']); assert 'noeviction' in d['services']['redis']['command']; assert 'CONTROLLER' in str(d['services']['kafka']['environment']); print('docker-compose.yml OK')"</automated>
  </verify>
  <done>
    ops/docker-compose.yml valid YAML with: Kafka KRaft (bitnami:3.8, persistent kafka-data volume, EXTERNAL listener :9094); Redis 7.2-alpine with --maxmemory-policy noeviction --appendonly yes; timescale/timescaledb:2.17.2-pg16; kafka-ui; all services healthchecked; all on named network
  </done>
</task>

<task id="01-02-T2" type="auto">
  <name>Task 2: Alembic init + 7 migration files</name>
  <files>
    alembic.ini,
    migrations/env.py,
    migrations/script.py.mako,
    migrations/README.md,
    migrations/versions/0001_extensions.py,
    migrations/versions/0002_create_users.py,
    migrations/versions/0003_create_restaurants.py,
    migrations/versions/0004_create_watchlist_entries.py,
    migrations/versions/0005_create_notification_log.py,
    migrations/versions/0006_create_availability_events_hypertable.py,
    migrations/versions/0007_create_poll_log_hypertable.py
  </files>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-04, D-30, D-31, D-32, D-33),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§2 TimescaleDB Alembic migration pattern — verbatim code examples),
    .planning/research/PITFALLS.md (§ Pitfall 12 — autogenerate ban)
  </read_first>
  <action>
Run `uv run alembic init migrations` to generate the scaffold, then replace/customize the generated files.

Create `alembic.ini` at repo root, setting `sqlalchemy.url` to use `DATABASE_URL_SYNC` env var:
```ini
[alembic]
script_location = migrations
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url = postgresql+psycopg://mise:mise@localhost:5432/mise

[post_write_hooks]

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

Replace `migrations/env.py` to use psycopg3 sync driver (D-04, D-30):
```python
"""Alembic env.py — psycopg3 sync driver (D-04, D-30). DO NOT use asyncpg here."""
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override sqlalchemy.url from env if DATABASE_URL_SYNC is set
database_url = os.getenv("DATABASE_URL_SYNC")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Import Base to make target_metadata available (filled in later plans)
try:
    from shared.db import Base
    target_metadata = Base.metadata
except ImportError:
    target_metadata = None


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
            # CRITICAL: do NOT enable autogenerate for hypertables (Pitfall 12)
        )
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

Create `migrations/README.md`:
```markdown
# Migrations

## Rules

**NEVER run `alembic revision --autogenerate` after a hypertable exists.**

TimescaleDB wraps the `time` column in internal chunk management structures.
If autogenerate scans the live database, it will try to drop/recreate the time index
and corrupt the hypertable (Alembic issue #1465, Pitfall 12 in PITFALLS.md).

Always hand-write hypertable migrations using:
```python
op.execute(
    "SELECT create_hypertable('table_name', 'time', "
    "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
)
```

## Migration Order

| Revision | Table / Action |
|----------|----------------|
| 0001_extensions | CREATE EXTENSION timescaledb, pgcrypto |
| 0002_create_users | users table |
| 0003_create_restaurants | restaurants table |
| 0004_create_watchlist_entries | watchlist_entries table |
| 0005_create_notification_log | notification_log table |
| 0006_create_availability_events_hypertable | availability_events hypertable (chunk=1d) |
| 0007_create_poll_log_hypertable | poll_log hypertable (chunk=1d) |
```

Create migration files. Each has a `revision`, `down_revision`, `upgrade()`, and `downgrade()`.

`migrations/versions/0001_extensions.py`:
```python
"""0001: Enable timescaledb and pgcrypto extensions."""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")  # D-32: phone columns BYTEA


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS timescaledb")
```

`migrations/versions/0002_create_users.py`:
```python
"""0002: Create users table."""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("phone", sa.LargeBinary, nullable=True),  # BYTEA — AES-256-GCM via pgcrypto (D-32, T-04)
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
```

`migrations/versions/0003_create_restaurants.py`:
```python
"""0003: Create restaurants table."""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "restaurants",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),          # 'opentable' | 'resy'
        sa.Column("platform_id", sa.Text, nullable=False),     # stringified OT rid or Resy venue_id
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("neighborhood", sa.Text, nullable=False),
        sa.Column("cuisine", sa.Text, nullable=False),
        sa.Column(
            "price_tier",
            sa.Integer,
            sa.CheckConstraint("price_tier BETWEEN 1 AND 4", name="ck_restaurants_price_tier"),
            nullable=False,
        ),
        sa.Column("cover_photo_url", sa.Text, nullable=False),
        sa.Column("date_range_days", sa.Integer, server_default="7", nullable=False),
        sa.Column(
            "party_sizes",
            sa.ARRAY(sa.Integer),
            server_default=sa.text("'{2,4}'::integer[]"),
            nullable=False,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "platform_id", name="uq_restaurants_source_platform_id"),
    )
    op.create_index("ix_restaurants_slug", "restaurants", ["slug"], unique=True)
    op.create_index("ix_restaurants_source_platform_id", "restaurants", ["source", "platform_id"])


def downgrade() -> None:
    op.drop_index("ix_restaurants_source_platform_id", table_name="restaurants")
    op.drop_index("ix_restaurants_slug", table_name="restaurants")
    op.drop_table("restaurants")
```

`migrations/versions/0004_create_watchlist_entries.py`:
```python
"""0004: Create watchlist_entries table (columns only; CRUD in Phase 5)."""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger, sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("date_from", sa.Date, nullable=False),
        sa.Column("date_to", sa.Date, nullable=False),
        sa.Column("time_window_from", sa.Time, nullable=True),
        sa.Column("time_window_to", sa.Time, nullable=True),
        sa.Column("days_of_week", sa.Text, nullable=True),  # comma-separated: "mon,tue,fri"
        sa.Column("seat_type_filter", sa.Text, nullable=True),
        sa.Column("channels", sa.Text, server_default="email", nullable=False),  # "email,sms,push"
        sa.Column("status", sa.Text, server_default="active", nullable=False),  # active|paused|deleted
        sa.Column("management_token", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_watchlist_entries_user_id", "watchlist_entries", ["user_id"])
    op.create_index("ix_watchlist_entries_restaurant_id", "watchlist_entries", ["restaurant_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_entries_restaurant_id", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_user_id", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
```

`migrations/versions/0005_create_notification_log.py`:
```python
"""0005: Create notification_log table (columns only; writes in Phase 4)."""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watchlist_entries.id"), nullable=False),
        sa.Column("event_id", sa.Text, nullable=False),
        sa.Column("channel", sa.Text, nullable=False),  # email|sms|push
        sa.Column("status", sa.Text, nullable=False),   # sent|delivered|clicked|failed
        sa.Column("provider_id", sa.Text, nullable=True),  # Twilio SID, Resend ID, etc.
        sa.Column("slot_still_available", sa.Boolean, nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_log_watch_id", "notification_log", ["watch_id"])
    op.create_index("ix_notification_log_event_id", "notification_log", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_log_event_id", table_name="notification_log")
    op.drop_index("ix_notification_log_watch_id", table_name="notification_log")
    op.drop_table("notification_log")
```

`migrations/versions/0006_create_availability_events_hypertable.py`:
```python
"""0006: Create availability_events hypertable (chunk_time_interval = 1 day, D-33)."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: create plain Postgres table
    op.create_table(
        "availability_events",   # restaurant_id is BigInteger to match restaurants.id
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("time_slot", sa.Time, nullable=True),
        sa.Column("party_size", sa.Integer, nullable=True),
        sa.Column("seat_type", sa.Text, nullable=True),
        sa.Column("booking_token", sa.Text, nullable=True),
        sa.Column("first_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("hours_before_service", sa.Float, nullable=True),
        sa.Column("day_of_week", sa.Integer, nullable=True),  # 0=Mon..6=Sun
    )
    # Step 2: convert to hypertable — NEVER autogenerate (Pitfall 12, D-33)
    op.execute(
        "SELECT create_hypertable('availability_events', 'time', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )
    op.create_index("ix_avail_events_restaurant_time", "availability_events", ["restaurant_id", "time"])


def downgrade() -> None:
    op.drop_index("ix_avail_events_restaurant_time", table_name="availability_events")
    op.drop_table("availability_events")
```

`migrations/versions/0007_create_poll_log_hypertable.py`:
```python
"""0007: Create poll_log hypertable (chunk_time_interval = 1 day, D-33)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: create plain Postgres table — Named Symbol columns verbatim
    op.create_table(
        "poll_log",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger, nullable=False),   # matches restaurants.id (BigInteger)
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),   # 'success' | 'error' | 'timeout'
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("poll_id", UUID(as_uuid=True), nullable=False),
    )
    # Step 2: convert to hypertable with explicit chunk_time_interval (D-33, Pitfall 12)
    op.execute(
        "SELECT create_hypertable('poll_log', 'time', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )
    # Step 3: supporting index (Timescale auto-creates on `time`)
    op.create_index("ix_poll_log_restaurant_time", "poll_log", ["restaurant_id", "time"])


def downgrade() -> None:
    op.drop_index("ix_poll_log_restaurant_time", table_name="poll_log")
    op.drop_table("poll_log")
```
  </action>
  <verify>
    <automated>python3 -c "
import ast, pathlib
for f in ['0001_extensions.py','0006_create_availability_events_hypertable.py','0007_create_poll_log_hypertable.py']:
    txt = pathlib.Path(f'migrations/versions/{f}').read_text()
    assert 'create_hypertable' in txt or 'pgcrypto' in txt, f'Missing expected content in {f}'
    if 'hypertable' in f:
        assert 'autogenerate' not in txt.lower() or '# NEVER' in txt, f'autogenerate reference in {f}'
print('Migration files OK')
" && grep -q "noeviction" ops/docker-compose.yml && grep -q "kafka-data" ops/docker-compose.yml</automated>
  </verify>
  <done>
    7 migration files exist with correct revision chains (0001→0007); 0006 and 0007 use op.execute("SELECT create_hypertable(...)") with chunk_time_interval => INTERVAL '1 day'; 0001 enables pgcrypto; users.phone is BYTEA; ops/docker-compose.yml has kafka-data volume and Redis noeviction; migrations/README.md bans autogenerate
  </done>
</task>

<task id="01-02-T3" type="auto">
  <name>Task 3: scripts/create_topics.py and [BLOCKING] infra verification</name>
  <files>scripts/create_topics.py</files>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-27, D-28, D-29),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§1 topic creation script verbatim)
  </read_first>
  <action>
Create `scripts/create_topics.py` using the exact retention values from D-27:

```python
#!/usr/bin/env python
"""
Idempotent Kafka topic creation for Mise en Place (D-27).
Run: uv run python scripts/create_topics.py
Or:  make topics

Topics and retention:
  availability.raw      1 partition, 24h  (86_400_000 ms)
  availability.events   1 partition, 7d   (604_800_000 ms)
  polls.completed       1 partition, 7d   (604_800_000 ms)
  notifications.queued  1 partition, 30d  (2_592_000_000 ms)
  notifications.sent    1 partition, 30d  (2_592_000_000 ms)

Named Symbols (D-27, D-28, D-29):
  Kafka topics: availability.raw, availability.events, notifications.queued,
                notifications.sent, polls.completed
  Message key: {source}:{restaurant_id}
  Replication factor: 1 (MVP single-broker; documented tradeoff in README, Pitfall 11)
"""
import asyncio
import os

from aiokafka.admin import AIOKafkaAdminClient, NewTopic


BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")

TOPICS = [
    NewTopic(
        "availability.raw",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(86_400_000)},       # 24h
    ),
    NewTopic(
        "availability.events",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(604_800_000)},      # 7d
    ),
    NewTopic(
        "polls.completed",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(604_800_000)},      # 7d
    ),
    NewTopic(
        "notifications.queued",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(2_592_000_000)},    # 30d
    ),
    NewTopic(
        "notifications.sent",
        num_partitions=1,
        replication_factor=1,
        topic_configs={"retention.ms": str(2_592_000_000)},    # 30d
    ),
]


async def main() -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=BOOTSTRAP_SERVERS)
    await admin.start()
    try:
        existing: set[str] = set(await admin.list_topics())
        to_create = [t for t in TOPICS if t.name not in existing]
        if to_create:
            await admin.create_topics(to_create)
            print(f"Created topics: {[t.name for t in to_create]}")
        else:
            print("All topics already exist — idempotent no-op")
    finally:
        await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
```

After writing this file, run the [BLOCKING] infra verification:

```bash
make up && sleep 15 && make migrate
```

Then verify hypertables:
```bash
psql "$DATABASE_URL_SYNC" -tAc "SELECT hypertable_name, chunk_time_interval FROM timescaledb_information.dimensions WHERE hypertable_name IN ('poll_log','availability_events') ORDER BY hypertable_name;"
```

Expected output (both rows must be present):
```
availability_events|86400000000
poll_log|86400000000
```

If the psql command is not available, connect via Docker:
```bash
docker exec mise-postgres psql -U mise -d mise -tAc "SELECT hypertable_name, chunk_time_interval FROM timescaledb_information.dimensions WHERE hypertable_name IN ('poll_log','availability_events') ORDER BY hypertable_name;"
```

Both rows must return `86400000000` microseconds (= 1 day) — this verifies SC4 foundation.

Also run `make topics` and verify output shows all 5 topics created or "already exist".
  </action>
  <verify>
    <automated>python3 -c "
import ast, pathlib
src = pathlib.Path('scripts/create_topics.py').read_text()
assert 'availability.raw' in src
assert 'availability.events' in src
assert 'polls.completed' in src
assert 'notifications.queued' in src
assert 'notifications.sent' in src
assert '86_400_000' in src or '86400000' in src
assert '604_800_000' in src or '604800000' in src
assert '2_592_000_000' in src or '2592000000' in src
assert 'AIOKafkaAdminClient' in src
print('create_topics.py OK')
"</automated>
  </verify>
  <done>
    scripts/create_topics.py has all 5 topics with correct retention.ms values; AIOKafkaAdminClient used (not kafka-python); script is idempotent (skips existing topics); BLOCKING verification: `make migrate` runs without error; both hypertables return chunk_time_interval=86400000000 from timescaledb_information.dimensions; `make topics` runs without error
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| DB column → application | phone columns defined as BYTEA from day 1; no plaintext phone values ever written |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-04 | Information Disclosure | users.phone column / pgcrypto | mitigate | pgcrypto extension enabled in migration 0001; users.phone defined as `BYTEA` (not `TEXT`) in migration 0002 per D-32; application layer never writes plaintext phone numbers — Phase 5 will encrypt via pgcrypto AES-256-GCM before INSERT; database dump of `users.phone` will show only `\x...` bytes |
</threat_model>

<verification>
After all three tasks complete:

```bash
# 1. Compose file valid
docker compose -f ops/docker-compose.yml config --quiet

# 2. All 7 migrations exist
ls migrations/versions/ | wc -l | grep "^7"

# 3. Hypertable migrations use op.execute (not autogenerate)
grep -l "create_hypertable" migrations/versions/*.py | wc -l | grep "^2"

# 4. create_topics.py has all 5 topic names
grep -c "availability\.\|polls\.\|notifications\." scripts/create_topics.py | grep -q "[5-9]"

# 5. Redis noeviction in compose
grep -q "noeviction" ops/docker-compose.yml && echo "noeviction OK"

# 6. Kafka persistent volume
grep -q "kafka-data" ops/docker-compose.yml && echo "kafka-data volume OK"

# 7. Unit tests still pass
uv run pytest tests/unit -x -q
```
</verification>

<success_criteria>
- `ops/docker-compose.yml` has Kafka (KRaft, bitnami:3.8, persistent kafka-data volume), Redis (7.2-alpine, noeviction, appendonly yes), TimescaleDB (2.17.2-pg16), Kafka UI, all on named network
- All 7 Alembic migration files exist with correct revision chain (0001→0007)
- Migration 0006 and 0007 use `op.execute("SELECT create_hypertable(..., chunk_time_interval => INTERVAL '1 day', ...)")` — no autogenerate
- Migration 0001 enables both `timescaledb` and `pgcrypto`
- `users.phone` column type is `sa.LargeBinary` (BYTEA)
- `poll_log` columns match Named Symbols verbatim: time, restaurant_id, source, status, latency_ms, http_status, error, poll_id
- `scripts/create_topics.py` uses `AIOKafkaAdminClient`, creates all 5 Named Symbol topics with correct retention.ms, is idempotent
- [BLOCKING] `make migrate` succeeds against running TimescaleDB; both hypertables show `chunk_time_interval=86400000000` µs
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-02-SUMMARY.md`
</output>
