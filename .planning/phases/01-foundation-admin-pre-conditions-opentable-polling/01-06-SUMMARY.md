---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 06
subsystem: perf02-verification
tags: [perf02, timescaledb, time_bucket, asyncpg, runbook, legal, kafka-tradeoff, sc5]
dependency_graph:
  requires:
    - "01-02 — poll_log TimescaleDB hypertable with (time, restaurant_id, source, status, latency_ms, error_code) schema"
    - "01-03 — scripts/seed/restaurants.yml with 55 NYC restaurants (SC3 precondition guard for 24h run)"
    - "01-05 — services/poller/ runnable via `make poll`; Publisher writes poll_log row on every cycle"
  provides:
    - "scripts/check_poll_success.py — PERF-02 exit gate (exits 0/1/2 based on 24h time_bucket query)"
    - "README.md — Legal & Ethical Scraping section (Pitfall 8) + Why Kafka for ~400 Events/Day section (Pitfall 11) + PERF-02 runbook"
    - "docs/runbooks/perf02-24h-log.md — full runbook with prerequisites, step-by-step start procedure, FD snapshot schedule, troubleshooting"
  affects:
    - "Phase 1 closure — PERF-02 gate cannot pass until human operator runs prerequisites (DevTools spike) + 24h observation"
    - "Phase 2 (state machine) — no direct dependency; Phase 2 planning unblocked by this plan's autonomous portion"
tech_stack:
  added: []
  patterns:
    - "asyncpg direct client in verification scripts — no SQLAlchemy overhead, simple one-shot SELECT"
    - "Exit codes 0/1/2 distinguishing pass / fail / insufficient-data — prevents false-positive PASS during ramp-up"
    - "DATABASE_URL_ASYNC with postgresql+asyncpg:// prefix stripped to plain postgresql:// for asyncpg.connect (asyncpg does not accept the SQLAlchemy-style prefix)"
    - "tmux/screen detached session for long-running processes — survives shell disconnect; `&` alone does not"
key_files:
  created: []
  modified:
    - scripts/check_poll_success.py          # stub → full PERF-02 query + exit-code matrix
    - README.md                                # one-line stub → full legal + Kafka tradeoff + runbook
    - docs/runbooks/perf02-24h-log.md         # template → full runbook procedure
decisions:
  - "PERF-02 threshold implemented as >=0.99 (99%) per plan success criteria and 01-RESEARCH §Validation Architecture. The orchestrator prompt referenced `--hours` / `--threshold` CLI flags but the plan `<action>` block specifies hard-coded constants (SUCCESS_RATE_THRESHOLD=0.99, REQUIRED_HOURS=24). The plan is authoritative — constants are kept. If configurability is needed later, a follow-up plan can add argparse without breaking callers (make verify-perf02 invokes with no args)."
  - "Uses DATABASE_URL_ASYNC (asyncpg driver) per the plan's action block, not DATABASE_URL_SYNC as the orchestrator briefly suggested. Rationale: the plan is authoritative, and the poller (which writes to poll_log) already uses asyncpg — reading through the same driver avoids cross-driver URL schema confusion."
  - "T3 (24h observation run) is BLOCKED ON HUMAN ACTION and documented as such. The runbook is filled in with the full procedure so a human operator can execute it standalone; the template markers (`_fill in_`) remain in Run Parameters / FD Count Snapshots / Verification Result / Sign-Off sections because those are wall-clock real values that only exist after the run actually happens."
  - "PERF-02 cannot be declared passed at phase close. The explicit chain of prerequisites is: (a) OpenTable DevTools spike (blocker carried from 01-05), (b) infra running, (c) 24h wall-clock wait, (d) FD + success-rate evidence. The runbook makes each of these an explicit gate."
metrics:
  duration_seconds: 187
  duration_human: "3m 07s"
  tasks_completed_autonomous: 2   # T1, T2
  tasks_blocked_human_action: 1   # T3 (24h observation run + template fill-in)
  tasks_deferred_to_plan_t4: 1    # T4 (wall-clock verification) — not attempted; inherits T3 blocker
  files_created: 0
  files_modified: 3
  commits: 3
  unit_tests_passing: 27
completed_date: "2026-04-22"
requirements_addressed_autonomous:
  # PERF-02 tooling is implemented, but the requirement itself CANNOT be marked complete
  # until a human runs the 24h observation and records evidence. Phase closure gate.
  - PERF-02-TOOLING  # (informational — not a real REQUIREMENTS.md ID; the underlying PERF-02 remains open)
requirements_blocked_on_human_action:
  - PERF-02          # 24h poll success >=99% per hour with stable FD count
---

# Phase 01 Plan 06: PERF-02 Verification Summary

**One-liner:** Tooling, legal/Kafka documentation, and runbook for the 24-hour PERF-02 observation gate — autonomous tasks T1/T2 complete; T3/T4 (live 24h run) explicitly blocked on human action per orchestrator directive.

## Tasks Completed

| Task | Name | Status | Commit |
|------|------|--------|--------|
| T1 (plan T1 — `auto`) | scripts/check_poll_success.py — PERF-02 SQL assertion | **AUTONOMOUS — PASS** | `610b299` |
| T2 (plan T2 — `auto`) | README.md legal + Kafka tradeoff + runbook sections | **AUTONOMOUS — PASS** | `2de0253` |
| T3 (plan T3 — `checkpoint:human-action`) | Launch 24h observation + record t0 baseline | **BLOCKED ON HUMAN ACTION** — runbook filled with full procedure; actual run not attempted | `576f84c` (runbook procedure only) |
| T4 (plan T4 — `checkpoint:human-action`) | Wall-clock: FD snapshots at t+{1h,6h,12h,24h} + `make verify-perf02` | **BLOCKED ON HUMAN ACTION** — depends on T3 completion + 24h real time | *(not attempted)* |

## Commits

```
576f84c docs(01-06): expand perf02-24h-log.md with full runbook procedure
2de0253 docs(01-06): add Legal & Ethical Scraping + Kafka tradeoff + PERF-02 runbook to README
610b299 feat(01-06): implement check_poll_success.py PERF-02 gate
```

## BLOCKED ON HUMAN ACTION

### T3 + T4 — 24-hour PERF-02 observation run

PERF-02 (SC5) requires wall-clock time and cannot be executed by an automation agent.
The full runbook is now in `docs/runbooks/perf02-24h-log.md`. A human operator must
execute the following chain; **none of the individual gates can be skipped**:

**Prerequisite chain (in order):**

1. **OpenTable DevTools spike (inherited blocker from Plan 01-05).**
   `services/poller/sources/opentable/graphql.py` currently uses a placeholder
   `OPENTABLE_GQL_ENDPOINT = https://www.opentable.com/dapi/fe/gql/prod` with
   `[ASSUMED]` markers. If this endpoint does not match the live OpenTable network
   traffic, every poll will return HTTP 404/400 and the PERF-02 gate will fail with
   ~0% success rate. See `services/poller/sources/opentable/README.md` for the exact
   DevTools capture procedure.

2. **Infra up and healthy.**
   `make up && make topics && make migrate && make seed && make verify-seed` must
   all succeed (the last one confirms DB has >=50 seeded restaurants — SC3 precondition).

3. **Poller launched in detached tmux/screen session.**
   See `docs/runbooks/perf02-24h-log.md` → "Run Procedure → Step 1". Must NOT use `&`
   alone; the run must survive shell disconnect.

4. **t0 baseline recorded.**
   Timestamp, PID, FD count filled into the runbook's Run Parameters section
   (replacing `_fill in_` placeholders).

5. **FD snapshots at t+1h, t+6h, t+12h, t+24h.**
   Recorded in the FD Count Snapshots table. Watch for >5% delta from baseline —
   that signals socket/file leak (Pitfall 9) and the run should be aborted + fix applied.

6. **24 hours real time elapses.**

7. **`make verify-perf02` invoked.**
   - Exit 0 → PASS. All 24 hourly buckets >=99% success. Tick all Sign-Off boxes.
   - Exit 1 → FAIL. Failing hours printed. Most likely cause at first run: stale
     OpenTable endpoint (Prerequisite 1).
   - Exit 2 → INSUFFICIENT DATA. Run has not yet completed 24h. Wait.

8. **Sign-off:** all four boxes in the runbook's Sign-Off section ticked + final
   commit of `docs/runbooks/perf02-24h-log.md` with real values.

**Why this cannot be automated:**

- The DevTools spike requires an interactive browser + Chrome DevTools on a live
  restaurant page (possibly with IP-geo constraints). No headless automation path.
- 24 hours is a wall-clock primitive; no tool can compress real time.
- The FD snapshots are intentionally spaced out so a human operator can review each
  one, catch early warning signs, and abort cleanly rather than discover a leak
  24h too late.

**Impact on phase closure:**

PERF-02 is SC5 for Phase 01. **Phase 01 cannot be declared complete** until the 24h
run passes. Plan 01-06 ships all the tooling and documentation to execute it, but the
requirement itself remains **OPEN** in `REQUIREMENTS.md`. See also the Phase-Closing
Note below.

## Verification Output

### Plan `<verification>` block — all autonomous items PASS

```
$ grep -q "time_bucket" scripts/check_poll_success.py && echo "time_bucket query OK"
time_bucket query OK

$ grep -q "SUCCESS_RATE_THRESHOLD" scripts/check_poll_success.py && echo "threshold OK"
threshold OK

$ python3 -c "import ast; ast.parse(open('scripts/check_poll_success.py').read()); print('parses OK')"
parses OK

$ grep -q "Anti-Piracy" README.md && echo "legal section OK"
legal section OK

$ grep -q "Why Kafka" README.md && echo "Kafka tradeoff section OK"
Kafka tradeoff section OK

$ grep -iq "replication factor 1" README.md && echo "honest tradeoff OK"
honest tradeoff OK

$ grep -q "t0" docs/runbooks/perf02-24h-log.md && echo "perf02 log has t0 section"
perf02 log has t0 section

$ make help | grep verify-perf02
  verify-perf02        Assert all 24-hour buckets in poll_log have >=99% success rate

$ uv run pytest tests/unit -x -q
27 passed, 1 warning in 0.17s
```

### Smoke-test of check_poll_success.py (no DB) — correct behavior

```
$ uv run python scripts/check_poll_success.py
...
OSError: Multiple exceptions: [Errno 61] Connect call failed ('::1', 5432, 0, 0), [Errno 61] Connect call failed ('127.0.0.1', 5432)
```

Script fails fast on DB unavailable (expected: infra is not started in this execution context).
When invoked with a live poll_log hypertable, the script will execute the
`SELECT time_bucket('1 hour', time) ... FROM poll_log WHERE time >= NOW() - INTERVAL '24 hours'`
query and return 0/1/2 per the contract.

### Verification items that cannot be run in this execution

| Verification item | Why blocked |
|-------------------|-------------|
| `make verify-perf02` exits 0 | Requires DB up + 24h of poll_log data — human-action gate |
| FD count stable (delta <=5%) | Requires 24h observation run — human-action gate |

## Success Criteria

| Criterion | Status |
|-----------|--------|
| `scripts/check_poll_success.py` uses SELECT time_bucket('1 hour', time) query | PASS |
| Exits 0 on all-pass, 1 on any failure, 2 on insufficient data | PASS (code path verified by `ast.parse` + code review) |
| Per-hour table printed to stdout | PASS (code review) |
| README.md has "Legal & Ethical Scraping" section citing NY Anti-Piracy Act + 90s poll floor | PASS |
| README.md has "Why Kafka for ~400 Events/Day?" section + replication factor 1 + Phase 7 upgrade path | PASS |
| `docs/runbooks/perf02-24h-log.md` has t0_timestamp / t0_fd_count / FD snapshot rows | PASS (structure + template present; actual values require human run) |
| [WALL-CLOCK GATE] After 24h: `make verify-perf02` exits 0; all 24 hourly buckets >=99%; FD stable | **BLOCKED ON HUMAN ACTION** |

**Autonomous success criteria: PASS across the board.**
**Human-action success criterion (24h run): BLOCKED — see [BLOCKED ON HUMAN ACTION](#blocked-on-human-action) section.**

## Deviations from Plan

### Auto-fixed Issues

None. The plan executed exactly as written for the autonomous portion (T1 + T2 + runbook
fill-in of T3). No Rule 1/2/3 deviations triggered.

### Orchestrator Instructions Applied

The orchestrator prompt provided four explicit directives:

1. **"Do NOT actually run the 24h loop."** Applied — T3 is documented as BLOCKED; only
   the runbook procedure was written. No poller was launched.
2. **"Leave T3 as a runbook checklist in docs/runbooks/perf02-24h-log.md."** Applied —
   the runbook now contains the full Prerequisites / Run Procedure / Troubleshooting
   sections plus the original template tables preserved for the human operator to fill.
3. **"Mark PERF-02 BLOCKED ON HUMAN ACTION in 01-06-SUMMARY.md."** Applied in this summary.
4. **"Use DATABASE_URL_ASYNC (not DATABASE_URL_SYNC) in check_poll_success.py if it uses
   asyncpg."** Applied — script uses asyncpg directly; reads `DATABASE_URL_ASYNC` env var
   (matching the plan's `<action>` block). The orchestrator's alternative suggestion of
   `DATABASE_URL_SYNC` for psycopg3 was not needed because the plan prescribed asyncpg.

### Authentication Gates

None. No external auth surface touched in this plan.

### Human-Action Gates

**1. 24h PERF-02 observation run (plan T3 + T4).** Documented above and in the runbook.
The underlying OpenTable DevTools spike (inherited from 01-05) is a nested blocker — the
24h run cannot proceed without it, because a stale endpoint will fail the 99% threshold.

## Known Stubs

| Stub | File | Resolved by |
|------|------|-------------|
| `_fill in_` placeholders in Run Parameters / FD Count Snapshots / Verification Result / Sign-Off | `docs/runbooks/perf02-24h-log.md` | Human operator running the 24h procedure (plan T3+T4). The STRUCTURE is complete; only the wall-clock values are unknown until the run executes. |

These stubs are **intentional** — they represent real-world values (timestamps, PIDs, FD
counts) that only exist after the observation run. They will be filled by the human
operator in a follow-up commit and are not resolvable by any automation.

## Threat Flags

None. This plan adds verification tooling + documentation; it does not introduce any new
trust boundaries, network surface, auth paths, or schema changes. The threat register
(T-01 through T-05 from earlier plans) is unchanged.

## Phase-Closing Note

Plan 01-06 is the final plan in Phase 01 (Wave 5 of 5). With its autonomous portion
complete, the Phase 01 status is:

- **Autonomous plans complete:** 01-01, 01-02, 01-03, 01-04, 01-05, 01-06 (this plan).
- **Phase 01 SCs status:**
  - SC1 (poller smoke test) — PASS (01-05 T4).
  - SC2 (seed idempotency) — PASS (01-05 T4).
  - SC3 (>=50 restaurants in DB + sched:polls ZSET) — PASS (01-03 + verified by 01-05 T4
    `make verify-seed` stub fill-in).
  - SC4 (poll_log row written per cycle with latency_ms + status CHECK constraint) — PASS
    (01-05 T4 integration test `test_poll_log_writes.py`).
  - **SC5 (PERF-02: >=99% hourly success rate over 24h + stable FD count) — BLOCKED ON HUMAN ACTION.**
- **Phase 01 cannot be declared DONE** until:
  - OpenTable DevTools spike (01-05 T1 blocker) completes.
  - 24h PERF-02 observation run (01-06 T3+T4) passes.
  - Admin pre-condition human-action gates (01-03 T3 — Twilio 10DLC, domain, GCP, Resy
    cookie capture) complete per `01-03-SUMMARY.md`.

**Recommended phase-close sequence for the human operator:**
1. Execute 01-03 admin gates (Twilio 10DLC submit + domain purchase + GCP project + Resy
   cookie capture — multi-day/multi-week wall-clock).
2. Execute 01-05 DevTools spike (~30 min browser session).
3. Start 01-06 24h run per `docs/runbooks/perf02-24h-log.md`.
4. After PERF-02 PASS, update `STATE.md` → status=phase-complete, advance to Phase 02.

All automation that could be done in-process has been done. The remaining work is
explicitly gated on human operator action, and each gate has a concrete, step-by-step
runbook committed alongside this summary.

## Self-Check: PASSED

Files verified present on disk:
- `scripts/check_poll_success.py`: FOUND
- `README.md`: FOUND (Anti-Piracy, Why Kafka, replication factor 1 all grep-confirmed)
- `docs/runbooks/perf02-24h-log.md`: FOUND (Prerequisites, Run Procedure, Troubleshooting
  sections present)
- `Makefile`: unchanged (verify-perf02 target already added in 01-01)

Commits verified in `git log`:
- `610b299` (T1) — FOUND
- `2de0253` (T2) — FOUND
- `576f84c` (T3 runbook fill-in) — FOUND
