"""Microsoft Graph HTTP policy: bounded read retries and safe submission failures."""

import logging
import re
import time

import requests

from .diagnostics import network_error_kind
from .errors import GraphError, SendStatusUnknown

logger = logging.getLogger("registrar.graph")
GRAPH_URL = "https://graph.microsoft.com/v1.0"


class GraphTransport:
    def __init__(self, settings, auth, session):
        self.settings, self.auth, self.session = settings, auth, session

    def request(self, method: str, path: str, *, params=None, payload=None):
        refresh = False
        for attempt in range(3):
            token = self.auth.get_token(refresh=refresh)
            start = time.monotonic()
            logger.debug("SENT %s %s", method, path)
            try:
                response = self.session.request(
                    method,
                    GRAPH_URL + path,
                    params=params,
                    json=payload,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=(5, self.settings.timeout),
                    allow_redirects=False,
                )
            except requests.RequestException as error:
                network_error = network_error_kind(error)
                if method == "POST":
                    raise SendStatusUnknown(
                        "Could not confirm submission. Check Sent Items before retrying: "
                        "Microsoft may have accepted the email.",
                        network_error=network_error,
                    ) from None
                raise GraphError(
                    "Could not connect to Microsoft Graph. Try the request again.",
                    network_error=network_error,
                ) from None
            logger.debug(
                "%s %s -> HTTP %s (%d ms)",
                method,
                path,
                response.status_code,
                (time.monotonic() - start) * 1000,
            )
            if response.status_code == 401 and not refresh and attempt < 2:
                refresh = True
                continue
            if method == "GET" and response.status_code in {429, 503} and attempt < 2:
                try:
                    delay = float(response.headers.get("Retry-After", "1"))
                except ValueError:
                    delay = 1
                if 0 <= delay <= 10:
                    logger.debug("RETRY GET after %.1f seconds", delay)
                    time.sleep(delay)
                    continue
            if response.status_code == 404 and method == "GET":
                return response
            if method == "POST" and (response.status_code >= 500 or response.status_code == 408):
                raise SendStatusUnknown(
                    f"Microsoft Graph: HTTP {response.status_code}. Submission status is unknown. "
                    "Check Sent Items before retrying.",
                    status_code=response.status_code,
                )
            if not 200 <= response.status_code < 300:
                code = ""
                try:
                    data = response.json()
                    error = data.get("error", {}) if isinstance(data, dict) else {}
                    candidate = error.get("code", "") if isinstance(error, dict) else ""
                    if isinstance(candidate, str) and re.fullmatch(r"[\w.-]{1,100}", candidate):
                        code = f" ({candidate})"
                except ValueError:
                    pass
                raise GraphError(
                    f"Microsoft Graph: HTTP {response.status_code}{code}.",
                    status_code=response.status_code,
                )
            return response
        raise GraphError("Microsoft Graph did not accept the request.")

    @staticmethod
    def data(response) -> dict:
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except ValueError:
            raise GraphError("Microsoft Graph returned an unexpected response format.") from None
