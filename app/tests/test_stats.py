from datetime import datetime, timezone

import pytest

from app.models import MediaItem, User, WatchEntry
from app.services.stats import get_stats


@pytest.mark.asyncio
async def test_stats_aggregates_watch_data(db_session):
    user = User(username="stats_user", email="stats@example.com", hashed_password="pw")
    movie = MediaItem(
        tmdb_id=1,
        media_type="movie",
        title="Movie One",
        release_date="2020-04-01",
        genres="Drama, Science Fiction",
    )
    tv = MediaItem(
        tmdb_id=2,
        media_type="tv",
        title="TV One",
        release_date="2019-01-01",
        genres="Drama, Comedy",
    )
    pending = MediaItem(tmdb_id=3, media_type="movie", title="Pending")
    db_session.add_all([user, movie, tv, pending])
    await db_session.commit()

    db_session.add_all([
        WatchEntry(
            user_id=user.id,
            media_item_id=movie.id,
            status="watched",
            rating=9,
            completed_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        ),
        WatchEntry(
            user_id=user.id,
            media_item_id=tv.id,
            status="watched",
            rating=7,
            completed_at=datetime(2026, 2, 11, tzinfo=timezone.utc),
        ),
        WatchEntry(user_id=user.id, media_item_id=pending.id, status="want_to_watch"),
    ])
    await db_session.commit()

    stats = await get_stats(db_session, user.id, year=2026)

    assert stats["overview"]["total_entries"] == 3
    assert stats["overview"]["watched"] == 2
    assert stats["overview"]["want_to_watch"] == 1
    assert stats["overview"]["completion_rate"] == pytest.approx(66.7)
    assert stats["overview"]["average_rating"] == 8.0
    assert stats["watched_types"] == {"movies": 1, "tv": 1, "total": 2}
    assert stats["trend"][0]["count"] == 1
    assert stats["trend"][1]["count"] == 1
    assert stats["genres"][0]["name"] == "Drama"
    assert stats["genres"][0]["count"] == 2
    assert stats["genre_ratings"][0]["name"] == "Drama"
    assert stats["genre_ratings"][0]["average"] == 8.0
    assert stats["release_years"] == [{"label": "2010s", "count": 1}, {"label": "2020s", "count": 1}]
    assert stats["tv"]["tracked"] == 1
    assert stats["tv"]["completed"] == 1


@pytest.mark.asyncio
async def test_stats_handles_empty_library(db_session):
    user = User(username="empty_stats", email="empty@example.com", hashed_password="pw")
    db_session.add(user)
    await db_session.commit()

    stats = await get_stats(db_session, user.id)

    assert stats["overview"]["total_entries"] == 0
    assert stats["overview"]["completion_rate"] == 0
    assert stats["overview"]["average_rating"] is None
    assert stats["genres"] == []
    assert stats["release_years"] == []
    assert stats["milestones"]["first_completed"] is None
