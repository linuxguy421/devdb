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


@router.get("/my-media", response_class=HTMLResponse)
async def my_media_page(
    request: Request,
    status: Optional[str] = "in_progress",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    valid_statuses = {"want_to_watch", "in_progress", "watched"}
    selected_status = status if status in valid_statuses or status == "all" else "in_progress"

    stmt = (
        select(WatchEntry)
        .options(joinedload(WatchEntry.media_item))
        .where(WatchEntry.user_id == current_user.id)
    )

    if selected_status != "all":
        stmt = stmt.where(WatchEntry.status == selected_status)

    stmt = stmt.order_by(WatchEntry.updated_at.desc())
    result = await db.execute(stmt)
    entries = result.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="my_media.html",
        context={
            "request": request,
            "current_user": current_user,
            "entries": entries,
            "current_status": selected_status,
        },
    )


@router.get("/to-watch")
async def redirect_to_watch():
    return RedirectResponse(url="/my-media?status=want_to_watch", status_code=301)


@router.get("/watched")
async def redirect_watched():
    return RedirectResponse(url="/my-media?status=watched", status_code=301)


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
