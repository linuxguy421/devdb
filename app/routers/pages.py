from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Friendship, User, WatchEntry
from app.routers.auth import get_current_user
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
        .where(WatchEntry.user_id == current_user.id, WatchEntry.status == "watched")
        .order_by(WatchEntry.created_at.desc())
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    for entry in entries:
        entry.tmdb_data = await tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type)

    return templates.TemplateResponse(
        request=request, name="watched.html", context={"entries": entries, "current_user": current_user}
    )
