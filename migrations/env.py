import asyncio
from pathlib import Path

from alembic import context

from app.models import Base


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def connect():
    from app.db import Database
    from config import BotSettings
    path = context.get_x_argument(as_dictionary=True).get("env_file")
    database = Database(BotSettings.load(Path(path) if path else None).database_url)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(run)
    finally:
        await database.close()


connection = context.config.attributes.get("connection")
if connection is not None:
    run(connection)
else:
    asyncio.run(connect())
