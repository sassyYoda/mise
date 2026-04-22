"""Unit tests for shared.events Pydantic models."""
import pytest
from uuid import uuid4
from shared.events import AvailabilityRaw, PollCompleted


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
