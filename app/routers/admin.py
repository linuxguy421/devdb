"""Administrator routes: dashboard, user list, enable/disable accounts."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import MediaItem, User, WatchEntry
from app.routers.auth import require_admin

router = APIRouter(prefix="/admin", tags=["Admin"])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    active_count = (
        await db.execute(select(func.count(User.id)).where(User.is_active.is_(True)))
    ).scalar() or 0
    admin_count = (
        await db.execute(select(func.count(User.id)).where(User.is_admin.is_(True)))
    ).scalar() or 0
    media_count = (await db.execute(select(func.count(MediaItem.id)))).scalar() or 0
    entry_count = (await db.execute(select(func.count(WatchEntry.id)))).scalar() or 0

    db_ok = True
    try:
        await db.execute(select(1))
    except Exception:
        db_ok = False

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "current_user": current_user,
            "counts": {
                "users": user_count,
                "active_users": active_count,
                "admins": admin_count,
                "media_items": media_count,
                "watch_entries": entry_count,
            },
            "db_ok": db_ok,
        },
    )


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    q: Optional[str] = Query(None),
    status_filter: Optional[str] = Query("all", alias="status"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    stmt = select(User).order_by(User.created_at.desc())

    search = (q or "").strip()
    if search:
        like = f"%{search}%"
        stmt = stmt.where(
            or_(User.username.ilike(like), User.email.ilike(like))
        )

    if status_filter == "active":
        stmt = stmt.where(User.is_active.is_(True))
    elif status_filter == "disabled":
        stmt = stmt.where(User.is_active.is_(False))
    elif status_filter == "admin":
        stmt = stmt.where(User.is_admin.is_(True))

    result = await db.execute(stmt)
    users = result.scalars().all()

    # Entry counts per user (batch)
    entry_counts = {}
    if users:
        ids = [u.id for u in users]
        count_stmt = (
            select(WatchEntry.user_id, func.count(WatchEntry.id))
            .where(WatchEntry.user_id.in_(ids))
            .group_by(WatchEntry.user_id)
        )
        count_result = await db.execute(count_stmt)
        entry_counts = {row[0]: row[1] for row in count_result.all()}

    return templates.TemplateResponse(
        request=request,
        name="admin/users.html",
        context={
            "current_user": current_user,
            "users": users,
            "entry_counts": entry_counts,
            "search_query": search,
            "status_filter": status_filter or "all",
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if user_id == current_user.id:
        return RedirectResponse(
            url="/admin/users?error=You+cannot+disable+your+own+account",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    target = result.scalar_one_or_none()
    if not target:
        return RedirectResponse(
            url="/admin/users?error=User+not+found",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target.is_active = not target.is_active
    await db.commit()

    action = "enabled" if target.is_active else "disabled"
    return RedirectResponse(
        url=f"/admin/users?message=User+{target.username}+{action}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
