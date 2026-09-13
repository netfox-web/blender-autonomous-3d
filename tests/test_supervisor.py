"""Tests for Event-Driven Autonomous Supervisor Control Plane covering all 19 mandatory scenarios."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
import pytest
from fastapi.testclient import TestClient

from services.supervisor.ai_adapter import (
    ExternalProviderSupervisorAdapter,
    MockSupervisorAdapter,
    OpenAISupervisorAdapter,
    RuleBasedSupervisorAdapter,
    SemanticEvidenceSupervisorAdapter,
    create_supervisor_adapter,
)
from services.supervisor.config import ConfigValidationError, SupervisorConfig, validate_live_config
from services.supervisor.engine import SupervisorEngine
from services.supervisor.github_client import GitHubClient, GitHubClientInterface, GitHubVerificationError
from services.supervisor.main import create_app
from services.supervisor.models import (
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
        return self.commits_log

    def get_diff_between(self, base_sha: str, head_sha: str = "main") -> str:
        return getattr(self, "diff_text", "")

    def commit_instruction_file(self, file_path: str, content: str, commit_message: str, branch: str = "main") -> str:
        new_sha = f"instr_{len(self.committed_instructions) + 1:04d}"
        self.committed_instructions.append({
            "file_path": file_path,
            "content": content,
            "commit_message": commit_message,
            "sha": new_sha,
        })
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

    c_text = valid_contract_text(code_sha="c0de111", docs_sha="d0c5111", evidence_id="gen_win_b1")
    contract = ReadyForReGateContract.parse_from_text(c_text)

    # Simulate that remote origin already contains a commit matching (code_sha, evidence_generation_id)
    gh.commits_log = [{
        "sha": "remote_instr_existing_sha_999",
        "commit": {
            "message": f"supervisor: accept c0de111 and start next-phase\n\nReviewed: c0de111\nEvidence-ID: gen_win_b1"
        }
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

