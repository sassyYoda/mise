# PERF-02 24-Hour Observation Log

**Purpose:** Record FD counts and per-hour poll success rates during the 24h PERF-02
verification run (SC5).

**Status:** BLOCKED ON HUMAN ACTION — see [Prerequisites](#prerequisites) below. The 24h
loop cannot be started by an automation agent; it must be launched manually after the
OpenTable DevTools spike is complete and infra is up.

---

## Prerequisites

The following must all hold true BEFORE starting the 24h run. Each item is a hard gate.

### 1. OpenTable DevTools spike complete (BLOCKER from Plan 01-05)

`services/poller/sources/opentable/graphql.py` currently uses a placeholder
`OPENTABLE_GQL_ENDPOINT` and `OPENTABLE_HEADERS` derived from 01-RESEARCH §4 with
`[ASSUMED]` markers. If the live endpoint differs, polls will return HTTP 404/400 and
the PERF-02 gate will fail.

- **Action:** Follow `services/poller/sources/opentable/README.md` to capture live
  endpoint + headers + GraphQL operation via Chrome DevTools on a NYC OpenTable page.
- **Verification:** `uv run pytest tests/integration/test_poller_smoke.py` passes against
  a live `make up` stack (Docker required).

### 2. Infra up and healthy

```bash
make up                                              # Start docker-compose stack
docker compose -f ops/docker-compose.yml ps          # All services healthy
make topics                                          # Idempotent — ensures 5 Named-Symbol topics exist
make migrate                                         # Idempotent — Alembic migrations applied
```

### 3. Seed populated (>=50 restaurants — SC3 gate)

```bash
# Precondition: YAML has >=50 entries (currently 55 from Plan 01-03).
uv run python -c "import yaml; assert len(yaml.safe_load(open('scripts/seed/restaurants.yml'))['restaurants']) >= 50, 'ABORT: < 50 entries'"

make seed                                            # Idempotent — populates DB + sched:polls ZSET
make verify-seed                                     # Hard gate: exits 0 when DB has >=50 and ZSET has >=50
```

If `make verify-seed` fails: abort. Do not start the 24h run with a partial seed.

### 4. Secrets loaded

`.env` must be populated (Plan 01-03 wrote `HMAC_MGMT_SECRET_V1`, `VAPID_PRIVATE_KEY`,
`VAPID_PUBLIC_KEY`, `VAPID_SUBJECT`). Verify via `ls -la .env`.

---

## Run Procedure

### Step 1: Start poller in detached session

The 24h run MUST survive shell disconnect. Do not use `&` — use `tmux` or `screen`.

```bash
mkdir -p logs
tmux new-session -d -s mise-poll 'make poll 2>&1 | tee logs/poll-$(date +%Y%m%dT%H%M%SZ).log'
# Wait ~5 seconds for asyncio to spawn child tasks, then capture PID:
sleep 5
POLLER_PID=$(pgrep -f "services.poller" | head -1)
echo "Poller PID: $POLLER_PID"
```

Sanity check: `tmux ls` should list the `mise-poll` session. `tmux attach -t mise-poll`
lets you peek at the live log (detach with Ctrl-b d).

### Step 2: Record t0 baseline

```bash
T0=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Linux:
FD_COUNT=$(ls /proc/$POLLER_PID/fd 2>/dev/null | wc -l)

# macOS:
FD_COUNT=$(lsof -p $POLLER_PID 2>/dev/null | wc -l)

echo "t0=$T0 PID=$POLLER_PID FD=$FD_COUNT"
```

Fill into the [Run Parameters](#run-parameters) section below. These are real wall-clock
values; do not commit with `_fill in_` placeholders.

### Step 3: FD snapshots at t+1h, t+6h, t+12h, t+24h

Set calendar reminders. At each checkpoint, re-run:

```bash
# Linux:
FD_COUNT=$(ls /proc/$(pgrep -f "services.poller" | head -1)/fd 2>/dev/null | wc -l)
# macOS:
FD_COUNT=$(lsof -p $(pgrep -f "services.poller" | head -1) 2>/dev/null | wc -l)
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) FD=$FD_COUNT"
```

Append to the [FD Count Snapshots](#fd-count-snapshots) table.

**Watch for:** FD delta > 5% from baseline signals socket/file leak (Pitfall 9). If
observed, abort, fix the leak in `shared/http_client.py` or adapter, and restart.

### Step 4: Run PERF-02 gate after 24h

```bash
make verify-perf02
echo "Exit code: $?"
```

- Exit `0` — PASS: all 24 buckets >=99% success. Record in
  [Verification Result](#verification-result), tick all boxes in [Sign-Off](#sign-off),
  commit this file.
- Exit `1` — FAIL: at least one bucket <99%. Capture the printed failing hours.
  Investigate via `docker logs mise-poller`, `make logs`, or
  `psql "$DATABASE_URL_SYNC" -c "SELECT time_bucket('1 hour', time) h, status, COUNT(*) FROM poll_log WHERE time >= NOW() - INTERVAL '24 hours' GROUP BY h, status ORDER BY h, status"`.
  Most common cause at this stage: stale OpenTable endpoint (Step 1 of prerequisites).
- Exit `2` — INSUFFICIENT DATA: run has not completed 24h. Wait.

### Step 5: Stop poller

```bash
tmux kill-session -t mise-poll
```

---

## Run Parameters

- Start time (t0): _fill in (real ISO-8601 UTC)_
- Poller PID at t0: _fill in_
- FD count at t0: _fill in_
- OpenTable endpoint version at t0: _fill in (DevTools-captured URL or "[ASSUMED placeholder]")_

## FD Count Snapshots

| Time  | Snapshot Label | FD Count | Notes |
|-------|---------------|----------|-------|
| t=0   | baseline      | _fill in_ | `ls /proc/$(pgrep -f services.poller)/fd \| wc -l` (Linux) / `lsof -p ... \| wc -l` (macOS) |
| t=1h  | t_plus_1h     | _fill in_ | |
| t=6h  | t_plus_6h     | _fill in_ | |
| t=12h | t_plus_12h    | _fill in_ | |
| t=24h | t_plus_24h    | _fill in_ | |

## Verification Result

- `make verify-perf02` exit code: _fill in (0, 1, or 2)_
- All 24 hourly buckets >=99% success: _yes / no_
- FD count at t+24h: _fill in_
- FD count delta from t0 (must be <=5% of baseline): _fill in absolute + percentage_
- Failing hours (if exit 1): _fill in list or "none"_

## Sign-Off

- [ ] All hourly buckets >= 0.99 success rate (exit 0)
- [ ] FD count stable over 24h (delta <= 5%)
- [ ] `make verify-perf02` exits 0
- [ ] This log committed with all `_fill in_` placeholders replaced

## Troubleshooting

**No data in poll_log (exit 2):**
- Poller is not actually running. Check `tmux ls`, `pgrep -f services.poller`,
  `docker compose ps`.
- Kafka topic startup guard failed. Check log for `_assert_topics_exist` error — run
  `make topics` to repair.
- DATABASE_URL_ASYNC mismatch. Poller writes to one DB, `check_poll_success.py` reads
  from another. Ensure both use the same value (default:
  `postgresql+asyncpg://mise:mise@localhost:5432/mise`).

**Every bucket failing (exit 1, success rate ~0%):**
- OpenTable endpoint is wrong. Re-run Prerequisite 1 (DevTools spike).
- Network blocked. Test: `curl -sv https://www.opentable.com/ > /dev/null`.

**FD count climbing (leak):**
- Shared httpx.AsyncClient singleton bypassed. Search for `httpx.AsyncClient(` outside
  `shared/http_client.py` — it should only be constructed there.
- Kafka producer not closed on shutdown. Check `services/poller/main.py` finally block.
