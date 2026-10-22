import argparse
import asyncio
from pathlib import Path

from app.db import Database
from config import BotSettings


async def migrate(settings):
    database = Database(settings.database_url)
    try:
        await database.migrate()
    finally:
        await database.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply database migrations.")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args()
    asyncio.run(migrate(BotSettings.load(args.env_file)))
