---
phase: 03-resy-playwright-fleet
plan: 03
type: execute
wave: 1
depends_on: []
files_modified:
  - services/poller/config.py
  - migrations/versions/0009_restaurant_slug_source_unique.py
  - scripts/seed/restaurants.yml
  - scripts/seed_restaurants.py
  - scripts/resolve_resy_venue_ids.py
  - .env.example
  - tests/unit/test_resy_config_lazy.py
  - tests/integration/test_migration_0009.py
  - tests/integration/test_seed_idempotency.py
autonomous: true
requirements: [POLL-05]

estimate:
  tokens: 56000
  raw_tokens: 56000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "`alembic upgrade head` on a fresh database reaches revision 0009, after which `restaurants` enforces `UNIQUE(slug, source)` and no longer enforces `UNIQUE(slug)` — one logical restaurant keeps the same human slug across two sources while `(source, platform_id)` stays the upsert and join key (D-63b, D-52)."
    - "Migration 0009 refuses to run rather than destroy data when the table already holds a duplicate `(slug, source)` pair, raising a message that names the offending rows and the remediation — copying the 0008 pre-flight guard idiom."
    - "`scripts/seed/restaurants.yml` carries `resy_url_slug` (the human URL slug, 31 populated) and `resy_venue_id` (integer or null, null for all 55 until a human resolves them); `uv run python -c` over the parsed YAML reports 55 entries, 0 non-integer `resy_venue_id` values, and 31 non-null `resy_url_slug` values (D-63a, research B-4)."
    - "`make seed` creates a `resy` row and enqueues `resy:{venue_id}` ONLY when the entry has a numeric `resy_venue_id` AND `RESY_ENABLED` is true; with the shipped YAML (all ids null) the seed produces exactly the same rows and the same `sched:polls` membership as before this plan."
    - "Every Resy setting in `services/poller/config.py` is read through a FUNCTION, never a module constant, so importing the poller during test collection cannot pin a later test to the localhost defaults (the 02-02 deviation); a source-scan unit test proves no new module-level `os.getenv` was added."
    - "`scripts/resolve_resy_venue_ids.py --dry-run` runs to completion with no credentials, reporting how many slugs remain unresolved and exiting non-zero, without making any network call."
    - statement: "The numeric Resy `venue_id` for each of the 31 Resy restaurants is unknown and the `GET /3/venue?url_slug=...` resolution endpoint is [ASSUMED] (research A4, D-63a); confirming both requires a human DevTools capture with a real `RESY_API_KEY`, documented as pending-human in `docs/runbooks/resy-cookie-capture.md`."
      verification: backstop
  artifacts:
    - migrations/versions/0009_restaurant_slug_source_unique.py
    - scripts/resolve_resy_venue_ids.py
    - tests/integration/test_migration_0009.py
    - tests/unit/test_resy_config_lazy.py
  key_links:
    - "`resy_enabled()` -> `scripts/seed_restaurants.py` -> `sched:polls` membership -> `poll_loop` dispatch (03-06) — the single switch that keeps an unconfigured deployment from ever launching Chromium (D-63)."
    - "`restaurants.resy_venue_id` (numeric) -> the `resy:{venue_id}` job descriptor -> `int(rid_str)` in `poll_loop` -> `AvailabilityRaw.restaurant_id: int` — a slug anywhere in that chain is an unrecoverable poison job (research B-4)."
    - "`UNIQUE(slug, source)` -> Phase 5/6 slug lookups now return one row per source; recorded in `services/poller/sources/resy/README.md` (03-05) so downstream phases do not assume a single row."
  prohibitions:
    - "MUST NOT seed a `restaurants` row, enqueue a poll job, or present as resolved any Resy venue id that is still a placeholder or a URL slug; an unresolved venue must be visibly absent from the queue rather than silently polled against a fabricated id."
---

<objective>
Make a Resy job representable at all: give `restaurants` a per-source unique slug, split the seed
file's overloaded `resy_venue_id` field into a human slug and a numeric id, and read every new Resy
setting lazily so no import can freeze the environment.

Purpose: research reproduced three separate hard failures from the current seed data — `int(slug)`
raises, `AvailabilityRaw.restaurant_id` rejects a string, and a second `restaurants` row collides on
`UNIQUE(slug)`. Until all three are fixed, no amount of Playwright work can produce a single poll.
Output: migration 0009, a corrected YAML schema, a two-row seed path gated on `RESY_ENABLED`, a
human-gated resolver script, and function-based Resy config.
</objective>

<execution_context>
@$HOME/.claude/gsd-core/workflows/execute-plan.md
@$HOME/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/03-resy-playwright-fleet/03-CONTEXT.md
@.planning/phases/03-resy-playwright-fleet/03-PATTERNS.md
</context>

<tasks>

<task type="tracer">
  <name>Task 1: End-to-end tracer — migration 0009 plus a two-source seed produces a Resy job</name>
  <files>migrations/versions/0009_restaurant_slug_source_unique.py, scripts/seed/restaurants.yml, scripts/seed_restaurants.py, tests/integration/test_migration_0009.py</files>
  <read_first>
    - migrations/versions/0008_add_event_id_to_availability_events.py in full (revision header, the pre-flight guard that refuses rather than deletes, the `create_index` + doubled-`%%` `COMMENT ON` idiom, the honest `downgrade()`)
    - migrations/versions/0003_create_restaurants.py lines 14-40 (the `unique=True` column AND the separate `ix_restaurants_slug` unique index — the constraint is declared twice and both must go)
    - scripts/seed_restaurants.py lines 53-137 (the `if/elif` source derivation that makes the Resy branch unreachable, the `ON CONFLICT (source, platform_id)` upsert, the ZSET enqueue)
    - scripts/seed/restaurants.yml lines 1-70 (the header schema comment block and the placeholder convention `opentable_rid: 900000001  # TODO(01-05 spike)`)
    - tests/integration/test_migration_0008.py (the migration-test template: container, `alembic upgrade`, introspection asserts)
    - tests/integration/conftest.py (`apply_migrations`, `db_urls`, `redis_url`, `reset_shared_db_singletons`)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-63, §D-63a, §D-63b
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §B-4, §B-5, §Open Questions Q3
  </read_first>
  <action>
Write `migrations/versions/0009_restaurant_slug_source_unique.py` with `revision = "0009"` and
`down_revision = "0008"`. Its docstring names D-63b and states plainly what defect it corrects: the
slug constraint was declared twice in 0003 (once as a column `unique=True`, once as the separate
`ix_restaurants_slug` unique index), so a second row for the same restaurant on a different source
was impossible. `upgrade()` runs a pre-flight guard first — count rows that would violate the new
composite constraint (`GROUP BY slug, source HAVING count(*) > 1`) and, if any exist, raise a
`RuntimeError` naming the count and the remediation, exactly as 0008 refuses rather than deletes.
Then drop `ix_restaurants_slug` and the `restaurants_slug_key` column constraint, and create
`uq_restaurants_slug_source` as a unique constraint over `(slug, source)`. Add a
`COMMENT ON CONSTRAINT`/`COMMENT ON COLUMN` line recording that `(source, platform_id)` remains the
upsert and join key (D-52) and that a slug now identifies a restaurant, not a row. Write an honest
`downgrade()` that states it will fail whenever two rows share a slug, because restoring
`UNIQUE(slug)` is only possible after one of them is deleted.

Edit `scripts/seed/restaurants.yml`: rename the existing string field `resy_venue_id` to
`resy_url_slug` on all 31 entries that carry it, and add `resy_venue_id: null  # TODO(03 spike):
numeric venue_id from Resy DevTools — see docs/runbooks/resy-cookie-capture.md` to those same
entries. Update the header schema comment block (which currently documents `resy_venue_id` as an
optional string) so the file is self-describing, and extend the PLACEHOLDER WARNING block with the
Resy resolution procedure. Do not invent numeric ids: D-63a requires null until a human resolves
them, and a fabricated id would produce a job that polls a real stranger's venue.

Rework the source-derivation block in `scripts/seed_restaurants.py`: replace the `if/elif` with a
per-entry list of `(source, platform_id)` pairs — always the OpenTable pair when `opentable_rid` is
present, plus the Resy pair when `resy_venue_id` is a non-null integer. Upsert one row per pair
through the existing `ON CONFLICT (source, platform_id) DO UPDATE` statement, keeping the SAME human
slug for both rows (migration 0009 makes that legal). Raise the existing `ValueError` only when an
entry yields no pairs at all. Enqueue `resy:{venue_id}` into `sched:polls` with the same initial
random spread as the OpenTable branch, but ONLY when the Resy pair exists AND `RESY_ENABLED` is
true; read that flag through the config function from Task 3 rather than an inline `os.getenv`.
Extend the closing summary print with the Resy row and job counts so `make seed` output states
plainly how many Resy venues are still unresolved.

Write `tests/integration/test_migration_0009.py` as the tracer: bring up the Timescale container,
`alembic upgrade head`, then assert the end-to-end slice — introspection shows
`uq_restaurants_slug_source` present and `ix_restaurants_slug` absent; inserting two rows with the
same slug and different sources succeeds; inserting a duplicate `(slug, source)` raises; running the
seed with a temporary YAML that carries one numeric `resy_venue_id` and `RESY_ENABLED=true` produces
two `restaurants` rows sharing a slug and a `resy:{id}` member in `sched:polls`; and running the same
seed twice is idempotent in both the table and the ZSET.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_migration_0009.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_migration_0009.py -q -p no:cacheprovider` exits 0 (or skips with the existing Docker-guard message).
    - `uv run python -c "import yaml,pathlib; d=yaml.safe_load(pathlib.Path('scripts/seed/restaurants.yml').read_text())['restaurants']; print(len(d), sum(1 for r in d if r.get('resy_url_slug')), sum(1 for r in d if r.get('resy_venue_id') is not None))"` prints `55 31 0`.
    - `grep -c "resy_url_slug" scripts/seed/restaurants.yml` returns 31.
    - `uv run pytest tests/integration/test_seed_idempotency.py -q -p no:cacheprovider` exits 0 — the pre-existing seed contract is unchanged for OpenTable.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>A fresh database migrates to 0009 and a seed run with a numeric Resy id produces two rows sharing one slug plus a `resy:{id}` job, idempotently.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: The human-gated venue-id resolver</name>
  <files>scripts/resolve_resy_venue_ids.py, tests/integration/test_seed_idempotency.py</files>
  <read_first>
    - scripts/seed_restaurants.py (YAML read, `asyncio.run(main())` shape) and scripts/verify_seed.py (the report-and-exit shape)
    - scripts/check_poll_success.py lines 1-45 and 120-132 (the docstring exit-code contract and the `main()` / `sys.exit` pattern this repo uses)
    - scripts/seed/restaurants.yml (as edited in Task 1)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-63a
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Assumptions Log A4 (the endpoint is [ASSUMED]) and §B-4
    - shared/telemetry.py (the redactor — the script must never print the API key)
  </read_first>
  <behavior>
    - `--dry-run` with no `RESY_API_KEY` set: prints how many entries have a `resy_url_slug` and no numeric `resy_venue_id`, makes zero network calls, and exits 2 (not-enough-data), matching the `check_poll_success.py` exit convention.
    - No `RESY_API_KEY` without `--dry-run`: exits 2 with a message naming the env var and the runbook path; still zero network calls.
    - `--slug <one>` restricts the work set to a single entry.
    - A successful resolution writes the integer back into `resy_venue_id` in the YAML, preserves the `resy_url_slug`, and leaves every other key and the file's comment blocks intact.
    - The script never prints or logs the API key, and never writes a file outside the repository.
  </behavior>
  <action>
Write `scripts/resolve_resy_venue_ids.py`: a human-gated one-shot that fills the numeric
`resy_venue_id` values D-63a leaves null. Its module docstring carries a `STATUS: pending-human`
banner, states that it requires a real `RESY_API_KEY` captured by the procedure in
`docs/runbooks/resy-cookie-capture.md`, and marks the resolution endpoint
(`GET {RESY_API_BASE}/3/venue?url_slug={slug}&location=ny`) as `[ASSUMED]` per research A4 with a
`TODO(spike)` marker. CLI: `--dry-run`, `--slug`, `--yaml` (defaulting to the seed path).

Because the endpoint is unverified and no credentials exist, the resolution call itself must be a
single small function with the network call isolated inside it, so the [ASSUMED] shape can be
corrected in one place. Guard every step: refuse to run without a key unless `--dry-run`; resolve
and reject any `--yaml` path outside the repository root before writing; write through a temp file
and rename so an interrupted run cannot truncate the seed data. Use `ruamel`-free plain text editing
or a targeted line rewrite so the YAML's extensive comment blocks survive — `yaml.safe_dump` would
destroy them, which is itself the reason to do the surgical edit. Follow the repo's exit-code
convention: 0 resolved everything requested, 1 one or more lookups failed, 2 preconditions not met.

Extend `tests/integration/test_seed_idempotency.py` with the Resy dimension: seeding twice with
`RESY_ENABLED=true` and one numeric id leaves exactly two rows and one `resy:` ZSET member, and
seeding with `RESY_ENABLED=false` leaves zero `resy:` ZSET members while still creating the Resy
`restaurants` row only if a numeric id is present.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; env -u RESY_API_KEY uv run python scripts/resolve_resy_venue_ids.py --dry-run; test $? -eq 2</automated>
  </verify>
  <acceptance_criteria>
    - `env -u RESY_API_KEY uv run python scripts/resolve_resy_venue_ids.py --dry-run` exits 2 and its stdout names the count of unresolved slugs and the runbook path.
    - `git diff --stat scripts/seed/restaurants.yml` is empty after the dry run (a dry run writes nothing).
    - `grep -c "STATUS: pending-human" scripts/resolve_resy_venue_ids.py` returns at least 1.
    - `uv run pytest tests/integration/test_seed_idempotency.py -q -p no:cacheprovider` exits 0 (or skips with the Docker-guard message).
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>The one step that genuinely needs a human is a runnable, self-documenting script that refuses safely without credentials and never touches the network on a dry run.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Lazily-read Resy configuration and the `.env.example` contract</name>
  <files>services/poller/config.py, .env.example, tests/unit/test_resy_config_lazy.py</files>
  <read_first>
    - services/poller/config.py in full (note line 44 — `KAFKA_BOOTSTRAP_SERVERS: str = os.getenv(...)` is the module-constant anti-pattern this task must not extend)
    - services/state_machine/config.py lines 1-40 (the function-per-setting pattern, its docstring explaining the 02-02 deviation, and the `__all__` list required for `mypy --strict` re-exports)
    - .env.example lines 35-49 (the existing Resy block and the two-phase secret-handling comment)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-61, §D-62, §D-63, §D-64, §D-69, §D-72, and §code_context "Integration Points" (the exact env var list)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Anti-Patterns to Avoid ("Reading Resy env vars into module-level constants") and §Assumptions Log A5 (keep the auth header NAME in config, not hard-coded in the adapter)
    - .planning/STATE.md ("services/poller/config.py freezes env vars at import time")
  </read_first>
  <behavior>
    - Every new setting is a zero-argument function; calling it after `monkeypatch.setenv` returns the NEW value in the same interpreter (a module constant could not).
    - `resy_enabled()` is false for unset, empty, `false`, `0`, `no`, and true for `true`, `TRUE`, `1`, `yes`.
    - `resy_contexts()` defaults to 4; `resy_global_rpm()` to 80; `resy_baseline_interval_seconds()` to 180; `resy_date_range_days()` to 3; `resy_party_sizes()` to `[2]`; `metrics_port()` to 9101.
    - `poll_workers()` returns 1 when Resy is disabled and `1 + resy_contexts()` when it is enabled, and honours an explicit `POLL_WORKERS` override.
    - A non-integer value in an integer setting raises at call time with a message naming the env var — never silently falls back to the default.
    - A source-scan test asserts the module gained no new module-level `os.getenv` assignment.
  </behavior>
  <action>
Add the Resy settings block to `services/poller/config.py`, every one a function, following
`services/state_machine/config.py` rather than this file's own legacy constants. Copy that module's
explanatory docstring verbatim in spirit: the poller's existing module constants froze the
environment at import and pinned a whole integration run to the localhost defaults, and the fix is
to read lazily. Do not touch the existing constants — other modules import them and this plan owns
none of those call sites.

Functions to add: `resy_enabled()`, `resy_api_base()` (default `https://api.resy.com`),
`resy_api_key()`, `resy_auth_token_header()` (default `X-Resy-Auth-Token`, kept in config rather
than hard-coded because research A5 records a sibling header name that may turn out to be the right
one), `resy_accounts_json()`, `resy_proxy_url()`, `resy_contexts()`, `resy_global_rpm()`,
`resy_baseline_interval_seconds()`, `resy_date_range_days()`, `resy_party_sizes()`,
`metrics_port()`, and `poll_workers()`. Give the integer readers a shared private parser that raises
a clear error naming the variable rather than swallowing a typo into a default — a silently-default
`RESY_GLOBAL_RPM` would mean polling at 80 rpm when the operator meant 8. Add an `__all__` entry for
each new name.

Extend `.env.example`'s Resy block with `RESY_ENABLED=false`, `RESY_API_BASE=https://api.resy.com`,
`RESY_API_KEY=`, `RESY_PROXY_URL=`, `RESY_CONTEXTS=4`, `RESY_GLOBAL_RPM=80`,
`RESY_BASELINE_INTERVAL_SECONDS=180`, `RESY_DATE_RANGE_DAYS=3`, `POLL_WORKERS=`, and
`METRICS_PORT=9101`, each with a one-line comment naming its effect. Keep the existing two-phase
secret-handling comment and add a line stating that `RESY_ENABLED=true` with no accounts starts the
fleet in a visibly-labelled anonymous mode rather than failing, and that leaving it false means
Chromium is never launched.

Write `tests/unit/test_resy_config_lazy.py` covering every row in `<behavior>`, including the
`monkeypatch.setenv`-then-call assertion for at least three settings and the source-scan assertion.
The source scan must strip full-line comments before matching (the `tests/unit/test_no_inline_sleep.py`
helper is the template) and must carry a non-vacuity assertion that the scanned file is non-empty.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/unit/test_resy_config_lazy.py -q</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_resy_config_lazy.py -q` exits 0.
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run python -c "from services.poller import config as c; print(c.resy_enabled(), c.resy_contexts(), c.resy_global_rpm(), c.resy_baseline_interval_seconds(), c.metrics_port(), c.poll_workers())"` prints `False 4 80 180 9101 1`.
    - `grep -c "^RESY_\|^METRICS_PORT\|^POLL_WORKERS" .env.example` returns at least 13.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>Every Resy setting is readable at call time, defaults are pinned by a unit test, and `.env.example` documents the full contract including the disabled-by-default switch.</done>
</task>

</tasks>

## Artifacts this phase produces (plan 03)

| Kind | Symbol / path | Notes |
|------|---------------|-------|
| migration | `migrations/versions/0009_restaurant_slug_source_unique.py` | `revision = "0009"`, `down_revision = "0008"` |
| db constraint | `uq_restaurants_slug_source` | replaces `ix_restaurants_slug` + `restaurants_slug_key` |
| yaml field | `resy_url_slug` (string) | renamed from the old string `resy_venue_id`, 31 populated |
| yaml field | `resy_venue_id` (integer \| null) | null on all 55 until resolved |
| script | `scripts/resolve_resy_venue_ids.py` | human-gated; `--dry-run`, `--slug`, `--yaml`; exit 0/1/2 |
| env var | `RESY_ENABLED` | default `false` — gates the Resy row, the job and Chromium |
| env var | `RESY_API_BASE` | default `https://api.resy.com`; tests point it at the stub |
| env var | `RESY_API_KEY` | human-gated |
| env var | `RESY_ACCOUNTS_JSON` | pre-existing; contract restated |
| env var | `RESY_PROXY_URL` | optional |
| env var | `RESY_CONTEXTS` | default 4 |
| env var | `RESY_GLOBAL_RPM` | default 80 |
| env var | `RESY_BASELINE_INTERVAL_SECONDS` | default 180 |
| env var | `RESY_DATE_RANGE_DAYS` | default 3 |
| env var | `POLL_WORKERS` | default `1 + RESY_CONTEXTS` when Resy is enabled, else 1 |
| env var | `METRICS_PORT` | default 9101 |
| function | `resy_enabled()`, `resy_api_base()`, `resy_api_key()`, `resy_auth_token_header()`, `resy_accounts_json()`, `resy_proxy_url()`, `resy_contexts()`, `resy_global_rpm()`, `resy_baseline_interval_seconds()`, `resy_date_range_days()`, `resy_party_sizes()`, `metrics_port()`, `poll_workers()` | all in `services/poller/config.py`, all lazy |
| test | `tests/integration/test_migration_0009.py` | migration + seed tracer |
| test | `tests/unit/test_resy_config_lazy.py` | lazy-read + source scan |

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| seed YAML -> `restaurants` / `sched:polls` | Hand-curated data becomes the identity of every polled venue; a wrong id points the fleet at a stranger |
| `RESY_API_KEY` -> `resolve_resy_venue_ids.py` -> stdout / logs | A human-captured third-party credential crosses into a script that prints a report |
| `--yaml` argument -> filesystem write | Operator-supplied path, written to |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-03-10 | Spoofing | seed venue ids | high | mitigate | `resy_venue_id` stays null until a human resolves it, and the seed enqueues nothing for a null id — no fabricated placeholder can point a live poll at an unrelated venue (D-63a) |
| T-03-11 | Information Disclosure | `resolve_resy_venue_ids.py` | high | mitigate | The API key is read through the config function and never printed; the run summary reports counts and slugs only, and `shared/telemetry.py` (extended in 03-02) redacts `RESY_API_KEY` if it ever reaches a log call |
| T-03-12 | Denial of Service | migration 0009 | high | mitigate | Pre-flight guard raises with a remediation message when a duplicate `(slug, source)` exists, rather than dropping or deleting rows to force the constraint through (0008 precedent) |
| T-03-13 | Tampering | `--yaml` path write | medium | mitigate | The path is resolved and rejected when outside the repository root; the write goes through a temp file plus rename so an interrupt cannot truncate the seed data (ASVS V12) |
| T-03-14 | Repudiation | `RESY_ENABLED` default | medium | mitigate | Default false, so an unconfigured deployment can neither seed a Resy job nor launch a browser; the seed's summary line reports the resulting counts explicitly |
| T-03-SC | Tampering | npm/pip/cargo installs | low | accept | No new packages; `pyyaml`, `sqlalchemy`, `alembic` and `redis` are already pinned in `uv.lock` (research §Package Legitimacy Audit) |
</threat_model>

## Flagged assumptions (probe, unresolved — review manually)

None in this plan. The unclassified POLL-02 / POLL-06 / PERF-05 probe rows are carried in plans
03-02, 03-05 and 03-07 respectively.

<verification>
- `uv run alembic upgrade head` on a fresh container reaches 0009.
- `uv run pytest tests/unit -q` exits 0.
- `uv run pytest tests/integration/test_migration_0009.py tests/integration/test_seed_idempotency.py tests/integration/test_migrations_apply.py -q -p no:cacheprovider` exits 0 or skips with the Docker guard.
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
</verification>

<success_criteria>
- A restaurant can exist on two sources with one human slug and one join key.
- The seed file distinguishes a URL slug from a numeric venue id, and no id is fabricated.
- `RESY_ENABLED=false` (the default) produces byte-identical seed behaviour to before this plan.
- No Resy setting is frozen at import.
</success_criteria>

<output>
Create `.planning/phases/03-resy-playwright-fleet/03-03-SUMMARY.md` when done.
</output>
</content>
