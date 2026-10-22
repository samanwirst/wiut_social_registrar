import os
from datetime import datetime, timezone

import pytest_asyncio
from aiogram.types import User
from sqlalchemy import text
from sqlalchemy.engine import make_url

from app.db import Database
from app.repositories import RegistrationRepository


@pytest_asyncio.fixture(
    params=["sqlite"] + (["postgresql"] if os.environ.get("TEST_DATABASE_URL") else [])
)
async def repository(request, tmp_path):
    url = (
        os.environ["TEST_DATABASE_URL"]
        if request.param == "postgresql"
        else "sqlite+aiosqlite:///" + str(tmp_path / "db.sqlite3")
    )
    if request.param == "postgresql":
        assert make_url(url).database.endswith("_test"), "Use a dedicated database ending in _test."
    db = Database(url)
    await db.migrate()
    if request.param == "postgresql":
        async with db.engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE pending_event_registrations, event_registrations, events, "
                    "registration_events, verification_challenges, telegram_users, "
                    "outlook_profiles RESTART IDENTITY CASCADE"
                )
            )
    now = [datetime(2026, 10, 21, tzinfo=timezone.utc)]
    repo = RegistrationRepository(db, "ab" * 32, clock=lambda: now[0])
    repo.test_clock = now
    for user_id in (100, 200):
        await repo.touch_user(
            User(
                id=user_id,
                is_bot=False,
                first_name="First",
                last_name="Last",
                username=f"user_{user_id}",
                language_code="en",
                is_premium=True,
            )
        )
    try:
        yield repo
    finally:
        await db.close()
