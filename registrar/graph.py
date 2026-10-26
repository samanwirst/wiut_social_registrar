from __future__ import annotations

import logging
import time
from collections.abc import Callable
from urllib.parse import quote

import requests

from .auth import TokenProvider
from .config import Settings
from .errors import AuthenticationError, GraphError, SendStatusUnknown
from .models import EMAIL_PATTERN, Student, validate_message, validate_student_id
from .transport import GraphTransport

logger = logging.getLogger("registrar.graph")
PROFILE_FIELDS = "id,displayName,givenName,surname,mail,userPrincipalName"


class GraphClient:
    def __init__(
        self, settings: Settings, status: Callable[[str], None] = print, *, auth=None, session=None
    ):
        self.settings = settings
        self.auth = auth or TokenProvider(settings, status)
        self.session = session or requests.Session()
        self.transport = GraphTransport(settings, self.auth, self.session)
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

    def profile(self, *, refresh: bool = False) -> dict:
        if self._profile is None or refresh:
            response = self.transport.request("GET", "/me", params={"$select": PROFILE_FIELDS})
            data = self.transport.data(response)
            upn, mail = data.get("userPrincipalName"), data.get("mail")
            if not isinstance(upn, str) or not EMAIL_PATTERN.fullmatch(upn):
                raise GraphError("Microsoft Graph did not return your account identifier.")
            if mail and (not isinstance(mail, str) or not EMAIL_PATTERN.fullmatch(mail)):
                raise GraphError(
                    "Microsoft Graph returned an invalid email address for your account."
                )
            if self.settings.account and self.settings.account.casefold() not in {
                upn.casefold(),
                str(mail).casefold(),
            }:
                raise AuthenticationError(
                    "You are signed in to a different account. Check GRAPH_ACCOUNT and run --login."
                )
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
        response = self.transport.request(
            "GET", "/users/" + quote(account, safe=""), params={"$select": PROFILE_FIELDS}
        )
        if response.status_code == 404:
            return None
        data = self.transport.data(response)
        upn = data.get("userPrincipalName")
        email = data.get("mail") or upn
        if not isinstance(upn, str) or upn.casefold() != account.casefold():
            raise GraphError("Microsoft Graph returned a different student identifier.")
        if not isinstance(email, str) or not EMAIL_PATTERN.fullmatch(email):
            raise GraphError("Microsoft Graph did not return a valid student email address.")
        student = Student(
            student_id,
            data.get("displayName") or "",
            email,
            account=upn,
            email_addresses=list(dict.fromkeys([email, upn])),
            source="microsoft_graph",
            graph_id=data.get("id") or "",
            given_name=data.get("givenName") or "",
            surname=data.get("surname") or "",
        )
        if len(self._students) >= 256:
            self._students.pop(next(iter(self._students)))
        self._students[student_id] = (time.monotonic() + self.settings.cache_ttl, student)
        return student

    def mail_preview(self, student: Student, subject: str, body: str) -> dict:
        validate_message(subject, body)
        if not EMAIL_PATTERN.fullmatch(student.email):
            raise ValueError("Invalid recipient email address.")
        return {
            "from": self.sender_email,
            "to": student.email,
            "subject": subject.strip(),
            "body": body,
        }

    def send_email(self, student: Student, subject: str, body: str) -> None:
        message = self.mail_preview(student, subject, body)
        response = self.transport.request(
            "POST",
            "/me/sendMail",
            payload={
                "message": {
                    "subject": message["subject"],
                    "body": {"contentType": "Text", "content": message["body"]},
                    "toRecipients": [{"emailAddress": {"address": message["to"]}}],
                }
            },
        )
        if response.status_code != 202:
            raise SendStatusUnknown(
                "Microsoft did not confirm acceptance of the email. Check Sent Items before retrying.",
                status_code=response.status_code,
            )
