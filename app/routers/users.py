from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app import models, schemas
from app.routers.auth import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}/stats", response_model=schemas.UserStats)
async def get_user_stats(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    user = await db.scalar(select(models.User).where(models.User.id == user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    total = await db.scalar(
        select(func.count(models.WatchEntry.id)).where(models.WatchEntry.user_id == user_id)
    )
    avg_rating = await db.scalar(
        select(func.avg(models.WatchEntry.rating)).where(
            models.WatchEntry.user_id == user_id,
            models.WatchEntry.rating.isnot(None),
        )
    )

    return schemas.UserStats(
        total_watched=total or 0,
        average_rating=round(avg_rating, 2) if avg_rating else None,
    )
