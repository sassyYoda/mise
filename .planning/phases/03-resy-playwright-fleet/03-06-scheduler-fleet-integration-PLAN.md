---
phase: 03-resy-playwright-fleet
plan: 06
type: execute
wave: 4
depends_on: [03-01, 03-02, 03-03, 03-05]
files_modified:
  - services/poller/scheduler.py
  - services/poller/main.py
  - services/poller/publisher.py
  - tests/integration/test_release_precedence.py
  - tests/integration/test_per_context_floor.py
  - tests/integration/test_429_backoff_and_recycle.py
  - tests/integration/test_ban_reaction.py
  - tests/integration/test_fleet_pause.py
  - tests/integration/test_resy_e2e_state_machine.py
autonomous: true
requirements: [POLL-02, POLL-05, POLL-06]

estimate:
  tokens: 72000
  raw_tokens: 72000
  tasks: 4
  confidence: low

must_haves:
  truths:
    - "SC3: a stub serving 429 causes the claimed job to be released at `now + backoff_seconds * 1000` AND the serving context to be recycled, both observable within a single poll cycle — asserted by reading the `sched:polls` score and `resy_context_recycles_total` after one iteration (D-59, D-60)."
    - "`poll_loop` dispatches through the `{source: adapter}` registry instead of an inline `if source ==` branch, and an unknown source is DROPPED from `sched:polls:inflight` rather than left to be re-enqueued by the reaper forever (D-63, research §Pattern 1)."
    - "Release precedence is exactly: an active `backoff:{source}:{rid}` wins and the expedite flag is still `GETDEL`'d so it cannot fire later; otherwise the expedite flag gives `now + CONFIRM_DELAY_MS`; otherwise `now + jitter(effective_interval_seconds(...))` (D-59, research §Pattern 2)."
    - "Pre-dispatch gates run BEFORE any browser work and each RELEASES rather than drops: `resy:paused` present -> `now + 60_000`; global minute budget refused -> `now + 5_000` with no budget consumed; no context passes the 45 s floor for this venue -> `now + 5_000` (D-65, D-68)."
    - "PROBE POLL-02: a successful Resy poll DELetes `backoff:{source}:{rid}`, so the next interval returns to the tier cadence; consecutive failures escalate `min(interval * 2 ** n, 1800)` and the key's TTL is twice its value so a stalled job self-heals."
    - "A canary ban increments `scrape_ban_total{source=\"resy\",reason=...}` (read via `get_sample_value` with the correct sample name), publishes `polls.completed` with `status=\"banned\"` and the serving `context_id`, poisons the context for recycle, and applies backoff — and the state machine marks the restaurant UNKNOWN rather than treating it as a success (D-67, D-67a)."
    - "When every context is poisoned inside a 5-minute window the fleet sets `resy:paused` with a 900 s TTL, the scheduler dispatches zero Resy polls while it exists, and `resy_fleet_paused` is logged at ERROR (D-68)."
    - "SC5 at the integration tier: a Resy `availability.raw` message published by the real publisher produces an `availability.events` message through the running state machine, with `PARSER_REGISTRY` holding exactly one new key and no source name appearing in `services/state_machine/engine.py` (D-67a restatement of SC5)."
    - "`main.py` runs `poll_workers()` concurrent `poll_loop` tasks over the single ZSET — safe without further change because the claim Lua is atomic — starts the Prometheus HTTP server on `METRICS_PORT`, constructs the pool only when `RESY_ENABLED` is true, and shuts both down on every exit path (D-69, D-72)."
  artifacts:
    - tests/integration/test_429_backoff_and_recycle.py
    - tests/integration/test_release_precedence.py
    - tests/integration/test_fleet_pause.py
    - tests/integration/test_resy_e2e_state_machine.py
  key_links:
    - "`ADAPTERS[source]` (03-05 registry) -> `poll_loop` dispatch — the replacement for the inline branch; a missing key must `drop()` the job, never `continue` past it."
    - "`RESY_BUDGET_LUA` + `set_nx_ex(rate_ctx_venue_key(...))` -> the pre-dispatch gate -> `scheduler.release(job, now + 5000)` — the enforcement point for the two limits the public README promises; a bypass here makes the README false."
    - "`ban_verdict` (03-05) -> `scrape_ban_total` + `PollCompleted(status='banned', context_id=...)` -> `consumer._handle_completed` (03-01) -> `mark_unknown` — the full ban reaction chain across three plans."
    - "`start_http_server(metrics_port())` -> Phase 7 Grafana scrape — the only externally visible surface this phase adds."
  prohibitions:
    - "MUST NOT dispatch a Resy request that would take the fleet past 80 requests in an epoch minute across all contexts, or past one request per 45 seconds for a given (restaurant, context) — these are limits the project's public README commits to, and exceeding them is a broken promise, not a tuning choice."
---

<objective>
Wire the fleet into the scheduler: registry dispatch, pre-dispatch rate and pause gates, tier-based
release scores with backoff precedence, the ban reaction, concurrent workers, and the metrics
endpoint.

Purpose: this is where POLL-02's cadence and POLL-05's caps stop being primitives and start being
enforced, and where SC3 and SC5 become demonstrable. Every wait is a ZSET score — the scheduler
exists precisely so no worker ever sleeps to be polite.
Output: an extended `poll_loop`, a Resy-aware `main.py` lifespan, and the six integration tests that
read like the demo.
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
  <name>Task 1: End-to-end tracer (SC3) — a simulated 429 becomes a backoff score and a context recycle in one cycle</name>
  <precondition>`make browsers` (03-04) has been run and a Docker-compatible runtime is reachable for the Redis testcontainer.</precondition>
  <files>services/poller/scheduler.py, tests/integration/test_429_backoff_and_recycle.py</files>
  <read_first>
    - services/poller/scheduler.py in full (lines 30-36 the hard-coded interval constants; 62-78 the `drop()` malformed-job pattern the fixer added; 94-106 the inline source branch; 107-133 the error taxonomy and the `finally` latency block; 147-158 the release path with the expedite hook)
    - shared/scheduler/lua.py (`claim`, `release`, `drop`, `consume_expedite`)
    - shared/redis_keys.py (everything added in 03-02: `RESY_BUDGET_LUA`, `rate_minute_key`, `rate_ctx_venue_key`, `backoff_key`, `RESY_PAUSED_KEY`, `WATCH_COUNT_HASH`, `TIER_OVERRIDE_HASH`, `effective_interval_seconds`, `jittered_score_ms`, `next_backoff_seconds`, `backoff_ttl_seconds`, `RATE_REFUSAL_RETRY_MS`, `FLEET_PAUSE_RETRY_MS`)
    - services/poller/sources/registry.py, pool.py, adapter.py, canary.py (03-05)
    - shared/metrics.py (03-02)
    - tests/integration/test_poller_expedite_release.py and test_scheduler_claim_release.py (the driving pattern for one poll iteration against a live Redis)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pattern 1, §Pattern 2, §Pattern 3 (a full recycle measured ~5 ms, so SC3 is never at risk), §Pattern 5 (429 is RETURNED, not raised, so backoff is triggered from `response.status`), §Pitfall 4
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-59, §D-63, §D-65
  </read_first>
  <action>
Restructure `services/poller/scheduler.py` around the registry and the gates, keeping every existing
OpenTable behaviour byte-identical in effect.

Change `_next_poll_score(now_ms)` to `_next_poll_score(now_ms, interval_seconds)` delegating to
`jittered_score_ms`, and delete the two module-level interval constants it closed over — the Resy
baseline and the tier result must both flow through the parameter. Every existing OpenTable call site
passes `POLL_INTERVAL_SECONDS`, so the 90 s +/- 15 % behaviour is unchanged.

Replace the inline `if source == "opentable"` branch with a lookup in the `ADAPTERS` mapping passed
into `poll_loop`. An unregistered source must `await scheduler.drop(job)` and log at ERROR — the
current `else` branch logs and falls through to the release path, which keeps a permanently
unpollable descriptor cycling forever.

Add the pre-dispatch gate block, running after the descriptor is parsed and BEFORE any adapter call,
for Resy jobs only. In order: if `RESY_PAUSED_KEY` exists, release at `now + FLEET_PAUSE_RETRY_MS`
and continue; if the budget Lua refuses the request cost for this poll, release at
`now + RATE_REFUSAL_RETRY_MS` and continue (the refusal consumes no budget by construction); if
`pool.acquire(venue_id)` returns None because every idle context is still inside its 45 s floor for
this venue, release at `now + RATE_REFUSAL_RETRY_MS` and continue. Each gate RELEASES — a `drop` here
would delete a perfectly good job, and a bare `continue` would leak it into the inflight set.

Extend the release path with the D-59 precedence: read `backoff:{source}:{rid}`; when present,
compute the score from it AND still `consume_expedite(job)` so a stale flag cannot fire later; when
absent, keep today's expedite-then-jitter logic but source the interval from
`effective_interval_seconds(source, watches, override)` with the watch count and override read from
the two Redis hashes (defaulting to 0 and None). On a 429 or 503 response status, write the next
backoff value with its `2 * value` TTL and poison the serving context; on a successful poll, DELete
the backoff key so the tier cadence resumes immediately.

Record the poll outcome through `shared/metrics.py` (`poll_total`, `poll_latency_seconds`,
`resy_rate_budget_remaining`) and pass the serving `context_id` through to the publisher.

Write the tracer `tests/integration/test_429_backoff_and_recycle.py` so it reads like the SC3 demo:
seed one `resy:{id}` job, point `RESY_API_BASE` at the stub, set the stub to `rate_limited`, run ONE
`poll_loop` iteration, then assert — in one test — that the job's `sched:polls` score is at least
`now + baseline_interval * 1000`, that `backoff:resy:{id}` exists with a TTL of twice its value, that
`resy_context_recycles_total` increased with the rate-limit reason, and that the pool reports a
different context id for the same slot than before. Assert the elapsed wall time of the iteration is
under two seconds, proving the recycle happened within the cycle rather than through a wait.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_429_backoff_and_recycle.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_429_backoff_and_recycle.py -q -p no:cacheprovider` exits 0 (or skips with a documented environment guard).
    - `uv run pytest tests/integration/test_poller_smoke.py tests/integration/test_poller_expedite_release.py tests/integration/test_scheduler_claim_release.py -q -p no:cacheprovider` exits 0 — every pre-existing OpenTable scheduler behaviour is preserved.
    - `uv run pytest tests/unit -q` exits 0.
    - `uv run pytest tests/unit/test_no_inline_sleep_resy.py -q` exits 0 — no wait was introduced by the gates.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>A rate-limited response becomes a scheduler score and a fresh context within one iteration, with no OpenTable behaviour disturbed.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Release precedence and the two rate gates, proven against a live Redis</name>
  <files>tests/integration/test_release_precedence.py, tests/integration/test_per_context_floor.py, services/poller/scheduler.py</files>
  <read_first>
    - services/poller/scheduler.py (as restructured in Task 1)
    - shared/redis_keys.py (`RESY_BUDGET_LUA`, `set_nx_ex`, `RESY_CTX_FLOOR_SECONDS`, `RATE_REFUSAL_RETRY_MS`)
    - tests/integration/test_expedite_lua.py (the Lua-against-container assertion style) and tests/integration/test_poller_expedite_release.py (driving one release)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pattern 2 (the precedence order and that the flag must still be consumed), §Pattern 6 (verified budget numbers: cost 3 / cap 80 grants 26; `SET NX EX 45` returns `None` on the second attempt and does not slide the TTL)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-59, §D-65
  </read_first>
  <behavior>
    - Backoff present + expedite flag set -> released at the backoff score, and `sched:expedite:{job}` is gone afterwards (the flag was consumed, not left to fire).
    - Backoff absent + expedite flag set -> released at `now + CONFIRM_DELAY_MS`.
    - Backoff absent + no flag, `watch:count` 12 -> released inside `now + 60 s +/- 15 %` for Resy and `now + 90 s +/- 15 %` for OpenTable.
    - `tier:override` = 3 with `watch:count` 12 -> released on the 600 s tier, clamped by the source rules.
    - A successful poll after a backoff -> `backoff:{source}:{rid}` no longer exists.
    - Budget exhausted for the current minute -> the job is released at `now + 5_000`, the adapter is never called, and the minute counter is unchanged by the refusal.
    - Every idle context inside the 45 s floor for the venue -> released at `now + 5_000`, adapter never called; after the floor expires the next iteration dispatches normally.
    - In every gate case the job is in `sched:polls` and absent from `sched:polls:inflight` afterwards — no path leaks a claimed job.
  </behavior>
  <action>
Write `tests/integration/test_release_precedence.py` and `tests/integration/test_per_context_floor.py`
covering every row in `<behavior>` against the Redis container plus the stub, driving one `poll_loop`
iteration per case with an explicit injected `now_ms` where the score assertion needs one. Drive the
minute counter directly with `INCRBY` rather than issuing 80 real requests — the budget Lua is
already proven in 03-02 and this file is about the gate's REACTION.

Assert the no-leak invariant in every case with a shared helper that checks both ZSETs; that
invariant is the one the Phase-2 fixer had to repair, and a gate is the easiest place to reintroduce
it.

Fix `services/poller/scheduler.py` for whatever the matrix exposes — in particular any ordering bug
between reading the backoff key and consuming the expedite flag — rather than weakening an assertion.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_release_precedence.py tests/integration/test_per_context_floor.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_release_precedence.py tests/integration/test_per_context_floor.py -q -p no:cacheprovider` exits 0 (or skips with a documented environment guard).
    - Both files contain a shared no-leak assertion applied in every case; `grep -c "inflight" tests/integration/test_release_precedence.py` returns at least 1.
    - `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>Backoff beats expedite without stranding the flag, both rate gates refuse by rescheduling rather than waiting, and no gate can leak a claimed job.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Ban reaction and fleet pause</name>
  <files>tests/integration/test_ban_reaction.py, tests/integration/test_fleet_pause.py, services/poller/scheduler.py, services/poller/publisher.py</files>
  <read_first>
    - services/poller/publisher.py in full (the `status` parameter, the two `send` calls, the `poll_log` insert — `context_id` must reach `PollCompleted` without disturbing `AvailabilityRaw`)
    - services/poller/sources/resy/canary.py (03-05: `response_signature`, `ban_verdict`, `record_signature`, `BanReason`)
    - shared/events.py (03-01: the widened `status` Literal, `context_id`, `FAILED_POLL_STATUSES`)
    - shared/metrics.py (`scrape_ban_total`) and .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pitfall 6 (the `get_sample_value` sample-name trap)
    - shared/redis_keys.py (`RESY_PAUSED_KEY`, `RESY_PAUSE_TTL_SECONDS`, `FLEET_PAUSE_RETRY_MS`, `canary_key`)
    - migrations/versions/0007_create_poll_log_hypertable.py line 19 (`status` is plain TEXT with no CHECK constraint — no migration is needed for `banned`)
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-67, §D-67a, §D-68
  </read_first>
  <behavior>
    - Stub in `challenge_403` mode -> `ban_verdict` fires, `scrape_ban_total{source="resy",reason="challenge_403"}` increments by 1, a `polls.completed` message carries `status="banned"` and the serving `context_id`, a `poll_log` row records `banned`, the context is recycled, and a backoff key exists.
    - Stub in `banned_empty` mode for three consecutive polls after a non-empty baseline -> a ban on the third poll and NOT on the second.
    - A `banned` `polls.completed` message consumed by the state machine marks the restaurant UNKNOWN (never a success), reusing the 03-01 consumer change.
    - All contexts poisoned within a 5-minute window -> `resy:paused` set with a TTL of 900 s, an ERROR-level `resy_fleet_paused` log, zero further Resy dispatches while the key exists, and Resy jobs released at `now + 60_000`.
    - While paused, OpenTable jobs continue to dispatch normally — the pause is source-scoped.
    - After the key is deleted, the next iteration dispatches Resy again with no restart.
  </behavior>
  <action>
Thread `context_id` through `services/poller/publisher.py::publish` as an optional keyword defaulting
to None, passed into `PollCompleted` only. Do NOT add it to `AvailabilityRaw`, whose field order the
golden replay files depend on, and do not add a `poll_log` column — `poll_log.status` is plain TEXT
with no CHECK constraint, so `banned` needs no migration.

Add the ban reaction to `poll_loop`: after each Resy response, build the signature, push it into the
rolling window, evaluate `ban_verdict`, and on a verdict increment `scrape_ban_total` with the
reason, set the poll status to `banned`, poison the serving context, and apply backoff. Track poisoned
contexts against a 5-minute window in the pool; when every context has been poisoned inside it, set
`RESY_PAUSED_KEY` with its TTL, log `resy_fleet_paused` at ERROR, and let the pre-dispatch pause gate
from Task 1 do the rest — the pause must be expressed as a key plus a gate, never as a flag held in
one worker's memory, because `poll_workers()` workers run concurrently.

Write `tests/integration/test_ban_reaction.py` and `tests/integration/test_fleet_pause.py` covering
every row in `<behavior>`. Read metrics with `get_sample_value("scrape_ban_total", labels)` — the
doubled-suffix name returns None, and an assertion written against it would silently always pass.
Drive the state-machine leg of the ban case by publishing the `polls.completed` message and asserting
`mark_unknown` was reached, reusing the Phase-2 e2e harness rather than a new one.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_ban_reaction.py tests/integration/test_fleet_pause.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_ban_reaction.py tests/integration/test_fleet_pause.py -q -p no:cacheprovider` exits 0 (or skips with a documented environment guard).
    - `uv run pytest tests/unit/test_replay_determinism.py -q` exits 0 and `git diff --stat tests/fixtures/raw_streams/` is empty — threading `context_id` did not perturb replay.
    - `ls migrations/versions/ | wc -l` is unchanged from the count after 03-03 — no migration was added for `banned`.
    - `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/` exits 0.
  </acceptance_criteria>
  <done>A soft ban is counted, published as a non-success, attributed to a context, and escalates to a fleet-wide pause that only the pause key can release.</done>
</task>

<task type="auto">
  <name>Task 4: Poller lifespan — concurrent workers, the metrics server, and the SC5 end-to-end proof</name>
  <files>services/poller/main.py, tests/integration/test_resy_e2e_state_machine.py</files>
  <read_first>
    - services/poller/main.py in full (the nested try/finally lifecycle, the `_assert_topics_exist` startup guard, the single `poll_loop` in `asyncio.gather`)
    - services/state_machine/main.py (the lazy-config wiring pattern to mirror)
    - services/poller/config.py (`poll_workers()`, `metrics_port()`, `resy_enabled()` from 03-03)
    - services/poller/sources/registry.py, pool.py (03-05)
    - tests/integration/test_state_machine_e2e.py lines 1-45 (the template: `pytestmark = pytest.mark.integration`, the rule that `services.state_machine` is imported INSIDE the test body, explicit `polled_at_epoch_ms` so the 8 s confirmation window costs no real time, and the local `_raw(...)` builder mirroring the publisher)
    - .planning/phases/03-resy-playwright-fleet/03-RESEARCH.md §Pitfall 4 (one serial loop makes four contexts decorative; N workers over the atomic claim Lua is safe), §Code Examples "Prometheus in an asyncio process" (`start_http_server` returns `(WSGIServer, Thread)`; shut it down in `finally`), §Pitfall 6
    - .planning/phases/03-resy-playwright-fleet/03-CONTEXT.md §D-69, §D-72, and §Claude's Discretion (lifespan ordering is discretionary; `browser.close()` in `finally` is not)
  </read_first>
  <action>
Extend `services/poller/main.py::run()`: build the adapter registry via `build_adapters(...)`,
constructing and starting `ContextPool` ONLY when `resy_enabled()` is true so an unconfigured
deployment never launches Chromium. Start the Prometheus exporter with
`start_http_server(metrics_port(), registry=REGISTRY)`, keeping the returned `(server, thread)` so it
can be shut down; the daemon thread introduces no `time.sleep`, no `requests` and no synchronous
`redis` import, so all three CI ban-greps stay green — say so in a comment, because a future reader
will otherwise "fix" it. Fan `asyncio.gather` out to `poll_workers()` `poll_loop` tasks over the one
`LuaScheduler` plus the single `reaper_loop`; the claim Lua is atomic, so N workers need no other
change. Document the accepted caveat from D-72 in the module docstring: a slow Resy poll can delay an
OpenTable poll by at most one poll duration, and source-filtered claims are deferred. Teardown order
in the `finally` chain: stop the workers, `await pool.stop()` (whose own `finally` shields
`browser.close()`), shut down the metrics server and join its thread, then the existing producer and
Redis teardown — so a browser can never outlive the process.

Write `tests/integration/test_resy_e2e_state_machine.py` as the SC5 proof at the integration tier,
following the Phase-2 e2e template exactly, including importing `services.state_machine` inside the
test body and passing explicit `polled_at_epoch_ms` values so the confirmation window costs no real
time. Publish two Resy `availability.raw` messages built the way the real publisher builds them,
9_000 ms apart, run the state machine, and assert an `availability.events` message appears with the
Resy source. Add the two structural assertions that make it an SC5 proof rather than a smoke test:
`PARSER_REGISTRY` holds exactly the two expected keys, and a comment-stripped scan of
`services/state_machine/engine.py` finds no source-platform name — with a non-vacuity assertion that
the scanned file is non-empty.
  </action>
  <verify>
    <automated>cd /Users/aryanahuja/projects/mise &amp;&amp; uv run pytest tests/integration/test_resy_e2e_state_machine.py -q -p no:cacheprovider</automated>
  </verify>
  <acceptance_criteria>
    - `uv run pytest tests/integration/test_resy_e2e_state_machine.py -q -p no:cacheprovider` exits 0 (or skips with a documented environment guard).
    - `RESY_ENABLED=false uv run python -c "import asyncio, services.poller.main as m; print('import ok')"` prints `import ok` and `pgrep -f ms-playwright | wc -l` reports 0 — a disabled deployment launches no browser.
    - `uv run pytest tests/integration -q -p no:cacheprovider` exits 0.
    - `grep -rn "^import requests\|^from requests \|time\.sleep(\|^import redis$\|^from redis import" services/ shared/ | wc -l` returns 0 — all three CI ban-greps stay green.
    - `uv run ruff check . &amp;&amp; uv run mypy shared/ services/ scripts/` exits 0.
  </acceptance_criteria>
  <done>The poller runs N workers with a live metrics endpoint, launches a browser only when Resy is enabled, tears everything down on every exit path, and a Resy poll demonstrably becomes an event through the untouched engine.</done>
</task>

</tasks>

## Artifacts this phase produces (plan 06)

| Kind | Symbol / path | Notes |
|------|---------------|-------|
| function | `services/poller/scheduler.py :: _next_poll_score(now_ms, interval_seconds)` | interval is now a parameter |
| function | `poll_loop(scheduler, adapters, publisher, pool=None, redis=None)` | registry dispatch + pre-dispatch gates |
| gate | fleet-pause gate | `RESY_PAUSED_KEY` present -> release at `now + FLEET_PAUSE_RETRY_MS` |
| gate | minute-budget gate | `RESY_BUDGET_LUA` refusal -> release at `now + RATE_REFUSAL_RETRY_MS` |
| gate | per-context floor gate | no eligible context -> release at `now + RATE_REFUSAL_RETRY_MS` |
| behaviour | backoff-beats-expedite release precedence | flag still `GETDEL`'d while backed off |
| behaviour | backoff DEL on the next successful poll | tier cadence resumes immediately |
| behaviour | ban reaction | `scrape_ban_total` + `status="banned"` + `context_id` + poison + backoff |
| behaviour | fleet pause | `resy:paused` EX 900, `resy_fleet_paused` at ERROR, source-scoped |
| parameter | `Publisher.publish(..., context_id: str \| None = None)` | reaches `PollCompleted` only |
| lifecycle | `main.run()` fans out `poll_workers()` `poll_loop` tasks | atomic claim Lua makes this safe |
| endpoint | Prometheus HTTP exporter on `METRICS_PORT` (default 9101) | `(WSGIServer, Thread)`, shut down in `finally` |
| test | `tests/integration/test_429_backoff_and_recycle.py` | SC3 |
| test | `tests/integration/test_resy_e2e_state_machine.py` | SC5 |
| test | `tests/integration/test_release_precedence.py`, `test_per_context_floor.py`, `test_ban_reaction.py`, `test_fleet_pause.py` | |

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| `sched:polls` claim -> dispatch | A claimed job is process-owned state; losing it strands a restaurant forever |
| poller -> Resy | The dispatch decision is the last point at which the fleet can still be polite |
| `METRICS_PORT` -> the network | A new listening socket is exposed by the poller process |
| `polls.completed` -> state machine | The status field decides whether a restaurant goes UNKNOWN |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-03-27 | Denial of Service (self-inflicted) | pre-dispatch gates | critical | mitigate | The budget and floor are checked BEFORE any request is issued and refuse by rescheduling, so the fleet cannot exceed the caps the public README promises even under N concurrent workers |
| T-03-28 | Denial of Service | claimed-job handling | high | mitigate | Every gate releases and every unknown source drops; an integration assertion checks both ZSETs in every gate case, because a bare `continue` after a claim is the exact defect the Phase-2 fixer had to repair |
| T-03-29 | Repudiation | ban visibility | high | mitigate | A ban is a counted metric, a published non-success status, an attributed `context_id` and an ERROR log — never a silent retry that looks like a slow day |
| T-03-30 | Information Disclosure | `METRICS_PORT` listener | medium | accept | The exporter binds the default `prometheus_client` address and exposes only aggregate counters with no restaurant identity or credential; Phase 7 owns network exposure and scrape auth. Recorded as accepted here rather than mitigated |
| T-03-31 | Denial of Service | worker fan-out | medium | mitigate | Workers share the atomic claim Lua (already proven in Phase 2), and the fleet pause is a Redis key plus a gate rather than in-memory state, so it applies to every worker at once |
| T-03-32 | Tampering | `Publisher` change | high | mitigate | `context_id` is added to `PollCompleted` only; `AvailabilityRaw` field order is untouched and the golden replay byte-identity test is an explicit acceptance criterion |
| T-03-SC | Tampering | npm/pip/cargo installs | low | accept | No new packages (research §Package Legitimacy Audit) |
</threat_model>

## Flagged assumptions (probe, unresolved — review manually)

None new in this plan. The POLL-02 unclassified probe row is carried in 03-02 and its two recorded
choices — a missing `watch:count` degrades to the slowest tier, and backoff resets on the first
success rather than after a sustained clean window — are implemented here, so a reviewer contradicting
either changes this plan's release path.

<verification>
- `uv run pytest tests/unit -q` exits 0.
- `uv run pytest tests/integration -q -p no:cacheprovider` exits 0 (52 pre-existing integration tests plus the new ones; environment-guarded skips are acceptable, failures are not).
- `uv run ruff check . && uv run mypy shared/ services/ scripts/` exits 0.
- The three CI ban-greps return zero matches under `services/` and `shared/`.
</verification>

<success_criteria>
- SC3: a simulated 429 produces an observable backoff score and context recycle within one poll cycle.
- SC5: a Resy raw message becomes an `availability.events` message through the unchanged diff engine.
- The 80 rpm cap and 45 s floor are enforced before dispatch, by rescheduling rather than waiting.
- A soft ban escalates to a source-scoped fleet pause and back out again without a restart.
</success_criteria>

<output>
Create `.planning/phases/03-resy-playwright-fleet/03-06-SUMMARY.md` when done.
</output>
</content>
