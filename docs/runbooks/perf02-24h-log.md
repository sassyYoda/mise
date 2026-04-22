# PERF-02 24-Hour Observation Log

**Purpose:** Record FD counts and success rates during the 24h PERF-02 verification run (SC5).

## Run Parameters

- Start time (t0): _fill in_
- Poller PID at t0: _fill in_
- FD count at t0: _fill in_

## FD Count Snapshots

| Time | Snapshot Label | FD Count | Notes |
|------|---------------|----------|-------|
| t=0  | baseline | | `ls /proc/$(pgrep -f services.poller)/fd \| wc -l` |
| t=1h | t_plus_1h | | |
| t=6h | t_plus_6h | | |
| t=12h | t_plus_12h | | |
| t=24h | t_plus_24h | | |

## Verification Result

- `make verify-perf02` exit code: _fill in_
- All 24 hourly buckets >=99% success: yes / no
- FD count stable (delta ≤ 5% from baseline): yes / no

## Sign-Off

- [ ] All hourly buckets >= 0.99 success rate
- [ ] FD count stable over 24h
- [ ] `make verify-perf02` exits 0
