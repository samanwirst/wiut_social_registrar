from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from aiogram.exceptions import TelegramAPIError
from sqlalchemy.exc import SQLAlchemyError

from app.bot import BotApp
from config import BotSettings
from registrar.config import ConfigurationError
from registrar.errors import GraphError

logger = logging.getLogger(__name__)


async def run(settings: BotSettings, *, check: bool = False) -> None:
    app = BotApp(settings)
    try:
        logger.info("Using Telegram %s environment.", "TEST" if settings.telegram_test_environment else "production")
        me = await app.check_connection()
        logger.info("Telegram @%s, Outlook, and the database are ready.", me.username)
        if not check:
            await app.run()
    finally:
        await app.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Telegram student registration and profile lookup.")
    parser.add_argument("--env-file", type=Path, help="Path to .env (defaults to the project directory).")
    parser.add_argument("--check", action="store_true", help="Check Telegram and Outlook connections, then exit.")
    parser.add_argument("--debug", action="store_true", help="Show Microsoft Graph request diagnostics.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        settings = BotSettings.load(args.env_file)
        logging.getLogger("registrar").setLevel(logging.DEBUG if args.debug or settings.graph.debug else logging.WARNING)
        asyncio.run(run(settings, check=args.check))
        return 0
    except KeyboardInterrupt:
        return 130
    except (ConfigurationError, GraphError) as error:
        logger.error("%s", error)
    except TelegramAPIError as error:
        # Transport errors may include a URL containing the bot token.
        logger.error("Telegram connection failed (%s). Check the token and network connection.", type(error).__name__)
    except SQLAlchemyError as error:
        logger.error("Database operation failed (%s). Check database configuration and migrations.", type(error).__name__)
    except OSError:
        logger.error("Could not access the configuration or network. Check file permissions and connectivity.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
