"""
add media dossier fields

Revision ID: 9c7e2f1a4b6d
Revises: f1a82c304d10
Create Date: 2026-09-09 14:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9c7e2f1a4b6d"
down_revision = "f1a82c304d10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Add completed_at.
    #
    # This is intentionally nullable. Existing watched entries do not
    # have a trustworthy completion timestamp because the old
    # watched_date field was removed by the canonical migration.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE watch_entries
        ADD COLUMN IF NOT EXISTS completed_at
        TIMESTAMP WITH TIME ZONE;
        """
    )

    # ------------------------------------------------------------------
    # 2. Make sure updated_at exists and is populated.
    #
    # f1a82c304d10 creates this column, but this is defensive so that
    # semi-production databases with slightly different intermediate
    # states can still be upgraded safely.
    # ------------------------------------------------------------------
    op.execute(
        """
        ALTER TABLE watch_entries
        ADD COLUMN IF NOT EXISTS updated_at
        TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;
        """
    )

    op.execute(
        """
        UPDATE watch_entries
        SET updated_at = COALESCE(updated_at, created_at, CURRENT_TIMESTAMP)
        WHERE updated_at IS NULL;
        """
    )

    op.execute(
        """
        ALTER TABLE watch_entries
        ALTER COLUMN updated_at SET DEFAULT CURRENT_TIMESTAMP;
        """
    )

    op.execute(
        """
        ALTER TABLE watch_entries
        ALTER COLUMN updated_at SET NOT NULL;
        """
    )

    # ------------------------------------------------------------------
    # 3. Normalize any NULL statuses before enforcing the canonical
    # status constraint.
    #
    # NULL historically meant "not explicitly classified", so the least
    # destructive canonical interpretation is want_to_watch.
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE watch_entries
        SET status = 'want_to_watch'
        WHERE status IS NULL;
        """
    )

    # Normalize any legacy values that somehow remain in semi-production.
    op.execute(
        """
        UPDATE watch_entries
        SET status = CASE
            WHEN status IN ('plan_to_watch', 'to_watch')
                THEN 'want_to_watch'
            WHEN status = 'currently_watching'
                THEN 'in_progress'
            ELSE status
        END
        WHERE status IS NOT NULL;
        """
    )

    # Fail rather than silently deleting or reclassifying unexpected data.
    op.execute(
        """
        DO $$
        DECLARE
            invalid_count INTEGER;
        BEGIN
            SELECT COUNT(*)
            INTO invalid_count
            FROM watch_entries
            WHERE status NOT IN (
                'want_to_watch',
                'in_progress',
                'watched'
            );

            IF invalid_count > 0 THEN
                RAISE EXCEPTION
                    'Migration aborted: % watch_entries rows have invalid status values.',
                    invalid_count;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        ALTER TABLE watch_entries
        ALTER COLUMN status SET NOT NULL;
        """
    )

    # ------------------------------------------------------------------
    # 4. Add the canonical status constraint if it does not already
    # exist.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_watch_entry_status_valid'
            ) THEN
                ALTER TABLE watch_entries
                ADD CONSTRAINT ck_watch_entry_status_valid
                CHECK (
                    status IN (
                        'want_to_watch',
                        'in_progress',
                        'watched'
                    )
                );
            END IF;
        END $$;
        """
    )

    # ------------------------------------------------------------------
    # 5. Ensure is_private is canonical and non-null.
    # ------------------------------------------------------------------
    op.execute(
        """
        UPDATE watch_entries
        SET is_private = FALSE
        WHERE is_private IS NULL;
        """
    )

    op.execute(
        """
        ALTER TABLE watch_entries
        ALTER COLUMN is_private SET DEFAULT FALSE;
        """
    )

    op.execute(
        """
        ALTER TABLE watch_entries
        ALTER COLUMN is_private SET NOT NULL;
        """
    )

    # ------------------------------------------------------------------
    # 6. Add the 1-10 rating constraint.
    #
    # Existing ratings are retained. We do not rewrite them here.
    # Invalid existing data causes the migration to fail rather than
    # silently changing a user's rating.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        DECLARE
            invalid_count INTEGER;
        BEGIN
            SELECT COUNT(*)
            INTO invalid_count
            FROM watch_entries
            WHERE rating IS NOT NULL
              AND rating NOT BETWEEN 1 AND 10;

            IF invalid_count > 0 THEN
                RAISE EXCEPTION
                    'Migration aborted: % watch_entries rows have ratings outside 1-10.',
                    invalid_count;
            END IF;
        END $$;
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_watch_entry_rating_valid'
            ) THEN
                ALTER TABLE watch_entries
                ADD CONSTRAINT ck_watch_entry_rating_valid
                CHECK (
                    rating IS NULL
                    OR rating BETWEEN 1 AND 10
                );
            END IF;
        END $$;
        """
    )

    # ------------------------------------------------------------------
    # 7. Make sure the progress constraint exists.
    #
    # f1a82c304d10 already creates this, but keeping this operation
    # idempotent makes the new migration tolerant of an existing
    # semi-production database with the same canonical constraint.
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_watch_entry_progress_valid'
            ) THEN
                ALTER TABLE watch_entries
                ADD CONSTRAINT ck_watch_entry_progress_valid
                CHECK (
                    (
                        last_watched_season IS NULL
                        AND last_watched_episode IS NULL
                    )
                    OR
                    (
                        last_watched_season >= 0
                        AND last_watched_episode >= 0
                    )
                );
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # Remove only the fields/constraints introduced by this migration.
    #
    # Existing canonical data is otherwise left untouched.

    op.execute(
        """
        ALTER TABLE watch_entries
        DROP CONSTRAINT IF EXISTS ck_watch_entry_rating_valid;
        """
    )

    op.execute(
        """
        ALTER TABLE watch_entries
        DROP CONSTRAINT IF EXISTS ck_watch_entry_status_valid;
        """
    )

    op.execute(
        """
        ALTER TABLE watch_entries
        DROP COLUMN IF EXISTS completed_at;
        """
    )
