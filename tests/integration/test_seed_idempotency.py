"""Integration: SC3 — seed populates all fields and ``sched:polls`` ZSET; idempotent.

Runs ``scripts/seed_restaurants.py`` twice against testcontainers Postgres +
Redis and asserts (a) all required columns are populated, (b) the
``sched:polls`` ZSET has >=1 entry, and (c) the row count is unchanged by
the second run (UPSERT idempotency).

03-03 added the Resy dimension at the bottom of this file. One YAML entry may now
produce TWO rows sharing one human slug (D-63b), and the second row plus its
``resy:{venue_id}`` job appear only when the entry carries a real integer
``resy_venue_id`` AND ``RESY_ENABLED`` is true (D-63a). The tests above this line are
unchanged and still pass with the shipped seed file, which is the point: every id in it
is null, so the default configuration produces exactly the rows and the ZSET membership
it always did.
"""
from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

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


def _run_seed(
    db_url_async: str,
    redis_url: str,
    *,
    yaml_path: Path | None = None,
    resy_enabled: bool = False,
) -> None:
    """Run the seed. Defaults reproduce the pre-03-03 invocation exactly."""
    env = {
        **os.environ,
        "DATABASE_URL_ASYNC": db_url_async,
        "REDIS_URL": redis_url,
        "RESY_ENABLED": "true" if resy_enabled else "false",
    }
    if yaml_path is not None:
        env["SEED_YAML_PATH"] = str(yaml_path)
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


# --------------------------------------------------------------------------------------
# The Resy dimension (03-03, D-63a/D-63b)
# --------------------------------------------------------------------------------------

RESY_SLUG = "seed-resy-dimension"
RESY_OT_RID = 920000001
RESY_VENUE_ID = 820000001


@pytest.fixture
def resy_yaml(tmp_path) -> Path:
    """One entry on both sources, with a RESOLVED numeric venue id.

    The shipped seed file cannot exercise this: every id in it is null, deliberately
    (D-63a), because a fabricated id would be a syntactically valid job pointing at a
    stranger's venue. So the two-source path is proven against a fixture instead, and the
    prohibition on the shipped file is asserted separately in test_migration_0009.py.
    """
    path = tmp_path / "resy_dimension.yml"
    path.write_text(
        textwrap.dedent(
            f"""\
            restaurants:
              - name: "Seed Resy Dimension"
                slug: "{RESY_SLUG}"
                neighborhood: "Test"
                cuisine: "Test"
                price_tier: 2
                cover_photo_url: "https://placeholder.mise.place/seed-resy.jpg"
                opentable_rid: {RESY_OT_RID}
                resy_url_slug: "seed-resy-dimension-new-york"
                resy_venue_id: {RESY_VENUE_ID}
            """
        )
    )
    return path


async def _resy_state(asyncpg_dsn: str, redis_url: str) -> tuple[list[str], object]:
    conn = await asyncpg.connect(asyncpg_dsn)
    try:
        sources = [
            row["source"]
            for row in await conn.fetch(
                "SELECT source FROM restaurants WHERE slug = $1 ORDER BY source",
                RESY_SLUG,
            )
        ]
    finally:
        await conn.close()

    r = aioredis.from_url(redis_url)
    try:
        score = await r.zscore("sched:polls", f"resy:{RESY_VENUE_ID}")
    finally:
        await r.aclose()
    return sources, score


async def _clean_resy(asyncpg_dsn: str, redis_url: str) -> None:
    conn = await asyncpg.connect(asyncpg_dsn)
    try:
        await conn.execute("DELETE FROM restaurants WHERE slug = $1", RESY_SLUG)
    finally:
        await conn.close()
    r = aioredis.from_url(redis_url)
    try:
        await r.zrem(
            "sched:polls", f"resy:{RESY_VENUE_ID}", f"opentable:{RESY_OT_RID}"
        )
    finally:
        await r.aclose()


async def test_resy_enabled_seeds_two_rows_and_one_job_idempotently(
    asyncpg_dsn, db_url_async, redis_url, resy_yaml
):
    """Seeding TWICE leaves exactly two rows sharing one slug and one `resy:` job.

    Idempotency here is not the same property as for OpenTable. The upsert key is
    (source, platform_id), so the two rows never collide with each other — but they DO
    share a slug, which was impossible before migration 0009 and is the whole reason this
    test exists.
    """
    await _clean_resy(asyncpg_dsn, redis_url)
    try:
        _run_seed(db_url_async, redis_url, yaml_path=resy_yaml, resy_enabled=True)
        first_sources, first_score = await _resy_state(asyncpg_dsn, redis_url)

        _run_seed(db_url_async, redis_url, yaml_path=resy_yaml, resy_enabled=True)
        second_sources, second_score = await _resy_state(asyncpg_dsn, redis_url)

        assert first_sources == ["opentable", "resy"], first_sources
        assert second_sources == first_sources, "the second run duplicated a row"
        assert first_score is not None, "no resy:{venue_id} job was enqueued"
        assert second_score is not None

        r = aioredis.from_url(redis_url)
        try:
            members = await r.zrange("sched:polls", 0, -1)
        finally:
            await r.aclose()
        decoded = [m.decode() if isinstance(m, bytes) else m for m in members]
        assert decoded.count(f"resy:{RESY_VENUE_ID}") == 1, decoded
    finally:
        await _clean_resy(asyncpg_dsn, redis_url)


async def test_resy_disabled_seeds_no_resy_row_and_no_resy_job(
    asyncpg_dsn, db_url_async, redis_url, resy_yaml
):
    """The default configuration, on the SAME data that produces a Resy job when enabled.

    D-63a gates the ROW as well as the job, not just the job. The alternative — write the
    row, withhold the job — leaves a `restaurants` row nothing polls and nothing closes,
    which reads to every downstream query in Phase 5/6 as a restaurant that is simply
    never available. Absent is honest; present-but-dead is not.
    """
    await _clean_resy(asyncpg_dsn, redis_url)
    try:
        _run_seed(db_url_async, redis_url, yaml_path=resy_yaml, resy_enabled=False)
        sources, score = await _resy_state(asyncpg_dsn, redis_url)

        assert sources == ["opentable"], f"RESY_ENABLED=false created a Resy row: {sources}"
        assert score is None, "RESY_ENABLED=false enqueued a Resy job"
    finally:
        await _clean_resy(asyncpg_dsn, redis_url)
