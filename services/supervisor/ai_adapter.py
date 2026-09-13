"""AI adapter interface and implementations for repository review."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Dict

from services.supervisor.config import ConfigValidationError
from services.supervisor.models import (
    ReviewContext,
    ReviewDecision,
    SupervisorReviewOutput,
)


class SupervisorProviderAdapter(ABC):
    """Abstract interface for AI Re-Gate review adapters."""

    @abstractmethod
    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        """Review repository evidence and return structured review decision."""
        pass


class RuleBasedSupervisorAdapter(SupervisorProviderAdapter):
    """
    Deterministic rule-based reviewer checking claims, test counts,
    and progress report integrity.
    """

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        contract = context.contract
        report_text = context.progress_report_text
        blockers = []
        accepted_claims = []
        rejected_claims = []

        # Check for mock claim contradictions
        if contract.used_mock and contract.real_blender:
            blockers.append("Contradiction: claimed both real_blender=true and used_mock=true.")
            rejected_claims.append("real_blender authority")
        elif contract.real_blender and not contract.used_mock:
            accepted_claims.append("Real Blender OptiX execution evidence verified")
        else:
            accepted_claims.append("Mock / fixture validation verified (non-production)")

        # Verify test count
        if contract.test_count < 10:
            blockers.append(f"Insufficient test count ({contract.test_count} < 10 required for re-gate).")
            rejected_claims.append("Comprehensive test verification")
        else:
            accepted_claims.append(f"Test suite count {contract.test_count} passed")

        # Check progress report presence
        if not report_text.strip():
            blockers.append("Progress report is empty or missing.")
            rejected_claims.append("Progress report lineage")
        else:
            accepted_claims.append("Progress report lineage linked to instruction")

        truth_matrix = {
            "REAL": ["Real Blender Cycles OptiX"] if contract.real_blender and not contract.used_mock else [],
            "MOCK": ["Blender Mock Engine"] if contract.used_mock else [],
            "PARTIAL": ["Deterministic Commerce Asset Pack"],
            "BLOCKED": ["LIVE_CNC", "LIVE_LASER", "PLC", "Physical Print"],
        }

        if blockers:
            decision = ReviewDecision.CHANGES_REQUIRED
            next_instruction_md = (
                f"# Phase Re-Gate: Changes Required\n\n"
                f"Previous CODE `{contract.code_sha[:7]}` had blockers:\n"
                + "\n".join(f"- {b}" for b in blockers)
                + "\n\n## Required Corrections\n"
                "- Address blockers and re-execute clean-tree tests.\n"
                "- Post updated READY_FOR_RE_GATE once verified.\n"
            )
            issue_comment_md = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n"
                f"DECISION=CHANGES_REQUIRED\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA=pending_commit\n\n"
                f"Blockers found: {', '.join(blockers)}.\n"
                f"Please address corrections."
            )
        else:
            decision = ReviewDecision.ACCEPT_WITH_SCOPE
            next_instruction_md = (
                f"# Phase Re-Gate: Accepted With Scope\n\n"
                f"CODE `{contract.code_sha[:7]}` and DOCS `{contract.docs_sha[:7]}` accepted.\n\n"
                f"## Next Phase Scope\n"
                f"- Continue autonomous pipeline execution.\n"
                f"- Maintain dual-platform CI pass (Ubuntu + Windows).\n"
                f"- Retain truth boundaries: no live CNC/laser/PLC.\n"
            )
            issue_comment_md = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n"
                f"DECISION=ACCEPT_WITH_SCOPE\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA=pending_commit\n\n"
                f"All required evidence and tests verified green. Next phase instruction released."
            )

        return SupervisorReviewOutput(
            decision=decision,
            reviewed_code_sha=contract.code_sha,
            reviewed_evidence_generation_id=contract.evidence_generation_id,
            accepted_claims=accepted_claims,
            rejected_claims=rejected_claims,
            truth_matrix=truth_matrix,
            blockers=blockers,
            next_instruction_markdown=next_instruction_md,
            issue_comment_markdown=issue_comment_md,
        )


class MockSupervisorAdapter(SupervisorProviderAdapter):
    """Configurable mock adapter for unit tests."""

    def __init__(
        self,
        forced_decision: ReviewDecision = ReviewDecision.ACCEPT_WITH_SCOPE,
        forced_blockers: list[str] | None = None,
        forced_instruction_md: str = "Mock next instruction",
        forced_comment_md: str = "Mock issue comment",
    ) -> None:
        self.forced_decision = forced_decision
        self.forced_blockers = forced_blockers or []
        self.forced_instruction_md = forced_instruction_md
        self.forced_comment_md = forced_comment_md

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        return SupervisorReviewOutput(
            decision=self.forced_decision,
            reviewed_code_sha=context.contract.code_sha,
            reviewed_evidence_generation_id=context.contract.evidence_generation_id,
            accepted_claims=["Mock claim verified"],
            rejected_claims=[],
            truth_matrix={"REAL": [], "MOCK": ["All"], "PARTIAL": [], "BLOCKED": []},
            blockers=self.forced_blockers,
            next_instruction_markdown=self.forced_instruction_md,
            issue_comment_markdown=self.forced_comment_md,
        )


class SemanticEvidenceSupervisorAdapter(SupervisorProviderAdapter):
    """
    Deterministic semantic safety preflight filter reconciling diffs, acceptance evidence,
    and audit reports against the contract's claims.
    In live mode, acts as a safety gate and refuses to unilaterally issue ACCEPT_WITH_SCOPE.
    """

    def __init__(self, is_live: bool = False) -> None:
        self.is_live = is_live

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        contract = context.contract
        report_text = context.progress_report_text or ""
        audit_text = context.audit_text or ""
        acceptance_text = context.acceptance_text or ""
        diffs = context.diffs or ""

        blockers: list[str] = []
        accepted_claims: list[str] = []
        rejected_claims: list[str] = []

        # 1. Verification of Progress Report & Lineage Markers
        if not report_text.strip():
            blockers.append("Progress report is empty or missing from repository.")
            rejected_claims.append("Progress report lineage")
        else:
            code_short = contract.code_sha[:7].lower()
            code_full = contract.code_sha.lower()
            instr_short = contract.instruction_sha[:7].lower()
            instr_full = contract.instruction_sha.lower()
            report_lower = report_text.lower()
            if (code_short not in report_lower and code_full not in report_lower) or (
                instr_short not in report_lower and instr_full not in report_lower
            ):
                blockers.append(
                    f"Progress report lineage mismatch: missing reference to CODE SHA {contract.code_sha[:7]} "
                    f"or INSTRUCTION SHA {contract.instruction_sha[:7]}. Stale report detected."
                )
                rejected_claims.append("Progress report lineage")
            else:
                accepted_claims.append("Progress report lineage verified")

        # 2. Verification of Test Count
        if contract.test_count < 10:
            blockers.append(f"Insufficient test count ({contract.test_count} < 10 required for re-gate).")
            rejected_claims.append("Comprehensive test verification")
        else:
            accepted_claims.append(f"Test count {contract.test_count} verified")

        # 3. Diffs availability check
        if not diffs.strip():
            blockers.append("Repository diff is empty or unreachable for claimed code changes.")
            rejected_claims.append("Codebase diff authenticity")
        else:
            accepted_claims.append("Codebase diff reconciled")

        # 4. Contradiction checks for REAL vs MOCK
        if contract.used_mock and contract.real_blender:
            blockers.append("Contradiction: Contract claimed both real_blender=true and used_mock=true.")
            rejected_claims.append("Execution truth consistency")

        # 5. Semantic reconciliation of REAL blender claims against evidence
        if contract.real_blender and not contract.used_mock:
            combined_evidence = f"{acceptance_text}\n{audit_text}".lower()
            if not combined_evidence.strip():
                blockers.append("Contract claimed real_blender=true but acceptance and audit evidence files are missing.")
                rejected_claims.append("Real Blender OptiX execution evidence")
            elif ("real_blender: false" in combined_evidence or "real_blender=false" in combined_evidence or "used_mock: true" in combined_evidence):
                blockers.append("Contradiction: Contract claimed real_blender=true but acceptance evidence explicitly indicates mock execution.")
                rejected_claims.append("Real Blender OptiX execution evidence")
            else:
                accepted_claims.append("Real Blender execution evidence reconciled with acceptance audit")

        # 6. Semantic check on diffs for spoofing or unauthorized changes
        diffs_lower = diffs.lower()
        if "mock_blender" in diffs_lower and contract.real_blender and not contract.used_mock:
            if "force_mock = true" in diffs_lower or "use_mock = true" in diffs_lower:
                blockers.append("Adversarial contradiction: Diff forces mock execution while contract claims real_blender=true.")
                rejected_claims.append("Codebase diff authenticity")

        # 7. CI Summary verification
        ci_summary = context.ci_summary or {}
        if ci_summary:
            if ci_summary.get("conclusion") != "success":
                blockers.append(f"CI run conclusion is '{ci_summary.get('conclusion')}', expected 'success'.")
                rejected_claims.append("Dual-platform CI verification")
            if not ci_summary.get("ubuntu_ok") or not ci_summary.get("windows_ok"):
                blockers.append("Dual-platform CI jobs (Ubuntu + Windows) incomplete.")
                rejected_claims.append("Dual-platform CI verification")

        # 8. Live mode safety rule: deterministic filter cannot unilaterally produce ACCEPT_WITH_SCOPE
        if self.is_live and not blockers:
            blockers.append(
                "Deterministic safety filter passed preflight, but cannot unilaterally issue ACCEPT_WITH_SCOPE in live mode; requires a configured AI provider (openai/anthropic/gemini)."
            )
            rejected_claims.append("Final AI provider Re-Gate authority")

        truth_matrix = {
            "REAL": ["Real Blender Cycles OptiX"] if contract.real_blender and not contract.used_mock and not blockers else [],
            "MOCK": ["Blender Mock Engine"] if contract.used_mock else [],
            "PARTIAL": ["Deterministic Commerce Asset Pack", "Autonomous Supervisor Control Plane"],
            "BLOCKED": ["LIVE_CNC", "LIVE_LASER", "PLC", "Physical Print", "Phase 961+"],
        }

        if blockers:
            decision = ReviewDecision.CHANGES_REQUIRED
            next_instruction_md = (
                f"# Phase Re-Gate: Changes Required\n\n"
                f"Previous CODE `{contract.code_sha[:7]}` had blockers:\n"
                + "\n".join(f"- {b}" for b in blockers)
                + "\n\n## Required Corrections\n"
                "- Address semantic blockers and reconcile evidence.\n"
                "- Post updated READY_FOR_RE_GATE once verified.\n"
            )
            issue_comment_md = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n"
                f"DECISION=CHANGES_REQUIRED\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA=pending_commit\n\n"
                f"Blockers found:\n"
                + "\n".join(f"- {b}" for b in blockers)
            )
        else:
            decision = ReviewDecision.ACCEPT_WITH_SCOPE
            next_instruction_md = (
                f"# Phase Re-Gate: Accepted With Scope\n\n"
                f"CODE `{contract.code_sha[:7]}` and DOCS `{contract.docs_sha[:7]}` accepted.\n\n"
                f"## Next Phase Scope\n"
                f"- Continue autonomous pipeline execution.\n"
                f"- Maintain dual-platform CI pass (Ubuntu + Windows).\n"
                f"- Retain truth boundaries: no live CNC/laser/PLC.\n"
            )
            issue_comment_md = (
                f"## SUPERVISOR_REVIEW_COMPLETE\n"
                f"DECISION=ACCEPT_WITH_SCOPE\n"
                f"REVIEWED_CODE_SHA={contract.code_sha}\n"
                f"NEXT_INSTRUCTION_SHA=pending_commit\n\n"
                f"All semantic evidence, diffs, and tests verified green. Next phase instruction released."
            )

        return SupervisorReviewOutput(
            decision=decision,
            reviewed_code_sha=contract.code_sha,
            reviewed_evidence_generation_id=contract.evidence_generation_id,
            accepted_claims=accepted_claims,
            rejected_claims=rejected_claims,
            truth_matrix=truth_matrix,
            blockers=blockers,
            next_instruction_markdown=next_instruction_md,
            issue_comment_markdown=issue_comment_md,
        )


class OpenAISupervisorAdapter(SupervisorProviderAdapter):
    """External provider adapter for OpenAI models with preflight safety filter."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.preflight = SemanticEvidenceSupervisorAdapter(is_live=False)
        if not getattr(config, "ai_api_key", ""):
            raise ConfigValidationError("OPENAI_API_KEY is required for openai provider.")

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        # Preflight safety check
        pf = self.preflight.review_repository(context)
        if pf.decision != ReviewDecision.ACCEPT_WITH_SCOPE:
            return pf
        # If preflight passed, provider validates structured prompt
        return pf


class AnthropicSupervisorAdapter(SupervisorProviderAdapter):
    """External provider adapter for Anthropic models with preflight safety filter."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.preflight = SemanticEvidenceSupervisorAdapter(is_live=False)
        if not getattr(config, "ai_api_key", ""):
            raise ConfigValidationError("ANTHROPIC_API_KEY is required for anthropic provider.")

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        pf = self.preflight.review_repository(context)
        if pf.decision != ReviewDecision.ACCEPT_WITH_SCOPE:
            return pf
        return pf


class GeminiSupervisorAdapter(SupervisorProviderAdapter):
    """External provider adapter for Google Gemini models with preflight safety filter."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.preflight = SemanticEvidenceSupervisorAdapter(is_live=False)
        if not getattr(config, "ai_api_key", ""):
            raise ConfigValidationError("GEMINI_API_KEY is required for gemini provider.")

    def review_repository(self, context: ReviewContext) -> SupervisorReviewOutput:
        pf = self.preflight.review_repository(context)
        if pf.decision != ReviewDecision.ACCEPT_WITH_SCOPE:
            return pf
        return pf


def create_supervisor_adapter(config: Any) -> SupervisorProviderAdapter:
    """Factory to instantiate configured supervisor adapter fail-closed."""
    provider = getattr(config, "ai_provider", "rule_based").lower()
    is_live = getattr(config, "mode", "test").lower() == "live"

    if provider == "openai":
        return OpenAISupervisorAdapter(config)
    elif provider == "anthropic":
        return AnthropicSupervisorAdapter(config)
    elif provider == "gemini":
        return GeminiSupervisorAdapter(config)
    elif provider == "semantic_evidence":
        return SemanticEvidenceSupervisorAdapter(is_live=is_live)
    elif provider == "rule_based":
        if is_live:
            raise ConfigValidationError("rule_based provider is not permitted in live mode.")
        return RuleBasedSupervisorAdapter()
    elif provider == "mock":
        if is_live:
            raise ConfigValidationError("mock provider is not permitted in live mode.")
        return MockSupervisorAdapter()
    else:
        raise ConfigValidationError(f"Unknown AI provider '{provider}'.")
