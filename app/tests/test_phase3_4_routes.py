from unittest.mock import patch
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.responses import HTMLResponse

from app.database import get_db
from app.main import app
from app.models import MediaItem, User, WatchEntry
from app.routers.auth import get_current_user_optional


@pytest.mark.asyncio
async def test_my_media_page_and_redirects(db_session):
    user = User(username="route_tester", email="rt@example.com", hashed_password="pw")
    item = MediaItem(tmdb_id=505, media_type="movie", title="The Matrix")
    db_session.add_all([user, item])
    await db_session.commit()

    entry = WatchEntry(user_id=user.id, media_item_id=item.id, status="in_progress")
    db_session.add(entry)
    await db_session.commit()

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_current_user_optional] = lambda: user
    app.dependency_overrides[get_db] = _get_db_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("starlette.templating.Jinja2Templates.TemplateResponse", return_value=HTMLResponse("OK")):
            res = await ac.get("/my-media?status=in_progress")
            assert res.status_code == 200

        res_redirect = await ac.get("/watched", follow_redirects=False)
        assert res_redirect.status_code == 301
        assert res_redirect.headers["location"] == "/my-media?status=watched"

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_watch_entry_htmx_actions(db_session):
    user = User(username="action_tester", email="at@example.com", hashed_password="pw")
    item = MediaItem(tmdb_id=606, media_type="tv", title="Andor", total_seasons=2, total_episodes=24)
    db_session.add_all([user, item])
    await db_session.commit()

    entry = WatchEntry(user_id=user.id, media_item_id=item.id, status="want_to_watch")
    db_session.add(entry)
    await db_session.commit()

    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_current_user_optional] = lambda: user
    app.dependency_overrides[get_db] = _get_db_override

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        with patch("starlette.templating.Jinja2Templates.get_template") as mock_get_template:
            mock_get_template.return_value.render.return_value = "<div>Mock Card</div>"

            # Start watching
            res = await ac.post(f"/watch-entries/{entry.id}/start")
            assert res.status_code == 200

            await db_session.refresh(entry)
            assert entry.status == "in_progress"

            # Increment progress
            res_prog = await ac.post(f"/watch-entries/{entry.id}/progress")
            assert res_prog.status_code == 200

            await db_session.refresh(entry)
            assert entry.last_watched_season == 1
            assert entry.last_watched_episode == 1

            # Reset
            res_reset = await ac.post(f"/watch-entries/{entry.id}/reset")
            assert res_reset.status_code == 200

            await db_session.refresh(entry)
            assert entry.status == "want_to_watch"
            assert entry.last_watched_season is None

    app.dependency_overrides.clear()
