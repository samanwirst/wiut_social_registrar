"""Synchronize directory fields within the caller's transaction."""

from app.models import OutlookProfile


async def upsert_outlook_profile(session, insert, student, now):
    data = dict(
        student_id=student.student_id,
        graph_id=student.graph_id or None,
        account=student.account,
        display_name=student.name or None,
        given_name=student.given_name or None,
        surname=student.surname or None,
        email=student.email,
        email_addresses=student.email_addresses,
        updated_at=now,
    )
    stmt = insert(OutlookProfile).values(**data, first_seen_at=now)
    result = await session.execute(
        stmt.on_conflict_do_update(index_elements=[OutlookProfile.account], set_=data).returning(
            OutlookProfile.id
        )
    )
    return result.scalar_one()
