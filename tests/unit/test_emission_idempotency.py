"""Unit: STATE-04 — the three Layer-1 claim outcomes, with no broker and no Redis (D-46).

The claim is one atomic ``SET key 1 NX EX 1200``. What the shell does when it FAILS is the
whole crash-safety argument, and it is a branch that only fires after a real crash — so it is
pinned here with mocks rather than left to the chaos test alone:

* claim taken, record already AVAILABLE  -> a completed prior attempt: send nothing.
* claim taken, record still PENDING       -> died between claim and state write: re-send the
  SAME deterministic event id, because losing a real opening is worse than one duplicate that
  downstream dedupes by id.
* claim won                               -> send exactly once.
"""
from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from services.state_machine.consumer import StateMachineConsumer
from services.state_machine.engine import DiffEngine
from services.state_machine.models import Emit, SlotRecord, SlotState
from services.state_machine.store import MemoryStateStore
from shared.events import AvailabilityEvent, make_event_id
from shared.redis_keys import EVENT_IDEMPOTENCY_TTL_SECONDS, event_idempotency_key

RID = 42
DATE = "2026-05-01"
PARTY = 2
SLOT_KEY = "19:00|bar"
TOKEN = "abc123-reservation-token"
FIRST_POLL_ID = "6f1b1c62-0000-4000-8000-000000000001"


def _emit() -> Emit:
    event = AvailabilityEvent(
        event_id=make_event_id("opentable", RID, DATE, PARTY, SLOT_KEY, FIRST_POLL_ID),
        event_type="slot_opened",
        source="opentable",
        restaurant_id=RID,
        date=DATE,
        time_slot="19:00",
        party_size=PARTY,
        seat_type="bar",
        booking_token=TOKEN,
        first_seen_at_epoch_ms=1_800_000_000_000,
        confirmed_at_epoch_ms=1_800_000_009_000,
        produced_at_epoch_ms=1_800_000_009_000,
        confirming_poll_id=UUID(int=9),
    )
    return Emit(
        event=event, idempotency_token=TOKEN, date=DATE, party_size=PARTY, slot_key=SLOT_KEY
    )


def _record(state: SlotState) -> SlotRecord:
    return SlotRecord(
        state=state,
        token=TOKEN,
        first_seen_ms=1_800_000_000_000,
        first_poll_id=FIRST_POLL_ID,
        last_seen_ms=1_800_000_009_000,
    )


def _shell(*, claim_succeeds: bool, stored: SlotRecord | None, monkeypatch) -> tuple[
    StateMachineConsumer, AsyncMock, AsyncMock
]:
    """A consumer whose Redis, producer and durable store are all mocks."""
    redis_client = AsyncMock()
    # redis-py returns True when NX sets the key and None when it does not.
    redis_client.set.return_value = True if claim_succeeds else None

    producer = AsyncMock()
    store = AsyncMock()
    store.get_slots.return_value = {} if stored is None else {SLOT_KEY: stored}

    # Keep the unit tier hermetic: the analytics write is exercised against a real hypertable
    # in tests/integration/test_availability_events_persistence.py.
    inserted = AsyncMock()
    monkeypatch.setattr("services.state_machine.consumer.insert_event", inserted)

    shell = StateMachineConsumer(
        consumer=AsyncMock(),
        producer=producer,
        redis_client=redis_client,
        scheduler=AsyncMock(),
        engine=DiffEngine(MemoryStateStore(), confirm_delay_ms=8_000),
        store=store,
    )
    return shell, producer, redis_client


@pytest.mark.asyncio
async def test_a_won_claim_sends_exactly_once(monkeypatch):
    shell, producer, _ = _shell(claim_succeeds=True, stored=None, monkeypatch=monkeypatch)

    await shell._apply_emit(_emit())

    assert producer.send_and_wait.await_count == 1


@pytest.mark.asyncio
async def test_the_claim_is_one_atomic_set_nx_ex_call(monkeypatch):
    """Never a two-command SETNX + EXPIRE, and never an inline key string (D-42, D-46)."""
    shell, _, redis_client = _shell(claim_succeeds=True, stored=None, monkeypatch=monkeypatch)

    await shell._apply_emit(_emit())

    redis_client.set.assert_called_once_with(
        event_idempotency_key(RID, DATE, PARTY, SLOT_KEY, TOKEN),
        "1",
        nx=True,
        ex=EVENT_IDEMPOTENCY_TTL_SECONDS,
    )
    assert EVENT_IDEMPOTENCY_TTL_SECONDS == 1_200


@pytest.mark.asyncio
async def test_a_taken_claim_with_an_available_record_sends_nothing(monkeypatch):
    """The chaos path: a prior attempt completed, so this redelivery is a no-op."""
    shell, producer, _ = _shell(
        claim_succeeds=False, stored=_record(SlotState.AVAILABLE), monkeypatch=monkeypatch
    )

    await shell._apply_emit(_emit())

    assert producer.send_and_wait.await_count == 0


@pytest.mark.asyncio
async def test_a_taken_claim_with_a_pending_record_resends_the_same_event_id(monkeypatch):
    """Crashed between claim and state write: re-send, identical id, deduped downstream."""
    emit = _emit()
    shell, producer, _ = _shell(
        claim_succeeds=False, stored=_record(SlotState.PENDING), monkeypatch=monkeypatch
    )

    await shell._apply_emit(emit)

    assert producer.send_and_wait.await_count == 1
    sent = producer.send_and_wait.await_args
    assert sent.args[0] == "availability.events"
    assert sent.kwargs["key"] == f"opentable:{RID}"
    resent = AvailabilityEvent.model_validate_json(sent.kwargs["value"])
    assert resent.event_id == emit.event.event_id


@pytest.mark.asyncio
async def test_a_taken_claim_with_no_record_at_all_resends(monkeypatch):
    """A vanished record (TTL expiry, flushed Redis) is treated as the crash case, not a skip."""
    shell, producer, _ = _shell(claim_succeeds=False, stored=None, monkeypatch=monkeypatch)

    await shell._apply_emit(_emit())

    assert producer.send_and_wait.await_count == 1
