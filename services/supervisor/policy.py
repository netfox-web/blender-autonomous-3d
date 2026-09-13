"""Write policy layer and guardrails for supervisor execution."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from services.supervisor.models import ReviewDecision, SupervisorReviewOutput


class PolicyViolation(Exception):
    """Raised when an action violates supervisor security policy."""
    pass


FORBIDDEN_OPERATIONS = {
    "delete_branch",
    "force_push",
    "close_issue",
    "merge_pr",
    "delete_file",
    "modify_secrets",
    "modify_github_settings",
    "run_shell",
}

BLOCKED_TRIGGER_PATTERNS = [
    "run live_cnc",
    "execute live_cnc",
    "trigger live_cnc",
    "start live_cnc",
    "operate live_cnc",
    "run live_laser",
    "execute live_laser",
    "operate live_laser",
    "connect plc",
    "execute plc",
    "control machine",
    "production payment",
    "destructive prod",
    "rm -rf /",
    "drop table",
    "delete secrets",
]


class PolicyEngine:
    """Enforces write permissions, safety boundaries, and audit logging."""

    def __init__(self, audit_log_path: Path) -> None:
        self.audit_log_path = audit_log_path

    def audit_log(self, action: str, details: Dict[str, Any], allowed: bool, reason: str = "") -> None:
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "allowed": allowed,
            "reason": reason,
            "details": details,
        }
        with open(self.audit_log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def validate_action(self, requested_action: str) -> None:
        if requested_action in FORBIDDEN_OPERATIONS:
            self.audit_log(
                action=requested_action,
                details={},
                allowed=False,
                reason=f"Action '{requested_action}' is prohibited by supervisor write policy.",
            )
            raise PolicyViolation(f"Prohibited operation: '{requested_action}' is not allowed.")

    def check_guardrails(self, text_to_check: str) -> Optional[str]:
        """
        Check for any forbidden live physical or destructive operations.
        Returns the matched trigger keyword or None.
        """
        lower = text_to_check.lower()
        for kw in BLOCKED_TRIGGER_PATTERNS:
            if kw in lower:
                return kw
        return None

    def enforce_output_policy(self, output: SupervisorReviewOutput) -> SupervisorReviewOutput:
        """
        Inspect AI output and diffs.
        If guardrails violated, downgrade decision to BLOCKED with HUMAN_APPROVAL_REQUIRED comment.
        """
        # Check blockers, next instruction, and comment markdown
        content_blob = (
            output.next_instruction_markdown + "\n" +
            output.issue_comment_markdown + "\n" +
            " ".join(output.blockers)
        )
        guardrail_trigger = self.check_guardrails(content_blob)
        if guardrail_trigger:
            self.audit_log(
                action="enforce_output_policy",
                details={"trigger": guardrail_trigger},
                allowed=False,
                reason=f"Guardrail triggered by '{guardrail_trigger}'. Downgrading to BLOCKED.",
            )
            return SupervisorReviewOutput(
                decision=ReviewDecision.BLOCKED,
                reviewed_code_sha=output.reviewed_code_sha,
                reviewed_evidence_generation_id=output.reviewed_evidence_generation_id,
                accepted_claims=output.accepted_claims,
                rejected_claims=output.rejected_claims + [f"Triggered guardrail: {guardrail_trigger}"],
                truth_matrix=output.truth_matrix,
                blockers=output.blockers + [f"Guardrail violation: {guardrail_trigger}"],
                next_instruction_markdown=(
                    f"# Phase Blocked: Human Approval Required\n\n"
                    f"Action required human authorization due to trigger `{guardrail_trigger}`.\n"
                    f"Execution halted per Autonomous Supervisor Policy."
                ),
                issue_comment_markdown=(
                    f"## SUPERVISOR_REVIEW_COMPLETE\n"
                    f"DECISION=BLOCKED\n"
                    f"REVIEWED_CODE_SHA={output.reviewed_code_sha}\n\n"
                    f"HUMAN_APPROVAL_REQUIRED\n"
                    f"Reason: Guardrail `{guardrail_trigger}` requires explicit human authorization."
                ),
            )

        self.audit_log(
            action="enforce_output_policy",
            details={"decision": output.decision.value},
            allowed=True,
            reason="Output passed all policy checks.",
        )
        return output
