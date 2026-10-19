import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.scrobble.adapters import parse_jellyfin_payload, parse_plex_payload
from app.scrobble.schemas import NormalizedScrobble
from app.scrobble.service import process_scrobble

router = APIRouter(prefix="/api/v1/scrobble", tags=["Scrobbling"])


def _header_token(authorization: str | None, devdb_token: str | None) -> str:
    if devdb_token and devdb_token.strip():
        return devdb_token.strip()
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.casefold() == "bearer" and value.strip():
            return value.strip()
    raise HTTPException(
        status_code=401,
        detail="Provide a DevDB token in Authorization: Bearer ... or X-DevDB-Token",
    )


async def _read_plex_request(request: Request) -> Any:
    content_type = request.headers.get("content-type", "").casefold()
    if "application/json" in content_type:
        try:
            return await request.json()
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="Invalid Plex JSON payload") from exc

    if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        payload = form.get("payload") or form.get("Payload")
        if payload is None:
            raise HTTPException(status_code=422, detail="Plex form payload field is missing")
        return {"Payload": payload}

    try:
        return await request.json()
    except Exception as exc:
        raise HTTPException(status_code=415, detail="Unsupported Plex content type") from exc


@router.post("/generic")
async def scrobble_generic(
    payload: NormalizedScrobble,
    authorization: str | None = Header(default=None),
    x_devdb_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Prefer a header credential; retain body-token compatibility for existing clients.
    if authorization or x_devdb_token:
        payload.user_token = _header_token(authorization, x_devdb_token)
    if not payload.user_token:
        raise HTTPException(status_code=401, detail="Provide a DevDB JWT/API key in the Authorization header or user_token field")
    return await process_scrobble(db, payload, source="generic")


@router.post("/plex")
async def scrobble_plex(
    request: Request,
    authorization: str | None = Header(default=None),
    x_devdb_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = _header_token(authorization, x_devdb_token)
    normalized = parse_plex_payload(await _read_plex_request(request), token)
    return await process_scrobble(db, normalized, source="plex")


@router.post("/jellyfin")
async def scrobble_jellyfin(
    request: Request,
    authorization: str | None = Header(default=None),
    x_devdb_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = _header_token(authorization, x_devdb_token)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid Jellyfin JSON payload") from exc
    normalized = parse_jellyfin_payload(payload, token)
    return await process_scrobble(db, normalized, source="jellyfin")
