from typing import Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, WatchEntry
from app.routers.auth import get_current_user
from app.services.tmdb import tmdb_service

router = APIRouter(prefix="/titles", tags=["Titles"])
templates = Jinja2Templates(directory="app/templates")

GENRE_MAP = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie",
    53: "Thriller", 10752: "War", 37: "Western",
    10759: "Action & Adventure", 10762: "Kids", 10765: "Sci-Fi & Fantasy"
}

DECADE_MAP = {
    "decade_2020s": "2020s",
    "decade_2010s": "2010s",
    "decade_2000s": "2000s",
    "decade_1990s": "1990s",
    "decade_1980s": "1980s",
    "decade_1970s": "1970s",
    "decade_1960s": "1960s",
    "decade_1950s": "1950s",
}

SORT_MAP = {
    "popularity.desc": "Popular",
    "vote_average.desc": "Top Rated",
    "primary_release_date.desc": "Newest Releases",
    "primary_release_date.asc": "Oldest Releases",
    "first_air_date.desc": "Newest Releases",
    "first_air_date.asc": "Oldest Releases",
}


def construct_browse_label(media_type: str, sort_by: str, genre_id: Optional[int], year_filter: Optional[str]) -> str:
    type_str = "TV Series" if media_type == "tv" else ("Movies" if media_type == "movie" else "Titles")
    sort_str = SORT_MAP.get(sort_by, "Popular")
    genre_str = GENRE_MAP.get(genre_id, "") if genre_id else ""

    year_str = ""
    if year_filter:
        if year_filter in DECADE_MAP:
            year_str = f"({DECADE_MAP[year_filter]})"
        elif year_filter.isdigit():
            year_str = f"({year_filter})"

    parts = [p for p in [sort_str, genre_str, type_str, year_str] if p]
    return f"Browsing: {' '.join(parts)}"


@router.get("/browse-partial", response_class=HTMLResponse)
async def browse_titles_partial(
    request: Request,
    media_type: Optional[str] = "movie",
    sort_by: Optional[str] = "popularity.desc",
    genre_id: Optional[str] = None,
    year_filter: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    target_media = media_type if media_type in ("movie", "tv") else "movie"
    sort_key = sort_by if sort_by else "popularity.desc"
    parsed_genre_id = int(genre_id) if genre_id and genre_id.isdigit() else None
    year_val = year_filter if year_filter else None

    if target_media == "tv":
        if "primary_release_date" in sort_key:
            sort_key = sort_key.replace("primary_release_date", "first_air_date")
    else:
        if "first_air_date" in sort_key:
            sort_key = sort_key.replace("first_air_date", "primary_release_date")

    data = await tmdb_service.discover_titles(
        media_type=target_media,
        sort_by=sort_key,
        genre_id=parsed_genre_id,
        year_filter=year_val,
    )
    results = data.get("results", [])

    tmdb_ids = [r["id"] for r in results if "id" in r]
    existing_entries = {}

    if tmdb_ids and current_user:
        stmt = select(WatchEntry).where(
            WatchEntry.user_id == current_user.id,
            WatchEntry.tmdb_id.in_(tmdb_ids),
        )
        db_res = await db.execute(stmt)
        entries = db_res.scalars().all()
        existing_entries = {entry.tmdb_id: entry for entry in entries}

    active_label = construct_browse_label(target_media, sort_key, parsed_genre_id, year_val)

    return templates.TemplateResponse(
        request=request,
        name="partials/search_results.html",
        context={
            "results": results,
            "existing_entries": existing_entries,
            "active_label": active_label,
        },
    )


@router.get("/search-partial", response_class=HTMLResponse)
async def search_titles_partial(
    request: Request,
    q: str = "",
    media_type: Optional[str] = None,
    genre_id: Optional[str] = None,
    year_filter: Optional[str] = None,
    sort_by: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    query_str = q.strip()
    parsed_genre_id = int(genre_id) if genre_id and genre_id.isdigit() else None
    year_val = year_filter if year_filter else None
    sort_key = sort_by if sort_by else "popularity.desc"
    media_val = media_type if media_type in ("movie", "tv") else None

    if not query_str:
        return await browse_titles_partial(
            request=request,
            media_type=media_val or "movie",
            sort_by=sort_key,
            genre_id=genre_id,
            year_filter=year_val,
            db=db,
            current_user=current_user,
        )

    data = await tmdb_service.search_multi(query=query_str)
    results = data.get("results", [])
    media_results = [r for r in results if r.get("media_type") in ("movie", "tv")]

    # Filter by media_type (movie/tv)
    if media_val:
        media_results = [r for r in media_results if r.get("media_type") == media_val]

    # Filter by genre_id
    if parsed_genre_id:
        media_results = [r for r in media_results if parsed_genre_id in r.get("genre_ids", [])]

    # Filter by release year or decade
    if year_val:
        def matches_year(item):
            date_str = item.get("release_date") or item.get("first_air_date") or ""
            if not date_str or len(date_str) < 4:
                return False
            yr = date_str[:4]
            if year_val.startswith("decade_"):
                dec = int(year_val.replace("decade_", "").replace("s", ""))
                return yr.isdigit() and dec <= int(yr) <= dec + 9
            elif year_val.isdigit():
                return yr == year_val
            return True

        media_results = [r for r in media_results if matches_year(r)]

    # Apply local sorting
    if sort_key == "vote_average.desc":
        media_results.sort(key=lambda x: x.get("vote_average", 0), reverse=True)
    elif sort_key in ("primary_release_date.desc", "first_air_date.desc"):
        media_results.sort(key=lambda x: x.get("release_date") or x.get("first_air_date") or "", reverse=True)
    elif sort_key in ("primary_release_date.asc", "first_air_date.asc"):
        media_results.sort(key=lambda x: x.get("release_date") or x.get("first_air_date") or "")

    tmdb_ids = [r["id"] for r in media_results if "id" in r]
    existing_entries = {}

    if tmdb_ids and current_user:
        stmt = select(WatchEntry).where(
            WatchEntry.user_id == current_user.id,
            WatchEntry.tmdb_id.in_(tmdb_ids),
        )
        db_res = await db.execute(stmt)
        entries = db_res.scalars().all()
        existing_entries = {entry.tmdb_id: entry for entry in entries}

    return templates.TemplateResponse(
        request=request,
        name="partials/search_results.html",
        context={
            "results": media_results,
            "existing_entries": existing_entries,
            "active_label": f"Search results for \"{query_str}\"",
        },
    )


@router.get("/info-modal/{tmdb_id}/{media_type}", response_class=HTMLResponse)
async def get_title_info_modal(
    request: Request,
    tmdb_id: int,
    media_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    tmdb_data = await tmdb_service.get_formatted_details(tmdb_id, media_type)

    existing_entry = None
    if current_user:
        stmt = select(WatchEntry).where(
            WatchEntry.user_id == current_user.id,
            WatchEntry.tmdb_id == tmdb_id
        )
        res = await db.execute(stmt)
        existing_entry = res.scalar_one_or_none()

    return templates.TemplateResponse(
        request=request,
        name="partials/title_info_modal.html",
        context={
            "tmdb_data": tmdb_data,
            "tmdb_id": tmdb_id,
            "media_type": media_type,
            "existing_entry": existing_entry,
            "current_user": current_user,
        }
    )
