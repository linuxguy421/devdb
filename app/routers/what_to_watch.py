from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.routers.auth import get_current_user_optional as get_current_user
from app.services.watch_recommendations import get_watch_pick, pick_length_label

router = APIRouter(tags=["What Should I Watch"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/what-to-watch", response_class=HTMLResponse)
async def what_to_watch(
    request: Request,
    media_type: str = Query("all"),
    length: str = Query("any"),
    mood: str = Query("comfort"),
    exclude: Optional[int] = Query(None),
    surprise: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    media_type = media_type if media_type in {"all", "movie", "tv"} else "all"
    length = length if length in {"any", "short", "normal", "long"} else "any"
    mood = mood if mood in {"comfort", "new"} else "comfort"

    pick = await get_watch_pick(
        db,
        current_user.id,
        media_type=media_type,
        length=length,
        mood=mood,
        exclude_entry_id=exclude,
        surprise=surprise,
    )

    return templates.TemplateResponse(
        request=request,
        name="what_to_watch.html",
        context={
            "request": request,
            "current_user": current_user,
            "pick": pick,
            "pick_length": pick_length_label(pick.media) if pick else None,
            "filters": {
                "media_type": media_type,
                "length": length,
                "mood": mood,
            },
        },
    )
