"""add users.last_login_at

Revision ID: d9e6f1b2c3a4
Revises: c8f4b2a1e9d0
Create Date: 2026-10-17 01:25:00.000000

Tracks last successful login for admin user management.
"""

from alembic import op

revision = "d9e6f1b2c3a4"
down_revision = "c8f4b2a1e9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_last_login_at ON users (last_login_at);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_last_login_at;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS last_login_at;")
