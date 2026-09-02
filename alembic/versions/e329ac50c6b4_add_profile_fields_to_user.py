"""add profile fields to user and migrate schema

Revision ID: e329ac50c6b4
Revises: 507931ac3cd5
Create Date: 2026-09-02 20:30:13.843626

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e329ac50c6b4'
down_revision = '507931ac3cd5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Create media_items table matching models.py if it does not exist
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
        last_synced_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT uq_media_item_tmdb_type UNIQUE (tmdb_id, media_type)
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_media_items_id ON media_items (id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_media_items_tmdb_id ON media_items (tmdb_id);")

    # 2. Update users table safely
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url VARCHAR;")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT;")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;")
    op.execute("ALTER TABLE users ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC';")

    # 3. Update watch_entries table
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS media_item_id INTEGER;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS tmdb_id INTEGER DEFAULT 0;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS media_type VARCHAR DEFAULT 'movie';")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS poster_path VARCHAR;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'plan_to_watch';")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS notes VARCHAR;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS is_private BOOLEAN DEFAULT FALSE;")
    op.execute("ALTER TABLE watch_entries ALTER COLUMN created_at TYPE TIMESTAMP WITH TIME ZONE USING created_at AT TIME ZONE 'UTC';")

    # Drop legacy indexes/constraints safely
    op.execute("DROP INDEX IF EXISTS ix_watch_entries_title_id;")
    op.execute("DROP INDEX IF EXISTS ix_watch_entries_user_id;")
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS uq_user_title;")
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS watch_entries_title_id_fkey;")
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS watch_entries_user_id_fkey;")

    # Add new indexes safely
    op.execute("CREATE INDEX IF NOT EXISTS ix_watch_entries_media_item_id ON watch_entries (media_item_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_watch_entries_tmdb_id ON watch_entries (tmdb_id);")

    # Safely attach constraints and foreign keys
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'uq_watch_entry_user_title') THEN
            ALTER TABLE watch_entries ADD CONSTRAINT uq_watch_entry_user_title UNIQUE (user_id, tmdb_id, media_type);
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_watch_entries_users') THEN
            ALTER TABLE watch_entries ADD CONSTRAINT fk_watch_entries_users FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
        END IF;

        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_watch_entries_media_items') THEN
            ALTER TABLE watch_entries ADD CONSTRAINT fk_watch_entries_media_items FOREIGN KEY (media_item_id) REFERENCES media_items(id) ON DELETE SET NULL;
        END IF;
    END $$;
    """)

    # Drop unused legacy columns from watch_entries
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS updated_at;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS title_id;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS review_text;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS watched_date;")

    # 4. Create friendships & recommendations tables if they do not exist
    op.execute("""
    CREATE TABLE IF NOT EXISTS friendships (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id),
        buddy_id INTEGER NOT NULL REFERENCES users(id),
        status VARCHAR(20) DEFAULT 'pending',
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT unique_user_buddy_pair UNIQUE (user_id, buddy_id)
    );
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS recommendations (
        id SERIAL PRIMARY KEY,
        sender_id INTEGER NOT NULL REFERENCES users(id),
        receiver_id INTEGER NOT NULL REFERENCES users(id),
        tmdb_id INTEGER NOT NULL,
        media_type VARCHAR(20) DEFAULT 'movie',
        note TEXT,
        created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_recommendations_id ON recommendations (id);")

    # 5. Drop deprecated titles table
    op.execute("DROP INDEX IF EXISTS ix_titles_id;")
    op.execute("DROP INDEX IF EXISTS ix_titles_tmdb_id;")
    op.execute("DROP TABLE IF EXISTS titles;")


def downgrade() -> None:
    # Recreate titles table
    op.execute("""
    CREATE TABLE IF NOT EXISTS titles (
        id SERIAL PRIMARY KEY,
        tmdb_id INTEGER NOT NULL,
        media_type VARCHAR(10) NOT NULL,
        name VARCHAR(500) NOT NULL,
        release_year INTEGER,
        poster_path VARCHAR(255),
        overview TEXT,
        genres VARCHAR(255),
        cached_at TIMESTAMP WITHOUT TIME ZONE,
        CONSTRAINT uq_tmdb_id_media_type UNIQUE (tmdb_id, media_type)
    );
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_titles_tmdb_id ON titles (tmdb_id);")
    op.execute("CREATE INDEX IF NOT EXISTS ix_titles_id ON titles (id);")

    # Revert watch_entries constraints and columns
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS fk_watch_entries_media_items;")
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS fk_watch_entries_users;")
    op.execute("ALTER TABLE watch_entries DROP CONSTRAINT IF EXISTS uq_watch_entry_user_title;")
    op.execute("DROP INDEX IF EXISTS ix_watch_entries_tmdb_id;")
    op.execute("DROP INDEX IF EXISTS ix_watch_entries_media_item_id;")

    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS watched_date TIMESTAMP WITHOUT TIME ZONE;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS review_text TEXT;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS title_id INTEGER;")
    op.execute("ALTER TABLE watch_entries ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP WITHOUT TIME ZONE;")

    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS is_private;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS notes;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS status;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS poster_path;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS media_type;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS tmdb_id;")
    op.execute("ALTER TABLE watch_entries DROP COLUMN IF EXISTS media_item_id;")

    # Drop added tables
    op.execute("DROP TABLE IF EXISTS recommendations;")
    op.execute("DROP TABLE IF EXISTS friendships;")
    op.execute("DROP TABLE IF EXISTS media_items;")

    # Revert users columns
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_active;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS bio;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS avatar_url;")
