from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api_keys.models import APIKey
from app.api_keys.service import generate_api_key, SCROBBLE_WRITE_SCOPE
from app.database import get_db
from app.models import User
from app.routers.auth import get_current_user

router = APIRouter(prefix="/api/v1/api-keys", tags=["API keys"])


class CreateAPIKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scope: Literal["scrobble:write"] = SCROBBLE_WRITE_SCOPE


@router.get("")
async def list_api_keys(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIKey).where(APIKey.user_id == current_user.id).order_by(APIKey.created_at.desc()))
    keys = result.scalars().all()
    return {"api_keys": [{"id": key.id, "name": key.name, "prefix": key.key_prefix, "scopes": key.scopes.split(), "created_at": key.created_at, "last_used_at": key.last_used_at, "revoked_at": key.revoked_at, "active": key.revoked_at is None} for key in keys]}


@router.post("", status_code=201)
async def create_api_key(payload: CreateAPIKeyRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    raw_key, prefix, key_hash = generate_api_key()
    record = APIKey(user_id=current_user.id, name=payload.name.strip(), key_prefix=prefix, key_hash=key_hash, scopes=payload.scope)
    if not record.name:
        raise HTTPException(status_code=422, detail="Name cannot be blank")
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return {"id": record.id, "name": record.name, "key": raw_key, "prefix": record.key_prefix, "scopes": record.scopes.split(), "created_at": record.created_at, "warning": "Copy this key now. It will not be shown again."}


@router.delete("/{key_id}", status_code=204)
async def revoke_api_key(key_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(APIKey).where(APIKey.id == key_id, APIKey.user_id == current_user.id))
    record = result.scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found")
    if record.revoked_at is None:
        record.revoked_at = datetime.now().astimezone()
        await db.commit()
    return None
