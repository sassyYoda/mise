"""Integration: FOUND-04 — all 5 Kafka topics exist with correct retention. Stub filled by Plan 02."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 02 (topics script)")
async def test_all_five_topics_have_retention(kafka_container):
    """
    Run scripts/create_topics.py against testcontainers Kafka.
    Assert all 5 topics exist: availability.raw, availability.events,
    notifications.queued, notifications.sent, polls.completed.
    Assert retention.ms matches: 86400000, 604800000, 2592000000, 2592000000, 604800000.
    Run twice; assert idempotency.
    """
    raise NotImplementedError
