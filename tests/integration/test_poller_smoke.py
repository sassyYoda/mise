"""Integration smoke: SC1 — end-to-end emit within 60s. Stub filled by Plan 05."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 05 (poller service)")
async def test_end_to_end_emit_within_60s(kafka_container, redis_container, timescale_container):
    """
    Boot poller against testcontainers. After seed + one scheduler cycle,
    assert one message appears on availability.raw within 60s with correct
    Kafka key '{source}:{restaurant_id}' and valid AvailabilityRaw JSON.
    Also assert one row in poll_log with status='success' and latency_ms > 0.
    """
    raise NotImplementedError
