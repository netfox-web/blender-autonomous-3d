"""Tests for Event-Driven Autonomous Supervisor Control Plane covering all 19 mandatory scenarios."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest
from fastapi.testclient import TestClient

from services.supervisor.ai_adapter import MockSupervisorAdapter, RuleBasedSupervisorAdapter
from services.supervisor.config import SupervisorConfig
from services.supervisor.engine import SupervisorEngine
from services.supervisor.github_client import GitHubClientInterface, GitHubVerificationError
from services.supervisor.main import create_app
from services.supervisor.models import (
    ReadyForReGateContract,
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
) -> str:
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
    body = json.dumps({"action": "created", "issue": {"number": 1}, "comment": {"body": "hello"}}).encode("utf-8")
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
