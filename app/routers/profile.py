from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.security import require_csrf
from app.models import Friendship, RecoveryCode, User, WatchEntry
from app.routers.auth import get_current_user_optional as get_current_user
from app.services.avatars import (
    AVATAR_URL_PREFIX,
    AvatarError,
    delete_local_avatar_by_url,
    is_local_avatar_url,
    save_avatar_upload,
)
from app.services.recovery_codes import generate_user_recovery_codes

router = APIRouter(prefix="/profile", tags=["Profile"], dependencies=[Depends(require_csrf)])
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
        context={
            "request": request,
            "current_user": current_user,
            "active_tab": tab,
            "avatar_is_local": is_local_avatar_url(current_user.avatar_url),
        },
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

    context = {
        "request": request,
        "current_user": current_user,
        "active_tab": tab_name,
        "avatar_is_local": is_local_avatar_url(current_user.avatar_url),
    }

    if tab_name == "buddies":
        stmt_pending = (
            select(Friendship)
            .options(selectinload(Friendship.requester))
            .where(Friendship.buddy_id == current_user.id, Friendship.status == "pending")
        )
        res_pending = await db.execute(stmt_pending)
        context["pending_requests"] = res_pending.scalars().all()

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

    elif tab_name == "security":
        stmt_codes = select(RecoveryCode).where(
            RecoveryCode.user_id == current_user.id,
            RecoveryCode.is_used == False,  # noqa: E712
        )
        res_codes = await db.execute(stmt_codes)
        active_codes = res_codes.scalars().all()
        context["active_recovery_codes_count"] = len(active_codes)

    elif tab_name == "settings":
        stmt_total = select(WatchEntry).where(WatchEntry.user_id == current_user.id)
        res_total = await db.execute(stmt_total)
        entries = res_total.scalars().all()

        context["stats"] = {
            "total_entries": len(entries),
            "watched": len([e for e in entries if e.status == "watched"]),
            "to_watch": len([e for e in entries if e.status == "want_to_watch"]),
        }

    template_map = {
        "edit": "partials/profile_tab_edit.html",
        "buddies": "partials/profile_tab_buddies.html",
        "security": "partials/profile_tab_security.html",
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
    new_url = (avatar_url or "").strip() or None

    # Never accept client-supplied local media paths (those are server-assigned only)
    if new_url and new_url.startswith(AVATAR_URL_PREFIX):
        new_url = None

    previous = current_user.avatar_url

    if new_url:
        # External URL replaces local file
        if is_local_avatar_url(previous):
            delete_local_avatar_by_url(previous)
        current_user.avatar_url = new_url
    else:
        # Empty URL field: keep existing local avatar; clear only external URLs
        if is_local_avatar_url(previous):
            pass  # retain local path; use Remove avatar to clear
        else:
            current_user.avatar_url = None

    current_user.bio = bio.strip() if bio else None
    await db.commit()

    response = HTMLResponse(status_code=200)
    response.headers["HX-Refresh"] = "true"
    return response


@router.post("/avatar", response_class=HTMLResponse)
async def upload_avatar(
    request: Request,
    avatar: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=401)

    try:
        public_url = await save_avatar_upload(
            avatar,
            replace_url=current_user.avatar_url,
        )
    except AvatarError as exc:
        return HTMLResponse(
            f"<div class='p-3 rounded-xl bg-red-950/40 border border-red-800/60 text-red-300 text-xs font-semibold'>{exc}</div>",
            status_code=400,
        )

    current_user.avatar_url = public_url
    await db.commit()

    response = HTMLResponse(status_code=200)
    response.headers["HX-Refresh"] = "true"
    return response


@router.post("/avatar/remove", response_class=HTMLResponse)
async def remove_avatar(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=401)

    if is_local_avatar_url(current_user.avatar_url):
        delete_local_avatar_by_url(current_user.avatar_url)

    current_user.avatar_url = None
    await db.commit()

    response = HTMLResponse(status_code=200)
    response.headers["HX-Refresh"] = "true"
    return response


@router.post("/change-password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=401)

    from app.routers.auth import get_password_hash, validate_password, verify_password

    if not verify_password(current_password, current_user.hashed_password):
        return HTMLResponse(
            "<div class='p-3 rounded-xl bg-red-950/40 border border-red-800/60 text-red-300 text-xs font-semibold'>Incorrect current password.</div>",
            status_code=400,
        )

    password_error = validate_password(new_password)
    if password_error:
        return HTMLResponse(
            f"<div class='p-3 rounded-xl bg-red-950/40 border border-red-800/60 text-red-300 text-xs font-semibold'>{password_error}</div>",
            status_code=400,
        )

    current_user.hashed_password = get_password_hash(new_password)
    await db.commit()

    return HTMLResponse(
        "<div class='p-3 rounded-xl bg-emerald-950/40 border border-emerald-800/60 text-emerald-300 text-xs font-semibold'>Password updated successfully!</div>"
    )


@router.post("/recovery-codes/regenerate", response_class=HTMLResponse)
async def regenerate_recovery_codes(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=401)

    codes = await generate_user_recovery_codes(db, current_user.id)

    return templates.TemplateResponse(
        request=request,
        name="partials/recovery_codes_modal.html",
        context={"request": request, "codes": codes},
    )
