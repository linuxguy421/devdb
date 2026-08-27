from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from app.database import Base

class Friendship(Base):
    __tablename__ = 'friendships'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    buddy_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(String(20), default='pending')  # 'pending', 'accepted'
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
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


class WatchEntry(Base):
    __tablename__ = "watch_entries"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tmdb_id = Column(Integer, nullable=False, index=True)
    media_type = Column(String, nullable=False, default="movie")
    poster_path = Column(String, nullable=True)
    status = Column(String, nullable=False, default="plan_to_watch")
    rating = Column(Integer, nullable=True)
    notes = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="watch_entries")

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
