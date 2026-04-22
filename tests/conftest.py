"""Shared pytest fixtures for Mise en Place test suite."""
import pytest
from testcontainers.kafka import KafkaContainer
from testcontainers.redis import RedisContainer
from testcontainers.postgres import PostgresContainer


@pytest.fixture(scope="module")
def kafka_container():
    with KafkaContainer(image="apache/kafka:3.8.1") as kc:
        yield kc


@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer(image="redis:7.2-alpine") as rc:
        client = rc.get_client()
        client.config_set("maxmemory-policy", "noeviction")
        yield rc


@pytest.fixture(scope="module")
def timescale_container():
    container = PostgresContainer(
        image="timescale/timescaledb:2.17.2-pg16",
        username="mise",
        password="mise",
        dbname="mise",
    )
    with container as tc:
        yield tc
