import logging
from typing import Optional
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Friendship, User, WatchEntry
from app.routers.auth import get_current_user, verify_password, get_password_hash  # Adjust import to your password hash helpers

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/modal", response_class=HTMLResponse)
async def profile_modal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Fetch Quick Account Stats
    stmt_watched = select(func.count(WatchEntry.id)).where(
        WatchEntry.user_id == current_user.id, WatchEntry.status == "watched"
    )
    stmt_to_watch = select(func.count(WatchEntry.id)).where(
        WatchEntry.user_id == current_user.id, WatchEntry.status == "to_watch"
    )
    stmt_buddies = select(func.count(Friendship.id)).where(
        (Friendship.user_id == current_user.id) | (Friendship.buddy_id == current_user.id),
        Friendship.status == "accepted"
    )

    watched_count = (await db.execute(stmt_watched)).scalar() or 0
    to_watch_count = (await db.execute(stmt_to_watch)).scalar() or 0
    buddies_count = (await db.execute(stmt_buddies)).scalar() or 0

    return templates.TemplateResponse(
        request=request,
        name="partials/profile_modal.html",
        context={
            "current_user": current_user,
            "stats": {
                "watched": watched_count,
                "to_watch": to_watch_count,
                "buddies": buddies_count,
            },
        },
    )


@router.post("/update-info", response_class=HTMLResponse)
async def update_profile_info(
    request: Request,
    email: Optional[str] = Form(None),
    avatar_url: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if hasattr(current_user, "email"):
        current_user.email = email.strip() if email else None
    if hasattr(current_user, "avatar_url"):
        current_user.avatar_url = avatar_url.strip() if avatar_url else None
    if hasattr(current_user, "bio"):
        current_user.bio = bio.strip() if bio else None

    await db.commit()
    await db.refresh(current_user)

    return HTMLResponse(
        '<div class="p-3 bg-emerald-950/80 border border-emerald-800 text-emerald-300 text-xs rounded-xl font-semibold">Profile details updated successfully!</div>'
    )


@router.post("/change-password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Verify current password
    if not verify_password(current_password, current_user.hashed_password):
        return HTMLResponse(
            '<div class="p-3 bg-rose-950/80 border border-rose-800 text-rose-300 text-xs rounded-xl font-semibold">Current password is incorrect.</div>',
            status_code=400
        )

    if new_password != confirm_password:
        return HTMLResponse(
            '<div class="p-3 bg-rose-950/80 border border-rose-800 text-rose-300 text-xs rounded-xl font-semibold">New passwords do not match.</div>',
            status_code=400
        )

    if len(new_password) < 6:
        return HTMLResponse(
            '<div class="p-3 bg-rose-950/80 border border-rose-800 text-rose-300 text-xs rounded-xl font-semibold">Password must be at least 6 characters long.</div>',
            status_code=400
        )

    current_user.hashed_password = get_password_hash(new_password)
    await db.commit()

    return HTMLResponse(
        '<div class="p-3 bg-emerald-950/80 border border-emerald-800 text-emerald-300 text-xs rounded-xl font-semibold">Password changed successfully!</div>'
    )
