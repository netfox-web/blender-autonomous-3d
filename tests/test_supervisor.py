"""Tests for Event-Driven Autonomous Supervisor Control Plane covering all 19 mandatory scenarios."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import subprocess
import httpx
import pytest
from fastapi.testclient import TestClient

from services.supervisor.ai_adapter import (
    ExternalProviderSupervisorAdapter,
    MockSupervisorAdapter,
    OpenAISupervisorAdapter,
    RuleBasedSupervisorAdapter,
    SemanticEvidenceSupervisorAdapter,
    SupervisorProviderAdapter,
    create_supervisor_adapter,
)
from services.supervisor.config import ConfigValidationError, SupervisorConfig, validate_live_config
from services.supervisor.engine import SupervisorEngine, parse_diff_changed_files
from services.supervisor.github_client import GitHubClient, GitHubClientInterface, GitHubVerificationError
from services.supervisor.main import create_app
from services.supervisor.models import (
    ChangedFileItem,
    EvidenceSectionCompleteness,
    HEX40_PATTERN,
    ReadyForReGateContract,
    ReviewContext,
    ReviewDecision,
    SupervisorReviewOutput,
    SupervisorStatus,
)
from services.supervisor.policy import PolicyEngine
from services.supervisor.security import verify_github_signature
from services.supervisor.state import StateManager
from scripts.antigravity_watcher import format_ready_contract


class MockGitHubClient(GitHubClientInterface):
    """Deterministic mock GitHub client for testing."""

    def __init__(self) -> None:
        self.valid_commits: set[str] = {"c0de111", "d0c5111", "c0de222", "d0c5222"}
        self.ci_runs: Dict[str, Dict[str, Any]] = {
            "run_ok": {
                "head_sha": "c0de111",
                "status": "completed",
                "conclusion": "success",
                "jobs": [
                    {"name": "unit (ubuntu-latest)", "conclusion": "success"},
                    {"name": "unit (windows-latest)", "conclusion": "success"},
                ],
            },
            "run_docs_ok": {
                "head_sha": "d0c5111",
                "status": "completed",
                "conclusion": "success",
                "jobs": [
                    {"name": "unit (ubuntu-latest)", "conclusion": "success"},
                    {"name": "unit (windows-latest)", "conclusion": "success"},
                ],
            },
            "run_pending": {
                "head_sha": "c0de111",
                "status": "in_progress",
                "conclusion": None,
                "jobs": [],
            },
            "run_failed": {
                "head_sha": "c0de111",
                "status": "completed",
                "conclusion": "failure",
                "jobs": [
                    {"name": "unit (ubuntu-latest)", "conclusion": "failure"},
                    {"name": "unit (windows-latest)", "conclusion": "success"},
                ],
            },
        }
        self.files: Dict[str, str] = {
            "docs/GROK_PROGRESS_REPORT.md": "# Progress Report\nTests passed: 628.",
            "docs/GROK_NEXT_PHASE_INSTRUCTIONS.md": "# Phase 901 Instructions",
            "docs/CURRENT_IMPLEMENTATION_AUDIT.md": "# Audit OK",
            "docs/REAL_E2E_ACCEPTANCE.md": "# Real E2E OK",
            "docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md": "# Event Driven Acceptance OK",
        }
        self.commits_log: List[Dict[str, Any]] = []
        self.committed_instructions: List[Dict[str, str]] = []
        self.posted_comments: List[Dict[str, Any]] = []

    def verify_commit_on_main(self, sha: str) -> bool:
        return sha in self.valid_commits

    def get_ci_run_details(self, run_id: str) -> Dict[str, Any]:
        if run_id not in self.ci_runs:
            raise GitHubVerificationError(f"Run {run_id} not found.")
        return self.ci_runs[run_id]

    def verify_ci_run(self, run_id: str, expected_code_sha: str) -> Dict[str, Any]:
        data = self.get_ci_run_details(run_id)
        head_sha = data["head_sha"]
        if head_sha != expected_code_sha:
            raise GitHubVerificationError(f"CI run head_sha {head_sha} != {expected_code_sha}")
        if data.get("status") != "completed":
            raise GitHubVerificationError(f"CI run status is {data.get('status')} (not concluded).")
        if data.get("conclusion") != "success":
            raise GitHubVerificationError(f"CI run conclusion is {data.get('conclusion')}")

        ubuntu_ok = any(j.get("name", "").startswith("unit (ubuntu") and j.get("conclusion") == "success" for j in data.get("jobs", []))
        windows_ok = any(j.get("name", "").startswith("unit (windows") and j.get("conclusion") == "success" for j in data.get("jobs", []))
        if not (ubuntu_ok and windows_ok):
            raise GitHubVerificationError("Ubuntu or Windows job did not succeed.")
        return {"run_id": run_id, "conclusion": "success", "ubuntu_ok": True, "windows_ok": True}

    def get_file_content(self, path: str, ref: str = "main") -> str:
        return self.files.get(path, "")

    def get_commits_since(self, base_sha: str, head_sha: str = "main") -> List[Dict[str, Any]]:
        if hasattr(self, "commits_since_error") and self.commits_since_error:
            if getattr(self, "recovery_only_error", False) and not str(head_sha).startswith("origin/"):
                return self.commits_log
            raise GitHubVerificationError(self.commits_since_error)
        return self.commits_log

    def get_diff_between(self, base_sha: str, head_sha: str = "main") -> str:
        return getattr(self, "diff_text", "")

    def get_changed_files_between(self, base_sha: str, head_sha: str = "main") -> List[ChangedFileItem]:
        if hasattr(self, "mock_changed_files"):
            return self.mock_changed_files
        diff = self.get_diff_between(base_sha, head_sha)
        if diff:
            return parse_diff_changed_files(diff)
        return []

    def commit_instruction_file(self, file_path: str, content: str, commit_message: str, branch: str = "main") -> str:
        new_sha = f"instr_{len(self.committed_instructions) + 1:04d}"
        entry = {
            "file_path": file_path,
            "content": content,
            "commit_message": commit_message,
            "message": commit_message,
            "sha": new_sha,
        }
        self.committed_instructions.append(entry)
        self.commits_log.append(entry)
        self.files[file_path] = content
        return new_sha

    def add_issue_comment(self, issue_number: int, comment_body: str) -> str:
        comment_id = f"comment_{len(self.posted_comments) + 1}"
        self.posted_comments.append({
            "id": comment_id,
            "issue_number": issue_number,
            "body": comment_body,
        })
        return comment_id

    def get_latest_issue_comments(self, issue_number: int, count: int = 10) -> List[Dict[str, Any]]:
        if hasattr(self, "comments_error") and self.comments_error:
            raise GitHubVerificationError(self.comments_error)
        return self.posted_comments[-count:]


@pytest.fixture
def env_setup(tmp_path: Path):
    db_path = tmp_path / "supervisor.db"
    audit_path = tmp_path / "audit.log"
    config = SupervisorConfig(
        repo_name="netfox-web/blender-autonomous-3d",
        allowed_branch="main",
        allowed_issue_number=1,
        webhook_secret="test-secret-12345",
        state_db_path=db_path,
        audit_log_path=audit_path,
        repo_root=tmp_path,
    )
    state_mgr = StateManager(db_path)
    policy_engine = PolicyEngine(audit_path)
    github_client = MockGitHubClient()
    ai_adapter = RuleBasedSupervisorAdapter()
    engine = SupervisorEngine(
        config=config,
        state_mgr=state_mgr,
        github_client=github_client,
        ai_adapter=ai_adapter,
        policy_engine=policy_engine,
    )

    app = create_app(config)
    # Inject test dependencies into app
    app.state.state_mgr = state_mgr
    app.state.github_client = github_client
    app.state.policy_engine = policy_engine
    app.state.ai_adapter = ai_adapter
    app.state.engine = engine

    client = TestClient(app)
    return {
        "config": config,
        "state_mgr": state_mgr,
        "policy_engine": policy_engine,
        "github_client": github_client,
        "ai_adapter": ai_adapter,
        "engine": engine,
        "client": client,
    }


def make_sig(body: bytes, secret: str) -> str:
    h = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={h}"


def valid_contract_text(
    code_sha: str = "c0de111",
    docs_sha: str = "d0c5111",
    ci_run_id: str = "run_ok",
    test_count: int = 628,
    evidence_id: str = "gen_001",
    instruction_sha: str = "instr_000",
    real_blender: bool = True,
    used_mock: bool = False,
    repo: str = "netfox-web/blender-autonomous-3d",
    issue: int = 1,
    code_ci_run_id: Optional[str] = None,
    docs_ci_run_id: str = "run_docs_ok",
) -> str:
    actual_code_ci = ci_run_id if code_ci_run_id is None else code_ci_run_id
    return format_ready_contract(
        instruction_sha=instruction_sha,
        code_sha=code_sha,
        docs_sha=docs_sha,
        ci_run_id=ci_run_id,
        test_count=test_count,
        evidence_generation_id=evidence_id,
        real_blender=real_blender,
        used_mock=used_mock,
        repo=repo,
        issue=issue,
        code_ci_run_id=actual_code_ci,
        docs_ci_run_id=docs_ci_run_id,
    )


# 1. invalid webhook signature -> reject
def test_1_invalid_webhook_signature_rejected(env_setup):
    client = env_setup["client"]
    resp = client.post(
        "/webhooks/github",
        content=b'{"test": 1}',
        headers={"X-Hub-Signature-256": "sha256=invalid", "X-GitHub-Event": "push"},
    )
    assert resp.status_code == 401


# 2. duplicate delivery -> once
def test_2_duplicate_delivery_deduplication(env_setup):
    client = env_setup["client"]
    cfg = env_setup["config"]
    body = json.dumps({
        "repository": {"full_name": "netfox-web/blender-autonomous-3d"},
        "action": "created",
        "sender": {"login": "netfox-web"},
        "issue": {"number": 1},
        "comment": {"body": "hello", "author_association": "OWNER"},
    }).encode("utf-8")
    sig = make_sig(body, cfg.webhook_secret)
    headers = {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Event": "issue_comment",
        "X-GitHub-Delivery": "deliv_12345",
    }
    r1 = client.post("/webhooks/github", content=body, headers=headers)
    assert r1.status_code == 200
    assert r1.json()["status"] == "IGNORED_NO_CONTRACT"

    # Second request with same delivery ID is skipped as duplicate
    r2 = client.post("/webhooks/github", content=body, headers=headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "IGNORED_DUPLICATE_DELIVERY"


# 3. duplicate READY -> once
def test_3_duplicate_ready_contract_idempotent(env_setup):
    engine = env_setup["engine"]
    c_text = valid_contract_text(evidence_id="gen_uniq_1")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    assert contract is not None

    r1 = engine.handle_ready_contract(contract)
    assert r1["status"] == "COMPLETED"

    # Immediate second call with same code_sha and evidence_id must be ignored
    r2 = engine.handle_ready_contract(contract)
    assert r2["status"] == "IGNORE_DUPLICATE"


# 4. wrong repo -> reject
def test_4_wrong_repo_rejected(env_setup):
    engine = env_setup["engine"]
    c_text = valid_contract_text(repo="other-org/other-repo")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    res = engine.handle_ready_contract(contract)
    assert res["status"] == "REJECTED"


# 5. wrong issue -> reject
def test_5_wrong_issue_rejected(env_setup):
    engine = env_setup["engine"]
    c_text = valid_contract_text(issue=99)
    contract = ReadyForReGateContract.parse_from_text(c_text)
    res = engine.handle_ready_contract(contract)
    assert res["status"] == "REJECTED"


# 6. CI pending -> wait
def test_6_ci_pending_waits(env_setup):
    engine = env_setup["engine"]
    c_text = valid_contract_text(ci_run_id="run_pending", evidence_id="gen_ci_pending")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    with pytest.raises(GitHubVerificationError, match="not concluded"):
        engine.handle_ready_contract(contract)


# 7. CI failure -> BLOCK
def test_7_ci_failure_blocks(env_setup):
    engine = env_setup["engine"]
    c_text = valid_contract_text(ci_run_id="run_failed", evidence_id="gen_ci_failed")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    with pytest.raises(GitHubVerificationError, match="failure"):
        engine.handle_ready_contract(contract)


# 8. CODE SHA not on main -> reject
def test_8_code_sha_not_on_main_rejected(env_setup):
    engine = env_setup["engine"]
    c_text = valid_contract_text(code_sha="unmerged_code_sha", evidence_id="gen_code_not_main")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    with pytest.raises(GitHubVerificationError, match="not reachable"):
        engine.handle_ready_contract(contract)


# 9. docs mismatch -> reject
def test_9_docs_mismatch_rejected(env_setup):
    engine = env_setup["engine"]
    c_text = valid_contract_text(docs_sha="unmerged_docs_sha", evidence_id="gen_docs_not_main")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    with pytest.raises(GitHubVerificationError, match="DOCS_SHA"):
        engine.handle_ready_contract(contract)


# 10. ACCEPT -> one instruction commit
def test_10_accept_with_scope_single_instruction_commit(env_setup):
    engine = env_setup["engine"]
    gh = env_setup["github_client"]
    c_text = valid_contract_text(evidence_id="gen_accept_scope")
    contract = ReadyForReGateContract.parse_from_text(c_text)

    res = engine.handle_ready_contract(contract)
    assert res["status"] == "COMPLETED"
    assert res["decision"] == "ACCEPT_WITH_SCOPE"
    assert len(gh.committed_instructions) == 1
    assert "start next-phase" in gh.committed_instructions[0]["commit_message"]
    assert len(gh.posted_comments) == 1
    assert "SUPERVISOR_REVIEW_COMPLETE" in gh.posted_comments[0]["body"]
    assert "DECISION=ACCEPT_WITH_SCOPE" in gh.posted_comments[0]["body"]


# 11. CHANGES_REQUIRED -> correction only
def test_11_changes_required_correction_only(env_setup):
    engine = env_setup["engine"]
    gh = env_setup["github_client"]
    # Force contradiction: real_blender=True AND used_mock=True
    c_text = valid_contract_text(
        real_blender=True,
        used_mock=True,
        evidence_id="gen_contradiction",
    )
    contract = ReadyForReGateContract.parse_from_text(c_text)

    res = engine.handle_ready_contract(contract)
    assert res["status"] == "COMPLETED"
    assert res["decision"] == "CHANGES_REQUIRED"
    assert len(gh.committed_instructions) == 1
    assert "correction-only" in gh.committed_instructions[0]["commit_message"]
    assert "SUPERVISOR_REVIEW_COMPLETE" in gh.posted_comments[0]["body"]
    assert "DECISION=CHANGES_REQUIRED" in gh.posted_comments[0]["body"]


# 12. BLOCKED -> no agent start
def test_12_blocked_guardrail_human_approval(env_setup):
    engine = env_setup["engine"]
    gh = env_setup["github_client"]
    # Inject a mock adapter that attempts LIVE_CNC
    engine.ai_adapter = MockSupervisorAdapter(
        forced_decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        forced_instruction_md="Execute run live_cnc on factory machine",
    )
    c_text = valid_contract_text(evidence_id="gen_cnc_blocked")
    contract = ReadyForReGateContract.parse_from_text(c_text)

    res = engine.handle_ready_contract(contract)
    assert res["decision"] == "BLOCKED"
    # Instruction file must NOT be committed on BLOCKED
    assert len(gh.committed_instructions) == 0
    # Must post HUMAN_APPROVAL_REQUIRED on issue
    assert len(gh.posted_comments) == 1
    assert "HUMAN_APPROVAL_REQUIRED" in gh.posted_comments[0]["body"]


# 13. Supervisor own commit -> no loop
def test_13_supervisor_own_commit_no_loop(env_setup):
    client = env_setup["client"]
    cfg = env_setup["config"]
    payload = {
        "repository": {"full_name": "netfox-web/blender-autonomous-3d"},
        "ref": "refs/heads/main",
        "head_commit": {
            "message": "supervisor: accept 4406119 and start next-phase",
            "author": {"name": "Fox3D Supervisor"},
        },
    }
    body = json.dumps(payload).encode("utf-8")
    sig = make_sig(body, cfg.webhook_secret)
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "push"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "EVENT_ACKNOWLEDGED"


# 14. Issue own comment -> no loop
def test_14_supervisor_own_issue_comment_no_loop(env_setup):
    client = env_setup["client"]
    cfg = env_setup["config"]
    payload = {
        "repository": {"full_name": "netfox-web/blender-autonomous-3d"},
        "action": "created",
        "issue": {"number": 1},
        "comment": {
            "body": "[SUPERVISOR] ## SUPERVISOR_REVIEW_COMPLETE\nDECISION=ACCEPT_WITH_SCOPE",
        },
        "sender": {"login": "fox3d-supervisor[bot]"},
    }
    body = json.dumps(payload).encode("utf-8")
    sig = make_sig(body, cfg.webhook_secret)
    resp = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "issue_comment"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "IGNORED_SUPERVISOR_OWN_COMMENT"


# 15. two simultaneous READY -> serialized
def test_15_concurrent_ready_contracts_serialized(env_setup):
    state_mgr = env_setup["state_mgr"]
    engine = env_setup["engine"]

    # Pre-lock with review A
    acquired, _ = state_mgr.acquire_review_lock("rev_A", "c0de111")
    assert acquired is True

    # Incoming contract with newer code B while A is running
    c_text_B = valid_contract_text(code_sha="c0de222", docs_sha="d0c5222", evidence_id="gen_B")
    contract_B = ReadyForReGateContract.parse_from_text(c_text_B)

    res_B = engine.handle_ready_contract(contract_B)
    assert res_B["status"] == "PENDING_NEWER_EVIDENCE"

    # Verify B is queued
    pending = state_mgr.pop_latest_pending()
    assert pending is not None
    assert pending["code_sha"] == "c0de222"

    # Release lock
    state_mgr.release_review_lock("rev_A")


# 16. crash during review -> resume safely
def test_16_crash_during_review_resumes_safely(env_setup):
    state_mgr = env_setup["state_mgr"]
    state_mgr.start_review("rev_crash", "c0de111", "gen_crash")
    st = state_mgr.get_state()
    assert st.status == SupervisorStatus.REVIEWING
    assert st.active_review_id == "rev_crash"

    # Simulate recovery on crash
    state_mgr.fail_review("rev_crash", "Simulated process killed")
    recovered_st = state_mgr.get_state()
    assert recovered_st.status == SupervisorStatus.FAILED
    assert recovered_st.active_review_id is None
    assert recovered_st.retry_count == 1


# 17. crash before GitHub write -> retry once
def test_17_crash_before_github_write_retries(env_setup):
    engine = env_setup["engine"]
    state_mgr = env_setup["state_mgr"]

    # Inject an adapter that throws an unexpected error before write
    class CrashingAdapter(MockSupervisorAdapter):
        def review_repository(self, context):
            raise RuntimeError("Transient crash before write")

    engine.ai_adapter = CrashingAdapter()
    c_text = valid_contract_text(evidence_id="gen_retry_me")
    contract = ReadyForReGateContract.parse_from_text(c_text)

    with pytest.raises(RuntimeError, match="Transient crash"):
        engine.handle_ready_contract(contract)

    # Lock must be released and status marked FAILED
    st = state_mgr.get_state()
    assert st.status == SupervisorStatus.FAILED

    # Now repair adapter and retry
    engine.ai_adapter = RuleBasedSupervisorAdapter()
    retry_res = engine.handle_ready_contract(contract)
    assert retry_res["status"] == "COMPLETED"


# 18. crash after GitHub write -> no duplicate commit
def test_18_crash_after_github_write_no_duplicate(env_setup):
    engine = env_setup["engine"]
    gh = env_setup["github_client"]
    c_text = valid_contract_text(evidence_id="gen_post_write")
    contract = ReadyForReGateContract.parse_from_text(c_text)

    # First successful run
    res = engine.handle_ready_contract(contract)
    assert res["status"] == "COMPLETED"
    assert len(gh.committed_instructions) == 1

    # Immediate replay after write must detect already reviewed and NOT commit again
    dup_res = engine.handle_ready_contract(contract)
    assert dup_res["status"] == "IGNORE_DUPLICATE"
    assert len(gh.committed_instructions) == 1


# 19. Antigravity sees new instruction -> auto claim; same instruction -> never execute twice
def test_19_antigravity_watcher_claims_and_no_duplicate(tmp_path: Path, monkeypatch):
    from scripts import antigravity_watcher

    fake_state_file = tmp_path / "watcher_state.json"
    monkeypatch.setattr(antigravity_watcher, "WATCH_STATE_FILE", fake_state_file)

    # Case A: new instruction available and approved
    monkeypatch.setattr(antigravity_watcher, "get_current_instruction_blob_sha", lambda: "sha_new_123")
    monkeypatch.setattr(
        antigravity_watcher,
        "get_latest_issue_comment",
        lambda: {"id": "c1", "body": "## SUPERVISOR_REVIEW_COMPLETE\nDECISION=ACCEPT_WITH_SCOPE"},
    )
    res1 = antigravity_watcher.check_for_claimable_instruction()
    assert res1["claimable"] is True
    assert res1["instructionSha"] == "sha_new_123"

    # Agent claims instruction
    antigravity_watcher.claim_instruction("sha_new_123")

    # Case B: check again with same instruction -> must NOT claim
    res2 = antigravity_watcher.check_for_claimable_instruction()
    assert res2["claimable"] is False
    assert "already executed" in res2["reason"]


# 20. Blocker A: Outsider commenter rejected with 403 Forbidden
def test_20_outsider_comment_rejected_403(env_setup):
    client = env_setup["client"]
    cfg = env_setup["config"]
    body = json.dumps({
        "action": "created",
        "repository": {"full_name": cfg.repo_name},
        "sender": {"login": "outsider-attacker"},
        "issue": {"number": 1},
        "comment": {"body": "READY_FOR_RE_GATE", "author_association": "NONE"},
    }).encode("utf-8")
    sig = make_sig(body, cfg.webhook_secret)
    headers = {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Event": "issue_comment",
        "X-GitHub-Delivery": "deliv_outsider",
    }
    r = client.post("/webhooks/github", content=body, headers=headers)
    assert r.status_code == 403
    assert "not authorized" in r.json()["detail"]


# 21. Blocker A: Wrong repo payload ignored with IGNORED_WRONG_REPOSITORY
def test_21_wrong_repo_payload_ignored(env_setup):
    client = env_setup["client"]
    cfg = env_setup["config"]
    body = json.dumps({
        "action": "created",
        "repository": {"full_name": "attacker/spoofed-repo"},
        "sender": {"login": "netfox-web"},
        "issue": {"number": 1},
        "comment": {"body": "hello", "author_association": "OWNER"},
    }).encode("utf-8")
    sig = make_sig(body, cfg.webhook_secret)
    headers = {
        "X-Hub-Signature-256": sig,
        "X-GitHub-Event": "issue_comment",
        "X-GitHub-Delivery": "deliv_wrong_repo",
    }
    r = client.post("/webhooks/github", content=body, headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "IGNORED_WRONG_REPOSITORY"


# 22. Blocker A: Edited or deleted comment actions ignored
def test_22_edited_or_deleted_comment_ignored(env_setup):
    client = env_setup["client"]
    cfg = env_setup["config"]
    for action in ("edited", "deleted"):
        body = json.dumps({
            "action": action,
            "repository": {"full_name": cfg.repo_name},
            "sender": {"login": "netfox-web"},
            "issue": {"number": 1},
            "comment": {"body": "hello", "author_association": "OWNER"},
        }).encode("utf-8")
        sig = make_sig(body, cfg.webhook_secret)
        headers = {
            "X-Hub-Signature-256": sig,
            "X-GitHub-Event": "issue_comment",
            "X-GitHub-Delivery": f"deliv_{action}",
        }
        r = client.post("/webhooks/github", content=body, headers=headers)
        assert r.status_code == 200
        assert r.json()["status"] == "IGNORED_UNSUPPORTED_ACTION"


# 23. Blocker B: Durable delivery lifecycle & retryable failure recovery
def test_23_durable_delivery_lifecycle_and_retryable(env_setup):
    state_mgr = env_setup["state_mgr"]
    delivery_id = "deliv_lifecycle_test"

    # Step 1: New delivery can process
    can_proc, reason = state_mgr.evaluate_delivery(delivery_id)
    assert can_proc is True
    assert reason == "NEW"

    # Step 2: Record received & processing
    state_mgr.record_delivery_received(delivery_id, "issue_comment")
    state_mgr.set_delivery_status(delivery_id, "PROCESSING")

    # While processing in-flight, cannot process again
    can_proc2, reason2 = state_mgr.evaluate_delivery(delivery_id)
    assert can_proc2 is False
    assert reason2 == "PROCESSING_IN_FLIGHT"

    # Step 3: FAILED_RETRYABLE allows resume
    state_mgr.set_delivery_status(delivery_id, "FAILED_RETRYABLE", error="Temporary network glitch")
    can_proc3, reason3 = state_mgr.evaluate_delivery(delivery_id)
    assert can_proc3 is True
    assert reason3 == "RETRYABLE_FAILURE"

    # Step 4: COMPLETED is deduplicated safely
    state_mgr.set_delivery_status(delivery_id, "COMPLETED")
    can_proc4, reason4 = state_mgr.evaluate_delivery(delivery_id)
    assert can_proc4 is False
    assert reason4 == "IGNORED_DUPLICATE_DELIVERY"


# 24. Blocker B: Crash after instruction push but before comment resumes without duplicate commit
def test_24_crash_after_push_resumes_without_duplicate_commit(env_setup):
    engine = env_setup["engine"]
    gh = env_setup["github_client"]

    c_text = valid_contract_text(evidence_id="gen_crash_window_1")
    contract = ReadyForReGateContract.parse_from_text(c_text)

    # Intercept add_issue_comment to crash on the first attempt
    original_add_comment = gh.add_issue_comment
    attempt = 0

    def flaky_add_comment(issue_number: int, comment_body: str) -> str:
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise RuntimeError("Simulated crash right after git push before comment posted")
        return original_add_comment(issue_number, comment_body)

    gh.add_issue_comment = flaky_add_comment

    # First run crashes during comment posting
    with pytest.raises(RuntimeError, match="Simulated crash right after git push"):
        engine.handle_ready_contract(contract)

    assert len(gh.committed_instructions) == 1
    committed_sha = gh.committed_instructions[0]["sha"]

    # Now retry execution: engine must reuse the staged commit and post comment without creating a second commit!
    res = engine.handle_ready_contract(contract)
    assert res["status"] == "COMPLETED"
    assert res["new_instruction_sha"] == committed_sha
    assert len(gh.committed_instructions) == 1  # No duplicate commit!
    assert len(gh.posted_comments) == 1


# 25. Blocker C: Live mode push failure is never swallowed
def test_25_live_mode_git_push_failure_never_swallowed(tmp_path: Path, monkeypatch):
    import subprocess
    cfg = SupervisorConfig(
        mode="live",
        repo_root=tmp_path,
        webhook_secret="strong-live-secret-12345",
        github_token="fake-token",
        allowed_senders=("netfox-web",),
        ai_provider="semantic_evidence",
    )
    client = GitHubClient(cfg)

    def mock_run(cmd, *args, **kwargs):
        if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "push":
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="error: failed to push some refs")
        if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "status":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
        if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "diff-index":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
        if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "fetch":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
        if len(cmd) >= 2 and cmd[0] == "git" and cmd[1] == "rev-parse":
            if "--abbrev-ref" in cmd:
                return subprocess.CompletedProcess(cmd, returncode=0, stdout="main\n")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="head_sha_123\n")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="")

    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(GitHubVerificationError, match="git push failed in live mode"):
        client.commit_instruction_file(
            file_path="docs/GROK_NEXT_PHASE_INSTRUCTIONS.md",
            content="# Test Content",
            commit_message="test commit",
            branch="main",
        )


# 26. Blocker C: Unauthorized instruction path rejected
def test_26_unauthorized_instruction_path_rejected(tmp_path: Path):
    cfg = SupervisorConfig(mode="live", repo_root=tmp_path)
    client = GitHubClient(cfg)

    with pytest.raises(GitHubVerificationError, match="not an authorized supervisor instruction"):
        client.commit_instruction_file(
            file_path="services/malicious.py",
            content="# Exploit",
            commit_message="exploit commit",
            branch="main",
        )


# 27. Blocker D: SemanticEvidenceSupervisorAdapter adversarial contradiction checks
def test_27_semantic_evidence_adversarial_rejection():
    adapter = SemanticEvidenceSupervisorAdapter()

    # Case A: Contract claims real_blender=true, but diff forces mock -> REJECTED
    c_text1 = valid_contract_text(evidence_id="gen_adv_1")
    contract1 = ReadyForReGateContract.parse_from_text(c_text1)
    context1 = ReviewContext(
        contract=contract1,
        diffs="--- a/engine.py\n+++ b/engine.py\n+mock_blender = True\n+force_mock = True",
        progress_report_text="# Progress Report\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
    )
    res1 = adapter.review_repository(context1)
    assert res1.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("Diff forces mock execution" in b for b in res1.blockers)

    # Case B: Contract claims real_blender=true, but acceptance evidence explicitly indicates mock execution -> REJECTED
    c_text2 = valid_contract_text(evidence_id="gen_adv_2")
    contract2 = ReadyForReGateContract.parse_from_text(c_text2)
    context2 = ReviewContext(
        contract=contract2,
        diffs="clean diff without mock",
        progress_report_text="# Progress Report\nTests: 628",
        audit_text="# Audit\nreal_blender: false",
        acceptance_text="# Acceptance\nused_mock: true",
    )
    res2 = adapter.review_repository(context2)
    assert res2.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("indicates mock execution" in b for b in res2.blockers)

    # Case C: Genuine evidence -> ACCEPT_WITH_SCOPE
    c_text3 = valid_contract_text(evidence_id="gen_adv_3")
    contract3 = ReadyForReGateContract.parse_from_text(c_text3)
    context3 = ReviewContext(
        contract=contract3,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract3.code_sha}\nINSTRUCTION: {contract3.instruction_sha}\nTests: 628",
        audit_text="# Audit\nBlender Cycles OptiX verified on GPU",
        acceptance_text="# Acceptance\nReal renders produced with non-zero size",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res3 = adapter.review_repository(context3)
    assert res3.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert len(res3.blockers) == 0


# 28. Blocker E: Live configuration fails closed on missing/weak settings
def test_28_live_config_fails_closed(tmp_path: Path):
    # Missing token
    with pytest.raises(ConfigValidationError, match="non-empty GITHUB_TOKEN"):
        validate_live_config(SupervisorConfig(
            mode="live",
            webhook_secret="strong-secret-123456",
            github_token="",
            allowed_senders=("netfox-web",),
            ai_provider="semantic_evidence",
        ))

    # Default/weak webhook secret
    with pytest.raises(ConfigValidationError, match="strong, non-default GITHUB_WEBHOOK_SECRET"):
        validate_live_config(SupervisorConfig(
            mode="live",
            webhook_secret="dev-webhook-secret-not-for-prod",
            github_token="valid_token",
            allowed_senders=("netfox-web",),
            ai_provider="semantic_evidence",
        ))

    # Missing senders
    with pytest.raises(ConfigValidationError, match="at least one authorized sender"):
        validate_live_config(SupervisorConfig(
            mode="live",
            webhook_secret="strong-secret-123456",
            github_token="valid_token",
            allowed_senders=(),
            ai_provider="semantic_evidence",
        ))

    # Rule-based or mock provider in live mode
    with pytest.raises(ConfigValidationError, match="requires a real AI provider"):
        validate_live_config(SupervisorConfig(
            mode="live",
            webhook_secret="strong-secret-123456",
            github_token="valid_token",
            allowed_senders=("netfox-web",),
            ai_provider="rule_based",
        ))


# 29. Blocker E: Admin auth protects observability endpoints in live mode
def test_29_admin_auth_endpoints_in_live_mode(tmp_path: Path):
    cfg = SupervisorConfig(
        mode="live",
        admin_key="secret-admin-pass-123",
        state_db_path=tmp_path / "supervisor.db",
        audit_log_path=tmp_path / "audit.log",
        repo_root=tmp_path,
        webhook_secret="strong-secret-123456",
        github_token="fake-token",
        allowed_senders=("netfox-web",),
        ai_provider="semantic_evidence",
    )
    app = create_app(cfg)
    client = TestClient(app)

    # Unauthorized access rejected with 401
    r_unauth = client.get("/supervisor/status")
    assert r_unauth.status_code == 401

    # Authorized with Bearer token succeeds with 200
    r_auth = client.get("/supervisor/status", headers={"Authorization": "Bearer secret-admin-pass-123"})
    assert r_auth.status_code == 200
    assert r_auth.json()["repo_name"] == cfg.repo_name

    # Authorized with X-Supervisor-Admin-Key succeeds with 200
    r_key = client.get("/supervisor/reviews", headers={"X-Supervisor-Admin-Key": "secret-admin-pass-123"})
    assert r_key.status_code == 200


# 30. Blocker A: Webhook envelope fail-closed on missing/null repository
def test_30_webhook_envelope_fail_closed(env_setup):
    client = env_setup["client"]
    cfg = env_setup["config"]

    # Missing repository field completely -> 400
    p1 = {"action": "created", "sender": {"login": "netfox-web"}, "issue": {"number": 1}}
    b1 = json.dumps(p1).encode("utf-8")
    r1 = client.post("/webhooks/github", content=b1, headers={"X-Hub-Signature-256": make_sig(b1, cfg.webhook_secret), "X-GitHub-Event": "issue_comment"})
    assert r1.status_code == 400
    assert "repository envelope" in r1.json()["detail"]

    # repository field is None or not a dict -> 400
    p2 = {"repository": None, "action": "created"}
    b2 = json.dumps(p2).encode("utf-8")
    r2 = client.post("/webhooks/github", content=b2, headers={"X-Hub-Signature-256": make_sig(b2, cfg.webhook_secret), "X-GitHub-Event": "issue_comment"})
    assert r2.status_code == 400

    # repository.full_name is missing or empty -> 400
    p3 = {"repository": {"full_name": ""}, "action": "created"}
    b3 = json.dumps(p3).encode("utf-8")
    r3 = client.post("/webhooks/github", content=b3, headers={"X-Hub-Signature-256": make_sig(b3, cfg.webhook_secret), "X-GitHub-Event": "issue_comment"})
    assert r3.status_code == 400
    assert "repository.full_name" in r3.json()["detail"]

    # repository.full_name is wrong repo -> IGNORED_WRONG_REPOSITORY
    p4 = {"repository": {"full_name": "other-owner/other-repo"}, "action": "created"}
    b4 = json.dumps(p4).encode("utf-8")
    r4 = client.post("/webhooks/github", content=b4, headers={"X-Hub-Signature-256": make_sig(b4, cfg.webhook_secret), "X-GitHub-Event": "issue_comment"})
    assert r4.status_code == 200
    assert r4.json()["status"] == "IGNORED_WRONG_REPOSITORY"


# 31. Blocker A: In live mode, X-GitHub-Delivery is strictly required
def test_31_live_mode_requires_delivery_id(tmp_path: Path):
    cfg = SupervisorConfig(
        mode="live",
        admin_key="secret-admin-pass-123",
        state_db_path=tmp_path / "supervisor.db",
        audit_log_path=tmp_path / "audit.log",
        repo_root=tmp_path,
        webhook_secret="strong-secret-123456",
        github_token="fake-token",
        allowed_senders=("netfox-web",),
        ai_provider="semantic_evidence",
    )
    app = create_app(cfg)
    client = TestClient(app)

    p = {"repository": {"full_name": cfg.repo_name}, "action": "created"}
    b = json.dumps(p).encode("utf-8")
    sig = make_sig(b, cfg.webhook_secret)

    # Missing X-GitHub-Delivery header in live mode -> 400
    r_no_deliv = client.post("/webhooks/github", content=b, headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "issue_comment"})
    assert r_no_deliv.status_code == 400
    assert "X-GitHub-Delivery header is required in live mode" in r_no_deliv.json()["detail"]


# 32. Blocker B: Window B1 remote commit adoption on crash recovery
def test_32_crash_recovery_window_b1_commit_adoption(env_setup):
    engine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]
    state_mgr = env_setup["state_mgr"]

    c_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_win_b1")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    review_id = "rev_exact_b1"
    state_mgr.start_review(review_id, contract.code_sha, contract.evidence_generation_id)

    commit_trailers = (
        f"\n\nReviewed-Code-Sha: {contract.code_sha}\n"
        f"Reviewed-Docs-Sha: {contract.docs_sha}\n"
        f"Reviewed-Instruction-Sha: {contract.instruction_sha}\n"
        f"Reviewed-Evidence-Id: {contract.evidence_generation_id}\n"
        f"Supervisor-Decision: ACCEPT_WITH_SCOPE\n"
        f"Supervisor-Review-Id: {review_id}"
    )
    commit_msg = f"supervisor: accept {contract.code_sha[:7]} and start next-phase{commit_trailers}"
    content_marker = (
        f"\n\n<!-- SUPERVISOR_COMMIT_IDENTITY:\n"
        f"CODE_SHA={contract.code_sha}\n"
        f"DOCS_SHA={contract.docs_sha}\n"
        f"INSTRUCTION_SHA={contract.instruction_sha}\n"
        f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n"
        f"DECISION=ACCEPT_WITH_SCOPE\n"
        f"REVIEW_ID={review_id}\n"
        f"-->\n"
    )
    next_md = (
        f"# Phase Re-Gate: Accepted With Scope\n\n"
        f"CODE `{contract.code_sha[:7]}` and DOCS `{contract.docs_sha[:7]}` accepted.\n\n"
        f"## Next Phase Scope\n"
        f"- Continue autonomous pipeline execution.\n"
        f"- Maintain dual-platform CI pass (Ubuntu + Windows).\n"
        f"- Retain truth boundaries: no live CNC/laser/PLC.\n"
    )
    full_content = next_md + content_marker
    gh.files["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = full_content

    # Simulate that remote origin already contains a commit matching (code_sha, evidence_generation_id)
    gh.commits_log = [{
        "sha": "remote_instr_existing_sha_999",
        "commit": {
            "message": commit_msg
        },
        "message": commit_msg,
    }]

    res = engine.handle_ready_contract(contract)
    assert res["status"] == "COMPLETED"
    # Ensure that it adopted the remote commit rather than committing a new one
    assert len(gh.committed_instructions) == 0
    assert res["new_instruction_sha"] == "remote_instr_existing_sha_999"


# 33. Blocker B: Window B2 issue comment adoption on crash recovery
def test_33_crash_recovery_window_b2_comment_adoption(env_setup):
    engine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    c_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", evidence_id="gen_win_b2")
    contract = ReadyForReGateContract.parse_from_text(c_text)

    # Simulate issue comment already exists on Issue #1 with deterministic marker
    marker = "<!-- REVIEW_MARKER: CODE_SHA=c0de111 EVIDENCE_ID=gen_win_b2 -->"
    gh.posted_comments = [{
        "id": "comment_already_posted_555",
        "issue_number": 1,
        "body": f"## SUPERVISOR_REVIEW_COMPLETE\nDECISION=ACCEPT_WITH_SCOPE\n{marker}",
    }]

    res = engine.handle_ready_contract(contract)
    assert res["status"] == "COMPLETED"
    # Ensure that no new comment was posted
    assert len(gh.posted_comments) == 1
    # Check that the review record has adopted the existing comment ID
    state_mgr: StateManager = env_setup["state_mgr"]
    rev = state_mgr.get_review_by_contract("c0de111", "gen_win_b2")
    assert rev is not None
    assert rev["issue_comment_id"] == "comment_already_posted_555"


# 34. Blocker C: Git preflight rejects detached HEAD, mismatch, and dirty tree
def test_34_git_preflight_rejections(tmp_path: Path, monkeypatch):
    import subprocess
    cfg = SupervisorConfig(
        mode="live",
        repo_root=tmp_path,
        webhook_secret="strong-live-secret-12345",
        github_token="fake-token",
        allowed_senders=("netfox-web",),
        ai_provider="semantic_evidence",
    )
    client = GitHubClient(cfg)

    # Scenario 1: Dirty working tree
    def mock_dirty_tree(cmd, *args, **kwargs):
        if "status" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=" M dirty_file.py\n")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
    monkeypatch.setattr(subprocess, "run", mock_dirty_tree)
    with pytest.raises(GitHubVerificationError, match="Refusing to commit instruction on a dirty working tree"):
        client.commit_instruction_file("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", "content", "msg")

    # Scenario 2: Staged uncommitted changes (diff-index != 0)
    def mock_dirty_index(cmd, *args, **kwargs):
        if "status" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
        if "diff-index" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
    monkeypatch.setattr(subprocess, "run", mock_dirty_index)
    with pytest.raises(GitHubVerificationError, match="staged or unstaged changes exist"):
        client.commit_instruction_file("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", "content", "msg")

    # Scenario 3: Detached HEAD
    def mock_detached_head(cmd, *args, **kwargs):
        if "status" in cmd or "diff-index" in cmd or "fetch" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="HEAD\n")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
    monkeypatch.setattr(subprocess, "run", mock_detached_head)
    with pytest.raises(GitHubVerificationError, match="detached HEAD forbidden"):
        client.commit_instruction_file("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", "content", "msg")

    # Scenario 4: Local HEAD mismatch with origin/main
    def mock_mismatch_head(cmd, *args, **kwargs):
        if "status" in cmd or "diff-index" in cmd or "fetch" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
        if "rev-parse" in cmd and "--abbrev-ref" in cmd:
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="main\n")
        if "rev-parse" in cmd and cmd[-1] == "HEAD":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="sha_local_aaa\n")
        if "rev-parse" in cmd and cmd[-1] == "origin/main":
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="sha_remote_bbb\n")
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="")
    monkeypatch.setattr(subprocess, "run", mock_mismatch_head)
    with pytest.raises(GitHubVerificationError, match="does not match origin/main"):
        client.commit_instruction_file("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", "content", "msg")


# 35. Blocker D: Provider factory, stale progress report, and live preflight rules
def test_35_provider_factory_and_stale_lineage(tmp_path: Path):
    # Provider factory requires API key for openai/anthropic/gemini
    cfg_openai_nokey = SupervisorConfig(ai_provider="openai", ai_api_key="")
    with pytest.raises(ConfigValidationError, match="OPENAI_API_KEY is required"):
        create_supervisor_adapter(cfg_openai_nokey)

    # Provider factory succeeds with key
    cfg_openai_withkey = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test12345")
    adapter_openai = create_supervisor_adapter(cfg_openai_withkey)
    assert adapter_openai is not None

    # Stale progress report (missing code_sha or instruction_sha) fails closed
    adapter = SemanticEvidenceSupervisorAdapter()
    c_text = valid_contract_text(code_sha="c0de999", instruction_sha="instr_888", evidence_id="gen_stale")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    context_stale = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text="# Progress Report\nCODE: wrong_code_111\nINSTRUCTION: wrong_instr_222\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res = adapter.review_repository(context_stale)
    assert res.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("Progress report lineage mismatch" in b for b in res.blockers)

    # Empty diff fails closed
    context_nodiff = ReviewContext(
        contract=contract,
        diffs="",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res_nodiff = adapter.review_repository(context_nodiff)
    assert res_nodiff.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("diff is empty" in b for b in res_nodiff.blockers)

    # In live mode, SemanticEvidenceSupervisorAdapter cannot unilaterally issue ACCEPT_WITH_SCOPE
    adapter_live = SemanticEvidenceSupervisorAdapter(is_live=True)
    context_valid = ReviewContext(
        contract=contract,
        diffs="valid diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res_live = adapter_live.review_repository(context_valid)
    assert res_live.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("cannot unilaterally issue ACCEPT_WITH_SCOPE" in b for b in res_live.blockers)


# 36. Blocker A: OpenAI provider executes real HTTP request with mock transport and schema validation
def test_36_openai_provider_real_http_request(tmp_path: Path):
    requests_captured = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        requests_captured.append(request)
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": ["Real Blender OptiX execution evidence verified"],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": ["Real Blender Cycles OptiX"], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "# Next Phase Instructions",
            "issueCommentMarkdown": "## SUPERVISOR_REVIEW_COMPLETE\nDECISION=ACCEPT_WITH_SCOPE",
        })
        body = json.dumps({"choices": [{"message": {"content": content}}]})
        return httpx.Response(200, content=body.encode("utf-8"))

    transport = httpx.MockTransport(mock_handler)
    cfg = SupervisorConfig(ai_provider="openai", ai_api_key="sk-real-key-12345")
    adapter = create_supervisor_adapter(cfg, transport=transport)

    c_text = valid_contract_text(code_sha="c0de111", instruction_sha="instr_000", evidence_id="gen_001")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    context = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )

    res = adapter.review_repository(context)
    assert res.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert len(requests_captured) == 1
    assert str(requests_captured[0].url) == "https://api.openai.com/v1/chat/completions"
    assert "Bearer sk-real-key-12345" in requests_captured[0].headers["Authorization"]


# 37. Blocker A: Anthropic and Gemini provider execution with mock transport
def test_37_anthropic_and_gemini_provider_execution():
    anthropic_reqs = []
    def anthropic_handler(request: httpx.Request) -> httpx.Response:
        anthropic_reqs.append(request)
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": ["Anthropic verified claims"],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": ["Real Blender Cycles OptiX"], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "# Anthropic Next",
            "issueCommentMarkdown": "## Anthropic Review Complete",
        })
        return httpx.Response(200, json={"content": [{"text": content}]})

    cfg_anthropic = SupervisorConfig(ai_provider="anthropic", ai_api_key="sk-ant-test")
    adapter_ant = create_supervisor_adapter(cfg_anthropic, transport=httpx.MockTransport(anthropic_handler))

    c_text = valid_contract_text(code_sha="c0de111", instruction_sha="instr_000", evidence_id="gen_001")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    context = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res_ant = adapter_ant.review_repository(context)
    assert res_ant.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert len(anthropic_reqs) == 1
    assert "api.anthropic.com" in str(anthropic_reqs[0].url)
    assert anthropic_reqs[0].headers["x-api-key"] == "sk-ant-test"

    # Gemini
    gemini_reqs = []
    def gemini_handler(request: httpx.Request) -> httpx.Response:
        gemini_reqs.append(request)
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": ["Gemini verified"],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": ["Real Blender Cycles OptiX"], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "# Gemini Next",
            "issueCommentMarkdown": "## Gemini Review Complete",
        })
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": content}]}}]})

    cfg_gemini = SupervisorConfig(ai_provider="gemini", ai_api_key="sk-gem-test")
    adapter_gem = create_supervisor_adapter(cfg_gemini, transport=httpx.MockTransport(gemini_handler))
    res_gem = adapter_gem.review_repository(context)
    assert res_gem.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert len(gemini_reqs) == 1
    assert "generativelanguage.googleapis.com" in str(gemini_reqs[0].url)


# 38. Blocker A: Provider malformed JSON fails closed with CHANGES_REQUIRED
def test_38_provider_malformed_json_fails_closed():
    def bad_json_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "Not JSON at all, error!"}}]})

    cfg = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test-bad")
    adapter = create_supervisor_adapter(cfg, transport=httpx.MockTransport(bad_json_handler))

    c_text = valid_contract_text(code_sha="c0de111", instruction_sha="instr_000", evidence_id="gen_001")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    context = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res = adapter.review_repository(context)
    assert res.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("schema validation failed" in b for b in res.blockers)


# 39. Blocker A: Provider mismatched reviewed SHA or evidence ID fails closed
def test_39_provider_mismatched_sha_fails_closed():
    def wrong_sha_handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de999",  # Mismatched SHA!
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_wrong",  # Mismatched ID!
            "acceptedClaims": [],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": [], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    cfg = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test-wrong")
    adapter = create_supervisor_adapter(cfg, transport=httpx.MockTransport(wrong_sha_handler))

    c_text = valid_contract_text(code_sha="c0de111", instruction_sha="instr_000", evidence_id="gen_001")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    context = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res = adapter.review_repository(context)
    assert res.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("mismatched reviewedCodeSha" in b for b in res.blockers)


# 40. Blocker A: Provider timeout or 500 fails closed without crashing
def test_40_provider_500_or_timeout_fails_closed():
    def error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"Internal Server Error")

    cfg = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test-err")
    adapter = create_supervisor_adapter(cfg, transport=httpx.MockTransport(error_handler))

    c_text = valid_contract_text(code_sha="c0de111", instruction_sha="instr_000", evidence_id="gen_001")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    context = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res = adapter.review_repository(context)
    assert res.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("Provider openai request failed" in b for b in res.blockers)


# 41. Blocker A: Deterministic preflight rejection skips provider call
def test_41_preflight_rejection_skips_provider():
    called = []
    def handler(request: httpx.Request) -> httpx.Response:
        called.append(True)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    cfg = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test-skip")
    adapter = create_supervisor_adapter(cfg, transport=httpx.MockTransport(handler))

    # Contract claims both real_blender and used_mock -> Contradiction fails preflight!
    c_text = valid_contract_text(code_sha="c0de111", real_blender=True, used_mock=True)
    contract = ReadyForReGateContract.parse_from_text(c_text)
    context = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res = adapter.review_repository(context)
    assert res.decision == ReviewDecision.CHANGES_REQUIRED
    # Assert provider was never called!
    assert len(called) == 0


# 42. Blocker D: Provider cannot promote mock execution to REAL
def test_42_provider_cannot_promote_mock_to_real():
    def mock_promo_handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": [],
            "rejectedClaims": [],
            # Maliciously claiming REAL even though contract used_mock=True!
            "truthMatrix": {"REAL": ["Real Blender Cycles OptiX"], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    cfg = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test-promo")
    adapter = create_supervisor_adapter(cfg, transport=httpx.MockTransport(mock_promo_handler))

    c_text = valid_contract_text(code_sha="c0de111", instruction_sha="instr_000", evidence_id="gen_001", real_blender=False, used_mock=True)
    contract = ReadyForReGateContract.parse_from_text(c_text)
    context = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nMock verified",
        acceptance_text="# Acceptance\nMock rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res = adapter.review_repository(context)
    assert res.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("promoted mock execution" in b for b in res.blockers)


# 43. Blocker C: Dual-CI contract validation rejects mismatched or incomplete CI runs
def test_43_dual_ci_contract_validation(env_setup):
    engine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    # Scenario 1: docs CI run passed into CODE_CI_RUN_ID -> reject
    c1_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", code_ci_run_id="run_docs_ok", docs_ci_run_id="run_docs_ok")
    contract1 = ReadyForReGateContract.parse_from_text(c1_text)
    with pytest.raises(GitHubVerificationError, match="!=|head_sha|does not match"):
        engine.handle_ready_contract(contract1)

    # Scenario 2: code CI run passed into DOCS_CI_RUN_ID -> reject
    c2_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", code_ci_run_id="run_ok", docs_ci_run_id="run_ok")
    contract2 = ReadyForReGateContract.parse_from_text(c2_text)
    with pytest.raises(GitHubVerificationError, match="!=|head_sha|does not match"):
        engine.handle_ready_contract(contract2)

    # Scenario 3: Live mode requires explicit DOCS_CI_RUN_ID
    cfg_live = SupervisorConfig(mode="live", repo_root=env_setup["config"].repo_root)
    engine_live = SupervisorEngine(
        config=cfg_live,
        state_mgr=env_setup["state_mgr"],
        github_client=gh,
        ai_adapter=env_setup["ai_adapter"],
        policy_engine=env_setup["policy_engine"],
    )
    c3_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", code_ci_run_id="run_ok", docs_ci_run_id="")
    contract3 = ReadyForReGateContract.parse_from_text(c3_text)
    with pytest.raises(GitHubVerificationError, match="Live mode requires explicit DOCS_CI_RUN_ID"):
        engine_live.handle_ready_contract(contract3)

    # Scenario 4: Windows failure/missing in CI run -> reject
    gh.ci_runs["run_code_no_win"] = {
        "head_sha": "c0de111",
        "status": "completed",
        "conclusion": "failure",
        "jobs": [
            {"name": "unit (ubuntu-latest)", "conclusion": "success"},
            {"name": "unit (windows-latest)", "conclusion": "failure"},
        ],
    }
    c4_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", code_ci_run_id="run_code_no_win", docs_ci_run_id="run_docs_ok")
    contract4 = ReadyForReGateContract.parse_from_text(c4_text)
    with pytest.raises(GitHubVerificationError, match="conclusion is failure|failure|does not succeed"):
        engine.handle_ready_contract(contract4)


# 44. Blocker B: Pinned stale progress report vs current exact progress report
def test_44_stale_vs_exact_progress_report():
    adapter = SemanticEvidenceSupervisorAdapter()

    # Case A: Stale report referencing old CODE 4406119 and instruction 59ad337
    stale_text = "# Progress Report\nSource instruction: 59ad337\nCODE: 4406119\nTests passed: 628"
    contract = ReadyForReGateContract.parse_from_text(valid_contract_text(code_sha="d77cfe7", instruction_sha="8b0b788"))
    context_stale = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=stale_text,
        audit_text="# Audit\nOptiX ok",
        acceptance_text="# Acceptance\nRender ok",
    )
    res_stale = adapter.review_repository(context_stale)
    assert res_stale.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("Progress report lineage mismatch" in b for b in res_stale.blockers)

    # Case B: Current exact report referencing exact d77cfe7 and 8b0b788
    exact_text = f"# Progress Report\nINSTRUCTION: {contract.instruction_sha}\nCODE: {contract.code_sha}\nTests: 733"
    context_exact = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=exact_text,
        audit_text="# Audit\nOptiX ok",
        acceptance_text="# Acceptance\nRender ok",
    )
    res_exact = adapter.review_repository(context_exact)
    assert res_exact.decision == ReviewDecision.ACCEPT_WITH_SCOPE


# 45. Blocker A: Provider mismatched reviewedDocsSha or reviewedInstructionSha fails closed
def test_45_provider_mismatched_docs_or_instruction_sha_fails_closed():
    # Sub-case 1: Wrong docs SHA
    def wrong_docs_handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "wrong_docs_sha",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": [],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": [], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    cfg = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test-docs-sha")
    adapter_docs = create_supervisor_adapter(cfg, transport=httpx.MockTransport(wrong_docs_handler))

    c_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_001")
    contract = ReadyForReGateContract.parse_from_text(c_text)
    context = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res_docs = adapter_docs.review_repository(context)
    assert res_docs.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("mismatched reviewedDocsSha" in b for b in res_docs.blockers)

    # Sub-case 2: Wrong instruction SHA
    def wrong_instr_handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "wrong_instr_sha",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": [],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": [], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    adapter_instr = create_supervisor_adapter(cfg, transport=httpx.MockTransport(wrong_instr_handler))
    res_instr = adapter_instr.review_repository(context)
    assert res_instr.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("mismatched reviewedInstructionSha" in b for b in res_instr.blockers)


# 46. Blocker B: Provider prompt includes exact instruction text, changed files manifest, and bounded completeness metadata
def test_46_provider_prompt_includes_exact_instruction_text_and_completeness_metadata():
    captured_requests = []
    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": [],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": ["Real Blender Cycles OptiX"], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    cfg = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test-prompt")
    adapter = create_supervisor_adapter(cfg, transport=httpx.MockTransport(handler))

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_001")
    )
    context = ReviewContext(
        contract=contract,
        diffs="diff --git a/services/supervisor/engine.py b/services/supervisor/engine.py\n+new line",
        changed_files=["services/supervisor/engine.py"],
        instruction_text="# Explicit instruction text from INSTRUCTION_SHA\nMust verify Blender OptiX.",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )

    res = adapter.review_repository(context)
    assert res.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert len(captured_requests) == 1
    req_body = captured_requests[0].read().decode("utf-8")
    assert "Explicit instruction text from INSTRUCTION_SHA" in req_body
    assert "=== CHANGED FILES MANIFEST ===" in req_body
    assert "services/supervisor/engine.py" in req_body
    assert "[METADATA: path=" in req_body
    assert "sha256_prefix=" in req_body
    assert "reviewedDocsSha" in req_body
    assert "reviewedInstructionSha" in req_body


# 47. Blocker C: Engine independent mismatch verification handles errors and logs without NameError
def test_47_engine_independent_mismatch_verification_safe_logging(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    # 1. Adapter returns wrong CODE SHA -> Engine catches it independently
    bad_code_adapter = MockSupervisorAdapter(
        forced_decision=ReviewDecision.ACCEPT_WITH_SCOPE,
    )
    engine.ai_adapter = bad_code_adapter

    c_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_mismatch_1")
    contract = ReadyForReGateContract.parse_from_text(c_text)

    # Force adapter to return wrong CODE SHA
    bad_code_adapter.review_repository = lambda ctx: SupervisorReviewOutput(
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        reviewed_code_sha="wrong_code_sha",
        reviewed_docs_sha="d0c5111",
        reviewed_instruction_sha="instr_000",
        reviewed_evidence_generation_id="gen_mismatch_1",
        next_instruction_markdown="# Next",
        issue_comment_markdown="## Comment",
    )
    res = engine.handle_ready_contract(contract)
    assert res["status"] == "COMPLETED"
    assert res["decision"] == "CHANGES_REQUIRED"

    # 2. Adapter returns wrong DOCS SHA -> Engine catches it independently
    bad_docs_adapter = MockSupervisorAdapter()
    bad_docs_adapter.review_repository = lambda ctx: SupervisorReviewOutput(
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        reviewed_code_sha="c0de111",
        reviewed_docs_sha="wrong_docs_sha",
        reviewed_instruction_sha="instr_000",
        reviewed_evidence_generation_id="gen_mismatch_2",
        next_instruction_markdown="# Next",
        issue_comment_markdown="## Comment",
    )
    engine.ai_adapter = bad_docs_adapter
    c_text2 = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_mismatch_2")
    res2 = engine.handle_ready_contract(ReadyForReGateContract.parse_from_text(c_text2))
    assert res2["decision"] == "CHANGES_REQUIRED"

    # 3. Adapter returns wrong INSTRUCTION SHA -> Engine catches it independently
    bad_instr_adapter = MockSupervisorAdapter()
    bad_instr_adapter.review_repository = lambda ctx: SupervisorReviewOutput(
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        reviewed_code_sha="c0de111",
        reviewed_docs_sha="d0c5111",
        reviewed_instruction_sha="wrong_instr_sha",
        reviewed_evidence_generation_id="gen_mismatch_3",
        next_instruction_markdown="# Next",
        issue_comment_markdown="## Comment",
    )
    engine.ai_adapter = bad_instr_adapter
    c_text3 = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_mismatch_3")
    res3 = engine.handle_ready_contract(ReadyForReGateContract.parse_from_text(c_text3))
    assert res3["decision"] == "CHANGES_REQUIRED"

    # 4. Adapter promotes mock to REAL -> Engine downgrades to CHANGES_REQUIRED
    promo_adapter = MockSupervisorAdapter()
    promo_adapter.review_repository = lambda ctx: SupervisorReviewOutput(
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        reviewed_code_sha="c0de111",
        reviewed_docs_sha="d0c5111",
        reviewed_instruction_sha="instr_000",
        reviewed_evidence_generation_id="gen_mismatch_4",
        truth_matrix={"REAL": ["Real Blender Cycles OptiX"]},
        next_instruction_markdown="# Next",
        issue_comment_markdown="## Comment",
    )
    engine.ai_adapter = promo_adapter
    c_text4 = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_mismatch_4", real_blender=False, used_mock=True)
    res4 = engine.handle_ready_contract(ReadyForReGateContract.parse_from_text(c_text4))
    assert res4["decision"] == "CHANGES_REQUIRED"


# 48. Blocker E: BLOCKED decision Issue comment crash window is idempotent
def test_48_blocked_decision_issue_comment_idempotency(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    blocked_adapter = MockSupervisorAdapter(
        forced_decision=ReviewDecision.BLOCKED,
        forced_blockers=["Physical machinery LIVE_CNC requested."],
        forced_comment_md="Physical machine control blocked.",
    )
    engine.ai_adapter = blocked_adapter

    # Case A: GitHub issue already has a comment with deterministic marker (Window B2 adoption)
    c_text1 = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_blocked_1")
    contract1 = ReadyForReGateContract.parse_from_text(c_text1)

    marker1 = f"<!-- REVIEW_MARKER: CODE_SHA={contract1.code_sha} EVIDENCE_ID={contract1.evidence_generation_id} REVIEW_ID=rev_crash -->"
    gh.posted_comments = [{
        "id": "existing_blocked_comment_999",
        "issue_number": 1,
        "body": f"## SUPERVISOR_REVIEW_COMPLETE\nDECISION=BLOCKED\n{marker1}\nHUMAN_APPROVAL_REQUIRED",
    }]

    initial_comment_count = len(gh.posted_comments)
    res1 = engine.handle_ready_contract(contract1)
    assert res1["status"] == "COMPLETED"
    assert res1["decision"] == "BLOCKED"
    # Adopted existing comment without posting duplicate!
    assert len(gh.posted_comments) == initial_comment_count
    rev1 = engine.state_mgr.get_review_by_contract(contract1.code_sha, contract1.evidence_generation_id)
    assert rev1 is not None
    assert rev1["issue_comment_id"] == "existing_blocked_comment_999"

    # Case B: Fresh contract posts comment with deterministic marker and records in DB
    gh.ci_runs["run_code_222"] = {
        "head_sha": "c0de222",
        "status": "completed",
        "conclusion": "success",
        "jobs": [
            {"name": "unit (ubuntu-latest)", "conclusion": "success"},
            {"name": "unit (windows-latest)", "conclusion": "success"},
        ],
    }
    gh.ci_runs["run_docs_222"] = {
        "head_sha": "d0c5222",
        "status": "completed",
        "conclusion": "success",
        "jobs": [
            {"name": "unit (ubuntu-latest)", "conclusion": "success"},
            {"name": "unit (windows-latest)", "conclusion": "success"},
        ],
    }
    c_text2 = valid_contract_text(
        code_sha="c0de222",
        docs_sha="d0c5222",
        code_ci_run_id="run_code_222",
        docs_ci_run_id="run_docs_222",
        instruction_sha="instr_000",
        evidence_id="gen_blocked_2",
    )
    contract2 = ReadyForReGateContract.parse_from_text(c_text2)

    res2 = engine.handle_ready_contract(contract2)
    assert res2["status"] == "COMPLETED"
    assert res2["decision"] == "BLOCKED"
    assert len(gh.posted_comments) == initial_comment_count + 1
    new_comment = gh.posted_comments[-1]
    assert "HUMAN_APPROVAL_REQUIRED" in new_comment["body"]
    assert f"CODE_SHA={contract2.code_sha}" in new_comment["body"]
    assert f"EVIDENCE_ID={contract2.evidence_generation_id}" in new_comment["body"]
    rev2 = engine.state_mgr.get_review_by_contract(contract2.code_sha, contract2.evidence_generation_id)
    assert rev2 is not None
    assert rev2["issue_comment_id"] == new_comment["id"]


# 49. Blocker D: Configurable SUPERVISOR_AI_MODEL is respected by adapters and recorded in audit trail
def test_49_configurable_ai_model():
    reqs_captured = []
    def handler(request: httpx.Request) -> httpx.Response:
        reqs_captured.append(request)
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": [],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": ["Real Blender Cycles OptiX"], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    cfg = SupervisorConfig(
        ai_provider="openai",
        ai_api_key="sk-test-model",
        ai_model="gpt-4o-2024-11-20",
    )
    adapter = create_supervisor_adapter(cfg, transport=httpx.MockTransport(handler))

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_001")
    )
    context = ReviewContext(
        contract=contract,
        diffs="clean diff",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )

    res = adapter.review_repository(context)
    assert res.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert len(reqs_captured) == 1
    body = json.loads(reqs_captured[0].read().decode("utf-8"))
    assert body["model"] == "gpt-4o-2024-11-20"
    assert res.audit_trail["model"] == "gpt-4o-2024-11-20"
    assert res.audit_trail["provider"] == "openai"


# 50. Blocker A: Machine-readable evidence completeness structure and truncation gate
def test_50_evidence_completeness_truncation_gate():
    def handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": [],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": ["Real Blender Cycles OptiX"], "MOCK": [], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    cfg = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test-completeness")
    adapter = create_supervisor_adapter(cfg, transport=httpx.MockTransport(handler))

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_001")
    )
    long_diff = "diff --git a/big.py b/big.py\n" + ("+line with code\n" * 600)
    context = ReviewContext(
        contract=contract,
        diffs=long_diff,
        instruction_text="Standard instruction",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        event_driven_acceptance_text="# Event Driven Acceptance",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )

    res = adapter.review_repository(context)
    assert res.decision == ReviewDecision.CHANGES_REQUIRED
    assert any("truncated without full completeness coverage" in b for b in res.blockers)
    assert "completeness" in res.audit_trail
    diff_comp = next(c for c in res.audit_trail["completeness"] if c["path"] == "git diff")
    assert diff_comp["truncated"] is True
    assert diff_comp["critical"] is True
    assert diff_comp["original_chars"] > 8000
    assert diff_comp["supplied_chars"] == 8000

    context2 = ReviewContext(
        contract=contract,
        diffs="small diff within budget",
        instruction_text="Standard instruction within budget",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        event_driven_acceptance_text="# Event Driven Acceptance",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )
    res2 = adapter.review_repository(context2)
    assert res2.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert all(not c["truncated"] for c in res2.audit_trail["completeness"])


# 51. Blocker A: Changed-files manifest status parsing (A/M/D/R) and engine omission detection
def test_51_changed_files_manifest_status_and_omission_detection():
    sample_diff = """diff --git a/services/supervisor/new_file.py b/services/supervisor/new_file.py
new file mode 100644
index 0000000..1234567
--- /dev/null
+++ b/services/supervisor/new_file.py
@@ -0,0 +1,5 @@
+new code
diff --git a/services/supervisor/engine.py b/services/supervisor/engine.py
index 1111111..2222222 100644
--- a/services/supervisor/engine.py
+++ b/services/supervisor/engine.py
@@ -1,3 +1,4 @@
+modified line
diff --git a/old_module.py b/old_module.py
deleted file mode 100644
--- a/old_module.py
+++ /dev/null
@@ -1,5 +0,0 @@
-deleted
diff --git a/old_name.py b/new_name.py
similarity index 100%
rename from old_name.py
rename to new_name.py
"""
    items = parse_diff_changed_files(sample_diff)
    status_map = {item.path: item for item in items}
    assert "services/supervisor/new_file.py" in status_map
    assert status_map["services/supervisor/new_file.py"].status == "A"
    assert status_map["services/supervisor/engine.py"].status == "M"
    assert status_map["old_module.py"].status == "D"
    assert status_map["new_name.py"].status.startswith("R")
    assert status_map["new_name.py"].old_path == "old_name.py"
    assert "R old_name.py -> new_name.py" in status_map["new_name.py"].format_entry()

    actual_diff_paths = {item.path for item in items}
    omitted = actual_diff_paths - {"services/supervisor/new_file.py", "services/supervisor/engine.py", "old_module.py"}
    assert "new_name.py" in omitted


# 52. Blocker B: Pinned evidence fetching fails closed before AI provider call
def test_52_fail_closed_pinned_evidence_fetch(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    provider_called = []
    class GuardedAdapter(SupervisorProviderAdapter):
        def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
            provider_called.append(True)
            return SupervisorReviewOutput(
                decision=ReviewDecision.ACCEPT_WITH_SCOPE,
                reviewed_code_sha=context.contract.code_sha,
                reviewed_docs_sha=context.contract.docs_sha,
                reviewed_instruction_sha=context.contract.instruction_sha,
                reviewed_evidence_generation_id=context.contract.evidence_generation_id,
                next_instruction_markdown="# Next Instructions",
                issue_comment_markdown="## Review Passed",
            )

    engine.ai_adapter = GuardedAdapter()

    # Case 1: Pinned instruction text is 404/missing
    gh.files.pop("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", None)
    c1 = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_001")
    )
    res1 = engine.handle_ready_contract(c1)
    assert res1["status"] == "COMPLETED"
    assert res1["decision"] == "CHANGES_REQUIRED"
    assert len(provider_called) == 0

    # Case 2: Pinned progress report is empty
    gh.files["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = "# Pinned Instructions"
    gh.files["docs/GROK_PROGRESS_REPORT.md"] = "   \n  "
    c2 = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_002")
    )
    res2 = engine.handle_ready_contract(c2)
    assert res2["decision"] == "CHANGES_REQUIRED"
    assert len(provider_called) == 0

    # Case 3: Pinned implementation audit is missing
    gh.files["docs/GROK_PROGRESS_REPORT.md"] = "# Valid Progress Report"
    gh.files.pop("docs/CURRENT_IMPLEMENTATION_AUDIT.md", None)
    c3 = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_003")
    )
    res3 = engine.handle_ready_contract(c3)
    assert res3["decision"] == "CHANGES_REQUIRED"
    assert len(provider_called) == 0

    # Case 4: Supervisor acceptance report missing
    gh.files["docs/CURRENT_IMPLEMENTATION_AUDIT.md"] = "# Audit OK"
    gh.files.pop("docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md", None)
    c4 = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_004")
    )
    res4 = engine.handle_ready_contract(c4)
    assert res4["decision"] == "CHANGES_REQUIRED"
    assert len(provider_called) == 0

    # Case 5: All required present, optional cabinet missing -> succeeds and calls provider
    gh.files["docs/EVENT_DRIVEN_SUPERVISOR_ACCEPTANCE.md"] = "# Supervisor Acceptance OK"
    gh.files.pop("docs/CABINET_REAL_ACCEPTANCE.md", None)
    c5 = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_005")
    )
    res5 = engine.handle_ready_contract(c5)
    assert len(provider_called) == 1
    assert res5["decision"] == "ACCEPT_WITH_SCOPE"


# 53. Blocker C: Window B1 exact 5-trailer and content marker matching with evidence isolation
def test_53_window_b1_multi_trailer_and_marker_isolation(env_setup):
    gh: MockGitHubClient = env_setup["github_client"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_target")
    )
    review_id = "rev_test_53"

    commit_a_msg = (
        f"supervisor: accept {contract.code_sha[:7]} and start next-phase\n\n"
        f"Reviewed-Code-Sha: {contract.code_sha}\n"
        f"Reviewed-Docs-Sha: {contract.docs_sha}\n"
        f"Reviewed-Instruction-Sha: {contract.instruction_sha}\n"
        f"Reviewed-Evidence-Id: gen_other_evidence\n"
        f"Supervisor-Decision: ACCEPT_WITH_SCOPE\n"
        f"Supervisor-Review-Id: {review_id}"
    )
    gh.commits_log = [{"sha": "commit_sha_a", "commit": {"message": commit_a_msg}}]
    gh.files["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = f"<!-- SUPERVISOR_COMMIT_IDENTITY:\nCODE_SHA={contract.code_sha}\nDOCS_SHA={contract.docs_sha}\nINSTRUCTION_SHA={contract.instruction_sha}\nEVIDENCE_GENERATION_ID=gen_other_evidence\nDECISION=ACCEPT_WITH_SCOPE\nREVIEW_ID={review_id}\n-->"

    candidates = []
    for c in gh.commits_log:
        msg = c.get("commit", {}).get("message", "")
        if f"Reviewed-Code-Sha: {contract.code_sha}" in msg and f"Reviewed-Evidence-Id: {contract.evidence_generation_id}" in msg:
            candidates.append(c["sha"])
    assert len(candidates) == 0

    commit_b_msg = (
        f"supervisor: accept {contract.code_sha[:7]} and start next-phase\n\n"
        f"Reviewed-Code-Sha: {contract.code_sha}\n"
        f"Reviewed-Docs-Sha: {contract.docs_sha}\n"
        f"Reviewed-Instruction-Sha: {contract.instruction_sha}\n"
        f"Reviewed-Evidence-Id: {contract.evidence_generation_id}\n"
        f"Supervisor-Decision: ACCEPT_WITH_SCOPE\n"
        f"Supervisor-Review-Id: {review_id}"
    )
    gh.commits_log = [{"sha": "commit_sha_b", "commit": {"message": commit_b_msg}}]
    gh.files["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = (
        f"# Content\n\n<!-- SUPERVISOR_COMMIT_IDENTITY:\n"
        f"CODE_SHA={contract.code_sha}\n"
        f"DOCS_SHA={contract.docs_sha}\n"
        f"INSTRUCTION_SHA={contract.instruction_sha}\n"
        f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n"
        f"DECISION=ACCEPT_WITH_SCOPE\n"
        f"REVIEW_ID={review_id}\n-->\n"
    )

    matching_candidates = []
    for c in gh.commits_log:
        msg = c.get("commit", {}).get("message", "")
        if (
            f"Reviewed-Code-Sha: {contract.code_sha}" in msg
            and f"Reviewed-Docs-Sha: {contract.docs_sha}" in msg
            and f"Reviewed-Instruction-Sha: {contract.instruction_sha}" in msg
            and f"Reviewed-Evidence-Id: {contract.evidence_generation_id}" in msg
            and f"Supervisor-Decision: ACCEPT_WITH_SCOPE" in msg
        ):
            blob_content = gh.get_file_content("docs/GROK_NEXT_PHASE_INSTRUCTIONS.md", ref=c["sha"])
            if (
                f"CODE_SHA={contract.code_sha}" in blob_content
                and f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}" in blob_content
            ):
                matching_candidates.append(c["sha"])
    assert len(matching_candidates) == 1
    assert matching_candidates[0] == "commit_sha_b"


# 54. Blocker C: Multiple matching Window B1 candidates fails closed
def test_54_window_b1_multiple_matching_candidates_fails_closed(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_dup",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    review_id = "rev_dup"
    commit_msg = (
        f"supervisor: accept {contract.code_sha[:7]} and start next-phase\n\n"
        f"Reviewed-Code-Sha: {contract.code_sha}\n"
        f"Reviewed-Docs-Sha: {contract.docs_sha}\n"
        f"Reviewed-Instruction-Sha: {contract.instruction_sha}\n"
        f"Reviewed-Evidence-Id: {contract.evidence_generation_id}\n"
        f"Supervisor-Decision: ACCEPT_WITH_SCOPE\n"
        f"Supervisor-Review-Id: {review_id}"
    )
    next_md = (
        f"# Phase Re-Gate: Accepted With Scope\n\n"
        f"CODE `{contract.code_sha[:7]}` and DOCS `{contract.docs_sha[:7]}` accepted.\n\n"
        f"## Next Phase Scope\n"
        f"- Continue autonomous pipeline execution.\n"
        f"- Maintain dual-platform CI pass (Ubuntu + Windows).\n"
        f"- Retain truth boundaries: no live CNC/laser/PLC.\n"
    )
    content_marker = (
        f"\n\n<!-- SUPERVISOR_COMMIT_IDENTITY:\n"
        f"CODE_SHA={contract.code_sha}\n"
        f"DOCS_SHA={contract.docs_sha}\n"
        f"INSTRUCTION_SHA={contract.instruction_sha}\n"
        f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n"
        f"DECISION=ACCEPT_WITH_SCOPE\n"
        f"REVIEW_ID={review_id}\n"
        f"-->\n"
    )
    full_content = next_md + content_marker
    gh.files["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = full_content
    gh.files["docs/REAL_E2E_ACCEPTANCE.md"] = "# Real E2E OK\nOptiX Cycles verified"
    gh.files["docs/GROK_PROGRESS_REPORT.md"] = f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628"

    gh.commits_log = [
        {"sha": "candidate_1", "message": commit_msg, "commit": {"message": commit_msg}},
        {"sha": "candidate_2", "message": commit_msg, "commit": {"message": commit_msg}},
    ]

    with pytest.raises(GitHubVerificationError, match="Multiple matching remote instruction commits found"):
        engine._execute_review(review_id, contract)


# 55. Blocker D: Strict boolean parsing and 40-character hex SHA validation
def test_55_contract_strict_boolean_and_hex_sha_validation():
    base_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_001")

    text_bad_mock = base_text.replace("USED_MOCK=false", "USED_MOCK=tru")
    assert ReadyForReGateContract.parse_from_text(text_bad_mock) is None

    text_bad_blender = base_text.replace("REAL_BLENDER=true", "REAL_BLENDER=maybe")
    assert ReadyForReGateContract.parse_from_text(text_bad_blender) is None

    text_bad_test = base_text.replace("TEST_COUNT=628", "TEST_COUNT=-1")
    assert ReadyForReGateContract.parse_from_text(text_bad_test) is None

    text_non_int = base_text.replace("TEST_COUNT=628", "TEST_COUNT=six_hundred")
    assert ReadyForReGateContract.parse_from_text(text_non_int) is None

    c_short = ReadyForReGateContract.parse_from_text(base_text)
    assert c_short is not None
    with pytest.raises(ValueError, match="must be 40-character hex"):
        c_short.validate_strict(strict_sha=True)

    c_non_hex = ReadyForReGateContract.parse_from_text(
        base_text.replace("CODE_SHA=c0de111", "CODE_SHA=zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz")
    )
    assert c_non_hex is not None
    with pytest.raises(ValueError, match="must be 40-character hex"):
        c_non_hex.validate_strict(strict_sha=True)

    valid_40_code = "1111111111222222222233333333334444444444"
    valid_40_docs = "5555555555666666666677777777778888888888"
    valid_40_instr = "9999999999000000000011111111112222222222"
    text_40 = valid_contract_text(
        code_sha=valid_40_code,
        docs_sha=valid_40_docs,
        instruction_sha=valid_40_instr,
        code_ci_run_id="34775155653",
        docs_ci_run_id="34776279326",
    )
    c_valid = ReadyForReGateContract.parse_from_text(text_40)
    assert c_valid is not None
    c_valid.validate_strict(is_live=True, strict_sha=True)

    c_valid.code_ci_run_id = "not_digits"
    with pytest.raises(ValueError, match="positive numeric integer"):
        c_valid.validate_strict(is_live=True, strict_sha=True)


# 56. Blocker D: Live mode SUPERVISOR_AI_MODEL configuration validation
def test_56_live_mode_model_config_validation(tmp_path: Path):
    db_path = tmp_path / "supervisor.db"
    audit_path = tmp_path / "audit.log"

    cfg_blank = SupervisorConfig(
        mode="live",
        webhook_secret="strong-live-webhook-secret-12345",
        github_token="ghp_mock_live_token_12345",
        ai_provider="openai",
        ai_api_key="sk-test-live",
        ai_model="   ",
        repo_root=tmp_path,
        state_db_path=db_path,
        audit_log_path=audit_path,
    )
    with pytest.raises(ConfigValidationError, match="requires non-empty ai_model / SUPERVISOR_AI_MODEL"):
        validate_live_config(cfg_blank)

    cfg_mismatch = SupervisorConfig(
        mode="live",
        webhook_secret="strong-live-webhook-secret-12345",
        github_token="ghp_mock_live_token_12345",
        ai_provider="openai",
        ai_api_key="sk-test-live",
        ai_model="claude-3-5-sonnet-20241022",
        repo_root=tmp_path,
        state_db_path=db_path,
        audit_log_path=audit_path,
    )
    with pytest.raises(ConfigValidationError, match="Invalid model.*for provider 'openai'"):
        validate_live_config(cfg_mismatch)

    for provider, model in [
        ("openai", "gpt-4o"),
        ("anthropic", "claude-3-5-sonnet-20241022"),
        ("gemini", "gemini-1.5-pro"),
    ]:
        cfg_ok = SupervisorConfig(
            mode="live",
            webhook_secret="strong-live-webhook-secret-12345",
            github_token="ghp_mock_live_token_12345",
            admin_key="admin-key-16-characters-min",
            ai_provider=provider,
            ai_api_key="sk-valid",
            ai_model=model,
            repo_root=tmp_path,
            state_db_path=db_path,
            audit_log_path=audit_path,
        )
        validate_live_config(cfg_ok)


# 57. Blocker A: Exact 6-field trailer enforcement for Window B1 adoption
def test_57_window_b1_exact_6_trailer_enforcement(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_trailers",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    review_id = "rev_trailers_test"
    valid_trailers = {
        "reviewed-code-sha": contract.code_sha,
        "reviewed-docs-sha": contract.docs_sha,
        "reviewed-instruction-sha": contract.instruction_sha,
        "reviewed-evidence-id": contract.evidence_generation_id,
        "supervisor-decision": "ACCEPT_WITH_SCOPE",
        "supervisor-review-id": review_id,
    }

    # 1. Short CODE SHA only + evidence ID -> reject
    short_msg = f"supervisor: accept c0de111\n\nReviewed: {contract.code_sha[:7]}\nEvidence-ID: {contract.evidence_generation_id}"
    assert not engine._verify_instruction_candidate(
        candidate_sha="cand_short",
        commit_msg=short_msg,
        contract=contract,
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        review_id=review_id,
        intended_digest=None,
    )

    # 2. Missing any trailer of the 6 -> reject
    for missing_key in valid_trailers.keys():
        subset = {k: v for k, v in valid_trailers.items() if k != missing_key}
        partial_msg = "supervisor: commit\n\n" + "\n".join(f"{k.title()}: {v}" for k, v in subset.items())
        assert not engine._verify_instruction_candidate(
            candidate_sha=f"cand_missing_{missing_key}",
            commit_msg=partial_msg,
            contract=contract,
            decision=ReviewDecision.ACCEPT_WITH_SCOPE,
            review_id=review_id,
            intended_digest=None,
        )

    # 3. Forged commit message with full trailers but incomplete blob markers -> reject
    full_msg = "supervisor: accept\n\n" + "\n".join(f"{k}: {v}" for k, v in valid_trailers.items())
    gh.files["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = f"<!-- INCOMPLETE: CODE_SHA={contract.code_sha} -->"
    assert not engine._verify_instruction_candidate(
        candidate_sha="cand_forged",
        commit_msg=full_msg,
        contract=contract,
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        review_id=review_id,
        intended_digest=None,
    )


# 58. Blocker A: Remote blob fetch exception, empty blob, and SHA256 content digest authority
def test_58_window_b1_blob_fetch_error_and_digest_authority(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_digest",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    review_id = "rev_digest_test"
    trailers_str = (
        f"\n\nReviewed-Code-Sha: {contract.code_sha}\n"
        f"Reviewed-Docs-Sha: {contract.docs_sha}\n"
        f"Reviewed-Instruction-Sha: {contract.instruction_sha}\n"
        f"Reviewed-Evidence-Id: {contract.evidence_generation_id}\n"
        f"Supervisor-Decision: ACCEPT_WITH_SCOPE\n"
        f"Supervisor-Review-Id: {review_id}"
    )
    commit_msg = f"supervisor: accept {contract.code_sha[:7]}{trailers_str}"

    blob_marker = (
        f"\n\n<!-- SUPERVISOR_COMMIT_IDENTITY:\n"
        f"CODE_SHA={contract.code_sha}\n"
        f"DOCS_SHA={contract.docs_sha}\n"
        f"INSTRUCTION_SHA={contract.instruction_sha}\n"
        f"EVIDENCE_GENERATION_ID={contract.evidence_generation_id}\n"
        f"DECISION={output.decision.value if False else 'ACCEPT_WITH_SCOPE'}\n"
        f"REVIEW_ID={review_id}\n"
        f"-->\n"
    )
    matching_content = f"# Phase Instructions\nValid content{blob_marker}"
    intended_digest = hashlib.sha256(matching_content.encode("utf-8")).hexdigest()

    # 1. Blob fetch throws exception -> fails closed (rejects candidate)
    original_get_content = gh.get_file_content
    def raise_on_blob(path, ref="main"):
        if path == "docs/GROK_NEXT_PHASE_INSTRUCTIONS.md":
            raise RuntimeError("Network timeout fetching blob")
        return original_get_content(path, ref=ref)
    gh.get_file_content = raise_on_blob

    assert not engine._verify_instruction_candidate(
        candidate_sha="cand_err",
        commit_msg=commit_msg,
        contract=contract,
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        review_id=review_id,
        intended_digest=intended_digest,
    )
    gh.get_file_content = original_get_content

    # 2. Blob is empty -> reject
    gh.files["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = "   \n"
    assert not engine._verify_instruction_candidate(
        candidate_sha="cand_empty",
        commit_msg=commit_msg,
        contract=contract,
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        review_id=review_id,
        intended_digest=intended_digest,
    )

    # 3. Digest mismatch: blob contains markers but different content digest -> reject
    tampered_content = f"# Tampered Instructions\nMalicious code{blob_marker}"
    gh.files["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = tampered_content
    assert not engine._verify_instruction_candidate(
        candidate_sha="cand_tampered",
        commit_msg=commit_msg,
        contract=contract,
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        review_id=review_id,
        intended_digest=intended_digest,
    )

    # 4. Exact 6-field trailers + 6 blob markers + exact intended digest -> accept exactly once
    gh.files["docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"] = matching_content
    assert engine._verify_instruction_candidate(
        candidate_sha="cand_valid",
        commit_msg=commit_msg,
        contract=contract,
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        review_id=review_id,
        intended_digest=intended_digest,
    )


# 59. Blocker A: DB staged_sha verification and cross-adoption isolation
def test_59_window_b1_staged_sha_verification_and_isolation(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]
    state_mgr: StateManager = env_setup["state_mgr"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_staged_iso",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    review_id = "rev_staged_iso"
    state_mgr.start_review(review_id, contract.code_sha, contract.evidence_generation_id)

    # 1. DB staged_sha pointing to non-existent / invalid remote commit -> must NOT adopt
    state_mgr.set_review_staged_commit(review_id, "corrupt_staged_sha_12345")
    # commits_log doesn't contain corrupt_staged_sha_12345
    gh.files["docs/REAL_E2E_ACCEPTANCE.md"] = "# Real E2E OK\nOptiX Cycles verified"
    gh.files["docs/GROK_PROGRESS_REPORT.md"] = f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628"

    res = engine.handle_ready_contract(contract)
    assert res["status"] == "COMPLETED"
    # Corrupt staged sha was rejected and a fresh valid instruction commit was created
    assert res["new_instruction_sha"] != "corrupt_staged_sha_12345"
    assert len(gh.committed_instructions) == 1

    # 2. Cross-adoption isolation: Same CODE SHA, but candidate has different evidence ID or review ID -> reject
    other_evidence_id = "gen_different_002"
    commit_msg = (
        f"supervisor: accept {contract.code_sha[:7]}\n\n"
        f"Reviewed-Code-Sha: {contract.code_sha}\n"
        f"Reviewed-Docs-Sha: {contract.docs_sha}\n"
        f"Reviewed-Instruction-Sha: {contract.instruction_sha}\n"
        f"Reviewed-Evidence-Id: {other_evidence_id}\n"
        f"Supervisor-Decision: ACCEPT_WITH_SCOPE\n"
        f"Supervisor-Review-Id: rev_other"
    )
    assert not engine._verify_instruction_candidate(
        candidate_sha="cand_cross",
        commit_msg=commit_msg,
        contract=contract,
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        review_id=review_id,
        intended_digest=None,
    )


# 60. Blocker B: Real Blender mandatory acceptance evidence vs Product Truth fallback rejection
def test_60_real_blender_mandatory_acceptance_evidence(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_real_b",
            real_blender=True,
            used_mock=False,
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    gh.files["docs/GROK_PROGRESS_REPORT.md"] = f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628"
    # Product truth acceptance exists, but REAL_E2E_ACCEPTANCE.md is missing (404)
    gh.files["docs/PRODUCT_TRUTH_RENDER_PACK_ACCEPTANCE.md"] = "# Product Truth Pack OK"
    gh.files.pop("docs/REAL_E2E_ACCEPTANCE.md", None)

    # 1. REAL_E2E 404, Product Truth exists -> provider NOT called, fails closed to CHANGES_REQUIRED
    res = engine.handle_ready_contract(contract)
    assert res["status"] == "COMPLETED"
    assert res["decision"] == "CHANGES_REQUIRED"

    rec = env_setup["state_mgr"].get_review_by_contract(contract.code_sha, contract.evidence_generation_id)
    assert rec is not None
    assert rec["decision"] == "CHANGES_REQUIRED"
    out_obj = json.loads(rec["output_json"])
    assert any("Real Blender mandatory acceptance report" in b for b in out_obj["blockers"])

    # 2. REAL_E2E is empty -> CHANGES_REQUIRED
    gh.files["docs/REAL_E2E_ACCEPTANCE.md"] = "   \n"
    res2 = engine.handle_ready_contract(
        ReadyForReGateContract.parse_from_text(
            valid_contract_text(
                code_sha="c0de111",
                docs_sha="d0c5111",
                instruction_sha="instr_000",
                evidence_id="gen_real_empty",
                real_blender=True,
                used_mock=False,
                code_ci_run_id="run_ok",
                docs_ci_run_id="run_docs_ok",
            )
        )
    )
    assert res2["decision"] == "CHANGES_REQUIRED"
    rec2 = env_setup["state_mgr"].get_review_by_contract("c0de111", "gen_real_empty")
    assert any("Real Blender mandatory acceptance report" in b for b in json.loads(rec2["output_json"])["blockers"])

    # 3. REAL_E2E exact pinned OK -> can proceed to review
    gh.files["docs/REAL_E2E_ACCEPTANCE.md"] = "# Real E2E Acceptance\nOptiX Cycles execution verified."
    res3 = engine.handle_ready_contract(
        ReadyForReGateContract.parse_from_text(
            valid_contract_text(
                code_sha="c0de111",
                docs_sha="d0c5111",
                instruction_sha="instr_000",
                evidence_id="gen_real_ok",
                real_blender=True,
                used_mock=False,
                code_ci_run_id="run_ok",
                docs_ci_run_id="run_docs_ok",
            )
        )
    )
    assert res3["decision"] == "ACCEPT_WITH_SCOPE"


# 61. Blocker C: Authoritative changed-files manifest comparison (omission, phantom, status spoof, rename)
def test_61_authoritative_changed_files_manifest_validation(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_manifest_c",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    gh.files["docs/REAL_E2E_ACCEPTANCE.md"] = "# Real E2E OK\nOptiX Cycles verified"
    gh.files["docs/GROK_PROGRESS_REPORT.md"] = f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628"

    # Base diff text: modified services/supervisor/engine.py
    gh.diff_text = "diff --git a/services/supervisor/engine.py b/services/supervisor/engine.py\n--- a/services/supervisor/engine.py\n+++ b/services/supervisor/engine.py\n@@ -1 +1 @@\n+line\n"

    # 1. Authoritative compare has file that manifest omitted -> no ACCEPT
    gh.mock_changed_files = [
        ChangedFileItem(status="M", path="services/supervisor/engine.py"),
        ChangedFileItem(status="A", path="services/supervisor/audit.py"),
    ]
    res_omitted = engine.handle_ready_contract(contract)
    assert res_omitted["decision"] == "CHANGES_REQUIRED"
    rec_omitted = env_setup["state_mgr"].get_review_by_contract(contract.code_sha, contract.evidence_generation_id)
    assert any("omitted from manifest" in b for b in json.loads(rec_omitted["output_json"])["blockers"])

    # 2. Manifest has phantom file not present in authoritative changes -> no ACCEPT
    contract_phantom = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_manifest_phantom",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    gh.mock_changed_files = []  # Authoritative has none, but diff has engine.py
    res_phantom = engine.handle_ready_contract(contract_phantom)
    assert res_phantom["decision"] == "CHANGES_REQUIRED"
    rec_phantom = env_setup["state_mgr"].get_review_by_contract(contract_phantom.code_sha, contract_phantom.evidence_generation_id)
    assert any("phantom files" in b for b in json.loads(rec_phantom["output_json"])["blockers"])

    # 3. Status spoofing: manifest says M, authoritative says D -> no ACCEPT
    contract_status = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_manifest_status",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    gh.mock_changed_files = [
        ChangedFileItem(status="D", path="services/supervisor/engine.py"),
    ]
    res_status = engine.handle_ready_contract(contract_status)
    assert res_status["decision"] == "CHANGES_REQUIRED"
    rec_status = env_setup["state_mgr"].get_review_by_contract(contract_status.code_sha, contract_status.evidence_generation_id)
    assert any("status spoof" in b for b in json.loads(rec_status["output_json"])["blockers"])

    # 4. Rename path spoof: old_path mismatch -> no ACCEPT
    contract_rename = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_manifest_rename",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    gh.diff_text = "diff --git a/old.py b/new.py\nrename from old.py\nrename to new.py\n"
    gh.mock_changed_files = [
        ChangedFileItem(status="R", path="new.py", old_path="actual_old.py"),
    ]
    res_rename = engine.handle_ready_contract(contract_rename)
    assert res_rename["decision"] == "CHANGES_REQUIRED"
    rec_rename = env_setup["state_mgr"].get_review_by_contract(contract_rename.code_sha, contract_rename.evidence_generation_id)
    assert any("Rename path mismatch" in b for b in json.loads(rec_rename["output_json"])["blockers"])

    # Clean up mock_changed_files
    delattr(gh, "mock_changed_files")


# 62. Blocker C: Distinct CODE and DOCS diff ranges and contamination prevention
def test_62_distinct_diff_ranges_and_contamination_prevention(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_diff_ranges",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    gh.files["docs/REAL_E2E_ACCEPTANCE.md"] = "# Real E2E OK\nOptiX Cycles verified"
    gh.files["docs/GROK_PROGRESS_REPORT.md"] = f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628"

    # Simulate: CODE diff has code file + contaminated docs file from docs commit
    def get_diff_mock(base_sha, head_sha="main"):
        if head_sha == contract.code_sha:
            return "diff --git a/code.py b/code.py\n+code\ndiff --git a/docs/EXTRA.md b/docs/EXTRA.md\n+doc\n"
        return "diff --git a/docs/EXTRA.md b/docs/EXTRA.md\n+doc\n"
    gh.get_diff_between = get_diff_mock

    def get_changed_mock(base_sha, head_sha="main"):
        if head_sha == contract.code_sha:
            return [ChangedFileItem(status="M", path="code.py")]
        elif base_sha == contract.code_sha and head_sha == contract.docs_sha:
            return [ChangedFileItem(status="A", path="docs/EXTRA.md")]
        return [ChangedFileItem(status="M", path="code.py"), ChangedFileItem(status="A", path="docs/EXTRA.md")]
    gh.get_changed_files_between = get_changed_mock

    # When CODE diff range is contaminated with DOCS-only files -> fails closed
    res = engine.handle_ready_contract(contract)
    assert res["decision"] == "CHANGES_REQUIRED"
    rec = env_setup["state_mgr"].get_review_by_contract(contract.code_sha, contract.evidence_generation_id)
    assert any("CODE diff range contaminated with DOCS-only commit files" in b for b in json.loads(rec["output_json"])["blockers"])


# 63. Blocker D: Strict DOCS_CI_RUN_ID validation at contract parse boundary
def test_63_strict_docs_ci_run_id_parser_boundary():
    valid_40_code = "1111111111222222222233333333334444444444"
    valid_40_docs = "5555555555666666666677777777778888888888"
    valid_40_instr = "9999999999000000000011111111112222222222"

    text = valid_contract_text(
        code_sha=valid_40_code,
        docs_sha=valid_40_docs,
        instruction_sha=valid_40_instr,
        code_ci_run_id="34775155653",
    )
    # text has no DOCS_CI_RUN_ID

    # 1. In strict mode, missing DOCS_CI_RUN_ID returns None
    assert ReadyForReGateContract.parse_from_text(text, strict=True) is None

    # 2. Legacy CI_RUN_ID cannot substitute for DOCS_CI_RUN_ID in strict mode
    legacy_text = text + "CI_RUN_ID=34775155653\n"
    assert ReadyForReGateContract.parse_from_text(legacy_text, strict=True) is None

    # 3. Non-numeric or invalid DOCS_CI_RUN_ID -> returns None in strict mode
    bad_docs_ci = text + "DOCS_CI_RUN_ID=invalid_alpha\n"
    assert ReadyForReGateContract.parse_from_text(bad_docs_ci, strict=True) is None

    zero_docs_ci = text + "DOCS_CI_RUN_ID=0\n"
    assert ReadyForReGateContract.parse_from_text(zero_docs_ci, strict=True) is None

    # 4. Valid positive numeric DOCS_CI_RUN_ID -> parses successfully
    good_text = text + "DOCS_CI_RUN_ID=34776279326\n"
    c_good = ReadyForReGateContract.parse_from_text(good_text, strict=True)
    assert c_good is not None
    assert c_good.docs_ci_run_id == "34776279326"


# 64. Blocker D: Provider request ID and review audit trail capture
def test_64_provider_request_id_and_review_audit_trail():
    # 1. OpenAI response with id
    def openai_handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": ["OK"],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": [], "MOCK": ["All"], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={
            "id": "chatcmpl-test-openai-998877",
            "choices": [{"message": {"content": content}}],
        })

    cfg_openai = SupervisorConfig(ai_provider="openai", ai_api_key="sk-test-openai", ai_model="gpt-4o")
    adapter_openai = create_supervisor_adapter(cfg_openai, transport=httpx.MockTransport(openai_handler))

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_001")
    )
    context = ReviewContext(
        contract=contract,
        review_id="rev_audit_test_001",
        diffs="diff",
        instruction_text="instr",
        progress_report_text=f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628",
        audit_text="# Audit\nReal OptiX verified",
        acceptance_text="# Acceptance\nCycles rendered",
        event_driven_acceptance_text="# Acceptance",
        ci_summary={"conclusion": "success", "ubuntu_ok": True, "windows_ok": True},
    )

    out_openai = adapter_openai.review_repository(context)
    assert out_openai.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert out_openai.audit_trail["provider_request_id"] == "chatcmpl-test-openai-998877"
    assert out_openai.audit_trail["review_id"] == "rev_audit_test_001"
    assert out_openai.audit_trail["reviewed_code_sha"] == contract.code_sha
    assert out_openai.audit_trail["reviewed_docs_sha"] == contract.docs_sha
    assert out_openai.audit_trail["reviewed_instruction_sha"] == contract.instruction_sha
    assert out_openai.audit_trail["reviewed_evidence_generation_id"] == contract.evidence_generation_id

    # 2. Anthropic response with id
    def anthropic_handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": ["OK"],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": [], "MOCK": ["All"], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={
            "id": "msg_anthropic_test_554433",
            "content": [{"type": "text", "text": content}],
        })

    cfg_anthropic = SupervisorConfig(ai_provider="anthropic", ai_api_key="sk-test-anthropic", ai_model="claude-3-5-sonnet-20241022")
    adapter_anthropic = create_supervisor_adapter(cfg_anthropic, transport=httpx.MockTransport(anthropic_handler))
    out_anthropic = adapter_anthropic.review_repository(context)
    assert out_anthropic.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert out_anthropic.audit_trail["provider_request_id"] == "msg_anthropic_test_554433"

    # 3. Provider response without id -> audit explicitly null/unavailable
    def no_id_handler(request: httpx.Request) -> httpx.Response:
        content = json.dumps({
            "decision": "ACCEPT_WITH_SCOPE",
            "reviewedCodeSha": "c0de111",
            "reviewedDocsSha": "d0c5111",
            "reviewedInstructionSha": "instr_000",
            "reviewedEvidenceGenerationId": "gen_001",
            "acceptedClaims": ["OK"],
            "rejectedClaims": [],
            "truthMatrix": {"REAL": [], "MOCK": ["All"], "PARTIAL": [], "BLOCKED": []},
            "blockers": [],
            "nextInstructionMarkdown": "Next",
            "issueCommentMarkdown": "Comment",
        })
        return httpx.Response(200, json={
            "choices": [{"message": {"content": content}}],
        })

    adapter_no_id = create_supervisor_adapter(cfg_openai, transport=httpx.MockTransport(no_id_handler))
    out_no_id = adapter_no_id.review_repository(context)
    assert out_no_id.decision == ReviewDecision.ACCEPT_WITH_SCOPE
    assert out_no_id.audit_trail["provider_request_id"] is None


# 65. Blocker A: Real GitHubClient.get_commits_since() integration test with trailers & formatting
def test_65_real_github_client_commits_since_trailers(tmp_path: Path):
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo_dir), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test Agent"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "config", "user.email", "agent@test.local"], cwd=str(repo_dir), check=True)

    # Initial commit (base)
    f1 = repo_dir / "README.md"
    f1.write_text("# Initial", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=str(repo_dir), check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=str(repo_dir), check=True, capture_output=True)
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_dir), capture_output=True, text=True).stdout.strip()

    # Create instruction file and commit with full 6 trailers, pipes, and newlines in body
    instr_file = repo_dir / "docs" / "GROK_NEXT_PHASE_INSTRUCTIONS.md"
    instr_file.parent.mkdir(parents=True)
    full_content = (
        "# Phase 901 Instructions\n\n"
        "<!-- SUPERVISOR_COMMIT_IDENTITY:\n"
        "CODE_SHA=c0de111\n"
        "DOCS_SHA=d0c5111\n"
        "INSTRUCTION_SHA=instr_000\n"
        "EVIDENCE_GENERATION_ID=gen_001\n"
        "DECISION=ACCEPT_WITH_SCOPE\n"
        "REVIEW_ID=rev_real_client_001\n"
        "-->\n"
    )
    instr_file.write_text(full_content, encoding="utf-8")
    subprocess.run(["git", "add", "docs/GROK_NEXT_PHASE_INSTRUCTIONS.md"], cwd=str(repo_dir), check=True)

    body_with_pipes = (
        "supervisor: accept c0de111 and start next-phase\n\n"
        "This commit message has pipes | and multiple\nlines of body context | table | data.\n\n"
        "Reviewed-Code-Sha: c0de111\n"
        "Reviewed-Docs-Sha: d0c5111\n"
        "Reviewed-Instruction-Sha: instr_000\n"
        "Reviewed-Evidence-Id: gen_001\n"
        "Supervisor-Decision: ACCEPT_WITH_SCOPE\n"
        "Supervisor-Review-Id: rev_real_client_001\n"
    )
    subprocess.run(["git", "commit", "-m", body_with_pipes], cwd=str(repo_dir), check=True, capture_output=True)
    head_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_dir), capture_output=True, text=True).stdout.strip()

    # Use real GitHubClient with repo_root pointed to temp repo
    cfg = SupervisorConfig(repo_name="netfox-web/blender-autonomous-3d", repo_root=repo_dir)
    client = GitHubClient(cfg)

    commits = client.get_commits_since(base_sha, head_sha)
    assert len(commits) == 1
    commit_item = commits[0]
    assert commit_item["sha"] == head_sha
    msg = commit_item["message"]

    # Verify full message contains pipes, newlines, and all 6 trailers
    assert "pipes | and multiple" in msg
    assert "Reviewed-Code-Sha: c0de111" in msg
    assert "Reviewed-Docs-Sha: d0c5111" in msg
    assert "Reviewed-Instruction-Sha: instr_000" in msg
    assert "Reviewed-Evidence-Id: gen_001" in msg
    assert "Supervisor-Decision: ACCEPT_WITH_SCOPE" in msg
    assert "Supervisor-Review-Id: rev_real_client_001" in msg

    # Verify engine._verify_instruction_candidate can verify it using this client
    state_mgr = StateManager(tmp_path / "test_state.db")
    policy_engine = PolicyEngine(tmp_path / "audit.jsonl")
    engine = SupervisorEngine(
        config=cfg,
        github_client=client,
        state_mgr=state_mgr,
        ai_adapter=MockSupervisorAdapter(),
        policy_engine=policy_engine,
    )
    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", instruction_sha="instr_000", evidence_id="gen_001")
    )
    intended_digest = hashlib.sha256(full_content.encode("utf-8")).hexdigest()

    assert engine._verify_instruction_candidate(
        candidate_sha=head_sha,
        commit_msg=msg,
        contract=contract,
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        review_id="rev_real_client_001",
        intended_digest=intended_digest,
    )


# 66. Blocker B: Candidate discovery failure fails closed and prevents duplicate instruction commit
def test_66_candidate_discovery_failure_fails_closed(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]
    state_mgr: StateManager = env_setup["state_mgr"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_disc_fail_01",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    gh.files["docs/REAL_E2E_ACCEPTANCE.md"] = "# Real E2E OK\nOptiX Cycles verified"
    gh.files["docs/GROK_PROGRESS_REPORT.md"] = f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628"

    # 1. Staged SHA exists in DB, but remote commit discovery fails (e.g. network/git error)
    review_id = "rev_staged_disc_fail"
    state_mgr.start_review(review_id, contract.code_sha, contract.evidence_generation_id)
    state_mgr.set_review_staged_commit(review_id, "staged_candidate_sha_99")

    gh.recovery_only_error = True
    gh.commits_since_error = "Network timeout querying origin/main"
    with pytest.raises(GitHubVerificationError) as excinfo:
        engine._execute_review(review_id, contract)
    assert "remote commit discovery failed" in str(excinfo.value).lower()
    # Refuses to create a new instruction commit!
    assert len(gh.committed_instructions) == 0

    # 2. No staged commit, but remote candidate discovery fails
    contract2 = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_disc_fail_02",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    with pytest.raises(GitHubVerificationError) as excinfo2:
        engine._execute_review("rev_unstaged_disc_fail", contract2)
    assert "remote commit discovery failed" in str(excinfo2.value).lower()
    # Still 0 commits created!
    assert len(gh.committed_instructions) == 0

    if hasattr(gh, "commits_since_error"):
        delattr(gh, "commits_since_error")
    if hasattr(gh, "recovery_only_error"):
        delattr(gh, "recovery_only_error")


# 67. Blocker C: Window B2 REST fallback pagination fetches latest comments without duplicate
def test_67_window_b2_rest_fallback_pagination(tmp_path: Path):
    cfg = SupervisorConfig(
        repo_name="netfox-web/blender-autonomous-3d",
        repo_root=tmp_path,
        allowed_issue_number=1,
    )

    marker = "<!-- REVIEW_MARKER: CODE_SHA=c0de111 EVIDENCE_ID=gen_b2_page REVIEW_ID=rev_b2_page -->"

    page1_comments = [{"id": f"c_{i}", "body": f"Old comment {i}"} for i in range(1, 101)]
    page3_comments = [
        {"id": "c_201", "body": "Comment 201"},
        {"id": "c_202", "body": f"## SUPERVISOR_REVIEW_COMPLETE\n\n{marker}\nDECISION=ACCEPT_WITH_SCOPE"},
        {"id": "c_203", "body": "Comment 203"},
    ]

    client = GitHubClient(cfg)

    def transport_handler(request: httpx.Request) -> httpx.Response:
        url_str = str(request.url)
        if "page=3" in url_str:
            return httpx.Response(200, request=request, json=page3_comments, headers={
                "link": f'<{client.base_url}/repos/{cfg.repo_name}/issues/1/comments?per_page=100&page=2>; rel="prev", <{client.base_url}/repos/{cfg.repo_name}/issues/1/comments?per_page=100&page=3>; rel="last"'
            })
        elif "page=2" in url_str:
            return httpx.Response(200, request=request, json=[{"id": f"c_{i}", "body": f"Mid {i}"} for i in range(101, 201)])
        else:
            return httpx.Response(200, request=request, json=page1_comments, headers={
                "link": f'<{client.base_url}/repos/{cfg.repo_name}/issues/1/comments?per_page=100&page=2>; rel="next", <{client.base_url}/repos/{cfg.repo_name}/issues/1/comments?per_page=100&page=3>; rel="last"'
            })

    transport = httpx.MockTransport(transport_handler)

    orig_run = subprocess.run
    def mock_run(cmd, *args, **kwargs):
        if cmd[0] == "gh":
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="gh unavailable")
        return orig_run(cmd, *args, **kwargs)

    import unittest.mock as mock
    with mock.patch("subprocess.run", side_effect=mock_run):
        with mock.patch("httpx.get", side_effect=lambda url, **kw: transport.handle_request(httpx.Request("GET", url, headers=kw.get("headers")))):
            comments = client.get_latest_issue_comments(1, count=10)
            assert len(comments) == 10
            assert comments[-2]["id"] == "c_202"
            assert marker in comments[-2]["body"]


# 68. Blocker C: Issue comments fetch failure fails closed without duplicate comment
def test_68_issue_comments_failure_fails_closed(env_setup):
    engine: SupervisorEngine = env_setup["engine"]
    gh: MockGitHubClient = env_setup["github_client"]

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(
            code_sha="c0de111",
            docs_sha="d0c5111",
            instruction_sha="instr_000",
            evidence_id="gen_comm_err",
            code_ci_run_id="run_ok",
            docs_ci_run_id="run_docs_ok",
        )
    )
    gh.files["docs/REAL_E2E_ACCEPTANCE.md"] = "# Real E2E OK\nOptiX Cycles verified"
    gh.files["docs/GROK_PROGRESS_REPORT.md"] = f"# Progress Report\nCODE: {contract.code_sha}\nINSTRUCTION: {contract.instruction_sha}\nTests: 628"

    gh.comments_error = "GitHub API comments rate limited or 500 error"

    with pytest.raises(GitHubVerificationError) as excinfo:
        engine._execute_review("rev_comment_fail", contract)
    assert "rate limited or 500 error" in str(excinfo.value)
    assert len(gh.posted_comments) == 0

    delattr(gh, "comments_error")
