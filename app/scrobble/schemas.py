from enum import Enum
import re
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class IdentifierSource(str, Enum):
    TMDB = "tmdb"
    IMDB = "imdb"
    TVDB = "tvdb"


class ScrobbleMediaType(str, Enum):
    MOVIE = "movie"
    SHOW = "show"


class ScrobbleEventType(str, Enum):
    START = "start"
    PAUSE = "pause"
    STOP = "stop"


class MediaIdentifier(BaseModel):
    """An external ID used to resolve a DevDB canonical MediaItem."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    source: IdentifierSource
    value: Annotated[str, Field(min_length=1, max_length=100)]

    @field_validator("value")
    @classmethod
    def validate_identifier(cls, value: str, info):
        source = info.data.get("source")
        if source == IdentifierSource.TMDB and not value.isdigit():
            raise ValueError("TMDB identifiers must be numeric")
        if source == IdentifierSource.TVDB and not value.isdigit():
            raise ValueError("TVDB identifiers must be numeric")
        if source == IdentifierSource.IMDB and not re.fullmatch(r"tt\d+", value):
            raise ValueError("IMDb identifiers must look like tt1234567")
        if source in {IdentifierSource.TMDB, IdentifierSource.TVDB} and int(value) < 1:
            raise ValueError("Identifiers must be positive")
        return value


class NormalizedScrobble(BaseModel):
    """Canonical payload accepted by the ingestion pipeline.

    user_token is a DevDB access token (JWT). Source-specific adapters obtain it
    from the Authorization/X-DevDB-Token header rather than trusting webhook
    fields that could let a sender impersonate another user.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    user_token: Annotated[str, Field(min_length=20, max_length=4096)]
    media_identifier: MediaIdentifier
    media_type: ScrobbleMediaType
    season: int | None = Field(default=None, ge=0, le=500)
    episode: int | None = Field(default=None, ge=1, le=10000)
    progress_percent: float = Field(ge=0, le=100)
    event_type: ScrobbleEventType
    source_event_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_episode_fields(self):
        if self.media_type == ScrobbleMediaType.MOVIE and (
            self.season is not None or self.episode is not None
        ):
            raise ValueError("season and episode are only valid for shows")
        if (self.season is None) != (self.episode is None):
            raise ValueError("season and episode must be provided together")
        return self
