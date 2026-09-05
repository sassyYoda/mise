"""Integration: STATE-05 — migration 0008 on a live TimescaleDB hypertable.

Carries standing regression guards for two blocking corrections reproduced in research:
B-2 (a unique index on a hypertable must include the partitioning column ``time``) and
B-3 (a PK of ``(time, restaurant_id)`` collides when one poll confirms two slots).
"""
import contextlib
import os
import subprocess
import uuid
from datetime import UTC, datetime
from datetime import date as date_cls

import asyncpg
import pytest

from tests.integration.conftest import apply_migrations

pytestmark = pytest.mark.integration

INDEX_NAME = "uq_availability_events_event_id_time"
TIME_A = datetime(2026, 5, 1, 23, 0, tzinfo=UTC)


@pytest.fixture(scope="module", autouse=True)
def migrated(db_urls):
    """Apply every migration, including 0008, against the module's container."""
    apply_migrations({**os.environ, "DATABASE_URL_SYNC": db_urls["sync"]})
    return db_urls


async def _insert(conn, *, event_id, time_, restaurant_id=42, on_conflict=False):
    conflict = ' ON CONFLICT (event_id, "time") DO NOTHING' if on_conflict else ""
    await conn.execute(
        'INSERT INTO availability_events '
        '("time", restaurant_id, source, date, party_size, event_id) '
        "VALUES ($1, $2, 'opentable', $3, 2, $4)" + conflict,
        time_, restaurant_id, date_cls(2026, 5, 1), event_id,
    )


@pytest.mark.asyncio
async def test_event_id_column_is_uuid_not_null(db_urls):
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        row = await conn.fetchrow(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'availability_events' AND column_name = 'event_id'"
        )
        assert row is not None, "event_id column missing — migration 0008 did not apply"
        assert row["data_type"] == "uuid"
        assert row["is_nullable"] == "NO"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_unique_index_covers_event_id_and_time(db_urls):
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        indexdef = await conn.fetchval(
            "SELECT indexdef FROM pg_indexes "
            "WHERE tablename = 'availability_events' AND indexname = $1",
            INDEX_NAME,
        )
        assert indexdef is not None, f"{INDEX_NAME} missing"
        assert "UNIQUE" in indexdef
        assert "event_id" in indexdef
        assert "time" in indexdef
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_b2_guard_unique_index_without_time_is_rejected(db_urls):
    """Research B-2, reproduced: the literal D-48 index shape cannot exist here."""
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        with pytest.raises(Exception) as exc_info:
            await conn.execute(
                "CREATE UNIQUE INDEX probe_rid_event ON availability_events "
                "(restaurant_id, event_id)"
            )
        assert "used in partitioning" in str(exc_info.value)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_b3_guard_one_poll_confirming_two_slots_writes_two_rows(db_urls):
    """Research B-3: same ("time", restaurant_id), different event_id — both must insert."""
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        a, b = uuid.uuid4(), uuid.uuid4()
        await _insert(conn, event_id=a, time_=TIME_A)
        await _insert(conn, event_id=b, time_=TIME_A)

        count = await conn.fetchval(
            'SELECT count(*) FROM availability_events WHERE "time" = $1 AND restaurant_id = 42',
            TIME_A,
        )
        assert count == 2
    finally:
        await conn.execute('DELETE FROM availability_events WHERE "time" = $1', TIME_A)
        await conn.close()


@pytest.mark.asyncio
async def test_on_conflict_event_id_time_is_idempotent(db_urls):
    """The arbiter names both index columns, so a redelivered emit inserts once."""
    conn = await asyncpg.connect(db_urls["dsn"])
    time_b = datetime(2026, 5, 2, 23, 0, tzinfo=UTC)
    try:
        event_id = uuid.uuid4()
        await _insert(conn, event_id=event_id, time_=time_b, on_conflict=True)
        await _insert(conn, event_id=event_id, time_=time_b, on_conflict=True)

        count = await conn.fetchval(
            "SELECT count(*) FROM availability_events WHERE event_id = $1", event_id
        )
        assert count == 1
    finally:
        await conn.execute('DELETE FROM availability_events WHERE "time" = $1', time_b)
        await conn.close()


@pytest.mark.asyncio
async def test_column_comments_record_the_semantics(db_urls):
    """D-48 / B-5 day_of_week convention and D-52 restaurant_id meaning live in the DB."""
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        rows = await conn.fetch(
            """
            SELECT a.attname,
                   col_description('availability_events'::regclass, a.attnum) AS comment
            FROM pg_attribute a
            WHERE a.attrelid = 'availability_events'::regclass
              AND a.attname IN ('day_of_week', 'restaurant_id')
            """
        )
        comments = {r["attname"]: (r["comment"] or "") for r in rows}
        assert "0=Sun" in comments["day_of_week"], comments["day_of_week"]
        assert "platform" in comments["restaurant_id"].lower(), comments["restaurant_id"]
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_reapplying_head_is_a_no_op(db_urls):
    """Idempotency edge (STATE-05): a second `upgrade head` changes nothing."""
    env = {**os.environ, "DATABASE_URL_SYNC": db_urls["sync"]}
    apply_migrations(env)

    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        assert await conn.fetchval(
            "SELECT count(*) FROM pg_indexes WHERE indexname = $1", INDEX_NAME
        ) == 1
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_downgrade_then_upgrade_restores_the_same_schema(db_urls):
    """A real downgrade() exists and the round trip is lossless.

    The restore is in a `finally` (WR-07). The container is MODULE-scoped, so a failure
    between the downgrade and `apply_migrations` used to leave the shared database at
    revision 0007 with no `event_id` column, and every later test in this module then failed
    for an unrelated reason — burying the real failure behind collateral damage whose
    membership varies with collection order.
    """
    env = {**os.environ, "DATABASE_URL_SYNC": db_urls["sync"]}
    result = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "-1"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"downgrade failed: {result.stderr}"

    try:
        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            assert await conn.fetchval(
                "SELECT count(*) FROM pg_indexes WHERE indexname = $1", INDEX_NAME
            ) == 0
            assert await conn.fetchval(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name = 'availability_events' AND column_name = 'event_id'"
            ) == 0
        finally:
            await conn.close()
    finally:
        apply_migrations(env)

    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        assert await conn.fetchval(
            "SELECT count(*) FROM pg_indexes WHERE indexname = $1", INDEX_NAME
        ) == 1
        row = await conn.fetchrow(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'availability_events' AND column_name = 'event_id'"
        )
        assert row["data_type"] == "uuid" and row["is_nullable"] == "NO"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_a_non_empty_table_is_refused_not_deleted(db_urls):
    """CR-03: 0008 must never `DELETE FROM availability_events`.

    The original migration added `event_id` nullable and then deleted every row where it
    was NULL — which is every pre-existing row. On any database that already held rows,
    `alembic upgrade head` destroyed the whole hypertable's contents with no backup, no
    count and no log. It must fail loudly instead, leaving the rows untouched.
    """
    env = {**os.environ, "DATABASE_URL_SYNC": db_urls["sync"]}
    legacy_time = datetime(2026, 5, 3, 23, 0, tzinfo=UTC)

    downgraded = subprocess.run(
        ["uv", "run", "alembic", "downgrade", "-1"],
        env=env, capture_output=True, text=True,
    )
    assert downgraded.returncode == 0, f"downgrade failed: {downgraded.stderr}"

    # The restore is in a `finally` (WR-07), and this test is the reason it matters most:
    # `assert failed.returncode != 0` is exactly what fails if someone reintroduces the
    # DELETE, and that failure used to leave the module's shared database at revision 0007.
    try:
        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            # A pre-0008 row: no event_id column exists at this revision.
            await conn.execute(
                'INSERT INTO availability_events '
                '("time", restaurant_id, source, date, party_size) '
                "VALUES ($1, 4242, 'opentable', $2, 2)",
                legacy_time, date_cls(2026, 5, 3),
            )

            failed = subprocess.run(
                ["uv", "run", "alembic", "upgrade", "head"],
                env=env, capture_output=True, text=True,
            )
            assert failed.returncode != 0, "0008 must refuse to run against a non-empty table"
            assert "pre-0008 row" in failed.stderr + failed.stdout, (
                f"expected the explicit refusal; got {failed.stderr[-2000:]!r}"
            )

            survivors = await conn.fetchval(
                'SELECT count(*) FROM availability_events WHERE "time" = $1', legacy_time
            )
            assert survivors == 1, "the migration deleted a row it was refusing to migrate"
        finally:
            # suppress(Exception) around the cleanup (IN-06): if the failure that reached this
            # finally was itself a connection failure, an unguarded DELETE raises and REPLACES
            # the original AssertionError — the same buried-failure problem WR-07 fixed one
            # level up. The close is still unconditional.
            with contextlib.suppress(Exception):
                await conn.execute(
                    'DELETE FROM availability_events WHERE "time" = $1', legacy_time
                )
            await conn.close()
    finally:
        # Restore the module's schema for anything that runs after this test.
        apply_migrations(env)
