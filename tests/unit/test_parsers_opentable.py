"""
OpenTable parser failure matrix (D-37, D-39; research Pitfall 8, Security Domain DoS row).

One unhandled KeyError in the parser would halt the whole Kafka partition, so every malformed
payload must surface as a ParseError. The three fixtures imported here are the authoritative
payload shapes; no test invents its own.
"""
from __future__ import annotations

import pytest

from services.poller.sources.opentable.fixtures import (
    OPENTABLE_EMPTY_RESPONSE,
    OPENTABLE_RATE_LIMIT_RESPONSE,
    OPENTABLE_SUCCESS_RESPONSE,
)
from services.state_machine.parsers import PARSER_REGISTRY, parse_raw
from services.state_machine.parsers.errors import ParseError, UnsupportedSourceError
from services.state_machine.parsers.opentable import parse_opentable
from tests.unit.factories import make_raw

RID = 42
DATE = "2026-05-01"
T0 = 1_788_000_000_000


def _raw(response, parties=(2, 4), source="opentable"):  # type: ignore[no-untyped-def]
    return make_raw(
        rid=RID,
        dates=[DATE],
        parties=list(parties),
        response=response,
        polled_at_epoch_ms=T0,
        source=source,
    )


def test_success_response_yields_one_slot_per_seating_type():
    parsed = parse_opentable(_raw(OPENTABLE_SUCCESS_RESPONSE))
    assert len(parsed.slots) == 2
    assert {s.seat_type for s in parsed.slots} == {"bar", "standard"}
    assert {s.slot_key for s in parsed.slots} == {"19:00|bar", "19:00|standard"}
    assert parsed.coverage == frozenset({(DATE, 2)})
    assert all(s.booking_token == "abc123-reservation-token" for s in parsed.slots)
    assert all(s.party_size == 2 for s in parsed.slots)


def test_success_response_carries_poll_identity_through():
    raw = _raw(OPENTABLE_SUCCESS_RESPONSE)
    parsed = parse_opentable(raw)
    assert parsed.restaurant_id == RID
    assert parsed.source == "opentable"
    assert parsed.poll_id == raw.poll_id
    assert parsed.polled_at_epoch_ms == T0


def test_empty_response_is_a_valid_zero_slot_observation():
    """D-39: zero slots is an observation that closes covered slots, not a parse failure."""
    parsed = parse_opentable(_raw(OPENTABLE_EMPTY_RESPONSE))
    assert parsed.slots == ()
    assert parsed.coverage == frozenset({(DATE, 2)})


def test_rate_limit_response_raises_parse_error():
    with pytest.raises(ParseError):
        parse_opentable(_raw(OPENTABLE_RATE_LIMIT_RESPONSE))


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": None},
        {"data": []},
        {"availability": []},
        {"data": {"availability": []}, "errors": [{"message": "partial failure"}]},
    ],
)
def test_malformed_payloads_raise_parse_error(payload):
    with pytest.raises(ParseError):
        parse_opentable(_raw(payload))


def test_non_mapping_payload_raises_parse_error():
    raw = _raw(OPENTABLE_SUCCESS_RESPONSE)
    broken = raw.model_copy(update={"raw_response": ["not", "a", "mapping"]})
    with pytest.raises(ParseError):
        parse_opentable(broken)


def test_parse_error_message_never_echoes_the_payload():
    """Third-party payload bodies must not reach the logs through an exception message."""
    secret = "leaky-third-party-token"
    with pytest.raises(ParseError) as exc:
        parse_opentable(_raw({"errors": [{"message": secret}]}))
    assert secret not in str(exc.value)


def test_tolerates_missing_and_ragged_fields():
    """`.get()` chains only: ragged entries are skipped, never crash the partition."""
    payload = {
        "data": {
            "availability": [
                "not-a-mapping",
                {"restaurantId": 999, "availability": []},  # different restaurant, skipped
                {
                    "restaurantId": RID,
                    "availability": [
                        "junk",
                        {"date": None, "timeSlots": [{"time": "18:00"}]},  # no usable date
                        {"date": DATE, "timeSlots": "not-a-list"},
                        {"date": DATE, "timeSlots": [{"noTime": True}, {"time": "20:00"}]},
                    ],
                },
            ]
        }
    }
    parsed = parse_opentable(_raw(payload))
    assert [s.slot_key for s in parsed.slots] == ["20:00|-"]
    assert parsed.slots[0].booking_token is None


def test_resy_source_is_unsupported_until_phase_three():
    with pytest.raises(UnsupportedSourceError):
        parse_raw(_raw(OPENTABLE_SUCCESS_RESPONSE, source="resy"))


def test_unsupported_source_error_is_a_parse_error():
    """One `except ParseError` handler covers both failure modes (D-37)."""
    assert issubclass(UnsupportedSourceError, ParseError)
    with pytest.raises(ParseError):
        parse_raw(_raw(OPENTABLE_SUCCESS_RESPONSE, source="resy"))


def test_registry_dispatches_opentable_without_the_engine_branching_on_source():
    assert set(PARSER_REGISTRY) == {"opentable"}
    assert PARSER_REGISTRY["opentable"] is parse_opentable
    assert parse_raw(_raw(OPENTABLE_SUCCESS_RESPONSE)).source == "opentable"
