"""
Resy parser failure matrix (D-64, D-66, D-39; research §V5, Pitfall 10, T-03-01, T-03-04).

Two properties are on trial here and they pull in opposite directions, which is why the matrix
has to be explicit about every row:

  * **Nothing unusable may escape as an exception.** `/4/find` bodies are untrusted third-party
    JSON. One unhandled `KeyError` or `TypeError` out of this parser reaches the consumer's
    transient branch, rewinds the partition, and retries forever against a payload that can
    never decode — a total pipeline outage for a single-partition topic.
  * **Nothing unreadable may pass as an observation.** A `ParseError` becomes UNKNOWN, which
    removes nothing and closes nothing. A `ParsedPoll` with coverage is a claim that the poll
    SAW those `(date, party_size)` buckets, and every slot it did not report there gets closed.
    Reporting a rate-limited date as observed-and-empty would close every real slot on it.

Payload shapes come from `services/poller/sources/resy/fixtures.py` — the single `[ASSUMED]`
definition — and envelopes from `tests/unit/factories.py`. No test inlines a body: a shape
correction after the DevTools spike must break one file, not thirty.
"""
from __future__ import annotations

from typing import Any

import pytest

from services.poller.sources.resy.fixtures import (
    RESY_CHALLENGE_HTML,
    RESY_DUPLICATE_SLOT_RESPONSE,
    RESY_EMPTY_VENUES_RESPONSE,
    RESY_FIXTURE_VENUE_ID,
    RESY_MALFORMED_SLOTS_RESPONSE,
    RESY_MISSING_RESULTS_RESPONSE,
    RESY_RATE_LIMIT_RESPONSE,
    RESY_RESULTS_NOT_A_MAPPING_RESPONSE,
    RESY_RESULTS_WITHOUT_VENUES_RESPONSE,
    RESY_SUCCESS_RESPONSE,
)
from services.state_machine.parsers.errors import ParseError
from services.state_machine.parsers.resy import envelope_coverage, parse_resy
from shared.events import AvailabilityRaw
from tests.unit.factories import make_resy_envelope, make_resy_raw

RID = RESY_FIXTURE_VENUE_ID
DATE = "2026-05-01"
DATE_1 = "2026-05-02"
DATE_2 = "2026-05-03"
PARTY = 2
T0 = 1_788_000_000_000


def _raw(**kwargs: Any) -> AvailabilityRaw:
    kwargs.setdefault("rid", RID)
    kwargs.setdefault("dates", [DATE])
    kwargs.setdefault("parties", [PARTY])
    kwargs.setdefault("polled_at_epoch_ms", T0)
    return make_resy_raw(**kwargs)


def _unvalidated(payload: Any) -> AvailabilityRaw:
    """
    An AvailabilityRaw whose `raw_response` skipped pydantic validation.

    `raw_response` is typed `dict[str, Any]`, so a list or a string cannot normally get this
    far. `model_construct` is how the matrix reaches the parser's own type guards anyway: they
    are defence in depth against a producer bug or a schema loosened later, and defence that is
    never exercised is defence nobody knows is broken.
    """
    return AvailabilityRaw.model_construct(
        poll_id=_raw().poll_id,
        source="resy",
        restaurant_id=RID,
        polled_at_epoch_ms=T0,
        raw_response=payload,
        request_params={},
    )


# --- the happy path ------------------------------------------------------------------------


def test_success_envelope_maps_every_field_per_d66() -> None:
    parsed = parse_resy(_raw(body=RESY_SUCCESS_RESPONSE))
    assert parsed.restaurant_id == RID
    assert parsed.source == "resy"
    assert parsed.polled_at_epoch_ms == T0
    assert parsed.coverage == frozenset({(DATE, PARTY)})
    assert [(s.time_slot, s.seat_type, s.booking_token) for s in parsed.slots] == [
        ("19:00", "Dining Room", "rgs-dining-room-1900"),
        ("19:00", "Bar", "rgs-bar-1900"),
        ("21:30", "Patio", "333"),
    ]
    # date and party_size come from the ENVELOPE ENTRY, so every slot lands in a bucket that is
    # also in coverage — a slot outside coverage would be opened and then never closed (D-38a).
    assert {(s.date, s.party_size) for s in parsed.slots} == parsed.coverage


def test_booking_token_falls_back_to_config_id_when_token_is_absent() -> None:
    """Research A2: public captures disagree on the field name, so the parser accepts both."""
    parsed = parse_resy(_raw(body=RESY_SUCCESS_RESPONSE))
    patio = [s for s in parsed.slots if s.seat_type == "Patio"]
    assert len(patio) == 1
    assert patio[0].booking_token == "333"


def test_empty_venues_is_a_truthful_zero_slot_observation() -> None:
    """
    Pitfall 10: a fully booked venue and a soft ban look identical here, and that is fine.

    The parser reports what the body says — covered, nothing available — because a fully booked
    venue MUST close its slots. Telling a ban apart needs a rolling cross-venue baseline the
    parser does not have and must not grow; that is the POLL-06 canary's job.
    """
    parsed = parse_resy(_raw(body=RESY_EMPTY_VENUES_RESPONSE))
    assert parsed.coverage == frozenset({(DATE, PARTY)})
    assert parsed.slots == ()


# --- poll-level unusability: ParseError -> UNKNOWN -> closes nothing ------------------------


@pytest.mark.parametrize("payload", [[], "not-json", None, 42, RESY_CHALLENGE_HTML])
def test_a_non_mapping_payload_raises_parse_error(payload: Any) -> None:
    with pytest.raises(ParseError, match="payload not a mapping"):
        parse_resy(_unvalidated(payload))


@pytest.mark.parametrize("payload", [{}, {"requests": None}, {"requests": {}}, {"requests": "x"}])
def test_a_missing_or_non_list_requests_key_raises_parse_error(payload: dict[str, Any]) -> None:
    with pytest.raises(ParseError, match="no requests list"):
        parse_resy(_raw(envelope=payload))


def test_an_empty_requests_list_raises_parse_error() -> None:
    """A poll that issued no requests is not a poll that found nothing."""
    with pytest.raises(ParseError, match="requests list is empty"):
        parse_resy(_raw(envelope={"requests": []}))


def test_an_envelope_with_no_200_entry_raises_parse_error() -> None:
    """
    T-03-04: every date rate-limited or challenged means the poll OBSERVED NOTHING.

    Returning coverage here would mark the restaurant healthy and close every slot on all three
    dates — the single most destructive thing this parser could do.
    """
    raw = _raw(
        dates=[DATE, DATE_1, DATE_2],
        body=RESY_RATE_LIMIT_RESPONSE,
        statuses={(DATE, PARTY): 429, (DATE_1, PARTY): 403, (DATE_2, PARTY): 500},
    )
    with pytest.raises(ParseError, match="no envelope entry returned 200"):
        parse_resy(raw)


def test_a_200_entry_missing_results_raises_parse_error() -> None:
    """Unreadable is not empty: no `results` key means the observation did not happen."""
    with pytest.raises(ParseError, match="no results key"):
        parse_resy(_raw(body=RESY_MISSING_RESULTS_RESPONSE))


def test_a_200_entry_whose_results_is_not_a_mapping_raises_parse_error() -> None:
    with pytest.raises(ParseError, match="results is not a mapping"):
        parse_resy(_raw(body=RESY_RESULTS_NOT_A_MAPPING_RESPONSE))


def test_a_200_entry_whose_results_has_no_venues_list_raises_parse_error() -> None:
    """
    `results` without a `venues` list is a shape this parser does not understand.

    It is NOT `venues: []`. Treating an unrecognised body as a zero-slot observation would
    close every covered slot on the strength of a response nobody has verified — so it takes
    the UNKNOWN path instead, which closes nothing and is recoverable on the next poll.
    """
    with pytest.raises(ParseError, match="venues"):
        parse_resy(_raw(body=RESY_RESULTS_WITHOUT_VENUES_RESPONSE))


def test_a_200_entry_whose_body_is_a_challenge_page_raises_parse_error() -> None:
    """The 403 soft-ban body is HTML. If it ever arrives tagged 200, it is still not data."""
    envelope = make_resy_envelope(dates=[DATE], party_sizes=[PARTY])
    envelope["requests"][0]["body"] = RESY_CHALLENGE_HTML
    with pytest.raises(ParseError, match="body is not a mapping"):
        parse_resy(_raw(envelope=envelope))


# --- the D-64 coverage rule ----------------------------------------------------------------


def test_coverage_holds_only_the_dates_that_actually_returned_200() -> None:
    """
    THE reason the D-64 envelope exists (T-03-04, research B-4).

    A mixed poll must report exactly the pairs it observed. Including the rate-limited middle
    date would close every real slot on it — a silent, total data loss for that day that looks
    from the outside like a restaurant with no availability.
    """
    raw = _raw(
        dates=[DATE, DATE_1, DATE_2],
        body=RESY_SUCCESS_RESPONSE,
        statuses={(DATE_1, PARTY): 429},
    )
    parsed = parse_resy(raw)
    assert parsed.coverage == frozenset({(DATE, PARTY), (DATE_2, PARTY)})
    assert (DATE_1, PARTY) not in parsed.coverage
    assert {s.date for s in parsed.slots} == {DATE, DATE_2}


@pytest.mark.parametrize("status", [201, 204, 302, 429, 403, 500, "200", True, None])
def test_only_the_literal_integer_200_counts_as_an_observation(status: Any) -> None:
    envelope = make_resy_envelope(dates=[DATE], party_sizes=[PARTY], body=RESY_SUCCESS_RESPONSE)
    envelope["requests"][0]["status"] = status
    with pytest.raises(ParseError, match="no envelope entry returned 200"):
        parse_resy(_raw(envelope=envelope))


@pytest.mark.parametrize(
    "bad",
    [
        {"date": None},
        {"date": 20260501},
        {"date": ""},
        {"party_size": "2"},
        {"party_size": None},
        {"party_size": True},
    ],
)
def test_an_entry_whose_own_metadata_is_unusable_contributes_no_coverage(
    bad: dict[str, Any],
) -> None:
    """
    Skipped, not raised — but the poll as a whole still fails if nothing usable is left.

    Dropping one unreadable entry closes nothing on that date and lets the rest of the poll
    land; raising would blind every date the poll DID read successfully.
    """
    envelope = make_resy_envelope(dates=[DATE], party_sizes=[PARTY], body=RESY_SUCCESS_RESPONSE)
    envelope["requests"][0].update(bad)
    with pytest.raises(ParseError, match="no envelope entry returned 200"):
        parse_resy(_raw(envelope=envelope))


def test_a_non_mapping_entry_is_skipped_and_the_rest_of_the_poll_lands() -> None:
    envelope = make_resy_envelope(
        dates=[DATE, DATE_1], party_sizes=[PARTY], body=RESY_SUCCESS_RESPONSE
    )
    envelope["requests"].insert(0, "not-an-entry")
    parsed = parse_resy(_raw(envelope=envelope))
    assert parsed.coverage == frozenset({(DATE, PARTY), (DATE_1, PARTY)})


def test_envelope_coverage_returns_the_observed_entries_in_wire_order() -> None:
    """Order stability starts here: entries are consumed exactly as the adapter emitted them."""
    envelope = make_resy_envelope(
        dates=[DATE, DATE_1, DATE_2],
        party_sizes=[PARTY],
        body=RESY_SUCCESS_RESPONSE,
        statuses={(DATE_1, PARTY): 429},
    )
    coverage, observed = envelope_coverage(envelope)
    assert coverage == frozenset({(DATE, PARTY), (DATE_2, PARTY)})
    assert [e["date"] for e in observed] == [DATE, DATE_2]


# --- per-slot defects: skipped, never raised ------------------------------------------------


def test_malformed_slots_are_skipped_and_the_good_one_still_parses() -> None:
    """
    T-03-01: one bad slot may not blind a restaurant.

    Four different per-slot type guards fire in this fixture — a non-string `date.start`, a
    missing `config`, a non-mapping `size`, a non-mapping `date` — and the parser must
    `continue` past all four. Raising would convert a partial reading into a total blackout,
    and the blackout would recur on every poll for as long as the venue serves that slot.
    """
    parsed = parse_resy(_raw(body=RESY_MALFORMED_SLOTS_RESPONSE))
    assert parsed.coverage == frozenset({(DATE, PARTY)})
    assert [(s.time_slot, s.booking_token) for s in parsed.slots] == [("20:00", "rgs-good-2000")]


@pytest.mark.parametrize(
    ("start", "expected"),
    [
        ("2026-05-01 19:00:00", "19:00"),
        ("2026-05-01T19:00:00", "19:00"),
        ("19:00:00", "19:00"),
        ("19:00", "19:00"),
    ],
)
def test_time_slot_is_an_hh_mm_string_slice_never_a_parsed_datetime(
    start: str, expected: str
) -> None:
    """D-49: constructing a datetime would make the wire bytes depend on the process timezone."""
    envelope = make_resy_envelope(dates=[DATE], party_sizes=[PARTY])
    envelope["requests"][0]["body"] = {
        "results": {"venues": [{"slots": [{"date": {"start": start}, "config": {"type": "Bar"}}]}]}
    }
    parsed = parse_resy(_raw(envelope=envelope))
    assert [s.time_slot for s in parsed.slots] == [expected]


@pytest.mark.parametrize("start", ["9:00:00", "not-a-time", "", "2026-05-01", 1900, None])
def test_a_slot_whose_start_is_not_hh_mm_is_dropped_not_guessed_at(start: Any) -> None:
    """A guessed time becomes a slot_key nothing will ever match again — silently permanent."""
    envelope = make_resy_envelope(dates=[DATE], party_sizes=[PARTY])
    envelope["requests"][0]["body"] = {
        "results": {"venues": [{"slots": [{"date": {"start": start}, "config": {"type": "Bar"}}]}]}
    }
    parsed = parse_resy(_raw(envelope=envelope))
    assert parsed.slots == ()
    assert parsed.coverage == frozenset({(DATE, PARTY)})


def test_a_non_string_seat_type_becomes_none_rather_than_dropping_the_slot() -> None:
    """The slot is real; only its label is unreadable. `Slot.seat_type` is already optional."""
    envelope = make_resy_envelope(dates=[DATE], party_sizes=[PARTY])
    envelope["requests"][0]["body"] = {
        "results": {
            "venues": [
                {"slots": [{"date": {"start": "18:00:00"}, "config": {"type": 7, "token": "t"}}]}
            ]
        }
    }
    parsed = parse_resy(_raw(envelope=envelope))
    assert [(s.time_slot, s.seat_type, s.slot_key) for s in parsed.slots] == [
        ("18:00", None, "18:00|-")
    ]


def test_a_slot_with_neither_token_nor_id_keeps_a_null_booking_token() -> None:
    envelope = make_resy_envelope(dates=[DATE], party_sizes=[PARTY])
    envelope["requests"][0]["body"] = {
        "results": {"venues": [{"slots": [{"date": {"start": "18:00:00"}, "config": {}}]}]}
    }
    parsed = parse_resy(_raw(envelope=envelope))
    assert [s.booking_token for s in parsed.slots] == [None]


def test_an_empty_token_string_falls_through_to_config_id() -> None:
    """An empty token is not a token — Phase 4's deep link would build a broken URL from it."""
    envelope = make_resy_envelope(dates=[DATE], party_sizes=[PARTY])
    envelope["requests"][0]["body"] = {
        "results": {
            "venues": [
                {
                    "slots": [
                        {"date": {"start": "18:00:00"}, "config": {"token": "", "id": 987}}
                    ]
                }
            ]
        }
    }
    parsed = parse_resy(_raw(envelope=envelope))
    assert [s.booking_token for s in parsed.slots] == ["987"]


@pytest.mark.parametrize("venues", [[], ["not-a-venue"], [{}], [{"slots": "not-a-list"}]])
def test_a_venue_that_yields_no_readable_slots_is_still_a_zero_slot_observation(
    venues: list[Any],
) -> None:
    envelope = make_resy_envelope(dates=[DATE], party_sizes=[PARTY])
    envelope["requests"][0]["body"] = {"results": {"venues": venues}}
    parsed = parse_resy(_raw(envelope=envelope))
    assert parsed.slots == ()
    assert parsed.coverage == frozenset({(DATE, PARTY)})


# --- collisions belong to the engine, not the parser ---------------------------------------


def test_duplicate_slot_keys_are_both_emitted_for_the_engine_to_resolve() -> None:
    """
    D-36: the parser observes, the engine resolves. A parser-side dedup would hide the collapse
    from `DiffEngine.last_collision_count`, which is the only thing that makes the [ASSUMED]
    payload shape's surprises visible in the consumer's audit log.
    """
    parsed = parse_resy(_raw(body=RESY_DUPLICATE_SLOT_RESPONSE))
    assert len(parsed.slots) == 2
    assert {s.slot_key for s in parsed.slots} == {"20:00|Bar"}
    assert [s.booking_token for s in parsed.slots] == ["rgs-first", "rgs-second"]


def test_parsing_is_order_stable_across_repeated_calls() -> None:
    raw = _raw(dates=[DATE, DATE_1], body=RESY_SUCCESS_RESPONSE)
    first = parse_resy(raw)
    second = parse_resy(raw)
    assert first.coverage == second.coverage
    assert first.slots == second.slots
    assert [s.date for s in first.slots] == [DATE] * 3 + [DATE_1] * 3


def test_the_parser_reads_no_clock_and_carries_the_polls_identity_through() -> None:
    """D-49: every timestamp on the ParsedPoll is the poll's own, so replay is deterministic."""
    raw = _raw(body=RESY_SUCCESS_RESPONSE)
    parsed = parse_resy(raw)
    assert parsed.poll_id == raw.poll_id
    assert parsed.polled_at_epoch_ms == raw.polled_at_epoch_ms == T0
