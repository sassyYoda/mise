"""0007: Create poll_log hypertable (chunk_time_interval = 1 day, D-33)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: create plain Postgres table — Named Symbol columns verbatim
    op.create_table(
        "poll_log",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger, nullable=False),   # matches restaurants.id (BigInteger)
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),   # 'success' | 'error' | 'timeout'
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("poll_id", UUID(as_uuid=True), nullable=False),
    )
    # Step 2: convert to hypertable with explicit chunk_time_interval (D-33, Pitfall 12)
    # NEVER use `alembic revision --autogenerate` after a hypertable exists (Pitfall 12)
    op.execute(
        "SELECT create_hypertable('poll_log', 'time', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )
    # Step 3: supporting index (Timescale auto-creates on `time`)
    op.create_index("ix_poll_log_restaurant_time", "poll_log", ["restaurant_id", "time"])


def downgrade() -> None:
    op.drop_index("ix_poll_log_restaurant_time", table_name="poll_log")
    op.drop_table("poll_log")
