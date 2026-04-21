---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - pyproject.toml
  - uv.lock
  - Makefile
  - .env.example
  - .gitignore
  - .ruff.toml
  - CONTRIBUTING.md
  - shared/__init__.py
  - shared/events.py
  - shared/redis_keys.py
  - shared/telemetry.py
  - tests/conftest.py
  - tests/unit/__init__.py
  - tests/unit/test_redis_keys.py
  - tests/unit/test_events_schema.py
  - tests/unit/test_telemetry_redaction.py
  - tests/integration/__init__.py
  - tests/integration/test_poller_smoke.py
  - tests/integration/test_seed_idempotency.py
  - tests/integration/test_hypertable_config.py
  - tests/integration/test_poll_log_writes.py
  - tests/integration/test_topics_created.py
  - tests/integration/test_redis_config.py
  - tests/integration/test_scheduler_claim_release.py
  - scripts/check_poll_success.py
  - docs/runbooks/perf02-24h-log.md
  - docs/admin-evidence/.gitkeep
autonomous: true
requirements_addressed:
  - FOUND-01

must_haves:
  truths:
    - "pyproject.toml exists with all pinned deps from STACK.md and a [dependency-groups.dev] block"
    - "`uv run python -c 'import shared.events'` succeeds after `uv sync`"
    - "`make help` prints all defined targets without error"
    - "All Wave-0 test stubs exist and `uv run pytest tests/unit -x -q` completes (skips/xfails acceptable; import errors are not)"
    - "`.env` is in `.gitignore`; `.env.example` lists all Named Symbol env vars"
    - "`.ruff.toml` bans `import requests`, `time.sleep(`, and sync `import redis` without `.asyncio`"
  artifacts:
    - path: pyproject.toml
      provides: "Pinned dependency declarations for all runtime + dev libs"
      contains: "asyncio_mode"
    - path: Makefile
      provides: "Command facade with all required targets"
      contains: "verify-perf02"
    - path: shared/events.py
      provides: "Empty scaffold with correct imports (Pydantic v2)"
    - path: shared/redis_keys.py
      provides: "SCHED_POLLS and SCHED_POLLS_INFLIGHT constant stubs"
    - path: tests/conftest.py
      provides: "Shared testcontainers fixtures at module scope"
    - path: tests/integration/test_poller_smoke.py
      provides: "Wave-0 stub for SC1"
    - path: scripts/check_poll_success.py
      provides: "Wave-0 stub for SC5/PERF-02"
  key_links:
    - from: pyproject.toml
      to: tests/conftest.py
      via: "[tool.pytest.ini_options] asyncio_mode=auto"
      pattern: "asyncio_mode"
    - from: .gitignore
      to: .env
      via: "gitignore entry"
      pattern: "^\\.env$"
---

<objective>
Scaffold the monorepo: install all pinned dependencies, create the Makefile command facade, establish shared skeleton modules, write all Wave-0 test stubs from 01-VALIDATION.md, and configure the ruff lint bans that enforce async hygiene throughout the codebase.

Purpose: Later plans build on top of this foundation. Every subsequent plan's `<automated>` verify command references a file created here (either a test stub or a Makefile target).

Output: A fully-importable `shared/` package, a functional `pyproject.toml` + `uv.lock`, a Makefile with all required targets, and a complete set of Wave-0 test stubs that collect (not fail) with a single `uv run pytest tests/unit -x -q` invocation.
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
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-VALIDATION.md
@.planning/research/STACK.md
@.planning/research/PITFALLS.md
</context>

<tasks>

<task id="01-01-T1" type="auto">
  <name>Task 1: pyproject.toml, uv.lock, .gitignore, .env.example</name>
  <files>
    pyproject.toml,
    uv.lock,
    .gitignore,
    .env.example
  </files>
  <read_first>
    .planning/research/STACK.md (§ Installation / pyproject.toml excerpt),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-01, D-09, D-34, D-35),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§ Named Symbols — env vars list)
  </read_first>
  <action>
Create `pyproject.toml` at repo root with the following exact content:

```toml
[project]
name = "mise"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = [
    "fastapi==0.136.0",
    "uvicorn[standard]==0.44.0",
    "pydantic==2.13.3",
    "pydantic-settings>=2.6",
    "playwright==1.58.0",
    "tf-playwright-stealth==1.2.0",
    "httpx==0.28.1",
    "tenacity==9.1.4",
    "aiokafka==0.13.0",
    "redis==7.4.0",
    "sqlalchemy[asyncio]==2.0.49",
    "asyncpg==0.31.0",
    "psycopg[binary]==3.3.3",
    "alembic==1.18.4",
    "resend==2.29.0",
    "twilio==9.10.5",
    "pywebpush==2.3.0",
    "cryptography>=43",
    "prometheus-client==0.25.0",
    "prometheus-fastapi-instrumentator==7.1.0",
    "structlog==25.5.0",
    "orjson==3.11.8",
]

[dependency-groups]
dev = [
    "pytest==9.0.3",
    "pytest-asyncio==1.1.0",
    "pytest-httpx>=0.35",
    "testcontainers[kafka,redis,postgres]>=4.8",
    "respx>=0.21",
    "freezegun>=1.5",
    "ruff>=0.8",
    "mypy>=1.13",
    "pre-commit>=4.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["."]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Run `uv sync` to generate `uv.lock`. Commit both files.

Create `.gitignore` at repo root containing at minimum:
```
.env
.venv/
__pycache__/
*.pyc
*.pyo
*.pyd
.mypy_cache/
.pytest_cache/
.ruff_cache/
dist/
build/
*.egg-info/
.coverage
htmlcov/
```

Create `.env.example` listing all Named Symbol env vars with placeholder values:
```
# Kafka
KAFKA_BOOTSTRAP_SERVERS=localhost:9094

# Redis
REDIS_URL=redis://localhost:6379/0

# Database
DATABASE_URL=postgresql+asyncpg://mise:mise@localhost:5432/mise
DATABASE_URL_SYNC=postgresql+psycopg://mise:mise@localhost:5432/mise

# Twilio
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_MESSAGING_SERVICE_SID=MGxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Resy
RESY_ACCOUNTS_JSON=[{"email":"example@email.com","cookies":{}}]

# VAPID
VAPID_PUBLIC_KEY=your_vapid_public_key_here
VAPID_PRIVATE_KEY=your_vapid_private_key_here

# HMAC
HMAC_SECRET_V1=your_32_byte_hex_secret_here

# GCP
GCP_PROJECT_ID=mise-en-place-prod

# Runtime
ENV=dev
```
  </action>
  <verify>
    <automated>uv run python -c "import tomllib; data=tomllib.loads(open('pyproject.toml').read()); assert 'aiokafka==0.13.0' in str(data['project']['dependencies']); assert 'asyncio_mode' in str(data['tool']['pytest']['ini_options']); print('pyproject.toml OK')" && grep -q "^\.env$" .gitignore && grep -q "KAFKA_BOOTSTRAP_SERVERS" .env.example</automated>
  </verify>
  <done>pyproject.toml has all pinned deps + pytest config; uv.lock generated; .gitignore has .env entry; .env.example has all 13 Named Symbol env vars</done>
</task>

<task id="01-01-T2" type="auto">
  <name>Task 2: Makefile, ruff config, mypy config, CONTRIBUTING.md lint bans</name>
  <files>
    Makefile,
    .ruff.toml,
    CONTRIBUTING.md
  </files>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-10, D-35),
    .planning/research/PITFALLS.md (§ Pitfall 16),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-VALIDATION.md (§ Wave 0 Requirements — Makefile targets)
  </read_first>
  <action>
Create `Makefile` at repo root with these exact targets (all must appear in `make help`):

```makefile
.DEFAULT_GOAL := help

.PHONY: up down migrate seed poll test test-integration lint fmt smoke verify-seed verify-perf02 help topics

up: ## Start all infrastructure containers (Kafka, Redis, Postgres+TimescaleDB, Kafka UI)
	docker compose -f ops/docker-compose.yml up -d

down: ## Stop and remove infrastructure containers
	docker compose -f ops/docker-compose.yml down

topics: ## Create Kafka topics idempotently
	uv run python scripts/create_topics.py

migrate: ## Run Alembic migrations
	uv run alembic upgrade head

seed: ## Seed 50 NYC restaurants from scripts/seed/restaurants.yml
	uv run python scripts/seed_restaurants.py

poll: ## Run OpenTable poller on host
	uv run python -m services.poller

test: ## Run unit tests
	uv run pytest tests/unit -x -q

test-integration: ## Run integration tests (requires running infra)
	uv run pytest tests/unit tests/integration -v

lint: ## Run ruff check + mypy
	uv run ruff check .
	uv run mypy shared/ services/

fmt: ## Format code with ruff
	uv run ruff format .

smoke: ## Quick smoke test: docker compose up, wait 30s, consume one availability.raw message
	docker compose -f ops/docker-compose.yml up -d
	sleep 30
	docker compose -f ops/docker-compose.yml exec kafka kafka-console-consumer.sh --bootstrap-server localhost:9092 --topic availability.raw --max-messages 1 --timeout-ms 30000

verify-seed: ## Assert >=50 restaurants in DB with all required fields; >=50 entries in sched:polls ZSET
	uv run python scripts/verify_seed.py

verify-perf02: ## Assert all 24-hour buckets in poll_log have >=99% success rate
	uv run python scripts/check_poll_success.py

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'
```

Create `.ruff.toml` at repo root:
```toml
[lint]
select = ["E", "F", "W", "I", "UP", "ASYNC"]
ignore = []

[lint.per-file-ignores]
"tests/**" = ["S101"]

# Pitfall 16: Ban blocking patterns in async service code.
# These are enforced here and documented in CONTRIBUTING.md.
# ruff does not have a custom "banned import" rule natively — use the ASYNC rules
# plus document the CI grep in CONTRIBUTING.md.
```

Create `CONTRIBUTING.md` documenting the async hygiene rules (Pitfall 16):
```markdown
# Contributing

## Async Hygiene Rules (Pitfall 16)

The following patterns are BANNED in `services/` and `shared/` and will cause CI to fail:

- `import requests` — use `httpx.AsyncClient` (D-05)
- `time.sleep(` — use `asyncio.sleep(` 
- `import redis\n` or `from redis import` without `.asyncio` submodule — use `import redis.asyncio as redis` (D-03)

CI enforcement:
```
grep -rn "import requests" services/ shared/ && echo "BANNED: use httpx.AsyncClient" && exit 1 || true
grep -rn "time\.sleep(" services/ shared/ && echo "BANNED: use asyncio.sleep" && exit 1 || true
```

## Alembic

NEVER run `alembic revision --autogenerate` after a hypertable exists. Always hand-write hypertable migrations using `op.execute("SELECT create_hypertable(...)")`. See migrations/README.md.

## Redis Atomicity (Pitfall 7)

NEVER use `SETNX` + `EXPIRE` as two separate commands. Always use the single atomic `SET key value NX EX ttl` form. The codebase has zero occurrences of `SETNX` — keep it that way.
```
  </action>
  <verify>
    <automated>make help 2>&1 | grep -E "verify-perf02|test-integration|smoke|verify-seed" | wc -l | grep -q "^4" && grep -q "ASYNC" .ruff.toml && grep -q "SETNX" CONTRIBUTING.md</automated>
  </verify>
  <done>make help shows all 14 required targets; .ruff.toml has ASYNC lint group; CONTRIBUTING.md documents the three banned patterns with grep enforcement</done>
</task>

<task id="01-01-T3" type="auto">
  <name>Task 3: shared/ skeleton modules (events.py, redis_keys.py, telemetry.py, __init__.py)</name>
  <files>
    shared/__init__.py,
    shared/events.py,
    shared/redis_keys.py,
    shared/telemetry.py
  </files>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-06, D-12, D-18),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§ Named Symbols — Redis keys, Pydantic classes; §3 Redis ZSET Lua scripts; §7 structlog JSON config)
  </read_first>
  <action>
Create `shared/__init__.py` as an empty file.

Create `shared/events.py` as a scaffold with correct imports — bodies are stubs for now (Plan 04 fills them in):
```python
"""
Pydantic v2 Kafka message schemas.
Single source of truth for all Kafka message contracts (D-06).
Named symbols: AvailabilityRawEvent, PollsCompletedEvent
"""
from __future__ import annotations
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AvailabilityRawEvent(BaseModel):
    """Emitted to availability.raw for each completed OpenTable or Resy poll."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_id: UUID
    source: Literal["opentable", "resy"]
    restaurant_id: int
    polled_at_epoch_ms: int
    raw_response: dict[str, Any]

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")


class PollsCompletedEvent(BaseModel):
    """Emitted to polls.completed after each poll attempt."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_id: UUID
    source: Literal["opentable", "resy"]
    restaurant_id: int
    completed_at_epoch_ms: int
    status: Literal["success", "error", "timeout"]
    latency_ms: int
    http_status: int | None = None
    error: str | None = None

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")
```

Create `shared/redis_keys.py` with constants and stubs:
```python
"""
Single source of truth for ALL Redis key patterns and TTLs (D-18).
Any Redis access in services/ MUST import from here.
Named symbols: SCHED_POLLS, SCHED_POLLS_INFLIGHT
"""
from __future__ import annotations

# -- Scheduler ZSETs --
SCHED_POLLS = "sched:polls"              # score = next_poll_epoch_ms
SCHED_POLLS_INFLIGHT = "sched:polls:inflight"  # score = now_ms + visibility_ms

# -- Timing constants --
POLL_VISIBILITY_TIMEOUT_MS: int = 60_000   # 60s (D-18)
POLL_INTERVAL_SECONDS: int = 90            # D-17
POLL_JITTER_FRACTION: float = 0.15        # D-17 (±15%)
REAPER_INTERVAL_SECONDS: int = 10         # Claude discretion (D-18 range: 5-15s)


def job(source: str, restaurant_id: int) -> str:
    """Return canonical job descriptor '{source}:{restaurant_id}' (D-18, D-29)."""
    return f"{source}:{restaurant_id}"


async def set_nx_ex(r: object, key: str, value: str, ttl_seconds: int) -> bool:
    """
    Atomic SETNX+EX in a single Redis call (Pitfall 7).
    NEVER use two-command SETNX + EXPIRE.
    Returns True if key was set (did not exist), False if it already existed.
    """
    # r is redis.asyncio.Redis — typed as object to avoid import at this layer
    result = await r.set(key, value, nx=True, ex=ttl_seconds)  # type: ignore[union-attr]
    return result is True


# -- Lua scripts (D-18) --
CLAIM_POLL_LUA = """
-- KEYS[1] = sched:polls
-- KEYS[2] = sched:polls:inflight
-- ARGV[1] = now_ms
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
  redis.call('ZADD', KEYS[2], ARGV[1], job)
end
return expired
"""
```

Create `shared/telemetry.py` as a stub with correct signature (Plan 04 fills body):
```python
"""
Structured logging via structlog (D-12, D-13).
Named symbol: configure_logging, get_logger
"""
from __future__ import annotations
import logging
import os
import sys
from typing import Any

import structlog

_CONFIGURED = False


def _redact_secrets(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Strips values matching sensitive env-var names from log event dicts (T-02).
    Applied on every log call.
    """
    _REDACTED = "[REDACTED]"
    _SECRET_KEYS = {
        "TWILIO_AUTH_TOKEN",
        "HMAC_SECRET_V1",
        "VAPID_PRIVATE_KEY",
        "RESY_ACCOUNTS_JSON",
    }
    for k in _SECRET_KEYS:
        if k in event_dict:
            event_dict[k] = _REDACTED
    return event_dict


def configure_logging(env: str | None = None) -> None:
    """Call once at service startup. Idempotent."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    env = env or os.getenv("ENV", "dev")
    log_level_name = os.getenv("LOG_LEVEL", "INFO" if env == "prod" else "DEBUG").upper()
    log_level = getattr(logging, log_level_name, logging.DEBUG)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=log_level)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _redact_secrets,
    ]

    if env == "prod":
        renderer: list[Any] = [structlog.processors.JSONRenderer()]
    else:
        renderer = [structlog.dev.ConsoleRenderer(colors=True)]

    structlog.configure(
        processors=shared_processors + renderer,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str) -> structlog.BoundLogger:
    """Return a structlog BoundLogger for the given name."""
    configure_logging()
    return structlog.get_logger(name)
```
  </action>
  <verify>
    <automated>uv run python -c "from shared.events import AvailabilityRawEvent, PollsCompletedEvent; from shared.redis_keys import SCHED_POLLS, SCHED_POLLS_INFLIGHT, job, set_nx_ex; from shared.telemetry import get_logger, configure_logging; print('shared imports OK')"</automated>
  </verify>
  <done>All four shared/ files importable; AvailabilityRawEvent and PollsCompletedEvent have model_config=ConfigDict(frozen=True, extra='forbid') and to_bytes(); SCHED_POLLS='sched:polls', SCHED_POLLS_INFLIGHT='sched:polls:inflight'; set_nx_ex uses r.set(key, value, nx=True, ex=ttl_seconds) single call; telemetry._redact_secrets strips TWILIO_AUTH_TOKEN, HMAC_SECRET_V1, VAPID_PRIVATE_KEY, RESY_ACCOUNTS_JSON</done>
</task>

<task id="01-01-T4" type="auto">
  <name>Task 4: Wave-0 test stubs, conftest.py, docs stubs</name>
  <files>
    tests/conftest.py,
    tests/unit/__init__.py,
    tests/unit/test_redis_keys.py,
    tests/unit/test_events_schema.py,
    tests/unit/test_telemetry_redaction.py,
    tests/integration/__init__.py,
    tests/integration/test_poller_smoke.py,
    tests/integration/test_seed_idempotency.py,
    tests/integration/test_hypertable_config.py,
    tests/integration/test_poll_log_writes.py,
    tests/integration/test_topics_created.py,
    tests/integration/test_redis_config.py,
    tests/integration/test_scheduler_claim_release.py,
    scripts/check_poll_success.py,
    docs/runbooks/perf02-24h-log.md,
    docs/admin-evidence/.gitkeep
  </files>
  <read_first>
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-VALIDATION.md (§ Wave 0 Requirements, § Per-Criterion Verification Map),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§6 testcontainers fixtures)
  </read_first>
  <action>
Create `tests/conftest.py` with shared testcontainers fixtures at module scope:
```python
"""Shared pytest fixtures for Mise en Place test suite."""
import pytest
from testcontainers.kafka import KafkaContainer
from testcontainers.redis import RedisContainer
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="module")
def kafka_container():
    with KafkaContainer(image="apache/kafka:3.8.1") as kc:
        yield kc


@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer(image="redis:7.2-alpine") as rc:
        client = rc.get_client()
        client.config_set("maxmemory-policy", "noeviction")
        yield rc


@pytest.fixture(scope="module")
def timescale_container():
    container = PostgresContainer(
        image="timescale/timescaledb:2.17.2-pg16",
        username="mise",
        password="mise",
        dbname="mise",
    )
    with container as tc:
        yield tc
```

Create `tests/unit/__init__.py` and `tests/integration/__init__.py` as empty files.

Create `tests/unit/test_redis_keys.py`:
```python
"""Unit tests for shared.redis_keys constants and helpers."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from shared.redis_keys import (
    SCHED_POLLS,
    SCHED_POLLS_INFLIGHT,
    POLL_VISIBILITY_TIMEOUT_MS,
    POLL_INTERVAL_SECONDS,
    POLL_JITTER_FRACTION,
    job,
    set_nx_ex,
)


def test_sched_polls_constant():
    assert SCHED_POLLS == "sched:polls"


def test_sched_polls_inflight_constant():
    assert SCHED_POLLS_INFLIGHT == "sched:polls:inflight"


def test_job_descriptor_format():
    assert job("opentable", 42) == "opentable:42"
    assert job("resy", 123) == "resy:123"


@pytest.mark.asyncio
async def test_set_nx_ex_uses_single_atomic_call():
    """set_nx_ex MUST call r.set with nx=True and ex= in a single call (Pitfall 7)."""
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    result = await set_nx_ex(mock_redis, "testkey", "testval", 60)
    mock_redis.set.assert_called_once_with("testkey", "testval", nx=True, ex=60)
    assert result is True


@pytest.mark.asyncio
async def test_set_nx_ex_returns_false_when_key_exists():
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None  # Redis returns None when NX fails
    result = await set_nx_ex(mock_redis, "existing", "val", 60)
    assert result is False
```

Create `tests/unit/test_events_schema.py`:
```python
"""Unit tests for shared.events Pydantic models."""
import pytest
from uuid import uuid4
from shared.events import AvailabilityRawEvent, PollsCompletedEvent


def test_availability_raw_event_to_bytes():
    evt = AvailabilityRawEvent(
        poll_id=uuid4(),
        source="opentable",
        restaurant_id=42,
        polled_at_epoch_ms=1_000_000,
        raw_response={"slots": []},
    )
    b = evt.to_bytes()
    assert isinstance(b, bytes)
    assert b'"source":"opentable"' in b.decode() or '"source": "opentable"' in b.decode()


def test_availability_raw_event_frozen():
    evt = AvailabilityRawEvent(
        poll_id=uuid4(),
        source="opentable",
        restaurant_id=42,
        polled_at_epoch_ms=1_000_000,
        raw_response={},
    )
    with pytest.raises(Exception):
        evt.restaurant_id = 99  # type: ignore[misc]


def test_polls_completed_event_extra_fields_forbidden():
    with pytest.raises(Exception):
        PollsCompletedEvent(
            poll_id=uuid4(),
            source="opentable",
            restaurant_id=42,
            completed_at_epoch_ms=1_000_000,
            status="success",
            latency_ms=100,
            unknown_field="oops",
        )


def test_polls_completed_event_optional_fields():
    evt = PollsCompletedEvent(
        poll_id=uuid4(),
        source="resy",
        restaurant_id=7,
        completed_at_epoch_ms=1_000_000,
        status="error",
        latency_ms=500,
        http_status=503,
        error="Service Unavailable",
    )
    assert evt.status == "error"
    assert evt.http_status == 503
```

Create `tests/unit/test_telemetry_redaction.py`:
```python
"""Unit tests for shared.telemetry secret-redaction processor."""
import pytest
from shared.telemetry import _redact_secrets


def test_redacts_twilio_auth_token():
    event = {"event": "test", "TWILIO_AUTH_TOKEN": "secret123"}
    result = _redact_secrets(None, "info", event)
    assert result["TWILIO_AUTH_TOKEN"] == "[REDACTED]"


def test_redacts_hmac_secret():
    event = {"event": "test", "HMAC_SECRET_V1": "deadbeef" * 4}
    result = _redact_secrets(None, "info", event)
    assert result["HMAC_SECRET_V1"] == "[REDACTED]"


def test_redacts_vapid_private_key():
    event = {"event": "test", "VAPID_PRIVATE_KEY": "very_private"}
    result = _redact_secrets(None, "info", event)
    assert result["VAPID_PRIVATE_KEY"] == "[REDACTED]"


def test_redacts_resy_accounts_json():
    event = {"RESY_ACCOUNTS_JSON": '[{"email":"x","cookies":{}}]', "event": "poll"}
    result = _redact_secrets(None, "info", event)
    assert result["RESY_ACCOUNTS_JSON"] == "[REDACTED]"


def test_leaves_non_secret_fields_alone():
    event = {"event": "poll_completed", "restaurant_id": 42, "status": "success"}
    result = _redact_secrets(None, "info", event)
    assert result["restaurant_id"] == 42
    assert result["status"] == "success"
```

Create Wave-0 integration test stubs. Each file must import, define a stub test function marked `pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 0X")`, so `pytest tests/unit -x -q` runs without needing infra.

Create `tests/integration/test_poller_smoke.py`:
```python
"""Integration smoke: SC1 — end-to-end emit within 60s. Stub filled by Plan 05."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 05 (poller service)")
async def test_end_to_end_emit_within_60s(kafka_container, redis_container, timescale_container):
    """
    Boot poller against testcontainers. After seed + one scheduler cycle,
    assert one message appears on availability.raw within 60s with correct
    Kafka key '{source}:{restaurant_id}' and valid AvailabilityRawEvent JSON.
    Also assert one row in poll_log with status='success' and latency_ms > 0.
    """
    raise NotImplementedError
```

Create `tests/integration/test_seed_idempotency.py`:
```python
"""Integration: SC3 — seed populates all fields and sched:polls ZSET. Stub filled by Plan 05."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 05 (seed script)")
async def test_seed_populates_all_fields_and_zset(redis_container, timescale_container):
    """
    Run seed_restaurants.py against testcontainers Postgres + Redis.
    Assert: COUNT(*) FROM restaurants WHERE opentable_rid IS NOT NULL
              AND neighborhood IS NOT NULL AND cuisine IS NOT NULL
              AND price_tier IS NOT NULL AND cover_photo_url IS NOT NULL >= 50.
    Assert: ZCARD sched:polls >= 50.
    Run twice; assert idempotency (count stays the same on second run).
    """
    raise NotImplementedError
```

Create `tests/integration/test_hypertable_config.py`:
```python
"""Integration: SC4 — hypertables have chunk_time_interval = 1 day. Stub filled by Plan 04."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 04 (migrations)")
async def test_chunk_interval_is_one_day(timescale_container):
    """
    Apply Alembic migrations to testcontainers TimescaleDB.
    Query: SELECT chunk_time_interval FROM timescaledb_information.dimensions
           WHERE hypertable_name IN ('availability_events', 'poll_log');
    Assert both rows return 86400000000 microseconds (1 day).
    """
    raise NotImplementedError
```

Create `tests/integration/test_poll_log_writes.py`:
```python
"""Integration: SC4 — poll_log rows written with latency. Stub filled by Plan 05."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 05 (publisher)")
async def test_poll_writes_row_with_latency(kafka_container, redis_container, timescale_container):
    """
    Run one poll cycle against mocked OpenTable (respx).
    Assert: SELECT COUNT(*) FROM poll_log WHERE latency_ms IS NOT NULL
            AND status IN ('success','error','timeout') > 0 after cycle.
    Assert: poll_log.status values only ever 'success', 'error', or 'timeout'.
    """
    raise NotImplementedError
```

Create `tests/integration/test_topics_created.py`:
```python
"""Integration: FOUND-04 — all 5 Kafka topics exist with correct retention. Stub filled by Plan 02."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 02 (topics script)")
async def test_all_five_topics_have_retention(kafka_container):
    """
    Run scripts/create_topics.py against testcontainers Kafka.
    Assert all 5 topics exist: availability.raw, availability.events,
    notifications.queued, notifications.sent, polls.completed.
    Assert retention.ms matches: 86400000, 604800000, 2592000000, 2592000000, 604800000.
    Run twice; assert idempotency.
    """
    raise NotImplementedError
```

Create `tests/integration/test_redis_config.py`:
```python
"""Integration: Pitfall 18 — Redis maxmemory-policy = noeviction. Stub filled by Plan 02."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 02 (docker-compose)")
async def test_eviction_policy_is_noeviction(redis_container):
    """
    Connect to testcontainers Redis.
    Run: CONFIG GET maxmemory-policy.
    Assert the returned value is 'noeviction'.
    """
    raise NotImplementedError
```

Create `tests/integration/test_scheduler_claim_release.py`:
```python
"""Integration: POLL-01 — Lua ZSET scheduler claim/release/reap. Stub filled by Plan 04."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 04 (shared kernel Lua scripts)")
async def test_claim_release_cycle(redis_container):
    """
    Load Lua scripts via script_load.
    ZADD sched:polls with score = now_ms - 1 (due immediately).
    Call CLAIM_POLL_LUA: assert returns 'opentable:42', job moved to inflight.
    Call RELEASE_POLL_LUA with next_score = now_ms + 90000.
    Assert sched:polls has the job back with the new score.
    Assert sched:polls:inflight is empty.
    """
    raise NotImplementedError


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 04 (shared kernel Lua scripts)")
async def test_reaper_requeues_expired_inflight(redis_container):
    """
    ZADD sched:polls:inflight with score = now_ms - 1 (expired).
    Call REAP_INFLIGHT_LUA with now_ms.
    Assert the job is back in sched:polls.
    Assert sched:polls:inflight is empty.
    """
    raise NotImplementedError
```

Create `scripts/check_poll_success.py` as a stub:
```python
#!/usr/bin/env python
"""
SC5 / PERF-02: Assert >=99% poll success rate in every hourly bucket over last 24h.
Filled in by Plan 06.
"""
import sys


def main() -> None:
    print("check_poll_success.py: stub — implemented in Plan 06")
    # Plan 06 replaces this with:
    # SELECT time_bucket('1 hour', time) AS hour,
    #        COUNT(*) AS total,
    #        SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS success
    # FROM poll_log
    # WHERE time >= NOW() - INTERVAL '24 hours'
    # GROUP BY hour ORDER BY hour
    # Assert every row: success::float / total >= 0.99
    sys.exit(0)


if __name__ == "__main__":
    main()
```

Create `docs/runbooks/perf02-24h-log.md`:
```markdown
# PERF-02 24-Hour Observation Log

**Purpose:** Record FD counts and success rates during the 24h PERF-02 verification run (SC5).

## Run Parameters

- Start time (t0): _fill in_
- Poller PID at t0: _fill in_
- FD count at t0: _fill in_

## FD Count Snapshots

| Time | Snapshot Label | FD Count | Notes |
|------|---------------|----------|-------|
| t=0  | baseline | | `ls /proc/$(pgrep -f services.poller)/fd \| wc -l` |
| t=1h | t_plus_1h | | |
| t=6h | t_plus_6h | | |
| t=12h | t_plus_12h | | |
| t=24h | t_plus_24h | | |

## Verification Result

- `make verify-perf02` exit code: _fill in_
- All 24 hourly buckets >=99% success: yes / no
- FD count stable (delta ≤ 5% from baseline): yes / no

## Sign-Off

- [ ] All hourly buckets >= 0.99 success rate
- [ ] FD count stable over 24h
- [ ] `make verify-perf02` exits 0
```

Create `docs/admin-evidence/.gitkeep` as an empty file.
  </action>
  <verify>
    <automated>uv run pytest tests/unit -x -q 2>&1 | tail -5 && uv run python -c "import tests.integration.test_poller_smoke; import tests.integration.test_hypertable_config; print('integration stubs importable')"</automated>
  </verify>
  <done>
    All Wave-0 stubs from 01-VALIDATION.md exist as Python files; `uv run pytest tests/unit -x -q` passes (tests that are not stubs pass, stubs are skipped); scripts/check_poll_success.py is importable and exits 0; docs/runbooks/perf02-24h-log.md has the FD snapshot table template; docs/admin-evidence/.gitkeep exists
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| repo → .env | Secret values must not cross from .env into git history |
| logs → stdout | Log output must not emit raw secret values even in dev mode |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01 | Information Disclosure | .env / secrets | mitigate | `.env` listed in `.gitignore` day 1 (per D-09); `.env.example` ships placeholders only — no real values; CI step runs `grep -rn "TWILIO_AUTH_TOKEN\|HMAC_SECRET_V1\|VAPID_PRIVATE_KEY" .env.example` and fails if non-placeholder values appear |
| T-02 | Information Disclosure | structlog / log output | mitigate | `_redact_secrets` processor wired in `shared/telemetry.py` processor chain (this plan); strips `TWILIO_AUTH_TOKEN`, `HMAC_SECRET_V1`, `VAPID_PRIVATE_KEY`, `RESY_ACCOUNTS_JSON` from every log event dict; unit test in `tests/unit/test_telemetry_redaction.py` verifies all four keys are redacted |
</threat_model>

<verification>
After all four tasks complete:

```bash
# 1. All shared modules import cleanly
uv run python -c "from shared.events import AvailabilityRawEvent, PollsCompletedEvent; from shared.redis_keys import SCHED_POLLS, SCHED_POLLS_INFLIGHT, set_nx_ex; from shared.telemetry import get_logger; print('OK')"

# 2. Unit tests pass
uv run pytest tests/unit -v

# 3. .env not tracked
git status .env 2>&1 | grep -q "nothing to commit\|untracked\|not staged" || git check-ignore -q .env

# 4. All Makefile targets present
make help | grep -E "verify-perf02|smoke|verify-seed|test-integration|topics|migrate|seed|poll"

# 5. No banned patterns in shared/
grep -rn "import requests" shared/ services/ 2>/dev/null | grep -v "^Binary" | wc -l | grep -q "^0"
grep -rn "time\.sleep(" shared/ services/ 2>/dev/null | wc -l | grep -q "^0"
```
</verification>

<success_criteria>
- `uv run python -c "from shared.events import AvailabilityRawEvent"` exits 0
- `uv run pytest tests/unit -x -q` produces 0 failures (skips are OK)
- `make help` lists all 14 targets including `verify-perf02`, `smoke`, `verify-seed`, `topics`
- `.env` is in `.gitignore`; `.env.example` has all 13 Named Symbol env vars as placeholders
- `shared/redis_keys.py::set_nx_ex` calls `r.set(key, value, nx=True, ex=ttl_seconds)` — confirmed by `test_set_nx_ex_uses_single_atomic_call`
- `shared/telemetry.py::_redact_secrets` strips all four secret env-var names — confirmed by unit tests
- All 10 Wave-0 test stubs from 01-VALIDATION.md exist as importable Python files
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-01-SUMMARY.md`
</output>
