import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from config import BotSettings
from monitoring import telegram, watchdog
from monitoring.state import admin_ids, read_json, save_json
from registrar.config import ConfigurationError
from tests.helpers import TEST_TOKEN


def arguments(tmp_path, **changes):
    return SimpleNamespace(
        **{
            "env_dir": tmp_path,
            "project": None,
            "user_service": None,
            "url": "https://example.test/health",
            "runtime": False,
            "require_runtime": False,
            "public_url": "",
            "backups": None,
            "repair": False,
            **changes,
        }
    )


@pytest.mark.parametrize(
    "raw", ["{}", "null", "[true]", "[0]", "[-1]", '["100"]', "broken", "[9223372036854775808]"]
)
def test_administrators_require_a_safe_numeric_json_array(raw):
    with pytest.raises(ValueError, match="BOT_ADMIN_IDS must be a JSON array"):
        admin_ids(raw)


def test_admins_are_loaded_from_selected_env_and_explicit_overrides(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(f"TELEGRAM_BOT_TOKEN={TEST_TOKEN}\nBOT_ADMIN_IDS='[100,200,100]'\n")
    monkeypatch.delenv("BOT_ADMIN_IDS", raising=False)
    assert BotSettings.load(path).admin_ids == (100, 200)
    monkeypatch.setenv("BOT_ADMIN_IDS", "[300]")
    assert BotSettings.load(path).admin_ids == (300,)
    monkeypatch.setenv("BOT_ADMIN_IDS", '["private-invalid-value"]')
    with pytest.raises(ConfigurationError) as error:
        BotSettings.load(path)
    assert "private-invalid-value" not in str(error.value)


def test_operational_state_is_private_atomic_and_recovers_from_bad_json(tmp_path):
    path = tmp_path / ".bot-watchdog.json"
    save_json(path, {"version": 1})
    save_json(path, {"version": 2})
    assert read_json(path) == {"version": 2}
    assert path.stat().st_mode & 0o777 == 0o600
    path.write_text("partial")
    assert read_json(path) == {}
    assert len(list(tmp_path.iterdir())) == 1


def check_alerts(state, issues, now, send, recipients=(100,)):
    watchdog.observe(state, issues, recipients, now=now, name="Test")
    watchdog.deliver(state, send, now=now)


def test_failure_and_stable_recovery_survive_monitor_restarts_without_repeated_alerts(tmp_path):
    state, send = {}, Mock(return_value=True)
    issues = {"database": "Database unavailable"}
    check_alerts(state, issues, 1000, send)
    assert not send.called
    path = tmp_path / "state.json"
    save_json(path, state)
    state = read_json(path)
    check_alerts(state, issues, 1030, send)
    assert send.call_count == 1
    check_alerts(state, {}, 1040, send)
    check_alerts(state, {}, 1099, send)
    assert send.call_count == 1
    save_json(path, state)
    state = read_json(path)
    check_alerts(state, {}, 1100, send)
    check_alerts(state, {}, 1120, send)
    assert send.call_count == 2
    assert "Alert:" in send.call_args_list[0].args[1]
    assert "Recovered:" in send.call_args_list[1].args[1]


@pytest.mark.parametrize(
    "key",
    [
        "application",
        "restart",
        "email",
        "email:GraphError",
        "handler:RuntimeError",
        "qr:ValueError",
    ],
)
def test_isolated_application_errors_and_restarts_never_page_or_claim_recovery(key):
    state, send = {}, Mock(return_value=True)
    for now in range(1000, 2000, 10):
        check_alerts(state, {key: "Diagnostic only"}, now, send)
    check_alerts(state, {}, 2100, send)
    assert not send.called


def test_repeated_brief_outlook_failures_never_page_or_accumulate_confirmation_time():
    state, send = {}, Mock(return_value=True)
    for start in (1000, 1500, 2000):
        for now in range(start, start + 60, 10):
            check_alerts(state, {"outlook": "Outlook: GraphError"}, now, send)
        check_alerts(state, {}, start + 60, send)
    assert not send.called


@pytest.mark.parametrize(
    ("key", "duration"),
    [
        ("outlook", 180),
        ("broadcasts", 180),
        ("cleanup", 180),
        ("supervisor", 180),
        ("backup", 300),
        ("disk", 300),
        ("tls", 300),
    ],
)
def test_dependency_and_operational_failures_have_independent_confirmation_windows(key, duration):
    state, send = {}, Mock(return_value=True)
    for now in range(1000, 1000 + duration, 10):
        check_alerts(state, {key: "Unavailable"}, now, send)
    assert not send.called
    check_alerts(state, {key: "Unavailable"}, 1000 + duration, send)
    assert send.call_count == 1


def test_outlook_requires_three_minutes_and_does_not_remind_or_flap():
    state, send = {}, Mock(return_value=True)
    issues = {"outlook": "Outlook: HTTP 503"}
    for now in range(1000, 1180, 10):
        check_alerts(state, issues, now, send)
    assert not send.called
    check_alerts(state, issues, 1180, send)
    assert send.call_count == 1
    for now in range(1190, 3000, 10):
        check_alerts(state, issues, now, send)
    assert send.call_count == 1
    check_alerts(state, {}, 3000, send)
    check_alerts(state, {}, 3050, send)
    check_alerts(state, issues, 3060, send)
    check_alerts(state, {}, 3070, send)
    check_alerts(state, {}, 3130, send)
    assert send.call_count == 2
    check_alerts(state, issues, 3140, send)
    for now in range(3150, 3321, 10):
        check_alerts(state, issues, now, send)
    assert send.call_count == 3  # A new confirmed outage after stable recovery.


def test_related_service_symptoms_produce_one_alert_and_wait_for_all_to_recover():
    state, send = {}, Mock(return_value=True)
    issues = {"http": "HTTP unavailable", "database": "Database unavailable", "heartbeat": "Stale"}
    check_alerts(state, issues, 1000, send)
    check_alerts(state, issues, 1030, send)
    assert send.call_count == 1
    assert "Database unavailable" in send.call_args.args[1]
    check_alerts(state, {"http": "HTTP unavailable"}, 1040, send)
    check_alerts(state, {"polling": "Polling unavailable"}, 1120, send)
    assert send.call_count == 1
    check_alerts(state, {}, 1130, send)
    check_alerts(state, {}, 1190, send)
    assert send.call_count == 2


def test_recovered_unsent_outage_is_not_replayed_when_telegram_returns():
    state, send = {}, Mock(return_value=False)
    check_alerts(state, {"http": "Unavailable"}, 1000, send)
    check_alerts(state, {"http": "Unavailable"}, 1030, send)
    assert send.call_count == 1
    send.reset_mock(return_value=True)
    check_alerts(state, {}, 1040, send)
    check_alerts(state, {}, 1100, send)
    assert not send.called
    assert not state["records"]["availability"]["pending"]


def test_delivery_backoff_and_recovery_only_for_admins_who_received_the_alert():
    state, send = {}, Mock(side_effect=lambda recipient, text: recipient == 100)
    issues = {"http": "Unavailable"}
    check_alerts(state, issues, 1000, send, (100, 200, 300))
    check_alerts(state, issues, 1030, send, (100, 200, 300))
    assert send.call_count == 3
    assert state["next_delivery"] == 1050
    check_alerts(state, issues, 1040, send, (100, 200))
    assert send.call_count == 3
    check_alerts(state, {}, 1050, send, (100, 200))
    check_alerts(state, {}, 1110, send, (100, 200))
    assert send.call_count == 4
    assert send.call_args.args[0] == 100
    assert "Recovered:" in send.call_args.args[1]
    assert not state["records"]["availability"]["pending"]


def test_removed_admins_are_not_contacted_and_delivery_is_bounded():
    state, send = {}, Mock(return_value=False)
    issues = {"http": "Unavailable"}
    check_alerts(state, issues, 1000, send, tuple(range(1, 21)))
    check_alerts(state, issues, 1030, send, tuple(range(1, 21)))
    assert send.call_count == 3
    send.reset_mock(return_value=True)
    check_alerts(state, issues, 1050, send, (20,))
    assert send.call_count == 1
    assert send.call_args.args[0] == 20


def test_unobserved_time_cannot_confirm_an_outage_or_recovery():
    state, send = {}, Mock(return_value=True)
    issues = {"http": "Unavailable"}
    check_alerts(state, issues, 1000, send)
    check_alerts(state, issues, 2000, send)
    assert not send.called
    check_alerts(state, issues, 2030, send)
    assert send.call_count == 1
    check_alerts(state, {}, 2040, send)
    check_alerts(state, {}, 3000, send)
    assert send.call_count == 1
    check_alerts(state, {}, 3060, send)
    assert send.call_count == 2


def test_old_policy_discards_stale_spam_without_resetting_repair_budget():
    state = {
        "records": {
            "application": {"open": False, "pending": [{"text": "Old alert", "remaining": [100]}]}
        },
        "repairs": [900],
        "container": "a" * 64,
        "next_delivery": 2000,
    }
    send = Mock(return_value=True)
    check_alerts(state, {}, 1000, send)
    assert not send.called
    assert state["records"] == {}
    assert state["repairs"] == [900] and state["container"] == "a" * 64


def test_dependency_alerts_and_recoveries_are_suppressed_during_service_outage():
    state, send = {}, Mock(return_value=True)
    issues = {"outlook": "Outlook unavailable"}
    for now in range(1000, 1181, 10):
        check_alerts(state, issues, now, send)
    assert send.call_count == 1
    for now in range(1190, 1500, 10):
        check_alerts(state, {"http": "Unavailable"}, now, send)
    assert send.call_count == 2
    assert all("Recovered:" not in call.args[1] for call in send.call_args_list)
    check_alerts(state, {}, 1500, send)
    check_alerts(state, {}, 1560, send)
    assert send.call_count == 4


def test_incomplete_probes_cannot_confirm_failures_or_recoveries():
    state, send = {}, Mock(return_value=True)
    for now in range(1000, 1181, 10):
        check_alerts(state, {"outlook": "Unavailable"}, now, send)
    for now in range(1190, 1370, 10):
        watchdog.observe(
            state, {"supervisor": "Probe failed"}, (100,), now=now, name="Test", complete=False
        )
        watchdog.deliver(state, send, now=now)
    assert send.call_count == 1
    assert state["records"]["outlook"]["open"]
    assert all("Recovered:" not in call.args[1] for call in send.call_args_list)


def test_telegram_notifier_preserves_trusted_hostname_while_pinning_only_tcp(monkeypatch):
    connection, response = Mock(), Mock(status=200)
    response.read.return_value = b'{"ok":true}'
    connection.getresponse.return_value = response
    factory = Mock(return_value=connection)
    connect = Mock()
    monkeypatch.setattr(telegram.http.client, "HTTPSConnection", factory)
    monkeypatch.setattr(telegram.socket, "create_connection", connect)
    assert telegram.send_alert(TEST_TOKEN, 100, "Alert", address="192.0.2.1")
    assert factory.call_args.args == ("api.telegram.org",)
    context = factory.call_args.kwargs["context"]
    assert context.check_hostname
    connection._create_connection(("api.telegram.org", 443), 6)
    assert connect.call_args.args[0] == ("192.0.2.1", 443)
    assert connection.request.call_args.args[1].endswith("/sendMessage")
    assert json.loads(connection.request.call_args.kwargs["body"])["chat_id"] == 100
    connection.close.assert_called_once()


def test_notifier_does_not_leak_transport_errors_or_retry_ambiguously_accepted_messages(
    monkeypatch, capsys
):
    connection = Mock()
    connection.request.side_effect = OSError("private-token-or-url")
    monkeypatch.setattr(telegram.http.client, "HTTPSConnection", Mock(return_value=connection))
    assert not telegram.send_alert(TEST_TOKEN, 100, "Alert")
    connection.request.assert_called_once()
    assert "private-token" not in capsys.readouterr().out


def test_development_ca_augments_public_trust_instead_of_replacing_system_roots(monkeypatch):
    context = Mock()
    factory = Mock(return_value=context)
    response = Mock(status=200)
    response.read.return_value = b'{"status":"ok"}'
    opener = Mock()
    opener.return_value.__enter__ = Mock(return_value=response)
    opener.return_value.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(watchdog.ssl, "create_default_context", factory)
    monkeypatch.setattr(watchdog.urllib.request, "urlopen", opener)
    assert watchdog.health_url("https://example.test/health", ca_file="synthetic-ca.pem")
    factory.assert_called_once_with()
    context.load_verify_locations.assert_called_once_with(cafile="synthetic-ca.pem")


def test_healthy_http_does_not_hide_a_stale_runtime_or_polling(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "health_url", lambda *a, **k: True)
    args = arguments(tmp_path, runtime=True, require_runtime=True)
    save_json(
        tmp_path / ".bot-health.json",
        {
            "updated_at": 1000,
            "phase": "running",
            "components": {"polling": {"ok": True, "checked_at": 800}},
        },
    )
    issues, _, repair = watchdog.collect(args, {}, now=1000)
    assert "polling" in issues and "http" not in issues and not repair
    issues, _, _ = watchdog.collect(args, {}, now=1100)
    assert "heartbeat" in issues


def test_runtime_incidents_never_copy_sensitive_error_details(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "health_url", lambda *a, **k: True)
    save_json(
        tmp_path / ".bot-health.json",
        {
            "updated_at": 1000,
            "phase": "running",
            "components": {"outlook": {"ok": False, "reason": "private@account.test?token=secret"}},
            "incidents": {"handler:RuntimeError": {"at": 999}, "private-token": {"at": 999}},
        },
    )
    issues, _, _ = watchdog.collect(arguments(tmp_path, runtime=True), {}, now=1000)
    assert issues["outlook"] == "Outlook: unavailable"
    assert "handler:RuntimeError" in issues
    assert "private" not in json.dumps(issues)


def test_autorepair_is_bounded_and_never_restarts_for_outlook_or_database_alone(
    tmp_path, monkeypatch
):
    calls, persisted = [], []
    monkeypatch.setattr(watchdog, "command", lambda *a, **k: calls.append(a))
    args = arguments(tmp_path, repair=True, user_service="wiut-social-registrar.service")
    state = {}
    for now in (1000, 1010, 1020):
        watchdog.repair(args, state, {"outlook": "Down", "database": "Down"}, True, now=now)
    assert not calls
    for now in range(1030, 2400, 10):
        watchdog.repair(
            args,
            state,
            {"http": "Down"},
            True,
            now=now,
            persist=lambda: persisted.append(list(state["repairs"])),
        )
    assert len(calls) == len(persisted) == 3
    assert all(b - a >= 300 for a, b in zip(state["repairs"], state["repairs"][1:]))
    watchdog.repair(args, {}, {"http": "Down"}, False, now=2500)
    assert len(calls) == 3


def test_ambiguous_restart_is_counted_before_the_command_can_timeout(tmp_path, monkeypatch):
    state = {"failed_checks": 2, "container": "a" * 64}
    path = tmp_path / "state.json"

    def timeout(*a, **k):
        assert read_json(path)["repairs"] == [1000]
        raise TimeoutError

    monkeypatch.setattr(watchdog, "command", timeout)
    with pytest.raises(TimeoutError):
        watchdog.repair(
            arguments(tmp_path, repair=True, project="wiut-social-registrar-production"),
            state,
            {"heartbeat": "Stale"},
            True,
            now=1000,
            persist=lambda: save_json(path, state),
        )


def test_legacy_production_probe_is_scoped_and_sends_only_fixed_error_categories(
    tmp_path, monkeypatch
):
    commands = []
    items = [
        {
            "Id": "a" * 64,
            "Config": {"Labels": {"com.docker.compose.service": name}},
            "State": {"Status": "running", "StartedAt": "2026-01-01T00:00:00.000000000Z"},
            "RestartCount": 0,
        }
        for name in ("bot", "postgres", "caddy")
    ]

    def command(arguments, **kwargs):
        commands.append(arguments)
        return "a" * 64 if arguments[1] == "ps" else json.dumps(items)

    monkeypatch.setattr(watchdog, "command", command)
    monkeypatch.setattr(watchdog, "health_url", lambda *a, **k: True)
    monkeypatch.setattr(
        watchdog.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=" ERROR private-student-secret", stderr=""),
    )
    issues, _, repair = watchdog.collect(
        arguments(tmp_path, project="wiut-social-registrar-production"), {}, now=1800000000
    )
    assert commands[0][-1] == "label=com.docker.compose.project=wiut-social-registrar-production"
    assert "application" in issues and "private-student-secret" not in json.dumps(issues)
    assert repair


def test_main_preserves_incidents_when_a_monitor_probe_itself_fails(tmp_path, monkeypatch):
    path = tmp_path / ".bot-watchdog.json"
    state = {}
    initial_send = Mock(return_value=True)
    for now in (1000, 1090, 1180):
        check_alerts(state, {"outlook": "Unavailable"}, now, initial_send)
    assert initial_send.call_count == 1
    save_json(path, state)
    monkeypatch.setattr(watchdog.time, "time", lambda: 1190)
    monkeypatch.setenv("BOT_ADMIN_IDS", "[100]")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TEST_TOKEN)
    monkeypatch.setattr(watchdog, "collect", Mock(side_effect=RuntimeError("private-probe-error")))
    send = Mock(return_value=True)
    monkeypatch.setattr(watchdog, "send_alert", send)
    assert watchdog.main(["--env-dir", str(tmp_path)]) == 0
    assert read_json(path)["records"]["outlook"]["open"]
    assert not send.called
