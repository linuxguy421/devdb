from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, WatchEntry
from app.routers.auth import get_current_user_optional as get_current_user
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
async def create_watch_entry(
    request: Request,
    tmdb_id: int = Form(...),
    media_type: str = Form(...),
    status_val: str = Form("to_watch"),
    from_modal: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": "/login"})

    stmt = select(WatchEntry).where(
        WatchEntry.user_id == current_user.id,
        WatchEntry.tmdb_id == tmdb_id,
        WatchEntry.media_type == media_type,
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()

    if not entry:
        entry = WatchEntry(user_id=current_user.id, tmdb_id=tmdb_id, media_type=media_type, status=status_val)
        db.add(entry)
    else:
        entry.status = status_val

    try:
        await db.commit()
    except IntegrityError:
        # Lost a race with a duplicate submit; fall back to the row that won.
        await db.rollback()
        stmt = select(WatchEntry).where(
            WatchEntry.user_id == current_user.id,
            WatchEntry.tmdb_id == tmdb_id,
            WatchEntry.media_type == media_type,
        )
        entry = (await db.execute(stmt)).scalar_one()
        entry.status = status_val
        await db.commit()

    await db.refresh(entry)

    toast_oob = render_toast("Added to watchlist!")

    if status_val != "watched":
        # "Want to see" keeps the old, no-modal behavior.
        if from_modal == "true":
            return HTMLResponse(content=f'<div id="modal-container" hx-swap-oob="true"></div>{toast_oob}')

        btn_html = templates.get_template("partials/watch_button.html").render(
            {"request": request, "entry": entry, "tmdb_id": tmdb_id, "media_type": media_type}
        )
        return HTMLResponse(content=btn_html + toast_oob)

    # Marked watched: jump straight to the rating/notes modal rather than
    # leaving the user to go find it themselves afterwards.
    entry.tmdb_data = await tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type)
    edit_modal_html = templates.get_template("partials/edit_modal.html").render(
        {"request": request, "entry": entry}
    )
    modal_oob = f'<div id="modal-container" hx-swap-oob="true">{edit_modal_html}</div>'

    btn_html = templates.get_template("partials/watch_button.html").render(
        {"request": request, "entry": entry, "tmdb_id": tmdb_id, "media_type": media_type}
    )
    btn_oob = btn_html.replace(f'id="watch-btn-{tmdb_id}"', f'id="watch-btn-{tmdb_id}" hx-swap-oob="true"')

    if from_modal == "true":
        # Came from the title info modal (which is already open) -- update
        # the grid card behind it too, so it's correct once the edit modal closes.
        return HTMLResponse(content=modal_oob + btn_oob + toast_oob)

    return HTMLResponse(content=btn_html + modal_oob + toast_oob)


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
    is_private: Optional[str] = Form(None),
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

    if rating is not None:
        rating_str = rating.strip()
        entry.rating = int(rating_str) if rating_str.isdigit() else None

    if notes is not None:
        entry.notes = notes

    entry.is_private = True if is_private else False

    if status_val is not None:
        entry.status = status_val

    await db.commit()
    await db.refresh(entry)

    entry.tmdb_data = await tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type)

    card_html = templates.get_template("partials/watched_card.html").render({"request": request, "entry": entry})
    oob_close_modal = '<div id="modal-container" hx-swap-oob="true"></div>'

    btn_html = templates.get_template("partials/watch_button.html").render({
        "request": request,
        "entry": entry,
        "tmdb_id": entry.tmdb_id,
        "media_type": entry.media_type
    })
    oob_btn_swap = btn_html.replace(f'id="watch-btn-{entry.tmdb_id}"', f'id="watch-btn-{entry.tmdb_id}" hx-swap-oob="true"')
    toast_oob = render_toast("Entry updated!")

    return HTMLResponse(content=card_html + oob_close_modal + oob_btn_swap + toast_oob)


@router.post("/{entry_id}/quick-watched", response_class=HTMLResponse)
async def quick_mark_watched(
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

    entry.status = "watched"
    await db.commit()
    await db.refresh(entry)

    # Same as create_watch_entry: open the rating/notes modal right away
    # instead of leaving the user to go find it. The primary target
    # (#entry-card-{id}) still gets swapped to empty by omission below,
    # which is what already removes the card from this to-watch list.
    entry.tmdb_data = await tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type)
    edit_modal_html = templates.get_template("partials/edit_modal.html").render(
        {"request": request, "entry": entry}
    )
    modal_oob = f'<div id="modal-container" hx-swap-oob="true">{edit_modal_html}</div>'

    toast_oob = render_toast("Marked as watched!")
    return HTMLResponse(content=modal_oob + toast_oob)


@router.delete("/{entry_id}", response_class=HTMLResponse)
async def delete_watch_entry(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": "/login"})

    stmt = select(WatchEntry).where(WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id)
    entry = (await db.execute(stmt)).scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    tmdb_id = entry.tmdb_id
    media_type = entry.media_type

    await db.delete(entry)
    await db.commit()

    card_oob_delete = f'<div id="entry-{entry_id}" hx-swap-oob="delete"></div><div id="entry-card-{entry_id}" hx-swap-oob="delete"></div>'
    modal_oob_close = '<div id="modal-container" hx-swap-oob="true"></div>'
    toast_oob = render_toast("Removed entry", badge_type="remove")

    try:
        watch_btn_content = templates.get_template("partials/watch_button.html").render({
            "request": request,
            "entry": None,
            "tmdb_id": tmdb_id,
            "media_type": media_type,
        })
        watch_btn_oob = watch_btn_content.replace(f'id="watch-btn-{tmdb_id}"', f'id="watch-btn-{tmdb_id}" hx-swap-oob="true"')
    except Exception:
        watch_btn_oob = ""

    return HTMLResponse(content=card_oob_delete + modal_oob_close + watch_btn_oob + toast_oob)
