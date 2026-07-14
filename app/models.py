from datetime import datetime, timezone

from sqlalchemy import Integer, String, Boolean, DateTime, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Settings(Base):
    """Single-row table (id is always 1) holding all user-editable config."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # Plex connection
    plex_base_url: Mapped[str] = mapped_column(String, default="")
    plex_token: Mapped[str] = mapped_column(String, default="")

    # Break heuristic parameters
    break_min_duration_min: Mapped[int] = mapped_column(Integer, default=20)
    break_max_duration_min: Mapped[int] = mapped_column(Integer, default=60)
    break_lead_time_s: Mapped[int] = mapped_column(Integer, default=120)

    # Web Push
    webpush_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    vapid_public_key: Mapped[str] = mapped_column(String, default="")
    vapid_private_key: Mapped[str] = mapped_column(String, default="")

    # Gotify
    gotify_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    gotify_url: Mapped[str] = mapped_column(String, default="")
    gotify_token: Mapped[str] = mapped_column(String, default="")

    # Telegram
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    telegram_bot_token: Mapped[str] = mapped_column(String, default="")
    telegram_chat_id: Mapped[str] = mapped_column(String, default="")


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("endpoint"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(String)
    p256dh: Mapped[str] = mapped_column(String)
    auth: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class SessionState(Base):
    """Tracks one Plex playback session's computed break point + notify dedup."""

    __tablename__ = "session_state"
    __table_args__ = (UniqueConstraint("session_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_key: Mapped[str] = mapped_column(String)
    rating_key: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    suggested_break_offset_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
