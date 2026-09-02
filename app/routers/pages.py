from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Friendship, User, WatchEntry
from app.routers.auth import get_current_user_optional as get_current_user
from app.services.media_sync import get_or_sync_media_item
from app.services.tmdb import tmdb_service

router = APIRouter(tags=["Pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        trending = await tmdb_service.get_trending()
    except Exception:
        trending = []

    stmt_pending_count = select(func.count(Friendship.id)).where(
        Friendship.buddy_id == current_user.id,
        Friendship.status == "pending"
    )
    pending_buddies_count = (await db.execute(stmt_pending_count)).scalar() or 0

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current_user": current_user,
            "trending": trending,
            "pending_buddies_count": pending_buddies_count,
        },
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: Optional[str] = None,
    success: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)

    error_msg = None
    if error == "invalid":
        error_msg = "Invalid username or password."
    elif isinstance(error, str):
        error_msg = error

    success_msg = None
    if success == "registered":
        success_msg = "Account created! Please sign in."

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error_msg, "success": success_msg},
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    error: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)

    error_msg = None
    if error == "exists":
        error_msg = "Username already exists."
    elif error == "email_exists":
        error_msg = "An account with that email already exists."
    elif isinstance(error, str):
        error_msg = error

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"error": error_msg},
    )


@router.get("/watched", response_class=HTMLResponse)
async def watched_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    stmt = (
        select(WatchEntry)
        .options(joinedload(WatchEntry.media_item))
        .where(WatchEntry.user_id == current_user.id, WatchEntry.status == "watched")
        .order_by(WatchEntry.created_at.desc())
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    dirty = False
    for entry in entries:
        if not entry.media_item:
            item = await get_or_sync_media_item(db, entry.tmdb_id, entry.media_type)
            if item:
                entry.media_item = item
                entry.media_item_id = item.id
                dirty = True

        if entry.media_item:
            m = entry.media_item
            entry.tmdb_data = {
                "id": m.tmdb_id,
                "title": m.title,
                "overview": m.overview,
                "poster_path": m.poster_path,
                "backdrop_path": m.backdrop_path,
                "release_date": m.release_date,
                "runtime": m.runtime,
                "genres": m.genres,
                "vote_average": m.vote_average,
            }
        else:
            entry.tmdb_data = await tmdb_service.get_formatted_details(
                entry.tmdb_id, entry.media_type
            )

    if dirty:
        await db.commit()

    return templates.TemplateResponse(
        request=request,
        name="watched.html",
        context={"entries": entries, "current_user": current_user},
    )
