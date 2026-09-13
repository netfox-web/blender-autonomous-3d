"""Data contracts, models, and enums for Autonomous Supervisor."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class SupervisorStatus(str, Enum):
    IDLE = "IDLE"
    VALIDATING = "VALIDATING"
    REVIEWING = "REVIEWING"
    WRITING_INSTRUCTIONS = "WRITING_INSTRUCTIONS"
    WAITING_AGENT = "WAITING_AGENT"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ReviewDecision(str, Enum):
    ACCEPT_WITH_SCOPE = "ACCEPT_WITH_SCOPE"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    BLOCKED = "BLOCKED"


class ReadyForReGateContract(BaseModel):
    repo: str
    issue: int
    instruction_sha: str
    code_sha: str
    docs_sha: str
    ci_run_id: str = ""
    code_ci_run_id: str = ""
    docs_ci_run_id: str = ""
    test_count: int
    evidence_generation_id: str
    real_blender: bool
    used_mock: bool

    @classmethod
    def parse_from_text(cls, text: str) -> Optional["ReadyForReGateContract"]:
        if "READY_FOR_RE_GATE" not in text:
            return None

        data: Dict[str, str] = {}
        for line in text.splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                data[k.strip().upper()] = v.strip()

        required_keys = [
            "REPO",
            "ISSUE",
            "INSTRUCTION_SHA",
            "CODE_SHA",
            "DOCS_SHA",
            "TEST_COUNT",
            "EVIDENCE_GENERATION_ID",
            "REAL_BLENDER",
            "USED_MOCK",
        ]
        if not all(k in data for k in required_keys):
            return None

        code_ci_run_id = data.get("CODE_CI_RUN_ID", "")
        docs_ci_run_id = data.get("DOCS_CI_RUN_ID", "")
        legacy_ci = data.get("CI_RUN_ID", "")
        if not code_ci_run_id and legacy_ci:
            code_ci_run_id = legacy_ci
        if not code_ci_run_id and not legacy_ci:
            return None

        try:
            return cls(
                repo=data["REPO"],
                issue=int(data["ISSUE"]),
                instruction_sha=data["INSTRUCTION_SHA"],
                code_sha=data["CODE_SHA"],
                docs_sha=data["DOCS_SHA"],
                ci_run_id=legacy_ci or code_ci_run_id,
                code_ci_run_id=code_ci_run_id,
                docs_ci_run_id=docs_ci_run_id,
                test_count=int(data["TEST_COUNT"]),
                evidence_generation_id=data["EVIDENCE_GENERATION_ID"],
                real_blender=data["REAL_BLENDER"].lower() in ("true", "1", "yes"),
                used_mock=data["USED_MOCK"].lower() in ("true", "1", "yes"),
            )
        except Exception:
            return None

    def to_contract_block(self) -> str:
        lines = [
            "READY_FOR_RE_GATE\n",
            f"REPO={self.repo}",
            f"ISSUE={self.issue}",
            f"INSTRUCTION_SHA={self.instruction_sha}",
            f"CODE_SHA={self.code_sha}",
            f"DOCS_SHA={self.docs_sha}",
        ]
        if self.code_ci_run_id:
            lines.append(f"CODE_CI_RUN_ID={self.code_ci_run_id}")
        if self.docs_ci_run_id:
            lines.append(f"DOCS_CI_RUN_ID={self.docs_ci_run_id}")
        if self.ci_run_id and not self.code_ci_run_id:
            lines.append(f"CI_RUN_ID={self.ci_run_id}")
        lines.extend([
            f"TEST_COUNT={self.test_count}",
            f"EVIDENCE_GENERATION_ID={self.evidence_generation_id}",
            f"REAL_BLENDER={'true' if self.real_blender else 'false'}",
            f"USED_MOCK={'true' if self.used_mock else 'false'}",
        ])
        return "\n".join(lines) + "\n"


class TruthMatrixSchema(BaseModel):
    REAL: List[str] = Field(default_factory=list)
    MOCK: List[str] = Field(default_factory=list)
    PARTIAL: List[str] = Field(default_factory=list)
    BLOCKED: List[str] = Field(default_factory=list)


class ProviderReviewResponseSchema(BaseModel):
    decision: ReviewDecision
    reviewedCodeSha: str
    reviewedDocsSha: str
    reviewedInstructionSha: str
    reviewedEvidenceGenerationId: str
    acceptedClaims: List[str] = Field(default_factory=list)
    rejectedClaims: List[str] = Field(default_factory=list)
    truthMatrix: TruthMatrixSchema = Field(default_factory=TruthMatrixSchema)
    blockers: List[str] = Field(default_factory=list)
    nextInstructionMarkdown: str = ""
    issueCommentMarkdown: str = ""


class ReviewContext(BaseModel):
    contract: ReadyForReGateContract
    commits: List[Dict[str, Any]] = Field(default_factory=list)
    diffs: str = ""
    changed_files: List[str] = Field(default_factory=list)
    progress_report_text: str = ""
    audit_text: str = ""
    acceptance_text: str = ""
    cabinet_acceptance_text: str = ""
    event_driven_acceptance_text: str = ""
    ci_summary: Dict[str, Any] = Field(default_factory=dict)
    code_ci_summary: Dict[str, Any] = Field(default_factory=dict)
    docs_ci_summary: Dict[str, Any] = Field(default_factory=dict)
    instruction_text: str = ""
    raw_issue_comment: str = ""


class SupervisorReviewOutput(BaseModel):
    decision: ReviewDecision
    reviewed_code_sha: str
    reviewed_docs_sha: str = ""
    reviewed_instruction_sha: str = ""
    reviewed_evidence_generation_id: str
    accepted_claims: List[str] = Field(default_factory=list)
    rejected_claims: List[str] = Field(default_factory=list)
    truth_matrix: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            "REAL": [],
            "MOCK": [],
            "PARTIAL": [],
            "BLOCKED": [],
        }
    )
    blockers: List[str] = Field(default_factory=list)
    next_instruction_markdown: str
    issue_comment_markdown: str
    audit_trail: Dict[str, Any] = Field(default_factory=dict)


class SupervisorState(BaseModel):
    last_seen_event_id: Optional[str] = None
    last_reviewed_code_sha: Optional[str] = None
    last_reviewed_docs_sha: Optional[str] = None
    last_processed_instruction_sha: Optional[str] = None
    active_review_id: Optional[str] = None
    status: SupervisorStatus = SupervisorStatus.IDLE
    retry_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class ReviewRecord(BaseModel):
    review_id: str
    code_sha: str
    evidence_generation_id: str
    decision: Optional[ReviewDecision] = None
    created_at: str
    completed_at: Optional[str] = None
    instruction_commit_sha: Optional[str] = None
    instruction_remote_verified_at: Optional[str] = None
    issue_comment_id: Optional[str] = None
    issue_comment_posted_at: Optional[str] = None
    review_write_stage: str = "NONE"
    output: Optional[SupervisorReviewOutput] = None
    error: Optional[str] = None
