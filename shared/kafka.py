"""
AIOKafkaProducer factory for Mise en Place (D-02).
Named config: acks='all', enable_idempotence=True, compression_type='gzip', linger_ms=20.
All producers created via this factory — no inline instantiation in services.
"""
from __future__ import annotations
import os

from aiokafka import AIOKafkaProducer


async def make_producer(bootstrap_servers: str | None = None) -> AIOKafkaProducer:
    """
    Create and start an AIOKafkaProducer with correct durability config (D-02, Pitfall 11).

    Args:
        bootstrap_servers: Comma-separated Kafka brokers. Defaults to KAFKA_BOOTSTRAP_SERVERS env var.

    Returns:
        A started AIOKafkaProducer. Caller is responsible for .stop() on shutdown.
    """
    servers = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9094")
    producer = AIOKafkaProducer(
        bootstrap_servers=servers,
        acks="all",                                   # D-02: wait for all in-sync replicas
        enable_idempotence=True,                      # prevents duplicates on retry
        max_in_flight_requests_per_connection=5,      # required with idempotence=True
        compression_type="gzip",                      # cheap at ~10KB messages
        linger_ms=20,                                  # small batching window
        request_timeout_ms=30_000,
        value_serializer=lambda v: v if isinstance(v, bytes) else v.encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
    )
    await producer.start()
    return producer
