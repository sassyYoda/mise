"""
Monotonic UNKNOWN marking (D-39, D-41, D-53; research Pitfall 2).

`getone()` across two topics is not fair, so a stale polls.completed error can arrive after a
newer successful availability.raw. Marking must therefore be monotonic in polled_at_epoch_ms:
an older error never overrides a newer success. That is also what makes replay order-independent.
"""
from __future__ import annotations

from services.state_machine.engine import DiffEngine
from services.state_machine.models import SlotState
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
