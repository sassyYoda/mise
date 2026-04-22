"""Integration: Pitfall 18 — Redis maxmemory-policy = noeviction. Stub filled by Plan 02."""
import pytest


@pytest.mark.skip(reason="Wave-0 stub — implemented in Plan 02 (docker-compose)")
async def test_eviction_policy_is_noeviction(redis_container):
    """
    Connect to testcontainers Redis.
    Run: CONFIG GET maxmemory-policy.
    Assert the returned value is 'noeviction'.
    """
    raise NotImplementedError
