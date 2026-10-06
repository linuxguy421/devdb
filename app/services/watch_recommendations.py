from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Optional

from app.models import MediaItem, Recommendation, WatchEntry


@dataclass
class WatchPick:
    entry: WatchEntry
    media: MediaItem
    score: float
    reasons: list[str]


def _genres(media: MediaItem) -> list[str]:
    if not media.genres:
        return []
    return [g.strip() for g in media.genres.split(",") if g.strip()]


def _genre_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _runtime_bucket(media: MediaItem) -> str:
    if media.media_type == "movie":
        if not media.runtime:
            return "unknown"
        if media.runtime <= 100:
            return "short"
        if media.runtime >= 150:
            return "long"
        return "normal"

    if not media.total_episodes:
        return "unknown"
    if media.total_episodes <= 8:
        return "short"
    if media.total_episodes >= 25:
        return "long"
    return "normal"


def _matches_length(media: MediaItem, length: str) -> bool:
    return length == "any" or _runtime_bucket(media) == length


def _format_length(media: MediaItem) -> str:
    if media.media_type == "movie":
        if media.runtime:
            hours, minutes = divmod(media.runtime, 60)
            return f"{hours}h {minutes}m" if hours else f"{minutes}m"
        return "Runtime unknown"

    if media.total_episodes:
        return f"{media.total_episodes} episodes"
    return "Episode count unknown"


def _genre_stats(watched: list[WatchEntry]):
    counts: Counter[str] = Counter()
    ratings: dict[str, list[int]] = defaultdict(list)

    for entry in watched:
        if not entry.media_item:
            continue
        for genre in _genres(entry.media_item):
            key = _genre_key(genre)
            counts[key] += 1
            if entry.rating is not None:
                ratings[key].append(entry.rating)

    averages = {
        key: sum(values) / len(values)
        for key, values in ratings.items()
        if values
    }
    return counts, averages


def _score_candidate(
    entry: WatchEntry,
    watched: list[WatchEntry],
    incoming_recommendations: set[tuple[int, str]],
    mood: str,
) -> WatchPick:
    media = entry.media_item
    assert media is not None

    counts, genre_averages = _genre_stats(watched)
    rated = [e.rating for e in watched if e.rating is not None]
    global_avg = sum(rated) / len(rated) if rated else 7.0

    candidate_genres = _genres(media)
    known_genres = {_genre_key(g) for g in counts}
    matched_genres = [_genre_key(g) for g in candidate_genres if _genre_key(g) in known_genres]

    score = 0.0
    reasons: list[str] = []

    genre_lifts = [
        genre_averages[key] - global_avg
        for key in matched_genres
        if key in genre_averages
    ]
    if genre_lifts:
        lift = sum(genre_lifts) / len(genre_lifts)
        score += lift * 12
        best_genre = max(
            matched_genres,
            key=lambda key: genre_averages.get(key, global_avg),
        )
        best_average = genre_averages.get(best_genre)
        if best_average is not None and best_average >= global_avg + 0.3:
            reasons.append(f"You rate {best_genre.title()} around {best_average:.1f}/10")

    familiarity = sum(counts[key] for key in matched_genres)
    if mood == "comfort":
        score += min(familiarity, 8) * 1.5
        if matched_genres:
            reasons.append("It matches genres you already watch")
    elif mood == "new":
        score -= min(familiarity, 6) * 1.0
        if not matched_genres:
            score += 8
            reasons.append("It gives you something outside your usual genres")
        elif familiarity <= 2:
            score += 4
            reasons.append("It is a less-explored genre for you")

    tmdb_rating = media.vote_average or 0
    if tmdb_rating:
        score += max(-1.0, min(3.0, tmdb_rating - 7.0))
        if tmdb_rating >= 8.0:
            reasons.append(f"TMDB rating is {tmdb_rating:.1f}/10")

    if (media.tmdb_id, media.media_type) in incoming_recommendations:
        score += 10
        reasons.append("A buddy recommended it to you")

    if not reasons:
        reasons.append("It is waiting in your Want to Watch list")

    return WatchPick(entry=entry, media=media, score=score, reasons=reasons[:3])


async def get_watch_pick(
    db,
    user_id: int,
    media_type: str = "all",
    length: str = "any",
    mood: str = "comfort",
    exclude_entry_id: Optional[int] = None,
    surprise: bool = False,
) -> Optional[WatchPick]:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    entry_stmt = (
        select(WatchEntry)
        .options(selectinload(WatchEntry.media_item))
        .where(
            WatchEntry.user_id == user_id,
            WatchEntry.status == "want_to_watch",
        )
    )
    if media_type in {"movie", "tv"}:
        entry_stmt = entry_stmt.join(WatchEntry.media_item).where(
            MediaItem.media_type == media_type
        )
    if exclude_entry_id is not None:
        entry_stmt = entry_stmt.where(WatchEntry.id != exclude_entry_id)

    entries = (await db.execute(entry_stmt)).scalars().all()
    entries = [
        entry for entry in entries
        if entry.media_item and _matches_length(entry.media_item, length)
    ]

    if not entries:
        return None

    watched_stmt = (
        select(WatchEntry)
        .options(selectinload(WatchEntry.media_item))
        .where(
            WatchEntry.user_id == user_id,
            WatchEntry.status == "watched",
        )
    )
    if media_type in {"movie", "tv"}:
        watched_stmt = watched_stmt.join(WatchEntry.media_item).where(
            MediaItem.media_type == media_type
        )
    watched = (await db.execute(watched_stmt)).scalars().all()

    rec_stmt = select(Recommendation.tmdb_id, Recommendation.media_type).where(
        Recommendation.receiver_id == user_id
    )
    recs = (await db.execute(rec_stmt)).all()
    incoming_recommendations = {(tmdb_id, media_kind) for tmdb_id, media_kind in recs}

    picks = [
        _score_candidate(entry, watched, incoming_recommendations, mood)
        for entry in entries
    ]
    picks.sort(key=lambda pick: (-pick.score, pick.media.title.casefold()))

    if surprise and len(picks) > 1:
        return random.choice(picks[: min(5, len(picks))])
    return picks[0]


def pick_length_label(media: MediaItem) -> str:
    return _format_length(media)
