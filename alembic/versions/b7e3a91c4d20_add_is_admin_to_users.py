"""add is_admin flag to users

Revision ID: b7e3a91c4d20
Revises: a1b2c3d4e5f6
Create Date: 2026-10-17 00:50:00.000000

Admin skeleton: boolean flag for operator access to /admin routes.
Bootstrap via ADMIN_USERNAMES env on login.
"""

from alembic import op

revision = "b7e3a91c4d20"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        DROP COLUMN IF EXISTS is_admin;
        """
    )
