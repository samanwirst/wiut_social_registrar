import json
from io import StringIO

import pytest

from deploy import release
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
