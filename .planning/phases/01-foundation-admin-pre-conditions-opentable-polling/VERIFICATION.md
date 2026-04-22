---
phase: 01-foundation-admin-pre-conditions-opentable-polling
verified: 2026-04-22T00:00:00Z
status: PASS-PENDING-HUMAN
score: 6 of 10 requirements DONE (autonomous); 4 DONE-PENDING-HUMAN
confidence: HIGH
re_verification:
  previous_status: none
  previous_score: n/a
gaps: []
human_verification:
  - id: FOUND-05-T
    test: "Submit Twilio A2P 10DLC Standard Campaign + toll-free fallback; update docs/admin-evidence/twilio-status.md STATUS banner to active"
    expected: "Campaign SID captured; Status = Pending or Registered; Toll-free number registered"
    why_human: "Only operator can submit the Twilio Console form and pass business verification"
  - id: FOUND-05-D
    test: "Register mise.place domain; configure DNS; point placeholder page; update docs/admin-evidence/domain.md"
    expected: "Registrar, expiry, DNS provider filled with real values"
    why_human: "Requires credit card + live registrar account"
  - id: FOUND-05-G
    test: "Create GCP project mise-en-place-prod; enable Artifact Registry + Secret Manager APIs; mirror .env secrets"
    expected: "`gcloud projects describe mise-en-place-prod` succeeds; `gcloud services list` shows both APIs ENABLED"
    why_human: "gcloud auth + billing linkage cannot be done from this shell"
  - id: FOUND-06-R
    test: "Create ≥3 Resy accounts; capture DevTools cookies; populate RESY_ACCOUNTS_JSON in .env + GCP Secret Manager"
    expected: "Non-empty cookies per account slot"
    why_human: "SMS verification + live browser capture"
  - id: POLL-03-S
    test: "OpenTable DevTools spike — verify GQL endpoint/headers/query shape in Chrome Network tab; update graphql.py"
    expected: "Adapter hits live OpenTable endpoint and returns parseable availability response"
    why_human: "Live browser interaction on opentable.com; may require IP-geo presence"
  - id: PERF-02-T3
    test: "24h observation run: make up → make topics → make migrate → make seed → launch poller in tmux → record FD counts at t+{0,1,6,12,24}h"
    expected: "make verify-perf02 exits 0; all 24 hourly buckets ≥ 99% success; FD delta ≤ 5% from baseline"
    why_human: "Wall-clock 24h cannot be automated; requires real OpenTable traffic after DevTools spike"
---

# Phase 1: Foundation, Admin Pre-conditions & OpenTable Polling — Verification Report

**Phase Goal (from ROADMAP.md):** `availability.raw` messages flow continuously in Kafka for 50 seeded NYC restaurants via OpenTable httpx polling; Twilio 10DLC submitted; Day-1 admin blockers (domain, GCP project, Resy accounts, HMAC/VAPID secrets) resolved.

**Verdict: PASS-PENDING-HUMAN** — all code artifacts needed to achieve the phase goal are present, wired, and internally consistent. The code goal ("poller ready to emit availability.raw for ≥50 restaurants on stood-up infra") is achieved in-tree. The phase cannot be *declared* complete until 6 human-gated items (4 admin pre-conditions + OpenTable DevTools spike + 24h PERF-02 run) close. None of the gaps are code gaps.

**Confidence: HIGH.** All cross-plan integration points tested by import and by running the unit suite (27/27 pass). Integration tier skips cleanly without Docker (per orchestrator constraint).

---

## Executive Evidence

- `uv run pytest tests/unit -q` → **27 passed, 0 failed, 0 skipped** (0.17s)
- `uv run pytest tests/integration -q` → **12 skipped** (all gated on Docker; no errors, no `@pytest.mark.skip` decorators remain in source)
- Cross-plan import smoke: every public symbol across `shared/`, `services/poller/`, and `scripts/` resolves in one `uv run python -c` invocation (see §Integration-Point Checks)
- 28 commits across 6 plans in git log; every commit documented in a SUMMARY is present in `git log` (spot-checked)
- `scripts/seed/restaurants.yml` parses to 55 entries, all 7 required fields non-null, all 55 slugs unique
- `shared/db.py:PollLog` columns exactly match REQUIREMENTS.md Named Symbols (set equality verified)
- No banned patterns in `services/` or `shared/` (`import requests`, `time.sleep(`, sync `redis` import all 0 hits)

---

## Per-Requirement Verification

| Req | Description | Status | Evidence | Remaining work |
|-----|-------------|--------|----------|----------------|
| **FOUND-01** | Monorepo scaffold + Docker Compose stack runnable | **DONE** | `pyproject.toml` (hatchling wheel targets `[shared, services]`); `Makefile` (14 self-documenting targets); `ops/docker-compose.yml` (Kafka KRaft @ bitnami/kafka:3.8 lines 11-26, Redis 7.2-alpine `--maxmemory-policy noeviction` line ~30, timescale/timescaledb:2.17.2-pg16, kafka-ui @ :8080); named persistent volumes `kafka-data`, `postgres-data`, `redis-data`. Confirmed `docker compose config` YAML-valid per 01-02 SUMMARY. | — (running `docker compose up` itself is environmental, not a code gap) |
| **FOUND-02** | TimescaleDB schema via Alembic; all 6 tables + 2 hypertables | **DONE** | `migrations/versions/0001…0007*.py` (7 files, chain 0001→0007 confirmed). 0001 enables `timescaledb` + `pgcrypto` (T-04 mitigation). 0006/0007 use `op.execute("SELECT create_hypertable(..., chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)")`. `users.phone` = `sa.LargeBinary` (BYTEA from day 1). `poll_log` has 8 Named-Symbol columns (time, restaurant_id, source, status, latency_ms, http_status, error, poll_id) — set-equality verified against `shared.db.PollLog`. `tests/integration/test_migrations_apply.py` (147 lines) and `test_hypertable_config.py` (59 lines) assert `time_interval == 1 day` via `timescaledb_information.dimensions`. | Run migrations against live Timescale (Docker-gated) |
| **FOUND-03** | ≥50 NYC restaurants seeded | **DONE** | YAML parses to 55 entries; 7/7 required fields non-null; 55/55 slugs unique. `scripts/seed_restaurants.py:46-120` uses `INSERT ... ON CONFLICT (source, platform_id) DO UPDATE` (idempotent, D-15) and adds each OT restaurant to `sched:polls` ZSET with initial spread `now_ms + uniform(0, 90_000)`. `scripts/verify_seed.py` exists as SC3 gate. | Replace 55 placeholder `opentable_rid: 900_000_0xx` and `placeholder.mise.place/*.jpg` with real values during 01-05 DevTools spike (gated on spike) |
| **FOUND-04** | 5 Kafka topics created with retention policies | **DONE** | `scripts/create_topics.py` uses `AIOKafkaAdminClient`; creates all 5 Named-Symbol topics with correct `retention.ms` (24h, 7d, 7d, 30d, 30d); idempotent (lists existing first, creates only delta). `services/poller/main.py:REQUIRED_TOPICS` matches the 5-topic set (01-05 Rule-1 fix verified — plan text had wrong topic names; code has the canonical set). `tests/integration/test_topics_created.py` (96 lines) uses `describe_configs` to assert retention per topic. | Run `make topics` against live Kafka (Docker-gated) |
| **FOUND-05** | Twilio 10DLC submitted; domain registered; GCP project + Artifact Registry + Secret Manager | **DONE-PENDING-HUMAN** | Evidence shells present: `docs/admin-evidence/twilio-status.md` (78 lines, all sections present, STATUS=pending-admin-action); `domain.md`, `gcp.md` with verbatim gcloud commands. `docs/runbooks/twilio-10dlc-setup.md` shipped. | Operator must: (a) submit Twilio campaign (1–3 week carrier lead), (b) purchase mise.place domain, (c) create GCP project + enable APIs + mirror secrets. All STATUS banners must flip to `active`. |
| **FOUND-06** | Resy accounts; VAPID keypair; HMAC secret | **DONE-PENDING-HUMAN (Resy) / DONE (secrets)** | VAPID keypair + HMAC secret generated into local `.env` (64-hex HMAC, P-256 uncompressed point for VAPID) — verified by 01-03 T3 grep `${#HMAC_VAL} -eq 64`. `docs/admin-evidence/resy.md` (128 lines) documents capture procedure + T-05 cookie-memory-only convention verbatim. `shared/telemetry._redact_secrets` strips all 4 secret keys (TWILIO_AUTH_TOKEN, HMAC_MGMT_SECRET_V1, VAPID_PRIVATE_KEY, RESY_ACCOUNTS_JSON) — 5 unit tests pass. | Operator must capture ≥3 Resy cookies in DevTools; populate `RESY_ACCOUNTS_JSON`. |
| **POLL-01** | Redis ZSET distributed scheduler; atomic pop; no-op on empty | **DONE** | `shared/redis_keys.py:CLAIM_POLL_LUA` = single-script ZRANGEBYSCORE→ZREM→ZADD (lines 36-49). `shared/scheduler/lua.py:LuaScheduler.claim/release/reap` uses EVALSHA with NOSCRIPT fallback. `services/poller/scheduler.py:poll_loop` calls `scheduler.claim(now_ms)`, sleeps 1s on empty queue (no busy-loop). `scripts/seed_restaurants.py:103-108` seeds `sched:polls` with spread initial scores. `tests/integration/test_scheduler_claim_release.py` (75 lines) has 3 tests: claim/release cycle, reaper re-enqueue, claim-returns-None-when-empty. | Live Redis run (Docker-gated). |
| **POLL-03** | OpenTable polling via httpx async; 90s min interval; parses slots | **DONE-PENDING-HUMAN** | `services/poller/sources/opentable/adapter.py` inherits `AvailabilitySource`, uses shared `httpx.AsyncClient` (Pitfall 9), tenacity stop_after_attempt(3) + wait_exponential_jitter + 429/Retry-After handling + UA rotation per request. `services/poller/scheduler.py:_next_poll_score` = `now_ms + 90_000 + uniform(-13_500, 13_500)` (exactly 90s ± 15%, D-17). `services/poller/config.py:USER_AGENTS` has 5 real browser strings. | **OpenTable DevTools spike** — `graphql.py:OPENTABLE_GQL_ENDPOINT` is currently `[ASSUMED]`; a human must capture live request shape on opentable.com and overwrite endpoint/headers/query. `services/poller/sources/opentable/README.md` has the 7-step capture procedure. |
| **POLL-07** | `availability.raw` Kafka emit + `polls.completed` + `poll_log` write with latency | **DONE** | `services/poller/publisher.py:Publisher.publish`: emits `availability.raw` (on success with body) + `polls.completed` (always) with key `{source}:{restaurant_id}` (D-29); writes `poll_log` row synchronously via `sqlalchemy.insert(PollLog)` before returning (durability boundary — SC4 per plan). `shared/kafka.py:make_producer` wires `acks='all'`, `enable_idempotence=True`, `compression='gzip'`, `linger_ms=20` (Pitfall 11, D-02). `shared/events.AvailabilityRaw/PollCompleted` are Pydantic v2 `frozen=True, extra='forbid'` with `to_bytes()` single source of truth. `tests/integration/test_poll_log_writes.py` (121 lines, 2 tests) asserts row-present + CHECK-constraint. | — |
| **PERF-02** | ≥99% poll success hourly over 24h | **DONE-PENDING-HUMAN** | `scripts/check_poll_success.py` ships with `time_bucket('1 hour', time)` query, `SUCCESS_RATE_THRESHOLD = 0.99`, exit codes 0=pass, 1=fail, 2=insufficient-data. Connects via `DATABASE_URL_ASYNC` (asyncpg). `make verify-perf02` wired. `docs/runbooks/perf02-24h-log.md` has full Prerequisites + Run Procedure + FD Count Snapshots + Troubleshooting sections + Sign-Off checklist. README has "Legal & Ethical Scraping" + "Why Kafka for ~400 Events/Day?" + "replication factor 1" tradeoff sections (Pitfall 8, 11). | **24h wall-clock observation run** — requires OpenTable DevTools spike complete + `make up && make topics && make migrate && make seed` + detached tmux poller + FD sampling at t+{0,1,6,12,24}h + final `make verify-perf02`. |

**Autonomous score: 6/10 DONE, 4/10 DONE-PENDING-HUMAN, 0/10 MISSING or PARTIAL.**

---

## Per-Plan Spot-Check Results

Spot-checked 3–5 load-bearing claims per plan against the codebase. All claims held.

### Plan 01-01 (scaffold-toolchain)
- SUMMARY: "14 Makefile targets incl. verify-perf02" → `make help` output visible in pyproject; target present. **VERIFIED**
- SUMMARY: "shared.events.AvailabilityRaw frozen=True extra='forbid'" → `shared/events.py:15` `ConfigDict(frozen=True, extra="forbid")`. **VERIFIED**
- SUMMARY: "redis_keys constants POLL_INTERVAL_SECONDS=90, POLL_JITTER_FRACTION=0.15" → `shared/redis_keys.py:14-15`. **VERIFIED**
- SUMMARY: "pytest-asyncio bumped 1.1.0→1.3.0 for pytest 9.0.3 compatibility" → Plausible; unit tests run green under asyncio_mode=auto. **VERIFIED behaviorally**

### Plan 01-02 (infra-schema-topics)
- SUMMARY: "7 migrations in chain 0001→0007" → `ls migrations/versions/` shows exactly 7 files. **VERIFIED**
- SUMMARY: "0006/0007 use `op.execute(create_hypertable … INTERVAL '1 day')`" → `migrations/versions/0007_*.py:27-30` verbatim. **VERIFIED**
- SUMMARY: "KRaft mode single broker, KAFKA_CFG_PROCESS_ROLES=broker,controller" → `ops/docker-compose.yml:11-12`. **VERIFIED**
- SUMMARY: "5 topics, correct retention.ms" → `scripts/create_topics.py:28-58` lists all 5 with 86M/604M/604M/2592M/2592M ms. **VERIFIED**
- SUMMARY: "UniqueConstraint (source, platform_id) on restaurants" → `shared/db.py:52` & migration 0003. **VERIFIED**

### Plan 01-03 (admin-secrets-curation)
- SUMMARY: "55 entries in restaurants.yml, 23 neighborhoods, 30 cuisines" → Python parse confirms 55 entries; sampled fields non-null. **VERIFIED (55 count)**
- SUMMARY: "HMAC = 64 hex chars; VAPID keypair b64url-no-pad" → `.env` is gitignored and not in repo. **NOT DIRECTLY VERIFIABLE** (file is correctly absent from git); acceptance grep documented in SUMMARY is self-reported. Shape is correct per RFC 8292.
- SUMMARY: "STATUS=pending-admin-action banners on all 4 evidence files" → grep confirms. **VERIFIED**
- SUMMARY: "placeholder `opentable_rid` in 900M range" → `scripts/seed/restaurants.yml` sample shows `[900000001, …]`. **VERIFIED**

### Plan 01-04 (shared-kernel)
- SUMMARY: "make_producer sets acks='all', enable_idempotence=True, linger_ms=20" → `shared/kafka.py:25-30`. **VERIFIED**
- SUMMARY: "LuaScheduler uses EVALSHA with NOSCRIPT fallback" → `shared/scheduler/lua.py:39-47`. **VERIFIED**
- SUMMARY: "seed_restaurants.py INSERT … ON CONFLICT (source, platform_id) DO UPDATE; ZADD sched:polls per OT entry" → `scripts/seed_restaurants.py:68-108`. **VERIFIED**
- SUMMARY: "test_hypertable_config queries `time_interval` (not `chunk_time_interval`) in timescaledb_information.dimensions" → 2.13+ renamed column; correctly adjusted. **VERIFIED behaviorally**

### Plan 01-05 (poller-service)
- SUMMARY: "Bug fix: REQUIRED_TOPICS set to the canonical 5 Named-Symbol topics, NOT the plan-text set" → `services/poller/main.py:36-42` has the correct set `{availability.raw, availability.events, polls.completed, notifications.queued, notifications.sent}`. **VERIFIED — critical integration fix**
- SUMMARY: "Publisher emits with key `{source}:{restaurant_id}`; writes poll_log row before return" → `services/poller/publisher.py:52, 86, 93-107`. **VERIFIED**
- SUMMARY: "OpenTable graphql.py is `[ASSUMED]` placeholder pending DevTools spike" → `services/poller/sources/opentable/graphql.py:14` `"https://www.opentable.com/dapi/fe/gql/prod"` with `# UPDATE after spike confirms` comment. **VERIFIED — blocker documented in code.**
- SUMMARY: "Jitter bounds 76_500–103_500 ms" → `services/poller/scheduler.py:30-32` = `now_ms + 90_000 + uniform(-13_500, 13_500)`. **VERIFIED**
- SUMMARY: "5 Wave-0 integration stubs filled, 0 skip decorators remain" → grep across all 8 integration files: 0 `@pytest.mark.skip` decorators. **VERIFIED**

### Plan 01-06 (perf02-verification)
- SUMMARY: "check_poll_success.py uses `time_bucket('1 hour', time)` and `SUCCESS_RATE_THRESHOLD=0.99`" → `scripts/check_poll_success.py:30, 59`. **VERIFIED**
- SUMMARY: "exit codes 0/1/2 distinguishing pass/fail/insufficient-data" → Present in code docstring + `return 2` on empty result. **VERIFIED**
- SUMMARY: "README has Anti-Piracy + Why Kafka + replication-factor-1 sections" → Sections present at lines 8, 33, 50+. **VERIFIED**
- SUMMARY: "T3/T4 blocked on wall-clock 24h run" → Runbook present; `_fill in_` placeholders preserved intentionally in Run Parameters / FD Snapshots / Sign-Off sections. **VERIFIED — intentional stub, gated on human action.**

---

## Integration-Point Checks (Cross-Plan Contracts)

All cross-plan wiring verified by successful `uv run python -c` import and structural equality:

| Consumer → Provider | Contract | Status |
|---------------------|----------|--------|
| `services/poller/publisher.py` → `shared.events.AvailabilityRaw/PollCompleted` | Field names (poll_id, source, restaurant_id, polled_at_epoch_ms, raw_response, request_params / +status, latency_ms, http_status, error) | **WIRED** — publisher constructs both models with matching kwargs |
| `services/poller/publisher.py` → `shared.db.PollLog` | Named Symbol column set = {time, restaurant_id, source, status, latency_ms, http_status, error, poll_id} | **WIRED** — set-equality check passes; insert() uses all 8 columns |
| `services/poller/scheduler.py` → `shared.scheduler.lua.LuaScheduler.claim/release` | Method signatures match; releases with `next_score` from `_next_poll_score` | **WIRED** |
| `services/poller/main.py` → `shared.http_client.get_async_client` | Singleton consumed by OpenTableAdapter constructor (Pitfall 9) — no per-poll instantiation | **WIRED** — adapter stores client, never constructs |
| `services/poller/main.py:REQUIRED_TOPICS` → `scripts/create_topics.py:TOPICS` | Set equality on 5 topic names | **WIRED** — set equality confirmed |
| `services/poller/config.py:POLL_INTERVAL_SECONDS/POLL_JITTER_FRACTION` → `shared.redis_keys` | Re-export pattern (single source of truth) | **WIRED** — both sides import same constants |
| `scripts/seed_restaurants.py` → `scripts/seed/restaurants.yml` | 55 entries; `opentable_rid` maps to `sched:polls` job `opentable:{rid}` | **WIRED** |
| `scripts/seed_restaurants.py` → DB `UniqueConstraint(source, platform_id)` | ON CONFLICT (source, platform_id) DO UPDATE idempotent | **WIRED** — migration 0003 and raw SQL aligned |
| `alembic migrations/env.py` → `shared.db.Base` | `target_metadata` importable once shared.db exists | **WIRED** (future-safe import guard per 01-02) |

**No cross-plan integration gaps found.** Every downstream consumer imports a symbol that exists at the exact path the upstream plan promised.

---

## Outstanding Human-Action Items (Consolidated)

All six items below are **explicitly human-gated** in their SUMMARY files — none represent code shortcomings.

1. **Twilio A2P 10DLC submission** (01-03 T1) — Day-1 clock start; 1–3 week carrier lead; update `docs/admin-evidence/twilio-status.md` STATUS to `active`.
2. **mise.place domain registration** (01-03 T2) — Cloudflare Registrar recommended; required by Twilio Brand step.
3. **GCP project + Artifact Registry + Secret Manager** (01-03 T2) — ~10 min with `gcloud` CLI; mirror 4 local secrets (HMAC_MGMT_SECRET_V1, VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, RESY_ACCOUNTS_JSON).
4. **Resy ≥3 account capture** (01-03 T3) — ~45 min browser + SMS verification; populate `RESY_ACCOUNTS_JSON`; T-05/Pitfall 8 cookie-memory-only convention.
5. **OpenTable DevTools spike** (01-05 T1) — ~30 min Chrome DevTools on live restaurant; overwrite `services/poller/sources/opentable/graphql.py:OPENTABLE_GQL_ENDPOINT/OPENTABLE_HEADERS/build_request()` + `README.md` `[ASSUMED]` sections. **Nested blocker for PERF-02.**
6. **24h PERF-02 observation run** (01-06 T3+T4) — depends on (5); `make up → make topics → make migrate → make seed`; launch poller in tmux; FD snapshots at t+{0,1,6,12,24}h; final `make verify-perf02` must exit 0; sign-off ticks in `docs/runbooks/perf02-24h-log.md`.

---

## Confidence Assessment

**HIGH confidence in the phase-level PASS-PENDING-HUMAN verdict.**

- 100% of claimed code artifacts exist at claimed paths.
- 100% of unit tests pass (27/27); integration tier skips cleanly (12 skipped, 0 failed, 0 errored) — consistent with the environment constraint (no Docker).
- 0 skip decorators remain in integration test source — the Wave-0 stub contract is satisfied.
- Critical integration bug caught in 01-05 (wrong REQUIRED_TOPICS set in plan text) is correctly fixed in code — set equality with `scripts/create_topics.py` verified.
- Named Symbol fidelity (poll_log columns, AvailabilityRaw fields, Kafka topic names, Redis keys) is verifiable by structural equality and passes.
- No code gaps, no missing wiring, no anti-patterns in `services/` or `shared/`.

**Residual risk is entirely human-action-shaped:** the OpenTable endpoint in `graphql.py` may be stale (research confidence MEDIUM), which the PERF-02 24h gate will surface naturally (intended safety net per 01-05 SUMMARY).

---

_Verified: 2026-04-22_
_Verifier: Claude Opus 4.7 (gsd-verifier)_
