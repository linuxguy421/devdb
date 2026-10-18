import json
from typing import Any

from fastapi import HTTPException

from app.scrobble.schemas import (
    IdentifierSource,
    MediaIdentifier,
    NormalizedScrobble,
    ScrobbleEventType,
    ScrobbleMediaType,
)


def _first_identifier(candidates: list[Any]) -> MediaIdentifier:
    """Return the first recognized TMDB/IMDb/TVDB GUID or provider ID."""
    for candidate in candidates:
        if isinstance(candidate, dict):
            raw = candidate.get("id") or candidate.get("Id") or candidate.get("value")
        else:
            raw = candidate

        if not isinstance(raw, str):
            continue
        raw = raw.strip()
        lowered = raw.lower()
        for prefix, source in (
            ("tmdb://", IdentifierSource.TMDB),
            ("imdb://", IdentifierSource.IMDB),
            ("tvdb://", IdentifierSource.TVDB),
        ):
            if lowered.startswith(prefix):
                value = raw[len(prefix):].split("/", 1)[0].strip()
                try:
                    return MediaIdentifier(source=source, value=value)
                except ValueError:
                    continue

    raise HTTPException(
        status_code=422,
        detail="Webhook has no supported TMDB, IMDb, or TVDB media identifier",
    )


def _progress(position: Any, duration: Any) -> float:
    try:
        current = float(position or 0)
        total = float(duration or 0)
    except (TypeError, ValueError):
        return 0.0
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, current / total * 100.0))


def _plex_event(value: Any) -> ScrobbleEventType:
    event = str(value or "").strip().lower()
    mapping = {
        "media.play": ScrobbleEventType.START,
        "media.resume": ScrobbleEventType.START,
        "media.pause": ScrobbleEventType.PAUSE,
        "media.stop": ScrobbleEventType.STOP,
        "media.scrobble": ScrobbleEventType.STOP,
    }
    if event not in mapping:
        raise HTTPException(status_code=422, detail=f"Unsupported Plex event: {event or 'missing'}")
    return mapping[event]


def _decode_plex_payload(raw: Any) -> dict[str, Any]:
    # Plex's webhook plugin commonly posts form data with a JSON "payload"
    # field; tests and reverse proxies may instead send JSON directly.
    if isinstance(raw, dict):
        payload = raw.get("Payload", raw.get("payload", raw))
    else:
        payload = raw

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Plex payload field must contain JSON") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Plex payload must be a JSON object")
    return payload


def parse_plex_payload(raw: Any, user_token: str) -> NormalizedScrobble:
    payload = _decode_plex_payload(raw)
    metadata = payload.get("Metadata") or payload.get("metadata")
    if not isinstance(metadata, dict):
        raise HTTPException(status_code=422, detail="Plex payload is missing Metadata")

    plex_type = str(metadata.get("type") or metadata.get("Type") or "").lower()
    media_type = ScrobbleMediaType.MOVIE if plex_type == "movie" else ScrobbleMediaType.SHOW
    if plex_type not in {"movie", "show", "episode"}:
        raise HTTPException(status_code=422, detail=f"Unsupported Plex media type: {plex_type or 'missing'}")

    # For an episode, prefer series-level GUIDs. Plex's episode-level GUID may
    # identify an individual episode rather than the show.
    guid_values: list[Any] = []
    if plex_type == "episode":
        guid_values.extend([
            metadata.get("grandparentGuid"),
            metadata.get("GrandparentGuid"),
            metadata.get("grandparent_guid"),
        ])

    guids = metadata.get("Guid") or metadata.get("guid") or []
    if isinstance(guids, (str, dict)):
        guids = [guids]
    if isinstance(guids, list):
        guid_values.extend(guids)

    if plex_type != "episode":
        guid_values.extend([metadata.get("guid"), metadata.get("Guid")])

    identifier = _first_identifier(guid_values)
    event_type = _plex_event(payload.get("event") or payload.get("Event"))

    season = metadata.get("parentIndex") if plex_type == "episode" else None
    episode = metadata.get("index") if plex_type == "episode" else None
    try:
        season = int(season) if season is not None else None
        episode = int(episode) if episode is not None else None
    except (TypeError, ValueError):
        season = episode = None

    progress = _progress(
        metadata.get("viewOffset") or metadata.get("ViewOffset"),
        metadata.get("duration") or metadata.get("Duration"),
    )

    return NormalizedScrobble(
        user_token=user_token,
        media_identifier=identifier,
        media_type=media_type,
        season=season,
        episode=episode,
        progress_percent=progress,
        event_type=event_type,
        source_event_id=payload.get("eventId") or payload.get("EventId"),
    )


def _jellyfin_event(value: Any) -> ScrobbleEventType:
    event = str(value or "").strip().casefold()
    mapping = {
        "playback start": ScrobbleEventType.START,
        "playback started": ScrobbleEventType.START,
        "playback resume": ScrobbleEventType.START,
        "playback paused": ScrobbleEventType.PAUSE,
        "playback pause": ScrobbleEventType.PAUSE,
        "playback progress": ScrobbleEventType.PAUSE,
        "playback stopped": ScrobbleEventType.STOP,
        "playback stop": ScrobbleEventType.STOP,
    }
    if event not in mapping:
        raise HTTPException(status_code=422, detail=f"Unsupported Jellyfin event: {event or 'missing'}")
    return mapping[event]


def parse_jellyfin_payload(payload: dict[str, Any], user_token: str) -> NormalizedScrobble:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Jellyfin payload must be a JSON object")

    item = payload.get("Item") or payload.get("item") or payload
    if not isinstance(item, dict):
        raise HTTPException(status_code=422, detail="Jellyfin payload Item must be an object")

    item_type = str(item.get("Type") or item.get("type") or payload.get("ItemType") or "").casefold()
    media_type = ScrobbleMediaType.MOVIE if item_type == "movie" else ScrobbleMediaType.SHOW
    if item_type not in {"movie", "series", "episode", "tvshow", "tv"}:
        raise HTTPException(status_code=422, detail=f"Unsupported Jellyfin media type: {item_type or 'missing'}")

    provider_ids = item.get("ProviderIds") or item.get("provider_ids") or {}
    if not isinstance(provider_ids, dict):
        provider_ids = {}

    candidates: list[Any] = [
        f"tmdb://{provider_ids['Tmdb']}" if provider_ids.get("Tmdb") else None,
        f"imdb://{provider_ids['Imdb']}" if provider_ids.get("Imdb") else None,
        f"tvdb://{provider_ids['Tvdb']}" if provider_ids.get("Tvdb") else None,
        f"tmdb://{payload['Provider_tmdb']}" if payload.get("Provider_tmdb") else None,
        f"imdb://{payload['Provider_imdb']}" if payload.get("Provider_imdb") else None,
        f"tvdb://{payload['Provider_tvdb']}" if payload.get("Provider_tvdb") else None,
    ]

    # Episode notifications often put series provider IDs on SeriesProviderIds.
    series_ids = payload.get("SeriesProviderIds") or item.get("SeriesProviderIds") or {}
    if isinstance(series_ids, dict):
        candidates = [
            f"tmdb://{series_ids['Tmdb']}" if series_ids.get("Tmdb") else None,
            f"imdb://{series_ids['Imdb']}" if series_ids.get("Imdb") else None,
            f"tvdb://{series_ids['Tvdb']}" if series_ids.get("Tvdb") else None,
        ] + candidates

    identifier = _first_identifier(candidates)
    event_type = _jellyfin_event(payload.get("NotificationType") or payload.get("notification_type"))

    season = payload.get("SeasonNumber", item.get("ParentIndexNumber"))
    episode = payload.get("EpisodeNumber", item.get("IndexNumber"))
    if item_type != "episode" and not payload.get("SeriesProviderIds"):
        season = episode = None
    try:
        season = int(season) if season is not None else None
        episode = int(episode) if episode is not None else None
    except (TypeError, ValueError):
        season = episode = None

    progress = _progress(
        payload.get("PlaybackPositionTicks") or payload.get("PositionTicks"),
        payload.get("RunTimeTicks") or payload.get("RuntimeTicks"),
    )

    return NormalizedScrobble(
        user_token=user_token,
        media_identifier=identifier,
        media_type=media_type,
        season=season,
        episode=episode,
        progress_percent=progress,
        event_type=event_type,
        source_event_id=payload.get("EventId") or payload.get("NotificationId"),
    )
