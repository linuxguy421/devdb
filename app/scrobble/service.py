from datetime import datetime, timezone

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import TVSeason, User, WatchEntry
from app.scrobble.identifiers import resolve_tmdb_identifier
from app.scrobble.models import ScrobbleEvent
from app.scrobble.schemas import NormalizedScrobble, ScrobbleEventType, ScrobbleMediaType
from app.services.media_sync import get_or_sync_media_item

COMPLETION_THRESHOLD_PERCENT = 85.0


async def authenticate_user_token(db: AsyncSession, token: str) -> User:
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid DevDB token")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired DevDB token") from exc

    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid DevDB token")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="DevDB account is disabled")
    return user


async def _is_final_available_episode(db: AsyncSession, media_item_id: int, season: int, episode: int) -> bool:
    """Return true when the scrobbled episode reaches the final cached episode."""
    result = await db.execute(
        select(TVSeason.season_number, TVSeason.episode_count)
        .where(TVSeason.media_item_id == media_item_id)
        .order_by(TVSeason.season_number.desc())
    )
    seasons = result.all()
    seasons = [row for row in seasons if row.season_number > 0 and row.episode_count > 0]
    if not seasons:
        return False
    final_season = seasons[0]
    return season == final_season.season_number and episode >= final_season.episode_count


async def process_scrobble(
    db: AsyncSession,
    scrobble: NormalizedScrobble,
    *,
    source: str,
) -> dict:
    """Authenticate, resolve media, update the user's watch entry, and append history."""
    user = await authenticate_user_token(db, scrobble.user_token)
    tmdb_id = await resolve_tmdb_identifier(
        scrobble.media_identifier,
        scrobble.media_type,
    )
    db_media_type = "movie" if scrobble.media_type == ScrobbleMediaType.MOVIE else "tv"

    media_item = await get_or_sync_media_item(
        db,
        tmdb_id=tmdb_id,
        media_type=db_media_type,
    )
    if media_item is None:
        raise HTTPException(status_code=422, detail="Media could not be resolved or synchronized")

    try:
        # Sources with stable event IDs can safely retry delivery.
        if scrobble.source_event_id:
            existing = await db.execute(
                select(ScrobbleEvent).where(
                    ScrobbleEvent.user_id == user.id,
                    ScrobbleEvent.source == source,
                    ScrobbleEvent.source_event_id == scrobble.source_event_id,
                )
            )
            prior_event = existing.scalar_one_or_none()
            if prior_event is not None:
                entry_result = await db.execute(
                    select(WatchEntry).where(
                        WatchEntry.user_id == user.id,
                        WatchEntry.media_item_id == media_item.id,
                    )
                )
                entry = entry_result.scalar_one_or_none()
                return {
                    "status": "duplicate",
                    "user_id": user.id,
                    "media_item_id": media_item.id,
                    "watch_status": entry.status if entry else None,
                    "completed": bool(entry and entry.status == "watched"),
                    "history_id": prior_event.id,
                }

        entry_result = await db.execute(
            select(WatchEntry).where(
                WatchEntry.user_id == user.id,
                WatchEntry.media_item_id == media_item.id,
            )
        )
        entry = entry_result.scalar_one_or_none()
        if entry is None:
            entry = WatchEntry(
                user_id=user.id,
                media_item_id=media_item.id,
                status="in_progress",
            )
            db.add(entry)
            await db.flush()

        now = datetime.now(timezone.utc)
        is_completed_stop = (
            scrobble.event_type == ScrobbleEventType.STOP
            and scrobble.progress_percent > COMPLETION_THRESHOLD_PERCENT
        )

        if db_media_type == "movie":
            if is_completed_stop:
                entry.status = "watched"
                entry.completed_at = now
            else:
                entry.status = "in_progress"
                entry.completed_at = None
        else:
            # Finishing an episode advances the series cursor; it must not
            # mark an entire show watched unless the final cached episode ended.
            entry.status = "in_progress"
            entry.completed_at = None
            if is_completed_stop and scrobble.season is not None and scrobble.episode is not None:
                entry.last_watched_season = scrobble.season
                entry.last_watched_episode = scrobble.episode
                if await _is_final_available_episode(
                    db,
                    media_item.id,
                    scrobble.season,
                    scrobble.episode,
                ):
                    entry.status = "watched"
                    entry.completed_at = now

        history = ScrobbleEvent(
            user_id=user.id,
            media_item_id=media_item.id,
            source=source,
            event_type=scrobble.event_type.value,
            progress_percent=scrobble.progress_percent,
            season=scrobble.season,
            episode=scrobble.episode,
            identifier_source=scrobble.media_identifier.source.value,
            identifier_value=scrobble.media_identifier.value,
            source_event_id=scrobble.source_event_id,
        )
        db.add(history)
        await db.commit()
        await db.refresh(history)

        return {
            "status": "processed",
            "user_id": user.id,
            "media_item_id": media_item.id,
            "watch_status": entry.status,
            "completed": entry.status == "watched",
            "history_id": history.id,
        }
    except Exception:
        await db.rollback()
        raise
