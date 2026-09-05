"""0008: Add event_id + unique (event_id, time) to availability_events (D-48a, corrected).

Destroys nothing: the upgrade refuses to run against a non-empty table rather than
deleting the rows it cannot backfill (see the guard in upgrade()).

Corrects three defects research reproduced as hard runtime errors:
  B-2 — a unique index on a hypertable must include the partitioning column "time";
        D-48's literal `(restaurant_id, event_id)` cannot be created at all.
  B-3 — the declarative PK `(time, restaurant_id)` collides when one poll confirms two
        slots, because every slot in a poll shares the confirming poll's timestamp.
  B-5 — `day_of_week` is `isoweekday() % 7` (0=Sun .. 6=Sat), not the 0=Mon..6=Sun the
        inline comment in migration 0006 claims.
Also records the D-52 meaning of `restaurant_id` in the database itself.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NEVER use `alembic revision --autogenerate` on a hypertable (Pitfall 12, D-33):
    # autogenerate does not understand hypertables and will propose dropping and
    # recreating the table, destroying every chunk.
    # This migration NEVER deletes a row. `event_id` is NOT NULL and there is no
    # deterministic value to backfill a pre-0008 row with: the id is uuid5 over
    # (source, rid, date, party, slot_key, first_poll_id) (D-45) and a pre-0008 row
    # records neither slot_key nor first_poll_id. So a non-empty table is refused
    # loudly and the operator decides, rather than silently destroying the whole
    # hypertable's contents to make an ALTER succeed.
    #
    # In every environment this is a no-op: Phase 1 never wrote to availability_events
    # (D-31), and the state machine that does write to it cannot run before 0008.
    existing = op.get_bind().execute(
        sa.text("SELECT count(*) FROM availability_events")
    ).scalar_one()
    if existing:
        raise RuntimeError(
            f"availability_events holds {existing} pre-0008 row(s). event_id is NOT NULL "
            "and cannot be backfilled deterministically (the uuid5 recipe needs slot_key "
            "and first_poll_id, neither of which a pre-0008 row carries). Refusing to "
            "destroy them. Either archive and TRUNCATE availability_events deliberately, "
            "or backfill event_id yourself, then re-run `alembic upgrade head`."
        )

    op.add_column(
        "availability_events",
        sa.Column("event_id", PG_UUID(as_uuid=True), nullable=True),
    )
    op.alter_column("availability_events", "event_id", nullable=False)

    # TimescaleDB: a UNIQUE index MUST include the partitioning column "time".
    # Verified server error when it is omitted:
    #   ERROR: cannot create a unique index without the column "time" (used in partitioning)
    # ON CONFLICT inherits the restriction, so every arbiter and every close-UPDATE
    # predicate must name "time" too. Do not "simplify" this index (research B-2).
    op.create_index(
        "uq_availability_events_event_id_time",
        "availability_events",
        ["event_id", "time"],
        unique=True,
    )

    # B-5: supersedes the stale `# 0=Mon..6=Sun` inline comment in migration 0006.
    # The doubled percent sign is required — alembic passes the string through a
    # format step before executing it.
    op.execute(
        "COMMENT ON COLUMN availability_events.day_of_week IS "
        "'0=Sun .. 6=Sat (service_date.isoweekday() %% 7) "
        "— matches the Phase 6 heatmap y-axis (D-48)'"
    )
    # D-52 / Pitfall 5: this column holds the SOURCE PLATFORM id, exactly as
    # poll_log.restaurant_id already does — NOT restaurants.id.
    op.execute(
        "COMMENT ON COLUMN availability_events.restaurant_id IS "
        "'Source platform id (OpenTable rid / Resy venue id), matching "
        "poll_log.restaurant_id — NOT restaurants.id. The complete join key against "
        "restaurants is (source, platform_id) (D-52)'"
    )


def downgrade() -> None:
    """Drop the index and the column.

    Dropping `event_id` is lossy by nature — the ids cannot be recomputed from what is
    left in the row — so a downgrade on a populated table means the subsequent upgrade
    will (correctly) refuse to run until those rows are archived or removed.
    """
    op.drop_index("uq_availability_events_event_id_time", table_name="availability_events")
    op.drop_column("availability_events", "event_id")
