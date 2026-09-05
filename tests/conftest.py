"""Shared pytest fixtures for Mise en Place test suite."""
import pytest
from testcontainers.kafka import KafkaContainer
from testcontainers.postgres import PostgresContainer
from testcontainers.redis import RedisContainer


def _docker_available() -> bool:
    """Return True if a Docker-compatible runtime is reachable."""
    try:
        import docker

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def kafka_container(request):
    if not _docker_available():
        pytest.skip("Docker not available")
    with KafkaContainer(image="confluentinc/cp-kafka:7.6.0") as kc:
        yield kc


@pytest.fixture(scope="module")
def redis_container(request):
    if not _docker_available():
        pytest.skip("Docker not available")
    with RedisContainer(image="redis:7.2-alpine") as rc:
        client = rc.get_client()
        client.config_set("maxmemory-policy", "noeviction")
        yield rc


@pytest.fixture(scope="module")
def timescale_container(request):
    if not _docker_available():
        pytest.skip("Docker not available")
    container = PostgresContainer(
        image="timescale/timescaledb:2.17.2-pg16",
        username="mise",
        password="mise",
        dbname="mise",
    )
    with container as tc:
        yield tc
