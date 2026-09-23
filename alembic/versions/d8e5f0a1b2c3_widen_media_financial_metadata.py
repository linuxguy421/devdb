"""widen media financial metadata to bigint

Revision ID: d8e5f0a1b2c3
Revises: c7d4e91f2a63
Create Date: 2026-09-23 18:30:00.000000

TMDB revenue can exceed PostgreSQL INTEGER (int4) range.
"""

from alembic import op

revision = "d8e5f0a1b2c3"
down_revision = "c7d4e91f2a63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE media_items
        ALTER COLUMN budget TYPE BIGINT
        USING budget::BIGINT;
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        ALTER COLUMN revenue TYPE BIGINT
        USING revenue::BIGINT;
        """
    )


def downgrade() -> None:
    # Refuse to narrow values that cannot fit in PostgreSQL INTEGER.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM media_items
                WHERE budget IS NOT NULL
                  AND (budget > 2147483647 OR budget < -2147483648)
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade media_items.budget to INTEGER: out-of-range values exist.';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM media_items
                WHERE revenue IS NOT NULL
                  AND (revenue > 2147483647 OR revenue < -2147483648)
            ) THEN
                RAISE EXCEPTION
                    'Cannot downgrade media_items.revenue to INTEGER: out-of-range values exist.';
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        ALTER TABLE media_items
        ALTER COLUMN budget TYPE INTEGER
        USING budget::INTEGER;
        """
    )
    op.execute(
        """
        ALTER TABLE media_items
        ALTER COLUMN revenue TYPE INTEGER
        USING revenue::INTEGER;
        """
    )
