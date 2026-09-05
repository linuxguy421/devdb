"""phase1 canonical schema migration

Revision ID: f1a82c304d10
Revises: e329ac50c6b4
Create Date: 2026-09-05 14:35:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f1a82c304d10'
down_revision = 'e329ac50c6b4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Ensure media_items table exists with all columns
    op.execute("""
    CREATE TABLE IF NOT EXISTS media_items (
        id SERIAL PRIMARY KEY,
        tmdb_id INTEGER NOT NULL,
        media_type VARCHAR(20) NOT NULL DEFAULT 'movie',
        title VARCHAR NOT NULL,
        overview TEXT,
        poster_path VARCHAR,
        backdrop_path VARCHAR,
        release_date VARCHAR,
        runtime INTEGER,
        genres TEXT,
        vote_average DOUBLE PRECISION,
        total_seasons INTEGER,
        total_episodes INTEGER,
        last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_media_item_tmdb_type UNIQUE (tmdb_id, media_type)
    );
    """)
    op.execute("ALTER TABLE media_items ADD COLUMN IF NOT EXISTS total_seasons INTEGER;")
    op.execute("ALTER TABLE media_items ADD COLUMN IF NOT EXISTS total_episodes INTEGER;")
    op.execute("CREATE INDEX IF NOT EXISTS ix_media_items_id ON media_items (id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_media_items_tmdb_id ON media_items (tmdb_id);")

    # 2. Backfill missing media_items from watch_entries where media_item_id IS NULL
    op.execute("""
    INSERT INTO media_items (tmdb_id, media_type, title, poster_path, last_synced_at)
    SELECT DISTINCT
        we.tmdb_id,
        COALESCE(we.media_type, 'movie'),
        'Untitled Media',
        we.poster_path,
        CURRENT_TIMESTAMP
    FROM watch_entries we
    WHERE we.tmdb_id IS NOT NULL
      AND we.tmdb_id > 0
      AND NOT EXISTS (
          SELECT 1 FROM media_items mi
          WHERE mi.tmdb_id = we.tmdb_id
            AND mi.media_type = COALESCE(we.media_type, 'movie')
      );
    """)

    # 3. Link watch_entries to media_items
    op.execute("""
    UPDATE watch_entries we
    SET media_item_id = mi.id
    FROM media_items mi
    WHERE we.media_item_id IS NULL
      AND we.tmdb_id = mi.tmdb_id
      AND COALESCE(we.media_type, 'movie') = mi.media_type;
    """)

    # 4. Status normalization and validation
    # Verify no invalid statuses exist
    op.execute("""
    DO $$
    DECLARE
        invalid_count INTEGER;
    BEGIN
        SELECT COUNT(*) INTO invalid_count
        FROM watch_entries
        WHERE status NOT IN ('want_to_watch', 'plan_to_watch', 'to_watch', 'currently_watching', 'in_progress', 'watched');

        IF invalid_count > 0 THEN
            RAISE EXCEPTION 'Migration aborted: % watch_entries rows have unrecognized status values.', invalid_count;
        END IF;
    END $$;
    """)

    op.execute("""
    UPDATE watch_entries
    SET status = CASE
        WHEN status IN ('plan_to_watch', 'to_watch') THEN 'want_to_watch'
        WHEN status = 'currently_watching' THEN 'in_progress'
        ELSE status
    END;
    """)

    # 5. Deduplicate watch_entries on (user_id, media_item_id)
    op.execute("""
    DELETE FROM watch_entries we1
    USING watch_entries we2
    WHERE we1.user_id = we2.user_id
      AND we1.media_item_id = we2.media_item_id
      AND we1.id < we2.id;
    """)

    # 6. Alter watch_entries columns & constraints
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS last_watched_season INTEGER;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS last_watched_episode INTEGER;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP;")
    op.execute("ALTER TABLE watch_entries ALTER COLUMN rating TYPE INTEGER USING ROUND(rating)::INTEGER;")
    op.execute("ALTER TABLE watch_entries ALTER COLUMN notes TYPE TEXT;")

    # Drop legacy constraints/indexes
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS uq_watch_entry_user_title;")
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS uq_watch_entry_user_media_item;")
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS fk_watch_entries_media_items;")
    op.execute("DROP INDEX IF EXISTS ix_watch_entries_tmdb_id;")

    # Make media_item_id NOT NULL and attach clean constraints
    op.execute("ALTER TABLE watch_entries ALTER COLUMN media_item_id SET NOT NULL;")
    op.execute("""
    ALTER TABLE watch_entries
    ADD CONSTRAINT fk_watch_entries_media_items
    FOREIGN KEY (media_item_id) REFERENCES media_items(id) ON DELETE CASCADE;
    """)
    op.execute("""
    ALTER TABLE watch_entries
    ADD CONSTRAINT uq_watch_entry_user_media_item
    UNIQUE (user_id, media_item_id);
    """)
    op.execute("""
    ALTER TABLE watch_entries
    ADD CONSTRAINT ck_watch_entry_progress_valid
    CHECK (
        (last_watched_season IS NULL AND last_watched_episode IS NULL) OR
        (last_watched_season >= 0 AND last_watched_episode >= 0)
    );
    """)

    # Drop redundant columns off watch_entries
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS tmdb_id;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS media_type;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS poster_path;")

    # 7. Drop legacy titles table if present
    op.execute("DROP TABLE IF EXISTS titles CASCADE;")


def downgrade() -> None:
    # Re-add redundant columns to watch_entries
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS poster_path VARCHAR;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS media_type VARCHAR DEFAULT 'movie';")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS tmdb_id INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE watch_entries ALTER COLUMN media_item_id DROP NOT NULL;")

    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS ck_watch_entry_progress_valid;")
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS uq_watch_entry_user_media_item;")

    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS updated_at;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS last_watched_episode;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS last_watched_season;")

    op.execute("ALTER TABLE media_items DROP COLUMN IF EXISTS total_episodes;")
    op.execute("ALTER TABLE media_items DROP COLUMN IF EXISTS total_seasons;")
