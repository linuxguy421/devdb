Fix for TMDB financial metadata overflow.

Changes:
- MediaItem.budget/revenue use PostgreSQL BIGINT.
- Alembic migration d8e5f0a1b2c3 widens both columns.

Apply:
  docker compose build app
  docker compose up -d

The application must run `alembic upgrade head` as part of the normal deployment/migration process before creating new MediaItems.
