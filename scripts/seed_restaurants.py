#!/usr/bin/env python
"""
Idempotent restaurant seed script (D-15, D-16, D-19).
Reads scripts/seed/restaurants.yml, upserts into restaurants table,
and populates sched:polls ZSET with initial poll scores.

Usage: uv run python scripts/seed_restaurants.py
Or:    make seed
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

from shared.redis_keys import SCHED_POLLS, job as make_job

YAML_PATH = Path("scripts/seed/restaurants.yml")


async def seed(
    db_url: str | None = None,
    redis_url: str | None = None,
) -> int:
    """
    Upsert restaurants from YAML and seed sched:polls.
    Returns number of restaurants processed.
    """
    db_url = db_url or os.getenv(
        "DATABASE_URL_ASYNC",
        "postgresql+asyncpg://mise:mise@localhost:5432/mise",
    )
    redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")

    data = yaml.safe_load(YAML_PATH.read_text())
    restaurants: list[dict[str, Any]] = data["restaurants"]

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    r = redis.from_url(redis_url)
    try:
        async with async_session() as session:
            for rest in restaurants:
                # Derive (source, platform_id) from YAML fields (D-15).
                source: str | None = None
                platform_id: str | None = None
                if rest.get("opentable_rid") is not None:
                    source = "opentable"
                    platform_id = str(rest["opentable_rid"])
                elif rest.get("resy_venue_id") is not None:
                    source = "resy"
                    platform_id = str(rest["resy_venue_id"])
                else:
                    raise ValueError(
                        f"Restaurant {rest.get('slug')!r} missing both "
                        f"opentable_rid and resy_venue_id"
                    )

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
                if source == "opentable":
                    score = int(time.time() * 1000) + int(random.uniform(0, 90_000))
                    await r.zadd(
                        SCHED_POLLS,
                        {make_job("opentable", int(platform_id)): score},
                    )

            await session.commit()

        ot_count = len(
            [rest for rest in restaurants if rest.get("opentable_rid") is not None]
        )
        print(
            f"Seeded {len(restaurants)} restaurants "
            f"({ot_count} with OpenTable RIDs in sched:polls)"
        )
        return len(restaurants)

    finally:
        await r.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
