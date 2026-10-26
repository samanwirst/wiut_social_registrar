from __future__ import annotations

from collections.abc import Callable

import msal
import requests

from .config import Settings
from .diagnostics import network_error_kind
from .errors import AuthenticationError

SCOPES = ["User.Read", "User.ReadBasic.All", "Mail.Send"]


class TokenProvider:
    """Microsoft's public-client flow, with its renewable cache kept in .env."""

    def __init__(
        self, settings: Settings, status: Callable[[str], None], *, interactive: bool = True
    ):
        self.settings = settings
        self.status = status
        self.interactive = interactive
        self.cache = msal.SerializableTokenCache()
        self.app = None

    def _initialize(self, reset: bool = False):
        if self.app is not None and not reset:
            return
        if not self.settings.client_id:
            raise AuthenticationError("Set GRAPH_CLIENT_ID and GRAPH_TENANT_ID in .env.")
        self.cache = msal.SerializableTokenCache()
        if not reset:
            try:
                self.cache.deserialize(self.settings.load_cache())
            except (ValueError, TypeError, KeyError):
                raise AuthenticationError(
                    "The token cache is corrupted. Run cli.py --login."
                ) from None
        self.app = msal.PublicClientApplication(
            self.settings.client_id,
            authority=f"https://login.microsoftonline.com/{self.settings.tenant_id}",
            token_cache=self.cache,
            enable_pii_log=False,
            timeout=self.settings.timeout,
        )

    def _save(self):
        if self.cache.has_state_changed:
            self.settings.save_cache(self.cache.serialize())

    def _silent(self, *, refresh: bool = False):
        accounts = self.app.get_accounts(username=self.settings.account or None)
        if len(accounts) > 1:
            raise AuthenticationError(
                "The cache contains multiple accounts. Set GRAPH_ACCOUNT in .env."
            )
        return (
            self.app.acquire_token_silent(SCOPES, account=accounts[0], force_refresh=refresh)
            if accounts
            else None
        )

    def login(self, *, force: bool = False) -> str:
        try:
            self._initialize(reset=force)
            result = None if force else self._silent()
            if not result or "access_token" not in result:
                if not self.interactive:
                    raise AuthenticationError(
                        "Outlook sign-in is required. Run python cli.py --login on the bot host."
                    )
                flow = self.app.initiate_device_flow(scopes=SCOPES)
                if "user_code" not in flow:
                    raise AuthenticationError(
                        "Microsoft did not allow sign-in. Check the application's public client settings."
                    )
                self.status(flow["message"])
                result = self.app.acquire_token_by_device_flow(flow)
            if not result or "access_token" not in result:
                raise AuthenticationError(
                    "Sign-in failed or permissions were not granted. Run cli.py --login again."
                )
            return result["access_token"]
        except requests.RequestException as error:
            raise AuthenticationError(
                "Could not connect to the Microsoft sign-in service.",
                network_error=network_error_kind(error),
                service="sign-in",
            ) from None
        finally:
            self._save()

    def get_token(self, *, refresh: bool = False) -> str:
        if not refresh:
            return self.login()
        try:
            self._initialize()
            result = self._silent(refresh=True)
            if not result or "access_token" not in result:
                raise AuthenticationError("Your Microsoft session has expired. Run cli.py --login.")
            return result["access_token"]
        except requests.RequestException as error:
            raise AuthenticationError(
                "Could not refresh your Microsoft session.",
                network_error=network_error_kind(error),
                service="sign-in",
            ) from None
        finally:
            self._save()
