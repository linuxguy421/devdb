"""add admin_audit_logs table

Revision ID: c8f4b2a1e9d0
Revises: b7e3a91c4d20
Create Date: 2026-10-17 01:05:00.000000

Stores administrator actions for a simple audit trail.
"""

from alembic import op

revision = "c8f4b2a1e9d0"
down_revision = "b7e3a91c4d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id SERIAL PRIMARY KEY,
            actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            target_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            action VARCHAR(50) NOT NULL,
            detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_actor_id ON admin_audit_logs (actor_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_target_user_id ON admin_audit_logs (target_user_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_action ON admin_audit_logs (action);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_created_at ON admin_audit_logs (created_at);"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_audit_logs;")
