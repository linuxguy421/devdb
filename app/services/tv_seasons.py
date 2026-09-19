from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MediaItem, TVSeason
from app.services.tmdb import tmdb_service


def _season_summary_from_tmdb(season: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize a TMDB season summary into fields we persist locally."""
    try:
        season_number = int(season.get("season_number"))
    except (TypeError, ValueError):
        return None

    if season_number < 0:
        return None

    episode_count = season.get("episode_count")
    if episode_count is None:
        episodes = season.get("episodes") or []
        episode_numbers = [
            e.get("episode_number")
            for e in episodes
            if e.get("episode_number") is not None
        ]
        episode_count = max(episode_numbers, default=0)

    try:
        episode_count = max(0, int(episode_count or 0))
    except (TypeError, ValueError):
        episode_count = 0

    return {
        "season_number": season_number,
        "name": season.get("name"),
        "overview": season.get("overview"),
        "poster_path": season.get("poster_path"),
        "air_date": season.get("air_date"),
        "episode_count": episode_count,
    }


async def sync_tv_seasons(
    db: AsyncSession,
    media_item: MediaItem,
    details: Optional[Dict[str, Any]] = None,
) -> List[TVSeason]:
    """
    Upsert season metadata from a TMDB TV details response.

    TMDB's TV details endpoint already includes season summaries with
    episode_count, so normal synchronization does not require one HTTP
    request per season.
    """
    if media_item.media_type != "tv":
        return []

    if details is None:
        details = await tmdb_service.get_formatted_details(
            media_item.tmdb_id,
            "tv",
        )

    if not details:
        return []

    summaries = []
    for season in details.get("seasons") or []:
        if isinstance(season, dict):
            normalized = _season_summary_from_tmdb(season)
            if normalized is not None:
                summaries.append(normalized)

    if not summaries:
        return []

    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(TVSeason).where(TVSeason.media_item_id == media_item.id)
    )
    existing = {
        season.season_number: season
        for season in result.scalars().all()
    }

    seen_numbers = set()

    for data in summaries:
        season_number = data["season_number"]
        seen_numbers.add(season_number)

        season = existing.get(season_number)
        if season is None:
            season = TVSeason(
                media_item_id=media_item.id,
                season_number=season_number,
            )
            db.add(season)

        season.name = data["name"]
        season.overview = data["overview"]
        season.poster_path = data["poster_path"]
        season.air_date = data["air_date"]
        season.episode_count = data["episode_count"]
        season.last_synced_at = now

    # Remove season rows that TMDB no longer reports. This keeps the local
    # cache an accurate representation of the current series structure.
    stale_ids = [
        season.id
        for number, season in existing.items()
        if number not in seen_numbers
    ]
    if stale_ids:
        await db.execute(
            delete(TVSeason).where(TVSeason.id.in_(stale_ids))
        )

    await db.flush()

    result = await db.execute(
        select(TVSeason)
        .where(TVSeason.media_item_id == media_item.id)
        .order_by(TVSeason.season_number)
    )
    return list(result.scalars().all())


async def get_tv_seasons(
    db: AsyncSession,
    media_item_id: int,
) -> List[TVSeason]:
    result = await db.execute(
        select(TVSeason)
        .where(TVSeason.media_item_id == media_item_id)
        .order_by(TVSeason.season_number)
    )
    return list(result.scalars().all())


async def get_season_episode_counts(
    db: AsyncSession,
    media_item: MediaItem,
) -> Dict[int, int]:
    """
    Return the persisted season -> episode count map.

    If a migrated/historical TV title has no cached seasons yet, perform a
    one-time synchronization. Once rows exist, progress operations are
    entirely database-backed and do not contact TMDB.
    """
    seasons = await get_tv_seasons(db, media_item.id)

    if not seasons and media_item.media_type == "tv":
        seasons = await sync_tv_seasons(db, media_item)
        if seasons:
            await db.commit()

    return {
        season.season_number: season.episode_count
        for season in seasons
        if season.episode_count >= 0
    }
