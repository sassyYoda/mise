"""Integration: SC4 — hypertables have chunk_time_interval = 1 day. Stub filled by Plan 04."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 04 (migrations)")
async def test_chunk_interval_is_one_day(timescale_container):
    """
    Apply Alembic migrations to testcontainers TimescaleDB.
    Query: SELECT chunk_time_interval FROM timescaledb_information.dimensions
           WHERE hypertable_name IN ('availability_events', 'poll_log');
    Assert both rows return 86400000000 microseconds (1 day).
    """
    raise NotImplementedError
