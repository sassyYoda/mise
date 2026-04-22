"""Integration: SC4 — hypertables have chunk_time_interval = 1 day."""
import os
import subprocess

import asyncpg
import pytest


@pytest.fixture(scope="module")
def db_url_sync(timescale_container):
    # testcontainers postgres returns a psycopg2-style URL; Alembic uses psycopg3
    return timescale_container.get_connection_url().replace("psycopg2", "psycopg")


@pytest.fixture(scope="module")
def db_url_async(timescale_container):
    host = timescale_container.get_container_host_ip()
    port = timescale_container.get_exposed_port(5432)
    return f"postgresql://mise:mise@{host}:{port}/mise"


@pytest.fixture(scope="module", autouse=True)
def run_migrations(db_url_sync):
    """Run Alembic migrations against the testcontainer."""
    env = {**os.environ, "DATABASE_URL_SYNC": db_url_sync}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"


@pytest.mark.asyncio
async def test_chunk_interval_is_one_day(db_url_async):
    """SC4: Both hypertables must have chunk_time_interval = 86400000000 microseconds (1 day)."""
    conn = await asyncpg.connect(db_url_async)
    try:
        rows = await conn.fetch(
            """
            SELECT hypertable_name, time_interval
            FROM timescaledb_information.dimensions
            WHERE hypertable_name IN ('poll_log', 'availability_events')
            ORDER BY hypertable_name
            """
        )
        assert len(rows) == 2, f"Expected 2 hypertables, got {len(rows)}"
        for row in rows:
            interval = row["time_interval"]
            # time_interval is returned as timedelta for interval-based dimensions
            if hasattr(interval, "total_seconds"):
                interval_us = int(interval.total_seconds() * 1_000_000)
            else:
                interval_us = int(interval)
            assert interval_us == 86_400_000_000, (
                f"{row['hypertable_name']} chunk_time_interval is {interval_us}, "
                f"expected 86400000000"
            )
    finally:
        await conn.close()
