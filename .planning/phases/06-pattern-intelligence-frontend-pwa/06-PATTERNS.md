# Phase 6: Pattern Intelligence & Frontend PWA - Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 48 (14 backend, 34 frontend/tooling)
**Analogs found:** 41 / 48 (7 have no analog — see `## No Analog Found`)

> **Repo state at mapping time (verified on disk, 2026-09-05):** `migrations/versions/` ends at
> `0008_add_event_id_to_availability_events.py`; `services/` contains only `poller/` and
> `state_machine/`; there is no `services/api/`, no `services/notifier/`, no `web/`. Every
> Phase 4 (D-81..D-87) and Phase 5 (D-98..D-100) artifact this phase extends is **not yet
> executed**. Where a "closest analog" is a Phase 4/5 file, it is marked `[NOT ON DISK]` with
> the defining decision id, and the planner must treat it as a dependency, not as a file to read.
> Frontend analogs are the executed research scaffold at
> `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-06/web/`
> (referred to below as `SCRATCH/web`) — real files, built green on this machine, not
> hypothetical snippets.

---

## File Classification

### Backend (Python)

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `migrations/versions/0011_availability_events_hourly_cagg.py` | migration | batch / DDL | `migrations/versions/0008_add_event_id_to_availability_events.py` + `SCRATCH/alembictest/migrations/versions/0002_cagg.py` | role-match + executed CAGG proof |
| `shared/pattern/__init__.py` | package init | — | `shared/scheduler/__init__.py` | exact |
| `shared/pattern/model.py` | model (pure functional core) | transform | `services/state_machine/engine.py` | exact (pure, no clock, no I/O) |
| `shared/pattern/repo.py` | repository | CRUD (read-only) | `services/state_machine/persistence.py` | exact |
| `shared/pattern/service.py` | service (cached shell) | request-response + cache-aside | `services/state_machine/store.py` (store seam) + `shared/redis_keys.py` (keys/TTL/casts) | role-match |
| `shared/redis_keys.py` (modified — add `pattern_cache_key`, `heatmap_cache_key`, `PATTERN_CACHE_TTL_SECONDS`) | config / constants | — | itself (existing section idiom) | exact |
| `services/api/routers/restaurants.py` (modified — `/heatmap`, `/pattern`, `pattern_status`) | route | request-response | Phase 5 D-100 router `[NOT ON DISK]`; nearest on-disk shape: none | no analog |
| `services/api/routers/links.py` (modified — `Accept: application/json` mode on `/go/{token}`) | route | request-response | Phase 4 D-84 `links.py` `[NOT ON DISK]` | no analog |
| `services/api/sse.py` (modified — emit `retry: 2000` first frame) | service (streaming) | streaming | Phase 5 D-98 `FeedHub` `[NOT ON DISK]`; executed proof in `SCRATCH/sse/test_sse.py` | partial (proof only) |
| `services/notifier/pattern_hook.py` (implement) | utility / adapter | request-response | Phase 4 D-81 stub `[NOT ON DISK]` | no analog |
| `tests/unit/test_pattern_model.py` | test (unit) | transform | `tests/unit/test_engine_transitions.py` | exact |
| `tests/unit/test_pattern_wilson_and_quartiles.py` | test (unit) | transform | `tests/unit/test_engine_purity.py`, `tests/unit/test_backoff_math.py` | exact |
| `tests/unit/test_pattern_hook.py` | test (unit) | request-response | `tests/unit/test_service_time_math.py` | role-match |
| `tests/integration/test_cagg_availability_events_hourly.py` | test (integration) | batch | `tests/integration/test_migration_0008.py` + `tests/integration/conftest.py` | exact |
| `tests/integration/test_pattern_routes.py` | test (integration) | request-response | `tests/integration/test_migration_0008.py` (fixtures) — route-client idiom is Phase 4 D-87 `[NOT ON DISK]` | partial |

### Frontend (`web/`) — no code exists in the repo; analog source is `SCRATCH/web`

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `web/package.json` | config | — | `SCRATCH/web/package.json` | exact (installed + built) |
| `web/next.config.ts` | config | — | `SCRATCH/web/next.config.ts` | exact |
| `web/tsconfig.json` | config | — | `SCRATCH/web/tsconfig.json` | exact |
| `web/eslint.config.mjs` | config | — | `SCRATCH/web/eslint.config.mjs` | exact |
| `web/vitest.config.mts`, `web/vitest.setup.ts` | config (test) | — | `SCRATCH/web/vitest.config.mts`, `vitest.setup.ts` | exact |
| `web/src/app/globals.css` | config (design tokens) | — | UI-SPEC `## Design System` token-wiring block (`@theme inline`) | spec-match |
| `web/src/app/layout.tsx` | provider / shell | — | `SCRATCH/web/src/app/layout.tsx` + UI-SPEC `## Component Inventory` #5 (toast live region) | role-match |
| `web/src/app/manifest.ts` | config | — | `SCRATCH/web/src/app/manifest.ts` | exact |
| `web/src/app/sw.ts` | service worker | event-driven / pub-sub | `SCRATCH/web/src/app/sw.ts` | exact (built to `public/sw.js`) |
| `web/src/app/page.tsx` (home) | page (server) | request-response | `SCRATCH/web/src/app/page.tsx` + UI-SPEC `## Page Layout Contracts` row `/` | role-match |
| `web/src/app/restaurant/[slug]/page.tsx` | page (server) | request-response | UI-SPEC `/restaurant/[slug]` row; data shape from D-107/D-108 | spec-match |
| `web/src/app/watch/[slug]/page.tsx` + `WatchForm.tsx` | page + client island | request-response + file/IDB queue | UI-SPEC `/watch/[slug]` row + `## Push-permission states` | spec-match |
| `web/src/app/manage/t/[token]/page.tsx` + `WatchCardActions.tsx` | page (server shell) + client island | CRUD | UI-SPEC `/manage/t/[token]` row + `WatchCard` (#8) | spec-match |
| `web/src/app/go/[token]/page.tsx` | page | request-response + redirect | D-116a (RSC fetch + client redirect island) — **conflicts with UI-SPEC** (see Conflicts) | spec-match, needs resolution |
| `web/src/app/offline/page.tsx` | page (static) | — | `SCRATCH/web/src/app/offline/page.tsx` (precached in the executed build) + UI-SPEC `OfflineState` (#12) | exact |
| `web/src/lib/api.ts` | service (HTTP client) | request-response | `SCRATCH/web/src/lib/api.ts` **plus the BC-2 `safeFetch` correction** | role-match (analog must be corrected) |
| `web/src/lib/feed.ts` | store (reducer, pure) | event-driven | `SCRATCH/web/src/lib/feed.ts` | exact |
| `web/src/lib/preview.ts` | utility (pure) | transform | `services/notifier/templates.py` `[NOT ON DISK]` (D-81 wording is the source of truth) | no analog |
| `web/src/lib/format.ts` | utility (pure) | transform | `services/state_machine/persistence.py::day_of_week` (weekday convention 0=Sun) | partial |
| `web/src/components/Heatmap.tsx` | component (server SVG) | transform | `SCRATCH/web/src/components/Heatmap.tsx` (table version) upgraded to the UI-SPEC SVG contract (#6) | role-match |
| `web/src/components/ui/{Button,Card,Field,Badge,Toast}.tsx` | component | — | UI-SPEC `## Component Inventory` #1–#5 | spec-match |
| `web/src/components/{FeedRow,WatchCard,StepIndicator,PatternCard,EmptyState,OfflineState}.tsx` | component | — | UI-SPEC #7–#12 | spec-match |
| `web/src/components/*.test.tsx`, `web/src/lib/*.test.ts` | test | — | `SCRATCH/web/src/components/Heatmap.test.tsx`, `SCRATCH/web/src/lib/feed.test.ts` | exact |
| `web/src/test/fixtures/*.ts` | test fixture | — | `tests/unit/factories.py` (typed factory idiom); D-118a forbids MSW | partial |
| `web/scripts/lighthouse.mjs` | script | batch | `SCRATCH/web/scripts/lighthouse.mjs` | exact (executed: LCP 1810 ms) |
| `Makefile` (modified — `web-install`, `web-dev`, `web-build`, `web-build-offline`, `web-test`, `lighthouse`) | config | — | `Makefile` existing targets | exact |
| `.env.example` (modified — `NEXT_PUBLIC_*`, `PUBLIC_BASE_URL` = web origin) | config | — | `.env.example` existing sections | exact |
| `web/README.md`, `docs/api.md` note, `docs/runbooks/ios-pwa-push.md` (modified) | docs | — | `services/state_machine/README.md` | role-match |

---

## Pattern Assignments

### `migrations/versions/0011_availability_events_hourly_cagg.py` (migration, DDL)

**Analogs:** `migrations/versions/0008_add_event_id_to_availability_events.py` (repo idiom) and
`SCRATCH/alembictest/migrations/versions/0002_cagg.py` (executed CAGG, upgrade + downgrade +
re-upgrade against `timescale/timescaledb:2.17.2-pg16`).

**Header + revision pattern to copy** (`0008…py:1-24`) — a docstring that names the decision ids
*and* the research corrections it encodes, then bare module-level revision globals:

```python
"""0008: Add event_id + unique (event_id, time) to availability_events (D-48a, corrected).
...
  B-2 — a unique index on a hypertable must include the partitioning column "time";
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None
```

`down_revision` for 0011 is **whatever Phase 4/5 last shipped** (0009/0010 do not exist yet) —
the plan must read `migrations/versions/` at execution time, not hardcode `"0010"`.

**Guard-before-destructive-DDL pattern** (`0008…py:37-49`) — 0011 is additive so it needs no
row guard, but the same "refuse loudly rather than silently destroy" tone applies to the
downgrade:

```python
    existing = op.get_bind().execute(
        sa.text("SELECT count(*) FROM availability_events")
    ).scalar_one()
    if existing:
        raise RuntimeError(...)
```

**COMMENT-ON-COLUMN pattern** (`0008…py:69-79`) — note the doubled `%%`, required because
alembic format-steps the string. Reuse it to document `dow_local` vs `day_of_week` (BC-11):

```python
    op.execute(
        "COMMENT ON COLUMN availability_events.day_of_week IS "
        "'0=Sun .. 6=Sat (service_date.isoweekday() %% 7) "
        "— matches the Phase 6 heatmap y-axis (D-48)'"
    )
```

**Core CAGG pattern — copy verbatim** from `SCRATCH/alembictest/migrations/versions/0002_cagg.py`
(this exact file ran `upgrade`/`downgrade`/`upgrade` green), adding the BC-11 `dow_local` column:

```python
CAGG = """
CREATE MATERIALIZED VIEW availability_events_hourly
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT time_bucket('1 hour', "time") AS bucket,
       restaurant_id, source, day_of_week,
       EXTRACT(dow  FROM "time" AT TIME ZONE 'America/New_York')::int AS dow_local,
       EXTRACT(hour FROM "time" AT TIME ZONE 'America/New_York')::int AS hour_local,
       count(*) AS events,
       sum(duration_seconds)::bigint AS duration_sum,
       count(duration_seconds) AS duration_n,
       min("time") AS first_event, max("time") AS last_event
FROM availability_events
GROUP BY bucket, restaurant_id, source, day_of_week, dow_local, hour_local
WITH NO DATA
"""

def upgrade() -> None:
    # in-transaction: WITH NO DATA is legal (BC-5)
    op.execute(CAGG)
    op.execute("""SELECT add_continuous_aggregate_policy('availability_events_hourly',
        start_offset => INTERVAL '30 days', end_offset => INTERVAL '1 hour',
        schedule_interval => INTERVAL '15 minutes', if_not_exists => TRUE)""")
    # refresh MUST be outside a transaction (BC-5)
    with op.get_context().autocommit_block():
        op.execute("CALL refresh_continuous_aggregate('availability_events_hourly', NULL, NULL)")

def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS availability_events_hourly")
```

Non-negotiables carried from research: `timescaledb.materialized_only = false` explicit (BC-6),
no `avg`/`percentile_cont` in the view (not re-aggregable, D-105a), `WITH NO DATA` (BC-5).

---

### `shared/pattern/model.py` (model, pure transform)

**Analog:** `services/state_machine/engine.py` — the repo's canonical functional core.

**Module docstring + purity declaration to copy** (`engine.py:1-9`) — the "Named symbols:" line
is a repo-wide convention (present in `engine.py`, `store.py`, `persistence.py`,
`redis_keys.py`, `config.py`, `tests/integration/conftest.py`) and CI/greps rely on it:

```python
"""
Pure diff engine: normalised poll in, decisions out (D-38, D-41, D-44, D-49, D-53; STATE-02, STATE-04).

Functional core / imperative shell. This module performs no I/O of any kind, reads no clock and
draws no entropy — every timestamp in every decision comes from the message's polled_at_epoch_ms,
and all state access goes through the StateStore protocol. That is precisely what makes
byte-identical replay provable in CI (STATE-06); a single clock read here would make it flake.
Named symbols: StateStore, DiffEngine, MASS_CLOSURE_AUDIT_THRESHOLD
"""
from __future__ import annotations
```

`compute_pattern(events, now, cfg)` takes `now` as a parameter for exactly the reason stated
above — no `datetime.now()` in this module. Mirror it with a `tests/unit/test_pattern_purity.py`
modelled on the existing `tests/unit/test_engine_purity.py`.

**Threshold-constant pattern** (`engine.py:26-30`) — a named module constant with a comment
explaining it is an *observation* threshold, not an outcome lever:

```python
# Above this many closures in a single poll the shell logs a distinct auditable event, so the
# Phase 3 soft-ban canary has a training signal (research Pitfall 10). It is an observation
# threshold only: it never changes the diff outcome, which must stay deterministic.
MASS_CLOSURE_AUDIT_THRESHOLD: int = 5
```

Apply to `PATTERN_MIN_EVENTS = 30`, `MIN_DAYS_OF_HISTORY = 14`, `RULE_48H_MIN_SHARE = 0.25`,
`RULE_48H_MIN_CI_LOW = 0.15`, `LOAD_DAY_RATIO = 3.0`, `DURATION_MIN_N = 10`,
`SPARSE_CELL_THRESHOLD = 10` — all as `PatternConfig` defaults, not scattered literals.

**Protocol/seam pattern** (`engine.py:33-47`) — if the model needs a pluggable input source, use
`typing.Protocol` with the concrete implementations named in the docstring, as `StateStore` does.

**Weekday convention — the load-bearing detail (BC-11).** `services/state_machine/persistence.py:53-55`
is the source of truth for `day_of_week`:

```python
def day_of_week(service_date: date) -> int:
    """0=Sun .. 6=Sat — the Phase 6 heatmap y-axis and migration 0008's column comment (B-5)."""
    return service_date.isoweekday() % 7
```

`EventObs.day_of_week` (service night, heatmap y-axis) and `EventObs.dow_local`
(observation weekday, inventory-load-day rule) are **different fields**. Both are 0=Sun.

**Statistics:** stdlib only — `math` for the Wilson closed form, `statistics.quantiles(method="inclusive")`
for p25/p50/p75 (D-106a; proven byte-identical to SQL `percentile_cont`). No numpy/scipy.

---

### `shared/pattern/repo.py` (repository, read-only DB access)

**Analog:** `services/state_machine/persistence.py`.

**Imports + session-factory pattern** (`persistence.py:11-31`):

```python
from __future__ import annotations

from sqlalchemy import CursorResult, Integer, func, literal, update
from shared.db import AvailabilityEvent as AvailabilityEventRow
from shared.db import get_async_session
from shared.telemetry import get_logger, safe_error

log = get_logger(__name__)

# Service times are local to the restaurant; every mise restaurant is in NYC (PROJECT.md).
_SERVICE_TZ = ZoneInfo("America/New_York")
```

**Session usage** (`persistence.py:100-105`) — acquire the factory, open a context-managed
session per operation, never a module-level session:

```python
        session_factory = get_async_session()
        async with session_factory() as session:
            await session.execute(statement)
            await session.commit()
```

D-107 signatures take `session` as a parameter, so the repo functions are the *inner* layer and
`service.py` owns the `async with session_factory()`.

**Error-handling pattern** (`persistence.py:110-124`) — `safe_error(exc)`, **never** `str(exc)`
(CR-03), plus structured kwargs on the logger. Reads cannot leak booking tokens the way the
insert can, but the `safe_error` rule is repo-wide and greps enforce it
(`tests/unit/test_safe_error.py`, `tests/unit/test_logs_never_carry_payload.py`).

**Hypertable predicate rule (B-2/B-3, `persistence.py:66-73` + `0008` comments):** any predicate
against `availability_events` must name `"time"` so the planner gets a single-chunk index scan.
`load_observations(..., since)` therefore filters on `"time" >= :since` first.

**Column reference:** `shared/db.py:110-136` (`AvailabilityEvent`) — the exact column set the repo
may select (`first_seen_at`, `duration_seconds`, `hours_before_service`, `day_of_week`, …) and the
D-52 warning that `restaurant_id` is the **source platform id**, not `restaurants.id`. The
slug→sources merge (D-107, Phase 5 D-100) must therefore join on `(source, platform_id)`.

---

### `shared/pattern/service.py` (service, cache-aside over Redis)

**Analogs:** `shared/redis_keys.py` (all key strings + TTLs + redis-py casts live there) and
`services/state_machine/store.py` (the consumer of those helpers).

**Rule to copy verbatim** (`store.py:9-11`):

```
Every key string comes from `shared.redis_keys` and every redis-py cast lives there too, so
this module contains neither (D-42, research Pitfall 3).
```

So `pattern:{slug}` / `heatmap:{slug}` and `PATTERN_CACHE_TTL_SECONDS = 600` are **added to
`shared/redis_keys.py`**, not written inline in `service.py`. Follow the existing section style
(`redis_keys.py:59-73`), including the "Named symbols:" header update at `redis_keys.py:2-21`:

```python
# -- Availability state (D-40, D-42, STATE-01) --
AVAIL_STATE_TTL_SECONDS: int = 90_000        # 25 h — one full service day plus slack

def avail_state_key(restaurant_id: int, date: str, party_size: int) -> str:
    """Return the HASH key holding known slot records for one (rid, date, party) (D-40)."""
    return f"avail:{restaurant_id}:{date}:{party_size}"
```

**Single-command SET-with-TTL** (`redis_keys.py:522-529`) — the JSON cache write uses
`set_str_ex`, never `SET` then `EXPIRE`; `tests/unit/test_no_setnx_expire_pairs.py` greps for
the pair and will fail the build:

```python
async def set_str_ex(r: Redis, key: str, value: str, ttl_seconds: int) -> bool:
    """
    SET ``key`` to ``value`` with a TTL in a single command (never SET then EXPIRE).
    ...
```

**Defensive decode** (`store.py:41-43`) — `redis.from_url` does not decode by default:

```python
def _text(value: object) -> str:
    """Decode defensively: `redis.from_url` defaults to `decode_responses=False`."""
    return value.decode() if isinstance(value, (bytes, bytearray)) else str(value)
```

**Redis client acquisition:** `services/state_machine/main.py:115` / `services/poller/main.py:84`
(`r = redis.from_url(url)` in the shell, url from a lazy config function).

**Lazy env reads** — `services/state_machine/config.py:7-14` states the rule explicitly:

```
Every environment read below is a FUNCTION, not a module constant, and that is deliberate.
`services/poller/config.py` freezes KAFKA_BOOTSTRAP_SERVERS / REDIS_URL into module constants
at IMPORT time, so any integration test that imports the service during collection pins the
whole run to the localhost defaults instead of its testcontainers (02-02 deviation 1).
```

`PATTERN_MIN_EVENTS` therefore reads via a function, not a module constant.

---

### `services/notifier/pattern_hook.py` (utility/adapter)

**Analog:** none on disk — the stub is created by Phase 4 **D-81** and must already exist before
this file is implemented. The contract is fixed there:
`estimate_window_text(source, restaurant_id) -> str | None`, and `templates.py` omits the line
on `None`. Implementation reads `shared/pattern/service.py`, returns text only when
`status == "ready"` **and** duration `n >= 10` (D-108). Style: copy the docstring +
`Named symbols:` + `safe_error` logging idiom from `services/state_machine/persistence.py`.

---

### `services/api/routers/restaurants.py`, `links.py`, `services/api/sse.py` (routes / streaming)

**Analog:** none on disk. `services/api/` is created by Phase 4 **D-84** (`create_app()`,
`routers/links.py`, `routers/webhooks.py`) and extended by Phase 5 **D-98/D-100**
(`routers/restaurants.py`, `sse.py :: FeedHub`). The planner must:

- add `/heatmap` and `/pattern` to the **existing** Phase 5 restaurants router (D-108), never a
  new router file;
- add the `Accept: application/json` branch to the **existing** Phase 4 `/go/{token}` handler,
  preserving the 302 for non-JSON clients (D-116) and the D-84 click-capture write;
- add the `retry: 2000` first frame to the Phase 5 `FeedHub` stream generator (D-112a) — the
  executed SSE proof at `SCRATCH/sse/test_sse.py:30-40` shows the exact frame ordering and
  headers Chromium honours:

```python
        if n == 0:
            yield b"retry: 300\n\n"
            yield b"id: evt-1\nevent: slot_opened\ndata: {\"event_id\":\"evt-1\"}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

If Phase 5 has already shipped `retry:`, this becomes a no-op verification task.

---

### `tests/unit/test_pattern_model.py` (test, unit)

**Analog:** `tests/unit/test_engine_transitions.py`.

**Docstring + no-clock discipline** (`test_engine_transitions.py:1-6`):

```python
"""
The full D-41 transition table, driven entirely by explicit poll timestamps.

No test here waits on real time, uses freezegun, or touches Redis: every timing fact is a
polled_at_epoch_ms value passed to the factory (D-44, D-49).
"""
```

Pattern tests pass an explicit `now` into `compute_pattern` for the same reason.

**Fixture constants + private builder** (`test_engine_transitions.py:11-29`):

```python
from tests.unit.factories import make_parsed, make_slot

RID = 42
DATE = "2026-05-01"
T0 = 1_788_000_000_000

def _engine() -> tuple[DiffEngine, MemoryStateStore]:
    store = MemoryStateStore()
    return DiffEngine(store, confirm_delay_ms=CONFIRM_DELAY_MS), store
```

Add `make_event_obs(...)` to `tests/unit/factories.py` (the existing shared factory module) and
build the four D-108 corpora (48-hour-heavy, load-day, flat, sparse) from it.

**Test naming:** full-sentence names asserting the behaviour and citing the decision, e.g.
`test_pending_slot_absent_on_next_covered_poll_is_dropped_with_no_event`, with a one-line
docstring naming the requirement (`ROADMAP SC1`).

---

### `tests/integration/test_cagg_availability_events_hourly.py` (test, integration)

**Analog:** `tests/integration/test_migration_0008.py` + `tests/integration/conftest.py`.

**Module header, marker, module-scoped migration fixture** (`test_migration_0008.py:1-30`):

```python
"""Integration: STATE-05 — migration 0008 on a live TimescaleDB hypertable.

Carries standing regression guards for two blocking corrections reproduced in research:
B-2 ... and B-3 ...
"""
import asyncpg
import pytest
from tests.integration.conftest import apply_migrations

pytestmark = pytest.mark.integration

@pytest.fixture(scope="module", autouse=True)
def migrated(db_urls):
    """Apply every migration, including 0008, against the module's container."""
    apply_migrations({**os.environ, "DATABASE_URL_SYNC": db_urls["sync"]})
    return db_urls
```

**Raw-asyncpg connection + try/finally close** (`test_migration_0008.py:42-54`):

```python
@pytest.mark.asyncio
async def test_event_id_column_is_uuid_not_null(db_urls):
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        row = await conn.fetchrow(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'availability_events' AND column_name = 'event_id'"
        )
        assert row is not None, "event_id column missing — migration 0008 did not apply"
    finally:
        await conn.close()
```

**Fixtures available from `tests/integration/conftest.py`** (do not re-implement): `db_urls`
(`sync` / `async` / `dsn`, lines 55-70), `redis_url`, `apply_migrations`, `create_topics`,
`reset_shared_db_singletons`.

**Phase-6-specific assertions** (from BC-5/BC-6): `SELECT materialized_only FROM
timescaledb_information.continuous_aggregates WHERE view_name = 'availability_events_hourly'`
is `false`; one policy job exists; `CALL refresh_continuous_aggregate(...)` must be issued
**outside** any transaction in the test connection.

---

### `web/` scaffold configs — `package.json`, `next.config.ts`, `tsconfig.json`, `eslint.config.mjs`, `vitest.config.mts`

**Analog:** `SCRATCH/web/*` — these exact files scaffolded, installed, built and tested green on
this machine on 2026-09-05. Copy them, then apply the deltas noted.

**`package.json` scripts — the BC-1 non-negotiable** (`SCRATCH/web/package.json`):

```json
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint",
    "test": "vitest run",
    "test:watch": "vitest",
    "typecheck": "tsc --noEmit"
  }
```

No `--turbopack` anywhere (BC-1: turbopack builds exit 0 and emit **no** service worker). Add
the grep gate. Deltas from the scratch file: **drop `msw`** (D-118a) and add `api:check`.

**`next.config.ts`** (`SCRATCH/web/next.config.ts`) — copy, then add the BC-3 corrections
(`fallbacks.entries` for `/offline`, `/` in `additionalPrecacheEntries` with a build-id revision)
and regenerate `remotePatterns` from the real seed hostnames (D-109b — the seed file's
`cover_photo_url` hosts on disk today are `placeholder.mise.place`, `resizer.otstatic.com` is an
assumption in the scratch file and must be re-derived at execution time):

```ts
const withSerwist = withSerwistInit({
  swSrc: "src/app/sw.ts",
  swDest: "public/sw.js",
  cacheOnNavigation: true,
  reloadOnOnline: true,
  disable: process.env.NODE_ENV === "development",
  additionalPrecacheEntries: [{ url: "/offline", revision: "1" }],
});
```

**`tsconfig.json`** — two build-breaking requirements proven by BC-8:
`"lib": ["dom","dom.iterable","esnext","webworker"]`, `"types": ["@serwist/next/typings"]`,
and `"exclude": ["node_modules", "public/sw.js"]`.

**`eslint.config.mjs`** — BC-7 ignores (`npm run lint` is red without them):

```js
    ignores: [
      "node_modules/**", ".next/**", "out/**", "build/**", "next-env.d.ts",
      "public/sw.js", "public/sw*.js", "public/swe-worker*.js",
    ],
```

Same three globs go into `web/.gitignore`.

**`vitest.config.mts` + `vitest.setup.ts`** — copy verbatim:

```ts
export default defineConfig({
  plugins: [react()],
  resolve: { tsconfigPaths: true },
  test: { environment: "jsdom", globals: true, setupFiles: ["./vitest.setup.ts"], include: ["src/**/*.test.{ts,tsx}"] },
});
```
```ts
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
afterEach(() => cleanup());
```

---

### `web/src/app/sw.ts` (service worker, event-driven)

**Analog:** `SCRATCH/web/src/app/sw.ts` — compiled to a working `public/sw.js` in the executed
build. Copy in full; the `push` handler's `waitUntil`-wraps-the-entire-async-chain shape is the
STATE.md iOS pitfall fix and must not be refactored:

```ts
declare const self: ServiceWorkerGlobalScope;

self.addEventListener("push", (event: PushEvent) => {
  // The ENTIRE async chain must be inside waitUntil or iOS silently revokes the
  // subscription after ~3 pushes (STATE.md Phase 4 pitfall).
  event.waitUntil(
    (async () => {
      let payload: MisePushPayload = { title: "mise en place", body: "A table opened." };
      try {
        if (event.data) payload = { ...payload, ...(event.data.json() as MisePushPayload) };
      } catch {
        if (event.data) payload = { ...payload, body: event.data.text() };
      }
      await self.registration.showNotification(payload.title, {
        body: payload.body, tag: payload.tag, data: { url: payload.url ?? "/" },
        icon: "/icons/icon-192.png", badge: "/icons/badge-72.png",
      });
    })(),
  );
});

self.addEventListener("notificationclick", (event: NotificationEvent) => {   // BC-8: NOT NotificationClickEvent
```

**Required delta (BC-4):** `runtimeCaching: defaultCache` in the scratch file is wrong for a
cross-origin API. Prepend an explicit rule and exclude the SSE endpoint:

```ts
const apiOrigin = new URL(process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000").origin;
runtimeCaching: [
  { matcher: ({ url }) => url.origin === apiOrigin && url.pathname.startsWith("/api/")
             && !url.pathname.startsWith("/api/feed/live"),
    method: "GET",
    handler: new NetworkFirst({ cacheName: "mise-api", networkTimeoutSeconds: 5,
      plugins: [new ExpirationPlugin({ maxEntries: 64, maxAgeSeconds: 300 })] }) },
  ...defaultCache,
]
```

**Push payload contract** comes from Phase 4 D-81: `{title, body, url, tag=event_id}`.

---

### `web/src/lib/api.ts` (service, HTTP client)

**Analog:** `SCRATCH/web/src/lib/api.ts` for the shape (typed response interfaces, `ApiError`
class, `Bearer` header on mutations) — **but its `getPattern` throws on `!res.ok`, which is
exactly the BC-2 build-breaker.** The corrected core pattern is mandatory:

```ts
export async function safeFetch<T>(path: string, init?: RequestInit & { next?: { revalidate: number } }): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`, init);
    if (!res.ok) return null;          // 4xx/5xx -> offline state, not a throw
    return (await res.json()) as T;
  } catch {
    return null;                        // ECONNREFUSED / DNS / timeout
  }
}
```

**Reusable from the scratch analog** — env base, typed models, mutation shape:

```ts
const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export class ApiError extends Error { constructor(readonly status: number, message: string) { super(message); } }
export async function pauseWatch(id: number, token: string): Promise<void> {
  const res = await fetch(`${API}/watches/${id}`, {
    method: "PATCH", headers: { "content-type": "application/json", authorization: `Bearer ${token}` },
    body: JSON.stringify({ status: "paused" }),
  });
  if (!res.ok) throw new ApiError(res.status, "pause failed");
}
```

Mutations (client islands) *may* throw — the Toast rollback (UI-SPEC #5, D-115) consumes it.
Reads called from server components go through `safeFetch` and **never** throw. Grep gate: no
bare `await fetch(` outside `src/lib/api.ts`. Never set `revalidate` and `cache` on one call.

---

### `web/src/lib/feed.ts` (store, pure reducer)

**Analog:** `SCRATCH/web/src/lib/feed.ts` — copy verbatim (dedupe by `event_id`, bounded `seen`
list, queue + `tick` drain that gives the 1 event/s cap without a timer in the reducer):

```ts
export function feedReducer(s: FeedState, a: FeedAction): FeedState {
  switch (a.type) {
    case "received":
      if (s.seen.includes(a.event.event_id)) return s;
      return { ...s, queue: [...s.queue, a.event], seen: [a.event.event_id, ...s.seen].slice(0, 200) };
    case "tick": {
      if (s.queue.length === 0) return s;
      const [next, ...rest] = s.queue;
      return { ...s, queue: rest, shown: [next, ...s.shown].slice(0, MAX_SHOWN) };
    }
  }
}
```

The timer lives in the `LiveFeed` client island, which also owns the `EventSource`, the
"Reconnecting…" state after 3 consecutive `onerror`s (D-112a — **no client-side backoff**; the
server's `retry:` frame owns it) and the WCAG 2.2.2 "Pause updates" toggle (UI-SPEC A-6).

---

### `web/src/components/Heatmap.tsx` (component, server-rendered)

**Analog:** `SCRATCH/web/src/components/Heatmap.tsx` for the data contract, the pure bucket
function and the per-cell `aria-label` (executed RTL + axe test, 168 labelled cells) — **but the
UI-SPEC (#6) supersedes its `<table>` markup with SVG.** Keep from the analog:

```ts
const DAYS = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"];   // 0=Sun matches persistence.day_of_week
export interface Cell { count: number; sparse: boolean }
export function scaleClass(count: number, max: number, sparse: boolean): string {
  if (sparse) return "bg-neutral-200";
  const r = max === 0 ? 0 : count / max;
  ...
}
  aria-label={`${DAYS[d]} ${h}:00 — ${c.sparse ? "fewer than 10 observations" : `${c.count} openings`}`}
```

Replace with the UI-SPEC contract: signature `({ cells, max, days, hours, windowDays, sample? })`,
`viewBox="0 0 466 144"`, pure `bucket(count, max) → 1..5` against the 5-step ramp
(UI-SPEC `## Heatmap Color Scale`), sparse = gray fill **plus** a single shared
`<pattern id="sparse-hatch">` in `<defs>` (A-4), `<title>` per `<g tabindex="-1">` for the
CSS-only tooltip (A-8), numeric legend ranges, and `max` taken from the API payload, never
recomputed (D-107).

---

### `web/src/components/**` primitives and domain components

**Analog:** UI-SPEC `## Component Inventory` #1–#12 is the contract (variants, sizes, states,
a11y wiring) and `## Copywriting Contract` supplies every string. Repo-wide constraints to carry
into each file: real `<button>`/`<a>` never a clickable `<div>`; every interactive element
≥ 44 px (`min-h-11 min-w-11`) except heatmap cells (A-5 WCAG 2.5.8 "Essential" exemption);
`:focus-visible` 2px `--ring` at 2px offset; error slot always in the DOM; no color-only state.
Tokens are consumed as Tailwind utilities mapped from `globals.css` via `@theme inline`
(plain `@theme` drops the dark-mode override — UI-SPEC `## Design System`).

---

### `web/src/components/*.test.tsx`, `web/src/lib/*.test.ts` (tests)

**Analogs:** `SCRATCH/web/src/components/Heatmap.test.tsx` (RTL + direct `axe-core`) and
`SCRATCH/web/src/lib/feed.test.ts` (pure reducer + fake timers). Both executed green.

**axe pattern — call `axe.run` directly, no `vitest-axe`/`jest-axe`** (D-118 a11y gate):

```tsx
  it("has no axe violations", async () => {
    const { container } = render(<Heatmap cells={grid} max={20} />);
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
```

**Fake-timer rate-cap pattern**:

```ts
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());
    vi.advanceTimersByTime(1000); expect(s.shown).toHaveLength(1);
```

**Mocking (D-118a — no MSW):** `vi.stubGlobal("fetch", …)` with typed fixtures under
`src/test/fixtures/`. The repo analog for typed factories is `tests/unit/factories.py`.

---

### `web/scripts/lighthouse.mjs` (script)

**Analog:** `SCRATCH/web/scripts/lighthouse.mjs` — copy verbatim; it executed with LCP 1810 ms,
perf 100, a11y 100 and both exit paths proven. The `chrome-headless-shell` path is load-bearing
(the full Chrome for Testing build returns `NO_FCP`):

```js
const CHROME_PATH =
  process.env.LH_CHROME_PATH ??
  `${process.env.HOME}/Library/Caches/ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-mac-arm64/chrome-headless-shell`;
...
  if (lcp > BUDGET_MS) { console.error(`FAIL: LCP ${lcp} ms > ${BUDGET_MS} ms`); process.exitCode = 1; }
```

Delta from D-111a: run 5 times and gate on the **median**, not a single run.

---

### `Makefile` (modified)

**Analog:** the existing file. Copy the `.PHONY` + `## comment` convention exactly — `make help`
parses `^[a-zA-Z0-9_-]+:.*?## .*$` (`Makefile:59-60`):

```make
.PHONY: up down migrate seed poll state-machine replay test test-integration lint fmt smoke verify-seed verify-perf02 help topics

migrate: ## Run Alembic migrations
	uv run alembic upgrade head
```

New targets must be added to `.PHONY` **and** carry a `##` doc comment, or they vanish from
`make help`: `web-install` (`cd web && npm ci` — BC-9: the flag is only for the one-time
scaffold install, never in this target), `web-dev`, `web-build`, `web-build-offline`
(`NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:1 npm run build`, D-110a), `web-test`, `lighthouse`.

Where a target encodes a non-obvious constraint, the existing file writes a multi-line comment
above it (see the `test:` target's `-W error::RuntimeWarning` rationale, `Makefile:29-37`) —
do the same for `web-build-offline` and the no-turbopack rule.

---

### `.env.example` (modified)

**Analog:** the existing file — grouped `# Section` headers, and long comments explaining *why*
a value is not configurable (see the "the confirmation window is NOT an environment variable"
block). Add a `# Frontend (web/)` section documenting `NEXT_PUBLIC_API_BASE_URL`,
`NEXT_PUBLIC_SITE_URL`, `NEXT_PUBLIC_VAPID_PUBLIC_KEY`, and — with a BC-10 comment — that
`NEXT_PUBLIC_*` is **inlined at build time**, so changing it on Vercel needs a redeploy, not a
restart. Also amend `PUBLIC_BASE_URL` (Phase 4 D-83) to state that it is now the **web** origin.

---

## Shared Patterns

### Module docstring with `Named symbols:` (all backend files)
**Source:** `services/state_machine/engine.py:1-9`, `shared/redis_keys.py:1-21`,
`tests/integration/conftest.py:1-11`
**Apply to:** every new `.py` file in this phase.
Docstring states purpose, cites decision ids (`D-105`, `PATTERN-01`), records any research
correction it encodes, and ends with a `Named symbols:` line listing the public API.

### `safe_error`, never `str(exc)` (backend logging)
**Source:** `services/state_machine/persistence.py:110-124`; enforced by
`tests/unit/test_safe_error.py` and `tests/unit/test_logs_never_carry_payload.py`
**Apply to:** `shared/pattern/repo.py`, `shared/pattern/service.py`, `pattern_hook.py`
```python
from shared.telemetry import get_logger, safe_error
log = get_logger(__name__)
        log.error("availability_event_insert_failed", event_id=str(event.event_id), error=safe_error(exc))
```

### All Redis keys/TTLs/casts in `shared/redis_keys.py`
**Source:** `services/state_machine/store.py:9-11`, `shared/redis_keys.py:522-529`
**Apply to:** `shared/pattern/service.py`
Single-command `set_str_ex`; no `SET`+`EXPIRE` pair (grep-gated).

### Lazy environment reads
**Source:** `services/state_machine/config.py:7-14`
**Apply to:** any new config surface (`PATTERN_MIN_EVENTS`, cache TTL overrides)
Env reads are functions called at runtime, not module constants evaluated at import.

### Weekday convention 0=Sun, two distinct axes
**Source:** `services/state_machine/persistence.py:53-55`;
`migrations/versions/0008_…py:69-79` column comment
**Apply to:** migration 0011, `model.py`, `repo.py`, `Heatmap.tsx`, `format.ts`
`day_of_week` = service night (heatmap y). `dow_local` = observation weekday (load-day rule).
Migration 0006's `# 0=Mon..6=Sun` comment is stale and superseded by 0008 (B-5).

### Hypertable predicates always name `"time"`
**Source:** `services/state_machine/persistence.py:1-9` (module docstring) and the B-2/B-3
comments in `0008_…py:56-67`
**Apply to:** `shared/pattern/repo.py`, the CAGG query, both integration tests.

### `safeFetch` never throws (all frontend server components)
**Source:** RESEARCH BC-2 (executed prerender failure + the passing `rv-caught` fix)
**Apply to:** every read in `web/src/lib/api.ts` and every server component
Grep gate: no bare `await fetch(` outside `src/lib/api.ts`. `make web-build-offline` is the proof.

### No `--turbopack`, anywhere
**Source:** RESEARCH BC-1 (turbopack build exits 0 and emits no `sw.js`)
**Apply to:** `web/package.json`, docs, CI
Grep gate: `! grep -rn -- "--turbopack" web/package.json`.

### 44 px targets, visible focus, no color-only state
**Source:** UI-SPEC `## Accessibility Contract` + `## Component Inventory`
**Apply to:** every component under `web/src/components/`
Only documented exception: heatmap cells (A-5).

### Direct `axe-core` per page shell
**Source:** `SCRATCH/web/src/components/Heatmap.test.tsx`
**Apply to:** every page-shell test (D-118)

---

## No Analog Found

| File | Role | Data Flow | Reason / defining decision |
|------|------|-----------|----------------------------|
| `services/api/routers/restaurants.py` (modify) | route | request-response | Router is created by **Phase 5 D-100**, not yet executed. No FastAPI router exists anywhere on disk. Planner: hard dependency on Phase 5. |
| `services/api/routers/links.py` (modify) | route | request-response | Created by **Phase 4 D-84**. JSON mode per **D-116**. |
| `services/api/sse.py` (modify) | service | streaming | `FeedHub` created by **Phase 5 D-98**; `retry:` frame per **D-112a**. Only proof material exists (`SCRATCH/sse/test_sse.py`). |
| `services/notifier/pattern_hook.py` (implement) | utility | request-response | Stub created by **Phase 4 D-81** (returns `None`); implemented per **D-108**. |
| `web/src/lib/preview.ts` | utility | transform | Must mirror `services/notifier/templates.py` (**Phase 4 D-81**, `string.Template`), which does not exist. Parity test needs a checked-in JSON of backend-rendered samples produced at execution time. |
| `web/src/app/manage/t/[token]/page.tsx` | page | CRUD | No frontend precedent and the API shape (`GET /api/manage/{token}`, `PATCH/DELETE /watches/{id}`) is **Phase 5 D-100/D-115** and `[ASSUMED]` until Phase 5 executes. Build against the Phase 5 OpenAPI snapshot + `docs/api.md`. |
| `web/src/app/go/[token]/page.tsx` | page | request-response | Depends on the Phase 4 route's new JSON mode; no analog and an unresolved rendering conflict (below). |

---

## Conflicts the Planner Must Resolve

1. **`/go/[token]` rendering.** UI-SPEC `## Page Layout Contracts` says *"Client island (must
   fetch with `Accept: application/json` and then redirect) … whole page"*, while **D-116a**
   says *"fetches the API JSON server-side (RSC) … a tiny client island performs the delayed
   `window.location.replace`."* D-116a is the later, research-informed amendment and avoids a
   cross-origin CORS preflight on a latency-critical path; recommend following D-116a and
   treating the UI-SPEC row as superseded. The UI-SPEC's *loading* state ("Checking that
   table…" + spinner as the default first paint) then only applies to the client island.
2. **`msw`.** D-109/RESEARCH stack list it; **D-118a** removes it (`vi.stubGlobal`). D-118a
   wins — drop `msw` from `SCRATCH/web/package.json` when copying, which also removes the
   `checkpoint:human-verify` the package-legitimacy audit would otherwise require.
3. **`images.remotePatterns`.** The scratch `next.config.ts` hardcodes `resizer.otstatic.com`
   and `image-resizer-cdn.eanalytics.io`; the seed file on disk today yields
   `placeholder.mise.place`, `www.opentable.com`, `resy.com`, `ny.eater.com`,
   `www.theinfatuation.com`. Per **D-109b**, regenerate from `scripts/seed/restaurants.yml`
   `cover_photo_url` values at execution time.
4. **Migration number.** `0011` assumes Phase 4 and Phase 5 each ship one migration
   (0009, 0010). Neither exists. The plan must read `migrations/versions/` and set
   `down_revision` to the actual head.

---

## Metadata

**Analog search scope:** `migrations/versions/`, `shared/`, `services/state_machine/`,
`services/poller/`, `tests/unit/`, `tests/integration/`, `Makefile`, `.env.example`,
`scripts/seed/`, and the executed research scratch at
`.../scratchpad/research-06/{web,sse,alembictest}/`
**Files scanned:** 61 (33 read in whole or in targeted part)
**Pattern extraction date:** 2026-09-05
