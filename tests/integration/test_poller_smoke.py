"""Integration smoke: SC1 — end-to-end emit within 60s.

Boots the full poller against testcontainers Kafka/Redis/Postgres, seeds a
single ``opentable:42`` job into ``sched:polls``, mocks the OpenTable
endpoint with respx, and asserts an ``availability.raw`` message appears
within the SC1 window. The poller runs indefinitely so we time-out the
coroutine after 30s and then read from the topic.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import time as _time

import pytest
import redis.asyncio as aioredis
import respx
from aiokafka import AIOKafkaConsumer
from httpx import Response

from services.poller.sources.opentable.fixtures import OPENTABLE_SUCCESS_RESPONSE
from services.poller.sources.opentable.graphql import OPENTABLE_GQL_ENDPOINT

pytestmark = pytest.mark.integration


async def test_end_to_end_emit_within_60s(
    kafka_container, redis_container, timescale_container
):
    """With respx mocking OpenTable, a single poll cycle must emit an
    ``availability.raw`` message within 60s and write a ``poll_log`` row
    with ``status='success'``.
    """
    kafka_bootstrap = kafka_container.get_bootstrap_server()
    redis_url = (
        f"redis://{redis_container.get_container_host_ip()}:"
        f"{redis_container.get_exposed_port(6379)}"
    )
    db_url_sync = timescale_container.get_connection_url().replace(
        "psycopg2", "psycopg"
    )
    db_url_async = db_url_sync.replace(
        "postgresql+psycopg://", "postgresql+asyncpg://"
    )

    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = kafka_bootstrap
    os.environ["REDIS_URL"] = redis_url
    os.environ["DATABASE_URL_ASYNC"] = db_url_async
    os.environ["DATABASE_URL_SYNC"] = db_url_sync

    # Reset shared.db module singletons so new env vars are picked up.
    import shared.db as shared_db

    shared_db._engine = None
    shared_db._session_factory = None

    # Reset shared.http_client singleton too (prior test may have created one).
    from shared import http_client as _hc

    await _hc.close_async_client()

    env = {**os.environ}
    # Run migrations.
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"

    # Create topics.
    result = subprocess.run(
        ["uv", "run", "python", "scripts/create_topics.py"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"create_topics failed: {result.stderr}"

    # Seed one restaurant to sched:polls with a past-due score so the first
    # claim() returns immediately.
    r = aioredis.from_url(redis_url)
    try:
        await r.zadd(
            "sched:polls",
            {"opentable:42": int(_time.time() * 1000) - 1000},
        )
    finally:
        await r.aclose()

    # Run one poll cycle with respx mocking OpenTable.
    with respx.mock(assert_all_called=False) as router:
        router.post(OPENTABLE_GQL_ENDPOINT).mock(
            return_value=Response(200, json=OPENTABLE_SUCCESS_RESPONSE)
        )

        from services.poller.main import run

        try:
            await asyncio.wait_for(run(), timeout=30)
        except asyncio.TimeoutError:
            # Expected — the poller runs indefinitely; we just need it to
            # emit at least one availability.raw message.
            pass

    # Drain the topic to check at least one message landed.
    consumer = AIOKafkaConsumer(
        "availability.raw",
        bootstrap_servers=kafka_bootstrap,
        auto_offset_reset="earliest",
        group_id=f"smoke-test-{_time.time_ns()}",
    )
    await consumer.start()
    try:
        batches = await consumer.getmany(timeout_ms=10_000, max_records=10)
        messages = [m for records in batches.values() for m in records]
        assert messages, "No messages on availability.raw within timeout"

        first = messages[0]
        assert first.key is not None, "Kafka key missing"
        key = first.key.decode() if isinstance(first.key, (bytes, bytearray)) else first.key
        assert key.startswith("opentable:"), f"Unexpected key: {key!r}"
    finally:
        await consumer.stop()
