from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app import models, schemas
from app.auth import get_current_user

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/{user_id}/stats", response_model=schemas.UserStats)
def get_user_stats(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    total = (
        db.query(func.count(models.WatchEntry.id))
        .filter(models.WatchEntry.user_id == user_id)
        .scalar()
    )
    avg_rating = (
        db.query(func.avg(models.WatchEntry.rating))
        .filter(
            models.WatchEntry.user_id == user_id,
            models.WatchEntry.rating.isnot(None),
        )
        .scalar()
    )

    return schemas.UserStats(
        total_watched=total or 0,
        average_rating=round(avg_rating, 2) if avg_rating else None,
    )
