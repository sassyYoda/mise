# Phase 5: API, Watchlist CRUD & SSE - Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 43 new/modified files
**Analogs found:** 31 / 43 (12 have no on-disk analog — 9 of those are blocked on Phase 4 artifacts that do not exist yet)

> **Working-tree reality check (verified this session, HEAD `ac8676d`).** Phase 4 has not
> executed: `services/api/` does not exist, `shared/tokens.py` / `shared/crypto.py` /
> `services/notifier/` do not exist, and `migrations/versions/` ends at `0008`. Phase 3 is
> partially landed: `shared/redis_keys.py` **does** now carry `WATCH_COUNT_HASH`,
> `TIER_OVERRIDE_HASH`, `watch_count_field()`, `tier_override_field()` and the tier arithmetic
> (commit `ac8676d`, plan 03-02) — this contradicts 05-RESEARCH.md § Sequencing Dependencies,
> which was written before that commit. `shared/metrics.py` is still absent even though
> `tests/unit/test_metrics_registry.py` exists (03-02 is mid-flight in another worktree).
> Migration `0009` (Phase 3 `UNIQUE(slug, source)`) and `0010` (Phase 4) are both still absent,
> so D-93b's "migration 0012" is currently numbered against a chain that does not reach 0011 —
> the planner must resolve the next free number at execution time, as D-93b already allows.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/api/app.py` (modify) | app factory / lifespan | request-response | `services/state_machine/main.py` | role-match (lifespan/AsyncExitStack only) |
| `services/api/config.py` | config | — | `services/state_machine/config.py` | exact |
| `services/api/deps.py` | provider / DI | request-response | `services/state_machine/main.py:106-133` (resource construction) | partial |
| `services/api/middleware.py` | middleware | request-response + streaming | **none** (`shared/telemetry.py` for the log fields only) | no analog |
| `services/api/ratelimit.py` | middleware / dependency | request-response | `shared/redis_keys.py:447-483` (`RESY_BUDGET_LUA`) | role-match |
| `services/api/sse.py` | service (fan-out) | streaming / pub-sub | `services/state_machine/consumer.py` (consume loop shape only) | partial |
| `services/api/schemas/*.py` | model (DTO) | transform | `shared/events.py` (pydantic v2 wire models) | role-match |
| `services/api/routers/watches.py` | controller | CRUD | **none on disk** — Phase 4 D-84 / plan 04-04 creates `routers/links.py` | no analog |
| `services/api/routers/manage.py` | controller | request-response | same (04-04 `routers/links.py`) | no analog |
| `services/api/routers/restaurants.py` | controller | CRUD (read) | `scripts/verify_seed.py` + `shared/db.py` query shapes | partial |
| `services/api/routers/feed.py` | controller | streaming | **none** | no analog |
| `services/api/routers/admin.py` | controller | CRUD | `scripts/seed_restaurants.py` (write + `sched:polls` seed) | partial |
| `services/api/routers/push.py` | controller | CRUD | **none** (`push_subscriptions` table is Phase 4 migration 0010) | no analog |
| `services/api/routers/metrics.py` | controller | request-response | **none** (`shared/metrics.py` pending, plan 03-02) | no analog |
| `services/api/routers/health.py` | controller | request-response | `services/state_machine/main.py:63-79` (`_assert_topics_exist` readiness idiom) | partial |
| `services/api/watch_service.py` | service | CRUD | `services/state_machine/persistence.py` | exact |
| `shared/servicetime.py` | utility | transform | `services/state_machine/persistence.py:31-56` (`_SERVICE_TZ`, `hours_before_service`) | exact (a move, not a rewrite) |
| `shared/watch_counts.py` | service | CRUD → Redis | `shared/redis_keys.py:317-334` + `shared/scheduler/lua.py` | role-match |
| `shared/redis_keys.py` (modify) | config / key registry | — | itself (`rate_minute_key`, `RESY_BUDGET_LUA`) | exact |
| `shared/kafka.py` (modify) | factory | pub-sub | `shared/kafka.py:47-81` (`make_consumer`) | exact |
| `migrations/versions/00XX_watch_dedupe.py` | migration | batch | `migrations/versions/0008_add_event_id_to_availability_events.py` | exact |
| `scripts/rotate_hmac_secret.py` | script | batch | `scripts/verify_seed.py` / `scripts/seed_restaurants.py` | role-match |
| `tests/integration/conftest.py` (modify) | test fixture | — | `tests/integration/conftest.py` + 03-04 plan `stub_base` fixture | exact |
| `tests/unit/test_api_async_only.py` | test (grep gate) | — | `tests/unit/test_no_inline_sleep.py` | exact |
| `tests/unit/test_no_setnx_expire_pairs.py` (modify) | test (grep gate) | — | itself | exact |
| `tests/unit/test_api_logs_never_carry_payload.py` | test | — | `tests/unit/test_logs_never_carry_payload.py` | exact |
| `tests/unit/test_metrics_*` / `test_openapi_snapshot.py` | test | — | `tests/unit/test_metrics_registry.py` | role-match |
| `tests/integration/test_sse_live.py` | test | streaming | **none** (BC-1 harness is new) | no analog |
| `Makefile` (modify) | config | — | `Makefile:1-60` | exact |
| `.env.example` (modify) | config | — | `.env.example` | exact |
| `docs/api.md` | docs | — | **none** (`docs/` has no route reference yet) | no analog |

---

## Pattern Assignments

### `services/api/config.py` (config)

**Analog:** `services/state_machine/config.py` — copy this file's *shape* wholesale.

**Lazy-env pattern** (`services/state_machine/config.py:44-60`):

```python
def kafka_bootstrap_servers() -> str:
    """Broker list. Default matches services/poller/config.py — the two must never disagree."""
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")


def redis_url() -> str:
    """Redis URL. Default matches services/poller/config.py."""
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def database_url_async() -> str:
    """asyncpg driver URL. Default matches services/poller/config.py (Named Symbol)."""
    return os.getenv(
        "DATABASE_URL_ASYNC",
        "postgresql+asyncpg://mise:mise@localhost:5432/mise",
    )
```

The module docstring states the reason, and the planner should restate it in
`services/api/config.py` (`services/state_machine/config.py:1-15`): *"Every environment read
below is a FUNCTION, not a module constant… `services/poller/config.py` freezes … at IMPORT
time, so any integration test that imports the service during collection pins the whole run to
the localhost defaults instead of its testcontainers (02-02 deviation 1)."*

**Fail-closed validated env** (`services/state_machine/config.py:96-129`, `max_message_attempts`)
is the pattern for `TRUST_PROXY_HEADERS` / `PROXY_HOPS` / `ADMIN_BASIC_*` / `HMAC_GRACE_UNTIL`:
parse, refuse a typo with a `RuntimeError` naming the variable and the remedy, never
silently coerce. Also copy the `__all__` + Named-symbols docstring block
(`services/state_machine/config.py:16-40`).

---

### `services/api/app.py` (app factory, lifespan) — MODIFY Phase 4's file

**Analog:** `services/state_machine/main.py` (the `AsyncExitStack` lifespan), plus
`services/api/app.py :: create_app()` itself once Phase 4 plan **04-04** has created it
(defining decision **D-84**; the file does not exist on disk today).

**Resource acquisition + LIFO teardown** (`services/state_machine/main.py:106-133`):

```python
        async with AsyncExitStack() as stack:
            # persistence.py creates the SQLAlchemy engine lazily on its first write, so
            # nothing else ever disposes it. Registered before anything is acquired, which
            # under LIFO unwinding makes it the LAST thing torn down …
            stack.push_async_callback(dispose_engine)

            r = redis.from_url(url)
            stack.push_async_callback(r.aclose)

            scheduler = LuaScheduler(r)
            await scheduler.start()

            # Precondition: all 5 Named-Symbol topics must exist (D-27).
            await _assert_topics_exist(bootstrap_servers)

            producer = await make_producer(bootstrap_servers)
            stack.push_async_callback(producer.stop)
```

Map to D-97/RESEARCH § "Lifespan with `AsyncExitStack`": `dispose_engine` pushed first, Redis
second, `close_async_client` (`shared/http_client.py`) third, then `_assert_topics_exist`, then
`hub.start()` + `stack.push_async_callback(hub.stop)`, then `yield {"hub": hub, "redis": r}`.

**Startup topic guard to reuse verbatim** (`services/state_machine/main.py:63-79`) — D-98a
requires it because a `group_id=None` consumer dies at `start()` on a missing topic:

```python
async def _assert_topics_exist(bootstrap_servers: str) -> None:
    """Startup guard: refuse to run if any required topic is missing (D-27)."""
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    try:
        await admin.start()
        existing = set(await admin.list_topics())
    finally:
        await admin.close()
    missing = REQUIRED_TOPICS - existing
    if missing:
        raise RuntimeError(
            f"Kafka topics missing: {sorted(missing)}. Run `make topics` first."
        )
```

Note the `start()`-inside-`try` comment (IN-02) — keep it. The same `AIOKafkaAdminClient`
acquire/close shape is the analog for `/admin/health`'s lag summary (D-103).

**Deliberate divergence:** the API must **not** call `run_until_signal`
(`services/state_machine/main.py:162`). uvicorn installs its own SIGTERM handling and drives
lifespan shutdown; `shared/shutdown.py` stays with the worker services (05-RESEARCH.md
§ Code Examples). The planner should state this in the module docstring so the omission reads
as a decision rather than an oversight.

**Startup log line** (`services/state_machine/main.py:145-152`): one `*_ready` event carrying
the resolved URLs and config values — mirror it as `api_ready`.

---

### `services/api/ratelimit.py` (middleware/dependency, request-response)

**Analog:** `shared/redis_keys.py` — the Resy minute budget. The new Lua goes in
`shared/redis_keys.py` beside it (project rule: every Redis key and script lives there), and
`ratelimit.py` holds only the FastAPI dependency.

**Key helper to copy** (`shared/redis_keys.py:261-269`):

```python
def rate_minute_key(epoch_minute: int) -> str:
    """
    Return the minute-bucket counter key 'rate:resy:{epoch_minute}' (D-65, POLL-05).

    ``epoch_minute`` is ``now_ms // 60_000`` — integer division, never a float and never a
    formatted timestamp, so two callers a millisecond apart inside the same wall minute
    always land on the same key.
    """
    return f"rate:resy:{epoch_minute}"
```

Add `api_rate_key(bucket: str, ip: str, epoch_minute: int) -> str` returning
`rate:api:{bucket}:{ip}:{epoch_minute}` (D-96) with the same integer-division docstring.
TTL constant follows `RESY_RATE_TTL_SECONDS: int = 90  # > 60 s so a counter always outlives its own minute`
(`shared/redis_keys.py:257`) — D-96 asks for 120 s; keep the "why > 60" comment.

**Single-script INCR+EXPIRE** (`shared/redis_keys.py:447-483`) — the exact structure to adapt:

```python
RESY_BUDGET_LUA = """
-- KEYS[1] = rate:resy:{epoch_minute}
-- ARGV[1] = cost … ARGV[2] = cap … ARGV[3] = ttl seconds
-- Returns {granted(0|1), count_after, remaining}
--
-- INCRBY and EXPIRE must be in ONE script. A bare `INCR` followed by a separate `EXPIRE`
-- from Python is two round trips and two race windows: if the process died between them the
-- counter would have NO TTL at all (verified: `ttl == -1`), and under `noeviction` that key
-- is permanent …
-- The EXPIRE is set only when `new == cost`, i.e. on the FIRST increment of this minute;
-- re-setting it on every increment would slide the window past the minute it describes.
local cur  = tonumber(redis.call('GET', KEYS[1]) or '0')
local cost = tonumber(ARGV[1])
local cap  = tonumber(ARGV[2])
if cur + cost > cap then
  return {0, cur, cap - cur}
end
local new = redis.call('INCRBY', KEYS[1], cost)
if new == cost then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
end
return {1, new, cap - new}
"""
```

Difference to carry: the API script must also return the **TTL** so the `Retry-After` header is
the real remaining window (D-96 + Pitfall 10), i.e. `return {count, allowed, redis.call('TTL', KEYS[1])}`
as in 05-RESEARCH.md § Rate-limit dependency.

**mypy cast discipline** (`shared/redis_keys.py:487-535`): redis-py types commands as
`Union[Awaitable[T], T]`; every `cast` lives in `shared/redis_keys.py` exactly once so callers
carry none. `services/api/**` must contain no `cast(Awaitable[...], r.<cmd>)`.

**Grep gate:** `tests/unit/test_no_setnx_expire_pairs.py` already scans
`SCANNED_DIRS = ("services", "shared", "scripts")` (line 15), so `services/api` is covered the
moment it exists — the RESEARCH "extend its scanned set" item is already satisfied; instead add
the non-vacuity assertion that an `services/api` file is in the scanned set.

---

### `shared/watch_counts.py` (service, CRUD → Redis)

**Analog:** `shared/redis_keys.py:315-334` (already on disk, plan 03-02 / D-58) — this phase is
the **writer** of a contract whose reader already exists:

```python
# -- Watch counts and admin tier override (D-58) --
# Both HASHes are WRITTEN by Phase 5 and only READ here. They are therefore untrusted input
# from this module's point of view: a missing field, a non-integer value or a negative count
# must degrade to the slowest tier, never raise inside poll_loop (T-03-09).
WATCH_COUNT_HASH = "watch:count"      # field '{source}:{restaurant_id}' -> active watch count
TIER_OVERRIDE_HASH = "tier:override"  # field '{source}:{restaurant_id}' -> 1 | 2 | 3


def watch_count_field(source: str, restaurant_id: int) -> str:
    """Return the `watch:count` HASH field '{source}:{restaurant_id}' (D-58)."""
    return f"{source}:{restaurant_id}"
```

**Field-key trap for the planner:** the on-disk helper keys by `restaurant_id` (int), while
D-95/D-100 describe the field as `{source}:{platform_id}`. These are the same string only if
`platform_id == str(restaurant_id)`, which is false for Resy. `recount()` must call
`watch_count_field(...)` rather than f-string its own field, and the planner should raise the
discrepancy explicitly (it is a Phase 3 ↔ Phase 5 contract, not a Phase 5 choice).

**Best-effort write pattern** (D-95a) — copy the swallow-and-log shape from
`services/state_machine/persistence.py:106-113`:

```python
    except Exception as exc:  # noqa: BLE001 — best effort: never block the emit or the commit
        log.error(
            "availability_event_insert_failed",
            ...
            error=safe_error(exc),
        )
```

`recount()` gets the same `except Exception … # noqa: BLE001 — best effort: a stale count only
slows a poll` + `safe_error(exc)` treatment.

---

### `services/api/watch_service.py` (service, CRUD)

**Analog:** `services/state_machine/persistence.py` — same import block, same session idiom,
same upsert dialect import.

**Imports + session/upsert** (`services/state_machine/persistence.py:19-27`, `97-105`):

```python
from sqlalchemy import CursorResult, Integer, func, literal, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from shared.db import AvailabilityEvent as AvailabilityEventRow
from shared.db import get_async_session
from shared.telemetry import get_logger, safe_error

        statement = (
            pg_insert(AvailabilityEventRow)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["event_id", "time"])
        )
        session_factory = get_async_session()
        async with session_factory() as session:
            await session.execute(statement)
            await session.commit()
```

D-90's user upsert is the `on_conflict_do_update(index_elements=["email"]).returning(...)`
variant. **`index_elements` is always named** — 05-RESEARCH.md § Anti-Patterns reproduced the
silent row-loss when it is omitted, and the analog above already names both columns.

**Not best-effort here.** `insert_event`'s swallow (`persistence.py:106`) exists because a
Postgres stall must not block a Kafka emit; a failed `POST /watches` insert must *fail the
request*. Copy the imports and statement shape, not the `except Exception` arm. The one
best-effort arm in this phase is the management email (D-93) and `recount()` (D-95a).

**Timezone move** (D-93a) — `services/state_machine/persistence.py:31-33` is the code being
relocated to `shared/servicetime.py`, with a re-export left behind:

```python
# Service times are local to the restaurant; every mise restaurant is in NYC (PROJECT.md).
_SERVICE_TZ = ZoneInfo("America/New_York")
```

`shared/redis_keys.py:1-21` (`CONFIRM_DELAY_MS` re-export) and
`services/state_machine/config.py:19-24` show the sanctioned re-export idiom, including the
`# noqa: F401 (re-exported for consumers)` comment and the `__all__` entry mypy `--strict`
requires.

---

### `services/api/sse.py` (service, streaming/pub-sub)

**Analog:** partial only. The consume-loop and lifecycle come from
`services/state_machine/consumer.py`; the `FeedHub` itself has **no analog in this repository**
— use the executed sketch in 05-RESEARCH.md § Code Examples "FeedHub (the parts that matter)"
verbatim (it is mypy `--strict` and ruff clean).

**Consumer factory** (`shared/kafka.py:47-81`) — the feed consumer must go through a factory in
this file, not inline (module docstring: *"All producers and consumers are created via these
factories — no inline instantiation in services"*):

```python
async def make_consumer(
    *topics: str,
    group_id: str,
    bootstrap_servers: str | None = None,
) -> AIOKafkaConsumer:
    """
    MUST be called from inside a running event loop: ``AIOKafkaConsumer.__init__``
    calls ``get_running_loop()`` and raises ``RuntimeError`` otherwise. Being an
    ``async def`` factory, this function structurally cannot be called at import time.
    """
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=servers,
        group_id=group_id,
        enable_auto_commit=False,               # Pitfall 4 — manual commit only
        auto_offset_reset="earliest",           # D-47a
        max_poll_records=1,                     # Pitfall 10 — one message at a time
        isolation_level="read_uncommitted",
    )
    await consumer.start()
    return consumer
```

`group_id` is currently a **required `str`** and `auto_offset_reset` is hard-wired to
`"earliest"`, so D-98 needs a sibling factory (`make_groupless_consumer(...)`, `group_id=None`,
`auto_offset_reset="latest"`, `enable_auto_commit=False`) rather than a widened signature —
widening `group_id` to `str | None` would let a worker service silently lose its offsets. Keep
the "no inline instantiation" and "async factory ⇒ cannot be built at import" docstring claims.
`tests/unit/test_kafka_consumer_config.py` is the analog for the D-98 config assertion test.

**Never `str(exc)` in the pump's error arm** — `services/state_machine/consumer.py:47` imports
`safe_error`, and `_failure_shape` (line 83) is the stricter variant used for
producer-supplied data. The feed pump handles broker-supplied bytes: use `_failure_shape`'s
rationale (`consumer.py:684-697`) when logging a decode failure, `safe_error` for our own
infrastructure failures.

**Heartbeat gate:** `tests/unit/test_no_inline_sleep.py` is the exact template for the D-98
"no `while True: await asyncio.sleep(` in `services/api/sse.py`" gate, including its
non-vacuity companion (`test_no_inline_sleep.py:40-47`).

---

### `services/api/middleware.py` (middleware — `RequestLog` + `ErrorBoundary`)

**Analog:** none. Nothing in the repo is an ASGI middleware. Use the executed, typechecked
sketches in 05-RESEARCH.md § Code Examples ("Pure-ASGI request logging middleware",
"Token redaction") as the source.

**What *does* have an analog is the redaction contract** — `shared/telemetry.py:52-95`:

```python
def safe_error(exc: BaseException) -> str:
    """
    Render an exception as `module.ClassName: <scrubbed message>` for a log field (CR-03).

    `error=str(exc)` is never safe in this codebase …
    """
```

BC-3's `ErrorBoundary` calls `safe_error(exc)` and never re-raises. Also extend
`_redact_secrets._SECRET_KEYS` (`shared/telemetry.py:97-112`) — it already lists
`HMAC_MGMT_SECRET_V1`; D-92's rotation adds `HMAC_MGMT_SECRET_V{n}`, so the membership test must
become a prefix test, and `token` / `management_url` should be added as value-shaped keys.

**Log-field vocabulary to match** (`services/state_machine/main.py:145-152` style): one event
name in `snake_case`, ids and counts as kwargs, no free-text interpolation.

---

### `services/api/routers/admin.py` (controller, CRUD)

**Analog:** `scripts/seed_restaurants.py` — for the "create a restaurant ⇒ seed `sched:polls`"
half of D-103 (the auth half has no analog; use 05-RESEARCH.md § HTTP Basic).

**Imports and the ZSET seed** (`scripts/seed_restaurants.py:11-28`):

```python
import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from shared.redis_keys import SCHED_POLLS
from shared.redis_keys import job as make_job
```

`shared/redis_keys.py:43-46` defines the job descriptor the admin create path must reuse:

```python
def job(source: str, restaurant_id: int) -> str:
    """Return canonical job descriptor '{source}:{restaurant_id}' (D-18, D-29)."""
    return f"{source}:{restaurant_id}"
```

The router constructs no Redis client of its own — it takes the lifespan client from
`deps.get_redis`, unlike the script (which is a standalone process).

**Optional-arg typing note worth copying** (`scripts/seed_restaurants.py:39-52`): explicit
`if x is not None else` rather than `or`, because mypy `--strict` types `optional or fallback`
as optional. The same rule bites on `PROXY_HOPS` / `limit` / `offset` defaults.

---

### `migrations/versions/00XX_*.py` (migration, D-93b partial unique index)

**Analog:** `migrations/versions/0008_add_event_id_to_availability_events.py` — exact.

**Header + revision chain** (`0008…py:16-22`):

```python
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None
```

**Refuse-rather-than-destroy pre-flight guard** (`0008…py:25-47`) — the shape D-93b needs,
because a partial unique index cannot be created while duplicate active watches exist:

```python
    # NEVER use `alembic revision --autogenerate` on a hypertable (Pitfall 12, D-33) …
    existing = op.get_bind().execute(
        sa.text("SELECT count(*) FROM availability_events")
    ).scalar_one()
    if existing:
        raise RuntimeError(
            f"availability_events holds {existing} pre-0008 row(s). … Refusing to "
            "destroy them. Either archive and TRUNCATE … deliberately, "
            "or backfill event_id yourself, then re-run `alembic upgrade head`."
        )
```

Copy the docstring convention too (`0008…py:1-14`): title line with the revision number and the
owning decision id, then a numbered list of the defects the migration corrects. Phase 4 plan
**04-02** owns migration `0010` (`push_subscriptions`, `users.phone_hash`) and carries the same
guard idiom — this phase's migration is downstream of it.

---

### `tests/integration/conftest.py` (test fixtures) — MODIFY

**Analog:** itself, plus the `stub_base` fixture specified in Phase 3 plan
`03-04-browser-harness-fingerprints-stealth-PLAN.md:117-122` (**not yet on disk** — 03-04 has
not executed; cite the plan, and if it has landed by execution time, copy the shipped fixture
instead of re-deriving it):

> *"a `stub_base` fixture … that binds an ephemeral port, runs `uvicorn.Server.serve()` as a
> task, waits for `server.started` under `asyncio.wait_for`, yields the base URL, and shuts down
> with `server.should_exit = True` plus a bounded `wait_for` — never by cancelling the serve
> task. Do not add the `install_signal_handlers = lambda: None` workaround; it has no effect in
> the pinned uvicorn."*

That is exactly the BC-1 `live_api` harness; the two fixtures should share one helper.

**Env-freeze workaround the `api_app` fixture must call** (`tests/integration/conftest.py:19-25`):

```python
def reset_shared_db_singletons() -> None:
    """Drop the cached engine/session factory so new DATABASE_URL_* env vars take effect."""
    import shared.db as shared_db

    shared_db._engine = None
    shared_db._session_factory = None
```

**Container URL fixtures to reuse as-is** (`tests/integration/conftest.py:53-70`): `redis_url`
(module-scoped) and `db_urls` (`sync` / `async` / raw `dsn`). Migrations and topics come from
`apply_migrations(env)` / `create_topics(env)` (lines 28-50), both subprocess-based with an
assert on `returncode`.

---

### `tests/unit/test_api_async_only.py` and the other grep gates

**Analog:** `tests/unit/test_no_inline_sleep.py` (non-vacuity) + `test_no_setnx_expire_pairs.py`
(comment stripping) — copy both halves.

**Comment-stripping scan** (`test_no_setnx_expire_pairs.py:13-33`):

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
SCANNED_DIRS = ("services", "shared", "scripts")

DEPRECATED_CLAIM = re.compile(r"\.\s*setnx\s*\(", re.IGNORECASE)


def _code_lines(path: Path) -> str:
    """Source with full-line comments stripped, so a comment can neither satisfy
    nor break the gate."""
    return "\n".join(
        line for line in path.read_text().splitlines() if not line.strip().startswith("#")
    )
```

**Mandatory non-vacuity companion** (`test_no_inline_sleep.py:40-47`):

```python
def test_scanned_file_set_is_not_empty():
    """A glob that silently matched nothing would make both assertions below vacuous."""
    assert len(SCANNED_FILES) >= 8
    for path in SCANNED_FILES:
        assert path.is_file(), path
    names = {path.name for path in SCANNED_FILES}
    assert {"consumer.py", "main.py", "engine.py", "store.py"} <= names
```

For `services/api` the name set is `{"app.py", "sse.py", "ratelimit.py", "middleware.py"}`.

**Behavioural-claim gate** (`test_no_setnx_expire_pairs.py:55-67`, `test_set_nx_ex_is_a_single_atomic_call`)
is the template for "the API rate-limit script issues exactly one `INCR` and one conditional
`EXPIRE` inside one `redis.call` script" and for D-98's consumer-config assertions.

**Log-leak test** (`tests/unit/test_logs_never_carry_payload.py`) is the named model for BC-3's
`test_api_logs_never_carry_payload.py`; `tests/unit/test_safe_error.py` and
`test_telemetry_redaction.py` are the existing assertions the new one must not duplicate.

**Metrics test** (`tests/unit/test_metrics_registry.py:1-30`) documents the two traps any
`/api/metrics` test inherits: double registration at import, and the `Counter("x_total")` →
sample-name `x_total` / `x_created` trap where `assert value is None` passes vacuously. Note
`shared/metrics.py` itself is still absent (plan 03-02, in flight).

---

### `Makefile` and `.env.example` (config) — MODIFY

**Makefile target shape** (`Makefile:1-30`): every target has a `## comment` (the `help` target
greps for it) and every target name is listed in the single `.PHONY` line. Add `api` and
`api-smoke` there. Long rationale goes *inside* the recipe as `#` lines — see the `test` target
(`Makefile:31-39`), which explains `-W error::RuntimeWarning` in six lines.

**`.env.example` convention** (`.env.example:11-30`): each block has a `# Section` header, and
any variable with a safety property carries a multi-line comment stating the failure mode and
the interlock (`MISE_CRASH_AFTER`, `STATE_MACHINE_MAX_ATTEMPTS`). The Phase 5 block
(`PUBLIC_BASE_URL`, `CORS_ALLOWED_ORIGINS`, `ADMIN_BASIC_*`, `TRUST_PROXY_HEADERS`,
`PROXY_HOPS`, `HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL`, `API_PORT`) must state BC-2's
"second-to-last hop, one appending proxy" assumption next to `TRUST_PROXY_HEADERS`, and that
`false` is the local default. `HMAC_MGMT_SECRET_V1` already appears in
`shared/telemetry.py`'s `_SECRET_KEYS` — keep the placeholder-value style used by
`TWILIO_AUTH_TOKEN=your_auth_token_here`.

---

## Shared Patterns

### Exception → log field
**Source:** `shared/telemetry.py:52-95` (`safe_error`), `services/state_machine/consumer.py:83`
(`_failure_shape`)
**Apply to:** every `except` arm in `services/api/**`, especially `middleware.py :: ErrorBoundary`
(BC-3) and `watch_service.py` (whose bound parameters are the encrypted phone and the email).

```python
    message = _SQL_DETAIL_RE.sub("", str(exc))          # strips SQLAlchemy's [SQL:]/[parameters:]
    message = _INPUT_VALUE_RE.sub(f"input_value={_SCRUBBED}", message)   # pydantic input echo
    message = _PG_DETAIL_RE.sub(rf"\1\2: {_SCRUBBED}", message)         # PG DETAIL:/HINT:
```

Use `safe_error` for our own infrastructure failures and `_failure_shape` for failures raised
while handling producer- or client-supplied data (the docstring at
`shared/telemetry.py:78-95` states the split).

### Logger acquisition
**Source:** `shared/telemetry.py:136-144` + every service module header
**Apply to:** every module in `services/api/**` and `shared/watch_counts.py`

```python
from shared.telemetry import get_logger, safe_error

log = get_logger(__name__)
```

`configure_logging()` is idempotent and is called once at startup (`main.py:81`); the API calls
it inside `lifespan` before anything else, and additionally routes `uvicorn.error` /
`uvicorn.access` through structlog (D-97a / OQ-6). Note `configure_logging` currently owns
`logging.basicConfig` (`shared/telemetry.py:118`) — the uvicorn `log_config=None` decision
depends on that.

### Redis access
**Source:** `shared/redis_keys.py` module docstring (lines 1-21) and the typed helper block
(lines 487-545)
**Apply to:** `ratelimit.py`, `watch_counts.py`, `routers/admin.py`, `routers/restaurants.py`
(`/api/stats` cache)

*"Single source of truth for ALL Redis key patterns and TTLs (D-18). Any Redis access in
services/ MUST import from here."* Every new key (`rate:api:*`, the `/api/stats` cache key) gets
a named function plus an entry in the `Named symbols:` docstring list. Every mutation-plus-TTL
is one command or one script — `set_str_ex` (line 522), `canary_window_push` (line 537).

### Module docstring contract
**Source:** every shipped module (`shared/kafka.py:1-8`, `shared/redis_keys.py:1-21`,
`services/state_machine/persistence.py:1-9`)
**Apply to:** all new modules

Three parts: what the module is and the decision ids it implements; the non-obvious constraint
that will otherwise be "fixed" by a future reader (e.g. D-98a's "`commit()` is never called on
this consumer"; Pitfall 6's "`enable_auto_commit=False` with `group_id=None` is not a
contradiction"); and a `Named symbols:` list.

### Best-effort side effect
**Source:** `services/state_machine/persistence.py:106-113` and `:165`
**Apply to:** `recount()` (D-95a), the management-link email (D-93)

```python
    except Exception as exc:  # noqa: BLE001 — best effort: never block the emit or the commit
```

The `noqa` comment states *why* the blind except is correct. Reproduce that discipline; a bare
`# noqa: BLE001` with no reason is not the pattern.

---

## No Analog Found

| File | Role | Data Flow | Reason | Use instead |
|------|------|-----------|--------|-------------|
| `services/api/routers/{watches,manage,push}.py` | controller | CRUD | No FastAPI router exists on disk. Phase 4 **D-84 / plan 04-04** (`04-04-api-links-webhooks-PLAN.md`) creates `services/api/app.py`, `routers/links.py`, `routers/webhooks.py` | 04-04's plan text; extend `create_app()`, never rewrite it |
| `services/api/middleware.py` | middleware | streaming | No ASGI middleware in the repo | 05-RESEARCH.md § Code Examples (executed, mypy-clean) |
| `services/api/sse.py :: FeedHub` | service | pub-sub | No in-memory fan-out anywhere | 05-RESEARCH.md § Code Examples "FeedHub" |
| `services/api/routers/feed.py` | controller | streaming | No `StreamingResponse` in the repo | 05-RESEARCH.md § SSE (wire format + headers) |
| `services/api/routers/metrics.py` | controller | request-response | `shared/metrics.py` not yet on disk (Phase 3 **D-69 / plan 03-02**, in flight) | 03-02 plan; `tests/unit/test_metrics_registry.py` already pins its contract |
| `services/api/schemas/*.py` | model | transform | `shared/events.py` is the closest (pydantic v2 wire models) but is Kafka-shaped, not HTTP-shaped | 05-RESEARCH.md § Request Models (`WatchCreate` sketch, 18-rule matrix) |
| token verify / HMAC call sites | utility | — | `shared/tokens.py` does not exist (Phase 4 **D-82 / plan 04-01**) | 04-01 plan §"New symbols — `shared/tokens.py`" |
| phone encrypt call sites | utility | — | `shared/crypto.py` does not exist (Phase 4 **D-85 / plan 04-01**) | 04-01 plan §"New symbols — `shared/crypto.py`" |
| management-link email | service | request-response | `services/notifier/providers/email.py` does not exist (Phase 4 **D-78 / plan 04-05**) | 04-05 plan |
| `push_subscriptions` writes | model | CRUD | Table is created by Phase 4 **migration 0010 / plan 04-02** | 04-02 plan |
| slug-sibling fan-out | service | CRUD | `services/notifier/matching.py` does not exist (Phase 4 **D-73 / plan 04-03**) | 04-03 plan; this phase amends its join |
| `docs/api.md` | docs | — | No route reference document exists | 05-CONTEXT §Specifics (curl walkthrough as the SC artifact) |

**Wave 0 consequence (D-93a):** every row above whose analog is a Phase 3/4 artifact is a
precondition assertion, not a pattern. The verification wave should fail with the owning
decision id (`D-82`, `D-85`, `D-78`, `D-84`, `D-73`, `D-58`, `D-69`, `D-63b`) rather than with
an `ImportError`.

**One live trap to re-verify at execution time** (05-RESEARCH.md § Sequencing Dependencies,
still true at HEAD): `shared/db.py:57` declares
`slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)`. Phase 3 plan 03-03 is
supposed to replace it with the `(slug, source)` constraint. Until it does, any
`Base.metadata.create_all` rebuilds the old unique constraint and the entire "one slug, two
source rows" model of D-93/D-100 silently fails. The `Restaurant` class already carries the
right shape for the sibling constraint to copy (`shared/db.py:68-70`):

```python
    __table_args__ = (
        UniqueConstraint("source", "platform_id", name="uq_restaurants_source_platform_id"),
    )
```

## Metadata

**Analog search scope:** `services/`, `shared/`, `scripts/`, `migrations/versions/`, `tests/unit/`,
`tests/integration/`, `Makefile`, `.env.example`, plus the Phase 3 and Phase 4 plan files for
artifacts not yet on disk.
**Files scanned:** 41 source files, 4 plan documents.
**Repository state:** HEAD `ac8676d` (`feat(03-02)`), 2026-09-05.
**Pattern extraction date:** 2026-09-05
