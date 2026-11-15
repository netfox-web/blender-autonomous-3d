"""Write policy layer and guardrails for supervisor execution."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from services.supervisor.models import ReviewDecision, SupervisorReviewOutput


class PolicyViolation(Exception):
    """Raised when an action violates supervisor security policy."""
    pass


ALLOWED_OPERATIONS = frozenset(
    {
        "update_next_instruction",
        "add_issue_comment",
    }
)

_ACTION_VERBS_EN = ("run", "execute", "start", "trigger", "operate")
_ACTION_VERBS_ZH = ("啟動", "執行", "操作")
_PLC_VERBS_EN = ("connect", "execute")
_PLC_VERBS_ZH = ("連線",)
_LIVE_TARGETS = ("live cnc", "live laser")

_STANDALONE_GUARDRAILS = (
    "control machine",
    "production payment",
    "destructive prod",
    "delete secrets",
    "drop table",
)


def normalize_policy_text(text: str) -> str:
    """Lowercase, NFKC, map '-'/'_' to space, collapse whitespace."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r"[-_]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _has_token(norm: str, token: str) -> bool:
    if token.isascii():
        return re.search(rf"\b{re.escape(token)}\b", norm) is not None
    return token in norm


def _has_any_token(norm: str, tokens: tuple[str, ...]) -> bool:
    return any(_has_token(norm, token) for token in tokens)


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
        if requested_action not in ALLOWED_OPERATIONS:
            self.audit_log(
                action=requested_action,
                details={},
                allowed=False,
                reason=f"Action '{requested_action}' is not on the supervisor write whitelist.",
            )
            raise PolicyViolation(
                f"Prohibited operation: '{requested_action}' is not allowed (not whitelisted)."
            )
        self.audit_log(
            action=requested_action,
            details={},
            allowed=True,
            reason="Action permitted by supervisor write whitelist.",
        )

    def check_guardrails(self, text_to_check: str) -> Optional[str]:
        """
        Check for any forbidden live physical or destructive operations.
        Returns the matched trigger keyword or None.
        """
        norm = normalize_policy_text(text_to_check)

        for target in _LIVE_TARGETS:
            if target not in norm:
                continue
            if _has_any_token(norm, _ACTION_VERBS_EN) or _has_any_token(norm, _ACTION_VERBS_ZH):
                return target

        if _has_token(norm, "plc") and _has_any_token(norm, _PLC_VERBS_EN + _PLC_VERBS_ZH):
            return "plc"

        for phrase in _STANDALONE_GUARDRAILS:
            if phrase in norm:
                return phrase

        if re.search(r"\brm\s+rf\b", norm):
            return "rm -rf"

        return None

    @staticmethod
    def _iter_output_text_segments(output: SupervisorReviewOutput) -> list[str]:
        segments = [
            output.next_instruction_markdown,
            output.issue_comment_markdown,
            *output.blockers,
            *output.accepted_claims,
            *output.rejected_claims,
        ]
        for values in output.truth_matrix.values():
            segments.extend(values)
        return segments

    def enforce_output_policy(self, output: SupervisorReviewOutput) -> SupervisorReviewOutput:
        """
        Inspect AI output and diffs.
        If guardrails violated, downgrade decision to BLOCKED with HUMAN_APPROVAL_REQUIRED comment.
        """
        guardrail_trigger: Optional[str] = None
        for segment in self._iter_output_text_segments(output):
            guardrail_trigger = self.check_guardrails(segment)
            if guardrail_trigger:
                break
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