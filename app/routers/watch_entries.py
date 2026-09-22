from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models import MediaItem, User, WatchEntry
from app.routers.auth import get_current_user_optional as get_current_user
from app.services.media_sync import get_or_sync_media_item
from app.services.progress import (
    ProgressDomainError,
    complete,
    mark_next_episode_watched,
    reset_progress,
    set_status,
    start_watching,
)
from app.services.tmdb import tmdb_service
from app.services.tv_seasons import get_season_episode_counts


router = APIRouter(prefix="/watch-entries", tags=["Watch Entries"])
templates = Jinja2Templates(directory="app/templates")

VALID_STATUSES = {
    "want_to_watch",
    "in_progress",
    "watched",
}


def parse_optional_int(
    value: Optional[str],
    field_name: str,
) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None

    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be a whole number.",
        )


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
    ).render({"entry": entry})


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
        content=render_card(entry) + render_toast(toast_msg, badge_type)
    )


async def render_info_modal(
    request: Request,
    entry: WatchEntry,
    current_user: User,
    tmdb_data: Optional[dict] = None,
    error_message: Optional[str] = None,
    db: Optional[AsyncSession] = None,
) -> str:
    if tmdb_data is None:
        try:
            tmdb_data = await tmdb_service.get_formatted_details(
                entry.media_item.tmdb_id,
                entry.media_item.media_type,
            )
        except Exception:
            tmdb_data = {}

    season_episode_counts = {}
    if entry.media_item and entry.media_item.media_type == "tv":
        try:
            if db is not None:
                season_episode_counts = await get_season_episode_counts(
                    db,
                    entry.media_item,
                )
        except Exception:
            # The persisted season data remains authoritative for validation.
            # If it cannot be read here, leave the detail display empty rather
            # than making the modal itself fail.
            season_episode_counts = {}

    return templates.get_template(
        "partials/info_modal.html"
    ).render(
        {
            "request": request,
            "tmdb_data": tmdb_data or {},
            "tmdb_id": entry.media_item.tmdb_id,
            "media_type": entry.media_item.media_type,
            "existing_entry": entry,
            "current_user": current_user,
            "season_episode_counts": season_episode_counts,
            "error_message": error_message,
        }
    )


@router.get("/{entry_id}/edit-modal", response_class=HTMLResponse)
async def get_edit_modal(
    request: Request,
    entry_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    """
    Compatibility route for browse/search controls.

    The application now uses the same editable info modal everywhere;
    this route remains so older HTMX controls do not break.
    """
    if not current_user:
        return HTMLResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": "/login"},
        )

    entry = await get_entry(db, entry_id, current_user.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    return HTMLResponse(
        await render_info_modal(request, entry, current_user, db=db)
    )


@router.post("", response_class=HTMLResponse)
@router.post("/add", response_class=HTMLResponse)
async def create_watch_entry(
    request: Request,
    tmdb_id: int = Form(...),
    media_type: str = Form(...),
    status_val: str = Form("want_to_watch"),
    rating: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    season: Optional[str] = Form(None),
    episode: Optional[str] = Form(None),
    is_private: Optional[str] = Form(None),
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
    elif status_val in ("currently_watching", "watching"):
        status_val = "in_progress"

    if status_val not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid watch status")

    media_item = await get_or_sync_media_item(db, tmdb_id, media_type)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    stmt = (
        select(WatchEntry)
        .options(joinedload(WatchEntry.media_item))
        .where(
            WatchEntry.user_id == current_user.id,
            WatchEntry.media_item_id == media_item.id,
        )
    )
    entry = (await db.execute(stmt)).scalar_one_or_none()

    if entry is None:
        entry = WatchEntry(
            user_id=current_user.id,
            media_item_id=media_item.id,
            status="want_to_watch",
        )
        db.add(entry)
        await db.flush()

    old_status = entry.status
    if old_status != status_val:
        set_status(entry, status_val)

    if rating is not None:
        rating_num = parse_optional_int(rating, "Rating")
        if rating_num is not None and not 1 <= rating_num <= 10:
            raise HTTPException(status_code=400, detail="Rating must be between 1 and 10")
        entry.rating = rating_num

    if notes is not None:
        entry.notes = notes.strip() or None

    if is_private is not None:
        entry.is_private = str(is_private).lower() in (
            "true", "1", "on", "yes"
        )

    if media_item.media_type == "tv":
        season_num = parse_optional_int(season, "Season")
        episode_num = parse_optional_int(episode, "Episode")

        if (season_num is None) != (episode_num is None):
            raise HTTPException(
                status_code=400,
                detail="Season and episode must be provided together.",
            )

        if season_num is not None:
            if season_num < 1 or episode_num < 1:
                raise HTTPException(
                    status_code=400,
                    detail="Season and episode must be at least 1.",
                )

            counts = await get_season_episode_counts(db, media_item)
            max_episode = counts.get(season_num)
            if max_episode is None:
                raise HTTPException(
                    status_code=400,
                    detail="That season is not available.",
                )
            if episode_num > max_episode:
                raise HTTPException(
                    status_code=400,
                    detail=f"Season {season_num} has only {max_episode} episodes.",
                )

            entry.last_watched_season = season_num
            entry.last_watched_episode = episode_num

    if status_val == "want_to_watch":
        entry.last_watched_season = None
        entry.last_watched_episode = None
        entry.completed_at = None
    elif status_val == "watched" and old_status != "watched":
        entry.completed_at = datetime.now(timezone.utc)
    elif status_val == "in_progress":
        entry.completed_at = None

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This media entry already exists.",
        )

    await db.refresh(entry)

    if from_modal:
        modal_html = await render_info_modal(
            request,
            entry,
            current_user,
        )
        return HTMLResponse(
            content=(
                modal_html
                + render_card_oob(entry)
                + render_toast(
                    "Saved to My Media."
                    if old_status != status_val
                    else "Updated My Media entry."
                )
            )
        )

    return HTMLResponse(
        content=(
            render_watch_button(request, entry)
            + render_card_oob(entry)
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
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": "/login"},
        )

    entry = await get_entry(db, entry_id, current_user.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    old_status = entry.status

    try:
        if status_val is not None:
            if status_val not in VALID_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid watch status")
            if status_val != old_status:
                set_status(entry, status_val)

        rating_num = parse_optional_int(rating, "Rating")
        if rating_num is not None and not 1 <= rating_num <= 10:
            raise HTTPException(
                status_code=400,
                detail="Rating must be between 1 and 10",
            )
        if rating is not None:
            entry.rating = rating_num

        if notes is not None:
            entry.notes = notes.strip() or None

        if is_private is not None:
            entry.is_private = str(is_private).lower() in (
                "true", "1", "on", "yes"
            )

        is_tv = (
            entry.media_item is not None
            and entry.media_item.media_type == "tv"
        )

        if is_tv:
            season_num = parse_optional_int(season, "Season")
            episode_num = parse_optional_int(episode, "Episode")

            if (season_num is None) != (episode_num is None):
                raise HTTPException(
                    status_code=400,
                    detail="Season and episode must be provided together.",
                )

            if season_num is not None:
                if season_num < 1 or episode_num < 1:
                    raise HTTPException(
                        status_code=400,
                        detail="Season and episode must be at least 1.",
                    )

                counts = await get_season_episode_counts(
                    db,
                    entry.media_item,
                )
                max_episode = counts.get(season_num)

                if max_episode is None:
                    available = (
                        ", ".join(
                            f"S{season}: {count} episodes"
                            for season, count in sorted(counts.items())
                        )
                        if counts
                        else "no season information is available"
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Season {season_num} is not available for this series "
                            f"({available})."
                        ),
                    )

                # This is the authoritative server-side boundary. A user can
                # never save S1E10 when persisted season data says S1 has 9.
                if episode_num > max_episode:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Season {season_num} has only {max_episode} "
                            f"episodes. Episode {episode_num} cannot be saved."
                        ),
                    )

                entry.last_watched_season = season_num
                entry.last_watched_episode = episode_num

        if entry.status == "want_to_watch":
            entry.last_watched_season = None
            entry.last_watched_episode = None
            entry.completed_at = None
        elif entry.status == "in_progress":
            entry.completed_at = None
        elif entry.status == "watched":
            if old_status != "watched":
                entry.completed_at = datetime.now(timezone.utc)

        await db.commit()
        await db.refresh(entry)

    except HTTPException as exc:
        if exc.status_code != 400:
            raise

        # Do not leave a partially edited ORM object in the session after a
        # rejected save. Re-render the same edit surface with a useful error
        # instead of returning a bare 400 page.
        await db.rollback()
        entry = await get_entry(db, entry_id, current_user.id)
        if not entry:
            raise HTTPException(status_code=404, detail="Watch entry not found")

        return HTMLResponse(
            content=await render_info_modal(
                request,
                entry,
                current_user,
                db=db,
                error_message=str(exc.detail),
            )
        )

    # Successful edit: the form targets #info-modal with hx-swap="outerHTML".
    # We intentionally return only OOB card/toast updates, so the modal target
    # disappears and Edit closes automatically.
    return HTMLResponse(
        content=(
            render_card_oob(entry)
            + render_toast("Saved changes.")
        )
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
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": "/login"},
        )

    entry = await get_entry(db, entry_id, current_user.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

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
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": "/login"},
        )

    entry = await get_entry(db, entry_id, current_user.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    if not entry.media_item:
        raise HTTPException(status_code=400, detail="Watch entry has no media item")

    if entry.media_item.media_type != "tv":
        raise HTTPException(
            status_code=400,
            detail="Episode progress is only available for TV shows",
        )

    season_episode_counts = await get_season_episode_counts(
        db,
        entry.media_item,
    )

    if not season_episode_counts:
        return HTMLResponse(
            content=render_toast(
                "Unable to load season information for this show.",
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
        await db.rollback()
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

    return render_entry_response(request, entry, message)


@router.post("/{entry_id}/complete", response_class=HTMLResponse)
async def action_complete_media(
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
        raise HTTPException(status_code=404, detail="Watch entry not found")

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
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": "/login"},
        )

    entry = await get_entry(db, entry_id, current_user.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

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
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"HX-Redirect": "/login"},
        )

    entry = await get_entry(db, entry_id, current_user.id)
    if not entry:
        raise HTTPException(status_code=404, detail="Watch entry not found")

    await db.delete(entry)
    await db.commit()

    return HTMLResponse(
        content=(
            f'<div id="entry-card-{entry_id}" hx-swap-oob="delete"></div>'
            + render_toast("Removed entry", badge_type="remove")
        )
    )
