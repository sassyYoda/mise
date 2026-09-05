"""Unit tests for shared.events Pydantic models."""
import json
from uuid import UUID, uuid4

import pytest

from shared.events import AvailabilityEvent, AvailabilityRaw, PollCompleted, make_event_id


def test_availability_raw_event_to_bytes():
    evt = AvailabilityRaw(
        poll_id=uuid4(),
        source="opentable",
        restaurant_id=42,
        polled_at_epoch_ms=1_000_000,
        raw_response={"slots": []},
        request_params={"rid": 42, "date_range_days": 7, "party_sizes": [2, 4]},
    )
    b = evt.to_bytes()
    assert isinstance(b, bytes)
    decoded = b.decode()
    assert '"source":"opentable"' in decoded or '"source": "opentable"' in decoded


def test_availability_raw_event_frozen():
    evt = AvailabilityRaw(
        poll_id=uuid4(),
        source="opentable",
        restaurant_id=42,
        polled_at_epoch_ms=1_000_000,
        raw_response={},
        request_params={},
    )
    with pytest.raises(Exception):
        evt.restaurant_id = 99  # type: ignore[misc]


def test_polls_completed_event_extra_fields_forbidden():
    with pytest.raises(Exception):
        PollCompleted(
            poll_id=uuid4(),
            source="opentable",
            restaurant_id=42,
            polled_at_epoch_ms=1_000_000,
            status="success",
            latency_ms=100,
            unknown_field="oops",
        )


def test_polls_completed_event_optional_fields():
    evt = PollCompleted(
        poll_id=uuid4(),
        source="resy",
        restaurant_id=7,
        polled_at_epoch_ms=1_000_000,
        status="error",
        latency_ms=500,
        http_status=503,
        error="Service Unavailable",
    )
    assert evt.status == "error"
    assert evt.http_status == 503


def _availability_event(**overrides):
    fields = {
        "event_id": make_event_id("opentable", 42, "2026-05-01", 2, "19:00|bar", "poll-1"),
        "event_type": "slot_opened",
        "source": "opentable",
        "restaurant_id": 42,
        "date": "2026-05-01",
        "time_slot": "19:00",
        "party_size": 2,
        "seat_type": "bar",
        "booking_token": "abc123-reservation-token",
        "first_seen_at_epoch_ms": 1_788_000_000_000,
        "confirmed_at_epoch_ms": 1_788_000_009_000,
        "produced_at_epoch_ms": 1_788_000_009_000,
        "confirming_poll_id": UUID("11111111-2222-3333-4444-555555555555"),
    }
    fields.update(overrides)
    return AvailabilityEvent(**fields)


def test_availability_event_frozen():
    evt = _availability_event()
    with pytest.raises(Exception):
        evt.party_size = 4  # type: ignore[misc]


def test_availability_event_extra_fields_forbidden():
    with pytest.raises(Exception):
        _availability_event(unknown_field="oops")


def test_availability_event_to_bytes_round_trips():
    evt = _availability_event()
    assert AvailabilityEvent.model_validate_json(evt.to_bytes()) == evt


def test_availability_event_wire_order_follows_declaration_order():
    """Declaration order IS wire order — byte-identical replay depends on it (STATE-06)."""
    evt = _availability_event()
    reversed_fields = dict(reversed(list(evt.model_dump().items())))
    assert AvailabilityEvent(**reversed_fields).to_bytes() == evt.to_bytes()
    assert list(json.loads(evt.to_bytes())) == list(AvailabilityEvent.model_fields)


def test_availability_event_carries_no_wall_clock_field():
    """Every timestamp is a poll timestamp; nothing on this model may come from `now` (D-45)."""
    assert "produced_at_epoch_ms" in AvailabilityEvent.model_fields
    evt = _availability_event()
    assert evt.produced_at_epoch_ms == evt.confirmed_at_epoch_ms


def test_availability_event_optional_fields_are_emitted_as_null():
    """No exclude_none anywhere: an omitted-vs-null difference would break byte identity."""
    evt = _availability_event(seat_type=None, booking_token=None)
    decoded = json.loads(evt.to_bytes())
    assert decoded["seat_type"] is None
    assert decoded["booking_token"] is None
