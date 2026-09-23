from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Friendship, MediaItem, User, WatchEntry
from app.routers.auth import get_current_user_optional as get_current_user
from app.services.tmdb import tmdb_service

router = APIRouter(tags=["Pages"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def home_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    try:
        trending = await tmdb_service.get_trending()
    except Exception:
        trending = []

    stmt_pending_count = select(func.count(Friendship.id)).where(
        Friendship.buddy_id == current_user.id,
        Friendship.status == "pending"
    )
    pending_buddies_count = (await db.execute(stmt_pending_count)).scalar() or 0

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "current_user": current_user,
            "trending": trending,
            "pending_buddies_count": pending_buddies_count,
        },
    )


@router.get("/my-media", response_class=HTMLResponse)
async def my_media_page(
    request: Request,
    status: Optional[str] = "all",
    media_type: Optional[str] = "all",
    year: Optional[str] = "all",
    genre: Optional[str] = "all",
    q: Optional[str] = None,
    sort: Optional[str] = "recent",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    valid_statuses = {"want_to_watch", "in_progress", "watched"}
    selected_status = status if status in valid_statuses or status == "all" else "all"
    selected_media_type = media_type if media_type in {"movie", "tv"} else "all"
    selected_year = year if year and year != "all" and year.isdigit() else "all"
    selected_genre = genre.strip() if genre and genre != "all" else "all"
    search_query = q.strip() if q else ""
    valid_sorts = {"recent", "title", "year_desc", "year_asc", "tmdb_rating"}
    selected_sort = sort if sort in valid_sorts else "recent"

    # Build filter choices from the user's complete My Media collection so
    # filters only offer values that can actually return something.
    all_entries_stmt = (
        select(WatchEntry)
        .options(joinedload(WatchEntry.media_item))
        .where(WatchEntry.user_id == current_user.id)
    )
    all_entries_result = await db.execute(all_entries_stmt)
    all_entries = all_entries_result.unique().scalars().all()

    years = sorted(
        {
            entry.media_item.release_date[:4]
            for entry in all_entries
            if entry.media_item
            and entry.media_item.release_date
            and len(entry.media_item.release_date) >= 4
            and entry.media_item.release_date[:4].isdigit()
        },
        reverse=True,
    )

    genres = set()
    for entry in all_entries:
        if not entry.media_item or not entry.media_item.genres:
            continue
        for raw_genre in entry.media_item.genres.split(","):
            value = raw_genre.strip()
            if value:
                genres.add(value)
    genres = sorted(genres, key=str.casefold)

    stmt = (
        select(WatchEntry)
        .options(joinedload(WatchEntry.media_item))
        .where(WatchEntry.user_id == current_user.id)
    )

    if selected_status != "all":
        stmt = stmt.where(WatchEntry.status == selected_status)

    if selected_media_type != "all":
        stmt = stmt.join(WatchEntry.media_item).where(
            MediaItem.media_type == selected_media_type
        )

    if selected_year != "all":
        if selected_media_type == "all":
            stmt = stmt.join(WatchEntry.media_item)
        stmt = stmt.where(func.substr(MediaItem.release_date, 1, 4) == selected_year)

    if selected_genre != "all":
        if selected_media_type == "all" and selected_year == "all":
            stmt = stmt.join(WatchEntry.media_item)
        genre_lower = selected_genre.casefold()
        genre_column = func.lower(MediaItem.genres)
        stmt = stmt.where(
            or_(
                genre_column == genre_lower,
                genre_column.like(f"{genre_lower}, %"),
                genre_column.like(f"%, {genre_lower}, %"),
                genre_column.like(f"%, {genre_lower}"),
            )
        )

    if search_query:
        if selected_media_type == "all" and selected_year == "all" and selected_genre == "all":
            stmt = stmt.join(WatchEntry.media_item)
        stmt = stmt.where(MediaItem.title.ilike(f"%{search_query}%"))

    if selected_sort == "title":
        stmt = stmt.order_by(func.lower(MediaItem.title).asc(), WatchEntry.updated_at.desc())
    elif selected_sort == "year_desc":
        stmt = stmt.order_by(MediaItem.release_date.desc().nullslast(), WatchEntry.updated_at.desc())
    elif selected_sort == "year_asc":
        stmt = stmt.order_by(MediaItem.release_date.asc().nullsfirst(), WatchEntry.updated_at.desc())
    elif selected_sort == "tmdb_rating":
        stmt = stmt.order_by(MediaItem.vote_average.desc().nullslast(), WatchEntry.updated_at.desc())
    else:
        stmt = stmt.order_by(WatchEntry.updated_at.desc())

    result = await db.execute(stmt)
    entries = result.unique().scalars().all()

    filter_params = {
        key: value
        for key, value in {
            "media_type": selected_media_type,
            "year": selected_year,
            "genre": selected_genre,
            "q": search_query,
            "sort": selected_sort,
        }.items()
        if value and value != "all"
    }
    filter_query = urlencode(filter_params)

    return templates.TemplateResponse(
        request=request,
        name="my_media.html",
        context={
            "request": request,
            "current_user": current_user,
            "entries": entries,
            "current_status": selected_status,
            "current_media_type": selected_media_type,
            "current_year": selected_year,
            "current_genre": selected_genre,
            "search_query": search_query,
            "current_sort": selected_sort,
            "years": years,
            "genres": genres,
            "filter_query": filter_query,
        },
    )


@router.get("/to-watch")
async def redirect_to_watch():
    return RedirectResponse(url="/my-media?status=want_to_watch", status_code=301)


@router.get("/watched")
async def redirect_watched():
    return RedirectResponse(url="/my-media?status=watched", status_code=301)


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    error: Optional[str] = None,
    success: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)

    error_msg = None
    if error == "invalid":
        error_msg = "Invalid username or password."
    elif isinstance(error, str):
        error_msg = error

    success_msg = None
    if success == "registered":
        success_msg = "Account created! Please sign in."

    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": error_msg, "success": success_msg},
    )


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request,
    error: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    if current_user:
        return RedirectResponse(url="/", status_code=303)

    error_msg = None
    if error == "exists":
        error_msg = "Username already exists."
    elif error == "email_exists":
        error_msg = "An account with that email already exists."
    elif isinstance(error, str):
        error_msg = error

    return templates.TemplateResponse(
        request=request,
        name="register.html",
        context={"error": error_msg},
    )
