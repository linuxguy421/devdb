"""add persistent TV season metadata cache

Revision ID: b4c91e7d2f10
Revises: 9c7e2f1a4b6d
Create Date: 2026-09-12 16:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b4c91e7d2f10"
down_revision = "9c7e2f1a4b6d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tv_seasons",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "media_item_id",
            sa.Integer(),
            sa.ForeignKey("media_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("season_number", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("poster_path", sa.String(), nullable=True),
        sa.Column("air_date", sa.String(), nullable=True),
        sa.Column(
            "episode_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "media_item_id",
            "season_number",
            name="uq_tv_season_media_item_number",
        ),
        sa.CheckConstraint(
            "season_number >= 0",
            name="ck_tv_season_number_valid",
        ),
        sa.CheckConstraint(
            "episode_count >= 0",
            name="ck_tv_season_episode_count_valid",
        ),
    )

    op.create_index(
        "ix_tv_seasons_media_item_id",
        "tv_seasons",
        ["media_item_id"],
    )
    op.create_index(
        "ix_tv_seasons_id",
        "tv_seasons",
        ["id"],
    )


def downgrade() -> None:
    op.drop_index("ix_tv_seasons_id", table_name="tv_seasons")
    op.drop_index("ix_tv_seasons_media_item_id", table_name="tv_seasons")
    op.drop_table("tv_seasons")
