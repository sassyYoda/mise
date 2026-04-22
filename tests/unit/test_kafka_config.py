"""Unit test for shared.kafka producer config (D-02)."""
import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_make_producer_config():
    """Verify make_producer uses correct acks and idempotence settings."""
    from shared.kafka import make_producer
    with patch("shared.kafka.AIOKafkaProducer") as MockProducer:
        instance = AsyncMock()
        MockProducer.return_value = instance
        instance.start = AsyncMock()
        await make_producer("localhost:9094")
        call_kwargs = MockProducer.call_args.kwargs
        assert call_kwargs["acks"] == "all"
        assert call_kwargs["enable_idempotence"] is True
        assert call_kwargs["compression_type"] == "gzip"
        assert call_kwargs["linger_ms"] == 20
        assert call_kwargs["max_in_flight_requests_per_connection"] == 5
        assert call_kwargs["bootstrap_servers"] == "localhost:9094"


@pytest.mark.asyncio
async def test_make_producer_defaults_to_env_var():
    """make_producer should read KAFKA_BOOTSTRAP_SERVERS from env when not given."""
    import os
    from shared.kafka import make_producer
    os.environ["KAFKA_BOOTSTRAP_SERVERS"] = "kafka-env:9092"
    try:
        with patch("shared.kafka.AIOKafkaProducer") as MockProducer:
            instance = AsyncMock()
            MockProducer.return_value = instance
            instance.start = AsyncMock()
            await make_producer()
            assert MockProducer.call_args.kwargs["bootstrap_servers"] == "kafka-env:9092"
    finally:
        os.environ.pop("KAFKA_BOOTSTRAP_SERVERS", None)
