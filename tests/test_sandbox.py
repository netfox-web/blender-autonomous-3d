from unittest.mock import patch

import pytest

from fox3d.sandbox import ContainerBackend, PathGuardBackend, SandboxRegistry, job_policy_manifest


def test_registry_rejects_unknown_backend_and_keeps_default():
    registry = SandboxRegistry()
    assert registry.get().name == "PATH_GUARD_ONLY"
    with pytest.raises(KeyError, match="CONTAINR"):
        registry.get("CONTAINR")


def test_path_guard_calls_path_check_and_rejects_traversal():
    backend = PathGuardBackend()
    job = {"glbPath": "safe/model.glb"}
    with patch("fox3d.sandbox.assert_job_paths_safe") as check:
        backend.enforce(job, {})
    check.assert_called_once_with(job)
    with pytest.raises(PermissionError):
        backend.enforce({"glbPath": "../outside.glb"}, {})


def test_path_guard_reports_unenforced_limits():
    result = PathGuardBackend().enforce({}, {"networkAllowed": False, "cpuLimit": 2})
    assert result["status"] == "PARTIAL"
    assert result["osJail"] is False
    assert result["enforced"] == ["path_guard"]
    assert "network" in result["notEnforced"]
    assert "rlimit" in result["notEnforced"]


@pytest.mark.parametrize("name", ["CONTAINER", "JOB_OBJECT"])
def test_unavailable_jail_backends_are_blocked(name):
    backend = SandboxRegistry().get(name)
    assert isinstance(backend, ContainerBackend)
    result = backend.enforce({}, {})
    assert result["status"] == "BLOCKED"
    assert result["osJail"] is False


def test_manifest_fields_and_defaults():
    assert job_policy_manifest({"jobId": "job-1"}, work_dir="/work") == {
        "jobId": "job-1",
        "filesystemAllowlist": ["/work", "/work"],
        "networkAllowed": False,
        "cpuLimit": 120,
        "memoryMb": 4096,
        "timeLimitSec": 300,
        "envAllowlist": ["FOX3D_WORK", "BLENDER_USER_RESOURCES"],
        "backend": "PATH_GUARD_ONLY",
        "enforce": "PARTIAL",
        "osJail": False,
        "note": "Host cannot enforce network/CPU/memory without a jail backend.",
    }


def test_manifest_uses_job_limits_and_work_dir():
    result = job_policy_manifest(
        {"workDir": "/work/job", "cpuLimit": 4, "memoryMb": 1024, "timeoutSeconds": 60}, work_dir="/work"
    )
    assert result["filesystemAllowlist"] == ["/work", "/work/job"]
    assert (result["cpuLimit"], result["memoryMb"], result["timeLimitSec"]) == (4, 1024, 60)
