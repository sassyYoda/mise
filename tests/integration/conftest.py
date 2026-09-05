"""Shared helpers and fixtures for the Phase 2 integration tier.

Collects the container-URL plumbing and the ``alembic upgrade head`` /
``create_topics.py`` subprocess calls that were previously duplicated inline in
``test_poller_smoke.py`` and ``test_hypertable_config.py``, so the Phase 2
integration files (``test_expedite_lua.py``, ``test_poller_expedite_release.py``,
``test_migration_0008.py``) share one implementation.

Named symbols: reset_shared_db_singletons, apply_migrations, create_topics,
               redis_url, db_urls
"""
from __future__ import annotations

import subprocess
from typing import Any

import pytest


def reset_shared_db_singletons() -> None:
    """Drop the cached engine/session factory so new DATABASE_URL_* env vars take effect."""
    import shared.db as shared_db

    shared_db._engine = None
    shared_db._session_factory = None


def apply_migrations(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run ``alembic upgrade head`` against the container named by ``env``."""
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"
    return result


def create_topics(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run ``scripts/create_topics.py`` against the broker named by ``env``."""
    result = subprocess.run(
        ["uv", "run", "python", "scripts/create_topics.py"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"create_topics failed: {result.stderr}"
    return result


@pytest.fixture(scope="module")
def redis_url(redis_container: Any) -> str:
    """``redis://host:port`` for the module-scoped Redis 7.2 testcontainer."""
    host = redis_container.get_container_host_ip()
    port = redis_container.get_exposed_port(6379)
    return f"redis://{host}:{port}"


@pytest.fixture(scope="module")
def db_urls(timescale_container: Any) -> dict[str, str]:
    """Sync (Alembic/psycopg3), async (asyncpg via SQLAlchemy) and raw asyncpg DSNs."""
    sync_url = timescale_container.get_connection_url().replace("psycopg2", "psycopg")
    host = timescale_container.get_container_host_ip()
    port = timescale_container.get_exposed_port(5432)
    return {
        "sync": sync_url,
        "async": sync_url.replace("postgresql+psycopg://", "postgresql+asyncpg://"),
        "dsn": f"postgresql://mise:mise@{host}:{port}/mise",
    }
