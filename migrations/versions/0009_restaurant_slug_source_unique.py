"""0009: Replace UNIQUE(slug) on restaurants with UNIQUE(slug, source) (D-63b).

Destroys nothing: the upgrade refuses to run when the table already holds a duplicate
`(slug, source)` pair rather than deleting one of them to force the constraint through
(the 0008 precedent).

Corrects the defect research reproduced as a hard runtime error (§B-5):

    ERROR:  duplicate key value violates unique constraint "restaurants_slug_key"
    DETAIL:  Key (slug)=(carbone) already exists.

D-63 requires a Resy job *in addition to* the OpenTable job, which means a second
`restaurants` row with `source='resy'` for the same restaurant. `UNIQUE(slug)` made that
row impossible, so the Resy branch of `scripts/seed_restaurants.py` was unreachable and no
Resy poll could ever be scheduled.

The slug constraint is declared TWICE in migration 0003 and both declarations must go:
  - `sa.Column("slug", sa.Text, nullable=False, unique=True)`   -> constraint
    `restaurants_slug_key` (0003:18)
  - `op.create_index("ix_restaurants_slug", ..., unique=True)`  -> index
    `ix_restaurants_slug` (0003:38)
`restaurants_slug_key` is a UNIQUE *constraint* whose backing index carries the same name;
dropping it with `op.drop_index` raises `DependentObjectsStillExistError`, so it is dropped
as a constraint and only `ix_restaurants_slug` is dropped as an index.

After this migration a slug identifies a RESTAURANT, not a row: one logical restaurant keeps
the same human slug across two sources. `(source, platform_id)` remains the upsert and join
key (D-52) — Phase 5/6 slug lookups now return one row per source and must not assume a
single row.
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_restaurants_slug_source"
OLD_CONSTRAINT_NAME = "restaurants_slug_key"
OLD_INDEX_NAME = "ix_restaurants_slug"


def upgrade() -> None:
    # Pre-flight guard (0008 precedent, T-03-12): this migration NEVER deletes a row.
    # A duplicate `(slug, source)` pair cannot be created while UNIQUE(slug) is in force,
    # so in every normal environment this guard is a no-op. It exists for the environment
    # where someone dropped the slug index by hand: there, blindly creating the composite
    # constraint would fail with Postgres' own opaque message and the obvious "fix" is to
    # delete one of the colliding rows. The operator decides that, not the migration.
    duplicates = op.get_bind().execute(
        sa.text(
            "SELECT slug, source, count(*) AS n FROM restaurants "
            "GROUP BY slug, source HAVING count(*) > 1 ORDER BY slug, source"
        )
    ).all()
    if duplicates:
        listed = ", ".join(f"({r.slug!r}, {r.source!r}) x{r.n}" for r in duplicates[:10])
        more = "" if len(duplicates) <= 10 else f" (and {len(duplicates) - 10} more)"
        raise RuntimeError(
            f"restaurants holds {len(duplicates)} duplicate (slug, source) pair(s): "
            f"{listed}{more}. {CONSTRAINT_NAME} cannot be created over them and this "
            "migration refuses to delete a row to make an ALTER succeed. Decide which row "
            "is canonical, merge or re-slug the others (the upsert key is "
            "(source, platform_id), D-52), then re-run `alembic upgrade head`."
        )

    op.drop_index(OLD_INDEX_NAME, table_name="restaurants")
    # NOT drop_index: `restaurants_slug_key` is a UNIQUE CONSTRAINT whose backing index
    # shares its name, and Postgres refuses to drop that index while the constraint owns it
    # (DependentObjectsStillExistError). Research §B-5.
    op.drop_constraint(OLD_CONSTRAINT_NAME, "restaurants", type_="unique")

    op.create_unique_constraint(CONSTRAINT_NAME, "restaurants", ["slug", "source"])

    # The doubled percent sign is required — alembic passes the string through a format
    # step before executing it. (None is needed below, but the idiom is kept intact so a
    # future edit that adds one does not silently break.)
    op.execute(
        f"COMMENT ON CONSTRAINT {CONSTRAINT_NAME} ON restaurants IS "
        "'A slug identifies a RESTAURANT, not a row (D-63b): one logical restaurant keeps "
        "one human slug across sources. The upsert and join key remains "
        "(source, platform_id) (D-52) — never the slug.'"
    )
    op.execute(
        "COMMENT ON COLUMN restaurants.slug IS "
        "'Human URL slug, unique per (slug, source) since 0009 (D-63b). A slug lookup "
        "returns ONE ROW PER SOURCE; Phase 5/6 must not assume a single row. Join to "
        "poll_log / availability_events on (source, platform_id), not on slug (D-52).'"
    )


def downgrade() -> None:
    """Restore UNIQUE(slug) — which FAILS whenever two rows share a slug.

    That failure is the honest outcome, not a defect: the whole point of 0009 is that a
    restaurant may hold one row per source under one slug. Restoring the old constraint is
    only possible after every duplicate slug has been deleted or re-slugged, and choosing
    which row dies is an operator decision, so this migration will not make it silently.
    Postgres reports it as `duplicate key value violates unique constraint
    "restaurants_slug_key"`, naming the offending slug.
    """
    op.drop_constraint(CONSTRAINT_NAME, "restaurants", type_="unique")
    op.create_unique_constraint(OLD_CONSTRAINT_NAME, "restaurants", ["slug"])
    op.create_index(OLD_INDEX_NAME, "restaurants", ["slug"], unique=True)
