"""Administrator routes: dashboard, users, promote/demote, audit log."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import settings
from app.database import get_db
from app.models import AdminAuditLog, MediaItem, User, WatchEntry
from app.routers.auth import require_admin

router = APIRouter(prefix="/admin", tags=["Admin"])
templates = Jinja2Templates(directory="app/templates")

AUDIT_ACTIONS = (
    "user.enabled",
    "user.disabled",
    "user.promoted",
    "user.demoted",
)


async def _log_action(
    db: AsyncSession,
    *,
    actor: User,
    target: Optional[User],
    action: str,
    detail: str | None = None,
) -> None:
    db.add(
        AdminAuditLog(
            actor_id=actor.id,
            target_user_id=target.id if target else None,
            action=action,
            detail=detail,
        )
    )


def _redirect_after_user_action(
    user_id: int,
    redirect_to: str | None = None,
    message: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    params = []
    if message:
        params.append(f"message={quote(message)}")
    if error:
        params.append(f"error={quote(error)}")
    qs = ("?" + "&".join(params)) if params else ""

    if redirect_to == "detail":
        return RedirectResponse(
            url=f"/admin/users/{user_id}{qs}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse(url=f"/admin/users{qs}", status_code=status.HTTP_303_SEE_OTHER)


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
    disabled_count = user_count - active_count

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_login_count = (
        await db.execute(
            select(func.count(User.id)).where(User.last_login_at >= week_ago)
        )
    ).scalar() or 0

    db_ok = True
    try:
        await db.execute(select(1))
    except Exception:
        db_ok = False

    recent_stmt = (
        select(AdminAuditLog)
        .options(
            joinedload(AdminAuditLog.actor),
            joinedload(AdminAuditLog.target_user),
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(8)
    )
    recent_logs = (await db.execute(recent_stmt)).unique().scalars().all()

    app_version = os.environ.get("APP_VERSION", "dev")

    return templates.TemplateResponse(
        request=request,
        name="admin/dashboard.html",
        context={
            "current_user": current_user,
            "counts": {
                "users": user_count,
                "active_users": active_count,
                "disabled_users": disabled_count,
                "admins": admin_count,
                "media_items": media_count,
                "watch_entries": entry_count,
                "recent_logins": recent_login_count,
            },
            "db_ok": db_ok,
            "recent_logs": recent_logs,
            "app_version": app_version,
            "environment": settings.ENVIRONMENT,
            "debug": settings.DEBUG,
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

    admin_count = (
        await db.execute(select(func.count(User.id)).where(User.is_admin.is_(True)))
    ).scalar() or 0

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
            "admin_count": admin_count,
            "is_super_admin": settings.is_super_admin,
        },
    )


@router.get("/users/{user_id}", response_class=HTMLResponse)
async def admin_user_detail(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    target = result.scalar_one_or_none()
    if not target:
        return RedirectResponse(
            url="/admin/users?error=" + quote("User not found."),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    status_counts_rows = (
        await db.execute(
            select(WatchEntry.status, func.count(WatchEntry.id))
            .where(WatchEntry.user_id == user_id)
            .group_by(WatchEntry.status)
        )
    ).all()
    status_counts = {row[0]: row[1] for row in status_counts_rows}
    total_entries = sum(status_counts.values())

    recent_entries_stmt = (
        select(WatchEntry)
        .options(joinedload(WatchEntry.media_item))
        .where(WatchEntry.user_id == user_id)
        .order_by(WatchEntry.updated_at.desc().nullslast(), WatchEntry.created_at.desc())
        .limit(12)
    )
    recent_entries = (await db.execute(recent_entries_stmt)).unique().scalars().all()

    audit_stmt = (
        select(AdminAuditLog)
        .options(
            joinedload(AdminAuditLog.actor),
            joinedload(AdminAuditLog.target_user),
        )
        .where(
            or_(
                AdminAuditLog.target_user_id == user_id,
                AdminAuditLog.actor_id == user_id,
            )
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(20)
    )
    user_logs = (await db.execute(audit_stmt)).unique().scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin/user_detail.html",
        context={
            "current_user": current_user,
            "target": target,
            "is_super": settings.is_super_admin(target.username),
            "status_counts": status_counts,
            "total_entries": total_entries,
            "recent_entries": recent_entries,
            "user_logs": user_logs,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
            "is_super_admin": settings.is_super_admin,
        },
    )


@router.post("/users/{user_id}/toggle-active")
async def toggle_user_active(
    user_id: int,
    reason: Optional[str] = Form(None),
    redirect_to: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if user_id == current_user.id:
        return _redirect_after_user_action(
            user_id, redirect_to, error="You cannot disable your own account."
        )

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    target = result.scalar_one_or_none()
    if not target:
        return _redirect_after_user_action(user_id, redirect_to, error="User not found.")

    if settings.is_super_admin(target.username):
        return _redirect_after_user_action(
            user_id,
            redirect_to,
            error="Cannot disable the super admin (SUPER_ADMIN).",
        )

    target.is_active = not target.is_active
    action = "user.enabled" if target.is_active else "user.disabled"
    reason_clean = (reason or "").strip()
    detail_parts = [f"{target.username} set active={target.is_active}"]
    if reason_clean and not target.is_active:
        detail_parts.append(f"reason={reason_clean}")
    await _log_action(
        db,
        actor=current_user,
        target=target,
        action=action,
        detail="; ".join(detail_parts),
    )
    await db.commit()

    label = "enabled" if target.is_active else "disabled"
    return _redirect_after_user_action(
        user_id, redirect_to, message=f"User {target.username} {label}."
    )


@router.post("/users/{user_id}/toggle-admin")
async def toggle_user_admin(
    user_id: int,
    redirect_to: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    if user_id == current_user.id:
        return _redirect_after_user_action(
            user_id, redirect_to, error="You cannot change your own admin role."
        )

    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    target = result.scalar_one_or_none()
    if not target:
        return _redirect_after_user_action(user_id, redirect_to, error="User not found.")

    if settings.is_super_admin(target.username):
        return _redirect_after_user_action(
            user_id,
            redirect_to,
            error="Cannot demote the super admin (SUPER_ADMIN).",
        )

    if target.is_admin:
        admin_count = (
            await db.execute(select(func.count(User.id)).where(User.is_admin.is_(True)))
        ).scalar() or 0
        if admin_count <= 1:
            return _redirect_after_user_action(
                user_id, redirect_to, error="Cannot demote the last administrator."
            )

    target.is_admin = not target.is_admin
    action = "user.promoted" if target.is_admin else "user.demoted"
    await _log_action(
        db,
        actor=current_user,
        target=target,
        action=action,
        detail=f"{target.username} is_admin={target.is_admin}",
    )
    await db.commit()

    label = "promoted to admin" if target.is_admin else "removed from admins"
    return _redirect_after_user_action(
        user_id, redirect_to, message=f"User {target.username} {label}."
    )


@router.get("/audit", response_class=HTMLResponse)
async def admin_audit(
    request: Request,
    action: Optional[str] = Query(None),
    actor: Optional[str] = Query(None),
    target: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    stmt = (
        select(AdminAuditLog)
        .options(
            joinedload(AdminAuditLog.actor),
            joinedload(AdminAuditLog.target_user),
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(200)
    )

    action_clean = (action or "").strip()
    if action_clean and action_clean != "all":
        stmt = stmt.where(AdminAuditLog.action == action_clean)

    actor_clean = (actor or "").strip()
    if actor_clean:
        stmt = stmt.join(AdminAuditLog.actor).where(
            User.username.ilike(f"%{actor_clean}%")
        )

    target_clean = (target or "").strip()
    if target_clean:
        # Use alias-safe filter via subquery on target_user relationship
        target_ids = (
            select(User.id).where(User.username.ilike(f"%{target_clean}%"))
        )
        stmt = stmt.where(AdminAuditLog.target_user_id.in_(target_ids))

    since_dt = None
    until_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
            stmt = stmt.where(AdminAuditLog.created_at >= since_dt)
        except ValueError:
            since_dt = None
    if until:
        try:
            until_dt = datetime.fromisoformat(until).replace(tzinfo=timezone.utc)
            # Inclusive end-of-day if date-only (YYYY-MM-DD)
            if len(until.strip()) <= 10:
                until_dt = until_dt + timedelta(days=1) - timedelta(microseconds=1)
            stmt = stmt.where(AdminAuditLog.created_at <= until_dt)
        except ValueError:
            until_dt = None

    logs = (await db.execute(stmt)).unique().scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="admin/audit.html",
        context={
            "current_user": current_user,
            "logs": logs,
            "actions": AUDIT_ACTIONS,
            "filter_action": action_clean or "all",
            "filter_actor": actor_clean,
            "filter_target": target_clean,
            "filter_since": since or "",
            "filter_until": until or "",
        },
    )
