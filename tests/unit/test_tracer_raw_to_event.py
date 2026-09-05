"""
Tracer: two raw OpenTable polls 9000 ms apart become one deterministic AvailabilityEvent.

Runs entirely in-process — no Redis, no Kafka, no Postgres, no network, no wall clock
(D-41, D-44, D-45, D-49; STATE-02, STATE-04).
"""
from __future__ import annotations

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.state_machine.engine import DiffEngine
from services.state_machine.models import Emit, Expedite
from services.state_machine.parsers import parse_raw
from services.state_machine.store import MemoryStateStore
from shared.events import AvailabilityEvent
from tests.unit.factories import make_raw

RID = 42
DATE = "2026-05-01"
FIRST_POLL_MS = 1_788_000_000_000
CONFIRM_POLL_MS = 1_788_000_009_000  # 9000 ms later, above the 8000 ms confirm delay
CONFIRM_DELAY_MS = 8_000


def _raw(polled_at_epoch_ms: int):  # type: ignore[no-untyped-def]
    return make_raw(
        rid=RID,
        dates=[DATE],
        parties=[2, 4],
        response=OPENTABLE_SUCCESS_RESPONSE,
        polled_at_epoch_ms=polled_at_epoch_ms,
    )


async def _run_two_polls() -> tuple[list[object], list[object]]:
    engine = DiffEngine(MemoryStateStore(), confirm_delay_ms=CONFIRM_DELAY_MS)
    first = await engine.process(parse_raw(_raw(FIRST_POLL_MS)))
    second = await engine.process(parse_raw(_raw(CONFIRM_POLL_MS)))
    return list(first), list(second)


def _bar_event(decisions: list[object]) -> AvailabilityEvent:
    emits = [d for d in decisions if isinstance(d, Emit)]
    bar = [e for e in emits if e.event.seat_type == "bar"]
    assert len(bar) == 1
    return bar[0].event


async def test_first_poll_expedites_and_emits_nothing() -> None:
    """A first sighting yields exactly one Expedite (one per restaurant) and zero events."""
    first, _second = await _run_two_polls()
    assert [d for d in first if isinstance(d, Expedite)] == [Expedite(source="opentable", restaurant_id=RID)]
    assert [d for d in first if isinstance(d, Emit)] == []


async def test_second_poll_confirms_and_emits_without_expediting() -> None:
    """The confirming poll emits one event per observed slot and expedites nothing further."""
    _first, second = await _run_two_polls()
    assert [d for d in second if isinstance(d, Expedite)] == []
    emits = [d for d in second if isinstance(d, Emit)]
    # OPENTABLE_SUCCESS_RESPONSE carries seatingTypes ["bar", "standard"] -> two distinct slots.
    assert len(emits) == 2
    assert [e.event.seat_type for e in emits] == ["bar", "standard"]  # sorted by slot_key


async def test_confirmed_event_field_values() -> None:
    """Every field of the confirmed event comes from the poll payload, never the clock."""
    _first, second = await _run_two_polls()
    event = _bar_event(second)
    assert event.event_type == "slot_opened"
    assert event.source == "opentable"
    assert event.restaurant_id == RID
    assert event.date == DATE
    assert event.time_slot == "19:00"
    assert event.party_size == 2
    assert event.seat_type == "bar"
    assert event.booking_token == "abc123-reservation-token"
    assert event.first_seen_at_epoch_ms == FIRST_POLL_MS
    assert event.confirmed_at_epoch_ms == CONFIRM_POLL_MS
    assert event.produced_at_epoch_ms == CONFIRM_POLL_MS
    assert event.confirming_poll_id == _raw(CONFIRM_POLL_MS).poll_id


async def test_wire_bytes_follow_declaration_order_not_input_order() -> None:
    """Declaration order is wire order: a reversed input dict yields identical bytes."""
    _first, second = await _run_two_polls()
    event = _bar_event(second)
    reversed_fields = dict(reversed(list(event.model_dump().items())))
    rebuilt = AvailabilityEvent(**reversed_fields)
    assert rebuilt.to_bytes() == event.to_bytes()


async def test_replaying_the_same_polls_is_byte_identical() -> None:
    """A fresh MemoryStateStore replaying the same two messages reproduces the same bytes."""
    _first_a, second_a = await _run_two_polls()
    _first_b, second_b = await _run_two_polls()
    event_a = _bar_event(second_a)
    event_b = _bar_event(second_b)
    assert event_a.event_id == event_b.event_id
    assert event_a.to_bytes() == event_b.to_bytes()


async def test_emit_carries_an_idempotency_token() -> None:
    """Emit.idempotency_token is the booking token when present (D-46)."""
    _first, second = await _run_two_polls()
    emits = [d for d in second if isinstance(d, Emit)]
    assert {e.idempotency_token for e in emits} == {"abc123-reservation-token"}
