---
phase: 06-pattern-intelligence-frontend-pwa
plan: 02
type: execute
wave: 2
depends_on: ["06-01"]
files_modified:
  - migrations/versions/00NN_availability_events_hourly_cagg.py
  - shared/redis_keys.py
  - shared/pattern/repo.py
  - shared/pattern/service.py
  - shared/pattern/config.py
  - tests/unit/test_redis_keys_phase6.py
  - tests/unit/test_heatmap_densify.py
  - tests/integration/test_cagg_availability_events_hourly.py
  - tests/integration/test_pattern_quartiles_match_sql.py
  - tests/integration/test_pattern_service_cache.py
autonomous: true
requirements: [PATTERN-01, PATTERN-02]

estimate:
  tokens: 88000
  raw_tokens: 88000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Migration NNNN creates the continuous aggregate `availability_events_hourly` with `timescaledb.materialized_only = false` set EXPLICITLY (real-time aggregation is off by default in 2.17.2 — BC-6) and a 15-minute refresh policy over a 30-day start offset and a 1-hour end offset (D-105, D-105a)."
    - "`CREATE MATERIALIZED VIEW ... WITH NO DATA` and `add_continuous_aggregate_policy` run inside the ordinary migration transaction; `CALL refresh_continuous_aggregate(...)` is the ONE statement wrapped in `op.get_context().autocommit_block()` (BC-5, D-105a)."
    - "The CAGG carries `dow_local` (observation weekday, `EXTRACT(dow FROM \"time\" AT TIME ZONE 'America/New_York')`) AND `day_of_week` (service weekday) as separate columns; the heatmap y-axis reads `day_of_week` and the inventory-load-day rule reads `dow_local` (BC-11, D-105a)."
    - "The CAGG stores `duration_sum` and `duration_n`, never `avg` and never `percentile_cont` — per-bucket averages and percentiles are not re-aggregable across a 30-day window (D-105a)."
    - "`upgrade` then `downgrade` then `upgrade` all exit 0 against `timescale/timescaledb:2.17.2-pg16`, and `downgrade` drops the materialized view."
    - "PATTERN-02 precision probe: `shared.pattern.stats.quartiles` over a seeded set of `duration_seconds` equals PostgreSQL `percentile_cont(0.25|0.5|0.75)` over the same rows to within 1e-9 (D-106a cross-check)."
    - "PATTERN-02 adjacency probe: a heatmap cell with exactly 10 observations is NOT `sparse`; a cell with exactly 9 IS `sparse` — the boundary is `count < observations_threshold` with the threshold at 10 (D-107)."
    - "PATTERN-02 empty probe: a restaurant with zero events yields a heatmap payload of exactly 168 cells, every one `count == 0` and `sparse == true`, with `max == 0` — never a short grid and never a division by zero (D-107)."
    - "The heatmap payload is `{days: 7, hours: 24, cells, observations_threshold: 10, window_days: 30, max}` with `cells` densified to 7x24 in Python and each cell carrying its server-computed `sparse` flag, so the frontend can never forget the rule (D-107, RESEARCH Pitfall 7)."
    - "`get_pattern(slug)` and `get_heatmap(slug)` merge every source row of the slug (a restaurant may have both an OpenTable and a Resy row) and cache the JSON in Redis under `pattern:{slug}` / `heatmap:{slug}` with a 600 s TTL written by a single `SET ... EX` command (D-107)."
    - "Every hypertable predicate names `\"time\"` so the planner produces a single-chunk index scan rather than a full 30-day scan (repo-wide rule from migration 0008 B-2/B-3)."
    - "`get_pattern(slug)` is the single source of `pattern_status` — the restaurant route in 06-03 reads it from the same cached value rather than recomputing, so the two can never disagree (RESEARCH Pitfall 8)."
  artifacts:
    - migrations/versions/00NN_availability_events_hourly_cagg.py
    - shared/pattern/repo.py
    - shared/pattern/service.py
    - shared/pattern/config.py
    - tests/unit/test_redis_keys_phase6.py
    - tests/unit/test_heatmap_densify.py
    - tests/integration/test_cagg_availability_events_hourly.py
    - tests/integration/test_pattern_quartiles_match_sql.py
    - tests/integration/test_pattern_service_cache.py
  key_links:
    - "`availability_events.restaurant_id` is the SOURCE PLATFORM id (D-52), not `restaurants.id`; the slug -> sources join is on `(source, platform_id)` and every repo query filters on both."
    - "`shared/redis_keys.py` gains `pattern_cache_key`, `heatmap_cache_key` and `PATTERN_CACHE_TTL_SECONDS`; `shared/pattern/service.py` contains no key string and no redis-py cast of its own."
    - "The migration's `down_revision` is the Alembic head recorded by plan 06-01's `current_migration_head()`, resolved at execution time — never hardcoded to `0010`."
    - "`heatmap_cells()` reads the CAGG; `load_observations()` reads the raw `availability_events` hypertable so the duration quartiles stay exact (D-105)."
  prohibitions:
    - "The heatmap never reports a cell as non-sparse below the 10-observation threshold, and `sparse` is computed server-side only — no client-side re-derivation path exists."
    - "The CAGG definition contains no `avg(` and no `percentile_cont(` (grep over the migration source with full-line comments stripped)."
    - "No two-command `SET` + `EXPIRE` claim: the cache write uses `shared.redis_keys.set_str_ex` and `tests/unit/test_no_setnx_expire_pairs.py` stays green."
    - "No `str(exc)` in any log call in `shared/pattern/repo.py` or `shared/pattern/service.py` — `safe_error(exc)` only, per the repo-wide gate."
    - "No key string and no TTL literal appears in `shared/pattern/service.py`; both live in `shared/redis_keys.py`."
    - "No environment variable is read as a module constant — every config read in `shared/pattern/config.py` is a function called at runtime (Phase 2 import-time-freeze lesson)."
---

<objective>
Materialise the hourly rollup the heatmap reads, and put a cached, source-merging read layer in front of the pure
kernel from 06-01.

Purpose: PATTERN-01's quartiles must be exact (raw hypertable) while the 168-cell heatmap must be cheap (continuous
aggregate). This plan builds both paths, the Redis cache-aside that keeps a page view off the database, and the
server-side `sparse` flag that makes over-claiming structurally impossible.

Output: migration `NNNN`, `shared/pattern/{repo,service,config}.py`, three `shared/redis_keys.py` additions, two unit
test modules and three integration test modules.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md
@.planning/phases/06-pattern-intelligence-frontend-pwa/06-01-SUMMARY.md
@CLAUDE.md
</context>

## Artifacts this phase produces (this plan's share)

| Kind | Artifact | Notes |
|------|----------|-------|
| migration | `migrations/versions/00NN_availability_events_hourly_cagg.py` | `down_revision` resolved at execution time |
| DB view | `availability_events_hourly` | continuous aggregate, real-time enabled |
| DB policy | `add_continuous_aggregate_policy('availability_events_hourly', ...)` | 15-minute schedule |
| lib function | `shared.pattern.repo.load_observations(session, sources, since) -> list[EventObs]` | raw hypertable, exact quartiles |
| lib function | `shared.pattern.repo.heatmap_cells(session, sources, window_days=30) -> list[tuple[int, int, int]]` | CAGG, `(day_of_week, hour_local, n)` |
| lib function | `shared.pattern.service.get_pattern(slug) -> PatternReport` | Redis cache-aside |
| lib function | `shared.pattern.service.get_heatmap(slug) -> HeatmapPayload` | Redis cache-aside |
| lib function | `shared.pattern.service.densify(rows, threshold) -> HeatmapPayload` | pure 7x24 densifier |
| redis keys | `shared.redis_keys.pattern_cache_key(slug)`, `heatmap_cache_key(slug)`, `PATTERN_CACHE_TTL_SECONDS` | 600 s |
| config fns | `shared.pattern.config.pattern_min_events()`, `pattern_cache_ttl_seconds()` | lazy env reads |

<tasks>

<task type="tracer">
  <name>Task 1: Tracer — the continuous aggregate, refreshed and queried end to end on a live database</name>
  <files>migrations/versions/00NN_availability_events_hourly_cagg.py, tests/integration/test_cagg_availability_events_hourly.py</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md` → "`migrations/versions/0011_availability_events_hourly_cagg.py`" — the verbatim CAGG DDL, the header/revision-globals idiom, the doubled-`%%` COMMENT ON COLUMN pattern
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Architecture Patterns → Pattern 1 and Pattern 2, and §Blocking Corrections BC-5, BC-6, BC-11
    - `/private/tmp/claude-501/-Users-aryanahuja-employment/6e0b7e8c-ed74-4891-9c51-2883d43c7173/scratchpad/research-06/alembictest/migrations/versions/0002_cagg.py` — the executed migration that ran upgrade/downgrade/upgrade green against the pinned image
    - `migrations/versions/0008_add_event_id_to_availability_events.py` — repo migration header, revision globals, COMMENT ON COLUMN
    - `tests/integration/test_migration_0008.py` and `tests/integration/conftest.py` — `pytestmark`, the module-scoped `apply_migrations` fixture, `db_urls` (`sync`/`async`/`dsn`), and the raw-asyncpg try/finally idiom
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-01-SUMMARY.md` — the resolved Alembic head to use as `down_revision`
  </read_first>
  <action>
Resolve the revision number first: run `uv run alembic heads` (or call `current_migration_head()` from
`tests/unit/test_phase6_preconditions.py`) and name the new file `00NN_availability_events_hourly_cagg.py` where
`NN` is the next free integer after the head. Set `down_revision` to that head verbatim. Do not assume `0010`.

Write the migration with a docstring naming D-105, D-105a and the three corrections it encodes (BC-5, BC-6, BC-11),
then the bare module-level `revision` / `down_revision` / `branch_labels` / `depends_on` globals in the 0008 shape.

`upgrade()` executes, in this order and in the ordinary transaction: the `CREATE MATERIALIZED VIEW
availability_events_hourly WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS SELECT ... WITH NO
DATA` statement exactly as the PATTERNS file gives it — `time_bucket('1 hour', "time") AS bucket`, `restaurant_id`,
`source`, `day_of_week`, `EXTRACT(dow FROM "time" AT TIME ZONE 'America/New_York')::int AS dow_local`, `EXTRACT(hour
FROM "time" AT TIME ZONE 'America/New_York')::int AS hour_local`, `count(*) AS events`, `sum(duration_seconds)::bigint
AS duration_sum`, `count(duration_seconds) AS duration_n`, `min("time") AS first_event`, `max("time") AS last_event`,
grouped by every non-aggregate column; then `add_continuous_aggregate_policy` with a 30-day `start_offset`, a 1-hour
`end_offset`, a 15-minute `schedule_interval` and `if_not_exists => TRUE`. Only after those, open
`op.get_context().autocommit_block()` and issue the single `CALL refresh_continuous_aggregate('availability_events_hourly',
NULL, NULL)`.

Add a `COMMENT ON COLUMN` (or view comment) recording that `day_of_week` is the SERVICE weekday and `dow_local` is
the OBSERVATION weekday, both 0=Sun, and that the heatmap y-axis uses the former while the inventory-load-day rule
uses the latter. Remember the doubled `%%` if a percent sign appears — alembic format-steps the string.

`downgrade()` drops the materialized view with `IF EXISTS`. It is additive DDL, so no row guard is needed, but keep
the 0008 "refuse loudly rather than silently destroy" tone in the docstring.

Write `tests/integration/test_cagg_availability_events_hourly.py` with `pytestmark = pytest.mark.integration` and the
module-scoped `apply_migrations` fixture from `tests/integration/conftest.py`. Assert: the view exists in
`timescaledb_information.continuous_aggregates`; its `materialized_only` is `false`; exactly one refresh policy job
exists for it; the view's column list contains both `day_of_week` and `dow_local` and contains neither an `avg` nor a
`percentile_cont` derived column. Then seed a deterministic set of `availability_events` rows across several
`(day_of_week, hour_local)` buckets, issue `CALL refresh_continuous_aggregate(...)` on a connection with
`execution_options(isolation_level="AUTOCOMMIT")` (a plain connection raises
`ActiveSQLTransactionError` — RESEARCH Pattern 2), and assert the materialised rows sum to the seeded counts. Finally
assert that a `downgrade` to the previous revision drops the view and a re-`upgrade` recreates it.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_cagg_availability_events_hourly.py -x -q -p no:cacheprovider` exits 0.
    - `grep -v '^\s*#' migrations/versions/*_availability_events_hourly_cagg.py | grep -c 'materialized_only = false'` is at least 1.
    - `grep -v '^\s*#' migrations/versions/*_availability_events_hourly_cagg.py | grep -cE 'avg\(|percentile_cont\('` equals 0.
    - `grep -v '^\s*#' migrations/versions/*_availability_events_hourly_cagg.py | grep -c 'autocommit_block'` equals 1.
    - `grep -v '^\s*#' migrations/versions/*_availability_events_hourly_cagg.py | grep -c 'dow_local'` is at least 2.
    - `uv run alembic upgrade head` then `uv run alembic downgrade -1` then `uv run alembic upgrade head` all exit 0 against a running `make up` stack.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/integration/test_cagg_availability_events_hourly.py -x -q -p no:cacheprovider</automated>
  </verify>
  <done>The continuous aggregate exists with real-time aggregation on, both weekday axes, re-aggregable duration columns, and a proven upgrade/downgrade/upgrade cycle.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Read layer — repo queries, Redis key registry and the pure heatmap densifier</name>
  <files>shared/pattern/repo.py, shared/pattern/config.py, shared/redis_keys.py, tests/unit/test_redis_keys_phase6.py, tests/unit/test_heatmap_densify.py</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-107 (function signatures, cache keys, TTL, payload shape, sparse flag)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Architecture Patterns → Pattern 3 (`HEATMAP_SQL` and its captured EXPLAIN, and the "densify in Python, not with generate_series" rule)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md` → "`shared/pattern/repo.py`" and "`shared/pattern/service.py`" — the persistence.py import/session/error idioms and the redis_keys section style
    - `services/state_machine/persistence.py` — session-factory usage, `safe_error` logging, the `"time"` predicate rule
    - `shared/redis_keys.py` (lines 1-30 for the `Named symbols:` header, lines 55-80 for a section, lines 515-535 for `set_str_ex`)
    - `shared/db.py` (lines 110-145) — the `AvailabilityEvent` column set and the D-52 note that `restaurant_id` is the source platform id
    - `services/state_machine/config.py` (lines 1-20) — the lazy-env rule
  </read_first>
  <behavior>
    - `densify([], threshold=10)` returns 7 rows of 24 cells, every cell `{count: 0, sparse: true}`, `max == 0`.
    - `densify` marks a cell with count 9 as `sparse` and a cell with count 10 as not `sparse` (the boundary is `count < threshold`).
    - `densify` returns `max` as the largest observed count, and cells are indexed `cells[day][hour]` with day 0 = Sunday and hour 0 = midnight local.
    - `densify` ignores nothing: a row for `(day=6, hour=23)` lands at `cells[6][23]`.
    - `pattern_cache_key("carbone")` returns `pattern:carbone` and `heatmap_cache_key("carbone")` returns `heatmap:carbone`; `PATTERN_CACHE_TTL_SECONDS == 600`.
  </behavior>
  <action>
`shared/pattern/config.py`: lazy environment reads only — `pattern_min_events()` defaulting to 30 and
`pattern_cache_ttl_seconds()` defaulting to `shared.redis_keys.PATTERN_CACHE_TTL_SECONDS`. Each is a FUNCTION, not a
module constant, with the docstring stating why (a module constant freezes the value at import time and pins any
integration test that imports this module to the process defaults — the 02-02 lesson).

`shared/redis_keys.py`: add a new `# -- Pattern intelligence (D-107, PATTERN-01/02) --` section in the existing
section style with `PATTERN_CACHE_TTL_SECONDS: int = 600`, `pattern_cache_key(slug) -> str` and
`heatmap_cache_key(slug) -> str`, each with a one-line docstring citing D-107. Extend the module docstring's
`Named symbols:` list with the three new names. Add nothing else to this file.

`shared/pattern/repo.py`: module docstring in the persistence.py shape (purpose, D-107, the `"time"` predicate rule,
`Named symbols:`). Import `safe_error` and `get_logger` from `shared.telemetry`. Two async functions, each taking an
open `AsyncSession` as its first parameter so the caller owns the session lifetime:

`load_observations(session, sources, since)` reads the RAW `availability_events` hypertable — filtering `"time" >=
:since` FIRST so the planner gets a single-chunk index scan, then `(source, restaurant_id)` against the caller's list
of `(source, platform_id)` pairs — and returns a list of `EventObs` built from `first_seen_at`,
`hours_before_service`, `day_of_week`, `duration_seconds`, plus `hour_local` and `dow_local` derived in SQL with
`EXTRACT(... FROM "time" AT TIME ZONE 'America/New_York')::int` so Python and the CAGG agree exactly. Quartiles must
stay exact, which is why this reads raw rows and not the aggregate (D-105).

`heatmap_cells(session, sources, window_days=30)` reads the CAGG with the RESEARCH Pattern 3 statement —
`SELECT day_of_week, hour_local, sum(events)::int AS n FROM availability_events_hourly WHERE bucket >= now() -
make_interval(days => :window_days) AND (source, restaurant_id) IN ... GROUP BY day_of_week, hour_local ORDER BY
day_of_week, hour_local` — and returns the raw `(day_of_week, hour_local, n)` triples. Do NOT densify in SQL.

Add a pure module-level `densify(rows, threshold, days=7, hours=24, window_days=30)` to `shared/pattern/service.py`
(it is pure and testable without Redis or a database; declaring it here keeps the payload shape beside its consumer)
returning the D-107 payload: `days`, `hours`, `cells` as a `days x hours` list of `{count, sparse}` mappings,
`observations_threshold`, `window_days` and `max`. `sparse` is `count < threshold`. Guard the `max == 0` case so no
division occurs anywhere in this function.

Every log call in this file passes the exception through `safe_error(...)`; the raw exception string is never
interpolated into a log line (the repo-wide gate greps for it).

Tests: `tests/unit/test_redis_keys_phase6.py` pins the two key strings and the TTL constant (mirroring
`tests/unit/test_redis_keys_phase2.py`). `tests/unit/test_heatmap_densify.py` asserts every item in the
`<behavior>` block, including the empty-input 168-cell case and the 9-vs-10 boundary.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_redis_keys_phase6.py tests/unit/test_heatmap_densify.py -x -q` exits 0.
    - `uv run pytest tests/unit/test_no_setnx_expire_pairs.py tests/unit/test_safe_error.py -x -q` exits 0.
    - `grep -v '^\s*#' shared/pattern/repo.py | grep -c '"time" >='` is at least 1.
    - `grep -v '^\s*#' shared/pattern/repo.py shared/pattern/service.py | grep -c 'str(exc)'` equals 0.
    - `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_redis_keys_phase6.py tests/unit/test_heatmap_densify.py -x -q</automated>
  </verify>
  <done>Both reads are written against the right storage tier, the keys live in the one registry, and the 7x24 densifier is pinned at its empty case and its sparse boundary.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Cached pattern service, slug-to-sources merge and the SQL quartile cross-check</name>
  <files>shared/pattern/service.py, tests/integration/test_pattern_service_cache.py, tests/integration/test_pattern_quartiles_match_sql.py</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-107 (cache-aside, TTL, source merge), D-108 (`pattern_status` single source of truth)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Common Pitfalls → Pitfall 8 (`pattern_status` and the pattern card disagreeing) and §Code Examples → "Quartiles"
    - `.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md` — D-100 (the merged logical restaurant: one object with a `sources` list), D-95b (`restaurant_id` is the platform id)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-PATTERNS.md` → "`shared/pattern/service.py`" — `set_str_ex`, the defensive `_text` decode, redis client acquisition from a lazy config function
    - `services/state_machine/store.py` (lines 1-50) — the "every key string comes from shared.redis_keys" rule and `_text`
    - `shared/pattern/model.py` and `shared/pattern/repo.py` as written in 06-01 and Task 2
  </read_first>
  <behavior>
    - `get_pattern(slug)` on a cache miss reads the raw hypertable, calls `compute_pattern`, writes the JSON to `pattern:{slug}` with a 600 s TTL in one command, and returns the report; a second call within the TTL performs no database query.
    - `get_heatmap(slug)` behaves identically against `heatmap:{slug}` and always returns exactly 168 cells.
    - A slug with two source rows (one OpenTable, one Resy) produces one merged report whose `n_events` is the sum across both sources.
    - A slug with no matching restaurant row raises a typed `PatternNotFound` (or returns `None` per the chosen signature) rather than an unhandled exception, and does not write a cache entry.
    - A Redis failure on the read path is logged with `safe_error` and falls through to a live computation — a cache outage degrades latency, never correctness.
    - `shared.pattern.stats.quartiles` over the seeded `duration_seconds` equals PostgreSQL `percentile_cont(0.25|0.5|0.75) WITHIN GROUP (ORDER BY duration_seconds)` over the same rows to within 1e-9.
  </behavior>
  <action>
Complete `shared/pattern/service.py`: module docstring citing D-107, D-108 and RESEARCH Pitfall 8, ending with a
`Named symbols:` line that includes `densify`, `get_pattern`, `get_heatmap` and the not-found error type.

Resolve slug to sources by querying `restaurants` for every row whose `slug` matches, collecting `(source,
platform_id)` pairs — the join key against `availability_events` is `(source, platform_id)`, never `restaurants.id`
(D-52). An empty result is the not-found path.

`get_pattern(slug)`: read `pattern_cache_key(slug)` from Redis, decode defensively (`redis.from_url` does not decode
by default), and on a hit deserialise straight to the `PatternReport` shape. On a miss, open a session from
`get_async_session()`, call `repo.load_observations(session, sources, since=now - window_days)`, call
`compute_pattern(events, now, cfg)` with `cfg` built from `shared/pattern/config.py`, serialise to JSON and write with
`shared.redis_keys.set_str_ex(r, key, value, PATTERN_CACHE_TTL_SECONDS)` — one command, never `SET` then `EXPIRE`.
`get_heatmap(slug)` is the same shape over `repo.heatmap_cells` piped through `densify`.

Expose `pattern_status(slug)` as a thin accessor that returns `get_pattern(slug).status` from the SAME cached value.
Add a comment recording why: two independently-TTL'd caches with a time-dependent gate will disagree at the boundary
and render a card with no content (RESEARCH Pitfall 8). 06-03's restaurant route calls this, not a second
computation.

Wrap the Redis read in a try/except that logs with `safe_error(exc)` and continues to the live path. Never let a
cache failure surface to the caller.

`tests/integration/test_pattern_service_cache.py` (`pytestmark = pytest.mark.integration`, containers from
`tests/integration/conftest.py`): seed two `restaurants` rows sharing one slug across two sources plus events on
each; assert the merged `n_events`; assert the second call issues no query (count queries with a SQLAlchemy event
listener or assert the cache key exists and the report is byte-equal); assert the key's TTL is at or below 600 and
above 0; assert the not-found path; assert a simulated Redis failure still returns a correct report.

`tests/integration/test_pattern_quartiles_match_sql.py`: seed a known spread of `duration_seconds`, compute
`quartiles(...)` in Python and `percentile_cont` in SQL over the same rows, and assert equality to 1e-9. This is the
PATTERN-02 precision probe and the reason D-106a chose the inclusive method.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_pattern_service_cache.py tests/integration/test_pattern_quartiles_match_sql.py -x -q -p no:cacheprovider` exits 0.
    - `grep -v '^\s*#' shared/pattern/service.py | grep -cE '"(pattern|heatmap):'` equals 0 (no inline key string).
    - `grep -v '^\s*#' shared/pattern/service.py | grep -c 'set_str_ex'` is at least 1.
    - `grep -v '^\s*#' shared/pattern/service.py | grep -ciE 'ttl[^=]*=[[:space:]]*[0-9]'` equals 0 (the TTL number lives only in `shared/redis_keys.py`).
    - `uv run pytest tests/unit -x -q -W error::RuntimeWarning` exits 0 and `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/integration/test_pattern_service_cache.py tests/integration/test_pattern_quartiles_match_sql.py -x -q -p no:cacheprovider</automated>
  </verify>
  <done>One cached, source-merging read layer serves both the pattern report and the 168-cell heatmap, and the Python quartiles are proven equal to the database's.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| scraped rows → materialized view | `availability_events` rows produced from third-party payloads are aggregated into a view the public heatmap reads |
| Redis cache → API response | cached JSON is returned to unauthenticated callers without recomputation |
| slug (user input) → SQL | the slug arrives from a public URL path segment |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-06-05 | Tampering | `slug` in `repo` / `service` queries | high | mitigate | Every query is a parameterised SQLAlchemy statement; the slug is bound, never interpolated. A grep in the acceptance criteria proves no f-string SQL in `repo.py` |
| T-06-06 | Information disclosure | cached JSON payloads | medium | mitigate | `pattern:{slug}` and `heatmap:{slug}` hold only aggregate counts and rendered prose — no booking token, no user id, no email. `EventObs` has no `booking_token` field, so one cannot leak through |
| T-06-07 | Denial of service | a CAGG query per page view | medium | mitigate | 600 s Redis cache-aside in front of both reads; the CAGG turns the 30-day aggregation into an indexed scan of the materialised hypertable (EXPLAIN captured in RESEARCH Pattern 3) |
| T-06-08 | Tampering | over-claiming heatmap cells | high | mitigate | `sparse` is computed server-side in `densify` at the 10-observation threshold and shipped in the payload; the frontend has no threshold of its own to forget (D-107, Pitfall 7) |
| T-06-09 | Denial of service | Redis outage | low | mitigate | Cache read failures are caught, logged with `safe_error`, and fall through to a live computation |
| T-06-SC | Tampering | python package installs | high | mitigate | This plan adds no dependency; the CAGG is DDL and the statistics are stdlib. Recorded in the SUMMARY |
</threat_model>

<verification>
- `uv run pytest tests/unit -x -q -W error::RuntimeWarning`
- `uv run pytest tests/integration -q -p no:cacheprovider`
- `uv run ruff check . && uv run mypy shared/ services/ scripts/`
- `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
</verification>

<success_criteria>
- `availability_events_hourly` exists with real-time aggregation explicitly enabled and one 15-minute refresh policy.
- Both weekday axes are present and documented; no `avg` or `percentile_cont` column exists in the view.
- The heatmap payload is always 7x24 with a server-computed `sparse` flag at the 10-observation boundary.
- `get_pattern` / `get_heatmap` merge every source row of a slug, cache for 600 s in one command, and survive a Redis outage.
- Python quartiles equal SQL `percentile_cont` to 1e-9.
</success_criteria>

<output>
Create `.planning/phases/06-pattern-intelligence-frontend-pwa/06-02-SUMMARY.md` when done.
Record the actual migration revision number chosen and its `down_revision`, so Phase 5's D-93b migration numbering
note can be reconciled.
</output>
