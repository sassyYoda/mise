#!/usr/bin/env python
"""
Idempotent restaurant seed script (D-15, D-16, D-19, D-63, D-63a, D-63b).
Reads scripts/seed/restaurants.yml, upserts into restaurants table,
and populates sched:polls ZSET with initial poll scores.

One YAML entry may yield TWO rows — one per source — sharing one human slug, which
migration 0009 made legal by replacing UNIQUE(slug) with UNIQUE(slug, source) (D-63b).
The upsert key is still (source, platform_id) (D-52), never the slug.

The Resy row and the `resy:{venue_id}` job are created ONLY when the entry carries a real
integer `resy_venue_id` AND RESY_ENABLED is true (D-63a). Every id in the shipped YAML is
null pending a human resolution (scripts/resolve_resy_venue_ids.py), so with the shipped
data this script produces exactly the rows and the sched:polls membership it always did.

Usage: uv run python scripts/seed_restaurants.py
Or:    make seed
Env:   RESY_ENABLED=true        also seed the Resy rows/jobs (default false)
       SEED_YAML_PATH=<path>    read a different seed file (tests only)
"""
from __future__ import annotations

import asyncio
import os
import random
import time
from pathlib import Path
from typing import Any

import redis.asyncio as redis
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from services.poller.config import resy_enabled
from shared.redis_keys import SCHED_POLLS
from shared.redis_keys import job as make_job

YAML_PATH = Path("scripts/seed/restaurants.yml")

# Initial spread across workers, in ms — the same window the OpenTable branch has always
# used, so a Resy job is not born in a thundering herd with its OpenTable sibling.
INITIAL_SPREAD_MS = 90_000


def _numeric_venue_id(raw: object) -> int | None:
    """
    Return `raw` as a Resy venue id, or None when it is not one.

    `isinstance(raw, bool)` is excluded FIRST: bool is a subclass of int in Python, so
    `resy_venue_id: true` would otherwise seed the job `resy:1` — a real venue belonging to
    somebody else. A string is refused rather than coerced: every value in the shipped YAML
    was a URL slug until this plan, `int("carbone-new-york-new-york")` raises inside
    `poll_loop`, and the poller logs `invalid_restaurant_id` and continues WITHOUT releasing
    the job, so the job never leaves the inflight set (research B-4, T-03-10).
    """
    if raw is None or isinstance(raw, bool) or not isinstance(raw, int):
        return None
    return raw


def _source_pairs(rest: dict[str, Any], *, with_resy: bool) -> list[tuple[str, str]]:
    """
    Every (source, platform_id) row this YAML entry should produce.

    Was an `if/elif` that preferred OpenTable, which made the Resy branch unreachable for
    every entry that had both (research B-5) — the reason no Resy poll had ever existed.
    """
    pairs: list[tuple[str, str]] = []
    if rest.get("opentable_rid") is not None:
        pairs.append(("opentable", str(rest["opentable_rid"])))
    if with_resy:
        venue_id = _numeric_venue_id(rest.get("resy_venue_id"))
        if venue_id is not None:
            pairs.append(("resy", str(venue_id)))
    return pairs


async def seed(
    db_url: str | None = None,
    redis_url: str | None = None,
    yaml_path: Path | None = None,
) -> int:
    """
    Upsert restaurants from YAML and seed sched:polls.
    Returns number of restaurants processed.
    """
    # New names rather than reassignment, and an explicit `is not None` rather than `or`:
    # the parameters are declared `str | None`, so rebinding them keeps that declared type,
    # and mypy types `optional or fallback` as optional too. Both forms left every downstream
    # call typed as possibly-None under `mypy --strict`, which now covers scripts/ (IN-05).
    resolved_db_url: str = (
        db_url
        if db_url is not None
        else os.getenv(
            "DATABASE_URL_ASYNC",
            "postgresql+asyncpg://mise:mise@localhost:5432/mise",
        )
    )
    resolved_redis_url: str = (
        redis_url
        if redis_url is not None
        else os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )

    # SEED_YAML_PATH exists so an integration test can seed a two-row fixture without
    # editing the committed 55-entry file. `make seed` never sets it.
    resolved_yaml_path: Path = (
        yaml_path
        if yaml_path is not None
        else Path(os.getenv("SEED_YAML_PATH", str(YAML_PATH)))
    )
    data = yaml.safe_load(resolved_yaml_path.read_text())
    restaurants: list[dict[str, Any]] = data["restaurants"]

    # Read ONCE per run, not per entry: a flag that could change mid-run would produce a
    # half-Resy database, and the closing summary would not describe either half.
    with_resy = resy_enabled()

    # Counted from the rows actually written, not from the YAML: the closing summary
    # must describe what reached the database, or `make seed` reports a Resy fleet
    # that does not exist.
    rows_by_source: dict[str, int] = {}

    engine = create_async_engine(resolved_db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    r = redis.from_url(resolved_redis_url)
    try:
        async with async_session() as session:
            for rest in restaurants:
                # Derive every (source, platform_id) this entry yields (D-15, D-63a).
                # One entry may now produce TWO rows sharing one slug (D-63b).
                pairs = _source_pairs(rest, with_resy=with_resy)
                if not pairs:
                    # Unchanged contract: an entry that yields NO row at all is a data
                    # error. A null resy_venue_id is not — it is the expected state of all
                    # 55 entries until a human resolves them (D-63a), and it is why the
                    # message names opentable_rid alone as the required field.
                    raise ValueError(
                        f"Restaurant {rest.get('slug')!r} yields no (source, platform_id) "
                        f"pair: it needs an opentable_rid, or a numeric resy_venue_id with "
                        f"RESY_ENABLED=true (it has resy_venue_id="
                        f"{rest.get('resy_venue_id')!r}, RESY_ENABLED={with_resy})"
                    )

                for source, platform_id in pairs:
                    # Idempotent UPSERT keyed on (source, platform_id) UNIQUE constraint (D-15).
                    await session.execute(
                        text(
                            """
                            INSERT INTO restaurants
                                (source, platform_id, name, slug, neighborhood, cuisine,
                                 price_tier, cover_photo_url, date_range_days, party_sizes, created_at)
                            VALUES
                                (:source, :platform_id, :name, :slug, :neighborhood, :cuisine,
                                 :price_tier, :cover_photo_url, :date_range_days, :party_sizes, NOW())
                            ON CONFLICT (source, platform_id) DO UPDATE SET
                                name             = EXCLUDED.name,
                                slug             = EXCLUDED.slug,
                                neighborhood     = EXCLUDED.neighborhood,
                                cuisine          = EXCLUDED.cuisine,
                                price_tier       = EXCLUDED.price_tier,
                                cover_photo_url  = EXCLUDED.cover_photo_url,
                                date_range_days  = EXCLUDED.date_range_days,
                                party_sizes      = EXCLUDED.party_sizes
                            """
                        ),
                        {
                            "source": source,
                            "platform_id": platform_id,
                            "name": rest["name"],
                            "slug": rest["slug"],
                            "neighborhood": rest["neighborhood"],
                            "cuisine": rest["cuisine"],
                            "price_tier": rest["price_tier"],
                            "cover_photo_url": rest["cover_photo_url"],
                            "date_range_days": rest.get("date_range_days", 7),
                            "party_sizes": rest.get("party_sizes", [2, 4]),
                        },
                    )
                    # Add to sched:polls ZSET with initial spread (D-15, D-17).
                    # Score = now_ms + random jitter 0..90s for initial spread across workers.
                    # Both sources take the same spread; `pairs` has already applied the
                    # RESY_ENABLED + numeric-id gate, so there is no second gate here to
                    # disagree with the row that was just written.
                    score = int(time.time() * 1000) + int(
                        random.uniform(0, INITIAL_SPREAD_MS)
                    )
                    await r.zadd(
                        SCHED_POLLS,
                        {make_job(source, int(platform_id)): score},
                    )
                    rows_by_source[source] = rows_by_source.get(source, 0) + 1

            await session.commit()

        ot_count = rows_by_source.get("opentable", 0)
        resy_count = rows_by_source.get("resy", 0)
        unresolved = sum(
            1
            for rest in restaurants
            if rest.get("resy_url_slug") and _numeric_venue_id(rest.get("resy_venue_id")) is None
        )
        print(
            f"Seeded {len(restaurants)} restaurants "
            f"({ot_count} with OpenTable RIDs in sched:polls)"
        )
        print(
            f"Resy: RESY_ENABLED={str(with_resy).lower()}, {resy_count} row(s) and "
            f"{resy_count} job(s) in sched:polls, {unresolved} venue(s) still unresolved "
            f"(resy_venue_id is null — run scripts/resolve_resy_venue_ids.py)"
        )
        return len(restaurants)

    finally:
        await r.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
