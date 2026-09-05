---
phase: 03-resy-playwright-fleet
plan: 02
subsystem: scheduling-kernel
tags: [resy, rate-limit, redis-lua, tier-cadence, backoff, jitter, redaction, prometheus, poll-02, poll-05]
status: complete

# Dependency graph
requires:
  - phase: 02-state-machine-event-pipeline
    provides: "shared/redis_keys.py key-registry + cast(Awaitable[T]) convention; set_nx_ex; LuaScheduler script_load/_evalsha_with_fallback; the module-scoped Redis 7.2 container fixture"
  - phase: 01-foundation-admin-pre-conditions-opentable-polling
    provides: "POLL_INTERVAL_SECONDS / POLL_JITTER_FRACTION; shared/telemetry.py::_redact_secrets and its four-key set; prometheus-client==0.25.0 pinned in uv.lock"
provides:
  - "shared.redis_keys :: RESY_BUDGET_LUA — the ONLY enforcement point for the publicly promised 80 req/min cap"
  - "shared.redis_keys :: tier_interval_seconds / effective_interval_seconds — POLL-02 tiers with the per-source clamp"
  - "shared.redis_keys :: jittered_score_ms / next_backoff_seconds / backoff_ttl_seconds"
  - "shared.redis_keys :: the Phase-3 key registry (rate:resy:{minute}, rate:resy:ctx:{ctx}:{venue}, canary:resy:{venue}, backoff:{source}:{rid}, resy:paused, watch:count, tier:override) — every key with a mandatory TTL constant"
  - "shared.redis_keys :: nine typed async helpers incl. canary_window_push (one MULTI/EXEC), so downstream Resy modules contain zero inline casts"
  - "shared/metrics.py — the single definition site for all seven Phase-3 Prometheus metrics"
  - "shared.telemetry :: _redact_secrets extended to the eight secret-bearing key names the Resy fleet introduces, plus proxy-credential masking"
affects: [03-03-pool, 03-04-adapter, 03-05-canary, 03-06-poller-gate, 04-notifier, 07-observability]

actuals:
  # chars/4 over the full contents of every changed source/test file (90_160 chars),
  # the same convention 03-01 used. The measure over the realized diff alone is ~18_700.
  tokens: 23000
  tasks: 3
  commits: 5

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A publicly promised rate limit is enforced in ONE Lua script at the scheduler before dispatch, never in the worker that makes the request — the worker is too late to be polite"
    - "A conservative refusal: cost 3 against cap 80 stops at 78 and leaves 2 unused rather than overshooting to 81. Never round in our own favour against somebody else's infrastructure"
    - "EXPIRE inside the same script as the INCRBY, fired only on the first increment of the window — a separate EXPIRE is two race windows and leaves ttl == -1 if the process dies between them"
    - "min(tier, baseline) then clamped UP to a per-source floor: a demand signal may only speed a source up, and the floor is applied last because the floor is the promise"
    - "A key-name redactor splits its match sets by ORIGIN: env-var names case-sensitively, HTTP header names case-insensitively (a header's casing is whatever the peer sent)"
    - "Credential masking rather than blanking where the non-secret half of a value is a real diagnostic (which proxy host was in play), failing closed on anything unparseable"
    - "One module-level definition site for every metric in the repo, with the double-import regression test written before any producer exists"
    - "Mutation-testing a new assertion matrix (flip >= to >, constant-ify the jitter, delete the cap) to prove it is non-vacuous before trusting it"

key-files:
  created:
    - shared/metrics.py
    - tests/integration/test_rate_budget_lua.py
    - tests/integration/test_redis_helpers_phase3.py
    - tests/unit/test_metrics_registry.py
    - tests/unit/test_tier_cadence.py
    - tests/unit/test_effective_interval.py
    - tests/unit/test_jitter_bounds.py
    - tests/unit/test_backoff_math.py
  modified:
    - shared/redis_keys.py
    - shared/telemetry.py
    - tests/unit/test_telemetry_redaction.py

key-decisions:
  - "The minute budget refuses BEFORE it increments, so a refusal consumes none of the budget and the job can be released at now + 5 s with the cap untouched — a refusal that consumed budget would let a busy minute starve itself"
  - "The EXPIRE fires only when `new == cost` (the first increment of the minute). Re-setting it on every call would slide the 90 s TTL forward on every poll and make one busy minute's counter effectively immortal"
  - "OpenTable's baseline and minimum are BOTH 90 s, so `min(tier, baseline)` makes ten watches a no-op there. Watches may only speed a source up; a 60 s OpenTable poll would break POLL-03's heatmap cadence, whose value is that every restaurant is sampled on the SAME interval"
  - "An out-of-range `tier:override` falls back to the COMPUTED tier rather than to tier 1. Tier 1 is the fastest rate — the one that breaks the promise — so an operator typo must never select it"
  - "An unknown source degrades to the 180 s baseline and the STRICTEST known floor (90 s) instead of raising: `AvailabilityRaw.source` is a Literal so the branch is unreachable today, and a poller that crashes on a bad hash value is a worse failure than one that polls slowly"
  - "The redactor splits into a case-SENSITIVE env-var set and a case-INSENSITIVE header set. Case-folding the env-var names too would have been simpler and wrong in the over-broad direction; leaving the header names case-sensitive would have been the leak research already reproduced"
  - "`RESY_PROXY_URL` is masked, not blanked, and fails CLOSED on anything it cannot parse as `scheme://…`. Which proxy host the fleet egressed through is a real diagnostic during a ban incident; the userinfo segment is a purchased subscription's password"
  - "`shared/metrics.py` is imported, never reloaded. The double-import test is written now, before any producer exists, because the failure is a ValueError at IMPORT that takes the poller down at start rather than at first scrape"

patterns-established:
  - "Pattern: an integration tracer that drives a whole DECISION (watch-count -> tier -> interval -> jitter -> budget -> floor) rather than a single primitive, so the seams between the pure math and the atomic Redis calls are exercised together"
  - "Pattern: assert the CORRECT prometheus sample name is a float BEFORE asserting the doubled-suffix name is None — `assert x is None` against a name that never existed passes forever while testing nothing"
  - "Pattern: an over-breadth guard beside every redaction assertion (`cookie_count` passes through), because a redactor that swallows diagnostics trains readers to ignore [REDACTED]"
  - "Pattern: every expected value in an arithmetic matrix is a literal copied from the requirement text, never re-derived from the function under test"
  - "Pattern: a distinct-values assertion beside every bounds assertion — a stubbed constant satisfies bounds-only checks"

requirements-completed: []
requirements-advanced: [POLL-02, POLL-05, POLL-06]  # all three left Pending — see Deviations

coverage:
  - id: T1
    description: "One Resy job's whole scheduling decision — watch:count -> tier -> effective interval -> jittered score -> minute budget -> per-context floor — runs end to end against a live Redis 7.2"
    requirement: POLL-05
    verification:
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_one_resy_job_decides_its_next_poll_end_to_end"
        status: pass
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_an_admin_override_wins_over_the_watch_count"
        status: pass
    human_judgment: false
  - id: T2
    description: "PROBE POLL-05/boundary — the budget grants at current + cost == cap, refuses at cap + 1, and a refusal consumes none of the budget"
    requirement: POLL-05
    verification:
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_the_budget_grants_when_current_plus_cost_equals_the_cap_exactly"
        status: pass
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_the_budget_refuses_at_cap_plus_one_and_consumes_nothing"
        status: pass
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_a_cost_of_one_still_fits_where_a_cost_of_three_did_not"
        status: pass
    human_judgment: false
  - id: T3
    description: "PROBE POLL-05/adjacency — the per-context floor grants exactly once; SET NX EX returns None (not False) for the loser, and eight simultaneous claims yield one winner"
    requirement: POLL-05
    verification:
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_the_context_floor_grants_once_and_then_returns_falsy"
        status: pass
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_two_simultaneous_claims_on_one_context_venue_pair_yield_one_winner"
        status: pass
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_the_context_floor_ttl_does_not_slide"
        status: pass
    human_judgment: false
  - id: T4
    description: "PROBE POLL-05/precision — epoch_minute is now_ms // 60_000, the TTL is set on the first increment only, jitter is integer and never nets negative, backoff TTL is exactly 2x"
    requirement: POLL-05
    verification:
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_the_ttl_is_set_on_the_first_increment_only"
        status: pass
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_the_epoch_minute_is_integer_division_of_now_ms"
        status: pass
      - kind: unit
        ref: "tests/unit/test_jitter_bounds.py#test_the_score_is_an_integer_millisecond"
        status: pass
      - kind: unit
        ref: "tests/unit/test_backoff_math.py#test_the_ttl_is_exactly_twice_the_backoff_it_holds"
        status: pass
    human_judgment: false
  - id: T5
    description: "PROBE POLL-05/concurrency — 30 concurrent calls at cost 3 against cap 80 grant exactly 26 and refuse 4, and the counter carries a TTL after the FIRST increment"
    requirement: POLL-05
    verification:
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_thirty_concurrent_polls_at_cost_three_grant_exactly_twenty_six"
        status: pass
      - kind: integration
        ref: "tests/integration/test_rate_budget_lua.py#test_the_counter_never_exceeds_the_cap_under_concurrency"
        status: pass
    human_judgment: false
  - id: T6
    description: "POLL-02 tier boundaries: 60 / 180 / 600 with both sides of the 2/3 and 9/10 thresholds asserted, and a negative watch count degrading to the slowest tier"
    requirement: POLL-02
    verification:
      - kind: unit
        ref: "tests/unit/test_tier_cadence.py#test_tier_interval_seconds_matches_the_literal_poll_02_tiers"
        status: pass
      - kind: unit
        ref: "tests/unit/test_tier_cadence.py#test_a_negative_watch_count_degrades_to_the_slowest_tier_rather_than_raising"
        status: pass
      - kind: command
        ref: "mutation: `>= 10` -> `> 10` fails 2 tests (executed 2026-09-05)"
        status: pass
    human_judgment: false
  - id: T7
    description: "The per-source clamp: OpenTable is 90 s at every watch count, Resy clamps a sub-45 s baseline back up, and an override still passes the clamp"
    requirement: POLL-02
    verification:
      - kind: unit
        ref: "tests/unit/test_effective_interval.py#test_opentable_always_polls_at_ninety_seconds"
        status: pass
      - kind: unit
        ref: "tests/unit/test_effective_interval.py#test_a_caller_supplied_baseline_is_clamped_up_to_the_poll_05_floor"
        status: pass
      - kind: unit
        ref: "tests/unit/test_effective_interval.py#test_an_absent_or_out_of_range_override_falls_back_to_the_computed_tier"
        status: pass
    human_judgment: false
  - id: T8
    description: "Jitter is +/- 15 %, integer, never nets negative, and actually varies (>100 distinct values in 1000 seeded draws)"
    requirement: POLL-02
    verification:
      - kind: unit
        ref: "tests/unit/test_jitter_bounds.py#test_every_draw_lies_inside_the_fifteen_percent_band"
        status: pass
      - kind: unit
        ref: "tests/unit/test_jitter_bounds.py#test_no_draw_ever_schedules_a_poll_at_or_before_now"
        status: pass
      - kind: unit
        ref: "tests/unit/test_jitter_bounds.py#test_the_jitter_actually_varies"
        status: pass
      - kind: command
        ref: "mutation: constant jitter fails 8 tests (executed 2026-09-05)"
        status: pass
    human_judgment: false
  - id: T9
    description: "The backoff ladder is exactly 180/360/720/1440/1800/1800 with the ceiling engaging between n=3 and n=4"
    requirement: POLL-02
    verification:
      - kind: unit
        ref: "tests/unit/test_backoff_math.py#test_the_backoff_ladder_from_a_one_hundred_eighty_second_interval"
        status: pass
      - kind: unit
        ref: "tests/unit/test_backoff_math.py#test_the_backoff_never_exceeds_the_ceiling_for_any_input"
        status: pass
      - kind: command
        ref: "mutation: removing the 1800 s cap fails 9 tests (executed 2026-09-05)"
        status: pass
    human_judgment: false
  - id: T10
    description: "Every one of the eight secret-bearing key names research B-6 reproduced leaking is redacted, case-insensitively, and RESY_PROXY_URL keeps its host while masking credentials"
    requirement: POLL-06
    verification:
      - kind: unit
        ref: "tests/unit/test_telemetry_redaction.py#test_redacts_every_secret_bearing_key_case_insensitively (16 params)"
        status: pass
      - kind: unit
        ref: "tests/unit/test_telemetry_redaction.py#test_proxy_url_keeps_its_host_but_masks_the_credentials"
        status: pass
      - kind: unit
        ref: "tests/unit/test_telemetry_redaction.py#test_a_malformed_proxy_url_is_redacted_wholesale_rather_than_parsed"
        status: pass
      - kind: unit
        ref: "tests/unit/test_telemetry_redaction.py#test_benign_keys_pass_through_untouched"
        status: pass
    human_judgment: false
  - id: T11
    description: "shared/metrics.py imports twice without Duplicated timeseries, and poll_latency_seconds declares buckets past 10 s"
    requirement: POLL-06
    verification:
      - kind: unit
        ref: "tests/unit/test_metrics_registry.py#test_importing_the_module_twice_in_one_process_raises_nothing"
        status: pass
      - kind: unit
        ref: "tests/unit/test_metrics_registry.py#test_poll_latency_seconds_has_a_bucket_above_ten_seconds"
        status: pass
      - kind: unit
        ref: "tests/unit/test_metrics_registry.py#test_the_doubled_suffix_sample_name_is_the_trap_not_the_metric"
        status: pass
    human_judgment: false
  - id: T12
    description: "The nine typed Redis helpers execute against a live Redis, incl. canary_window_push landing four commands as one transaction"
    requirement: POLL-06
    verification:
      - kind: integration
        ref: "tests/integration/test_redis_helpers_phase3.py#test_the_canary_window_never_grows_past_its_configured_size"
        status: pass
      - kind: integration
        ref: "tests/integration/test_redis_helpers_phase3.py#test_a_concurrent_reader_never_sees_a_window_longer_than_the_bound"
        status: pass
      - kind: integration
        ref: "tests/integration/test_redis_helpers_phase3.py#test_a_backoff_key_round_trips_with_a_ttl_of_twice_its_value"
        status: pass
    human_judgment: false

metrics:
  duration_minutes: 34
  completed: 2026-09-05
  unit_tests_before: 379
  unit_tests_after: 535
  integration_tests_before: 62
  integration_tests_after: 86
---

# Phase 3 Plan 2: Scheduling Kernel, Metrics & Redaction Summary

The 80 req/min cap and the 45 s floor stopped being prose in a README and became one Lua
script and one `SET NX EX`, verified under 30-way concurrency against a live Redis; and the
redactor learned every secret name the Resy fleet will handle **before a single line of
cookie-handling code exists**.

## What Was Built

**`shared/redis_keys.py`** gained the Phase-3 key registry, the pure scheduling arithmetic
and one Lua script. Three properties are worth naming.

*The budget refuses before it increments.* `RESY_BUDGET_LUA` GETs, compares, and only then
`INCRBY`s. A refusal therefore consumes nothing, which is what lets the poller release a
refused job back at `now + RATE_REFUSAL_RETRY_MS` with the minute's budget intact. The
refusal is deliberately conservative — cost 3 against cap 80 stops at 78 and leaves 2 unused
rather than overshooting to 81. Never round in our own favour against somebody else's
infrastructure.

*The `EXPIRE` lives inside the script, and fires once.* A bare `INCR` followed by a separate
`EXPIRE` from Python is two round trips and two race windows; research verified that the
counter is left with `ttl == -1` if the process dies between them, and under the pinned
`maxmemory-policy noeviction` that key is permanent — it would refuse every Resy poll for the
rest of the server's life. Equally, the `EXPIRE` fires only when `new == cost` (the first
increment of the minute); re-setting it on every call would slide the 90 s window forward on
every poll and make one busy minute's counter effectively immortal.

*The clamp is `min`, and the floor is applied last.* `effective_interval_seconds` is
`max(min(tier, baseline), minimum)`. `min` and not `max` because watches may only speed a
source **up**: OpenTable's baseline and minimum are both 90 s, so ten watches on an OpenTable
restaurant are a deliberate no-op rather than a 60 s poll that would break POLL-03's heatmap
cadence — whose whole value is that every restaurant is sampled on the *same* interval. The
floor goes last because the floor is the promise: no baseline argument, no tier and no admin
override can buy a rate below Resy's 45 s.

**`shared/telemetry.py`** — `_redact_secrets` now carries two match sets with different
rules, split by origin. Env-var names stay case-**sensitive** (an env var's name is its exact
spelling). The eight Phase-3 names are matched case-**insensitively**, because they are HTTP
header names as much as env vars and a header's casing is whatever the peer sent — `Cookie`,
`cookie` and `COOKIE` are one header. Research reproduced six of these eight leaking in full
against the old redactor, including the proxy URL with embedded credentials.

`RESY_PROXY_URL` is **masked rather than blanked**: which proxy host the fleet egressed
through is a real diagnostic during a soft-ban incident, while the userinfo segment is a
purchased subscription's password. The masker fails **closed** — a non-string, or anything
that does not parse as `scheme://…`, is redacted wholesale rather than emitted on the hope
that it carries no password.

The docstring now records the limitation this design cannot escape: the redactor is
key-name based and cannot save a caller who logs a whole header mapping under a benign key.
The ban on logging `raw_response` or a header dict at INFO is the control; this function is
the backstop. It is also deliberately not over-broad — `cookie_count` is a count, and a
redactor that swallowed it would destroy the diagnostics an incident depends on while
training readers to ignore `[REDACTED]`.

**`shared/metrics.py`** (new) defines all seven Phase-3 metrics exactly once at module scope
against the default `REGISTRY`, with a prominent comment stating that this file is imported
and never reloaded, and that Phases 4-7 append here rather than defining elsewhere.
`poll_latency_seconds` carries explicit buckets to 60 s — the library default stops at 10.0,
and a three-request Playwright poll that exceeds it would land in `+Inf`, invisible to every
latency percentile exactly when the fleet is degrading.

**`tests/integration/test_rate_budget_lua.py`** is the tracer: one Resy job's whole
scheduling *decision*, not one primitive. It seeds `watch:count` and `tier:override`, reads
them back through the new helpers, computes the interval and the jittered score, then calls
the budget script and the floor — so the seams between the pure math and the atomic Redis
calls are exercised together, which is where the mistakes actually live.

## Key Decisions

1. **A refusal consumes no budget, and the EXPIRE fires only on the first increment.** Both
   are single-line properties of the script with multi-hour failure modes: a budget-consuming
   refusal would let a busy minute starve itself, and a sliding TTL would make a counter
   immortal.

2. **An out-of-range `tier:override` falls back to the computed tier, not to tier 1.** Tier 1
   is the fastest rate — the one that breaks the promise. An operator typo (`4`, `0`, an empty
   string) must never be the input that selects it.

3. **An unknown source degrades rather than raises.** It gets the 180 s baseline and the
   strictest known floor (90 s), so an unrecognised platform can never be polled faster than a
   recognised one. `AvailabilityRaw.source` is a Literal, so the branch is unreachable today;
   it exists because a poller that crashes on a bad value is a worse failure than one that
   polls slowly (T-03-09).

4. **The redactor's two sets have deliberately different case rules.** Folding the env-var
   names too would have been simpler and wrong in the over-broad direction; leaving the header
   names case-sensitive would have preserved exactly the leak research reproduced.

5. **The metrics double-import test was written before any producer exists.** The failure is a
   `ValueError` at *import*, which takes the poller down at start rather than at first scrape —
   and this repo already evicts modules from `sys.modules` in integration teardown, so the
   trigger is one careless fixture away.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] Eight of the nine new Redis helpers had zero test coverage**
- **Found during:** plan-level verification, after Task 3
- **Issue:** Task 1 added nine typed helpers to `shared/redis_keys.py`; only `hget_field` was
  reachable from the tracer. The other eight (`incrby`, `getdel_str`, `lpush_sig`,
  `ltrim_window`, `lrange_window`, `set_str_ex`, `delete_key`, `canary_window_push`) would have
  shipped never having executed. These are exactly the wrappers where a mistake is invisible to
  the type checker: `cast(Awaitable[T], …)` *asserts* a return type to mypy without checking
  it, so a wrong `T`, a transposed argument or an `LTRIM 0, size` off-by-one all pass
  `mypy --strict` and fail only in production — in 03-05's canary and 03-06's poller gate,
  which are built directly on them. `canary_window_push` is the sharpest case: its entire
  reason to exist is that four commands land as ONE transaction, a property no unit test can
  observe.
- **Fix:** Added `tests/integration/test_redis_helpers_phase3.py` (12 tests) against the same
  container: 25 pushes leave exactly 20 entries, the head is the newest signature, `llen` never
  exceeds the bound across 40 pushes, the D-59 backoff round trip carries `TTL == 2x`, the
  reset `DEL` is idempotent, the fleet pause self-lifts at 900 s, and `getdel_str` consumes
  exactly once.
- **Files modified:** none — the fix is a new test file
- **Commit:** 4a52bd9

**2. [Rule 1 - Bug] `mypy --strict` rejected the backoff return as `Any`**
- **Found during:** Task 1
- **Issue:** `min(interval_seconds * 2**exponent, BACKOFF_MAX_SECONDS)` fails
  `no-any-return`: mypy types `int ** int` as `Any` because a negative exponent yields a float.
- **Fix:** Bound the product to an annotated `doubled: int` with a comment naming *why* the
  annotation is real rather than a silencer — the `max(0, …)` guard above it is what makes the
  integer result true. A `# type: ignore` here would have hidden the genuine negative-exponent
  case, which `test_a_negative_failure_count_is_treated_as_the_first_failure` now pins.
- **Files modified:** `shared/redis_keys.py`
- **Commit:** ac8676d

**3. [Rule 1 - Bug] The first proxy masker redacted a credential-free URL wholesale**
- **Found during:** Task 2 (GREEN), caught by `test_a_proxy_url_without_credentials_is_left_readable`
- **Issue:** The regex required a `userinfo@` segment, and the no-match fallback redacted any
  value containing `:` — which every URL contains (`http:`, `:8080`). A perfectly safe
  `http://proxy.example.com:8080` came out as `[REDACTED]`, destroying the one diagnostic the
  masking design exists to preserve.
- **Fix:** Made the userinfo group optional and branched on `match.group(2) is None`: a
  well-formed URL with no credentials is returned untouched, an unparseable value still fails
  closed. The over-breadth was caught only because the test file asserts the *readable* case
  alongside the redacted ones.
- **Files modified:** `shared/telemetry.py`
- **Commit:** 33b9d6e

### Additions beyond the plan's named artifacts

- **`tests/integration/test_redis_helpers_phase3.py`** — see Rule 2 above. Kept as a separate
  file rather than appended to `test_rate_budget_lua.py`, whose subject is the budget script.
- **`resy_auth_mode` gauge and `POLL_LATENCY_BUCKETS`** — the gauge is named in the plan's
  artifact table; the bucket tuple is exported as a named constant so Phase 7's Grafana panels
  can reference the same boundaries rather than re-typing them.
- **A mutation check on the Task-3 matrix.** Three mutations were applied to
  `shared/redis_keys.py` and reverted: `>= 10` → `> 10` (2 failures), a constant jitter
  (8 failures), and a removed 1800 s cap (9 failures). The matrix is non-vacuous. The working
  tree was verified clean (`git diff --stat` empty) before the commit.
- **`test_metrics_are_defined_at_module_scope_not_inside_a_function`** — a source-level scan
  off disk, because the defect this file guards is a definition that *runs* twice, and a
  source gate catches it before the second call ever happens.

**4. [Rule 1 - Bug] POLL-02 / POLL-05 / POLL-06 left Pending rather than marked complete**
- **Found during:** state update
- **Issue:** The plan frontmatter declares `requirements: [POLL-02, POLL-05, POLL-06]`, and
  `execute-plan` marks every frontmatter requirement complete. But this plan builds the
  *enforcement primitives*, not the enforcement: nothing calls `RESY_BUDGET_LUA` yet (03-06's
  poller gate does), nothing sets `scrape_ban_total` (03-05's canary does), and no adapter
  exists (03-04). POLL-02 additionally requires backoff wired to real 429/503 responses.
  Marking them Done would make the traceability table claim capabilities the codebase does not
  have, and the phase's own acceptance criteria would then have no open requirement behind
  them.
- **Fix:** All three left `Pending`, following the 03-01 and 02-01 precedent. No
  `requirements mark-complete` call was made.
- **Files modified:** none — the correction is the ABSENCE of the call
- **Commit:** this plan's docs commit

### Checkpoints

None. This plan is fully autonomous (`autonomous: true`, no checkpoint task) and no
authentication gate was reached — nothing here touches a Resy credential, only the key *names*
under which one must never be logged.

## Known Stubs

None.

Seven metrics and five Redis keys are defined here with no producer yet, which is the plan's
explicit purpose — `shared/metrics.py` is the single definition site that 03-03 through 03-06
and Phases 4-7 import from, and defining a metric at its first use is precisely the
`Duplicated timeseries` defect this plan exists to prevent. Every one of them is *executed* by
a test (the gauges are set and read back through `get_sample_value`; every key helper round
trips against a live Redis), so none is unverified surface. No hardcoded empty value, no
placeholder string and no unwired component was introduced.

`.planning/WINDOWS.md` gained no new entry: no stub, no skipped test, and no unrun `<verify>`.
Entry 1 (the `[ASSUMED]` Resy `/4/find` shape from 03-01) is untouched by this plan.

## Threat Flags

None. Every file this plan touched is covered by the plan's own `<threat_model>`. No new
network endpoint, auth path or file access pattern was introduced; the only trust boundary
this plan moves is the *logging* one, and it moves it in the safe direction (T-03-05
mitigated: eight previously-leaking key names now redacted, with one assertion per key).

The threat register's `mitigate` dispositions were all applied: T-03-05 (redaction, Task 2),
T-03-06 (cap in one atomic script, Task 1), T-03-07 (every new key carries an explicit TTL
constant), T-03-08 (single metric definition site plus the double-import test), T-03-09
(negative/absent/non-integer watch counts degrade to the slowest tier rather than raising).
T-03-SC holds: no new package was added.

## Verification

| Gate | Result |
|------|--------|
| `uv run ruff check .` | pass |
| `uv run mypy shared/ services/ scripts/` | pass (45 source files, was 44) |
| `uv run pytest tests/unit -q` | 535 passed in 0.89 s (was 379; +156) |
| `uv run pytest tests/integration -q -p no:cacheprovider` | 86 passed (was 62; +24) |
| `uv run pytest tests/integration/test_rate_budget_lua.py -q` | 12 passed |
| `uv run pytest tests/unit/test_no_setnx_expire_pairs.py -q` | 3 passed — the budget is one Lua script, the floor one `SET NX EX` |
| `uv run python -c "…tier_interval_seconds…"` | prints `60 180 600 90 60` (the plan's literal expectation) |
| `uv run python -c "import importlib, shared.metrics…"` | prints `ok` |
| `grep -c "cast(Awaitable" shared/redis_keys.py` | 9 (pre-plan: 1) |
| `grep -c "def test_" tests/unit/test_telemetry_redaction.py` | 14 (pre-plan: 5) |
| mutation check (3 mutations, reverted) | 2 / 8 / 9 failures respectively — matrix non-vacuous |

## TDD Gate Compliance

Task 2 followed RED → GREEN with the RED commit verified failing first:

| Task | RED | GREEN |
|------|-----|-------|
| 2 (redaction + metrics) | 8baabc3 — 21 redaction failures, and a collection error on `ModuleNotFoundError: No module named 'shared.metrics'` | 33b9d6e |

**Task 3 has no RED commit, and this is by the plan's own construction.** Its `<read_first>`
names "shared/redis_keys.py (the functions written in Task 1)" — the arithmetic it tests was
shipped by the tracer task, so a failing-first commit was not available. The fail-fast rule
("if a test passes unexpectedly during RED, stop and investigate") was applied: the passes
were *expected*, and the investigation took the form of the mutation check recorded above,
which proves the matrix would have failed against a wrong implementation. Task 1 is a
`type="tracer"` task and is not marked `tdd="true"`, so it carries no RED requirement; its
feedback gate ran autonomously and its `<verify>` was re-run green (12 passed) before any
expansion task began.

## Notes for Next Plan (03-03 and beyond)

- **`RESY_BUDGET_LUA` must be loaded with `script_load` and called through a NOSCRIPT
  fallback**, exactly as `shared/scheduler/lua.py::_evalsha_with_fallback` does. A bare
  `evalsha` breaks after a Redis restart or a `SCRIPT FLUSH`. The tracer loads it directly
  because a test owns its own container; production code must not copy that shortcut.
- **The budget is charged per REQUEST, not per poll.** `cost` is the number of `/4/find`
  requests the poll will make (typically 3, one per date). Phase 2's confirmation re-poll
  counts against the same budget (D-65) — 03-06 must charge it too, or the cap is a fiction.
- **`resy_rate_budget_remaining` is the third element of the script's return value.** Setting
  the gauge from it costs nothing and is the only way Grafana sees headroom; 03-06 should do it
  on every call, granted or refused.
- **`resy_auth_mode` exists because a silently anonymous fleet still returns `200 OK`**, which
  is indistinguishable from a soft ban at the response level. 03-03's pool must set it after
  cookie load, or 03-05's canary will attribute an auth failure to a ban.
- **`effective_interval_seconds` reaches production only as a ZSET score** through
  `_next_poll_score` (03-06). It must never become an `asyncio.sleep` — that burns a pool slot
  and a worker task, and `tests/unit/test_no_inline_sleep.py` already scans for it.
- **`watch:count` and `tier:override` are read as `bytes | None`.** The parse to `int` belongs
  at the call site with a defensive default (0 / `None`); `tier_interval_seconds` tolerates a
  negative but not a `ValueError` from `int(b"")`.
- **`shared/metrics.py` must not be evicted from `sys.modules` by any fixture.** If a future
  integration teardown needs to reset state, reset the metric *values*, never the module.

## Self-Check: PASSED

All eleven claimed files exist on disk (8 created, 3 modified) and all five claimed commits
are reachable in `git log --all`. Verified 2026-09-05.
