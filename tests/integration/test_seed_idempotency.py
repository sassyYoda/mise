"""Integration: SC3 — seed populates all fields and sched:polls ZSET. Stub filled by Plan 05."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 05 (seed script)")
async def test_seed_populates_all_fields_and_zset(redis_container, timescale_container):
    """
    Run seed_restaurants.py against testcontainers Postgres + Redis.
    Assert: COUNT(*) FROM restaurants WHERE source='opentable' AND platform_id IS NOT NULL
              AND neighborhood IS NOT NULL AND cuisine IS NOT NULL
              AND price_tier IS NOT NULL AND cover_photo_url IS NOT NULL >= 50.
    Assert: ZCARD sched:polls >= 50.
    Run twice; assert idempotency (count stays the same on second run).
    """
    raise NotImplementedError
