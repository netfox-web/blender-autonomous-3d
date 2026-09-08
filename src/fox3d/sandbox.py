"""Sandbox backend interface. Path guard is PARTIAL, not an OS jail."""

from __future__ import annotations

from typing import Any, Protocol

from fox3d.ops import assert_job_paths_safe


class SandboxBackend(Protocol):
    name: str
    status: str

    def enforce(self, job: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]: ...


class PathGuardBackend:
    name = "PATH_GUARD_ONLY"
    status = "PARTIAL"

    def enforce(self, job: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
        assert_job_paths_safe(job)
        enforced = ["path_guard"]
        not_enforced = []
        if not policy.get("networkAllowed", False):
            not_enforced.append("network")  # host cannot deny blender outbound here
        if policy.get("cpuLimit") or policy.get("memoryMb"):
            not_enforced.append("rlimit")
        return {
            "backend": self.name,
            "status": self.status,
            "enforced": enforced,
            "notEnforced": not_enforced,
            "osJail": False,
            "note": "path guard only — not CONTAINER/JOB_OBJECT",
        }


class ContainerBackend:
    name = "CONTAINER"
    status = "BLOCKED"

    def enforce(self, job: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
        _ = job, policy
        return {"backend": self.name, "status": self.status, "osJail": False, "note": "no container runtime wired"}


def job_policy_manifest(job: dict[str, Any], *, work_dir: str) -> dict[str, Any]:
    allow = [work_dir, str(job.get("workDir") or work_dir)]
    man = {
        "jobId": job.get("jobId"),
        "filesystemAllowlist": allow,
        "networkAllowed": False,
        "cpuLimit": job.get("cpuLimit") or 120,
        "memoryMb": job.get("memoryMb") or 4096,
        "timeLimitSec": job.get("timeoutSeconds") or 300,
        "envAllowlist": ["FOX3D_WORK", "BLENDER_USER_RESOURCES"],
        "backend": "PATH_GUARD_ONLY",
        "enforce": "PARTIAL",
        "osJail": False,
        "note": "Host cannot enforce network/CPU/memory without a jail backend.",
    }
    return man


class SandboxRegistry:
    def __init__(self) -> None:
        self.backends = {
            "PATH_GUARD_ONLY": PathGuardBackend(),
            "CONTAINER": ContainerBackend(),
            "JOB_OBJECT": ContainerBackend(),
        }

    def get(self, name: str = "PATH_GUARD_ONLY") -> SandboxBackend:
        return self.backends.get(name) or self.backends["PATH_GUARD_ONLY"]
