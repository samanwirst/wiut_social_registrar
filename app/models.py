from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from registrar.models import Student


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("Database timestamps must include a timezone.")
            return value.astimezone(timezone.utc)
        return None

    def process_result_value(self, value, dialect):
        return (
            value.replace(tzinfo=timezone.utc)
            if value is not None and value.tzinfo is None
            else value
        )


class Base(DeclarativeBase):
    pass


class OutlookProfile(Base):
    __tablename__ = "outlook_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[str] = mapped_column(String(32), index=True)
    graph_id: Mapped[str | None] = mapped_column(String(64), index=True)
    account: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(256))
    given_name: Mapped[str | None] = mapped_column(String(256))
    surname: Mapped[str | None] = mapped_column(String(256))
    email: Mapped[str] = mapped_column(String(320))
    email_addresses: Mapped[list] = mapped_column(JSON)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)

    def student(self) -> Student:
        return Student(
            self.student_id,
            self.display_name or "",
            self.email,
            account=self.account,
            email_addresses=self.email_addresses,
            graph_id=self.graph_id or "",
            given_name=self.given_name or "",
            surname=self.surname or "",
        )


class TelegramUser(Base):
    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    first_name: Mapped[str] = mapped_column(String(256))
    last_name: Mapped[str | None] = mapped_column(String(256))
    username: Mapped[str | None] = mapped_column(String(64), index=True)
    language_code: Mapped[str | None] = mapped_column(String(35))
    is_premium: Mapped[bool | None]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    profile_updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    phone_number: Mapped[str | None] = mapped_column(String(32))
    phone_shared_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    education_level: Mapped[str | None] = mapped_column(String(16), index=True)
    education_selected_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    registered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    outlook_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("outlook_profiles.id"), index=True
    )


class VerificationChallenge(Base):
    __tablename__ = "verification_challenges"

    telegram_user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id"), primary_key=True)
    outlook_profile_id: Mapped[int] = mapped_column(ForeignKey("outlook_profiles.id"), index=True)
    nonce: Mapped[str] = mapped_column(String(32))
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts_left: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    email_status: Mapped[str] = mapped_column(String(20))


class RegistrationEvent(Base):
    __tablename__ = "registration_events"
    __table_args__ = (
        Index("ix_events_user_type_time", "telegram_user_id", "event_type", "occurred_at"),
        Index("ix_events_profile_type_time", "outlook_profile_id", "event_type", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id"))
    outlook_profile_id: Mapped[int | None] = mapped_column(ForeignKey("outlook_profiles.id"))
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    details: Mapped[dict] = mapped_column(JSON)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    creator_telegram_user_id: Mapped[int] = mapped_column(
        ForeignKey("telegram_users.id"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    registration_open: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    questions: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    response_retention_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    form_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    form_locked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class EventRegistration(Base):
    __tablename__ = "event_registrations"
    __table_args__ = (
        UniqueConstraint("event_id", "outlook_profile_id", name="uq_event_student"),
        UniqueConstraint("event_id", "telegram_user_id", name="uq_event_telegram_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"))
    telegram_user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id"), index=True)
    outlook_profile_id: Mapped[int] = mapped_column(ForeignKey("outlook_profiles.id"), index=True)
    registered_at: Mapped[datetime] = mapped_column(UTCDateTime)


class PendingEventRegistration(Base):
    __tablename__ = "pending_event_registrations"

    telegram_user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime)


class EventAnswers(Base):
    __tablename__ = "event_answers"

    registration_id: Mapped[int] = mapped_column(
        ForeignKey("event_registrations.id", ondelete="CASCADE"), primary_key=True
    )
    answers: Mapped[dict] = mapped_column(JSON)
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class EventFormSession(Base):
    """Short-lived questionnaire progress; never part of the student's permanent profile."""

    __tablename__ = "event_form_sessions"

    telegram_user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id"), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    question_index: Mapped[int] = mapped_column(Integer)
    token: Mapped[str] = mapped_column(String(16))
    answers: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
