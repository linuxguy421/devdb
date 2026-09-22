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


Task 13 follow-up: Edit save validation
- Successful Edit saves still close the modal and update the card.
- Validation failures re-render the Edit modal with an inline error instead of a bare 400 response.
- TV progress is server-validated against persisted TVSeason episode counts; impossible episodes such as S1E10 for a 9-episode season cannot be saved.
- No migration is required.
