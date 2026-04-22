"""Integration: SC3 — seed populates all fields and ``sched:polls`` ZSET; idempotent.

Runs ``scripts/seed_restaurants.py`` twice against testcontainers Postgres +
Redis and asserts (a) all required columns are populated, (b) the
``sched:polls`` ZSET has >=1 entry, and (c) the row count is unchanged by
the second run (UPSERT idempotency).
"""
from __future__ import annotations

import os
import subprocess

import asyncpg
import pytest
import redis.asyncio as aioredis

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def db_url_sync(timescale_container):
    """SQLAlchemy+psycopg driver URL for Alembic."""
    return timescale_container.get_connection_url().replace("psycopg2", "psycopg")


@pytest.fixture(scope="module")
def db_url_async(db_url_sync):
    """SQLAlchemy+asyncpg driver URL for seed script."""
    return db_url_sync.replace("postgresql+psycopg://", "postgresql+asyncpg://")


@pytest.fixture(scope="module")
def asyncpg_dsn(timescale_container):
    """Plain PG DSN (no SQLAlchemy prefix) for asyncpg.connect()."""
    host = timescale_container.get_container_host_ip()
    port = timescale_container.get_exposed_port(5432)
    return f"postgresql://mise:mise@{host}:{port}/mise"


@pytest.fixture(scope="module")
def redis_url(redis_container):
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}/0"


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


def _run_seed(db_url_async: str, redis_url: str) -> None:
    env = {
        **os.environ,
        "DATABASE_URL_ASYNC": db_url_async,
        "REDIS_URL": redis_url,
    }
    result = subprocess.run(
        ["uv", "run", "python", "scripts/seed_restaurants.py"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"seed failed: {result.stderr}"


async def test_seed_populates_all_fields_and_zset(
    asyncpg_dsn, db_url_async, redis_url
):
    _run_seed(db_url_async, redis_url)

    conn = await asyncpg.connect(asyncpg_dsn)
    try:
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM restaurants
            WHERE source = 'opentable'
              AND platform_id IS NOT NULL
              AND neighborhood IS NOT NULL
              AND cuisine IS NOT NULL
              AND price_tier IS NOT NULL
              AND cover_photo_url IS NOT NULL
            """
        )
    finally:
        await conn.close()

    # Production SC3 requires >=50; CI may run against a stub YAML so we
    # only assert >=1 here and leave the >=50 gate to scripts/verify_seed.py.
    assert count >= 1, f"No restaurants seeded (count={count})"

    r = aioredis.from_url(redis_url)
    try:
        zcard = await r.zcard("sched:polls")
        assert zcard >= 1, "sched:polls is empty"
    finally:
        await r.aclose()


async def test_seed_idempotent(asyncpg_dsn, db_url_async, redis_url):
    """Running seed twice produces the same row count (no duplicates)."""
    _run_seed(db_url_async, redis_url)
    conn = await asyncpg.connect(asyncpg_dsn)
    try:
        count_first = await conn.fetchval("SELECT COUNT(*) FROM restaurants")
    finally:
        await conn.close()

    _run_seed(db_url_async, redis_url)
    conn = await asyncpg.connect(asyncpg_dsn)
    try:
        count_second = await conn.fetchval("SELECT COUNT(*) FROM restaurants")
    finally:
        await conn.close()

    assert count_first == count_second, (
        f"Seed not idempotent: first={count_first}, second={count_second}"
    )
    assert count_first >= 1
