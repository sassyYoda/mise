# mise

Mise en Place — real-time restaurant availability notifications.

When a coveted table opens, the watching user is notified fast enough to actually book it.
Target: p95 detection-to-notification latency <= 60 seconds.

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

## Operations Runbook

### PERF-02 24-Hour Verification (SC5)

PERF-02 requires that >=99% of OpenTable polls succeed in every hourly bucket over a 24-hour
observation window, with a stable FD count (no socket leaks — Pitfall 9 mitigation).

**Prerequisites before starting the 24h run:**
1. OpenTable DevTools spike complete (see `services/poller/sources/opentable/README.md`). The
   placeholder `OPENTABLE_GQL_ENDPOINT` must be replaced with the live endpoint captured from
   a real browser session, or the poller will hit HTTP 404/400 and fail the 99% threshold.
2. Infrastructure up: `make up && make topics && make migrate && make seed && make verify-seed`.
3. `scripts/seed/restaurants.yml` has >=50 entries (verified by `make verify-seed`).

**Start the 24h run:**
```bash
# In a detached tmux/screen session (must survive shell close):
tmux new-session -d -s mise-poll 'make poll 2>&1 | tee logs/poll-$(date +%Y%m%dT%H%M%SZ).log'
POLLER_PID=$(pgrep -f "services.poller" | head -1)
echo "Poller PID: $POLLER_PID"

# Record the t0 baseline in docs/runbooks/perf02-24h-log.md:
T0=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
# Linux:
FD_COUNT=$(ls /proc/$POLLER_PID/fd 2>/dev/null | wc -l)
# macOS:
FD_COUNT=$(lsof -p $POLLER_PID 2>/dev/null | wc -l)
echo "t0=$T0 PID=$POLLER_PID FD=$FD_COUNT"
```

**Snapshot FD count at t+1h, t+6h, t+12h, t+24h** and fill the table in
`docs/runbooks/perf02-24h-log.md`.

**After 24 hours, run the PERF-02 gate:**
```bash
make verify-perf02
```

Expected: exits 0 and prints "PERF-02 PASSED: All 24 hourly buckets >= 99% success rate."

**Exit codes:**
- `0` — all 24 hourly buckets >=99% success (PERF-02 satisfied)
- `1` — at least one bucket below 99% (failing hours printed to stdout; investigate via
  `make logs` or `docker logs mise-postgres`)
- `2` — fewer than 24 hourly buckets of data (run has not yet completed 24h)

**Passing criteria for phase closure:**
- `make verify-perf02` exits 0.
- FD count at t+24h is within 5% of the t0 baseline (confirms Pitfall 9 avoidance — shared
  httpx.AsyncClient singleton is not leaking connections).
- `docs/runbooks/perf02-24h-log.md` is fully filled in (no `_fill in_` placeholders).
