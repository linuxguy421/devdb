from typing import Optional
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Friendship, User, WatchEntry
from app.routers.auth import get_current_user_optional as get_current_user

router = APIRouter(prefix="/profile", tags=["Profile"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/modal", response_class=HTMLResponse)
@router.get("/edit-modal", response_class=HTMLResponse)
async def get_profile_modal(
    request: Request,
    tab: str = "edit",
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=401)

    return templates.TemplateResponse(
        request=request,
        name="partials/profile_modal.html",
        context={"request": request, "current_user": current_user, "active_tab": tab},
    )


@router.get("/tab/{tab_name}", response_class=HTMLResponse)
async def get_profile_tab(
    request: Request,
    tab_name: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=401)

    context = {"request": request, "current_user": current_user, "active_tab": tab_name}

    if tab_name == "buddies":
        # Query incoming pending requests
        stmt_pending = (
            select(Friendship)
            .options(selectinload(Friendship.requester))
            .where(Friendship.buddy_id == current_user.id, Friendship.status == "pending")
        )
        res_pending = await db.execute(stmt_pending)
        context["pending_requests"] = res_pending.scalars().all()

        # Query accepted friendships
        stmt_accepted = select(Friendship).where(
            or_(Friendship.user_id == current_user.id, Friendship.buddy_id == current_user.id),
            Friendship.status == "accepted",
        )
        res_accepted = await db.execute(stmt_accepted)
        accepted_friendships = res_accepted.scalars().all()

        buddy_ids = [
            f.buddy_id if f.user_id == current_user.id else f.user_id
            for f in accepted_friendships
        ]

        accepted_buddies = []
        if buddy_ids:
            stmt_buddies = select(User).where(User.id.in_(buddy_ids))
            res_buddies = await db.execute(stmt_buddies)
            accepted_buddies = res_buddies.scalars().all()

        context["accepted_buddies"] = accepted_buddies
        context["accepted_count"] = len(accepted_buddies)

    elif tab_name == "settings":
        # Calculate user entry statistics
        stmt_total = select(WatchEntry).where(WatchEntry.user_id == current_user.id)
        res_total = await db.execute(stmt_total)
        entries = res_total.scalars().all()

        context["stats"] = {
            "total_entries": len(entries),
            "watched": len([e for e in entries if e.status == "watched"]),
            "to_watch": len([e for e in entries if e.status in ("to_watch", "plan_to_watch")]),
        }

    template_map = {
        "edit": "partials/profile_tab_edit.html",
        "buddies": "partials/profile_tab_buddies.html",
        "settings": "partials/profile_tab_settings.html",
    }

    template_name = template_map.get(tab_name, "partials/profile_tab_edit.html")
    return templates.TemplateResponse(request=request, name=template_name, context=context)


@router.post("/update", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    username: str = Form(...),
    avatar_url: Optional[str] = Form(None),
    bio: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=401)

    current_user.username = username.strip()
    current_user.avatar_url = avatar_url.strip() if avatar_url else None
    current_user.bio = bio.strip() if bio else None
    await db.commit()

    response = HTMLResponse(status_code=200)
    response.headers["HX-Refresh"] = "true"
    return response
