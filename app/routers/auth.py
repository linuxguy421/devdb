from datetime import datetime, timedelta, timezone
from typing import Optional
import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User

router = APIRouter(tags=["Auth"])
templates = Jinja2Templates(directory="app/templates")

# bcrypt silently ignores/errors past 72 bytes of input; truncate consistently
# everywhere a password is hashed or checked so hashing and verifying agree.
BCRYPT_MAX_BYTES = 72


def get_password_hash(password: str) -> str:
    pwd_bytes = password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pwd_bytes = plain_password.encode("utf-8")[:BCRYPT_MAX_BYTES]
    hashed_bytes = hashed_password.encode("utf-8")
    return bcrypt.checkpw(pwd_bytes, hashed_bytes)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _extract_token(request: Request) -> Optional[str]:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]

    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token.split(" ", 1)[1] if cookie_token.startswith("Bearer ") else cookie_token

    return None


async def get_current_user_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Resolves the logged-in User from the request, or None. Never raises.

    Use this (directly, or aliased as `get_current_user` on import) in routes
    that should still render for logged-out visitors and handle the missing
    user themselves (redirect to /login, render an anonymous view, etc).
    """
    token = _extract_token(request)
    if not token:
        return None

    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            return None
    except JWTError:
        return None

    stmt = select(User).where(User.username == username)
    res = await db.execute(stmt)
    return res.scalar_one_or_none()


async def get_current_user(
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """Resolves the logged-in User, or raises 401. Use for routes that should
    never be reachable while logged out and don't want to handle that case
    themselves.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return current_user


@router.post("/register")
async def register_post(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    username = username.strip()
    email = email.strip().lower()

    stmt = select(User).where(User.username == username)
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        return RedirectResponse(url="/register?error=exists", status_code=status.HTTP_303_SEE_OTHER)

    new_user = User(
        username=username,
        email=email,
        hashed_password=get_password_hash(password),
    )
    db.add(new_user)

    try:
        await db.commit()
    except IntegrityError:
        # Most likely a duplicate email, since username was already checked above.
        await db.rollback()
        return RedirectResponse(url="/register?error=email_exists", status_code=status.HTTP_303_SEE_OTHER)

    return RedirectResponse(url="/login?success=registered", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(User.username == username.strip())
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "error": "Invalid username or password.",
                "username": username,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    access_token = create_access_token(data={"sub": user.username})
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=f"Bearer {access_token}",
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response
