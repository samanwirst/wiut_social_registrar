from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from .environment import read_environment, save_environment_value

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ConfigurationError(ValueError):
    pass


@dataclass
class Settings:
    env_file: Path
    client_id: str = ""
    tenant_id: str = "organizations"
    account: str = ""
    student_domain: str = ""
    timeout: float = 15
    cache_ttl: float = 300
    debug: bool = False
    token_cache_b64: str = field(default="", repr=False)

    @classmethod
    def load(cls, env_file: Path | None = None) -> Settings:
        path = (env_file or PROJECT_ROOT / ".env").expanduser().resolve()
        values = read_environment(path)

        def value(key: str, default: str = "") -> str:
            return str(values.get(key) or default).strip()

        def seconds(key: str, default: str) -> float:
            try:
                result = float(value(key, default))
                if not 0 < result <= 3600:
                    raise ValueError
                return result
            except ValueError:
                raise ConfigurationError(
                    f"{key}: specify a number of seconds greater than 0 and at most 3600."
                ) from None

        client_id = value("GRAPH_CLIENT_ID")
        tenant_id = value("GRAPH_TENANT_ID", "organizations")
        try:
            if client_id:
                UUID(client_id)
            if tenant_id != "organizations":
                UUID(tenant_id)
        except ValueError:
            raise ConfigurationError(
                "GRAPH_CLIENT_ID and GRAPH_TENANT_ID must contain valid Microsoft Entra IDs."
            ) from None
        domain = value("GRAPH_STUDENT_DOMAIN")
        if domain and not re.fullmatch(r"[a-zA-Z0-9-]+(?:[.][a-zA-Z0-9-]+)+", domain):
            raise ConfigurationError(
                "GRAPH_STUDENT_DOMAIN must be a domain name, such as university.edu."
            )
        debug = value("GRAPH_DEBUG", "false").lower()
        if debug not in {"true", "false", "1", "0"}:
            raise ConfigurationError("GRAPH_DEBUG: use true or false.")
        return cls(
            env_file=path,
            client_id=client_id,
            tenant_id=tenant_id,
            account=value("GRAPH_ACCOUNT"),
            student_domain=domain,
            timeout=seconds("GRAPH_TIMEOUT_SECONDS", "15"),
            cache_ttl=seconds("GRAPH_CACHE_TTL_SECONDS", "300"),
            debug=debug in {"true", "1"},
            token_cache_b64=value("GRAPH_TOKEN_CACHE_B64"),
        )

    def load_cache(self) -> str:
        if not self.token_cache_b64:
            return "{}"
        try:
            serialized = base64.b64decode(self.token_cache_b64, validate=True).decode()
            if not isinstance(json.loads(serialized), dict):
                raise ValueError
            return serialized
        except (ValueError, TypeError):
            raise ConfigurationError(
                "The token cache in .env is corrupted. Run cli.py --login."
            ) from None

    def save_cache(self, serialized: str | None) -> None:
        encoded = base64.b64encode(serialized.encode()).decode() if serialized else ""
        save_environment_value(self.env_file, "GRAPH_TOKEN_CACHE_B64", encoded)
        self.token_cache_b64 = encoded
