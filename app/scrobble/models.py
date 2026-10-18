from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class ScrobbleEvent(Base):
    """Append-only ingestion history; never stores bearer tokens or raw payloads."""

    __tablename__ = "scrobble_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    media_item_id: Mapped[int] = mapped_column(
        ForeignKey("media_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(10), nullable=False)
    progress_percent: Mapped[float] = mapped_column(Float, nullable=False)
    season: Mapped[int | None] = mapped_column(Integer, nullable=True)
    episode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    identifier_source: Mapped[str] = mapped_column(String(10), nullable=False)
    identifier_value: Mapped[str] = mapped_column(String(100), nullable=False)
    source_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    received_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "event_type IN ('start', 'pause', 'stop')",
            name="ck_scrobble_events_type_valid",
        ),
        CheckConstraint(
            "progress_percent >= 0 AND progress_percent <= 100",
            name="ck_scrobble_events_progress_valid",
        ),
        CheckConstraint(
            "(season IS NULL AND episode IS NULL) OR "
            "(season >= 0 AND episode >= 1)",
            name="ck_scrobble_events_episode_valid",
        ),
        UniqueConstraint(
            "user_id",
            "source",
            "source_event_id",
            name="uq_scrobble_event_source_id",
        ),
    )
