"""
The full D-41 transition table, driven entirely by explicit poll timestamps.

No test here waits on real time, uses freezegun, or touches Redis: every timing fact is a
polled_at_epoch_ms value passed to the factory (D-44, D-49).
"""
from __future__ import annotations

from services.state_machine.engine import MASS_CLOSURE_AUDIT_THRESHOLD, DiffEngine
from services.state_machine.models import Close, Emit, Expedite, SlotState
from services.state_machine.store import MemoryStateStore
from tests.unit.factories import make_parsed, make_slot

RID = 42
DATE = "2026-05-01"
PARTY = 2
COVERAGE = {(DATE, PARTY)}
T0 = 1_788_000_000_000
CONFIRM_DELAY_MS = 8_000


def _engine() -> tuple[DiffEngine, MemoryStateStore]:
    store = MemoryStateStore()
    return DiffEngine(store, confirm_delay_ms=CONFIRM_DELAY_MS), store


def _slot(time_slot: str = "19:00", seat_type: str | None = "bar", token: str | None = "tok-1"):  # type: ignore[no-untyped-def]
    return make_slot(date=DATE, party_size=PARTY, time_slot=time_slot, seat_type=seat_type, booking_token=token)


async def test_pending_slot_absent_on_next_covered_poll_is_dropped_with_no_event() -> None:
    """The false-positive guard: a one-poll ghost never becomes an event (ROADMAP SC1)."""
    engine, store = _engine()
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=[_slot()]))
    decisions = await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=COVERAGE))
    assert decisions == []
    assert await store.get_slots(RID, DATE, PARTY) == {}


async def test_second_sighting_below_confirm_delay_does_not_confirm() -> None:
    """3000 ms apart is not a confirmation; the slot stays PENDING and is expedited again (D-44)."""
    engine, store = _engine()
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=[_slot()]))
    decisions = await engine.process(
        make_parsed(rid=RID, polled_at_epoch_ms=T0 + 3_000, coverage=COVERAGE, slots=[_slot()])
    )
    assert [d for d in decisions if isinstance(d, Emit)] == []
    assert [d for d in decisions if isinstance(d, Expedite)] == [Expedite(source="opentable", restaurant_id=RID)]
    record = (await store.get_slots(RID, DATE, PARTY))["19:00|bar"]
    assert record.state is SlotState.PENDING
    assert record.first_seen_ms == T0
    assert record.last_seen_ms == T0 + 3_000


async def test_available_slot_absent_on_covered_poll_closes_once() -> None:
    """AVAILABLE to UNAVAILABLE yields exactly one Close carrying the original event id."""
    engine, store = _engine()
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=[_slot()]))
    emits = [
        d
        for d in await engine.process(
            make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=COVERAGE, slots=[_slot()])
        )
        if isinstance(d, Emit)
    ]
    event = emits[0].event

    decisions = await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 99_000, coverage=COVERAGE))
    closes = [d for d in decisions if isinstance(d, Close)]
    assert len(closes) == 1
    assert closes[0] == Close(
        event_id=event.event_id,
        restaurant_id=RID,
        date=DATE,
        party_size=PARTY,
        slot_key="19:00|bar",
        confirmed_at_epoch_ms=T0 + 9_000,
        last_seen_at_epoch_ms=T0 + 99_000,
    )
    assert (await store.get_slots(RID, DATE, PARTY))["19:00|bar"].state is SlotState.UNAVAILABLE


async def test_closed_slot_is_a_no_op_on_further_polls() -> None:
    """A slot already UNAVAILABLE never closes twice."""
    engine, _store = _engine()
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=[_slot()]))
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=COVERAGE, slots=[_slot()]))
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 99_000, coverage=COVERAGE))
    assert await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 199_000, coverage=COVERAGE)) == []


async def test_reopened_slot_starts_a_new_cycle_with_a_new_event_id() -> None:
    """A re-open is a distinct event because first_poll_id changes (D-41, D-45)."""
    engine, _store = _engine()
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=[_slot()]))
    first = [
        d
        for d in await engine.process(
            make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=COVERAGE, slots=[_slot()])
        )
        if isinstance(d, Emit)
    ][0].event
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 99_000, coverage=COVERAGE))

    reopen = await engine.process(
        make_parsed(rid=RID, polled_at_epoch_ms=T0 + 199_000, coverage=COVERAGE, slots=[_slot()])
    )
    assert [d for d in reopen if isinstance(d, Expedite)] == [Expedite(source="opentable", restaurant_id=RID)]
    second = [
        d
        for d in await engine.process(
            make_parsed(rid=RID, polled_at_epoch_ms=T0 + 209_000, coverage=COVERAGE, slots=[_slot()])
        )
        if isinstance(d, Emit)
    ][0].event
    assert second.event_id != first.event_id
    assert second.first_seen_at_epoch_ms == T0 + 199_000


async def test_empty_poll_with_no_prior_state_returns_no_decisions() -> None:
    """A well-formed zero-slot observation against an empty store is simply nothing to do."""
    engine, _store = _engine()
    assert await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE)) == []


async def test_empty_poll_closes_available_and_drops_pending_together() -> None:
    """Zero slots is a valid observation that both closes and drops covered records (D-39)."""
    engine, store = _engine()
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=[_slot()]))
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=COVERAGE, slots=[_slot()]))
    await engine.process(
        make_parsed(
            rid=RID,
            polled_at_epoch_ms=T0 + 19_000,
            coverage=COVERAGE,
            slots=[_slot(), _slot(time_slot="20:00")],
        )
    )
    decisions = await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 29_000, coverage=COVERAGE))
    assert len([d for d in decisions if isinstance(d, Close)]) == 1  # the AVAILABLE 19:00 slot
    records = await store.get_slots(RID, DATE, PARTY)
    assert list(records) == ["19:00|bar"]  # the PENDING 20:00 slot was dropped, not closed
    assert records["19:00|bar"].state is SlotState.UNAVAILABLE


async def test_duplicate_time_and_seat_type_collapse_to_one_field() -> None:
    """Adjacency: identical (time_slot, seat_type) collapse deterministically, last parsed wins."""
    engine, store = _engine()
    decisions = await engine.process(
        make_parsed(
            rid=RID,
            polled_at_epoch_ms=T0,
            coverage=COVERAGE,
            slots=[_slot(token="tok-old"), _slot(token="tok-new")],
        )
    )
    assert [d for d in decisions if isinstance(d, Expedite)] == [Expedite(source="opentable", restaurant_id=RID)]
    records = await store.get_slots(RID, DATE, PARTY)
    assert list(records) == ["19:00|bar"]
    assert records["19:00|bar"].token == "tok-new"


async def test_same_time_different_seat_types_stay_two_events() -> None:
    """Adjacency: seat_type is part of slot identity, so two seatings are two distinct events."""
    engine, _store = _engine()
    slots = [_slot(seat_type="bar"), _slot(seat_type="standard")]
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=slots))
    emits = [
        d
        for d in await engine.process(
            make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=COVERAGE, slots=slots)
        )
        if isinstance(d, Emit)
    ]
    assert len(emits) == 2
    assert len({e.event.event_id for e in emits}) == 2


async def test_decisions_are_sorted_and_reproducible() -> None:
    """Ordering: equal-comparing slots have a specified, stable output order (STATE-06)."""

    async def run() -> list[tuple[str, int, str]]:
        engine, _store = _engine()
        slots = [
            make_slot(date="2026-05-02", party_size=2, time_slot="18:00", seat_type="bar"),
            make_slot(date="2026-05-01", party_size=4, time_slot="21:00", seat_type=None),
            make_slot(date="2026-05-01", party_size=2, time_slot="21:00", seat_type="bar"),
            make_slot(date="2026-05-01", party_size=2, time_slot="19:00", seat_type="standard"),
        ]
        coverage = {("2026-05-01", 2), ("2026-05-01", 4), ("2026-05-02", 2)}
        await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=coverage, slots=slots))
        decisions = await engine.process(
            make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=coverage, slots=slots)
        )
        return [(d.date, d.party_size, d.slot_key) for d in decisions if isinstance(d, Emit)]

    keys = await run()
    assert keys == sorted(keys)
    assert keys == await run()


async def test_last_close_count_is_exposed_for_the_mass_closure_audit() -> None:
    """Pitfall 10: closures are counted so the shell can log a distinct auditable event."""
    engine, _store = _engine()
    slots = [_slot(time_slot=f"{hour}:00", token=f"tok-{hour}") for hour in range(17, 24)]
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=slots))
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=COVERAGE, slots=slots))
    assert engine.last_close_count == 0

    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 19_000, coverage=COVERAGE))
    assert engine.last_close_count == len(slots)
    assert engine.last_close_count > MASS_CLOSURE_AUDIT_THRESHOLD
