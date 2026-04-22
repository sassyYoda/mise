"""0003: Create restaurants table."""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "restaurants",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text, nullable=False),          # 'opentable' | 'resy'
        sa.Column("platform_id", sa.Text, nullable=False),     # stringified OT rid or Resy venue_id
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("neighborhood", sa.Text, nullable=False),
        sa.Column("cuisine", sa.Text, nullable=False),
        sa.Column(
            "price_tier",
            sa.Integer,
            sa.CheckConstraint("price_tier BETWEEN 1 AND 4", name="ck_restaurants_price_tier"),
            nullable=False,
        ),
        sa.Column("cover_photo_url", sa.Text, nullable=False),
        sa.Column("date_range_days", sa.Integer, server_default="7", nullable=False),
        sa.Column(
            "party_sizes",
            sa.ARRAY(sa.Integer),
            server_default=sa.text("'{2,4}'::integer[]"),
            nullable=False,
        ),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "platform_id", name="uq_restaurants_source_platform_id"),
    )
    op.create_index("ix_restaurants_slug", "restaurants", ["slug"], unique=True)
    op.create_index("ix_restaurants_source_platform_id", "restaurants", ["source", "platform_id"])


def downgrade() -> None:
    op.drop_index("ix_restaurants_source_platform_id", table_name="restaurants")
    op.drop_index("ix_restaurants_slug", table_name="restaurants")
    op.drop_table("restaurants")
