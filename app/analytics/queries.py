"""Administrator-only aggregate projections. No answers, contacts, codes or file references."""

import hashlib
import hmac
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import case, distinct, func, select

from app.analytics.events import properties
from app.analytics.models import AnalyticsSetting, UsageEvent
from app.clock import utc_now
from app.models import (
    BroadcastRecipient,
    Event,
    EventFormSession,
    EventRegistration,
    RegistrationEvent,
    TelegramUser,
    VerificationChallenge,
)


def date_range(start, end, *, now=None):
    now = now or utc_now()
    try:
        start = datetime.combine(
            datetime.strptime(start, "%Y-%m-%d").date(), time.min, timezone.utc
        )
        end = datetime.combine(
            datetime.strptime(end, "%Y-%m-%d").date(), time.min, timezone.utc
        ) + timedelta(days=1)
        if not 0 < (end - start).days <= 365 or start > now:
            raise ValueError
    except (TypeError, ValueError):
        raise ValueError("Choose a valid UTC date range of at most 365 days") from None
    return start, min(end, now)


def bounded_page(value):
    try:
        page = int(value)
        if not 0 <= page <= 10000:
            raise ValueError
        return page
    except (ValueError, TypeError):
        raise ValueError("Choose a valid page") from None


def in_range(column, start, end):
    return (column >= start) & (column < end)


def percentage(part, total):
    return round(100 * part / total, 1) if total else 0


class AnalyticsQueries:
    def __init__(self, database, secret, *, clock=utc_now):
        self.db, self.clock, self.secret = database, clock, secret.encode()

    def user_label(self, user_id):
        return (
            "User " + hmac.new(self.secret, str(user_id).encode(), hashlib.sha256).hexdigest()[:10]
        )

    async def summary(self, start, end):
        usage_period = in_range(UsageEvent.occurred_at, start, end)
        user_period = in_range(TelegramUser.created_at, start, end)
        async with self.db.transaction() as session:

            async def count(model, *conditions):
                return await session.scalar(
                    select(func.count()).select_from(model).where(*conditions)
                )

            inventory = {
                "users": await count(TelegramUser),
                "registered": await count(TelegramUser, TelegramUser.registered_at.is_not(None)),
                "organizers": await session.scalar(
                    select(func.count(distinct(Event.creator_telegram_user_id)))
                ),
                "forms": await count(Event),
                "open_forms": await count(Event, Event.registration_open.is_(True)),
                "anonymous_forms": await count(Event, Event.anonymous.is_(True)),
                "submissions": await count(EventRegistration),
                "active_questionnaires": await count(
                    EventFormSession, EventFormSession.expires_at > self.clock()
                ),
                "pending_email": await count(
                    VerificationChallenge, VerificationChallenge.expires_at > self.clock()
                ),
            }
            metrics = {
                "events": await count(UsageEvent, usage_period),
                "active_users": await session.scalar(
                    select(func.count(distinct(UsageEvent.user_id))).where(usage_period)
                ),
                "new_users": await count(TelegramUser, user_period),
                "completed_registrations": await count(
                    TelegramUser, in_range(TelegramUser.registered_at, start, end)
                ),
                "submissions": await count(
                    EventRegistration, in_range(EventRegistration.registered_at, start, end)
                ),
                "miniapp_sessions": await session.scalar(
                    select(func.count(distinct(UsageEvent.session_id))).where(
                        usage_period, UsageEvent.source == "miniapp"
                    )
                ),
                "errors": await count(UsageEvent, usage_period, UsageEvent.outcome == "error"),
            }
            funnel = [{"stage": "First interaction", "users": metrics["new_users"]}]
            for name, title in (
                ("verification_requested", "Student ID accepted"),
                ("verification_succeeded", "Email verified"),
                ("phone_shared", "Phone shared"),
                ("registration_completed", "Education selected / complete"),
            ):
                reached = await session.scalar(
                    select(func.count(distinct(RegistrationEvent.telegram_user_id)))
                    .join(TelegramUser, TelegramUser.id == RegistrationEvent.telegram_user_id)
                    .where(
                        user_period,
                        RegistrationEvent.occurred_at < end,
                        RegistrationEvent.event_type == name,
                    )
                )
                previous = funnel[-1]["users"]
                funnel.append(
                    {
                        "stage": title,
                        "users": reached,
                        "dropoff": max(0, previous - reached),
                        "conversion": percentage(reached, previous),
                    }
                )

            day = func.date(UsageEvent.occurred_at)
            daily = [
                {"date": str(date), "events": total, "users": users, "errors": errors}
                for date, total, users, errors in (
                    await session.execute(
                        select(
                            day,
                            func.count(),
                            func.count(distinct(UsageEvent.user_id)),
                            func.sum(case((UsageEvent.outcome == "error", 1), else_=0)),
                        )
                        .where(usage_period)
                        .group_by(day)
                        .order_by(day)
                    )
                ).all()
            ]
            by_day = {row["date"]: row for row in daily}
            daily = []
            day_cursor = start.date()
            while day_cursor <= (end - timedelta(microseconds=1)).date():
                key = day_cursor.isoformat()
                daily.append(by_day.get(key, {"date": key, "events": 0, "users": 0, "errors": 0}))
                day_cursor += timedelta(days=1)

            async def distribution(expression, *, condition=None, limit=30):
                query = select(expression, func.count()).where(
                    usage_period, expression.is_not(None)
                )
                if condition is not None:
                    query = query.where(condition)
                return [
                    {"label": str(key), "count": value}
                    for key, value in (
                        await session.execute(
                            query.group_by(expression).order_by(func.count().desc()).limit(limit)
                        )
                    ).all()
                ]

            actions = await distribution(UsageEvent.properties["action"].as_string())
            platforms = await distribution(
                UsageEvent.properties["platform"].as_string(),
                condition=UsageEvent.name == "panel_opened",
            )
            outcomes = await distribution(UsageEvent.name, condition=UsageEvent.outcome != "ok")
            features = await distribution(
                UsageEvent.properties["action"].as_string(),
                condition=UsageEvent.name.in_(["chat_action", "ui_action"])
                & UsageEvent.properties["action"]
                .as_string()
                .not_in(["other_control", "field_interaction"]),
            )
            if not features:
                features = await distribution(
                    UsageEvent.name,
                    condition=UsageEvent.name.not_in(
                        ["http_request", "telegram_request", "screen_engagement"]
                    ),
                )
            error_kind = UsageEvent.properties["error"].as_string()
            issues = [
                {
                    "event": name,
                    "category": error or "unknown",
                    "outcome": outcome,
                    "count": total,
                    "last_seen": last.isoformat(),
                }
                for name, error, outcome, total, last in (
                    await session.execute(
                        select(
                            UsageEvent.name,
                            error_kind,
                            UsageEvent.outcome,
                            func.count(),
                            func.max(UsageEvent.occurred_at),
                        )
                        .where(usage_period, UsageEvent.outcome != "ok")
                        .group_by(UsageEvent.name, error_kind, UsageEvent.outcome)
                        .order_by(func.count().desc())
                        .limit(40)
                    )
                ).all()
            ]
            route = UsageEvent.properties["route"].as_string()
            performance = [
                {
                    "route": name,
                    "requests": total,
                    "average_ms": round(mean or 0),
                    "maximum_ms": maximum or 0,
                    "slow": slow or 0,
                    "errors": errors or 0,
                }
                for name, total, mean, maximum, slow, errors in (
                    await session.execute(
                        select(
                            route,
                            func.count(),
                            func.avg(UsageEvent.duration_ms),
                            func.max(UsageEvent.duration_ms),
                            func.sum(case((UsageEvent.duration_ms >= 2000, 1), else_=0)),
                            func.sum(case((UsageEvent.outcome == "error", 1), else_=0)),
                        )
                        .where(usage_period, UsageEvent.name == "http_request")
                        .group_by(route)
                        .order_by(func.count().desc())
                        .limit(40)
                    )
                ).all()
            ]
            screen = UsageEvent.properties["screen"].as_string()
            screens = [
                {"screen": name, "visits": total, "active_ms": duration or 0}
                for name, total, duration in (
                    await session.execute(
                        select(screen, func.count(), func.sum(UsageEvent.duration_ms))
                        .where(usage_period, UsageEvent.name == "screen_engagement")
                        .group_by(screen)
                        .order_by(func.count().desc())
                    )
                ).all()
            ]
            education = [
                {"label": level or "Not selected", "count": total}
                for level, total in (
                    await session.execute(
                        select(TelegramUser.education_level, func.count()).group_by(
                            TelegramUser.education_level
                        )
                    )
                ).all()
            ]
            languages = [
                {"label": language or "Unknown", "count": total}
                for language, total in (
                    await session.execute(
                        select(TelegramUser.language_code, func.count())
                        .group_by(TelegramUser.language_code)
                        .order_by(func.count().desc())
                        .limit(20)
                    )
                ).all()
            ]
            stages = case(
                (TelegramUser.registered_at.is_not(None), "Registered"),
                (TelegramUser.phone_shared_at.is_not(None), "Education"),
                (TelegramUser.verified_at.is_not(None), "Phone"),
                (VerificationChallenge.telegram_user_id.is_not(None), "Email code"),
                else_="Student ID",
            )
            stalled = [
                {"stage": stage, "users": total}
                for stage, total in (
                    await session.execute(
                        select(stages, func.count())
                        .select_from(TelegramUser)
                        .outerjoin(VerificationChallenge)
                        .where(
                            TelegramUser.registered_at.is_(None),
                            TelegramUser.last_seen_at < self.clock() - timedelta(hours=1),
                        )
                        .group_by(stages)
                    )
                ).all()
            ]
            email = [
                {"status": name.removeprefix("verification_email_"), "count": total}
                for name, total in (
                    await session.execute(
                        select(RegistrationEvent.event_type, func.count())
                        .where(
                            in_range(RegistrationEvent.occurred_at, start, end),
                            RegistrationEvent.event_type.in_(
                                [
                                    "verification_email_accepted",
                                    "verification_email_failed",
                                    "verification_email_unknown",
                                ]
                            ),
                        )
                        .group_by(RegistrationEvent.event_type)
                    )
                ).all()
            ]
            deliveries = [
                {"status": status, "count": total}
                for status, total in (
                    await session.execute(
                        select(BroadcastRecipient.status, func.count())
                        .where(in_range(BroadcastRecipient.updated_at, start, end))
                        .group_by(BroadcastRecipient.status)
                    )
                ).all()
            ]
            coverage = await session.get(AnalyticsSetting, "started_at")
            return {
                "range": {"start": start.isoformat(), "end": end.isoformat(), "timezone": "UTC"},
                "inventory": inventory,
                "metrics": metrics,
                "registration_funnel": funnel,
                "daily": daily,
                "actions": actions,
                "platforms": platforms,
                "features": features,
                "outcomes": outcomes,
                "issues": issues,
                "performance": performance,
                "screens": screens,
                "education": education,
                "languages": languages,
                "stalled_registration": stalled,
                "email": email,
                "deliveries": deliveries,
                "collection_started_at": coverage.value if coverage else None,
            }

    async def forms(self, start, end, page=0):
        async with self.db.transaction() as session:
            total = await session.scalar(select(func.count()).select_from(Event))
            rows = (
                await session.scalars(
                    select(Event)
                    .order_by(Event.created_at.desc(), Event.id)
                    .offset(page * 20)
                    .limit(20)
                )
            ).all()
            ids = [row.id for row in rows]
            submissions = dict(
                (
                    await session.execute(
                        select(EventRegistration.event_id, func.count())
                        .where(
                            EventRegistration.event_id.in_(ids),
                            in_range(EventRegistration.registered_at, start, end),
                        )
                        .group_by(EventRegistration.event_id)
                    )
                ).all()
            )
            opens = dict(
                (
                    await session.execute(
                        select(UsageEvent.form_id, func.count())
                        .where(
                            UsageEvent.form_id.in_(ids),
                            UsageEvent.name == "form_opened",
                            in_range(UsageEvent.occurred_at, start, end),
                        )
                        .group_by(UsageEvent.form_id)
                    )
                ).all()
            )
            return {
                "total": total,
                "page": page,
                "pages": max(1, (total + 19) // 20),
                "forms": [
                    {
                        "id": row.id,
                        "title": row.title,
                        "anonymous": row.anonymous,
                        "open": row.registration_open,
                        "questions": len(row.questions),
                        "opens": opens.get(row.id, 0),
                        "submissions": submissions.get(row.id, 0),
                    }
                    for row in rows
                ],
            }

    async def form(self, form_id, start, end):
        async with self.db.transaction() as session:
            form = await session.get(Event, form_id)
            if form is None:
                return None
            period = in_range(UsageEvent.occurred_at, start, end)
            base = (UsageEvent.form_id == form_id) & period
            counts = dict(
                (
                    await session.execute(
                        select(UsageEvent.name, func.count()).where(base).group_by(UsageEvent.name)
                    )
                ).all()
            )
            qid = UsageEvent.properties["question_id"].as_string()
            question_rows = (
                await session.execute(
                    select(
                        qid,
                        UsageEvent.name,
                        func.count(distinct(UsageEvent.session_id)),
                        func.avg(UsageEvent.duration_ms),
                        func.count(),
                    )
                    .where(
                        base,
                        UsageEvent.name.in_(
                            ["question_reached", "question_answered", "question_rejected"]
                        ),
                    )
                    .group_by(qid, UsageEvent.name)
                )
            ).all()
            by_question = {
                (key, name): (unique, mean, total)
                for key, name, unique, mean, total in question_rows
            }
            reached_attempts = (
                select(UsageEvent.session_id.label("attempt"), qid.label("question"))
                .where(
                    base, UsageEvent.name == "question_reached", UsageEvent.session_id.is_not(None)
                )
                .distinct()
                .subquery()
            )
            # Use the same reached cohort for the numerator; answers from an earlier
            # period must not produce conversion rates above 100%.
            answered_cohort = {
                key: (count, mean)
                for key, count, mean in (
                    await session.execute(
                        select(
                            reached_attempts.c.question,
                            func.count(distinct(UsageEvent.session_id)),
                            func.avg(UsageEvent.duration_ms),
                        )
                        .select_from(reached_attempts)
                        .outerjoin(
                            UsageEvent,
                            (UsageEvent.form_id == form_id)
                            & (UsageEvent.session_id == reached_attempts.c.attempt)
                            & (qid == reached_attempts.c.question)
                            & (UsageEvent.name == "question_answered")
                            & period,
                        )
                        .group_by(reached_attempts.c.question)
                    )
                ).all()
            }
            stalled = dict(
                (
                    await session.execute(
                        select(EventFormSession.question_index, func.count())
                        .where(
                            EventFormSession.event_id == form_id,
                            EventFormSession.expires_at > self.clock(),
                        )
                        .group_by(EventFormSession.question_index)
                    )
                ).all()
            )
            questions = []
            for index, question in enumerate(form.questions):
                reached = by_question.get((question["id"], "question_reached"), (0, 0, 0))[0]
                answered, mean = answered_cohort.get(question["id"], (0, 0))
                questions.append(
                    {
                        "id": question["id"],
                        "index": index,
                        "label": question["label"],
                        "type": question["type"],
                        "reached": reached,
                        "answered": answered,
                        "not_answered": max(0, reached - answered),
                        "conversion": percentage(answered, reached),
                        "average_ms": round(mean or 0),
                        "rejections": by_question.get(
                            (question["id"], "question_rejected"), (0, 0, 0)
                        )[2],
                        "active_drafts": stalled.get(index, 0),
                    }
                )
            submissions = await session.scalar(
                select(func.count())
                .select_from(EventRegistration)
                .where(
                    EventRegistration.event_id == form_id,
                    in_range(EventRegistration.registered_at, start, end),
                )
            )
            return {
                "id": form.id,
                "title": form.title,
                "anonymous": form.anonymous,
                "open": form.registration_open,
                "counts": counts,
                "submissions": submissions,
                "questions": questions,
            }

    async def users(self, start, end, page=0):
        async with self.db.transaction() as session:
            # An organizer may reopen a saved panel button without messaging the bot.
            # Include authenticated panel activity as well as the historical bot record.
            observed = (
                select(UsageEvent.id)
                .where(
                    UsageEvent.user_id == TelegramUser.id,
                    in_range(UsageEvent.occurred_at, start, end),
                )
                .exists()
            )
            condition = in_range(TelegramUser.last_seen_at, start, end) | observed
            total = await session.scalar(
                select(func.count()).select_from(TelegramUser).where(condition)
            )
            rows = (
                await session.scalars(
                    select(TelegramUser)
                    .where(condition)
                    .order_by(TelegramUser.last_seen_at.desc(), TelegramUser.id)
                    .offset(page * 30)
                    .limit(30)
                )
            ).all()
            return {
                "total": total,
                "page": page,
                "pages": max(1, (total + 29) // 30),
                "users": [
                    {
                        "id": str(row.id),
                        "label": self.user_label(row.id),
                        "created_at": row.created_at.isoformat(),
                        "last_seen_at": row.last_seen_at.isoformat(),
                        "stage": "registered"
                        if row.registered_at
                        else "education"
                        if row.phone_shared_at
                        else "phone"
                        if row.verified_at
                        else "email_or_id",
                    }
                    for row in rows
                ],
            }

    async def timeline(
        self, start, end, *, page=0, user_id=None, name=None, outcome=None, source=None
    ):
        async with self.db.transaction() as session:
            condition = in_range(UsageEvent.occurred_at, start, end)
            for column, value in (
                (UsageEvent.user_id, user_id),
                (UsageEvent.name, name),
                (UsageEvent.outcome, outcome),
                (UsageEvent.source, source),
            ):
                if value is not None:
                    condition &= column == value
            total = await session.scalar(
                select(func.count()).select_from(UsageEvent).where(condition)
            )
            rows = (
                await session.scalars(
                    select(UsageEvent)
                    .where(condition)
                    .order_by(UsageEvent.occurred_at.desc(), UsageEvent.id)
                    .offset(page * 50)
                    .limit(50)
                )
            ).all()
            history = []
            if user_id is not None and page == 0:
                for row in (
                    await session.scalars(
                        select(RegistrationEvent)
                        .where(
                            RegistrationEvent.telegram_user_id == user_id,
                            in_range(RegistrationEvent.occurred_at, start, end),
                        )
                        .order_by(RegistrationEvent.occurred_at.desc())
                        .limit(50)
                    )
                ).all():
                    # In particular, requested_student_id is never included.
                    history.append({"name": row.event_type, "at": row.occurred_at.isoformat()})
            return {
                "total": total,
                "page": page,
                "pages": max(1, (total + 49) // 50),
                "registration_history": history,
                "events": [
                    {
                        "id": row.id,
                        "name": row.name,
                        "source": row.source,
                        "actor": self.user_label(row.user_id)
                        if row.user_id
                        else "Anonymous / system",
                        "form_id": row.form_id,
                        "at": row.occurred_at.isoformat(),
                        "duration_ms": row.duration_ms,
                        "outcome": row.outcome,
                        "properties": properties(row.properties),
                    }
                    for row in rows
                ],
            }

    async def retention(self, start, end):
        async with self.db.transaction() as session:
            result = []
            coverage = await session.get(AnalyticsSetting, "started_at")
            if coverage:
                start = max(start, datetime.fromisoformat(coverage.value))
            # Calendar-day return, not an unqualified "all-time retention" percentage.
            for day in (1, 7, 30):
                eligible = (TelegramUser.created_at >= start) & (
                    TelegramUser.created_at < min(end, self.clock()) - timedelta(days=day + 1)
                )
                if self.db.engine.dialect.name == "sqlite":
                    age = func.julianday(UsageEvent.occurred_at) - func.julianday(
                        TelegramUser.created_at
                    )
                else:
                    age = (
                        func.extract("epoch", UsageEvent.occurred_at - TelegramUser.created_at)
                        / 86400
                    )
                cohort = await session.scalar(
                    select(func.count()).select_from(TelegramUser).where(eligible)
                )
                returned = await session.scalar(
                    select(func.count(distinct(TelegramUser.id)))
                    .join(UsageEvent, UsageEvent.user_id == TelegramUser.id)
                    .where(
                        eligible,
                        age >= day,
                        age < day + 1,
                        UsageEvent.occurred_at < end,
                        UsageEvent.name.in_(["chat_action", "panel_opened", "ui_action"]),
                    )
                )
                result.append(
                    {
                        "day": day,
                        "eligible": cohort,
                        "returned": returned,
                        "rate": percentage(returned, cohort),
                    }
                )
            return result
