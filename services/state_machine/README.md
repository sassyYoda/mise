# State machine service

Consumes `availability.raw` and `polls.completed`, normalises each source's payload into slot
records, diffs them against Redis state with a tri-state model, and emits a confirmed
`availability.events` message the moment a slot has been seen open by two independent
successful polls at least `CONFIRM_DELAY_MS` apart. Confirmed events are also written to the
`availability_events` TimescaleDB hypertable, and a slot that later vanishes has its row closed
with a `duration_seconds` — closures are database-only and never reach Kafka. The service never
calls OpenTable or Resy itself and never waits out the confirmation delay in process: it lowers
the restaurant's due score in the poller's ZSET, and the confirmation arrives as another
message (D-43, STATE-03).

Run it with `uv run python -m services.state_machine` against a `make up` stack.

## Layout

| File | Role |
|------|------|
| `engine.py` | Pure diff core. No I/O, no clock read, no entropy — this is what makes replay byte-identical (D-49). |
| `models.py` | Value types: `SlotState`, `Slot`, `ParsedPoll`, `SlotRecord`, and the `Expedite` / `Emit` / `Close` decisions. |
| `parsers/` | Per-source registry. Phase 2 registers `opentable`; `resy` raises `UnsupportedSourceError` until Phase 3. |
| `store.py` | `MemoryStateStore` (replay, tests), `RedisStateStore` (production), `BufferedStateStore` (write-behind, see below). |
| `consumer.py` | The imperative shell. Every side effect lives here and nowhere else. |
| `persistence.py` | Best-effort hypertable insert and close, plus the New York service-time math. |
| `main.py` | Lifecycle: topic guard, Redis, scheduler, producer, consumer, teardown. |

## State transitions (D-41)

A slot is identified by `(source, restaurant_id, date, party_size, time_slot, seat_type)`. The
`booking_token` is data, not identity — tokens rotate between polls for the same physical slot.

| From | Trigger | To | Emits |
|------|---------|----|-------|
| absent | slot seen on a successful poll | PENDING | nothing (the next poll is expedited to t+8 s) |
| PENDING | seen again, `polled_at - first_seen >= CONFIRM_DELAY_MS` | AVAILABLE | `availability.events` + a hypertable row |
| PENDING | seen again, but sooner than `CONFIRM_DELAY_MS` | PENDING | nothing (an accidental duplicate poll cannot confirm) |
| PENDING | absent on the next successful *covered* poll | dropped | nothing — this is the false-positive guard |
| AVAILABLE | still seen | AVAILABLE | nothing (refreshes `last_seen` and the rotated token) |
| AVAILABLE | absent on a successful *covered* poll | UNAVAILABLE | nothing on Kafka; the DB row is closed with `duration_seconds` |
| UNAVAILABLE / absent | seen again | PENDING | nothing — a re-open is a brand-new cycle with a new `event_id` |
| any | poll errored, timed out, or was unparseable | unchanged | nothing; the restaurant meta is marked UNKNOWN |

UNKNOWN is a **restaurant-level** mark, never a slot state: `SlotState` has three members and
no UNKNOWN, because an errored poll must leave every slot at its last known state (D-41).

Two rules keep this honest:

* **Coverage bounds closure.** A slot is only closed or dropped when its `(date, party_size)`
  was actually observed by that poll. A date window that rolls forward, or a party size the
  adapter did not really request, closes nothing (D-38, D-38a).
* **UNKNOWN never moves a slot toward UNAVAILABLE**, and the mark is monotonic in poll time —
  a stale error cannot re-mark a restaurant whose newer poll succeeded (D-53).

## Emit ordering (D-46)

```
   message
      |
      v
  [ DiffEngine.process ]  -- decisions as data, no I/O
      |
      +--> Expedite: ZADD sched:polls XX LT (poll_time + 8000)
      |
      +--> Emit, per slot, in this order and no other:
      |       1. SET event:{rid}:{date}:{party}:{slot_key}:{token} 1 NX EX 1200  <- Layer-1 claim
      |       2. producer.send_and_wait("availability.events", ...)    <- acks=all, never a bare send
      |       3. INSERT ... ON CONFLICT (event_id, "time") DO NOTHING  <- idempotent, best effort
      |       4. HSET avail:{rid}:{date}:{party} <slot> AVAILABLE      <- state write, THIS slot only
      |
      +--> Close: UPDATE ... WHERE event_id = ? AND "time" = ?         <- DB only, no Kafka
      |
      v
  consumer.commit({tp: offset + 1})     <- after the WHOLE message, never before
```

The order is not stylistic. Each step is placed so that a crash at any point is safe:

| Crash point | Redis `event:*` | Kafka | Redis state | Offset | Restart behaviour |
|-------------|-----------------|-------|-------------|--------|-------------------|
| before `SET NX` | absent | none | PENDING | uncommitted | full re-diff, emits once |
| after `SET NX`, before send | present | none | PENDING | uncommitted | NX fails + state PENDING → **re-send** same deterministic `event_id` (Layer-2 dedupes in P4) |
| after send, before state write | present | sent | PENDING | uncommitted | same as above — one duplicate on the wire, identical `event_id` |
| after state write, before commit | present | sent | AVAILABLE | uncommitted | NX fails + state AVAILABLE → **skip**. This is the D-51 chaos path. Zero duplicates. |
| after commit | present | sent | AVAILABLE | committed | not redelivered |

The table is **per slot**, and that word is load-bearing. One poll routinely confirms several
slots (the OpenTable payload alone fans one timeslot out into one slot per seating type), and
each of them walks steps 1-4 independently. Three implementation notes make the table true
rather than aspirational:

* **`BufferedStateStore` exists for row 2 and row 3.** The engine writes through its store as it
  diffs, so a bare `RedisStateStore` would record AVAILABLE *before* the Kafka send — and a
  crash in that window would leave a record the next diff reads as already-emitted, losing the
  opening for good. The shell buffers the engine's writes and flushes them at step 3.
* **Step 3 flushes ONE slot, not the message.** `DiffEngine.process()` runs to completion before
  any decision is applied, so when the first slot of a multi-slot poll reaches step 3 the
  AVAILABLE records of every *other* slot are already in the buffer. A message-wide flush there
  would make them durable before their own step 2, and rows 2 and 3 would be false for every
  emit after the first. `BufferedStateStore.flush_slot` therefore makes exactly the acked slot
  durable; the remaining buffered writes (drops, closures, meta) are flushed at the tail of the
  message. Guarded by `tests/unit/test_emit_flush_ordering.py`, which snapshots the durable
  store at the moment of each send and replays a crash on the second slot's send.
* **The INSERT sits before the state write, not after.** It is idempotent, so a duplicate
  attempt is free; a never-attempted one is not recoverable. With the state write first, a
  crash between them left the slot durably AVAILABLE and the event on the wire with no DB row
  — the redelivered poll produces no `Emit`, `insert_event` is never retried, and the later
  `Close` UPDATE silently matches zero rows. D-48's best-effort persistence covers a *failed*
  insert, not a never-attempted one.
* **On the row-4 restart the skip happens one layer earlier than the table suggests.** The
  redelivered poll now finds the slot AVAILABLE, so the engine produces no `Emit` at all and
  the shell's claim branch is never reached. The outcome — zero duplicates — is identical, and
  `tests/integration/test_state_machine_chaos.py` proves it with a real `SIGKILL`.

The offset is committed even for a **poison** message, after the failure is logged: a payload
that cannot be decoded will never decode, and it must never stall the partition. Unparseable
payloads mark the restaurant UNKNOWN and remove nothing (D-39).

A **transient** failure — a Redis timeout, a broker outage, a producer error — is the opposite
case. It is deliberately *not* committed **and the partition is rewound to the failed offset**
(`seek`), then paused for a bounded backoff and resumed. Both halves are required. Skipping the
commit on its own does *not* keep the offset where it is: the consumer's position has already
advanced, so `run()` immediately pulls the next message and its own `commit(offset + 1)` sets
the group watermark strictly past the failed one, which is then below the watermark and never
redelivered. Only the rewind makes the failed message the next one delivered. The pause is what
stops a dead dependency turning redelivery into a hot loop; it is scoped to the affected
partition, so any other assigned partition keeps flowing. Committing here would silently drop
an observation the next attempt would have handled: for a `polls.completed` `error`/`timeout`
that is the UNKNOWN mark lost for good.

The backoff is `consumer.pause()` plus a `loop.call_later` `resume`, never an inline
`asyncio.sleep` — `tests/unit/test_no_inline_sleep.py` bans a sleep anywhere in this service
(D-43, STATE-03), and pause/resume is what Kafka provides for exactly this backpressure.

### The rewind is bounded (CR-01)

"Everything that is not a `ValidationError`/`ParseError`" is **not** a synonym for
"transient". It includes `AttributeError`, `KeyError`, an `UnknownTopicOrPartitionError` after
someone deletes a topic, a Redis `WRONGTYPE` or `OOM command not allowed`, and every
programming bug that will ever be introduced into `engine.py` or `store.py`. None of those
succeeds on retry. An unbounded rewind therefore trades a silent data loss for a permanently
stalled partition — which on a single-partition topic is a total pipeline outage whose only
symptom is `message_handling_failed` + `message_retry_scheduled` at 0.5 Hz, forever. **Stalling
is not the safer failure: it drops every later observation too.**

So the retry is capped at `STATE_MACHINE_MAX_ATTEMPTS` (default 5, `>= 1` enforced at startup),
counted per `(topic, partition, offset)`. On exhaustion the message is treated as poison:

| Step | What happens |
|------|--------------|
| 1 | `message_retries_exhausted` at ERROR, with the attempt count, the failure **shape**, and `metric=state_machine_messages_dead_lettered_total` for Phase 7's exporter |
| 2 | the ORIGINAL bytes are published to **`availability.dlq`** (7-day retention, so the record outlives `availability.raw`'s 24 h), with `original_topic` / `original_partition` / `original_offset` / `attempts` / `error` headers |
| 3 | the offset is committed and the partition moves on |

The DLQ publish is best effort by design: if the broker is down too, `dead_letter_publish_failed`
is logged and the commit still happens. A dead-letter topic that is itself unavailable must not
be able to re-create the stall this mechanism exists to end. `availability.dlq` is created by
`scripts/create_topics.py` and guarded at startup by both services' `REQUIRED_TOPICS`, so a
deployment that skipped `make topics` fails immediately rather than at the moment the pipeline
is already poisoned.

### A retry never re-sends an acked event

The second half of CR-01, and the more expensive one. When a permanent failure lands *after* a
slot's `send_and_wait` — `_flush_slot` is the live example — every retry used to re-execute the
emit: `set_nx_ex` returns False, `_crashed_mid_emit` reads a durable record still PENDING
(because `_discard()` threw the buffered write away), answers True, and the event goes out
again. At a 2 s backoff that is roughly 43k duplicate events a day. Phase 4's Layer-2 key
dedupes the *notification*; nothing dedupes the topic, the analytics insert attempt, or the log
stream.

The shell therefore records each `event_id` the broker has **acked** for the offset currently
under retry, and a retry skips the send for those (`emit_skipped_already_acked`) while still
running the remaining, idempotent steps — the INSERT and the per-slot state write — so the slot
does not stay PENDING with its event already on the wire. The set is cleared the moment the
offset advances, because retry accounting that leaked across messages would suppress a genuine
later emit. Guarded by `tests/unit/test_retry_cap_and_dlq.py`, which drives `run()` over the
two-slot payload and asserts the retry sends the remaining slot **only**.

## Redis keys

All key patterns and TTLs are declared in `shared/redis_keys.py` — never inline a key string
here (D-42).

| Key | Type | TTL | Contents |
|-----|------|-----|----------|
| `avail:{rid}:{date}:{party}` | HASH | 90000 s (25 h) | field = `{time_slot}\|{seat_type or '-'}`, value = compact JSON slot record |
| `avail:{rid}:meta` | HASH | 90000 s | `unknown_since_ms`, `last_success_ms` |
| `event:{rid}:{date}:{party}:{slot_key}:{token}` (each component percent-escaped) | STRING | 1200 s | the Layer-1 emission claim, one key per slot identity |
| `sched:expedite:{source}:{rid}` | STRING | 120 s | set when the job is in flight; the poller consumes it with `GETDEL` |

The claim key includes the **slot key**, not just the booking token. `seat_type` is part of
slot identity (D-36) and OpenTable gives every seating type of one timeslot the *same*
`token`, so a token-only claim key would collapse two distinct slots onto one key: the second
slot's `SET NX` would fail, its confirmed event would be skipped rather than re-sent, and the
opening would be lost. `scripts/replay_raw.py` uses no claim key at all, so a token-only key
also made production and replay disagree on the same input — a STATE-06 violation. The
regression guard is `tests/unit/test_two_seat_types_one_token.py`.

Every component is **percent-escaped** before the join, so the key is injective. `slot_key` is
`{time_slot}|{seat_type or '-'}` and both halves, like `token`, are payload data that the
parser only isinstance-checks — and a time slot always contains a `:`, the separator itself.
A plain join was therefore ambiguous in the ordinary case, not an exotic one: `slot_key
= "19:00|bar", token = "a:b"` and `slot_key = "19:00|bar:a", token = "b"` both rendered
`event:42:D:2:19:00|bar:a:b`, so one confirmed opening could claim the other's key and be
dropped. `shared/events.py`'s `make_event_id` has the same concatenation and deliberately does
NOT escape: its output is a permanent uuid5 already recorded in every golden and every
`availability_events` row. The constraint is documented there.

The TTL is **key-level and refreshed on every write**, deliberately. Per-field hash TTL
(`HEXPIRE`) is a Redis 7.4 *server* feature; redis-py 7.4.0 has the client method, so using it
would lint clean and fail only at runtime against the pinned `redis:7.2-alpine`.

## How to join

`restaurant_id` — on the wire, in the Redis keys above, in `AvailabilityEvent`, and in the
`availability_events.restaurant_id` column — is the **source platform id** (the OpenTable rid,
the Resy venue id), exactly as `poll_log.restaurant_id` already is. It is **not**
`restaurants.id` (D-52).

Phases 4, 5 and 6 must therefore join on the pair:

```sql
SELECT ...
FROM availability_events e
JOIN restaurants r
  ON r.source = e.source
 AND r.platform_id = e.restaurant_id::text   -- platform_id is TEXT
```

Joining `r.id = e.restaurant_id` compiles, runs, and silently returns zero rows. The same
statement is recorded in the database itself as a `COMMENT ON COLUMN` (migration 0008).

## Scaling

`availability.raw` has **one partition**, so this service scales by partition count, not by
replica count. A second member of the `state-machine` consumer group would simply idle with no
partition assigned — it is a warm standby, not extra throughput. Per-restaurant ordering is
guaranteed by the `{source}:{restaurant_id}` Kafka key, so partition count can be raised later
without breaking the diff. At the MVP's ~400 events/day, one consumer is far from saturated.

## Replay

```
make replay ARGS="--help"
make replay ARGS="--input tests/fixtures/raw_streams/happy.jsonl"
make replay ARGS="--from-offset 2 --to-offset 5 --output /tmp/events.jsonl"
make replay ARGS="--from-offset 0 --partition 2"
```

`scripts/replay_raw.py` feeds raw messages through `DiffEngine(MemoryStateStore())` and writes
one canonical event per line — `AvailabilityEvent.to_bytes()`, the same serializer the producer
uses, so the output is byte-identical to what the consumer put on the wire.

`--to-offset` is **EXCLUSIVE** and defaults to the topic's end offsets, so `--from-offset 2
--to-offset 5` replays offsets 2, 3 and 4 (D-55).

`--partition` names the partition to replay. Kafka offsets are per-partition, so it is
**required** once the topic has more than one — `availability.raw` has one today, and the
scaling section above contemplates raising that. A multi-partition topic with no `--partition`
is refused with an explicit error rather than silently replaying partition 0 and exiting 0 as
though it had covered the whole stream. Replay uses `group_id=None` with
`assign`/`seek` and never `subscribe`, so it cannot move the `state-machine` group's committed
offsets, and it opens no Redis or Postgres connection at all (D-49, D-50).

Exit codes: `0` success (an empty result is a success), `1` usage or I/O error, `2` no messages
found in the requested offset range.

The committed fixture corpus in `tests/fixtures/raw_streams/` pins the behaviour. Each `*.jsonl`
input has a `*.events.jsonl` golden generated by the script and compared byte-for-byte in CI:

| Fixture | Events | Proves |
|---------|--------|--------|
| `happy.jsonl` | 1 | Two polls 9 s apart confirm one slot; two replays are byte-identical (STATE-06) |
| `transient_errors.jsonl` | 0 | Timeout, 503, GraphQL errors array and an empty body emit nothing (ROADMAP SC1) |
| `flapping.jsonl` | 1 | Seen, gone, seen again is ONE opening dated from the second sighting |

Fixture lines are tagged envelopes so one file can carry both topics:
`{"topic": "availability.raw" | "polls.completed", "value": { ...message body... }}`.
Every timestamp and poll id in them is a hard-coded literal — a golden generated from a clock
would stop being a golden.

## Environment

| Name | Default | Notes |
|------|---------|-------|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9094` | Same default as the poller — the two must agree. |
| `REDIS_URL` | `redis://localhost:6379/0` | Slot state, the emission claim and the scheduler ZSET. |
| `DATABASE_URL_ASYNC` | `postgresql+asyncpg://mise:mise@localhost:5432/mise` | Analytics writes only; a failure is logged, never fatal. |
| `CONFIRM_DELAY_MS` | — | **Not an environment variable.** The confirmation window is the compile-time constant `shared.redis_keys.CONFIRM_DELAY_MS` (8000 ms); setting it in a shell or a deployment does nothing. Listed here because it used to be documented as tunable. |
| `STATE_MACHINE_MAX_ATTEMPTS` | `5` | How many times one message may be retried before it is dead-lettered to `availability.dlq` and committed past (CR-01). Must be `>= 1`: a value of `0`, a negative, or a non-integer is refused at startup rather than silently restoring the unbounded retry that stalled the partition forever. At the 2 s backoff, 5 attempts is ~10 s of trying — long enough to ride out a Redis failover, short enough that a permanent failure does not hold the partition. |
| `ENV` | `dev` | Must be **explicitly** one of `dev`, `test`, `ci`, `local` for `MISE_CRASH_AFTER` to be accepted. Anything else — including unset — refuses to start with the hook armed. |
| `MISE_CRASH_AFTER` | unset | **TEST ONLY.** SIGKILLs the process after the named stage (`nx_claim`, `kafka_send`, `state_write`, `commit`) so the chaos test can prove crash safety. `main.run()` raises unless `ENV` is explicitly one of `dev`/`test`/`ci`/`local`; the interlock fails closed, so an unconfigured container is not the most permissive configuration. |

Every variable in the table above (bar the last-but-one row, which is not one) is read lazily,
inside `run()`, never frozen into a module constant at import time — that is what lets an
integration test point the service at a container after collection.

The confirmation window is deliberately *not* configurable. `tests/fixtures/raw_streams/*.events.jsonl`
are byte-for-byte goldens, and a golden whose value depends on the caller's environment is not
a golden; `scripts/replay_raw.py` therefore compiles the same constant in rather than reading
it. Changing the window is a source edit in `shared/redis_keys.py`, which regenerates the
goldens under review — which is the point.
