"""Offline unit tests for supervisor PolicyEngine guardrails and write whitelist."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from services.supervisor.engine import SupervisorEngine
from services.supervisor.models import ReadyForReGateContract, ReviewDecision, SupervisorReviewOutput
from services.supervisor.policy import (
    ALLOWED_OPERATIONS,
    PolicyEngine,
    PolicyViolation,
    normalize_policy_text,
)
from tests.test_supervisor import MockGitHubClient, MockSupervisorAdapter, valid_contract_text


BYPASS_STRINGS = [
    "run  live_cnc",
    "Run LIVE-CNC now",
    "execute the live_cnc job",
    "run live cnc",
    "啟動 LIVE_CNC",
    "connect to plc",
    "rm -rf  /",
    "DROP  TABLE x",
]

SAFE_STRINGS = [
    "live provider integration for mock tests",
    "CNC 報告文件",
    "plc_docs.md 文件更新",
    "review laser cutter documentation offline",
    "discuss production readiness in CI only",
    "table layout for acceptance matrix",
    "rm unused import in python file",
    "secrets management policy in documentation",
    "connect mock github client in unit test",
    "execute pytest locally without factory hardware",
    "operator manual for desk workflow",
]


@pytest.fixture
def policy_engine(tmp_path: Path) -> PolicyEngine:
    return PolicyEngine(tmp_path / "audit.jsonl")


@pytest.mark.parametrize("text", BYPASS_STRINGS)
def test_guardrail_bypass_strings_are_blocked(text: str, policy_engine: PolicyEngine) -> None:
    assert policy_engine.check_guardrails(text) is not None


@pytest.mark.parametrize("text", SAFE_STRINGS)
def test_guardrail_safe_strings_not_blocked(text: str, policy_engine: PolicyEngine) -> None:
    assert policy_engine.check_guardrails(text) is None


def test_normalize_policy_text_collapses_separators() -> None:
    assert normalize_policy_text("run  LIVE_CNC") == "run live cnc"
    assert normalize_policy_text("Run-LIVE_CNC") == "run live cnc"


def test_enforce_output_policy_scans_all_text_fields(policy_engine: PolicyEngine) -> None:
    output = SupervisorReviewOutput(
        decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        reviewed_code_sha="a" * 40,
        reviewed_evidence_generation_id="ev-1",
        next_instruction_markdown="harmless phase instructions",
        issue_comment_markdown="all good",
        accepted_claims=["please connect to plc on the shop floor"],
    )
    blocked = policy_engine.enforce_output_policy(output)
    assert blocked.decision == ReviewDecision.BLOCKED
    assert "HUMAN_APPROVAL_REQUIRED" in blocked.issue_comment_markdown


def test_validate_action_whitelist_rejects_unknown(policy_engine: PolicyEngine) -> None:
    with pytest.raises(PolicyViolation, match="not whitelisted"):
        policy_engine.validate_action("Delete_Branch")
    with pytest.raises(PolicyViolation, match="not whitelisted"):
        policy_engine.validate_action("push")

    log_text = policy_engine.audit_log_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in log_text.strip().splitlines()]
    denied = [r for r in records if r["action"] == "Delete_Branch" and r["allowed"] is False]
    assert denied


def test_validate_action_whitelist_allows_known(policy_engine: PolicyEngine) -> None:
    policy_engine.validate_action("update_next_instruction")
    policy_engine.validate_action("add_issue_comment")
    log_text = policy_engine.audit_log_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in log_text.strip().splitlines()]
    allowed = [r for r in records if r["allowed"] is True]
    assert len(allowed) == 2


def _minimal_engine(tmp_path: Path) -> tuple[SupervisorEngine, MockGitHubClient, PolicyEngine]:
    from services.supervisor.config import SupervisorConfig
    from services.supervisor.state import StateManager

    audit_path = tmp_path / "audit.jsonl"
    config = SupervisorConfig(
        repo_name="netfox-web/blender-autonomous-3d",
        allowed_branch="main",
        allowed_issue_number=1,
        webhook_secret="test-secret-12345",
        state_db_path=tmp_path / "supervisor.db",
        audit_log_path=audit_path,
        repo_root=tmp_path,
    )
    policy_engine = PolicyEngine(audit_path)
    github_client = MockGitHubClient()
    engine = SupervisorEngine(
        config=config,
        state_mgr=StateManager(config.state_db_path),
        github_client=github_client,
        policy_engine=policy_engine,
        ai_adapter=MockSupervisorAdapter(
            forced_decision=ReviewDecision.ACCEPT_WITH_SCOPE,
            forced_instruction_md="# Next phase\nContinue development.",
        ),
    )
    return engine, github_client, policy_engine


def test_guardrail_blocked_writes_no_instruction_file(tmp_path: Path) -> None:
    engine, gh, _ = _minimal_engine(tmp_path)
    engine.ai_adapter = MockSupervisorAdapter(
        forced_decision=ReviewDecision.ACCEPT_WITH_SCOPE,
        forced_instruction_md="Run LIVE-CNC now on the factory line",
    )
    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(evidence_id="ev_guardrail_block")
    )
    assert contract is not None
    result = engine.handle_ready_contract(contract)
    assert result["decision"] == "BLOCKED"
    assert gh.committed_instructions == []
    # validate_action should not have been invoked for instruction update on BLOCKED path
    audit_lines = engine.policy_engine.audit_log_path.read_text(encoding="utf-8").splitlines()
    update_attempts = [
        json.loads(line)
        for line in audit_lines
        if json.loads(line).get("action") == "update_next_instruction"
    ]
    assert not update_attempts


def test_accept_path_validates_before_each_github_write(tmp_path: Path) -> None:
    engine, gh, policy_engine = _minimal_engine(tmp_path)

    contract = ReadyForReGateContract.parse_from_text(
        valid_contract_text(evidence_id="ev_accept_writes")
    )
    assert contract is not None
    result = engine.handle_ready_contract(contract)
    assert result["decision"] == "ACCEPT_WITH_SCOPE"
    assert gh.committed_instructions
    assert gh.posted_comments
    audit_lines = [
        json.loads(line) for line in policy_engine.audit_log_path.read_text(encoding="utf-8").splitlines()
    ]
    allowed_writes = [
        record["action"]
        for record in audit_lines
        if record["action"] in ALLOWED_OPERATIONS and record["allowed"] is True
    ]
    assert "update_next_instruction" in allowed_writes
    assert "add_issue_comment" in allowed_writes
    assert allowed_writes.index("update_next_instruction") < allowed_writes.index("add_issue_comment")