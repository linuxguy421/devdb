# Scrobble ingestion

DevDB accepts normalized scrobbles and adapts Plex/Jellyfin webhook payloads into the same internal model. All routes use the existing DevDB access JWT and write an append-only row to `scrobble_events`.

## Routes

- `POST /api/v1/scrobble/generic` — normalized JSON; token is the `user_token` field.
- `POST /api/v1/scrobble/plex` — Plex JSON or form/multipart request with a JSON `payload` field.
- `POST /api/v1/scrobble/jellyfin` — Jellyfin notification JSON.

Plex and Jellyfin requests must send the user's DevDB JWT as `Authorization: Bearer <jwt>` or `X-DevDB-Token: <jwt>`. The API scrobble paths are exempt from browser CSRF validation because they are machine-to-machine endpoints; they are not exempt from token authentication. If a webhook sender cannot set a header, configure a trusted reverse proxy to inject one, and do not expose an unauthenticated public webhook URL.

## Normalized payload

```json
{
  "user_token": "<DevDB access JWT>",
  "media_identifier": { "source": "tmdb", "value": "550" },
  "media_type": "movie",
  "season": null,
  "episode": null,
  "progress_percent": 91.2,
  "event_type": "stop",
  "source_event_id": "optional-provider-event-id"
}
```

`media_identifier.source` is `tmdb`, `imdb`, or `tvdb`. IMDb values look like `tt0133093`; TMDB and TVDB values are numeric. IMDb/TVDB IDs are resolved through TMDB's `/find` API and therefore require `TMDB_API_KEY`.

For shows, `season` is zero-based and `episode` starts at 1. A stop event completes a movie only when progress is strictly greater than 85%. For shows, a qualifying stop advances the episode cursor; the series is marked watched only if that episode is the final episode in the cached season metadata. Start/pause events set the entry to in progress.

A source-provided `source_event_id` is used for duplicate suppression. Events without a stable source ID are recorded as delivered, so webhook retries may produce duplicate history rows. The bearer token and raw webhook payload are never stored in history.

## Database rollout

Apply the new migration before deploying code:

```sh
alembic upgrade head
```

The migration merges the two existing heads and adds `scrobble_events`; it does not rewrite existing watch-entry data.
