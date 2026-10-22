import json
from io import StringIO

import pytest

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
