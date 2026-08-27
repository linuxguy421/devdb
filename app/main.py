from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import models  # Import models so Base metadata is populated
from app.config import settings
from app.database import Base, engine
from app.routers import auth, pages, titles, users, watch_entries, buddies, to_watch, profile


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables on startup using async engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="DevDB",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

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


app.include_router(auth.router)
app.include_router(titles.router)
app.include_router(watch_entries.router)
app.include_router(users.router)
app.include_router(pages.router)
app.include_router(buddies.router)
app.include_router(to_watch.router)
app.include_router(profile.router)
