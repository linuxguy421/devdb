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


@router.get("/search-partial", response_class=HTMLResponse)
async def search_titles_partial(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not q.strip():
        return templates.TemplateResponse(
            request=request,
            name="partials/search_results.html",
            context={"results": [], "existing_entries": {}},
        )

    data = await tmdb_service.search_multi(query=q)
    results = data.get("results", [])
    media_results = [r for r in results if r.get("media_type") in ("movie", "tv")]

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
