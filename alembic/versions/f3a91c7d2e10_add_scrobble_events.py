"""add append-only scrobble event history

Revision ID: f3a91c7d2e10
Revises: b7e3a91c4d20, e0f7a2b3c4d5
Create Date: 2026-10-17 22:00:00.000000

Merge both existing migration heads and add the new scrobble history table.
"""
from alembic import op
import sqlalchemy as sa

revision = "f3a91c7d2e10"
down_revision = ("b7e3a91c4d20", "e0f7a2b3c4d5")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scrobble_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("event_type", sa.String(length=10), nullable=False),
        sa.Column("progress_percent", sa.Float(), nullable=False),
        sa.Column("season", sa.Integer(), nullable=True),
        sa.Column("episode", sa.Integer(), nullable=True),
        sa.Column("identifier_source", sa.String(length=10), nullable=False),
        sa.Column("identifier_value", sa.String(length=100), nullable=False),
        sa.Column("source_event_id", sa.String(length=255), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "event_type IN ('start', 'pause', 'stop')",
            name="ck_scrobble_events_type_valid",
        ),
        sa.CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_scrobble_events_progress_valid",
        ),
        sa.CheckConstraint(
            "(season IS NULL AND episode IS NULL) OR "
            "(season >= 0 AND episode >= 1)",
            name="ck_scrobble_events_episode_valid",
        ),
        sa.UniqueConstraint(
            "user_id",
            "source",
            "source_event_id",
            name="uq_scrobble_event_source_id",
        ),
    )
    op.create_index("ix_scrobble_events_user_id", "scrobble_events", ["user_id"])
    op.create_index("ix_scrobble_events_media_item_id", "scrobble_events", ["media_item_id"])
    op.create_index("ix_scrobble_events_received_at", "scrobble_events", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_scrobble_events_received_at", table_name="scrobble_events")
    op.drop_index("ix_scrobble_events_media_item_id", table_name="scrobble_events")
    op.drop_index("ix_scrobble_events_user_id", table_name="scrobble_events")
    op.drop_table("scrobble_events")
