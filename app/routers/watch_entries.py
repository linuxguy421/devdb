from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models import User, WatchEntry
from app.routers.auth import get_current_user_optional as get_current_user
from app.services.media_sync import get_or_sync_media_item
from app.services.progress import (
    start_watching,
    mark_next_episode_watched,
    complete,
    reset_progress,
    ProgressDomainError,
)
from app.services.tmdb import tmdb_service

router = APIRouter(prefix="/watch-entries", tags=["Watch Entries"])
templates = Jinja2Templates(directory="app/templates")


def render_toast(message: str, badge_type: str = "success") -> str:
    border_color = "border-emerald-500/40 text-emerald-400" if badge_type == "success" else "border-rose-500/40 text-rose-400"
    dot_color = "bg-emerald-400" if badge_type == "success" else "bg-rose-400"
    return f"""
    <div id="toast-container" hx-swap-oob="afterbegin">
        <div class="animate-toast flex items-center gap-2 bg-neutral-900 border {border_color} px-3.5 py-2.5 rounded-xl shadow-2xl text-xs font-semibold backdrop-blur-md pointer-events-auto">
            <span class="w-2 h-2 rounded-full {dot_color}"></span>
            <span>{message}</span>
        </div>
    </div>
    """


@router.post("", response_class=HTMLResponse)
@router.post("/add", response_class=HTMLResponse)
async def create_watch_entry(
    request: Request,
    tmdb_id: int = Form(...),
    media_type: str = Form(...),
    status_val: str = Form("want_to_watch"),
    from_modal: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": "/login"})

    norm_status = status_val
    if status_val in ("to_watch", "plan_to_watch"):
        norm_status = "want_to_watch"
    elif status_val == "currently_watching":
        norm_status = "in_progress"

    media_item = await get_or_sync_media_item(db, tmdb_id, media_type)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    stmt = select(WatchEntry).options(joinedload(WatchEntry.media_item)).where(
        WatchEntry.user_id == current_user.id,
        WatchEntry.media_item_id == media_item.id,
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()

    if not entry:
        entry = WatchEntry(
            user_id=current_user.id,
            media_item_id=media_item.id,
            status=norm_status,
        )
        db.add(entry)
    else:
        entry.status = norm_status

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        entry = (await db.execute(stmt)).scalar_one()
        entry.status = norm_status
        await db.commit()

    await db.refresh(entry)

    toast_msg = "Marked as watched!" if norm_status == "watched" else "Added to My Media!"
    toast_oob = render_toast(toast_msg)

    btn_html = templates.get_template("partials/watch_button.html").render(
        {"request": request, "entry": entry, "tmdb_id": tmdb_id, "media_type": media_type}
    )
    return HTMLResponse(content=btn_html + toast_oob)


@router.post("/{entry_id}/start", response_class=HTMLResponse)
async def action_start_watching(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED)

    stmt = select(WatchEntry).options(joinedload(WatchEntry.media_item)).where(
        WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    start_watching(entry)
    await db.commit()
    await db.refresh(entry)

    card_html = templates.get_template("partials/my_media_card.html").render({"request": request, "entry": entry})
    return HTMLResponse(content=card_html + render_toast("Moved to In Progress"))


@router.post("/{entry_id}/progress", response_class=HTMLResponse)
async def action_increment_progress(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED)

    stmt = select(WatchEntry).options(joinedload(WatchEntry.media_item)).where(
        WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    details = await tmdb_service.get_formatted_details(entry.media_item.tmdb_id, "tv")
    seasons_raw = details.get("seasons", []) if details else []

    season_episode_counts = {
        s["season_number"]: s["episode_count"]
        for s in seasons_raw
        if isinstance(s, dict) and "season_number" in s and "episode_count" in s
    }

    if not season_episode_counts and entry.media_item.total_seasons and entry.media_item.total_episodes:
        eps_per_season = max(1, entry.media_item.total_episodes // entry.media_item.total_seasons)
        season_episode_counts = {s: eps_per_season for s in range(1, entry.media_item.total_seasons + 1)}

    try:
        mark_next_episode_watched(entry, entry.media_item, season_episode_counts)
        await db.commit()
        await db.refresh(entry)
    except ProgressDomainError as err:
        return HTMLResponse(content=render_toast(str(err), badge_type="remove"), status_code=400)

    card_html = templates.get_template("partials/my_media_card.html").render({"request": request, "entry": entry})
    msg = "Completed series!" if entry.status == "watched" else f"Updated to S{entry.last_watched_season:02d}E{entry.last_watched_episode:02d}"
    return HTMLResponse(content=card_html + render_toast(msg))


@router.post("/{entry_id}/complete", response_class=HTMLResponse)
async def action_complete_media(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED)

    stmt = select(WatchEntry).options(joinedload(WatchEntry.media_item)).where(
        WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    complete(entry)
    await db.commit()
    await db.refresh(entry)

    card_html = templates.get_template("partials/my_media_card.html").render({"request": request, "entry": entry})
    return HTMLResponse(content=card_html + render_toast("Marked as Watched!"))


@router.post("/{entry_id}/reset", response_class=HTMLResponse)
async def action_reset_media(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED)

    stmt = select(WatchEntry).options(joinedload(WatchEntry.media_item)).where(
        WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    reset_progress(entry)
    await db.commit()
    await db.refresh(entry)

    card_html = templates.get_template("partials/my_media_card.html").render({"request": request, "entry": entry})
    return HTMLResponse(content=card_html + render_toast("Reset back to Want to Watch"))


@router.delete("/{entry_id}", response_class=HTMLResponse)
async def delete_watch_entry(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED)

    stmt = select(WatchEntry).where(WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id)
    entry = (await db.execute(stmt)).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    await db.delete(entry)
    await db.commit()

    card_oob_delete = f'<div id="entry-card-{entry_id}" hx-swap-oob="delete"></div>'
    return HTMLResponse(content=card_oob_delete + render_toast("Removed entry", badge_type="remove"))
