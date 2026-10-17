"""add recovery_codes table

Revision ID: e0f7a2b3c4d5
Revises: d9e6f1b2c3a4
Create Date: 2026-10-17 02:40:00.000000

Stores hashed account recovery codes for password reset.
"""

from alembic import op

revision = "e0f7a2b3c4d5"
down_revision = "d9e6f1b2c3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS recovery_codes (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash VARCHAR NOT NULL,
            is_used BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recovery_codes_id ON recovery_codes (id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_recovery_codes_user_id ON recovery_codes (user_id);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS recovery_codes;")
