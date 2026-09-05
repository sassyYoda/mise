"""Unit: WR-04 — a startup that fails partway must not leak the resources it acquired.

`main.run()`'s docstring promised "nested try/finally teardown", but there was exactly one
`try/finally` and it started AFTER Redis, the scheduler, the producer and the consumer had all
been constructed. A missing Kafka topic — the documented `_assert_topics_exist` failure — left
the Redis connection open; a failing `make_consumer` left a started producer behind too.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.state_machine import main


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    client = AsyncMock()
    monkeypatch.setattr(main.redis, "from_url", lambda url: client)
    return client


@pytest.mark.asyncio
async def test_a_missing_topic_still_closes_redis(monkeypatch, fake_redis) -> None:
    """The documented startup-guard path (D-27) must not leak the Redis connection."""
    async def _boom(bootstrap_servers: str) -> None:
        raise RuntimeError("Kafka topics missing: ['availability.events']")

    monkeypatch.setattr(main, "_assert_topics_exist", _boom)

    with pytest.raises(RuntimeError, match="topics missing"):
        await main.run()

    assert fake_redis.aclose.await_count == 1, "the Redis connection was leaked"


@pytest.mark.asyncio
async def test_a_failing_consumer_closes_redis_and_the_producer(
    monkeypatch, fake_redis
) -> None:
    """Teardown is LIFO and covers every resource acquired before the failure."""
    producer = AsyncMock()

    async def _ok(bootstrap_servers: str) -> None:
        return None

    async def _make_producer(bootstrap_servers: str) -> AsyncMock:
        return producer

    async def _make_consumer(*topics: str, **kwargs: object) -> None:
        raise RuntimeError("broker refused the group join")

    monkeypatch.setattr(main, "_assert_topics_exist", _ok)
    monkeypatch.setattr(main, "make_producer", _make_producer)
    monkeypatch.setattr(main, "make_consumer", _make_consumer)

    with pytest.raises(RuntimeError, match="group join"):
        await main.run()

    assert producer.stop.await_count == 1, "the started producer was leaked"
    assert fake_redis.aclose.await_count == 1, "the Redis connection was leaked"


# -- WR-05: the SQLAlchemy async engine must be disposed on shutdown --


@pytest.mark.asyncio
async def test_the_db_engine_is_disposed_even_when_startup_fails(
    monkeypatch, fake_redis
) -> None:
    """`persistence` creates the engine lazily and nothing else ever disposes it."""
    disposed: list[str] = []

    async def _dispose() -> None:
        disposed.append("disposed")

    async def _boom(bootstrap_servers: str) -> None:
        raise RuntimeError("Kafka topics missing: ['availability.events']")

    monkeypatch.setattr(main, "dispose_engine", _dispose)
    monkeypatch.setattr(main, "_assert_topics_exist", _boom)

    with pytest.raises(RuntimeError, match="topics missing"):
        await main.run()

    assert disposed == ["disposed"], "the asyncpg pool was never closed"


@pytest.mark.asyncio
async def test_dispose_engine_is_a_no_op_without_an_engine() -> None:
    """Safe on a service that never wrote a row, and safe to call twice."""
    import shared.db as shared_db

    original_engine = shared_db._engine
    original_factory = shared_db._session_factory
    try:
        shared_db._engine = None
        shared_db._session_factory = None
        await shared_db.dispose_engine()
        await shared_db.dispose_engine()
    finally:
        shared_db._engine = original_engine
        shared_db._session_factory = original_factory


# -- WR-13: the crash-hook interlock must fail CLOSED --


@pytest.mark.parametrize(
    "env_value",
    [None, "prod", "production", "PROD", "Production", "staging", "", "  "],
    ids=["unset", "prod", "production", "upper", "mixed", "staging", "empty", "blank"],
)
@pytest.mark.asyncio
async def test_the_crash_hook_is_refused_outside_the_allowlist(
    monkeypatch, fake_redis, env_value
) -> None:
    """`env_name() == 'prod'` armed a SIGKILL hook for every one of these."""
    monkeypatch.setenv("MISE_CRASH_AFTER", "state_write")
    if env_value is None:
        monkeypatch.delenv("ENV", raising=False)
    else:
        monkeypatch.setenv("ENV", env_value)

    with pytest.raises(RuntimeError, match="MISE_CRASH_AFTER"):
        await main.run()

    assert fake_redis.aclose.await_count == 0, "the guard must run before anything is acquired"


@pytest.mark.parametrize("env_value", ["dev", "test", "ci", "local", "TEST", " dev "])
@pytest.mark.asyncio
async def test_the_crash_hook_is_allowed_in_named_non_production_environments(
    monkeypatch, env_value
) -> None:
    """The chaos test has to be able to arm it; only the interlock changed, not the feature."""
    from services.state_machine.config import crash_hook_allowed

    monkeypatch.setenv("ENV", env_value)
    assert crash_hook_allowed() is True


@pytest.mark.asyncio
async def test_no_hook_means_no_guard(monkeypatch, fake_redis) -> None:
    """A production service without the variable set is unaffected by the interlock."""
    async def _boom(bootstrap_servers: str) -> None:
        raise RuntimeError("Kafka topics missing: ['availability.events']")

    monkeypatch.delenv("MISE_CRASH_AFTER", raising=False)
    monkeypatch.setenv("ENV", "prod")
    monkeypatch.setattr(main, "_assert_topics_exist", _boom)

    with pytest.raises(RuntimeError, match="topics missing"):
        await main.run()
