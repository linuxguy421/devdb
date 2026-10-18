from datetime import datetime, timezone

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import User, WatchEntry
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
        # Retry-safe for sources that provide a stable event ID. PostgreSQL's
        # unique constraint is the final arbiter when duplicate requests race.
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
        if scrobble.event_type == ScrobbleEventType.STOP:
            if scrobble.progress_percent > COMPLETION_THRESHOLD_PERCENT:
                entry.status = "watched"
                entry.completed_at = now
            else:
                entry.status = "in_progress"
                entry.completed_at = None
        else:
            entry.status = "in_progress"
            entry.completed_at = None

        if db_media_type == "tv" and scrobble.season is not None:
            entry.last_watched_season = scrobble.season
            entry.last_watched_episode = scrobble.episode

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
