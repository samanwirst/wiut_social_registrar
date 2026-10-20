import base64
import json
import stat
from unittest.mock import Mock

import pytest
import requests

from registrar.auth import SCOPES, TokenProvider
from registrar.config import ConfigurationError, Settings
from registrar.errors import AuthenticationError


@pytest.fixture
def provider(tmp_path, monkeypatch):
    settings = Settings(tmp_path / ".env", client_id="a1622de9-bfa2-464b-9d04-aab4190c90ab")
    status = Mock()
    app = Mock()
    app.get_accounts.return_value = [{"username": "sender@example.test"}]
    app.acquire_token_silent.return_value = {"access_token": "secret-access-token"}
    monkeypatch.setattr("registrar.auth.msal.PublicClientApplication", Mock(return_value=app))
    return TokenProvider(settings, status), app, status


def test_cached_login_uses_silent_and_refresh(provider):
    auth, app, status = provider
    assert auth.get_token() == "secret-access-token"
    assert auth.get_token(refresh=True) == "secret-access-token"
    assert app.acquire_token_silent.call_args.kwargs["force_refresh"] is True
    assert app.acquire_token_silent.call_args.args[0] == SCOPES
    app.initiate_device_flow.assert_not_called()
    status.assert_not_called()


def test_new_login_uses_device_flow_and_persists_cache(provider):
    auth, app, status = provider
    app.get_accounts.return_value = []
    flow = {"user_code": "test-code", "message": "Open Microsoft and enter code"}
    app.initiate_device_flow.return_value = flow

    def acquire(_flow):
        auth.cache.deserialize(json.dumps({"test": "cache-value"}))
        auth.cache.has_state_changed = True
        return {"access_token": "secret-access-token"}

    app.acquire_token_by_device_flow.side_effect = acquire
    assert auth.login() == "secret-access-token"
    status.assert_called_once_with(flow["message"])
    assert json.loads(Settings.load(auth.settings.env_file).load_cache()) == {"test": "cache-value"}


def test_force_login_recovers_from_bad_cache(provider):
    auth, app, _ = provider
    auth.settings.token_cache_b64 = "secret-bad-cache"
    app.initiate_device_flow.return_value = {"user_code": "code", "message": "Sign in"}
    app.acquire_token_by_device_flow.return_value = {"access_token": "new-token"}
    assert auth.login(force=True) == "new-token"
    app.acquire_token_silent.assert_not_called()


def test_multiple_accounts_require_selection(provider):
    auth, app, _ = provider
    app.get_accounts.return_value = [{}, {}]
    with pytest.raises(AuthenticationError, match="multiple"):
        auth.login()
    app.initiate_device_flow.assert_not_called()


def test_failed_refresh_does_not_start_interactive_flow(provider):
    auth, app, _ = provider
    app.acquire_token_silent.return_value = None
    with pytest.raises(AuthenticationError, match="--login"):
        auth.get_token(refresh=True)
    app.initiate_device_flow.assert_not_called()


def test_auth_network_failure_hides_transport_details(provider):
    auth, app, _ = provider
    app.acquire_token_silent.side_effect = requests.ConnectionError("secret-in-url")
    with pytest.raises(AuthenticationError) as error:
        auth.login()
    assert "secret-in-url" not in str(error.value)


def test_cache_only_written_to_private_env(tmp_path):
    path = tmp_path / ".env"
    path.write_text("GRAPH_DEBUG=false\n")
    settings = Settings(path)
    cache = '{"RefreshToken":{"secret":"secret-refresh-token"}}'
    settings.save_cache(cache)
    assert Settings.load(path).load_cache() == cache
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [path]
    assert "secret-refresh-token" not in path.read_text()
    settings.save_cache(None)
    assert Settings.load(path).load_cache() == "{}"


@pytest.mark.parametrize("value", ["secret-bad-cache", base64.b64encode(b"not-json").decode(), base64.b64encode(b"[]").decode(), base64.b64encode(b"\xff").decode()])
def test_bad_cache_errors_hide_value(tmp_path, value):
    settings = Settings(tmp_path / ".env", token_cache_b64=value)
    with pytest.raises(ConfigurationError) as error:
        settings.load_cache()
    assert value not in str(error.value)


@pytest.mark.parametrize("line", ["GRAPH_TIMEOUT_SECONDS=nan", "GRAPH_TIMEOUT_SECONDS=-1", "GRAPH_CACHE_TTL_SECONDS=inf", "GRAPH_CLIENT_ID=invalid", "GRAPH_TENANT_ID=invalid", "GRAPH_STUDENT_DOMAIN=bad/path", "GRAPH_DEBUG=maybe"])
def test_invalid_configuration_is_rejected(tmp_path, line):
    path = tmp_path / ".env"
    path.write_text(line)
    with pytest.raises(ConfigurationError):
        Settings.load(path)
