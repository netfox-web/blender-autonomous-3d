"""Supervisor configuration loaded from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SupervisorConfig:
    repo_name: str = "netfox-web/blender-autonomous-3d"
    allowed_branch: str = "main"
    allowed_issue_number: int = 1
    webhook_secret: str = ""
    github_token: str = ""
    host: str = "0.0.0.0"
    port: int = 8791
    state_db_path: Path = Path(".fox3d-data/supervisor_state.db")
    audit_log_path: Path = Path(".fox3d-data/supervisor_audit.log")
    ai_provider: str = "rule_based"
    ai_api_key: str = ""
    watchdog_interval_seconds: int = 3600
    repo_root: Path = Path(__file__).resolve().parents[2]


def load_config() -> SupervisorConfig:
    repo_root = Path(__file__).resolve().parents[2]
    db_env = os.getenv("SUPERVISOR_STATE_DB_PATH", ".fox3d-data/supervisor_state.db")
    audit_env = os.getenv("SUPERVISOR_AUDIT_LOG_PATH", ".fox3d-data/supervisor_audit.log")

    return SupervisorConfig(
        repo_name=os.getenv("GITHUB_REPO_NAME", "netfox-web/blender-autonomous-3d"),
        allowed_branch=os.getenv("GITHUB_ALLOWED_BRANCH", "main"),
        allowed_issue_number=int(os.getenv("GITHUB_ALLOWED_ISSUE", "1")),
        webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", "dev-webhook-secret-not-for-prod"),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        host=os.getenv("SUPERVISOR_HOST", "0.0.0.0"),
        port=int(os.getenv("SUPERVISOR_PORT", "8791")),
        state_db_path=(repo_root / db_env).resolve(),
        audit_log_path=(repo_root / audit_env).resolve(),
        ai_provider=os.getenv("SUPERVISOR_AI_PROVIDER", "rule_based"),
        ai_api_key=os.getenv("SUPERVISOR_AI_API_KEY", ""),
        watchdog_interval_seconds=int(os.getenv("SUPERVISOR_WATCHDOG_INTERVAL", "3600")),
        repo_root=repo_root,
    )
