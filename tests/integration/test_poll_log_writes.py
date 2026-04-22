"""Integration: SC4 — ``poll_log`` rows written with ``latency_ms`` after a poll cycle.

Calls :meth:`Publisher.publish` directly against a testcontainers Postgres
(Kafka is mocked with :class:`AsyncMock` since this test focuses on the DB
write side of the contract). Asserts the row is present with the correct
status / latency / http_status fields.
"""
from __future__ import annotations

import os
import subprocess
import uuid
from unittest.mock import AsyncMock

import asyncpg
import pytest

from services.poller.publisher import Publisher

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db_url_sync(timescale_container):
    return timescale_container.get_connection_url().replace("psycopg2", "psycopg")


@pytest.fixture(scope="module")
def db_url_async(db_url_sync):
    return db_url_sync.replace("postgresql+psycopg://", "postgresql+asyncpg://")


@pytest.fixture(scope="module")
def asyncpg_dsn(timescale_container):
    host = timescale_container.get_container_host_ip()
    port = timescale_container.get_exposed_port(5432)
    return f"postgresql://mise:mise@{host}:{port}/mise"


@pytest.fixture(scope="module", autouse=True)
def run_migrations(db_url_sync):
    env = {**os.environ, "DATABASE_URL_SYNC": db_url_sync}
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"


@pytest.fixture(autouse=True)
def _reset_db_singleton(db_url_async):
    """Point shared.db at the testcontainers DB and reset cached engine.

    shared.db caches the engine + session factory at module level — in a
    test run the env var changes after import, so we clear the cache.
    """
    os.environ["DATABASE_URL_ASYNC"] = db_url_async
    import shared.db as shared_db

    shared_db._engine = None
    shared_db._session_factory = None
    yield
    shared_db._engine = None
    shared_db._session_factory = None


async def test_poll_writes_row_with_latency(asyncpg_dsn):
    """Publisher.publish writes a poll_log row with status + latency_ms."""
    mock_producer = AsyncMock()
    mock_producer.send = AsyncMock()

    publisher = Publisher(producer=mock_producer)
    poll_id = uuid.uuid4()

    await publisher.publish(
        poll_id=poll_id,
        source="opentable",
        restaurant_id=42,
        raw_response={"data": {"availability": []}},
        request_params={
            "rid": 42,
            "dates": ["2026-04-22"],
            "party_sizes": [2, 4],
        },
        status="success",
        latency_ms=250,
        http_status=200,
    )

    conn = await asyncpg.connect(asyncpg_dsn)
    try:
        row = await conn.fetchrow(
            "SELECT * FROM poll_log WHERE poll_id = $1",
            poll_id,
        )
    finally:
        await conn.close()

    assert row is not None, "poll_log row not found"
    assert row["status"] == "success"
    assert row["latency_ms"] == 250
    assert row["http_status"] == 200
    assert row["restaurant_id"] == 42
    assert row["source"] == "opentable"


async def test_poll_log_status_values_constrained(asyncpg_dsn):
    """All ``poll_log.status`` values must be 'success', 'error', or 'timeout'."""
    conn = await asyncpg.connect(asyncpg_dsn)
    try:
        invalid = await conn.fetchval(
            """
            SELECT COUNT(*) FROM poll_log
            WHERE status NOT IN ('success', 'error', 'timeout')
            """
        )
    finally:
        await conn.close()
    assert invalid == 0, f"{invalid} rows with invalid status values"
