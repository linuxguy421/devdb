from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MediaItem, TVSeason
from app.services.tmdb import tmdb_service
from app.services.tv_seasons import sync_tv_seasons


async def get_or_sync_media_item(
    db: AsyncSession,
    tmdb_id: int,
    media_type: str = "movie",
    max_age_days: int = 30,
) -> Optional[MediaItem]:
    """
    Retrieve a MediaItem from the persistent cache or synchronize it from TMDB.

    TV season metadata is synchronized alongside TV media metadata. Historical
    TV rows created before the TVSeason table existed are initialized lazily
    the first time this function is called for that title.
    """
    target_media = media_type if media_type in ("movie", "tv") else "movie"

    stmt = select(MediaItem).where(
        MediaItem.tmdb_id == tmdb_id,
        MediaItem.media_type == target_media,
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    now = datetime.now(timezone.utc)

    if item and item.last_synced_at:
        sync_time = item.last_synced_at
        if sync_time.tzinfo is None:
            sync_time = sync_time.replace(tzinfo=timezone.utc)

        if now - sync_time < timedelta(days=max_age_days):
            if target_media != "tv":
                return item

            season_count = (
                await db.execute(
                    select(func.count(TVSeason.id)).where(
                        TVSeason.media_item_id == item.id
                    )
                )
            ).scalar_one()

            # Existing TV titles from before TVSeason was introduced need a
            # one-time season cache initialization.
            if season_count > 0:
                return item

            details = await tmdb_service.get_formatted_details(
                tmdb_id,
                "tv",
            )
            if details:
                await sync_tv_seasons(db, item, details)
                await db.commit()
            return item

    details = await tmdb_service.get_formatted_details(
        tmdb_id,
        target_media,
    )
    if not details or not (details.get("title") or details.get("name")):
        return item

    raw_genres = details.get("genres", [])
    if isinstance(raw_genres, list):
        genre_names = [
            g["name"] if isinstance(g, dict) else str(g)
            for g in raw_genres
        ]
        genres_str = ", ".join(genre_names)
    else:
        genres_str = str(raw_genres) if raw_genres else None

    production_companies = details.get("production_companies", [])
    if isinstance(production_companies, list):
        production_str = ", ".join(
            str(c) for c in production_companies if c
        ) or None
    else:
        production_str = str(production_companies) if production_companies else None

    title = (
        details.get("title")
        or details.get("name")
        or details.get("original_title")
        or ""
    )
    release_date = (
        str(details.get("release_date"))
        if details.get("release_date")
        else None
    )

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
            budget=details.get("budget"),
            revenue=details.get("revenue"),
            status=details.get("status"),
            tagline=details.get("tagline"),
            production_companies=production_str,
        )
        db.add(item)
        await db.flush()
    else:
        item.title = title or item.title
        item.overview = details.get("overview", item.overview)
        item.poster_path = details.get("poster_path", item.poster_path)
        item.backdrop_path = details.get("backdrop_path", item.backdrop_path)
        item.release_date = release_date or item.release_date
        item.runtime = details.get("runtime", item.runtime)
        item.genres = genres_str or item.genres
        item.vote_average = details.get("vote_average", item.vote_average)
        item.total_seasons = (
            total_seasons
            if total_seasons is not None
            else item.total_seasons
        )
        item.total_episodes = (
            total_episodes
            if total_episodes is not None
            else item.total_episodes
        )
        item.budget = details.get("budget", item.budget)
        item.revenue = details.get("revenue", item.revenue)
        item.status = details.get("status", item.status)
        item.tagline = details.get("tagline", item.tagline)
        item.production_companies = production_str or item.production_companies
        item.last_synced_at = now

    if target_media == "tv":
        await sync_tv_seasons(db, item, details)

    await db.commit()
    await db.refresh(item)
    return item
