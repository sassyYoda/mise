---
phase: 01-foundation-admin-pre-conditions-opentable-polling
plan: 06
type: execute
wave: 5
depends_on: ["05"]
files_modified:
  - scripts/check_poll_success.py
  - Makefile
  - README.md
  - docs/runbooks/perf02-24h-log.md
autonomous: false
requirements_addressed:
  - PERF-02

must_haves:
  truths:
    - "`make verify-perf02` exits 0 when every hourly bucket in poll_log has success_rate >= 0.99"
    - "`make verify-perf02` exits 1 and prints failing hours when any bucket is below 0.99"
    - "README.md has a 'Legal & Ethical Scraping' section (Pitfall 8) and a 'Kafka Single-Broker Tradeoff' section (Pitfall 11)"
    - "docs/runbooks/perf02-24h-log.md is filled in with t0_timestamp, t0_fd_count, and FD snapshots at t+1h, t+6h, t+12h, t+24h"
    - "After 24 hours of running `make poll`, `make verify-perf02` exits 0 (SC5 / PERF-02)"
  artifacts:
    - path: scripts/check_poll_success.py
      provides: "PERF-02 SQL assertion script: exits 0 if all 24 buckets >= 99%, exits 1 otherwise"
      contains: "time_bucket"
    - path: README.md
      provides: "Legal & Ethical Scraping section + Kafka tradeoff section"
      contains: "Anti-Piracy"
    - path: docs/runbooks/perf02-24h-log.md
      provides: "FD count log with t0, t+1h, t+6h, t+12h, t+24h snapshots"
      contains: "t0_timestamp"
  key_links:
    - from: scripts/check_poll_success.py
      to: poll_log
      via: "psycopg/asyncpg SELECT time_bucket('1 hour', time) GROUP BY hour"
      pattern: "time_bucket"
    - from: Makefile
      to: scripts/check_poll_success.py
      via: "verify-perf02 target"
      pattern: "check_poll_success"
---

<objective>
Complete the PERF-02 verification tooling, write the required README sections, and execute the 24-hour observation run that proves SC5. This plan delivers `scripts/check_poll_success.py` (the PERF-02 exit gate), the README legal and Kafka tradeoff sections, and the 24-hour FD observation log.

Purpose: SC5 (poll success >= 99% hourly across 24h; stable FD count) is the hardest P1 exit gate because it requires wall-clock time. This plan starts the observation clock and captures the evidence.

Output: Fully implemented check_poll_success.py; README legal + Kafka sections; filled perf02-24h-log.md; PERF-02 verification passing.
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
@.planning/research/PITFALLS.md
@.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-05-SUMMARY.md
@scripts/check_poll_success.py
@Makefile
</context>

<tasks>

<task id="01-06-T1" type="auto">
  <name>Task 1: scripts/check_poll_success.py — PERF-02 SQL assertion</name>
  <files>scripts/check_poll_success.py</files>
  <read_first>
    scripts/check_poll_success.py (current stub from Plan 01),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-11, D-31),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-RESEARCH.md (§ Validation Architecture SC5 artifact)
  </read_first>
  <action>
Replace the stub body in scripts/check_poll_success.py with the full implementation:

```python
#!/usr/bin/env python
"""
SC5 / PERF-02: Assert >= 99% poll success rate in every hourly bucket over last 24h.
Queries poll_log TimescaleDB hypertable using time_bucket() (D-11).

Usage: uv run python scripts/check_poll_success.py
Or:    make verify-perf02

Exit codes:
  0 — All hourly buckets have success_rate >= 0.99 (PERF-02 passed)
  1 — One or more buckets are below 0.99 (PERF-02 failed)
  2 — Not enough data (fewer than 24 hourly buckets — run has not completed 24h yet)
"""
from __future__ import annotations
import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Any

import asyncpg

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://mise:mise@localhost:5432/mise"
)

# PERF-02 success threshold
SUCCESS_RATE_THRESHOLD = 0.99

# Minimum hours of data required to claim PERF-02 (24h window)
REQUIRED_HOURS = 24


@dataclass
class HourlyBucket:
    hour: Any          # datetime
    total: int
    success: int

    @property
    def rate(self) -> float:
        return self.success / self.total if self.total > 0 else 0.0


async def check() -> int:
    """
    Run PERF-02 check. Returns exit code (0=pass, 1=fail, 2=insufficient data).
    """
    # Strip asyncpg prefix if set; asyncpg uses postgresql:// not postgresql+asyncpg://
    url = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            """
            SELECT
                time_bucket('1 hour', time)           AS hour,
                COUNT(*)                               AS total,
                SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) AS success
            FROM poll_log
            WHERE time >= NOW() - INTERVAL '24 hours'
            GROUP BY hour
            ORDER BY hour
            """
        )
    finally:
        await conn.close()

    if not rows:
        print("ERROR: No data in poll_log for the last 24 hours.", file=sys.stderr)
        print("Ensure the poller has been running for at least 1 hour.", file=sys.stderr)
        return 2

    buckets = [
        HourlyBucket(
            hour=row["hour"],
            total=int(row["total"]),
            success=int(row["success"]),
        )
        for row in rows
    ]

    # Print per-hour table
    print(f"{'Hour (UTC)':<25} {'Total':>8} {'Success':>8} {'Rate':>8} {'Status':>8}")
    print("-" * 62)

    failing_hours: list[HourlyBucket] = []
    for b in buckets:
        status = "PASS" if b.rate >= SUCCESS_RATE_THRESHOLD else "FAIL"
        if b.rate < SUCCESS_RATE_THRESHOLD:
            failing_hours.append(b)
        print(f"{str(b.hour):<25} {b.total:>8} {b.success:>8} {b.rate:>8.4f} {status:>8}")

    print("-" * 62)
    print(f"Total hours with data: {len(buckets)}")

    if len(buckets) < REQUIRED_HOURS:
        print(
            f"\nWARNING: Only {len(buckets)} hourly buckets found (need {REQUIRED_HOURS} for PERF-02).",
            file=sys.stderr,
        )
        print("PERF-02: INSUFFICIENT DATA — run has not completed 24h yet.", file=sys.stderr)
        return 2

    if failing_hours:
        print(f"\nPERF-02 FAILED: {len(failing_hours)} hourly bucket(s) below {SUCCESS_RATE_THRESHOLD:.0%}:")
        for b in failing_hours:
            print(f"  {b.hour}: {b.rate:.4f} ({b.success}/{b.total})")
        return 1

    print(f"\nPERF-02 PASSED: All {len(buckets)} hourly buckets >= {SUCCESS_RATE_THRESHOLD:.0%} success rate.")
    return 0


def main() -> None:
    exit_code = asyncio.run(check())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
```
  </action>
  <verify>
    <automated>python3 -c "import ast; ast.parse(open('scripts/check_poll_success.py').read()); print('check_poll_success.py parses OK')" && grep -q "time_bucket" scripts/check_poll_success.py && grep -q "SUCCESS_RATE_THRESHOLD" scripts/check_poll_success.py && grep -q "sys.exit" scripts/check_poll_success.py</automated>
  </verify>
  <done>
    scripts/check_poll_success.py has full implementation: SELECT time_bucket('1 hour', time) GROUP BY hour WHERE time >= NOW() - INTERVAL '24 hours'; asserts every bucket has success::float/total >= 0.99; exits 0 on pass, 1 on any failing bucket, 2 on insufficient data; prints per-hour table to stdout
  </done>
</task>

<task id="01-06-T2" type="auto">
  <name>Task 2: README.md legal stub and Kafka tradeoff sections</name>
  <files>README.md</files>
  <read_first>
    README.md (current content — read before modifying),
    .planning/research/PITFALLS.md (Pitfall 8 — Legal/ToS section; Pitfall 11 — Kafka single-broker tradeoff)
  </read_first>
  <action>
Read the current README.md. Add or replace the following two sections. If README.md does not exist, create it. If it exists, append these sections at the end (do not remove existing content).

Add this section for Pitfall 8 compliance:

```markdown
## Legal & Ethical Scraping

This project is a personal portfolio demo that monitors publicly visible restaurant availability
data. The following policies govern its operation:

- **Public data only**: All polled data is visible to any anonymous browser user on OpenTable.com
  and Resy.com. No private APIs, no auth bypass, no credential theft.
- **Rate limiting**: Polling is capped at 90-second minimum intervals per restaurant for httpx
  (OpenTable) and 80 req/min total for Playwright (Resy). These caps are enforced in code and
  documented here as a public commitment.
- **No booking automation**: The system detects availability and notifies users. It does not
  automate the booking step. Per the
  [NY Restaurant Reservation Anti-Piracy Act (Feb 2025)](https://columbianewsservice.com/2025/07/28/new-york-banned-reservation-resales-now-appointment-trader-is-testing-the-law-with-ai/),
  automated reservation resale and booking automation are explicitly prohibited — and we agree
  with that posture.
- **No account creation automation**: Resy polling accounts are created manually by the developer.
  Automated account creation violates Resy's ToS.
- **Compliance response**: If OpenTable or Resy requests takedown, the scraper stops within 24 hours.
  Historical heatmap data may remain as a static portfolio artifact.
- **robots.txt**: We respect robots.txt directives for all polled domains.
- **Portfolio scope**: This is a non-commercial portfolio project. No paid tier, no resale,
  no monetization.

*Privacy Policy and Terms of Service for mise.place: Coming Soon.*
```

Add this section for Pitfall 11 compliance:

```markdown
## Why Kafka for ~400 Events/Day?

This project uses Apache Kafka as its event pipeline backbone even though the MVP volume
is roughly 400 `availability.raw` events per day (50 restaurants × ~8 polls/hour).

**Honest tradeoff:**
- At MVP volume, a simple Postgres table with a background worker would work fine.
- Kafka is chosen here as a portfolio-grade architectural decision:
  - **Durable replay**: The `availability.raw` stream is an immutable log. Phase 2's
    `scripts/replay_raw.py` can re-run the diff engine over any offset range without
    re-polling OpenTable — this is a key portfolio artifact.
  - **Decoupled consumers**: State machine (Phase 2) and Notification Consumer (Phase 4)
    read from `availability.events` independently, with their own offsets and consumer groups.
    Adding a new consumer (e.g., analytics) requires zero changes to producers.
  - **Future scaling**: If the restaurant catalog grows to 5,000 entries or the system goes
    multi-city, Kafka handles the throughput increase with partition addition only.

**Single-broker tradeoff (MVP):**
- Replication factor 1 (single broker on GCE, persistent disk, KRaft mode).
- If the broker host is preempted, in-flight messages in the last 7 days may be replayed from
  Kafka's log; older messages are in TimescaleDB (`poll_log`, `availability_events`).
- `acks=all` on all producers ensures fsync before ack.
- **Upgrade path (Phase 7)**: Add a second broker, increase `default.replication.factor=2`,
  and update `min.insync.replicas=2`. No application code changes required.
```
  </action>
  <verify>
    <automated>grep -q "Anti-Piracy" README.md && grep -q "Why Kafka" README.md && grep -q "replication factor" README.md && echo "README sections OK"</automated>
  </verify>
  <done>
    README.md has "Legal & Ethical Scraping" section citing NY Restaurant Reservation Anti-Piracy Act, rate limit caps, no booking automation, no account creation automation, compliance response; README.md has "Why Kafka for ~400 Events/Day?" section documenting replication factor 1 as honest tradeoff with upgrade path in Phase 7; both sections present before phase exit
  </done>
</task>

<task id="01-06-T3" type="auto">
  <name>Task 3: Launch 24h observation run and record t0 baseline</name>
  <files>docs/runbooks/perf02-24h-log.md</files>
  <read_first>
    docs/runbooks/perf02-24h-log.md (template from Plan 01),
    .planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-CONTEXT.md (D-11)
  </read_first>
  <action>
This task runs autonomously — it starts the poller and records the initial baseline.

Verify infra is running and seeded:
```bash
docker compose -f ops/docker-compose.yml ps   # all services healthy
make topics                                    # idempotent — ensures topics exist
make migrate                                   # idempotent — migrations applied
make seed                                      # idempotent — 50 restaurants seeded
```

Start the poller in a background process or detached tmux/screen session:
```bash
make poll &
POLLER_PID=$!
echo "Poller PID: $POLLER_PID"
```

Record the t0 baseline in docs/runbooks/perf02-24h-log.md:
```bash
T0=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
FD_COUNT=$(ls /proc/$POLLER_PID/fd 2>/dev/null | wc -l || echo "N/A — use lsof on macOS")

# On macOS, use:
# FD_COUNT=$(lsof -p $POLLER_PID 2>/dev/null | wc -l || echo "N/A")
```

Update docs/runbooks/perf02-24h-log.md with actual values:
- t0_timestamp: [value of $T0]
- Poller PID at t0: [value of $POLLER_PID]
- FD count at t0: [value of $FD_COUNT]
- t=0 row in the FD Count Snapshots table: [fill in]

Note: The 24h clock starts when this task completes. The wall-clock checkpoint in Task 4 runs after 24h have elapsed.
  </action>
  <verify>
    <automated>grep -q "t0_timestamp\|Start time" docs/runbooks/perf02-24h-log.md && python3 -c "import ast; ast.parse(open('scripts/check_poll_success.py').read()); print('check_poll_success parses OK')"</automated>
  </verify>
  <done>
    Poller process started (make poll running); docs/runbooks/perf02-24h-log.md has t0 filled in (not the template placeholder) with actual timestamp, PID, and FD count; 24h observation clock running
  </done>
</task>

<task id="01-06-T4" type="checkpoint:human-action">
  <name>Task 4 [WALL-CLOCK]: Capture FD snapshots and run make verify-perf02 after 24 hours</name>
  <read_first>
    docs/runbooks/perf02-24h-log.md (current log with t0 baseline from Task 3)
  </read_first>
  <action>
WAIT: This task runs 24 hours after Task 3 completed. Do not attempt before 24h have elapsed.

At t+1h, t+6h, t+12h, t+24h, capture FD count snapshots:
```bash
# Linux:
FD_COUNT=$(ls /proc/$(pgrep -f "services.poller") /fd 2>/dev/null | wc -l)
# macOS:
FD_COUNT=$(lsof -p $(pgrep -f "services.poller") 2>/dev/null | wc -l)
```

Fill in the FD Count Snapshots table in docs/runbooks/perf02-24h-log.md at each checkpoint.

After 24h have elapsed, run the PERF-02 verification:
```bash
make verify-perf02
```

Expected: Exits 0 and prints "PERF-02 PASSED: All 24 hourly buckets >= 99% success rate."

If it exits 1, review which hours failed and investigate (check logs via `make logs` or `docker logs mise-postgres`).

Record final results in docs/runbooks/perf02-24h-log.md:
- make verify-perf02 exit code: [0 or 1]
- All 24 hourly buckets >= 99% success: [yes/no]
- FD count at t+24h: [value]
- FD count delta from t0: [value — should be < 5% of baseline]

Commit docs/runbooks/perf02-24h-log.md after filling in all values.
  </action>
  <acceptance_criteria>
    - `make verify-perf02` exits 0
    - `grep -q "PASSED\|exit code: 0" docs/runbooks/perf02-24h-log.md`
    - `grep -q "t+24h\|t_plus_24h" docs/runbooks/perf02-24h-log.md`
    - FD count at t+24h must be within 5% of t0 baseline (stable connection pool confirms Pitfall 9 avoidance)
  </acceptance_criteria>
</task>

</tasks>

<threat_model>
## Trust Boundaries

No new trust boundaries introduced in this plan — it is a verification and documentation layer only.

## STRIDE Threat Register

No new threats introduced. This plan verifies existing mitigations.

| Note | — | — | — | This plan adds a legal analysis (README), documents an honest Kafka tradeoff, and runs a 24h observation. No new attack surface is introduced. All previously identified threats (T-01 through T-05) were mitigated in Plans 01-05. |
</threat_model>

<verification>
After all four tasks complete:

```bash
# 1. check_poll_success.py is fully implemented
grep -q "time_bucket" scripts/check_poll_success.py && echo "time_bucket query OK"
grep -q "SUCCESS_RATE_THRESHOLD" scripts/check_poll_success.py && echo "threshold OK"
python3 -c "import ast; ast.parse(open('scripts/check_poll_success.py').read()); print('parses OK')"

# 2. README has required sections
grep -q "Anti-Piracy" README.md && echo "legal section OK"
grep -q "Why Kafka" README.md && echo "Kafka tradeoff section OK"
grep -q "replication factor 1" README.md && echo "honest tradeoff OK"

# 3. PERF-02 log has t0 baseline
grep -v "fill in\|_fill in" docs/runbooks/perf02-24h-log.md | grep -q "t0" && echo "perf02 log has baseline"

# 4. make verify-perf02 is wired
make help | grep -q "verify-perf02" && echo "Makefile target OK"

# 5. Unit tests still pass
uv run pytest tests/unit -x -q
```
</verification>

<success_criteria>
- scripts/check_poll_success.py: SELECT time_bucket('1 hour', time) query; exits 0 on all-pass, 1 on any failure, 2 on insufficient data; per-hour table printed to stdout
- README.md has "Legal & Ethical Scraping" section citing NY Restaurant Reservation Anti-Piracy Act and 90-second poll floor
- README.md has "Why Kafka for ~400 Events/Day?" section with honest tradeoff + replication factor 1 + upgrade path in Phase 7
- docs/runbooks/perf02-24h-log.md has t0_timestamp, t0_fd_count, and FD snapshots filled in (not template placeholders)
- [WALL-CLOCK GATE] After 24h: `make verify-perf02` exits 0; all 24 hourly buckets >= 99% success rate; FD count at t+24h stable (SC5 / PERF-02 satisfied)
</success_criteria>

<output>
After completion, create `.planning/phases/01-foundation-admin-pre-conditions-opentable-polling/01-06-SUMMARY.md`
</output>
