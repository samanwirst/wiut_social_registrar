import json
from datetime import datetime, timezone

import pytest
from aiogram.types import User
from sqlalchemy import delete

from app.db import Database
from app.models import Base
from app.repositories import RegistrationRepository
from registrar.models import Student
from scripts.transfer_database import export_database, import_database
from tests.helpers import complete_student_registration


@pytest.mark.asyncio
async def test_database_transfer_preserves_profiles_and_refuses_to_overwrite_existing_data(
    repository, tmp_path
):
    source = Database("sqlite+aiosqlite:///" + str(tmp_path / "source.sqlite3"))
    await source.migrate()
    try:
        source_repository = RegistrationRepository(
            source, "ab" * 32, clock=lambda: datetime(2026, 10, 22, tzinfo=timezone.utc)
        )
        student = Student(
            "00000001",
            "Synthetic <Student>",
            "student@example.test",
            account="00000001@example.test",
        )
        await source_repository.touch_user(User(id=100, is_bot=False, first_name="Synthetic"))
        await complete_student_registration(
            source_repository, 100, student, education_level="Level 4", code="123456"
        )
        snapshot = json.loads(json.dumps(await export_database(source)))
        async with repository.db.transaction(write=True) as session:
            for table in reversed(Base.metadata.sorted_tables):
                await session.execute(delete(table))
        await import_database(repository.db, snapshot)
        restored = await repository.verified(100)
        assert restored.student_id == student.student_id and restored.email == student.email
        assert restored.name == student.name
        with pytest.raises(ValueError, match="must be empty"):
            await import_database(repository.db, snapshot)
        assert (await repository.verified(100)).email == student.email
        # In PostgreSQL explicit imported IDs must not collide with subsequent sequence values.
        await repository.touch_user(User(id=300, is_bot=False, first_name="New student"))
        await repository.reserve_code(
            300,
            Student("00000003", "New", "new@example.test", account="00000003@example.test"),
            "654321",
        )
    finally:
        await source.close()
