DevDB Task #13 — Unified My Media Cards + Rich Detail Modal

Drop-in UI patch built on the reconciled 12-fix state.

Includes:
- one consistent My Media card layout for movie/TV and all statuses
- TMDB vote_average + personal rating
- notes + private indicator
- status, TV cursor, completion date
- whole-card click opens the detail/edit modal
- richer persisted detail modal with overview, genres, production, movie finances, TV season cache, and watch log
- persisted MediaItem data is used for existing My Media entries, so opening an existing entry does not require a TMDB request

Replace:
- app/routers/titles.py
- app/templates/partials/my_media_card.html
- app/templates/partials/info_modal.html

No migration is required.

Rebuild:
  docker compose build app
  docker compose up -d

This patch assumes the reconciled 12-fix bundle is already installed.
