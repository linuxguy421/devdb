"""add missing media item dossier columns

Revision ID: c7d4e91f2a63
Revises: 9c7e2f1a4b6d
Create Date: 2026-09-19 14:00:00.000000

The MediaItem ORM model already defines these fields, but the migration
chain did not create them.  Keep the columns nullable so this migration is
safe for existing media_items rows in semi-production databases.
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "c7d4e91f2a63"
down_revision = "b4c91e7d2f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These definitions intentionally match app.models.MediaItem exactly:
    #   budget               -> Integer
    #   revenue              -> Integer
    #   status               -> String(50)
    #   tagline              -> Text
    #   production_companies -> Text
    #
    # All are nullable because they are TMDB dossier metadata and existing
    # MediaItem rows may predate these fields.
    op.execute(
        """
        ALTER TABLE media_items
        ADD COLUMN IF NOT EXISTS budget INTEGER;
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        ADD COLUMN IF NOT EXISTS revenue INTEGER;
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        ADD COLUMN IF NOT EXISTS status VARCHAR(50);
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        ADD COLUMN IF NOT EXISTS tagline TEXT;
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        ADD COLUMN IF NOT EXISTS production_companies TEXT;
        """
    )


def downgrade() -> None:
    # These columns contain optional TMDB metadata and were introduced by
    # this migration, so they can be removed independently of the canonical
    # MediaItem/watch-entry schema.
    op.execute(
        """
        ALTER TABLE media_items
        DROP COLUMN IF EXISTS production_companies;
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        DROP COLUMN IF EXISTS tagline;
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        DROP COLUMN IF EXISTS status;
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        DROP COLUMN IF EXISTS revenue;
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        DROP COLUMN IF EXISTS budget;
        """
    )
