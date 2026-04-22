"""Integration: SC4 / Plan 02 BLOCKING — `make migrate` applies and creates hypertables with chunk_time_interval = 1 day.

Plan 02 owns this test. It proves:
  1. All 7 Alembic migrations apply cleanly against a TimescaleDB 2.17.2-pg16 container.
  2. timescaledb + pgcrypto extensions are enabled (migration 0001).
  3. availability_events and poll_log are hypertables with chunk_time_interval = 86_400_000_000 µs (= 1 day).
  4. users.phone is BYTEA (not TEXT) — mitigation for T-04.
  5. restaurants has UniqueConstraint("source", "platform_id") with BigInteger id.

Requires a container runtime; skipped automatically if unavailable.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


def _run_alembic_upgrade(sync_url: str, repo_root: Path) -> None:
    env = os.environ.copy()
    env["DATABASE_URL_SYNC"] = sync_url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(repo_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"alembic upgrade head failed (exit {result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def test_migrations_apply_and_hypertables_exist(timescale_container):
    """
    Apply all 7 migrations against a live TimescaleDB container and assert the
    hypertable geometry matches D-33 (chunk_time_interval = INTERVAL '1 day' = 86_400_000_000 µs).
    """
    import sqlalchemy as sa

    repo_root = Path(__file__).resolve().parents[2]

    # The PostgresContainer default driver is `psycopg2`; force psycopg3 sync driver (D-30).
    raw_url = timescale_container.get_connection_url()
    # Convert postgresql+psycopg2://... or postgresql://... to postgresql+psycopg://...
    if raw_url.startswith("postgresql+psycopg2://"):
        sync_url = raw_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    elif raw_url.startswith("postgresql://"):
        sync_url = raw_url.replace("postgresql://", "postgresql+psycopg://", 1)
    else:
        sync_url = raw_url

    _run_alembic_upgrade(sync_url, repo_root)

    engine = sa.create_engine(sync_url)
    try:
        with engine.connect() as conn:
            # 1. Extensions enabled
            exts = set(
                conn.execute(
                    sa.text(
                        "SELECT extname FROM pg_extension "
                        "WHERE extname IN ('timescaledb', 'pgcrypto')"
                    )
                )
                .scalars()
                .all()
            )
            assert exts == {"timescaledb", "pgcrypto"}, f"extensions missing: {exts}"

            # 2. Hypertables have chunk_time_interval = 1 day (86_400_000_000 µs)
            rows = conn.execute(
                sa.text(
                    "SELECT hypertable_name, time_interval "
                    "FROM timescaledb_information.dimensions "
                    "WHERE hypertable_name IN ('availability_events', 'poll_log') "
                    "ORDER BY hypertable_name"
                )
            ).all()
            assert len(rows) == 2, f"expected 2 hypertable dimension rows, got {rows}"
            # time_interval is returned as a Python timedelta (= 1 day = 86_400 seconds)
            from datetime import timedelta

            for name, interval in rows:
                assert interval == timedelta(days=1), (
                    f"{name}: chunk_time_interval is {interval!r}, expected 1 day"
                )

            # 3. users.phone is BYTEA (not text)
            phone_type = conn.execute(
                sa.text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'users' AND column_name = 'phone'"
                )
            ).scalar()
            assert phone_type == "bytea", f"users.phone expected bytea, got {phone_type}"

            # 4. restaurants has UniqueConstraint(source, platform_id) + BigInteger id
            uq = conn.execute(
                sa.text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'restaurants'::regclass AND contype = 'u' "
                    "  AND conname = 'uq_restaurants_source_platform_id'"
                )
            ).scalar()
            assert uq == "uq_restaurants_source_platform_id"

            id_type = conn.execute(
                sa.text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'restaurants' AND column_name = 'id'"
                )
            ).scalar()
            assert id_type == "bigint", f"restaurants.id expected bigint, got {id_type}"

            # 5. poll_log Named Symbol columns are all present (D-33)
            cols = set(
                conn.execute(
                    sa.text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'poll_log'"
                    )
                )
                .scalars()
                .all()
            )
            expected_cols = {
                "time",
                "restaurant_id",
                "source",
                "status",
                "latency_ms",
                "http_status",
                "error",
                "poll_id",
            }
            assert expected_cols.issubset(cols), (
                f"poll_log missing named-symbol columns: expected superset of {expected_cols}, got {cols}"
            )
    finally:
        engine.dispose()
