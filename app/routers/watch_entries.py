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
    ProgressDomainError,
    complete,
    mark_next_episode_watched,
    reset_progress,
    start_watching,
)
from app.services.tmdb import tmdb_service


router = APIRouter(prefix="/watch-entries", tags=["Watch Entries"])
templates = Jinja2Templates(directory="app/templates")


VALID_STATUSES = {
    "want_to_watch",
    "in_progress",
    "watched",
}


def safe_int(val: Optional[str]) -> Optional[int]:
    if val is None or str(val).strip() == "":
        return None

    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def render_toast(message: str, badge_type: str = "success") -> str:
    border_color = (
        "border-emerald-500/40 text-emerald-400"
        if badge_type == "success"
        else "border-rose-500/40 text-rose-400"
    )

    dot_color = (
        "bg-emerald-400"
        if badge_type == "success"
        else "bg-rose-400"
    )

    return f"""
    <div id="toast-container" hx-swap-oob="afterbegin">
        <div class="animate-toast flex items-center gap-2 bg-neutral-900 border {border_color} px-3.5 py-2.5 rounded-xl shadow-2xl text-xs font-semibold backdrop-blur-md pointer-events-auto">
            <span class="w-2 h-2 rounded-full {dot_color}"></span>
            <span>{message}</span>
        </div>
    </div>
    """


async def get_entry(
    db: AsyncSession,
    entry_id: int,
    user_id: int,
) -> Optional[WatchEntry]:
    stmt = (
        select(WatchEntry)
        .options(joinedload(WatchEntry.media_item))
        .where(
            WatchEntry.id == entry_id,
            WatchEntry.user_id == user_id,
        )
    )

    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def render_card(entry: WatchEntry) -> str:
    return templates.get_template(
        "partials/my_media_card.html"
    ).render(
        {
            "entry": entry,
        }
    )


def render_watch_button(
    request: Request,
    entry: WatchEntry,
) -> str:
    return templates.get_template(
        "partials/watch_button.html"
    ).render(
        {
            "request": request,
            "entry": entry,
            "tmdb_id": (
                entry.media_item.tmdb_id
                if entry.media_item
                else None
            ),
            "media_type": (
                entry.media_item.media_type
                if entry.media_item
                else "movie"
            ),
        }
    )


def render_card_oob(entry: WatchEntry) -> str:
    card_html = render_card(entry)

    marker = f'id="entry-card-{entry.id}"'

    if marker in card_html:
        return card_html.replace(
            marker,
            f'{marker} hx-swap-oob="outerHTML"',
            1,
        )

    return (
        f'<div id="entry-card-{entry.id}" '
        f'hx-swap-oob="outerHTML">'
        f'{card_html}'
        f'</div>'
    )


def render_entry_response(
    request: Request,
    entry: WatchEntry,
    toast_msg: str,
    badge_type: str = "success",
) -> HTMLResponse:
    hx_target = request.headers.get("HX-Target", "")

    if hx_target.startswith("watch-button"):
        return HTMLResponse(
            content=(
                render_watch_button(request, entry)
                + render_card_oob(entry)
                + render_toast(toast_msg, badge_type)
            )
        )

    return HTMLResponse(
        content=(
            render_card(entry)
            + render_toast(toast_msg, badge_type)
        )
    )


@router.get("/{entry_id}/edit-modal", response_class=HTMLResponse)
async def get_edit_modal(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": "/login"},
        )

    entry = await get_entry(db, entry_id, current_user.id)
    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Watch entry not found",
        )

    return templates.TemplateResponse(
        request=request,
        name="partials/edit_modal.html",
        context={
            "request": request,
            "entry": entry,
            "current_user": current_user,
        },
    )


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
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": "/login"},
        )

    if status_val in ("to_watch", "plan_to_watch"):
        status_val = "want_to_watch"
    elif status_val == "currently_watching":
        status_val = "in_progress"

    if status_val not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Invalid watch status",
        )

    media_item = await get_or_sync_media_item(
        db,
        tmdb_id,
        media_type,
    )

    if not media_item:
        raise HTTPException(
            status_code=404,
            detail="Media item not found",
        )

    stmt = (
        select(WatchEntry)
        .options(joinedload(WatchEntry.media_item))
        .where(
            WatchEntry.user_id == current_user.id,
            WatchEntry.media_item_id == media_item.id,
        )
    )

    entry = (
        await db.execute(stmt)
    ).scalar_one_or_none()

    if not entry:
        entry = WatchEntry(
            user_id=current_user.id,
            media_item_id=media_item.id,
            status=status_val,
        )
        db.add(entry)
    else:
        entry.status = status_val

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()

        entry = (
            await db.execute(stmt)
        ).scalar_one()

        entry.status = status_val

        await db.commit()

    await db.refresh(entry)

    return HTMLResponse(
        content=(
            render_watch_button(request, entry)
            + render_toast(
                "Marked as watched!"
                if status_val == "watched"
                else "Added to My Media!"
            )
        )
    )


@router.post("/{entry_id}/update", response_class=HTMLResponse)
async def update_watch_entry(
    request: Request,
    entry_id: int,
    status_val: Optional[str] = Form(None),
    season: Optional[str] = Form(None),
    episode: Optional[str] = Form(None),
    rating: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    is_private: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    entry = await get_entry(
        db,
        entry_id,
        current_user.id,
    )

    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Watch entry not found",
        )

    if status_val is not None:
        if status_val not in VALID_STATUSES:
            raise HTTPException(
                status_code=400,
                detail="Invalid watch status",
            )

        entry.status = status_val

    if rating is not None:
        rating_num = safe_int(rating)

        if rating_num is not None and not 1 <= rating_num <= 10:
            raise HTTPException(
                status_code=400,
                detail="Rating must be between 1 and 10",
            )

        entry.rating = rating_num

    if notes is not None:
        cleaned_notes = notes.strip()
        entry.notes = cleaned_notes or None

    if is_private is not None:
        entry.is_private = (
            str(is_private).lower()
            in ("true", "1", "on", "yes")
        )

    is_tv = (
        entry.media_item is not None
        and entry.media_item.media_type == "tv"
    )

    if is_tv:
        season_num = safe_int(season)
        episode_num = safe_int(episode)

        if season_num is not None:
            if season_num < 1:
                raise HTTPException(
                    status_code=400,
                    detail="Season must be at least 1",
                )

            entry.last_watched_season = season_num

        if episode_num is not None:
            if episode_num < 0:
                raise HTTPException(
                    status_code=400,
                    detail="Episode must be at least 0",
                )

            entry.last_watched_episode = episode_num

        if (
            (
                season_num is not None
                or episode_num is not None
            )
            and entry.status == "want_to_watch"
        ):
            entry.status = "in_progress"

    await db.commit()
    await db.refresh(entry)

    try:
        tmdb_data = await tmdb_service.get_formatted_details(
            entry.media_item.tmdb_id,
            entry.media_item.media_type,
        )
    except Exception:
        tmdb_data = {}

    modal_html = templates.get_template(
        "partials/info_modal.html"
    ).render(
        {
            "request": request,
            "tmdb_data": tmdb_data,
            "tmdb_id": entry.media_item.tmdb_id,
            "media_type": entry.media_item.media_type,
            "existing_entry": entry,
            "current_user": current_user,
        }
    )

    card_oob = render_card_oob(entry)

    return HTMLResponse(
        content=modal_html + card_oob
    )


@router.post("/{entry_id}/start", response_class=HTMLResponse)
async def action_start_watching(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    entry = await get_entry(
        db,
        entry_id,
        current_user.id,
    )

    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Watch entry not found",
        )

    start_watching(entry)

    await db.commit()
    await db.refresh(entry)

    return render_entry_response(
        request,
        entry,
        "Moved to In Progress",
    )


@router.post("/{entry_id}/progress", response_class=HTMLResponse)
async def action_increment_progress(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    entry = await get_entry(
        db,
        entry_id,
        current_user.id,
    )

    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Watch entry not found",
        )

    if not entry.media_item:
        raise HTTPException(
            status_code=400,
            detail="Watch entry has no media item",
        )

    if entry.media_item.media_type != "tv":
        raise HTTPException(
            status_code=400,
            detail="Episode progress is only available for TV shows",
        )

    total_seasons = entry.media_item.total_seasons or 0

    if total_seasons <= 0:
        try:
            details = await tmdb_service.get_formatted_details(
                entry.media_item.tmdb_id,
                "tv",
            )
            total_seasons = int(details.get("number_of_seasons") or 0)
        except Exception:
            total_seasons = 0

    season_episode_counts = {}

    for season_number in range(1, total_seasons + 1):
        try:
            season_data = await tmdb_service.get_tv_season(
                entry.media_item.tmdb_id,
                season_number,
            )
        except Exception:
            season_data = None

        if not season_data:
            continue

        episodes = season_data.get("episodes") or []

        episode_numbers = [
            episode.get("episode_number")
            for episode in episodes
            if episode.get("episode_number") is not None
        ]

        if episode_numbers:
            season_episode_counts[season_number] = max(episode_numbers)

    if not season_episode_counts and entry.media_item.total_seasons and entry.media_item.total_episodes:
        eps_per_season = max(1, entry.media_item.total_episodes // entry.media_item.total_seasons)
        season_episode_counts = {s: eps_per_season for s in range(1, entry.media_item.total_seasons + 1)}

    if not season_episode_counts:
        return HTMLResponse(
            content=render_toast(
                "Unable to load episode information from TMDB.",
                badge_type="remove",
            ),
            status_code=502,
        )

    try:
        mark_next_episode_watched(
            entry,
            entry.media_item,
            season_episode_counts,
        )

        await db.commit()
        await db.refresh(entry)

    except ProgressDomainError as err:
        return HTMLResponse(
            content=render_toast(
                str(err),
                badge_type="remove",
            ),
            status_code=400,
        )

    if entry.status == "watched":
        message = "Completed series!"
    else:
        message = (
            f"Updated to "
            f"S{entry.last_watched_season:02d}"
            f"E{entry.last_watched_episode:02d}"
        )

    return render_entry_response(
        request,
        entry,
        message,
    )


@router.post("/{entry_id}/complete", response_class=HTMLResponse)
async def action_complete_media(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    entry = await get_entry(
        db,
        entry_id,
        current_user.id,
    )

    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Watch entry not found",
        )

    complete(entry)

    await db.commit()
    await db.refresh(entry)

    return render_entry_response(
        request,
        entry,
        "Marked as Watched!",
    )


@router.post("/{entry_id}/reset", response_class=HTMLResponse)
async def action_reset_media(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    entry = await get_entry(
        db,
        entry_id,
        current_user.id,
    )

    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Watch entry not found",
        )

    reset_progress(entry)

    await db.commit()
    await db.refresh(entry)

    return render_entry_response(
        request,
        entry,
        "Reset back to Want to Watch",
    )


@router.delete("/{entry_id}", response_class=HTMLResponse)
async def delete_watch_entry(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED
        )

    entry = await get_entry(
        db,
        entry_id,
        current_user.id,
    )

    if not entry:
        raise HTTPException(
            status_code=404,
            detail="Watch entry not found",
        )

    await db.delete(entry)
    await db.commit()

    card_oob_delete = (
        f'<div id="entry-card-{entry_id}" '
        f'hx-swap-oob="delete"></div>'
    )

    return HTMLResponse(
        content=(
            card_oob_delete
            + render_toast(
                "Removed entry",
                badge_type="remove",
            )
        )
    )
