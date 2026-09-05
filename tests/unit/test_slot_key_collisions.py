"""Unit: IN-07 — two slots colliding on one `(time_slot, seat_type)` leave a trace.

`_group_by_bucket` resolves the collision last-wins with no diagnostic. The resolution is
deterministic and documented, but it is exactly the payload-shape surprise the [ASSUMED]
OpenTable schema warns about, and it used to disappear without a trace. The core stays free of
I/O (D-49), so the engine COUNTS and the shell logs — the same split `last_close_count`
already uses for the mass-closure audit.
"""
from __future__ import annotations

from services.state_machine.engine import DiffEngine
from services.state_machine.store import MemoryStateStore
from tests.unit.factories import make_parsed, make_slot

RID = 42
DATE = "2026-05-01"
PARTY = 2
T0 = 1_788_000_000_000
CONFIRM_DELAY_MS = 8_000


async def test_colliding_slots_are_counted() -> None:
    """Two slots on one (time_slot, seat_type) collapse last-wins — but leave a number behind."""
    store = MemoryStateStore()
    engine = DiffEngine(store, confirm_delay_ms=CONFIRM_DELAY_MS)
    parsed = make_parsed(
        rid=RID,
        polled_at_epoch_ms=T0,
        coverage={(DATE, PARTY)},
        slots=[
            make_slot(date=DATE, party_size=PARTY, time_slot="19:00", seat_type="bar",
                      booking_token="first"),
            make_slot(date=DATE, party_size=PARTY, time_slot="19:00", seat_type="bar",
                      booking_token="second"),
        ],
    )

    await engine.process(parsed)

    assert engine.last_collision_count == 1
    records = await store.get_slots(RID, DATE, PARTY)
    assert records["19:00|bar"].token == "second", "the documented last-wins resolution"


async def test_distinct_seat_types_are_not_collisions() -> None:
    """The shipped fixture shape (bar + standard) is two slots, not a collision."""
    engine = DiffEngine(MemoryStateStore(), confirm_delay_ms=CONFIRM_DELAY_MS)
    parsed = make_parsed(
        rid=RID,
        polled_at_epoch_ms=T0,
        coverage={(DATE, PARTY)},
        slots=[
            make_slot(date=DATE, party_size=PARTY, time_slot="19:00", seat_type=s,
                      booking_token="shared")
            for s in ("bar", "standard")
        ],
    )

    await engine.process(parsed)

    assert engine.last_collision_count == 0


async def test_the_collision_count_is_reset_between_polls() -> None:
    """A stale count would make the shell log a warning for a clean poll."""
    engine = DiffEngine(MemoryStateStore(), confirm_delay_ms=CONFIRM_DELAY_MS)
    colliding = make_parsed(
        rid=RID, polled_at_epoch_ms=T0, coverage={(DATE, PARTY)},
        slots=[
            make_slot(date=DATE, party_size=PARTY, time_slot="19:00", seat_type="bar"),
            make_slot(date=DATE, party_size=PARTY, time_slot="19:00", seat_type="bar"),
        ],
    )
    clean = make_parsed(
        rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage={(DATE, PARTY)},
        slots=[make_slot(date=DATE, party_size=PARTY, time_slot="19:00", seat_type="bar")],
    )

    await engine.process(colliding)
    assert engine.last_collision_count == 1
    await engine.process(clean)
    assert engine.last_collision_count == 0
