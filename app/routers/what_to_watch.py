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
    source: str = Query("for_you"),
    exclude_tmdb_id: Optional[int] = Query(None),
    genre: str = Query("any"),
    min_rating: float = Query(0, ge=0, le=10),
    year_filter: str = Query("any"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
):
    if not current_user:
        return RedirectResponse(url="/login", status_code=303)

    media_type = media_type if media_type in {"all", "movie", "tv"} else "all"
    length = length if length in {"any", "short", "normal", "long"} else "any"
    mood = mood if mood in {"comfort", "new"} else "comfort"
    source = source if source in {"for_you", "my_list", "discover", "buddies"} else "for_you"
    allowed_genres = {"any", "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary", "Drama", "Family", "Fantasy", "History", "Horror", "Mystery", "Romance", "Science Fiction", "Thriller", "Western", "Action & Adventure", "Kids", "Sci-Fi & Fantasy"}
    genre = genre if genre in allowed_genres else "any"
    allowed_years = {"any", "decade_2020s", "decade_2010s", "decade_2000s", "decade_1990s", "decade_1980s", "decade_1970s", "decade_1960s", "decade_1950s"}
    year_filter = year_filter if year_filter in allowed_years else "any"
    min_rating = min(max(min_rating, 0), 10)

    pick = await get_watch_pick(
        db,
        current_user.id,
        media_type=media_type,
        length=length,
        mood=mood,
        exclude_entry_id=exclude,
        surprise=surprise,
        source=source,
        exclude_tmdb_id=exclude_tmdb_id,
        genre=genre,
        min_rating=min_rating,
        year_filter=year_filter,
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
                "source": source,
                "genre": genre,
                "min_rating": min_rating,
                "year_filter": year_filter,
            },
        },
    )
