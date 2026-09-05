"""
Coverage bounding (D-38, D-38a; research B-4 / Pitfall 1).

The OpenTable adapter declares party_sizes [2, 4] but observes only party_sizes[0]. If the
engine trusted the declared list it would close every party-4 slot on every poll and no
party-4 event would ever be emitted. These tests are the regression guard for the Phase 3
change that makes the adapter loop party sizes.
"""
from __future__ import annotations

import pytest

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.state_machine.engine import DiffEngine
from services.state_machine.models import Close, Emit, SlotState
from services.state_machine.parsers.errors import ParseError
from services.state_machine.parsers.opentable import effective_coverage
from services.state_machine.store import MemoryStateStore
from tests.unit.factories import make_parsed, make_raw, make_slot

RID = 42
DATE = "2026-05-01"
OTHER_DATE = "2026-05-02"
T0 = 1_788_000_000_000
CONFIRM_DELAY_MS = 8_000


def test_effective_coverage_uses_only_the_first_party_size() -> None:
    """The declared list is [2, 4]; only party 2 is actually observed (D-38a)."""
    assert effective_coverage({"rid": RID, "dates": [DATE], "party_sizes": [2, 4]}) == frozenset({(DATE, 2)})


def test_effective_coverage_is_empty_when_either_list_is_empty() -> None:
    """An unbounded poll closes nothing rather than closing everything."""
    assert effective_coverage({"dates": [], "party_sizes": [2]}) == frozenset()
    assert effective_coverage({"dates": [DATE], "party_sizes": []}) == frozenset()
    assert effective_coverage({}) == frozenset()


def test_parsed_poll_coverage_comes_from_request_params_not_the_payload() -> None:
    """A real AvailabilityRaw declaring [2, 4] yields coverage for party 2 only."""
    from services.state_machine.parsers import parse_raw

    parsed = parse_raw(
        make_raw(
            rid=RID,
            dates=[DATE],
            parties=[2, 4],
            response=OPENTABLE_SUCCESS_RESPONSE,
            polled_at_epoch_ms=T0,
        )
    )
    assert parsed.coverage == frozenset({(DATE, 2)})


async def test_party_two_poll_never_closes_a_party_four_slot() -> None:
    """A confirmed party-4 slot survives a party-2-only poll untouched (research B-4)."""
    store = MemoryStateStore()
    engine = DiffEngine(store, confirm_delay_ms=CONFIRM_DELAY_MS)
    party4 = make_slot(date=DATE, party_size=4, time_slot="19:00", seat_type="bar", booking_token="tok-4")
    wide_coverage = {(DATE, 2), (DATE, 4)}

    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage=wide_coverage, slots=[party4]))
    await engine.process(
        make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage=wide_coverage, slots=[party4])
    )
    assert (await store.get_slots(RID, DATE, 4))["19:00|bar"].state is SlotState.AVAILABLE

    # Now a poll whose EFFECTIVE coverage is party 2 only, carrying no party-4 slot.
    decisions = await engine.process(
        make_parsed(rid=RID, polled_at_epoch_ms=T0 + 19_000, coverage={(DATE, 2)})
    )
    assert [d for d in decisions if isinstance(d, Close)] == []
    assert (await store.get_slots(RID, DATE, 4))["19:00|bar"].state is SlotState.AVAILABLE


async def test_party_two_poll_never_drops_a_pending_party_four_slot() -> None:
    """A PENDING party-4 slot must survive long enough to be confirmed by a later party-4 poll."""
    store = MemoryStateStore()
    engine = DiffEngine(store, confirm_delay_ms=CONFIRM_DELAY_MS)
    party4 = make_slot(date=DATE, party_size=4, time_slot="19:00", seat_type="bar", booking_token="tok-4")

    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage={(DATE, 4)}, slots=[party4]))
    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0 + 4_000, coverage={(DATE, 2)}))
    assert (await store.get_slots(RID, DATE, 4))["19:00|bar"].state is SlotState.PENDING

    emits = [
        d
        for d in await engine.process(
            make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage={(DATE, 4)}, slots=[party4])
        )
        if isinstance(d, Emit)
    ]
    assert len(emits) == 1
    assert emits[0].event.party_size == 4


async def test_out_of_window_date_is_never_closed() -> None:
    """When the date window rolls forward, yesterday's stored slots are untouched (D-38)."""
    store = MemoryStateStore()
    engine = DiffEngine(store, confirm_delay_ms=CONFIRM_DELAY_MS)
    slot = make_slot(date=DATE, party_size=2, time_slot="19:00", seat_type="bar", booking_token="tok-1")

    await engine.process(make_parsed(rid=RID, polled_at_epoch_ms=T0, coverage={(DATE, 2)}, slots=[slot]))
    await engine.process(
        make_parsed(rid=RID, polled_at_epoch_ms=T0 + 9_000, coverage={(DATE, 2)}, slots=[slot])
    )

    decisions = await engine.process(
        make_parsed(rid=RID, polled_at_epoch_ms=T0 + 19_000, coverage={(OTHER_DATE, 2)})
    )
    assert [d for d in decisions if isinstance(d, Close)] == []
    assert (await store.get_slots(RID, DATE, 2))["19:00|bar"].state is SlotState.AVAILABLE


# -- WR-08: request_params is producer-controlled data, not a validated schema --


@pytest.mark.parametrize(
    "parties",
    [["two"], [None], [{"party": 2}], [[2]]],
    ids=["non_numeric_string", "null", "mapping", "list"],
)
def test_an_unusable_party_size_is_a_parse_error(parties) -> None:
    """A bare int() raises ValueError/TypeError, and neither reaches the UNKNOWN path."""
    with pytest.raises(ParseError):
        effective_coverage({"rid": RID, "dates": [DATE], "party_sizes": parties})


def test_a_numeric_string_party_size_is_still_accepted() -> None:
    """Tolerance, not strictness, is the goal: '2' is unambiguously two covers."""
    assert effective_coverage({"dates": [DATE], "party_sizes": ["2"]}) == frozenset({(DATE, 2)})


@pytest.mark.parametrize(
    "dates",
    [[20260501], [None], [{"date": DATE}]],
    ids=["int", "null", "mapping"],
)
def test_an_unusable_date_is_a_parse_error(dates) -> None:
    """str() never raises, so a bad date would silently become coverage matching no slot."""
    with pytest.raises(ParseError):
        effective_coverage({"rid": RID, "dates": dates, "party_sizes": [2]})


async def test_an_unusable_party_size_surfaces_through_parse_raw() -> None:
    """The whole point: it must arrive as a ParseError at the consumer's UNKNOWN branch."""
    from services.state_machine.parsers import parse_raw

    raw = make_raw(
        rid=RID, dates=[DATE], parties=[2], response=OPENTABLE_SUCCESS_RESPONSE,
        polled_at_epoch_ms=T0,
    )
    broken = raw.model_copy(
        update={"request_params": {"rid": RID, "dates": [DATE], "party_sizes": ["two"]}}
    )
    with pytest.raises(ParseError):
        parse_raw(broken)


# -- WR-09: a poll that observed nothing must never report success --


@pytest.mark.parametrize(
    "request_params",
    [
        {},
        {"rid": RID},
        {"rid": RID, "dates": [], "party_sizes": [2]},
        {"rid": RID, "dates": [DATE], "party_sizes": []},
        {"rid": RID, "dates": "2026-05-01", "party_sizes": [2]},
    ],
    ids=["absent", "rid_only", "no_dates", "no_parties", "dates_not_a_list"],
)
def test_a_poll_without_coverage_is_a_parse_error(request_params) -> None:
    """Unbounded coverage means UNKNOWN, not a successful observation of nothing."""
    from services.state_machine.parsers import parse_raw

    raw = make_raw(
        rid=RID, dates=[DATE], parties=[2], response=OPENTABLE_SUCCESS_RESPONSE,
        polled_at_epoch_ms=T0,
    )
    with pytest.raises(ParseError):
        parse_raw(raw.model_copy(update={"request_params": request_params}))


async def test_a_poll_without_coverage_does_not_clear_an_unknown_mark() -> None:
    """The expensive part of the bug: mark_success ran and the restaurant looked healthy."""
    store = MemoryStateStore()
    engine = DiffEngine(store, confirm_delay_ms=CONFIRM_DELAY_MS)
    await engine.mark_unknown(RID, T0)

    from services.state_machine.parsers import parse_raw

    raw = make_raw(
        rid=RID, dates=[DATE], parties=[2], response=OPENTABLE_SUCCESS_RESPONSE,
        polled_at_epoch_ms=T0 + 90_000,
    )
    with pytest.raises(ParseError):
        parsed = parse_raw(raw.model_copy(update={"request_params": {}}))
        await engine.process(parsed)

    meta = await store.get_meta(RID)
    assert meta.unknown_since_ms == T0, "an unobservable poll cleared the UNKNOWN mark"
    assert meta.last_success_ms is None
