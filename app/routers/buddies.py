import asyncio
import logging
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Friendship, Recommendation, User, WatchEntry
from app.routers.auth import get_current_user
from app.services.tmdb import tmdb_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/buddies", tags=["buddies"])
templates = Jinja2Templates(directory="app/templates")


# --- Phase 1: Buddy Management & Search ---

@router.get("/modal", response_class=HTMLResponse)
async def buddy_modal(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt_pending = (
        select(Friendship)
        .options(selectinload(Friendship.requester))
        .where(
            Friendship.buddy_id == current_user.id,
            Friendship.status == "pending"
        )
    )
    res_pending = await db.execute(stmt_pending)
    pending_requests = res_pending.scalars().all()

    stmt_accepted = select(Friendship).where(
        or_(Friendship.user_id == current_user.id, Friendship.buddy_id == current_user.id),
        Friendship.status == "accepted"
    )
    res_accepted = await db.execute(stmt_accepted)
    accepted_friendships = res_accepted.scalars().all()

    return templates.TemplateResponse(
        request=request,
        name="partials/buddy_modal.html",
        context={
            "pending_requests": pending_requests,
            "accepted_count": len(accepted_friendships),
        }
    )


@router.get("/search", response_class=HTMLResponse)
async def search_users(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query_str = q.strip()
    if not query_str:
        return HTMLResponse("")

    stmt_users = select(User).where(
        User.username.ilike(f"%{query_str}%"),
        User.id != current_user.id
    ).limit(10)
    res_users = await db.execute(stmt_users)
    users = res_users.scalars().all()

    user_ids = [u.id for u in users]
    status_map = {}

    if user_ids:
        stmt_existing = select(Friendship).where(
            or_(
                and_(Friendship.user_id == current_user.id, Friendship.buddy_id.in_(user_ids)),
                and_(Friendship.buddy_id == current_user.id, Friendship.user_id.in_(user_ids))
            )
        )
        res_existing = await db.execute(stmt_existing)
        existing_friendships = res_existing.scalars().all()

        for f in existing_friendships:
            target_id = f.buddy_id if f.user_id == current_user.id else f.user_id
            status_map[target_id] = f.status

    return templates.TemplateResponse(
        request=request,
        name="partials/buddy_search_results.html",
        context={"users": users, "status_map": status_map}
    )


@router.post("/request/{user_id}", response_class=HTMLResponse)
async def send_request(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt_existing = select(Friendship).where(
        or_(
            and_(Friendship.user_id == current_user.id, Friendship.buddy_id == user_id),
            and_(Friendship.buddy_id == current_user.id, Friendship.user_id == user_id)
        )
    )
    res_existing = await db.execute(stmt_existing)
    existing = res_existing.scalars().first()

    if not existing:
        new_friendship = Friendship(user_id=current_user.id, buddy_id=user_id, status="pending")
        db.add(new_friendship)
        await db.commit()

    return HTMLResponse('<span class="text-xs font-semibold text-neutral-400 bg-neutral-800 px-3 py-1 rounded-full">Request Sent</span>')


@router.post("/respond/{friendship_id}", response_class=HTMLResponse)
async def respond_request(
    friendship_id: int,
    action: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt = select(Friendship).where(Friendship.id == friendship_id)
    res = await db.execute(stmt)
    friendship = res.scalars().first()

    if friendship and friendship.buddy_id == current_user.id:
        if action == "accept":
            friendship.status = "accepted"
            await db.commit()
        elif action == "decline":
            await db.delete(friendship)
            await db.commit()

    return HTMLResponse("")


# --- Phase 2: Activity Feed Partial ---

@router.get("/activity-partial", response_class=HTMLResponse)
async def buddy_activity_partial(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        stmt_friends = select(Friendship).where(
            or_(Friendship.user_id == current_user.id, Friendship.buddy_id == current_user.id),
            Friendship.status == "accepted"
        )
        res_friends = await db.execute(stmt_friends)
        friendships = res_friends.scalars().all()
        buddy_ids = [f.buddy_id if f.user_id == current_user.id else f.user_id for f in friendships]

        if not buddy_ids:
            return templates.TemplateResponse(
                request=request, name="partials/buddy_activity_feed.html", context={"activity_items": []}
            )

        stmt_entries = (
            select(WatchEntry, User)
            .join(User, WatchEntry.user_id == User.id)
            .where(WatchEntry.user_id.in_(buddy_ids))
            .order_by(WatchEntry.created_at.desc())
            .limit(12)
        )
        res_entries = await db.execute(stmt_entries)
        results = res_entries.all()

        async def fetch_item(entry, user):
            tmdb_data = None
            if entry.tmdb_id and entry.media_type:
                try:
                    tmdb_data = await asyncio.wait_for(
                        tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type),
                        timeout=2.0
                    )
                except Exception as err:
                    logger.warning(f"TMDB fetch bypassed for entry {entry.id}: {err}")

            if not tmdb_data or not tmdb_data.get("title"):
                tmdb_data = {
                    "title": f"Media #{entry.tmdb_id}",
                    "poster_path": entry.poster_path,
                }
            elif not tmdb_data.get("poster_path") and entry.poster_path:
                tmdb_data["poster_path"] = entry.poster_path

            return {
                "entry": entry,
                "user": user,
                "tmdb_data": tmdb_data,
            }

        activity_items = await asyncio.gather(*[fetch_item(entry, user) for entry, user in results])

    except Exception as exc:
        logger.error(f"Error in buddy_activity_partial: {exc}", exc_info=True)
        activity_items = []

    return templates.TemplateResponse(
        request=request,
        name="partials/buddy_activity_feed.html",
        context={"activity_items": activity_items}
    )


# --- Phase 3: Mutual Watchlist & Recommendations ---

@router.get("/mutual-watchlist", response_class=HTMLResponse)
async def get_mutual_watchlist(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt_friends = select(Friendship).where(
        or_(Friendship.user_id == current_user.id, Friendship.buddy_id == current_user.id),
        Friendship.status == "accepted"
    )
    res_friends = await db.execute(stmt_friends)
    friendships = res_friends.scalars().all()
    buddy_ids = [f.buddy_id if f.user_id == current_user.id else f.user_id for f in friendships]

    if not buddy_ids:
        return templates.TemplateResponse(
            request=request, name="partials/mutual_watchlist.html", context={"mutual_items": []}
        )

    my_stmt = select(WatchEntry).where(
        WatchEntry.user_id == current_user.id,
        WatchEntry.status == "to_watch"
    )
    my_entries = (await db.execute(my_stmt)).scalars().all()
    my_keys = {(e.tmdb_id, e.media_type) for e in my_entries}

    buddy_stmt = select(WatchEntry, User).join(User, WatchEntry.user_id == User.id).where(
        WatchEntry.user_id.in_(buddy_ids),
        WatchEntry.status == "to_watch"
    )
    results = (await db.execute(buddy_stmt)).all()

    mutual_items = []
    seen = set()
    for entry, buddy in results:
        key = (entry.tmdb_id, entry.media_type)
        if key in my_keys and key not in seen:
            seen.add(key)
            try:
                tmdb_data = await asyncio.wait_for(
                    tmdb_service.get_formatted_details(entry.tmdb_id, entry.media_type),
                    timeout=2.0
                )
            except Exception:
                tmdb_data = {"title": f"Media #{entry.tmdb_id}", "poster_path": entry.poster_path}
            mutual_items.append({"tmdb_data": tmdb_data, "buddy": buddy})

    return templates.TemplateResponse(
        request=request, name="partials/mutual_watchlist.html", context={"mutual_items": mutual_items}
    )


@router.get("/recommend-modal/{tmdb_id}/{media_type}", response_class=HTMLResponse)
async def recommend_modal(
    request: Request,
    tmdb_id: int,
    media_type: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    stmt_friends = select(Friendship).where(
        or_(Friendship.user_id == current_user.id, Friendship.buddy_id == current_user.id),
        Friendship.status == "accepted"
    )
    res_friends = await db.execute(stmt_friends)
    friendships = res_friends.scalars().all()
    buddy_ids = [f.buddy_id if f.user_id == current_user.id else f.user_id for f in friendships]

    buddies = []
    if buddy_ids:
        user_stmt = select(User).where(User.id.in_(buddy_ids))
        buddies = (await db.execute(user_stmt)).scalars().all()

    tmdb_data = await tmdb_service.get_formatted_details(tmdb_id, media_type)

    return templates.TemplateResponse(
        request=request,
        name="partials/recommend_modal.html",
        context={"tmdb_data": tmdb_data, "buddies": buddies, "tmdb_id": tmdb_id, "media_type": media_type}
    )


@router.post("/recommend", response_class=HTMLResponse)
async def send_recommendation(
    receiver_id: int = Form(...),
    tmdb_id: int = Form(...),
    media_type: str = Form(...),
    note: str = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rec = Recommendation(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        tmdb_id=tmdb_id,
        media_type=media_type,
        note=note
    )
    db.add(rec)
    await db.commit()

    return HTMLResponse('<div id="modal-container" hx-swap-oob="true"></div>')
