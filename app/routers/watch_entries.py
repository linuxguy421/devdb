from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import User, WatchEntry
from app.routers.auth import get_current_user_optional as get_current_user
from app.services.media_sync import get_or_sync_media_item
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
    status_val: str = Form("to_watch"),
    from_modal: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": "/login"})

    media_item = await get_or_sync_media_item(db, tmdb_id, media_type)

    stmt = select(WatchEntry).options(selectinload(WatchEntry.media_item)).where(
        WatchEntry.user_id == current_user.id,
        WatchEntry.tmdb_id == tmdb_id,
        WatchEntry.media_type == media_type,
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()

    if not entry:
        entry = WatchEntry(
            user_id=current_user.id,
            tmdb_id=tmdb_id,
            media_type=media_type,
            status=status_val,
            media_item_id=media_item.id if media_item else None,
            poster_path=media_item.poster_path if media_item else None,
        )
        db.add(entry)
    else:
        entry.status = status_val
        if media_item:
            entry.media_item_id = media_item.id
            entry.poster_path = media_item.poster_path

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        stmt = select(WatchEntry).options(selectinload(WatchEntry.media_item)).where(
            WatchEntry.user_id == current_user.id,
            WatchEntry.tmdb_id == tmdb_id,
            WatchEntry.media_type == media_type,
        )
        entry = (await db.execute(stmt)).scalar_one()
        entry.status = status_val
        if media_item:
            entry.media_item_id = media_item.id
            entry.poster_path = media_item.poster_path
        await db.commit()

    await db.refresh(entry)

    entry.tmdb_data = await tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type)

    toast_msg = "Marked as watched!" if status_val == "watched" else "Added to watchlist!"
    toast_oob = render_toast(toast_msg)

    modal_oob = ""
    if status_val == "watched":
        edit_modal_html = templates.get_template("partials/edit_modal.html").render(
            {"request": request, "entry": entry}
        )
        modal_oob = f'<div id="modal-container" hx-swap-oob="true">{edit_modal_html}</div>'
    elif from_modal == "true":
        modal_oob = '<div id="modal-container" hx-swap-oob="true"></div>'

    hx_target = request.headers.get("HX-Target", "")

    if hx_target == f"card-{tmdb_id}":
        title_val = (entry.tmdb_data.get("title") or entry.tmdb_data.get("name")) if entry.tmdb_data else (media_item.title if media_item else "")
        release_raw = (entry.tmdb_data.get("release_date") or entry.tmdb_data.get("first_air_date")) if entry.tmdb_data else (media_item.release_date if media_item else "")
        release_val = str(release_raw) if release_raw else ""
        poster_val = entry.tmdb_data.get("poster_path") if entry.tmdb_data else (entry.poster_path or (media_item.poster_path if media_item else None))
        vote_val = entry.tmdb_data.get("vote_average") if entry.tmdb_data else (media_item.vote_average if media_item else None)

        card_item = {
            "id": tmdb_id,
            "media_type": media_type,
            "title": title_val,
            "poster_path": poster_val,
            "release_date": release_val,
            "vote_average": vote_val,
            "user_entry": entry,
            "user_status": entry.status,
        }
        card_html = templates.get_template("partials/title_cards.html").render(
            {"request": request, "results": [card_item]}
        )
        return HTMLResponse(content=card_html + modal_oob + toast_oob)

    btn_html = templates.get_template("partials/watch_button.html").render(
        {"request": request, "entry": entry, "tmdb_id": tmdb_id, "media_type": media_type}
    )
    if from_modal == "true" or status_val == "watched":
        btn_oob = btn_html.replace(f'id="watch-btn-{tmdb_id}"', f'id="watch-btn-{tmdb_id}" hx-swap-oob="true"')
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

    stmt = select(WatchEntry).options(selectinload(WatchEntry.media_item)).where(
        WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    if not entry.media_item_id:
        media_item = await get_or_sync_media_item(db, entry.tmdb_id, entry.media_type)
        if media_item:
            entry.media_item_id = media_item.id
            await db.commit()

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

    stmt = select(WatchEntry).options(selectinload(WatchEntry.media_item)).where(
        WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    if not entry.media_item_id:
        media_item = await get_or_sync_media_item(db, entry.tmdb_id, entry.media_type)
        if media_item:
            entry.media_item_id = media_item.id

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

    stmt = select(WatchEntry).options(selectinload(WatchEntry.media_item)).where(
        WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    if not entry.media_item_id:
        media_item = await get_or_sync_media_item(db, entry.tmdb_id, entry.media_type)
        if media_item:
            entry.media_item_id = media_item.id

    entry.status = "watched"
    await db.commit()
    await db.refresh(entry)

    entry.tmdb_data = await tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type)
    edit_modal_html = templates.get_template("partials/edit_modal.html").render(
        {"request": request, "entry": entry}
    )
    modal_oob = f'<div id="modal-container" hx-swap-oob="true">{edit_modal_html}</div>'
    toast_oob = render_toast("Marked as watched!")

    hx_target = request.headers.get("HX-Target", "")

    if hx_target in (f"entry-card-{entry_id}", f"entry-{entry_id}"):
        return HTMLResponse(content=modal_oob + toast_oob)
    else:
        card_oob_delete = f'<div id="entry-card-{entry_id}" hx-swap-oob="delete"></div>'
        return HTMLResponse(content=card_oob_delete + modal_oob + toast_oob)


@router.delete("/{entry_id}", response_class=HTMLResponse)
async def delete_watch_entry(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(status_code=status.HTTP_401_UNAUTHORIZED, headers={"HX-Redirect": "/login"})

    stmt = select(WatchEntry).options(selectinload(WatchEntry.media_item)).where(
        WatchEntry.id == entry_id, WatchEntry.user_id == current_user.id
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()

    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    tmdb_id = entry.tmdb_id
    media_type = entry.media_type

    await db.delete(entry)
    await db.commit()

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

    hx_target = request.headers.get("HX-Target", "")

    if hx_target in (f"entry-card-{entry_id}", f"entry-{entry_id}"):
        return HTMLResponse(content=modal_oob_close + watch_btn_oob + toast_oob)
    else:
        card_oob_delete = f'<div id="entry-card-{entry_id}" hx-swap-oob="delete"></div>'
        return HTMLResponse(content=card_oob_delete + modal_oob_close + watch_btn_oob + toast_oob)
