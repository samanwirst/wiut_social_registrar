"""Optional server-side image generation credentials from the selected environment."""

import re
from dataclasses import dataclass, field

from registrar.config import ConfigurationError


@dataclass(frozen=True)
class QrImageSettings:
    account_id: str = field(default="", repr=False)
    api_token: str = field(default="", repr=False)

    @property
    def enabled(self):
        return bool(self.account_id and self.api_token)

    @classmethod
    def load(cls, values):
        account = str(values.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
        token = str(values.get("CLOUDFLARE_API_TOKEN") or "").strip()
        if bool(account) != bool(token):
            raise ConfigurationError(
                "Set both CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN, or leave both empty."
            )
        if account and not re.fullmatch(r"[a-fA-F0-9]{32}", account):
            raise ConfigurationError(
                "CLOUDFLARE_ACCOUNT_ID must contain 32 hexadecimal characters."
            )
        return cls(account, token)
