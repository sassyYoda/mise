"""Integration: Pitfall 18 — Redis maxmemory-policy = noeviction.

The ``redis_container`` conftest fixture already sets
``maxmemory-policy=noeviction`` at startup; this test verifies the setting
sticks so a future drift (e.g. in ops/docker-compose.yml) trips CI.
"""
from __future__ import annotations

import pytest
import redis

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def sync_redis_client(redis_container):
    port = redis_container.get_exposed_port(6379)
    host = redis_container.get_container_host_ip()
    return redis.Redis(host=host, port=port, decode_responses=True)


def test_eviction_policy_is_noeviction(sync_redis_client):
    """Redis must have ``maxmemory-policy = noeviction`` (Pitfall 18, D-03)."""
    policy = sync_redis_client.config_get("maxmemory-policy")
    assert policy.get("maxmemory-policy") == "noeviction", (
        f"Expected noeviction, got {policy}"
    )
