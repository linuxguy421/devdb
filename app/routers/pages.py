from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Friendship, MediaItem, User, WatchEntry, TVSeason
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


def _fmt_duration(minutes: int) -> str:
    if minutes <= 0:
        return "0h"
    hours = minutes // 60
    days = hours // 24
    rem_h = hours % 24
    if days > 0:
        return f"{days}d {rem_h}h"
    if hours > 0:
        rem_m = minutes % 60
        return f"{hours}h {rem_m}m" if rem_m else f"{hours}h"
    return f"{minutes}m"


async def _compute_stats(
    db: AsyncSession,
    user_id: int,
    time_range: str = "all",
    media_filter: str = "all",
) -> Dict[str, Any]:
    """Aggregate watch stats for the current user."""
    stmt = (
        select(WatchEntry)
        .options(
            joinedload(WatchEntry.media_item).joinedload(MediaItem.tv_seasons),
        )
        .where(WatchEntry.user_id == user_id)
    )
    result = await db.execute(stmt)
    entries = list(result.unique().scalars().all())

    if media_filter == "movie":
        entries = [e for e in entries if e.media_item and e.media_item.media_type == "movie"]
    elif media_filter == "tv":
        entries = [e for e in entries if e.media_item and e.media_item.media_type == "tv"]

    now = datetime.now(timezone.utc)
    if time_range in {"year", "month"}:
        if time_range == "year":
            cutoff = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            cutoff = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def _in_range(e: WatchEntry) -> bool:
            ts = e.completed_at or e.updated_at
            return bool(ts and ts >= cutoff)

        entries = [e for e in entries if _in_range(e)]

    total_tracked = len(entries)
    watched = [e for e in entries if e.status == "watched"]
    in_progress = [e for e in entries if e.status == "in_progress"]
    want = [e for e in entries if e.status == "want_to_watch"]

    completion_rate = (len(watched) / total_tracked * 100) if total_tracked else 0.0

    ratings = [e.rating for e in entries if e.rating is not None]
    avg_rating = (sum(ratings) / len(ratings)) if ratings else None

    total_minutes = 0
    for e in watched + in_progress:
        mi = e.media_item
        if not mi or not mi.runtime:
            continue
        if mi.media_type == "movie":
            total_minutes += mi.runtime
        else:
            ep_runtime = mi.runtime or 0
            if e.status == "watched":
                eps = mi.total_episodes
                if not eps and mi.tv_seasons:
                    eps = sum(s.episode_count for s in mi.tv_seasons if s.season_number > 0)
                if eps:
                    total_minutes += ep_runtime * eps
            elif e.status == "in_progress":
                counted = 0
                if (
                    e.last_watched_season is not None
                    and e.last_watched_episode is not None
                    and mi.tv_seasons
                ):
                    seasons = {
                        s.season_number: s.episode_count
                        for s in mi.tv_seasons
                        if s.season_number > 0
                    }
                    for sn in sorted(seasons):
                        if sn < e.last_watched_season:
                            counted += seasons[sn]
                        elif sn == e.last_watched_season:
                            counted += min(e.last_watched_episode, seasons[sn])
                            break
                elif e.last_watched_season is not None and e.last_watched_episode is not None:
                    counted = max(
                        0,
                        (e.last_watched_season - 1) * 10 + e.last_watched_episode,
                    )
                total_minutes += ep_runtime * counted

    year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    monthly: Counter = Counter()
    for e in watched:
        if e.completed_at and e.completed_at >= year_start:
            monthly[e.completed_at.month] += 1
    completed_by_month = [monthly.get(m, 0) for m in range(1, 13)]
    max_month = max(completed_by_month) if any(completed_by_month) else 1

    movie_count = sum(
        1 for e in watched if e.media_item and e.media_item.media_type == "movie"
    )
    tv_count = sum(
        1 for e in watched if e.media_item and e.media_item.media_type == "tv"
    )
    completed_total = movie_count + tv_count
    movie_pct = (movie_count / completed_total * 100) if completed_total else 0.0
    tv_pct = (tv_count / completed_total * 100) if completed_total else 0.0

    genre_counter: Counter = Counter()
    for e in watched:
        if e.media_item and e.media_item.genres:
            for g in e.media_item.genres.split(","):
                g = g.strip()
                if g:
                    genre_counter[g] += 1
    top_genres_raw = genre_counter.most_common(12)
    genre_total = sum(c for _, c in top_genres_raw) or 1
    top_genres = [
        (g, c, round(c / genre_total * 100, 1)) for g, c in top_genres_raw
    ]

    genre_ratings: Dict[str, List[int]] = defaultdict(list)
    for e in entries:
        if e.rating is None or not e.media_item or not e.media_item.genres:
            continue
        for g in e.media_item.genres.split(","):
            g = g.strip()
            if g:
                genre_ratings[g].append(e.rating)
    highest_rated = []
    for g, rs in genre_ratings.items():
        if rs:
            highest_rated.append((g, sum(rs) / len(rs), len(rs)))
    highest_rated.sort(key=lambda x: (-x[1], -x[2]))
    highest_rated = [
        (g, round(avg, 1), n) for g, avg, n in highest_rated[:8]
    ]

    decade_counter: Counter = Counter()
    for e in watched:
        rd = e.media_item.release_date if e.media_item else None
        if rd and len(rd) >= 4 and rd[:4].isdigit():
            year = int(rd[:4])
            decade_counter[(year // 10) * 10] += 1
    decades = sorted(decade_counter.items())
    max_decade = max((c for _, c in decades), default=1)

    tv_entries = [
        e for e in entries if e.media_item and e.media_item.media_type == "tv"
    ]
    tv_tracked = len(tv_entries)
    tv_completed = sum(1 for e in tv_entries if e.status == "watched")
    tv_in_progress = sum(1 for e in tv_entries if e.status == "in_progress")

    first_completed = None
    latest_completed = None
    highest_rated_entry = None
    most_recent_addition = None

    completed_sorted = sorted(
        [e for e in watched if e.completed_at],
        key=lambda e: e.completed_at,
    )
    if completed_sorted:
        first_completed = completed_sorted[0]
        latest_completed = completed_sorted[-1]

    rated = [e for e in entries if e.rating is not None]
    if rated:
        highest_rated_entry = max(
            rated,
            key=lambda e: (
                e.rating or 0,
                e.updated_at or datetime.min.replace(tzinfo=timezone.utc),
            ),
        )

    if entries:
        most_recent_addition = max(
            entries,
            key=lambda e: e.created_at
            or datetime.min.replace(tzinfo=timezone.utc),
        )

    return {
        "total_tracked": total_tracked,
        "watched_count": len(watched),
        "in_progress_count": len(in_progress),
        "want_count": len(want),
        "completion_rate": round(completion_rate, 1),
        "avg_rating": round(avg_rating, 1) if avg_rating is not None else None,
        "total_minutes": total_minutes,
        "duration_label": _fmt_duration(total_minutes),
        "completed_by_month": completed_by_month,
        "max_month": max(max_month, 1),
        "month_labels": [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ],
        "movie_count": movie_count,
        "tv_count": tv_count,
        "movie_pct": round(movie_pct, 1),
        "tv_pct": round(tv_pct, 1),
        "top_genres": top_genres,
        "highest_rated_genres": highest_rated,
        "decades": decades,
        "max_decade": max_decade,
        "tv_tracked": tv_tracked,
        "tv_completed": tv_completed,
        "tv_in_progress": tv_in_progress,
        "first_completed": first_completed,
        "latest_completed": latest_completed,
        "highest_rated_entry": highest_rated_entry,
        "most_recent_addition": most_recent_addition,
        "year_completed_total": sum(completed_by_month),
    }


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    time_range: Optional[str] = Query("all", alias="range"),
    media_type: Optional[str] = Query("all"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    selected_range = time_range if time_range in {"all", "year", "month"} else "all"
    selected_media = media_type if media_type in {"all", "movie", "tv"} else "all"

    stats = await _compute_stats(
        db,
        current_user.id,
        time_range=selected_range,
        media_filter=selected_media,
    )

    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context={
            "current_user": current_user,
            "stats": stats,
            "selected_range": selected_range,
            "selected_media": selected_media,
        },
    )
