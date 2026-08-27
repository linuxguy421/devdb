from datetime import datetime, timedelta
from typing import Optional
import bcrypt
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User

router = APIRouter(tags=["Auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False)

# Adjust directory to "app/templates" if your HTML files live under /app/templates
templates = Jinja2Templates(directory="app/templates")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db)) -> Optional[User]:
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]

    if not token:
        cookie_token = request.cookies.get("access_token")
        if cookie_token:
            token = cookie_token.split(" ")[1] if cookie_token.startswith("Bearer ") else cookie_token

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


@router.post("/register")
async def register_post(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(User.username == username)
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        return RedirectResponse(url="/register?error=exists", status_code=status.HTTP_303_SEE_OTHER)

    new_user = User(
        username=username,
        email=email,
        hashed_password=get_password_hash(password)
    )
    db.add(new_user)
    await db.commit()

    return RedirectResponse(url="/login?success=registered", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/login")
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(User).where(User.username == username)
    res = await db.execute(stmt)
    user = res.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={
                "request": request,  # <-- Crucial line
                "error": "Invalid username or password.",
                "username": username,
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    access_token = create_access_token(data={"sub": user.username})
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True, samesite="lax")
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    return response
