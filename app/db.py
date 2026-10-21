import os
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import event, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class Database:
    def __init__(self, url: str):
        parsed = make_url(url)
        if parsed.get_backend_name() == "sqlite" and parsed.database not in {None, "", ":memory:"}:
            path = Path(parsed.database)
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            os.close(descriptor)
            path.chmod(0o600)
        self.engine = create_async_engine(
            parsed,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"timeout": 15} if parsed.get_backend_name() == "sqlite" else {},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.insert = sqlite_insert if self.engine.dialect.name == "sqlite" else pg_insert
        if self.engine.dialect.name == "sqlite":

            @event.listens_for(self.engine.sync_engine, "connect")
            def configure(connection, _):
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

    async def migrate(self) -> None:
        def upgrade(connection):
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

        async with self.engine.begin() as connection:
            await connection.run_sync(upgrade)

    @asynccontextmanager
    async def transaction(self, *, write: bool = False):
        async with self.sessions() as session:
            async with session.begin():
                if write and self.engine.dialect.name == "sqlite":
                    await session.execute(text("BEGIN IMMEDIATE"))
                yield session

    async def close(self) -> None:
        await self.engine.dispose()
