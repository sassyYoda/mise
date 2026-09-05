# Phase 3: Resy & Playwright Fleet - Pattern Map

**Mapped:** 2026-09-05
**Files analyzed:** 47 (new + modified)
**Analogs found:** 39 / 47 exact-or-role match; 8 with no in-repo analog (use 03-RESEARCH.md §Code Examples)

> All excerpts below were read fresh from disk on 2026-09-05, **after** the concurrent code-review
> fixer's Phase 2 commits landed (`event_idempotency_key` now carries `slot_key`; `consumer._flush()`
> is per-emit; migration 0008 carries the non-empty-table guard; `poll_loop` now calls
> `scheduler.drop(job)` on a malformed descriptor). Line numbers match the current tree.

---

## File Classification

### Poller — Resy source package (all NEW)

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/poller/sources/resy/adapter.py` | adapter/service | request-response | `services/poller/sources/opentable/adapter.py` | exact (same ABC) |
| `services/poller/sources/resy/pool.py` | resource-pool provider | lifecycle / acquire-release | `shared/http_client.py` (singleton lifecycle) + `shared/scheduler/lua.py` (start/stop class) | partial |
| `services/poller/sources/resy/fingerprints.py` | config/data-table | pure data | `services/poller/config.py :: USER_AGENTS` + `tests/unit/test_ua_rotation.py` | role-match |
| `services/poller/sources/resy/stealth.py` | utility | pure transform | *(none)* | **no analog** |
| `services/poller/sources/resy/canary.py` | utility (pure verdict) + Redis window | transform / rolling-window | `services/state_machine/parsers/opentable.py :: effective_coverage` (pure fn, no clock) + `shared/redis_keys.py` pipeline helpers | role-match |
| `services/poller/sources/resy/accounts.py` | model (validation) | transform | `shared/events.py` (pydantic `ConfigDict(extra="forbid")`) | role-match |
| `services/poller/sources/resy/fixtures.py` | test fixture data | pure data | `services/poller/sources/opentable/fixtures.py` | exact |
| `services/poller/sources/resy/README.md` | doc | — | `services/poller/sources/opentable/README.md` | exact |
| `services/poller/sources/registry.py` | config/dispatch | request-response | *(new — replaces the inline `if source ==` in `scheduler.py:95`)* | partial |
| `services/poller/sources/resy/__init__.py` | package marker | — | `services/poller/sources/opentable/__init__.py` (0 bytes) | exact |

### Poller — modified

| Modified File | Role | Data Flow | Analog / precedent | Match Quality |
|---------------|------|-----------|--------------------|---------------|
| `services/poller/scheduler.py` | controller (poll loop) | event-driven / claim-dispatch-release | itself (extend `_next_poll_score` + release path at :147-158) | in-place |
| `services/poller/main.py` | entrypoint/lifespan | lifecycle | itself (:65-105) + `services/state_machine/main.py` for lazy-config wiring | in-place |
| `services/poller/config.py` | config | — | `services/state_machine/config.py` (**function-based env reads** — the correct pattern; poller's module constants are the anti-pattern) | role-match |

### Shared

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `shared/redis_keys.py` (modify) | config/key-registry + Lua | CRUD / pure math | itself — `set_nx_ex` :35-42, `CLAIM_POLL_LUA` :166-179, `hset_slot_with_ttl` :122-129 | in-place |
| `shared/events.py` (modify) | model | pub-sub schema | itself :57-71 | in-place |
| `shared/telemetry.py` (modify) | middleware (log processor) | transform | itself :17-32 | in-place |
| `shared/metrics.py` (NEW) | config/registry | instrumentation | *(none — nearest sibling idiom is `shared/redis_keys.py`: module-level, defined once, imported everywhere)* | partial |

### State machine

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `services/state_machine/parsers/resy.py` (NEW) | parser/transform | transform | `services/state_machine/parsers/opentable.py` | exact |
| `services/state_machine/parsers/__init__.py` (modify) | registry | dispatch | itself :15-17 | in-place (one dict entry) |
| `services/state_machine/consumer.py` (modify) | consumer | event-driven | itself :186-199 (`_handle_completed`) | in-place (invert one check) |
| `services/state_machine/README.md` (modify) | doc | — | itself | in-place |

### Migrations & scripts

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `migrations/versions/0009_restaurant_slug_source_unique.py` (NEW) | migration | schema | `migrations/versions/0008_add_event_id_to_availability_events.py` (guard + index + COMMENT idiom); target DDL in `0003_create_restaurants.py:18,38` | exact |
| `scripts/seed_restaurants.py` (modify) | script | batch/CRUD | itself :53-110 | in-place |
| `scripts/seed/restaurants.yml` (modify) | data | — | itself (`opentable_rid: 900000001  # TODO(01-05 spike)` at :54) | in-place |
| `scripts/resolve_resy_venue_ids.py` (NEW) | script (human-gated) | batch/file-I/O | `scripts/verify_seed.py` + `scripts/seed_restaurants.py` (YAML read/write + asyncio.run main) | role-match |
| `scripts/soak_playwright.py` (NEW) | script | sampling/batch | `scripts/check_poll_success.py` (exit-code 0/1/2 + `main()`/`asyncio.run` shape) | role-match |
| `scripts/replay_raw.py` (modify) | script | batch/replay | itself :108-110 | in-place |

### Tests (30 new files per RESEARCH §Validation Architecture)

| New/Modified File(s) | Role | Data Flow | Closest Analog | Match Quality |
|----------------------|------|-----------|----------------|---------------|
| `tests/fakes/resy_stub.py` (NEW) | test fake (FastAPI + `__ctl`) | request-response | *(none in repo)* — use RESEARCH §Code Examples "In-process uvicorn stub" | **no analog** |
| `tests/unit/test_parsers_resy.py` | unit | transform | `tests/unit/test_parsers_opentable.py` | exact |
| `tests/unit/test_tier_cadence.py`, `test_effective_interval.py`, `test_jitter_bounds.py`, `test_backoff_math.py` | unit (pure math) | transform | `tests/unit/test_service_time_math.py`, `tests/unit/test_redis_keys_phase2.py` | role-match |
| `tests/unit/test_response_signature.py`, `test_canary_verdict.py`, `test_soak_verdict.py` | unit (pure verdict) | transform | `tests/unit/test_engine_transitions.py` (matrix-style table tests) | role-match |
| `tests/unit/test_fingerprints.py` | unit (data invariants) | pure data | `tests/unit/test_ua_rotation.py` | exact |
| `tests/unit/test_no_inline_sleep_resy.py` | unit (grep gate) | file-I/O | `tests/unit/test_no_inline_sleep.py` | exact |
| `tests/unit/test_stealth_script_names.py`, `test_browser_guard.py`, `test_metrics_registry.py`, `test_soak_sampling.py`, `test_resy_accounts.py`, `test_resy_envelope.py`, `test_banned_marks_unknown.py` | unit | transform | `tests/unit/test_confirm_delay_is_not_configurable.py` (single-property guard style) | role-match |
| `tests/unit/test_telemetry_redaction.py` (**extend**) | unit | transform | itself | in-place |
| `tests/unit/test_events_schema.py`, `test_replay_determinism.py` (**extend**) | unit | transform | themselves | in-place |
| `tests/unit/factories.py` (**extend** with `make_resy_envelope`) | test factory | pure data | itself :21-39 | in-place |
| `tests/integration/test_context_pool.py`, `test_fingerprint_rotation.py`, `test_stealth_applied.py`, `test_anonymous_mode.py`, `test_resy_request_headers.py`, `test_429_backoff_and_recycle.py`, `test_ban_reaction.py`, `test_no_zombie_browsers.py`, `test_soak_ci.py` | integration (browser) | request-response | `tests/integration/test_poller_smoke.py` (structure) + RESEARCH §Code Examples browser fixture | partial |
| `tests/integration/test_rate_budget_lua.py`, `test_per_context_floor.py`, `test_canary_window.py`, `test_fleet_pause.py`, `test_release_precedence.py` | integration (Redis) | CRUD | `tests/integration/test_expedite_lua.py`, `test_scheduler_claim_release.py` | exact |
| `tests/integration/test_resy_e2e_state_machine.py` | integration (E2E, SC5) | event-driven | `tests/integration/test_state_machine_e2e.py` | exact |
| `tests/conftest.py` (**extend**: `_chromium_available()`, `browser` fixture) | test config | — | itself :8-17 (`_docker_available()` guard idiom) | exact |

### Ops / docs

| File | Role | Analog | Match |
|------|------|--------|-------|
| `Makefile` (`browsers`, `soak`) | config | itself :11-12, :50-51 | in-place |
| `.env.example` (Resy block) | config | itself :35-49 | in-place |
| `docs/runbooks/perf05-soak.md` (NEW) | doc | `docs/runbooks/perf02-24h-log.md` | exact |
| `docs/runbooks/resy-cookie-capture.md` (**NEW — does not exist yet**; D-63a assumes it does) | doc | `docs/runbooks/perf02-24h-log.md` + `services/poller/sources/opentable/README.md` | role-match |

---

## Pattern Assignments

### `services/poller/sources/resy/adapter.py` (adapter, request-response)

**Analog:** `services/poller/sources/opentable/adapter.py`

**Module docstring + imports pattern** (analog lines 1-31) — decision-ID citations in the
docstring, `from __future__ import annotations`, `log = get_logger(__name__)` at module scope:

```python
"""OpenTable availability polling adapter (D-05, D-19, POLL-03).

Uses the shared ``httpx.AsyncClient`` singleton — NEVER creates per-poll
clients (Pitfall 9). Implements tenacity retry with ``Retry-After`` header
support (T-03 mitigation).
"""
from __future__ import annotations
...
from services.poller.sources.base import AvailabilitySource
from shared.telemetry import get_logger

log = get_logger(__name__)
```

**Constructor pattern — inject the shared resource, never create it** (analog lines 46-53).
This is D-05; the Resy analogue is "never construct a `Browser` outside `ContextPool`":

```python
class OpenTableAdapter(AvailabilitySource):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client  # shared, NEVER per-poll (D-05, Pitfall 9)
```

→ `ResyAdapter(AvailabilitySource)` takes `pool: ContextPool` the same way.

**ABC contract to implement** — `services/poller/sources/base.py` lines 18-24 (the signature is
fixed; the envelope goes in the return value, not the signature):

```python
    @abstractmethod
    async def poll(
        self,
        rid: int,
        dates: list[date],
        party_sizes: list[int],
    ) -> dict[str, Any]:
```

**Single-transport-method isolation (D-64a)** — the analog already separates `_fetch` from
`poll` (lines 62-92 vs 94-105). Copy that split exactly: `ResyAdapter._fetch(ctx, url, headers)
-> APIResponse` is the ONE place the transport lives, so a future page-hosted `fetch()` is a
one-method change.

**DO NOT copy** the analog's 429 handling (lines 74-90) — it calls `await asyncio.sleep(retry_after)`,
which is banned for Resy by D-59/D-65 (the 429 must become a ZSET backoff score in the release
path). Also **do not copy** the tenacity `@retry` decorator: `APIRequestContext` *returns* 429/403
rather than raising, so there is nothing for `retry_if_exception_type` to catch.

**Envelope shape (D-64, new — no analog):**
```python
{"requests": [{"date": ..., "party_size": ..., "status": ..., "body": {...}}, ...]}
```

---

### `services/poller/sources/resy/pool.py` (resource pool, lifecycle)

**Analogs:** `shared/scheduler/lua.py` (explicit `start()` lifecycle class),
`shared/http_client.py` (single-shared-resource-per-process idiom).

**Lifecycle class pattern** (`shared/scheduler/lua.py` lines 29-47) — constructor stores the
handle, `async def start()` does the async setup, `assert self._x is not None, "Call start() first"`
guards every method:

```python
class LuaScheduler:
    def __init__(self, client: redis.Redis) -> None:
        self.r = client
        self._claim_sha: str | None = None
        ...

    async def start(self) -> None:
        """Load Lua scripts into Redis and cache SHAs."""
        self._claim_sha = await self.r.script_load(CLAIM_POLL_LUA)
```

**Shielded teardown (NO in-repo analog — from RESEARCH §Code Examples / Pitfall 1).** The nearest
in-repo teardown idiom is `services/poller/main.py` lines 95-105 (nested `try/finally`), but it
uses a bare `await`. For the browser this MUST be:

```python
    finally:
        await asyncio.shield(browser.close())   # bare await re-raises CancelledError immediately
        await pw.stop()
```

**Redis `SET NX EX` for the 45 s per-context floor** — use the existing helper verbatim,
`shared/redis_keys.py` lines 35-42 (note it returns `result is True`, because redis-py returns
`None`, not `False`, when the key exists):

```python
async def set_nx_ex(r: Redis, key: str, value: str, ttl_seconds: int) -> bool:
    """
    Atomic SETNX+EX in a single Redis call (Pitfall 7).
    NEVER use two-command SETNX + EXPIRE.
    """
    result = await r.set(key, value, nx=True, ex=ttl_seconds)
    return result is True
```

---

### `services/poller/scheduler.py` (controller, event-driven) — MODIFY

**Analog:** itself. Four surgical edits.

**1. Parameterise the interval** — current hard-coded form (lines 30-36):

```python
_INTERVAL_MS: int = POLL_INTERVAL_SECONDS * 1000  # 90_000 ms
_JITTER_MS: int = int(_INTERVAL_MS * POLL_JITTER_FRACTION)  # +/- 13_500 ms


def _next_poll_score(now_ms: int) -> int:
    """D-17: next score = ``now_ms + 90_000 + uniform(-13_500, 13_500)``."""
    return now_ms + _INTERVAL_MS + int(random.uniform(-_JITTER_MS, _JITTER_MS))
```
→ becomes `_next_poll_score(now_ms: int, interval_seconds: int) -> int`, keeping
`POLL_JITTER_FRACTION` as the ±15 % source of truth.

**2. Replace the inline source branch** (lines 94-106) with the `{source: adapter}` registry:

```python
        try:
            if source == "opentable":
                raw_response = await opentable.poll(...)
                status = "success"
                http_status = 200
            else:
                log.warning("unknown_source", source=source)
                status = "error"
                error_str = f"Unknown source: {source}"
```

**3. Copy the malformed-job release pattern verbatim** (lines 62-78) for the new pre-dispatch
gates — this is the fixer's `drop()` fix and it is the reference for "never leak a job into
inflight":

```python
        parts = job.split(":", 1)
        if len(parts) != 2:
            # A `continue` alone did NOT drop it: the job stayed in sched:polls:inflight with a
            # 60 s visibility score, so the reaper re-enqueued it into sched:polls, ... forever.
            await scheduler.drop(job)
            log.error("invalid_job_descriptor", job=job)
            continue

        source, rid_str = parts
        try:
            restaurant_id = int(rid_str)
        except ValueError:
            await scheduler.drop(job)
            log.error("invalid_restaurant_id", job=job)
            continue
```
Note for the new gates: a *rate-refused* or *paused* job is **released** (`scheduler.release(job,
now+5000)` / `now+60_000`), NOT dropped — `drop` is only for descriptors that can never succeed.

**4. Extend the release path** (lines 147-158) with backoff precedence (D-59: backoff beats
expedite, but the flag is still consumed):

```python
        release_now_ms = int(time.time() * 1000)
        expedited = await scheduler.consume_expedite(job)
        next_score = (
            release_now_ms + CONFIRM_DELAY_MS if expedited else _next_poll_score(release_now_ms)
        )
        if expedited:
            log.info("poll_expedited", restaurant_id=restaurant_id, next_score=next_score)
        await scheduler.release(job, next_score)
```

**Error-taxonomy pattern to mirror** (lines 107-133): a `finally:` block computes `latency_ms`
regardless of outcome, each `except` sets `status`/`error_str` and logs a distinct event name.
For Resy substitute `playwright.async_api.Error` / `TimeoutError` (a **subclass** of `Error` —
catch it first) for the httpx types.

---

### `shared/redis_keys.py` (config/key-registry) — MODIFY

**Analog:** itself. Every new key gets a `def *_key(...) -> str` with a decision-ID docstring.

**Key-function pattern** (lines 54-61, 160-162):

```python
def avail_state_key(restaurant_id: int, date: str, party_size: int) -> str:
    """Return the HASH key holding known slot records for one (rid, date, party) (D-40)."""
    return f"avail:{restaurant_id}:{date}:{party_size}"


def sched_expedite_key(job: str) -> str:
    """Return the expedite-flag key 'sched:expedite:{job}' for an in-flight poll (D-43)."""
    return f"sched:expedite:{job}"
```
→ add `rate_minute_key`, `rate_ctx_venue_key`, `canary_key`, `backoff_key`, `RESY_PAUSED`,
`WATCH_COUNT_HASH`, `TIER_OVERRIDE_HASH` + `tier_interval_seconds()` / `effective_interval_seconds()`
(pure, no clock, no IO — the D-49 precedent).

**Lua-script pattern** (lines 166-179) — KEYS/ARGV documented as leading comments, and the
`EXPEDITE_POLL_LUA` block (lines 203-223) shows the house style of explaining *why* each flag is
mandatory. Copy that commentary density for the budget script:

```python
CLAIM_POLL_LUA = """
-- KEYS[1] = sched:polls
-- KEYS[2] = sched:polls:inflight
-- ARGV[1] = now_ms
-- ARGV[2] = visibility_timeout_ms
local ready = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 1)
...
"""
```

**mypy-strict Redis cast pattern** (lines 80-110) — every `cast(Awaitable[T], ...)` lives in this
file exactly once. New commands (`LPUSH`, `LTRIM`, `LRANGE`, `HGET`, `GETDEL`) need helpers here,
not inline casts in `canary.py`:

```python
async def hgetall_slots(r: Redis, key: str) -> dict[bytes, bytes]:
    """HGETALL every slot record under ``key``. Returns {} when the key is absent."""
    return await cast(Awaitable[dict[bytes, bytes]], r.hgetall(key))
```

**Single-round-trip MULTI/EXEC pattern** (lines 122-129) — copy for the canary
`LPUSH`+`LTRIM`+`EXPIRE` window:

```python
async def hset_slot_with_ttl(
    r: Redis, key: str, field: str, value: str, ttl_seconds: int
) -> None:
    """HSET one slot record and refresh the key TTL in a single transaction."""
    async with r.pipeline(transaction=True) as pipe:
        pipe.hset(key, field, value)
        pipe.expire(key, ttl_seconds)
        await pipe.execute()
```

Also update the module docstring's `Named symbols:` list (lines 1-10) — that is the house
convention for every shared module.

---

### `shared/events.py` (model, pub-sub) — MODIFY

**Analog:** itself, lines 57-71:

```python
class PollCompleted(BaseModel):
    """Emitted to polls.completed after each poll attempt."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    poll_id: UUID
    source: Literal["opentable", "resy"]
    restaurant_id: int
    polled_at_epoch_ms: int
    status: Literal["success", "error", "timeout"]
    latency_ms: int
    http_status: int | None = None
    error: str | None = None
```
→ `status: Literal["success", "error", "timeout", "banned"]`, `context_id: str | None = None`
appended **last** (field order is wire order — see the `AvailabilityEvent` docstring at lines
88-90: *"Field declaration order below IS the JSON wire order that byte-identical replay depends
on — do not reorder"*). `extra="forbid"` is why `context_id` is currently rejected.

Add `FAILED_POLL_STATUSES: frozenset[str] = frozenset({"error", "timeout", "banned"})` here
(D-67a), following the `NAMESPACE_MISE: Final[UUID]` module-constant idiom at lines 13-20.

---

### `services/state_machine/consumer.py` + `scripts/replay_raw.py` (consumer/script) — MODIFY

**Analog:** each file itself. Two inverted checks.

`services/state_machine/consumer.py` lines 186-199:
```python
    async def _handle_completed(self, msg: Any) -> None:
        completed = PollCompleted.model_validate_json(msg.value)
        if completed.status not in ("error", "timeout"):
            # A success carries no new information here: the matching availability.raw message
            # is what advances state (D-47).
            return
        await self.engine.mark_unknown(completed.restaurant_id, completed.polled_at_epoch_ms)
        await self._flush()
```
→ `if completed.status == "success": return` (so every present and future non-success marks UNKNOWN).

`scripts/replay_raw.py` lines 106-110:
```python
async def _handle_completed(engine: DiffEngine, value: Any) -> None:
    """One polls.completed message: only error/timeout matters here (D-47)."""
    completed = PollCompleted.model_validate(value)
    if completed.status in ("error", "timeout"):
        await engine.mark_unknown(completed.restaurant_id, completed.polled_at_epoch_ms)
```
→ `if completed.status != "success":` (or `in FAILED_POLL_STATUSES`).

**`_flush()` placement:** note the analog flushes immediately after `mark_unknown` and after each
applied decision (consumer lines 163-164, 184-185) — that is the fixer's per-emit flush ordering.
Preserve it; do not batch.

---

### `services/state_machine/parsers/resy.py` (parser, transform)

**Analog:** `services/state_machine/parsers/opentable.py` — copy the whole shape.

**Docstring pattern** (lines 1-12), including the `[ASSUMED]`/spike pointer and the determinism claim:

```python
"""
OpenTable raw-payload normaliser (D-37, D-38a, D-39).

Shapes are [ASSUMED] per 01-RESEARCH.md section 4 — update from
services/poller/sources/opentable/README.md ## Query Shape after the
DevTools spike confirms the live response schema. Every walk below uses `.get()` chains and
explicit isinstance checks, never index assumption: one unhandled KeyError here would halt
the whole Kafka partition.

This module reads no clock and draws no entropy, so replay stays deterministic (D-49).
Named symbols: effective_coverage, parse_opentable
"""
```

**Coverage pattern** (lines 23-54) — for Resy, coverage comes from the D-64 **envelope entries
with status 200**, not from `request_params["party_sizes"][0]`. The analog's TODO at line 40
(`# TODO(P3/POLL-02): widen to the full party_sizes list when the adapter loops party sizes.`)
is exactly the bug the Resy envelope prevents. Keep the ParseError-on-unusable-input behaviour:

```python
    try:
        party = int(parties[0])
    except (TypeError, ValueError) as exc:
        raise ParseError(f"request_params.party_sizes[0] is not an integer: {exc}") from exc
```

**Defensive-walk + ParseError matrix** (lines 96-115):

```python
    payload = raw.raw_response
    if not isinstance(payload, Mapping):
        raise ParseError("payload not a mapping")
    if not payload:
        raise ParseError("empty payload")
    ...
    coverage = effective_coverage(raw.request_params)
    if not coverage:
        raise ParseError(
            "request_params yields no coverage: a poll that observed nothing cannot be "
            "reported as a successful observation"
        )
```

**Slot-emission + return pattern** (lines 117-159) — nested `for x in y if isinstance(y, list) else []`
walks, `continue` on every type mismatch, and the terminal `ParsedPoll(...)`:

```python
    return ParsedPoll(
        restaurant_id=raw.restaurant_id,
        source=raw.source,
        polled_at_epoch_ms=raw.polled_at_epoch_ms,
        poll_id=raw.poll_id,
        coverage=coverage,
        slots=tuple(slots),
    )
```
Resy field mapping (D-66): `time_slot` = `HH:MM` of `slot.date.start`, `seat_type` =
`slot.config.type`, `booking_token` = `slot.config.token`.

**Registration** — `services/state_machine/parsers/__init__.py` lines 15-17, exactly one new entry
(and the docstring at line 23 mentioning "`resy` until Phase 3" should be updated):

```python
PARSER_REGISTRY: dict[str, Callable[[AvailabilityRaw], ParsedPoll]] = {
    "opentable": parse_opentable,
}
```

---

### `services/poller/sources/resy/fixtures.py` (fixture data)

**Analog:** `services/poller/sources/opentable/fixtures.py` lines 1-16 — module docstring naming
the `[ASSUMED]` source, `TODO(spike):` marker above each body, one module-level
`dict[str, Any]` constant per scenario:

```python
"""
Golden-file JSON fixtures for OpenTable adapter unit/integration tests.
...
Shapes are [ASSUMED] per 01-RESEARCH.md §4 — update from
services/poller/sources/opentable/README.md ## Query Shape after the
DevTools spike confirms the live response schema.
"""
from __future__ import annotations

from typing import Any

# Minimal success response — 1 restaurant, 1 date, 1 timeslot.
# TODO(spike): confirm exact JSON structure against a live OpenTable response.
OPENTABLE_SUCCESS_RESPONSE: dict[str, Any] = {
```
→ `RESY_SUCCESS_RESPONSE`, `RESY_EMPTY_VENUES_RESPONSE`, `RESY_MISSING_RESULTS_RESPONSE`,
`RESY_RATE_LIMIT_RESPONSE`, `RESY_CHALLENGE_HTML` (the 403 body is HTML, not JSON — the adapter
must guard `.json()`).

---

### `services/poller/sources/resy/fingerprints.py` (data table)

**Analog:** `services/poller/config.py` lines 22-40 — a module-level list of real browser strings
with an invariant comment, plus a selection function:

```python
# User-Agent rotation list (T-03 — rotate per request to avoid fingerprinting).
# Must contain >=4 real browser strings; all entries unique.
USER_AGENTS: list[str] = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
    ...
]


def random_user_agent() -> str:
    """Return a random User-Agent from USER_AGENTS (T-03 mitigation)."""
    return random.choice(USER_AGENTS)
```
Differences to encode: Resy rotates **round-robin per context**, not `random.choice` per request;
each row is a frozen dataclass carrying UA + viewport + locale + `timezone_id` +
`device_scale_factor` + `sec-ch-ua` + `sec-ch-ua-platform` + `Accept-Language` + `platform` +
`hardwareConcurrency` + `deviceMemory` + WebGL vendor/renderer (B-3, B-9), and no row may contain
`Headless` (Pitfall 2).

**Test analog:** `tests/unit/test_ua_rotation.py` (31 lines) is the exact template for
`test_fingerprints.py` — assert count, uniqueness, and per-row invariants.

---

### `services/poller/sources/resy/accounts.py` (model, validation)

**Analog:** `shared/events.py` pydantic idiom (`model_config = ConfigDict(frozen=True,
extra="forbid")`, `Literal` fields, no wall-clock reads). No in-repo analog for *union-shaped
input normalisation*; encode D-61 + Pitfall 5 directly: both cookie shapes normalise to
`domain=".resy.com", path="/", secure=True`, and a host-only `resy.com` input logs a warning.

**Redaction dependency:** this file must not be written before `shared/telemetry.py` is extended
(B-6, Wave 0 ordering).

---

### `shared/metrics.py` (NEW, instrumentation)

**No direct analog.** Follow the `shared/redis_keys.py` module contract instead: module-level
definitions, a `Named symbols:` docstring list, imported (never re-defined) everywhere else.

Constraints from RESEARCH §Pitfall 6 that the planner must encode as task text:
- define each metric **exactly once** against the default `REGISTRY`; never `importlib.reload`;
- `Counter("scrape_ban_total", ...)` emits samples `scrape_ban_total` and `scrape_ban_created` —
  tests must call `get_sample_value("scrape_ban_total", labels)`, not `"scrape_ban_total_total"`;
- `poll_latency_seconds` needs **explicit buckets** (default buckets stop at 10.0):
  `(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60)`.

---

### `migrations/versions/0009_*.py` (migration, schema)

**Analog:** `migrations/versions/0008_add_event_id_to_availability_events.py`.

**Header + revision pattern** (lines 1-22) — a docstring that names the decision IDs and the
defects being corrected, then bare module-level revision vars:

```python
"""0008: Add event_id + unique (event_id, time) to availability_events (D-48a, corrected).

Destroys nothing: the upgrade refuses to run against a non-empty table rather than
deleting the rows it cannot backfill (see the guard in upgrade()).
...
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None
```
→ `revision = "0009"`, `down_revision = "0008"`.

**Pre-flight guard pattern** (lines 38-48) — the fixer's guard; copy this shape for 0009's
duplicate-`(slug, source)` check before adding the new unique constraint:

```python
    existing = op.get_bind().execute(
        sa.text("SELECT count(*) FROM availability_events")
    ).scalar_one()
    if existing:
        raise RuntimeError(
            f"availability_events holds {existing} pre-0008 row(s). ... Refusing to "
            "destroy them. Either archive and TRUNCATE ... then re-run `alembic upgrade head`."
        )
```

**Index + explanatory-comment pattern** (lines 61-83), including the doubled `%%` gotcha:

```python
    op.create_index(
        "uq_availability_events_event_id_time",
        "availability_events",
        ["event_id", "time"],
        unique=True,
    )
    # The doubled percent sign is required — alembic passes the string through a
    # format step before executing it.
    op.execute("COMMENT ON COLUMN ... IS '...'")
```

**What 0009 must undo** — `migrations/versions/0003_create_restaurants.py` declares the constraint
**twice**, so both must be dropped (D-63b):
```python
        sa.Column("slug", sa.Text, nullable=False, unique=True),   # :18  -> restaurants_slug_key
...
    op.create_index("ix_restaurants_slug", "restaurants", ["slug"], unique=True)   # :38
```
Also copy the **`downgrade()` honesty** pattern (0008 lines 86-94): state plainly what a downgrade
loses.

**Test analog:** `tests/integration/test_migration_0008.py` (246 lines) for the 0009 test.

---

### `scripts/seed_restaurants.py` + `scripts/seed/restaurants.yml` (script, batch)

**Analog:** itself.

**Source-derivation block to replace** (lines 53-67) — currently `elif`, so the Resy branch is
unreachable when an `opentable_rid` exists:

```python
                if rest.get("opentable_rid") is not None:
                    source = "opentable"
                    platform_id = str(rest["opentable_rid"])
                elif rest.get("resy_venue_id") is not None:
                    source = "resy"
                    platform_id = str(rest["resy_venue_id"])
```
→ loop over a list of `(source, platform_id, slug)` tuples per YAML entry, upserting one row each.
With migration 0009's `UNIQUE(slug, source)` the Resy row keeps the **same human slug** (D-63b
supersedes RESEARCH B-5's `-resy` suffix suggestion).

**Idempotent upsert pattern to reuse verbatim** (lines 69-102) — `ON CONFLICT (source, platform_id)
DO UPDATE SET ...` with a named-parameter dict.

**ZSET enqueue pattern** (lines 103-110) — extend with the `RESY_ENABLED` + numeric-id guard:

```python
                if source == "opentable":
                    score = int(time.time() * 1000) + int(random.uniform(0, 90_000))
                    await r.zadd(
                        SCHED_POLLS,
                        {make_job("opentable", int(platform_id)): score},
                    )
```

**YAML placeholder pattern** — `scripts/seed/restaurants.yml:54`:
```yaml
    opentable_rid: 900000001  # TODO(01-05 spike): replace with live rid from OpenTable DevTools
    resy_venue_id: "carbone-new-york-new-york"
```
→ rename the string field to `resy_url_slug` and add `resy_venue_id: null  # TODO(03 spike): numeric
venue_id from Resy DevTools` (D-63a). The header comment block at lines 14-19 documents the schema
and must be updated in the same edit.

**Test analog:** `tests/integration/test_seed_idempotency.py`.

---

### `scripts/soak_playwright.py` (script, sampling)

**Analog:** `scripts/check_poll_success.py` — for the exit-code contract and the CLI shape, NOT
for the sampling logic (which has no analog; use RESEARCH §Code Examples "RSS / PID sampling").

**Docstring + exit-code contract** (lines 1-13):

```python
#!/usr/bin/env python
"""
SC5 / PERF-02: Assert >= 99% poll success rate in every hourly bucket over last 24h.
...
Usage: uv run python scripts/check_poll_success.py
Or:    make verify-perf02

Exit codes:
  0 — All hourly buckets have success_rate >= 0.99 (PERF-02 passed)
  1 — One or more buckets are below 0.99 (PERF-02 failed)
  2 — Not enough data (fewer than 24 hourly buckets — run has not completed 24h yet)
"""
```

**Verdict-dataclass + threshold-constant pattern** (lines 29-44):

```python
SUCCESS_RATE_THRESHOLD = 0.99
REQUIRED_HOURS = 24


@dataclass
class HourlyBucket:
    hour: Any
    total: int
    success: int

    @property
    def rate(self) -> float:
        return self.success / self.total if self.total > 0 else 0.0
```
→ `SoakSample` / `SoakVerdict` with `RSS_GROWTH_THRESHOLD = 0.20`, `PID_SPREAD_MAX = 2`,
`SUCCESS_RATE_THRESHOLD = 0.99`. **Keep the verdict function pure** so `test_soak_verdict.py` can
feed it synthetic samples — the analog's `check()` mixes IO and verdict; split them here.

**`main()` / exit pattern** (lines 126-132):

```python
def main() -> None:
    exit_code = asyncio.run(check())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
```

**poll_log query pattern** (lines 56-67) for the success-rate sample: raw `asyncpg.connect(url)`
with the `postgresql+asyncpg://` → `postgresql://` strip at line 52.

---

### Test files

**Unit grep-gate** — `tests/unit/test_no_inline_sleep.py` is the exact template for
`test_no_inline_sleep_resy.py`. Copy all three pieces: the scanned-file tuple, the
comment-stripping helper, and the **non-vacuity guard**:

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
SERVICE_DIR = REPO_ROOT / "services" / "state_machine"

SCANNED_FILES: tuple[Path, ...] = (
    *sorted(SERVICE_DIR.glob("*.py")),
    *sorted((SERVICE_DIR / "parsers").glob("*.py")),
)

_FULL_LINE_COMMENT = re.compile(r"^\s*#")
_ASYNC_SLEEP = re.compile(r"asyncio\.sleep\(")


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Strip full-line comments so an explanatory comment cannot satisfy or break the gate."""
    ...


def test_scanned_file_set_is_not_empty():
    """A glob that silently matched nothing would make both assertions below vacuous."""
    assert len(SCANNED_FILES) >= 8
```

**Unit parser matrix** — `tests/unit/test_parsers_opentable.py` lines 1-40 for
`test_parsers_resy.py`: import the fixtures (never invent payloads inline), a local `_raw()`
wrapper over `tests/unit/factories.py :: make_raw`, and frozen constants `RID`, `DATE`,
`T0 = 1_788_000_000_000` (no wall clock).

**Unit factory** — `tests/unit/factories.py` lines 16-39 for `make_resy_envelope`:

```python
def deterministic_poll_id(source: str, rid: int, polled_at_epoch_ms: int) -> UUID:
    """Stable stand-in for the poller's uuid4 poll id, so repeated runs are byte-identical."""
    return uuid5(NAMESPACE_MISE, f"test-poll:{source}:{rid}:{polled_at_epoch_ms}")
```

**Environment guard** — `tests/conftest.py` lines 8-17 is the shape for `_chromium_available()`:

```python
def _docker_available() -> bool:
    """Return True if a Docker-compatible runtime is reachable."""
    try:
        ...
    except Exception:
        return False


@pytest.fixture(scope="module")
def redis_container(request):
    if not _docker_available():
        pytest.skip("Docker not available")
```
The Chromium version does the revision comparison from RESEARCH §Code Examples (a glob would
falsely pass on the stale `chromium-1223`), and skips with
`reason="Playwright Chromium for the pinned playwright version is not installed — run \`make browsers\`"`.

**Integration container plumbing** — `tests/integration/conftest.py` lines 20-70:
`reset_shared_db_singletons()`, `apply_migrations(env)`, `create_topics(env)`, `redis_url`,
`db_urls`. Reuse these; add `stub_base` / `browser` fixtures alongside them.

**Integration E2E (SC5)** — `tests/integration/test_state_machine_e2e.py` lines 1-45 is the
template for `test_resy_e2e_state_machine.py`. Copy in particular:
- the docstring rule *"``services.state_machine`` is imported INSIDE the test body, never at
  module scope"* (the 02-02 env-freeze workaround);
- `pytestmark = pytest.mark.integration`;
- explicit `polled_at_epoch_ms` everywhere so the 8 s confirmation window costs no real time;
- the local `_raw(...)` builder that constructs the message "exactly as
  `services/poller/publisher.py` would".

**Integration Redis/Lua** — `tests/integration/test_expedite_lua.py` and
`test_scheduler_claim_release.py` for `test_rate_budget_lua.py`, `test_per_context_floor.py`,
`test_canary_window.py`, `test_fleet_pause.py`, `test_release_precedence.py`.

---

### Docs

**`docs/runbooks/perf05-soak.md`** — analog `docs/runbooks/perf02-24h-log.md` lines 1-25: title,
`**Purpose:**`, a `**Status:** BLOCKED ON HUMAN ACTION` banner (D-70 asks for
`STATUS: pending-human-run`), then a `## Prerequisites` section of hard gates each with
`- **Action:**` / `- **Verification:**` bullets.

**`services/poller/sources/resy/README.md`** — analog
`services/poller/sources/opentable/README.md` lines 1-25: the
`<!-- SPIKE STATUS: PLACEHOLDER — needs live browser confirmation -->` marker, an explicit list of
"only these files need editing once a human completes the spike", and a closing rerun command.
Additions required by this phase: cite the functions enforcing the 80 rpm cap and 45 s floor (the
root README already promises both), and record the B-9 `APIRequestContext` TLS tradeoff (D-64a).

**`Makefile`** — analog lines 11-12 / 50-51; every target carries a `## description` because
`help` greps for it:

```make
topics: ## Create Kafka topics idempotently
	uv run python scripts/create_topics.py

verify-perf02: ## Assert all 24-hour buckets in poll_log have >=99% success rate
	uv run python scripts/check_poll_success.py
```
Add `browsers` and `soak` to the `.PHONY` list on line 3 as well — it is exhaustive today.

---

## Shared Patterns

### Structured logging + secret redaction
**Source:** `shared/telemetry.py` lines 17-32 and 71-74
**Apply to:** every new module under `services/poller/sources/resy/`

```python
def _redact_secrets(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    _REDACTED = "[REDACTED]"
    _SECRET_KEYS = {
        "TWILIO_AUTH_TOKEN",
        "HMAC_MGMT_SECRET_V1",
        "VAPID_PRIVATE_KEY",
        "RESY_ACCOUNTS_JSON",
    }
    for k in list(event_dict.keys()):
        if k in _SECRET_KEYS or k.startswith("RESY_ACCOUNT_") and k.endswith("_PASSWORD"):
            event_dict[k] = _REDACTED
    return event_dict
```
Extend with **case-insensitive** matching for `cookie`, `cookies`, `set-cookie`, `auth_token`,
`x-resy-auth-token`, `authorization`, `api_key`, plus exact `RESY_API_KEY` and `RESY_PROXY_URL`
(URL credentials masked). This is a **Wave 0 blocker** (B-6) — it must land before any
cookie-handling code exists.

Module-level logger, once per file: `log = get_logger(__name__)`
(`services/poller/sources/opentable/adapter.py:31`).

### Lazy config reads (never module constants)
**Source:** `services/state_machine/config.py` lines 1-40
**Apply to:** every new Resy setting in `services/poller/config.py`

```python
"""
Every environment read below is a FUNCTION, not a module constant, and that is deliberate.
`services/poller/config.py` freezes KAFKA_BOOTSTRAP_SERVERS / REDIS_URL into module constants
at IMPORT time, so any integration test that imports the service during collection pins the
whole run to the localhost defaults instead of its testcontainers (02-02 deviation 1). Reading
lazily inside `run()` removes that footgun for this service permanently.
"""

def kafka_bootstrap_servers() -> str:
    """Broker list. Default matches services/poller/config.py — the two must never disagree."""
    return os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
```
The `__all__` list (lines 22-33) is required for `mypy --strict` re-exports. The anti-pattern to
avoid is `services/poller/config.py:44` (`KAFKA_BOOTSTRAP_SERVERS: str = os.getenv(...)`).

### Service lifecycle / nested try-finally
**Source:** `services/poller/main.py` lines 65-105
**Apply to:** the Resy pool start/stop wiring

```python
async def run() -> None:
    configure_logging()
    log.info("poller_starting")

    http_client = get_async_client()
    try:
        r = redis.from_url(REDIS_URL)
        scheduler = LuaScheduler(r)
        await scheduler.start()
        ...
        opentable = OpenTableAdapter(client=http_client)
        publisher = Publisher(producer=producer)
        log.info("poller_ready", redis=REDIS_URL, kafka=KAFKA_BOOTSTRAP_SERVERS)
        try:
            await asyncio.gather(
                poll_loop(scheduler, opentable, publisher),
                reaper_loop(scheduler),
            )
        finally:
            await producer.stop()
            await r.aclose()
            log.info("poller_stopped")
    finally:
        await close_async_client()
```
Three modifications: `asyncio.gather` fans out `POLL_WORKERS` `poll_loop` tasks (D-72, Pitfall 4);
the pool is constructed only when `RESY_ENABLED=true`; the browser teardown uses
`await asyncio.shield(browser.close())` (Pitfall 1), not the bare `await` shown above.

### Never leak a claimed job
**Source:** `shared/scheduler/lua.py` lines 83-97 (`drop`) + `services/poller/scheduler.py` lines 62-78
**Apply to:** every new pre-dispatch gate in `poll_loop`

`drop()` = the descriptor can never succeed (malformed). `release(job, now + delay)` = the job is
fine but not now (paused, backed off, rate-refused, no eligible context). A bare `continue` after a
`claim()` is always a bug — the reaper will re-enqueue it forever.

### No sleeps for scheduling
**Source:** CI ban-grep (`.github/workflows/lint.yml:21-23`) + `tests/unit/test_no_inline_sleep.py`
**Apply to:** `services/poller/sources/resy/**` and the scheduler gates
The only legitimate `asyncio.sleep` in the poller is the empty-queue backoff at
`services/poller/scheduler.py:59`. The 45 s floor, the 80 rpm cap and the 429 backoff are all ZSET
scores.

### mypy --strict Redis awaits
**Source:** `shared/redis_keys.py` lines 80-110, `shared/scheduler/lua.py` lines 49-57
**Apply to:** `canary.py`, `pool.py`, the new scheduler gates
Every `cast(Awaitable[T], ...)` lives in `shared/redis_keys.py`, exactly once, never inline in a
service module. `playwright` ships `py.typed` so it needs no ignores; `playwright_stealth`
resolves to `Any`, so a `SCRIPTS` key typo needs a **unit test**, not a type annotation
(Pitfall 7).

### Decision-ID citation discipline
**Source:** every module in the repo
Module docstrings name the decisions they implement (`(D-05, D-19, POLL-03)`), shared modules list
`Named symbols:`, and non-obvious code carries a comment explaining what breaks without it
(`shared/redis_keys.py:64-77`, `services/poller/scheduler.py:64-67`). Match this density — the
planner should expect it in every new file.

---

## No Analog Found

| File | Role | Data Flow | Reason / where to get the pattern |
|------|------|-----------|-----------------------------------|
| `services/poller/sources/resy/stealth.py` | utility | pure transform | No browser-automation code exists in the repo. Use RESEARCH §Code Examples "Coherent per-context stealth" (`SCRIPT_ORDER` + `stealth_opts(fp)` + `context.add_init_script`) — verified working this session. |
| `services/poller/sources/resy/pool.py` (browser half) | resource pool | lifecycle | Class shape from `shared/scheduler/lua.py`; browser launch/teardown from RESEARCH §Code Examples "`ContextPool` browser lifecycle" (shielded `finally`). |
| `shared/metrics.py` | config/registry | instrumentation | No Prometheus code exists yet. RESEARCH §Pitfall 6 + §Code Examples "Prometheus in an asyncio process". |
| `tests/fakes/resy_stub.py` | test fake | request-response | No `tests/fakes/` directory exists; the repo's only fake-server idiom is `respx` mocks (Phase 1). Use RESEARCH §Code Examples "In-process uvicorn stub" (verified green, 2.94 s). |
| `tests/integration/test_no_zombie_browsers.py` | integration | process | No process-lifecycle test exists. RESEARCH §Pitfall 1 (both the leaking and the clean run were reproduced). |
| `scripts/soak_playwright.py` (sampling half) | script | process/file-I/O | `ps -o rss=` / `pgrep -f ms-playwright` sampling has no precedent. RESEARCH §B-8 + §Pattern 8. Note the `/proc` fallback requirement for slim CI images. |
| Rate-budget Lua (`shared/redis_keys.py` addition) | Lua | atomic counter | Style analog exists (`CLAIM_POLL_LUA`), but the INCRBY-with-cap script itself is new — RESEARCH §Pattern 6 / §Code Examples "Minute-budget Lua" (executed against Redis 7.2.16). |
| `docs/runbooks/resy-cookie-capture.md` | doc | — | **Does not exist** despite being referenced by D-63a and `.env.example:36`. Create it from `docs/runbooks/perf02-24h-log.md`'s prerequisite-gate structure. |

---

## Metadata

**Analog search scope:** `services/`, `shared/`, `scripts/`, `tests/`, `migrations/`, `docs/runbooks/`, `Makefile`, `.env.example`
**Files scanned:** 97 Python/YAML/Markdown files listed; 24 read in full or in targeted ranges
**Pattern extraction date:** 2026-09-05
**Freshness note:** read after the concurrent Phase 2 code-review fixes; no stale content used.
