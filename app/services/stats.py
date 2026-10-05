from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.models import MediaItem, WatchEntry


STATUS_WANT_TO_WATCH = "want_to_watch"
STATUS_IN_PROGRESS = "in_progress"
STATUS_WATCHED = "watched"


def _release_year(item: MediaItem) -> Optional[int]:
    value = (item.release_date or "").strip()
    if len(value) >= 4 and value[:4].isdigit():
        return int(value[:4])
    return None


def _genres(item: MediaItem) -> list[str]:
    if not item.genres:
        return []
    return [value.strip() for value in item.genres.split(",") if value.strip()]


def _normalize_genre(value: str) -> str:
    return " ".join(value.split()).casefold()


def _display_genres(values: Counter[str], display_names: dict[str, str]) -> list[dict[str, Any]]:
    total = sum(values.values())
    rows = []
    for key, count in values.most_common():
        rows.append({
            "name": display_names.get(key, key.title()),
            "count": count,
            "percentage": round((count / total) * 100, 1) if total else 0,
        })
    return rows


async def get_stats(
    db: AsyncSession,
    user_id: int,
    year: Optional[int] = None,
    media_type: str = "all",
) -> dict[str, Any]:
    """Build the user's private statistics from canonical persisted media data."""
    stmt = (
        select(WatchEntry)
        .options(joinedload(WatchEntry.media_item))
        .where(WatchEntry.user_id == user_id)
    )
    if media_type in {"movie", "tv"}:
        stmt = stmt.join(WatchEntry.media_item).where(MediaItem.media_type == media_type)

    result = await db.execute(stmt)
    entries = result.unique().scalars().all()

    total_entries = len(entries)
    watched_entries = [entry for entry in entries if entry.status == STATUS_WATCHED]
    in_progress_entries = [entry for entry in entries if entry.status == STATUS_IN_PROGRESS]
    want_entries = [entry for entry in entries if entry.status == STATUS_WANT_TO_WATCH]

    # The year filter applies to completion-based statistics while the overview
    # collection counts remain useful for the selected media type.
    watched_for_stats = [
        entry for entry in watched_entries
        if year is None or (entry.completed_at and entry.completed_at.year == year)
    ]

    ratings = [entry.rating for entry in watched_for_stats if entry.rating is not None]
    movie_watched = [
        entry for entry in watched_for_stats
        if entry.media_item and entry.media_item.media_type == "movie"
    ]
    tv_watched = [
        entry for entry in watched_for_stats
        if entry.media_item and entry.media_item.media_type == "tv"
    ]

    completion_rate = (len(watched_entries) / total_entries * 100) if total_entries else 0

    current_year = datetime.now(timezone.utc).year
    trend_year = year or current_year
    trend = []
    for month in range(1, 13):
        count = sum(
            1 for entry in watched_entries
            if entry.completed_at
            and entry.completed_at.year == trend_year
            and entry.completed_at.month == month
        )
        trend.append({"month": datetime(trend_year, month, 1).strftime("%b"), "count": count})

    genre_counts: Counter[str] = Counter()
    genre_display: dict[str, str] = {}
    genre_ratings: dict[str, list[int]] = {}
    for entry in watched_for_stats:
        if not entry.media_item:
            continue
        for raw_genre in _genres(entry.media_item):
            key = _normalize_genre(raw_genre)
            genre_counts[key] += 1
            genre_display.setdefault(key, raw_genre)
            if entry.rating is not None:
                genre_ratings.setdefault(key, []).append(entry.rating)

    genre_rows = _display_genres(genre_counts, genre_display)
    genre_rating_rows = []
    for key, values in genre_ratings.items():
        genre_rating_rows.append({
            "name": genre_display.get(key, key.title()),
            "average": round(sum(values) / len(values), 1),
            "rated_count": len(values),
        })
    genre_rating_rows.sort(key=lambda row: (-row["average"], row["name"].casefold()))

    release_year_counts: Counter[int] = Counter()
    for entry in watched_for_stats:
        if entry.media_item:
            release_year = _release_year(entry.media_item)
            if release_year is not None:
                release_year_counts[release_year] += 1

    release_years = sorted(release_year_counts.items(), key=lambda pair: pair[0])
    release_buckets = Counter()
    for release_year, count in release_years:
        decade = (release_year // 10) * 10
        release_buckets[decade] += count
    release_year_rows = [
        {"label": f"{decade}s", "count": count}
        for decade, count in sorted(release_buckets.items())
    ]

    all_completed = [entry for entry in watched_for_stats if entry.completed_at]
    first_completed = min(all_completed, key=lambda entry: entry.completed_at) if all_completed else None
    latest_completed = max(all_completed, key=lambda entry: entry.completed_at) if all_completed else None
    highest_rated = max(
        (entry for entry in watched_for_stats if entry.rating is not None),
        key=lambda entry: (entry.rating, entry.completed_at or datetime.min),
        default=None,
    )
    most_recent_addition = max(entries, key=lambda entry: entry.created_at or datetime.min, default=None)

    years = sorted({
        entry.completed_at.year
        for entry in watched_entries
        if entry.completed_at
    }, reverse=True)

    max_genre_count = max((row["count"] for row in genre_rows), default=0)
    max_trend_count = max((row["count"] for row in trend), default=0)
    max_release_count = max((row["count"] for row in release_year_rows), default=0)

    return {
        "filters": {"year": year, "media_type": media_type},
        "available_years": years,
        "overview": {
            "total_entries": total_entries,
            "watched": len(watched_entries),
            "in_progress": len(in_progress_entries),
            "want_to_watch": len(want_entries),
            "completion_rate": round(completion_rate, 1),
            "average_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
        },
        "watched_types": {
            "movies": len(movie_watched),
            "tv": len(tv_watched),
            "total": len(watched_for_stats),
        },
        "trend": trend,
        "max_trend_count": max_trend_count,
        "genres": genre_rows,
        "genre_ratings": genre_rating_rows[:10],
        "max_genre_count": max_genre_count,
        "release_years": release_year_rows,
        "max_release_count": max_release_count,
        "tv": {
            "tracked": sum(1 for entry in entries if entry.media_item and entry.media_item.media_type == "tv"),
            "completed": len(tv_watched),
            "in_progress": sum(
                1 for entry in in_progress_entries
                if entry.media_item and entry.media_item.media_type == "tv"
            ),
        },
        "milestones": {
            "first_completed": first_completed,
            "latest_completed": latest_completed,
            "highest_rated": highest_rated,
            "most_recent_addition": most_recent_addition,
        },
    }
