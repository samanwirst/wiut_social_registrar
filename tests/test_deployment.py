import json
from io import StringIO

import pytest

from deploy import release
from deploy.install_watchdog import units
from deploy.release import IMAGE, manifest


def payload(**changes):
    return {
        "image": IMAGE + "@sha256:" + "a" * 64,
        "commit": "b" * 40,
        "registry_user": "test-user",
        "registry_token": "dummy-registry-token",
        **changes,
    }


def test_deployment_accepts_only_immutable_images_from_this_project():
    expected = payload()
    assert manifest(StringIO(json.dumps(expected))) == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"image": IMAGE + ":latest"},
        {"image": "ghcr.io/other/project@sha256:" + "a" * 64},
        {"image": IMAGE + "@sha256:" + "a" * 64 + "; whoami"},
        {"commit": "main"},
        {"registry_user": "operator; whoami"},
        {"registry_token": ""},
        {"command": "docker compose down"},
    ],
)
def test_deployment_rejects_other_projects_shell_input_and_mutable_tags(changes):
    with pytest.raises(ValueError):
        manifest(StringIO(json.dumps(payload(**changes))))


def test_deployment_rejects_oversized_manifests():
    with pytest.raises(ValueError):
        manifest(StringIO(" " * 16385))


def test_initial_database_import_runs_once_without_starting_polling(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "initial-snapshot.json").write_text("{}")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    calls = []
    monkeypatch.setattr(release, "compose", lambda *args, **kwargs: calls.append(args))

    release.bootstrap_database({})
    release.bootstrap_database({})

    assert len(calls) == 1
    assert calls[0][0] == "run"
    assert "scripts.transfer_database" in calls[0]
    assert ":/migration/snapshot.json:ro" in calls[0][7]
    assert (shared / "initial-import.complete").stat().st_mode & 0o777 == 0o600


def test_initial_import_failure_does_not_mark_database_as_imported(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "initial-snapshot.json").write_text("{}")
    monkeypatch.setattr(release, "ROOT", tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("Synthetic import failure")

    monkeypatch.setattr(release, "compose", fail)
    with pytest.raises(RuntimeError):
        release.bootstrap_database({})
    assert not (shared / "initial-import.complete").exists()


def test_initial_import_requires_private_snapshot(tmp_path, monkeypatch):
    (tmp_path / "shared").mkdir()
    monkeypatch.setattr(release, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="snapshot is missing"):
        release.bootstrap_database({})


def test_existing_production_release_never_reimports_data(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "current.json").write_text("{}")
    monkeypatch.setattr(release, "ROOT", tmp_path)
    release.bootstrap_database({})


def test_network_override_is_scoped_and_only_used_when_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(release, "ROOT", tmp_path)
    normal = release.compose_command("up", "bot")
    overlay = tmp_path / "compose.telegram-ip.yaml"
    assert str(overlay) not in normal

    overlay.write_text("services: {}")
    overridden = release.compose_command("up", "bot")
    assert overridden == [*normal[:-2], "-f", str(overlay), "up", "bot"]


def test_monitor_installer_is_restricted_to_this_project_and_never_starts_polling():
    from pathlib import Path

    root = Path("/opt/wiut-social-registrar")
    name, service, timer = units(
        "production", root, root / ".local/.env", "http://127.0.0.1:18080/health"
    )
    assert name == "wiut-social-registrar-watchdog"
    assert '"--project" "wiut-social-registrar-production"' in service
    assert "ProtectSystem=strict" in service
    assert "monitoring.watchdog" in service and "main.py" not in service
    assert "OnUnitInactiveSec=10s" in timer
    with pytest.raises(ValueError, match="restricted"):
        units("production", Path("/opt/another-project"), root / ".local/.env", "")


def test_external_monitor_never_repairs_or_uses_production_credentials(tmp_path):
    _, service, _ = units("external", tmp_path, tmp_path / ".env", "https://example.test/health")
    assert '"--repair"' not in service
    assert '"--project"' not in service
    assert '"--runtime"' not in service
    assert ".bot-watchdog-production-external.json" in service


def test_generated_user_service_passes_systemd_path_and_command_validation(tmp_path):
    import os
    import shutil
    import subprocess
    import sys
    import tempfile

    if not shutil.which("systemd-analyze"):
        pytest.skip("systemd-analyze is unavailable in this test image")
    binary = tmp_path / ".venv/bin/python"
    binary.parent.mkdir(parents=True)
    binary.symlink_to(sys.executable)
    name, service, timer = units("dev", tmp_path, tmp_path / ".env", "https://example.test/health")
    paths = [tmp_path / (name + ".service"), tmp_path / (name + ".timer")]
    for path, content in zip(paths, (service, timer)):
        path.write_text(content)
    # User socket addresses must fit Unix's short path limit. Pytest's verbose
    # test directory can exceed that limit even though these units have no sockets.
    with tempfile.TemporaryDirectory(prefix="registrar-runtime-") as runtime:
        result = subprocess.run(
            ["systemd-analyze", "--user", "verify", *map(str, paths)],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "SYSTEMD_UNIT_PATH": str(tmp_path) + ":/usr/lib/systemd/user:/lib/systemd/user",
                "XDG_RUNTIME_DIR": runtime,
            },
        )
    assert result.returncode == 0, result.stderr
    assert "not absolute" not in result.stderr
    assert "ignoring" not in result.stderr.lower()
