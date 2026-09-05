"""
Monotonic UNKNOWN marking (D-39, D-41, D-53; research Pitfall 2).

`getone()` across two topics is not fair, so a stale polls.completed error can arrive after a
newer successful availability.raw. Marking must therefore be monotonic in polled_at_epoch_ms:
an older error never overrides a newer success. That is also what makes replay order-independent.
"""
from __future__ import annotations

import pytest

from services.state_machine.engine import DiffEngine
from services.state_machine.models import SlotRecord, SlotState
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


def _slot():  # type: ignore[no-untyped-def]
    return make_slot(date=DATE, party_size=PARTY, time_slot="19:00", seat_type="bar", booking_token="tok-1")


async def test_mark_unknown_sets_unknown_since_on_a_fresh_restaurant() -> None:
    engine, store = _engine()
    await engine.mark_unknown(RID, T0)
    meta = await store.get_meta(RID)
    assert meta.unknown_since_ms == T0
    assert meta.last_success_ms is None


async def test_mark_success_clears_unknown_and_records_last_success() -> None:
    engine, store = _engine()
    await engine.mark_unknown(RID, T0)
    await engine.mark_success(RID, T0 + 1_000)
    meta = await store.get_meta(RID)
    assert meta.unknown_since_ms is None
    assert meta.last_success_ms == T0 + 1_000


async def test_older_error_after_newer_success_is_a_no_op() -> None:
    """The out-of-order case Pitfall 2 describes: a stale error must not re-mark UNKNOWN."""
    engine, store = _engine()
    await engine.mark_success(RID, T0 + 5_000)
    await engine.mark_unknown(RID, T0)
    meta = await store.get_meta(RID)
    assert meta.unknown_since_ms is None
    assert meta.last_success_ms == T0 + 5_000


async def test_newer_error_after_older_success_marks_unknown() -> None:
    engine, store = _engine()
    await engine.mark_success(RID, T0)
    await engine.mark_unknown(RID, T0 + 5_000)
    meta = await store.get_meta(RID)
    assert meta.unknown_since_ms == T0 + 5_000
    assert meta.last_success_ms == T0


async def test_repeated_errors_keep_the_earliest_onset_in_either_order() -> None:
    """Two errors applied in either order converge on the same meta — replay is order-independent."""
    engine_a, store_a = _engine()
    await engine_a.mark_unknown(RID, T0)
    await engine_a.mark_unknown(RID, T0 + 5_000)

    engine_b, store_b = _engine()
    await engine_b.mark_unknown(RID, T0 + 5_000)
    await engine_b.mark_unknown(RID, T0)

    assert await store_a.get_meta(RID) == await store_b.get_meta(RID)
    assert (await store_a.get_meta(RID)).unknown_since_ms == T0


async def test_older_success_never_lowers_last_success() -> None:
    engine, store = _engine()
    await engine.mark_success(RID, T0 + 5_000)
    await engine.mark_success(RID, T0)
    assert (await store.get_meta(RID)).last_success_ms == T0 + 5_000


async def test_process_records_a_successful_poll() -> None:
    """Every successfully parsed poll advances last_success_ms (D-53)."""
    engine, store = _engine()
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=[_slot()]))
    assert (await store.get_meta(RID)).last_success_ms == T0


async def test_process_clears_a_stale_unknown_mark() -> None:
    engine, store = _engine()
    await engine.mark_unknown(RID, T0)
    await engine.process(
        make_parsed(rid=RID, polled_at_epoch_ms=T0 + 1_000, coverage=COVERAGE, slots=[_slot()])
    )
    assert (await store.get_meta(RID)).unknown_since_ms is None


async def test_unknown_mark_leaves_every_slot_record_untouched() -> None:
    """Errors never advance a slot toward UNAVAILABLE (D-41) — nothing is closed or dropped."""
    engine, store = _engine()
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=COVERAGE, slots=[_slot()]))
    await engine.process(
        make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=COVERAGE, slots=[_slot()])
    )
    before = await store.get_slots(RID, DATE, PARTY)

    await engine.mark_unknown(RID, T0 + 19_000)

    after = await store.get_slots(RID, DATE, PARTY)
    assert after == before
    assert after["19:00|bar"].state is SlotState.AVAILABLE


# -- IN-01: UNKNOWN is a restaurant-level mark, never a slot state --


def test_slot_state_has_no_unknown_member() -> None:
    """D-41 puts UNKNOWN on the meta record; a slot keeps its last known state.

    No code path ever constructed a SlotRecord(state=UNKNOWN), so the engine branch that
    tested for it was dead — and such a record would also have fallen through both closure
    branches in process() and persisted forever.
    """
    assert {s.value for s in SlotState} == {"PENDING", "AVAILABLE", "UNAVAILABLE"}
    assert not hasattr(SlotState, "UNKNOWN")


def test_an_unreadable_stored_state_is_rejected_rather_than_accepted() -> None:
    """A legacy or corrupt 'UNKNOWN' field must fail the parse, not resurrect the member.

    RedisStateStore.get_slots catches this and drops the field, so the slot re-enters the
    PENDING cycle and has to be confirmed again — the safe direction.
    """
    payload = (
        '{"s":"UNKNOWN","t":"tok","f":1,"p":"6f1b1c62-0000-4000-8000-000000000001",'
        '"l":2,"c":null,"e":null}'
    )
    with pytest.raises(ValueError):
        SlotRecord.from_json(payload)


# -- WR-08: a corrupt event_id must be dropped at the boundary, never raised from the core --


@pytest.mark.parametrize(
    "stored",
    ['"not-a-uuid"', '"6f1b1c62-0000-4000-8000-00000000000"', '""', "42"],
    ids=["garbage", "truncated", "empty", "number"],
)
def test_an_unparseable_event_id_is_rejected_at_the_boundary(stored: str) -> None:
    """`_close` used to run `UUID(record.event_id)` inside the pure core.

    A single bad character in one hash field then raised out of `DiffEngine.process()`, into
    `handle_message`'s transient branch — where, since CR-01, it would be rewound and retried
    forever against a record that can never parse. Validating in `from_json` puts it where
    every other field is already validated, so `get_slots` drops it with the existing
    `slot_record_unreadable` warning and the slot re-enters the PENDING cycle.
    """
    payload = (
        '{"s":"AVAILABLE","t":"tok","f":1,"p":"6f1b1c62-0000-4000-8000-000000000001",'
        f'"l":2,"c":2,"e":{stored}}}'
    )
    with pytest.raises((ValueError, TypeError, AttributeError)):
        SlotRecord.from_json(payload)


def test_a_well_formed_event_id_still_round_trips() -> None:
    """Validation must not become rejection: the ordinary record has to survive."""
    event_id = "6f1b1c62-0000-4000-8000-000000000002"
    payload = (
        '{"s":"AVAILABLE","t":"tok","f":1,"p":"6f1b1c62-0000-4000-8000-000000000001",'
        f'"l":2,"c":2,"e":"{event_id}"}}'
    )
    assert SlotRecord.from_json(payload).event_id == event_id


def test_a_corrupt_event_id_is_dropped_by_the_store_not_raised() -> None:
    """The end-to-end consequence: an unreadable record disappears, the poll survives."""
    import asyncio

    from services.state_machine.store import RedisStateStore

    class _Redis:
        async def hgetall(self, key):  # noqa: ANN001, ANN202 - test double
            return {
                b"19:00|bar": (
                    b'{"s":"AVAILABLE","t":"tok","f":1,'
                    b'"p":"6f1b1c62-0000-4000-8000-000000000001","l":2,"c":2,"e":"broken"}'
                ),
                b"20:00|bar": (
                    b'{"s":"PENDING","t":"tok","f":1,'
                    b'"p":"6f1b1c62-0000-4000-8000-000000000001","l":2,"c":null,"e":null}'
                ),
            }

    store = RedisStateStore(_Redis())  # type: ignore[arg-type]
    records = asyncio.run(store.get_slots(42, "2026-05-01", 2))

    assert set(records) == {"20:00|bar"}, "the corrupt record must be dropped, not fatal"
