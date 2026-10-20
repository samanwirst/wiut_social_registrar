from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path

from aiogram.utils.token import TokenValidationError, validate_token
from dotenv import dotenv_values, set_key
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from registrar.config import ConfigurationError, Settings


@dataclass(frozen=True)
class BotSettings:
    token: str = field(repr=False)
    graph: Settings = field(repr=False)
    database_url: str = field(default="", repr=False)
    verification_secret: str = field(default="", repr=False)
    environment: str = "local"

    @classmethod
    def load(cls, env_file: Path | None = None) -> BotSettings:
        graph = Settings.load(env_file)
        values = {**dotenv_values(graph.env_file, interpolate=False), **os.environ}
        token = str(values.get("TELEGRAM_BOT_TOKEN") or "").strip()
        try:
            validate_token(token)
        except TokenValidationError:
            raise ConfigurationError("Set a valid TELEGRAM_BOT_TOKEN in .env.") from None
        environment = str(values.get("APP_ENV") or "local").strip().lower()
        if environment not in {"local", "production"}:
            raise ConfigurationError("APP_ENV must be local or production.")
        database_url = str(values.get("DATABASE_URL") or "").strip()
        if not database_url:
            if environment == "production":
                password = str(values.get("POSTGRES_PASSWORD") or "")
                if not password:
                    raise ConfigurationError("Production requires DATABASE_URL or POSTGRES_PASSWORD in .env.")
                try:
                    port = int(values.get("POSTGRES_PORT") or "5432")
                except ValueError:
                    raise ConfigurationError("POSTGRES_PORT must be a valid port number.") from None
                database_url = URL.create("postgresql+asyncpg", username=values.get("POSTGRES_USER") or "registrar",
                    password=password, host=values.get("POSTGRES_HOST") or "postgres", port=port,
                    database=values.get("POSTGRES_DB") or "registrar").render_as_string(hide_password=False)
            else:
                database_url = "sqlite+aiosqlite:///" + (graph.env_file.parent / "registrations.sqlite3").as_posix()
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
            raise ConfigurationError("Use a valid SQLite URL locally or a PostgreSQL URL in production.") from None
        secret = str(values.get("BOT_VERIFICATION_SECRET") or "").strip()
        if not secret:
            secret = secrets.token_hex(32)
            descriptor = os.open(graph.env_file, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            os.close(descriptor)
            graph.env_file.chmod(0o600)
            set_key(graph.env_file, "BOT_VERIFICATION_SECRET", secret)
            graph.env_file.chmod(0o600)
        if not re.fullmatch(r"[0-9a-fA-F]{64}", secret):
            raise ConfigurationError("BOT_VERIFICATION_SECRET must contain 64 hexadecimal characters.")
        return cls(token, graph, database_url, secret, environment)
