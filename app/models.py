from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint, Float
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base


class Friendship(Base):
    __tablename__ = 'friendships'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    buddy_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(String(20), default='pending')
    created_at = Column(DateTime, default=datetime.utcnow)

    requester = relationship('User', foreign_keys=[user_id], backref='sent_requests')
    receiver = relationship('User', foreign_keys=[buddy_id], backref='received_requests')

    __table_args__ = (
        UniqueConstraint('user_id', 'buddy_id', name='unique_user_buddy_pair'),
    )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    avatar_url = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    watch_entries = relationship("WatchEntry", back_populates="user", cascade="all, delete-orphan")


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(Integer, primary_key=True, index=True)
    tmdb_id = Column(Integer, nullable=False, index=True)
    media_type = Column(String(20), nullable=False, default="movie")
    title = Column(String, nullable=False)
    overview = Column(Text, nullable=True)
    poster_path = Column(String, nullable=True)
    backdrop_path = Column(String, nullable=True)
    release_date = Column(String, nullable=True)
    runtime = Column(Integer, nullable=True)
    genres = Column(Text, nullable=True)
    vote_average = Column(Float, nullable=True)
    last_synced_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    watch_entries = relationship("WatchEntry", back_populates="media_item")

    __table_args__ = (
        UniqueConstraint("tmdb_id", "media_type", name="uq_media_item_tmdb_type"),
    )


class WatchEntry(Base):
    __tablename__ = "watch_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    media_item_id = Column(Integer, ForeignKey("media_items.id", ondelete="SET NULL"), nullable=True, index=True)
    tmdb_id = Column(Integer, nullable=False, index=True)
    media_type = Column(String, nullable=False, default="movie")
    poster_path = Column(String, nullable=True)
    status = Column(String, nullable=False, default="plan_to_watch")
    rating = Column(Float, nullable=True)
    notes = Column(String, nullable=True)
    is_private = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="watch_entries")
    media_item = relationship("MediaItem", back_populates="watch_entries")

    __table_args__ = (
        UniqueConstraint("user_id", "tmdb_id", "media_type", name="uq_watch_entry_user_title"),
    )


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    tmdb_id: Mapped[int] = mapped_column(Integer, nullable=False)
    media_type: Mapped[str] = mapped_column(String(20), default="movie")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sender: Mapped["User"] = relationship("User", foreign_keys=[sender_id])
    receiver: Mapped["User"] = relationship("User", foreign_keys=[receiver_id])
