from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.routers.auth import get_current_user_optional as get_current_user
from app.services.stats import get_stats

router = APIRouter(tags=["Stats"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    year: Optional[int] = None,
    media_type: str = "all",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    selected_media_type = media_type if media_type in {"all", "movie", "tv"} else "all"
    stats = await get_stats(db, current_user.id, year=year, media_type=selected_media_type)

    return templates.TemplateResponse(
        request=request,
        name="stats.html",
        context={
            "request": request,
            "current_user": current_user,
            "stats": stats,
        },
    )
