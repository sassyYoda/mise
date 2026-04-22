"""0006: Create availability_events hypertable (chunk_time_interval = 1 day, D-33)."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Step 1: create plain Postgres table
    op.create_table(
        "availability_events",   # restaurant_id is BigInteger to match restaurants.id
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger, nullable=False),
        sa.Column("source", sa.Text, nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("time_slot", sa.Time, nullable=True),
        sa.Column("party_size", sa.Integer, nullable=True),
        sa.Column("seat_type", sa.Text, nullable=True),
        sa.Column("booking_token", sa.Text, nullable=True),
        sa.Column("first_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("hours_before_service", sa.Float, nullable=True),
        sa.Column("day_of_week", sa.Integer, nullable=True),  # 0=Mon..6=Sun
    )
    # Step 2: convert to hypertable
    # NEVER use `alembic revision --autogenerate` on a hypertable (Pitfall 12, D-33)
    op.execute(
        "SELECT create_hypertable('availability_events', 'time', "
        "chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE)"
    )
    op.create_index("ix_avail_events_restaurant_time", "availability_events", ["restaurant_id", "time"])


def downgrade() -> None:
    op.drop_index("ix_avail_events_restaurant_time", table_name="availability_events")
    op.drop_table("availability_events")
