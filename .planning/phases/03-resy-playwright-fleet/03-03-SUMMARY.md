---
phase: 03-resy-playwright-fleet
plan: 03
subsystem: schema-seed-config
tags: [resy, migration, seed, yaml, lazy-config, human-gated, poll-05, d-63a, d-63b]
status: complete

# Dependency graph
requires:
  - phase: 01-foundation-admin-pre-conditions-opentable-polling
    provides: "migrations/versions/0003_create_restaurants.py; scripts/seed/restaurants.yml (55 entries); scripts/seed_restaurants.py ON CONFLICT (source, platform_id) upsert; .env.example Resy block; scripts/check_poll_success.py exit-code convention; shared/http_client.py singleton"
  - phase: 02-state-machine-event-pipeline
    provides: "migrations/versions/0008 pre-flight-guard idiom; tests/integration/conftest.py (apply_migrations, db_urls, redis_url); services/state_machine/config.py function-per-setting pattern"
  - phase: 03-resy-playwright-fleet
    provides: "03-02: shared/redis_keys.py RESY_GLOBAL_RPM_DEFAULT / RESY_BASELINE_INTERVAL_SECONDS_DEFAULT; extended telemetry redaction covering RESY_API_KEY"
provides:
  - "migration 0009 + db constraint `uq_restaurants_slug_source` — one logical restaurant, one human slug, one row per source"
  - "shared.db :: Restaurant matching the new uniqueness (Phase 5 slug lookups depend on it)"
  - "scripts/seed/restaurants.yml :: resy_url_slug (string, 31 populated) and resy_venue_id (int | null, null on all 55)"
  - "scripts/seed_restaurants.py :: _source_pairs / _numeric_venue_id — one row per (source, platform_id), Resy gated on RESY_ENABLED"
  - "scripts/seed_restaurants.py :: seed(yaml_path=...) + SEED_YAML_PATH — a seedable fixture path for tests"
  - "scripts/resolve_resy_venue_ids.py — human-gated resolver; --dry-run / --slug / --yaml; exit 0/1/2"
  - "docs/runbooks/resy-cookie-capture.md — the STATUS: pending-human handoff the whole phase points at"
  - "services/poller/config.py :: thirteen lazy Resy settings incl. resy_enabled(), resy_api_base(), resy_api_key(), poll_workers()"
affects: [03-04-adapter, 03-05-canary, 03-06-poller-gate, 05-api-watchlist, 06-frontend-heatmap]

actuals:
  # chars/4 over the full contents of every changed source/test/doc file (127_600 chars),
  # the convention 03-01 and 03-02 used. The same measure over the realized diff alone
  # is ~24_400.
  tokens: 32000
  tasks: 3
  commits: 6

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A migration that refuses rather than repairs: the pre-flight guard NAMES the offending rows and the remediation, and never deletes a row to make an ALTER succeed"
    - "Absolute alembic revisions in tests, never `downgrade -1` — a relative target silently retargets the moment a new head lands"
    - "Line-based surgical YAML editing where the comments carry the safety argument; `yaml.safe_dump` would delete the very text a human reads before trusting a value"
    - "A null is the honest placeholder when a fabricated value would still be syntactically valid — a fake venue id is a working job pointing at a stranger"
    - "Gate the ROW as well as the job: present-but-never-polled reads to every downstream query as 'never available', which is a lie; absent is honest"
    - "An integer env reader that RAISES naming the variable, so a typo cannot silently restore the default the operator was trying to change"

key-files:
  created:
    - migrations/versions/0009_restaurant_slug_source_unique.py
    - scripts/resolve_resy_venue_ids.py
    - docs/runbooks/resy-cookie-capture.md
    - tests/integration/test_migration_0009.py
    - tests/unit/test_resy_config_lazy.py
    - tests/unit/test_resolve_resy_venue_ids.py
  modified:
    - shared/db.py
    - scripts/seed/restaurants.yml
    - scripts/seed_restaurants.py
    - services/poller/config.py
    - .env.example
    - tests/integration/test_seed_idempotency.py
    - tests/integration/test_migration_0008.py

key-decisions:
  - "`restaurants_slug_key` is dropped as a CONSTRAINT and `ix_restaurants_slug` as an INDEX — the two declarations in 0003 are different object kinds, and dropping the constraint's backing index by name raises DependentObjectsStillExistError"
  - "The pre-flight guard is unreachable from a healthy 0008 database (UNIQUE(slug) already forbids the duplicate it looks for), and is kept anyway: the database where it fires is the one where an operator was doing this migration by hand, which is exactly where a silent DELETE is unrecoverable"
  - "No placeholder Resy venue id was minted, breaking with Phase 1's `opentable_rid: 900000001` precedent — an OpenTable placeholder produces a 404, a Resy placeholder produces a working poll against whatever real venue holds that id"
  - "RESY_ENABLED gates the Resy ROW as well as the job (D-63a), overriding the Task 2 behaviour line that would have written the row regardless"
  - "Task 3 was executed before Task 2 because Task 2's threat mitigation (read the API key through the config function) depends on Task 3's `resy_api_key()`"
  - "`resy_api_key()` returns None, never '', for an uncaptured key — an empty Authorization header turns a missing credential into a puzzling 401 instead of a clear precondition failure"
  - "`poll_workers()` honours an explicit override BEFORE consulting RESY_ENABLED, so an operator who measured their own box does not have to reason about RESY_CONTEXTS"

patterns-established:
  - "Pattern: a source-scan gate asserting SET EQUALITY against the legacy names, not absence — so both a new offender and a silently-deleted legacy constant fail, and the regex itself carries a non-vacuity test"
  - "Pattern: the prohibition as an executable test — `test_the_shipped_seed_file_enqueues_no_resy_job` runs the REAL seed under the MOST permissive configuration (RESY_ENABLED=true) and asserts the queue holds nothing Resy"
  - "Pattern: a secret-redaction test that goes through an EXCEPTION MESSAGE embedding the key, because that is the leak path nobody writes deliberately"
  - "Pattern: a path-containment test against a sibling directory sharing the root's name prefix (`repo-evil`), which a `str.startswith` check accepts"

requirements-completed: []
requirements-advanced: [POLL-05]  # left Pending — see Deviations

coverage:
  - id: T1
    description: "`alembic upgrade head` on a fresh database reaches 0009; restaurants enforces UNIQUE(slug, source) and no longer enforces UNIQUE(slug) in either of its two 0003 declarations"
    requirement: POLL-05
    verification:
      - kind: integration
        ref: "tests/integration/test_migration_0009.py#test_composite_constraint_replaced_both_slug_uniqueness_declarations"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0009.py#test_one_slug_on_two_sources_is_now_legal"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0009.py#test_a_duplicate_slug_source_pair_is_still_rejected"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0009.py#test_the_constraint_records_why_it_exists"
        status: pass
    human_judgment: false
  - id: T2
    description: "0009 applies to a database already at 0008 that already holds rows, and refuses — naming the rows and the remediation — when a duplicate (slug, source) pair exists, without deleting either row"
    requirement: POLL-05
    verification:
      - kind: integration
        ref: "tests/integration/test_migration_0009.py#test_0009_applies_over_a_populated_0008_database"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0009.py#test_the_preflight_guard_refuses_a_duplicate_rather_than_deleting_it"
        status: pass
    human_judgment: false
  - id: T3
    description: "restaurants.yml carries resy_url_slug (31 populated) and resy_venue_id (integer or null, null on all 55)"
    requirement: POLL-05
    verification:
      - kind: command
        ref: "uv run python -c '... print(len(d), sum(resy_url_slug), sum(resy_venue_id is not None))' -> `55 31 0`"
        status: pass
      - kind: command
        ref: "grep -c '^    resy_url_slug' scripts/seed/restaurants.yml -> 31"
        status: pass
    human_judgment: false
  - id: T4
    description: "The seed creates a resy row and enqueues resy:{venue_id} ONLY for a numeric id with RESY_ENABLED=true; with the shipped YAML the rows and the sched:polls membership are unchanged"
    requirement: POLL-05
    verification:
      - kind: integration
        ref: "tests/integration/test_migration_0009.py#test_seed_with_a_numeric_resy_id_produces_two_rows_and_a_resy_job"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0009.py#test_resy_disabled_seeds_no_resy_row_and_no_resy_job"
        status: pass
      - kind: integration
        ref: "tests/integration/test_migration_0009.py#test_the_shipped_seed_file_enqueues_no_resy_job"
        status: pass
      - kind: integration
        ref: "tests/integration/test_seed_idempotency.py#test_resy_enabled_seeds_two_rows_and_one_job_idempotently"
        status: pass
      - kind: integration
        ref: "tests/integration/test_seed_idempotency.py#test_resy_disabled_seeds_no_resy_row_and_no_resy_job"
        status: pass
      - kind: integration
        ref: "tests/integration/test_seed_idempotency.py#test_seed_populates_all_fields_and_zset (unchanged, still passes)"
        status: pass
    human_judgment: false
  - id: T5
    description: "Every Resy setting is read through a FUNCTION; a source scan proves no new module-level os.getenv was added"
    requirement: POLL-05
    verification:
      - kind: unit
        ref: "tests/unit/test_resy_config_lazy.py#test_no_new_module_level_getenv_was_added"
        status: pass
      - kind: unit
        ref: "tests/unit/test_resy_config_lazy.py#test_the_source_scan_would_catch_a_new_constant"
        status: pass
      - kind: unit
        ref: "tests/unit/test_resy_config_lazy.py#test_resy_enabled_reads_the_environment_at_call_time"
        status: pass
      - kind: unit
        ref: "tests/unit/test_resy_config_lazy.py (62 tests, whole file)"
        status: pass
    human_judgment: false
  - id: T6
    description: "resolve_resy_venue_ids.py --dry-run runs with no credentials, reports the unresolved count, exits non-zero, and makes no network call"
    requirement: POLL-05
    verification:
      - kind: command
        ref: "env -u RESY_API_KEY uv run python scripts/resolve_resy_venue_ids.py --dry-run -> exit 2, 31 slugs listed, git diff empty"
        status: pass
      - kind: unit
        ref: "tests/unit/test_resolve_resy_venue_ids.py#test_dry_run_without_a_key_reports_the_work_and_exits_two"
        status: pass
      - kind: unit
        ref: "tests/unit/test_resolve_resy_venue_ids.py#test_no_api_key_without_dry_run_exits_two_and_names_the_variable"
        status: pass
      - kind: unit
        ref: "tests/unit/test_resolve_resy_venue_ids.py#test_the_api_key_is_never_printed"
        status: pass
      - kind: unit
        ref: "tests/unit/test_resolve_resy_venue_ids.py#test_a_yaml_path_outside_the_repository_is_rejected"
        status: pass
    human_judgment: false
  - id: T7
    description: "The numeric venue_id for each of the 31 Resy restaurants is unknown, and the resolution endpoint is [ASSUMED] — confirming both needs a human DevTools capture with a real RESY_API_KEY"
    requirement: POLL-05
    verification:
      - kind: backstop
        ref: "docs/runbooks/resy-cookie-capture.md (STATUS: pending-human). Logged as WINDOWS.md entry 2. Only a human can capture the key and confirm the endpoint shape"
        status: pending
      - kind: unit
        ref: "tests/unit/test_resolve_resy_venue_ids.py#test_the_runbook_documents_the_step_as_pending_human"
        status: pass
    human_judgment: true

metrics:
  duration_minutes: 24
  completed: 2026-09-05
  unit_tests_before: 535
  unit_tests_after: 625
  integration_tests_before: 86
  integration_tests_after: 98
---

# Phase 3 Plan 3: Resy Config, Schema & Seed Summary

A Resy job is now representable at all: `restaurants` admits one row per source under one
human slug, the seed file distinguishes a URL slug from a numeric venue id and invents
neither, and every Resy setting is read at call time so no import can freeze the
environment.

## What Was Built

**`migrations/versions/0009_restaurant_slug_source_unique.py`** — replaces `UNIQUE(slug)`
with `uq_restaurants_slug_source` over `(slug, source)` (D-63b). Migration 0003 declared
slug uniqueness **twice** — once as a column `unique=True` (constraint
`restaurants_slug_key`) and once as a separate unique index (`ix_restaurants_slug`) — and
both had to go. They are different object kinds and are dropped differently: the index by
`op.drop_index`, the constraint by `op.drop_constraint(..., type_="unique")`, because
`restaurants_slug_key`'s backing index shares its name and Postgres refuses to drop that
index while the constraint owns it (`DependentObjectsStillExistError`).

The `upgrade()` opens with a pre-flight guard in the 0008 idiom: `GROUP BY slug, source
HAVING count(*) > 1`, and on a hit it raises naming the offending pairs and the
remediation rather than deleting a row to force the ALTER through (T-03-12). `COMMENT ON
CONSTRAINT` and `COMMENT ON COLUMN` record in the database itself that a slug now
identifies a *restaurant*, not a row, and that `(source, platform_id)` remains the upsert
and join key (D-52) — so a Phase 5/6 developer reading `\d restaurants` learns that a slug
lookup returns one row per source. `downgrade()` states plainly that it fails whenever two
rows share a slug, because restoring `UNIQUE(slug)` requires deciding which row dies, and
that is an operator's decision.

**`scripts/seed/restaurants.yml`** — the overloaded `resy_venue_id` is split into
`resy_url_slug` (string, 31 populated) and `resy_venue_id` (integer or `null`, present on
all 55, `null` on all 55). Both PLACEHOLDER WARNING blocks were extended and the schema
header rewritten to be self-describing, including the resolution procedure.

**No placeholder integer was minted**, deliberately breaking with Phase 1's
`opentable_rid: 900000001` precedent. The two cases are not analogous: an OpenTable
placeholder produces a 404, but a Resy placeholder produces a *working poll* against
whatever real venue happens to hold that id, with no signal that the data was invented.
Null is the honest value and the seed skips it (D-63a, T-03-10).

**`scripts/seed_restaurants.py`** — the `if/elif` source derivation, which preferred
OpenTable and therefore made the Resy branch unreachable for every entry that had both
(research B-5), became `_source_pairs()` returning a list of `(source, platform_id)` pairs
upserted one row each through the unchanged `ON CONFLICT (source, platform_id)` statement,
**keeping the same human slug for both**. `_numeric_venue_id()` excludes `bool` first
(`bool` is a subclass of `int`, so `resy_venue_id: true` would have seeded the job
`resy:1` — a real venue belonging to somebody else) and refuses a string rather than
coercing it. The closing summary now states the Resy row count, the job count and how many
venues remain unresolved, so `make seed` reports the state of the handoff.

**`scripts/resolve_resy_venue_ids.py`** — the human-gated one-shot, carrying a
`STATUS: pending-human` banner. `--dry-run` lists all 31 unresolved slugs, makes zero
network calls, writes nothing and exits 2; without a key and without `--dry-run` it exits
2 naming `RESY_API_KEY` and the runbook. The `[ASSUMED]` endpoint (research A4) lives in a
single function, `_resolve_one`, with a `TODO(spike)` marker, and its exception is reported
per slug rather than aborting the run — so correcting the shape after the DevTools capture
is a one-function edit. The `--yaml` path must resolve inside the repository
(`is_relative_to`, not a string prefix, so a sibling `mise-evil/` is refused), the write
goes through a temp file plus `fsync` plus `os.replace` with the temp removed on
`BaseException`, and a non-integer response is refused rather than written.

The YAML edit is line-based rather than `safe_load`/`safe_dump`. That is not a style
choice: the seed file carries ~90 lines of curation sources, schema documentation and two
placeholder warnings, `safe_dump` deletes every one of them silently, and those comments
are precisely what a human reads before trusting an id. Each resolved line records the
slug it came from, because a bare integer in a diff is unreviewable.

**`docs/runbooks/resy-cookie-capture.md`** — created (it did not exist, though the YAML,
03-01's summary and this plan's must_haves all pointed at it). Documents the API-key
capture, the account-cookie capture, the resolution procedure with its exit-code table,
the `[ASSUMED]`-endpoint caveat, and an explicit instruction to verify a resolved id
against `https://resy.com/cities/ny/<resy_url_slug>` before committing it — an id that
points at the wrong restaurant is worse than a null one, because it looks like it works.

**`services/poller/config.py`** — thirteen new settings, every one a zero-argument
function, following `services/state_machine/config.py` rather than this file's own legacy
constants (which are left untouched: other modules import them and this plan owns none of
those call sites). The integer readers share `_env_int`, which **raises naming the
variable** instead of swallowing a typo into the default. `resy_auth_token_header()` keeps
the header *name* in config because research A5 records a sibling `X-Resy-Universal-Auth`
that may turn out to be the right one. `poll_workers()` is 1 disabled and
`1 + RESY_CONTEXTS` enabled (D-72), so the default configuration is byte-for-byte today's
single serial loop.

## Key Decisions

1. **The pre-flight guard is unreachable from a healthy 0008 database, and is kept
   anyway.** `UNIQUE(slug)` already forbids the duplicate `(slug, source)` pair the guard
   looks for, so on any normal deployment it is a no-op. The database where it *does* fire
   is the one where someone dropped the slug index by hand — an operator mid-way through
   doing this migration manually — and that is exactly where a silent `DELETE` would be
   unrecoverable. `test_the_preflight_guard_refuses_a_duplicate_rather_than_deleting_it`
   constructs that database explicitly.

2. **`RESY_ENABLED` gates the Resy row, not only the Resy job.** The plan is internally
   inconsistent here (see Deviations); D-63a and must_have truth 4 both gate the row, and
   the Task 2 behaviour line does not. Gating the row won: a `restaurants` row that nothing
   polls and nothing closes reads to every Phase 5/6 query as a restaurant that is simply
   never available, which is a false statement about the world. Absent is honest.

3. **Task 3 ran before Task 2.** Task 2's threat mitigation (T-03-11 — read the API key
   through the config function so it is covered by the telemetry redactor) depends on Task
   3's `resy_api_key()`. Running them in the written order would have required either an
   inline `os.getenv` in the resolver or a forward-borrow of half of Task 3.

4. **Absolute alembic revisions in migration tests.** Landing 0009 broke two passing tests
   in `test_migration_0008.py`, and how it broke them is the lesson: `downgrade -1` means
   "one step back from HEAD", so those tests silently started downgrading 0009→0008 and
   failed with a `NotNullViolation` on a column they never mention. Both now name 0007
   explicitly, and `test_migration_0009.py` names 0008 through a `PREVIOUS_REVISION`
   constant so the trap does not spring on 0010.

5. **The prohibition is an executable test.**
   `test_the_shipped_seed_file_enqueues_no_resy_job` runs the *real* 55-entry seed under
   the *most permissive* configuration there is (`RESY_ENABLED=true`) and asserts
   `sched:polls` holds nothing Resy and the table holds no Resy row. Any future placeholder
   id anywhere in that file fails it.

## Deviations from Plan

### Resolved plan-internal contradictions

**1. `RESY_ENABLED=false` and the Resy `restaurants` row**
- **Found during:** Task 1
- **Issue:** must_have truth 4 and 03-CONTEXT §D-63a both say the seed creates a `resy` row
  ONLY when a numeric id is present **AND** `RESY_ENABLED` is true. Task 2's `<behavior>`
  block says the opposite — that `RESY_ENABLED=false` "still creat[es] the Resy restaurants
  row only if a numeric id is present". They cannot both hold.
- **Resolution:** D-63a and truth 4 win, per the standing instruction to prefer
  03-CONTEXT.md. Both integration files assert the row is absent when the flag is false, and
  the reasoning is recorded in the test's own docstring.
- **Files:** `scripts/seed_restaurants.py`, `tests/integration/test_seed_idempotency.py`,
  `tests/integration/test_migration_0009.py`
- **Commits:** 5a094f2, 92e3538

**2. `grep -c "resy_url_slug" scripts/seed/restaurants.yml` returns 32, not 31**
- **Found during:** Task 1
- **Issue:** The same task's action text requires the header schema block to document the
  new field ("so the file is self-describing"), and every line that does so is also a line
  `grep -c` counts. The acceptance criterion and the action text cannot both be satisfied
  literally.
- **Resolution:** The documentation won; the count is 31 entry lines plus one header
  mention. The anchored form `grep -c "^    resy_url_slug"` returns exactly 31, and the
  semantic check the same criterion list specifies —
  `print(len(d), sum(resy_url_slug), sum(resy_venue_id is not None))` — prints exactly
  `55 31 0`. Wording the header to avoid the literal token would have been obfuscation.

**3. Task order: 3 before 2** — see Key Decision 3. The tracer (Task 1) still ran first.

### Auto-fixed Issues

**4. [Rule 1 - Bug] Migration 0009 broke two passing tests in `test_migration_0008.py`**
- **Found during:** the plan's closing full-suite integration run
- **Issue:** Both used `alembic downgrade -1` to reach revision 0007. Adding 0009 made `-1`
  mean 0009→0008, so `test_a_non_empty_table_is_refused_not_deleted` inserted a row without
  `event_id` into a schema that still had it `NOT NULL` (`NotNullViolationError`), and
  `test_downgrade_then_upgrade_restores_the_same_schema` asserted an index count of 0 for
  an index that was still there. Directly caused by this plan's change.
- **Fix:** Both now downgrade to the absolute revision `0007`, with a comment explaining
  why relative targets are wrong here. `test_migration_0009.py` was given the same
  treatment pre-emptively.
- **Files modified:** `tests/integration/test_migration_0008.py`,
  `tests/integration/test_migration_0009.py`
- **Commit:** dc5c73f

**5. [Rule 2 - Missing critical] `docs/runbooks/resy-cookie-capture.md` did not exist**
- **Found during:** Task 1
- **Issue:** This plan's must_have truth 7 requires the pending-human step to be
  "documented as pending-human in `docs/runbooks/resy-cookie-capture.md`". The file was
  referenced by 03-01's summary, by this plan's YAML edits and by the resolver's docstring,
  and had never been created. A handoff document that does not exist is not a handoff.
- **Fix:** Written, with a `STATUS: pending-human` banner, a table of what is missing and
  what each thing unblocks, the API-key capture procedure, the resolver's exit codes, the
  `[ASSUMED]`-endpoint caveat, the verify-before-committing instruction, and a completion
  checklist. `test_the_runbook_documents_the_step_as_pending_human` pins its existence.
- **Files modified:** `docs/runbooks/resy-cookie-capture.md` (created)
- **Commit:** 5a094f2

**6. [Rule 3 - Blocking] The seed's YAML path was hard-coded**
- **Found during:** Task 1
- **Issue:** `YAML_PATH = Path("scripts/seed/restaurants.yml")` is read directly inside
  `seed()`, so the Task 1 test — which requires "running the seed with a temporary YAML
  that carries one numeric `resy_venue_id`" — could not be written without editing the
  committed 55-entry file from a test.
- **Fix:** `seed(yaml_path=...)` plus a `SEED_YAML_PATH` env override for the subprocess
  invocation the integration tier uses. `make seed` never sets it.
- **Files modified:** `scripts/seed_restaurants.py`
- **Commit:** 5a094f2

**7. [Rule 3 - Blocking] `resy_enabled()` was needed by Task 1 but specified in Task 3**
- **Found during:** Task 1
- **Issue:** Task 1's action text instructs the seed to read the flag "through the config
  function from Task 3 rather than an inline `os.getenv`", but Task 3 had not run.
- **Fix:** `_env_bool` and `resy_enabled()` were added in Task 1 (with the lazy-read
  docstring and `__all__`); Task 3 appended the remaining twelve settings around them. This
  is why `resy_enabled()` sits above the Resy block in the finished file, with a comment
  saying so.
- **Files modified:** `services/poller/config.py`
- **Commit:** 5a094f2

### Additions beyond the plan's named artifacts

- **`tests/unit/test_resolve_resy_venue_ids.py` (28 tests).** The plan gives Task 2 a
  five-row `<behavior>` block, marks it `tdd="true"`, and then names only
  `tests/integration/test_seed_idempotency.py` as its test file — which tests the seed, not
  the resolver. Its acceptance criteria would have left the resolver covered by one shell
  invocation of `--dry-run`. Every guard that makes this script safe to hand to a human
  (path containment, atomic write, key redaction, non-integer refusal) would have been
  untested.
- **`tests/integration/test_migration_0009.py` carries two seed tests the plan assigned to
  Task 2's file** (`test_resy_disabled_seeds_no_resy_row_and_no_resy_job`,
  `test_the_shipped_seed_file_enqueues_no_resy_job`). The tracer needed the
  disabled-case contrast to be meaningful, and the shipped-file prohibition belongs beside
  the migration that made a second row possible.
- **`shared/db.py :: Restaurant`** — not in the plan's `files_modified`, but required by
  the standing project rule ("update `shared/db.py :: Restaurant` so the ORM matches the
  new `(slug, source)` uniqueness"). Phase 5 depends on it.
- **`RESY_AUTH_TOKEN_HEADER` and `RESY_PARTY_SIZES`** added to `.env.example` beyond the
  ten the plan lists — both are settings this plan created, and an env var that exists in
  code but not in `.env.example` is one nobody discovers.

### Checkpoints

None. This plan is fully autonomous. No authentication gate was reached: the one step that
needs credentials is the resolver, and it is shipped as a dry-run-capable script with a
`STATUS: pending-human` runbook rather than as a blocking step.

## Known Stubs

| File | What | Why it is intentional |
|------|------|-----------------------|
| `scripts/seed/restaurants.yml` | All 55 `resy_venue_id` values are `null` | D-63a. The numeric ids are unknown and only a human with a real `RESY_API_KEY` can resolve them. A fabricated id would be a working poll against a stranger's venue (T-03-10), so null — and therefore visibly absent from the queue — is the honest state. `test_the_shipped_seed_file_enqueues_no_resy_job` enforces it. |
| `scripts/resolve_resy_venue_ids.py :: _resolve_one` | The resolution endpoint `GET {RESY_API_BASE}/3/venue?url_slug=…&location=ny` is `[ASSUMED]` (research A4), marked `TODO(spike)` | No call to resy.com is permitted in this phase, and no key exists to make one. The assumption is confined to one function whose failure is reported per slug, so correcting it after the DevTools capture is a single-function edit. Recorded as `.planning/WINDOWS.md` entry 2. |

Neither stub blocks this plan's goal. The goal was to make a Resy job *representable* —
proven end to end by `test_seed_with_a_numeric_resy_id_produces_two_rows_and_a_resy_job`,
which resolves an id in a fixture and gets two rows plus a `resy:{id}` job. Producing the
real ids is the human step this plan packaged.

## Threat Flags

None. Every file this plan touched is covered by its own `<threat_model>`. The one new
network call (`_resolve_one`) is named in T-03-11 and is unreachable without a
human-supplied credential; the one new filesystem write (`--yaml`) is named in T-03-13 and
is confined to the repository root.

## Verification

| Gate | Result |
|------|--------|
| `uv run ruff check .` | pass |
| `uv run mypy shared/ services/ scripts/` | pass (46 source files) |
| `uv run pytest tests/unit -q` | 625 passed (was 535; +90) |
| `uv run pytest tests/integration -q -p no:cacheprovider` | 98 passed (was 86; +12) |
| `uv run pytest tests/integration/test_migration_0009.py -q` | 10 passed |
| `uv run pytest tests/integration/test_seed_idempotency.py -q` | 4 passed |
| `uv run pytest tests/integration/test_migrations_apply.py -q` | pass — fresh DB reaches 0009 |
| yaml counts (`55 31 0`) | pass |
| `grep -c "^    resy_url_slug" scripts/seed/restaurants.yml` | 31 |
| `grep -c "^RESY_\|^METRICS_PORT\|^POLL_WORKERS" .env.example` | 19 (>= 13 required) |
| `c.resy_enabled(), c.resy_contexts(), c.resy_global_rpm(), c.resy_baseline_interval_seconds(), c.metrics_port(), c.poll_workers()` | `False 4 80 180 9101 1` |
| `env -u RESY_API_KEY … resolve_resy_venue_ids.py --dry-run` | exit 2, 31 slugs, `git diff` empty |
| `grep -c "STATUS: pending-human" scripts/resolve_resy_venue_ids.py` | 1 |

## TDD Gate Compliance

Tasks 2 and 3 carry `tdd="true"` and both followed RED → GREEN, each RED commit verified
failing before its GREEN counterpart:

| Task | RED | Observed failure | GREEN |
|------|-----|------------------|-------|
| 3 (config) | 0e021ff | 43 failed, 19 passed | 99abe60 |
| 2 (resolver) | 5e4cf59 | `ModuleNotFoundError: No module named 'scripts.resolve_resy_venue_ids'` | 92e3538 |

No REFACTOR commit was needed. Task 1 is `type="tracer"` and is exempt; its feedback gate
ran autonomously — the tracer's `<verify>` was re-run green (10 passed) before Task 3
began.

## Requirements

**POLL-05 left `Pending`**, following the 03-01 precedent. REQUIREMENTS.md defines POLL-05
as "calls `/api/4/find` directly … enforces <= 1 request / 45 s per restaurant per context
and <= 80 req/min total". This plan builds neither the adapter nor the enforcement call
site — 03-02 shipped the Lua that *can* enforce the cap and 03-04 will call it. Marking
POLL-05 Done here would make the traceability table claim a capability the codebase does
not have.

## Notes for Next Plans

- **03-04 / 03-06:** `poll_loop` still parses a job with `int(rid_str)` and `continue`s
  **without releasing** on failure (research B-4). Nothing can produce a malformed job any
  more, but D-63a explicitly asks for the release (`ZREM` from inflight) as defence in
  depth. It is not in this plan's file list and was left alone.
- **03-04:** the adapter must read `resy_api_base()`, `resy_api_key()` and
  `resy_auth_token_header()` — never `os.getenv` — or the stub-backed integration tests
  cannot repoint it. `resy_api_base()` already strips a trailing slash.
- **03-06:** `poll_workers()` exists and is unused; `services/poller/main.py` still runs
  exactly one `poll_loop`. Wiring it is D-72's remaining half.
- **Phase 5/6:** a slug lookup against `restaurants` now returns **one row per source**.
  The constraint comment in the database says so, and Phase 6's heatmap will need a
  merge/canonical concept if it wants one card per restaurant.

## Self-Check: PASSED

All fourteen claimed files exist on disk and all six claimed commits are reachable in
`git log --all`. Verified 2026-09-05.
