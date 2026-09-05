"""Unit: IN-07 — two slots colliding on one `(time_slot, seat_type)` leave a trace.

`_group_by_bucket` resolves the collision last-wins with no diagnostic. The resolution is
deterministic and documented, but it is exactly the payload-shape surprise the [ASSUMED]
OpenTable schema warns about, and it used to disappear without a trace. The core stays free of
I/O (D-49), so the engine COUNTS and the shell logs — the same split `last_close_count`
already uses for the mass-closure audit.
"""
from __future__ import annotations

import pytest

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


# -- IN-05: the two observation counters must share a reset point --


class _ExplodingStore(MemoryStateStore):
    """A store that fails partway through the diff, exactly as a Redis timeout would."""

    async def get_slots(self, rid: int, date: str, party: int):  # type: ignore[override]
        raise RuntimeError("redis went away mid-diff")


async def test_a_failed_poll_never_leaves_a_stale_close_count() -> None:
    """`last_close_count` used to be assigned only at the END of process().

    An exception mid-diff therefore left this poll's fresh collision count paired with the
    PREVIOUS poll's close count — two counters describing two different polls, which is the
    trap the Phase 3 canary that consumes them would inherit.
    """
    engine = DiffEngine(_ExplodingStore(), confirm_delay_ms=CONFIRM_DELAY_MS)
    engine.last_close_count = 7
    engine.last_collision_count = 3

    with pytest.raises(RuntimeError):
        await engine.process(
            make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage={(DATE, PARTY)})
        )

    assert engine.last_close_count == 0, "a stale close count survived a failed poll"
    assert engine.last_collision_count == 0


# -- WR-02 (iteration 3): the identity recipe's NON-injectivity, pinned as an executable fact --
#
# `make_event_id`'s docstring used to assert a safety property it does not have: that an
# ambiguity would need to straddle `slot_key` and `first_poll_id`, and that `first_poll_id`
# being a UUID therefore blocked it. Both halves were false. These two tests are the
# reproduction, kept executable so the constraint cannot drift back into comforting prose —
# and so that the day the recipe IS escaped (WR-01 in .planning/deferred-items.md), they fail
# loudly and have to be deleted deliberately rather than forgotten.


def test_the_event_id_recipe_is_not_injective_across_adjacent_payload_fields() -> None:
    """`date`, `party_size` and `slot_key` are adjacent, unescaped and all payload-derived."""
    from shared.events import make_event_id

    first = make_event_id("opentable", RID, "2026-05-01", 2, "19:00|bar", "pid")
    second = make_event_id("opentable", RID, "2026-05-01:2", 19, "00|bar", "pid")

    assert first == second, (
        "this collision is the KNOWN CONSTRAINT recorded on make_event_id. If it no longer "
        "holds, the recipe changed — every committed golden and every availability_events "
        "row must be regenerated in the same commit (WR-01)."
    )


def test_slot_key_itself_collapses_two_distinct_identities() -> None:
    """`slot_key` is a lossy join, so escaping the id recipe alone would not fix WR-01."""
    from services.state_machine.models import Slot

    embedded_in_time = Slot(
        date=DATE, party_size=PARTY, time_slot="19:00|bar", seat_type=None, booking_token="a"
    )
    embedded_in_seat = Slot(
        date=DATE, party_size=PARTY, time_slot="19:00", seat_type="bar|-", booking_token="b"
    )

    assert embedded_in_time.slot_key == embedded_in_seat.slot_key == "19:00|bar|-", (
        "two distinct slots share one Redis hash field, one SlotRecord and one event_id "
        "(WR-01, deferred: fixing it changes every event_id)"
    )
