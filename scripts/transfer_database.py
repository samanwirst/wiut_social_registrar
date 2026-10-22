"""Explicit, private database snapshots for a one-time SQLite to PostgreSQL move."""

import argparse
import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, func, select, text

from app.configuration.database import local_database_url
from app.db import Database
from app.models import Base, UTCDateTime
from config import BotSettings


async def export_database(database):
    snapshot = {"format": 1, "tables": {}}
    # BEGIN IMMEDIATE provides a consistent snapshot on SQLite, even in legacy driver mode.
    async with database.transaction(write=True) as session:
        for table in Base.metadata.sorted_tables:
            rows = (await session.execute(select(table))).mappings().all()
            snapshot["tables"][table.name] = [
                {
                    key: value.isoformat() if isinstance(value, datetime) else value
                    for key, value in row.items()
                }
                for row in rows
            ]
    return snapshot


async def import_database(database, snapshot):
    tables = Base.metadata.sorted_tables
    if snapshot.get("format") != 1 or set(snapshot.get("tables", {})) != {
        table.name for table in tables
    }:
        raise ValueError("Unsupported snapshot schema")
    async with database.transaction(write=True) as session:
        for table in tables:
            if await session.scalar(select(func.count()).select_from(table)):
                raise ValueError("The destination database must be empty")
        for table in tables:
            rows = snapshot["tables"][table.name]
            decoded = []
            for row in rows:
                if set(row) != {column.name for column in table.columns}:
                    raise ValueError("Snapshot columns do not match the application")
                decoded.append(
                    {
                        column.name: datetime.fromisoformat(row[column.name])
                        if row[column.name] is not None
                        and isinstance(column.type, (UTCDateTime, DateTime))
                        else row[column.name]
                        for column in table.columns
                    }
                )
            if decoded:
                await session.execute(table.insert(), decoded)
        if database.engine.dialect.name == "postgresql":
            for table in tables:
                for column in table.primary_key.columns:
                    if column.autoincrement is False or column.foreign_keys:
                        continue
                    sequence = await session.scalar(
                        text("SELECT pg_get_serial_sequence(:table, :column)"),
                        {"table": table.name, "column": column.name},
                    )
                    if sequence:
                        maximum = await session.scalar(select(func.max(column)))
                        await session.execute(
                            text("SELECT setval(:sequence, :value, :called)"),
                            {
                                "sequence": sequence,
                                "value": maximum or 1,
                                "called": maximum is not None,
                            },
                        )


async def transfer(args):
    settings = BotSettings.load(args.env_file)
    database = Database(
        settings.database_url
        or local_database_url(
            settings.graph.env_file, telegram_test=settings.telegram_test_environment
        )
    )
    try:
        if args.action == "export":
            snapshot = await export_database(database)
            descriptor = os.open(args.file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(descriptor, "w") as output:
                json.dump(snapshot, output, ensure_ascii=False)
            print("Private database snapshot created")
        else:
            if settings.environment != "production":
                raise ValueError("CLI imports require an explicit production configuration")
            await database.migrate()
            await import_database(database, json.loads(args.file.read_text()))
            print("Database imported into the empty production database")
    finally:
        await database.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("export", "import"))
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        asyncio.run(transfer(args))
        return 0
    except Exception as error:
        # Snapshot content, database parameters, and MSAL data must never enter logs.
        print("Database transfer failed (" + type(error).__name__ + ")")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
