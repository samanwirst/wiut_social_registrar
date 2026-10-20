import json
from unittest.mock import Mock

import pytest
import requests

from registrar.config import Settings
from registrar.errors import AuthenticationError, GraphError, SendStatusUnknown
from registrar.graph import GraphClient
from registrar.models import Student, validate_student_id

ME = {"displayName": "Sender", "mail": "sender@students.example.test", "userPrincipalName": "00000002@example.test"}
PERSON = {"displayName": "Student", "mail": "student@students.example.test", "userPrincipalName": "00000001@example.test"}


def response(status=200, data=None, headers=None):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    result.headers.update(headers or {})
    return result


@pytest.fixture
def client(tmp_path):
    auth = Mock()
    auth.get_token.return_value = "private-access-token"
    session = Mock()
    session.request.side_effect = [response(data=ME), response(data=PERSON)]
    return GraphClient(Settings(tmp_path / ".env"), auth=auth, session=session)


def test_exact_lookup_caches_profile_and_student_and_reuses_session(client, caplog):
    with caplog.at_level("DEBUG", logger="registrar.graph"):
        student = client.find_student(" 00000001 ")
        assert client.find_student("00000001") is student
    assert student.to_dict() == {
        "student_id": "00000001", "name": "Student", "email": "student@students.example.test",
        "account": "00000001@example.test", "email_addresses": ["student@students.example.test", "00000001@example.test"],
        "source": "microsoft_graph",
    }
    calls = client.session.request.call_args_list
    assert len(calls) == 2
    assert calls[0].args == ("GET", "https://graph.microsoft.com/v1.0/me")
    assert calls[1].args == ("GET", "https://graph.microsoft.com/v1.0/users/00000001%40example.test")
    assert calls[1].kwargs["params"] == {"$select": "displayName,mail,userPrincipalName"}
    assert calls[1].kwargs["allow_redirects"] is False
    assert calls[1].kwargs["timeout"] == (5, 15)
    assert "SENT GET" in caplog.text and "HTTP 200" in caplog.text and "CACHE" in caplog.text
    assert "private-access-token" not in caplog.text


@pytest.mark.parametrize("fresh", [True, False])
def test_refresh_and_expiry_bypass_student_cache(client, monkeypatch, fresh):
    client.find_student("00000001")
    client.session.request.side_effect = [response(data={**PERSON, "mail": "updated@example.test"})]
    if not fresh:
        client._students["00000001"] = (0, client._students["00000001"][1])
    assert client.find_student("00000001", refresh=fresh).email == "updated@example.test"
    assert client.session.request.call_count == 3


def test_not_found_does_not_cache_old_student(client):
    client.find_student("00000001")
    client.session.request.side_effect = [response(404), response(404)]
    assert client.find_student("00000001", refresh=True) is None
    assert client.find_student("00000001") is None


@pytest.mark.parametrize("status", [403, 500])
def test_lookup_error_is_not_not_found(client, status):
    client.session.request.side_effect = [response(data=ME), response(status, {"error": {"code": "Denied", "message": "private-response"}})]
    with pytest.raises(GraphError, match=f"HTTP {status}") as error:
        client.find_student("00000001")
    assert "private-response" not in str(error.value)


@pytest.mark.parametrize("data", [[], {"userPrincipalName": "00000003@example.test"}, {**PERSON, "mail": "invalid"}])
def test_malformed_or_wrong_student_never_used(client, data):
    client.session.request.side_effect = [response(data=ME), response(data=data)]
    with pytest.raises(GraphError):
        client.find_student("00000001")


def test_account_check_applies_with_domain_override(client):
    client.settings.account = "other@example.test"
    client.settings.student_domain = "another.example.test"
    with pytest.raises(AuthenticationError):
        client.find_student("00000001")
    assert client.session.request.call_count == 1


def test_upn_used_when_mail_missing(client):
    client.session.request.side_effect = [response(data=ME), response(data={**PERSON, "mail": None})]
    assert client.find_student("00000001").email == PERSON["userPrincipalName"]


def test_401_refreshes_once(client):
    client.session.request.side_effect = [response(401), response(data=ME), response(data=PERSON)]
    assert client.find_student("00000001").name == "Student"
    assert [c.kwargs["refresh"] for c in client.auth.get_token.call_args_list] == [False, True, False]


def test_throttled_read_obeys_retry_after(client, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr("registrar.graph.time.sleep", sleep)
    client.session.request.side_effect = [response(429, headers={"Retry-After": "2"}), response(data=ME), response(data=PERSON)]
    assert client.find_student("00000001")
    sleep.assert_called_once_with(2)


def test_mail_preview_never_submits_and_send_uses_current_account(client):
    student = client.find_student("00000001")
    preview = client.mail_preview(student, " Subject ", "Body\nSecond line")
    assert preview == {"from": ME["mail"], "to": PERSON["mail"], "subject": "Subject", "body": "Body\nSecond line"}
    assert client.session.request.call_count == 2
    client.session.request.side_effect = [response(202)]
    client.send_email(student, " Subject ", "Body\nSecond line")
    sent = client.session.request.call_args
    assert sent.args == ("POST", "https://graph.microsoft.com/v1.0/me/sendMail")
    assert sent.kwargs["json"] == {"message": {
        "subject": "Subject", "body": {"contentType": "Text", "content": "Body\nSecond line"},
        "toRecipients": [{"emailAddress": {"address": PERSON["mail"]}}],
    }}


@pytest.mark.parametrize("failure", [requests.Timeout("private-token"), response(503), response(408), response(200)])
def test_ambiguous_send_is_never_retried(client, failure):
    student = client.find_student("00000001")
    client.session.request.reset_mock()
    client.session.request.side_effect = [failure]
    with pytest.raises(SendStatusUnknown) as error:
        client.send_email(student, "Subject", "Body")
    assert client.session.request.call_count == 1
    assert "private-token" not in str(error.value)


@pytest.mark.parametrize("status", [403, 429])
def test_rejected_send_is_not_retried(client, status):
    student = client.find_student("00000001")
    client.session.request.reset_mock()
    client.session.request.side_effect = [response(status)]
    with pytest.raises(GraphError, match=f"HTTP {status}"):
        client.send_email(student, "Subject", "Body")
    assert client.session.request.call_count == 1


@pytest.mark.parametrize("subject,body", [("", "Body"), ("Title\nBcc: other", "Body"), ("Title", "  ")])
def test_invalid_mail_does_not_connect(client, subject, body):
    with pytest.raises(ValueError):
        client.send_email(Student("1", "Student", "student@example.test"), subject, body)
    client.session.request.assert_not_called()


@pytest.mark.parametrize("value", ["", "test", "123 OR 456", "123@domain.test", "١٢٣", "1" * 33])
def test_invalid_id_does_not_connect(client, value):
    with pytest.raises(ValueError):
        client.find_student(value)
    client.session.request.assert_not_called()


def test_leading_zeroes():
    assert validate_student_id(" 00000001 ") == "00000001"
