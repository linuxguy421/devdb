from typing import Optional
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User, WatchEntry
from app.routers.auth import get_current_user
from app.services.tmdb import tmdb_service

router = APIRouter(tags=["To Watch"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/to-watch", response_class=HTMLResponse)
async def get_to_watch_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    stmt = (
        select(WatchEntry)
        .where(
            WatchEntry.user_id == current_user.id,
            WatchEntry.status == "to_watch",
        )
        .order_by(WatchEntry.created_at.desc())
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()

    for entry in entries:
        entry.tmdb_data = await tmdb_service.get_formatted_details(
            entry.tmdb_id, entry.media_type
        )

    return templates.TemplateResponse(
        request=request,
        name="to_watch.html",
        context={
            "request": request,
            "entries": entries,
            "current_user": current_user,
        },
    )
