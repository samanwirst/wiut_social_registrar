from datetime import datetime

from sqlalchemy import JSON, BigInteger, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, UTCDateTime


class UsageEvent(Base):
    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_name_time", "name", "occurred_at"),
        Index("ix_usage_form_time", "form_id", "occurred_at"),
        Index("ix_usage_user_time", "user_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(16))
    user_id: Mapped[int | None] = mapped_column(BigInteger)
    form_id: Mapped[str | None] = mapped_column(String(36))
    session_id: Mapped[str | None] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(16))
    properties: Mapped[dict] = mapped_column(JSON)


class AdminLoginAttempt(Base):
    __tablename__ = "admin_login_attempts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administrator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    outcome: Mapped[str] = mapped_column(String(20))


class AdminChallenge(Base):
    __tablename__ = "admin_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    administrator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    code_hash: Mapped[str] = mapped_column(String(64))
    credential_hash: Mapped[str] = mapped_column(String(64))
    attempts_left: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    delivered: Mapped[bool]


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    administrator_id: Mapped[int] = mapped_column(BigInteger, index=True)
    credential_hash: Mapped[str] = mapped_column(String(64))
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class AnalyticsSetting(Base):
    __tablename__ = "analytics_settings"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[str] = mapped_column(String(100))
