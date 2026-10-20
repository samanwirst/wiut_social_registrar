from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from urllib.parse import quote

import requests

from .auth import TokenProvider
from .config import Settings
from .errors import AuthenticationError, GraphError, SendStatusUnknown
from .models import EMAIL_PATTERN, Student, validate_message, validate_student_id

logger = logging.getLogger("registrar.graph")
GRAPH_URL = "https://graph.microsoft.com/v1.0"
PROFILE_FIELDS = "id,displayName,givenName,surname,mail,userPrincipalName"


class GraphClient:
    def __init__(self, settings: Settings, status: Callable[[str], None] = print, *, auth=None, session=None):
        self.settings = settings
        self.auth = auth or TokenProvider(settings, status)
        self.session = session or requests.Session()
        self._profile = None
        self._students: dict[str, tuple[float, Student]] = {}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.session.close()

    def login(self, *, force=False):
        self.auth.login(force=force)
        self._profile = None
        self._students.clear()
        return self.profile()

    def _request(self, method: str, path: str, *, params=None, payload=None):
        refresh = False
        for attempt in range(3):
            token = self.auth.get_token(refresh=refresh)
            start = time.monotonic()
            logger.debug("SENT %s %s", method, path)
            try:
                response = self.session.request(
                    method, GRAPH_URL + path, params=params, json=payload,
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=(5, self.settings.timeout), allow_redirects=False,
                )
            except requests.RequestException:
                if method == "POST":
                    raise SendStatusUnknown(
                        "Could not confirm submission. Check Sent Items before retrying: "
                        "Microsoft may have accepted the email."
                    ) from None
                raise GraphError("Could not connect to Microsoft Graph. Try the request again.") from None
            logger.debug("%s %s -> HTTP %s (%d ms)", method, path, response.status_code, (time.monotonic() - start) * 1000)
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
                    "Check Sent Items before retrying."
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
                raise GraphError(f"Microsoft Graph: HTTP {response.status_code}{code}.")
            return response
        raise GraphError("Microsoft Graph did not accept the request.")

    @staticmethod
    def _data(response) -> dict:
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            return data
        except ValueError:
            raise GraphError("Microsoft Graph returned an unexpected response format.") from None

    def profile(self) -> dict:
        if self._profile is None:
            response = self._request("GET", "/me", params={"$select": PROFILE_FIELDS})
            data = self._data(response)
            upn, mail = data.get("userPrincipalName"), data.get("mail")
            if not isinstance(upn, str) or not EMAIL_PATTERN.fullmatch(upn):
                raise GraphError("Microsoft Graph did not return your account identifier.")
            if mail and (not isinstance(mail, str) or not EMAIL_PATTERN.fullmatch(mail)):
                raise GraphError("Microsoft Graph returned an invalid email address for your account.")
            if self.settings.account and self.settings.account.casefold() not in {upn.casefold(), str(mail).casefold()}:
                raise AuthenticationError("You are signed in to a different account. Check GRAPH_ACCOUNT and run --login.")
            self._profile = data
        return self._profile

    @property
    def sender_email(self) -> str:
        profile = self.profile()
        return profile.get("mail") or profile["userPrincipalName"]

    def find_student(self, student_id: str, *, refresh: bool = False) -> Student | None:
        student_id = validate_student_id(student_id)
        cached = self._students.get(student_id)
        if not refresh and cached and time.monotonic() < cached[0]:
            logger.debug("CACHE student_id=%s", student_id)
            return cached[1]
        self._students.pop(student_id, None)
        profile = self.profile()
        domain = self.settings.student_domain or profile["userPrincipalName"].split("@", 1)[1]
        account = f"{student_id}@{domain}"
        response = self._request("GET", "/users/" + quote(account, safe=""), params={"$select": PROFILE_FIELDS})
        if response.status_code == 404:
            return None
        data = self._data(response)
        upn = data.get("userPrincipalName")
        email = data.get("mail") or upn
        if not isinstance(upn, str) or upn.casefold() != account.casefold():
            raise GraphError("Microsoft Graph returned a different student identifier.")
        if not isinstance(email, str) or not EMAIL_PATTERN.fullmatch(email):
            raise GraphError("Microsoft Graph did not return a valid student email address.")
        student = Student(student_id, data.get("displayName") or "", email, account=upn,
                          email_addresses=list(dict.fromkeys([email, upn])), source="microsoft_graph",
                          graph_id=data.get("id") or "", given_name=data.get("givenName") or "",
                          surname=data.get("surname") or "")
        if len(self._students) >= 256:
            self._students.pop(next(iter(self._students)))
        self._students[student_id] = (time.monotonic() + self.settings.cache_ttl, student)
        return student

    def mail_preview(self, student: Student, subject: str, body: str) -> dict:
        validate_message(subject, body)
        if not EMAIL_PATTERN.fullmatch(student.email):
            raise ValueError("Invalid recipient email address.")
        return {"from": self.sender_email, "to": student.email, "subject": subject.strip(), "body": body}

    def send_email(self, student: Student, subject: str, body: str) -> None:
        message = self.mail_preview(student, subject, body)
        response = self._request("POST", "/me/sendMail", payload={"message": {
            "subject": message["subject"],
            "body": {"contentType": "Text", "content": message["body"]},
            "toRecipients": [{"emailAddress": {"address": message["to"]}}],
        }})
        if response.status_code != 202:
            raise SendStatusUnknown("Microsoft did not confirm acceptance of the email. Check Sent Items before retrying.")
