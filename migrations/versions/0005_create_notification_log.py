"""0005: Create notification_log table (columns only; writes in Phase 4)."""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("watch_id", sa.Integer, sa.ForeignKey("watchlist_entries.id"), nullable=False),
        sa.Column("event_id", sa.Text, nullable=False),
        sa.Column("channel", sa.Text, nullable=False),  # email|sms|push
        sa.Column("status", sa.Text, nullable=False),   # sent|delivered|clicked|failed
        sa.Column("provider_id", sa.Text, nullable=True),  # Twilio SID, Resend ID, etc.
        sa.Column("slot_still_available", sa.Boolean, nullable=True),
        sa.Column("sent_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_log_watch_id", "notification_log", ["watch_id"])
    op.create_index("ix_notification_log_event_id", "notification_log", ["event_id"])


def downgrade() -> None:
    op.drop_index("ix_notification_log_event_id", table_name="notification_log")
    op.drop_index("ix_notification_log_watch_id", table_name="notification_log")
    op.drop_table("notification_log")
