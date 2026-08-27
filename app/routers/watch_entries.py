from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, WatchEntry
from app.routers.auth import get_current_user
from app.services.tmdb import tmdb_service

router = APIRouter(prefix="/watch-entries", tags=["Watch Entries"])
templates = Jinja2Templates(directory="app/templates")

@router.post("", response_class=HTMLResponse)
async def create_watch_entry(
    request: Request,
    tmdb_id: int = Form(...),
    media_type: str = Form(...),
    status_val: str = Form("to_watch"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": "/login"})

    stmt = select(WatchEntry).where(WatchEntry.user_id == current_user.id, WatchEntry.tmdb_id == tmdb_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()

    if not entry:
        entry = WatchEntry(user_id=current_user.id, tmdb_id=tmdb_id, media_type=media_type, status=status_val)
        db.add(entry)
        await db.commit()
        await db.refresh(entry)

    return templates.TemplateResponse(
        request=request, name="partials/watch_button.html", context={"entry": entry, "tmdb_id": tmdb_id}
    )

@router.get("/{entry_id}/edit-modal", response_class=HTMLResponse)
async def get_edit_modal(
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
        raise HTTPException(status_code=404, detail="Entry not found")

    entry.tmdb_data = await tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type)

    return templates.TemplateResponse(
        request=request, name="partials/edit_modal.html", context={"entry": entry}
    )

@router.post("/{entry_id}/update", response_class=HTMLResponse)
async def update_watch_entry(
    request: Request,
    entry_id: int,
    rating: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    status_val: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": "/login"})

    stmt = select(WatchEntry).where(WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id)
    entry = (await db.execute(stmt)).scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    # Safely convert form string to int (or None if unrated/empty)
    if rating is not None:
        rating_str = rating.strip()
        entry.rating = int(rating_str) if rating_str.isdigit() else None

    if notes is not None:
        entry.notes = notes
    if status_val is not None:
        entry.status = status_val

    await db.commit()
    await db.refresh(entry)

    entry.tmdb_data = await tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type)

    # Render card partial
    card_html = templates.get_template("partials/watched_card.html").render({"request": request, "entry": entry})

    # Append OOB fragment to clear modal-container simultaneously
    oob_close_modal = '<div id="modal-container" hx-swap-oob="true"></div>'

    return HTMLResponse(content=card_html + oob_close_modal)

@router.post("/{entry_id}/quick-watched", response_class=HTMLResponse)
async def quick_mark_watched(
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

    entry.status = "watched"
    await db.commit()

    # Returning an empty response causes HTMX to remove the target card from the DOM
    return HTMLResponse(content="")
