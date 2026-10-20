import io
import json
from unittest.mock import Mock

import pytest

import cli
from registrar.errors import GraphError
from registrar.models import Student


@pytest.fixture
def client(monkeypatch):
    instance = Mock()
    instance.find_student.side_effect = lambda sid, **_: Student(sid, "Student", "student@example.test")
    instance.mail_preview.return_value = {"from": "sender@example.test", "to": "student@example.test", "subject": "Title", "body": "Body"}
    factory = Mock()
    factory.return_value.__enter__ = Mock(return_value=instance)
    factory.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(cli, "GraphClient", factory)
    return instance


@pytest.mark.parametrize("text", ["", "\n", "bad-id\n\n"])
def test_empty_console_does_not_authenticate(monkeypatch, capsys, tmp_path, client, text):
    monkeypatch.setattr("sys.stdin", io.StringIO(text))
    assert cli.main(["--env-file", str(tmp_path / ".env")]) == 0
    client.find_student.assert_not_called()
    client.login.assert_not_called()
    assert "Enter a student ID" in capsys.readouterr().out


def test_console_recovers_after_lookup_failure(monkeypatch, capsys, tmp_path, client):
    client.find_student.side_effect = [GraphError("Connection error"), Student("2", "Second Student", "second@example.test")]
    monkeypatch.setattr("sys.stdin", io.StringIO("1\n2\n\n"))
    assert cli.main(["--env-file", str(tmp_path / ".env")]) == 0
    captured = capsys.readouterr()
    assert "Second Student" in captured.out
    assert "Connection error" in captured.err
    assert client.find_student.call_count == 2


@pytest.mark.parametrize("found,code", [(True, 0), (False, 1)])
def test_json_stdout_is_machine_readable(capsys, tmp_path, client, found, code):
    client.find_student.side_effect = None
    client.find_student.return_value = Student("00000001", "Student", "student@example.test") if found else None
    assert cli.main(["--id", "00000001", "--json", "--env-file", str(tmp_path / ".env")]) == code
    result = json.loads(capsys.readouterr().out)
    assert (result["student_id"] if result else None) == ("00000001" if found else None)
    client.send_email.assert_not_called()


@pytest.mark.parametrize("send", [False, True])
def test_mail_preview_is_default_and_send_is_explicit(capsys, tmp_path, client, send):
    body_file = tmp_path / "letter.txt"
    body_file.write_text("Body", encoding="utf-8")
    args = ["--id", "00000001", "--subject", "Title", "--body-file", str(body_file), "--json", "--env-file", str(tmp_path / ".env")]
    assert cli.main(args + (["--send"] if send else [])) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["message"]["status"] == ("accepted" if send else "preview")
    assert client.send_email.call_count == int(send)
    client.find_student.assert_called_once_with("00000001", refresh=send)


def test_missing_student_cannot_receive_mail(capsys, tmp_path, client):
    client.find_student.side_effect = None
    client.find_student.return_value = None
    assert cli.main(["--id", "1", "--subject", "Title", "--body", "Body", "--send", "--env-file", str(tmp_path / ".env")]) == 1
    client.mail_preview.assert_not_called()
    client.send_email.assert_not_called()


@pytest.mark.parametrize("args", [["--send"], ["--id", "1", "--send"], ["--id", "1", "--subject", "Title"], ["--json"]])
def test_incomplete_mail_args_fail_before_client(monkeypatch, args):
    factory = Mock()
    monkeypatch.setattr(cli, "GraphClient", factory)
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2
    factory.assert_not_called()


@pytest.mark.parametrize("args", [["--id", "bad"], ["--id", "1", "--subject", "", "--body", "Body"], ["--id", "1", "--subject", "Title", "--body", ""]])
def test_invalid_values_fail_before_client(monkeypatch, tmp_path, args):
    factory = Mock()
    monkeypatch.setattr(cli, "GraphClient", factory)
    assert cli.main([*args, "--env-file", str(tmp_path / ".env")]) == 2
    factory.assert_not_called()


def test_logout_does_not_authenticate(monkeypatch, tmp_path):
    factory = Mock()
    monkeypatch.setattr(cli, "GraphClient", factory)
    assert cli.main(["--logout", "--env-file", str(tmp_path / ".env")]) == 0
    factory.assert_not_called()
