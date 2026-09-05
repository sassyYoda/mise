"""Integration: the 03-03 tracer — migration 0009 plus a two-source seed produces a Resy job.

This file is the end-to-end slice for the whole plan. It proves, against a live
TimescaleDB container, that the three hard failures research reproduced are gone:

  * research B-5 — a second `restaurants` row for the same restaurant on a different
    source collided with `UNIQUE(slug)` (`restaurants_slug_key`), so the Resy branch of
    `scripts/seed_restaurants.py` was unreachable and no Resy job could ever exist.
  * research B-4 — the seed's `resy_venue_id` values were URL slugs, so even a reachable
    branch would have enqueued `resy:carbone-new-york-new-york`, which `poll_loop` cannot
    parse and — worse — does not release.
  * D-63 — an unconfigured deployment must not acquire a Resy job at all.

It also carries the standing guard for T-03-12: 0009 refuses to run against a duplicate
`(slug, source)` pair rather than deleting a row to force the constraint through.

Test order in this file is load-bearing. The `alembic downgrade -1` tests restore
`UNIQUE(slug)`, which fails outright once two rows share a slug, so every test that
creates a shared slug either cleans up after itself or runs after the downgrade tests.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import textwrap
from pathlib import Path

import asyncpg
import pytest
import redis.asyncio as aioredis

from tests.integration.conftest import apply_migrations

pytestmark = pytest.mark.integration

CONSTRAINT_NAME = "uq_restaurants_slug_source"
OLD_CONSTRAINT_NAME = "restaurants_slug_key"
OLD_INDEX_NAME = "ix_restaurants_slug"

# Deliberately outside the shipped seed's 900_000_000+ OpenTable placeholder range and
# unrelated to any real Resy venue: this fixture never leaves the test container.
TRACER_SLUG = "tracer-two-source"
TRACER_OT_RID = 910000001
TRACER_RESY_VENUE_ID = 810000001


@pytest.fixture(scope="module", autouse=True)
def migrated(db_urls: dict[str, str]) -> dict[str, str]:
    """Apply every migration, including 0009, against the module's container."""
    apply_migrations({**os.environ, "DATABASE_URL_SYNC": db_urls["sync"]})
    return db_urls


def _alembic(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "alembic", *args], env=env, capture_output=True, text=True
    )


async def _insert(
    conn: asyncpg.Connection,
    *,
    slug: str,
    source: str,
    platform_id: str,
    name: str = "Tracer",
) -> None:
    await conn.execute(
        "INSERT INTO restaurants "
        "(source, platform_id, name, slug, neighborhood, cuisine, price_tier, "
        " cover_photo_url, created_at) "
        "VALUES ($1, $2, $3, $4, 'Test', 'Test', 2, 'https://example.test/x.jpg', NOW())",
        source, platform_id, name, slug,
    )


async def _delete_slug(conn: asyncpg.Connection, slug: str) -> None:
    with contextlib.suppress(Exception):
        await conn.execute("DELETE FROM restaurants WHERE slug = $1", slug)


# --------------------------------------------------------------------------------------
# Schema shape
# --------------------------------------------------------------------------------------


async def test_composite_constraint_replaced_both_slug_uniqueness_declarations(db_urls):
    """0003 declared UNIQUE(slug) TWICE — as a column constraint and as an index (B-5)."""
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        definition = await conn.fetchval(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'restaurants'::regclass AND conname = $1",
            CONSTRAINT_NAME,
        )
        assert definition is not None, f"{CONSTRAINT_NAME} missing — 0009 did not apply"
        assert "UNIQUE" in definition
        # Column ORDER is part of the contract only insofar as both are present; assert
        # membership rather than the rendered order so a future reorder is not a failure.
        assert "slug" in definition and "source" in definition, definition

        constraints = {
            row["conname"]
            for row in await conn.fetch(
                "SELECT conname FROM pg_constraint "
                "WHERE conrelid = 'restaurants'::regclass AND contype = 'u'"
            )
        }
        assert OLD_CONSTRAINT_NAME not in constraints, (
            "the column-level UNIQUE(slug) from 0003:18 survived — dropping only the index "
            "leaves the constraint enforcing the very thing 0009 exists to remove"
        )
        assert "uq_restaurants_source_platform_id" in constraints, (
            "the (source, platform_id) upsert/join key (D-52) must be untouched"
        )

        indexes = {
            row["indexname"]
            for row in await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'restaurants'"
            )
        }
        assert OLD_INDEX_NAME not in indexes, indexes
    finally:
        await conn.close()


async def test_the_constraint_records_why_it_exists(db_urls):
    """D-63b's meaning lives in the database, not only in a migration file."""
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        comment = await conn.fetchval(
            "SELECT obj_description(oid, 'pg_constraint') FROM pg_constraint "
            "WHERE conrelid = 'restaurants'::regclass AND conname = $1",
            CONSTRAINT_NAME,
        )
        assert comment and "source, platform_id" in comment, comment

        column_comment = await conn.fetchval(
            """
            SELECT col_description('restaurants'::regclass, a.attnum)
            FROM pg_attribute a
            WHERE a.attrelid = 'restaurants'::regclass AND a.attname = 'slug'
            """
        )
        assert column_comment and "ONE ROW PER SOURCE" in column_comment, column_comment
    finally:
        await conn.close()


async def test_one_slug_on_two_sources_is_now_legal(db_urls):
    """The exact insert that raised `duplicate key ... restaurants_slug_key` (B-5)."""
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        await _insert(conn, slug=TRACER_SLUG, source="opentable", platform_id="1")
        await _insert(conn, slug=TRACER_SLUG, source="resy", platform_id="2")

        sources = [
            row["source"]
            for row in await conn.fetch(
                "SELECT source FROM restaurants WHERE slug = $1 ORDER BY source",
                TRACER_SLUG,
            )
        ]
        assert sources == ["opentable", "resy"]
    finally:
        await _delete_slug(conn, TRACER_SLUG)
        await conn.close()


async def test_a_duplicate_slug_source_pair_is_still_rejected(db_urls):
    """Uniqueness was relaxed, not removed: one source may not claim one slug twice."""
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        await _insert(conn, slug=TRACER_SLUG, source="resy", platform_id="1")
        with pytest.raises(asyncpg.exceptions.UniqueViolationError) as exc_info:
            await _insert(conn, slug=TRACER_SLUG, source="resy", platform_id="2")
        assert CONSTRAINT_NAME in str(exc_info.value)
    finally:
        await _delete_slug(conn, TRACER_SLUG)
        await conn.close()


# --------------------------------------------------------------------------------------
# Migrating a database that is already at 0008 and already holds rows
# --------------------------------------------------------------------------------------


async def test_0009_applies_over_a_populated_0008_database(db_urls):
    """The real upgrade path: an existing deployment already holds 55 seeded rows.

    A migration that only works on an empty database is a migration nobody can run.
    """
    env = {**os.environ, "DATABASE_URL_SYNC": db_urls["sync"]}
    down = _alembic(env, "downgrade", "-1")
    assert down.returncode == 0, f"downgrade failed: {down.stderr}"

    try:
        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            # At 0008 the old uniqueness is back, and a second row for this slug is
            # impossible — which is precisely the defect.
            indexes = {
                row["indexname"]
                for row in await conn.fetch(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'restaurants'"
                )
            }
            assert OLD_INDEX_NAME in indexes, "downgrade did not restore ix_restaurants_slug"

            await _insert(conn, slug=TRACER_SLUG, source="opentable", platform_id="1")
            with pytest.raises(asyncpg.exceptions.UniqueViolationError):
                await _insert(conn, slug=TRACER_SLUG, source="resy", platform_id="2")
        finally:
            await conn.close()

        up = _alembic(env, "upgrade", "head")
        assert up.returncode == 0, f"0009 failed on a populated 0008 database: {up.stderr}"

        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            survived = await conn.fetchval(
                "SELECT count(*) FROM restaurants WHERE slug = $1", TRACER_SLUG
            )
            assert survived == 1, "0009 lost a pre-existing row"
            # And the row that was impossible a moment ago now inserts.
            await _insert(conn, slug=TRACER_SLUG, source="resy", platform_id="2")
        finally:
            await _delete_slug(conn, TRACER_SLUG)
            await conn.close()
    finally:
        apply_migrations(env)


async def test_the_preflight_guard_refuses_a_duplicate_rather_than_deleting_it(db_urls):
    """T-03-12 / the 0008 precedent: refuse loudly, never destroy to make an ALTER succeed.

    A duplicate `(slug, source)` pair cannot arise while UNIQUE(slug) holds, so the guard
    is only reachable in a database where someone dropped the slug uniqueness by hand.
    That database exists — it is the one where the operator was mid-way through doing this
    migration manually — and it is exactly where a silent `DELETE` would be unrecoverable.
    """
    env = {**os.environ, "DATABASE_URL_SYNC": db_urls["sync"]}
    down = _alembic(env, "downgrade", "-1")
    assert down.returncode == 0, f"downgrade failed: {down.stderr}"

    try:
        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            await conn.execute(f"DROP INDEX {OLD_INDEX_NAME}")
            await conn.execute(
                f"ALTER TABLE restaurants DROP CONSTRAINT {OLD_CONSTRAINT_NAME}"
            )
            await _insert(conn, slug=TRACER_SLUG, source="resy", platform_id="1")
            await _insert(conn, slug=TRACER_SLUG, source="resy", platform_id="2")

            failed = _alembic(env, "upgrade", "head")
            assert failed.returncode != 0, (
                "0009 must refuse to run against a duplicate (slug, source) pair"
            )
            output = failed.stdout + failed.stderr
            assert "duplicate (slug, source)" in output, output[-2000:]
            assert TRACER_SLUG in output, "the refusal must NAME the offending rows"
            assert "re-run `alembic upgrade head`" in output, "…and the remediation"

            survivors = await conn.fetchval(
                "SELECT count(*) FROM restaurants WHERE slug = $1", TRACER_SLUG
            )
            assert survivors == 2, "the migration deleted a row it was refusing to migrate"
        finally:
            # Put the hand-dropped 0008 uniqueness back BEFORE the restore below: the
            # guard did its job and stopped the migration at its first statement, so
            # `ix_restaurants_slug` is still missing and `apply_migrations` would fail on
            # `DROP INDEX` for an unrelated reason — burying this test's real result.
            await _delete_slug(conn, TRACER_SLUG)
            with contextlib.suppress(Exception):
                await conn.execute(
                    f"ALTER TABLE restaurants ADD CONSTRAINT {OLD_CONSTRAINT_NAME} "
                    "UNIQUE (slug)"
                )
            with contextlib.suppress(Exception):
                await conn.execute(
                    f"CREATE UNIQUE INDEX {OLD_INDEX_NAME} ON restaurants (slug)"
                )
            await conn.close()
    finally:
        apply_migrations(env)


# --------------------------------------------------------------------------------------
# The tracer proper: seed -> two rows + a Resy job
# --------------------------------------------------------------------------------------


def _write_tracer_yaml(tmp_path: Path) -> Path:
    """A two-entry seed file: one restaurant on both sources, one on OpenTable only."""
    path = tmp_path / "tracer_restaurants.yml"
    path.write_text(
        textwrap.dedent(
            f"""\
            restaurants:
              - name: "Tracer Two Source"
                slug: "{TRACER_SLUG}"
                neighborhood: "Test"
                cuisine: "Test"
                price_tier: 2
                cover_photo_url: "https://placeholder.mise.place/tracer.jpg"
                opentable_rid: {TRACER_OT_RID}
                resy_url_slug: "tracer-two-source-new-york"
                resy_venue_id: {TRACER_RESY_VENUE_ID}

              - name: "Tracer OpenTable Only"
                slug: "tracer-ot-only"
                neighborhood: "Test"
                cuisine: "Test"
                price_tier: 2
                cover_photo_url: "https://placeholder.mise.place/tracer2.jpg"
                opentable_rid: {TRACER_OT_RID + 1}
                resy_venue_id: null
            """
        )
    )
    return path


def _run_seed(
    db_url_async: str, redis_url: str, yaml_path: Path, *, resy_enabled: bool
) -> str:
    env = {
        **os.environ,
        "DATABASE_URL_ASYNC": db_url_async,
        "REDIS_URL": redis_url,
        "SEED_YAML_PATH": str(yaml_path),
        "RESY_ENABLED": "true" if resy_enabled else "false",
    }
    result = subprocess.run(
        ["uv", "run", "python", "scripts/seed_restaurants.py"],
        env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"seed failed: {result.stderr}"
    return result.stdout


async def _clean(db_urls: dict[str, str], redis_url: str) -> None:
    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        await conn.execute(
            "DELETE FROM restaurants WHERE slug IN ($1, 'tracer-ot-only')", TRACER_SLUG
        )
    finally:
        await conn.close()
    r = aioredis.from_url(redis_url)
    try:
        await r.zrem(
            "sched:polls",
            f"resy:{TRACER_RESY_VENUE_ID}",
            f"opentable:{TRACER_OT_RID}",
            f"opentable:{TRACER_OT_RID + 1}",
        )
    finally:
        await r.aclose()


async def test_seed_with_a_numeric_resy_id_produces_two_rows_and_a_resy_job(
    db_urls, redis_url, tmp_path
):
    """The tracer: YAML -> two rows sharing one slug -> `resy:{id}` in sched:polls."""
    await _clean(db_urls, redis_url)
    yaml_path = _write_tracer_yaml(tmp_path)
    try:
        stdout = _run_seed(db_urls["async"], redis_url, yaml_path, resy_enabled=True)
        assert "RESY_ENABLED=true" in stdout, stdout

        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            rows = await conn.fetch(
                "SELECT source, platform_id FROM restaurants WHERE slug = $1 "
                "ORDER BY source",
                TRACER_SLUG,
            )
            assert [(r["source"], r["platform_id"]) for r in rows] == [
                ("opentable", str(TRACER_OT_RID)),
                ("resy", str(TRACER_RESY_VENUE_ID)),
            ], "one entry must yield one row per source, both under the SAME human slug"
        finally:
            await conn.close()

        r = aioredis.from_url(redis_url)
        try:
            assert await r.zscore("sched:polls", f"resy:{TRACER_RESY_VENUE_ID}") is not None
            assert await r.zscore("sched:polls", f"opentable:{TRACER_OT_RID}") is not None
            # The OpenTable-only entry contributes no Resy job.
            assert await r.zscore("sched:polls", "resy:None") is None
        finally:
            await r.aclose()
    finally:
        await _clean(db_urls, redis_url)


async def test_the_two_source_seed_is_idempotent_in_the_table_and_the_zset(
    db_urls, redis_url, tmp_path
):
    """Re-running `make seed` must not double the rows or the jobs (D-15)."""
    await _clean(db_urls, redis_url)
    yaml_path = _write_tracer_yaml(tmp_path)
    try:
        _run_seed(db_urls["async"], redis_url, yaml_path, resy_enabled=True)

        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            first = await conn.fetchval(
                "SELECT count(*) FROM restaurants WHERE slug IN ($1, 'tracer-ot-only')",
                TRACER_SLUG,
            )
        finally:
            await conn.close()

        r = aioredis.from_url(redis_url)
        try:
            first_zcard = await r.zcard("sched:polls")
        finally:
            await r.aclose()

        _run_seed(db_urls["async"], redis_url, yaml_path, resy_enabled=True)

        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            second = await conn.fetchval(
                "SELECT count(*) FROM restaurants WHERE slug IN ($1, 'tracer-ot-only')",
                TRACER_SLUG,
            )
        finally:
            await conn.close()

        r = aioredis.from_url(redis_url)
        try:
            second_zcard = await r.zcard("sched:polls")
        finally:
            await r.aclose()

        assert first == 3, f"expected 2 rows + 1 OpenTable-only row, got {first}"
        assert second == first, f"seed not idempotent: {first} then {second}"
        assert second_zcard == first_zcard, (
            f"sched:polls grew on the second run: {first_zcard} then {second_zcard}"
        )
    finally:
        await _clean(db_urls, redis_url)


async def test_resy_disabled_seeds_no_resy_row_and_no_resy_job(
    db_urls, redis_url, tmp_path
):
    """D-63: the default configuration can neither seed a Resy job nor start a browser.

    Same YAML, same numeric venue id — only `RESY_ENABLED` differs, and that is enough for
    the Resy venue to be visibly ABSENT rather than silently polled.
    """
    await _clean(db_urls, redis_url)
    yaml_path = _write_tracer_yaml(tmp_path)
    try:
        stdout = _run_seed(db_urls["async"], redis_url, yaml_path, resy_enabled=False)
        assert "RESY_ENABLED=false" in stdout, stdout

        conn = await asyncpg.connect(db_urls["dsn"])
        try:
            resy_rows = await conn.fetchval(
                "SELECT count(*) FROM restaurants WHERE source = 'resy' AND slug = $1",
                TRACER_SLUG,
            )
            ot_rows = await conn.fetchval(
                "SELECT count(*) FROM restaurants WHERE source = 'opentable' "
                "AND slug = $1",
                TRACER_SLUG,
            )
        finally:
            await conn.close()
        assert resy_rows == 0, "RESY_ENABLED=false must not create a Resy row (D-63a)"
        assert ot_rows == 1, "…and must not disturb the OpenTable row"

        r = aioredis.from_url(redis_url)
        try:
            assert await r.zscore("sched:polls", f"resy:{TRACER_RESY_VENUE_ID}") is None
        finally:
            await r.aclose()
    finally:
        await _clean(db_urls, redis_url)


async def test_the_shipped_seed_file_enqueues_no_resy_job(db_urls, redis_url):
    """The prohibition, executable: every shipped id is null, so no Resy job can exist.

    Runs the REAL `scripts/seed/restaurants.yml` with `RESY_ENABLED=true` — the most
    permissive configuration there is — and asserts the queue still holds nothing Resy.
    A fabricated placeholder id anywhere in the file fails this test.
    """
    r = aioredis.from_url(redis_url)
    try:
        await r.delete("sched:polls")
    finally:
        await r.aclose()

    _run_seed(
        db_urls["async"], redis_url, Path("scripts/seed/restaurants.yml"),
        resy_enabled=True,
    )

    r = aioredis.from_url(redis_url)
    try:
        members = await r.zrange("sched:polls", 0, -1)
    finally:
        await r.aclose()

    decoded = [m.decode() if isinstance(m, bytes) else m for m in members]
    resy_members = [m for m in decoded if m.startswith("resy:")]
    assert resy_members == [], (
        f"an unresolved Resy venue reached the queue: {resy_members} — every "
        "resy_venue_id in the shipped seed must be null until a human resolves it (D-63a)"
    )
    assert len(decoded) == 55, f"the OpenTable membership changed: {len(decoded)}"

    conn = await asyncpg.connect(db_urls["dsn"])
    try:
        resy_rows = await conn.fetchval(
            "SELECT count(*) FROM restaurants WHERE source = 'resy'"
        )
    finally:
        await conn.close()
    assert resy_rows == 0
