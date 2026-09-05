"""Unit tests for shared.events Pydantic models."""
import json
import typing
from uuid import UUID, uuid4

import pytest

from shared.events import (
    FAILED_POLL_STATUSES,
    AvailabilityEvent,
    AvailabilityRaw,
    PollCompleted,
    make_event_id,
)


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


def _completed(**overrides):
    fields = {
        "poll_id": uuid4(),
        "source": "resy",
        "restaurant_id": 4242,
        "polled_at_epoch_ms": 1_788_000_000_000,
        "status": "success",
        "latency_ms": 1234,
    }
    fields.update(overrides)
    return PollCompleted(**fields)


def test_polls_completed_accepts_banned():
    """D-67, research B-7: a soft ban is a first-class poll outcome, not an `error`."""
    assert _completed(status="banned").status == "banned"


def test_polls_completed_accepts_a_context_id():
    """D-67: Grafana needs per-context latency, so the poll names the context that made it."""
    evt = _completed(context_id="ctx-3")
    assert evt.context_id == "ctx-3"
    assert _completed().context_id is None


def test_polls_completed_still_rejects_an_unknown_status():
    """Widening the Literal by three characters must not turn it into a free-text field."""
    with pytest.raises(Exception):
        _completed(status="quarantined")


def test_context_id_is_the_last_field_so_the_wire_order_is_append_only():
    """
    Field declaration order IS JSON wire order (see the AvailabilityEvent docstring), and every
    committed golden replay file encodes it. A new field may therefore only be APPENDED —
    inserting `context_id` anywhere else would have rewritten the bytes of every historical
    polls.completed record for no benefit at all.
    """
    assert list(PollCompleted.model_fields)[-1] == "context_id"
    assert list(json.loads(_completed(context_id="ctx-3").to_bytes()))[-1] == "context_id"


def test_failed_poll_statuses_covers_every_non_success_member_of_the_literal():
    """
    The frozenset and the Literal may not drift apart (D-67a).

    Both consumers branch on `!= "success"`, so a status added to the Literal is already
    handled correctly by them — but `FAILED_POLL_STATUSES` is what documents the KNOWN failure
    set for logs, dashboards and `poll_log.status` semantics, and a stale registry is a
    dashboard that silently under-reports bans. This assertion is what forces the two to be
    edited together.
    """
    declared = set(typing.get_args(PollCompleted.model_fields["status"].annotation))
    assert declared == FAILED_POLL_STATUSES | {"success"}
    assert FAILED_POLL_STATUSES == declared - {"success"}


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
