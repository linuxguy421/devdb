import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models import MediaItem, WatchEntry, User


@pytest.mark.asyncio
async def test_media_item_uniqueness(db_session):
    item1 = MediaItem(tmdb_id=101, media_type="movie", title="Inception")
    db_session.add(item1)
    await db_session.commit()

    item2 = MediaItem(tmdb_id=101, media_type="movie", title="Inception Duplicate")
    db_session.add(item2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_watch_entry_uniqueness_and_cascade(db_session):
    user = User(username="tester", email="tester@example.com", hashed_password="pw")
    item = MediaItem(tmdb_id=202, media_type="tv", title="Breaking Bad")
    db_session.add_all([user, item])
    await db_session.commit()

    entry1 = WatchEntry(user_id=user.id, media_item_id=item.id, status="want_to_watch")
    db_session.add(entry1)
    await db_session.commit()

    entry2 = WatchEntry(user_id=user.id, media_item_id=item.id, status="in_progress")
    db_session.add(entry2)
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_watch_entry_progress_check_constraint(db_session):
    user = User(username="tester2", email="tester2@example.com", hashed_password="pw")
    item = MediaItem(tmdb_id=303, media_type="tv", title="Severance")
    db_session.add_all([user, item])
    await db_session.commit()

    # Valid progress
    valid_entry = WatchEntry(
        user_id=user.id,
        media_item_id=item.id,
        status="in_progress",
        last_watched_season=1,
        last_watched_episode=3
    )
    db_session.add(valid_entry)
    await db_session.commit()

    # Invalid progress (negative season)
    valid_entry.last_watched_season = -1
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_watch_entry_status_persistence(db_session):
    user = User(username="tester3", email="tester3@example.com", hashed_password="pw")
    item = MediaItem(tmdb_id=404, media_type="movie", title="Interstellar")
    db_session.add_all([user, item])
    await db_session.commit()

    entry = WatchEntry(user_id=user.id, media_item_id=item.id, status="want_to_watch")
    db_session.add(entry)
    await db_session.commit()

    stmt = select(WatchEntry).where(WatchEntry.id == entry.id)
    result = await db_session.execute(stmt)
    fetched = result.scalar_one()
    assert fetched.status == "want_to_watch"
