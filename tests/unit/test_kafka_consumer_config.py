"""Unit tests for shared.kafka.make_consumer (D-47a, research B-1).

The locked D-47 wording passes topics as a *list*; ``AIOKafkaConsumer`` declares
``*topics`` (VAR_POSITIONAL) and a list raises ``TypeError: unhashable type: 'list'``.
These tests pin the corrected varargs form plus the manual-commit config that
Pitfall 4 / Pitfall 10 require.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from aiokafka import AIOKafkaConsumer


@pytest.mark.asyncio
async def test_make_consumer_config():
    """enable_auto_commit=False, auto_offset_reset='earliest', max_poll_records=1."""
    from shared.kafka import make_consumer

    with patch("shared.kafka.AIOKafkaConsumer") as MockConsumer:
        instance = AsyncMock()
        MockConsumer.return_value = instance
        instance.start = AsyncMock()
        await make_consumer("availability.raw", "polls.completed", group_id="state-machine")

        call_kwargs = MockConsumer.call_args.kwargs
        assert call_kwargs["enable_auto_commit"] is False
        assert call_kwargs["auto_offset_reset"] == "earliest"
        assert call_kwargs["max_poll_records"] == 1
        assert call_kwargs["group_id"] == "state-machine"
        assert call_kwargs["isolation_level"] == "read_uncommitted"
        # The shell wants raw bytes — a deserializer here would break replay byte-identity.
        assert "value_deserializer" not in call_kwargs
        # aiokafka has no such kwarg; it must not be reintroduced from the producer.
        assert "max_in_flight_requests_per_connection" not in call_kwargs
        instance.start.assert_awaited_once()


@pytest.mark.asyncio
async def test_make_consumer_passes_topics_as_varargs():
    """Topics reach the constructor positionally — a list argument would raise TypeError."""
    from shared.kafka import make_consumer

    with patch("shared.kafka.AIOKafkaConsumer") as MockConsumer:
        instance = AsyncMock()
        MockConsumer.return_value = instance
        instance.start = AsyncMock()
        await make_consumer("a", "b", group_id="g")

        assert MockConsumer.call_args.args == ("a", "b")
        assert "topics" not in MockConsumer.call_args.kwargs


@pytest.mark.asyncio
async def test_make_consumer_defaults_to_env_var():
    import os

    from shared.kafka import make_consumer

    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "kafka-env:9092"
    try:
        with patch("shared.kafka.AIOKafkaConsumer") as MockConsumer:
            instance = AsyncMock()
            MockConsumer.return_value = instance
            instance.start = AsyncMock()
            await make_consumer("t", group_id="g")
            assert MockConsumer.call_args.kwargs["bootstrap_servers"] == "kafka-env:9092"
    finally:
        os.environ.pop("KAFKA_BOOTSTRAP_SERVERS", None)


@pytest.mark.asyncio
async def test_real_consumer_accepts_varargs_and_rejects_a_list():
    """Research B-1, reproduced: the corrected form subscribes, the literal D-47 form raises."""
    ok = AIOKafkaConsumer(
        "availability.raw", "polls.completed",
        bootstrap_servers="localhost:9094", group_id="g",
    )
    assert ok.subscription() == frozenset({"availability.raw", "polls.completed"})

    with pytest.raises(TypeError, match="unhashable type"):
        AIOKafkaConsumer(
            ["availability.raw", "polls.completed"],
            bootstrap_servers="localhost:9094", group_id="g",
        )


def test_consumer_construction_outside_a_running_loop_raises():
    """AIOKafkaConsumer.__init__ calls get_running_loop() — build it inside async def run()."""
    with pytest.raises(RuntimeError):
        AIOKafkaConsumer("t", bootstrap_servers="localhost:9094", group_id="g")

    # make_consumer is async, so it structurally cannot be called at import time.
    from shared.kafka import make_consumer

    assert asyncio.iscoroutinefunction(make_consumer)
