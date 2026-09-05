"""
Imperative shell around the pure diff engine (D-43, D-46, D-47, D-51; STATE-02..05).

Routes one message at a time, asks DiffEngine for the decisions, and executes them in the
crash-safe order D-46 specifies: claim, send, record, persist — and only after the whole
message, commit the offset. The order is not arbitrary. Each step sits where it does so that a
crash at any point either replays harmlessly or re-sends the SAME deterministic event id, which
the Phase 4 Layer-2 key dedupes. The full crash-point table is reproduced in README.md.

Confirmation is never awaited in process: the re-verification arrives as another poll message,
pulled forward through the ZSET scheduler (D-43, STATE-03).

Logs carry ids and counts only — never a booking token and never a payload body (T-02-03).
Named symbols: StateMachineConsumer, RAW_TOPIC, COMPLETED_TOPIC, EVENTS_TOPIC, DLQ_TOPIC
"""
from __future__ import annotations

import asyncio
import os
import signal
from typing import Any
from uuid import UUID

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.errors import KafkaError
from pydantic import ValidationError
from redis.asyncio import Redis

from services.state_machine.config import crash_after, max_message_attempts
from services.state_machine.engine import (
    MASS_CLOSURE_AUDIT_THRESHOLD,
    DiffEngine,
    StateStore,
)
from services.state_machine.models import Close, Decision, Emit, Expedite, SlotState
from services.state_machine.parsers import ParseError, parse_raw
from services.state_machine.persistence import close_event, epoch_ms_to_utc, insert_event
from services.state_machine.store import BufferedStateStore
from shared.events import AvailabilityRaw, PollCompleted
from shared.redis_keys import (
    EVENT_IDEMPOTENCY_TTL_SECONDS,
    event_idempotency_key,
    job,
    set_nx_ex,
)
from shared.scheduler.lua import LuaScheduler
from shared.telemetry import get_logger, safe_error

log = get_logger(__name__)

# Named-Symbol Kafka topics (D-27, D-45).
RAW_TOPIC = "availability.raw"
COMPLETED_TOPIC = "polls.completed"
EVENTS_TOPIC = "availability.events"

# Dead-letter topic for a message that exhausted its retries (CR-01). 7-day retention, like
# the other diagnostic topics: long enough to survive a weekend, short enough not to become a
# second copy of the raw stream. Created by `scripts/create_topics.py` and guarded at startup
# by both services' `REQUIRED_TOPICS`, so by the time this module can publish it exists.
DLQ_TOPIC = "availability.dlq"

# How long a partition stays paused after a transient handler failure before the rewound
# message is retried. Bounded and deliberately short: the point is to stop a hot retry loop
# against a dead dependency, not to wait anything out. It is implemented with
# `loop.call_later` + `AIOKafkaConsumer.pause/resume` rather than `asyncio.sleep`, because
# `tests/unit/test_no_inline_sleep.py` bans an inline sleep anywhere in this service (D-43,
# STATE-03) and pause/resume is the primitive Kafka provides for exactly this backpressure.
TRANSIENT_RETRY_BACKOFF_SECONDS: float = 2.0

# How many times `_resume_partition` may re-schedule itself after an unexpected failure before
# it gives up and says so (WR-06). Bounded because the callback re-arms its own timer: against
# a consumer that is genuinely gone, an unbounded chain is a log flood with no end.
MAX_RESUME_ATTEMPTS: int = 3

# Prometheus counter names, declared here as placeholders so Phase 7's exporter has a stable
# hook and so the structlog events carry the name a dashboard will use (D-51 discretion note).
# They are emitted as a `metric=` field rather than incremented: this phase ships no registry,
# and inventing one in the consumer would put a second source of truth next to shared/.
METRIC_MESSAGES_DEAD_LETTERED = "state_machine_messages_dead_lettered_total"
METRIC_PARTITION_RESUME_ABANDONED = "state_machine_partition_resume_abandoned_total"


def _failure_shape(exc: BaseException) -> list[str] | str:
    """
    Describe a failure by its SHAPE, never by its content (T-02-03).

    `str(exc)` is not safe to log here and never was. Pydantic v2 renders the OFFENDING INPUT
    into a `ValidationError`'s message (`... input_value='SECRET-BOOKING-TOKEN-abc123' ...`),
    and `availability.raw` is producer-supplied data whose `raw_response` carries every
    booking token OpenTable returned. A booking token is a capability — it is what holds the
    reservation — so `error=str(exc)` put a live credential in the log stream, and any payload
    drift that lands a token in a wrongly-typed field puts it there with nobody doing anything
    wrong. The same argument applies to an arbitrary driver exception on the transient path: a
    redis-py or asyncpg message can carry a DSN, a URL or a query.

    So: for a `ValidationError`, the field path and the error TYPE of each error, which is
    everything needed to diagnose a schema mismatch and contains no input. For anything else,
    the exception's dotted type name.

    DEPENDENCY (IN-01): `error['loc']` is payload-free only because `AvailabilityRaw`'s
    `raw_response` and `request_params` are `dict[str, Any]`, which produces no nested errors.
    If either is ever tightened to a real model, `loc` will start carrying payload-supplied
    dict keys and this redaction silently weakens — cap the rendered path to `error['loc'][0]`
    in the same commit that tightens the schema.
    """
    if isinstance(exc, ValidationError):
        return [
            f"{'.'.join(str(part) for part in error['loc'])}:{error['type']}"
            for error in exc.errors()
        ]
    return f"{type(exc).__module__}.{type(exc).__name__}"


def _maybe_crash(stage: str) -> None:
    """
    TEST-ONLY SIGKILL hook; a no-op unless MISE_CRASH_AFTER names this stage.

    Stages, each fired immediately AFTER the named step completes: `nx_claim`, `kafka_send`,
    `state_write`, `commit`. SIGKILL and never SIGTERM: a catchable signal would let the
    consumer shut down cleanly and commit its offset, which is exactly the behaviour the chaos
    test has to prevent.

    The environment read is `config.crash_after` and nothing else. This module used to carry a
    byte-identical private copy while `main.run()`'s startup interlock consulted the config
    one, and two readers of a single safety-critical variable is one too many: a change to the
    variable's name or parsing in one place would silently disarm the interlock on the other.
    Reading it lazily (not at import) is what lets the chaos test control the hook purely by
    launching a subprocess.
    """
    if crash_after() == stage:
        os.kill(os.getpid(), signal.SIGKILL)


class StateMachineConsumer:
    """
    Owns every side effect the engine's decisions imply: expedite, claim, send, record, persist,
    commit. The engine returns decisions as data; this class is the only place that acts on them.
    """

    def __init__(
        self,
        *,
        consumer: AIOKafkaConsumer,
        producer: AIOKafkaProducer,
        redis_client: Redis,
        scheduler: LuaScheduler,
        engine: DiffEngine,
        store: StateStore,
        buffer: BufferedStateStore | None = None,
        max_attempts: int | None = None,
    ) -> None:
        self.consumer = consumer
        self.producer = producer
        self.r = redis_client
        self.scheduler = scheduler
        self.engine = engine
        # `store` is the DURABLE store. The claim-failure branch must read what actually
        # survived a crash, never the engine's not-yet-flushed view of it (D-46).
        self.store = store
        # When present, the engine's writes are buffered and land where D-46 puts the state
        # write: after the broker has acked. See BufferedStateStore for why that matters.
        self.buffer = buffer
        # Pending `resume` timers, one per rewound partition (see `_retry_later`). Entries are
        # removed when the timer fires or in `run()`'s finally, so a partition revoked by a
        # rebalance between the pause and the timer leaves its key here until the callback
        # no-ops. That is bounded by the ASSIGNMENT SIZE, not by traffic, so it is tidiness
        # rather than a leak (IN-04) — a `ConsumerRebalanceListener` would be the fix if the
        # partition count ever stopped being 1.
        self._resume_handles: dict[TopicPartition, asyncio.TimerHandle] = {}
        # Retry accounting for the message currently at the head of a partition (CR-01). Only
        # ONE message can be under retry at a time — the rewind makes the failed offset the
        # next one delivered — so a single key plus a counter is the whole state, and it
        # cannot grow. `_acked_event_ids` is the second half of the fix: it records which
        # events the BROKER has already accepted for this offset, so a retry after a partial
        # emit finishes the remaining work without putting a duplicate on the wire.
        self._attempt_key: tuple[str, int, int] | None = None
        self._attempts = 0
        self._acked_event_ids: set[UUID] = set()
        self._max_attempts = (
            max_message_attempts() if max_attempts is None else max_attempts
        )

    async def run(self) -> None:
        """Consume forever, one message at a time (D-47a: the factory sets max_poll_records=1)."""
        log.info("state_machine_loop_started")
        try:
            while True:
                msg = await self.consumer.getone()
                await self.handle_message(msg)
        finally:
            # A cancelled run() (SIGTERM) must not leave a timer holding a reference to a
            # consumer that is about to be stopped.
            for handle in self._resume_handles.values():
                handle.cancel()
            self._resume_handles.clear()

    async def handle_message(self, msg: Any) -> None:
        """
        Route one message by topic, then commit its offset — but only if it is safe to.

        POISON and TRANSIENT are not the same failure and must not get the same treatment. A
        payload that cannot be decoded will never decode, so committing it is the only way to
        keep it from stalling the partition forever. A Redis timeout, a broker outage or a
        producer failure is the opposite: the message is fine and the world is not, so
        committing it would silently drop an observation that a later attempt would have
        handled. For a polls.completed error/timeout that means losing the UNKNOWN mark
        permanently, along with any Close that had not run yet.

        A transient failure therefore REWINDS the partition (`_retry_later`). Merely skipping
        the commit is not enough and never was: the consumer POSITION has already advanced, so
        `run()` pulls the next message and its own `commit(offset + 1)` sets the group
        watermark strictly past the failed offset. The failed message ends up below the
        watermark and is never redelivered — the exact behaviour the no-commit branch was
        added to prevent. `tests/unit/test_offset_commit_policy.py` drives three messages
        through `run()` and asserts no committed offset ever passes a failed one.

        The rewind is BOUNDED (CR-01, iteration 3). "Everything that is not a
        `ValidationError`/`ParseError`" is not a synonym for "transient": it includes
        `AttributeError`, `KeyError`, an `UnknownTopicOrPartitionError` after someone deletes
        a topic, a Redis `WRONGTYPE`, and every programming bug that will ever be introduced
        into `engine.py` or `store.py`. None of those will ever succeed on retry, so an
        unbounded rewind converted iteration 2's silent data loss into a permanently stalled
        partition — for a single-partition topic, a total pipeline outage whose only symptom
        is two log lines at 0.5 Hz forever. Stalling the partition is not the safer failure:
        it drops every LATER observation too. After `_max_attempts` the message is treated as
        poison, published to the dead-letter topic, and committed past.
        """
        key = (msg.topic, msg.partition, msg.offset)
        if key != self._attempt_key:
            # A different message: whatever came before is committed or dead-lettered, so its
            # accounting is finished. Replacing rather than accumulating is what keeps this
            # bounded — only the head of a partition can be under retry.
            self._attempt_key = key
            self._attempts = 0
            self._acked_event_ids.clear()
        try:
            if msg.topic == RAW_TOPIC:
                await self._handle_raw(msg)
            elif msg.topic == COMPLETED_TOPIC:
                await self._handle_completed(msg)
            else:
                log.warning("unrouted_topic", topic=msg.topic, offset=msg.offset)
        except (ValidationError, ParseError) as exc:
            # Poison: undecodable now and undecodable on every redelivery. Log, drop, commit.
            #
            # `ParseError` is defence in depth, not a live route: `parse_raw` is the only
            # source and `_handle_raw` already catches it into the D-39 UNKNOWN path, while
            # `_handle_completed` does not parse at all. It stays in the tuple because the
            # alternative branch is now much worse than a dead one: since CR-01 the transient
            # arm REWINDS the partition, so a `ParseError` that ever did reach here would be
            # retried forever against a payload that can never decode.
            self._discard()
            log.error(
                "message_poison",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                # Field paths and error types only — never `str(exc)`, which embeds the
                # offending input value and therefore the payload (T-02-03).
                error=_failure_shape(exc),
            )
        except Exception as exc:  # noqa: BLE001 — presumed transient infrastructure failure
            self._discard()
            self._attempts += 1
            log.error(
                "message_handling_failed",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                error=_failure_shape(exc),
                attempt=self._attempts,
                max_attempts=self._max_attempts,
            )
            if self._attempts >= self._max_attempts:
                # Not transient after all. Escalate to poison rather than retry forever.
                log.error(
                    "message_retries_exhausted",
                    topic=msg.topic,
                    partition=msg.partition,
                    offset=msg.offset,
                    attempts=self._attempts,
                    error=_failure_shape(exc),
                    metric=METRIC_MESSAGES_DEAD_LETTERED,
                )
                await self._dead_letter(msg, exc)
                await self._commit(msg)
                return
            # Deliberately NOT committed, AND rewound: not committing on its own leaves the
            # consumer position past this message, so the next success would commit over it.
            self._retry_later(msg)
            return
        await self._commit(msg)

    async def _dead_letter(self, msg: Any, exc: BaseException) -> None:
        """
        Preserve a message that exhausted its retries, then let the caller commit past it.

        The value is the ORIGINAL bytes. A dead-letter record that has been redacted down to a
        failure shape is an audit trail nobody can replay from, and unlike a log line this is a
        Kafka topic with the same trust boundary as `availability.raw` itself — the payload is
        already there, this is a copy that outlives the raw topic's 24-hour retention. The
        diagnostic context (where it came from, how many attempts, what failed) goes in the
        headers, where the failure is rendered as a SHAPE because headers do end up in logs.

        Best effort, and deliberately so: the caller commits past this message whether or not
        the publish succeeds. A DLQ that is itself unavailable must not be able to re-create
        the stall this whole mechanism exists to end. If `availability.dlq` is missing the
        publish raises `UnknownTopicOrPartitionError`, which is caught here and logged — the
        startup guard in `main.REQUIRED_TOPICS` is what makes that case a misconfiguration
        rather than a routine one.
        """
        try:
            await self.producer.send_and_wait(
                DLQ_TOPIC,
                value=msg.value,
                key=f"{msg.topic}:{msg.partition}",
                headers=[
                    ("original_topic", msg.topic.encode()),
                    ("original_partition", str(msg.partition).encode()),
                    ("original_offset", str(msg.offset).encode()),
                    ("attempts", str(self._attempts).encode()),
                    ("error", str(_failure_shape(exc)).encode()),
                ],
            )
        except Exception as dlq_exc:  # noqa: BLE001 — a dead DLQ must not re-create the stall
            log.error(
                "dead_letter_publish_failed",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                error=_failure_shape(dlq_exc),
            )
            return
        log.error(
            "message_dead_lettered",
            topic=msg.topic,
            partition=msg.partition,
            offset=msg.offset,
            dlq_topic=DLQ_TOPIC,
            attempts=self._attempts,
        )

    def _retry_later(self, msg: Any) -> None:
        """
        Rewind this partition to the failed offset and pause it for a bounded backoff.

        `seek` is what actually keeps the offset where the transient branch claims to leave
        it: it makes THIS message the next one `getone()` returns, so the group watermark can
        never move past it. `pause` + a `call_later` `resume` is the backoff — without it a
        dead Redis turns redelivery into a hot loop that hammers the dependency and floods
        the log. Other assigned partitions keep flowing while this one is parked, so the
        stall is scoped to the partition that actually failed.

        A rebalance between the failure and the rewind unassigns the partition, and both
        `seek` and `pause` then raise `IllegalStateError` (a `KafkaError`). That is benign:
        the uncommitted offset is redelivered to whoever owns the partition now, which is the
        same outcome by a different route.

        The catch is `Exception` and not `(KafkaError, ValueError)` for the same reason as
        `_resume_partition` (WR-06): aiokafka's `SubscriptionState` asserts its way through a
        stop/rebalance race, and an `AssertionError` escaping here escapes `handle_message`
        too — it is raised from the transient EXCEPT block, so nothing above catches it and
        `run()` terminates. Failing to rewind is a bad outcome; killing the consumer because
        the rewind failed is a worse one.
        """
        topic_partition = TopicPartition(msg.topic, msg.partition)
        try:
            self.consumer.seek(topic_partition, msg.offset)
            self.consumer.pause(topic_partition)
        except Exception as exc:  # noqa: BLE001 — raised from an except block; nothing above catches
            log.warning(
                "transient_retry_rewind_failed",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                error=_failure_shape(exc),
            )
            return

        pending = self._resume_handles.pop(topic_partition, None)
        if pending is not None:
            pending.cancel()
        self._resume_handles[topic_partition] = asyncio.get_running_loop().call_later(
            TRANSIENT_RETRY_BACKOFF_SECONDS, self._resume_partition, topic_partition
        )
        log.warning(
            "message_retry_scheduled",
            topic=msg.topic,
            partition=msg.partition,
            offset=msg.offset,
            backoff_seconds=TRANSIENT_RETRY_BACKOFF_SECONDS,
        )

    def _resume_partition(self, topic_partition: TopicPartition, attempt: int = 1) -> None:
        """
        Un-pause a partition parked by `_retry_later`; a lost assignment is a no-op.

        This runs as a `call_later` callback, which means it executes outside any task and
        outside `handle_message`'s handlers: there is no caller for an exception to propagate
        to. Anything not caught here goes to the loop's DEFAULT exception handler, which
        writes to the `asyncio` logger — not through the structlog JSON pipeline — and by then
        the handle has already been popped from `_resume_handles`, so nothing would ever try
        to resume this partition again. The service stays up, `getone()` blocks forever, and
        the only trace is a line the log pipeline does not format. That is why the catch is
        broad (WR-06): `SubscriptionState._assigned_state` asserts on `self._subscription is
        not None` and on the assignment, both reachable during a stop/rebalance race, and an
        `AssertionError` is not a `KafkaError`.

        A failed resume is RE-SCHEDULED rather than dropped, so a transient race does not
        park the partition permanently — but only a bounded number of times, because an
        unbounded self-rescheduling timer against a consumer that is genuinely gone is a log
        flood that never ends. On exhaustion it says so, loudly and once.
        """
        self._resume_handles.pop(topic_partition, None)
        try:
            self.consumer.resume(topic_partition)
        except KafkaError:
            # Reassigned elsewhere while we were paused; nothing left to resume.
            return
        except Exception as exc:  # noqa: BLE001 — a callback has no caller to raise to
            log.error(
                "partition_resume_failed",
                topic=topic_partition.topic,
                partition=topic_partition.partition,
                attempt=attempt,
                max_attempts=MAX_RESUME_ATTEMPTS,
                error=_failure_shape(exc),
            )
            if attempt >= MAX_RESUME_ATTEMPTS:
                log.error(
                    "partition_resume_abandoned",
                    topic=topic_partition.topic,
                    partition=topic_partition.partition,
                    attempts=attempt,
                    metric=METRIC_PARTITION_RESUME_ABANDONED,
                )
                return
            self._resume_handles[topic_partition] = asyncio.get_running_loop().call_later(
                TRANSIENT_RETRY_BACKOFF_SECONDS,
                self._resume_partition,
                topic_partition,
                attempt + 1,
            )

    async def _handle_raw(self, msg: Any) -> None:
        raw = AvailabilityRaw.model_validate_json(msg.value)
        try:
            parsed = parse_raw(raw)
        except ParseError as exc:
            # D-39/D-37: an unparseable payload or an unregistered source means UNKNOWN. No slot
            # is removed, no slot moves toward UNAVAILABLE, and nothing is emitted.
            await self.engine.mark_unknown(raw.restaurant_id, raw.polled_at_epoch_ms)
            await self._flush()
            log.warning(
                "poll_unparseable",
                restaurant_id=raw.restaurant_id,
                poll_id=str(raw.poll_id),
                # The ParseError message is already payload-free by construction
                # (parsers/errors.py names the defect and the offending TYPE, never the
                # value); `safe_error` is belt-and-braces for anything a future parser
                # interpolates, and names the exception class alongside the reason.
                reason=safe_error(exc),
            )
            return

        decisions = await self.engine.process(parsed)
        if self.engine.last_close_count > MASS_CLOSURE_AUDIT_THRESHOLD:
            # Pitfall 10: a sanitised or soft-banned 200 OK closes everything at once. Leave an
            # auditable record so the Phase 3 canary can tell that apart from a full restaurant.
            log.warning(
                "mass_closure_detected",
                restaurant_id=parsed.restaurant_id,
                poll_id=str(parsed.poll_id),
                count=self.engine.last_close_count,
            )
        if self.engine.last_collision_count:
            # Two observed slots landed on one `(time_slot, seat_type)`. The resolution is
            # deterministic (last parsed wins) and does not change the diff, but it is the
            # payload-shape surprise the [ASSUMED] OpenTable schema warns about and it would
            # otherwise vanish without a trace.
            log.warning(
                "slot_key_collisions",
                restaurant_id=parsed.restaurant_id,
                poll_id=str(parsed.poll_id),
                count=self.engine.last_collision_count,
            )
        for decision in decisions:
            await self._apply(decision, parsed.polled_at_epoch_ms)
        await self._flush()

    async def _handle_completed(self, msg: Any) -> None:
        completed = PollCompleted.model_validate_json(msg.value)
        if completed.status not in ("error", "timeout"):
            # A success carries no new information here: the matching availability.raw message
            # is what advances state (D-47).
            return
        await self.engine.mark_unknown(completed.restaurant_id, completed.polled_at_epoch_ms)
        await self._flush()
        log.info(
            "restaurant_marked_unknown",
            restaurant_id=completed.restaurant_id,
            poll_id=str(completed.poll_id),
            status=completed.status,
        )

    async def _apply(self, decision: Decision, now_ms: int) -> None:
        if isinstance(decision, Expedite):
            await self._apply_expedite(decision, now_ms)
        elif isinstance(decision, Emit):
            await self._apply_emit(decision)
        else:
            await self._apply_close(decision)

    async def _apply_expedite(self, decision: Expedite, now_ms: int) -> None:
        """
        Pull the restaurant's next poll forward so a PENDING slot gets confirmed (D-43).

        `now_ms` is the POLL's timestamp, not the wall clock, so the re-verification lands 8 s
        after the sighting itself and replay reproduces the same score.
        """
        outcome = await self.scheduler.expedite(job(decision.source, decision.restaurant_id), now_ms)
        log.info("poll_expedited", restaurant_id=decision.restaurant_id, outcome=outcome)

    async def _apply_emit(self, decision: Emit) -> None:
        """One confirmed emission, in the D-46 order: claim, send, persist, record."""
        event = decision.event
        # The claim key carries the SLOT KEY as well as the token (D-36, D-46 as amended by
        # CR-01): OpenTable gives every seating type of one timeslot the same booking token,
        # so a token-only key would make two distinct slots claim the same key and the second
        # confirmed opening would be dropped, never retried.
        claim_key = event_idempotency_key(
            event.restaurant_id,
            decision.date,
            decision.party_size,
            decision.slot_key,
            decision.idempotency_token,
        )
        claimed = await set_nx_ex(self.r, claim_key, "1", EVENT_IDEMPOTENCY_TTL_SECONDS)
        _maybe_crash("nx_claim")
        if not claimed and not await self._crashed_mid_emit(decision):
            log.info(
                "emit_skipped_duplicate",
                event_id=str(event.event_id),
                restaurant_id=event.restaurant_id,
            )
            return

        if event.event_id in self._acked_event_ids:
            # This exact event was already ACKED BY THE BROKER during an earlier attempt at
            # this same offset, and the attempt then failed further down (CR-01, iteration 3).
            # Without this check every retry re-sent it: `set_nx_ex` returns False,
            # `_crashed_mid_emit` reads a durable record still PENDING (because `_discard()`
            # threw the buffered write away) and answers True, and the event goes out again on
            # every single retry — ~43k duplicate events a day against a permanent failure in
            # `_flush_slot`. Phase 4's Layer-2 key dedupes the notification, but nothing
            # dedupes the topic, the insert attempt or the log stream.
            #
            # The remaining steps still run. Both are idempotent (ON CONFLICT DO NOTHING, and
            # an HSET of the same record), and skipping them would leave the slot PENDING with
            # its event already on the wire — the one state the emit ordering exists to avoid.
            log.info(
                "emit_skipped_already_acked",
                event_id=str(event.event_id),
                restaurant_id=event.restaurant_id,
            )
        else:
            # send_and_wait, never a bare send: the shared producer factory sets a batching
            # window, so a bare send can return before the broker acks and the offset commit
            # would overtake the record (research Pattern 4).
            await self.producer.send_and_wait(
                EVENTS_TOPIC,
                value=event.to_bytes(),
                key=job(event.source, event.restaurant_id),
            )
            # Recorded only AFTER the ack. Recording before would suppress a re-send of an
            # event the broker never actually took.
            self._acked_event_ids.add(event.event_id)
            _maybe_crash("kafka_send")
            log.info(
                "availability_event_published",
                event_id=str(event.event_id),
                restaurant_id=event.restaurant_id,
                date=event.date,
                party_size=event.party_size,
            )

        # The analytics row goes in BEFORE the state write, not after. The insert is
        # idempotent (ON CONFLICT (event_id, "time") DO NOTHING), so attempting it twice is
        # harmless — but attempting it ZERO times is not recoverable. With the state write
        # first, a crash in between left the slot durably AVAILABLE and the event on the wire
        # with no DB row: the redelivered poll produces no Emit, insert_event is never
        # retried, and the later Close UPDATE silently matches zero rows. Best-effort
        # persistence (D-48) covers a FAILED insert, not a never-attempted one.
        await insert_event(event)

        # Flush ONLY this slot (D-46 step 3, CR-02). A message-wide flush here would make
        # every other slot in the poll durably AVAILABLE before its own send_and_wait had
        # happened, and a crash in that window would lose those openings for good: the next
        # diff reads AVAILABLE, takes the refresh path, and never emits again.
        await self._flush_slot(decision)
        _maybe_crash("state_write")

    async def _crashed_mid_emit(self, decision: Emit) -> bool:
        """
        The claim was already taken: decide between the two crash paths D-46 distinguishes.

        A durable record already AVAILABLE means a previous attempt ran to completion, so this
        is a redelivery and the right move is to skip — that is the chaos-test path, and it is
        what makes duplicates impossible. A record still PENDING (or gone) means the process
        died between the claim and the state write, so re-send the SAME deterministic event id
        and let the downstream dedupe it: losing a real opening is worse than one duplicate
        carrying an identical id.
        """
        records = await self.store.get_slots(
            decision.event.restaurant_id, decision.date, decision.party_size
        )
        record = records.get(decision.slot_key)
        return record is None or record.state is not SlotState.AVAILABLE

    async def _apply_close(self, decision: Close) -> None:
        """A confirmed slot vanished: close its row. Closures are database-only (D-45)."""
        await close_event(
            event_id=decision.event_id,
            confirmed_at=epoch_ms_to_utc(decision.confirmed_at_epoch_ms),
            last_seen_at=epoch_ms_to_utc(decision.last_seen_at_epoch_ms),
        )
        log.info(
            "availability_event_closed",
            event_id=str(decision.event_id),
            restaurant_id=decision.restaurant_id,
        )

    async def _flush(self) -> None:
        """Make the engine's buffered state writes durable (no-op without a buffer)."""
        if self.buffer is not None:
            await self.buffer.flush()

    async def _flush_slot(self, decision: Emit) -> None:
        """Make ONE emitted slot's state write durable, leaving the rest of the poll buffered."""
        if self.buffer is not None:
            await self.buffer.flush_slot(
                decision.event.restaurant_id,
                decision.date,
                decision.party_size,
                decision.slot_key,
            )

    def _discard(self) -> None:
        """Drop a failed message's partial writes rather than half-applying them."""
        if self.buffer is not None:
            self.buffer.discard()

    async def _commit(self, msg: Any) -> None:
        """
        Commit the offset of the NEXT record, and only after every side effect (D-46).

        A group rebalance mid-message makes this raise; log it and let redelivery happen — the
        claim plus the AVAILABLE record make reprocessing a no-op (research Pitfall 4).

        `KafkaError` and not `CommitFailedError`: aiokafka documents TWO rebalance outcomes for
        `commit` — `CommitFailedError` (group membership changed) and `IllegalStateError`
        ("if partitions not assigned") — plus a plain `KafkaError` for broker-side failures.
        `IllegalStateError` is a SIBLING of `CommitFailedError` under `KafkaError`, not a
        subclass, so naming only the latter left the other two uncaught. This method is called
        outside `handle_message`'s try block, so an uncaught commit error propagates through
        `run()` and terminates the service — a rebalance would kill the consumer outright.
        """
        topic_partition = TopicPartition(msg.topic, msg.partition)
        try:
            await self.consumer.commit({topic_partition: msg.offset + 1})
        except KafkaError as exc:
            log.warning(
                "offset_commit_failed",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                # `_failure_shape`, not `str(exc)` (WR-07). A KafkaError carries no booking
                # token, so the impact today is low — but `_failure_shape` exists precisely so
                # that no branch reaches for `str(exc)` again, and this was the last one that
                # did. Broker error strings routinely carry hostnames and ports, and once SASL
                # is configured in a later phase they carry principal names too. The value of
                # the discipline is that it is unconditional: a future reader copying the
                # nearest example must not find the wrong one.
                error=_failure_shape(exc),
            )
        _maybe_crash("commit")
