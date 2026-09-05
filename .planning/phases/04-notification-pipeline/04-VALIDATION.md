---
phase: 04
slug: notification-pipeline
# status lifecycle: draft (seeded by plan-phase) → validated (set by validate-phase §6)
# audit-milestone §5.5 distinguishes NOT-VALIDATED (draft) from PARTIAL (validated + nyquist_compliant: false) (#2117)
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-05
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio 1.3.0 (`asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — `testpaths = ["tests"]`, `pythonpath = ["."]`, marker `integration` |
| **Quick run command** | `make test` → `uv run pytest tests/unit -x -q -W error::RuntimeWarning` |
| **Full suite command** | `make test-integration` → `uv run pytest tests/unit tests/integration -v` |
| **Lint gate** | `make lint` → `uv run ruff check . && uv run mypy shared/ services/ scripts/` |
| **Container fixtures** | `tests/conftest.py` — module-scoped `kafka_container` (cp-kafka:7.6.0), `redis_container` (redis:7.2-alpine, `maxmemory-policy=noeviction`), `timescale_container` (timescaledb:2.17.2-pg16); all skip when Docker is unreachable |
| **Integration helpers** | `tests/integration/conftest.py` — `apply_migrations`, `create_topics`, `reset_shared_db_singletons`, `redis_url`, `db_urls`; this phase adds `seed_user_and_watch`, `fake_push_subscription`, `api_client` |
| **Estimated runtime** | unit tier ~30 s; unit + integration ~15 min (container startup dominates) |
| **New packages** | none — this phase installs zero dependencies, and `tests/unit/test_no_new_runtime_deps.py` enforces it |

---

## Sampling Rate

- **After every task commit:** `make test` plus `make lint`. Both are seconds-scale and catch every grep gate, both signature vector sets, the SMS septet budget and every `mypy --strict` regression.
- **After every plan wave:** `make test-integration` (Docker required).
- **Before `/gsd-verify-work`:** full suite green, plus `make verify-perf01` and `make verify-perf03` exercised against the synthetic fixtures so the exit-code contract is proven.
- **Max feedback latency:** 30 s at the unit tier.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 04-01-01 | 01 | 1 | NOTIF-07 | T-04-01 / T-04-02 / T-04-03 | Full 32-byte HMAC verified with `compare_digest` over the encoded payload BEFORE any JSON parse; purpose claim enforced per route | unit (tracer) | `uv run pytest tests/unit/test_tokens.py tests/unit/test_links.py -q -W error::RuntimeWarning` | ❌ W0 (task creates) | ⬜ pending |
| 04-01-02 | 01 | 1 | NOTIF-04 | T-04-06 / T-04-07 / T-04-08 | AES-256-GCM with a fresh 12-byte nonce, explicit key-length guard, one canonicalisation for `phone_hash`; SIGKILL allowlist fails closed with one definition site | unit | `uv run pytest tests/unit/test_crypto.py tests/unit/test_telemetry_redaction.py tests/unit/test_state_machine_startup.py -q -W error::RuntimeWarning` | ❌ W0 (task creates `test_crypto.py`; extends `test_telemetry_redaction.py`) | ⬜ pending |
| 04-01-03 | 01 | 1 | NOTIF-04 | T-04-04 / T-04-05 | Twilio HMAC-SHA1 over the CONFIG-derived URL and Svix HMAC-SHA256 over the raw body, both constant-time, both replay-bounded | unit | `uv run pytest tests/unit/test_twilio_signature.py tests/unit/test_svix_signature.py -q -W error::RuntimeWarning` | ❌ W0 (task creates) | ⬜ pending |
| 04-02-01 | 02 | 1 | NOTIF-02, NOTIF-06 | T-04-09 / T-04-10 / T-04-11 / T-04-12 | Single `SET … NX EX` claim, TTL always set in the same command or script, Layer-3 partial unique index on the identical triple | integration (tracer) | `uv run pytest tests/integration/test_notif_claim_and_cap.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-02-02 | 02 | 1 | NOTIF-01 | T-04-13 | Frozen, `extra="forbid"` wire schemas; deterministic `job_id` reused as the provider idempotency key | unit | `uv run pytest tests/unit/test_notification_events_schema.py tests/unit/test_events_schema.py -q -W error::RuntimeWarning` | ❌ W0 (task creates) | ⬜ pending |
| 04-02-03 | 02 | 1 | NOTIF-02 | T-04-12 / T-04-14 | Injective claim keys; migration guard reports a COUNT and a remedy, never row values | unit + integration | `uv run pytest tests/unit/test_notif_idempotency_key.py tests/integration/test_migration_0010.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-03-01 | 03 | 2 | NOTIF-01, NOTIF-06 | T-04-18 / T-04-19 | Bound parameters only, platform id bound as a string; failures logged by shape | integration (tracer) | `uv run pytest tests/integration/test_notifier_fanout.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-03-02 | 03 | 2 | NOTIF-01 | — | Pure matcher: no clock, no I/O, no entropy; fail-closed on an unparseable slot | unit | `uv run pytest tests/unit/test_matching_matrix.py tests/unit/test_notifier_config_lazy.py -q -W error::RuntimeWarning` | ❌ W0 (task creates) | ⬜ pending |
| 04-03-03 | 03 | 2 | NOTIF-02, NOTIF-06 | T-04-15 / T-04-16 / T-04-17 / T-04-20 | Cap enforced before any publish; seek-back on transient, dead-letter then commit on poison; never auto-commit | unit + integration | `uv run pytest tests/unit/test_notifier_offset_policy.py tests/integration/test_notifier_rate_limit.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-04-01 | 04 | 2 | NOTIF-07, PERF-03 | T-04-23 / T-04-25 / T-04-26 | Purpose-checked capability token; `Cache-Control: no-store`; three-way availability answer | integration (tracer, ASGI) | `uv run pytest tests/integration/test_api_go.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-04-02 | 04 | 2 | NOTIF-04 | T-04-24 / T-04-SC | Mutating path is POST only; a prefetched GET renders a form; no runtime dependency added | unit + integration | `uv run pytest tests/unit/test_no_new_runtime_deps.py tests/integration/test_api_unsubscribe.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-04-03 | 04 | 2 | NOTIF-04, NOTIF-06 | T-04-21 / T-04-22 / T-04-27 | Signature verified against the config-derived URL / raw body BEFORE any write; 403 short-circuits | integration (ASGI) | `uv run pytest tests/integration/test_api_webhooks.py tests/integration/test_notification_log_transitions.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-05-01 | 05 | 3 | NOTIF-03 | T-04-29 / T-04-30 | Shared httpx client injected; clamped `Retry-After`; no body or recipient in any log field | unit (tracer, respx) | `uv run pytest tests/unit/test_provider_email.py tests/unit/test_metrics_registry.py -q -W error::RuntimeWarning` | ❌ W0 (task creates `test_provider_email.py`; `test_metrics_registry.py` is a Phase-3 artifact) | ⬜ pending |
| 04-05-02 | 05 | 3 | NOTIF-04 | T-04-34 | Phone decrypted only inside the SMS provider; `InvalidTag` caught by type and recorded as a code | unit (respx) | `uv run pytest tests/unit/test_templates_sms_length.py tests/unit/test_provider_sms.py -q -W error::RuntimeWarning` | ❌ W0 (task creates, incl. `tests/unit/gsm7.py`) | ⬜ pending |
| 04-05-03 | 05 | 3 | NOTIF-05 | T-04-31 / T-04-32 / T-04-33 / T-04-35 | Per-endpoint VAPID audience, explicit 12 h expiry, non-empty title/body, no vendor SDK in either source tree | unit (respx) | `uv run pytest tests/unit/test_provider_push.py tests/unit/test_push_revocation.py tests/unit/test_retry_policy.py tests/unit/test_no_sync_sdk_imports.py -q -W error::RuntimeWarning` | ❌ W0 (task creates) | ⬜ pending |
| 04-06-01 | 06 | 4 | NOTIF-06, PERF-01 | T-04-37 / T-04-38 / T-04-39 | Commit only after the row is durable and the publish is acknowledged; `sms_opt_out` re-checked at the worker | integration (tracer) | `uv run pytest tests/integration/test_notifier_e2e.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-06-02 | 06 | 4 | NOTIF-02 (ROADMAP SC2) | T-04-36 / T-04-41 | Claim strictly precedes the provider call; SIGKILL between ack and commit yields exactly one provider-side send | integration (chaos, subprocess) | `uv run pytest tests/integration/test_notifier_chaos.py -q -p no:cacheprovider` | ❌ W0 (task creates, incl. `tests/fakes/provider_stub.py`) | ⬜ pending |
| 04-06-03 | 06 | 4 | NOTIF-02, NOTIF-06 | T-04-40 / T-04-42 | Ordering asserted as a sequence; no hand-rolled sleep in either new service tree; both consumer groups manual-commit | unit | `uv run pytest tests/unit/test_idempotency_ordering.py tests/unit/test_no_inline_sleep.py tests/unit/test_kafka_consumer_config.py -q -W error::RuntimeWarning` | ❌ W0 (task creates `test_idempotency_ordering.py`; extends the two gates) | ⬜ pending |
| 04-07-01 | 07 | 5 | PERF-01 | T-04-43 / T-04-44 | Three-way exit codes; aggregate output only, no row-level identifiers | integration (subprocess) | `uv run pytest tests/integration/test_check_notification_latency.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-07-02 | 07 | 5 | PERF-03 | T-04-43 / T-04-44 | Strict `<` at the threshold; unclassifiable clicks excluded from both halves and reported | integration (subprocess) | `uv run pytest tests/integration/test_check_false_positive_rate.py -q -p no:cacheprovider` | ❌ W0 (task creates) | ⬜ pending |
| 04-07-03 | 07 | 5 | PERF-01, PERF-03 | T-04-45 / T-04-46 / T-04-47 | Human-gated criteria recorded as `pending-human`, never as passes; `.env.example` keeps placeholder values | unit + lint | `uv run pytest tests/unit -q -W error::RuntimeWarning && uv run ruff check .` | ✅ (existing suite) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Sampling continuity:** every one of the 21 tasks carries an `<automated>` verify, so there is no
run of three consecutive tasks without automated feedback.

---

## Wave 0 Requirements

Every test file this phase needs is created by the task that depends on it, inside its own plan, so
there is no separate Wave-0 plan. The four SHARED fixtures other tasks depend on are called out here
because they must land with their first consumer rather than being deferred:

- [ ] `tests/unit/fixtures/__init__.py` + `tests/unit/fixtures/vectors.py` — the four Twilio and two
      Svix published vectors as parametrisable constants. **Owner: 04-01 task 3.**
- [ ] `tests/integration/conftest.py::seed_user_and_watch` — sets `created_at`/`updated_at`
      EXPLICITLY (the ORM declares them `nullable=False` with no `server_default`, so an omission
      fails on a NOT NULL violation) — and `fake_push_subscription()` generating a real P-256 keypair
      so 04-05's push assertions can decrypt. **Owner: 04-02 task 1.**
- [ ] `tests/unit/factories.py` — extend the existing file with `make_availability_event`,
      `make_notification_queued`, `make_watch_row`. **Owner: 04-02 task 2.**
- [ ] `tests/integration/conftest.py::api_client` — `httpx.AsyncClient(transport=ASGITransport(
      app=create_app()), base_url="https://api.mise.place")`, importing `create_app` inside the
      fixture body. **Owner: 04-04 task 1.**
- [ ] `tests/unit/gsm7.py` — the GSM 03.38 septet helper, independent of the renderer it checks.
      **Owner: 04-05 task 2.**
- [ ] `tests/fakes/provider_stub.py` — a real listener with a readable hit log, because `respx`
      patches httpx in-process and cannot survive the SIGKILLed chaos subprocess. Added to the
      existing `tests/fakes/` package created by Phase 3 plan 03-04. **Owner: 04-06 task 2.**

**Framework install:** none needed — pytest, pytest-asyncio, respx and testcontainers are all
present and version-verified.

**Cross-phase preconditions (declared on the consuming tasks, not deferrable):**

| Artifact | Created by | Consumed by | Precondition task |
|----------|-----------|-------------|-------------------|
| `migrations/versions/0009_*` | Phase 3 plan 03-03 | migration 0010's `down_revision` | 04-02 task 1 |
| `shared/metrics.py` (single definition site) | Phase 3 plan 03-02 | the two new notification metrics | 04-05 task 1 |
| `shared/telemetry.py::_redact_secrets` case-insensitive form | Phase 3 plan 03-02 (D-61a) | the new secret and value-shaped keys | 04-01 task 2 |
| `tests/fakes/__init__.py` | Phase 3 plan 03-04 | `tests/fakes/provider_stub.py` | 04-06 task 2 |

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| p95 detection-to-notification latency over a sustained 24-hour production window | PERF-01 / ROADMAP SC1 | Needs 24 hours of real traffic through real providers; no test can compress wall-clock time, and synthetic rows prove only the gate, not the system | `docs/runbooks/perf01-latency.md` (`STATUS: pending-human`): bring the stack up with real Twilio and Resend credentials, run 24 h, then `make verify-perf01` and capture its output and exit code |
| A real iPhone in PWA standalone mode receives 5 consecutive Web Push notifications without the subscription being revoked | NOTIF-05 / ROADMAP SC3 | Needs physical Apple hardware AND the service worker, which is Phase 6 — the `push` handler must wrap the whole async chain in `event.waitUntil(...)` | `docs/runbooks/ios-pwa-push.md` (`STATUS: pending-human`): install the PWA on a real device, send 5 pushes, confirm all 5 render and `push_subscriptions.revoked_at` stays NULL. Blocked until Phase 6 |
| STOP on a live US number and one-click unsubscribe verified against a real inbound webhook | NOTIF-04 / ROADMAP SC4 (live half) | Needs Twilio A2P 10DLC approval and a provisioned number | `docs/runbooks/perf01-latency.md` preconditions section. The signed-webhook half IS automated in `tests/integration/test_api_webhooks.py`, which proves the handler; only the live carrier round trip is manual |
| Deep links land on the correct pre-filled booking slot | NOTIF-07 / ROADMAP SC5 (live half) | Both platform URL schemes are `[ASSUMED]` (research A1/A2); OpenTable's public RestRef API is reported shut down, so only a human clicking a produced link can confirm the form | Recorded in `.planning/deferred-items.md` with the alternate candidate form. The URL SHAPE is automated in `tests/unit/test_links.py` and `tests/integration/test_api_go.py` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — 21/21 tasks carry one
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references — six shared fixtures, each with a named owning task
- [x] No watch-mode flags — every command is single-shot; `-p no:cacheprovider` on the container tier
- [x] Feedback latency < 30 s at the unit tier
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
