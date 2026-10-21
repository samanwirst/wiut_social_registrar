from pathlib import Path

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from registrar.config import ConfigurationError


def local_database_url(env_file: Path, *, telegram_test: bool = False) -> str:
    filename = "registrations.telegram-test.sqlite3" if telegram_test else "registrations.sqlite3"
    return "sqlite+aiosqlite:///" + (env_file.parent / filename).as_posix()


def load_database_url(values, env_file: Path, environment: str, telegram_test: bool) -> str:
    database_url = str(values.get("DATABASE_URL") or "").strip()
    if not database_url:
        if environment == "production":
            password = str(values.get("POSTGRES_PASSWORD") or "")
            if not password:
                raise ConfigurationError(
                    "Production requires DATABASE_URL or POSTGRES_PASSWORD in .env."
                )
            try:
                port = int(values.get("POSTGRES_PORT") or "5432")
            except ValueError:
                raise ConfigurationError("POSTGRES_PORT must be a valid port number.") from None
            database_url = URL.create(
                "postgresql+asyncpg",
                username=values.get("POSTGRES_USER") or "registrar",
                password=password,
                host=values.get("POSTGRES_HOST") or "postgres",
                port=port,
                database=values.get("POSTGRES_DB") or "registrar",
            ).render_as_string(hide_password=False)
        else:
            database_url = local_database_url(env_file, telegram_test=telegram_test)
    try:
        url = make_url(database_url)
        if url.drivername == "sqlite":
            url = url.set(drivername="sqlite+aiosqlite")
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+asyncpg")
        if url.drivername not in {"sqlite+aiosqlite", "postgresql+asyncpg"}:
            raise ValueError
        if environment == "production" and url.get_backend_name() != "postgresql":
            raise ValueError
        database_url = url.render_as_string(hide_password=False)
    except (ValueError, ArgumentError):
        raise ConfigurationError(
            "Use a valid SQLite URL locally or a PostgreSQL URL in production."
        ) from None
    return database_url
