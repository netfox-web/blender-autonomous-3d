"""Direct unit tests for supervisor signature, sender, admin auth, and watchdog."""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
from typing import Any, cast

import pytest

from services.supervisor.config import ConfigValidationError, SupervisorConfig, validate_live_config
from services.supervisor.engine import SupervisorEngine
from services.supervisor.models import ReadyForReGateContract
from services.supervisor.security import (
    SecurityError,
    authorize_sender,
    validate_repo_and_branch,
    verify_admin_auth,
    verify_github_signature,
)
from services.supervisor.watchdog import SupervisorWatchdog

_WEBHOOK_SECRET = "test-webhook-secret"
_ADMIN_KEY = "admin-key-0123456789"
_PAYLOAD = b'{"action":"created"}'


def _sign(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _contract_body(code_sha: str, evidence_id: str = "ev-1") -> str:
    return "\n".join(
        [
            "READY_FOR_RE_GATE",
            "REPO=netfox-web/blender-autonomous-3d",
            "ISSUE=1",
            f"INSTRUCTION_SHA={'c' * 40}",
            f"CODE_SHA={code_sha}",
            f"DOCS_SHA={'d' * 40}",
            "CI_RUN_ID=1001",
            "TEST_COUNT=4",
            f"EVIDENCE_GENERATION_ID={evidence_id}",
            "REAL_BLENDER=true",
            "USED_MOCK=false",
        ]
    )


class _FakeGitHub:
    def __init__(
        self,
        comments: list[dict[str, Any]] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.comments = comments or []
        self.error = error
        self.calls: list[tuple[int, int]] = []

    def get_latest_issue_comments(self, issue_number: int, count: int = 10) -> list[dict[str, Any]]:
        self.calls.append((issue_number, count))
        if self.error is not None:
            raise self.error
        return self.comments


class _FakeState:
    def __init__(self, reviewed: bool = False) -> None:
        self.reviewed = reviewed
        self.calls: list[tuple[str, str]] = []

    def is_already_reviewed(self, code_sha: str, evidence_generation_id: str) -> bool:
        self.calls.append((code_sha, evidence_generation_id))
        return self.reviewed


class _FakeConfig:
    def __init__(self, allowed_issue_number: int = 1) -> None:
        self.allowed_issue_number = allowed_issue_number


class _FakeEngine:
    def __init__(self, github: _FakeGitHub, state: _FakeState, issue_number: int = 1) -> None:
        self.github_client = github
        self.state_mgr = state
        self.config = _FakeConfig(issue_number)
        self.handled: list[ReadyForReGateContract] = []

    def handle_ready_contract(self, contract: ReadyForReGateContract) -> dict[str, str]:
        self.handled.append(contract)
        return {"status": "REVIEWED", "code_sha": contract.code_sha}


def _watchdog(engine: _FakeEngine) -> SupervisorWatchdog:
    return SupervisorWatchdog(cast(SupervisorEngine, engine))


def _live_config(tmp_path: Path, admin_key: str) -> SupervisorConfig:
    return SupervisorConfig(
        mode="live",
        webhook_secret="strong-secret-123456",
        github_token="fake-token-for-test",
        allowed_senders=("netfox-web",),
        ai_provider="semantic_evidence",
        admin_key=admin_key,
        state_db_path=tmp_path / "supervisor.db",
        audit_log_path=tmp_path / "audit.log",
    )


def test_verify_github_signature_accepts_correct_hmac() -> None:
    header = _sign(_PAYLOAD, _WEBHOOK_SECRET)
    assert verify_github_signature(_PAYLOAD, header, _WEBHOOK_SECRET) is True


def test_verify_github_signature_rejects_wrong_hmac() -> None:
    header = _sign(_PAYLOAD, "different-secret")
    assert verify_github_signature(_PAYLOAD, header, _WEBHOOK_SECRET) is False
    tampered = _sign(b"other-body", _WEBHOOK_SECRET)
    assert verify_github_signature(_PAYLOAD, tampered, _WEBHOOK_SECRET) is False


def test_verify_github_signature_rejects_missing_header() -> None:
    assert verify_github_signature(_PAYLOAD, None, _WEBHOOK_SECRET) is False
    assert verify_github_signature(_PAYLOAD, "", _WEBHOOK_SECRET) is False


def test_verify_github_signature_rejects_missing_prefix() -> None:
    digest = _sign(_PAYLOAD, _WEBHOOK_SECRET).split("=", 1)[1]
    assert verify_github_signature(_PAYLOAD, digest, _WEBHOOK_SECRET) is False
    assert verify_github_signature(_PAYLOAD, f"md5={digest}", _WEBHOOK_SECRET) is False


def test_verify_github_signature_requires_secret() -> None:
    header = _sign(_PAYLOAD, _WEBHOOK_SECRET)
    with pytest.raises(SecurityError, match="GITHUB_WEBHOOK_SECRET"):
        verify_github_signature(_PAYLOAD, header, "")


def test_validate_repo_is_case_insensitive() -> None:
    validate_repo_and_branch("Netfox-Web/Blender-Autonomous-3D", None)
    validate_repo_and_branch("NETFOX-WEB/blender-autonomous-3d", "main")
    with pytest.raises(SecurityError, match="not allowed"):
        validate_repo_and_branch("other-org/other-repo", "main")
    with pytest.raises(SecurityError, match="not allowed"):
        validate_repo_and_branch("", "main")


def test_validate_branch_accepts_ref_and_short_name() -> None:
    validate_repo_and_branch("netfox-web/blender-autonomous-3d", "main")
    validate_repo_and_branch("netfox-web/blender-autonomous-3d", "refs/heads/main")


def test_validate_branch_rejects_wrong_branch() -> None:
    with pytest.raises(SecurityError, match="Branch 'develop'"):
        validate_repo_and_branch("netfox-web/blender-autonomous-3d", "develop")
    with pytest.raises(SecurityError, match="refs/heads/feature"):
        validate_repo_and_branch("netfox-web/blender-autonomous-3d", "refs/heads/feature")


def test_authorize_sender_allows_whitelist() -> None:
    authorize_sender("Netfox-Web", "NONE", ["netfox-web"])
    authorize_sender("  other-admin  ", "CONTRIBUTOR", ["other-admin"])


def test_authorize_sender_allows_association() -> None:
    authorize_sender("stranger", "OWNER", [])
    authorize_sender("stranger", "member", ["someone-else"])
    authorize_sender("stranger", "COLLABORATOR", ["someone-else"])


def test_authorize_sender_default_denies() -> None:
    with pytest.raises(SecurityError, match="Default-deny"):
        authorize_sender("public-user", "NONE", ["netfox-web"])
    with pytest.raises(SecurityError, match="Unauthorized sender"):
        authorize_sender("public-user", "CONTRIBUTOR", ["netfox-web"])
    with pytest.raises(SecurityError, match="Unauthorized sender"):
        authorize_sender("", "", [])


def test_admin_auth_loopback_non_live_allows() -> None:
    for host in ("127.0.0.1", "localhost", "::1"):
        assert verify_admin_auth(None, _ADMIN_KEY, is_live=False, client_host=host) is True
    assert verify_admin_auth(None, _ADMIN_KEY, is_live=False, client_host="10.0.0.8") is False


def test_admin_auth_live_loopback_does_not_bypass() -> None:
    assert verify_admin_auth(None, _ADMIN_KEY, is_live=True, client_host="127.0.0.1") is False
    assert verify_admin_auth(None, _ADMIN_KEY, is_live=True, client_host="localhost") is False
    assert verify_admin_auth("", "", is_live=True, client_host="::1") is False
    allowed = verify_admin_auth(
        f"Bearer {_ADMIN_KEY}",
        _ADMIN_KEY,
        is_live=True,
        client_host="127.0.0.1",
    )
    assert allowed is True


def test_admin_auth_accepts_bearer_prefix() -> None:
    assert verify_admin_auth(f"Bearer {_ADMIN_KEY}", _ADMIN_KEY, is_live=True, client_host="10.0.0.8") is True
    assert verify_admin_auth(f"bearer {_ADMIN_KEY}", _ADMIN_KEY, is_live=True, client_host="10.0.0.8") is True
    assert verify_admin_auth(_ADMIN_KEY, _ADMIN_KEY, is_live=True, client_host="10.0.0.8") is True
    assert verify_admin_auth("Bearer wrong-admin-key", _ADMIN_KEY, is_live=True, client_host="10.0.0.8") is False
    assert verify_admin_auth(None, _ADMIN_KEY, is_live=True, client_host="10.0.0.8") is False


def test_admin_auth_rejects_whitespace_only_key() -> None:
    blank_key = " " * 16
    # Live mode must fail closed, including the empty Bearer bypass and loopback.
    assert verify_admin_auth("Bearer ", blank_key, is_live=True, client_host="203.0.113.9") is False
    assert verify_admin_auth("Bearer    ", blank_key, is_live=True, client_host="127.0.0.1") is False
    assert verify_admin_auth(None, "\t\n  ", is_live=True, client_host="127.0.0.1") is False
    assert verify_admin_auth(f"Bearer {blank_key}", blank_key, is_live=True, client_host="10.0.0.8") is False
    # Non-live, non-loopback treats a whitespace key as unset (same as "").
    assert verify_admin_auth(None, blank_key, is_live=False, client_host="10.0.0.8") is True
    assert verify_admin_auth("Bearer something", blank_key, is_live=False, client_host="10.0.0.8") is True
    assert verify_admin_auth(None, "", is_live=False, client_host="10.0.0.8") is True


def test_live_config_admin_key_length_uses_stripped_value(tmp_path: Path) -> None:
    with pytest.raises(ConfigValidationError, match="SUPERVISOR_ADMIN_KEY"):
        validate_live_config(_live_config(tmp_path, " " * 16))
    padded_short = (" " * 8) + "short" + (" " * 8)
    assert len(padded_short) >= 16
    assert len(padded_short.strip()) < 16
    with pytest.raises(ConfigValidationError, match="SUPERVISOR_ADMIN_KEY"):
        validate_live_config(_live_config(tmp_path, padded_short))
    padded_ok = "  " + ("k" * 16) + "  "
    validate_live_config(_live_config(tmp_path, padded_ok))


def test_watchdog_check_once_error() -> None:
    github = _FakeGitHub(error=RuntimeError("github unavailable"))
    state = _FakeState()
    engine = _FakeEngine(github, state, issue_number=7)
    result = _watchdog(engine).check_once()
    assert result == {"status": "ERROR", "error": "github unavailable"}
    assert github.calls == [(7, 10)]
    assert state.calls == []
    assert engine.handled == []


def test_watchdog_check_once_no_contract() -> None:
    comments = [
        {"body": "status update only"},
        {"body": "READY_FOR_RE_GATE\nREPO=netfox-web/blender-autonomous-3d"},
        {},
    ]
    github = _FakeGitHub(comments)
    state = _FakeState()
    engine = _FakeEngine(github, state)
    assert _watchdog(engine).check_once() == {"status": "NO_CONTRACT_FOUND"}
    assert _watchdog(_FakeEngine(_FakeGitHub([]), state)).check_once() == {"status": "NO_CONTRACT_FOUND"}
    assert state.calls == []
    assert engine.handled == []


def test_watchdog_check_once_up_to_date() -> None:
    older = "a" * 40
    newest = "b" * 40
    github = _FakeGitHub(
        [
            {"body": _contract_body(older, "ev-old")},
            {"body": _contract_body(newest, "ev-new")},
        ]
    )
    state = _FakeState(reviewed=True)
    engine = _FakeEngine(github, state)
    result = _watchdog(engine).check_once()
    assert result == {"status": "UP_TO_DATE", "code_sha": newest}
    assert state.calls == [(newest, "ev-new")]
    assert engine.handled == []


def test_watchdog_check_once_processed() -> None:
    older = "a" * 40
    newest = "b" * 40
    github = _FakeGitHub(
        [
            {"body": "not a contract"},
            {"body": _contract_body(older, "ev-old")},
            {"body": _contract_body(newest, "ev-new")},
        ]
    )
    state = _FakeState(reviewed=False)
    engine = _FakeEngine(github, state)
    result = _watchdog(engine).check_once()
    assert result["status"] == "PROCESSED"
    assert result["result"] == {"status": "REVIEWED", "code_sha": newest}
    assert state.calls == [(newest, "ev-new")]
    assert len(engine.handled) == 1
    assert engine.handled[0].code_sha == newest
    assert engine.handled[0].evidence_generation_id == "ev-new"
