"""0004: Create watchlist_entries table (columns only; CRUD in Phase 5)."""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist_entries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("restaurant_id", sa.BigInteger, sa.ForeignKey("restaurants.id"), nullable=False),
        sa.Column("party_size", sa.Integer, nullable=False),
        sa.Column("date_from", sa.Date, nullable=False),
        sa.Column("date_to", sa.Date, nullable=False),
        sa.Column("time_window_from", sa.Time, nullable=True),
        sa.Column("time_window_to", sa.Time, nullable=True),
        sa.Column("days_of_week", sa.Text, nullable=True),  # comma-separated: "mon,tue,fri"
        sa.Column("seat_type_filter", sa.Text, nullable=True),
        sa.Column("channels", sa.Text, server_default="email", nullable=False),  # "email,sms,push"
        sa.Column("status", sa.Text, server_default="active", nullable=False),  # active|paused|deleted
        sa.Column("management_token", sa.Text, nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_watchlist_entries_user_id", "watchlist_entries", ["user_id"])
    op.create_index("ix_watchlist_entries_restaurant_id", "watchlist_entries", ["restaurant_id"])


def downgrade() -> None:
    op.drop_index("ix_watchlist_entries_restaurant_id", table_name="watchlist_entries")
    op.drop_index("ix_watchlist_entries_user_id", table_name="watchlist_entries")
    op.drop_table("watchlist_entries")
