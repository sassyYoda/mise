# Phase 4: Notification Pipeline - Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 38 new/modified files (excluding the 26 test files, which are classified as one group with three analogs)
**Analogs found:** 34 / 38 (4 with no analog)

> All excerpts below were read fresh from disk this session. The Phase 2 files are under
> concurrent edit by a code fixer (bounded retry + DLQ, `safe_error`, store boundary guard) —
> the excerpts already include those changes (`_dead_letter`, `_max_attempts`,
> `shared/telemetry.py :: safe_error`, `store.get_slots` widened except tuple).

---

## Phase 3 artifacts that DO NOT EXIST on disk yet

Phase 3 has not executed. The planner must treat these as **created by Phase 3, appended to by Phase 4**, and must plan for the "Phase 3 not merged yet" case explicitly:

| Artifact | Defined by | Disk status (verified) |
|----------|-----------|------------------------|
| `shared/metrics.py` | Phase 3 **D-69** (metrics defined once: `scrape_ban_total`, `poll_latency_seconds`, `poll_total`, …) | **absent** — `ls shared/` shows no `metrics.py`. Phase 4's `notification_latency_seconds` / `notifications_total` (D-86) must be *added to* that module, never redefined; if Phase 3 has not landed, Phase 4 creates it with only its own metrics and a header comment claiming the single-definition rule. |
| `shared/events.py :: FAILED_POLL_STATUSES` | Phase 3 **D-67a** (frozenset shared by consumer + `replay_raw.py`) | **absent** — `shared/events.py` is 133 lines, ends at `AvailabilityEvent`; `status` Literal is still `success\|error\|timeout` (no `banned`). |
| `shared/telemetry.py` redaction extension (`authorization`, `api_key`, `cookie`, …) | Phase 3 **D-61a (B-6)** | **partially absent** — `_redact_secrets` (telemetry.py:87-102) currently redacts only `TWILIO_AUTH_TOKEN`, `HMAC_MGMT_SECRET_V1`, `VAPID_PRIVATE_KEY`, `RESY_ACCOUNTS_JSON` + `RESY_ACCOUNT_*_PASSWORD`. Phase 4 (D-72 code_context) adds `authorization`, `api_key`, phone numbers on top. |
| `migrations/versions/0009_*` | Phase 3 **D-63b (B-5)** (`UNIQUE(slug, source)` on `restaurants`) | **absent** — head on disk is `0008`. Migration 0010's `down_revision = "0009"` (D-89 sequencing) will not apply until Phase 3 lands. Plan a Wave-0 check. |
| `services/poller/sources/resy/*`, `scripts/soak_playwright.py` | Phase 3 | absent (irrelevant to Phase 4 except for the grep gates' scanned-dir lists). |

---

## File Classification

### `services/notifier/` (new service)

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/notifier/config.py` | config | — | `services/state_machine/config.py` | exact |
| `services/notifier/main.py` | entrypoint | — | `services/state_machine/main.py` | exact |
| `services/notifier/__main__.py` | entrypoint | — | `services/state_machine/__main__.py` | exact |
| `services/notifier/consumer.py` (loop A, fan-out) | consumer | event-driven | `services/state_machine/consumer.py` | exact |
| `services/notifier/workers.py` (loop B, delivery) | consumer | event-driven | `services/state_machine/consumer.py` (`_apply_emit` ordering) | exact |
| `services/notifier/dispatcher.py` | service | transform / pub-sub | `services/state_machine/consumer.py :: _handle_raw` | role-match |
| `services/notifier/matching.py` | pure function | transform | `services/state_machine/engine.py` (pure, no I/O) + `persistence.py :: day_of_week/_parse_time_slot` | role-match |
| `services/notifier/persistence.py` | persistence | CRUD | `services/state_machine/persistence.py` | exact (with an **inverted** best-effort rule — see Shared Pattern E) |
| `services/notifier/templates.py` | utility | transform | *(none)* | **no analog** |
| `services/notifier/pattern_hook.py` | utility | transform | `services/state_machine/parsers/__init__.py` (registry-stub shape) | partial |
| `services/notifier/providers/email.py` | provider client | request-response | `services/poller/sources/opentable/adapter.py` | role-match |
| `services/notifier/providers/sms.py` | provider client | request-response | same | role-match |
| `services/notifier/providers/push.py` | provider client | request-response | same (+ research BC-1 transcript for crypto) | partial |
| `services/notifier/README.md` | doc | — | `services/state_machine/consumer.py` module docstring + crash table in research | role-match |

### `services/api/` (new FastAPI skeleton)

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/api/app.py` | app factory | request-response | `services/state_machine/main.py` (lifespan/AsyncExitStack shape only) | partial |
| `services/api/routers/links.py` | router | request-response | *(none — first HTTP server in the repo)* | **no analog** |
| `services/api/routers/webhooks.py` | router | request-response | *(none)* | **no analog** |
| `services/api/config.py` (if split) | config | — | `services/state_machine/config.py` | exact |

### `shared/` additions

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `shared/tokens.py` | utility (crypto) | transform | `shared/redis_keys.py :: event_idempotency_key` (escaping/injectivity discipline) | partial |
| `shared/links.py` | utility | transform | `shared/redis_keys.py :: job()` | partial |
| `shared/crypto.py` | utility (crypto) | transform | *(none)* | **no analog** |
| `shared/twilio_signature.py` | utility (pure verifier) | transform | `shared/redis_keys.py` (pure module, no I/O) | partial |
| `shared/svix_signature.py` | utility (pure verifier) | transform | same | partial |
| `shared/crash_hook.py` (D-88) | config/safety | — | `services/state_machine/config.py:67-88` **moved verbatim** | exact |
| `shared/events.py` (+`NotificationQueued`, `NotificationSent`) | model | pub-sub | `shared/events.py :: AvailabilityEvent` | exact |
| `shared/redis_keys.py` (+`notif_idempotency_key`, `NOTIF_IDEMPOTENCY_TTL_SECONDS`, `rate:notif:*` + Lua) | config/registry | — | `shared/redis_keys.py :: event_idempotency_key`, `set_nx_ex`, `shared/scheduler/lua.py` | exact |
| `services/state_machine/config.py` (re-export `crash_hook_allowed`) | config | — | itself (lines 20-37 re-export idiom for `CONFIRM_DELAY_MS`) | exact |

### migrations / scripts / ops

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `migrations/versions/0010_notification_pipeline.py` | migration | — | `migrations/versions/0008_add_event_id_to_availability_events.py` | exact |
| `scripts/create_topics.py` (+`notifications.dlq`) | script | — | itself (lines 47-56, the `availability.dlq` entry) | exact |
| `scripts/check_notification_latency.py` | script | batch | `scripts/check_poll_success.py` | exact |
| `scripts/check_false_positive_rate.py` | script | batch | `scripts/check_poll_success.py` | exact |
| `Makefile` (+`notifier`, `api`, `verify-perf01`, `verify-perf03`) | config | — | `Makefile:20-27, 56-57` | exact |
| `.env.example` (provider block) | config | — | `.env.example:39-67` | exact |
| `docs/runbooks/ios-pwa-push.md` | doc | — | `docs/runbooks/twilio-10dlc-setup.md` | exact |
| `docs/runbooks/perf01-latency.md` | doc | — | `docs/runbooks/perf02-24h-log.md` | exact |

### tests (26 new files, grouped)

| Group | Analog | Match |
|-------|--------|-------|
| Pure-logic unit tests (matching matrix, templates/GSM-7, tokens, links, signatures, crypto) | `tests/unit/test_engine_transitions.py`, `tests/unit/test_parsers_opentable.py` | role-match |
| Grep gates (`test_no_sync_sdk_imports.py`, `test_no_new_runtime_deps.py`, extended no-sleep / no-SETNX) | `tests/unit/test_no_inline_sleep.py`, `tests/unit/test_no_setnx_expire_pairs.py` | exact |
| Config-assertion units (`enable_auto_commit=False` on the notifier factory) | `tests/unit/test_kafka_consumer_config.py`, `test_offset_commit_policy.py` | exact |
| Integration e2e | `tests/integration/test_state_machine_e2e.py` + `tests/integration/conftest.py` | exact |
| Chaos (`MISE_CRASH_AFTER=provider_ack`) | `tests/integration/test_state_machine_chaos.py` | exact |
| API route tests (ASGITransport) | *(none)* | **no analog** (use research `[VERIFIED: transcript]` shape) |

---

## Pattern Assignments

### `services/notifier/config.py` (config)

**Analog:** `services/state_machine/config.py` — copy the *whole shape*: module docstring naming symbols, `__all__` for mypy-strict re-exports, and **functions, never module constants**.

Lazy accessor + the reason (lines 7-14, 44-51):

```python
"""
Every environment read below is a FUNCTION, not a module constant, and that is deliberate.
`services/poller/config.py` freezes KAFKA_BOOTSTRAP_SERVERS / REDIS_URL into module constants
at IMPORT time, so any integration test that imports the service during collection pins the
whole run to the localhost defaults instead of its testcontainers (02-02 deviation 1).
"""

CONSUMER_GROUP_ID: str = "state-machine"


def kafka_bootstrap_servers() -> str:
    """Broker list. Default matches services/poller/config.py — the two must never disagree."""
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
```

→ Phase 4: `CONSUMER_GROUP_ID = "notifier"`, `WORKER_GROUP_ID = "notifier-workers"` (D-75), plus `notify_daily_cap_per_user()`, `notify_dry_run()`, `resend_api_base()`, `twilio_api_base()`, `public_base_url()` as functions.

Re-export idiom to copy for `crash_hook_allowed` (D-88), lines 20-37:

```python
from shared.redis_keys import CONFIRM_DELAY_MS  # noqa: F401 (re-exported for consumers)

# `__all__` makes the re-export explicit for mypy --strict, which otherwise refuses to let
# another module import CONFIRM_DELAY_MS from here.
__all__ = ["CONFIRM_DELAY_MS", "CONSUMER_GROUP_ID", ...]
```

Bounded-attempt cap to copy verbatim into the notifier (lines 95-129): `DEFAULT_MAX_MESSAGE_ATTEMPTS: int = 5`, `max_message_attempts()` refusing `< 1` and non-numeric values with a `RuntimeError`.

---

### `shared/crash_hook.py` (D-88, safety config)

**Analog:** `services/state_machine/config.py:67-88` — **move these three symbols verbatim**, then re-export from the state-machine config so the Phase 2 tests keep passing.

```python
# The ONLY environments in which the SIGKILL hook may be armed (T-02-04). An allowlist, not a
# denylist: `ENV == "prod"` let `ENV=production`, `ENV=PROD` and a container that forgot to set
# ENV at all start happily with a hook whose entire job is to kill the process mid-pipeline.
# A safety interlock must fail CLOSED.
CRASH_HOOK_ENVS: frozenset[str] = frozenset({"dev", "test", "ci", "local"})


def crash_hook_allowed() -> bool:
    raw = os.getenv("ENV")
    return raw is not None and raw.strip().lower() in CRASH_HOOK_ENVS


def crash_after() -> str | None:
    """TEST ONLY (D-51): stage after which the consumer SIGKILLs itself. Unset everywhere else."""
    return os.getenv("MISE_CRASH_AFTER")
```

The `_maybe_crash` helper itself lives in the consumer (`services/state_machine/consumer.py:108-125`) and its docstring records the rule the notifier must not break: *"The environment read is `config.crash_after` and nothing else … two readers of a single safety-critical variable is one too many."* Phase 4 stages (D-87 + research): `nx_claim`, `provider_ack`, `log_insert`, `sent_publish`, `commit`.

---

### `services/notifier/main.py` (entrypoint)

**Analog:** `services/state_machine/main.py` (168 lines, read in full).

**Startup interlock** (lines 87-93) — copy including the message:

```python
    if crash_after() is not None and not crash_hook_allowed():
        raise RuntimeError(
            f"MISE_CRASH_AFTER is set but ENV={os.getenv('ENV')!r} is not one of "
            f"{sorted(CRASH_HOOK_ENVS)}. That variable is a TEST-ONLY hook that SIGKILLs this "
            "process at the named stage (T-02-04); unset it, or set ENV explicitly to a "
            "non-production environment."
        )
```

**Topic guard** (lines 49-78) — extend `REQUIRED_TOPICS` with `"notifications.dlq"`:

```python
REQUIRED_TOPICS: set[str] = {
    "availability.raw", "availability.events", "availability.dlq",
    "polls.completed", "notifications.queued", "notifications.sent",
}

async def _assert_topics_exist(bootstrap_servers: str) -> None:
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    try:
        await admin.start()
        existing = set(await admin.list_topics())
    finally:
        await admin.close()
    missing = REQUIRED_TOPICS - existing
    if missing:
        raise RuntimeError(f"Kafka topics missing: {sorted(missing)}. Run `make topics` first.")
```

**Lifespan** (lines 105-162) — `dispose_engine` pushed FIRST so it unwinds LAST; one producer; **two** consumers (D-75); `close_async_client` must also be registered (the state machine has no HTTP client, so this is the one addition):

```python
        async with AsyncExitStack() as stack:
            stack.push_async_callback(dispose_engine)
            r = redis.from_url(url)
            stack.push_async_callback(r.aclose)
            await _assert_topics_exist(bootstrap_servers)
            producer = await make_producer(bootstrap_servers)
            stack.push_async_callback(producer.stop)
            consumer = await make_consumer(
                "availability.raw", "polls.completed",
                group_id=CONSUMER_GROUP_ID, bootstrap_servers=bootstrap_servers,
            )
            stack.push_async_callback(consumer.stop)
            ...
            await run_until_signal(state_machine.run())
```

`shared/shutdown.py:33-59` accepts a single awaitable and uses `asyncio.ensure_future`, with the comment *"the poller hands in an `asyncio.gather(...)` future rather than a bare coroutine, and cancelling that future cancels its children"* — so the two notifier loops go in as `run_until_signal(asyncio.gather(loop_a.run(), loop_b.run()))`. Both consumers are constructed **inside** `run()` (aiokafka calls `get_running_loop()` in `__init__`).

---

### `services/notifier/consumer.py` and `workers.py` (consumer, event-driven)

**Analog:** `services/state_machine/consumer.py` (675 lines).

**Poison vs transient routing, bounded retry, DLQ, then commit** (lines 217-281) — the entire control flow to copy:

```python
        key = (msg.topic, msg.partition, msg.offset)
        if key != self._attempt_key:
            self._attempt_key = key
            self._attempts = 0
            self._acked_event_ids.clear()
        try:
            ...
        except (ValidationError, ParseError) as exc:
            self._discard()
            log.error("message_poison", topic=msg.topic, partition=msg.partition,
                      offset=msg.offset, error=_failure_shape(exc))
        except Exception as exc:  # noqa: BLE001 — presumed transient infrastructure failure
            self._discard()
            self._attempts += 1
            log.error("message_handling_failed", ..., attempt=self._attempts,
                      max_attempts=self._max_attempts, error=_failure_shape(exc))
            if self._attempts >= self._max_attempts:
                log.error("message_retries_exhausted", ..., metric=METRIC_MESSAGES_DEAD_LETTERED)
                await self._dead_letter(msg, exc)
                await self._commit(msg)
                return
            self._retry_later(msg)
            return
        await self._commit(msg)
```

Phase 4 poison tuple = `(ValidationError,)` + `TemplateRenderError` if templates can raise. A provider 4xx is **not** Kafka-layer poison — it is a definitive failure that dead-letters to `notifications.dlq` and then commits.

**Seek-back backoff without `asyncio.sleep`** (lines 355-381) — the no-sleep gate applies to `services/notifier` too (D-79):

```python
        topic_partition = TopicPartition(msg.topic, msg.partition)
        try:
            self.consumer.seek(topic_partition, msg.offset)
            self.consumer.pause(topic_partition)
        except Exception as exc:  # noqa: BLE001 — raised from an except block; nothing above catches
            log.warning("transient_retry_rewind_failed", ..., error=_failure_shape(exc))
            return
        pending = self._resume_handles.pop(topic_partition, None)
        if pending is not None:
            pending.cancel()
        self._resume_handles[topic_partition] = asyncio.get_running_loop().call_later(
            TRANSIENT_RETRY_BACKOFF_SECONDS, self._resume_partition, topic_partition
        )
```

Plus the bounded self-rescheduling `_resume_partition` (lines 383-432, `MAX_RESUME_ATTEMPTS = 3`) and `run()`'s `finally` that cancels every pending timer (lines 172-184).

**Commit** (lines 642-675) — copy including the `KafkaError` (not `CommitFailedError`) catch and the trailing crash hook:

```python
        topic_partition = TopicPartition(msg.topic, msg.partition)
        try:
            await self.consumer.commit({topic_partition: msg.offset + 1})
        except KafkaError as exc:
            log.warning("offset_commit_failed", topic=msg.topic, partition=msg.partition,
                        offset=msg.offset, error=_failure_shape(exc))
        _maybe_crash("commit")
```

**Dead-letter** (lines 300-330) — original bytes as the value, diagnostics as headers, best effort:

```python
            await self.producer.send_and_wait(
                DLQ_TOPIC, value=msg.value, key=f"{msg.topic}:{msg.partition}",
                headers=[("original_topic", msg.topic.encode()),
                         ("original_partition", str(msg.partition).encode()),
                         ("original_offset", str(msg.offset).encode()),
                         ("attempts", str(self._attempts).encode()),
                         ("error", str(_failure_shape(exc)).encode())],
            )
        except Exception as dlq_exc:  # noqa: BLE001 — a dead DLQ must not re-create the stall
            log.error("dead_letter_publish_failed", ..., error=_failure_shape(dlq_exc))
            return
```

**Claim → send → record ordering** (`_apply_emit`, lines 513-590) — the direct model for the worker's D-76 order:

```python
        claimed = await set_nx_ex(self.r, claim_key, "1", EVENT_IDEMPOTENCY_TTL_SECONDS)
        _maybe_crash("nx_claim")
        if not claimed and not await self._crashed_mid_emit(decision):
            log.info("emit_skipped_duplicate", event_id=str(event.event_id), ...)
            return
        ...
            # send_and_wait, never a bare send: the shared producer factory sets a batching
            # window, so a bare send can return before the broker acks and the offset commit
            # would overtake the record (research Pattern 4).
            await self.producer.send_and_wait(
                EVENTS_TOPIC, value=event.to_bytes(), key=job(event.source, event.restaurant_id),
            )
            self._acked_event_ids.add(event.event_id)
            _maybe_crash("kafka_send")
```

Worker mapping: `nx_claim` → `provider.send()` + `_maybe_crash("provider_ack")` → `notification_log` insert + `_maybe_crash("log_insert")` → `send_and_wait("notifications.sent")` + `_maybe_crash("sent_publish")` → `_commit(msg)` + `_maybe_crash("commit")`. **`DEL` the claim only on a definitive provider failure**, never on success (`_apply_emit` never deletes — that discipline is the pattern to preserve).

**Payload-safe logging** (lines 83-105) — copy `_failure_shape` verbatim into the notifier:

```python
def _failure_shape(exc: BaseException) -> list[str] | str:
    if isinstance(exc, ValidationError):
        return [f"{'.'.join(str(part) for part in error['loc'])}:{error['type']}"
                for error in exc.errors()]
    return f"{type(exc).__module__}.{type(exc).__name__}"
```

Use `_failure_shape` for producer-supplied data (an undecodable `NotificationQueued`); use `shared.telemetry.safe_error` for our own infrastructure failures (a provider/asyncpg error) — `shared/telemetry.py:69-73` states the split explicitly.

---

### `services/notifier/persistence.py` (persistence, CRUD)

**Analog:** `services/state_machine/persistence.py` (173 lines) — copy the *statement shape*, **invert the best-effort rule**.

**Idempotent insert idiom** (lines 97-105), which becomes D-76a's `ON CONFLICT (watch_id, event_id, channel) DO NOTHING … RETURNING`:

```python
        statement = (
            pg_insert(AvailabilityEventRow)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["event_id", "time"])
        )
        session_factory = get_async_session()
        async with session_factory() as session:
            await session.execute(statement)
            await session.commit()
```

**rowcount discipline for the UPDATE path** (`/webhooks/twilio/status`, `/go` click-tracking) — lines 149-164:

```python
        async with session_factory() as session:
            # CursorResult, not Result: `rowcount` lives on the DBAPI-backed subclass, and
            # `Session.execute` is typed as returning the base class.
            result = cast(CursorResult[Any], await session.execute(statement))
            rowcount = result.rowcount
            await session.commit()
        if rowcount == 0:
            log.warning("availability_event_close_matched_no_row", ...)
```

**Error rendering** (lines 106-116):

```python
    except Exception as exc:  # noqa: BLE001 — best effort: never block the emit or the commit
        log.error("availability_event_insert_failed", event_id=str(event.event_id),
                  restaurant_id=event.restaurant_id, error=safe_error(exc))
```

**DO NOT copy the swallow.** The state machine swallows insert failures by design (D-48: *"a delivered notification beats a durable analytics row"*). That reasoning inverts here — the `sent` row is the SC2 duplicate proof and the PERF-01 measurement source, so a failed `notification_log` insert must raise into the transient arm and rewind the offset (research Pitfall 3, Anti-Patterns).

**Time helpers to reuse rather than reinvent** (lines 30-63):

```python
_SERVICE_TZ = ZoneInfo("America/New_York")          # daily-cap key date (D-74) uses THIS, not date.today()

def day_of_week(service_date: date) -> int:
    """0=Sun .. 6=Sat — the Phase 6 heatmap y-axis and migration 0008's column comment (B-5)."""
    return service_date.isoweekday() % 7

def _parse_time_slot(value: str) -> dt_time | None:
    """Tolerant `HH:MM` / `HH:MM:SS` parse; an unreadable slot stores NULL instead of failing."""
    try:
        return dt_time.fromisoformat(value)
    except ValueError:
        return None
```

`matching.py` reuses both: the `days_of_week` mapping must land on the 0=Sun..6=Sat numbering, and the time-window comparison must **fail closed** when `_parse_time_slot` returns `None`.

**ORM columns for the fan-out SELECT** (`shared/db.py:41-108`, read this session): `Restaurant.platform_id` is `Text` — bind `str(event.restaurant_id)` (`AvailabilityEvent.restaurant_id` is `int` and is the *platform* id, `shared/events.py:104-106`). `User.created_at/updated_at` and `WatchlistEntry.created_at/updated_at` are `nullable=False` **with no server_default**, so ORM-seeded test rows must set them explicitly.

---

### `services/notifier/providers/{email,sms,push}.py` (provider client, request-response)

**Analog:** `services/poller/sources/opentable/adapter.py`.

Imports + transient tuple + tenacity decorator (lines 3-58):

```python
"""Uses the shared ``httpx.AsyncClient`` singleton — NEVER creates per-poll
clients (Pitfall 9). Implements tenacity retry with ``Retry-After`` header ..."""
import httpx
from tenacity import retry, retry_if_exception_type, ...

_TRANSIENT_EXCEPTIONS = (
    httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.ConnectTimeout,
    httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout, httpx.RemoteProtocolError,
)

class OpenTableAdapter:
    def __init__(self, client: httpx.AsyncClient) -> None:  # client is INJECTED, never built
        ...

    @retry(..., retry=retry_if_exception_type(_TRANSIENT_EXCEPTIONS + (httpx.HTTPStatusError,)))
```

Client acquisition — `shared/http_client.py:9-10, 27-37`:

```python
"""Do NOT construct :class:`httpx.AsyncClient` anywhere else in the codebase.
Pitfall 9 in PITFALLS.md documents the FD leak caused by per-poll clients."""

TIMEOUT: httpx.Timeout = httpx.Timeout(10.0, connect=5.0)   # D-84 discretion default already matches

def get_async_client() -> httpx.AsyncClient: ...
```

**One deviation the planner must call out:** the adapter's 429 branch (lines 74-88) does `await asyncio.sleep(retry_after)` then re-raises. D-79 scopes the no-sleep gate to explicit `asyncio.sleep(` in `services/notifier`, so the notifier must express `Retry-After` through **tenacity's `wait`** instead of copying those lines. Copy the *status handling*, not the sleep.

Attempt counts: email 3 (exp 1-8 s), SMS 2, push 2 (D-79). Base URLs from `config.py` functions (`RESEND_API_BASE`, `TWILIO_API_BASE`) so `respx` can bind them.

---

### `shared/events.py` — `NotificationQueued` / `NotificationSent` (model, pub-sub)

**Analog:** `shared/events.py :: AvailabilityEvent` (lines 99-133). Copy the config, the wire-order warning, and `to_bytes`:

```python
class AvailabilityEvent(BaseModel):
    """
    Field declaration order below IS the JSON wire order that byte-identical replay depends
    on — do not reorder. date and time_slot are plain strings, never datetime, so no timezone
    renderer can perturb the bytes.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID
    event_type: Literal["slot_opened"]
    ...

    def to_bytes(self) -> bytes:
        return self.model_dump_json().encode("utf-8")
```

Deterministic id recipe to mirror for `job_id` (uuid5 over `notif:{watch_id}:{event_id}:{channel}`, D-75) — `make_event_id` (lines 23-64) is the template, **and its docstring is the warning**: that recipe is not injective because adjacent unescaped components can collapse. `job_id`'s components are an int, a UUID and a `Literal`, so it is safe — say so in the docstring rather than leaving it implicit.

---

### `shared/redis_keys.py` additions (registry)

**Analog:** the module itself.

Claim primitive (lines 35-42) — the only permitted claim route:

```python
async def set_nx_ex(r: Redis, key: str, value: str, ttl_seconds: int) -> bool:
    """
    Atomic SETNX+EX in a single Redis call (Pitfall 7).
    NEVER use two-command SETNX + EXPIRE.
    """
    result = await r.set(key, value, nx=True, ex=ttl_seconds)
    return result is True
```

Key-builder with injective escaping (lines 64-94) — `notif_idempotency_key` copies this exactly:

```python
def event_idempotency_key(restaurant_id: int, date: str, party_size: int, slot_key: str, token: str) -> str:
    """Every component is percent-escaped, so the key is INJECTIVE (WR-04)."""
    parts = (str(restaurant_id), date, str(party_size), slot_key, token)
    return "event:" + ":".join(quote(part, safe="") for part in parts)
```

TTL constants live beside the keys (line 50-51 style): add `NOTIF_IDEMPOTENCY_TTL_SECONDS: int = 86_400  # 24 h — NOTIF-02`.

The daily-cap Lua registers through `shared/scheduler/lua.py :: LuaScheduler`'s `register_script` pattern (`main.py:118-119` shows `scheduler.start()` being awaited at startup) — the D-74a `if n == 1 then EXPIRE` script must be `EXPIRE`-conditional; the MULTI form is reproduced as wrong in RESEARCH.

Also note the deletion notice at lines 110-116: bare `hset_slot`/`expire_key` were **deleted**, not deprecated, because `test_no_setnx_expire_pairs.py` only greps `.setnx(`. Do not reintroduce a mutate-then-EXPIRE pair for the rate-limit key.

---

### `migrations/versions/0010_notification_pipeline.py` (migration)

**Analog:** `migrations/versions/0008_add_event_id_to_availability_events.py` (94 lines).

Header + revision block (lines 1-22) — note `down_revision = "0009"` per D-89 (0009 does not exist yet):

```python
"""0008: Add event_id + unique (event_id, time) to availability_events (D-48a, corrected).

Destroys nothing: the upgrade refuses to run against a non-empty table rather than
deleting the rows it cannot backfill (see the guard in upgrade()).
"""
revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None
```

Non-destructive guard (lines 26-48) — the shape for any 0010 backfill (e.g. `users.sms_opt_out` is `NOT NULL DEFAULT false`, so a server_default carries it; `phone_hash` is nullable and needs no guard, but a unique index over existing rows does):

```python
    existing = op.get_bind().execute(
        sa.text("SELECT count(*) FROM availability_events")
    ).scalar_one()
    if existing:
        raise RuntimeError(f"availability_events holds {existing} pre-0008 row(s). ...")
```

Add-column-then-tighten idiom (lines 50-54) and unique-index creation (lines 61-66):

```python
    op.add_column("availability_events", sa.Column("event_id", PG_UUID(as_uuid=True), nullable=True))
    op.alter_column("availability_events", "event_id", nullable=False)

    op.create_index("uq_availability_events_event_id_time", "availability_events",
                    ["event_id", "time"], unique=True)
```

Documenting semantics **in the database** (lines 68-83) — do the same for `notification_log.status`'s vocabulary (D-85). Note the doubled `%%`:

```python
    op.execute(
        "COMMENT ON COLUMN availability_events.day_of_week IS "
        "'0=Sun .. 6=Sat (service_date.isoweekday() %% 7) ...'"
    )
```

Also copy the standing rule at line 26: *"NEVER use `alembic revision --autogenerate` on a hypertable (Pitfall 12, D-33)"*. `notification_log` is a plain table, so the D-76a `UNIQUE (watch_id, event_id, channel)` needs no partitioning column — but consider the **partial** index (`WHERE status IN ('sent','delivered','clicked')`) if suppressed rows must coexist (research recommends it explicitly).

---

### `scripts/check_notification_latency.py` / `check_false_positive_rate.py` (script, batch)

**Analog:** `scripts/check_poll_success.py` (132 lines) — copy the three-way exit-code contract verbatim so "not enough data" can never be confused with "passed".

```python
"""
Exit codes:
  0 — All hourly buckets have success_rate >= 0.99 (PERF-02 passed)
  1 — One or more buckets are below 0.99 (PERF-02 failed)
  2 — Not enough data (fewer than 24 hourly buckets — run has not completed 24h yet)
"""
DATABASE_URL_ASYNC = os.getenv("DATABASE_URL_ASYNC", "postgresql+asyncpg://mise:mise@localhost:5432/mise")

async def check() -> int:
    # Strip asyncpg prefix if set; asyncpg uses postgresql:// not postgresql+asyncpg://
    url = DATABASE_URL_ASYNC.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(""" ... time_bucket('1 hour', time) ... """)
    finally:
        await conn.close()
    if not rows:
        print("ERROR: No data ...", file=sys.stderr)
        return 2
    ...

def main() -> None:
    exit_code = asyncio.run(check())
    sys.exit(exit_code)
```

Table-printing convention (lines 86-96) and the failure-summary block (lines 110-122) carry across directly. D-86 thresholds: overall p95 ≤ 60 s, SMS p95 ≤ 10 s, push p95 ≤ 5 s; exit 2 below 100 samples. `check_false_positive_rate.py` exits 0 iff `slot_still_available=false / clicked < 2 %`, counting only TRUE/FALSE rows (D-86a).

---

### `scripts/create_topics.py` (+`notifications.dlq`)

**Analog:** the `availability.dlq` entry (lines 47-56) — copy the entry *and* its rationale comment style:

```python
    # Dead-letter topic (CR-01): one record per message that exhausted its retry cap in the
    # state machine, carrying the ORIGINAL bytes plus diagnostic headers. 7 days, not 24 hours
    # like availability.raw, precisely because its job is to outlive the raw record it copies —
    # a message that poisoned the pipeline on a Friday night must still be there on Monday.
    NewTopic("availability.dlq", num_partitions=1, replication_factor=1,
             topic_configs={"retention.ms": str(604_800_000)}),      # 7d
```

`notifications.dlq` uses `retention.ms = 2_592_000_000` (30 d, D-75). Update the module docstring's topic table (lines 7-19) in the same commit — it is a Named-Symbol list.

---

### Chaos test `tests/integration/test_notifier_chaos.py`

**Analog:** `tests/integration/test_state_machine_chaos.py` (read to line 140).

Docstring stating the non-vacuity guard (lines 18-19) — the sentence to reuse:

```python
"""The ``returncode == -SIGKILL`` assertion is load-bearing: without it, a run where the hook
never fired would pass vacuously."""
```

Subprocess launch + env plumbing (lines 71-78, 107-119, 138):

```python
def _launch(env: dict[str, str]) -> subprocess.Popen[bytes]:
    return subprocess.Popen(["uv", "run", "python", "-m", "services.state_machine"],
                            cwd=REPO_ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # monkeypatch, not a bare os.environ assignment: an unrestored KAFKA_BOOTSTRAP_SERVERS /
    # REDIS_URL / DATABASE_URL_* silently binds every later test in the session to a container
    # that has already been torn down — an order-dependent failure (WR-15).
    monkeypatch.setenv("KAFKA_BOOTSTRAP_SERVERS", bootstrap)
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("DATABASE_URL_ASYNC", db_urls["async"])
    monkeypatch.setenv("DATABASE_URL_SYNC", db_urls["sync"])
    reset_shared_db_singletons()
    base_env = {**os.environ}
    apply_migrations(base_env)
    create_topics(base_env)

    # ENV must be named explicitly: the crash-hook interlock fails closed (WR-13, T-02-04).
    crashing = _launch({**base_env, "MISE_CRASH_AFTER": "state_write", "ENV": "test"})
```

Drain helper with a unique group id (lines 81-97) transfers directly to draining `notifications.sent`.

**The one gap:** the provider must be mocked *inside the subprocess*. `respx` patches in-process only, so the analog does not cover it. Options for the planner: point `RESEND_API_BASE`/`TWILIO_API_BASE` at an in-test stub server (the Phase 3 D-71 `tests/fakes/resy_stub.py` FastAPI-on-uvicorn-random-port recipe is the intended shape, and it does not exist yet either), and use its hit log as the SID oracle. `respx`'s `route.call_count` only works for the in-process integration test.

Fixtures come from `tests/integration/conftest.py:20-70`: `reset_shared_db_singletons()`, `apply_migrations(env)`, `create_topics(env)`, `redis_url`, `db_urls`.

---

### Grep gates (`test_no_sync_sdk_imports.py`, `test_no_new_runtime_deps.py`, extended no-sleep/no-SETNX)

**Analog:** `tests/unit/test_no_inline_sleep.py` (60 lines) and `tests/unit/test_no_setnx_expire_pairs.py` (50 lines).

Non-vacuity guard + comment stripping — both are mandatory and both are load-bearing:

```python
def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Strip full-line comments so an explanatory comment cannot satisfy or break the gate."""
    return [(lineno, line) for lineno, line in enumerate(path.read_text().splitlines(), start=1)
            if not _FULL_LINE_COMMENT.match(line)]


def test_scanned_file_set_is_not_empty():
    """A glob that silently matched nothing would make both assertions below vacuous."""
    assert len(SCANNED_FILES) >= 8
    names = {path.name for path in SCANNED_FILES}
    assert {"consumer.py", "main.py", "engine.py", "store.py"} <= names
```

and the directory-scanning form (`test_no_setnx_expire_pairs.py:13-46`), which already covers `services/`, `shared/`, `scripts/` — so the new notifier code is inside the SETNX gate the moment it lands:

```python
SCANNED_DIRS = ("services", "shared", "scripts")
DEPRECATED_CLAIM = re.compile(r"\.\s*setnx\s*\(", re.IGNORECASE)

def test_scanned_dirs_are_non_empty():
    """Guard the guard: a path typo must not make this test vacuously pass."""
    assert len(_python_files()) > 10
```

`test_no_inline_sleep.py:19-24` hardcodes `SERVICE_DIR = .../services/state_machine` — Phase 4 must extend it (or add a sibling) to `services/notifier` incl. `providers/`, with its own non-vacuity assertion naming `workers.py`, `consumer.py`, `main.py`.

---

### `Makefile` / `.env.example`

**Analog:** `Makefile:3, 20-27, 56-57` — add targets to `.PHONY`, and every target carries a `##` help string (the `help` target greps for it):

```make
.PHONY: up down migrate seed poll state-machine replay test test-integration lint fmt smoke verify-seed verify-perf02 help topics

state-machine: ## Run the state machine consumer on host
	uv run python -m services.state_machine

verify-perf02: ## Assert all 24-hour buckets in poll_log have >=99% success rate
	uv run python scripts/check_poll_success.py
```

→ `notifier: ## Run the notification pipeline on host` → `uv run python -m services.notifier`; `api: ## Run the FastAPI app on host` → `uv run uvicorn services.api.app:app`; `verify-perf01`, `verify-perf03`.
`make lint` runs `mypy shared/ services/ scripts/` — everything new is under strict mypy, which is why RESEARCH's two typing notes (`json.loads` → `object` + `isinstance`, `http_ece.encrypt` → annotated local) matter.

`.env.example:39-67` already has the `TWILIO_*`, `VAPID_*` and `HMAC_MGMT_SECRET_V1` blocks with placeholder-value style (`your_..._here`). Phase 4 appends `RESEND_API_KEY`, `RESEND_API_BASE`, `RESEND_WEBHOOK_SECRET`, `NOTIFY_FROM_EMAIL`, `TWILIO_API_BASE`, `TWILIO_WEBHOOK_BASE_URL`, `NOTIFY_DRY_RUN`, `NOTIFY_DAILY_CAP_PER_USER`, `PUBLIC_BASE_URL`, `PHONE_HASH_SECRET`, `PHONE_ENCRYPTION_KEY`, `HMAC_TOKEN_VERSION`, `HMAC_GRACE_UNTIL` in the same style.

---

### Runbooks

**Analogs on disk:** `docs/runbooks/twilio-10dlc-setup.md` (→ `ios-pwa-push.md`), `docs/runbooks/perf02-24h-log.md` (→ `perf01-latency.md`). Both carry the pending-human banner convention Phase 3 D-70 names `STATUS: pending-human-run`; D-87 uses `STATUS: pending-human`. Pick one spelling and use it in both new files.

---

## Shared Patterns

### A. Lazy env config (never a module constant)
**Source:** `services/state_machine/config.py:7-14, 44-64`
**Apply to:** `services/notifier/config.py`, `services/api/` config, every provider base URL.
The poller's import-time freeze is the documented bug this avoids.

### B. Payload-safe error logging
**Source:** `services/state_machine/consumer.py:83-105` (`_failure_shape`) and `shared/telemetry.py:48-84` (`safe_error`)
**Apply to:** every `except` in `services/notifier/**` and `services/api/**`.
`shared/telemetry.py:69-73` states the split: `_failure_shape` for producer-supplied data, `safe_error` for our own infrastructure. Never `str(exc)`. Phase 4 adds phone numbers, `authorization` and `api_key` to `_redact_secrets` (telemetry.py:87-102), on top of Phase 3's D-61a extension.

### C. Single-atomic-command Redis claim
**Source:** `shared/redis_keys.py:35-42` + `tests/unit/test_no_setnx_expire_pairs.py`
**Apply to:** the Layer-2 notification claim and the daily-cap key. The gate already scans `services/`, `shared/`, `scripts/`.

### D. `send_and_wait`, never a bare `send`
**Source:** `shared/kafka.py:33` (`linger_ms=20`) + `services/state_machine/consumer.py:556-563`
**Apply to:** `notifications.queued`, `notifications.sent`, `notifications.dlq`.

### E. Persistence best-effort — **inverted for this phase**
**Source:** `services/state_machine/persistence.py:1-9, 106-116` (swallows by design, D-48)
**Apply to:** nothing verbatim. `services/notifier/persistence.py` copies the *statement* shapes and the `safe_error` rendering but must let a failed `sent`-row insert propagate into the transient arm (research Pitfall 3 / Anti-Patterns).

### F. Crash hook behind a fail-closed ENV allowlist
**Source:** `services/state_machine/config.py:67-88` (moving to `shared/crash_hook.py`, D-88) + `main.py:87-93` interlock + `consumer.py:108-125` `_maybe_crash`
**Apply to:** `services/notifier/{main,workers}.py` and the chaos test.

### G. Shared `httpx.AsyncClient`
**Source:** `shared/http_client.py:9-10, 20-37`
**Apply to:** all three providers. Never construct a client in a provider; inject it (the OpenTable adapter's `__init__(self, client)` is the shape).

### H. Non-vacuous grep gates
**Source:** `tests/unit/test_no_inline_sleep.py:26-46`, `tests/unit/test_no_setnx_expire_pairs.py:20-38`
**Apply to:** the four new/extended gates. Every gate needs a `test_scanned_*_is_not_empty` companion and comment-stripping.

### I. Integration container plumbing
**Source:** `tests/integration/conftest.py:20-70`
**Apply to:** every Phase 4 integration test. `reset_shared_db_singletons()` **after** monkeypatching `DATABASE_URL_ASYNC`, or the cached engine still points at localhost.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `services/api/routers/links.py` | router | request-response | No HTTP **server** exists in the repo today (FastAPI is pinned but only used by Phase 3's not-yet-written stub). Use RESEARCH's `[VERIFIED: transcript]` `/go` 302 sketch and BC-3's `parse_qsl` body read. |
| `services/api/routers/webhooks.py` | router | request-response | Same. Signature verifiers are pure functions in `shared/` precisely so they can be tested without a server. |
| `services/notifier/templates.py` | utility | transform | No rendering of any kind exists. Use RESEARCH's GSM-7 septet table (BC-2) as the executable contract. |
| `shared/crypto.py` | utility | transform | No AES/AEAD usage exists. `cryptography` 46.0.7 `AESGCM` per D-85; nonce-reuse is the named anti-pattern. |

Adjacent but weaker matches worth naming for the planner: `shared/tokens.py`, `shared/twilio_signature.py` and `shared/svix_signature.py` have **no** cryptographic analog either, but they should copy `shared/redis_keys.py`'s module discipline (docstring `Named symbols:` line, pure functions, no I/O, injectivity reasoning in the docstring) and `hmac.compare_digest` per RESEARCH.

---

## Metadata

**Analog search scope:** `services/`, `shared/`, `scripts/`, `migrations/versions/`, `tests/unit/`, `tests/integration/`, `docs/runbooks/`, `Makefile`, `.env.example`
**Files scanned:** 89 Python files listed; 17 read in full or in targeted ranges
**Pattern extraction date:** 2026-09-05
