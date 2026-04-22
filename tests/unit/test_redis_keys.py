"""Unit tests for shared.redis_keys constants and helpers."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from shared.redis_keys import (
    SCHED_POLLS,
    SCHED_POLLS_INFLIGHT,
    POLL_VISIBILITY_TIMEOUT_MS,
    POLL_INTERVAL_SECONDS,
    POLL_JITTER_FRACTION,
    job,
    set_nx_ex,
)


def test_sched_polls_constant():
    assert SCHED_POLLS == "sched:polls"


def test_sched_polls_inflight_constant():
    assert SCHED_POLLS_INFLIGHT == "sched:polls:inflight"


def test_job_descriptor_format():
    assert job("opentable", 42) == "opentable:42"
    assert job("resy", 123) == "resy:123"


@pytest.mark.asyncio
async def test_set_nx_ex_uses_single_atomic_call():
    """set_nx_ex MUST call r.set with nx=True and ex= in a single call (Pitfall 7)."""
    mock_redis = AsyncMock()
    mock_redis.set.return_value = True
    result = await set_nx_ex(mock_redis, "testkey", "testval", 60)
    mock_redis.set.assert_called_once_with("testkey", "testval", nx=True, ex=60)
    assert result is True


@pytest.mark.asyncio
async def test_set_nx_ex_returns_false_when_key_exists():
    mock_redis = AsyncMock()
    mock_redis.set.return_value = None  # Redis returns None when NX fails
    result = await set_nx_ex(mock_redis, "existing", "val", 60)
    assert result is False


def test_lua_scripts_are_non_empty_strings():
    from shared.redis_keys import CLAIM_POLL_LUA, RELEASE_POLL_LUA, REAP_INFLIGHT_LUA
    assert isinstance(CLAIM_POLL_LUA, str) and len(CLAIM_POLL_LUA) > 50
    assert isinstance(RELEASE_POLL_LUA, str) and len(RELEASE_POLL_LUA) > 30
    assert isinstance(REAP_INFLIGHT_LUA, str) and len(REAP_INFLIGHT_LUA) > 50


def test_lua_claim_uses_zrangebyscore():
    from shared.redis_keys import CLAIM_POLL_LUA
    assert "ZRANGEBYSCORE" in CLAIM_POLL_LUA
    assert "ZADD" in CLAIM_POLL_LUA
    assert "ZREM" in CLAIM_POLL_LUA


def test_constants_values():
    from shared.redis_keys import (
        POLL_VISIBILITY_TIMEOUT_MS,
        POLL_INTERVAL_SECONDS,
        POLL_JITTER_FRACTION,
    )
    assert POLL_VISIBILITY_TIMEOUT_MS == 60_000
    assert POLL_INTERVAL_SECONDS == 90
    assert abs(POLL_JITTER_FRACTION - 0.15) < 0.001
