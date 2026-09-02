from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, ConfigDict


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    created_at: datetime


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TitleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tmdb_id: int
    media_type: str
    name: str
    release_year: Optional[int] = None
    poster_path: Optional[str] = None
    overview: Optional[str] = None
    genres: Optional[str] = None


class TitleSearchResult(BaseModel):
    tmdb_id: int
    media_type: str
    name: str
    release_year: Optional[int] = None
    poster_path: Optional[str] = None
    overview: Optional[str] = None


class WatchEntryCreate(BaseModel):
    tmdb_id: int
    media_type: str
    rating: Optional[float] = Field(default=None, ge=0, le=10)
    review_text: Optional[str] = None
    watched_date: Optional[datetime] = None


class WatchEntryUpdate(BaseModel):
    rating: Optional[float] = Field(default=None, ge=0, le=10)
    review_text: Optional[str] = None
    watched_date: Optional[datetime] = None


class WatchEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    rating: Optional[float] = None
    review_text: Optional[str] = None
    watched_date: Optional[datetime] = None
    created_at: datetime
    title: TitleOut


class UserStats(BaseModel):
    total_watched: int
    average_rating: Optional[float] = None
