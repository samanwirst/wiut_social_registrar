from __future__ import annotations

import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

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
    mini_app_url: str = ""
    mini_app_host: str = "127.0.0.1"
    mini_app_port: int = 8080
    telegram_test_environment: bool = False
    mini_app_tls_cert_file: Path | None = None
    mini_app_tls_key_file: Path | None = None

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
        telegram_test = str(values.get("TELEGRAM_TEST_ENVIRONMENT") or "false").strip().lower()
        if telegram_test not in {"true", "false"}:
            raise ConfigurationError("TELEGRAM_TEST_ENVIRONMENT must be true or false.")
        telegram_test = telegram_test == "true"
        if telegram_test and environment != "local":
            raise ConfigurationError("TELEGRAM_TEST_ENVIRONMENT is available only with APP_ENV=local.")
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
                filename = "registrations.telegram-test.sqlite3" if telegram_test else "registrations.sqlite3"
                database_url = "sqlite+aiosqlite:///" + (graph.env_file.parent / filename).as_posix()
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
        mini_app_url = str(values.get("MINI_APP_URL") or "").strip().rstrip("/")
        if mini_app_url:
            try:
                parsed = urlsplit(mini_app_url)
                allowed_schemes = {"https", "http"} if telegram_test else {"https"}
                if (parsed.scheme not in allowed_schemes or not parsed.hostname or parsed.username or parsed.password
                        or parsed.path or parsed.query or parsed.fragment or parsed.port == 0):
                    raise ValueError
            except ValueError:
                raise ConfigurationError("MINI_APP_URL must be an HTTPS origin. HTTP is allowed only with TELEGRAM_TEST_ENVIRONMENT=true.") from None
        cert_value = str(values.get("MINI_APP_TLS_CERT_FILE") or "").strip()
        key_value = str(values.get("MINI_APP_TLS_KEY_FILE") or "").strip()
        if bool(cert_value) != bool(key_value):
            raise ConfigurationError("Set both MINI_APP_TLS_CERT_FILE and MINI_APP_TLS_KEY_FILE, or leave both empty.")
        if cert_value and (not mini_app_url or urlsplit(mini_app_url).scheme != "https"):
            raise ConfigurationError("Direct TLS requires an HTTPS MINI_APP_URL.")
        cert_file = (graph.env_file.parent / cert_value).resolve() if cert_value else None
        key_file = (graph.env_file.parent / key_value).resolve() if key_value else None
        try:
            mini_app_port = int(values.get("MINI_APP_PORT") or "8080")
            if not 1 <= mini_app_port <= 65535:
                raise ValueError
        except ValueError:
            raise ConfigurationError("MINI_APP_PORT must be a valid port number.") from None
        return cls(token, graph, database_url, secret, environment, mini_app_url,
                   str(values.get("MINI_APP_HOST") or "127.0.0.1").strip(), mini_app_port,
                   telegram_test, cert_file, key_file)
