#!/usr/bin/env python
"""
Verify seed: assert >= 50 restaurants with all required fields in DB;
assert >= 50 entries in sched:polls ZSET (SC3, make verify-seed target).
"""
from __future__ import annotations

import asyncio
import os
import sys

import redis.asyncio as redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def verify() -> None:
    db_url = os.getenv(
        "DATABASE_URL_ASYNC",
        "postgresql+asyncpg://mise:mise@localhost:5432/mise",
    )
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    engine = create_async_engine(db_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    r = redis.from_url(redis_url)

    try:
        async with async_session() as session:
            result = await session.execute(
                text(
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
            )
            db_count = result.scalar_one()

        zcard = await r.zcard("sched:polls")

        print(f"Restaurants in DB with all fields: {db_count}")
        print(f"Entries in sched:polls: {zcard}")

        errors = []
        if db_count < 50:
            errors.append(f"Expected >= 50 restaurants in DB, got {db_count}")
        if zcard < 50:
            errors.append(f"Expected >= 50 entries in sched:polls, got {zcard}")

        if errors:
            for e in errors:
                print(f"FAIL: {e}", file=sys.stderr)
            sys.exit(1)
        else:
            print("SC3 verification PASSED")

    finally:
        await r.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(verify())
