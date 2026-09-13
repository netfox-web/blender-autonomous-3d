"""Supervisor configuration loaded from environment with strict live fail-closed validation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple


@dataclass(frozen=True)
class SupervisorConfig:
    repo_name: str = "netfox-web/blender-autonomous-3d"
    allowed_branch: str = "main"
    allowed_issue_number: int = 1
    webhook_secret: str = ""
    github_token: str = ""
    mode: str = "test"  # "test" or "live"
    allowed_senders: Tuple[str, ...] = ("netfox-web",)
    allowed_associations: Tuple[str, ...] = ("OWNER", "MEMBER", "COLLABORATOR")
    admin_key: str = ""
    host: str = "0.0.0.0"
    port: int = 8791
    state_db_path: Path = Path(".fox3d-data/supervisor_state.db")
    audit_log_path: Path = Path(".fox3d-data/supervisor_audit.log")
    ai_provider: str = "rule_based"
    ai_api_key: str = ""
    watchdog_interval_seconds: int = 3600
    repo_root: Path = Path(__file__).resolve().parents[2]


class ConfigValidationError(Exception):
    """Raised when configuration validation fails (especially in live mode)."""
    pass


def validate_live_config(config: SupervisorConfig) -> None:
    """Ensure live mode fails closed if any security or execution prerequisite is missing."""
    if config.mode.lower() != "live":
        return

    if not config.webhook_secret or config.webhook_secret == "dev-webhook-secret-not-for-prod":
        raise ConfigValidationError("Live mode requires a strong, non-default GITHUB_WEBHOOK_SECRET.")

    if not config.github_token:
        raise ConfigValidationError("Live mode requires a non-empty GITHUB_TOKEN with repository scope.")

    if not config.allowed_senders:
        raise ConfigValidationError("Live mode requires at least one authorized sender in allowed_senders.")

    if config.ai_provider in ("mock", "rule_based"):
        raise ConfigValidationError(
            f"Live mode requires a real AI provider (not '{config.ai_provider}'). Configure 'semantic_evidence', 'openai', 'anthropic', 'gemini', or a verified external provider."
        )

    # Ensure storage paths are writable
    try:
        config.state_db_path.parent.mkdir(parents=True, exist_ok=True)
        config.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise ConfigValidationError(f"Live storage path validation failed: {e}")


def load_config() -> SupervisorConfig:
    repo_root = Path(__file__).resolve().parents[2]
    db_env = os.getenv("SUPERVISOR_STATE_DB_PATH", ".fox3d-data/supervisor_state.db")
    audit_env = os.getenv("SUPERVISOR_AUDIT_LOG_PATH", ".fox3d-data/supervisor_audit.log")
    senders_env = os.getenv("SUPERVISOR_ALLOWED_SENDERS", "netfox-web")
    allowed_senders = tuple(s.strip() for s in senders_env.split(",") if s.strip())

    mode = os.getenv("SUPERVISOR_MODE", "test").lower()

    cfg = SupervisorConfig(
        repo_name=os.getenv("GITHUB_REPO_NAME", "netfox-web/blender-autonomous-3d"),
        allowed_branch=os.getenv("GITHUB_ALLOWED_BRANCH", "main"),
        allowed_issue_number=int(os.getenv("GITHUB_ALLOWED_ISSUE", "1")),
        webhook_secret=os.getenv("GITHUB_WEBHOOK_SECRET", "dev-webhook-secret-not-for-prod"),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        mode=mode,
        allowed_senders=allowed_senders,
        allowed_associations=("OWNER", "MEMBER", "COLLABORATOR"),
        admin_key=os.getenv("SUPERVISOR_ADMIN_KEY", ""),
        host=os.getenv("SUPERVISOR_HOST", "0.0.0.0"),
        port=int(os.getenv("SUPERVISOR_PORT", "8791")),
        state_db_path=(repo_root / db_env).resolve(),
        audit_log_path=(repo_root / audit_env).resolve(),
        ai_provider=os.getenv("SUPERVISOR_AI_PROVIDER", "rule_based"),
        ai_api_key=os.getenv("SUPERVISOR_AI_API_KEY", ""),
        watchdog_interval_seconds=int(os.getenv("SUPERVISOR_WATCHDOG_INTERVAL", "3600")),
        repo_root=repo_root,
    )

    validate_live_config(cfg)
    return cfg
