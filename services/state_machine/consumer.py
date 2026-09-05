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
Named symbols: StateMachineConsumer, RAW_TOPIC, COMPLETED_TOPIC, EVENTS_TOPIC
"""
from __future__ import annotations

import os
import signal
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.errors import KafkaError
from pydantic import ValidationError
from redis.asyncio import Redis

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
from shared.telemetry import get_logger

log = get_logger(__name__)

# Named-Symbol Kafka topics (D-27, D-45).
RAW_TOPIC = "availability.raw"
COMPLETED_TOPIC = "polls.completed"
EVENTS_TOPIC = "availability.events"


def _crash_after() -> str | None:
    """
    TEST ONLY (D-51). The stage after which this process kills itself.

    Read lazily from the environment so the chaos test controls it purely by launching a
    subprocess. `main.run()` refuses to start when it is set and ENV is prod (T-02-04).
    """
    return os.getenv("MISE_CRASH_AFTER")


def _maybe_crash(stage: str) -> None:
    """
    TEST-ONLY SIGKILL hook; a no-op unless MISE_CRASH_AFTER names this stage.

    Stages, each fired immediately AFTER the named step completes: `nx_claim`, `kafka_send`,
    `state_write`, `commit`. SIGKILL and never SIGTERM: a catchable signal would let the
    consumer shut down cleanly and commit its offset, which is exactly the behaviour the chaos
    test has to prevent.
    """
    if _crash_after() == stage:
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

    async def run(self) -> None:
        """Consume forever, one message at a time (D-47a: the factory sets max_poll_records=1)."""
        log.info("state_machine_loop_started")
        while True:
            msg = await self.consumer.getone()
            await self.handle_message(msg)

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
        """
        try:
            if msg.topic == RAW_TOPIC:
                await self._handle_raw(msg)
            elif msg.topic == COMPLETED_TOPIC:
                await self._handle_completed(msg)
            else:
                log.warning("unrouted_topic", topic=msg.topic, offset=msg.offset)
        except (ValidationError, ParseError) as exc:
            # Poison: undecodable now and undecodable on every redelivery. Log, drop, commit.
            self._discard()
            log.error(
                "message_poison",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                error=str(exc),
            )
        except Exception as exc:  # noqa: BLE001 — transient infrastructure failure
            self._discard()
            log.error(
                "message_handling_failed",
                topic=msg.topic,
                partition=msg.partition,
                offset=msg.offset,
                error=str(exc),
            )
            # Deliberately NOT committed: leave the offset where it is so a restart
            # reprocesses this message instead of skipping it.
            return
        await self._commit(msg)

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
                reason=str(exc),
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
        """One confirmed emission, executed in the D-46 order: claim, send, record, persist."""
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

        # send_and_wait, never a bare send: the shared producer factory sets a batching window,
        # so a bare send can return before the broker acks and the offset commit would overtake
        # the record (research Pattern 4).
        await self.producer.send_and_wait(
            EVENTS_TOPIC,
            value=event.to_bytes(),
            key=job(event.source, event.restaurant_id),
        )
        _maybe_crash("kafka_send")
        log.info(
            "availability_event_published",
            event_id=str(event.event_id),
            restaurant_id=event.restaurant_id,
            date=event.date,
            party_size=event.party_size,
        )

        # Flush ONLY this slot (D-46 step 3, CR-02). A message-wide flush here would make
        # every other slot in the poll durably AVAILABLE before its own send_and_wait had
        # happened, and a crash in that window would lose those openings for good: the next
        # diff reads AVAILABLE, takes the refresh path, and never emits again.
        await self._flush_slot(decision)
        _maybe_crash("state_write")

        await insert_event(event)

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
                error=str(exc),
            )
        _maybe_crash("commit")
