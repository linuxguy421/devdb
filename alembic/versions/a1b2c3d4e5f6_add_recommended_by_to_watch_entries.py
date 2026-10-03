"""add recommended_by_id to watch_entries

Revision ID: a1b2c3d4e5f6
Revises: d8e5f0a1b2c3
Create Date: 2026-10-03 21:00:00.000000

Stores which buddy recommended a title when the receiver adds it
from a recommendation card.
"""

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "d8e5f0a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE watch_entries
        ADD COLUMN IF NOT EXISTS recommended_by_id INTEGER
        REFERENCES users(id) ON DELETE SET NULL;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_watch_entries_recommended_by_id
        ON watch_entries (recommended_by_id);
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_watch_entries_recommended_by_id;")
    op.execute(
        """
        ALTER TABLE watch_entries
        DROP COLUMN IF EXISTS recommended_by_id;
        """
    )
