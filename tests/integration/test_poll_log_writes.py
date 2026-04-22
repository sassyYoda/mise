"""Integration: SC4 — poll_log rows written with latency. Stub filled by Plan 05."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 05 (publisher)")
async def test_poll_writes_row_with_latency(kafka_container, redis_container, timescale_container):
    """
    Run one poll cycle against mocked OpenTable (respx).
    Assert: SELECT COUNT(*) FROM poll_log WHERE latency_ms IS NOT NULL
            AND status IN ('success','error','timeout') > 0 after cycle.
    Assert: poll_log.status values only ever 'success', 'error', or 'timeout'.
    """
    raise NotImplementedError
