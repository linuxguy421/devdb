from datetime import datetime, timedelta, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MediaItem
from app.services.tmdb import tmdb_service


async def get_or_sync_media_item(
    db: AsyncSession,
    tmdb_id: int,
    media_type: str = "movie",
    max_age_days: int = 30,
) -> Optional[MediaItem]:
    """
    Retrieves a MediaItem from Postgres or fetches/upserts it from TMDB if missing or stale.
    """
    target_media = media_type if media_type in ("movie", "tv") else "movie"

    stmt = select(MediaItem).where(
        MediaItem.tmdb_id == tmdb_id,
        MediaItem.media_type == target_media,
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    # Return cached item if missing sync timestamp or still fresh
    if item and item.last_synced_at:
        sync_time = item.last_synced_at
        if sync_time.tzinfo is None:
            sync_time = sync_time.replace(tzinfo=timezone.utc)
        if now - sync_time < timedelta(days=max_age_days):
            return item

    # Fetch updated details from TMDB
    details = await tmdb_service.get_formatted_details(tmdb_id, target_media)
    if not details or not (details.get("title") or details.get("name")):
        return item

    raw_genres = details.get("genres", [])
    if isinstance(raw_genres, list):
        genre_names = [g["name"] if isinstance(g, dict) else str(g) for g in raw_genres]
        genres_str = ", ".join(genre_names)
    else:
        genres_str = str(raw_genres) if raw_genres else None

    title = details.get("title") or details.get("name") or details.get("original_title") or ""
    release_date = str(details.get("release_date")) if details.get("release_date") else None

    total_seasons = details.get("number_of_seasons") or details.get("total_seasons")
    total_episodes = details.get("number_of_episodes") or details.get("total_episodes")

    if not item:
        item = MediaItem(
            tmdb_id=tmdb_id,
            media_type=target_media,
            title=title,
            overview=details.get("overview"),
            poster_path=details.get("poster_path"),
            backdrop_path=details.get("backdrop_path"),
            release_date=release_date,
            runtime=details.get("runtime"),
            genres=genres_str,
            vote_average=details.get("vote_average"),
            total_seasons=total_seasons,
            total_episodes=total_episodes,
            last_synced_at=now,
        )
        db.add(item)
    else:
        item.title = title or item.title
        item.overview = details.get("overview", item.overview)
        item.poster_path = details.get("poster_path", item.poster_path)
        item.backdrop_path = details.get("backdrop_path", item.backdrop_path)
        item.release_date = release_date or item.release_date
        item.runtime = details.get("runtime", item.runtime)
        item.genres = genres_str or item.genres
        item.vote_average = details.get("vote_average", item.vote_average)
        item.total_seasons = total_seasons if total_seasons is not None else item.total_seasons
        item.total_episodes = total_episodes if total_episodes is not None else item.total_episodes
        item.last_synced_at = now

    await db.commit()
    await db.refresh(item)
    return item
