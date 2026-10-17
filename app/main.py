from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.middleware import SecurityMiddleware

from app.config import settings
from app.database import AsyncSessionLocal
from app.routers import auth, pages, titles, users, watch_entries, buddies, profile, what_to_watch, admin
from app.services.avatars import ensure_avatar_dir


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ensure_avatar_dir()
    except OSError:
        # Volume permissions may need fixing on first deploy; routes will error clearly.
        pass
    yield


app = FastAPI(
    title="DevDB",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Mount static directory for logo and asset serving
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Local avatars (Docker volume or host path via AVATAR_DIR)
avatar_dir = Path(settings.AVATAR_DIR)
avatar_dir.mkdir(parents=True, exist_ok=True)
app.mount(
    "/media/avatars",
    StaticFiles(directory=str(avatar_dir)),
    name="avatars",
)

app.add_middleware(SecurityMiddleware)

# Permit origins across localhost and LAN
origins = [
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://onyx:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", status_code=200, tags=["Health"])
async def healthz():
    return {"status": "ok"}


@app.get("/readyz", status_code=200, tags=["Health"])
async def readyz():
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready"})

    return {"status": "ready"}


app.include_router(auth.router)
app.include_router(titles.router)
app.include_router(watch_entries.router)
app.include_router(users.router)
app.include_router(pages.router)
app.include_router(buddies.router)
app.include_router(profile.router)
app.include_router(what_to_watch.router)
app.include_router(admin.router)
