---
phase: 06-pattern-intelligence-frontend-pwa
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - tests/unit/test_phase6_preconditions.py
  - tests/unit/factories.py
  - shared/pattern/__init__.py
  - shared/pattern/stats.py
  - shared/pattern/model.py
  - tests/unit/test_pattern_stats.py
  - tests/unit/test_pattern_model.py
  - tests/unit/test_pattern_gating.py
  - tests/unit/test_pattern_summary_text.py
  - tests/unit/test_pattern_purity.py
  - tests/fixtures/pattern/48h_heavy.json
  - tests/fixtures/pattern/load_day.json
  - tests/fixtures/pattern/flat.json
  - tests/fixtures/pattern/sparse.json
  - tests/fixtures/pattern/gate_boundary.json
autonomous: true
requirements: [PATTERN-01, PATTERN-02]

estimate:
  tokens: 82000
  raw_tokens: 82000
  tasks: 3
  confidence: low

must_haves:
  truths:
    - "Wave 0 gate: every Phase 4 / Phase 5 artifact this phase MODIFIES (services/api/routers/restaurants.py, services/api/sse.py, services/api/routers/links.py, services/notifier/pattern_hook.py, services/notifier/templates.py, docs/api.md, and the Phase 4 migration adding push_subscriptions) exists on disk before any Phase 6 backend task runs; a missing artifact HALTS the plan with the name of the Phase 4/5 plan that must execute first."
    - "compute_pattern is a pure function of (events, now, cfg): it reads no clock, opens no connection and draws no entropy — a source-scan test pins this permanently (D-106, mirroring tests/unit/test_engine_purity.py)."
    - "PATTERN-01 probe (48-hour rule): over tests/fixtures/pattern/48h_heavy.json (n=100, exactly 36 events with 46 <= hours_before_service <= 50) compute_pattern reports share == 0.36 exactly and the Wilson 95% interval (0.272712, 0.457646) to 6 decimal places, and detected is True (D-106, RESEARCH Wilson transcript)."
    - "PATTERN-01 (inventory-load day) uses dow_local (observation weekday), never day_of_week (service weekday): over load_day.json the rule returns day 2 with ratio 6.0 and detected True, while the same corpus evaluated on the service weekday detects nothing (BC-11)."
    - "PATTERN-01 (cancellation peaks) returns exactly the top 3 hour_local bins, each with its share, n and Wilson interval."
    - "PATTERN-01 (duration) returns median/p25/p75 from statistics.quantiles(method='inclusive') and None when the closed-event count is below DURATION_MIN_N (D-106a)."
    - "PATTERN-02 boundary probe: exactly 30 events spanning exactly 14 days yields status 'ready'; 29 events over 14 days yields 'collecting_data'; 30 events over 13 days yields 'collecting_data'."
    - "PATTERN-02 adjacency probe: a 48-hour share of exactly 0.25 with a Wilson lower bound of exactly 0.15 is DETECTED (both thresholds are inclusive), and one step below either threshold is not."
    - "PATTERN-02 empty probe: compute_pattern([], now, cfg) returns status 'collecting_data', an empty rule list, days_of_history 0, n_events 0 and the exact quantified placeholder sentence — it never raises and never returns a partial rule."
    - "PATTERN-02 ordering probe: when two hour bins have equal counts the earlier hour sorts first, and repeated calls on the same corpus return byte-identical PatternReport contents (stable ordering, no set iteration)."
    - "PATTERN-02 precision probe: Wilson bounds clamp to [0.0, 1.0] (k=0 gives lower bound exactly 0.0; k=n gives upper bound exactly 1.0), Z95 satisfies 0.5*(1+erf(Z95/sqrt(2))) == 0.975 to 1e-12, and every percentage rendered into summary_text is a rounded integer with its n alongside."
    - "summary_text names ONLY detected rules; an undetected rule produces no sentence, no hedge and no 'not detected' phrasing (D-106, UI-SPEC pattern sentence rule 1)."
    - "Every rule the report exposes carries n, ci_low and ci_high — there is no code path that returns a share without its sample size (UI-SPEC pattern sentence rule 2)."
    - "summary_text states the observation window ('over the last 30 days') and uses observational verbs only (UI-SPEC pattern sentence rules 3 and 4)."
  artifacts:
    - tests/unit/test_phase6_preconditions.py
    - shared/pattern/__init__.py
    - shared/pattern/stats.py
    - shared/pattern/model.py
    - tests/fixtures/pattern/48h_heavy.json
    - tests/fixtures/pattern/load_day.json
    - tests/fixtures/pattern/flat.json
    - tests/fixtures/pattern/sparse.json
    - tests/fixtures/pattern/gate_boundary.json
    - tests/unit/test_pattern_stats.py
    - tests/unit/test_pattern_model.py
    - tests/unit/test_pattern_gating.py
    - tests/unit/test_pattern_summary_text.py
    - tests/unit/test_pattern_purity.py
  key_links:
    - "EventObs.day_of_week (service weekday, 0=Sun, from services/state_machine/persistence.py::day_of_week) and EventObs.dow_local (observation weekday, 0=Sun) are DISTINCT fields; the load-day rule reads dow_local and the heatmap axis reads day_of_week (BC-11)."
    - "PatternConfig defaults are the single definition site for PATTERN_MIN_EVENTS=30, MIN_DAYS_OF_HISTORY=14, RULE_48H_MIN_SHARE=0.25, RULE_48H_MIN_CI_LOW=0.15, RULE_48H_WINDOW=(46,50), LOAD_DAY_RATIO=3.0, LOAD_DAY_MIN_OBS=3, DURATION_MIN_N=10, PEAK_BINS=3, WINDOW_DAYS=30 — 06-02 and 06-03 import them, never re-declare."
    - "compute_pattern's PatternReport is the exact payload shape shared/pattern/service.py (06-02) caches and services/api/routers/restaurants.py (06-03) serialises."
  prohibitions:
    - "shared/pattern/model.py and shared/pattern/stats.py contain no wall-clock read, no entropy draw and no I/O (banned tokens scanned with full-line comments stripped: time.time( / datetime.now( / uuid4( / random. / open( / requests / httpx)."
    - "No third-party statistics dependency is added — pyproject.toml gains no numpy, scipy or statsmodels entry."
    - "summary_text never contains a certainty word: will, predicts, prediction, guaranteed, always, never, best time to book, secret, hack, insider, beat the system (UI-SPEC forbidden list) — scanned over rendered output for all five fixtures, not over source."
    - "No percentage is ever rendered into summary_text without its sample size in the same sentence."
    - "The precondition task creates NO Phase 4 / Phase 5 file; it only asserts and halts."
---

<objective>
Open Phase 6 with the Wave-0 precondition gate, then land the pure pattern kernel — the Wilson/quartile
statistics and `compute_pattern` — proven against five deterministic corpora.

Purpose: every later Phase 6 backend plan modifies a Phase 4 or Phase 5 file. This plan proves those files
exist before anything is written, and delivers the functional core (PATTERN-01, PATTERN-02) that the CAGG,
the cached service, the API routes and the notifier hook all read.

Output: `tests/unit/test_phase6_preconditions.py`, `shared/pattern/{__init__,stats,model}.py`, five JSON
corpora under `tests/fixtures/pattern/`, and five unit test modules.
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
@CLAUDE.md
</context>

## Artifacts this phase produces (this plan's share)

| Kind | Artifact | Notes |
|------|----------|-------|
| package | `shared/pattern/` | new backend package: `__init__.py`, `stats.py`, `model.py` |
| lib function | `shared.pattern.stats.wilson(k, n, z=Z95) -> tuple[float, float]` | closed form, no continuity correction |
| lib function | `shared.pattern.stats.quartiles(values) -> tuple[float, float, float] \| None` | `statistics.quantiles(method="inclusive")` |
| constant | `shared.pattern.stats.Z95 = 1.959963984540054` | `Phi(Z95) == 0.975` |
| lib function | `shared.pattern.model.compute_pattern(events, now, cfg) -> PatternReport` | pure |
| dataclass | `shared.pattern.model.EventObs` | `first_seen_at, hours_before_service, day_of_week, dow_local, hour_local, duration_seconds` |
| dataclass | `shared.pattern.model.PatternConfig` | every threshold default |
| dataclass | `shared.pattern.model.PatternReport` | `status, days_of_history, n_events, window_days, rules, duration, summary_text` |
| test fixtures | `tests/fixtures/pattern/{48h_heavy,load_day,flat,sparse,gate_boundary}.json` | deterministic corpora |
| test factory | `tests/unit/factories.py :: make_event_obs` | added to the existing shared factory module |

<tasks>

<task type="auto">
  <name>Task 1: Wave-0 precondition gate for the Phase 4 / Phase 5 artifacts this phase modifies</name>
  <files>tests/unit/test_phase6_preconditions.py</files>
  <read_first>
    - `.planning/phases/04-notification-pipeline/04-CONTEXT.md` — D-81 (`templates.py`, `pattern_hook.py` stub), D-84 (`services/api/app.py`, `routers/links.py`), D-85 (the migration adding `push_subscriptions` and `users.phone_hash`)
    - `.planning/phases/05-api-watchlist-crud-sse/05-CONTEXT.md` — D-98 (`services/api/sse.py :: FeedHub`), D-100 (`services/api/routers/restaurants.py`), D-102 (`/api/push/*`), D-104 (`docs/api.md`, OpenAPI snapshot test)
    - `tests/unit/test_no_setnx_expire_pairs.py` — the repo's guard-the-guard idiom (`test_scanned_dirs_are_non_empty`) that this module copies
    - `Makefile` — the `test` target (`-W error::RuntimeWarning`) this test runs under
  </read_first>
  <action>
Create `tests/unit/test_phase6_preconditions.py`: a fast, dependency-free assertion module that fails the unit
suite with an actionable message the moment a Phase 4 / Phase 5 artifact this phase edits is absent. Module
docstring cites PATTERN-03, FE-06, FE-02 and ends with a `Named symbols:` line per the repo convention.

Assert the existence of each required path and, for each, name the upstream plan in the assertion message:
`services/api/app.py` and `services/api/routers/links.py` (Phase 4 plan 04-04, D-84); `services/notifier/templates.py`
and `services/notifier/pattern_hook.py` (Phase 4 plan 04-05 / 04-03, D-81); `services/api/sse.py` and
`services/api/routers/restaurants.py` (Phase 5, D-98 / D-100); `docs/api.md` (Phase 5, D-104); `shared/tokens.py`,
`shared/crypto.py`, `shared/links.py` (Phase 4, D-82 / D-83 / D-85). Add a content assertion for the two contracts
this phase depends on rather than merely the filenames: `services/notifier/pattern_hook.py` must define a callable
named `estimate_window_text` taking `source` and `restaurant_id`, and `migrations/versions/` must contain a revision
whose source mentions the `push_subscriptions` table (Phase 4 D-85). Use `pathlib` + `ast` for the signature check —
do not import the Phase 4/5 modules, because importing `services.api` pulls FastAPI and a config surface this test
must not depend on.

Add a separate assertion that records the current Alembic head so plan 06-02 has a resolved `down_revision`: read
every file under `migrations/versions/*.py`, parse the module-level `revision` and `down_revision` string literals
with `ast`, and assert exactly one revision is not referenced as any other's `down_revision` — that single value is
the head. Expose it as a module-level helper `current_migration_head()` so 06-02's migration test can reuse it, and
assert the head is not already a Phase 6 CAGG revision.

Add the guard-the-guard test: assert the list of scanned migration files has more than five entries, so a path typo
cannot make the head resolution vacuously pass.

If any assertion fails at execution time, STOP the plan and report which upstream plan must run first. Do not
create, stub or scaffold the missing file: Phase 6 never redefines a Phase 4 / Phase 5 artifact.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_phase6_preconditions.py -x -q` exits 0.
    - `uv run python -c "from tests.unit.test_phase6_preconditions import current_migration_head; print(current_migration_head())"` prints exactly one revision id and exits 0.
    - `grep -c 'estimate_window_text' tests/unit/test_phase6_preconditions.py` is at least 1.
    - The module contains no `import services.` and no `import fastapi`: `grep -v '^\s*#' tests/unit/test_phase6_preconditions.py | grep -cE '^\s*(import|from) (services|fastapi)\b'` equals 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_phase6_preconditions.py -x -q</automated>
  </verify>
  <done>Every Phase 4 / Phase 5 artifact this phase edits is proven present, the Alembic head is machine-readable, and the guard cannot pass vacuously.</done>
</task>

<task type="tracer" tdd="true">
  <name>Task 2: Tracer — Wilson/quartile statistics and the 48-hour rule end to end on a real corpus</name>
  <files>shared/pattern/__init__.py, shared/pattern/stats.py, shared/pattern/model.py, tests/unit/factories.py, tests/fixtures/pattern/48h_heavy.json, tests/unit/test_pattern_stats.py, tests/unit/test_pattern_model.py</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Code Examples — the verified `wilson()` closed form, the `Z95` constant, the seven-case verification transcript, and the `quartiles()` inclusive-method rationale
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-106 (rule definitions and thresholds), D-106a (quartile method, Wilson closed form)
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Copywriting Contract → "Pattern sentence rules" — the seven rules and the reference sentence `summary_text` must match in shape
    - `services/state_machine/engine.py` (lines 1-50) — the module-docstring + purity-declaration + named-threshold-constant idiom to copy
    - `services/state_machine/persistence.py` (lines 48-56) — `day_of_week` 0=Sun convention
    - `tests/unit/factories.py` — the existing deterministic-builder module `make_event_obs` is added to
    - `tests/unit/test_engine_transitions.py` (lines 1-30) — test docstring, fixture-constant and naming idiom
  </read_first>
  <behavior>
    - `wilson(36, 100)` returns `(0.272712, 0.457646)` when both bounds are rounded to 6 decimal places.
    - `wilson(0, 10)` returns a lower bound of exactly `0.0`; `wilson(10, 10)` returns an upper bound of exactly `1.0`; `wilson(k, 0)` returns `(0.0, 1.0)`.
    - `0.5 * (1 + math.erf(Z95 / math.sqrt(2)))` equals `0.975` to within `1e-12`.
    - `quartiles([60, 90, 120, 150, 180, 240, 300, 420, 600, 900])` returns `(127.5, 210.0, 390.0)`.
    - `quartiles([])` and `quartiles([300.0])` return `None` (fewer than two data points) rather than raising `StatisticsError`.
    - `compute_pattern` over `48h_heavy.json` with a `now` 30 days after the earliest event returns `status == "ready"`, a 48-hour rule with `share == 0.36`, `n == 100`, `ci_low`/`ci_high` matching `wilson(36, 100)`, and a `summary_text` that contains `36%`, `100` and `95% CI`.
    - `compute_pattern` over `48h_heavy.json` is byte-stable: two calls with the same arguments produce equal `PatternReport` values.
  </behavior>
  <action>
Write the thinnest complete path through the pattern kernel: statistics, the dataclasses, one detected rule, the
gate, and a rendered sentence — proven on a real corpus in one commit.

`shared/pattern/__init__.py`: package marker with a one-line docstring naming PATTERN-01..03 and D-105..D-108.

`shared/pattern/stats.py`: module docstring citing D-106a and the RESEARCH verification transcript, ending with a
`Named symbols:` line. Define `Z95` as a module constant with the comment that it is pinned so a typo'd digit is
caught by the erf assertion. Define `wilson(k, n, z=Z95) -> tuple[float, float]` exactly as the verified closed form
(centre and half-width over the `1 + z*z/n` denominator, both bounds clamped into `[0.0, 1.0]`, `n == 0` returning
the uninformative `(0.0, 1.0)`). Define `quartiles(values) -> tuple[float, float, float] | None` returning `None`
for fewer than two values and otherwise `statistics.quantiles(values, n=4, method="inclusive")` as a 3-tuple —
the inclusive method is load-bearing because it never extrapolates outside the observed range and because it is what
makes the 06-02 SQL cross-check possible. `math` and `statistics` are the only imports.

`shared/pattern/model.py`: module docstring in the `engine.py` shape — purpose, decision ids (D-106, D-106a, BC-11),
an explicit statement that this module performs no I/O, reads no clock and draws no entropy (every timestamp comes
from the caller's `now`), and a `Named symbols:` line. Declare frozen dataclasses `EventObs` (`first_seen_at:
datetime`, `hours_before_service: float`, `day_of_week: int`, `dow_local: int`, `hour_local: int`,
`duration_seconds: int | None`) with a comment stating that `day_of_week` is the SERVICE weekday used by the heatmap
y-axis while `dow_local` is the OBSERVATION weekday used by the inventory-load-day rule, and that both are 0=Sun;
`PatternConfig` carrying `min_events=30`, `min_days_of_history=14`, `window_days=30`, `rule_48h_window=(46.0, 50.0)`,
`rule_48h_min_share=0.25`, `rule_48h_min_ci_low=0.15`, `load_day_ratio=3.0`, `load_day_min_obs=3`,
`duration_min_n=10`, `peak_bins=3`, each with the "observation threshold, not an outcome lever" comment style from
`engine.py`; `RuleFinding` (`rule: str`, `share: float`, `n: int`, `k: int`, `ci_low: float`, `ci_high: float`, plus
an optional `detail` mapping); `DurationSummary` (`p25`, `p50`, `p75`, `n`); and `PatternReport` (`status:
Literal["collecting_data", "ready"]`, `days_of_history: int`, `n_events: int`, `window_days: int`, `rules:
tuple[RuleFinding, ...]`, `duration: DurationSummary | None`, `summary_text: str`).

Implement `compute_pattern(events, now, cfg)` for this tracer with the 48-hour rule only, plus the full gate and the
sentence renderer. `days_of_history` is the whole number of days between the earliest `first_seen_at` and `now`.
`status` is `"ready"` only when `days_of_history >= cfg.min_days_of_history` AND `len(events) >= cfg.min_events`,
otherwise `"collecting_data"`. The 48-hour rule counts events whose `hours_before_service` lies inclusively inside
`cfg.rule_48h_window`, computes `share = k / n`, takes `wilson(k, n)`, and is detected when `share >=
cfg.rule_48h_min_share` AND `ci_low >= cfg.rule_48h_min_ci_low` — both comparisons inclusive, which is the
adjacency contract. Undetected rules are omitted from `rules` entirely.

`summary_text` when `status == "ready"`: open with the window ("Over the last 30 days"), use only observational
verbs ("have tended to", "we've seen"), and render each detected rule with its integer percentage, its `n`, and its
95% CI as an integer percentage range. When `status == "collecting_data"` render the exact quantified placeholder
from the UI-SPEC — the sentence that states the two thresholds and then the actual days and openings so far. Build
the placeholder from `cfg` values and the report's own counts, never from hard-coded numbers duplicated from `cfg`.
Percentages are rendered with `round()` on `share * 100`.

Add `make_event_obs(...)` to `tests/unit/factories.py` (keyword-only, explicit values, no defaults that hide a clock)
and extend that module's `Named symbols:` docstring line.

`tests/fixtures/pattern/48h_heavy.json`: a JSON list of 100 `EventObs` records — exactly 36 with
`hours_before_service` inside `[46, 50]` and 64 spread over `[2, 120]` avoiding that band; `first_seen_at` values
spanning exactly 30 days so `days_of_history` is 30; `day_of_week`, `dow_local` and `hour_local` varied; a mix of
`duration_seconds` values and nulls. Generate it deterministically and commit the file — no generator at test time.

`tests/unit/test_pattern_stats.py` and `tests/unit/test_pattern_model.py`: assert every item in the `<behavior>`
block. Test names are full sentences naming the behaviour and the requirement, per the repo idiom. No test reads the
wall clock; every `now` is an explicit `datetime`.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_pattern_stats.py tests/unit/test_pattern_model.py -x -q` exits 0.
    - `uv run python -c "import json,pathlib; d=json.loads(pathlib.Path('tests/fixtures/pattern/48h_heavy.json').read_text()); print(len(d), sum(1 for e in d if 46 <= e['hours_before_service'] <= 50))"` prints `100 36`.
    - `uv run ruff check shared/pattern/ && uv run mypy shared/` exits 0.
    - `grep -v '^\s*#' shared/pattern/stats.py | grep -cE '^\s*(import|from) (numpy|scipy|statsmodels)\b'` equals 0.
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit/test_pattern_stats.py tests/unit/test_pattern_model.py -x -q</automated>
  </verify>
  <done>The 48-hour rule runs end to end on a committed 100-event corpus with an exact share, an exact Wilson pair and a rendered sentence carrying both.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Remaining rules, the gate boundary matrix and the purity gate</name>
  <files>shared/pattern/model.py, tests/fixtures/pattern/load_day.json, tests/fixtures/pattern/flat.json, tests/fixtures/pattern/sparse.json, tests/fixtures/pattern/gate_boundary.json, tests/unit/test_pattern_model.py, tests/unit/test_pattern_gating.py, tests/unit/test_pattern_summary_text.py, tests/unit/test_pattern_purity.py</files>
  <read_first>
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-CONTEXT.md` — D-106 (inventory-load day, cancellation peaks, duration quartiles, gating), D-106a
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-RESEARCH.md` §Validation Architecture → "Deterministic pattern corpus design" — the exact construction and assertion for each of the four fixtures plus the gate-boundary fifth
    - `.planning/phases/06-pattern-intelligence-frontend-pwa/06-UI-SPEC.md` §Copywriting Contract → "Pattern sentence rules" — the forbidden-word list and the reference sentence
    - `tests/unit/test_engine_purity.py` — the banned-token source-scan idiom (comment stripping, `SCANNED_FILES`, guard-the-guard) this plan's purity test copies
    - `shared/pattern/model.py` as written in Task 2
  </read_first>
  <behavior>
    - `load_day.json` (n=60; 30 events with `dow_local == 2`, 5 on each of the other six days): the load-day rule returns day 2 with ratio exactly 6.0 and detected True; evaluating the same corpus on `day_of_week` detects nothing, proving the two axes are separate.
    - A day with a 3x ratio but only 2 observations is NOT detected (the `load_day_min_obs` floor).
    - Cancellation peaks return exactly 3 bins; when two bins tie on count the earlier `hour_local` sorts first; when fewer than 3 distinct hours exist, only the populated bins are returned.
    - `flat.json` (n=60, uniform across every axis): `rules` is empty and `summary_text` contains no rule sentence and no hedged phrasing.
    - `sparse.json` (n=8 over 20 days): `status == "collecting_data"` (day count passes, event count fails) and `duration` is `None`.
    - `gate_boundary.json` drives the three-point boundary: 30 events over exactly 14 days → `ready`; the same corpus truncated to 29 events → `collecting_data`; the same 30 events compressed to 13 days → `collecting_data`.
    - `compute_pattern([], now, cfg)` returns `status == "collecting_data"`, `rules == ()`, `duration is None`, `n_events == 0`, `days_of_history == 0`, and the placeholder sentence — no exception.
    - `duration` is `None` when the count of non-null `duration_seconds` is below `duration_min_n`, and is the inclusive-method p25/p50/p75 with its `n` at or above it.
    - Two consecutive calls on the same corpus return equal reports (stable ordering).
  </behavior>
  <action>
Complete `compute_pattern` with the remaining three rules and pin the whole surface.

Inventory-load day: bucket events by `dow_local`, compare each day's count against the mean of the OTHER six days,
and detect when the ratio is at or above `cfg.load_day_ratio` and the day has at least `cfg.load_day_min_obs`
observations. Report the day and the ratio in `RuleFinding.detail` alongside the Wilson interval for that day's
share of all events. Add an inline comment at the bucketing line stating that this rule reads the observation
weekday and that using the service weekday here is the BC-11 defect.

Cancellation peaks: count events by `hour_local`, take the top `cfg.peak_bins` by count with ties broken by the
earlier hour (sort on `(-count, hour)` so the ordering is total and stable), and report each bin's share, `k`, `n`
and Wilson interval. Return fewer than `peak_bins` findings when fewer distinct hours are populated.

Duration: collect non-null `duration_seconds`, and when the count is at or above `cfg.duration_min_n` return a
`DurationSummary` from `quartiles(...)`; otherwise `None`.

Extend `summary_text` to render a sentence per detected rule in a fixed order (48-hour rule, load day, peaks,
duration), each carrying its integer percentage and its `n`, and to append the duration sentence in the reference
shape ("stays open for about N minutes (median of K openings)") with the median converted from seconds to whole
minutes. Do not add a sentence for any rule absent from `rules`.

Build the four remaining fixtures exactly to the RESEARCH construction table and commit them.

`tests/unit/test_pattern_gating.py` drives the three-point boundary matrix and the empty-input case.
`tests/unit/test_pattern_summary_text.py` renders `summary_text` for all five corpora and asserts: every detected
rule's percentage appears with its `n` in the same sentence; no undetected rule name appears anywhere in the string;
and the rendered text contains none of the UI-SPEC forbidden words. Scan the RENDERED OUTPUT for the forbidden list,
never the source file, so the contract cannot be satisfied or broken by a comment.
`tests/unit/test_pattern_purity.py` copies `tests/unit/test_engine_purity.py`: strip full-line comments, scan
`shared/pattern/model.py` and `shared/pattern/stats.py` for the banned wall-clock / entropy / I/O tokens, and include
the guard-the-guard assertion that the scanned file list is non-empty and both files are present.
  </action>
  <acceptance_criteria>
    - `uv run pytest tests/unit/test_pattern_model.py tests/unit/test_pattern_gating.py tests/unit/test_pattern_summary_text.py tests/unit/test_pattern_purity.py -x -q` exits 0.
    - `uv run python -c "import json,pathlib;d=json.loads(pathlib.Path('tests/fixtures/pattern/load_day.json').read_text());print(len(d), sum(1 for e in d if e['dow_local']==2))"` prints `60 30`.
    - `uv run python -c "import json,pathlib;print(len(json.loads(pathlib.Path('tests/fixtures/pattern/sparse.json').read_text())))"` prints `8`.
    - `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
    - `uv run pytest tests/unit -x -q -W error::RuntimeWarning` exits 0 (the whole unit suite still green).
  </acceptance_criteria>
  <verify>
    <automated>uv run pytest tests/unit -x -q -W error::RuntimeWarning</automated>
  </verify>
  <done>All four PATTERN-01 rules, the PATTERN-02 gate with its exact boundary, the honest-sentence contract and the purity gate are pinned by tests over five committed corpora.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| DB rows → pattern model | `availability_events` rows (written by the Phase 2 pipeline from scraped payloads) become `EventObs` values that drive user-facing claims |
| pattern model → user-facing prose | `summary_text` is rendered verbatim on the restaurant page and in notifications |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-06-01 | Tampering | `summary_text` rendered from model output | high | mitigate | Only detected rules are rendered; every percentage carries its `n` and CI; a rendered-output scan for the UI-SPEC forbidden-certainty words runs over all five corpora (Task 3) |
| T-06-02 | Information disclosure | `shared/pattern/model.py` logging | medium | mitigate | The module performs no logging and no I/O at all; the purity gate scans for it. Booking tokens present on `availability_events` are never carried into `EventObs` (the dataclass has no such field) |
| T-06-03 | Denial of service | unbounded corpus into `compute_pattern` | low | accept | The caller (06-02 `repo.load_observations`) bounds the read to a 30-day window per restaurant; the model is O(n) over that bounded set |
| T-06-04 | Repudiation | non-deterministic report | medium | mitigate | `now` is a parameter, ordering is total (`(-count, hour)`), and a stability test asserts two calls are equal — a report can always be reproduced from its inputs |
| T-06-SC | Tampering | python package installs | high | mitigate | This plan adds **no** dependency: `math` and `statistics` only. The acceptance criteria grep proves no numpy/scipy/statsmodels import. No package-manager install task exists, so no legitimacy checkpoint is required; the SUMMARY records "zero new dependencies" |
</threat_model>

<verification>
- `uv run pytest tests/unit -x -q -W error::RuntimeWarning` — whole unit suite green
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` — lint and strict types clean
- `uv run python -c "from tests.unit.test_phase6_preconditions import current_migration_head; print(current_migration_head())"` — the resolved Alembic head recorded in the SUMMARY for plan 06-02
</verification>

<success_criteria>
- Every Phase 4 / Phase 5 artifact this phase modifies is proven present, or the plan halted naming the upstream plan.
- `compute_pattern` detects all four PATTERN-01 rules on their corpora and detects none on `flat.json`.
- The PATTERN-02 gate flips at exactly 30 events and exactly 14 days, and one step below either threshold stays `collecting_data`.
- Every reported rule carries `n`, `ci_low`, `ci_high`; `summary_text` names only detected rules and contains no forbidden-certainty word.
- The purity gate is green and cannot pass vacuously.
</success_criteria>

<output>
Create `.planning/phases/06-pattern-intelligence-frontend-pwa/06-01-SUMMARY.md` when done.
Record in it: the resolved Alembic head (for 06-02's `down_revision`), the exact Wilson pair asserted, and the
statement that zero new Python dependencies were added.
</output>
