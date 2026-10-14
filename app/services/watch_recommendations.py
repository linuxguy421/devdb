from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Optional

from app.models import Friendship, MediaItem, Recommendation, User, WatchEntry


@dataclass(frozen=True)
class WatchCandidate:
    """Normalized title candidate; entry is absent for external discoveries."""

    media: MediaItem
    source: str
    entry: Optional[WatchEntry] = None
    recommendation_names: list[str] = field(default_factory=list)
    recommendation_notes: list[str] = field(default_factory=list)


@dataclass
class WatchPick:
    entry: Optional[WatchEntry]
    media: MediaItem
    score: float
    reasons: list[str]
    source: str = "want_to_watch"
    recommendation_names: list[str] = field(default_factory=list)
    recommendation_notes: list[str] = field(default_factory=list)


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
    entry: WatchEntry | WatchCandidate,
    watched: list[WatchEntry],
    incoming_recommendations: set[tuple[int, str]],
    mood: str,
    profile: Optional[tuple[Counter[str], dict[str, float], float]] = None,
) -> WatchPick:
    candidate = (
        entry
        if isinstance(entry, WatchCandidate)
        else WatchCandidate(media=entry.media_item, source="want_to_watch", entry=entry)
    )
    media = candidate.media

    if profile is None:
        counts, genre_averages = _genre_stats(watched)
        rated = [e.rating for e in watched if e.rating is not None]
        global_avg = sum(rated) / len(rated) if rated else 7.0
    else:
        counts, genre_averages, global_avg = profile

    candidate_genres = _genres(media)
    known_genres = {_genre_key(g) for g in counts}
    matched_genres = [_genre_key(g) for g in candidate_genres if _genre_key(g) in known_genres]

    score = 0.0
    reasons: list[str] = []
    if candidate.recommendation_names:
        names = ", ".join(candidate.recommendation_names[:3])
        reasons.append(f"Recommended by {names}")
    if candidate.recommendation_notes and candidate.recommendation_notes[0]:
        reasons.append(f"Buddy note: {candidate.recommendation_notes[0][:100]}")

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

        watched_types = Counter(
            e.media_item.media_type
            for e in watched
            if getattr(e, "media_item", None) is not None
            and getattr(e.media_item, "media_type", None) in {"movie", "tv"}
        )
        total_watched = sum(watched_types.values())
        if total_watched >= 4:
            preferred_type, preferred_count = watched_types.most_common(1)[0]
            share = preferred_count / total_watched
            if share >= 0.65:
                if media.media_type == preferred_type:
                    score += 3
                    reasons.append(
                        "It matches your usual "
                        f"{'movies' if preferred_type == 'movie' else 'TV'} preference"
                    )
                elif media.media_type in {"movie", "tv"}:
                    score -= 1.5
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
        reasons.append(
            "It is waiting in your Want to Watch list"
            if candidate.source == "want_to_watch"
            else "It was discovered on TMDB and matches your filters"
        )

    return WatchPick(
        entry=candidate.entry,
        media=media,
        score=score,
        reasons=reasons[:3],
        source=candidate.source,
        recommendation_names=candidate.recommendation_names,
        recommendation_notes=candidate.recommendation_notes,
    )


class CandidateSource:
    """Interface for database-backed candidate sources.

    Each source returns normalized WatchCandidate objects. External candidates
    can omit the WatchEntry and still use the shared ranking pipeline.
    """

    name = "base"

    async def fetch(
        self,
        db,
        user_id: int,
        media_type: str,
        length: str,
        exclude_entry_id: Optional[int],
    ) -> list[WatchCandidate]:
        raise NotImplementedError


class WantToWatchSource(CandidateSource):
    """Fetch eligible titles already saved in the user's Want to Watch list."""

    name = "want_to_watch"

    async def fetch(
        self,
        db,
        user_id: int,
        media_type: str = "all",
        length: str = "any",
        exclude_entry_id: Optional[int] = None,
    ) -> list[WatchCandidate]:
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        stmt = (
            select(WatchEntry)
            .options(selectinload(WatchEntry.media_item))
            .where(
                WatchEntry.user_id == user_id,
                WatchEntry.status == "want_to_watch",
            )
        )
        if media_type in {"movie", "tv"}:
            stmt = stmt.join(WatchEntry.media_item).where(
                MediaItem.media_type == media_type
            )
        if exclude_entry_id is not None:
            stmt = stmt.where(WatchEntry.id != exclude_entry_id)

        entries = (await db.execute(stmt)).scalars().all()
        return [
            WatchCandidate(
                media=entry.media_item,
                source=self.name,
                entry=entry,
            )
            for entry in entries
            if entry.media_item and _matches_length(entry.media_item, length)
        ]


class TMDBDiscoverySource(CandidateSource):
    """Discover external titles without persisting them to the user's library."""

    name = "tmdb_discovery"

    # TMDB genre IDs are stable identifiers. Keep labels normalized to the
    # comma-separated format used by MediaItem and the ranking profile.
    GENRES = {
        "movie": {
            28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
            80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
            14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
            9648: "Mystery", 10749: "Romance", 878: "Science Fiction",
            10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
        },
        "tv": {
            10759: "Action & Adventure", 16: "Animation", 35: "Comedy",
            80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
            10762: "Kids", 9648: "Mystery", 10763: "News", 10764: "Reality",
            10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk",
            10768: "War & Politics", 37: "Western",
        },
    }

    async def fetch(
        self,
        db,
        user_id: int,
        media_type: str = "all",
        length: str = "any",
        exclude_entry_id: Optional[int] = None,
    ) -> list[WatchCandidate]:
        from sqlalchemy import select
        from app.services.tmdb import tmdb_service

        existing_stmt = (
            select(MediaItem.tmdb_id, MediaItem.media_type)
            .join(WatchEntry, WatchEntry.media_item_id == MediaItem.id)
            .where(WatchEntry.user_id == user_id)
        )
        existing = {
            (tmdb_id, kind)
            for tmdb_id, kind in (await db.execute(existing_stmt)).all()
        }

        kinds = [media_type] if media_type in {"movie", "tv"} else ["movie", "tv"]
        candidates: list[WatchCandidate] = []
        for kind in kinds:
            # The existing service caches discovery results; one page per type
            # keeps the request bounded and avoids unbounded external API calls.
            try:
                payload = await tmdb_service.discover_titles(
                    media_type=kind,
                    sort_by="popularity.desc",
                )
            except Exception:
                # A transient TMDB failure should not take down the blended
                # recommendation page or prevent the local-list source working.
                continue
            for raw in payload.get("results", []):
                tmdb_id = raw.get("id")
                if not tmdb_id or (tmdb_id, kind) in existing:
                    continue

                title = raw.get("title") if kind == "movie" else raw.get("name")
                if not title:
                    continue

                genre_map = self.GENRES[kind]
                genres = [
                    genre_map[genre_id]
                    for genre_id in raw.get("genre_ids", [])
                    if genre_id in genre_map
                ]
                media = MediaItem(
                    tmdb_id=tmdb_id,
                    media_type=kind,
                    title=title,
                    overview=raw.get("overview"),
                    poster_path=raw.get("poster_path"),
                    backdrop_path=raw.get("backdrop_path"),
                    release_date=raw.get("release_date") if kind == "movie" else raw.get("first_air_date"),
                    runtime=None,
                    genres=", ".join(genres) or None,
                    vote_average=raw.get("vote_average"),
                    total_seasons=None,
                    total_episodes=raw.get("number_of_episodes"),
                )
                if length != "any" and _runtime_bucket(media) != "unknown" and not _matches_length(media, length):
                    continue
                candidates.append(
                    WatchCandidate(media=media, source=self.name, entry=None)
                )

        return candidates


class BuddyRecommendationSource(CandidateSource):
    """Fetch incoming recommendations from accepted buddies, without persisting metadata."""

    name = "buddies"

    async def fetch(
        self,
        db,
        user_id: int,
        media_type: str = "all",
        length: str = "any",
        exclude_entry_id: Optional[int] = None,
    ) -> list[WatchCandidate]:
        from sqlalchemy import and_, or_, select
        from app.services.tmdb import tmdb_service

        friendship = select(Friendship.id).where(
            Friendship.status == "accepted",
            or_(
                and_(Friendship.user_id == user_id, Friendship.buddy_id == Recommendation.sender_id),
                and_(Friendship.buddy_id == user_id, Friendship.user_id == Recommendation.sender_id),
            ),
        ).exists()
        stmt = (
            select(Recommendation, User.username)
            .join(User, User.id == Recommendation.sender_id)
            .where(Recommendation.receiver_id == user_id, friendship)
            .order_by(Recommendation.created_at.desc())
            .limit(50)
        )
        if media_type in {"movie", "tv"}:
            stmt = stmt.where(Recommendation.media_type == media_type)
        rows = (await db.execute(stmt)).all()
        grouped: dict[tuple[int, str], dict] = {}
        for rec, username in rows:
            key = (rec.tmdb_id, rec.media_type)
            item = grouped.setdefault(key, {"names": [], "notes": []})
            if username not in item["names"]:
                item["names"].append(username)
            if rec.note and rec.note not in item["notes"]:
                item["notes"].append(rec.note)

        candidates: list[WatchCandidate] = []
        for (tmdb_id, kind), info in grouped.items():
            try:
                details = await tmdb_service.get_formatted_details(tmdb_id, kind)
            except Exception:
                continue
            if not details or not details.get("title"):
                continue
            raw_genres = details.get("genres") or []
            genre_names = [
                genre.get("name", "") if isinstance(genre, dict) else str(genre)
                for genre in raw_genres
            ]
            runtime = details.get("runtime")
            media = MediaItem(
                tmdb_id=tmdb_id,
                media_type=kind,
                title=details.get("title"),
                overview=details.get("overview"),
                poster_path=details.get("poster_path"),
                backdrop_path=details.get("backdrop_path"),
                release_date=details.get("release_date"),
                runtime=runtime if kind == "movie" else None,
                genres=", ".join(name for name in genre_names if name) or None,
                vote_average=details.get("vote_average"),
                total_seasons=details.get("number_of_seasons"),
                total_episodes=details.get("number_of_episodes"),
            )
            if not _matches_length(media, length):
                # Keep unknown runtimes eligible, matching discovery's behavior.
                if length != "any" and _runtime_bucket(media) != "unknown":
                    continue
            candidates.append(WatchCandidate(
                media=media,
                source=self.name,
                recommendation_names=info["names"],
                recommendation_notes=info["notes"],
            ))
        return candidates


async def get_watch_pick(
    db,
    user_id: int,
    media_type: str = "all",
    length: str = "any",
    mood: str = "comfort",
    exclude_entry_id: Optional[int] = None,
    surprise: bool = False,
    source: str = "for_you",
    exclude_tmdb_id: Optional[int] = None,
    genre: str = "any",
    min_rating: float = 0,
    year_filter: str = "any",
) -> Optional[WatchPick]:
    source_map = {
        "my_list": [WantToWatchSource()],
        "discover": [TMDBDiscoverySource()],
        "buddies": [BuddyRecommendationSource()],
        "for_you": [WantToWatchSource(), BuddyRecommendationSource(), TMDBDiscoverySource()],
    }
    sources = source_map.get(source, source_map["for_you"])
    candidates: list[WatchCandidate] = []
    for candidate_source in sources:
        candidates.extend(
            await candidate_source.fetch(
                db,
                user_id,
                media_type=media_type,
                length=length,
                exclude_entry_id=exclude_entry_id,
            )
        )

    # Multiple providers may surface the same title. Prefer the saved entry
    # when present so existing watch actions remain available.
    unique: dict[tuple[int, str], WatchCandidate] = {}
    for candidate in candidates:
        key = (candidate.media.tmdb_id, candidate.media.media_type)
        previous = unique.get(key)
        if previous is None or (previous.entry is None and candidate.entry is not None):
            unique[key] = candidate
    candidates = [
        candidate for candidate in unique.values()
        if (exclude_tmdb_id is None or candidate.media.tmdb_id != exclude_tmdb_id)
        and (genre == "any" or any(_genre_key(g) == _genre_key(genre) for g in _genres(candidate.media)))
        and ((candidate.media.vote_average or 0) >= min_rating)
        and (
            year_filter == "any"
            or (
                bool(candidate.media.release_date)
                and candidate.media.release_date[:4].isdigit()
                and (
                    candidate.media.release_date[:4] == year_filter
                    if year_filter.isdigit()
                    else year_filter.startswith("decade_")
                    and int(year_filter.replace("decade_", "").replace("s", "")) <= int(candidate.media.release_date[:4]) <= int(year_filter.replace("decade_", "").replace("s", "")) + 9
                )
            )
        )
    ]

    if not candidates:
        return None

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

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

    counts, genre_averages = _genre_stats(watched)
    rated = [e.rating for e in watched if e.rating is not None]
    global_avg = sum(rated) / len(rated) if rated else 7.0
    profile = (counts, genre_averages, global_avg)

    picks = [
        _score_candidate(
            candidate,
            watched,
            incoming_recommendations,
            mood,
            profile=profile,
        )
        for candidate in candidates
    ]
    picks.sort(key=lambda pick: (-pick.score, pick.media.title.casefold()))

    if surprise and len(picks) > 1:
        return random.choice(picks[: min(5, len(picks))])
    return picks[0]


def pick_length_label(media: MediaItem) -> str:
    return _format_length(media)
