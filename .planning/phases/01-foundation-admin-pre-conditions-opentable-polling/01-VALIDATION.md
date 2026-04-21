---
phase: 1
slug: foundation-admin-pre-conditions-opentable-polling
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-21
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution. Derived from RESEARCH.md § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest 8.x` + `pytest-asyncio 1.1.0` (`asyncio_mode = "auto"`) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`) — created in Wave 0 |
| **Quick run command** | `uv run pytest tests/unit -x -q` |
| **Full suite command** | `uv run pytest tests/unit tests/integration -v` |
| **Estimated runtime** | Quick: ~10s · Full: ~120s (testcontainers cold-start dominates) |

Integration tests use `testcontainers-python==4.x` with **per-file (module) scope** for Kafka/Redis/Postgres+TimescaleDB (D-34). OpenTable is mocked via `respx` in integration; real calls occur only during PERF-02 24h run.

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest tests/unit -x -q` (< 10s)
- **After every plan wave:** Run `uv run pytest tests/unit tests/integration -v` (full suite)
- **Before `/gsd-verify-work`:** Full suite must be green, plus PERF-02 24h run (SC5) must have been launched
- **Max feedback latency:** 10 seconds (unit tier)

CI runs both tiers on every PR (D-35). E2E tier deferred to Phase 7.

---

## Per-Criterion Verification Map

Phase 1 validates against ROADMAP Success Criteria (SC1–SC5), each mapped to a named test/artifact from RESEARCH.md.

| SC | Requirement | Test Type | Named Artifact | Automated Command | Status |
|----|-------------|-----------|----------------|-------------------|--------|
| SC1 | `docker compose up` boots infra; poller emits `availability.raw` within 60s | integration + manual smoke | `tests/integration/test_poller_smoke.py::test_end_to_end_emit_within_60s` + `make smoke` | `uv run pytest tests/integration/test_poller_smoke.py -v` / `make smoke` | ⬜ pending (W0) |
| SC2 | Twilio 10DLC submission in Pending/Registered; toll-free backup registered | manual runbook completion | `docs/runbooks/twilio-10dlc-setup.md` checklist + screenshot evidence committed to `docs/admin-evidence/` | Manual — record in `docs/admin-evidence/twilio-status.md` | ⬜ pending (W0) |
| SC3 | ≥50 NYC restaurants fully populated; scheduled in `sched:polls` ZSET | integration + SQL/Redis check | `tests/integration/test_seed_idempotency.py::test_seed_populates_all_fields_and_zset` + `make verify-seed` | `uv run pytest tests/integration/test_seed_idempotency.py -v` / `make verify-seed` | ⬜ pending (W0) |
| SC4 | `availability_events` and `poll_log` hypertables have `chunk_time_interval = 1 day`; `polls.completed` written with latency | integration + SQL introspection | `tests/integration/test_hypertable_config.py::test_chunk_interval_is_one_day` + `tests/integration/test_poll_log_writes.py::test_poll_writes_row_with_latency` | `uv run pytest tests/integration/test_hypertable_config.py tests/integration/test_poll_log_writes.py -v` | ⬜ pending (W0) |
| SC5 / PERF-02 | Poll success ≥99% hourly across 24h; stable FD count | SQL verification + FD audit | `scripts/check_poll_success.py` + `make verify-perf02` + `docs/runbooks/perf02-24h-log.md` | `make verify-perf02` (asserts all 24 hourly buckets ≥ 0.99) | ⬜ pending (W0) |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Task-Level Verification (populated by planner)

The planner expands this table with one row per task emitted across plans 01–05 (Wave 0..5), using the template below. Every task must have either an `<automated>` verification command OR a Wave 0 artifact it depends on.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-00-01 | 00-bootstrap | 0 | FOUND-01 | — | pyproject.toml + uv.lock committed | unit (import test) | `uv run python -c "import shared.events"` | ❌ W0 | ⬜ pending |

---

## Wave 0 Requirements

Wave 0 installs test infrastructure and creates the stubs that later waves fill in. Nothing in Wave 0 is skippable — subsequent waves' `<automated>` references point at these files.

- [ ] `pyproject.toml` — `[tool.pytest.ini_options]` block with `asyncio_mode = "auto"`, `testpaths = ["tests"]`, `pythonpath = ["."]`, dev dependency group containing `pytest`, `pytest-asyncio==1.1.0`, `testcontainers[kafka,redis,postgres]==4.*`, `respx`, `pytest-httpx`, `ruff`, `mypy`
- [ ] `tests/conftest.py` — shared fixtures (event loop, structured-log silencer, testcontainers `kafka_container`, `redis_container`, `postgres_container` at `scope="module"`)
- [ ] `tests/unit/__init__.py` + `tests/integration/__init__.py` — package markers
- [ ] `tests/unit/test_redis_keys.py` — stubs for `shared.redis_keys` constants
- [ ] `tests/unit/test_events_schema.py` — stubs for `shared.events` Pydantic models (AvailabilityRawEvent, PollsCompletedEvent)
- [ ] `tests/integration/test_poller_smoke.py` — stub for SC1
- [ ] `tests/integration/test_seed_idempotency.py` — stub for SC3
- [ ] `tests/integration/test_hypertable_config.py` — stub for SC4
- [ ] `tests/integration/test_poll_log_writes.py` — stub for SC4
- [ ] `tests/integration/test_topics_created.py` — stub for FOUND-04 / POLL-07
- [ ] `tests/integration/test_redis_config.py` — stub for Pitfall 18 (`maxmemory-policy = noeviction`)
- [ ] `tests/integration/test_scheduler_claim_release.py` — stub for POLL-01 (Lua ZSET script)
- [ ] `scripts/check_poll_success.py` — stub for SC5 / PERF-02
- [ ] `Makefile` — targets `smoke`, `verify-seed`, `verify-perf02`, `test`, `test-integration` (see D-10)
- [ ] `docs/runbooks/perf02-24h-log.md` — stub log format
- [ ] `docs/admin-evidence/` — directory for Twilio/domain/GCP screenshots (SC2)
- [ ] CI lint rule file — `.ruff.toml` or `pyproject.toml [tool.ruff]` banning `import requests`, `time.sleep(` in async code, `import redis\n` without `.asyncio` (Pitfall 16)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Twilio A2P 10DLC Standard Campaign submitted | SC2 / FOUND-03 | Requires Twilio Console login, identity verification, and multi-week carrier approval clock | Follow `docs/runbooks/twilio-10dlc-setup.md`; record Brand SID, Campaign SID, and status screenshot in `docs/admin-evidence/twilio-status.md`. Toll-free number purchased + registered as backup — record SID in same file. |
| `mise.place` domain registered | FOUND-04 | Requires registrar account + payment | Record registrar, expiry date, and DNS provider in `docs/admin-evidence/domain.md` |
| GCP project provisioned + APIs enabled | FOUND-05 | Requires GCP console / billing | `gcloud projects create mise-en-place-prod` then enable Artifact Registry + Secret Manager APIs; record project ID in `docs/admin-evidence/gcp.md` |
| Resy pre-auth accounts captured | FOUND-06 | Requires real Resy signups and manual login capture | Stored in `.env` (`RESY_ACCOUNTS_JSON`) + GCP Secret Manager; record account count (≥3) in `docs/admin-evidence/resy.md` |
| 50 NYC restaurants hand-curated | SC3 / D-14..D-16 | Curation is narrative/editorial judgment, not scriptable | Edit `scripts/seed/restaurants.yml`; `make verify-seed` enforces ≥50 rows with all 5 required fields populated |
| FD count stable over 24h | SC5 | Requires wall-clock 24h observation | Capture `ls /proc/$(pgrep -f services.poller)/fd \| wc -l` snapshots in `docs/runbooks/perf02-24h-log.md` at t=0, t=1h, t=6h, t=12h, t=24h |
| OpenTable GraphQL endpoint verification spike | A1 assumption | Endpoint path/headers not publicly documented; 30-min DevTools inspection | Captured in `services/poller/sources/opentable/README.md` — record exact URL, required headers, sample request/response |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s (unit) / < 120s (full)
- [ ] `nyquist_compliant: true` set in frontmatter after planner populates task rows
- [ ] SC2 manual evidence committed to `docs/admin-evidence/` before phase verification
- [ ] PERF-02 24h run launched with timestamp recorded in `docs/runbooks/perf02-24h-log.md`

**Approval:** pending
